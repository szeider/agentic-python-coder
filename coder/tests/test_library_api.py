#!/usr/bin/env python3
"""Tests for the library API."""

import tempfile
import sys
from io import StringIO


def test_imports_from_package():
    """Test that all public API can be imported from the package."""
    from agentic_python_coder import (  # noqa: F401
        __version__,
        solve_task,
        CodingAgent,
        create_coding_agent,
        run_agent,
        get_final_response,
        LLMConfig,
        get_openrouter_llm,
        list_available_models,
        DEFAULT_MODEL,
        Tool,
        ToolRegistry,
        create_tool_registry,
    )

    from importlib.metadata import version

    assert __version__ == version("agentic-python-coder")
    assert callable(solve_task)
    assert callable(create_coding_agent)
    assert callable(run_agent)
    assert callable(get_final_response)
    assert callable(get_openrouter_llm)
    assert callable(list_available_models)
    assert callable(create_tool_registry)
    assert isinstance(DEFAULT_MODEL, str)


def test_model_registry():
    """Test that list_available_models returns expected models."""
    from agentic_python_coder import list_available_models

    models = list_available_models()
    expected_models = [
        "sonnet45",
        "sonnet46",
        "sonnet5",
        "opus45",
        "opus48",
        "deepseek31",
        "grok41",
        "qwen3",
        "gemini25",
        "gemini31",
        "gpt52",
        "gpt56sol",
        "gpt56terra",
    ]
    for model in expected_models:
        assert model in models, f"Missing model: {model}"


def test_create_agent_with_string_prompt():
    """Test creating agent with system_prompt as string."""
    from agentic_python_coder import create_coding_agent, CodingAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="You are a helpful coding assistant.",
            model="sonnet45",
        )
        assert agent is not None
        assert isinstance(agent, CodingAgent)
        assert agent.working_directory == tmpdir


def test_create_agent_metadata():
    """Test that agent properties are properly stored."""
    from agentic_python_coder import create_coding_agent

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test",
            model="sonnet45",
            with_packages=["numpy", "pandas"],
            task_basename="test_task",
        )
        assert agent.working_directory == tmpdir
        assert agent.tools is not None
        assert agent.llm_config is not None


def test_create_agent_with_custom_llm_config():
    """Test that a pre-built LLMConfig is used directly (no OpenRouter setup)."""
    from openai import OpenAI
    from agentic_python_coder import create_coding_agent, LLMConfig

    custom_config = LLMConfig(
        client=OpenAI(api_key="dummy", base_url="http://localhost:11434/v1"),
        model="llama3",
        api_params={"temperature": 0.5},
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        agent = create_coding_agent(
            working_directory=tmpdir,
            system_prompt="Test",
            llm_config=custom_config,
        )
        assert agent.llm_config is custom_config
        assert agent.llm_config.model == "llama3"


def test_solve_task_accepts_llm_config():
    """Test that solve_task exposes the llm_config parameter."""
    import inspect
    from agentic_python_coder import solve_task

    sig = inspect.signature(solve_task)
    assert "llm_config" in sig.parameters


def test_model_json_base_url_and_api_key_env(tmp_path, monkeypatch):
    """Test base_url and api_key_env keys in a custom model JSON."""
    import json
    import pytest
    from agentic_python_coder import get_openrouter_llm

    config_path = tmp_path / "custom.json"
    config_path.write_text(
        json.dumps(
            {
                "path": "my-org/my-model",
                "base_url": "http://localhost:8000/v1",
                "api_key_env": "MY_CUSTOM_KEY",
                "temperature": 0.0,
            }
        )
    )

    # Missing env var raises
    monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
    with pytest.raises(ValueError, match="MY_CUSTOM_KEY"):
        get_openrouter_llm(model=str(config_path))

    # With env var set, client points at the custom endpoint
    monkeypatch.setenv("MY_CUSTOM_KEY", "test-key")
    llm_config = get_openrouter_llm(model=str(config_path))
    assert str(llm_config.client.base_url).startswith("http://localhost:8000/v1")
    assert llm_config.model == "my-org/my-model"
    # OpenRouter attribution headers are skipped for custom endpoints
    assert "HTTP-Referer" not in llm_config.client.default_headers


def test_save_code_rejects_syntax_errors(tmp_path):
    """save_code must not write non-compiling code; it returns an error instead."""
    import json
    import agentic_python_coder.tools as tools_mod
    from agentic_python_coder.tools import save_code, working_dir

    tools_mod._task_basename = None
    working_dir.set(str(tmp_path))

    result = json.loads(save_code("def broken(:\n    pass"))
    assert result["success"] is False
    assert "syntax error" in result["error"].lower()
    assert not (tmp_path / "solution.py").exists()

    result_ok = json.loads(save_code("print('hi')"))
    assert result_ok["success"] is True
    assert (tmp_path / "solution.py").exists()


def test_run_agent_recovers_from_length_truncation(tmp_path):
    """A finish_reason == 'length' response must not be taken as final answer."""
    from agentic_python_coder import (
        CodingAgent,
        LLMConfig,
        create_tool_registry,
        run_agent,
        get_final_response,
    )

    class FakeMessage:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None

    class FakeChoice:
        def __init__(self, content, finish_reason):
            self.message = FakeMessage(content)
            self.finish_reason = finish_reason

    class FakeResponse:
        def __init__(self, choice):
            self.choices = [choice]
            self.usage = None

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(FakeChoice("partial answ", "length"))
            return FakeResponse(FakeChoice("full answer", "stop"))

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    agent = CodingAgent(
        llm_config=LLMConfig(client=FakeClient(), model="fake", api_params={}),
        tools=create_tool_registry(),
        system_prompt="test",
        working_directory=str(tmp_path),
    )

    messages, stats = run_agent(agent, "hello", quiet=True)
    assert get_final_response(messages) == "full answer"
    assert agent.llm_config.client.chat.completions.calls == 2


def test_get_final_response():
    """Test get_final_response helper function."""
    from agentic_python_coder import get_final_response

    # Test with empty list
    assert get_final_response([]) is None

    # Test with dict messages (new format)
    messages = [
        {"role": "assistant", "content": "First response"},
        {"role": "assistant", "content": "Final response"},
    ]
    assert get_final_response(messages) == "Final response"

    # Test skipping tool_calls messages
    messages_with_tools = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "test", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "result"},
        {"role": "assistant", "content": "Final after tool"},
    ]
    assert get_final_response(messages_with_tools) == "Final after tool"


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


def test_tool_registry_creation():
    """Test tool registry creation with and without todo."""
    from agentic_python_coder import create_tool_registry

    # Without todo
    registry = create_tool_registry(todo=False)
    assert "python_exec" in registry
    assert "save_code" in registry
    assert "todo_write" not in registry
    assert len(registry) == 2

    # With todo
    registry_todo = create_tool_registry(todo=True)
    assert "python_exec" in registry_todo
    assert "save_code" in registry_todo
    assert "todo_write" in registry_todo
    assert len(registry_todo) == 3


def test_tool_openai_format():
    """Test that tools produce valid OpenAI format."""
    from agentic_python_coder import create_tool_registry

    registry = create_tool_registry(todo=False)
    tools = registry.get_openai_tools()

    assert len(tools) == 2
    for tool in tools:
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_malformed_json_args():
    """Test that malformed tool arguments are handled gracefully."""
    import json

    # Simulate what happens when json.loads fails on tool args
    bad_args = "not valid json {"
    try:
        json.loads(bad_args)
        assert False, "Should have raised JSONDecodeError"
    except json.JSONDecodeError:
        # This is the expected path in run_agent
        result = json.dumps({"error": f"Invalid JSON arguments: {bad_args}"})
        parsed = json.loads(result)
        assert "error" in parsed


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
