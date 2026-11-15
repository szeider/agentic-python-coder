"""Busy kernel after an ignored interrupt (E1).

Stubborn code ignores SIGINT with signal.SIG_IGN, so the timeout interrupt
cannot stop it. Each test uses its own kernel, warmed before timing.
"""

import asyncio
import json
import os
import subprocess
import time
from queue import Empty

import pytest

from agentic_python_coder import kernel as kmod
from agentic_python_coder import mcp_server
from agentic_python_coder.mcp_server import call_tool

SIGIGN = "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
STUBBORN = SIGIGN + "while True:\n    time.sleep(0.1)\n"
PREFIX = "Execution timed out after"
STOPPED = "Execution timed out after {}. Code interrupted but session state preserved."
REFUSED = (
    "Kernel busy with earlier code; this code was not executed. python_status"
    " shows when it is idle; python_interrupt tries to stop the earlier code;"
    ' python_reset(kernel_id="{}") replaces the kernel.'
)
BUSY_SENTENCE = " The previous kernel was still running code and was terminated."


def gate(path, body=""):
    """Code that ignores SIGINT and runs until the file at path exists."""
    return (
        SIGIGN
        + f"import os\nwhile not os.path.exists({str(path)!r}):\n    time.sleep(0.05)\n"
        + body
    )


def chatty_gate(path):
    """Like gate, but prints a line every 0.1 s while it waits."""
    return (
        SIGIGN + f"import os\ni = 0\nwhile not os.path.exists({str(path)!r}):\n"
        "    print('stale', i, flush=True)\n    i += 1\n    time.sleep(0.1)\n"
    )


async def wait_sent(kid, limit=10):
    """Wait until a call on kid holds the lock with its request sent."""
    k = kernel_obj(kid)
    end = time.monotonic() + limit
    while not (k._exec_lock.locked() and k._pending is not None):
        assert time.monotonic() < end, "request was not sent in time"
        await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def clean_kernels():
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()
    yield
    kmod.kill_all_kernel_process_groups()
    kmod.shutdown_all_kernels()


async def call(name, args):
    return json.loads((await call_tool(name, args))[0].text)


async def timed(name, args):
    start = time.monotonic()
    data = await call(name, args)
    return data, time.monotonic() - start


async def new_kernel():
    """A fresh, warmed kernel; returns its id."""
    kid = (await call("python_reset", {}))["kernel_id"]
    data = await call("python_exec", {"kernel_id": kid, "code": "1", "timeout": 30})
    assert data["success"] is True, data
    return kid


async def exec_(kid, code, timeout):
    return await timed(
        "python_exec", {"kernel_id": kid, "code": code, "timeout": timeout}
    )


def kernel_obj(kid):
    with kmod._kernels_lock:
        return kmod._kernels[kid].kernel


async def wait_idle(kid, limit):
    """Poll python_status until kernel_busy is False; returns the status."""
    end = time.monotonic() + limit
    while True:
        status = await call("python_status", {"kernel_id": kid})
        if not status["kernel_busy"] or time.monotonic() > end:
            return status
        await asyncio.sleep(0.2)


async def stubborn(kid, timeout=1):
    data, elapsed = await exec_(kid, STUBBORN, timeout)
    assert data["success"] is False, data
    assert data["error"].startswith(f"{PREFIX} {float(timeout)}s."), data
    assert "still running" in data["error"], data
    assert data["timed_out"] is True and data["kernel_busy"] is True, data
    return data, elapsed


def process_gone(pid, limit=5.0):
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
async def test_t1_stopped():
    kid = await new_kernel()
    data, elapsed = await exec_(kid, "import time; time.sleep(30)", 1)
    assert data["error"] == STOPPED.format("1.0s"), data
    assert data["success"] is False
    assert data["timed_out"] is True and data["kernel_busy"] is False, data
    assert elapsed < 3, elapsed
    data, _ = await exec_(kid, "1+1", 10)
    assert data["success"] is True and data["result"] == "2", data


@pytest.mark.asyncio
async def test_t1b_stopped_keeps_partial_output():
    kid = await new_kernel()
    code = "import time\nprint('a')\n7\nprint('b', flush=True)\ntime.sleep(30)"
    data, _ = await exec_(kid, code, 1)
    assert data["error"] == STOPPED.format("1.0s"), data
    assert data["stdout"] == "a\nb\n", data
    assert "result" in data


@pytest.mark.asyncio
async def test_t2_t3_t4_t5_still_running_refused_status_reset():
    kid = await new_kernel()
    k = kernel_obj(kid)
    old_pid = k.km.provisioner.process.pid

    # T2: still running
    data, elapsed = await stubborn(kid)
    assert elapsed < 4.5, elapsed
    assert not k._exec_lock.locked()

    # T3: refused without sending
    data, elapsed = await exec_(kid, "print(1)", 5)
    assert data == {
        "success": False,
        "kernel_id": kid,
        "error": REFUSED.format(kid),
        "executed": False,
        "kernel_busy": True,
        "timed_out": False,
    }, data
    assert PREFIX not in data["error"]
    assert elapsed < 1, elapsed

    # T4: status reports busy, quickly
    status, elapsed = await timed("python_status", {"kernel_id": kid})
    assert status["kernel_busy"] is True and status["active"] is True, status
    assert status["packages"] == [] and status["packages_total"] is None, status
    assert elapsed < 1, elapsed

    # T5: reset does not wait for the running code
    data, elapsed = await timed("python_reset", {"kernel_id": kid})
    assert data["success"] is True, data
    assert data["replaced_busy_kernel"] is True, data
    assert data["message"] == "Session started (no packages)." + BUSY_SENTENCE
    assert elapsed < 5 + 5, elapsed  # 5 s bound plus a normal kernel start
    assert process_gone(old_pid), f"old kernel {old_pid} still alive"
    data, _ = await exec_(kid, "1+1", 10)
    assert data["success"] is True and data["result"] == "2", data
    status = await call("python_status", {"kernel_id": kid})
    assert status["kernel_busy"] is False, status


@pytest.mark.asyncio
async def test_t4_idle_status_unchanged():
    kid = await new_kernel()
    await exec_(kid, "x = 1", 10)
    status = await call("python_status", {"kernel_id": kid})
    assert set(status) == {
        "kernel_id",
        "active",
        "all_kernels",
        "python_version",
        "packages",
        "packages_total",
        "variables",
        "kernel_busy",
    }
    assert status["kernel_busy"] is False
    assert status["python_version"] and status["packages"], status
    assert status["packages_total"] >= len(status["packages"]), status
    assert status["variables"] == ["x"], status


@pytest.mark.asyncio
async def test_idle_reset_reply_unchanged():
    kid = await new_kernel()
    data = await call("python_reset", {"kernel_id": kid})
    assert data == {
        "success": True,
        "kernel_id": kid,
        "message": "Session started (no packages)",
    }


@pytest.mark.asyncio
async def test_t6_reset_during_in_flight_call():
    kid = await new_kernel()
    task = asyncio.create_task(exec_(kid, "import time; time.sleep(60)", 60))
    await wait_sent(kid)
    data, elapsed = await timed("python_reset", {"kernel_id": kid})
    assert data["success"] is True, data
    assert data["replaced_busy_kernel"] is True, data
    assert elapsed < 6 + 5, elapsed
    reset_done = time.monotonic()
    exec_data, _ = await asyncio.wait_for(task, 10)
    assert exec_data["success"] is False, exec_data
    assert time.monotonic() - reset_done < 3
    data, _ = await exec_(kid, "1+1", 10)
    assert data["result"] == "2", data


@pytest.mark.asyncio
async def test_t7_two_concurrent_execs():
    kid = await new_kernel()
    r1, r2 = await asyncio.gather(
        exec_(kid, "x = 1; import time; time.sleep(0.3); x", 30),
        exec_(kid, "y = 2; import time; time.sleep(0.3); y", 30),
    )
    assert r1[0]["result"] == "1", r1
    assert r2[0]["result"] == "2", r2


@pytest.mark.asyncio
async def test_t8_behind_a_call_that_turns_stubborn(tmp_path):
    kid = await new_kernel()
    stop = tmp_path / "stop"
    first = asyncio.create_task(exec_(kid, gate(stop), 2))
    await wait_sent(kid)
    data, elapsed = await exec_(kid, "flag = 1", 10)
    assert data["success"] is False and data["executed"] is False, data
    assert data["error"] == REFUSED.format(kid), data
    assert elapsed < 6, elapsed
    first_data, _ = await first
    assert first_data["kernel_busy"] is True, first_data
    stop.touch()
    status = await wait_idle(kid, 10)
    assert status["kernel_busy"] is False, status
    data, _ = await exec_(kid, "'flag' in globals()", 10)
    assert data["success"] is True and data["result"] == "False", data


@pytest.mark.asyncio
async def test_t8b_waited_whole_timeout_behind_live_call(tmp_path):
    kid = await new_kernel()
    stop = tmp_path / "stop"
    first = asyncio.create_task(exec_(kid, gate(stop, "'ok'\n"), 30))
    await wait_sent(kid)
    data, elapsed = await exec_(kid, "flag = 1", 1.5)
    assert data == {
        "success": False,
        "kernel_id": kid,
        "error": "Kernel was busy with an earlier call for the whole 1.5s of this"
        " call; this code was not executed.",
        "executed": False,
        "kernel_busy": True,
        "timed_out": False,
    }, data
    assert 1.4 < elapsed < 2.5, elapsed
    stop.touch()
    first_data, _ = await first
    assert first_data["success"] is True and first_data["result"] == "'ok'"
    data, _ = await exec_(kid, "'flag' in globals()", 10)
    assert data["result"] == "False", data


@pytest.mark.asyncio
async def test_t9_self_recovery_no_hidden_queue(tmp_path):
    kid = await new_kernel()
    stop = tmp_path / "stop"
    data, _ = await exec_(kid, gate(stop), 1)
    assert data["kernel_busy"] is True, data
    data, _ = await exec_(kid, "flag = 1", 5)
    assert data["executed"] is False, data
    stop.touch()
    status = await wait_idle(kid, 10)
    assert status["kernel_busy"] is False, status
    data, _ = await exec_(kid, "'flag' in globals()", 10)
    assert data["success"] is True and data["result"] == "False", data
    status = await call("python_status", {"kernel_id": kid})
    assert status["kernel_busy"] is False, status


@pytest.mark.asyncio
async def test_t10_late_error(tmp_path):
    kid = await new_kernel()
    await exec_(kid, "x = 'state'", 10)
    stop = tmp_path / "stop"
    data, _ = await exec_(kid, gate(stop, "1/0\n"), 3)
    assert data["kernel_busy"] is True and "still running" in data["error"], data
    data, elapsed = await exec_(kid, "pass", 2)
    assert data["executed"] is False, data
    assert elapsed < 0.5, elapsed
    stop.touch()  # the earlier code now ends with its late error
    status = await wait_idle(kid, 10)
    assert status["kernel_busy"] is False, status
    data, _ = await exec_(kid, "print(1)", 10)
    assert data["success"] is True and data["stdout"] == "1\n", data
    data, _ = await exec_(kid, "print(x)", 10)
    assert data["success"] is True and data["stdout"] == "state\n", data


# --- T11: shell reply status "aborted", with fake channels -------------------


class FakeKM:
    def is_alive(self):
        return True

    def interrupt_kernel(self):
        pass


class FakeKC:
    """Channels that release scripted messages at given offsets after send."""

    def __init__(self, iopub, shell):
        self.iopub = list(iopub)  # [(offset_seconds, msg)]
        self.shell = list(shell)
        self.sent = []
        self.t0 = None

    def execute(self, code, **kwargs):
        self.sent.append((code, kwargs))
        self.t0 = time.monotonic()
        return "m1"

    def _get(self, queue, timeout):
        end = time.monotonic() + (timeout or 0)
        while True:
            if queue and self.t0 is not None:
                ready_at = self.t0 + queue[0][0]
                if time.monotonic() >= ready_at:
                    return queue.pop(0)[1]
                wait = min(ready_at, end) - time.monotonic()
            else:
                wait = end - time.monotonic()
            if wait <= 0:
                raise Empty
            time.sleep(min(wait, 0.01))

    def get_iopub_msg(self, timeout=None):
        return self._get(self.iopub, timeout)

    def get_shell_msg(self, timeout=None):
        return self._get(self.shell, timeout)


def _msg(msg_type, content, parent="m1"):
    return {
        "header": {"msg_type": msg_type},
        "parent_header": {"msg_id": parent},
        "content": content,
    }


def fake_kernel(iopub, shell):
    k = kmod.PythonKernel.__new__(kmod.PythonKernel)
    k._exec_lock = kmod.threading.Lock()
    k._pending = None
    k.km = FakeKM()
    k.kc = FakeKC(iopub, shell)
    return k


IDLE = _msg("status", {"execution_state": "idle"})
BUSY = _msg("status", {"execution_state": "busy"})
ABORTED_REPLY = _msg("execute_reply", {"status": "aborted"})
OK_REPLY = _msg("execute_reply", {"status": "ok"})
ABORTED_TEXT = (
    "The kernel aborted this request after an earlier error;"
    " this code was not executed. Send it again."
)


@pytest.mark.parametrize(
    "shell",
    [
        [(0.0, ABORTED_REPLY)],  # reply before idle
        [(0.3, ABORTED_REPLY)],  # reply arrives after idle, within the wait
    ],
)
def test_t11_aborted_reply(shell):
    k = fake_kernel([(0.0, BUSY), (0.05, IDLE)], shell)
    raw = k._execute_bounded("print(1)", 5)
    assert raw["_outcome"] == "aborted", raw
    assert k.kc.sent[0][1]["stop_on_error"] is False
    reply = mcp_server._exec_reply(raw, 5.0, "abcd1234")
    assert reply == {
        "success": False,
        "kernel_id": "abcd1234",
        "stdout": "",
        "stderr": "",
        "result": None,
        "error": ABORTED_TEXT,
        "executed": False,
        "kernel_busy": False,
        "timed_out": False,
    }
    assert k._pending is None
    assert not k._exec_lock.locked()


def test_t11_aborted_during_interrupt_grace():
    # The deadline passes first; the aborted reply arrives in the grace
    k = fake_kernel([(0.0, BUSY), (0.2, IDLE)], [(0.2, ABORTED_REPLY)])
    out, outcome = k._run("print(1)", time.monotonic() + 0.05)
    assert outcome == "aborted", outcome
    assert out == {"stdout": "", "stderr": "", "result": None, "error": ABORTED_TEXT}
    assert k._pending is None
    reply = mcp_server._exec_reply(dict(out, _outcome=outcome), 0.05, "abcd1234")
    assert reply["executed"] is False and reply["timed_out"] is False, reply
    assert reply["error"] == ABORTED_TEXT and PREFIX not in reply["error"]
    assert reply["success"] is False and reply["kernel_busy"] is False


def test_t11_aborted_during_grace_on_bounded_and_agent_paths():
    k = fake_kernel([(0.0, BUSY), (0.2, IDLE)], [(0.2, ABORTED_REPLY)])
    raw = k._execute_bounded("print(1)", 0.05)
    assert raw["_outcome"] == "aborted" and raw["error"] == ABORTED_TEXT, raw
    k = fake_kernel([(0.0, BUSY), (0.2, IDLE)], [(0.2, ABORTED_REPLY)])
    out = k.execute("print(1)", deadline_timeout=0.05)
    assert out["error"] == ABORTED_TEXT, out


def test_t11_aborted_on_agent_path():
    k = fake_kernel([(0.0, IDLE)], [(0.0, ABORTED_REPLY)])
    out = k.execute("print(1)", deadline_timeout=5)
    assert out["error"] == ABORTED_TEXT, out
    assert out["stdout"] == ""


def test_t11_other_requests_replies_ignored_and_missing_reply_completes():
    # An aborted reply to another request must not count; with no reply of
    # its own after idle, the request completes with the output collected
    other = _msg("execute_reply", {"status": "aborted"}, parent="old")
    stream = _msg("stream", {"name": "stdout", "text": "hi\n"})
    k = fake_kernel([(0.0, stream), (0.0, IDLE)], [(0.0, other)])
    start = time.monotonic()
    raw = k._execute_bounded("print('hi')", 5)
    assert raw["_outcome"] == "done", raw
    assert raw["stdout"] == "hi\n" and raw["error"] is None
    assert time.monotonic() - start < 1.5  # the reply wait is bounded


def test_t11_ok_reply_success():
    stream = _msg("stream", {"name": "stdout", "text": "1\n"})
    k = fake_kernel([(0.0, stream), (0.0, IDLE)], [(0.0, OK_REPLY)])
    raw = k._execute_bounded("print(1)", 5)
    reply = mcp_server._exec_reply(raw, 5.0, "abcd1234")
    assert reply["success"] is True and reply["stdout"] == "1\n", reply
    assert "executed" not in reply and "kernel_busy" not in reply


# --- T12: agent path -----------------------------------------------------------


@pytest.fixture
def agent_kernel():
    k = kmod.PythonKernel()
    yield k
    kmod._kill_process_group(k)
    k.shutdown()


def test_t12_agent_waits_for_earlier_code(agent_kernel, tmp_path):
    import threading

    k = agent_kernel
    assert k.execute("1")["error"] is None  # warm
    stop = tmp_path / "stop"
    out = k.execute(gate(stop), deadline_timeout=1)
    assert out["error"] == (
        "Execution timed out after 1 seconds (partial output returned)"
    ), out
    assert k._pending is not None  # still running
    # Let the earlier code end while the next call is waiting for it
    threading.Timer(1.0, stop.touch).start()
    start = time.monotonic()
    out = k.execute("21*2", deadline_timeout=20)
    assert out["error"] is None and out["result"] == "42", out
    assert time.monotonic() - start < 8


def test_t12_agent_permanently_stubborn(agent_kernel):
    k = agent_kernel
    assert k.execute("1")["error"] is None  # warm
    out = k.execute(STUBBORN, deadline_timeout=1)
    assert "timed out" in out["error"], out
    start = time.monotonic()
    out = k.execute("flag = 1", deadline_timeout=4)
    elapsed = time.monotonic() - start
    assert "still running" in out["error"] and "not executed" in out["error"], out
    assert "python_reset" not in out["error"]
    assert set(out) == {"stdout", "stderr", "result", "error"}
    assert elapsed < 6, elapsed


# --- T13, T14 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t13_stale_output_does_not_leak(tmp_path):
    kid = await new_kernel()
    stop = tmp_path / "stop"
    data, _ = await exec_(kid, chatty_gate(stop), 1)
    assert data["kernel_busy"] is True, data
    assert "stale 0" in data["stdout"], data
    status = await call("python_status", {"kernel_id": kid})
    assert status["kernel_busy"] is True, status  # still printing
    stop.touch()
    status = await wait_idle(kid, 10)
    assert status["kernel_busy"] is False, status
    data, _ = await exec_(kid, "print('fresh')", 10)
    assert data["success"] is True and data["stdout"] == "fresh\n", data


@pytest.mark.asyncio
async def test_t13b_stale_output_after_refusal_does_not_leak(tmp_path):
    # The abandoned code keeps printing while a refusal drains its messages
    kid = await new_kernel()
    stop = tmp_path / "stop"
    await exec_(kid, chatty_gate(stop), 1)
    data, _ = await exec_(kid, "print('x')", 5)
    assert data["executed"] is False, data
    stop.touch()
    status = await wait_idle(kid, 10)
    assert status["kernel_busy"] is False, status
    data, _ = await exec_(kid, "print('fresh')", 10)
    assert data["stdout"] == "fresh\n", data


@pytest.mark.asyncio
async def test_t14_timeout_text(monkeypatch):
    kid = await new_kernel()
    data, _ = await exec_(kid, "import time; time.sleep(30)", 3)
    assert data["error"] == STOPPED.format("3.0s"), data
    monkeypatch.setattr(mcp_server, "DEFAULT_TIMEOUT", 1)
    data, _ = await timed(
        "python_exec", {"kernel_id": kid, "code": "import time; time.sleep(30)"}
    )
    assert data["error"] == STOPPED.format("1s"), data


@pytest.mark.asyncio
async def test_prefix_only_in_timeout_replies():
    kid = await new_kernel()
    data, _ = await exec_(kid, "1/0", 5)
    assert PREFIX not in data["error"]
    assert set(data) == {"stdout", "stderr", "result", "error", "kernel_id", "success"}
