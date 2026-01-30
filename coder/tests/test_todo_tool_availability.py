#!/usr/bin/env python3
"""Test to verify that todo_write tool availability matches the --todo flag."""

import tempfile
from agentic_python_coder.agent import create_coding_agent, CodingAgent
from agentic_python_coder.runner import get_system_prompt_path


def test_agent_tools_without_todo():
    """Test that agent created without --todo flag has no todo_write tool."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test prompt",
            model="sonnet45",
            todo=False,
        )
        assert agent is not None
        assert isinstance(agent, CodingAgent)
        assert "python_exec" in agent.tools
        assert "save_code" in agent.tools
        assert "todo_write" not in agent.tools


def test_agent_tools_with_todo():
    """Test that agent created with --todo flag has todo_write tool."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test prompt",
            model="sonnet45",
            todo=True,
        )
        assert agent is not None
        assert isinstance(agent, CodingAgent)
        assert "python_exec" in agent.tools
        assert "save_code" in agent.tools
        assert "todo_write" in agent.tools


def test_prompt_path_default():
    """Test that default mode uses system.md."""
    path = get_system_prompt_path(todo=False)
    assert path.name == "system.md"
    assert path.exists()


def test_prompt_path_todo():
    """Test that todo mode uses system_todo.md."""
    path = get_system_prompt_path(todo=True)
    assert path.name == "system_todo.md"
    assert path.exists()


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
