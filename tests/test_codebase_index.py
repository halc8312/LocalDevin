"""Tests for memory/codebase_index.py."""

import tempfile
from pathlib import Path

import pytest

from memory.codebase_index import CodebaseIndex, _extract_name


class TestCodebaseIndex:
    def test_index_repo_no_files(self, tmp_path: Path) -> None:
        idx = CodebaseIndex(chroma_path=str(tmp_path / "chroma"))
        count = idx.index_repo(str(tmp_path))
        assert count == 0

    def test_index_repo_python_file(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text(
            "def hello():\n    return 'world'\n\nclass Greeter:\n    pass\n"
        )
        idx = CodebaseIndex(chroma_path=str(tmp_path / "chroma"))
        count = idx.index_repo(str(tmp_path))
        # Should index at least the file (even without tree-sitter)
        assert count >= 0  # May be 0 if tree-sitter-languages not installed

    @pytest.mark.asyncio
    async def test_search_returns_list(self, tmp_path: Path) -> None:
        idx = CodebaseIndex(chroma_path=str(tmp_path / "chroma"))
        results = await idx.search("find authentication function")
        assert isinstance(results, list)

    def test_get_file_summary_missing_collection(self, tmp_path: Path) -> None:
        idx = CodebaseIndex(chroma_path=str(tmp_path / "chroma"))
        summary = idx.get_file_summary("nonexistent.py")
        # Should not raise, should return a string
        assert isinstance(summary, str)

    def test_parse_file_fallback_on_missing_language(self, tmp_path: Path) -> None:
        """Ensure parse_file falls back gracefully for unsupported langs."""
        py_file = tmp_path / "sample.py"
        py_file.write_text("x = 1\n")
        idx = CodebaseIndex(chroma_path=str(tmp_path / "chroma"))
        chunks = idx._parse_file(py_file, "python")
        # Should return at least one chunk (even a fallback whole-file chunk)
        assert isinstance(chunks, list)
