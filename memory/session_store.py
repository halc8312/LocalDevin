"""SQLite-backed session and event store."""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionStore:
    """Persist sessions, events, and knowledge suggestions in SQLite.

    The store is safe for concurrent async usage via an ``asyncio.Lock``.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialise the store and create schema.

        Args:
            db_path: SQLite database path. Use ``:memory:`` for testing.
        """
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create database tables and indexes."""
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id           TEXT PRIMARY KEY,
                    task         TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    repo_path    TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL,
                    completed_at TEXT,
                    total_tokens INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_id    TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    data       TEXT NOT NULL DEFAULT '{}',
                    timestamp  TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS knowledge_suggestions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    suggestion TEXT NOT NULL,
                    status     TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_ks_session
                    ON knowledge_suggestions(session_id);
                """
            )

    async def create_session(
        self,
        task: str,
        repo_path: str,
        session_id: str | None = None,
    ) -> str:
        """Create a new session record.

        Args:
            task: Task description.
            repo_path: Repository path.
            session_id: Optional pre-generated UUID. A new one is created
                if not supplied.

        Returns:
            The session ID string.
        """
        import uuid

        sid = session_id or str(uuid.uuid4())
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (id, task, repo_path, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (sid, task, repo_path, datetime.now().isoformat()),
                )
        return sid

    async def update_status(self, session_id: str, status: str) -> None:
        """Update the status of a session.

        Args:
            session_id: Target session ID.
            status: New status string.
        """
        completed_at = (
            datetime.now().isoformat()
            if status in ("completed", "failed", "escalated")
            else None
        )
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET status=?, completed_at=? WHERE id=?",
                    (status, completed_at, session_id),
                )

    async def update_total_tokens(self, session_id: str, total_tokens: int) -> None:
        """Persist the total token count for a session.

        Args:
            session_id: Target session ID.
            total_tokens: Aggregated token count to store.
        """
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET total_tokens=? WHERE id=?",
                    (total_tokens, session_id),
                )

    async def get_session(self, session_id: str) -> dict[str, object] | None:
        """Return a single session row if it exists."""
        async with self._lock:
            with self._get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT id, task, status, repo_path, created_at,
                           completed_at, total_tokens
                    FROM sessions WHERE id = ?
                    """,
                    (session_id,),
                ).fetchone()
        return dict(row) if row is not None else None

    async def record_event(
        self,
        session_id: str,
        step_id: str,
        event_type: str,
        data: object,
    ) -> None:
        """Append an event to a session.

        Args:
            session_id: Target session ID.
            step_id: Plan step identifier (or a descriptive label).
            event_type: Short event type name.
            data: Serialisable event payload.
        """
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO events (session_id, step_id, event_type, data, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        step_id,
                        event_type,
                        json.dumps(data, default=str),
                        datetime.now().isoformat(),
                    ),
                )

    async def get_session_history(self, session_id: str) -> list[dict[str, object]]:
        """Retrieve all events for a session.

        Args:
            session_id: The session to query.

        Returns:
            List of event dicts ordered by timestamp.
        """
        async with self._lock:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT step_id, event_type, data, timestamp
                    FROM events WHERE session_id = ?
                    ORDER BY id
                    """,
                    (session_id,),
                ).fetchall()
        return [
            {
                "step_id": r["step_id"],
                "event_type": r["event_type"],
                "data": json.loads(r["data"]),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]

    async def get_recent_sessions(self, limit: int = 10) -> list[dict[str, object]]:
        """Return the most recently created sessions.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session dicts.
        """
        async with self._lock:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT id, task, status, repo_path, created_at,
                           completed_at, total_tokens
                    FROM sessions ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    async def add_knowledge_suggestion(
        self, session_id: str, suggestion: str
    ) -> None:
        """Record a knowledge suggestion for later review.

        Args:
            session_id: The session this suggestion comes from.
            suggestion: The knowledge suggestion text.
        """
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO knowledge_suggestions (session_id, suggestion, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, suggestion, datetime.now().isoformat()),
                )
