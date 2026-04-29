"""Tests for tools/router.py."""

from unittest.mock import AsyncMock

import pytest

from core.models import ToolResult, ToolType
from tools.router import ToolRouter


class TestToolRouter:
    @pytest.mark.asyncio
    async def test_routes_search_tool(self) -> None:
        search_tool = AsyncMock()
        search_tool.execute.return_value = ToolResult(success=True, output="result")
        router = ToolRouter(tools={ToolType.SEARCH: search_tool})

        result = await router.execute(ToolType.SEARCH, query="planner")

        assert result.success is True
        search_tool.execute.assert_awaited_once_with(query="planner")

    @pytest.mark.asyncio
    async def test_routes_editor_read_with_action(self) -> None:
        editor_tool = AsyncMock()
        editor_tool.execute.return_value = ToolResult(success=True, output="content")
        router = ToolRouter(tools={ToolType.EDITOR_READ: editor_tool})

        await router.execute(ToolType.EDITOR_READ, path="README.md")

        editor_tool.execute.assert_awaited_once_with(action="read", path="README.md")

    @pytest.mark.asyncio
    async def test_records_tool_events(self) -> None:
        shell_tool = AsyncMock()
        shell_tool.execute.return_value = ToolResult(success=True, output="ok")
        store = AsyncMock()
        router = ToolRouter(tools={ToolType.SHELL: shell_tool}, session_store=store)

        await router.execute(ToolType.SHELL, session_id="sess-1", step_id="step-1", command="pwd")

        assert store.record_event.await_count == 2
        start_call = store.record_event.await_args_list[0]
        end_call = store.record_event.await_args_list[1]
        assert start_call.args[:3] == ("sess-1", "step-1", "tool_started")
        assert end_call.args[:3] == ("sess-1", "step-1", "tool_completed")

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        router = ToolRouter(tools={})

        result = await router.execute(ToolType.GIT)

        assert result.success is False
        assert result.error == "Unknown tool: git"
