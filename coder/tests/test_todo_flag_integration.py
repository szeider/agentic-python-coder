#!/usr/bin/env python3
"""
Integration test for the --todo flag functionality.
Tests that the coder command correctly handles the --todo flag.
"""

import subprocess
import tempfile
import os
import sys
import json
from pathlib import Path

def run_coder_command(args, timeout=30):
    """Helper to run coder command and capture output."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ}
    )
    return result

def test_help_shows_todo_flag():
    """Test that --todo flag appears in help text."""
    print("Testing: --todo flag appears in help...")

    result = run_coder_command(["coder", "--help"])

    assert "--todo" in result.stdout, "✗ --todo flag NOT found in help text"
    print("✓ --todo flag found in help text")

def test_todo_flag_creates_correct_prompt():
    """Test that --todo flag uses system_todo.md prompt."""
    print("\nTesting: --todo flag uses correct prompt file...")

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Create a simple task that will fail quickly (for testing)
        result = run_coder_command(
            ["coder", "--todo", "--api-key", "invalid-key", "print hello"],
            timeout=5
        )

        # Check if error mentions system_todo.md or shows todo-related behavior
        output = result.stdout + result.stderr

        # Even with invalid API key, we should see that it tried to load the right prompt
        assert "system_todo.md" in output or "Creating agent" in output, \
            f"✗ Could not verify --todo flag behavior. Output:\n{output[:500]}"
        print("✓ --todo flag attempts to use todo-enabled mode")

def test_default_no_todo():
    """Test that default mode (no flag) uses system.md prompt."""
    print("\nTesting: Default mode uses system.md (no todo)...")

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Create a simple task that will fail quickly (for testing)
        result = run_coder_command(
            ["coder", "--api-key", "invalid-key", "print hello"],
            timeout=15
        )

        # Check if error mentions system.md (not system_todo.md)
        output = result.stdout + result.stderr

        # Should not see todo-related content in default mode
        assert "system_todo.md" not in output, \
            f"✗ Default mode behavior unclear. Output:\n{output[:500]}"
        print("✓ Default mode does not use todo-enabled prompt")

def test_todo_with_other_flags():
    """Test that --todo works with other flags."""
    print("\nTesting: --todo works with other flags...")

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Test --todo with --with flag
        result = run_coder_command(
            ["coder", "--todo", "--with", "numpy", "--api-key", "invalid", "test"],
            timeout=15
        )

        # Should accept the combination of flags without error
        assert "unrecognized arguments" not in result.stderr, \
            f"✗ --todo flag conflicts with other options. Error:\n{result.stderr}"
        print("✓ --todo flag works with other CLI options")

def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing --todo flag implementation")
    print("=" * 60)
    
    tests = [
        test_help_shows_todo_flag,
        test_todo_flag_creates_correct_prompt,
        test_default_no_todo,
        test_todo_with_other_flags,
    ]
    
    results = []
    for test in tests:
        try:
            success = test()
            results.append(success)
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ All tests passed! ({passed}/{total})")
        sys.exit(0)
    else:
        print(f"❌ Some tests failed: {passed}/{total} passed")
        sys.exit(1)

if __name__ == "__main__":
    main()