"""GitHub API bridge using PyGithub."""

import logging

from config.settings import Settings

logger = logging.getLogger(__name__)


class GitHubBridge:
    """High-level GitHub API client.

    Wraps ``PyGithub`` to provide operations needed by LocalDevin:
    PR creation, issue management, and repository metadata.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the bridge.

        Args:
            settings: Application settings (must include ``github_token``).
        """
        self._settings = settings
        self._gh: object | None = None

    def _get_gh(self) -> object:
        """Lazily create the GitHub client.

        Returns:
            An authenticated ``github.Github`` instance.

        Raises:
            RuntimeError: If no GitHub token is configured.
        """
        if self._gh is not None:
            return self._gh
        if not self._settings.github_token:
            raise RuntimeError(
                "GitHub token not configured. Set LD_GITHUB_TOKEN in your .env file."
            )
        from github import Github

        self._gh = Github(self._settings.github_token)
        return self._gh

    def get_repo(self, repo_slug: str) -> object:
        """Get a repository object.

        Args:
            repo_slug: Repository in ``owner/name`` format.

        Returns:
            A ``github.Repository.Repository`` object.
        """
        gh = self._get_gh()
        return gh.get_repo(repo_slug)  # type: ignore[attr-defined]

    def create_pull_request(
        self,
        repo_slug: str,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> str:
        """Create a pull request and return its URL.

        Args:
            repo_slug: Repository in ``owner/name`` format.
            title: PR title.
            body: PR body (Markdown).
            head: Source branch.
            base: Target branch (defaults to ``settings.github_default_branch``).

        Returns:
            The HTML URL of the created PR.
        """
        base = base or self._settings.github_default_branch
        try:
            repo = self.get_repo(repo_slug)
            pr = repo.create_pull(title=title, body=body, head=head, base=base)  # type: ignore[attr-defined]
            pr_url: str = pr.html_url
            logger.info("Created PR: %s", pr_url)
            return pr_url
        except Exception as exc:
            logger.error("PR creation failed: %s", exc)
            raise

    def list_open_issues(self, repo_slug: str) -> list[dict[str, object]]:
        """Return open issues for a repository.

        Args:
            repo_slug: Repository in ``owner/name`` format.

        Returns:
            List of issue dicts with ``number``, ``title``, ``url`` keys.
        """
        try:
            repo = self.get_repo(repo_slug)
            issues = repo.get_issues(state="open")  # type: ignore[attr-defined]
            return [
                {"number": i.number, "title": i.title, "url": i.html_url}
                for i in issues
            ]
        except Exception as exc:
            logger.error("Failed to list issues: %s", exc)
            return []
