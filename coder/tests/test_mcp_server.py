"""Tests for the MCP server."""

import pytest
import json
import asyncio

from agentic_python_coder import mcp_server
from agentic_python_coder.mcp_server import (
    call_tool,
    list_tools,
    truncate_output,
    MAX_OUTPUT,
)
from agentic_python_coder.kernel import shutdown_kernel


@pytest.fixture(autouse=True)
def reset_mcp_state():
    """Reset MCP server state before and after each test."""
    # Reset before test
    mcp_server._kernel = None
    mcp_server._initialized = False
    mcp_server._packages = []
    shutdown_kernel()

    yield

    # Reset after test
    mcp_server._kernel = None
    mcp_server._initialized = False
    mcp_server._packages = []
    shutdown_kernel()


class TestListTools:
    """Test tool listing."""

    @pytest.mark.asyncio
    async def test_lists_all_tools(self):
        """All four tools are listed."""
        tools = await list_tools()
        names = [t.name for t in tools]
        assert "python_exec" in names
        assert "python_reset" in names
        assert "python_status" in names
        assert "python_interrupt" in names

    @pytest.mark.asyncio
    async def test_python_exec_schema(self):
        """python_exec has correct schema."""
        tools = await list_tools()
        exec_tool = next(t for t in tools if t.name == "python_exec")
        assert "code" in exec_tool.inputSchema["properties"]
        assert "timeout" in exec_tool.inputSchema["properties"]
        assert "code" in exec_tool.inputSchema["required"]


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
    """Tests for python_reset tool (optional, for packages/reset)."""

    @pytest.mark.asyncio
    async def test_reset_no_packages(self):
        """Reset session without packages."""
        result = await call_tool("python_reset", {})
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert "no packages" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_reset_clears_session(self):
        """Calling reset clears existing session."""
        await call_tool("python_exec", {"code": "x = 42"})  # auto-starts
        await call_tool("python_reset", {})  # Reset
        result = await call_tool("python_exec", {"code": "x"})
        data = json.loads(result[0].text)
        assert data["success"] is False
        assert "NameError" in data["error"]


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
