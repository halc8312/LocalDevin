"""PR reviewer – git diff → LLM analysis → structured review result."""

import json
import logging
import re
from pathlib import Path

from config.settings import Settings
from core.models import ReviewIssue, ReviewResult

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    prompt_path = Path(__file__).parent.parent / "config" / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


def _parse_review(raw: str) -> ReviewResult:
    """Parse a review JSON response from the LLM.

    Args:
        raw: Raw string from the LLM.

    Returns:
        A ReviewResult instance.

    Raises:
        ValueError: If parsing fails.
    """
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw.strip()
    data = json.loads(json_str)
    issues = [ReviewIssue(**issue) for issue in data.get("issues", [])]
    return ReviewResult(
        summary=data.get("summary", ""),
        issues=issues,
        approved=data.get("approved", False),
    )


class PRReviewer:
    """Reviews pull requests by analysing git diffs with an LLM."""

    def __init__(self, settings: Settings, llm_client: object) -> None:
        """Initialise the reviewer.

        Args:
            settings: Application settings.
            llm_client: LLM client instance.
        """
        self._settings = settings
        self._llm = llm_client
        self._system_prompt = _load_prompt("review_system.md")

    async def review(self, repo_path: str, branch: str = "") -> ReviewResult:
        """Review the diff between the current branch and the default branch.

        Args:
            repo_path: Filesystem path to the repository.
            branch: Branch to review (defaults to current HEAD).

        Returns:
            A ReviewResult with categorised issues.
        """
        diff = self._get_diff(repo_path, branch)
        if not diff or diff == "(no changes)":
            return ReviewResult(summary="No changes to review.", approved=True)

        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    f"Please review the following git diff:\n\n"
                    f"```diff\n{diff[:8000]}\n```"
                ),
            },
        ]

        try:
            raw = await self._llm.chat(  # type: ignore[attr-defined]
                messages=messages,
                model=self._settings.main_model,
                temperature=self._settings.temperature,
            )
            result = _parse_review(raw)
            severe_count = sum(1 for i in result.issues if i.category == "Severe Bug")
            logger.info(
                "Review: %d issues (%d severe), approved=%s",
                len(result.issues),
                severe_count,
                result.approved,
            )
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Review parse failed: %s", exc)
            return ReviewResult(summary=f"Review parse error: {exc}", approved=False)
        except Exception as exc:
            logger.error("Review failed: %s", exc)
            return ReviewResult(summary=f"Review error: {exc}", approved=False)

    def _get_diff(self, repo_path: str, branch: str) -> str:
        """Get the git diff for review.

        Args:
            repo_path: Repository path.
            branch: Branch name (unused if empty; diffs against default).

        Returns:
            Diff string.
        """
        try:
            import git

            repo = git.Repo(repo_path)
            base = self._settings.github_default_branch
            return repo.git.diff(base)
        except Exception as exc:
            logger.warning("git diff failed: %s", exc)
            return ""
