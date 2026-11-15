"""A kernel started with packages gets exactly those packages (4.0.0).

It is launched with `uv run --isolated --no-project --no-env-file` and without
PYTHONPATH, so neither a surrounding virtual environment (VIRTUAL_ENV, or a
.venv in the kernel's cwd), nor an env file named by UV_ENV_FILE, nor
PYTHONPATH reaches it. A kernel without packages runs the server's
interpreter and keeps seeing its environment (frozen behavior).

Markers, each a module that only one way can deliver: VENV_MARKER sits in
the site-packages of a virtual environment built here (so the tests do not
depend on how pytest itself runs), ENV_MARKER in a directory that only the
env file puts on PYTHONPATH, PP_MARKER in a directory on our PYTHONPATH.
yaml (a dependency of this package, not of six or ipykernel) stands for the
test interpreter's environment. Requested package: six, as elsewhere.
"""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_python_coder import kernel as kmod
from agentic_python_coder import tools
from agentic_python_coder.mcp_server import call_tool

MARKER = "yaml"
PP_MARKER = "iso_pythonpath_marker"
VENV_MARKER = "iso_venv_marker"
ENV_MARKER = "iso_envfile_marker"
LEAKS = [MARKER, PP_MARKER, VENV_MARKER, ENV_MARKER]
# Result of PROBE in a kernel: the markers it can import
PROBE = (
    "import importlib.util as _u;"
    f" print(sorted(m for m in {LEAKS!r} if _u.find_spec(m)))"
)
NO_MARKER = f"No module named '{MARKER}'"
HOST_PY = f"{sys.version_info[0]}.{sys.version_info[1]}"


@pytest.fixture(scope="module")
def marker_venv(tmp_path_factory):
    """A virtual environment of the host's Python with VENV_MARKER in its
    site-packages (no network: the marker is a plain module file)."""
    venv = tmp_path_factory.mktemp("markervenv") / "venv"
    subprocess.run(
        ["uv", "venv", "--python", HOST_PY, str(venv)],
        check=True,
        capture_output=True,
    )
    (site,) = venv.glob("lib/python*/site-packages")
    (site / f"{VENV_MARKER}.py").write_text("X = 1\n")
    return venv


@pytest.fixture(autouse=True)
def leaky_environment(monkeypatch, tmp_path, marker_venv):
    """Every way the surrounding environment used to reach such a kernel.

    VIRTUAL_ENV names the marker venv (uv used it as the base of the --with
    layer when its Python version matched, which it does: the kernel follows
    the host's Python), UV_ENV_FILE names a file that sets PYTHONPATH, and
    PYTHONPATH holds a marker module.
    """
    assert importlib.util.find_spec(MARKER) is not None, (
        f"{MARKER} must be importable in the test interpreter"
    )
    monkeypatch.setenv("VIRTUAL_ENV", str(marker_venv))
    pp = tmp_path / "pythonpath"
    pp.mkdir()
    (pp / f"{PP_MARKER}.py").write_text("X = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(pp))
    envpp = tmp_path / "envfilepath"
    envpp.mkdir()
    (envpp / f"{ENV_MARKER}.py").write_text("X = 1\n")
    envfile = tmp_path / "uv.env"
    envfile.write_text(f"PYTHONPATH={envpp}\n")
    monkeypatch.setenv("UV_ENV_FILE", str(envfile))
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()
    yield
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()


def run(kid, code):
    return kmod.execute_in_kernel(kid, code, timeout=60)


async def call(name, args):
    return json.loads((await call_tool(name, args))[0].text)


def leaks(kid):
    out = run(kid, PROBE)
    assert out["error"] is None, out
    return out["stdout"].strip()


async def mcp_leaks(args):
    out = await call("python_exec", dict(args, code=PROBE))
    assert out["success"] is True, out
    return out["stdout"].strip()


def test_kernel_with_packages_gets_only_its_packages():
    kid = kmod.create_kernel(with_packages=["six"])
    assert run(kid, "import six; six.__name__")["result"] == "'six'"
    assert leaks(kid) == "[]"
    out = run(kid, f"import {MARKER}")
    assert NO_MARKER in (out["error"] or ""), out
    assert run(kid, "import ipykernel; 1")["result"] == "1"
    # Python version follows the host's
    version = run(kid, "import sys; sys.version_info[:2]")["result"]
    assert version == repr(tuple(sys.version_info[:2])), version


def test_venv_in_kernel_cwd_does_not_leak(monkeypatch, tmp_path, marker_venv):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / ".venv").symlink_to(marker_venv)
    kid = kmod.create_kernel(with_packages=["six"], cwd=str(cwd))
    assert run(kid, "import six; 1")["result"] == "1"
    assert leaks(kid) == "[]"


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
    assert await mcp_leaks({}) == "[]"

    # Reset keeps the packages and the isolation
    data = await call("python_reset", {})
    assert data["success"] is True and "six" in data["message"], data
    assert await mcp_leaks({}) == "[]"
    out = await call("python_exec", {"code": "import six; 1"})
    assert out["success"] is True and out["result"] == "1", out


@pytest.mark.asyncio
async def test_mcp_named_kernel_with_packages_is_isolated():
    data = await call("python_reset", {"kernel_id": "iso", "packages": ["six"]})
    assert data["success"] is True, data
    assert await mcp_leaks({"kernel_id": "iso"}) == "[]"
    # The default kernel (no packages) still sees the server's environment
    out = await call("python_exec", {"code": f"import {MARKER}; 1"})
    assert out["success"] is True and out["result"] == "1", out


def test_agent_tool_with_packages_is_isolated(monkeypatch, tmp_path):
    """`coder --with six` path: CODER_WITH_PACKAGES -> get_kernel()."""
    monkeypatch.setenv("CODER_WITH_PACKAGES", json.dumps(["six"]))
    monkeypatch.setattr(tools.working_dir, "_working_dir", tmp_path.resolve())
    out = json.loads(tools.python_exec("import six; six.__name__"))
    assert out["success"] is True and out["result"] == "'six'", out
    out = json.loads(tools.python_exec(PROBE))
    assert out["success"] is True and out["stdout"].strip() == "[]", out


def write_uv(path: Path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def fake_uv_script(version: str, real_uv: str) -> str:
    """A uv that reports `version` and otherwise runs the real uv."""
    return (
        f'if [ "$1" = "--version" ]; then echo "uv {version} (85f9a0d0e)";'
        f' else exec {real_uv} "$@"; fi\n'
    )


def test_old_uv_is_refused_with_clear_error(monkeypatch, tmp_path):
    real_uv = shutil.which("uv")
    fake = tmp_path / "bin" / "uv"
    write_uv(fake, fake_uv_script("0.4.29", real_uv))
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=["six"])
    msg = str(exc.value)
    assert "uv 0.4.30 or newer is required for kernels with packages" in msg, msg
    assert "found uv 0.4.29" in msg and str(fake) in msg, msg
    assert kmod.list_kernels() == []

    # The same executable updated: accepted (the refusal was not cached)
    write_uv(fake, fake_uv_script("0.99.0", real_uv))
    kid = kmod.create_kernel(with_packages=["six"])
    assert run(kid, "import six; 1")["result"] == "1"
    kmod.shutdown_kernel_by_id(kid)

    # ...and replaced by an older one again: refused (the success is not
    # trusted for a changed executable)
    write_uv(fake, fake_uv_script("0.4.1", real_uv))
    with pytest.raises(RuntimeError) as exc:
        kmod.create_kernel(with_packages=["six"])
    assert "found uv 0.4.1 " in str(exc.value), exc.value


def test_checked_uv_is_the_launched_uv(monkeypatch, tmp_path):
    """With a relative PATH entry, `uv` names another file in the kernel's
    cwd than in ours; the launch must run the uv that was checked."""
    real_uv = shutil.which("uv")
    server = tmp_path / "server"
    kernel_cwd = tmp_path / "kernel"
    write_uv(server / "bin" / "uv", f'exec {real_uv} "$@"\n')
    write_uv(kernel_cwd / "bin" / "uv", "exit 3\n")
    monkeypatch.chdir(server)
    monkeypatch.setenv("PATH", f"bin{os.pathsep}{os.environ['PATH']}")
    kid = kmod.create_kernel(with_packages=["six"], cwd=str(kernel_cwd))
    assert run(kid, "import six; 1")["result"] == "1"
    km = kmod._kernels[kid].kernel.km
    assert km.uv_prefix[0] == os.path.abspath(server / "bin" / "uv"), km.uv_prefix
