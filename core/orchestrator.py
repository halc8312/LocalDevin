"""Main orchestrator – coordinates the full LocalDevin session lifecycle."""

import logging

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from config.settings import Settings
from core.executor import Executor
from core.models import Plan, SessionStatus
from core.planner import Planner
from core.replanner import Replanner
from core.session import Session

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Top-level coordinator for a LocalDevin session.

    Manages the full pipeline:
    ``task → plan → approval → execute → replan → PR → review → insights``.
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: object,
        tool_router: object,
        session_store: object,
        pr_reviewer: object | None = None,
        auto_fix: object | None = None,
        session_analyzer: object | None = None,
        token_tracker: object | None = None,
    ) -> None:
        """Initialise the Orchestrator with all required dependencies.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
            tool_router: Tool router for dispatching tool calls.
            session_store: Persistent session store.
            pr_reviewer: Optional PR reviewer instance.
            auto_fix: Optional auto-fix instance.
            session_analyzer: Optional session analyser instance.
            token_tracker: Optional token tracker instance.
        """
        self._settings = settings
        self._llm = llm_client
        self._tool_router = tool_router
        self._store = session_store
        self._pr_reviewer = pr_reviewer
        self._auto_fix = auto_fix
        self._analyzer = session_analyzer
        self._token_tracker = token_tracker

        self._planner = Planner(settings=settings, llm_client=llm_client)
        self._replanner = Replanner(settings=settings, llm_client=llm_client)
        self._executor = Executor(
            settings=settings,
            llm_client=llm_client,
            tool_router=tool_router,
            session_store=session_store,
        )

    async def run_session(self, task: str, repo_path: str) -> Session:
        """Run a full LocalDevin session for the given task.

        Args:
            task: Natural language task description.
            repo_path: Filesystem path to the target repository.

        Returns:
            The completed (or failed/escalated) Session object.
        """
        session = Session(task=task, repo_path=repo_path)

        console.print(
            Panel(
                f"[bold green]🤖 LocalDevin Session Started[/bold green]\n"
                f"Task: {task}\nRepo: {repo_path}",
                title=f"Session {session.session_id[:8]}",
            )
        )

        try:
            await self._store.create_session(  # type: ignore[attr-defined]
                task=task,
                repo_path=repo_path,
                session_id=session.session_id,
            )
        except Exception as exc:
            logger.warning("Could not persist session: %s", exc)

        # ── Phase 1: Planning ─────────────────────────────────────────────────
        session.transition(SessionStatus.PLANNING)
        plan = await self._run_planning(session, task)

        # ── Phase 2: Await Approval ───────────────────────────────────────────
        session.transition(SessionStatus.AWAITING_APPROVAL)
        approved = self._request_approval(plan)
        if not approved:
            session.transition(SessionStatus.FAILED)
            console.print("[red]Plan rejected by user. Session aborted.[/red]")
            return session

        # ── Phase 3: Execution ────────────────────────────────────────────────
        session.transition(SessionStatus.EXECUTING)
        history = await self._run_execution(session, plan)

        # ── Phase 4: PR Creation ──────────────────────────────────────────────
        pr_url = await self._create_pr(session, plan)

        # ── Phase 5: Review & Auto-fix ────────────────────────────────────────
        if pr_url and self._pr_reviewer is not None:
            await self._run_review(session, repo_path)

        # ── Phase 6: Session Insights ─────────────────────────────────────────
        if self._analyzer is not None:
            await self._run_insights(session)

        session.transition(SessionStatus.COMPLETED)
        console.print(
            Panel(
                f"[bold green]✅ Session Completed[/bold green]\n"
                f"Tokens used: {session.total_tokens:,}",
                title="Done",
            )
        )
        return session

    async def _run_planning(self, session: Session, task: str) -> Plan:
        """Run the planning phase.

        Args:
            session: Current session.
            task: Task description.

        Returns:
            The generated Plan.
        """
        console.print("[bold cyan]📋 Planning...[/bold cyan]")
        try:
            plan = await self._planner.create_plan(task)
            console.print(
                f"[green]Plan created:[/green] {plan.task_summary} "
                f"({len(plan.steps)} steps)"
            )
            await self._store.record_event(  # type: ignore[attr-defined]
                session.session_id, "planning", "plan_created", plan.model_dump()
            )
            return plan
        except Exception as exc:
            logger.error("Planning failed: %s", exc)
            session.transition(SessionStatus.FAILED)
            raise

    def _request_approval(self, plan: Plan) -> bool:
        """Display the plan and request user approval.

        Args:
            plan: The plan to display.

        Returns:
            True if the user approves, False otherwise.
        """
        console.print("\n[bold]📋 Execution Plan:[/bold]")
        console.print(f"  Summary: {plan.task_summary}")
        console.print("  Completion criteria:")
        for criterion in plan.completion_criteria:
            console.print(f"    ✓ {criterion}")
        console.print("  Steps:")
        for step in plan.steps:
            deps = f" (depends: {step.depends_on})" if step.depends_on else ""
            console.print(
                f"    [{step.size.value}] {step.id}: {step.description}{deps}"
            )
        return Confirm.ask("\n[bold yellow]Approve this plan?[/bold yellow]")

    async def _run_execution(self, session: Session, plan: Plan) -> list[object]:
        """Run the execution phase.

        Args:
            session: Current session.
            plan: Approved plan to execute.

        Returns:
            List of completed ReActStep objects.
        """
        console.print("[bold cyan]⚙️  Executing...[/bold cyan]")

        async def on_error(error: str, current_plan: Plan, history: list[object]) -> None:
            session.transition(SessionStatus.REPLANNING)
            try:
                await self._replanner.handle_error(  # type: ignore[arg-type]
                    error=error, plan=current_plan, history=history  # type: ignore[arg-type]
                )
            finally:
                session.transition(SessionStatus.EXECUTING)

        try:
            history = await self._executor.execute_plan(
                plan=plan,
                session_id=session.session_id,
                on_error=on_error,
            )
            session.add_tokens(sum(getattr(s, "tokens_used", 0) for s in history))
            return history
        except RuntimeError as exc:
            if "Circuit breaker" in str(exc):
                session.transition(SessionStatus.ESCALATED)
            else:
                session.transition(SessionStatus.FAILED)
            raise

    async def _create_pr(self, session: Session, plan: Plan) -> str | None:
        """Create a GitHub PR after execution completes.

        Args:
            session: Current session.
            plan: The completed plan (used for PR title/body).

        Returns:
            PR URL string, or None if PR creation was skipped.
        """
        if not self._settings.github_token:
            logger.info("No GitHub token configured – skipping PR creation")
            return None

        try:
            git_tool = self._tool_router.get_tool("git")  # type: ignore[attr-defined]
            branch = f"{self._settings.pr_branch_prefix}{session.session_id[:8]}"
            await git_tool.create_branch(branch)
            await git_tool.commit(
                message=f"feat: {plan.task_summary}",
                files=[],
            )
            pr_url: str = await git_tool.create_pr(
                title=plan.task_summary,
                body="\n".join(f"- {c}" for c in plan.completion_criteria),
                base=self._settings.github_default_branch,
            )
            console.print(f"[green]🔀 PR created:[/green] {pr_url}")
            await self._store.record_event(  # type: ignore[attr-defined]
                session.session_id, "pr", "pr_created", {"url": pr_url}
            )
            return pr_url
        except Exception as exc:
            logger.warning("PR creation failed: %s", exc)
            return None

    async def _run_review(self, session: Session, repo_path: str) -> None:
        """Run PR review and auto-fix.

        Args:
            session: Current session.
            repo_path: Path to the target repository.
        """
        console.print("[bold cyan]🔎 Reviewing PR...[/bold cyan]")
        try:
            branch = f"{self._settings.pr_branch_prefix}{session.session_id[:8]}"
            review_result = await self._pr_reviewer.review(  # type: ignore[union-attr]
                repo_path=repo_path, branch=branch
            )
            await self._store.record_event(  # type: ignore[attr-defined]
                session.session_id,
                "review",
                "review_completed",
                review_result.model_dump(),
            )
            severe = [i for i in review_result.issues if i.category == "Severe Bug"]
            if severe and self._auto_fix is not None:
                await self._auto_fix.fix(  # type: ignore[union-attr]
                    review_result=review_result,
                    repo_path=repo_path,
                    session_id=session.session_id,
                )
        except Exception as exc:
            logger.warning("Review phase failed: %s", exc)

    async def _run_insights(self, session: Session) -> None:
        """Generate session insights.

        Args:
            session: Current session.
        """
        try:
            insight = await self._analyzer.analyze(  # type: ignore[union-attr]
                session_id=session.session_id
            )
            console.print(
                f"[bold]📊 Session Insights:[/bold] "
                f"size={insight.session_size}, "
                f"category={insight.category}, "
                f"tokens={insight.total_tokens:,}"
            )
        except Exception as exc:
            logger.warning("Insights generation failed: %s", exc)
