"""Automatic fix loop for issues detected during PR review."""

import logging
import subprocess
from pathlib import Path

from config.settings import Settings
from core.models import ReviewResult

logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = 3


class AutoFix:
    """Automatically fix bugs identified by the PRReviewer.

    Runs up to ``MAX_FIX_ATTEMPTS`` iterations of:
    ``fix → test → verify``, rolling back if tests fail.
    """

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise AutoFix.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
        """
        self._settings = settings
        self._llm = llm_client

    async def fix(
        self,
        review_result: ReviewResult,
        repo_path: str,
        session_id: str,
    ) -> bool:
        """Apply fixes for severe and non-severe bugs, then verify with tests.

        Args:
            review_result: Review result containing issues to fix.
            repo_path: Filesystem path to the repository.
            session_id: Current session ID (for logging).

        Returns:
            True if all fixes were applied and tests pass, False otherwise.
        """
        fixable = [
            i for i in review_result.issues
            if i.category in ("Severe Bug", "Non-severe Bug")
        ]
        if not fixable:
            logger.info("No fixable issues found")
            return True

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            logger.info(
                "AutoFix attempt %d/%d for session %s",
                attempt,
                MAX_FIX_ATTEMPTS,
                session_id,
            )
            backup_applied = False
            try:
                for issue in fixable:
                    await self._apply_fix(issue, repo_path)

                test_passed = self._run_tests(repo_path)
                if test_passed:
                    logger.info("AutoFix: all tests passed after fix")
                    return True

                logger.warning(
                    "AutoFix attempt %d: tests failed – rolling back", attempt
                )
                self._rollback(repo_path)
                backup_applied = True
            except Exception as exc:
                logger.error("AutoFix attempt %d failed: %s", attempt, exc)
                if not backup_applied:
                    self._rollback(repo_path)

        logger.error(
            "AutoFix exhausted %d attempts without success", MAX_FIX_ATTEMPTS
        )
        return False

    async def _apply_fix(self, issue: object, repo_path: str) -> None:
        """Ask the LLM to generate a fix for a single issue.

        Args:
            issue: A ReviewIssue to fix.
            repo_path: Repository path.
        """
        from core.models import ReviewIssue

        if not isinstance(issue, ReviewIssue):
            return

        if not issue.file:
            return

        file_path = Path(repo_path) / issue.file
        if not file_path.exists():
            logger.warning("AutoFix: file not found %s", file_path)
            return

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        messages = [
            {
                "role": "system",
                "content": "You are an expert programmer. Fix the described bug by outputting the complete corrected file.",
            },
            {
                "role": "user",
                "content": (
                    f"Bug: {issue.description}\n"
                    f"Suggestion: {issue.suggestion}\n\n"
                    f"File ({issue.file}):\n```\n{source[:4000]}\n```\n\n"
                    "Output only the corrected file content, no explanation."
                ),
            },
        ]

        try:
            import re

            fixed = await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.main_model,
                temperature=0.0,
            )
            # Strip markdown fences if present
            match = re.search(r"```\w*\n([\s\S]+?)```", fixed)
            fixed_content = match.group(1) if match else fixed.strip()

            # Backup original
            backup = file_path.with_suffix(file_path.suffix + ".autofixbak")
            import shutil

            shutil.copy2(file_path, backup)
            file_path.write_text(fixed_content, encoding="utf-8")
            logger.info("Applied fix to %s", file_path)
        except Exception as exc:
            logger.warning("Could not apply fix to %s: %s", issue.file, exc)

    def _run_tests(self, repo_path: str) -> bool:
        """Run the test suite and return whether it passes.

        Args:
            repo_path: Repository path.

        Returns:
            True if tests pass (exit code 0), False otherwise.
        """
        try:
            result = subprocess.run(
                ["pytest", "--tb=no", "-q"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.warning("Test run failed: %s", exc)
            return False

    def _rollback(self, repo_path: str) -> None:
        """Roll back autofix backups.

        Args:
            repo_path: Repository path.
        """
        root = Path(repo_path)
        for backup in root.rglob("*.autofixbak"):
            original = backup.with_suffix("")  # Remove .autofixbak
            try:
                import shutil

                shutil.copy2(backup, original)
                backup.unlink()
                logger.info("Rolled back %s", original)
            except OSError as exc:
                logger.warning("Rollback failed for %s: %s", backup, exc)
