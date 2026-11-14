"""Tests for the IPython kernel module."""

import os

import pytest
from agentic_python_coder.kernel import (
    PythonKernel,
    get_kernel,
    shutdown_kernel,
    format_output,
)


@pytest.fixture
def kernel():
    """Create a fresh kernel for each test."""
    # Shutdown any existing global kernel
    shutdown_kernel()
    # Create a new kernel
    k = PythonKernel()
    yield k
    # Cleanup
    k.shutdown()
    shutdown_kernel()


class TestKernelBasics:
    """Test basic kernel execution."""

    def test_simple_expression(self, kernel):
        """Basic expression returns result."""
        output = kernel.execute("2 + 2")
        assert output["error"] is None
        assert output["result"] == "4"

    def test_print_output(self, kernel):
        """Print statements captured in stdout."""
        output = kernel.execute("print('hello world')")
        assert output["error"] is None
        assert "hello world" in output["stdout"]

    def test_multiline_code(self, kernel):
        """Multiline code executes correctly."""
        code = """
x = 10
y = 20
x + y
"""
        output = kernel.execute(code)
        assert output["error"] is None
        assert output["result"] == "30"

    def test_syntax_error(self, kernel):
        """Syntax errors are captured."""
        output = kernel.execute("def (")
        assert output["error"] is not None
        assert "SyntaxError" in output["error"]

    def test_runtime_error(self, kernel):
        """Runtime errors are captured."""
        output = kernel.execute("1 / 0")
        assert output["error"] is not None
        assert "ZeroDivisionError" in output["error"]

    def test_stderr_capture(self, kernel):
        """Stderr is captured."""
        output = kernel.execute("import sys; print('error', file=sys.stderr)")
        assert "error" in output["stderr"]


class TestKernelStatePersistence:
    """Test that state persists across executions."""

    def test_variable_persistence(self, kernel):
        """Variables persist between calls."""
        kernel.execute("x = 42")
        output = kernel.execute("x * 2")
        assert output["result"] == "84"

    def test_function_persistence(self, kernel):
        """Functions persist between calls."""
        kernel.execute("def double(n): return n * 2")
        output = kernel.execute("double(21)")
        assert output["result"] == "42"

    def test_import_persistence(self, kernel):
        """Imports persist between calls."""
        kernel.execute("import math")
        output = kernel.execute("math.pi")
        assert "3.14" in output["result"]

    def test_class_persistence(self, kernel):
        """Classes persist between calls."""
        kernel.execute("class Counter:\n    def __init__(self):\n        self.n = 0")
        kernel.execute("c = Counter()")
        kernel.execute("c.n = 5")
        output = kernel.execute("c.n")
        assert output["result"] == "5"


class TestMessageLoopFix:
    """Test that message loop waits for idle status."""

    def test_slow_print_captured(self, kernel):
        """Slow output is fully captured (waits for idle, not Empty)."""
        # This used to break early on Empty before the fix
        code = """
import time
for i in range(5):
    print(f"line {i}")
    time.sleep(0.1)
print("done")
"""
        output = kernel.execute(code)
        assert output["error"] is None
        assert "line 0" in output["stdout"]
        assert "line 4" in output["stdout"]
        assert "done" in output["stdout"]

    def test_delayed_result(self, kernel):
        """Result from delayed computation is captured."""
        code = """
import time
time.sleep(0.5)
42 * 2
"""
        output = kernel.execute(code)
        assert output["error"] is None
        assert output["result"] == "84"


class TestFormatOutput:
    """Test output formatting."""

    def test_success_format(self):
        """Successful output is formatted correctly."""
        output = {"stdout": "hello", "stderr": "", "result": "42", "error": None}
        result = format_output(output)
        assert '"success": true' in result
        assert '"stdout": "hello"' in result
        assert '"result": "42"' in result

    def test_error_format(self):
        """Error output is formatted correctly."""
        output = {
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": "ValueError: bad",
        }
        result = format_output(output)
        assert '"success": false' in result
        assert "ValueError" in result

    def test_none_values_removed(self):
        """None values are removed from output."""
        output = {"stdout": "", "stderr": None, "result": None, "error": None}
        result = format_output(output)
        assert "stderr" not in result
        assert "result" not in result


class TestGlobalKernel:
    """Test global kernel management."""

    def test_get_kernel_creates_kernel(self):
        """get_kernel creates a new kernel if none exists."""
        shutdown_kernel()  # Ensure clean state
        k = get_kernel()
        assert k is not None
        output = k.execute("1 + 1")
        assert output["result"] == "2"
        shutdown_kernel()

    def test_get_kernel_reuses_kernel(self):
        """get_kernel reuses existing kernel with same config."""
        shutdown_kernel()
        k1 = get_kernel()
        k1.execute("x = 123")
        k2 = get_kernel()
        output = k2.execute("x")
        assert output["result"] == "123"
        shutdown_kernel()

    def test_shutdown_clears_state(self):
        """shutdown_kernel clears the global kernel."""
        shutdown_kernel()
        k = get_kernel()
        k.execute("y = 456")
        shutdown_kernel()
        k2 = get_kernel()
        output = k2.execute("y")
        assert output["error"] is not None
        assert "NameError" in output["error"]
        shutdown_kernel()


class TestDeadlineTimeout:
    """Deadline overrun must report a timeout error, not silent success."""

    def test_timeout_reports_error_and_interrupts(self, kernel):
        output = kernel.execute("import time; time.sleep(30)", deadline_timeout=2)
        assert output["error"] is not None
        assert "timed out" in output["error"]

        # The interrupt (plus grace period) must leave the kernel usable
        output2 = kernel.execute("21 * 2")
        assert output2["error"] is None
        assert output2["result"] == "42"

    def test_fast_code_unaffected_by_deadline(self, kernel):
        output = kernel.execute("1 + 1", deadline_timeout=30)
        assert output["error"] is None
        assert output["result"] == "2"


class TestKernelStdoutIsolation:
    """Kernel fd-level stdout must not reach the host's stdout (MCP pipe)."""

    def test_fd1_write_goes_to_stderr_not_stdout(self):
        import subprocess
        import sys

        script = (
            "from agentic_python_coder.kernel import PythonKernel\n"
            "k = PythonKernel()\n"
            "out = k.execute('import os; os.write(1, b\"FD1_MARKER\\\\n\")')\n"
            "assert out['error'] is None, out\n"
            "k.shutdown()\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "FD1_MARKER" not in proc.stdout
        # Positive control: the write happened and was redirected to stderr
        assert "FD1_MARKER" in proc.stderr


class TestStartupNamespace:
    """Startup code must not leak its imports into the user namespace."""

    def test_startup_names_not_in_namespace(self, kernel):
        output = kernel.execute("sorted(n for n in dir() if not n.startswith('_'))")
        assert output["error"] is None, output
        names = output["result"]
        for leaked in ("sys", "warnings", "builtins", "InteractiveShell"):
            assert f"'{leaked}'" not in names, names
        # Positive control: the probe sees the namespace
        assert "'get_ipython'" in names

    def test_startup_behaviour_unchanged(self, kernel):
        output = kernel.execute("input('x')")
        assert output["error"] is not None  # input() must not hang
        output = kernel.execute("x = 3\nx * 2")
        assert output["result"] == "6"


class TestNativeKernelspec:
    """A user/system "python3" kernelspec must not replace our interpreter."""

    def test_user_python3_kernelspec_ignored(self, tmp_path, monkeypatch):
        import json
        import os
        import sys

        spec_dir = tmp_path / "kernels" / "python3"
        spec_dir.mkdir(parents=True)
        (spec_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Foreign Python 3",
                    "language": "python",
                    "env": {"FOREIGN_KERNELSPEC_MARKER": "1"},
                }
            )
        )
        monkeypatch.setenv("JUPYTER_PATH", str(tmp_path))
        k = PythonKernel()
        try:
            output = k.execute(
                "import os, sys; "
                "(os.environ.get('FOREIGN_KERNELSPEC_MARKER'), sys.executable)"
            )
        finally:
            k.shutdown()
        assert output["error"] is None, output
        marker, exe = eval(output["result"])
        assert marker is None, "kernel was launched from the foreign kernelspec"
        assert os.path.realpath(exe) == os.path.realpath(sys.executable)


class TestTracebackNoAnsi:
    """Error tracebacks must be plain text (no ANSI colour codes)."""

    def test_error_has_no_ansi_escapes(self, kernel):
        output = kernel.execute("1 / 0")
        assert output["error"] is not None
        assert "ZeroDivisionError" in output["error"]
        assert "Traceback" in output["error"]  # traceback still included
        assert "\x1b" not in output["error"]


class TestKernelCrash:
    """A dying kernel is reported promptly and can be restarted by ID."""

    def test_crash_detected_promptly_and_restart_keeps_config(
        self, tmp_path, monkeypatch
    ):
        import time

        from agentic_python_coder import kernel as kernel_mod

        # Record how kernels are (re)started; packages are dropped for the
        # real launch so the test needs no uv/network
        launches = []
        real_kernel_cls = kernel_mod.PythonKernel

        def recording_kernel(cwd=None, with_packages=None, **kw):
            launches.append((cwd, with_packages))
            return real_kernel_cls(cwd=cwd, **kw)

        monkeypatch.setattr(kernel_mod, "PythonKernel", recording_kernel)

        kid = kernel_mod.create_kernel(cwd=str(tmp_path))
        try:
            with kernel_mod._kernels_lock:
                state = kernel_mod._kernels[kid]
            state.packages = ["fakepkg"]  # pretend it was created with packages
            old_kernel = state.kernel

            start = time.monotonic()
            result = kernel_mod.execute_in_kernel(
                kid, "import os; os._exit(1)", timeout=30
            )
            elapsed = time.monotonic() - start
            assert elapsed < 10, f"crash took {elapsed:.1f}s to report"
            assert "crash" in result["error"].lower(), result
            assert "timed out" not in result["error"].lower()

            # Dead kernel's client channels and manager were released
            assert old_kernel.kc is None
            assert old_kernel.km is None

            # Restart by ID with the same packages and cwd
            kernel_mod.restart_kernel(kid)
            assert launches[-1] == (str(tmp_path), ["fakepkg"])
            info = kernel_mod.get_kernel_info(kid)
            assert info["packages"] == ["fakepkg"]
            assert info["cwd"] == str(tmp_path)
            out = kernel_mod.execute_in_kernel(kid, "import os; os.getcwd()")
            assert out["error"] is None, out
            assert os.path.realpath(eval(out["result"])) == os.path.realpath(tmp_path)
        finally:
            kernel_mod.shutdown_kernel_by_id(kid)


class TestRetiredKernelRaces:
    """Callers holding a KernelState that another caller retired."""

    @pytest.fixture
    def kmod(self):
        from agentic_python_coder import kernel as kernel_mod

        yield kernel_mod
        kernel_mod.shutdown_all_kernels()

    def test_execute_on_retired_state_returns_crash_result(self, kmod):
        kid = kmod.create_kernel()
        with kmod._kernels_lock:
            state = kmod._kernels[kid]
        kmod._retire_dead_kernel(kid, state)  # caller A retires

        # Caller B already held the state and now executes on it
        out = state.kernel.execute("1 + 1")
        assert out["error"] is not None and "died" in out["error"]

    def test_execute_in_kernel_retired_midway_returns_crash_result(
        self, kmod, monkeypatch
    ):
        kid = kmod.create_kernel()
        with kmod._kernels_lock:
            state = kmod._kernels[kid]
        real_execute = state.kernel.execute

        def execute_then_retired_by_other(code, deadline_timeout=60):
            out = real_execute(code, deadline_timeout)
            kmod._retire_dead_kernel(kid, state)  # another caller retires
            return out

        monkeypatch.setattr(state.kernel, "execute", execute_then_retired_by_other)
        result = kmod.execute_in_kernel(kid, "1 + 1")
        assert "crashed" in result["error"], result
        assert result["kernel_id"] == kid

    def test_stale_retire_does_not_record_crash(self, kmod):
        kid = kmod.create_kernel()
        with kmod._kernels_lock:
            old_state = kmod._kernels[kid]
        kmod._retire_dead_kernel(kid, old_state)
        kmod.restart_kernel(kid)  # id comes back
        assert kid not in kmod._crashed

        # A delayed second caller retires the OLD state again
        kmod._retire_dead_kernel(kid, old_state)
        assert kid not in kmod._crashed
        assert kmod.kernel_exists(kid)  # the new kernel is untouched

    def test_shutdown_forgets_crash_record(self, kmod):
        kid = kmod.create_kernel()
        with kmod._kernels_lock:
            state = kmod._kernels[kid]
        kmod._retire_dead_kernel(kid, state)
        assert kid in kmod._crashed
        assert not isinstance(kmod._crashed[kid], kmod.KernelState)

        kmod.shutdown_kernel_by_id(kid)
        assert kid not in kmod._crashed
        with pytest.raises(KeyError):
            kmod.restart_kernel(kid)

        kid2 = kmod.create_kernel()
        with kmod._kernels_lock:
            state2 = kmod._kernels[kid2]
        kmod._retire_dead_kernel(kid2, state2)
        kmod.shutdown_all_kernels()
        assert kid2 not in kmod._crashed
