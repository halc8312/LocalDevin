"""Tests for review/pr_reviewer.py."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from config.settings import Settings
from review.pr_reviewer import PRReviewer, _parse_review


VALID_REVIEW_JSON = json.dumps({
    "summary": "Minor issues found",
    "issues": [
        {
            "category": "Informational",
            "file": "src/auth.py",
            "line": 10,
            "description": "Variable name is not descriptive",
            "suggestion": "Rename 'x' to 'user_id'",
        }
    ],
    "approved": True,
})

SEVERE_REVIEW_JSON = json.dumps({
    "summary": "Critical security issue",
    "issues": [
        {
            "category": "Severe Bug",
            "file": "src/db.py",
            "line": 42,
            "description": "SQL injection vulnerability",
            "suggestion": "Use parameterised queries",
        }
    ],
    "approved": False,
})


class TestParseReview:
    def test_parse_valid_review(self) -> None:
        result = _parse_review(VALID_REVIEW_JSON)
        assert result.summary == "Minor issues found"
        assert len(result.issues) == 1
        assert result.approved is True

    def test_parse_with_markdown_fences(self) -> None:
        fenced = f"```json\n{VALID_REVIEW_JSON}\n```"
        result = _parse_review(fenced)
        assert result.approved is True

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_review("not json at all")


class TestPRReviewer:
    @pytest.mark.asyncio
    async def test_review_no_diff(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        reviewer = PRReviewer(settings=settings, llm_client=mock_llm)
        with patch.object(reviewer, "_get_diff", return_value=""):
            result = await reviewer.review(repo_path=".", branch="main")
        assert result.approved is True
        assert "No changes" in result.summary
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_review_with_diff(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{VALID_REVIEW_JSON}\n```"
        reviewer = PRReviewer(settings=settings, llm_client=mock_llm)
        with patch.object(reviewer, "_get_diff", return_value="diff --git a/x b/x"):
            result = await reviewer.review(repo_path=".", branch="main")
        assert result.summary == "Minor issues found"
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_review_detects_severe_bug(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{SEVERE_REVIEW_JSON}\n```"
        reviewer = PRReviewer(settings=settings, llm_client=mock_llm)
        with patch.object(reviewer, "_get_diff", return_value="some diff"):
            result = await reviewer.review(repo_path=".", branch="main")
        severe = [i for i in result.issues if i.category == "Severe Bug"]
        assert len(severe) == 1
        assert result.approved is False
