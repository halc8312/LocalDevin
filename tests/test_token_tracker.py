"""Tests for llm/token_tracker.py."""

import pytest

from llm.token_tracker import TokenTracker, _classify_size


class TestClassifySize:
    def test_xs(self) -> None:
        assert _classify_size(5_000) == "XS"
        assert _classify_size(20_000) == "XS"

    def test_s(self) -> None:
        assert _classify_size(20_001) == "S"
        assert _classify_size(50_000) == "S"

    def test_m(self) -> None:
        assert _classify_size(50_001) == "M"
        assert _classify_size(100_000) == "M"

    def test_l(self) -> None:
        assert _classify_size(100_001) == "L"
        assert _classify_size(200_000) == "L"

    def test_xl(self) -> None:
        assert _classify_size(200_001) == "XL"
        assert _classify_size(1_000_000) == "XL"


class TestTokenTracker:
    def _make_tracker(self) -> TokenTracker:
        return TokenTracker(db_path=":memory:", max_session_tokens=500_000)

    @pytest.mark.asyncio
    async def test_record_and_get_session_total(self) -> None:
        tracker = self._make_tracker()
        await tracker.record("sess-1", "qwen3.6:35b", 1000, 500)
        await tracker.record("sess-1", "qwen3.6:35b", 200, 100)
        result = await tracker.get_session_total("sess-1")
        assert result["total_tokens"] == 1800
        assert result["prompt_tokens"] == 1200
        assert result["completion_tokens"] == 600
        assert result["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_get_session_total_empty(self) -> None:
        tracker = self._make_tracker()
        result = await tracker.get_session_total("nonexistent")
        assert result["total_tokens"] == 0
        assert result["size"] == "XS"

    @pytest.mark.asyncio
    async def test_get_daily_total(self) -> None:
        tracker = self._make_tracker()
        await tracker.record("sess-1", "model-a", 100, 50)
        await tracker.record("sess-2", "model-b", 200, 100)
        result = await tracker.get_daily_total()
        assert result["total_tokens"] == 450
        assert len(result["breakdown"]) == 2

    @pytest.mark.asyncio
    async def test_size_label_in_session_total(self) -> None:
        tracker = self._make_tracker()
        await tracker.record("sess-big", "model", 60_000, 0)
        result = await tracker.get_session_total("sess-big")
        assert result["size"] == "M"
