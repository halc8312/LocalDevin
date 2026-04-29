"""APScheduler-based periodic task scheduler."""

import asyncio
import logging
import signal
from datetime import datetime
from types import FrameType
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings

logger = logging.getLogger(__name__)


class Scheduler:
    """Manage recurring and one-time LocalDevin tasks.

    Wraps APScheduler and integrates with the Orchestrator to execute
    tasks on a schedule, persisting results and sending Slack notifications.
    """

    def __init__(
        self,
        settings: Settings,
        orchestrator: object,
        slack_bridge: object | None = None,
    ) -> None:
        """Initialise the scheduler.

        Args:
            settings: Application settings.
            orchestrator: Orchestrator instance for running sessions.
            slack_bridge: Optional SlackBridge for notifications.
        """
        self._settings = settings
        self._orchestrator = orchestrator
        self._slack = slack_bridge
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")
        else:
            logger.warning("Scheduler is already running")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
        else:
            logger.warning("Scheduler is not running")

    def add_recurring(
        self,
        name: str,
        cron_expr: str,
        task: str,
        repo_path: str,
        playbook: str | None = None,
    ) -> None:
        """Register a recurring cron job.

        Args:
            name: Unique job name.
            cron_expr: Cron expression (e.g. ``"0 9 * * *"``).
            task: Natural language task description.
            repo_path: Repository path.
            playbook: Optional playbook name.

        Raises:
            ValueError: If cron expression is invalid.
        """
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
        except (ValueError, TypeError) as exc:
            logger.error("Invalid cron expression '%s': %s", cron_expr, exc)
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        
        self._scheduler.add_job(
            func=self._run_task,
            trigger=trigger,
            id=name,
            kwargs={"task": task, "repo_path": repo_path, "playbook": playbook},
            replace_existing=True,
        )
        self._jobs[name] = {
            "type": "recurring",
            "cron": cron_expr,
            "task": task,
            "repo_path": repo_path,
            "playbook": playbook,
        }
        logger.info("Recurring job '%s' registered: %s", name, cron_expr)

    def add_onetime(
        self,
        name: str,
        run_at: datetime,
        task: str,
        repo_path: str,
    ) -> None:
        """Register a one-time scheduled job.

        Args:
            name: Unique job name.
            run_at: Datetime when the job should run.
            task: Natural language task description.
            repo_path: Repository path.
        """
        self._scheduler.add_job(
            func=self._run_task,
            trigger="date",
            run_date=run_at,
            id=name,
            kwargs={"task": task, "repo_path": repo_path},
            replace_existing=True,
        )
        self._jobs[name] = {
            "type": "onetime",
            "run_at": run_at.isoformat(),
            "task": task,
            "repo_path": repo_path,
        }
        logger.info("One-time job '%s' registered for %s", name, run_at)

    def list_schedules(self) -> list[dict[str, Any]]:
        """Return information about all registered jobs.

        Returns:
            List of job info dicts.
        """
        result: list[dict[str, Any]] = []
        for job in self._scheduler.get_jobs():
            info = self._jobs.get(job.id, {})
            # APScheduler 3.x uses next_run_time
            next_run = getattr(job, "next_run_time", None)
            result.append({
                "name": job.id,
                "next_run": next_run.isoformat() if next_run else None,
                **info,
            })
        return result

    def pause(self, name: str) -> None:
        """Pause a scheduled job.

        Args:
            name: Job name to pause.

        Raises:
            ValueError: If job does not exist.
        """
        try:
            self._scheduler.pause_job(name)
            logger.info("Job '%s' paused", name)
        except Exception as exc:
            logger.error("Failed to pause job '%s': %s", name, exc)
            raise ValueError(f"Failed to pause job '{name}': {exc}") from exc

    def resume(self, name: str) -> None:
        """Resume a paused job.

        Args:
            name: Job name to resume.

        Raises:
            ValueError: If job does not exist.
        """
        try:
            self._scheduler.resume_job(name)
            logger.info("Job '%s' resumed", name)
        except Exception as exc:
            logger.error("Failed to resume job '%s': %s", name, exc)
            raise ValueError(f"Failed to resume job '{name}': {exc}") from exc

    def remove(self, name: str) -> None:
        """Remove a scheduled job.

        Args:
            name: Job name to remove.

        Raises:
            ValueError: If job does not exist.
        """
        try:
            self._scheduler.remove_job(name)
            self._jobs.pop(name, None)
            logger.info("Job '%s' removed", name)
        except Exception as exc:
            logger.error("Failed to remove job '%s': %s", name, exc)
            raise ValueError(f"Failed to remove job '{name}': {exc}") from exc

    async def run(self) -> None:
        """Run the scheduler in a long-lived event loop.

        This blocks until interrupted (SIGINT/SIGTERM). Useful for
        running the scheduler as a standalone service.
        """
        self.start()
        logger.info("Scheduler running. Press Ctrl+C to stop.")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def signal_handler(signum: int, _frame: FrameType | None) -> None:
            logger.info("Received signal %s, shutting down...", signum)
            loop.call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            await stop_event.wait()
        finally:
            self.stop()
            logger.info("Scheduler loop exited")

    async def _run_task(
        self,
        task: str,
        repo_path: str,
        playbook: str | None = None,
    ) -> None:
        """Execute a task via the Orchestrator.

        Args:
            task: Natural language task description.
            repo_path: Repository path.
            playbook: Optional playbook name (unused at orchestration level).
        """
        logger.info("Scheduled task starting: %s", task)
        session_id = "unknown"
        try:
            run_kwargs: dict[str, object] = {"task": task, "repo_path": repo_path}
            if playbook is not None:
                run_kwargs["playbook"] = playbook
            session = await self._orchestrator.run_session(  # type: ignore[attr-defined]
                **run_kwargs,
            )
            session_id = getattr(session, "session_id", "unknown")
            total_tokens = getattr(session, "total_tokens", 0)
            
            if self._slack is not None:
                self._slack.notify_session_completed(  # type: ignore[attr-defined]
                    session_id=session_id,
                    task=task,
                    tokens=total_tokens,
                )
            logger.info("Scheduled task completed: %s (session: %s)", task, session_id)
        except Exception as exc:
            logger.error("Scheduled task failed: %s – %s", task, exc, exc_info=True)
            if self._slack is not None:
                self._slack.notify_session_failed(  # type: ignore[attr-defined]
                    session_id=session_id, task=task, error=str(exc)
                )
