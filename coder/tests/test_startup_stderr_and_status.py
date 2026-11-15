"""uv's reason in startup errors (E2) and python_status's package list (E3).

When a uv-launched kernel dies during startup, the same uv command is rerun
with `python -c pass`; if that fails, its stderr tail is appended to the
error after "uv said:". A local path that does not exist fails in uv
without network access; the registry case is marked `network`.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import types

import pytest

from agentic_python_coder import kernel as kmod
from agentic_python_coder.mcp_server import call_tool

BAD_PATH = "/nonexistent/e2fix-no-such-pkg"
BAD_NAME = "this-package-does-not-exist-xyz123"
SESSION_PREFIX = "Failed to start session: Failed to start kernel:"
DIED = "Failed to start kernel: Kernel died before replying to kernel_info"


@pytest.fixture(autouse=True)
def clean_kernels():
    kmod.shutdown_all_kernels()
    yield
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()


async def call(name, args):
    return json.loads((await call_tool(name, args))[0].text)


def name_of(entry):
    return entry.split(" ")[0]


def fake_popen(monkeypatch, popen):
    """Replace subprocess.Popen as seen by the diagnosis only."""
    monkeypatch.setattr(
        kmod,
        "subprocess",
        types.SimpleNamespace(
            Popen=popen,
            DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )


def python_prefix(script):
    """A uv_prefix that runs script; the appended `python -c pass` become
    its harmless sys.argv."""
    return [sys.executable, "-c", script]


def gone(pid, limit=5.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- E2 ------


@pytest.mark.asyncio
async def test_reset_bad_package_reports_uv_reason():
    data = await call("python_reset", {"packages": [BAD_PATH]})
    assert data["success"] is False, data
    assert data["error"].startswith(SESSION_PREFIX), data
    assert "Kernel died before replying to kernel_info. uv said: " in data["error"]
    assert BAD_PATH in data["error"] and "Distribution not found" in data["error"]
    assert "\n" not in data["error"] and "\x1b" not in data["error"]


@pytest.mark.asyncio
async def test_reset_by_id_bad_package_reports_uv_reason():
    await call("python_exec", {"code": "1"})
    data = await call(
        "python_reset", {"kernel_id": kmod.DEFAULT_KERNEL_ID, "packages": [BAD_PATH]}
    )
    assert data["success"] is False, data
    assert data["error"].startswith(SESSION_PREFIX), data
    assert "uv said: " in data["error"], data
    assert BAD_PATH in data["error"] and "Distribution not found" in data["error"]


@pytest.mark.network
@pytest.mark.asyncio
async def test_reset_unknown_registry_package_reports_uv_reason():
    data = await call("python_reset", {"packages": [BAD_NAME]})
    assert data["success"] is False, data
    assert data["error"].startswith(SESSION_PREFIX), data
    assert "uv said: " in data["error"], data
    assert BAD_NAME in data["error"], data
    assert "not found in the package registry" in data["error"], data


def test_python_api_bad_package_raises_with_reason():
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=[BAD_PATH])
    msg = str(exc.value)
    assert msg.startswith(DIED + ". uv said: "), msg
    assert BAD_PATH in msg and "Distribution not found" in msg, msg
    assert kmod.list_kernels() == []


def test_other_cause_appends_nothing(monkeypatch):
    """The rerun succeeds (uv resolves): the kernel died for another reason."""
    calls = []

    class Proc:
        pid = None

        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

        def wait(self, timeout=None):
            return 0

    fake_popen(monkeypatch, Proc)
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=[BAD_PATH])
    assert str(exc.value) == DIED
    ((cmd, kwargs),) = calls
    assert cmd[:2] == ["uv", "run"] and cmd[-3:] == ["python", "-c", "pass"], cmd
    i = cmd.index(BAD_PATH)
    assert cmd[i - 1 : i + 1] == ["--with", BAD_PATH], cmd
    assert "--no-project" in cmd and "--python" in cmd and "ipykernel" in cmd
    # Same isolation as the launch: no surrounding venv, env file, PYTHONPATH
    assert "--isolated" in cmd and "--no-env-file" in cmd, cmd
    assert "PYTHONPATH" not in kwargs["env"]
    assert kwargs["start_new_session"] is True
    assert kwargs["stdout"] == kwargs["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("error", [RuntimeError("boom"), OSError("no uv")])
def test_diagnosis_exception_keeps_original_error(monkeypatch, error):
    def popen(cmd, **kwargs):
        raise error

    fake_popen(monkeypatch, popen)
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=[BAD_PATH])
    assert str(exc.value) == DIED


def test_diagnosis_timeout_keeps_original_error(monkeypatch):
    monkeypatch.setattr(kmod, "_UV_DIAGNOSIS_TIMEOUT", 0.001)
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=[BAD_PATH])
    assert str(exc.value) == DIED


def test_diagnosis_timeout_kills_command_and_children(monkeypatch, tmp_path):
    pids = tmp_path / "pids"
    script = (
        "import os, subprocess, time\n"
        "child = subprocess.Popen(['sleep', '300'])\n"
        f"open({str(pids)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        "time.sleep(300)\n"
    )
    monkeypatch.setattr(kmod, "_UV_DIAGNOSIS_TIMEOUT", 1)
    start = time.monotonic()
    assert kmod._uv_diagnosis(python_prefix(script), None) == ""
    assert time.monotonic() - start < 5
    parent, child = map(int, pids.read_text().split())
    assert gone(parent), f"command {parent} still alive"
    assert gone(child), f"child {child} (sleep 300) still alive"


def test_diagnosis_tail_is_bounded_and_cleaned():
    script = (
        "import sys\n"
        "sys.stderr.write('\\x1b[31merror\\x1b[0m:\\n  first   line\\r\\n')\n"
        "sys.stderr.write('x' * 5000)\n"
        "sys.exit(2)\n"
    )
    tail = kmod._uv_diagnosis(python_prefix(script), None)
    assert tail.startswith("...") and len(tail) <= 1500, len(tail)
    assert set(tail[3:]) == {"x"}

    script = (
        "import sys\n"
        "sys.stderr.write('\\x1b[1merror\\x1b[0m: No solution\\n  cause:   x\\n')\n"
        "sys.exit(1)\n"
    )
    assert kmod._uv_diagnosis(python_prefix(script), None) == (
        "error: No solution cause: x"
    )


def test_diagnosis_huge_stderr_is_bounded():
    script = "import sys\nsys.stderr.write('y' * 5_000_000)\nsys.exit(1)\n"
    tail = kmod._uv_diagnosis(python_prefix(script), None)
    assert tail.startswith("...y") and len(tail) <= 1500, len(tail)


def test_diagnosis_writes_nothing_to_our_streams(capfd):
    prefix = ["uv", "run", "--isolated", "--no-project", "--no-env-file"]
    prefix += ["--with", BAD_PATH, "--with", "ipykernel"]
    capfd.readouterr()
    reason = kmod._uv_diagnosis(prefix, None)
    assert BAD_PATH in reason and "Distribution not found" in reason, reason
    out, err = capfd.readouterr()
    assert out == "" and err == "", (out, err)


def test_successful_uv_start_runs_no_diagnosis(monkeypatch):
    calls = []
    monkeypatch.setattr(kmod, "_uv_diagnosis", lambda *a: calls.append(a) or "")
    kid = kmod.create_kernel(with_packages=["six"])
    out = kmod.execute_in_kernel(kid, "import six; 1+1", timeout=60)
    assert out["result"] == "2", out
    assert calls == []


# ---------------------------------------------------------------- E3 ------


def _check_order(packages, requested):
    assert [name_of(p).lower() for p in packages[: len(requested)]] == requested
    rest = [name_of(p).lower() for p in packages[len(requested) :]]
    assert rest == sorted(rest), rest


@pytest.mark.asyncio
async def test_status_lists_requested_packages_first():
    """Requested distributions first, in the order given, even hidden tools;
    the registry records packages as python_reset does (no uv needed)."""
    kid = kmod.create_kernel()
    kmod._kernels[kid].packages = ["Jupyter_Client", "ipykernel>=1", "./local/pkg"]
    status = await call("python_status", {"kernel_id": kid})
    packages = status["packages"]
    assert name_of(packages[0]) in ("jupyter_client", "jupyter-client"), packages
    assert name_of(packages[1]) == "ipykernel", packages
    _check_order(packages[2:], [])
    assert len(packages) == 20, packages
    assert isinstance(status["packages_total"], int)
    assert status["packages_total"] > len(packages), status


@pytest.mark.asyncio
async def test_status_packages_survive_shadowed_builtins():
    await call("python_exec", {"code": "sorted = len = reversed = repr = None"})
    status = await call("python_status", {})
    assert status["python_version"], status
    assert len(status["packages"]) == 20, status
    _check_order(status["packages"], [])
    assert status["variables"] == ["len", "repr", "reversed", "sorted"], status


@pytest.mark.asyncio
async def test_status_with_numpy_kernel():
    data = await call("python_reset", {"packages": ["numpy"]})
    assert data["success"] is True, data
    status = await call("python_status", {"kernel_id": data["kernel_id"]})
    packages = status["packages"]
    assert name_of(packages[0]) == "numpy", packages
    _check_order(packages, ["numpy"])
    assert 1 <= len(packages) <= 20
    assert status["packages_total"] >= len(packages), status
    assert all(isinstance(p, str) and len(p.split(" ")) == 2 for p in packages)


@pytest.mark.asyncio
async def test_status_busy_and_inactive_have_null_total():
    status = await call("python_status", {})
    assert status["active"] is False
    assert status["packages"] == [] and status["packages_total"] is None, status

    await call("python_exec", {"code": "x = 1"})
    task = asyncio.create_task(
        call("python_exec", {"code": "import time; time.sleep(2)", "timeout": 30})
    )
    await asyncio.sleep(0.5)
    status = await call("python_status", {})
    assert status["kernel_busy"] is True, status
    assert status["packages"] == [] and status["packages_total"] is None, status
    assert (await task)["success"] is True
