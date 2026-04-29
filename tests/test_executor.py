"""Tests for core/executor.py."""

import json
import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from core.executor import Executor, _topological_sort
from core.models import Plan, PlanStep, StepSize, ToolType, SessionStatus


def make_step(step_id: str, depends_on: list[str] | None = None) -> PlanStep:
    return PlanStep(
        id=step_id,
        description=f"Step {step_id}",
        depends_on=depends_on or [],
        tools=[ToolType.SHELL],
        size=StepSize.SMALL,
    )


def make_plan(*step_ids: str) -> Plan:
    return Plan(
        task_summary="Test",
        completion_criteria=["Done"],
        steps=[make_step(sid) for sid in step_ids],
    )


REACT_JSON = json.dumps({
    "think": "I need to run tests",
    "act": {"tool": "shell", "args": {"command": "pytest"}},
    "observe": "Tests passed",
    "next": "Done",
})


class TestTopologicalSort:
    def test_simple_chain(self) -> None:
        steps = [
            make_step("b", depends_on=["a"]),
            make_step("a"),
        ]
        ordered = _topological_sort(steps)
        ids = [s.id for s in ordered]
        assert ids.index("a") < ids.index("b")

    def test_no_dependencies(self) -> None:
        steps = [make_step("x"), make_step("y"), make_step("z")]
        ordered = _topological_sort(steps)
        assert len(ordered) == 3

    def test_diamond_dependency(self) -> None:
        steps = [
            make_step("d", depends_on=["b", "c"]),
            make_step("b", depends_on=["a"]),
            make_step("c", depends_on=["a"]),
            make_step("a"),
        ]
        ordered = _topological_sort(steps)
        ids = [s.id for s in ordered]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")


class TestExecutor:
    def _make_executor(self, settings: Settings, llm: object, store: object) -> Executor:
        from core.models import ToolResult

        router = AsyncMock()
        router.execute.return_value = ToolResult(success=True, output="ok")
        return Executor(
            settings=settings,
            llm_client=llm,
            tool_router=router,
            session_store=store,
        )

    @pytest.mark.asyncio
    async def test_execute_plan_success(
        self, settings: Settings, mock_session_store: AsyncMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REACT_JSON}\n```"
        executor = self._make_executor(settings, mock_llm, mock_session_store)
        plan = make_plan("step_1")
        history = await executor.execute_plan(plan=plan, session_id="sid")
        assert len(history) == 1
        assert history[0].step_id == "step_1"
        assert history[0].observe == "ok"

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips(
        self, settings: Settings, mock_session_store: AsyncMock
    ) -> None:
        from core.models import ToolResult

        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REACT_JSON}\n```"
        router = AsyncMock()
        router.execute.return_value = ToolResult(
            success=False, output="", error="Persistent failure"
        )
        executor = Executor(
            settings=settings,
            llm_client=mock_llm,
            tool_router=router,
            session_store=mock_session_store,
        )
        plan = Plan(
            task_summary="Test",
            completion_criteria=[],
            steps=[make_step(f"step_{i}") for i in range(5)],
        )
        with pytest.raises(RuntimeError, match="Circuit breaker"):
            await executor.execute_plan(plan=plan, session_id="sid")

    @pytest.mark.asyncio
    async def test_step_status_transitions(
        self, settings: Settings, mock_session_store: AsyncMock
    ) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REACT_JSON}\n```"
        from core.models import ToolResult

        router = AsyncMock()
        router.execute.return_value = ToolResult(success=True, output="ok")
        executor = Executor(
            settings=settings,
            llm_client=mock_llm,
            tool_router=router,
            session_store=mock_session_store,
        )
        plan = make_plan("step_1")
        await executor.execute_plan(plan=plan, session_id="sid")
        assert plan.steps[0].status == SessionStatus.COMPLETED
