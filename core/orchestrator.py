"""Main orchestrator – coordinates the full LocalDevin session lifecycle."""

import logging
import inspect

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from config.settings import Settings
from core.executor import Executor
from core.models import Plan, ReActStep, SessionStatus, ToolResult
from core.planner import Planner
from core.replanner import Replanner
from core.session import Session

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Top-level coordinator for a LocalDevin session."""

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

    async def run_session(
        self,
        task: str,
        repo_path: str,
        playbook: str | None = None,
        planning_context: dict[str, object] | None = None,
        context_metadata: dict[str, object] | None = None,
        require_approval: bool = True,
    ) -> Session:
        """Run a full LocalDevin session for the given task."""
        session = Session(task=task, repo_path=repo_path)

        console.print(
            Panel(
                f"[bold green]🤖 LocalDevin Session Started[/bold green]\n"
                f"Task: {task}\nRepo: {repo_path}",
                title=f"Session {session.session_id[:8]}",
            )
        )

        await self._store.create_session(
            task=task,
            repo_path=repo_path,
            session_id=session.session_id,
        )
        if hasattr(self._llm, "set_session_id"):
            maybe_awaitable = self._llm.set_session_id(session.session_id)  # type: ignore[attr-defined]
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        await self._store.record_event(
            session.session_id,
            "session",
            "session_started",
            {"task": task, "repo_path": repo_path, "playbook": playbook},
        )
        if context_metadata:
            await self._store.record_event(
                session.session_id,
                "context",
                "context_loaded",
                context_metadata,
            )

        try:
            await self._transition_session(session, SessionStatus.PLANNING)
            plan = await self._run_planning(session, task, planning_context)

            await self._transition_session(session, SessionStatus.AWAITING_APPROVAL)
            approved = self._request_approval(plan, require_approval=require_approval)
            await self._store.record_event(
                session.session_id,
                "approval",
                "approval_recorded",
                {"approved": approved},
            )
            if not approved:
                await self._transition_session(session, SessionStatus.FAILED)
                console.print("[red]Plan rejected by user. Session aborted.[/red]")
                await self._sync_total_tokens(session)
                return session

            await self._transition_session(session, SessionStatus.EXECUTING)
            await self._run_execution(session, plan)

            pr_url = await self._create_pr(session, plan)
            if pr_url and self._pr_reviewer is not None:
                await self._run_review(session, repo_path)

            if self._analyzer is not None:
                await self._run_insights(session)

            await self._sync_total_tokens(session)
            await self._transition_session(session, SessionStatus.COMPLETED)
            console.print(
                Panel(
                    f"[bold green]✅ Session Completed[/bold green]\n"
                    f"Tokens used: {session.total_tokens:,}",
                    title="Done",
                )
            )
            return session
        except RuntimeError as exc:
            final_status = (
                SessionStatus.ESCALATED
                if "Circuit breaker" in str(exc)
                else SessionStatus.FAILED
            )
            await self._sync_total_tokens(session)
            await self._transition_session(session, final_status)
            raise
        except Exception:
            await self._sync_total_tokens(session)
            await self._transition_session(session, SessionStatus.FAILED)
            raise

    async def _run_planning(
        self,
        session: Session,
        task: str,
        planning_context: dict[str, object] | None,
    ) -> Plan:
        """Run the planning phase."""
        console.print("[bold cyan]📋 Planning...[/bold cyan]")
        plan = await self._planner.create_plan(task, context=planning_context)
        console.print(
            f"[green]Plan created:[/green] {plan.task_summary} ({len(plan.steps)} steps)"
        )
        await self._store.record_event(
            session.session_id,
            "planning",
            "plan_created",
            plan.model_dump(),
        )
        return plan

    def _request_approval(self, plan: Plan, require_approval: bool) -> bool:
        """Display the plan and optionally request user approval."""
        console.print("\n[bold]📋 Execution Plan:[/bold]")
        console.print(f"  Summary: {plan.task_summary}")
        console.print("  Completion criteria:")
        for criterion in plan.completion_criteria:
            console.print(f"    ✓ {criterion}")
        console.print("  Steps:")
        for step in plan.steps:
            deps = f" (depends: {step.depends_on})" if step.depends_on else ""
            console.print(f"    [{step.size.value}] {step.id}: {step.description}{deps}")
        if not require_approval:
            console.print("[yellow]Auto-approving plan for non-interactive execution.[/yellow]")
            return True
        return Confirm.ask("\n[bold yellow]Approve this plan?[/bold yellow]")

    async def _run_execution(self, session: Session, plan: Plan) -> list[ReActStep]:
        """Run the execution phase."""
        console.print("[bold cyan]⚙️  Executing...[/bold cyan]")

        async def on_error(error: str, current_plan: Plan, history: list[ReActStep]) -> None:
            await self._transition_session(session, SessionStatus.REPLANNING)
            try:
                action = await self._replanner.handle_error(
                    error=error,
                    plan=current_plan,
                    history=history,
                )
                await self._store.record_event(
                    session.session_id,
                    "replanning",
                    "replan_decision",
                    action.model_dump(),
                )
            finally:
                await self._transition_session(session, SessionStatus.EXECUTING)

        history = await self._executor.execute_plan(
            plan=plan,
            session_id=session.session_id,
            on_error=on_error,
        )
        session.add_tokens(sum(step.tokens_used for step in history))
        await self._sync_total_tokens(session)
        return history

    async def _create_pr(self, session: Session, plan: Plan) -> str | None:
        """Create a GitHub PR after execution completes."""
        if not self._settings.github_token:
            logger.info("No GitHub token configured – skipping PR creation")
            return None

        git_tool = self._tool_router.get_tool("git")
        if git_tool is None:
            return None

        branch = f"{self._settings.pr_branch_prefix}{session.session_id[:8]}"
        branch_result: ToolResult = await git_tool.create_branch(branch)
        if not branch_result.success:
            logger.warning("Branch creation failed: %s", branch_result.error)
            return None

        commit_result: ToolResult = await git_tool.commit(
            message=f"feat: {plan.task_summary}",
            files=[],
        )
        if not commit_result.success:
            logger.warning("Commit failed: %s", commit_result.error)
            return None
        if "Nothing to commit" in commit_result.output:
            logger.info("Skipping PR creation because there is nothing to commit")
            await self._store.record_event(
                session.session_id,
                "pr",
                "pr_skipped",
                {"reason": "nothing_to_commit"},
            )
            return None

        push_result: ToolResult = await git_tool.push_branch(remote="origin")
        if not push_result.success:
            logger.warning("Branch push failed: %s", push_result.error)
            return None

        pr_result: ToolResult = await git_tool.create_pr(
            title=plan.task_summary,
            body="\n".join(f"- {criterion}" for criterion in plan.completion_criteria),
            base=self._settings.github_default_branch,
        )
        if not pr_result.success:
            logger.warning("PR creation failed: %s", pr_result.error)
            return None

        console.print(f"[green]🔀 PR created:[/green] {pr_result.output}")
        await self._store.record_event(
            session.session_id,
            "pr",
            "pr_created",
            {"url": pr_result.output, "branch": branch},
        )
        return pr_result.output

    async def _run_review(self, session: Session, repo_path: str) -> None:
        """Run PR review and auto-fix."""
        console.print("[bold cyan]🔎 Reviewing PR...[/bold cyan]")
        branch = f"{self._settings.pr_branch_prefix}{session.session_id[:8]}"
        review_result = await self._pr_reviewer.review(repo_path=repo_path, branch=branch)
        await self._store.record_event(
            session.session_id,
            "review",
            "review_completed",
            review_result.model_dump(),
        )
        severe = [issue for issue in review_result.issues if issue.category == "Severe Bug"]
        if severe and self._auto_fix is not None:
            await self._auto_fix.fix(
                review_result=review_result,
                repo_path=repo_path,
                session_id=session.session_id,
            )

    async def _run_insights(self, session: Session) -> None:
        """Generate session insights."""
        insight = await self._analyzer.analyze(session_id=session.session_id)
        console.print(
            f"[bold]📊 Session Insights:[/bold] size={insight.session_size}, "
            f"category={insight.category}, tokens={insight.total_tokens:,}"
        )

    async def _transition_session(
        self,
        session: Session,
        new_status: SessionStatus,
    ) -> None:
        """Persist a session status transition."""
        session.transition(new_status)
        await self._store.update_status(session.session_id, new_status.value)

    async def _sync_total_tokens(self, session: Session) -> None:
        """Synchronise token usage back into session storage."""
        if self._token_tracker is not None:
            try:
                totals = await self._token_tracker.get_session_total(session.session_id)
                session.total_tokens = int(totals.get("total_tokens", session.total_tokens))
            except Exception as exc:
                logger.warning("Token total sync failed: %s", exc)
        await self._store.update_total_tokens(session.session_id, session.total_tokens)
