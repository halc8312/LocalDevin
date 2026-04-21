"""Shared pytest fixtures for LocalDevin tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Return a test Settings instance with safe defaults."""
    return Settings(
        ollama_base_url="http://localhost:11434",
        main_model="qwen3.6:35b-a3b-q4_K_M",
        fast_model="qwen3.5:9b",
        db_path=":memory:",
        chroma_path="/tmp/test_chroma",
        github_token="",
        slack_bot_token="",
    )


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """Return an async mock LLM client with a default plan response."""
    client = AsyncMock()
    client.chat.return_value = (
        '```json\n'
        '{"task_summary": "Test task", '
        '"completion_criteria": ["Tests pass"], '
        '"steps": ['
        '{"id": "step_1", "description": "Investigate", '
        '"depends_on": [], "tools": ["shell"], "size": "small"}'
        ']}\n```'
    )
    return client


@pytest.fixture
def mock_session_store() -> AsyncMock:
    """Return an async mock session store."""
    store = AsyncMock()
    store.create_session.return_value = "test-session-id"
    store.get_session_history.return_value = []
    store.get_recent_sessions.return_value = []
    return store


@pytest.fixture
def mock_tool_router() -> AsyncMock:
    """Return an async mock tool router."""
    from core.models import ToolResult

    router = AsyncMock()
    router.execute.return_value = ToolResult(success=True, output="mock output")
    return router
