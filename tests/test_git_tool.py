"""Tests for tools/git_tool.py."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import ToolResult
from tools.git_tool import GitTool


class TestGitToolInit:
    """Test GitTool initialization."""

    def test_init_defaults(self) -> None:
        tool = GitTool()
        assert tool._repo_path == Path(".")
        assert tool._github_token == ""
        assert tool._default_branch == "main"

    def test_init_custom(self) -> None:
        tool = GitTool(
            repo_path="/custom/path",
            github_token="ghp_test123",
            default_branch="develop"
        )
        assert tool._repo_path == Path("/custom/path")
        assert tool._github_token == "ghp_test123"
        assert tool._default_branch == "develop"


class TestGitToolExecute:
    """Test GitTool action dispatch."""

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self) -> None:
        tool = GitTool()
        result = await tool.execute(action="invalid_action")
        assert not result.success
        assert "Unknown action" in result.error
        assert "Available actions" in result.suggestions[0]

    @pytest.mark.asyncio
    async def test_execute_dispatches_correctly(self) -> None:
        tool = GitTool()
        with patch.object(tool, "get_diff", return_value=ToolResult(success=True, output="diff")):
            result = await tool.execute(action="get_diff", base="main")
            assert result.success
            assert result.output == "diff"


class TestGitToolCreateBranch:
    """Test branch creation."""

    @pytest.mark.asyncio
    async def test_create_branch_empty_name(self) -> None:
        tool = GitTool()
        result = await tool.create_branch(name="")
        assert not result.success
        assert "must not be empty" in result.error

    @pytest.mark.asyncio
    async def test_create_branch_success(self, tmp_path: Path) -> None:
        """Test successful branch creation in a temp git repo."""
        import git
        
        # Create a temporary git repo
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.create_branch(name="feature/test")
        
        assert result.success
        assert "feature/test" in result.output
        assert repo.active_branch.name == "feature/test"

    @pytest.mark.asyncio
    async def test_create_branch_already_exists(self, tmp_path: Path) -> None:
        """Test creating a branch when Git raises an error."""
        import git

        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")

        tool = GitTool(repo_path=str(tmp_path))
        with patch.object(repo, "create_head", side_effect=git.exc.GitCommandError("branch", 1)):
            with patch("git.Repo", return_value=repo):
                result = await tool.create_branch(name="feature/test")

        assert result.success is False


class TestGitToolCommit:
    """Test commit creation."""

    @pytest.mark.asyncio
    async def test_commit_empty_message(self) -> None:
        tool = GitTool()
        result = await tool.commit(message="")
        assert not result.success
        assert "must not be empty" in result.error

    @pytest.mark.asyncio
    async def test_commit_invalid_format(self) -> None:
        tool = GitTool()
        result = await tool.commit(message="invalid commit message")
        assert not result.success
        assert "Conventional Commits" in result.error

    @pytest.mark.asyncio
    async def test_commit_nothing_to_commit(self, tmp_path: Path) -> None:
        """Test committing when there are no changes."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.commit(message="feat: no changes")
        
        assert result.success
        assert "Nothing to commit" in result.output

    @pytest.mark.asyncio
    async def test_commit_success(self, tmp_path: Path) -> None:
        """Test successful commit."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        # Make a change
        test_file.write_text("updated")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.commit(message="feat: update test file")
        
        assert result.success
        assert "Committed" in result.output
        assert "feat: update test file" in result.output

    @pytest.mark.asyncio
    async def test_commit_stages_untracked_files(self, tmp_path: Path) -> None:
        """Test that untracked files are committed when staging all files."""
        import git

        repo = git.Repo.init(tmp_path)
        tracked_file = tmp_path / "tracked.txt"
        tracked_file.write_text("initial")
        repo.index.add([str(tracked_file)])
        repo.index.commit("Initial commit")

        untracked_file = tmp_path / "new.txt"
        untracked_file.write_text("new file")

        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.commit(message="feat: add untracked file")

        assert result.success
        assert "new.txt" not in repo.untracked_files

    @pytest.mark.asyncio
    async def test_commit_specific_files(self, tmp_path: Path) -> None:
        """Test committing specific files."""
        import git
        
        repo = git.Repo.init(tmp_path)
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("file1")
        file2.write_text("file2")
        repo.index.add([str(file1)])
        repo.index.commit("Initial commit")
        
        # Update file1 and create file2
        file1.write_text("file1 updated")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.commit(
            message="fix: update file1",
            files=[str(file1)]
        )
        
        assert result.success
        # file2 should not be committed (use relative path)
        assert "file2.txt" in repo.untracked_files


class TestGitToolPushBranch:
    """Test branch pushing."""

    @pytest.mark.asyncio
    async def test_push_branch_no_remote(self, tmp_path: Path) -> None:
        """Test pushing when remote doesn't exist."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.push_branch(remote="origin")
        
        assert not result.success
        assert "not found" in result.error
        assert "Available remotes" in result.suggestions[0]

    @pytest.mark.asyncio
    async def test_push_branch_success(self, tmp_path: Path) -> None:
        """Test successful push with mocked remote."""
        import git
        
        # Create main repo
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        # Create a bare repo to act as remote
        remote_path = tmp_path / "remote.git"
        remote_path.mkdir()
        git.Repo.init(remote_path, bare=True)
        
        # Add remote
        repo.create_remote("origin", str(remote_path))
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.push_branch(remote="origin")
        
        assert result.success
        assert "Pushed branch" in result.output


class TestGitToolParseGithubRemote:
    """Test GitHub remote URL parsing."""

    def test_parse_https_url(self) -> None:
        tool = GitTool()
        
        # Standard HTTPS URL
        slug = tool._parse_github_remote("https://github.com/owner/repo")
        assert slug == "owner/repo"
        
        # HTTPS URL with .git suffix
        slug = tool._parse_github_remote("https://github.com/owner/repo.git")
        assert slug == "owner/repo"

    def test_parse_ssh_url(self) -> None:
        tool = GitTool()
        
        # Standard SSH URL
        slug = tool._parse_github_remote("git@github.com:owner/repo")
        assert slug == "owner/repo"
        
        # SSH URL with .git suffix
        slug = tool._parse_github_remote("git@github.com:owner/repo.git")
        assert slug == "owner/repo"

    def test_parse_invalid_url(self) -> None:
        tool = GitTool()
        
        # Not a GitHub URL
        slug = tool._parse_github_remote("https://gitlab.com/owner/repo")
        assert slug is None
        
        # Invalid format
        slug = tool._parse_github_remote("not-a-url")
        assert slug is None


class TestGitToolCreatePR:
    """Test PR creation."""

    @pytest.mark.asyncio
    async def test_create_pr_no_token(self) -> None:
        tool = GitTool(github_token="")
        result = await tool.create_pr(title="Test PR")
        assert not result.success
        assert "token not configured" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_empty_title(self) -> None:
        tool = GitTool(github_token="test_token")
        result = await tool.create_pr(title="")
        assert not result.success
        assert "must not be empty" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_no_remote(self, tmp_path: Path) -> None:
        """Test PR creation when no origin remote exists."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        tool = GitTool(repo_path=str(tmp_path), github_token="test_token")
        result = await tool.create_pr(title="Test PR")
        
        assert not result.success
        assert "No 'origin' remote found" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_invalid_remote_url(self, tmp_path: Path) -> None:
        """Test PR creation with invalid remote URL."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        repo.create_remote("origin", "https://example.com/not-github")
        
        tool = GitTool(repo_path=str(tmp_path), github_token="test_token")
        result = await tool.create_pr(title="Test PR")
        
        assert not result.success
        assert "Could not parse GitHub repository" in result.error

    @pytest.mark.asyncio
    async def test_create_pr_success(self, tmp_path: Path) -> None:
        """Test successful PR creation with mocked GitHub API."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        repo.create_remote("origin", "https://github.com/owner/repo.git")
        repo.create_head("feature/test")
        repo.heads["feature/test"].checkout()
        
        # Mock GitHub API
        mock_pr = MagicMock()
        mock_pr.html_url = "https://github.com/owner/repo/pull/123"
        
        mock_repo = MagicMock()
        mock_repo.create_pull.return_value = mock_pr
        
        mock_gh = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        
        with patch("github.Github", return_value=mock_gh):
            tool = GitTool(repo_path=str(tmp_path), github_token="test_token")
            result = await tool.create_pr(
                title="Test PR",
                body="Test body",
                base="main"
            )
        
        assert result.success
        assert "https://github.com/owner/repo/pull/123" in result.output
        mock_repo.create_pull.assert_called_once_with(
            title="Test PR",
            body="Test body",
            head="feature/test",
            base="main"
        )


class TestGitToolGetDiff:
    """Test diff retrieval."""

    @pytest.mark.asyncio
    async def test_get_diff_no_changes(self, tmp_path: Path) -> None:
        """Test diff when there are no changes."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        repo.index.commit("Initial commit")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.get_diff(base="HEAD")
        
        assert result.success
        assert result.output == "(no changes)"

    @pytest.mark.asyncio
    async def test_get_diff_with_changes(self, tmp_path: Path) -> None:
        """Test diff with actual changes."""
        import git
        
        repo = git.Repo.init(tmp_path)
        test_file = tmp_path / "test.txt"
        test_file.write_text("initial")
        repo.index.add([str(test_file)])
        initial_commit = repo.index.commit("Initial commit")
        
        # Make a change
        test_file.write_text("updated")
        repo.index.add([str(test_file)])
        repo.index.commit("Update file")
        
        tool = GitTool(repo_path=str(tmp_path))
        result = await tool.get_diff(base=initial_commit.hexsha)
        
        assert result.success
        assert "test.txt" in result.output
        assert "+updated" in result.output or "updated" in result.output
