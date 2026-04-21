"""Tests for insights/session_analyzer.py."""

import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from core.models import SessionInsight
from insights.session_analyzer import (
    SessionAnalyzer,
    _classify_category,
    _classify_size,
)


class TestClassifySize:
    def test_xs(self) -> None:
        assert _classify_size(0) == "XS"
        assert _classify_size(20_000) == "XS"

    def test_xl(self) -> None:
        assert _classify_size(500_000) == "XL"


class TestClassifyCategory:
    def test_bug_fixing(self) -> None:
        assert _classify_category("Fix authentication bug") == "Bug Fixing"

    def test_feature_development(self) -> None:
        assert _classify_category("Implement new payment feature") == "Feature Development"

    def test_test_generation(self) -> None:
        assert _classify_category("Add pytest coverage for auth module") == "Test Generation"

    def test_general_fallback(self) -> None:
        assert _classify_category("Something completely unrelated") == "General"


class TestSessionAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_empty_history(self, settings: Settings) -> None:
        mock_store = AsyncMock()
        mock_store.get_session_history.return_value = []
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "Better prompt here"

        analyzer = SessionAnalyzer(
            settings=settings, session_store=mock_store, llm_client=mock_llm
        )
        insight = await analyzer.analyze("test-session-id")
        assert isinstance(insight, SessionInsight)
        assert insight.session_id == "test-session-id"
        assert insight.total_tokens == 0
        assert insight.session_size == "XS"

    @pytest.mark.asyncio
    async def test_analyze_detects_retry_loop(self, settings: Settings) -> None:
        mock_store = AsyncMock()
        mock_store.get_session_history.return_value = [
            {"event_type": "step_failed", "step_id": f"step_{i}", "data": {"error": "err"}}
            for i in range(5)
        ]
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "Improved prompt"

        analyzer = SessionAnalyzer(
            settings=settings, session_store=mock_store, llm_client=mock_llm
        )
        insight = await analyzer.analyze("test-session-id")
        assert any(i["type"] == "retry_loop" for i in insight.issues)

    @pytest.mark.asyncio
    async def test_analyze_generates_knowledge_suggestions(self, settings: Settings) -> None:
        mock_store = AsyncMock()
        mock_store.get_session_history.return_value = [
            {
                "event_type": "step_failed",
                "step_id": "step_1",
                "data": {"error": "ModuleNotFoundError: stripe not found"},
            }
        ]
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "Improved"

        analyzer = SessionAnalyzer(
            settings=settings, session_store=mock_store, llm_client=mock_llm
        )
        insight = await analyzer.analyze("test-session-id")
        assert len(insight.knowledge_suggestions) >= 1
