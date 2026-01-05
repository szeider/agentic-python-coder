#!/usr/bin/env python3
"""Tests for the library API."""

import tempfile
import sys
from io import StringIO


def test_imports_from_package():
    """Test that all public API can be imported from the package."""
    from agentic_python_coder import (
        __version__,
        solve_task,
        create_coding_agent,
        run_agent,
        get_final_response,
        get_openrouter_llm,
        list_available_models,
        DEFAULT_MODEL,
    )

    assert __version__ == "2.3.0"
    assert callable(solve_task)
    assert callable(create_coding_agent)
    assert callable(run_agent)
    assert callable(get_final_response)
    assert callable(get_openrouter_llm)
    assert callable(list_available_models)
    assert isinstance(DEFAULT_MODEL, str)


def test_model_registry():
    """Test that list_available_models returns expected models."""
    from agentic_python_coder import list_available_models

    models = list_available_models()
    expected_models = ["sonnet45", "opus45", "deepseek31", "grok41", "qwen3", "gemini25", "gpt5"]
    for model in expected_models:
        assert model in models, f"Missing model: {model}"


def test_create_agent_with_string_prompt():
    """Test creating agent with system_prompt as string."""
    from agentic_python_coder import create_coding_agent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="You are a helpful coding assistant.",
            model="sonnet45",
        )
        assert agent is not None
        assert agent._coder_metadata["working_directory"] == tmpdir


def test_create_agent_metadata():
    """Test that agent metadata is properly stored."""
    from agentic_python_coder import create_coding_agent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test",
            model="sonnet45",
            with_packages=["numpy", "pandas"],
            task_basename="test_task",
        )
        metadata = agent._coder_metadata
        # Only working_directory is stored in metadata (used by run_agent)
        # with_packages and task_basename are used during agent creation only
        assert metadata["working_directory"] == tmpdir


def test_get_final_response():
    """Test get_final_response helper function."""
    from agentic_python_coder import get_final_response

    # Test with empty list
    assert get_final_response([]) is None

    # Test with mock AI message
    class MockMessage:
        def __init__(self, content, msg_type="ai"):
            self.content = content
            self.type = msg_type
            self.tool_calls = None
            self.additional_kwargs = {}

    messages = [
        MockMessage("First response", "ai"),
        MockMessage("Final response", "ai"),
    ]
    assert get_final_response(messages) == "Final response"


def test_verbose_false_suppresses_output():
    """Test that verbose=False suppresses model info output."""
    from agentic_python_coder import create_coding_agent

    with tempfile.TemporaryDirectory() as tmpdir:
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            create_coding_agent(
                working_directory=tmpdir,
                system_prompt="Test",
                model="sonnet45",
                verbose=False,  # Should suppress output
            )
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        # Should not contain model info
        assert "Using model" not in output


def test_global_state_reset():
    """Test that global state is reset between agent creations."""
    from agentic_python_coder import create_coding_agent
    from agentic_python_coder.tools import _task_basename

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create first agent
        create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test",
            model="sonnet45",
            task_basename="task1",
        )

        # Create second agent - should reset state
        create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test",
            model="sonnet45",
            task_basename="task2",
        )

        # Global state should be reset (task_basename set to new value)
        from agentic_python_coder.tools import _task_basename
        assert _task_basename == "task2"


def test_quiet_mode_structure():
    """Test that quiet parameter exists in run_agent signature."""
    from agentic_python_coder import run_agent
    import inspect

    sig = inspect.signature(run_agent)
    params = list(sig.parameters.keys())
    assert "quiet" in params


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
