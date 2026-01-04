"""MCP server exposing a stateful IPython kernel for Python code execution.

Supports multiple concurrent kernels via kernel_id parameter.
"""

import ast
import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from agentic_python_coder.kernel import (
    DEFAULT_KERNEL_ID,
    create_kernel,
    execute_in_kernel,
    interrupt_kernel_by_id,
    kernel_exists,
    list_kernels,
    restart_kernel,
    shutdown_kernel_by_id,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create MCP server
server = Server("ipython_mcp")

# Constants
MAX_OUTPUT = 100 * 1024  # 100KB truncation limit
MAX_TIMEOUT = 300  # Maximum allowed timeout in seconds
INTERRUPT_GRACE_PERIOD = 0.5  # Seconds to wait after kernel interrupt
KERNEL_TIMEOUT_BUFFER = 5  # Extra seconds for kernel deadline vs asyncio timeout

# Async lock for session operations (default kernel management)
_session_lock = asyncio.Lock()


def truncate_output(result: dict) -> dict:
    """Truncate stdout/stderr if too large and add success flag."""
    # Add success flag based on error field
    result["success"] = result.get("error") is None

    max_kb = MAX_OUTPUT // 1024
    for key in ["stdout", "stderr"]:
        if key in result and result[key] and len(result[key]) > MAX_OUTPUT:
            result[key] = (
                result[key][:MAX_OUTPUT] + f"\n[{key} truncated at {max_kb}KB]"
            )
    return result


def get_kernel_id(arguments: dict) -> str:
    """Get kernel_id from arguments, defaulting to DEFAULT_KERNEL_ID."""
    return arguments.get("kernel_id") or DEFAULT_KERNEL_ID


async def execute_with_timeout(
    code: str, timeout: float = 10.0, kernel_id: str = DEFAULT_KERNEL_ID
) -> dict:
    """Execute code with proper kernel-level timeout and interruption."""
    loop = asyncio.get_running_loop()

    # Auto-create default kernel with lock to prevent race conditions
    if kernel_id == DEFAULT_KERNEL_ID:
        async with _session_lock:
            if not kernel_exists(kernel_id):
                try:
                    await loop.run_in_executor(None, lambda: create_kernel(kernel_id))
                    logger.info(f"Auto-started kernel {kernel_id}")
                except Exception as e:
                    return {
                        "success": False,
                        "kernel_id": kernel_id,
                        "error": f"Failed to auto-start session: {str(e)}",
                    }
    elif not kernel_exists(kernel_id):
        # Non-default kernels should already exist (created via python_kernel_create)
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": f"Kernel {kernel_id} not found. Create it first with python_kernel_create.",
        }

    try:
        # Run blocking execute_in_kernel() in thread pool
        kernel_deadline = int(timeout) + KERNEL_TIMEOUT_BUFFER
        raw_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: execute_in_kernel(kernel_id, code, timeout=kernel_deadline),
            ),
            timeout=timeout,
        )
        # Truncate and return
        return truncate_output(raw_result)

    except asyncio.TimeoutError:
        # Interrupt kernel (interrupt_kernel_by_id already includes grace period sleep)
        try:
            await loop.run_in_executor(None, lambda: interrupt_kernel_by_id(kernel_id))
        except RuntimeError:
            # Kernel died from interrupt
            return {
                "success": False,
                "kernel_id": kernel_id,
                "error": f"Execution timed out after {timeout}s. Session crashed - call python_reset to restart.",
            }
        except Exception as e:
            logger.warning(f"Failed to interrupt kernel: {e}")
            # Check if kernel still alive after failed interrupt
            if not kernel_exists(kernel_id):
                return {
                    "success": False,
                    "kernel_id": kernel_id,
                    "error": f"Execution timed out after {timeout}s. Session crashed - call python_reset to restart.",
                }

        # Kernel still alive after interrupt
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": f"Execution timed out after {timeout}s. Code interrupted but session state preserved.",
        }

    except KeyError as e:
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": str(e),
        }

    except Exception as e:
        # Kernel crash or other error
        error_str = str(e)
        if "Invalid Signature" in error_str or "signature" in error_str.lower():
            error_msg = "Session crashed (kernel died). Call python_reset to restart."
        else:
            error_msg = f"Session crashed: {error_str}. Call python_reset to restart."
        return {"success": False, "kernel_id": kernel_id, "error": error_msg}


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
Use kernel_id to target a specific kernel (from python_kernel_create).

Output fields:
- result: final expression value (like REPL output)
- stdout: print() output
- error: error message if failed
- kernel_id: which kernel was used

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
                    "kernel_id": {
                        "type": "string",
                        "description": "Target kernel ID. Omit for default kernel.",
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
Use kernel_id to reset a specific kernel, omit for default.

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
                    },
                    "kernel_id": {
                        "type": "string",
                        "description": "Kernel to reset. Omit for default kernel.",
                    },
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

Use kernel_id to check a specific kernel, omit for default.
No side effects - safe to call anytime.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_id": {
                        "type": "string",
                        "description": "Kernel to check. Omit for default kernel.",
                    },
                },
            },
        ),
        Tool(
            name="python_interrupt",
            description="""Interrupt running code in the session.

Sends interrupt signal (like Ctrl+C) to stop long-running code.
Session state is preserved - variables defined before the interrupt remain.
Use kernel_id to target specific kernel, omit for default.

Use when:
- Code is taking too long
- You want to stop a computation early
- A loop seems stuck

Note: Call this, then call python_exec to continue working.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_id": {
                        "type": "string",
                        "description": "Kernel to interrupt. Omit for default kernel.",
                    },
                },
            },
        ),
        # New multi-kernel tools
        Tool(
            name="python_kernel_create",
            description="""Create a new isolated Python kernel.

Returns kernel_id - SAVE THIS and pass to other tools.
Use for parallel experiments or isolated execution contexts.

Example workflow:
1. python_kernel_create(packages=["numpy"]) -> {"kernel_id": "a1b2c3d4"}
2. python_exec(kernel_id="a1b2c3d4", code="import numpy as np")
3. python_kernel_shutdown(kernel_id="a1b2c3d4")""",
            inputSchema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "PyPI packages to install.",
                        "default": [],
                    },
                    "kernel_id": {
                        "type": "string",
                        "description": "Optional explicit ID (8 hex chars). Auto-generated if omitted.",
                    },
                },
            },
        ),
        Tool(
            name="python_kernel_list",
            description="""List all active kernels with IDs, packages, and status.

Use to see what kernels exist and their state.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="python_kernel_shutdown",
            description="""Shutdown a specific kernel by ID.

Frees resources. Cannot shutdown the default kernel this way (use python_reset).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "kernel_id": {
                        "type": "string",
                        "description": "Kernel ID to shutdown.",
                    },
                },
                "required": ["kernel_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    loop = asyncio.get_running_loop()

    if name == "python_reset":
        kernel_id = get_kernel_id(arguments)
        packages = arguments.get("packages", [])

        try:
            # Use restart_kernel if exists, otherwise create new
            if kernel_exists(kernel_id):
                # Pass packages directly - empty list means reset to no packages
                await loop.run_in_executor(
                    None, lambda: restart_kernel(kernel_id, packages)
                )
            else:
                await loop.run_in_executor(
                    None,
                    lambda: create_kernel(kernel_id, packages if packages else None),
                )

            if packages:
                # Try to get package versions
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
                    result = await execute_with_timeout(version_code, 30, kernel_id)
                    if result.get("result"):
                        versions = ast.literal_eval(result["result"])
                        if isinstance(versions, dict):
                            pkg_list = ", ".join(
                                f"{p} {v}" for p, v in versions.items()
                            )
                            msg = f"Session started. Packages: {pkg_list}"
                        else:
                            msg = (
                                f"Session started with packages: {', '.join(packages)}"
                            )
                    else:
                        msg = f"Session started with packages: {', '.join(packages)}"
                except Exception:
                    msg = f"Session started with packages: {', '.join(packages)}"
            else:
                msg = "Session started (no packages)"

            logger.info(msg)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": True, "kernel_id": kernel_id, "message": msg}
                    ),
                )
            ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "kernel_id": kernel_id,
                            "error": f"Failed to start session: {str(e)}",
                        }
                    ),
                )
            ]

    elif name == "python_exec":
        code = arguments.get("code", "")
        timeout = min(arguments.get("timeout", 30), MAX_TIMEOUT)
        kernel_id = get_kernel_id(arguments)

        if not code.strip():
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "kernel_id": kernel_id,
                            "stdout": "",
                            "result": None,
                        }
                    ),
                )
            ]

        result = await execute_with_timeout(code, timeout, kernel_id)
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "python_status":
        kernel_id = get_kernel_id(arguments)
        is_active = kernel_exists(kernel_id)

        status = {
            "kernel_id": kernel_id,
            "active": is_active,
            "python_version": None,
            "packages": [],
            "variables": [],
        }

        if is_active:
            # Get Python version
            try:
                result = await execute_with_timeout(
                    "import sys; sys.version", 10, kernel_id
                )
                if result.get("result"):
                    status["python_version"] = result["result"].strip("'\"")
            except Exception:
                pass

            # Get installed packages
            try:
                pkg_code = """
import importlib.metadata
[f"{d.metadata['Name']} {d.version}" for d in importlib.metadata.distributions()
 if d.metadata['Name'] not in ('pip', 'setuptools', 'wheel', 'ipykernel', 'jupyter-client')][:20]
"""
                result = await execute_with_timeout(pkg_code, 10, kernel_id)
                if result.get("result"):
                    status["packages"] = ast.literal_eval(result["result"])
            except Exception:
                pass

            # Get user-defined variables
            try:
                var_code = """
[name for name in dir() if not name.startswith('_')
 and name not in ('In', 'Out', 'get_ipython', 'exit', 'quit', 'open')]
"""
                result = await execute_with_timeout(var_code, 10, kernel_id)
                if result.get("result"):
                    status["variables"] = ast.literal_eval(result["result"])
            except Exception:
                pass

        return [TextContent(type="text", text=json.dumps(status))]

    elif name == "python_interrupt":
        kernel_id = get_kernel_id(arguments)

        if not kernel_exists(kernel_id):
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "kernel_id": kernel_id,
                            "error": "No active session to interrupt",
                        }
                    ),
                )
            ]

        try:
            # interrupt_kernel_by_id already includes grace period sleep
            await loop.run_in_executor(None, lambda: interrupt_kernel_by_id(kernel_id))

            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "kernel_id": kernel_id,
                            "message": "Interrupt sent. Session state preserved.",
                        }
                    ),
                )
            ]
        except RuntimeError:
            # Kernel died from interrupt
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "kernel_id": kernel_id,
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
                        {
                            "success": False,
                            "kernel_id": kernel_id,
                            "error": f"Failed to interrupt: {str(e)}",
                        }
                    ),
                )
            ]

    elif name == "python_kernel_create":
        packages = arguments.get("packages", [])
        explicit_id = arguments.get("kernel_id")

        try:
            kernel_id = await loop.run_in_executor(
                None,
                lambda: create_kernel(explicit_id, packages if packages else None),
            )
            kernels = await loop.run_in_executor(None, list_kernels)

            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "kernel_id": kernel_id,
                            "packages": packages,
                            "active_kernels": len(kernels),
                        }
                    ),
                )
            ]
        except ValueError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": str(e)}),
                )
            ]
        except RuntimeError as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"success": False, "error": str(e)}),
                )
            ]

    elif name == "python_kernel_list":
        kernels = await loop.run_in_executor(None, list_kernels)
        return [
            TextContent(
                type="text",
                text=json.dumps({"success": True, "kernels": kernels}),
            )
        ]

    elif name == "python_kernel_shutdown":
        kernel_id = arguments.get("kernel_id")

        if not kernel_id:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "error": "kernel_id is required"}
                    ),
                )
            ]

        if kernel_id == DEFAULT_KERNEL_ID:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "error": "Cannot shutdown default kernel. Use python_reset instead.",
                        }
                    ),
                )
            ]

        success = await loop.run_in_executor(
            None, lambda: shutdown_kernel_by_id(kernel_id)
        )

        if success:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": True,
                            "kernel_id": kernel_id,
                            "message": f"Kernel {kernel_id} shut down",
                        }
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "success": False,
                            "kernel_id": kernel_id,
                            "error": f"Kernel {kernel_id} not found",
                        }
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
