"""Regression tests for tool descriptions.

Tool-description quality directly drives agent performance (see
MEM_002_tool_description_quality). These tests pin the load-bearing phrases so
they cannot be silently dropped when editing tools.py or mcp_server.py.
"""

import pytest

from agentic_python_coder.tools import (
    PYTHON_EXEC_TOOL,
    SAVE_CODE_TOOL,
    TODO_WRITE_TOOL,
)
from agentic_python_coder.mcp_server import list_tools


class TestAgentToolDescriptions:
    def test_all_tools_document_args_and_returns(self):
        for tool in (PYTHON_EXEC_TOOL, SAVE_CODE_TOOL, TODO_WRITE_TOOL):
            assert "Args:" in tool.description, tool.name
            assert "Returns:" in tool.description, tool.name

    def test_python_exec_statefulness_warning(self):
        desc = PYTHON_EXEC_TOOL.description
        assert "The kernel maintains state between executions" in desc
        assert "persist across calls" in desc
        # Worked examples (few-shot) are part of the contract
        assert "First call:" in desc
        assert "Second call:" in desc

    def test_save_code_verification_requirement(self):
        desc = SAVE_CODE_TOOL.description
        assert "Only call this AFTER" in desc
        assert "verification" in desc
        assert "Do NOT save unverified code" in desc

    def test_save_code_mentions_syntax_check(self):
        desc = SAVE_CODE_TOOL.description
        assert "syntax-checked before saving" in desc
        assert "nothing is" in desc and "written" in desc

    def test_openai_format_carries_description(self):
        openai_tool = PYTHON_EXEC_TOOL.to_openai_tool()
        assert openai_tool["function"]["description"] == PYTHON_EXEC_TOOL.description
        assert openai_tool["function"]["parameters"]["required"] == ["code"]


class TestMCPToolDescriptions:
    @pytest.mark.asyncio
    async def test_python_exec_description(self):
        tools = {t.name: t for t in await list_tools()}
        desc = tools["python_exec"].description
        assert "persistent" in desc
        assert "State persists" in desc

    @pytest.mark.asyncio
    async def test_submit_code_contract(self):
        tools = {t.name: t for t in await list_tools()}
        desc = tools["submit_code"].description
        assert "final, verified, self-contained" in desc
        assert "verification passed" in desc
        assert "NOT executed" in desc
        assert "NOT written to disk" in desc

    @pytest.mark.asyncio
    async def test_every_tool_has_nonempty_schema(self):
        for tool in await list_tools():
            assert tool.description.strip(), tool.name
            assert tool.inputSchema.get("type") == "object", tool.name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
