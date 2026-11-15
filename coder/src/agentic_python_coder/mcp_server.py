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
from typing import Dict, List, Optional

import jsonschema
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from packaging.requirements import InvalidRequirement, Requirement

from agentic_python_coder.kernel import (
    _KERNEL_ID_RE,
    DEFAULT_KERNEL_ID,
    INTERRUPT_GRACE,
    _crash_record,
    _execute_bounded_in_kernel,
    _kernel_busy,
    _kernel_known,
    _KernelLimitError,
    _pop_replaced_busy,
    _retire_if_dead,
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

# One asyncio lock per kernel id: python_reset holds it for the whole call,
# python_exec for its existence check and auto-start only. Locks belong to
# the event loop that created them (tests run one loop per test).
_kernel_locks: Dict[str, asyncio.Lock] = {}
_kernel_locks_loop: Optional[asyncio.AbstractEventLoop] = None

# Ids python_reset refuses to create (compared case-insensitively), besides
# every id starting with "_" other than DEFAULT_KERNEL_ID
_RESERVED_IDS = ("default", "new", "none", "null")


def _kernel_lock(kernel_id: str) -> asyncio.Lock:
    global _kernel_locks_loop
    loop = asyncio.get_running_loop()
    if loop is not _kernel_locks_loop:
        _kernel_locks.clear()
        _kernel_locks_loop = loop
    return _kernel_locks.setdefault(kernel_id, asyncio.Lock())


def _has_lock(kernel_id: str) -> bool:
    """True if a lock exists for the id (a reset of it was handled)."""
    return (
        _kernel_locks_loop is asyncio.get_running_loop() and kernel_id in _kernel_locks
    )


# Inner tasks of _locked, kept referenced until they finish
_locked_tasks: set = set()


async def _locked(kernel_id: str, work):
    """Await work() while holding the kernel id's lock.

    The lock is taken here, in call order, and released by an inner task
    when work() has settled. A cancelled caller gets CancelledError at once,
    but the lock stays held until the worker thread is done, so the next
    call does not find a half-made kernel.
    """
    lock = _kernel_lock(kernel_id)
    await lock.acquire()

    async def inner():
        try:
            return await work()
        finally:
            lock.release()

    task = asyncio.ensure_future(inner())
    _locked_tasks.add(task)
    # Retrieve the result so an abandoned task logs no "never retrieved"
    task.add_done_callback(
        lambda t: _locked_tasks.discard(t) or t.cancelled() or t.exception()
    )
    return await asyncio.shield(task)


def _live_ids() -> List[str]:
    """Ids of registered kernels whose process is alive."""
    return [k["id"] for k in list_kernels() if k["alive"]]


def _kernel_id_error(kernel_id: str) -> Optional[str]:
    """Why python_reset may not create a kernel with this id, or None."""
    if kernel_id == DEFAULT_KERNEL_ID:
        return None
    if kernel_id.lower() in _RESERVED_IDS or kernel_id.startswith("_"):
        return (
            f'kernel_id "{kernel_id}" is reserved; omit kernel_id for the'
            " default kernel."
        )
    if not _KERNEL_ID_RE.fullmatch(kernel_id):
        return (
            f'Invalid kernel_id "{kernel_id}": use 1 to 64 letters, digits,'
            ' "_", "-" or ".", starting with a letter or digit; omit kernel_id'
            " for the default kernel."
        )
    return None


def _known(kernel_id: str) -> bool:
    """True if the id has a registered kernel (or slot) or a crash record."""
    return _kernel_known(kernel_id)


def _not_found_error(kernel_id: str) -> str:
    live = json.dumps(_live_ids())
    return (
        f'Kernel "{kernel_id}" not found. Live kernels: {live}.'
        f' python_reset(kernel_id="{kernel_id}") creates it; omit kernel_id for'
        " the default kernel."
    )


def _crashed_error(kernel_id: str) -> str:
    return (
        f'Kernel "{kernel_id}" crashed, its state is lost.'
        f' python_reset(kernel_id="{kernel_id}") restarts it with its packages.'
    )


def _restart_hint(kernel_id: str) -> str:
    """How a client gets a crashed kernel back."""
    if kernel_id == DEFAULT_KERNEL_ID:
        return (
            "The next python_exec restarts it with the same packages; that call is"
            " not executed and must be sent again. python_reset() restarts it as"
            " well."
        )
    return f'python_reset(kernel_id="{kernel_id}") restarts it with its packages.'


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
                "error": f"Execution timed out after {limit}. Session crashed."
                f" {_restart_hint(kernel_id)}",
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
    """Execute code with proper kernel-level timeout and interruption.

    The default kernel is started when it is not running: bare as on first
    use (then the code runs), or, after a crash, with its remembered
    packages, and then the code is not run (the error reply has
    "kernel_restarted": true and "executed": false). Named kernels are
    never created here.
    """
    # An unknown named id gets no lock (unless a reset of it was handled,
    # which may still be creating it)
    if (
        kernel_id != DEFAULT_KERNEL_ID
        and not _known(kernel_id)
        and not _has_lock(kernel_id)
    ):
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": _not_found_error(kernel_id),
        }

    # Held for the existence check and auto-start only: an exec that arrives
    # during a reset of its kernel runs in the new kernel afterwards
    error, restarted_with = await _locked(kernel_id, lambda: _ensure_kernel(kernel_id))
    if error is not None:
        return {"success": False, "kernel_id": kernel_id, "error": error}

    if restarted_with is not None:
        # The code was meant for the lost state: it is not run
        return {
            "success": False,
            "kernel_id": kernel_id,
            "error": "The default kernel had crashed and was started again with"
            f" packages [{', '.join(restarted_with)}]. Earlier variables, imports"
            " and definitions are gone. This code was not executed; send it again.",
            "executed": False,
            "kernel_restarted": True,
            "kernel_busy": False,
            "timed_out": False,
        }
    if code.strip():
        return await _execute_existing(code, timeout, kernel_id)
    return {"success": True, "kernel_id": kernel_id, "stdout": "", "result": None}


async def _ensure_kernel(kernel_id: str):
    """python_exec's management step; the caller holds the id's lock.

    Returns (error, restarted_with): an error text when the kernel cannot
    be used, and the packages of a crashed default kernel restarted here.
    """
    loop = asyncio.get_running_loop()
    if kernel_exists(kernel_id):
        # A process that died while idle gets its crash record now
        await loop.run_in_executor(None, lambda: _retire_if_dead(kernel_id))
    if kernel_exists(kernel_id):
        return None, None
    record = _crash_record(kernel_id)
    if kernel_id != DEFAULT_KERNEL_ID:
        if record is None:
            return _not_found_error(kernel_id), None
        return _crashed_error(kernel_id), None
    try:
        if record is None:
            await loop.run_in_executor(None, lambda: create_kernel(kernel_id))
            logger.info(f"Auto-started kernel {kernel_id}")
            return None, None
        await loop.run_in_executor(None, lambda: restart_kernel(kernel_id))
        logger.info(f"Restarted crashed kernel {kernel_id}")
        return None, list(record.packages)
    except Exception as e:
        return f"Failed to auto-start session: {str(e)}", None


async def _execute_existing(code: str, timeout: float, kernel_id: str) -> dict:
    """Run code in a registered kernel; the reply of python_exec."""
    loop = asyncio.get_running_loop()
    crash_error = (
        f'Kernel "{kernel_id}" crashed during execution, its state is lost.'
        f" {_restart_hint(kernel_id)}"
    )
    try:
        # The worker waits `timeout` (lock wait included), interrupts, waits
        # INTERRUPT_GRACE for the kernel to go idle and decides the outcome
        raw_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _execute_bounded_in_kernel(
                    kernel_id, code, timeout, crash_error
                ),
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
            error_msg = f"Session crashed (kernel died). {_restart_hint(kernel_id)}"
        else:
            error_msg = f"Session crashed: {error_str}. {_restart_hint(kernel_id)}"
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
- kernel_id: the kernel that ran the code ("_default" unless you passed one)

Tips:
- First import of large packages (numpy, pandas): use timeout=60
- All calls without kernel_id run in one default kernel, which starts by itself on first use. If it crashed, the next call restarts it with the same packages and is NOT executed; that reply has "kernel_restarted": true and "executed": false, earlier variables and imports are gone, and you send your code again.
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
                        "description": "Omit (normal case) to run in the default kernel. Pass an id only if you created a separate kernel with python_reset(kernel_id=...). An unknown id is an error; python_exec does not create named kernels.",
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="python_reset",
            description="""Restart the Python session with a clean state, optionally with packages.

Without kernel_id (normal case): restarts the default kernel, the one python_exec, python_status and python_interrupt use when kernel_id is omitted. It is started if it is not running. Variables, imports and definitions are gone afterwards.

With kernel_id: restarts that kernel, or creates it if no kernel has this id (the reply then has "created": true). Use this only for a second session separate from the default one. You choose the id (letters, digits, "_", "-", ".", for example "plots-7f3") and must pass the same kernel_id on every later python_exec, python_status and python_interrupt call.

Every caller of this server that omits kernel_id works in the same default kernel; in some hosts that includes other chats or subagents. If your state must stay untouched by them, use your own kernel_id on every call.

Example workflow:
1. python_reset(packages=["numpy"]) -> {"kernel_id": "_default", ...}
2. python_exec(code="import numpy as np")   (no kernel_id)
3. python_exec(code="np.random.rand(3)")

Separate kernel:
1. python_reset(kernel_id="plots-7f3", packages=["matplotlib"]) -> {"kernel_id": "plots-7f3", "created": true, ...}
2. python_exec(kernel_id="plots-7f3", code="import matplotlib")""",
            inputSchema={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "PyPI packages to install (e.g., ['numpy', 'pandas']). Uses UV for fast installation. The complete list for this kernel; it replaces the previous list. The kernel can import only these packages and their dependencies. Omitted or empty: the kernel keeps its current packages.",
                        "default": [],
                    },
                    "kernel_id": {
                        "type": "string",
                        "description": "Omit for the default kernel (normal case). Give an id to restart that kernel or, if no kernel has this id, to create a separate one.",
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
- See whether the kernel crashed (crashed field)
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

Note: Call this, then continue with python_exec using the same kernel_id (omit kernel_id for the default kernel).""",
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


async def _reset(kernel_id: str, packages: List[str]) -> dict:
    """python_reset's work; the caller holds the kernel id's lock.

    Restarts the id if it is live or has a crash record, otherwise creates
    it. Returns the success reply; raises when the kernel cannot start.
    """
    loop = asyncio.get_running_loop()
    created = not _known(kernel_id)
    replaced_busy = False
    if created:
        await loop.run_in_executor(
            None, lambda: create_kernel(kernel_id, packages or None)
        )
    else:
        # Also brings back a kernel that crashed, with its packages and cwd
        await loop.run_in_executor(
            None, lambda: restart_kernel(kernel_id, packages or None)
        )
        replaced_busy = _pop_replaced_busy(kernel_id)
        # Without packages the kernel keeps the ones it had: report what it
        # actually runs with
        if not packages:
            try:
                packages = list(get_kernel_info(kernel_id)["packages"] or [])
            except KeyError:
                pass

    # "restarted" for a live or crashed kernel brought back
    session = "Session started" if created else "Session restarted"
    if packages:
        msg = f"{session} with packages: {', '.join(packages)}"
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
                    pkg_list = ", ".join(f"{p} {v}" for p, v in versions.items())
                    msg = f"{session}. Packages: {pkg_list}"
        except Exception:
            pass
    else:
        msg = f"{session} (no packages)"

    reply = {"success": True, "kernel_id": kernel_id, "message": msg}
    if replaced_busy:
        if not msg.endswith("."):
            reply["message"] += "."
        reply["message"] += (
            " The previous kernel was still running code and was terminated."
        )
        reply["replaced_busy_kernel"] = True
    reply["created"] = created
    if created and kernel_id != DEFAULT_KERNEL_ID:
        if not reply["message"].endswith("."):
            reply["message"] += "."
        reply["message"] += (
            f' Created kernel "{kernel_id}". Pass kernel_id="{kernel_id}" on'
            " every python_exec, python_status and python_interrupt call;"
            " calls without kernel_id use the default kernel."
        )
    return reply


async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    loop = asyncio.get_running_loop()

    if name == "python_reset":
        # Omitted, null and "" mean the default kernel
        kernel_id = arguments.get("kernel_id") or DEFAULT_KERNEL_ID
        # A non-empty list replaces the kernel's packages; omitted, null and
        # [] keep them (a new kernel has none)
        packages = arguments.get("packages") or []

        if not _known(kernel_id):
            id_error = _kernel_id_error(kernel_id)
            if id_error:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "success": False,
                                "kernel_id": kernel_id,
                                "error": id_error,
                            }
                        ),
                    )
                ]

        try:
            reply = await _locked(kernel_id, lambda: _reset(kernel_id, packages))
            logger.info(reply["message"])
            return [TextContent(type="text", text=json.dumps(reply))]
        except _KernelLimitError as e:
            live = set(_live_ids())
            error = (
                f"Maximum of {e.limit} named kernels reached."
                f" Live: {', '.join(k for k in e.named if k in live)}."
                " python_reset(kernel_id=<one of these>) reuses that kernel and"
                " discards its state; omit kernel_id for the default kernel."
            )
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "kernel_id": kernel_id, "error": error}
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

        # Empty code goes through the same kernel handling, then is a no-op
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

        # Get all active kernel IDs (processes alive)
        all_kernel_ids = _live_ids()

        status = {
            "kernel_id": kernel_id,
            "active": is_active,
            "all_kernels": all_kernel_ids,
            "python_version": None,
            "packages": [],
            "packages_total": None,
            "variables": [],
            "kernel_busy": False,
            "crashed": False,
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
                status["all_kernels"] = _live_ids()
            else:
                # A call in flight or abandoned code still running
                status["kernel_busy"] = await loop.run_in_executor(
                    None, lambda: _kernel_busy(kernel_id)
                )

        status["crashed"] = _crash_record(kernel_id) is not None
        return [TextContent(type="text", text=json.dumps(status))]

    elif name == "python_interrupt":
        kernel_id = get_kernel_id(arguments)

        def absent_error() -> str:
            """Error for an id without a registered kernel."""
            if _crash_record(kernel_id) is not None:
                if kernel_id == DEFAULT_KERNEL_ID:
                    return (
                        f'Kernel "{kernel_id}" crashed, its state is lost.'
                        f" {_restart_hint(kernel_id)}"
                    )
                return _crashed_error(kernel_id)
            if kernel_id == DEFAULT_KERNEL_ID:
                return "No active session to interrupt"
            return _not_found_error(kernel_id)

        def error_reply(error: str):
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"success": False, "kernel_id": kernel_id, "error": error}
                    ),
                )
            ]

        # A process that died while idle gets its crash record now
        if kernel_exists(kernel_id):
            await loop.run_in_executor(None, lambda: _retire_if_dead(kernel_id))
        if not kernel_exists(kernel_id):
            return error_reply(absent_error())

        try:
            # interrupt_kernel_by_id already includes grace period sleep
            sent = await loop.run_in_executor(
                None, lambda: interrupt_kernel_by_id(kernel_id)
            )
            if not sent:
                # Died or replaced in the meantime
                await loop.run_in_executor(None, lambda: _retire_if_dead(kernel_id))
                if not kernel_exists(kernel_id):
                    return error_reply(absent_error())
                return error_reply("Failed to interrupt: the kernel is not running.")

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
                            "error": "Session crashed during interrupt."
                            f" {_restart_hint(kernel_id)}",
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
