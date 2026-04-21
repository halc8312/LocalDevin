"""Tests for memory/knowledge_base.py."""

import tempfile
from pathlib import Path

import pytest

from core.models import KnowledgeItem
from memory.knowledge_base import KnowledgeBase


class TestKnowledgeBase:
    def _make_kb(self, tmp_dir: str) -> KnowledgeBase:
        return KnowledgeBase(
            knowledge_dir=tmp_dir,
            chroma_path=f"{tmp_dir}/chroma",
        )

    def test_load_all_empty_directory(self, tmp_path: Path) -> None:
        kb = self._make_kb(str(tmp_path))
        items = kb.load_all()
        assert items == []

    def test_load_markdown_files(self, tmp_path: Path) -> None:
        (tmp_path / "test-knowledge.md").write_text("# Test\nContent here")
        triggers = "triggers:\n  test-knowledge: 'test trigger phrase'\n"
        (tmp_path / "triggers.yaml").write_text(triggers)
        kb = self._make_kb(str(tmp_path))
        items = kb.load_all()
        assert len(items) == 1
        assert items[0].name == "test-knowledge"
        assert items[0].trigger == "test trigger phrase"
        assert "Content here" in items[0].content

    def test_suggest_new_from_failures(self, tmp_path: Path) -> None:
        kb = self._make_kb(str(tmp_path))
        history = [
            {
                "event_type": "step_failed",
                "data": {"error": "ModuleNotFoundError: stripe"},
            },
            {"event_type": "step_completed", "data": {}},
        ]
        suggestions = kb.suggest_new(history)
        assert len(suggestions) >= 1
        assert any("stripe" in s.lower() or "ModuleNotFoundError" in s for s in suggestions)

    def test_get_relevant_without_chromadb(self, tmp_path: Path) -> None:
        (tmp_path / "stripe.md").write_text("# Stripe\nPayment setup")
        (tmp_path / "triggers.yaml").write_text(
            "triggers:\n  stripe: 'Stripe payment integration'\n"
        )
        kb = self._make_kb(str(tmp_path))
        kb.load_all()
        # Even without ChromaDB, it should fall back gracefully
        results = kb.get_relevant("payment integration")
        # Results may be empty (no ChromaDB) or populated – should not raise
        assert isinstance(results, list)
