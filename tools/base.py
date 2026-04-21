"""Base class for all LocalDevin tools."""

from abc import ABC, abstractmethod

from core.models import ToolResult


class BaseTool(ABC):
    """Abstract base class for all agent tools.

    Subclasses must define ``name``, ``description``, and implement
    the ``execute`` coroutine.  All tools are designed to be idempotent –
    calling them multiple times with the same arguments should be safe.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    async def execute(self, **kwargs: object) -> ToolResult:
        """Execute the tool and return a structured result.

        Args:
            **kwargs: Tool-specific keyword arguments.

        Returns:
            A ToolResult describing success or failure.
        """

    def _success(self, output: str) -> ToolResult:
        """Convenience constructor for a successful result.

        Args:
            output: The tool output string.

        Returns:
            ToolResult with ``success=True``.
        """
        return ToolResult(success=True, output=output)

    def _error(self, error: str, suggestions: list[str] | None = None) -> ToolResult:
        """Convenience constructor for a failed result.

        Args:
            error: Description of the error.
            suggestions: Optional list of remediation hints.

        Returns:
            ToolResult with ``success=False``.
        """
        return ToolResult(
            success=False,
            output="",
            error=error,
            suggestions=suggestions or [],
        )
