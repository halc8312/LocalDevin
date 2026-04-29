"""ReAct-loop execution engine."""

import json
import logging
import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from config.settings import Settings
from core.models import Plan, PlanStep, ReActStep, SessionStatus, ToolCall, ToolType

logger = logging.getLogger(__name__)
console = Console()

MAX_PARSE_RETRIES = 3


def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent.parent / "config" / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
    """Return steps in topological order respecting ``depends_on``.

    Args:
        steps: List of plan steps (may be in any order).

    Returns:
        Steps ordered so every dependency comes before the step that needs it.
    """
    index = {s.id: s for s in steps}
    visited: set[str] = set()
    result: list[PlanStep] = []

    def visit(step: PlanStep) -> None:
        if step.id in visited:
            return
        visited.add(step.id)
        for dep_id in step.depends_on:
            if dep_id in index:
                visit(index[dep_id])
        result.append(step)

    for step in steps:
        visit(step)
    return result


def _parse_react(raw: str) -> tuple[str, ToolCall, str, str]:
    """Parse a ReAct JSON blob from the LLM response.

    Args:
        raw: Raw string from the LLM.

    Returns:
        Tuple of (think, tool_call, observe, next_action).

    Raises:
        ValueError: If parsing fails.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw.strip()
    data = json.loads(json_str)
    act_data = data.get("act", {})
    tool_type = ToolType(act_data.get("tool", "shell"))
    tool_call = ToolCall(tool=tool_type, args=act_data.get("args", {}))
    return (
        data.get("think", ""),
        tool_call,
        data.get("observe", ""),
        data.get("next", ""),
    )


class Executor:
    """ReAct-loop execution engine.

    Executes a Plan by iterating over its steps in topological order,
    running a Think-Act-Observe loop for each step.
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: object,
        tool_router: object,
        session_store: object,
    ) -> None:
        """Initialise the Executor.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
            tool_router: Tool router for dispatching tool calls.
            session_store: Session store for recording events.
        """
        self._settings = settings
        self._llm = llm_client
        self._tool_router = tool_router
        self._store = session_store
        self._system_prompt = _load_prompt("execution_system.md")

    async def execute_plan(
        self,
        plan: Plan,
        session_id: str,
        on_error: object | None = None,
    ) -> list[ReActStep]:
        """Execute all steps of a plan using the ReAct loop.

        Args:
            plan: The plan to execute.
            session_id: Current session identifier.
            on_error: Optional async callable ``(error, plan, history) -> ReplanAction``
                invoked when the circuit breaker trips.

        Returns:
            List of completed ReActStep records.
        """
        ordered = _topological_sort(plan.steps)
        history: list[ReActStep] = []
        context_summary: str = ""
        consecutive_errors = 0

        for step in ordered:
            step.status = SessionStatus.EXECUTING
            console.rule(f"[bold cyan]Step: {step.id}[/bold cyan]")
            console.print(f"[dim]{step.description}[/dim]")

            try:
                react_step = await self._execute_step(
                    step=step,
                    session_id=session_id,
                    context_summary=context_summary,
                )
                step.status = SessionStatus.COMPLETED
                consecutive_errors = 0
                history.append(react_step)
                context_summary += f"\n[{step.id}] {react_step.observe}"
                await self._store.record_event(  # type: ignore[attr-defined]
                    session_id, step.id, "step_completed", react_step.model_dump()
                )
            except Exception as exc:
                consecutive_errors += 1
                step.status = SessionStatus.FAILED
                error_msg = str(exc)
                logger.error("Step %s failed: %s", step.id, error_msg)

                await self._store.record_event(  # type: ignore[attr-defined]
                    session_id, step.id, "step_failed", {"error": error_msg}
                )

                if consecutive_errors >= self._settings.max_consecutive_errors:
                    console.print(
                        Panel(
                            f"[red]Circuit breaker tripped after {consecutive_errors} "
                            f"consecutive errors.[/red]\nLast error: {error_msg}",
                            title="⚡ Circuit Breaker",
                        )
                    )
                    if on_error is not None:
                        await on_error(error_msg, plan, history)  # type: ignore[operator]
                    raise RuntimeError(
                        f"Circuit breaker tripped: {consecutive_errors} consecutive errors"
                    ) from exc

        return history

    async def _execute_step(
        self,
        step: PlanStep,
        session_id: str,
        context_summary: str,
    ) -> ReActStep:
        """Run the ReAct loop for a single plan step.

        Args:
            step: The plan step to execute.
            session_id: Current session identifier.
            context_summary: Accumulated observations from previous steps.

        Returns:
            A completed ReActStep.

        Raises:
            RuntimeError: If the step cannot be completed after retries.
        """
        user_content = (
            f"Execute step: {step.description}\n\n"
            f"Context so far:\n{context_summary or '(none)'}"
        )
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        last_error: Exception | None = None
        for attempt in range(1, MAX_PARSE_RETRIES + 1):
            try:
                raw = await self._llm.chat(  # type: ignore[attr-defined]
                    messages=messages,
                    model=self._settings.main_model,
                    temperature=self._settings.temperature,
                )
                think, tool_call, observe, next_action = _parse_react(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "ReAct parse attempt %d for step %s failed: %s",
                    attempt,
                    step.id,
                    exc,
                )
                continue

            self._display_react(step.id, think, tool_call, observe, next_action)

            # Execute the tool
            tool_result = await self._tool_router.execute(  # type: ignore[attr-defined]
                tool_call.tool,
                session_id=session_id,
                step_id=step.id,
                **tool_call.args,
            )

            tokens = getattr(raw, "__tokens__", 0)
            react_step = ReActStep(
                step_id=step.id,
                think=think,
                act=tool_call,
                observe=tool_result.output if tool_result.success else (tool_result.error or ""),
                next_action=next_action,
                tokens_used=tokens,
            )
            if not tool_result.success:
                raise RuntimeError(
                    tool_result.error or f"Tool {tool_call.tool.value} failed silently"
                )
            return react_step

        raise RuntimeError(
            f"Step '{step.id}' failed after {MAX_PARSE_RETRIES} parse attempts: {last_error}"
        )

    def _display_react(
        self,
        step_id: str,
        think: str,
        tool_call: ToolCall,
        observe: str,
        next_action: str,
    ) -> None:
        """Print a formatted ReAct iteration to the console.

        Args:
            step_id: The step ID being executed.
            think: The reasoning text.
            tool_call: The tool that was called.
            observe: The observation.
            next_action: What should happen next.
        """
        console.print(f"[yellow]🤔 Think:[/yellow] {think}")
        console.print(
            f"[blue]⚡ Act:[/blue] {tool_call.tool.value}({tool_call.args})"
        )
        console.print(f"[green]👁  Observe:[/green] {observe}")
        console.print(f"[dim]→ Next: {next_action}[/dim]")
