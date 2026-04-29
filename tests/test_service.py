"""Tests for core/service.py and runtime wiring."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.models import ToolResult
from core.orchestrator import Orchestrator
from core.service import SessionService, build_session_service
from memory.playbook_loader import PlaybookLoader

PLAN_JSON = json.dumps(
    {
        "task_summary": "Add search",
        "completion_criteria": ["Search works"],
        "steps": [
            {
                "id": "step_1",
                "description": "Run a shell check",
                "depends_on": [],
                "tools": ["shell"],
                "size": "small",
            }
        ],
    }
)

REACT_JSON = json.dumps(
    {
        "think": "Run shell",
        "act": {"tool": "shell", "args": {"command": "pwd"}},
        "observe": "done",
        "next": "done",
    }
)


class DummyOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run_session(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return type("SessionStub", (), {"session_id": "sess-1", "total_tokens": 0})()


class TestPlaybookLoader:
    def test_load_existing_playbook(self, tmp_path: Path) -> None:
        (tmp_path / "test-coverage.md").write_text("# Coverage")
        loader = PlaybookLoader(playbooks_dir=str(tmp_path))

        assert loader.load("test-coverage") == "# Coverage"

    def test_missing_playbook_raises(self, tmp_path: Path) -> None:
        loader = PlaybookLoader(playbooks_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Playbook 'missing' not found"):
            loader.load("missing")


class TestSessionService:
    @pytest.mark.asyncio
    async def test_run_task_passes_loaded_context(self, settings, tmp_path: Path) -> None:
        playbooks_dir = tmp_path / "playbooks"
        playbooks_dir.mkdir()
        (playbooks_dir / "bug-triage.md").write_text("# Bug triage")
        service = SessionService(settings.model_copy(update={"playbooks_dir": str(playbooks_dir)}))
        service._knowledge_base = MagicMock()  # type: ignore[assignment]
        service._knowledge_base.get_relevant.return_value = []
        service._codebase_index = AsyncMock()  # type: ignore[assignment]
        service._codebase_index.search.return_value = []
        dummy = DummyOrchestrator()
        service._build_orchestrator = lambda repo_path: dummy  # type: ignore[method-assign]

        await service.run_task("Fix tests", repo_path=str(tmp_path), playbook="bug-triage")

        assert dummy.calls[0]["playbook"] == "bug-triage"
        assert dummy.calls[0]["planning_context"] == {"playbook": "# Bug triage"}
        assert dummy.calls[0]["context_metadata"]["playbook"] == "bug-triage"

    def test_build_session_service_returns_service(self, settings) -> None:
        service = build_session_service(settings)

        assert isinstance(service, SessionService)


class TestOrchestratorPersistence:
    @pytest.mark.asyncio
    async def test_run_session_persists_statuses(self, settings, mock_session_store) -> None:
        mock_llm = AsyncMock()
        mock_llm.chat.side_effect = [f"```json\n{PLAN_JSON}\n```", f"```json\n{REACT_JSON}\n```"]
        mock_llm.set_session_id = MagicMock()
        tool_router = AsyncMock()
        tool_router.execute.return_value = ToolResult(success=True, output="ok")
        tool_router.get_tool.return_value = None
        orchestrator = Orchestrator(
            settings=settings,
            llm_client=mock_llm,
            tool_router=tool_router,
            session_store=mock_session_store,
        )

        session = await orchestrator.run_session(
            task="Fix tests",
            repo_path="/repo",
            require_approval=False,
        )

        statuses = [call.args[1] for call in mock_session_store.update_status.await_args_list]
        assert statuses == ["planning", "awaiting_approval", "executing", "completed"]
        mock_session_store.update_total_tokens.assert_awaited()
        assert session.status.value == "completed"
