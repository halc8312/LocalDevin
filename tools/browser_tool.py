"""Web search and documentation browser tool."""

import logging

import httpx

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_HEADERS = {"User-Agent": "LocalDevin/0.1 (research bot)"}


class BrowserTool(BaseTool):
    """Fetch web pages and perform simple text extraction.

    Uses ``httpx`` for HTTP requests.  The raw HTML is returned stripped of
    most tags so the LLM can process it as plain text.
    """

    name = "browser"
    description = "Fetch a URL and return its text content for research."

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """Initialise the tool.

        Args:
            timeout: HTTP request timeout in seconds.
        """
        self._timeout = timeout

    async def execute(self, url: str = "", **kwargs: object) -> ToolResult:
        """Fetch a URL and return extracted text.

        Args:
            url: The URL to fetch.
            **kwargs: Ignored extra arguments.

        Returns:
            ToolResult with extracted page text as output.
        """
        if not url:
            return self._error("No URL provided", ["Provide a 'url' argument."])

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, timeout=self._timeout, follow_redirects=True
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return self._error(
                f"HTTP {exc.response.status_code}: {url}",
                [f"Check the URL is accessible: {url}"],
            )
        except httpx.RequestError as exc:
            return self._error(str(exc), [f"Network error fetching {url}"])

        text = self._extract_text(response.text)
        logger.debug("BrowserTool: fetched %d chars from %s", len(text), url)
        return self._success(text[:10_000])  # Truncate to avoid huge contexts

    def _extract_text(self, html: str) -> str:
        """Strip HTML tags and return plain text.

        Args:
            html: Raw HTML string.

        Returns:
            Plain text content.
        """
        import re

        # Remove script and style blocks
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove all remaining tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text
