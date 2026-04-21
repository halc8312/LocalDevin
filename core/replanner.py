"""Dynamic replanning logic."""

import json
import logging
import re
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from config.settings import Settings
from core.models import (
    Plan,
    PlanStep,
    ReActStep,
    ReplanAction,
    ReplanDecision,
    SessionStatus,
    StepSize,
    ToolType,
)

logger = logging.getLogger(__name__)
console = Console()

MAX_REPLAN_COUNT = 5


def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent.parent / "config" / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def _parse_replan(raw: str) -> ReplanAction:
    """Parse a replanning JSON response from the LLM.

    Args:
        raw: Raw string from the LLM.

    Returns:
        A ReplanAction instance.

    Raises:
        ValueError: If parsing fails.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw.strip()
    data = json.loads(json_str)

    revised: list[PlanStep] = []
    for raw_step in data.get("revised_plan", []):
        tools = [
            ToolType(t) for t in raw_step.get("tools", [ToolType.SHELL.value])
        ]
        revised.append(
            PlanStep(
                id=raw_step["id"],
                description=raw_step["description"],
                depends_on=raw_step.get("depends_on", []),
                tools=tools,
                size=StepSize(raw_step.get("size", "medium")),
                status=SessionStatus.PENDING,
            )
        )

    return ReplanAction(
        original_step=data.get("original_step", ""),
        error=data.get("error", ""),
        decision=ReplanDecision(data.get("decision", ReplanDecision.ESCALATE.value)),
        reasoning=data.get("reasoning", ""),
        revised_steps=revised,
    )


class Replanner:
    """Dynamic replanning logic invoked after execution failures.

    Analyses the error, current plan, and history, then decides
    whether to investigate, fix, skip, or escalate.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise the Replanner.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
        """
        self._settings = settings
        self._llm = llm_client
        self._system_prompt = _load_prompt("replan_system.md")
        self._replan_count = 0

    async def handle_error(
        self,
        error: str,
        plan: Plan,
        history: list[ReActStep],
    ) -> ReplanAction:
        """Decide how to handle a step failure and modify the plan if needed.

        Args:
            error: The error message that triggered replanning.
            plan: The current execution plan.
            history: Completed ReAct steps so far.

        Returns:
            A ReplanAction describing the decision and any revised steps.

        Raises:
            RuntimeError: If the maximum replan count is exceeded.
        """
        self._replan_count += 1
        if self._replan_count > MAX_REPLAN_COUNT:
            logger.error("Maximum replan count (%d) exceeded", MAX_REPLAN_COUNT)
            raise RuntimeError(
                f"Maximum replan count ({MAX_REPLAN_COUNT}) exceeded. "
                "Forcing escalation."
            )

        history_summary = "\n".join(
            f"[{s.step_id}] think={s.think[:80]}... observe={s.observe[:80]}..."
            for s in history[-10:]
        )
        user_content = (
            f"Error: {error}\n\n"
            f"Current plan steps: {[s.id for s in plan.steps]}\n\n"
            f"Recent history:\n{history_summary}"
        )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.main_model,
                temperature=self._settings.temperature,
            )
            action = _parse_replan(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Replan parse failed: %s – defaulting to escalate", exc)
            action = ReplanAction(
                original_step="unknown",
                error=error,
                decision=ReplanDecision.ESCALATE,
                reasoning=f"Could not parse replan response: {exc}",
            )

        console.print(
            f"[bold magenta]🔄 Replan decision:[/bold magenta] "
            f"{action.decision.value} — {action.reasoning}"
        )

        if action.decision == ReplanDecision.ESCALATE:
            user_input = Prompt.ask(
                "[red]Escalation required. How should we proceed?[/red]",
                default="abort",
            )
            if user_input.strip().lower() == "abort":
                raise RuntimeError(f"User aborted after escalation: {error}")
            # User provided guidance – treat as skip and continue
            action.decision = ReplanDecision.SKIP_AND_LOG

        if action.decision == ReplanDecision.FIX and action.revised_steps:
            self._insert_revised_steps(plan, action)

        if action.decision == ReplanDecision.SKIP_AND_LOG:
            logger.info(
                "Skipping step '%s': %s", action.original_step, action.reasoning
            )

        return action

    def _insert_revised_steps(self, plan: Plan, action: ReplanAction) -> None:
        """Insert revised steps into the plan after the failed step.

        Args:
            plan: The plan to modify in place.
            action: The replanning action containing revised steps.
        """
        try:
            idx = next(
                i for i, s in enumerate(plan.steps) if s.id == action.original_step
            )
            # Replace the failed step with the revised steps
            plan.steps[idx : idx + 1] = action.revised_steps
        except StopIteration:
            # Step not found – append at end
            plan.steps.extend(action.revised_steps)
        logger.info(
            "Inserted %d revised steps into plan", len(action.revised_steps)
        )
