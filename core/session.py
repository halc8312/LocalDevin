"""Session lifecycle management."""

import logging
import uuid
from datetime import datetime

from core.models import SessionStatus

logger = logging.getLogger(__name__)


class Session:
    """Represents a LocalDevin session with lifecycle management.

    Attributes:
        session_id: Unique identifier for this session.
        task: The task description.
        repo_path: Path to the target repository.
        status: Current session status.
        created_at: Session creation timestamp.
        completed_at: Session completion timestamp (None if in progress).
        total_tokens: Total tokens consumed in this session.
        consecutive_errors: Counter for the circuit breaker.
        replan_count: Number of times replanning has occurred.
    """

    def __init__(self, task: str, repo_path: str) -> None:
        """Initialise a new session.

        Args:
            task: Natural language task description.
            repo_path: Filesystem path to the target repository.
        """
        self.session_id: str = str(uuid.uuid4())
        self.task: str = task
        self.repo_path: str = repo_path
        self.status: SessionStatus = SessionStatus.PENDING
        self.created_at: datetime = datetime.now()
        self.completed_at: datetime | None = None
        self.total_tokens: int = 0
        self.consecutive_errors: int = 0
        self.replan_count: int = 0

    def transition(self, new_status: SessionStatus) -> None:
        """Transition the session to a new status.

        Args:
            new_status: The status to transition to.
        """
        logger.info(
            "Session %s: %s -> %s",
            self.session_id,
            self.status.value,
            new_status.value,
        )
        self.status = new_status
        if new_status in (
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.ESCALATED,
        ):
            self.completed_at = datetime.now()

    def record_error(self) -> None:
        """Increment the consecutive error counter."""
        self.consecutive_errors += 1

    def reset_errors(self) -> None:
        """Reset the consecutive error counter after a successful step."""
        self.consecutive_errors = 0

    def add_tokens(self, count: int) -> None:
        """Add token usage to the session total.

        Args:
            count: Number of tokens to add.
        """
        self.total_tokens += count

    def is_circuit_open(self, max_errors: int) -> bool:
        """Check whether the circuit breaker is triggered.

        Args:
            max_errors: Maximum allowed consecutive errors.

        Returns:
            True if the circuit breaker should trip.
        """
        return self.consecutive_errors >= max_errors

    def to_dict(self) -> dict[str, object]:
        """Serialise the session to a plain dictionary.

        Returns:
            Dictionary representation of the session.
        """
        return {
            "session_id": self.session_id,
            "task": self.task,
            "repo_path": self.repo_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_tokens": self.total_tokens,
        }
