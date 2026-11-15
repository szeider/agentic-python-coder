"""MCP server exposing a stateful IPython kernel for Python code execution.

Supports multiple concurrent kernels via kernel_id parameter.
"""

import ast
import asyncio
import json
import logging
import os
import re
import signal
import threading
from typing import List, Optional

import jsonschema
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from packaging.requirements import InvalidRequirement, Requirement

from agentic_python_coder.kernel import (
    DEFAULT_KERNEL_ID,
    INTERRUPT_GRACE,
    _execute_bounded_in_kernel,
    _kernel_busy,
    _pop_replaced_busy,
    create_kernel,
    get_kernel_info,
    interrupt_kernel_by_id,
    kernel_exists,
    kill_all_kernel_process_groups,
    list_kernels,
    probe_kernel,
    restart_kernel,
    shutdown_all_kernels,
)

# Configure logging
logger = logging.getLogger(__name__)

# The MCP server object is created at the end of the module (see _make_server).

# Constants
MAX_OUTPUT = 100 * 1024  # 100KB truncation limit
MAX_TIMEOUT = 300  # Maximum allowed timeout in seconds
DEFAULT_TIMEOUT = 30  # Default timeout in seconds
STATUS_PROBE_TIMEOUT = 10  # Timeout for python_status introspection probes
# The kernel worker owns the execution timeout; this outer backstop only
# guards against a worker that never returns
BACKSTOP_SLACK = 10

# Async lock for session operations (default kernel management)
_session_lock = asyncio.Lock()


def truncate_output(result: dict) -> dict:
    """Truncate oversized text fields and add success flag."""
    # Add success flag based on error field
    result["success"] = result.get("error") is None

    max_kb = MAX_OUTPUT // 1024
    for key in ["stdout", "stderr", "result", "error"]:
        value = result.get(key)
        if isinstance(value, str) and len(value) > MAX_OUTPUT:
            result[key] = value[:MAX_OUTPUT] + f"\n[{key} truncated at {max_kb}KB]"
    return result


def _status_probe(expr: str) -> str:
    """Code that writes repr(expr) to stdout.

    Writing (instead of a last-expression value) keeps the probe out of the
    user's ``_``/``Out``, ``__import__`` keeps it from binding names, and
    sys.stdout.write survives a user-shadowed print, the builtins module's
    repr a user-shadowed repr.
    """
    return (
        "if True:\n    __import__('sys').stdout.write("
        f"__import__('builtins').repr({expr}) + '\\n')\n"
    )


def _distribution_name(requirement: str) -> Optional[str]:
    """Distribution name of a requirement string ("pkg>=1", "pkg[extra]").

    None when the string is not a PEP 508 requirement, e.g. a local path or
    a VCS URL, whose distribution name is unknown before installation.
    """
    try:
        return Requirement(requirement).name
    except InvalidRequirement:
        return None


def _package_versions_probe(packages: List[str]) -> str:
    """Probe code writing {requirement: version or "?"} to stdout."""
    pairs = [(p, _distribution_name(p)) for p in packages]
    return _status_probe(
        "{req: '?' if name is None else getattr(next(iter("
        "__import__('importlib.metadata').metadata.distributions(name=name)),"
        " None), 'version', '?')"
        f" for req, name in {pairs!r}}}"
    )


# python_status lists at most this many packages, and hides these tools
# unless they were requested
STATUS_MAX_PACKAGES = 20
_STATUS_HIDDEN = ("pip", "setuptools", "wheel", "ipykernel", "jupyter-client")


def _normalized_name(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _status_packages_probe(requested: List[str]) -> str:
    """Probe code writing (packages, total) to stdout.

    packages: "name version" strings, first the requested distributions in
    the order given, then the others sorted case-insensitively by name, cut
    at STATUS_MAX_PACKAGES. total: length of that list before the cut.
    """
    req = list(
        dict.fromkeys(
            _normalized_name(n)
            for n in (_distribution_name(p) for p in requested)
            if n is not None
        )
    )
    # Builtins are taken from the builtins module, so that user variables
    # named sorted, len or reversed do not break the probe. Reversed: the
    # first distribution on sys.path wins, as for importlib.metadata.version
    return _status_probe(
        "(lambda B, req, hidden, m: ("
        "([f'{m[k][0]} {m[k][1]}' for k in req if k in m]"
        " + [f'{n} {v}' for k, (n, v) in"
        " B.sorted(m.items(), key=lambda i: i[1][0].lower())"
        " if k not in req and k not in hidden])"
        f"[:{STATUS_MAX_PACKAGES}],"
        " B.len([k for k in m if k in req or k not in hidden])))("
        f"__import__('builtins'), {req!r}, {_STATUS_HIDDEN!r}, "
        "{__import__('re').sub('[-_.]+', '-', n).lower(): (n, d.version)"
        " for d, n in __import__('builtins').reversed([(d, d.metadata.get('Name'))"
        " for d in __import__('importlib.metadata').metadata.distributions()])"
        " if n})"
    )


def get_kernel_id(arguments: dict) -> str:
    """Get kernel_id from arguments, defaulting to DEFAULT_KERNEL_ID."""
    return arguments.get("kernel_id") or DEFAULT_KERNEL_ID


def _exec_reply(raw: dict, timeout: float, kernel_id: str) -> dict:
    """MCP reply for a result of _execute_bounded_in_kernel."""
    outcome = raw.pop("_outcome", "done")
    limit = f"{timeout}s"
    if outcome in ("refused_pending", "refused_lock"):
        if outcome == "refused_pending":
            error = (
                "Kernel busy with earlier code; this code was not executed."
                " python_status shows when it is idle; python_interrupt tries"
                " to stop the earlier code;"
                f' python_reset(kernel_id="{kernel_id}") replaces the kernel.'
            )
        else:
            error = (
                f"Kernel was busy with an earlier call for the whole {limit}"
                " of this call; this code was not executed."
            )
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": error,
            "executed": False,
            "kernel_busy": True,
            "timed_out": False,
        }
    if outcome == "aborted":
        return {
            "success": False,
            "kernel_id": kernel_id,
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": raw["error"],
            "executed": False,
            "kernel_busy": False,
            "timed_out": False,
        }
    if outcome in ("stopped", "running", "timeout_dead"):
        if outcome == "timeout_dead" or not kernel_exists(kernel_id):
            return {
                "success": False,
                "kernel_id": kernel_id,
                "error": f"Execution timed out after {limit}. Session crashed"
                " - call python_reset to restart.",
            }
        if outcome == "stopped":
            error = (
                f"Execution timed out after {limit}."
                " Code interrupted but session state preserved."
            )
        else:
            error = (
                f"Execution timed out after {limit}. The code is still"
                " running; the interrupt did not stop it. The kernel takes no"
                " new code until it ends. python_interrupt tries again;"
                f' python_reset(kernel_id="{kernel_id}") replaces the kernel'
                " and discards its state."
            )
        return truncate_output(
            {
                "success": False,
                "kernel_id": kernel_id,
                "error": error,
                "timed_out": True,
                "kernel_busy": outcome == "running",
                "stdout": raw.get("stdout", ""),
                "stderr": raw.get("stderr", ""),
                "result": raw.get("result"),
            }
        )
    return truncate_output(raw)


async def execute_with_timeout(
    code: str, timeout: float = DEFAULT_TIMEOUT, kernel_id: str = DEFAULT_KERNEL_ID
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
        # Non-default kernels should already exist (created via python_reset)
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": f"Kernel {kernel_id} not found. Create it first with python_reset().",
        }

    try:
        # The worker waits `timeout` (lock wait included), interrupts, waits
        # INTERRUPT_GRACE for the kernel to go idle and decides the outcome
        raw_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _execute_bounded_in_kernel(kernel_id, code, timeout),
            ),
            timeout=timeout + INTERRUPT_GRACE + BACKSTOP_SLACK,
        )
        return _exec_reply(raw_result, timeout, kernel_id)

    except asyncio.TimeoutError:
        # The worker did not return: its execution state is unknown
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": "No answer from the kernel worker; the state of this"
            " execution is unknown. python_status shows whether the kernel is"
            f' busy; python_reset(kernel_id="{kernel_id}") replaces the kernel.',
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
                        "description": "Target kernel ID (from python_reset). Omit for default kernel.",
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="python_reset",
            description="""Create a new kernel OR reset an existing one.

Two modes:
- WITHOUT kernel_id: Creates NEW isolated kernel, returns kernel_id
- WITH kernel_id: Resets that kernel (clears state, optionally installs packages)

For parallel agents: each agent calls python_reset() once to get its own kernel_id,
then uses that ID for all python_exec calls.

Note: Kernel IDs are auto-generated 8-char hex strings (e.g., "a94a7c7a").
You cannot specify custom IDs - the system assigns them.

Example workflow:
1. python_reset(packages=["numpy"]) -> {"kernel_id": "a94a7c7a"}
2. python_exec(kernel_id="a94a7c7a", code="import numpy as np")
3. python_exec(kernel_id="a94a7c7a", code="np.random.rand(3)")""",
            inputSchema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "PyPI packages to install (e.g., ['numpy', 'pandas']). Uses UV for fast installation.",
                        "default": [],
                    },
                    "kernel_id": {
                        "type": "string",
                        "description": "If provided: reset this kernel. If omitted: create NEW kernel.",
                    },
                },
            },
        ),
        Tool(
            name="python_status",
            description="""Check session status: active state, Python version, packages, and variables.

Use to:
- See if a session is active
- List all active kernel IDs (all_kernels field)
- Check what variables are defined
- Verify installed packages
- Get Python version info

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
            name="submit_code",
            description="""Submit your final, verified, self-contained Python program.

Call this ONCE at the end of a solve, only after you have executed the program
via python_exec and your verification passed. The submission must be a
standalone program: all imports included, no reliance on session state.

The code is syntax-checked with compile():
- {"ok": true} if it parses
- {"ok": false, "error": "<detail>"} on a syntax error — fix and resubmit

The code is NOT executed and NOT written to disk; the client persists it.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete standalone Python program (final answer).",
                    },
                },
                "required": ["code"],
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
                "properties": {
                    "kernel_id": {
                        "type": "string",
                        "description": "Kernel to interrupt. Omit for default kernel.",
                    },
                },
            },
        ),
    ]


async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    loop = asyncio.get_running_loop()

    if name == "python_reset":
        kernel_id = arguments.get("kernel_id")  # None means create new kernel
        packages = arguments.get("packages", [])
        replaced_busy = False

        try:
            if kernel_id is None:
                # No kernel_id provided: CREATE NEW kernel
                kernel_id = await loop.run_in_executor(
                    None,
                    lambda: create_kernel(None, packages if packages else None),
                )
            else:
                # kernel_id provided: RESET it (also brings back a kernel
                # that crashed, with its packages and cwd)
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: restart_kernel(
                            kernel_id, packages if packages else None
                        ),
                    )
                    replaced_busy = _pop_replaced_busy(kernel_id)
                except KeyError:
                    # kernel_id provided but doesn't exist: error
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {
                                    "success": False,
                                    "error": f"Kernel {kernel_id} not found. Omit kernel_id to create a new kernel.",
                                }
                            ),
                        )
                    ]
                # Without packages the kernel keeps the ones it had: report
                # what it actually runs with
                if not packages:
                    try:
                        packages = list(get_kernel_info(kernel_id)["packages"] or [])
                    except KeyError:
                        pass

            if packages:
                msg = f"Session started with packages: {', '.join(packages)}"
                # Same probe discipline as python_status: no names bound, no
                # history entry, _ untouched
                try:
                    probe = _package_versions_probe(packages)
                    results = await loop.run_in_executor(
                        None,
                        lambda: probe_kernel(kernel_id, [probe], DEFAULT_TIMEOUT),
                    )
                    result = results[0] if results else None
                    if result and result.get("error") is None and result.get("stdout"):
                        versions = ast.literal_eval(result["stdout"].strip())
                        if isinstance(versions, dict):
                            pkg_list = ", ".join(
                                f"{p} {v}" for p, v in versions.items()
                            )
                            msg = f"Session started. Packages: {pkg_list}"
                except Exception:
                    pass
            else:
                msg = "Session started (no packages)"

            reply = {"success": True, "kernel_id": kernel_id, "message": msg}
            if replaced_busy:
                if not msg.endswith("."):
                    reply["message"] += "."
                reply["message"] += (
                    " The previous kernel was still running code and was terminated."
                )
                reply["replaced_busy_kernel"] = True
            logger.info(reply["message"])
            return [TextContent(type="text", text=json.dumps(reply))]
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
        raw_timeout = arguments.get("timeout")
        try:
            timeout = (
                min(float(raw_timeout), MAX_TIMEOUT)
                if raw_timeout is not None
                else DEFAULT_TIMEOUT
            )
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        if not timeout > 0:  # also catches NaN
            timeout = DEFAULT_TIMEOUT
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

    elif name == "submit_code":
        code = arguments.get("code", "")
        if not code.strip():
            payload = {"ok": False, "error": "Empty submission"}
        else:
            try:
                compile(code, "<submission>", "exec")
                payload = {"ok": True}
            except SyntaxError as e:
                payload = {
                    "ok": False,
                    "error": f"Syntax error at line {e.lineno or '?'}: {e.msg}",
                }
            except ValueError as e:
                # compile() raises ValueError e.g. for null bytes in source
                payload = {"ok": False, "error": f"Invalid source: {e}"}
        return [TextContent(type="text", text=json.dumps(payload))]

    elif name == "python_status":
        kernel_id = get_kernel_id(arguments)
        is_active = kernel_exists(kernel_id)

        # Get all active kernel IDs
        all_kernel_info = list_kernels()
        all_kernel_ids = [k["id"] for k in all_kernel_info]

        status = {
            "kernel_id": kernel_id,
            "active": is_active,
            "all_kernels": all_kernel_ids,
            "python_version": None,
            "packages": [],
            "packages_total": None,
            "variables": [],
            "kernel_busy": False,
        }

        if is_active:
            try:
                requested = list(get_kernel_info(kernel_id)["packages"] or [])
            except KeyError:
                requested = []
            # Probes run only when the kernel is idle (a busy kernel keeps
            # the defaults above); they never interrupt user code
            probes = {
                "python_version": _status_probe("__import__('sys').version"),
                "packages": _status_packages_probe(requested),
                "variables": _status_probe(
                    "[name for name in dir() if not name.startswith('_')"
                    " and name not in"
                    " ('In', 'Out', 'get_ipython', 'exit', 'quit', 'open')]"
                ),
            }
            try:
                results = await loop.run_in_executor(
                    None,
                    lambda: probe_kernel(
                        kernel_id, list(probes.values()), STATUS_PROBE_TIMEOUT
                    ),
                )
            except Exception:
                results = None
            for key, result in zip(probes, results or []):
                if result.get("error") is None and result.get("stdout"):
                    try:
                        value = ast.literal_eval(result["stdout"].strip())
                    except (ValueError, SyntaxError):
                        continue
                    if key == "packages":
                        if isinstance(value, tuple) and len(value) == 2:
                            status["packages"], status["packages_total"] = value
                    else:
                        status[key] = value
            # The probe retires a kernel found dead: report it like any
            # kernel that is not in the registry
            if not kernel_exists(kernel_id):
                status["active"] = False
                status["all_kernels"] = [k["id"] for k in list_kernels()]
            else:
                # A call in flight or abandoned code still running
                status["kernel_busy"] = await loop.run_in_executor(
                    None, lambda: _kernel_busy(kernel_id)
                )

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

    return [
        TextContent(
            type="text",
            text=json.dumps({"success": False, "error": f"Unknown tool: {name}"}),
        )
    ]


async def _on_list_tools(ctx, params) -> ListToolsResult:
    """Lowlevel handler: wrap the tool list in its result type."""
    return ListToolsResult(tools=await list_tools())


async def _on_call_tool(ctx, params) -> CallToolResult:
    """Lowlevel handler.

    The SDK does not wrap a returned content list, and an exception would
    become a JSON-RPC error instead of an LLM-visible isError result, so both
    are done here.
    """
    arguments = params.arguments or {}
    # The SDK does not validate arguments against inputSchema
    tool = next((t for t in await list_tools() if t.name == params.name), None)
    if tool is not None:
        schema = tool.model_dump(by_alias=True)["inputSchema"]
        # Strict function calling sends null for omitted optional arguments:
        # treat those as absent so the defaults apply (null for a required
        # argument still fails validation)
        required = set(schema.get("required", []))
        arguments = {
            k: v for k, v in arguments.items() if v is not None or k in required
        }
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as e:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text", text=f"Input validation error: {e.message}"
                    )
                ],
                is_error=True,
            )
    try:
        content = await call_tool(params.name, arguments)
    except Exception as e:  # error text reaches the model
        return CallToolResult(
            content=[TextContent(type="text", text=str(e))], is_error=True
        )
    return CallToolResult(content=content)


def _make_server() -> Server:
    return Server(
        "ipython_mcp", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool
    )


server = _make_server()


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


# Hard-exit fallback if kernel cleanup hangs after a termination signal
_TERMINATION_CLEANUP_TIMEOUT = 10.0

# Set on the first termination signal; later signals are ignored instead of
# stacking additional timers and cleanup threads
_terminating = threading.Event()


def _handle_termination(signum, frame):
    """Shut down all kernels on SIGTERM/SIGINT, then exit.

    Kernel process groups are hard-killed first (lock-free, cannot block on
    a busy kernel's exec lock); the graceful registry cleanup then runs in a
    thread, with a timer that hard-exits if it hangs.
    """
    if _terminating.is_set():
        return
    _terminating.set()

    def _cleanup_and_exit():
        try:
            kill_all_kernel_process_groups()
            shutdown_all_kernels()
        finally:
            os._exit(128 + signum)

    threading.Timer(
        _TERMINATION_CLEANUP_TIMEOUT, lambda: os._exit(128 + signum)
    ).start()
    threading.Thread(target=_cleanup_and_exit, daemon=True).start()


def main():
    """Entry point for coder-mcp command."""
    signal.signal(signal.SIGTERM, _handle_termination)
    signal.signal(signal.SIGINT, _handle_termination)
    try:
        asyncio.run(run_server())
    finally:
        # stdin EOF / transport close / normal exit: the client is gone, so
        # hard-kill kernel groups first (immune to a busy kernel's exec
        # lock), then clean up the registry (atexit also runs the graceful
        # path, but only on clean interpreter shutdown)
        kill_all_kernel_process_groups()
        shutdown_all_kernels()


if __name__ == "__main__":
    main()
