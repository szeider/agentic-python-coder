"""Kernel-id semantics of ipython_mcp 4.0 (oracle/v1_rules.md).

An omitted kernel_id means the default kernel `_default` on every tool;
python_reset(kernel_id=X) restarts X or creates it; python_exec, python_status
and python_interrupt never create named kernels. Real kernels; the package
`six` is the one the other tests install, so network needs are unchanged.
"""

import ast
import asyncio
import importlib.util
import inspect
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest

from agentic_python_coder import kernel as kmod
from agentic_python_coder.mcp_server import call_tool

BAD_PATH = "/nonexistent/e2fix-no-such-pkg"
OMIT = "omit kernel_id for the default kernel"
CREATED_SENTENCE = (
    ' Created kernel "{0}". Pass kernel_id="{0}" on every python_exec,'
    " python_status and python_interrupt call; calls without kernel_id use the"
    " default kernel."
)
DEFAULT_HINT = (
    "The next python_exec restarts it with the same packages; that call is not"
    " executed and must be sent again. python_reset() restarts it as well."
)


def restarted(packages):
    """Rule 8 reply: the crashed default kernel was restarted, code not run."""
    return {
        "success": False,
        "kernel_id": "_default",
        "error": "The default kernel had crashed and was started again with"
        f" packages [{packages}]. Earlier variables, imports and definitions are"
        " gone. This code was not executed; send it again.",
        "executed": False,
        "kernel_restarted": True,
        "kernel_busy": False,
        "timed_out": False,
    }


SIGIGN = "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
STUBBORN = SIGIGN + "while True:\n    time.sleep(0.1)\n"


@pytest.fixture(autouse=True, scope="module")
def six_only_from_packages():
    """`import six` below proves that a kernel got its packages only if the
    test environment lacks six: a kernel without packages runs this
    interpreter. (Kernels with packages no longer see the test venv.)"""
    if importlib.util.find_spec("six") is not None:
        pytest.fail(
            "six is installed in the test environment, so the six imports in"
            " this file would pass without the kernel's packages"
        )


@pytest.fixture(autouse=True)
def clean_kernels():
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()
    yield
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()


async def call(name, args):
    return json.loads((await call_tool(name, args))[0].text)


def not_found(kid, live):
    return (
        f'Kernel "{kid}" not found. Live kernels: {json.dumps(live)}.'
        f' python_reset(kernel_id="{kid}") creates it; {OMIT}.'
    )


def crashed(kid):
    return (
        f'Kernel "{kid}" crashed, its state is lost.'
        f' python_reset(kernel_id="{kid}") restarts it with its packages.'
    )


async def kill(kid):
    """SIGKILL the kernel's process and wait until it is seen dead."""
    with kmod._kernels_lock:
        km = kmod._kernels[kid].kernel.km
    os.kill(km.provisioner.process.pid, signal.SIGKILL)
    end = time.monotonic() + 10
    while km.is_alive():
        assert time.monotonic() < end, "kernel did not die"
        await asyncio.sleep(0.05)


def live_ids():
    return sorted(k["id"] for k in kmod.list_kernels())


@pytest.fixture
def plain_launch(monkeypatch):
    """Kernels ignore packages at launch (no uv); the registry keeps them."""

    class PlainKernel(kmod.PythonKernel):
        def __init__(self, cwd=None, with_packages=None, **kwargs):
            super().__init__(cwd=cwd, with_packages=None, **kwargs)

    monkeypatch.setattr(kmod, "PythonKernel", PlainKernel)


# a ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reset_with_packages_then_bare_exec():
    data = await call("python_reset", {"packages": ["six"]})
    assert data["success"] is True, data
    assert data["kernel_id"] == "_default" and data["created"] is True, data
    assert "Created kernel" not in data["message"], data

    out = await call("python_exec", {"code": "import six; six.__name__"})
    assert out["success"] is True and out["result"] == "'six'", out
    assert out["kernel_id"] == "_default"
    assert "kernel_restarted" not in out and "executed" not in out, out

    status = await call("python_status", {})
    assert status["all_kernels"] == ["_default"], status
    assert status["active"] is True and status["crashed"] is False, status

    data = await call("python_reset", {})
    assert data["success"] is True and data["created"] is False, data
    assert data["kernel_id"] == "_default"
    assert "six" in data["message"], data


# b ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_explicit_default_id_creates_like_omitted():
    data = await call("python_reset", {"kernel_id": "_default"})
    assert data == {
        "success": True,
        "kernel_id": "_default",
        "message": "Session started (no packages)",
        "created": True,
    }
    out = await call("python_exec", {"code": "1 + 1"})
    assert out["result"] == "2" and out["kernel_id"] == "_default", out
    assert live_ids() == ["_default"]
    data = await call("python_reset", {"kernel_id": "_default"})
    assert data["created"] is False, data


# c ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_named_kernel_created_separate_and_reset():
    data = await call("python_reset", {"kernel_id": "work-1"})
    assert data["success"] is True and data["created"] is True, data
    assert data["kernel_id"] == "work-1"
    assert data["message"] == "Session started (no packages)." + (
        CREATED_SENTENCE.format("work-1")
    )

    out = await call("python_exec", {"kernel_id": "work-1", "code": "v = 'w'; v"})
    assert out["result"] == "'w'" and out["kernel_id"] == "work-1", out
    out = await call("python_exec", {"code": "v = 'd'; v"})
    assert out["result"] == "'d'" and out["kernel_id"] == "_default", out
    out = await call("python_exec", {"kernel_id": "work-1", "code": "v"})
    assert out["result"] == "'w'", out
    assert live_ids() == ["_default", "work-1"]

    data = await call("python_reset", {"kernel_id": "work-1"})
    assert data["success"] is True and data["created"] is False, data
    assert data["message"] == "Session restarted (no packages)", data
    out = await call("python_exec", {"kernel_id": "work-1", "code": "v"})
    assert out["success"] is False and "NameError" in out["error"], out
    out = await call("python_exec", {"code": "v"})
    assert out["result"] == "'d'", out


# d ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kid",
    [
        "default",
        "New",
        "none",
        "NULL",
        "null",
        "_x",
        "_DEFAULT",
        "a" * 65,
        "a b",
        "-x",
        ".x",
        "x/y",
        "work\n",
        "a" * 64 + "\n",
    ],
)
async def test_d_reserved_and_invalid_ids_rejected(kid):
    data = await call("python_reset", {"kernel_id": kid})
    assert data["success"] is False, data
    assert data["kernel_id"] == kid
    assert OMIT in data["error"], data
    assert "created" not in data
    assert kmod.list_kernels() == []
    assert kmod._crashed == {}


@pytest.mark.asyncio
async def test_d_longest_valid_id_accepted():
    kid = "A" + "b_.-9" * 12 + "xyz"
    assert len(kid) == 64
    data = await call("python_reset", {"kernel_id": kid})
    assert data["success"] is True and data["created"] is True, data


@pytest.mark.asyncio
async def test_d_empty_id_means_default():
    data = await call("python_reset", {"kernel_id": ""})
    assert data["success"] is True and data["kernel_id"] == "_default", data
    assert data["created"] is True
    out = await call("python_exec", {"code": "1", "kernel_id": ""})
    assert out["kernel_id"] == "_default" and out["success"] is True, out
    status = await call("python_status", {"kernel_id": ""})
    assert status["kernel_id"] == "_default" and status["active"] is True
    data = await call("python_interrupt", {"kernel_id": ""})
    assert data["success"] is True and data["kernel_id"] == "_default", data
    assert live_ids() == ["_default"]


# e ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e_unknown_named_id_not_created():
    out = await call("python_exec", {"kernel_id": "ghost", "code": "1"})
    assert out == {
        "success": False,
        "kernel_id": "ghost",
        "error": not_found("ghost", []),
    }
    await call("python_exec", {"code": "1"})  # default kernel now live
    out = await call("python_exec", {"kernel_id": "ghost", "code": "1"})
    assert out["error"] == not_found("ghost", ["_default"]), out
    data = await call("python_interrupt", {"kernel_id": "ghost"})
    assert data == {
        "success": False,
        "kernel_id": "ghost",
        "error": not_found("ghost", ["_default"]),
    }
    status = await call("python_status", {"kernel_id": "ghost"})
    assert status["active"] is False and status["crashed"] is False, status
    assert status["all_kernels"] == ["_default"]
    assert live_ids() == ["_default"]
    assert "ghost" not in kmod._crashed


@pytest.mark.asyncio
async def test_e_interrupt_default_not_running_unchanged():
    data = await call("python_interrupt", {})
    assert data == {
        "success": False,
        "kernel_id": "_default",
        "error": "No active session to interrupt",
    }


# f ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_reset_without_packages_keeps_them_real():
    data = await call("python_reset", {"packages": ["six"]})
    assert data["success"] is True, data
    data = await call("python_reset", {})
    assert data["success"] is True and "six" in data["message"], data
    out = await call("python_exec", {"code": "import six; 1"})
    assert out["success"] is True, out


@pytest.mark.asyncio
async def test_f_packages_rule(plain_launch):
    data = await call("python_reset", {"kernel_id": "pk", "packages": ["ipykernel"]})
    assert data["success"] is True, data
    assert kmod.get_kernel_info("pk")["packages"] == ["ipykernel"]
    for packages in ([], None):
        data = await call("python_reset", {"kernel_id": "pk", "packages": packages})
        assert data["success"] is True, data
        assert data["message"].startswith("Session restarted. Packages: ipykernel ")
        assert kmod.get_kernel_info("pk")["packages"] == ["ipykernel"]
    data = await call("python_reset", {"kernel_id": "pk"})
    assert kmod.get_kernel_info("pk")["packages"] == ["ipykernel"]
    data = await call(
        "python_reset", {"kernel_id": "pk", "packages": ["jupyter_client"]}
    )
    assert data["message"].startswith("Session restarted. Packages: jupyter_client ")
    assert "ipykernel" not in data["message"], data
    assert kmod.get_kernel_info("pk")["packages"] == ["jupyter_client"]


# g ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_default_kernel_restarts_after_crash(tmp_path):
    marker = tmp_path / "ran"
    out = await call("python_exec", {"code": "1"})
    assert out["success"] is True, out
    assert "kernel_restarted" not in out and "executed" not in out, out

    await call("python_reset", {"packages": ["six"]})
    await call("python_exec", {"code": "x = 5"})
    await kill("_default")
    status = await call("python_status", {})
    assert status["active"] is False and status["crashed"] is True, status

    # The restarting call does not run its code
    code = f"y = 1\nopen({str(marker)!r}, 'w').write('x')\nprint('ran')"
    out = await call("python_exec", {"code": code})
    assert out == restarted("six"), out
    assert not out["error"].startswith("Execution timed out after")
    assert not marker.exists(), "the restarting call ran its code"
    status = await call("python_status", {})
    assert status["active"] is True and status["crashed"] is False, status
    assert status["variables"] == [], status  # neither x nor y
    out = await call("python_exec", {"code": "import six; print(six.__name__)"})
    assert out["success"] is True and out["stdout"] == "six\n", out
    assert "kernel_restarted" not in out and "executed" not in out, out
    out = await call("python_exec", {"code": "x"})
    assert "NameError" in out["error"] and "kernel_restarted" not in out, out

    # A second crash gives the same reply again
    await kill("_default")
    out = await call("python_exec", {"code": "print('ran')"})
    assert out == restarted("six"), out
    out = await call("python_exec", {"code": "1 + 1"})
    assert out["result"] == "2" and "kernel_restarted" not in out, out


@pytest.mark.asyncio
async def test_g_crash_during_execution_texts():
    await call("python_exec", {"code": "1"})
    out = await call("python_exec", {"code": "import os; os._exit(1)"})
    assert out["success"] is False, out
    assert out["error"] == (
        'Kernel "_default" crashed during execution, its state is lost. ' + DEFAULT_HINT
    )
    out = await call("python_exec", {"code": "1 + 1"})
    assert out == restarted(""), out
    out = await call("python_exec", {"code": "1 + 1"})
    assert out["result"] == "2" and "kernel_restarted" not in out, out

    await call("python_reset", {"kernel_id": "w"})
    out = await call(
        "python_exec", {"kernel_id": "w", "code": "import os; os._exit(1)"}
    )
    assert out["error"] == (
        'Kernel "w" crashed during execution, its state is lost.'
        ' python_reset(kernel_id="w") restarts it with its packages.'
    )


# h ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_named_kernel_crash():
    data = await call("python_reset", {"kernel_id": "work-1", "packages": ["six"]})
    assert data["success"] is True, data
    await call("python_exec", {"kernel_id": "work-1", "code": "x = 1"})
    await kill("work-1")

    out = await call("python_exec", {"kernel_id": "work-1", "code": "1"})
    assert out == {"success": False, "kernel_id": "work-1", "error": crashed("work-1")}
    status = await call("python_status", {"kernel_id": "work-1"})
    assert status["active"] is False and status["crashed"] is True, status
    data = await call("python_interrupt", {"kernel_id": "work-1"})
    assert data["error"] == crashed("work-1"), data
    assert "work-1" not in live_ids()

    data = await call("python_reset", {"kernel_id": "work-1"})
    assert data["success"] is True and data["created"] is False, data
    assert "six" in data["message"] and "Created kernel" not in data["message"]
    out = await call("python_exec", {"kernel_id": "work-1", "code": "import six; x"})
    assert out["success"] is False and "NameError" in out["error"], out
    out = await call("python_exec", {"kernel_id": "work-1", "code": "import six; 2"})
    assert out["success"] is True and out["result"] == "2", out
    status = await call("python_status", {"kernel_id": "work-1"})
    assert status["crashed"] is False, status


# i ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_cap_counts_named_kernels_only(monkeypatch):
    monkeypatch.setattr(kmod, "MAX_KERNELS", 2)
    for kid in ("k1", "k2"):
        data = await call("python_reset", {"kernel_id": kid})
        assert data["success"] is True, data
    data = await call("python_reset", {"kernel_id": "k3"})
    assert data == {
        "success": False,
        "kernel_id": "k3",
        "error": "Maximum of 2 named kernels reached. Live: k1, k2."
        " python_reset(kernel_id=<one of these>) reuses that kernel and"
        " discards its state; omit kernel_id for the default kernel.",
    }
    assert "k3" not in kmod._crashed

    out = await call("python_exec", {"code": "1 + 1"})
    assert out["success"] is True and out["result"] == "2", out
    data = await call("python_reset", {})
    assert data["success"] is True, data
    data = await call("python_reset", {"kernel_id": "k1"})
    assert data["success"] is True and data["created"] is False, data
    assert live_ids() == ["_default", "k1", "k2"]


# j ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_reset_and_exec_sent_together():
    for i in range(5):
        reset, out = await asyncio.gather(
            call("python_reset", {}),
            call("python_exec", {"code": f"{i} + 1", "timeout": 60}),
        )
        assert reset["success"] is True, (i, reset)
        assert out["success"] is True and out["result"] == str(i + 1), (i, out)
        for reply in (reset, out):
            text = json.dumps(reply)
            assert "already exists" not in text and "auto-start" not in text


@pytest.mark.asyncio
async def test_j_named_reset_and_exec_sent_together():
    reset, out = await asyncio.gather(
        call("python_reset", {"kernel_id": "par"}),
        call("python_exec", {"kernel_id": "par", "code": "7", "timeout": 60}),
    )
    assert reset["success"] is True and reset["created"] is True, reset
    assert out["success"] is True and out["result"] == "7", out


# k ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_failed_restart_keeps_record_named():
    data = await call("python_reset", {"kernel_id": "work-1", "packages": ["six"]})
    assert data["success"] is True, data
    data = await call("python_reset", {"kernel_id": "work-1", "packages": [BAD_PATH]})
    assert data["success"] is False and "uv said:" in data["error"], data
    status = await call("python_status", {"kernel_id": "work-1"})
    assert status["active"] is False and status["crashed"] is True, status

    data = await call("python_reset", {"kernel_id": "work-1"})
    assert data["success"] is True and data["created"] is False, data
    assert "six" in data["message"], data
    out = await call("python_exec", {"kernel_id": "work-1", "code": "import six; 1"})
    assert out["success"] is True, out


@pytest.mark.asyncio
async def test_k_failed_restart_keeps_record_default():
    data = await call("python_reset", {"packages": ["six"]})
    assert data["success"] is True, data
    data = await call("python_reset", {"packages": [BAD_PATH]})
    assert data["success"] is False and "uv said:" in data["error"], data
    out = await call("python_exec", {"code": "import six; 1"})
    assert out == restarted("six"), out
    out = await call("python_exec", {"code": "import six; 1"})
    assert out["success"] is True and "kernel_restarted" not in out, out


def test_k_restart_kernel_api_keeps_record(monkeypatch):
    kid = kmod.create_kernel("api-1")

    def failing(*args, **kwargs):
        raise RuntimeError("no start")

    monkeypatch.setattr(kmod, "PythonKernel", failing)
    with pytest.raises(RuntimeError):
        kmod.restart_kernel(kid, ["x"])
    assert not kmod.kernel_exists(kid)
    assert kmod._crashed[kid].packages == []
    monkeypatch.undo()
    kmod.restart_kernel(kid)
    assert kmod.kernel_exists(kid)


# l ---------------------------------------------------------------------------


def test_l_python_api_ids():
    kid = kmod.create_kernel(None)
    assert re.fullmatch(r"[0-9a-f]{8}", kid), kid
    assert kmod.create_kernel("work-2") == "work-2"
    for bad in ("a b", "-x", "", "a" * 65, "work\n", "a" * 64 + "\n"):
        with pytest.raises(ValueError):
            kmod.create_kernel(bad)


def test_l_python_api_cap_exempts_default(monkeypatch):
    monkeypatch.setattr(kmod, "MAX_KERNELS", 1)
    kmod.create_kernel()
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel()
    assert str(exc.value) == "Maximum 1 kernels exceeded"
    kmod.get_kernel()  # the default kernel is never refused
    assert kmod.kernel_exists(kmod.DEFAULT_KERNEL_ID)


def _git_show(path):
    root = Path(__file__).resolve().parents[2]
    try:
        return subprocess.run(
            ["git", "show", f"main:{path}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git or branch main not available")


def _signatures(source, names):
    tree = ast.parse(source)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found[node.name] = (
                ast.unparse(node.args)
                + " -> "
                + (ast.unparse(node.returns) if node.returns else "")
            )
    return found


def test_l_exported_api_unchanged():
    init_path = "coder/src/agentic_python_coder/__init__.py"
    root = Path(__file__).resolve().parents[2]
    assert (root / init_path).read_text() == _git_show(init_path)

    import agentic_python_coder as pkg

    names = [
        n
        for n in pkg.__all__
        if inspect.isfunction(getattr(pkg, n))
        and getattr(pkg, n).__module__ == kmod.__name__
    ]
    assert "create_kernel" in names and "restart_kernel" in names
    kpath = "coder/src/agentic_python_coder/kernel.py"
    old = _signatures(_git_show(kpath), names)
    new = _signatures((root / kpath).read_text(), names)
    assert set(old) == set(names)
    assert new == old


# m ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_busy_default_kernel():
    # Imports and definition in a separate, awaited exec, so the timed cell
    # only calls the function. ipykernel puts its own SIGINT handler back at
    # the start of every execute request, so a handler installed by an
    # earlier cell would not survive into the timed cell.
    out = await call(
        "python_exec",
        {
            "code": "import signal, time\n"
            "def stubborn():\n"
            "    signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "    while True:\n"
            "        time.sleep(0.1)\n"
        },
    )
    assert out["success"] is True, out
    out = await call("python_exec", {"code": "stubborn()", "timeout": 1})
    assert out["timed_out"] is True and out["kernel_busy"] is True, out
    assert out["error"].startswith("Execution timed out after 1.0s."), out
    out = await call("python_exec", {"code": "print(1)", "timeout": 5})
    assert out == {
        "success": False,
        "kernel_id": "_default",
        "error": "Kernel busy with earlier code; this code was not executed."
        " python_status shows when it is idle; python_interrupt tries to stop"
        ' the earlier code; python_reset(kernel_id="_default") replaces the'
        " kernel.",
        "executed": False,
        "kernel_busy": True,
        "timed_out": False,
    }
    data = await call("python_reset", {})
    assert data["replaced_busy_kernel"] is True and data["created"] is False, data
    assert data["message"] == (
        "Session restarted (no packages). The previous kernel was still running"
        " code and was terminated."
    )
    out = await call("python_exec", {"code": "1 + 1"})
    assert out["result"] == "2" and "kernel_restarted" not in out, out


# Review fixes ------------------------------------------------------------------


def _pid(kid):
    with kmod._kernels_lock:
        return kmod._kernels[kid].kernel.km.provisioner.process.pid


def _gone(pid, limit=5.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        if not state or state.startswith("Z"):
            return True
        time.sleep(0.1)
    return False


@pytest.mark.asyncio
async def test_fix1_failed_shutdown_of_replaced_kernel(monkeypatch):
    def broken(kernel_id, kernel):
        raise RuntimeError("closed socket")

    for kid, args in (("w1", {"kernel_id": "w1"}), ("_default", {})):
        data = await call("python_reset", dict(args, packages=["six"]))
        assert data["success"] is True, data
        old = _pid(kid)
        monkeypatch.setattr(kmod, "_shutdown_replaced", broken)
        data = await call("python_reset", args)
        monkeypatch.undo()
        assert data["success"] is False and "closed socket" in data["error"], data
        assert _gone(old), f"old kernel {old} of {kid} still alive"
        assert kid not in kmod._kernels
        assert kmod._crashed[kid].packages == ["six"]
    data = await call("python_reset", {"kernel_id": "w1"})
    assert data["success"] is True and data["created"] is False, data
    assert "six" in data["message"], data
    out = await call("python_exec", {"code": "import six; 1"})
    assert out == restarted("six"), out
    out = await call("python_exec", {"code": "import six; 1"})
    assert out["success"] is True and out["result"] == "1", out


class _HookLock:
    """Registry lock that runs hook() once, before its second acquisition."""

    def __init__(self, real, hook):
        self.real, self.hook, self.entered = real, hook, 0

    def __enter__(self):
        self.entered += 1
        if self.entered == 2 and self.hook is not None:
            hook, self.hook = self.hook, None
            hook()
        return self.real.__enter__()

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)


def test_fix2_retirement_between_registry_reads(monkeypatch):
    """A concurrent status that retires the dead kernel right after
    restart_kernel's first critical section cannot make it fail (before the
    fix, the second read raised KeyError("Unknown kernel"))."""
    kid = kmod.create_kernel("w2")
    with kmod._kernels_lock:
        state = kmod._kernels[kid]
    state.kernel.km.signal_kernel(signal.SIGKILL)
    end = time.monotonic() + 10
    while state.kernel.km.is_alive():
        assert time.monotonic() < end
        time.sleep(0.05)

    def concurrent_status():
        kmod._retire_dead_kernel(kid, state)

    monkeypatch.setattr(
        kmod, "_kernels_lock", _HookLock(kmod._kernels_lock, concurrent_status)
    )
    kmod.restart_kernel(kid)
    monkeypatch.undo()
    assert kmod.kernel_exists(kid)
    assert kid not in kmod._crashed
    assert kmod.execute_in_kernel(kid, "6 * 7")["result"] == "42"


@pytest.mark.asyncio
async def test_fix3_cancelled_reset_keeps_lock_until_worker_settles(monkeypatch):
    import threading

    from agentic_python_coder import mcp_server

    entered, release = threading.Event(), threading.Event()
    real_create = kmod.create_kernel

    def paused_create(kernel_id, packages=None):
        entered.set()
        assert release.wait(30)
        return real_create(kernel_id, packages)

    monkeypatch.setattr(mcp_server, "create_kernel", paused_create)
    reset = asyncio.create_task(call("python_reset", {}))
    while not entered.is_set():
        await asyncio.sleep(0.02)
    reset.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reset
    monkeypatch.setattr(mcp_server, "create_kernel", real_create)
    exec_ = asyncio.create_task(call("python_exec", {"code": "2 + 3"}))
    await asyncio.sleep(0.5)
    assert not exec_.done(), "exec did not wait for the cancelled reset's worker"
    release.set()
    out = await asyncio.wait_for(exec_, 60)
    assert out["success"] is True and out["result"] == "5", out
    assert live_ids() == ["_default"]


@pytest.mark.asyncio
async def test_fix4_interrupt_on_idle_dead_kernel():
    await call("python_reset", {"kernel_id": "w4"})
    await kill("w4")
    data = await call("python_interrupt", {"kernel_id": "w4"})
    assert data == {"success": False, "kernel_id": "w4", "error": crashed("w4")}
    status = await call("python_status", {"kernel_id": "w4"})
    assert status["crashed"] is True, status

    await call("python_exec", {"code": "1"})
    await kill("_default")
    data = await call("python_interrupt", {})
    assert data == {
        "success": False,
        "kernel_id": "_default",
        "error": 'Kernel "_default" crashed, its state is lost. ' + DEFAULT_HINT,
    }


@pytest.mark.asyncio
async def test_fix5_live_lists_exclude_dead_kernels(monkeypatch):
    monkeypatch.setattr(kmod, "MAX_KERNELS", 2)
    await call("python_reset", {"kernel_id": "A"})
    await call("python_reset", {"kernel_id": "B"})
    await kill("A")
    status = await call("python_status", {"kernel_id": "B"})
    assert status["all_kernels"] == ["B"], status
    out = await call("python_exec", {"kernel_id": "ghost", "code": "1"})
    assert out["error"] == not_found("ghost", ["B"]), out
    data = await call("python_reset", {"kernel_id": "C"})
    assert "Live: B." in data["error"], data
    # The exported list is unchanged: it still reports the dead kernel
    assert {k["id"]: k["alive"] for k in kmod.list_kernels()} == {
        "A": False,
        "B": True,
    }


@pytest.mark.asyncio
async def test_fix6_empty_code_uses_kernel_handling():
    out = await call("python_exec", {"kernel_id": "ghost", "code": "  "})
    assert out == {
        "success": False,
        "kernel_id": "ghost",
        "error": not_found("ghost", []),
    }
    out = await call("python_exec", {"code": ""})
    assert out == {
        "success": True,
        "kernel_id": "_default",
        "stdout": "",
        "result": None,
    }
    assert live_ids() == ["_default"]
    await kill("_default")
    out = await call("python_exec", {"code": " \n "})
    assert out == restarted(""), out
    out = await call("python_exec", {"code": ""})
    assert out == {
        "success": True,
        "kernel_id": "_default",
        "stdout": "",
        "result": None,
    }
    await call("python_reset", {"kernel_id": "w6"})
    await kill("w6")
    out = await call("python_exec", {"kernel_id": "w6", "code": ""})
    assert out["error"] == crashed("w6"), out


@pytest.mark.asyncio
async def test_fix8_no_lock_for_unknown_ids():
    from agentic_python_coder import mcp_server

    for i in range(20):
        out = await call("python_exec", {"kernel_id": f"nope-{i}", "code": "1"})
        assert out["success"] is False, out
    assert not any(k.startswith("nope-") for k in mcp_server._kernel_locks)
