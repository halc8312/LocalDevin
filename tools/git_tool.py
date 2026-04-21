"""Git and GitHub operations tool."""

import logging
from pathlib import Path

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_CONVENTIONAL_PREFIXES = (
    "feat:", "fix:", "docs:", "style:", "refactor:",
    "perf:", "test:", "chore:", "ci:", "build:", "revert:",
)


class GitTool(BaseTool):
    """Perform Git operations and create GitHub PRs.

    Uses ``gitpython`` for local Git operations and ``PyGithub`` for the
    GitHub API.
    """

    name = "git"
    description = "Manage Git branches, commits, and GitHub pull requests."

    def __init__(
        self,
        repo_path: str = ".",
        github_token: str = "",
        default_branch: str = "main",
    ) -> None:
        """Initialise the tool.

        Args:
            repo_path: Local path to the Git repository.
            github_token: GitHub Personal Access Token.
            default_branch: Default base branch for PRs.
        """
        self._repo_path = Path(repo_path)
        self._github_token = github_token
        self._default_branch = default_branch

    async def execute(self, action: str = "get_diff", **kwargs: object) -> ToolResult:
        """Dispatch to the requested Git action.

        Args:
            action: One of ``create_branch``, ``commit``, ``create_pr``,
                ``get_diff``.
            **kwargs: Action-specific arguments.

        Returns:
            ToolResult for the requested action.
        """
        dispatch: dict[str, object] = {
            "create_branch": self.create_branch,
            "commit": self.commit,
            "create_pr": self.create_pr,
            "get_diff": self.get_diff,
        }
        handler = dispatch.get(action)
        if handler is None:
            return self._error(f"Unknown action: {action}", list(dispatch.keys()))
        return await handler(**kwargs)  # type: ignore[operator]

    async def create_branch(self, name: str = "", **_: object) -> ToolResult:
        """Create and checkout a new Git branch.

        Args:
            name: Branch name to create.

        Returns:
            ToolResult indicating success or failure.
        """
        if not name:
            return self._error("Branch name must not be empty")
        try:
            import git

            repo = git.Repo(self._repo_path)
            new_branch = repo.create_head(name)
            new_branch.checkout()
            return self._success(f"Created and checked out branch '{name}'")
        except Exception as exc:
            return self._error(str(exc))

    async def commit(
        self, message: str = "", files: list[str] | None = None, **_: object
    ) -> ToolResult:
        """Stage files and create a commit.

        Args:
            message: Commit message (must follow Conventional Commits format).
            files: List of file paths to stage. Pass an empty list to stage all.

        Returns:
            ToolResult indicating success or failure.
        """
        if not message:
            return self._error("Commit message must not be empty")
        if not any(message.startswith(prefix) for prefix in _CONVENTIONAL_PREFIXES):
            return self._error(
                "Commit message must follow Conventional Commits format",
                [f"Use a prefix like: {_CONVENTIONAL_PREFIXES[0]} or {_CONVENTIONAL_PREFIXES[1]}"],
            )
        try:
            import git

            repo = git.Repo(self._repo_path)
            if files:
                repo.index.add(files)
            else:
                repo.git.add(A=True)
            if not repo.index.diff("HEAD"):
                return self._success("Nothing to commit – working tree is clean")
            repo.index.commit(message)
            return self._success(f"Committed: {message}")
        except Exception as exc:
            return self._error(str(exc))

    async def create_pr(
        self, title: str = "", body: str = "", base: str = "", **_: object
    ) -> ToolResult:
        """Create a GitHub pull request.

        Args:
            title: PR title.
            body: PR body (Markdown).
            base: Base branch name (defaults to ``default_branch``).

        Returns:
            ToolResult with the PR URL as output.
        """
        if not self._github_token:
            return self._error(
                "GitHub token not configured",
                ["Set LD_GITHUB_TOKEN in your .env file."],
            )
        if not title:
            return self._error("PR title must not be empty")

        base = base or self._default_branch
        try:
            import git
            from github import Github

            repo = git.Repo(self._repo_path)
            remote_url: str = repo.remotes.origin.url
            # Extract "owner/repo" from the remote URL
            if remote_url.endswith(".git"):
                remote_url = remote_url[:-4]
            repo_slug = "/".join(remote_url.split("/")[-2:])

            gh = Github(self._github_token)
            gh_repo = gh.get_repo(repo_slug)
            current_branch = repo.active_branch.name
            pr = gh_repo.create_pull(
                title=title, body=body, head=current_branch, base=base
            )
            return self._success(pr.html_url)
        except Exception as exc:
            return self._error(str(exc))

    async def get_diff(self, base: str = "", **_: object) -> ToolResult:
        """Get the git diff against a base branch.

        Args:
            base: Base branch/commit to diff against.

        Returns:
            ToolResult with the diff string as output.
        """
        base = base or self._default_branch
        try:
            import git

            repo = git.Repo(self._repo_path)
            diff = repo.git.diff(base)
            return self._success(diff or "(no changes)")
        except Exception as exc:
            return self._error(str(exc))
