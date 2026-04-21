"""Token usage tracker – ACU-style accounting for local sessions."""

import asyncio
import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

# Session size thresholds (total tokens)
_SIZE_THRESHOLDS = [
    (20_000, "XS"),
    (50_000, "S"),
    (100_000, "M"),
    (200_000, "L"),
]
_XL_LABEL = "XL"


def _classify_size(total_tokens: int) -> str:
    """Classify a token count into a session-size label.

    Args:
        total_tokens: Total tokens consumed in the session.

    Returns:
        Size label: ``XS``, ``S``, ``M``, ``L``, or ``XL``.
    """
    for threshold, label in _SIZE_THRESHOLDS:
        if total_tokens <= threshold:
            return label
    return _XL_LABEL


class TokenTracker:
    """Tracks token usage per session using SQLite.

    Imitates Devin's ACU (Agent Compute Unit) tracking to give visibility
    into model usage and cost across sessions.
    """

    def __init__(self, db_path: str = ":memory:", max_session_tokens: int = 500_000) -> None:
        """Initialise the tracker and create the database schema.

        Args:
            db_path: Path to the SQLite database file.
                Use ``:memory:`` for an in-memory database (e.g. in tests).
            max_session_tokens: Token limit above which a warning is emitted.
        """
        self._db_path = db_path
        self._max_session_tokens = max_session_tokens
        self._lock = asyncio.Lock()
        # For in-memory databases keep a single persistent connection so that
        # the schema created in _init_db() is visible to all later operations.
        self._in_memory_conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._in_memory_conn is None:
                self._in_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._in_memory_conn.row_factory = sqlite3.Row
            return self._in_memory_conn
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the token usage table if it does not exist."""
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL,
                    model       TEXT    NOT NULL,
                    prompt_tokens      INTEGER NOT NULL DEFAULT 0,
                    completion_tokens  INTEGER NOT NULL DEFAULT 0,
                    total_tokens       INTEGER NOT NULL DEFAULT 0,
                    recorded_at TEXT    NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tu_session ON token_usage(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tu_date ON token_usage(recorded_at)"
            )

    async def record(
        self,
        session_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Record token usage for a single LLM call.

        Args:
            session_id: The session this usage belongs to.
            model: The model that was called.
            prompt_tokens: Number of tokens in the prompt.
            completion_tokens: Number of tokens in the completion.
        """
        total = prompt_tokens + completion_tokens
        async with self._lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO token_usage
                        (session_id, model, prompt_tokens, completion_tokens,
                         total_tokens, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        model,
                        prompt_tokens,
                        completion_tokens,
                        total,
                        datetime.now().isoformat(),
                    ),
                )
        session_total = await self.get_session_total(session_id)
        if session_total["total_tokens"] > self._max_session_tokens:
            logger.warning(
                "Session %s exceeded token limit: %d > %d",
                session_id,
                session_total["total_tokens"],
                self._max_session_tokens,
            )

    async def get_session_total(self, session_id: str) -> dict[str, object]:
        """Return aggregated token usage for a session.

        Args:
            session_id: The session to query.

        Returns:
            Dictionary with ``session_id``, ``total_tokens``, ``prompt_tokens``,
            ``completion_tokens``, and ``size`` keys.
        """
        async with self._lock:
            with self._get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT
                        SUM(prompt_tokens)     AS prompt_tokens,
                        SUM(completion_tokens) AS completion_tokens,
                        SUM(total_tokens)      AS total_tokens
                    FROM token_usage WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
        total = int(row["total_tokens"] or 0)
        return {
            "session_id": session_id,
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "total_tokens": total,
            "size": _classify_size(total),
        }

    async def get_daily_total(self) -> dict[str, object]:
        """Return aggregated token usage for today.

        Returns:
            Dictionary with ``date``, ``total_tokens``, and per-model breakdown.
        """
        today = date.today().isoformat()
        async with self._lock:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT model,
                           SUM(prompt_tokens)     AS prompt_tokens,
                           SUM(completion_tokens) AS completion_tokens,
                           SUM(total_tokens)      AS total_tokens
                    FROM token_usage
                    WHERE recorded_at LIKE ?
                    GROUP BY model
                    """,
                    (f"{today}%",),
                ).fetchall()
        breakdown = [
            {
                "model": r["model"],
                "prompt_tokens": int(r["prompt_tokens"]),
                "completion_tokens": int(r["completion_tokens"]),
                "total_tokens": int(r["total_tokens"]),
            }
            for r in rows
        ]
        grand_total = sum(r["total_tokens"] for r in breakdown)
        return {
            "date": today,
            "total_tokens": grand_total,
            "breakdown": breakdown,
        }
