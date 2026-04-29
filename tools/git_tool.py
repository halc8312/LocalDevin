"""Git and GitHub operations tool."""

import logging
import re
from pathlib import Path

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_CONVENTIONAL_PREFIXES = (
    "feat:", "fix:", "docs:", "style:", "refactor:",
    "perf:", "test:", "chore:", "ci:", "build:", "revert:",
)

# Regex patterns for GitHub remote URL parsing
_HTTPS_PATTERN = re.compile(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")
_SSH_PATTERN = re.compile(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")


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
            action: One of ``create_branch``, ``commit``, ``push_branch``,
                ``create_pr``, ``get_diff``.
            **kwargs: Action-specific arguments.

        Returns:
            ToolResult for the requested action.
        """
        dispatch: dict[str, object] = {
            "create_branch": self.create_branch,
            "commit": self.commit,
            "push_branch": self.push_branch,
            "create_pr": self.create_pr,
            "get_diff": self.get_diff,
        }
        handler = dispatch.get(action)
        if handler is None:
            return self._error(
                f"Unknown action: {action}",
                [f"Available actions: {', '.join(sorted(dispatch.keys()))}"]
            )
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
            
            # Check if there are any changes to commit
            if not repo.index.diff("HEAD") and not repo.untracked_files:
                logger.info("No changes to commit in %s", self._repo_path)
                return self._success("Nothing to commit – working tree is clean")
            
            commit = repo.index.commit(message)
            logger.info("Created commit %s: %s", commit.hexsha[:7], message)
            return self._success(f"Committed {commit.hexsha[:7]}: {message}")
        except git.exc.GitCommandError as exc:
            logger.error("Git commit failed: %s", exc)
            return self._error(f"Git command failed: {exc}")
        except Exception as exc:
            logger.error("Commit failed: %s", exc)
            return self._error(str(exc))

    async def push_branch(
        self, remote: str = "origin", force: bool = False, **_: object
    ) -> ToolResult:
        """Push the current branch to a remote.

        Args:
            remote: Remote name to push to (default: ``origin``).
            force: Whether to force-push.

        Returns:
            ToolResult indicating success or failure.
        """
        try:
            import git

            repo = git.Repo(self._repo_path)
            current_branch = repo.active_branch.name
            
            # Check if remote exists
            if remote not in [r.name for r in repo.remotes]:
                return self._error(
                    f"Remote '{remote}' not found",
                    [f"Available remotes: {', '.join(r.name for r in repo.remotes)}"]
                )
            
            remote_obj = repo.remote(remote)
            push_args = [f"{current_branch}:{current_branch}"]
            if force:
                push_args.insert(0, "--force")
            
            info = remote_obj.push(*push_args)
            if info and info[0].flags & git.PushInfo.ERROR:
                logger.error("Push failed: %s", info[0].summary)
                return self._error(
                    f"Push failed: {info[0].summary}",
                    ["Check if the branch exists on remote", "Try force=True if appropriate"]
                )
            
            logger.info("Pushed branch %s to %s", current_branch, remote)
            return self._success(f"Pushed branch '{current_branch}' to '{remote}'")
        except git.exc.GitCommandError as exc:
            logger.error("Git push failed: %s", exc)
            return self._error(
                f"Git push failed: {exc}",
                ["Check network connectivity", "Verify push permissions"]
            )
        except Exception as exc:
            logger.error("Push failed: %s", exc)
            return self._error(str(exc))

    def _parse_github_remote(self, remote_url: str) -> str | None:
        """Extract owner/repo slug from a GitHub remote URL.

        Supports both HTTPS and SSH formats:
        - https://github.com/owner/repo[.git]
        - git@github.com:owner/repo[.git]

        Args:
            remote_url: The Git remote URL.

        Returns:
            The owner/repo slug, or None if parsing fails.
        """
        # Try HTTPS pattern
        match = _HTTPS_PATTERN.match(remote_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        
        # Try SSH pattern
        match = _SSH_PATTERN.match(remote_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        
        return None

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
            
            # Check if origin remote exists
            if "origin" not in [r.name for r in repo.remotes]:
                return self._error(
                    "No 'origin' remote found",
                    ["Add a remote with: git remote add origin <url>"]
                )
            
            remote_url: str = repo.remotes.origin.url
            repo_slug = self._parse_github_remote(remote_url)
            
            if not repo_slug:
                return self._error(
                    f"Could not parse GitHub repository from remote URL: {remote_url}",
                    ["Ensure remote URL is a valid GitHub HTTPS or SSH URL"]
                )

            gh = Github(self._github_token)
            gh_repo = gh.get_repo(repo_slug)
            current_branch = repo.active_branch.name
            pr = gh_repo.create_pull(
                title=title, body=body, head=current_branch, base=base
            )
            logger.info("Created PR: %s", pr.html_url)
            return self._success(pr.html_url)
        except git.exc.GitCommandError as exc:
            logger.error("Git operation failed: %s", exc)
            return self._error(f"Git operation failed: {exc}")
        except Exception as exc:
            logger.error("PR creation failed: %s", exc)
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
