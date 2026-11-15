"""A kernel started with packages gets exactly those packages (4.0.0).

It is launched with `uv run --isolated --no-project --no-env-file` and without
PYTHONPATH, so neither the test interpreter's virtual environment (inherited
VIRTUAL_ENV, or a .venv in the kernel's cwd) nor PYTHONPATH reaches it. A
kernel without packages runs the server's interpreter and keeps seeing its
environment (frozen behavior). Marker: yaml, a dependency of this package and
not of six or ipykernel. Requested package: six, as in the other tests.
"""

import importlib.util
import json
import os
import stat
import sys

import pytest

from agentic_python_coder import kernel as kmod
from agentic_python_coder import tools
from agentic_python_coder.mcp_server import call_tool

MARKER = "yaml"
PP_MARKER = "iso_pythonpath_marker"
NO_MARKER = f"No module named '{MARKER}'"


@pytest.fixture(autouse=True)
def leaky_environment(monkeypatch, tmp_path):
    """Every way the surrounding environment used to reach such a kernel.

    VIRTUAL_ENV names the test interpreter's venv (uv used it as the base of
    the --with layer when its Python version matched, which it does: the
    kernel follows the host's Python), and PYTHONPATH holds a marker module.
    """
    assert importlib.util.find_spec(MARKER) is not None, (
        f"{MARKER} must be importable in the test interpreter"
    )
    if sys.prefix != sys.base_prefix:
        monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    pp = tmp_path / "pythonpath"
    pp.mkdir()
    (pp / f"{PP_MARKER}.py").write_text("X = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(pp))
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()
    yield
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()


def run(kid, code):
    return kmod.execute_in_kernel(kid, code, timeout=60)


async def call(name, args):
    return json.loads((await call_tool(name, args))[0].text)


def test_kernel_with_packages_gets_only_its_packages():
    kid = kmod.create_kernel(with_packages=["six"])
    assert run(kid, "import six; six.__name__")["result"] == "'six'"
    out = run(kid, f"import {MARKER}")
    assert NO_MARKER in (out["error"] or ""), out
    out = run(kid, f"import {PP_MARKER}")
    assert f"No module named '{PP_MARKER}'" in (out["error"] or ""), out
    assert run(kid, "import ipykernel; 1")["result"] == "1"
    # Python version follows the host's
    version = run(kid, "import sys; sys.version_info[:2]")["result"]
    assert version == repr(tuple(sys.version_info[:2])), version


@pytest.mark.skipif(sys.prefix == sys.base_prefix, reason="needs a venv")
def test_venv_in_kernel_cwd_does_not_leak(monkeypatch, tmp_path):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / ".venv").symlink_to(sys.prefix)
    kid = kmod.create_kernel(with_packages=["six"], cwd=str(cwd))
    assert run(kid, "import six; 1")["result"] == "1"
    out = run(kid, f"import {MARKER}")
    assert NO_MARKER in (out["error"] or ""), out


def test_kernel_without_packages_keeps_server_environment():
    kid = kmod.create_kernel()
    out = run(kid, f"import {MARKER}, {PP_MARKER}; {MARKER}.__name__")
    assert out["error"] is None and out["result"] == f"'{MARKER}'", out


@pytest.mark.asyncio
async def test_mcp_reset_with_packages_is_isolated_and_stays_so():
    data = await call("python_reset", {"packages": ["six"]})
    assert data["success"] is True, data
    out = await call("python_exec", {"code": "import six; six.__name__"})
    assert out["success"] is True and out["result"] == "'six'", out
    out = await call("python_exec", {"code": f"import {MARKER}"})
    assert out["success"] is False and NO_MARKER in out["error"], out

    # Reset keeps the packages and the isolation
    data = await call("python_reset", {})
    assert data["success"] is True and "six" in data["message"], data
    out = await call("python_exec", {"code": f"import {MARKER}"})
    assert out["success"] is False and NO_MARKER in out["error"], out
    out = await call("python_exec", {"code": "import six; 1"})
    assert out["success"] is True and out["result"] == "1", out


@pytest.mark.asyncio
async def test_mcp_named_kernel_with_packages_is_isolated():
    data = await call("python_reset", {"kernel_id": "iso", "packages": ["six"]})
    assert data["success"] is True, data
    out = await call("python_exec", {"kernel_id": "iso", "code": f"import {MARKER}"})
    assert out["success"] is False and NO_MARKER in out["error"], out
    # The default kernel (no packages) still sees the server's environment
    out = await call("python_exec", {"code": f"import {MARKER}; 1"})
    assert out["success"] is True and out["result"] == "1", out


def test_agent_tool_with_packages_is_isolated(monkeypatch, tmp_path):
    """`coder --with six` path: CODER_WITH_PACKAGES -> get_kernel()."""
    monkeypatch.setenv("CODER_WITH_PACKAGES", json.dumps(["six"]))
    monkeypatch.setattr(tools.working_dir, "_working_dir", tmp_path.resolve())
    out = json.loads(tools.python_exec("import six; six.__name__"))
    assert out["success"] is True and out["result"] == "'six'", out
    out = json.loads(tools.python_exec(f"import {MARKER}"))
    assert out["success"] is False and NO_MARKER in out["error"], out


def test_old_uv_is_refused_with_clear_error(monkeypatch, tmp_path):
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'uv 0.4.29 (85f9a0d0e 2024-10-30)'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=["six"])
    msg = str(exc.value)
    assert "uv 0.4.30 or newer is required for kernels with packages" in msg, msg
    assert "found uv 0.4.29" in msg and str(fake) in msg, msg
    assert kmod.list_kernels() == []
