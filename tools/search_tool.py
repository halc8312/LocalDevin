"""Codebase semantic search tool backed by ChromaDB."""

import logging

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)


class SearchTool(BaseTool):
    """Perform semantic search over an indexed codebase.

    Delegates to ``memory.codebase_index.CodebaseIndex`` which uses
    tree-sitter + sentence-transformers + ChromaDB under the hood.
    """

    name = "search"
    description = "Semantically search the indexed codebase for relevant code."

    def __init__(self, codebase_index: object) -> None:
        """Initialise the tool.

        Args:
            codebase_index: An instance of
                ``memory.codebase_index.CodebaseIndex``.
        """
        self._index = codebase_index

    async def execute(
        self, query: str = "", n_results: int = 10, **kwargs: object
    ) -> ToolResult:
        """Search the codebase for code relevant to ``query``.

        Args:
            query: Natural language search query.
            n_results: Maximum number of results to return.
            **kwargs: Ignored extra arguments.

        Returns:
            ToolResult with formatted search results as output.
        """
        if not query:
            return self._error("No query provided", ["Provide a 'query' argument."])
        try:
            results: list[dict[str, object]] = await self._index.search(  # type: ignore[attr-defined]
                query=query, n=n_results
            )
            if not results:
                return self._success("No results found.")
            lines: list[str] = []
            for i, r in enumerate(results, start=1):
                lines.append(
                    f"[{i}] {r.get('file', '?')} "
                    f"({r.get('name', '')}) "
                    f"score={r.get('score', 0):.3f}\n"
                    f"{r.get('snippet', '')}\n"
                )
            return self._success("\n".join(lines))
        except Exception as exc:
            return self._error(str(exc))
