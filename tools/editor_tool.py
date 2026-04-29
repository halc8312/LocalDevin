"""File editor tool – atomic read/write/patch with sandboxing."""

import logging
import shutil
from pathlib import Path

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyo",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}


class EditorTool(BaseTool):
    """Read and write files within a sandboxed root directory.

    All file operations are restricted to ``sandbox_root`` to prevent
    path-traversal attacks.  Write operations automatically create a
    ``.bak`` backup of existing files.
    """

    name = "editor"
    description = "Read and write files within a sandboxed directory."

    def __init__(self, sandbox_root: str = ".") -> None:
        """Initialise the tool.

        Args:
            sandbox_root: The root directory outside of which no file access
                is permitted.
        """
        self._root = Path(sandbox_root).resolve()

    async def execute(self, action: str = "read", **kwargs: object) -> ToolResult:
        """Dispatch to the requested file action.

        Args:
            action: One of ``read``, ``write``, ``patch``, ``list_dir``.
            **kwargs: Action-specific arguments.

        Returns:
            ToolResult for the requested action.
        """
        dispatch = {
            "read": self.read,
            "write": self.write,
            "patch": self.patch,
            "list_dir": self.list_dir,
        }
        handler = dispatch.get(action)
        if handler is None:
            return self._error(f"Unknown action: {action}", list(dispatch.keys()))
        return await handler(**kwargs)  # type: ignore[arg-type]

    async def read(self, path: str = "", **_: object) -> ToolResult:
        """Read a text file.

        Args:
            path: File path (relative to sandbox root or absolute within it).

        Returns:
            ToolResult with file contents as output.
        """
        try:
            resolved = self._resolve(path)
        except ValueError as exc:
            return self._error(str(exc))

        if not resolved.exists():
            return self._error(f"File not found: {path}")
        if resolved.is_dir():
            return self._error(f"Path is a directory: {path}", ["Use 'list_dir' instead."])
        if resolved.suffix.lower() in _BINARY_SUFFIXES:
            return self._error(
                f"Binary file not readable: {path}",
                ["This file type cannot be read as text."],
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return self._success(content)
        except OSError as exc:
            return self._error(str(exc))

    async def write(self, path: str = "", content: str = "", **_: object) -> ToolResult:
        """Write content to a file, backing up the original if it exists.

        Args:
            path: Destination file path.
            content: Text content to write.

        Returns:
            ToolResult indicating success or failure.
        """
        try:
            resolved = self._resolve(path)
        except ValueError as exc:
            return self._error(str(exc))

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            if resolved.exists():
                backup = resolved.with_suffix(resolved.suffix + ".bak")
                shutil.copy2(resolved, backup)
            resolved.write_text(content, encoding="utf-8")
            return self._success(f"Written {len(content)} chars to {path}")
        except OSError as exc:
            return self._error(str(exc))

    async def patch(
        self, path: str = "", search: str = "", replace: str = "", **_: object
    ) -> ToolResult:
        """Replace an exact string in a file (search/replace patch).

        Args:
            path: File to patch.
            search: String to search for (must be unique in the file).
            replace: Replacement string.

        Returns:
            ToolResult indicating success or failure.
        """
        read_result = await self.read(path=path)
        if not read_result.success:
            return read_result

        original = read_result.output
        if search not in original:
            return self._error(
                f"Search string not found in {path}",
                ["Ensure the search string matches the file content exactly."],
            )

        count = original.count(search)
        if count > 1:
            return self._error(
                f"Search string found {count} times in {path} – must be unique",
                ["Make the search string more specific to ensure uniqueness."],
            )

        patched = original.replace(search, replace, 1)
        return await self.write(path=path, content=patched)

    async def list_dir(self, path: str = ".", **_: object) -> ToolResult:
        """List the contents of a directory.

        Args:
            path: Directory path.

        Returns:
            ToolResult with a newline-separated list of entries.
        """
        try:
            resolved = self._resolve(path)
        except ValueError as exc:
            return self._error(str(exc))

        if not resolved.exists():
            return self._error(f"Directory not found: {path}")
        if not resolved.is_dir():
            return self._error(f"Not a directory: {path}")

        try:
            entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = [
                f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries
            ]
            return self._success("\n".join(lines))
        except OSError as exc:
            return self._error(str(exc))

    def _resolve(self, path: str) -> Path:
        """Resolve a path against the sandbox root, rejecting traversal.

        Args:
            path: User-supplied path string.

        Returns:
            Resolved absolute Path.

        Raises:
            ValueError: If the resolved path escapes the sandbox root.
        """
        if not path:
            raise ValueError("Empty path provided")
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves outside the sandbox root '{self._root}'"
            )
        return resolved
