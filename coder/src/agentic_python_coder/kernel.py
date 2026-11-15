"""IPykernel-based Python execution for persistent sessions.

Supports multiple concurrent kernels with isolated state via a registry pattern.
Each kernel has its own execution lock for thread-safe concurrent execution.
"""

import atexit
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import warnings
from dataclasses import dataclass, field
from queue import Empty
from typing import Any, Dict, List, Optional

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from packaging.version import Version

log_level = os.environ.get("CODER_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Resource limits. MAX_KERNELS counts kernels other than the default one,
# slots in creation included; the default kernel is never refused.
MAX_KERNELS = int(os.environ.get("CODER_MAX_KERNELS", "10"))
DEFAULT_KERNEL_ID = "_default"

# Explicit kernel ids other than DEFAULT_KERNEL_ID
_KERNEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class _KernelLimitError(RuntimeError):
    """MAX_KERNELS reached; named holds the ids that count against it."""

    def __init__(self, message: str, named: List[str], limit: int):
        super().__init__(message)
        self.named = named
        self.limit = limit


@dataclass
class KernelState:
    """Per-kernel state tracking."""

    kernel: Any  # PythonKernel (forward reference)
    packages: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


# Seconds the kernel gets to go idle after a timeout interrupt
INTERRUPT_GRACE = 2.0
# Seconds to wait for the shell execute_reply once iopub reported idle
_REPLY_WAIT = 1.0
# iopub poll interval: a dead kernel is noticed within one poll
_POLL = 0.25
# Messages read at most in one pass without waiting (chatty running code)
_MAX_DRAIN = 1000
# Seconds a reset waits for an in-flight call to release a killed kernel
_RESET_LOCK_WAIT = 5.0

_ABORTED_ERROR = (
    "The kernel aborted this request after an earlier error;"
    " this code was not executed. Send it again."
)
_EARLIER_RUNNING_ERROR = (
    "Earlier code is still running in the kernel; this code was not executed."
)


def _dead_output() -> Dict[str, Any]:
    return {
        "stdout": "",
        "stderr": "",
        "result": None,
        "error": "Kernel died during execution",
    }


def _empty_output(error: Optional[str] = None) -> Dict[str, Any]:
    return {"stdout": "", "stderr": "", "result": None, "error": error}


@dataclass
class _Request:
    """An execute request whose completion has not been read yet."""

    msg_id: str
    idle: bool = False  # iopub reported idle for it
    reply: Optional[str] = None  # status of its shell execute_reply


# Kernel registry and global lock
_kernels: Dict[str, Optional[KernelState]] = {}
_kernels_lock = threading.Lock()


@dataclass
class _CrashRecord:
    """Restart configuration of a kernel whose process died."""

    packages: List[str]
    cwd: Optional[str]


# Kernels whose process died, by ID, so that restart_kernel() can bring them
# back with the same packages and cwd. Guarded by _kernels_lock.
_crashed: Dict[str, _CrashRecord] = {}

# IDs whose last restart replaced a kernel that was busy (read by the MCP
# reset handler). Guarded by _kernels_lock.
_replaced_busy: set = set()

# ANSI escape sequences (IPython colours its tracebacks)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Diagnosis of a uv-launched kernel that died during startup: seconds
# allowed for the rerun, bytes read from the end of its stderr, and the
# maximum length of the text appended to the error (including "...")
_UV_DIAGNOSIS_TIMEOUT = 30
_UV_DIAGNOSIS_READ = 8192
_UV_DIAGNOSIS_TAIL = 1500


# Oldest uv that knows every option of the launch command (--no-env-file)
UV_MIN_VERSION = "0.4.30"

# Problem text per uv executable path ("" = version fine or unknown)
_uv_version_checked: Dict[str, str] = {}


def _uv_version_problem(uv: str) -> str:
    """Error text if the uv at path `uv` is older than UV_MIN_VERSION, else "".

    An unreadable version gives "" (the launch then reports uv's own error).
    """
    if uv not in _uv_version_checked:
        problem = ""
        try:
            out = subprocess.run(
                [uv, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            found = Version(out.split()[1])
            if found < Version(UV_MIN_VERSION):
                problem = (
                    f"uv {UV_MIN_VERSION} or newer is required for kernels with "
                    f"packages (found uv {found} at {uv}). Update uv, e.g. with: "
                    "uv self update"
                )
        except Exception:  # OSError, timeout, unexpected output
            pass
        _uv_version_checked[uv] = problem
    return _uv_version_checked[uv]


def _kernel_env_with_packages() -> Dict[str, str]:
    """Environment for a kernel with packages: ours without PYTHONPATH.

    PYTHONPATH would put modules from outside the requested packages on the
    kernel's sys.path.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _uv_diagnosis(uv_prefix: List[str], cwd: Optional[str]) -> str:
    """uv's reason why a kernel launched with uv_prefix died, or "".

    Reruns the same uv command with `python -c pass` in place of the kernel
    module, in its own session, with stderr in a temporary file. Returns the
    cleaned tail of its stderr if it exits nonzero, and "" if it succeeds,
    cannot be run or times out (then its process group is killed). Never
    raises; writes nothing to our stdout or stderr.
    """
    try:
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(
                list(uv_prefix) + ["python", "-c", "pass"],
                cwd=cwd or None,
                env=_kernel_env_with_packages(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=_UV_DIAGNOSIS_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
                return ""
            if code == 0:
                return ""
            size = err.seek(0, os.SEEK_END)
            err.seek(max(0, size - _UV_DIAGNOSIS_READ))
            data = err.read()
    except Exception:
        return ""
    text = " ".join(_ANSI_RE.sub("", data.decode("utf-8", "replace")).split())
    if len(text) > _UV_DIAGNOSIS_TAIL:
        text = "..." + text[-(_UV_DIAGNOSIS_TAIL - 3) :]
    return text


# Suppress Jupyter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


def _native_kernel_spec_manager() -> KernelSpecManager:
    """Kernelspec manager that only knows ipykernel's built-in "python3" spec.

    With the default search path, a user or system kernelspec named
    "python3" (Anaconda, Jupyter installs) would replace the interpreter,
    environment and launch arguments. The built-in spec launches
    ``sys.executable -m ipykernel_launcher -f {connection_file}``.
    """
    return KernelSpecManager(kernel_dirs=[])


class UVKernelManager(KernelManager):
    """KernelManager that can wrap kernel launch with UV for dynamic packages."""

    def __init__(
        self,
        with_packages: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        **kwargs,
    ):
        """Initialize the UV kernel manager.

        Args:
            with_packages: List of packages to include using UV's --with flag
            cwd: Working directory for the kernel
            **kwargs: Passed to parent KernelManager

        Raises:
            RuntimeError: If UV is not available in the system PATH
        """
        super().__init__(**kwargs)
        self.with_packages = with_packages
        self.uv_cwd = cwd
        # uv part of the last launch command, for diagnosing a failed start
        self.uv_prefix: Optional[List[str]] = None

        # Check UV availability and version
        if self.with_packages:
            uv = shutil.which("uv")
            if not uv:
                raise RuntimeError(
                    "UV is required for dynamic package mode but not found in PATH. "
                    "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
                )
            problem = _uv_version_problem(uv)
            if problem:
                raise RuntimeError(problem)

    def format_kernel_cmd(self, extra_arguments=None):
        """Override to wrap kernel command with UV if packages specified."""
        # Let parent build the canonical ipykernel command
        cmd = super().format_kernel_cmd(extra_arguments)

        # If no packages specified, return unchanged
        if not self.with_packages:
            return cmd

        # Build the UV wrapper
        uv_prefix = ["uv", "run"]

        # Set working directory (critical for file operations)
        if self.uv_cwd:
            uv_prefix.extend(["--directory", self.uv_cwd])

        # Exactly the requested packages: no project, and no surrounding
        # virtual environment as base (uv would otherwise layer the packages
        # on VIRTUAL_ENV or a .venv in the cwd or a parent), and no
        # environment variables from a UV_ENV_FILE
        uv_prefix.extend(["--isolated", "--no-project", "--no-env-file"])

        # Match the host's Python; uv's default may be a newer version for
        # which packages (e.g. ortools) have no wheels yet
        uv_prefix.extend(["--python", f"{sys.version_info[0]}.{sys.version_info[1]}"])

        # Add user-specified packages
        for pkg in self.with_packages:
            uv_prefix.extend(["--with", pkg])

        # Always need ipykernel for kernel communication
        uv_prefix.extend(["--with", "ipykernel"])

        # Replace the full python path with just "python" for UV to manage
        # UV needs to control the Python environment
        if cmd:
            cmd[0] = "python"

        # Return wrapped command
        self.uv_prefix = list(uv_prefix)
        wrapped_cmd = uv_prefix + cmd

        # Log the command for debugging
        logger.debug(f"UV kernel command: {' '.join(wrapped_cmd)}")

        return wrapped_cmd


class PythonKernel:
    """Manages a single IPython kernel for persistent code execution.

    Thread-safe: uses internal lock to prevent concurrent execution corruption.
    """

    def __init__(
        self,
        cwd: Optional[str] = None,
        with_packages: Optional[List[str]] = None,
        inject_startup: bool = True,
    ):
        """Initialize and start the kernel.

        Args:
            cwd: Working directory for the kernel process
            with_packages: List of packages to include using UV's --with flag
            inject_startup: Whether to inject MCP startup code (default True)

        Raises:
            RuntimeError: If kernel fails to start or UV is not available
        """
        # Per-kernel execution lock for thread safety
        self._exec_lock = threading.Lock()
        # Request sent but not seen to complete (read and written only
        # while holding _exec_lock). New code is sent only when it is None.
        self._pending: Optional[_Request] = None

        # Store configuration for comparison
        self.cwd = cwd
        self.with_packages = with_packages or []

        # Set kernel's working directory
        # Send the kernel's fd 1 to our stderr: inherited stdout is the
        # JSON-RPC pipe under ipython_mcp, and native code (e.g. solver
        # progress output) writing to fd 1 would corrupt the protocol.
        # print() is unaffected (ipykernel routes it over iopub).
        kernel_kwargs: Dict[str, Any] = {"stdout": 2}
        if cwd:
            kernel_kwargs["cwd"] = cwd
        if with_packages:
            kernel_kwargs["env"] = _kernel_env_with_packages()

        try:
            # Create appropriate kernel manager
            if with_packages is not None:
                logger.info(f"Starting UV kernel with packages: {with_packages}")
                self.km = UVKernelManager(
                    with_packages=with_packages,
                    cwd=cwd,
                    kernel_name="python3",
                    kernel_spec_manager=_native_kernel_spec_manager(),
                )
            else:
                logger.info("Starting standard kernel (no dynamic packages)")
                self.km = KernelManager(
                    kernel_name="python3",
                    kernel_spec_manager=_native_kernel_spec_manager(),
                )

            # Start the kernel
            logger.debug(f"Starting kernel in directory: {cwd}")
            self.km.start_kernel(**kernel_kwargs)
            self.kc = self.km.client()
            self.kc.start_channels()

            # Wait for kernel to be ready
            logger.debug("Waiting for kernel to be ready...")
            # Generous timeout: a cold uv cache or a source build can take minutes
            self.kc.wait_for_ready(timeout=180)
            logger.info("Kernel started successfully")

            # Configure IPython and inject startup code
            if inject_startup:
                self._inject_startup_code()

        except Exception as e:
            logger.error(f"Failed to start kernel: {e}")
            km = getattr(self, "km", None)
            died = km is not None and not self._alive()
            uv_prefix = getattr(km, "uv_prefix", None) if died else None
            # Clean up any partially started resources
            self._cleanup_on_error()
            message = f"Failed to start kernel: {e}"
            if uv_prefix:
                reason = _uv_diagnosis(uv_prefix, cwd)
                if reason:
                    message = f"{message.rstrip('.')}. uv said: {reason}"
            raise RuntimeError(message) from e

    def _inject_startup_code(self):
        """Inject safety and configuration code: block input(), set matplotlib, etc."""
        # Runs inside a function so its imports do not leak into the user
        # namespace (code relying on them would fail when run standalone)
        startup_code = """
def __coder_startup():
    import warnings
    import builtins
    from IPython.core.interactiveshell import InteractiveShell

    # Configure IPython to display last expression value
    InteractiveShell.ast_node_interactivity = 'last_expr'

    # Suppress pkg_resources deprecation warning from CPMpy
    warnings.filterwarnings('ignore', message='pkg_resources is deprecated', category=UserWarning)
    warnings.filterwarnings('ignore', message='.*pkg_resources.*', category=DeprecationWarning)

    # Block interactive input() - not supported in MCP/automated sessions
    def _blocked_input(*args, **kwargs):
        raise RuntimeError("Interactive input() not supported")
    builtins.input = _blocked_input

    # Set matplotlib to non-interactive backend if available
    try:
        import matplotlib
        matplotlib.use('Agg')
    except ImportError:
        pass

__coder_startup()
del __coder_startup
"""
        with self._exec_lock:
            self._execute_raw(startup_code)

    def _cleanup_on_error(self):
        """Clean up resources if initialization fails.

        Routes through shutdown() so a partially-started kernel tree gets
        the same defensive process-group kill as a healthy one.
        """
        try:
            self.shutdown()
        except Exception:
            pass  # Best effort cleanup

    def _alive(self) -> bool:
        """True if the kernel process runs (False once shut down/retired)."""
        km = self.km if hasattr(self, "km") else None
        return km is not None and km.is_alive()

    def _execute_raw(
        self,
        code: str,
        deadline_timeout: int = 60,
        store_history: bool = True,
        interrupt_on_timeout: bool = True,
    ) -> Dict[str, str]:
        """Execute code without locking (internal use only).

        Args:
            code: Python code to execute
            deadline_timeout: Hard deadline in seconds for entire execution
            store_history: Record the cell in IPython history
            interrupt_on_timeout: Interrupt the kernel when the deadline hits

        Returns:
            Dict with stdout, stderr, result, and error fields
        """
        return self._execute_collect(
            code, deadline_timeout, store_history, interrupt_on_timeout
        )[0]

    def _execute_collect(
        self,
        code: str,
        deadline_timeout: int = 60,
        store_history: bool = True,
        interrupt_on_timeout: bool = True,
    ) -> tuple:
        """Like _execute_raw, but returns (output, completed).

        completed is False when the kernel died, the deadline hit before the
        request completed, or earlier code is still running (then this code
        is not sent). Caller holds _exec_lock.
        """
        return self._execute_until(
            code,
            time.monotonic() + deadline_timeout,
            deadline_timeout,
            store_history,
            interrupt_on_timeout,
        )

    def _execute_until(
        self,
        code: str,
        deadline: float,
        label: Any,
        store_history: bool = True,
        interrupt_on_timeout: bool = True,
    ) -> tuple:
        """_execute_collect with an absolute deadline; label is the timeout
        printed in the timeout error."""
        if self.kc is None or not self._alive():
            # Shut down or retired by another caller while we waited
            return _dead_output(), False
        if not self._drain_pending():
            return _empty_output(_EARLIER_RUNNING_ERROR), False
        if not self._alive():
            return _dead_output(), False

        output, outcome = self._run(code, deadline, store_history, interrupt_on_timeout)
        if outcome in ("stopped", "running", "timeout_dead"):
            # Deadline hit while the kernel was still running: report a
            # timeout instead of silently returning partial output as success
            if output["error"] is None:
                output["error"] = (
                    f"Execution timed out after {label} seconds"
                    " (partial output returned)"
                )
        return output, outcome in ("done", "aborted")

    def _handle_iopub(
        self, req: _Request, msg: Dict[str, Any], output: Optional[Dict[str, Any]]
    ) -> None:
        """Apply one iopub message of req to output (None: discard output)."""
        # Only process messages for this request
        if msg["parent_header"].get("msg_id") != req.msg_id:
            return
        msg_type = msg["header"]["msg_type"]
        content = msg["content"]
        if msg_type == "status":
            if content["execution_state"] == "idle":
                req.idle = True
            return
        if output is None:
            return
        if msg_type == "stream":
            if content["name"] == "stdout":
                output["stdout"] += content["text"]
            elif content["name"] == "stderr":
                output["stderr"] += content["text"]
        elif msg_type == "execute_result":
            output["result"] = content["data"].get("text/plain", "")
        elif msg_type == "error":
            error = f"{content['ename']}: {content['evalue']}"
            # Include traceback for debugging
            if content.get("traceback"):
                error += "\n" + "\n".join(content["traceback"])
            output["error"] = _ANSI_RE.sub("", error)

    def _read_shell(self, req: _Request, timeout: float = 0.0) -> None:
        """Read shell messages until req's execute_reply or none is ready.

        Waits up to timeout for the first message, then reads without
        waiting. Replies to other requests are discarded.
        """
        for _ in range(_MAX_DRAIN):
            if req.reply is not None:
                return
            try:
                msg = self.kc.get_shell_msg(timeout=timeout)
            except Empty:
                return
            timeout = 0.0
            if (
                msg["parent_header"].get("msg_id") == req.msg_id
                and msg["header"]["msg_type"] == "execute_reply"
            ):
                req.reply = msg["content"].get("status", "ok")

    def _collect(
        self, req: _Request, until: float, output: Optional[Dict[str, Any]]
    ) -> str:
        """Read req's messages until it completes, the kernel dies or until.

        Messages that already arrived are read even after until (bounded),
        so code that finished at the deadline counts as finished. Completion
        needs req's iopub idle and its shell execute_reply; a reply that lags
        behind idle is awaited up to _REPLY_WAIT (within until, at least
        0.1 s), then completion is assumed.

        Returns "done", "aborted" (the kernel did not execute it), "dead"
        or "deadline".
        """
        late = 0
        while True:
            self._read_shell(req)
            if req.idle:
                now = time.monotonic()
                end = now + min(_REPLY_WAIT, max(until - now, 0.1))
                while req.reply is None:
                    remaining = end - time.monotonic()
                    if remaining <= 0 or not self._alive():
                        break
                    self._read_shell(req, min(remaining, 0.1))
                return "aborted" if req.reply == "aborted" else "done"
            remaining = until - time.monotonic()
            try:
                msg = self.kc.get_iopub_msg(timeout=min(max(remaining, 0.0), _POLL))
            except Empty:
                # No idle status will ever come from a dead kernel: report
                # the crash now instead of waiting for the deadline
                if not self._alive():
                    return "dead"
                if remaining <= 0:
                    return "deadline"
                continue
            self._handle_iopub(req, msg, output)
            if remaining <= 0:
                late += 1
                if late >= _MAX_DRAIN:
                    return "deadline"

    def _drain_pending(self) -> bool:
        """Read what arrived for the pending request, without waiting.

        Returns True when nothing is pending (any more). Caller holds
        _exec_lock.
        """
        req = self._pending
        if req is None:
            return True
        if self.kc is None or not self._alive():
            self._pending = None  # a dead kernel runs nothing
            return True
        if self._collect(req, time.monotonic(), None) == "deadline":
            return False
        self._pending = None
        return True

    def _interrupt(self) -> None:
        try:
            self.km.interrupt_kernel()
        except Exception:
            pass  # Best effort

    def _run(
        self,
        code: str,
        deadline: float,
        store_history: bool = True,
        interrupt_on_timeout: bool = True,
    ) -> tuple:
        """Send code and collect its output until deadline (monotonic).

        Caller holds _exec_lock and found nothing pending. When the deadline
        hits, the kernel is interrupted and gets INTERRUPT_GRACE seconds to
        go idle. Returns (output, outcome), outcome one of "done", "aborted"
        (not executed), "dead", and after the deadline "stopped" (the code
        ended), "running" (still running, stays pending), "timeout_dead"
        (died after the interrupt) or, without interrupt, "deadline" (still
        running, stays pending). Output keeps the error collected before the
        deadline, not the interrupt's KeyboardInterrupt.
        """
        output = _empty_output()
        # silent=False to get execute_result; allow_stdin=False prevents
        # input requests; stop_on_error=False: an error does not abort
        # requests queued behind this one
        msg_id = self.kc.execute(
            code,
            silent=False,
            store_history=store_history,
            allow_stdin=False,
            stop_on_error=False,
        )
        req = self._pending = _Request(msg_id)
        outcome = self._collect(req, deadline, output)
        if outcome == "deadline" and interrupt_on_timeout:
            error = output["error"]
            self._interrupt()
            outcome = {
                "done": "stopped",
                "aborted": "aborted",  # not executed, whenever it is seen
                "dead": "timeout_dead",
                "deadline": "running",
            }[self._collect(req, time.monotonic() + INTERRUPT_GRACE, output)]
            output["error"] = error
        if outcome not in ("deadline", "running"):
            self._pending = None
        if outcome == "aborted":
            output = _empty_output(_ABORTED_ERROR)
        elif outcome == "dead":
            output["error"] = "Kernel died during execution"
        return output, outcome

    def _wait_pending(self, interrupt_at: float, deadline: float) -> bool:
        """Wait for the pending request; interrupt it once at interrupt_at.

        Returns True when nothing is pending (any more). Caller holds
        _exec_lock.
        """
        req = self._pending
        if req is None or self.kc is None or not self._alive():
            self._pending = None
            return True
        outcome = self._collect(req, interrupt_at, None)
        if outcome == "deadline":
            self._interrupt()
            until = min(time.monotonic() + INTERRUPT_GRACE, deadline)
            outcome = self._collect(req, until, None)
        if outcome == "deadline":
            return False
        self._pending = None
        return True

    def execute(self, code: str, deadline_timeout: int = 60) -> Dict[str, str]:
        """Execute code with thread-safe locking.

        Args:
            code: Python code to execute
            deadline_timeout: Hard deadline in seconds for entire execution

        Returns:
            Dict with stdout, stderr, result, and error fields

        If earlier code is still running, it is waited for within this
        call's deadline (interrupted once more at half of it); if it does
        not end, this code is not executed and an error is returned.
        """
        with self._exec_lock:
            start = time.monotonic()
            deadline = start + deadline_timeout
            if self._pending is not None and not self._wait_pending(
                start + deadline_timeout / 2, deadline
            ):
                return _empty_output(_EARLIER_RUNNING_ERROR)
            return self._execute_until(code, deadline, deadline_timeout)[0]

    def _execute_bounded(self, code: str, timeout: float) -> Dict[str, Any]:
        """Execution for the MCP server: one deadline for the whole call.

        Waiting for the lock (an earlier call in flight) counts against
        timeout; code is refused without being sent when the lock does not
        come free in time or an abandoned request is still running. The
        lock is released before returning. The result carries "_outcome":
        an outcome of _run, "refused_lock" or "refused_pending".
        """
        deadline = time.monotonic() + timeout
        if not self._exec_lock.acquire(timeout=timeout):
            return dict(_empty_output(), _outcome="refused_lock")
        try:
            if self.kc is None or not self._alive():
                return dict(_dead_output(), _outcome="dead")
            if not self._drain_pending():
                return dict(_empty_output(), _outcome="refused_pending")
            if not self._alive():
                return dict(_dead_output(), _outcome="dead")
            if time.monotonic() >= deadline:
                return dict(_empty_output(), _outcome="refused_lock")
            output, outcome = self._run(code, deadline)
            output["_outcome"] = outcome
            return output
        finally:
            self._exec_lock.release()

    def shutdown(self):
        """Shutdown the kernel and clean up.

        Kernels run in their own process group (jupyter_client launches with
        start_new_session=True). After the regular shutdown, defensively kill
        the whole group: uv-wrapped kernels are a tree (uv parent + python
        child) and a surviving member would be orphaned.
        """
        # Capture the kernel's process group before shutdown clears it
        pgid = None
        try:
            if hasattr(self, "km") and self.km:
                pgid = getattr(getattr(self.km, "provisioner", None), "pgid", None)
        except Exception:
            pass

        try:
            if hasattr(self, "kc") and self.kc:
                try:
                    self.kc.stop_channels()
                except Exception:
                    pass
                self.kc = None  # Clear reference
            if hasattr(self, "km") and self.km:
                try:
                    if self.km.is_alive():
                        self.km.shutdown_kernel(now=True)
                    else:
                        # Dead kernel: still release the control socket,
                        # zmq context and connection file
                        self.km.cleanup_resources()
                except Exception:
                    pass
                self.km = None  # Clear reference
        except Exception:
            # Ignore errors during shutdown
            pass

        # Defensive: ensure no process-tree member survived. Never signal our
        # own group (pgid could be bogus if start_new_session did not apply).
        if pgid and pgid > 0:
            try:
                if pgid != os.getpgid(0):
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass


# =============================================================================
# Core Registry Functions
# =============================================================================


def _retire_dead_kernel(kernel_id: str, state: KernelState) -> None:
    """Drop a dead kernel from the registry, keeping its config for restart.

    Releases the dead kernel's client channels and manager resources.
    Callers must not hold the kernel's exec lock.
    """
    with _kernels_lock:
        # Record only if this call removed this exact state: a delayed
        # caller must not resurrect an ID that was reset or shut down since
        if _kernels.get(kernel_id) is state:
            _kernels.pop(kernel_id)
            _crashed[kernel_id] = _CrashRecord(list(state.packages), state.cwd)
    try:
        with state.kernel._exec_lock:
            state.kernel.shutdown()
    except Exception:
        pass  # Best effort


def create_kernel(
    kernel_id: Optional[str] = None,
    with_packages: Optional[List[str]] = None,
    cwd: Optional[str] = None,
) -> str:
    """Create a new kernel and return its ID.

    Args:
        kernel_id: Optional explicit ID: DEFAULT_KERNEL_ID, or 1-64 letters,
            digits, "_", "-", "." starting with a letter or digit.
            Auto-generated (8 hex chars) if None.
        with_packages: Packages to install via UV.
        cwd: Working directory for kernel.

    Returns:
        The kernel ID.

    Raises:
        ValueError: If kernel_id already exists or invalid format.
        RuntimeError: If kernel fails to start or MAX_KERNELS exceeded (the
            default kernel does not count and is never refused).
    """
    with _kernels_lock:
        # Check resource limit (named kernels only)
        if kernel_id != DEFAULT_KERNEL_ID:
            named = [k for k in _kernels if k != DEFAULT_KERNEL_ID]
            if len(named) >= MAX_KERNELS:
                raise _KernelLimitError(
                    f"Maximum {MAX_KERNELS} kernels exceeded", named, MAX_KERNELS
                )

        # Generate or validate ID
        if kernel_id is None:
            kernel_id = uuid.uuid4().hex[:8]
            while kernel_id in _kernels:  # Handle unlikely collision
                kernel_id = uuid.uuid4().hex[:8]
        else:
            if kernel_id != DEFAULT_KERNEL_ID:
                if not _KERNEL_ID_RE.fullmatch(kernel_id):
                    raise ValueError(f"Invalid kernel_id format: {kernel_id}")
            if kernel_id in _kernels:
                raise ValueError(f"Kernel {kernel_id} already exists")

        # Reserve slot (None = being created)
        _kernels[kernel_id] = None

    # Create kernel outside lock (can be slow)
    try:
        kernel = PythonKernel(cwd=cwd, with_packages=with_packages)
        state = KernelState(
            kernel=kernel,
            packages=with_packages or [],
            cwd=cwd,
        )
        with _kernels_lock:
            _kernels[kernel_id] = state
            _crashed.pop(kernel_id, None)
        logger.info(f"Created kernel {kernel_id}")
        return kernel_id
    except Exception:
        with _kernels_lock:
            _kernels.pop(kernel_id, None)  # Release reservation
        raise


def execute_in_kernel(
    kernel_id: str,
    code: str,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Execute code in specified kernel.

    Args:
        kernel_id: Target kernel ID.
        code: Python code to execute.
        timeout: Execution timeout in seconds.

    Returns:
        Dict with stdout, stderr, result, error, kernel_id fields.

    Raises:
        KeyError: If kernel not found.
        RuntimeError: If kernel crashed during execution.
    """
    with _kernels_lock:
        if kernel_id not in _kernels:
            raise KeyError(f"Unknown kernel: {kernel_id}")
        state = _kernels[kernel_id]
        if state is None:
            raise KeyError(f"Kernel {kernel_id} is being created")

    # Execute (uses per-kernel lock internally)
    return _execute_by_id(
        kernel_id, state, lambda k: k.execute(code, deadline_timeout=timeout)
    )


def _execute_bounded_in_kernel(
    kernel_id: str, code: str, timeout: float, crash_error: Optional[str] = None
) -> Dict[str, Any]:
    """execute_in_kernel for the MCP server (see PythonKernel._execute_bounded).

    The result also carries "_outcome". crash_error replaces the error text
    used when the kernel crashed during execution.
    """
    with _kernels_lock:
        if kernel_id not in _kernels:
            raise KeyError(f"Unknown kernel: {kernel_id}")
        state = _kernels[kernel_id]
        if state is None:
            raise KeyError(f"Kernel {kernel_id} is being created")
    return _execute_by_id(
        kernel_id, state, lambda k: k._execute_bounded(code, timeout), crash_error
    )


def _execute_by_id(
    kernel_id: str, state: KernelState, run, crash_error: Optional[str] = None
) -> Dict[str, Any]:
    """Run run(kernel) on a registered kernel, retiring it if it died."""
    # Check if alive before execution
    if not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        raise RuntimeError(f"Kernel {kernel_id} is dead")

    result = run(state.kernel)

    # Update last_used
    state.last_used = time.time()

    # Check if crashed during execution (or retired by another caller)
    if not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        result["error"] = crash_error or (
            f"Kernel {kernel_id} crashed during execution."
            " Call python_reset to restart it."
        )

    # Always include kernel_id in result
    result["kernel_id"] = kernel_id
    return result


def probe_kernel(
    kernel_id: str, codes: List[str], timeout: int
) -> Optional[List[Dict[str, Any]]]:
    """Run introspection snippets in an idle kernel (for python_status).

    Never waits behind or interrupts running user code: returns None when
    the kernel is unknown, dead or busy; a dead kernel is retired. Snippets
    are not stored in the IPython history. If a snippet does not complete,
    the remaining ones are not sent and the results so far are returned.
    """
    with _kernels_lock:
        state = _kernels.get(kernel_id)
    if state is None:
        return None
    kernel = state.kernel
    if not kernel._exec_lock.acquire(blocking=False):
        return None  # busy
    results: List[Dict[str, Any]] = []
    busy = False
    try:
        if kernel._alive():
            busy = not kernel._drain_pending()  # abandoned code still runs
            for code in [] if busy else codes:
                output, completed = kernel._execute_collect(
                    code, timeout, store_history=False, interrupt_on_timeout=False
                )
                if not completed:
                    break
                results.append(output)
    finally:
        kernel._exec_lock.release()
    if not kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        return None
    return None if busy else results


def _kernel_busy(kernel_id: str) -> bool:
    """True if a call on the kernel is in flight or abandoned code runs.

    Never waits and never interrupts.
    """
    with _kernels_lock:
        state = _kernels.get(kernel_id)
    if state is None:
        return False
    kernel = state.kernel
    if not kernel._exec_lock.acquire(blocking=False):
        return True  # a call is in flight
    try:
        return not kernel._drain_pending()
    finally:
        kernel._exec_lock.release()


def _crash_record(kernel_id: str) -> Optional[_CrashRecord]:
    """The crash record of a kernel that is not registered, or None."""
    with _kernels_lock:
        if kernel_id in _kernels:
            return None
        return _crashed.get(kernel_id)


def _kernel_known(kernel_id: str) -> bool:
    """True if the id is registered (slots in creation included) or has a
    crash record."""
    with _kernels_lock:
        return kernel_id in _kernels or kernel_id in _crashed


def _retire_if_dead(kernel_id: str) -> None:
    """Retire a registered kernel whose process died (it gets a crash record).

    Slots in creation and unknown ids are left alone.
    """
    with _kernels_lock:
        state = _kernels.get(kernel_id)
    if state is not None and not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)


def shutdown_kernel_by_id(kernel_id: str) -> bool:
    """Shutdown specific kernel.

    Returns:
        True if kernel existed and was shut down, False if not found.
    """
    with _kernels_lock:
        state = _kernels.pop(kernel_id, None)
        _crashed.pop(kernel_id, None)  # an explicit shutdown forgets a crash

    if state is None:
        return False

    # Acquire exec lock to ensure no execution in progress
    with state.kernel._exec_lock:
        state.kernel.shutdown()
    logger.info(f"Shut down kernel {kernel_id}")
    return True


def interrupt_kernel_by_id(kernel_id: str) -> bool:
    """Send interrupt signal to specific kernel.

    Returns:
        True if interrupt sent, False if kernel not found.

    Raises:
        RuntimeError: If kernel died from interrupt.
    """
    with _kernels_lock:
        if kernel_id not in _kernels:
            return False
        state = _kernels[kernel_id]

    km = state.kernel.km if state is not None else None
    if km is None or not km.is_alive():
        return False

    km.interrupt_kernel()
    time.sleep(0.5)  # Grace period

    if not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        raise RuntimeError(f"Kernel {kernel_id} died from interrupt")

    return True


def restart_kernel(
    kernel_id: str,
    with_packages: Optional[List[str]] = None,
) -> None:
    """Restart kernel with new config, preserving the ID.

    Args:
        kernel_id: Kernel to restart.
        with_packages: New packages (None = keep existing).

    A kernel that died (and was dropped from the registry) is restarted
    with the packages and cwd it had. If the new kernel fails to start, the
    ID is left with a crash record holding the old packages and cwd, so a
    later restart_kernel(kernel_id) can bring it back.

    Raises:
        KeyError: If kernel not found.
        RuntimeError: If new kernel fails to start.
    """
    # Choose the live or the crashed path and reserve the slot in one
    # critical section: a concurrent retirement cannot slip in between
    with _kernels_lock:
        _replaced_busy.discard(kernel_id)
        crashed = None
        if kernel_id in _kernels:
            state = _kernels[kernel_id]
            if state is None:
                raise KeyError(f"Kernel {kernel_id} is being created")
            # Mark as restarting
            _kernels[kernel_id] = None
        else:
            crashed = _crashed.get(kernel_id)
            if crashed is None:
                raise KeyError(f"Unknown kernel: {kernel_id}")
    if crashed is not None:
        packages = with_packages if with_packages is not None else crashed.packages
        create_kernel(kernel_id, packages, crashed.cwd)
        logger.info(f"Restarted crashed kernel {kernel_id}")
        return

    old_packages = state.packages
    old_cwd = state.cwd
    packages = with_packages if with_packages is not None else old_packages
    try:
        # Shutdown old kernel (a busy one is killed without waiting for its
        # code), then create the new kernel with the same ID
        if _shutdown_replaced(kernel_id, state.kernel):
            with _kernels_lock:
                _replaced_busy.add(kernel_id)
        kernel = PythonKernel(cwd=old_cwd, with_packages=packages)
        with _kernels_lock:
            _kernels[kernel_id] = KernelState(
                kernel=kernel,
                packages=packages,
                cwd=old_cwd,
            )
        logger.info(f"Restarted kernel {kernel_id}")
    except Exception:
        # Remove from registry on failure, keeping the old configuration;
        # the old process must not survive a failed shutdown
        _kill_process_group(state.kernel)
        with _kernels_lock:
            _kernels.pop(kernel_id, None)
            _crashed[kernel_id] = _CrashRecord(list(old_packages), old_cwd)
        raise


def _shutdown_replaced(kernel_id: str, kernel: "PythonKernel") -> bool:
    """Shut down a kernel that a restart replaces; True if it was busy.

    An idle kernel is shut down under its lock as before. A busy one (call
    in flight or abandoned code running) has its process group killed
    first: an in-flight collector then sees the dead kernel within one poll
    and releases the lock. If the lock does not come free in time, the
    sockets another thread may be reading are left open and the object is
    dropped.
    """
    if kernel._exec_lock.acquire(blocking=False):
        try:
            busy = not kernel._drain_pending()
            if busy:
                _kill_process_group(kernel)
            kernel.shutdown()
            return busy
        finally:
            kernel._exec_lock.release()
    _kill_process_group(kernel)
    if kernel._exec_lock.acquire(timeout=_RESET_LOCK_WAIT):
        try:
            kernel.shutdown()
        finally:
            kernel._exec_lock.release()
    else:
        logger.warning(
            f"Kernel {kernel_id}: killed, but its lock stayed held;"
            " dropping the old kernel without closing its channels"
        )
    return True


def _pop_replaced_busy(kernel_id: str) -> bool:
    """True if the last restart of kernel_id replaced a busy kernel."""
    with _kernels_lock:
        if kernel_id in _replaced_busy:
            _replaced_busy.discard(kernel_id)
            return True
        return False


def _kill_process_group(kernel: "PythonKernel") -> None:
    """SIGKILL the kernel's process group; never our own group."""
    try:
        own_pgid = os.getpgid(0)
    except OSError:
        own_pgid = None
    try:
        km = kernel.km
        pgid = getattr(getattr(km, "provisioner", None), "pgid", None)
        if pgid and pgid > 0 and pgid != own_pgid:
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        pass  # Best effort


# =============================================================================
# Query Functions
# =============================================================================


def list_kernels() -> List[Dict[str, Any]]:
    """List all active kernels.

    Returns:
        List of {id, packages, cwd, alive, created_at, last_used} dicts.
    """
    with _kernels_lock:
        result = []
        for kid, state in _kernels.items():
            if state is not None:
                result.append(
                    {
                        "id": kid,
                        "packages": state.packages,
                        "cwd": state.cwd,
                        "alive": state.kernel.km.is_alive(),
                        "created_at": state.created_at,
                        "last_used": state.last_used,
                    }
                )
        return result


def kernel_exists(kernel_id: str) -> bool:
    """Check if kernel exists (without raising)."""
    with _kernels_lock:
        return kernel_id in _kernels and _kernels[kernel_id] is not None


def get_kernel_info(kernel_id: str) -> Dict[str, Any]:
    """Get info for a specific kernel.

    Raises:
        KeyError: If kernel not found.
    """
    with _kernels_lock:
        if kernel_id not in _kernels or _kernels[kernel_id] is None:
            raise KeyError(f"Unknown kernel: {kernel_id}")
        state = _kernels[kernel_id]
        return {
            "id": kernel_id,
            "packages": state.packages,
            "cwd": state.cwd,
            "alive": state.kernel.km.is_alive(),
            "created_at": state.created_at,
            "last_used": state.last_used,
        }


def shutdown_all_kernels():
    """Shutdown all kernels. Called by atexit."""
    with _kernels_lock:
        kernel_ids = list(_kernels.keys())
        _crashed.clear()

    for kid in kernel_ids:
        try:
            shutdown_kernel_by_id(kid)
        except Exception:
            pass  # Best effort


def kill_all_kernel_process_groups():
    """Hard-kill (SIGKILL) every registered kernel's process group.

    Deliberately lock-free: this is the termination path, where a busy
    kernel's _exec_lock may be held indefinitely by an in-flight execution
    and the graceful shutdown_all_kernels() would block behind it. Snapshot
    the registry and signal each group directly. Never signals our own
    process group. Kernels mid-creation (registry slot still None) cannot
    be reached here — that sub-second window is a known limitation.
    """
    for state in list(_kernels.values()):
        if state is not None:
            _kill_process_group(state.kernel)


# =============================================================================
# Backward Compatibility API
# =============================================================================


def get_kernel(
    cwd: Optional[str] = None, with_packages: Optional[List[str]] = None
) -> PythonKernel:
    """Legacy API: get or create the default kernel.

    Note: Does NOT auto-restart on config change. Call shutdown_kernel()
    first if you need different packages/cwd.
    """
    if not kernel_exists(DEFAULT_KERNEL_ID):
        create_kernel(DEFAULT_KERNEL_ID, with_packages, cwd)

    with _kernels_lock:
        return _kernels[DEFAULT_KERNEL_ID].kernel


def shutdown_kernel():
    """Legacy API: shutdown the default kernel."""
    shutdown_kernel_by_id(DEFAULT_KERNEL_ID)


def format_output(output: Dict[str, str]) -> str:
    """Format kernel output for display as JSON."""
    # Clean up the output
    result = {
        "success": output.get("error") is None,
        "stdout": output.get("stdout", "").rstrip() if output.get("stdout") else None,
        "result": output.get("result")
        if output.get("result") and output["result"] != "None"
        else None,
        "stderr": output.get("stderr", "").rstrip() if output.get("stderr") else None,
        "error": output.get("error") if output.get("error") else None,
    }

    # Remove None values for cleaner output
    result = {k: v for k, v in result.items() if v is not None}

    return json.dumps(result, indent=2)


# Register cleanup on exit
atexit.register(shutdown_all_kernels)
