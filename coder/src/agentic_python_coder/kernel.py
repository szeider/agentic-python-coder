"""IPykernel-based Python execution for persistent sessions."""

import json
import logging
import shutil
import threading
import warnings
import atexit
from typing import Dict, Optional, List
from jupyter_client import KernelManager
from queue import Empty

# Configure logging - use environment variable or default to WARNING
import os

log_level = os.environ.get("CODER_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global kernel instance and lock
_kernel = None
_kernel_lock = threading.Lock()

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
        if cmd and cmd[0].endswith("python3"):
            cmd = ["python"] + cmd[1:]

        # Return wrapped command
        wrapped_cmd = uv_prefix + cmd

        # Log the command for debugging
        logger.debug(f"UV kernel command: {' '.join(wrapped_cmd)}")

        return wrapped_cmd


class PythonKernel:
    """Manages a single IPython kernel for persistent code execution."""

    def __init__(
        self, cwd: Optional[str] = None, with_packages: Optional[List[str]] = None
    ):
        """Initialize and start the kernel.

        Args:
            cwd: Working directory for the kernel process
            with_packages: List of packages to include using UV's --with flag

        Raises:
            RuntimeError: If kernel fails to start or UV is not available
        """
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

            # Configure IPython to always display the last value
            # and suppress pkg_resources deprecation warning from CPMpy
            startup_code = """
import sys
import warnings
from IPython.core.interactiveshell import InteractiveShell
InteractiveShell.ast_node_interactivity = 'last_expr'

# Suppress pkg_resources deprecation warning from CPMpy
warnings.filterwarnings('ignore', message='pkg_resources is deprecated', category=UserWarning)
warnings.filterwarnings('ignore', message='.*pkg_resources.*', category=DeprecationWarning)
"""
            self.execute(startup_code)

        except Exception as e:
            logger.error(f"Failed to start kernel: {e}")
            # Clean up any partially started resources
            self._cleanup_on_error()
            raise RuntimeError(f"Failed to start kernel: {e}") from e

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

    def execute(self, code: str, poll_timeout: int = 30) -> Dict[str, str]:
        """Execute code and return output.

        Args:
            code: Python code to execute
            poll_timeout: Timeout in seconds for each message poll (not total execution time)

        Returns:
            Dict with stdout, stderr, result, and error fields
        """
        # Send the execution request (silent=False to get execute_result)
        msg_id = self.kc.execute(code, silent=False, store_history=True)

        # Collect output
        output = {"stdout": "", "stderr": "", "result": None, "error": None}

        # Wait for and collect messages
        execution_state = "busy"
        while execution_state != "idle":
            try:
                msg = self.kc.get_iopub_msg(timeout=poll_timeout)
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
                elif msg_type == "status":
                    execution_state = content["execution_state"]
            except Empty:
                break

        return output

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


def get_kernel(
    cwd: Optional[str] = None, with_packages: Optional[List[str]] = None
) -> PythonKernel:
    """Get or create the global kernel instance.

    If a kernel is already running, it will be shut down and replaced if the
    requested `cwd` or `with_packages` are different.

    Args:
        cwd: Working directory for the kernel
        with_packages: List of packages to include using UV's --with flag

    Returns:
        The global kernel instance

    Raises:
        RuntimeError: If kernel fails to start
    """
    global _kernel

    requested_packages = with_packages or []

    with _kernel_lock:
        # Check if kernel is dead or if configuration has changed
        kernel_is_stale = False

        if _kernel is None:
            logger.debug("No existing kernel found")
            kernel_is_stale = True
        elif not _kernel.km.is_alive():
            logger.warning("Existing kernel is dead, will restart")
            kernel_is_stale = True
        elif _kernel.cwd != cwd:
            logger.info(
                f"Working directory changed from {_kernel.cwd} to {cwd}, restarting kernel"
            )
            kernel_is_stale = True
        elif set(_kernel.with_packages) != set(requested_packages):
            logger.info(
                f"Package list changed from {_kernel.with_packages} to {requested_packages}, restarting kernel"
            )
            kernel_is_stale = True

        if kernel_is_stale:
            if _kernel:
                logger.info("Shutting down existing kernel")
                _kernel.shutdown()  # Clean up old kernel

            logger.info(
                f"Creating new kernel with cwd={cwd}, packages={requested_packages}"
            )
            try:
                _kernel = PythonKernel(cwd, with_packages)
            except Exception as e:
                logger.error(f"Failed to create kernel: {e}")
                _kernel = None
                raise

        return _kernel


def shutdown_kernel():
    """Shutdown the global kernel if it exists."""
    global _kernel

    with _kernel_lock:
        if _kernel is not None:
            _kernel.shutdown()
            _kernel = None


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
atexit.register(shutdown_kernel)
