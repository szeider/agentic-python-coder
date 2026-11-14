"""Unit tests for run_agent's ReAct loop using a scripted fake client.

No API calls, no kernels: the fake client returns a pre-planned sequence of
responses, and tools are lightweight stubs. This exercises the loop's error
paths (unknown tool, malformed arguments, tool exceptions, step limits).
"""

import json

import pytest

from agentic_python_coder import agent as agent_module
from agentic_python_coder.agent import CodingAgent, run_agent, get_final_response
from agentic_python_coder.llm import LLMConfig
from agentic_python_coder.runner import save_conversation_log
from agentic_python_coder.tools import Tool, ToolRegistry


# --- fake OpenAI client -----------------------------------------------------


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name, arguments, call_id="tc1"):
        self.id = call_id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, message, finish_reason="stop"):
        self.choices = [FakeChoice(message, finish_reason)]
        self.usage = None


class FakeErrorResponse:
    """Mimics an OpenRouter 200-with-error body parsed by the OpenAI SDK."""

    def __init__(self, error=None):
        self.choices = None
        self.usage = None
        self.model_extra = {"error": error} if error else {}

    def model_dump_json(self):
        return json.dumps({"choices": None, "usage": None, **self.model_extra})


class FakeErrorFinishResponse:
    """Mimics a response whose choice carries finish_reason 'error'."""

    def __init__(self, error=None):
        choice = FakeChoice(FakeMessage(""), finish_reason="error")
        choice.model_extra = {"error": error} if error else {}
        self.choices = [choice]
        self.usage = None
        self.model_extra = {}


class ScriptedClient:
    """Returns the scripted responses in order; repeats the last one."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls += 1
                idx = min(outer.calls - 1, len(outer._responses) - 1)
                return outer._responses[idx]

        class Chat:
            completions = Completions()

        self.chat = Chat()


def make_agent(tmp_path, responses, tools=None):
    if tools is None:
        tools = ToolRegistry()
        tools.register(
            Tool(
                name="echo",
                description="Echo tool for tests.\n\nArgs:\n    text\n\nReturns:\n    JSON",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                function=lambda **kw: json.dumps({"ok": True, "echo": kw}),
            )
        )
    return CodingAgent(
        llm_config=LLMConfig(
            client=ScriptedClient(responses), model="fake", api_params={}
        ),
        tools=tools,
        system_prompt="test",
        working_directory=str(tmp_path),
    )


def tool_messages(messages):
    return [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]


# --- tests -------------------------------------------------------------------


class TestToolDispatch:
    def test_tool_call_then_final_answer(self, tmp_path):
        agent = make_agent(
            tmp_path,
            [
                FakeResponse(
                    FakeMessage(tool_calls=[FakeToolCall("echo", '{"text": "hi"}')])
                ),
                FakeResponse(FakeMessage("done")),
            ],
        )
        messages, stats = run_agent(agent, "go", quiet=True)
        assert get_final_response(messages) == "done"
        assert stats["tool_usage"] == {"echo": 1}
        result = json.loads(tool_messages(messages)[0]["content"])
        assert result["ok"] is True

    def test_unknown_tool_error_fed_back(self, tmp_path):
        agent = make_agent(
            tmp_path,
            [
                FakeResponse(
                    FakeMessage(tool_calls=[FakeToolCall("nonexistent", "{}")])
                ),
                FakeResponse(FakeMessage("recovered")),
            ],
        )
        messages, _ = run_agent(agent, "go", quiet=True)
        result = json.loads(tool_messages(messages)[0]["content"])
        assert "Unknown tool" in result["error"]
        assert get_final_response(messages) == "recovered"

    def test_invalid_json_arguments_fed_back(self, tmp_path):
        agent = make_agent(
            tmp_path,
            [
                FakeResponse(
                    FakeMessage(tool_calls=[FakeToolCall("echo", "not json {")])
                ),
                FakeResponse(FakeMessage("recovered")),
            ],
        )
        messages, _ = run_agent(agent, "go", quiet=True)
        result = json.loads(tool_messages(messages)[0]["content"])
        assert "Invalid JSON arguments" in result["error"]

    def test_tool_exception_fed_back(self, tmp_path):
        def explode(**kw):
            raise RuntimeError("boom")

        tools = ToolRegistry()
        tools.register(
            Tool(
                name="bomb",
                description="Always fails.\n\nArgs:\n    none\n\nReturns:\n    never",
                parameters={"type": "object", "properties": {}},
                function=explode,
            )
        )
        agent = make_agent(
            tmp_path,
            [
                FakeResponse(FakeMessage(tool_calls=[FakeToolCall("bomb", "{}")])),
                FakeResponse(FakeMessage("recovered")),
            ],
            tools=tools,
        )
        messages, _ = run_agent(agent, "go", quiet=True)
        result = json.loads(tool_messages(messages)[0]["content"])
        assert "failed" in result["error"]
        assert "boom" in result["error"]


class TestStepLimit:
    def test_exhaustion_sets_flag(self, tmp_path):
        # Client always wants another tool call: the loop must stop at the
        # limit and mark the run as truncated
        agent = make_agent(
            tmp_path,
            [
                FakeResponse(
                    FakeMessage(tool_calls=[FakeToolCall("echo", '{"text": "again"}')])
                )
            ],
        )
        messages, stats = run_agent(agent, "go", quiet=True, step_limit=3)
        assert stats["step_limit_reached"] is True
        assert stats["tool_usage"] == {"echo": 3}
        assert get_final_response(messages) is None

    def test_normal_finish_has_no_flag(self, tmp_path):
        agent = make_agent(tmp_path, [FakeResponse(FakeMessage("done"))])
        _, stats = run_agent(agent, "go", quiet=True, step_limit=3)
        assert "step_limit_reached" not in stats


class TestEmptyChoicesRetry:
    def test_transient_error_body_is_retried(self, tmp_path, monkeypatch):
        # Two error bodies, then a real answer: the loop must retry through
        # them instead of treating the error as a normal completion
        sleeps = []
        monkeypatch.setattr(agent_module.time, "sleep", sleeps.append)
        agent = make_agent(
            tmp_path,
            [
                FakeErrorResponse({"message": "Internal Server Error", "code": 500}),
                FakeErrorResponse({"message": "Internal Server Error", "code": 500}),
                FakeResponse(FakeMessage("done")),
            ],
        )
        messages, _ = run_agent(agent, "go", quiet=True)
        assert get_final_response(messages) == "done"
        assert agent.llm_config.client.calls == 3
        assert sleeps == [5, 10]

    def test_persistent_error_body_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_module.time, "sleep", lambda s: None)
        agent = make_agent(
            tmp_path,
            [FakeErrorResponse({"message": "Internal Server Error", "code": 500})],
        )
        with pytest.raises(RuntimeError, match="Internal Server Error"):
            run_agent(agent, "go", quiet=True)
        assert agent.llm_config.client.calls == 4  # 1 initial + 3 retries

    def test_empty_choices_without_error_field_raises(self, tmp_path, monkeypatch):
        # No error field in the body: still not a valid completion
        monkeypatch.setattr(agent_module.time, "sleep", lambda s: None)
        agent = make_agent(tmp_path, [FakeErrorResponse()])
        with pytest.raises(RuntimeError, match="no choices"):
            run_agent(agent, "go", quiet=True)

    def test_error_finish_reason_is_retried(self, tmp_path, monkeypatch):
        # A present choice with finish_reason "error" is an error envelope,
        # not a final answer
        sleeps = []
        monkeypatch.setattr(agent_module.time, "sleep", sleeps.append)
        agent = make_agent(
            tmp_path,
            [
                FakeErrorFinishResponse({"message": "Provider error", "code": 502}),
                FakeResponse(FakeMessage("done")),
            ],
        )
        messages, _ = run_agent(agent, "go", quiet=True)
        assert get_final_response(messages) == "done"
        assert agent.llm_config.client.calls == 2
        assert sleeps == [5]

    def test_persistent_error_finish_reason_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_module.time, "sleep", lambda s: None)
        agent = make_agent(
            tmp_path,
            [FakeErrorFinishResponse({"message": "Provider error", "code": 502})],
        )
        with pytest.raises(RuntimeError, match="Provider error"):
            run_agent(agent, "go", quiet=True)
        assert agent.llm_config.client.calls == 4


class TestConversationLogStatus:
    def test_success_status(self, tmp_path):
        log_path = save_conversation_log(tmp_path, [], stats={})
        events = [json.loads(line) for line in log_path.read_text().splitlines()]
        complete = [e for e in events if e["event"] == "complete"][0]
        assert complete["status"] == "success"

    def test_step_limit_status(self, tmp_path):
        log_path = save_conversation_log(
            tmp_path, [], stats={"step_limit_reached": True}
        )
        events = [json.loads(line) for line in log_path.read_text().splitlines()]
        complete = [e for e in events if e["event"] == "complete"][0]
        assert complete["status"] == "step_limit_reached"


def _tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


# A fixed run_agent-style message list (dicts only) covering every event kind
_LOG_MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "task"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            _tool_call("c1", "python_exec", json.dumps({"code": "print(6 * 7)"})),
            _tool_call(
                "c2", "save_code", json.dumps({"code": "x = 1\n", "filename": "s.py"})
            ),
            _tool_call(
                "c3",
                "todo_write",
                json.dumps(
                    {
                        "todos": [
                            {"content": "a", "status": "done"},
                            {"content": "b", "status": "pending", "id": "2"},
                        ]
                    }
                ),
            ),
            _tool_call("c4", "other_tool", "not json"),
            _tool_call("c5", "python_exec", None),
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps({"success": True, "stdout": "42\n"}),
    },
    {
        "role": "tool",
        "tool_call_id": "c2",
        "content": json.dumps({"success": False, "error": "disk full"}),
    },
    {"role": "tool", "tool_call_id": "c3", "content": "Todo list updated"},
    {
        "role": "tool",
        "tool_call_id": "c4",
        "content": json.dumps({"error": "Unknown tool: other_tool"}),
    },
    {"role": "tool", "tool_call_id": "c5", "content": json.dumps({"success": False})},
    {"role": "tool", "tool_call_id": "c6", "content": "42"},
    {"role": "tool", "tool_call_id": "c7", "content": None},
    {"role": "assistant", "content": "The answer is 42."},
]

_LOG_STATS = {
    "tool_usage": {"python_exec": 2, "save_code": 1},
    "token_consumption": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    "execution_time_seconds": 1.5,
    "step_limit_reached": False,
}

# Expected lines, recorded from the log writer before its object-message
# branch was removed (the JSONL format is a public contract)
_LOG_BODY = [
    '{"event": "python_exec", "code_length": 12}',
    '{"event": "save_code", "code_length": 6}',
    '{"event": "todo", "action": "update", "count": 2, "tasks": [{"content": "a",'
    ' "status": "done"}, {"content": "b", "status": "pending"}]}',
    '{"event": "tool_call", "tool": "other_tool"}',
    '{"event": "python_exec", "code_length": 0}',
    '{"event": "tool_response", "success": true, "error": null}',
    '{"event": "tool_response", "success": false, "error": "disk full"}',
    '{"event": "tool_response", "success": false, "error": null}',
]
_LOG_STATISTICS = (
    '{"event": "statistics", "tool_usage": {"python_exec": 2, "save_code": 1},'
    ' "tokens": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},'
    ' "execution_time": 1.5}'
)


class TestConversationLogGolden:
    """save_conversation_log output is byte-identical to the recorded format."""

    @staticmethod
    def _expected(task, statistics, status):
        lines = [f'{{"event": "start", "task": "{task}"}}', *_LOG_BODY]
        if statistics:
            lines.append(_LOG_STATISTICS)
        lines.append(f'{{"event": "complete", "status": "{status}"}}')
        return ("\n".join(lines) + "\n").encode()

    def test_with_stats_and_basename(self, tmp_path):
        log_path = save_conversation_log(tmp_path, _LOG_MESSAGES, _LOG_STATS, "golden")
        assert log_path == tmp_path / "golden.jsonl"
        assert log_path.read_bytes() == self._expected("golden", True, "success")

    def test_without_stats_or_basename(self, tmp_path):
        log_path = save_conversation_log(tmp_path, _LOG_MESSAGES)
        assert log_path == tmp_path / "log.jsonl"
        assert log_path.read_bytes() == self._expected("inline", False, "success")

    def test_step_limit(self, tmp_path):
        stats = {**_LOG_STATS, "step_limit_reached": True}
        log_path = save_conversation_log(tmp_path, _LOG_MESSAGES, stats, "lim")
        assert log_path.read_bytes() == self._expected(
            "lim", True, "step_limit_reached"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
