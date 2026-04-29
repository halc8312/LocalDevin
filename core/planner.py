"""DAG-based planning engine."""

import json
import logging
import re
from pathlib import Path

from config.settings import Settings
from core.models import Plan, PlanStep, SessionStatus, StepSize, ToolType

logger = logging.getLogger(__name__)

_TOOL_MAP: dict[str, ToolType] = {t.value: t for t in ToolType}
_SIZE_MAP: dict[str, StepSize] = {s.value: s for s in StepSize}

MAX_PARSE_RETRIES = 3


def _load_prompt(name: str) -> str:
    """Load a prompt file from config/prompts/.

    Args:
        name: Filename without path (e.g. ``planning_system.md``).

    Returns:
        File contents as a string.
    """
    prompt_path = Path(__file__).parent.parent / "config" / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def _validate_dag(steps: list[PlanStep]) -> None:
    """Validate that plan steps form a valid DAG (no cycles).

    Args:
        steps: List of plan steps to validate.

    Raises:
        ValueError: If a cycle or invalid dependency is detected.
    """
    ids = {s.id for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in ids:
                raise ValueError(
                    f"Step '{step.id}' depends on unknown step '{dep}'"
                )

    # Kahn's algorithm for cycle detection
    in_degree: dict[str, int] = {s.id: 0 for s in steps}
    adjacency: dict[str, list[str]] = {s.id: [] for s in steps}
    for step in steps:
        for dep in step.depends_on:
            adjacency[dep].append(step.id)
            in_degree[step.id] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbour in adjacency[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    if visited != len(steps):
        raise ValueError("Plan contains a cyclic dependency")


def _parse_plan(raw: str) -> Plan:
    """Parse raw JSON string into a Plan model.

    Args:
        raw: Raw JSON string from the LLM.

    Returns:
        Parsed Plan instance.

    Raises:
        ValueError: If parsing or validation fails.
    """
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw.strip()

    data = json.loads(json_str)
    steps: list[PlanStep] = []
    for raw_step in data.get("steps", []):
        tools = [_TOOL_MAP.get(t, ToolType.SHELL) for t in raw_step.get("tools", [])]
        size = _SIZE_MAP.get(raw_step.get("size", "medium"), StepSize.MEDIUM)
        steps.append(
            PlanStep(
                id=raw_step["id"],
                description=raw_step["description"],
                depends_on=raw_step.get("depends_on", []),
                tools=tools,
                size=size,
                status=SessionStatus.PENDING,
            )
        )
    plan = Plan(
        task_summary=data["task_summary"],
        completion_criteria=data.get("completion_criteria", []),
        steps=steps,
    )
    _validate_dag(plan.steps)
    return plan


class Planner:
    """DAG-based planning engine.

    Converts a natural language task into a structured execution plan
    with validated dependencies.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise the Planner.

        Args:
            settings: Application settings.
            llm_client: LLM client instance (``llm.client.LLMClient``).
        """
        self._settings = settings
        self._llm = llm_client
        self._system_prompt = _load_prompt("planning_system.md")

    async def create_plan(self, task: str, context: dict[str, object] | None = None) -> Plan:
        """Create an execution plan for the given task.

        Args:
            task: Natural language task description.
            context: Optional extra context (knowledge items, skill files, etc.).

        Returns:
            A validated Plan with DAG dependencies.

        Raises:
            RuntimeError: If plan generation fails after all retries.
        """
        context = context or {}
        extra = self._build_context_block(context)
        user_message = f"{task}\n\n{extra}".strip()

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_error: Exception | None = None
        for attempt in range(1, MAX_PARSE_RETRIES + 1):
            try:
                raw = await self._llm.chat(  # type: ignore[attr-defined]
                    messages=messages,
                    model=self._settings.main_model,
                    temperature=self._settings.temperature,
                )
                plan = _parse_plan(raw)
                logger.info(
                    "Plan created with %d steps (attempt %d)", len(plan.steps), attempt
                )
                return plan
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                last_error = exc
                logger.warning("Plan parse attempt %d failed: %s", attempt, exc)
                messages.append({"role": "assistant", "content": raw})  # type: ignore[possibly-undefined]
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Parse error: {exc}. "
                            "Please output valid JSON matching the required schema."
                        ),
                    }
                )

        raise RuntimeError(
            f"Plan generation failed after {MAX_PARSE_RETRIES} attempts: {last_error}"
        )

    def _build_context_block(self, context: dict[str, object]) -> str:
        """Build an additional context string to append to the user message.

        Args:
            context: Dictionary that may contain ``knowledge``, ``skill``,
                and ``playbook`` keys.

        Returns:
            Formatted context block string.
        """
        parts: list[str] = []
        if knowledge := context.get("knowledge"):
            parts.append(f"## Related Knowledge\n{knowledge}")
        if skill := context.get("skill"):
            parts.append(f"## SKILL.md\n{skill}")
        if playbook := context.get("playbook"):
            parts.append(f"## Playbook\n{playbook}")
        if search_results := context.get("search_results"):
            parts.append(f"## Code Search Results\n{search_results}")
        return "\n\n".join(parts)
