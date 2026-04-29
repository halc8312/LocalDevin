"""LocalDevin CLI – Typer-based command line interface."""

import asyncio
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from config.settings import Settings
from core.service import build_session_service

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("localdevin")

console = Console()
app = typer.Typer(name="localdevin", help="Devin AI workflow reproduced locally")


def _get_settings() -> Settings:
    """Return CLI settings."""
    return Settings()


@app.command()
def run(
    task: str = typer.Argument(..., help="Natural language task description"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the target repository"),
    playbook: Optional[str] = typer.Option(None, "--playbook", "-p", help="Playbook name"),
) -> None:
    """Run a task (equivalent to starting a Devin session)."""
    service = build_session_service(_get_settings())

    async def _run() -> None:
        session = await service.run_task(task=task, repo_path=repo, playbook=playbook)
        console.print(f"[green]Session {session.session_id[:8]} completed[/green]")

    asyncio.run(_run())


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the codebase"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
) -> None:
    """Ask a question about the codebase (equivalent to Ask Devin)."""
    service = build_session_service(_get_settings())

    async def _ask() -> None:
        answer = await service.ask_codebase(question=question, repo_path=repo)
        console.print(answer)

    asyncio.run(_ask())


@app.command()
def review(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to the repository"),
    branch: Optional[str] = typer.Option(None, "--branch", "-b", help="Branch to review"),
) -> None:
    """Review the current branch (equivalent to Devin Review)."""
    service = build_session_service(_get_settings())

    async def _review() -> None:
        result = await service.review_repo(repo_path=repo, branch=branch or "")
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
    service = build_session_service(_get_settings())
    count = service.index_repo(repo_path=repo)
    console.print(f"[green]Indexed {count} code chunks from {repo}[/green]")


@app.command()
def insights(
    session_id: str = typer.Argument(..., help="Session ID to analyse"),
) -> None:
    """Analyse a completed session (equivalent to Session Insights)."""
    service = build_session_service(_get_settings())

    async def _insights() -> None:
        insight = await service.analyze_session(session_id=session_id)
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
            for suggestion in insight.knowledge_suggestions:
                console.print(f"    • {suggestion}")
        console.print(f"\n[bold]Improved Prompt:[/bold]\n{insight.improved_prompt}")

    asyncio.run(_insights())


@app.command()
def schedule(
    name: str = typer.Argument(..., help="Unique job name"),
    cron: str = typer.Argument(..., help="Cron expression (e.g. '0 9 * * *')"),
    task: str = typer.Argument(..., help="Task description"),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository path"),
    playbook: Optional[str] = typer.Option(None, "--playbook", "-p", help="Playbook name"),
    run_scheduler: bool = typer.Option(
        False,
        "--run",
        help="Keep the scheduler process alive after registering the job",
    ),
) -> None:
    """Register a recurring scheduled task (equivalent to Scheduled Sessions)."""
    service = build_session_service(_get_settings())
    scheduler = service.create_scheduler()
    scheduler.add_recurring(
        name=name,
        cron_expr=cron,
        task=task,
        repo_path=repo,
        playbook=playbook,
    )
    console.print(f"[green]Scheduled '{name}': {task!r} every {cron!r} in {repo}[/green]")
    if run_scheduler:
        console.print("[cyan]Starting scheduler loop...[/cyan]")
        asyncio.run(scheduler.run())
    else:
        console.print("Use --run to keep the scheduler process alive and execute jobs.")


@app.command()
def knowledge() -> None:
    """List and manage the Knowledge Base."""
    service = build_session_service(_get_settings())
    items = service.list_knowledge()
    if not items:
        settings = _get_settings()
        console.print("[yellow]No knowledge items found.[/yellow]")
        console.print(f"Add Markdown files to: {settings.knowledge_dir}")
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
    service = build_session_service(_get_settings())

    async def _status() -> None:
        sessions = await service.get_recent_sessions(limit=10)
        if not sessions:
            console.print("[yellow]No sessions found.[/yellow]")
            return

        table = Table(title="Recent Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Status")
        table.add_column("Task")
        table.add_column("Tokens")
        table.add_column("Created")
        for session in sessions:
            sid = str(session.get("id", ""))[:8]
            status_value = str(session.get("status", ""))
            color = (
                "green"
                if status_value == "completed"
                else "red"
                if status_value in ("failed", "escalated")
                else "yellow"
            )
            table.add_row(
                sid,
                f"[{color}]{status_value}[/{color}]",
                str(session.get("task", ""))[:50],
                str(session.get("total_tokens", 0)),
                str(session.get("created_at", ""))[:19],
            )
        console.print(table)

    asyncio.run(_status())


if __name__ == "__main__":
    app()
