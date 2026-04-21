"""APScheduler-based periodic task scheduler."""

import asyncio
import logging
from datetime import datetime
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
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

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
        """
        trigger = CronTrigger.from_crontab(cron_expr)
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
            next_run = job.next_run_time
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
        """
        self._scheduler.pause_job(name)
        logger.info("Job '%s' paused", name)

    def resume(self, name: str) -> None:
        """Resume a paused job.

        Args:
            name: Job name to resume.
        """
        self._scheduler.resume_job(name)
        logger.info("Job '%s' resumed", name)

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
        try:
            session = await self._orchestrator.run_session(  # type: ignore[attr-defined]
                task=task, repo_path=repo_path
            )
            if self._slack is not None:
                self._slack.notify_session_completed(  # type: ignore[attr-defined]
                    session_id=session.session_id,
                    task=task,
                    tokens=session.total_tokens,
                )
            logger.info("Scheduled task completed: %s", task)
        except Exception as exc:
            logger.error("Scheduled task failed: %s – %s", task, exc)
            if self._slack is not None:
                self._slack.notify_session_failed(  # type: ignore[attr-defined]
                    session_id="unknown", task=task, error=str(exc)
                )
