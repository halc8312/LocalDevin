"""LocalDevin CLI – Typer-based command line interface."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("localdevin")

console = Console()
app = typer.Typer(name="localdevin", help="Devin AI workflow reproduced locally")


def _get_settings() -> object:
    from config.settings import Settings

    return Settings()


def _build_orchestrator(settings: object, repo_path: str) -> object:
    """Assemble all components and return an Orchestrator.

    Args:
        settings: Application settings.
        repo_path: Path to the target repository.

    Returns:
        A configured Orchestrator instance.
    """
    from llm.client import LLMClient
    from memory.session_store import SessionStore
    from review.auto_fix import AutoFix
    from review.pr_reviewer import PRReviewer

    from core.orchestrator import Orchestrator

    settings_obj = settings  # type: ignore[assignment]

    store = SessionStore(db_path=settings_obj.db_path)  # type: ignore[attr-defined]
    llm = LLMClient(
        base_url=f"{settings_obj.ollama_base_url}/v1",  # type: ignore[attr-defined]
    )

    from tools.editor_tool import EditorTool
    from tools.shell_tool import ShellTool
    from tools.git_tool import GitTool
    from tools.browser_tool import BrowserTool

    class _SimpleToolRouter:
        """Minimal tool router mapping ToolType → tool instance."""

        def __init__(self) -> None:
            self._shell = ShellTool(cwd=repo_path)
            self._editor = EditorTool(sandbox_root=repo_path)
            self._git = GitTool(
                repo_path=repo_path,
                github_token=settings_obj.github_token,  # type: ignore[attr-defined]
                default_branch=settings_obj.github_default_branch,  # type: ignore[attr-defined]
            )
            self._browser = BrowserTool()

        async def execute(self, tool: object, **kwargs: object) -> object:
            from core.models import ToolType

            mapping = {
                ToolType.SHELL: self._shell,
                ToolType.EDITOR_READ: self._editor,
                ToolType.EDITOR_WRITE: self._editor,
                ToolType.GIT: self._git,
                ToolType.BROWSER: self._browser,
            }
            tool_instance = mapping.get(tool, self._shell)  # type: ignore[arg-type]
            if tool in (ToolType.EDITOR_READ,):
                return await tool_instance.execute(action="read", **kwargs)  # type: ignore[union-attr]
            if tool in (ToolType.EDITOR_WRITE,):
                return await tool_instance.execute(action="write", **kwargs)  # type: ignore[union-attr]
            return await tool_instance.execute(**kwargs)  # type: ignore[union-attr]

        def get_tool(self, name: str) -> object:
            return {"git": self._git, "shell": self._shell, "editor": self._editor}.get(name)

    reviewer = PRReviewer(settings=settings_obj, llm_client=llm)  # type: ignore[arg-type]
    fixer = AutoFix(settings=settings_obj, llm_client=llm)  # type: ignore[arg-type]

    return Orchestrator(
        settings=settings_obj,  # type: ignore[arg-type]
        llm_client=llm,
        tool_router=_SimpleToolRouter(),
        session_store=store,
        pr_reviewer=reviewer,
        auto_fix=fixer,
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def run(
    task: str = typer.Argument(..., help="Natural language task description"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the target repository"),
    playbook: Optional[str] = typer.Option(None, "--playbook", "-p", help="Playbook name"),
) -> None:
    """Run a task (equivalent to starting a Devin session)."""
    settings = _get_settings()
    orchestrator = _build_orchestrator(settings, repo)

    async def _run() -> None:
        session = await orchestrator.run_session(task=task, repo_path=repo)  # type: ignore[attr-defined]
        console.print(f"[green]Session {session.session_id[:8]} completed[/green]")

    asyncio.run(_run())


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the codebase"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
) -> None:
    """Ask a question about the codebase (equivalent to Ask Devin)."""
    settings = _get_settings()

    async def _ask() -> None:
        from llm.client import LLMClient
        from memory.codebase_index import CodebaseIndex

        index = CodebaseIndex(chroma_path=settings.chroma_path)  # type: ignore[attr-defined]
        results = await index.search(query=question, n=5)

        context = "\n\n".join(
            f"[{r['file']}]\n{r['snippet']}" for r in results
        ) or "(no indexed code found)"

        llm = LLMClient(base_url=f"{settings.ollama_base_url}/v1")  # type: ignore[attr-defined]
        answer = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert code assistant. Answer the question based on the provided code context.",
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            model=settings.fast_model,  # type: ignore[attr-defined]
        )
        console.print(answer)

    asyncio.run(_ask())


@app.command()
def review(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    branch: Optional[str] = typer.Option(None, "--branch", "-b", help="Branch to review"),
) -> None:
    """Review the current branch (equivalent to Devin Review)."""
    settings = _get_settings()

    async def _review() -> None:
        from llm.client import LLMClient
        from review.pr_reviewer import PRReviewer

        llm = LLMClient(base_url=f"{settings.ollama_base_url}/v1")  # type: ignore[attr-defined]
        reviewer = PRReviewer(settings=settings, llm_client=llm)  # type: ignore[arg-type]
        result = await reviewer.review(repo_path=repo, branch=branch or "")
        console.print(f"[bold]Review:[/bold] {result.summary}")
        for issue in result.issues:
            color = "red" if issue.category == "Severe Bug" else "yellow"
            console.print(
                f"[{color}][{issue.category}] {issue.file}:{issue.line} – "
                f"{issue.description}[/{color}]"
            )
        status = "[green]Approved ✓[/green]" if result.approved else "[red]Not approved ✗[/red]"
        console.print(status)

    asyncio.run(_review())


@app.command()
def index(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository to index"),
) -> None:
    """Index a codebase for semantic search (equivalent to DeepWiki)."""
    settings = _get_settings()
    from memory.codebase_index import CodebaseIndex

    idx = CodebaseIndex(chroma_path=settings.chroma_path)  # type: ignore[attr-defined]
    count = idx.index_repo(repo_path=repo)
    console.print(f"[green]Indexed {count} code chunks from {repo}[/green]")


@app.command()
def insights(
    session_id: str = typer.Argument(..., help="Session ID to analyse"),
) -> None:
    """Analyse a completed session (equivalent to Session Insights)."""
    settings = _get_settings()

    async def _insights() -> None:
        from llm.client import LLMClient
        from memory.session_store import SessionStore
        from insights.session_analyzer import SessionAnalyzer

        store = SessionStore(db_path=settings.db_path)  # type: ignore[attr-defined]
        llm = LLMClient(base_url=f"{settings.ollama_base_url}/v1")  # type: ignore[attr-defined]
        analyzer = SessionAnalyzer(settings=settings, session_store=store, llm_client=llm)  # type: ignore[arg-type]
        insight = await analyzer.analyze(session_id=session_id)
        console.print(f"[bold]Session Insights – {session_id[:8]}[/bold]")
        console.print(f"  Category: {insight.category}")
        console.print(f"  Size: {insight.session_size}")
        console.print(f"  Tokens: {insight.total_tokens:,}")
        if insight.issues:
            console.print("  Issues:")
            for issue in insight.issues:
                console.print(f"    • {issue}")
        if insight.knowledge_suggestions:
            console.print("  Knowledge Suggestions:")
            for sug in insight.knowledge_suggestions:
                console.print(f"    • {sug}")
        console.print(f"\n[bold]Improved Prompt:[/bold]\n{insight.improved_prompt}")

    asyncio.run(_insights())


@app.command()
def schedule(
    name: str = typer.Argument(..., help="Unique job name"),
    cron: str = typer.Argument(..., help="Cron expression (e.g. '0 9 * * *')"),
    task: str = typer.Argument(..., help="Task description"),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository path"),
) -> None:
    """Register a recurring scheduled task (equivalent to Scheduled Sessions)."""
    settings = _get_settings()
    orchestrator = _build_orchestrator(settings, repo)
    from integrations.scheduler import Scheduler

    sched = Scheduler(settings=settings, orchestrator=orchestrator)  # type: ignore[arg-type]
    sched.add_recurring(name=name, cron_expr=cron, task=task, repo_path=repo)
    console.print(
        f"[green]Scheduled '{name}': {task!r} every {cron!r} in {repo}[/green]"
    )
    console.print("Note: The scheduler process must be kept running to execute jobs.")


@app.command()
def knowledge() -> None:
    """List and manage the Knowledge Base."""
    settings = _get_settings()
    from memory.knowledge_base import KnowledgeBase

    kb = KnowledgeBase(
        knowledge_dir=settings.knowledge_dir,  # type: ignore[attr-defined]
        chroma_path=settings.chroma_path,  # type: ignore[attr-defined]
    )
    items = kb.load_all()
    if not items:
        console.print("[yellow]No knowledge items found.[/yellow]")
        console.print(f"Add Markdown files to: {settings.knowledge_dir}")  # type: ignore[attr-defined]
        return

    table = Table(title="Knowledge Base")
    table.add_column("Name", style="cyan")
    table.add_column("Trigger")
    table.add_column("Repos")
    table.add_column("Enabled")
    for item in items:
        table.add_row(
            item.name,
            item.trigger[:60],
            ", ".join(item.repos),
            "✓" if item.enabled else "✗",
        )
    console.print(table)


@app.command()
def status() -> None:
    """Show recent sessions."""
    settings = _get_settings()

    async def _status() -> None:
        from memory.session_store import SessionStore

        store = SessionStore(db_path=settings.db_path)  # type: ignore[attr-defined]
        sessions = await store.get_recent_sessions(limit=10)
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        table = Table(title="Recent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Status")
        table.add_column("Task")
        table.add_column("Tokens")
        table.add_column("Created")
        for s in sessions:
            sid = str(s.get("id", ""))[:8]
            status_val = str(s.get("status", ""))
            color = "green" if status_val == "completed" else "red" if status_val in ("failed", "escalated") else "yellow"
            table.add_row(
                sid,
                f"[{color}]{status_val}[/{color}]",
                str(s.get("task", ""))[:50],
                str(s.get("total_tokens", 0)),
                str(s.get("created_at", ""))[:19],
            )
        console.print(table)

    asyncio.run(_status())


if __name__ == "__main__":
    app()
