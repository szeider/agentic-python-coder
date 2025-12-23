"""MCP server exposing a stateful IPython kernel for Python code execution."""

import ast
import asyncio
import json
import logging
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from agentic_python_coder.kernel import get_kernel, shutdown_kernel

# Configure logging
logger = logging.getLogger(__name__)

# Create MCP server
server = Server("ipython_mcp")

# Constants
MAX_OUTPUT = 100 * 1024  # 100KB truncation limit
MAX_TIMEOUT = 300  # Maximum allowed timeout in seconds
INTERRUPT_GRACE_PERIOD = 0.5  # Seconds to wait after kernel interrupt

# Global state
_kernel: Optional[Any] = None
_session_lock = asyncio.Lock()  # Shared lock for start AND exec
_initialized = False  # Track if startup code has been injected

# Startup code injected on first exec (handles input blocking, matplotlib)
MCP_STARTUP_CODE = """
import builtins
def _blocked_input(*args, **kwargs):
    raise RuntimeError("Interactive input() not supported in MCP session")
builtins.input = _blocked_input

try:
    import matplotlib
    matplotlib.use('Agg')
except ImportError:
    pass
"""


def truncate_output(result: dict) -> dict:
    """Truncate stdout/stderr if too large and add success flag."""
    # Add success flag based on error field
    result["success"] = result.get("error") is None

    for key in ["stdout", "stderr"]:
        if key in result and result[key] and len(result[key]) > MAX_OUTPUT:
            result[key] = result[key][:MAX_OUTPUT] + f"\n[{key} truncated at 100KB]"
    return result


async def execute_with_timeout(code: str, timeout: float = 10.0) -> dict:
    """Execute code with proper kernel-level timeout and interruption."""
    global _kernel, _initialized

    async with _session_lock:  # Serialize all session operations
        # Auto-start session if needed (no packages)
        if _kernel is None:
            try:
                _kernel = get_kernel(with_packages=None)
                _initialized = False  # Need to inject startup code
                logger.info("Auto-started session (no packages)")
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to auto-start session: {str(e)}",
                }

        loop = asyncio.get_event_loop()

        # Inject startup code on first exec (input blocking, matplotlib)
        if not _initialized:
            try:
                await loop.run_in_executor(None, _kernel.execute, MCP_STARTUP_CODE)
                _initialized = True
                logger.debug("Injected MCP startup code")
            except Exception as e:
                logger.warning(f"Failed to inject startup code: {e}")

        try:
            # Run blocking kernel.execute() in thread pool
            # Pass deadline_timeout slightly longer than asyncio timeout to let asyncio handle it
            kernel_deadline = int(timeout) + 5
            raw_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _kernel.execute(code, deadline_timeout=kernel_deadline),
                ),
                timeout=timeout,
            )
            # Truncate and return
            return truncate_output(raw_result)

        except asyncio.TimeoutError:
            # Step 1: Interrupt kernel (sends SIGINT on Unix, CTRL_C on Windows)
            try:
                _kernel.km.interrupt_kernel()
                await asyncio.sleep(INTERRUPT_GRACE_PERIOD)
            except Exception as e:
                logger.warning(f"Failed to interrupt kernel: {e}")

            # Step 2: Check if kernel recovered
            try:
                if not _kernel.km.is_alive():
                    # Kernel died - invalidate session
                    shutdown_kernel()
                    _kernel = None
                    _initialized = False
                    return {
                        "success": False,
                        "error": f"Execution timed out after {timeout}s. Session crashed - call python_reset to restart.",
                    }
            except Exception:
                pass

            # Kernel still alive after interrupt - can continue
            return {
                "success": False,
                "error": f"Execution timed out after {timeout}s. Code interrupted but session state preserved - variables still available.",
            }

        except Exception as e:
            # Kernel crash or other error - invalidate session
            try:
                shutdown_kernel()
            except Exception:
                pass
            _kernel = None
            _initialized = False
            # Provide cleaner error message for common crashes
            error_str = str(e)
            if "Invalid Signature" in error_str or "signature" in error_str.lower():
                error_msg = (
                    "Session crashed (kernel died). Call python_reset to restart."
                )
            else:
                error_msg = (
                    f"Session crashed: {error_str}. Call python_reset to restart."
                )
            return {"success": False, "error": error_msg}


@server.list_tools()
async def list_tools():
    """List available MCP tools."""
    return [
        Tool(
            name="python_exec",
            description="""Execute Python code in a persistent IPython session.

Use for: calculations, data analysis, testing code, running algorithms.
State persists: variables, imports, functions remembered across calls.
Auto-starts: no setup needed, just call with code.

Output fields:
- result: final expression value (like REPL output)
- stdout: print() output
- error: error message if failed

Tips:
- First import of large packages (numpy, pandas): use timeout=60
- If session crashes, call python_reset to restart
- Session survives most timeouts (code interrupted, state preserved)
- Use python_status to check session state and defined variables""",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Can be expressions (2+2), statements (x=1), or multi-line code.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds. Default 30, max 300. Use 60 for first import of heavy packages like numpy/pandas.",
                        "default": 30,
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="python_reset",
            description="""Reset session: kill current session and start fresh with optional packages.

WARNING: This clears ALL state - variables, imports, functions are lost.
If a computation is running, it will be killed.

Only needed when:
- You need packages not in stdlib (numpy, pandas, requests, etc.)
- You want to clear all variables and start fresh
- Session crashed and needs restart

Not needed for basic Python - python_exec auto-starts a session.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "PyPI packages to install (e.g., ['numpy', 'pandas']). Uses UV for fast installation. First import may need timeout=60.",
                        "default": [],
                    }
                },
            },
        ),
        Tool(
            name="python_status",
            description="""Check session status: active state, Python version, packages, and variables.

Use to:
- See if a session is active
- Check what variables are defined
- Verify installed packages
- Get Python version info

No side effects - safe to call anytime.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="python_interrupt",
            description="""Interrupt running code in the session.

Sends interrupt signal (like Ctrl+C) to stop long-running code.
Session state is preserved - variables defined before the interrupt remain.

Use when:
- Code is taking too long
- You want to stop a computation early
- A loop seems stuck

Note: Call this, then call python_exec to continue working.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    global _kernel, _packages, _initialized

    if name == "python_reset":
        async with _session_lock:  # Lock during session setup
            packages = arguments.get("packages", [])

            # Shutdown existing kernel if any
            if _kernel is not None:
                try:
                    shutdown_kernel()
                except Exception:
                    pass
                _kernel = None
                _initialized = False

            # Start new kernel with packages
            try:
                _packages = packages
                _kernel = get_kernel(with_packages=packages if packages else None)
                _initialized = False  # Need to inject startup code

                if packages:
                    # Try to get package versions
                    loop = asyncio.get_event_loop()
                    version_code = (
                        """
import importlib.metadata
versions = {}
for pkg in %r:
    try:
        versions[pkg] = importlib.metadata.version(pkg)
    except:
        versions[pkg] = "?"
versions
"""
                        % packages
                    )
                    try:
                        result = await loop.run_in_executor(
                            None, _kernel.execute, version_code
                        )
                        if result.get("result"):
                            # Parse the versions dict from repr (safely)
                            versions = ast.literal_eval(result["result"])
                            if isinstance(versions, dict):
                                pkg_list = ", ".join(
                                    f"{p} {v}" for p, v in versions.items()
                                )
                                msg = f"Session started. Packages: {pkg_list}"
                            else:
                                msg = f"Session started with packages: {', '.join(packages)}"
                        else:
                            msg = (
                                f"Session started with packages: {', '.join(packages)}"
                            )
                    except Exception:
                        msg = f"Session started with packages: {', '.join(packages)}"
                else:
                    msg = "Session started (no packages)"

                logger.info(msg)
                return [
                    TextContent(
                        type="text", text=json.dumps({"success": True, "message": msg})
                    )
                ]
            except Exception as e:
                _kernel = None
                _initialized = False
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "error": f"Failed to start session: {str(e)}",
                            }
                        ),
                    )
                ]

    elif name == "python_exec":
        code = arguments.get("code", "")
        timeout = min(arguments.get("timeout", 30), MAX_TIMEOUT)

        if not code.strip():
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": True, "stdout": "", "result": None}),
                )
            ]

        # execute_with_timeout handles locking and session checks
        result = await execute_with_timeout(code, timeout)
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "python_status":
        async with _session_lock:
            status = {
                "active": _kernel is not None and _kernel.km.is_alive(),
                "python_version": None,
                "packages": [],
                "variables": [],
            }

            if status["active"]:
                loop = asyncio.get_event_loop()

                # Get Python version
                try:
                    result = await loop.run_in_executor(
                        None, _kernel.execute, "import sys; sys.version"
                    )
                    if result.get("result"):
                        status["python_version"] = result["result"].strip("'\"")
                except Exception:
                    pass

                # Get installed packages (from session's package list)
                if hasattr(_kernel, "with_packages") and _kernel.with_packages:
                    try:
                        pkg_code = """
import importlib.metadata
versions = {}
for pkg in %r:
    try:
        versions[pkg] = importlib.metadata.version(pkg)
    except:
        versions[pkg] = "?"
versions
""" % _kernel.with_packages
                        result = await loop.run_in_executor(
                            None, _kernel.execute, pkg_code
                        )
                        if result.get("result"):
                            versions = ast.literal_eval(result["result"])
                            status["packages"] = [
                                f"{p} {v}" for p, v in versions.items()
                            ]
                    except Exception:
                        status["packages"] = _kernel.with_packages

                # Get user-defined variables (filter out internals)
                try:
                    var_code = """
[name for name in dir() if not name.startswith('_')
 and name not in ('In', 'Out', 'get_ipython', 'exit', 'quit', 'open')]
"""
                    result = await loop.run_in_executor(
                        None, _kernel.execute, var_code
                    )
                    if result.get("result"):
                        status["variables"] = ast.literal_eval(result["result"])
                except Exception:
                    pass

            return [TextContent(type="text", text=json.dumps(status))]

    elif name == "python_interrupt":
        async with _session_lock:
            if _kernel is None:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": False, "error": "No active session to interrupt"}
                        ),
                    )
                ]

            try:
                _kernel.km.interrupt_kernel()
                await asyncio.sleep(INTERRUPT_GRACE_PERIOD)

                # Check if kernel is still alive
                if _kernel.km.is_alive():
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "success": True,
                                    "message": "Interrupt sent. Session state preserved.",
                                }
                            ),
                        )
                    ]
                else:
                    # Kernel died from interrupt
                    shutdown_kernel()
                    _kernel = None
                    _initialized = False
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "success": False,
                                    "error": "Session crashed during interrupt. Call python_reset to restart.",
                                }
                            ),
                        )
                    ]
            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"success": False, "error": f"Failed to interrupt: {str(e)}"}
                        ),
                    )
                ]

    return [
        TextContent(
            type="text",
            text=json.dumps({"success": False, "error": f"Unknown tool: {name}"}),
        )
    ]


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    """Entry point for coder-mcp command."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
