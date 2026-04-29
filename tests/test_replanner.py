"""Tests for core/replanner.py."""

import json
import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from core.models import Plan, PlanStep, ReplanDecision, StepSize, ToolType
from core.replanner import Replanner


def make_step(step_id: str) -> PlanStep:
    return PlanStep(
        id=step_id,
        description=f"Step {step_id}",
        tools=[ToolType.SHELL],
        size=StepSize.SMALL,
    )


REPLAN_FIX_JSON = json.dumps({
    "original_step": "step_1",
    "error": "npm install failed",
    "decision": "fix",
    "reasoning": "Version conflict",
    "revised_plan": [
        {
            "id": "step_1a",
            "description": "Check versions",
            "depends_on": [],
            "tools": ["shell"],
            "size": "small",
        }
    ],
})

REPLAN_SKIP_JSON = json.dumps({
    "original_step": "step_1",
    "error": "pre-existing test failure",
    "decision": "skip_and_log",
    "reasoning": "Unrelated to our changes",
    "revised_plan": [],
})


class TestReplanner:
    @pytest.mark.asyncio
    async def test_fix_decision_inserts_steps(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REPLAN_FIX_JSON}\n```"
        replanner = Replanner(settings=settings, llm_client=mock_llm)

        plan = Plan(
            task_summary="Test",
            completion_criteria=[],
            steps=[make_step("step_1"), make_step("step_2")],
        )
        action = await replanner.handle_error(
            error="npm install failed", plan=plan, history=[]
        )
        assert action.decision == ReplanDecision.FIX
        assert any(s.id == "step_1a" for s in plan.steps)

    @pytest.mark.asyncio
    async def test_skip_and_log_decision(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REPLAN_SKIP_JSON}\n```"
        replanner = Replanner(settings=settings, llm_client=mock_llm)

        plan = Plan(
            task_summary="Test",
            completion_criteria=[],
            steps=[make_step("step_1")],
        )
        action = await replanner.handle_error(
            error="pre-existing failure", plan=plan, history=[]
        )
        assert action.decision == ReplanDecision.SKIP_AND_LOG

    @pytest.mark.asyncio
    async def test_max_replan_count_exceeded(self, settings: Settings) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = f"```json\n{REPLAN_FIX_JSON}\n```"
        replanner = Replanner(settings=settings, llm_client=mock_llm)
        replanner._replan_count = 5  # Already at max

        plan = Plan(task_summary="Test", completion_criteria=[], steps=[])
        with pytest.raises(RuntimeError, match="Maximum replan count"):
            await replanner.handle_error(error="error", plan=plan, history=[])
