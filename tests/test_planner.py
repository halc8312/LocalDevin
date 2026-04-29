"""Tests for core/planner.py."""

import json
import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from core.models import Plan, StepSize, ToolType
from core.planner import Planner, _validate_dag, _parse_plan


VALID_PLAN_JSON = json.dumps({
    "task_summary": "Add authentication",
    "completion_criteria": ["Users can log in", "JWT tokens are issued"],
    "steps": [
        {
            "id": "step_1",
            "description": "Inspect current auth code",
            "depends_on": [],
            "tools": ["shell"],
            "size": "small",
        },
        {
            "id": "step_2",
            "description": "Implement JWT",
            "depends_on": ["step_1"],
            "tools": ["editor_write"],
            "size": "medium",
        },
    ],
})


class TestParsePlan:
    def test_parse_valid_json(self) -> None:
        plan = _parse_plan(VALID_PLAN_JSON)
        assert plan.task_summary == "Add authentication"
        assert len(plan.steps) == 2
        assert plan.steps[0].id == "step_1"
        assert plan.steps[1].depends_on == ["step_1"]

    def test_parse_with_markdown_fences(self) -> None:
        fenced = f"```json\n{VALID_PLAN_JSON}\n```"
        plan = _parse_plan(fenced)
        assert len(plan.steps) == 2

    def test_parse_invalid_json_raises(self) -> None:
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_plan("not json")


class TestValidateDag:
    def test_valid_dag_passes(self) -> None:
        from core.models import PlanStep

        steps = [
            PlanStep(id="a", description="A", tools=[ToolType.SHELL], size=StepSize.SMALL),
            PlanStep(
                id="b",
                description="B",
                depends_on=["a"],
                tools=[ToolType.SHELL],
                size=StepSize.SMALL,
            ),
        ]
        _validate_dag(steps)  # Should not raise

    def test_cyclic_dependency_raises(self) -> None:
        from core.models import PlanStep

        steps = [
            PlanStep(
                id="a",
                description="A",
                depends_on=["b"],
                tools=[ToolType.SHELL],
                size=StepSize.SMALL,
            ),
            PlanStep(
                id="b",
                description="B",
                depends_on=["a"],
                tools=[ToolType.SHELL],
                size=StepSize.SMALL,
            ),
        ]
        with pytest.raises(ValueError, match="cyclic"):
            _validate_dag(steps)

    def test_unknown_dependency_raises(self) -> None:
        from core.models import PlanStep

        steps = [
            PlanStep(
                id="a",
                description="A",
                depends_on=["nonexistent"],
                tools=[ToolType.SHELL],
                size=StepSize.SMALL,
            ),
        ]
        with pytest.raises(ValueError, match="unknown"):
            _validate_dag(steps)


class TestPlanner:
    @pytest.mark.asyncio
    async def test_create_plan_success(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{VALID_PLAN_JSON}\n```"
        planner = Planner(settings=settings, llm_client=mock_llm)
        plan = await planner.create_plan("Add authentication")
        assert isinstance(plan, Plan)
        assert plan.task_summary == "Add authentication"

    @pytest.mark.asyncio
    async def test_create_plan_retries_on_parse_error(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = [
            "bad json",
            "still bad",
            f"```json\n{VALID_PLAN_JSON}\n```",
        ]
        planner = Planner(settings=settings, llm_client=mock_llm)
        plan = await planner.create_plan("Test task")
        assert plan.task_summary == "Add authentication"
        assert mock_llm.chat.call_count == 3

    @pytest.mark.asyncio
    async def test_create_plan_fails_after_max_retries(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "always bad json"
        planner = Planner(settings=settings, llm_client=mock_llm)
        with pytest.raises(RuntimeError, match="Plan generation failed"):
            await planner.create_plan("Test task")
