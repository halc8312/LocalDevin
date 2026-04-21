"""Session analytics – compute metrics and generate improvement suggestions."""

import logging
from typing import Any

from config.settings import Settings
from core.models import SessionInsight

logger = logging.getLogger(__name__)

_SIZE_THRESHOLDS = [
    (20_000, "XS"),
    (50_000, "S"),
    (100_000, "M"),
    (200_000, "L"),
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Test Generation": ["test", "spec", "coverage", "pytest", "unittest"],
    "Bug Fixing": ["fix", "bug", "error", "crash", "exception", "fail"],
    "Refactoring": ["refactor", "clean", "reorganize", "restructure", "simplify"],
    "Documentation": ["doc", "readme", "comment", "docstring"],
    "Feature Development": ["add", "implement", "feature", "create", "build", "new"],
}


def _classify_size(total_tokens: int) -> str:
    for threshold, label in _SIZE_THRESHOLDS:
        if total_tokens <= threshold:
            return label
    return "XL"


def _classify_category(task: str) -> str:
    task_lower = task.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in task_lower for kw in keywords):
            return category
    return "General"


class SessionAnalyzer:
    """Analyse completed sessions to produce actionable insights."""

    def __init__(
        self,
        settings: Settings,
        session_store: object,
        llm_client: object,
    ) -> None:
        """Initialise the analyser.

        Args:
            settings: Application settings.
            session_store: Session store for fetching history.
            llm_client: LLM client for generating prompt improvements.
        """
        self._settings = settings
        self._store = session_store
        self._llm = llm_client

    async def analyze(self, session_id: str) -> SessionInsight:
        """Analyse a session and return insights.

        Args:
            session_id: The session to analyse.

        Returns:
            A SessionInsight with metrics, issues, and suggestions.
        """
        history = await self._store.get_session_history(session_id)  # type: ignore[attr-defined]

        total_tokens = sum(
            e.get("data", {}).get("tokens_used", 0)
            for e in history
            if isinstance(e.get("data"), dict)
        )
        user_messages = sum(1 for e in history if e.get("event_type") == "user_message")
        task = self._extract_task(history)

        issues = self._detect_issues(history)
        improved_prompt = await self._improve_prompt(task, issues)
        knowledge_suggestions = self._generate_knowledge_suggestions(history)

        return SessionInsight(
            session_id=session_id,
            total_tokens=total_tokens,
            user_messages=user_messages,
            session_size=_classify_size(total_tokens),
            category=_classify_category(task),
            issues=issues,
            improved_prompt=improved_prompt,
            knowledge_suggestions=knowledge_suggestions,
        )

    def _extract_task(self, history: list[dict[str, Any]]) -> str:
        """Extract the original task from session history.

        Args:
            history: List of event dicts.

        Returns:
            Task string, or empty string if not found.
        """
        for event in history:
            if event.get("event_type") == "plan_created":
                data = event.get("data", {})
                if isinstance(data, dict):
                    return str(data.get("task_summary", ""))
        return ""

    def _detect_issues(
        self, history: list[dict[str, Any]]
    ) -> list[dict[str, object]]:
        """Detect common problems in a session's history.

        Args:
            history: List of event dicts.

        Returns:
            List of issue dicts.
        """
        issues: list[dict[str, object]] = []

        # Detect retry loops
        failed_steps: list[str] = [
            str(e.get("step_id", ""))
            for e in history
            if e.get("event_type") == "step_failed"
        ]
        if len(failed_steps) > 3:
            issues.append({
                "type": "retry_loop",
                "description": f"High failure rate: {len(failed_steps)} step failures",
                "severity": "warning",
            })

        # Detect escalation
        if any(e.get("event_type") == "escalation" for e in history):
            issues.append({
                "type": "escalation",
                "description": "Session required human escalation",
                "severity": "info",
            })

        return issues

    async def _improve_prompt(self, task: str, issues: list[dict[str, object]]) -> str:
        """Ask the LLM to suggest an improved prompt for the task.

        Args:
            task: The original task description.
            issues: Detected issues in the session.

        Returns:
            An improved prompt suggestion.
        """
        if not task:
            return ""

        issue_text = "\n".join(
            f"- {i['type']}: {i['description']}" for i in issues
        ) or "None detected"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a prompt engineering expert. "
                    "Given an original task prompt and detected execution issues, "
                    "suggest a more precise and effective prompt."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original task: {task}\n\n"
                    f"Issues detected:\n{issue_text}\n\n"
                    "Provide an improved prompt that would avoid these issues:"
                ),
            },
        ]

        try:
            return await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.fast_model,
                temperature=0.3,
            )
        except Exception as exc:
            logger.warning("Prompt improvement failed: %s", exc)
            return task

    def _generate_knowledge_suggestions(
        self, history: list[dict[str, Any]]
    ) -> list[str]:
        """Generate knowledge suggestions from session events.

        Args:
            history: List of event dicts.

        Returns:
            List of suggestion strings.
        """
        suggestions: list[str] = []
        for event in history:
            if event.get("event_type") == "step_failed":
                data = event.get("data", {})
                error = data.get("error", "") if isinstance(data, dict) else ""
                if error and len(str(error)) > 10:
                    suggestions.append(f"Document solution for: {str(error)[:80]}")
        return list(dict.fromkeys(suggestions))[:5]
