"""Tests for integrations/scheduler.py."""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from config.settings import Settings
from integrations.scheduler import Scheduler


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    """Return a mock orchestrator."""
    orchestrator = AsyncMock()
    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.total_tokens = 1000
    orchestrator.run_session.return_value = mock_session
    return orchestrator


@pytest.fixture
def mock_slack() -> MagicMock:
    """Return a mock Slack bridge."""
    slack = MagicMock()
    return slack


@pytest.fixture
def scheduler(settings: Settings, mock_orchestrator: AsyncMock) -> Scheduler:
    """Return a scheduler instance with mocked dependencies."""
    return Scheduler(
        settings=settings,
        orchestrator=mock_orchestrator,
        slack_bridge=None,
    )


class TestSchedulerInit:
    """Test Scheduler initialization."""

    def test_init_without_slack(
        self, settings: Settings, mock_orchestrator: AsyncMock
    ) -> None:
        scheduler = Scheduler(settings, mock_orchestrator, None)
        assert scheduler._settings == settings
        assert scheduler._orchestrator == mock_orchestrator
        assert scheduler._slack is None
        assert len(scheduler._jobs) == 0

    def test_init_with_slack(
        self,
        settings: Settings,
        mock_orchestrator: AsyncMock,
        mock_slack: MagicMock,
    ) -> None:
        scheduler = Scheduler(settings, mock_orchestrator, mock_slack)
        assert scheduler._slack == mock_slack


class TestSchedulerStartStop:
    """Test scheduler start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_scheduler(self, scheduler: Scheduler) -> None:
        scheduler.start()
        assert scheduler._scheduler.running
        
        # Starting again should log warning but not error
        scheduler.start()
        assert scheduler._scheduler.running
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_scheduler(self, scheduler: Scheduler) -> None:
        scheduler.start()
        scheduler.stop()
        # Give the scheduler a moment to shut down
        await asyncio.sleep(0.1)
        assert not scheduler._scheduler.running
        
        # Stopping again should log warning but not error
        scheduler.stop()
        assert not scheduler._scheduler.running


class TestSchedulerAddRecurring:
    """Test recurring job registration."""

    def test_add_recurring_valid_cron(self, scheduler: Scheduler) -> None:
        scheduler.add_recurring(
            name="daily-task",
            cron_expr="0 9 * * *",
            task="Run daily checks",
            repo_path="/test/repo",
            playbook="daily-check",
        )
        
        assert "daily-task" in scheduler._jobs
        job_info = scheduler._jobs["daily-task"]
        assert job_info["type"] == "recurring"
        assert job_info["cron"] == "0 9 * * *"
        assert job_info["task"] == "Run daily checks"
        assert job_info["repo_path"] == "/test/repo"
        assert job_info["playbook"] == "daily-check"

    def test_add_recurring_invalid_cron(self, scheduler: Scheduler) -> None:
        with pytest.raises(ValueError, match="Invalid cron expression"):
            scheduler.add_recurring(
                name="invalid-task",
                cron_expr="not a cron",
                task="Task",
                repo_path="/test/repo",
            )

    def test_add_recurring_replaces_existing(self, scheduler: Scheduler) -> None:
        scheduler.add_recurring(
            name="task",
            cron_expr="0 9 * * *",
            task="First task",
            repo_path="/test/repo",
        )
        
        scheduler.add_recurring(
            name="task",
            cron_expr="0 10 * * *",
            task="Replaced task",
            repo_path="/test/repo",
        )
        
        assert scheduler._jobs["task"]["cron"] == "0 10 * * *"
        assert scheduler._jobs["task"]["task"] == "Replaced task"


class TestSchedulerAddOnetime:
    """Test one-time job registration."""

    def test_add_onetime_future_date(self, scheduler: Scheduler) -> None:
        run_at = datetime.now() + timedelta(hours=1)
        scheduler.add_onetime(
            name="onetime-task",
            run_at=run_at,
            task="One-time task",
            repo_path="/test/repo",
        )
        
        assert "onetime-task" in scheduler._jobs
        job_info = scheduler._jobs["onetime-task"]
        assert job_info["type"] == "onetime"
        assert job_info["task"] == "One-time task"

    def test_add_onetime_past_date(self, scheduler: Scheduler) -> None:
        """Jobs with past dates may execute immediately or be skipped."""
        run_at = datetime.now() - timedelta(hours=1)
        scheduler.add_onetime(
            name="past-task",
            run_at=run_at,
            task="Past task",
            repo_path="/test/repo",
        )
        
        assert "past-task" in scheduler._jobs


class TestSchedulerListSchedules:
    """Test listing scheduled jobs."""

    def test_list_empty_schedules(self, scheduler: Scheduler) -> None:
        schedules = scheduler.list_schedules()
        assert schedules == []

    @pytest.mark.asyncio
    async def test_list_schedules_with_jobs(self, scheduler: Scheduler) -> None:
        # Need event loop for scheduler to work
        scheduler.start()
        try:
            scheduler.add_recurring(
                name="recurring-1",
                cron_expr="0 9 * * *",
                task="Task 1",
                repo_path="/repo1",
            )
            scheduler.add_recurring(
                name="recurring-2",
                cron_expr="0 10 * * *",
                task="Task 2",
                repo_path="/repo2",
            )
            
            schedules = scheduler.list_schedules()
            assert len(schedules) == 2
            
            names = [s["name"] for s in schedules]
            assert "recurring-1" in names
            assert "recurring-2" in names
        finally:
            scheduler.stop()


class TestSchedulerPauseResume:
    """Test pausing and resuming jobs."""

    def test_pause_job(self, scheduler: Scheduler) -> None:
        scheduler.add_recurring(
            name="pausable",
            cron_expr="0 9 * * *",
            task="Task",
            repo_path="/repo",
        )
        
        scheduler.pause("pausable")
        # Job should still exist but be paused
        assert "pausable" in scheduler._jobs

    def test_pause_nonexistent_job(self, scheduler: Scheduler) -> None:
        with pytest.raises(ValueError, match="Failed to pause job"):
            scheduler.pause("nonexistent")

    def test_resume_job(self, scheduler: Scheduler) -> None:
        scheduler.add_recurring(
            name="resumable",
            cron_expr="0 9 * * *",
            task="Task",
            repo_path="/repo",
        )
        scheduler.pause("resumable")
        scheduler.resume("resumable")
        
        assert "resumable" in scheduler._jobs

    def test_resume_nonexistent_job(self, scheduler: Scheduler) -> None:
        with pytest.raises(ValueError, match="Failed to resume job"):
            scheduler.resume("nonexistent")


class TestSchedulerRemove:
    """Test removing jobs."""

    def test_remove_job(self, scheduler: Scheduler) -> None:
        scheduler.add_recurring(
            name="removable",
            cron_expr="0 9 * * *",
            task="Task",
            repo_path="/repo",
        )
        
        scheduler.remove("removable")
        assert "removable" not in scheduler._jobs

    def test_remove_nonexistent_job(self, scheduler: Scheduler) -> None:
        with pytest.raises(ValueError, match="Failed to remove job"):
            scheduler.remove("nonexistent")


class TestSchedulerRunTask:
    """Test task execution."""

    @pytest.mark.asyncio
    async def test_run_task_success(
        self, scheduler: Scheduler, mock_orchestrator: AsyncMock
    ) -> None:
        await scheduler._run_task(
            task="Test task",
            repo_path="/test/repo",
            playbook=None,
        )
        
        mock_orchestrator.run_session.assert_called_once_with(
            task="Test task",
            repo_path="/test/repo"
        )

    @pytest.mark.asyncio
    async def test_run_task_with_slack_notification(
        self,
        settings: Settings,
        mock_orchestrator: AsyncMock,
        mock_slack: MagicMock,
    ) -> None:
        scheduler = Scheduler(settings, mock_orchestrator, mock_slack)
        
        await scheduler._run_task(
            task="Test task",
            repo_path="/test/repo",
        )
        
        mock_slack.notify_session_completed.assert_called_once()
        args = mock_slack.notify_session_completed.call_args[1]
        assert args["session_id"] == "test-session-123"
        assert args["task"] == "Test task"
        assert args["tokens"] == 1000

    @pytest.mark.asyncio
    async def test_run_task_failure(
        self,
        settings: Settings,
        mock_slack: MagicMock,
    ) -> None:
        # Create orchestrator that raises an error
        failing_orchestrator = AsyncMock()
        failing_orchestrator.run_session.side_effect = RuntimeError("Test error")
        
        scheduler = Scheduler(settings, failing_orchestrator, mock_slack)
        
        # Should not raise, just log the error
        await scheduler._run_task(
            task="Failing task",
            repo_path="/test/repo",
        )
        
        mock_slack.notify_session_failed.assert_called_once()
        args = mock_slack.notify_session_failed.call_args[1]
        assert args["task"] == "Failing task"
        assert "Test error" in args["error"]


class TestSchedulerRun:
    """Test long-lived scheduler run."""

    @pytest.mark.asyncio
    async def test_run_starts_scheduler(self, scheduler: Scheduler) -> None:
        """Test that run() starts the scheduler."""
        # We can't test the full blocking behavior without complex signal mocking,
        # but we can test that start() is called
        with patch.object(scheduler, "start") as mock_start:
            with patch.object(scheduler, "stop") as mock_stop:
                # Create a task that will immediately cancel
                async def quick_run() -> None:
                    run_task = asyncio.create_task(scheduler.run())
                    await asyncio.sleep(0.1)  # Let it start
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                
                await quick_run()
                mock_start.assert_called_once()
                # stop() is called in finally block
                mock_stop.assert_called()


class TestSchedulerIntegration:
    """Integration tests with actual APScheduler (no mocks)."""

    @pytest.mark.asyncio
    async def test_job_execution(self, settings: Settings) -> None:
        """Test that a job actually executes."""
        executed = []
        
        mock_orchestrator = AsyncMock()
        mock_session = MagicMock()
        mock_session.session_id = "test"
        mock_session.total_tokens = 100
        
        async def track_execution(task: str, repo_path: str) -> MagicMock:
            executed.append((task, repo_path))
            return mock_session
        
        mock_orchestrator.run_session = track_execution
        
        scheduler = Scheduler(settings, mock_orchestrator, None)
        scheduler.start()
        
        try:
            # Add a job that runs immediately
            run_at = datetime.now() + timedelta(seconds=0.5)
            scheduler.add_onetime(
                name="immediate",
                run_at=run_at,
                task="Immediate task",
                repo_path="/test",
            )
            
            # Wait for job to execute
            await asyncio.sleep(1)
            
            assert len(executed) == 1
            assert executed[0] == ("Immediate task", "/test")
        finally:
            scheduler.stop()
