"""Bug detection using LLM analysis and static code inspection."""

import logging
from pathlib import Path

from config.settings import Settings
from core.models import ReviewIssue, ReviewResult

logger = logging.getLogger(__name__)


class BugCatcher:
    """Detect bugs in source files using LLM analysis.

    Unlike the PRReviewer (which operates on diffs), BugCatcher scans
    individual files for structural issues and common bug patterns.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise the bug catcher.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
        """
        self._settings = settings
        self._llm = llm_client

    async def analyse_file(self, file_path: str) -> ReviewResult:
        """Analyse a single source file for bugs.

        Args:
            file_path: Path to the source file to analyse.

        Returns:
            ReviewResult with detected issues.
        """
        path = Path(file_path)
        if not path.exists():
            return ReviewResult(summary=f"File not found: {file_path}", approved=False)

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ReviewResult(summary=str(exc), approved=False)

        system_prompt = (
            "You are a static analysis tool. "
            "Find bugs, security issues, and logic errors in the provided code. "
            "Output a JSON object with 'summary', 'issues' (array), and 'approved' fields."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Analyse this {path.suffix} file for bugs:\n\n"
                    f"```{path.suffix.lstrip('.')}\n{source[:6000]}\n```"
                ),
            },
        ]

        try:
            import json
            import re

            raw = await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.main_model,
                temperature=0.0,
            )
            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
            json_str = match.group(1) if match else raw.strip()
            data = json.loads(json_str)
            issues = [ReviewIssue(**i) for i in data.get("issues", [])]
            return ReviewResult(
                summary=data.get("summary", ""),
                issues=issues,
                approved=data.get("approved", len(issues) == 0),
            )
        except Exception as exc:
            logger.warning("Bug analysis failed for %s: %s", file_path, exc)
            return ReviewResult(summary=f"Analysis error: {exc}", approved=False)
