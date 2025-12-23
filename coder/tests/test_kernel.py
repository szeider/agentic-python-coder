"""Tests for the IPython kernel module."""

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
