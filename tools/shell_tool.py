"""Shell command execution tool."""

import logging
import subprocess
from collections import deque

from core.models import ToolResult
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 300
_BLOCKLIST = [
    "rm -rf /",
    "rm -rf /*",
    "dd if=",
    "mkfs",
    "> /dev/sda",
    ":(){:|:&};:",
]

_MAX_HISTORY = 100


class ShellTool(BaseTool):
    """Execute shell commands in a subprocess.

    Commands are run with ``shell=True``, stdout and stderr are captured,
    and exit codes are mapped to success/failure in the ToolResult.

    Danger: A blocklist prevents obviously destructive commands.
    """

    name = "shell"
    description = "Execute a shell command and return stdout/stderr."

    def __init__(self, cwd: str | None = None) -> None:
        """Initialise the tool.

        Args:
            cwd: Working directory for commands. Defaults to current directory.
        """
        self._cwd = cwd
        self._history: deque[dict[str, object]] = deque(maxlen=_MAX_HISTORY)

    async def execute(self, command: str = "", **kwargs: object) -> ToolResult:
        """Run a shell command.

        Args:
            command: The shell command string to execute.
            **kwargs: Ignored extra arguments.

        Returns:
            ToolResult with stdout as output, or stderr as the error.
        """
        if not command:
            return self._error("No command provided", ["Provide a non-empty 'command' argument"])

        blocked = self._check_blocklist(command)
        if blocked:
            return self._error(
                f"Command blocked: {blocked}",
                ["This command is on the safety blocklist and cannot be executed."],
            )

        logger.debug("ShellTool: %s", command)
        self._history.append({"command": command, "cwd": self._cwd})

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                cwd=self._cwd,
            )
        except subprocess.TimeoutExpired:
            return self._error(
                f"Command timed out after {_TIMEOUT_SECONDS}s",
                ["Split the command into smaller steps or increase the timeout."],
            )
        except Exception as exc:
            return self._error(str(exc))

        combined = result.stdout
        if result.returncode != 0:
            return self._error(
                result.stderr or f"Exit code {result.returncode}",
                [f"stdout: {result.stdout[:500]}"] if result.stdout else [],
            )
        return self._success(combined)

    def get_history(self) -> list[dict[str, object]]:
        """Return the command execution history.

        Returns:
            List of executed command records.
        """
        return list(self._history)

    def _check_blocklist(self, command: str) -> str | None:
        """Check if a command matches the blocklist.

        Args:
            command: Command string to check.

        Returns:
            The matching blocklist entry, or None if safe.
        """
        for blocked in _BLOCKLIST:
            if blocked in command:
                return blocked
        return None
