"""Central tool router for LocalDevin runtime execution."""

from typing import Protocol

from core.models import ToolResult, ToolType


class SessionEventStore(Protocol):
    """Protocol for session event recording used by the tool router."""

    async def record_event(
        self,
        session_id: str,
        step_id: str,
        event_type: str,
        data: object,
    ) -> None:
        """Persist a session event."""


class ToolRouter:
    """Route tool requests to concrete tool instances."""

    def __init__(
        self,
        tools: dict[ToolType, object],
        named_tools: dict[str, object] | None = None,
        session_store: SessionEventStore | None = None,
    ) -> None:
        """Initialise the tool router.

        Args:
            tools: Mapping of tool types to tool instances.
            named_tools: Optional mapping for direct named lookup.
            session_store: Optional session store for tool event recording.
        """
        self._tools = tools
        self._named_tools = named_tools or {}
        self._store = session_store

    async def execute(
        self,
        tool: ToolType,
        session_id: str | None = None,
        step_id: str = "",
        **kwargs: object,
    ) -> ToolResult:
        """Execute a tool request.

        Args:
            tool: Tool identifier.
            session_id: Optional session ID for event recording.
            step_id: Optional plan step ID for event recording.
            **kwargs: Tool-specific arguments.

        Returns:
            Tool execution result.
        """
        tool_instance = self._tools.get(tool)
        if tool_instance is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {tool.value}",
                suggestions=[t.value for t in sorted(self._tools, key=lambda item: item.value)],
            )

        await self._record_event(
            session_id=session_id,
            step_id=step_id,
            event_type="tool_started",
            data={"tool": tool.value, "args": kwargs},
        )

        if tool is ToolType.EDITOR_READ:
            result = await tool_instance.execute(action="read", **kwargs)  # type: ignore[attr-defined]
        elif tool is ToolType.EDITOR_WRITE:
            result = await tool_instance.execute(action="write", **kwargs)  # type: ignore[attr-defined]
        else:
            result = await tool_instance.execute(**kwargs)  # type: ignore[attr-defined]

        await self._record_event(
            session_id=session_id,
            step_id=step_id,
            event_type="tool_completed" if result.success else "tool_failed",
            data={
                "tool": tool.value,
                "success": result.success,
                "output": result.output[:1000],
                "error": result.error,
            },
        )
        return result

    def get_tool(self, name: str) -> object | None:
        """Return a named tool instance."""
        return self._named_tools.get(name)

    async def _record_event(
        self,
        session_id: str | None,
        step_id: str,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        """Record a session event when a store is available."""
        if session_id is None or self._store is None:
            return
        try:
            await self._store.record_event(session_id, step_id, event_type, data)
        except Exception:
            return
