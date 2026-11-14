"""Tests for the MCP server."""

import pytest
import json
import asyncio

from agentic_python_coder.mcp_server import (
    call_tool,
    list_tools,
    truncate_output,
    MAX_OUTPUT,
)
from agentic_python_coder.kernel import shutdown_all_kernels


@pytest.fixture(autouse=True)
def reset_mcp_state():
    """Reset kernel state before and after each test."""
    # Reset before test
    shutdown_all_kernels()

    yield

    # Reset after test
    shutdown_all_kernels()


class TestListTools:
    """Test tool listing."""

    @pytest.mark.asyncio
    async def test_lists_all_tools(self):
        """All five tools are listed."""
        tools = await list_tools()
        names = [t.name for t in tools]
        assert "python_exec" in names
        assert "python_reset" in names
        assert "python_status" in names
        assert "python_interrupt" in names
        assert "submit_code" in names
        assert len(names) == 5

    @pytest.mark.asyncio
    async def test_python_exec_schema(self):
        """python_exec has correct schema."""
        tools = await list_tools()
        exec_tool = next(t for t in tools if t.name == "python_exec")
        assert (
            "code" in exec_tool.model_dump(by_alias=True)["inputSchema"]["properties"]
        )
        assert (
            "timeout"
            in exec_tool.model_dump(by_alias=True)["inputSchema"]["properties"]
        )
        assert "code" in exec_tool.model_dump(by_alias=True)["inputSchema"]["required"]


class TestAutoStart:
    """Tests for auto-start behavior."""

    @pytest.mark.asyncio
    async def test_auto_start_on_first_exec(self):
        """First exec auto-starts session (no packages)."""
        result = await call_tool("python_exec", {"code": "2 + 2"})
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["result"] == "4"

    @pytest.mark.asyncio
    async def test_state_persists_after_auto_start(self):
        """Variables persist after auto-start."""
        await call_tool("python_exec", {"code": "x = 42"})
        result = await call_tool("python_exec", {"code": "x * 2"})
        data = json.loads(result[0].text)
        assert data["result"] == "84"


class TestPythonReset:
    """Tests for python_reset tool."""

    @pytest.mark.asyncio
    async def test_reset_with_id_clears_session(self):
        """python_reset with kernel_id resets that kernel."""
        # Create a kernel
        create_result = await call_tool("python_reset", {})
        kernel_id = json.loads(create_result[0].text)["kernel_id"]

        # Set a variable
        await call_tool("python_exec", {"code": "x = 42", "kernel_id": kernel_id})

        # Reset that kernel
        await call_tool("python_reset", {"kernel_id": kernel_id})

        # Variable should be gone
        result = await call_tool("python_exec", {"code": "x", "kernel_id": kernel_id})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "NameError" in data["error"]

    @pytest.mark.asyncio
    async def test_reset_nonexistent_kernel_fails(self):
        """python_reset with non-existent kernel_id fails."""
        result = await call_tool("python_reset", {"kernel_id": "nonexist"})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "not found" in data["error"].lower()


class TestPythonStatus:
    """Tests for python_status tool."""

    @pytest.mark.asyncio
    async def test_status_no_session(self):
        """Status returns inactive when no session."""
        result = await call_tool("python_status", {})
        data = json.loads(result[0].text)
        assert data["active"] is False

    @pytest.mark.asyncio
    async def test_status_with_session(self):
        """Status returns active after exec."""
        await call_tool("python_exec", {"code": "x = 42"})
        result = await call_tool("python_status", {})
        data = json.loads(result[0].text)
        assert data["active"] is True
        assert data["python_version"] is not None
        assert "x" in data["variables"]

    @pytest.mark.asyncio
    async def test_status_shows_variables(self):
        """Status shows defined variables."""
        await call_tool("python_exec", {"code": "foo = 1; bar = 2"})
        result = await call_tool("python_status", {})
        data = json.loads(result[0].text)
        assert "foo" in data["variables"]
        assert "bar" in data["variables"]


class TestPythonInterrupt:
    """Tests for python_interrupt tool."""

    @pytest.mark.asyncio
    async def test_interrupt_no_session(self):
        """Interrupt with no session returns error."""
        result = await call_tool("python_interrupt", {})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "no active session" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_interrupt_idle_session(self):
        """Interrupt on idle session succeeds."""
        await call_tool("python_exec", {"code": "x = 1"})  # Start session
        result = await call_tool("python_interrupt", {})
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "preserved" in data["message"].lower()


class TestPythonExec:
    """Tests for python_exec tool."""

    @pytest.mark.asyncio
    async def test_simple_expression(self):
        """Basic expression evaluation."""
        result = await call_tool("python_exec", {"code": "2 + 2"})
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["result"] == "4"

    @pytest.mark.asyncio
    async def test_print_output(self):
        """Stdout capture."""
        result = await call_tool("python_exec", {"code": "print('hello')"})
        data = json.loads(result[0].text)
        assert "hello" in data["stdout"]

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        """Syntax errors reported correctly."""
        result = await call_tool("python_exec", {"code": "def ("})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "SyntaxError" in data["error"]

    @pytest.mark.asyncio
    async def test_runtime_error(self):
        """Runtime errors reported correctly."""
        result = await call_tool("python_exec", {"code": "1/0"})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "ZeroDivisionError" in data["error"]

    @pytest.mark.asyncio
    async def test_import_persistence(self):
        """Imports persist across calls."""
        await call_tool("python_exec", {"code": "import math"})
        result = await call_tool("python_exec", {"code": "math.pi"})
        data = json.loads(result[0].text)
        assert "3.14" in data["result"]

    @pytest.mark.asyncio
    async def test_empty_code(self):
        """Empty code returns success with no result."""
        result = await call_tool("python_exec", {"code": ""})
        data = json.loads(result[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_whitespace_only_code(self):
        """Whitespace-only code returns success with no result."""
        result = await call_tool("python_exec", {"code": "   \n   "})
        data = json.loads(result[0].text)
        assert data["success"] is True


class TestTimeout:
    """Tests for timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_short(self):
        """Code exceeding timeout is interrupted."""
        result = await call_tool(
            "python_exec", {"code": "import time; time.sleep(30)", "timeout": 1}
        )
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "timed out" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_timeout_recovery(self):
        """Session recovers after timeout (or auto-restarts)."""
        # Trigger timeout
        await call_tool(
            "python_exec", {"code": "import time; time.sleep(30)", "timeout": 1}
        )
        # Should still work (auto-restarts if crashed)
        result = await call_tool("python_exec", {"code": "1 + 1"})
        data = json.loads(result[0].text)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_timeout_cap_at_300(self):
        """Timeout is capped at 300s."""
        result = await call_tool("python_exec", {"code": "42", "timeout": 9999})
        data = json.loads(result[0].text)
        assert data["success"] is True


class TestInputBlocking:
    """Tests for input() blocking."""

    @pytest.mark.asyncio
    async def test_input_blocked(self):
        """input() raises error instead of hanging."""
        result = await call_tool(
            "python_exec", {"code": "x = input('name: ')", "timeout": 5}
        )
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert (
            "input" in data["error"].lower() or "not supported" in data["error"].lower()
        )


class TestTruncateOutput:
    """Tests for output truncation."""

    def test_truncate_stdout(self):
        """Stdout exceeding limit is truncated."""
        result = {"stdout": "x" * 200000, "stderr": "", "success": True}
        truncated = truncate_output(result)
        assert len(truncated["stdout"]) <= MAX_OUTPUT + 100  # Allow for message
        assert "truncated" in truncated["stdout"].lower()

    def test_truncate_stderr(self):
        """Stderr exceeding limit is truncated."""
        result = {"stdout": "", "stderr": "e" * 200000, "success": True}
        truncated = truncate_output(result)
        assert len(truncated["stderr"]) <= MAX_OUTPUT + 100
        assert "truncated" in truncated["stderr"].lower()

    def test_no_truncate_small_output(self):
        """Small output is not truncated."""
        result = {"stdout": "hello", "stderr": "", "success": True}
        truncated = truncate_output(result)
        assert truncated["stdout"] == "hello"

    def test_truncate_error_field(self):
        """Huge tracebacks in the error field are capped too."""
        result = {"stdout": "", "stderr": "", "error": "t" * 200000}
        truncated = truncate_output(result)
        assert len(truncated["error"]) <= MAX_OUTPUT + 100
        assert "truncated" in truncated["error"]
        assert truncated["success"] is False

    def test_truncate_result_field(self):
        """Huge repr in the result field is capped too."""
        result = {"stdout": "", "stderr": "", "result": "r" * 200000, "error": None}
        truncated = truncate_output(result)
        assert len(truncated["result"]) <= MAX_OUTPUT + 100
        assert truncated["success"] is True

    def test_none_result_untouched(self):
        """Non-string fields (result=None) must not break truncation."""
        result = {"stdout": "", "stderr": "", "result": None, "error": None}
        truncated = truncate_output(result)
        assert truncated["result"] is None

    @pytest.mark.asyncio
    async def test_large_output_truncated(self):
        """Output exceeding 100KB is truncated in exec."""
        result = await call_tool(
            "python_exec",
            {
                "code": "print('x' * 200000)"  # 200KB
            },
        )
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert len(data.get("stdout", "")) <= MAX_OUTPUT + 100
        assert "truncated" in data.get("stdout", "").lower()


class TestUnknownTool:
    """Test handling of unknown tools."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Unknown tool returns error."""
        result = await call_tool("unknown_tool", {})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "unknown tool" in data["error"].lower()


class TestConcurrency:
    """Tests for concurrent execution handling."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_serialized(self):
        """Concurrent calls don't interleave."""
        # Launch two operations concurrently
        task1 = asyncio.create_task(
            call_tool("python_exec", {"code": "x = 1; import time; time.sleep(0.3); x"})
        )
        task2 = asyncio.create_task(
            call_tool("python_exec", {"code": "y = 2; import time; time.sleep(0.3); y"})
        )

        results = await asyncio.gather(task1, task2)
        data1 = json.loads(results[0][0].text)
        data2 = json.loads(results[1][0].text)

        # Both should succeed with correct results (not interleaved)
        assert data1["result"] == "1"
        assert data2["result"] == "2"


class TestMultiKernel:
    """Tests for multi-kernel functionality via python_reset."""

    @pytest.mark.asyncio
    async def test_reset_creates_kernel_with_id(self):
        """python_reset without kernel_id creates new kernel with ID."""
        result = await call_tool("python_reset", {})
        data = json.loads(result[0].text)

        assert data["success"] is True
        assert "kernel_id" in data
        assert len(data["kernel_id"]) == 8  # 8-char hex

    @pytest.mark.asyncio
    async def test_exec_with_kernel_id(self):
        """python_exec can target specific kernel."""
        # Create a kernel via python_reset
        create_result = await call_tool("python_reset", {})
        kernel_id = json.loads(create_result[0].text)["kernel_id"]

        # Execute in that kernel
        result = await call_tool(
            "python_exec",
            {"code": "x = 42; x", "kernel_id": kernel_id},
        )
        data = json.loads(result[0].text)

        assert data["success"] is True
        assert data["result"] == "42"
        assert data["kernel_id"] == kernel_id

    @pytest.mark.asyncio
    async def test_kernels_have_isolated_state(self):
        """Different kernels have isolated state."""
        # Create two kernels via python_reset
        r1 = await call_tool("python_reset", {})
        r2 = await call_tool("python_reset", {})
        kernel1 = json.loads(r1[0].text)["kernel_id"]
        kernel2 = json.loads(r2[0].text)["kernel_id"]

        # Set different values in each
        await call_tool(
            "python_exec",
            {"code": "value = 'kernel1'", "kernel_id": kernel1},
        )
        await call_tool(
            "python_exec",
            {"code": "value = 'kernel2'", "kernel_id": kernel2},
        )

        # Check each kernel has its own value
        result1 = await call_tool(
            "python_exec", {"code": "value", "kernel_id": kernel1}
        )
        result2 = await call_tool(
            "python_exec", {"code": "value", "kernel_id": kernel2}
        )

        data1 = json.loads(result1[0].text)
        data2 = json.loads(result2[0].text)

        assert data1["result"] == "'kernel1'"
        assert data2["result"] == "'kernel2'"

    @pytest.mark.asyncio
    async def test_exec_in_nonexistent_kernel_fails(self):
        """python_exec fails for non-existent kernel."""
        result = await call_tool(
            "python_exec",
            {"code": "1+1", "kernel_id": "44444444"},
        )
        data = json.loads(result[0].text)

        assert data["success"] is False
        assert "not found" in data["error"].lower()


class TestKernelCrashRecovery:
    """A crashed kernel is reported promptly and python_reset revives its ID."""

    @pytest.mark.asyncio
    async def test_crash_then_reset_by_id(self):
        import time

        result = await call_tool("python_reset", {})
        kid = json.loads(result[0].text)["kernel_id"]

        start = time.monotonic()
        result = await call_tool(
            "python_exec",
            {"code": "import os; os._exit(1)", "kernel_id": kid, "timeout": 30},
        )
        elapsed = time.monotonic() - start
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "timed out" not in data["error"].lower(), data
        assert "crash" in data["error"].lower(), data
        assert elapsed < 10, f"crash took {elapsed:.1f}s to report"

        result = await call_tool("python_reset", {"kernel_id": kid})
        data = json.loads(result[0].text)
        assert data["success"] is True, data
        assert data["kernel_id"] == kid

        result = await call_tool("python_exec", {"code": "1 + 1", "kernel_id": kid})
        data = json.loads(result[0].text)
        assert data["success"] is True, data
        assert data["result"] == "2"


class TestStatusSideEffects:
    """python_status must not interrupt running code or touch user state."""

    @pytest.mark.asyncio
    async def test_status_does_not_interrupt_busy_kernel(self, monkeypatch):
        import time

        from agentic_python_coder import mcp_server

        # Short probe timeout: the old code interrupted the kernel after it
        monkeypatch.setattr(mcp_server, "STATUS_PROBE_TIMEOUT", 1)

        await call_tool("python_exec", {"code": "x = 1"})
        exec_task = asyncio.create_task(
            call_tool(
                "python_exec",
                {"code": "import time; time.sleep(4); 'done'", "timeout": 30},
            )
        )
        await asyncio.sleep(1.0)  # let the execution take the kernel

        start = time.monotonic()
        result = await call_tool("python_status", {})
        elapsed = time.monotonic() - start
        status = json.loads(result[0].text)
        assert set(status) == {
            "kernel_id",
            "active",
            "all_kernels",
            "python_version",
            "packages",
            "variables",
            "kernel_busy",
        }
        assert status["active"] is True
        assert elapsed < 2, f"status blocked for {elapsed:.1f}s"

        data = json.loads((await exec_task)[0].text)
        assert data["success"] is True, data
        assert data["result"] == "'done'"

    @pytest.mark.asyncio
    async def test_status_keeps_underscore_and_namespace(self):
        await call_tool("python_exec", {"code": "x = 1"})
        await call_tool("python_exec", {"code": "41 + 1"})

        result = await call_tool("python_status", {})
        status = json.loads(result[0].text)
        assert status["python_version"]
        assert status["packages"]
        assert status["variables"] == ["x"]

        result = await call_tool("python_exec", {"code": "_"})
        data = json.loads(result[0].text)
        assert data["result"] == "42", data


class TestResetPackageVersions:
    """python_reset's version probe leaves the fresh kernel's namespace alone.

    A real package install needs uv and network, so create_kernel is patched
    to start a plain kernel; the probe then reads the test environment.
    """

    @pytest.fixture
    def plain_kernels(self, monkeypatch):
        from agentic_python_coder import mcp_server
        from agentic_python_coder.kernel import create_kernel

        monkeypatch.setattr(
            mcp_server,
            "create_kernel",
            lambda kernel_id, packages=None: create_kernel(kernel_id, None),
        )

    @pytest.mark.asyncio
    async def test_versions_reported_and_namespace_clean(self, plain_kernels):
        import importlib.metadata

        packages = ["ipykernel>=1", "Jupyter_Client", "./local/pkg", "no-such-dist-x"]
        result = await call_tool("python_reset", {"packages": packages})
        data = json.loads(result[0].text)
        assert set(data) == {"success", "kernel_id", "message"}
        assert data["success"] is True, data
        ipk = importlib.metadata.version("ipykernel")
        jc = importlib.metadata.version("jupyter-client")
        assert data["message"] == (
            f"Session started. Packages: ipykernel>=1 {ipk}, Jupyter_Client {jc},"
            " ./local/pkg ?, no-such-dist-x ?"
        )

        kernel_id = data["kernel_id"]
        result = await call_tool(
            "python_exec",
            {
                "kernel_id": kernel_id,
                "code": "print(sorted(Out), repr(_), len(In),"
                " [n for n in ('importlib', 'versions', 'pkg') if n in globals()])",
            },
        )
        out = json.loads(result[0].text)
        assert out["success"] is True, out
        # Out empty, _ untouched, only the startup code and this cell in In
        assert out["stdout"].strip() == "[] '' 3 []", out

    @pytest.mark.asyncio
    async def test_reset_by_id_reports_versions(self, plain_kernels, monkeypatch):
        from agentic_python_coder import mcp_server
        from agentic_python_coder.kernel import restart_kernel

        monkeypatch.setattr(
            mcp_server,
            "restart_kernel",
            lambda kernel_id, packages=None: restart_kernel(kernel_id, None),
        )
        data = json.loads((await call_tool("python_reset", {}))[0].text)
        kernel_id = data["kernel_id"]
        await call_tool("python_exec", {"kernel_id": kernel_id, "code": "41 + 1"})
        result = await call_tool(
            "python_reset", {"kernel_id": kernel_id, "packages": ["IPyKernel[x]"]}
        )
        data = json.loads(result[0].text)
        assert data["success"] is True, data
        assert data["message"].startswith("Session started. Packages: IPyKernel[x] ")
        assert not data["message"].endswith("?"), data


class TestResetKeepsPackages:
    """python_reset by id without packages keeps the kernel's packages and
    says so. PythonKernel is patched to ignore packages at launch (no uv, no
    network); the registry still records them as with a real install."""

    @pytest.fixture
    def plain_launch(self, monkeypatch):
        from agentic_python_coder import kernel

        class PlainKernel(kernel.PythonKernel):
            def __init__(self, cwd=None, with_packages=None, **kwargs):
                super().__init__(cwd=cwd, with_packages=None, **kwargs)

        monkeypatch.setattr(kernel, "PythonKernel", PlainKernel)

    @pytest.mark.asyncio
    async def test_reset_by_id_without_packages_lists_kept(self, plain_launch):
        import importlib.metadata

        from agentic_python_coder.kernel import get_kernel_info

        packages = ["ipykernel>=1", "jupyter_client"]
        result = await call_tool("python_reset", {"packages": packages})
        kernel_id = json.loads(result[0].text)["kernel_id"]

        result = await call_tool("python_reset", {"kernel_id": kernel_id})
        data = json.loads(result[0].text)
        assert set(data) == {"success", "kernel_id", "message"}
        assert data["success"] is True, data
        assert data["kernel_id"] == kernel_id
        assert get_kernel_info(kernel_id)["packages"] == packages
        ipk = importlib.metadata.version("ipykernel")
        jc = importlib.metadata.version("jupyter-client")
        assert data["message"] == (
            f"Session started. Packages: ipykernel>=1 {ipk}, jupyter_client {jc}"
        )
        assert "no packages" not in data["message"]

    @pytest.mark.asyncio
    async def test_reset_by_id_without_any_packages(self, plain_launch):
        result = await call_tool("python_reset", {})
        kernel_id = json.loads(result[0].text)["kernel_id"]
        result = await call_tool("python_reset", {"kernel_id": kernel_id})
        data = json.loads(result[0].text)
        assert data["message"] == "Session started (no packages)", data


class TestDistributionName:
    @pytest.mark.parametrize(
        "requirement, name",
        [
            ("numpy", "numpy"),
            ("pkg>=1,<2", "pkg"),
            ("python-sat[pb]", "python-sat"),
            ("cpmpy ; python_version >= '3.10'", "cpmpy"),
            ("foo @ https://example.com/foo-1.0.tar.gz", "foo"),
            ("./local/pkg", None),
            ("/abs/path/pkg", None),
            ("git+https://github.com/a/b.git", None),
            ("", None),
        ],
    )
    def test_distribution_name(self, requirement, name):
        from agentic_python_coder.mcp_server import _distribution_name

        assert _distribution_name(requirement) == name


class TestTimeoutLowerBound:
    """Non-positive timeouts fall back to the default."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeout", [-5, 0])
    async def test_non_positive_timeout_uses_default(self, timeout):
        result = await call_tool("python_exec", {"code": "1 + 1", "timeout": timeout})
        data = json.loads(result[0].text)
        assert data["success"] is True, data
        assert data["result"] == "2"


class TestStatusDeadIdleKernel:
    """python_status retires a kernel that died while idle."""

    @pytest.mark.asyncio
    async def test_dead_idle_kernel_reported_inactive(self):
        import signal
        import time

        from agentic_python_coder import kernel as kernel_mod

        result = await call_tool("python_reset", {})
        kid = json.loads(result[0].text)["kernel_id"]
        with kernel_mod._kernels_lock:
            km = kernel_mod._kernels[kid].kernel.km
        km.signal_kernel(signal.SIGKILL)
        deadline = time.monotonic() + 10
        while km.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert not km.is_alive()

        status = json.loads(
            (await call_tool("python_status", {"kernel_id": kid}))[0].text
        )
        assert status["active"] is False, status
        assert kid not in status["all_kernels"]
        assert not kernel_mod.kernel_exists(kid)

        # The slot is freed and the id can be revived
        data = json.loads((await call_tool("python_reset", {"kernel_id": kid}))[0].text)
        assert data["success"] is True, data
