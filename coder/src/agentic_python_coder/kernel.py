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
import sys
import threading
import time
import uuid
import warnings
from dataclasses import dataclass, field
from queue import Empty
from typing import Any, Dict, List, Optional

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

log_level = os.environ.get("CODER_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Resource limits
MAX_KERNELS = int(os.environ.get("CODER_MAX_KERNELS", "10"))
DEFAULT_KERNEL_ID = "_default"


@dataclass
class KernelState:
    """Per-kernel state tracking."""

    kernel: Any  # PythonKernel (forward reference)
    packages: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


def _dead_output() -> Dict[str, Any]:
    return {
        "stdout": "",
        "stderr": "",
        "result": None,
        "error": "Kernel died during execution",
    }


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

# ANSI escape sequences (IPython colours its tracebacks)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

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

        # Check UV availability
        if self.with_packages and not shutil.which("uv"):
            raise RuntimeError(
                "UV is required for dynamic package mode but not found in PATH. "
                "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
            )

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

        # Don't load project dependencies (create clean environment)
        uv_prefix.append("--no-project")

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

        # Store configuration for comparison
        self.cwd = cwd
        self.with_packages = with_packages or []

        # Set kernel's working directory
        # Send the kernel's fd 1 to our stderr: inherited stdout is the
        # JSON-RPC pipe under ipython_mcp, and native code (e.g. solver
        # progress output) writing to fd 1 would corrupt the protocol.
        # print() is unaffected (ipykernel routes it over iopub).
        kernel_kwargs = {"stdout": 2}
        if cwd:
            kernel_kwargs["cwd"] = cwd

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
            # Clean up any partially started resources
            self._cleanup_on_error()
            raise RuntimeError(f"Failed to start kernel: {e}") from e

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

        completed is False when the kernel died or the deadline hit before
        the kernel reported idle.
        """
        if self.kc is None or not self._alive():
            # Shut down or retired by another caller while we waited
            return _dead_output(), False

        # Send the execution request (silent=False to get execute_result)
        # allow_stdin=False prevents kernel from requesting input
        msg_id = self.kc.execute(
            code, silent=False, store_history=store_history, allow_stdin=False
        )

        # Collect output
        output = {"stdout": "", "stderr": "", "result": None, "error": None}

        # Wait for and collect messages with hard deadline
        deadline = time.monotonic() + deadline_timeout
        completed = False

        while time.monotonic() < deadline:
            try:
                msg = self.kc.get_iopub_msg(timeout=1.0)
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                # Only process messages for our execution
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue

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
                elif msg_type == "status" and content["execution_state"] == "idle":
                    completed = True
                    break  # Only exit on idle status
            except Empty:
                # No idle status will ever come from a dead kernel: report
                # the crash now instead of waiting for the deadline
                if not self._alive():
                    output["error"] = "Kernel died during execution"
                    return output, False
                continue  # Keep waiting, don't break

        if not completed and interrupt_on_timeout:
            # Deadline hit while the kernel was still running: report a
            # timeout instead of silently returning partial output as success,
            # and interrupt so the kernel doesn't block the next execution
            if output["error"] is None:
                output["error"] = (
                    f"Execution timed out after {deadline_timeout} seconds"
                    " (partial output returned)"
                )
            try:
                self.km.interrupt_kernel()
                time.sleep(0.5)  # grace period so the next execute isn't aborted
            except Exception:
                pass  # Best effort

        return output, completed

    def execute(self, code: str, deadline_timeout: int = 60) -> Dict[str, str]:
        """Execute code with thread-safe locking.

        Args:
            code: Python code to execute
            deadline_timeout: Hard deadline in seconds for entire execution

        Returns:
            Dict with stdout, stderr, result, and error fields
        """
        with self._exec_lock:
            return self._execute_raw(code, deadline_timeout)

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
        kernel_id: Optional explicit ID (8 hex chars). Auto-generated if None.
        with_packages: Packages to install via UV.
        cwd: Working directory for kernel.

    Returns:
        The kernel ID.

    Raises:
        ValueError: If kernel_id already exists or invalid format.
        RuntimeError: If kernel fails to start or MAX_KERNELS exceeded.
    """
    with _kernels_lock:
        # Check resource limit
        if len(_kernels) >= MAX_KERNELS:
            raise RuntimeError(f"Maximum {MAX_KERNELS} kernels exceeded")

        # Generate or validate ID
        if kernel_id is None:
            kernel_id = uuid.uuid4().hex[:8]
            while kernel_id in _kernels:  # Handle unlikely collision
                kernel_id = uuid.uuid4().hex[:8]
        else:
            # Allow DEFAULT_KERNEL_ID or 8-char hex
            if kernel_id != DEFAULT_KERNEL_ID:
                if not re.match(r"^[0-9a-f]{8}$", kernel_id):
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

    # Check if alive before execution
    if not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        raise RuntimeError(f"Kernel {kernel_id} is dead")

    # Execute (uses per-kernel lock internally)
    result = state.kernel.execute(code, deadline_timeout=timeout)

    # Update last_used
    state.last_used = time.time()

    # Check if crashed during execution (or retired by another caller)
    if not state.kernel._alive():
        _retire_dead_kernel(kernel_id, state)
        result["error"] = (
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
    try:
        if kernel._alive():
            for code in codes:
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
    return results


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
    with the packages and cwd it had.

    Raises:
        KeyError: If kernel not found.
        RuntimeError: If new kernel fails to start.
    """
    with _kernels_lock:
        crashed = None if kernel_id in _kernels else _crashed.get(kernel_id)
    if crashed is not None:
        packages = with_packages if with_packages is not None else crashed.packages
        create_kernel(kernel_id, packages, crashed.cwd)
        logger.info(f"Restarted crashed kernel {kernel_id}")
        return

    with _kernels_lock:
        if kernel_id not in _kernels:
            raise KeyError(f"Unknown kernel: {kernel_id}")
        state = _kernels[kernel_id]
        if state is None:
            raise KeyError(f"Kernel {kernel_id} is being created")
        old_packages = state.packages
        old_cwd = state.cwd
        # Mark as restarting
        _kernels[kernel_id] = None

    # Shutdown old kernel
    with state.kernel._exec_lock:
        state.kernel.shutdown()

    # Create new kernel with same ID
    packages = with_packages if with_packages is not None else old_packages
    try:
        kernel = PythonKernel(cwd=old_cwd, with_packages=packages)
        with _kernels_lock:
            _kernels[kernel_id] = KernelState(
                kernel=kernel,
                packages=packages,
                cwd=old_cwd,
            )
        logger.info(f"Restarted kernel {kernel_id}")
    except Exception:
        # Remove from registry on failure
        with _kernels_lock:
            _kernels.pop(kernel_id, None)
        raise


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
    try:
        own_pgid = os.getpgid(0)
    except OSError:
        own_pgid = None

    for state in list(_kernels.values()):
        if state is None:
            continue
        try:
            km = state.kernel.km
            pgid = getattr(getattr(km, "provisioner", None), "pgid", None)
            if pgid and pgid > 0 and pgid != own_pgid:
                os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError, AttributeError):
            pass  # Best effort


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
