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
import threading
import time
import uuid
import warnings
from dataclasses import dataclass, field
from queue import Empty
from typing import Any, Dict, List, Optional

from jupyter_client import KernelManager

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


# Kernel registry and global lock
_kernels: Dict[str, Optional[KernelState]] = {}
_kernels_lock = threading.Lock()

# Suppress Jupyter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


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
        kernel_kwargs = {}
        if cwd:
            kernel_kwargs["cwd"] = cwd

        try:
            # Create appropriate kernel manager
            if with_packages is not None:
                logger.info(f"Starting UV kernel with packages: {with_packages}")
                self.km = UVKernelManager(
                    with_packages=with_packages, cwd=cwd, kernel_name="python3"
                )
            else:
                logger.info("Starting standard kernel (no dynamic packages)")
                self.km = KernelManager(kernel_name="python3")

            # Start the kernel
            logger.debug(f"Starting kernel in directory: {cwd}")
            self.km.start_kernel(**kernel_kwargs)
            self.kc = self.km.client()
            self.kc.start_channels()

            # Wait for kernel to be ready
            logger.debug("Waiting for kernel to be ready...")
            self.kc.wait_for_ready(
                timeout=30
            )  # Increased timeout for UV package installation
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
        startup_code = """
import sys
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
"""
        self._execute_raw(startup_code)

    def _cleanup_on_error(self):
        """Clean up resources if initialization fails."""
        try:
            if hasattr(self, "kc") and self.kc:
                self.kc.stop_channels()
            if hasattr(self, "km") and self.km:
                if self.km.is_alive():
                    self.km.shutdown_kernel(now=True)
        except Exception:
            pass  # Best effort cleanup

    def _execute_raw(self, code: str, deadline_timeout: int = 60) -> Dict[str, str]:
        """Execute code without locking (internal use only).

        Args:
            code: Python code to execute
            deadline_timeout: Hard deadline in seconds for entire execution

        Returns:
            Dict with stdout, stderr, result, and error fields
        """
        # Send the execution request (silent=False to get execute_result)
        # allow_stdin=False prevents kernel from requesting input
        msg_id = self.kc.execute(
            code, silent=False, store_history=True, allow_stdin=False
        )

        # Collect output
        output = {"stdout": "", "stderr": "", "result": None, "error": None}

        # Wait for and collect messages with hard deadline
        deadline = time.monotonic() + deadline_timeout

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
                    output["error"] = f"{content['ename']}: {content['evalue']}"
                    # Include traceback for debugging
                    if content.get("traceback"):
                        output["error"] += "\n" + "\n".join(content["traceback"])
                elif msg_type == "status" and content["execution_state"] == "idle":
                    break  # Only exit on idle status
            except Empty:
                continue  # Keep waiting, don't break

        return output

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
        """Shutdown the kernel and clean up."""
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
                except Exception:
                    pass
                self.km = None  # Clear reference
        except Exception:
            # Ignore errors during shutdown
            pass


# =============================================================================
# Core Registry Functions
# =============================================================================


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
    if not state.kernel.km.is_alive():
        with _kernels_lock:
            _kernels.pop(kernel_id, None)
        raise RuntimeError(f"Kernel {kernel_id} is dead")

    # Execute (uses per-kernel lock internally)
    result = state.kernel.execute(code, deadline_timeout=timeout)

    # Update last_used
    state.last_used = time.time()

    # Check if crashed during execution
    if not state.kernel.km.is_alive():
        with _kernels_lock:
            _kernels.pop(kernel_id, None)
        result["error"] = f"Kernel {kernel_id} crashed during execution"

    # Always include kernel_id in result
    result["kernel_id"] = kernel_id
    return result


def shutdown_kernel_by_id(kernel_id: str) -> bool:
    """Shutdown specific kernel.

    Returns:
        True if kernel existed and was shut down, False if not found.
    """
    with _kernels_lock:
        state = _kernels.pop(kernel_id, None)

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

    if state is None or not state.kernel.km.is_alive():
        return False

    state.kernel.km.interrupt_kernel()
    time.sleep(0.5)  # Grace period

    if not state.kernel.km.is_alive():
        with _kernels_lock:
            _kernels.pop(kernel_id, None)
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

    Raises:
        KeyError: If kernel not found.
        RuntimeError: If new kernel fails to start.
    """
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

    for kid in kernel_ids:
        try:
            shutdown_kernel_by_id(kid)
        except Exception:
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
