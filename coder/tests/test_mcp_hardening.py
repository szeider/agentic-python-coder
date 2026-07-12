"""Tests for submit_code and stale-process hardening of the MCP server.

The hardening tests spawn a real ipython_mcp server subprocess, drive it over
raw newline-delimited JSON-RPC (the MCP stdio transport), start a kernel, and
then kill the client side — asserting that no kernel processes survive.
"""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

import pytest

from agentic_python_coder.mcp_server import call_tool


# ---------------------------------------------------------------------------
# submit_code (direct handler tests)
# ---------------------------------------------------------------------------


class TestSubmitCode:
    @pytest.mark.asyncio
    async def test_valid_code_ok(self):
        result = await call_tool("submit_code", {"code": "import json\nprint(1)"})
        data = json.loads(result[0].text)
        assert data == {"ok": True}

    @pytest.mark.asyncio
    async def test_syntax_error_reported_with_line(self):
        result = await call_tool("submit_code", {"code": "def broken(:\n    pass"})
        data = json.loads(result[0].text)
        assert data["ok"] is False
        assert "line 1" in data["error"]

    @pytest.mark.asyncio
    async def test_unterminated_string_rejected(self):
        # The exact failure mode seen in the wild: a bad JSON escape turned
        # '\n'.join(...) into an unterminated string literal — here the
        # unterminated literal is the ONLY syntax problem in the code
        code = "facts = ['a', 'b']\ns = '\n'.join(facts)\nprint(s)\n"
        result = await call_tool("submit_code", {"code": code})
        data = json.loads(result[0].text)
        assert data["ok"] is False
        assert "line 2" in data["error"]

    @pytest.mark.asyncio
    async def test_null_byte_rejected_cleanly(self):
        # compile() raises ValueError (not SyntaxError) for null bytes; the
        # handler must still return the documented envelope, not crash
        result = await call_tool("submit_code", {"code": "print(1)\x00"})
        data = json.loads(result[0].text)
        assert data["ok"] is False
        assert data["error"]

    @pytest.mark.asyncio
    async def test_empty_submission_rejected(self):
        result = await call_tool("submit_code", {"code": "   \n"})
        data = json.loads(result[0].text)
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_code_is_not_executed(self, tmp_path):
        marker = tmp_path / "executed"
        code = f"open({str(marker)!r}, 'w').write('boom')"
        result = await call_tool("submit_code", {"code": code})
        data = json.loads(result[0].text)
        assert data["ok"] is True
        assert not marker.exists()


# ---------------------------------------------------------------------------
# Stale-process hardening (subprocess tests)
# ---------------------------------------------------------------------------


class MCPClient:
    """Minimal raw MCP stdio client for lifecycle tests."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "agentic_python_coder.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._lines: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._next_id = 0

    def _read_loop(self):
        for line in self.proc.stdout:
            self._lines.put(line)

    def _send(self, obj: dict):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 90.0) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no response to {method}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f"no response to {method}") from None
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == req_id:
                return msg

    def initialize(self):
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hardening-test", "version": "0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: dict, timeout: float = 90.0) -> dict:
        msg = self.request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=timeout
        )
        text = msg["result"]["content"][0]["text"]
        return json.loads(text)


def _descendants(root_pid: int) -> set:
    """All live descendant PIDs of root_pid, via ps."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True
    ).stdout
    children: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        children.setdefault(ppid, []).append(pid)
    result, frontier = set(), [root_pid]
    while frontier:
        p = frontier.pop()
        for c in children.get(p, []):
            if c not in result:
                result.add(c)
                frontier.append(c)
    return result


def _alive_pids(pids: set) -> set:
    out = subprocess.run(
        ["ps", "-axo", "pid=,stat="], capture_output=True, text=True
    ).stdout
    live = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[1].startswith("Z"):
            live.add(int(parts[0]))
    return pids & live


def _wait_until_dead(pids: set, timeout: float = 20.0) -> set:
    """Poll until all pids are gone (or zombies); return survivors."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        survivors = _alive_pids(pids)
        if not survivors:
            return set()
        time.sleep(0.5)
    return _alive_pids(pids)


@pytest.fixture
def mcp_client():
    client = MCPClient()
    yield client
    try:
        client.proc.kill()
    except ProcessLookupError:
        pass


class TestNoOrphanedKernels:
    def test_stdin_eof_kills_kernels(self, mcp_client):
        """Client closes the pipe (transport close): kernels must die."""
        mcp_client.initialize()
        result = mcp_client.call_tool("python_exec", {"code": "6 * 7", "timeout": 60})
        assert result["success"] is True

        kernel_pids = _descendants(mcp_client.proc.pid)
        assert kernel_pids, "expected a kernel process to exist"

        mcp_client.proc.stdin.close()
        mcp_client.proc.wait(timeout=20)

        survivors = _wait_until_dead(kernel_pids)
        assert not survivors, f"orphaned kernel processes: {survivors}"

    def test_sigterm_kills_uv_kernel_tree(self, mcp_client):
        """SIGTERM with a uv-wrapped kernel: the whole tree must die."""
        mcp_client.initialize()
        # uv-wrapped kernel (uv parent + python child in its own group)
        result = mcp_client.call_tool(
            "python_reset", {"packages": ["six"]}, timeout=180
        )
        assert result["success"] is True, result
        kernel_id = result["kernel_id"]
        result = mcp_client.call_tool(
            "python_exec",
            {"code": "import six; 1+1", "kernel_id": kernel_id, "timeout": 60},
        )
        assert result["success"] is True

        kernel_pids = _descendants(mcp_client.proc.pid)
        assert kernel_pids, "expected kernel processes to exist"

        os.kill(mcp_client.proc.pid, signal.SIGTERM)
        mcp_client.proc.wait(timeout=20)

        survivors = _wait_until_dead(kernel_pids)
        assert not survivors, f"orphaned kernel processes: {survivors}"

    def test_sigterm_with_busy_kernel_kills_tree(self, mcp_client):
        """SIGTERM while code is EXECUTING: the graceful path blocks on the
        kernel's exec lock, so the lock-free hard-kill must save the day."""
        mcp_client.initialize()
        result = mcp_client.call_tool("python_exec", {"code": "1+1", "timeout": 60})
        assert result["success"] is True

        # Fire a long-running execution and do NOT wait for its response
        mcp_client._send(
            {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "tools/call",
                "params": {
                    "name": "python_exec",
                    "arguments": {
                        "code": "import time; time.sleep(120)",
                        "timeout": 200,
                    },
                },
            }
        )
        time.sleep(2)  # let the execution start and take the exec lock

        kernel_pids = _descendants(mcp_client.proc.pid)
        assert kernel_pids, "expected a kernel process to exist"

        os.kill(mcp_client.proc.pid, signal.SIGTERM)
        mcp_client.proc.wait(timeout=20)

        survivors = _wait_until_dead(kernel_pids)
        assert not survivors, f"orphaned kernel processes: {survivors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
