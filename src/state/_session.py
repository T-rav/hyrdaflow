"""Session persistence (sessions.jsonl) and session counters."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from file_util import atomic_write
from models import SessionCounters, SessionLog, SessionStatus

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")


class SessionStateMixin:
    """Methods for session JSONL persistence and session counters."""

    _data: StateData
    _path: Path

    def save(self) -> None: ...  # provided by CoreMixin

    # --- session counters ---

    _SESSION_COUNTER_FIELDS = frozenset(
        {"triaged", "planned", "implemented", "reviewed", "merged"}
    )

    def increment_session_counter(self, stage: str) -> None:
        """Increment the session counter for *stage* and persist.

        Unknown stage names are silently ignored.
        """
        if stage not in self._SESSION_COUNTER_FIELDS:
            return
        sc = self._data.session_counters
        setattr(sc, stage, getattr(sc, stage) + 1)
        self.save()

    def get_session_counters(self) -> SessionCounters:
        """Return a copy of the current session counters."""
        return self._data.session_counters.model_copy()

    def reset_session_counters(self, session_start: str) -> None:
        """Replace session counters with a fresh instance and persist."""
        self._data.session_counters = SessionCounters(session_start=session_start)
        self.save()

    def compute_session_throughput(self) -> dict[str, float]:
        """Compute issues/hour per stage from session counters and uptime.

        Returns a dict with keys matching the counter fields, values in issues/hour.
        Returns all zeros if session_start is empty or unparseable.
        """
        sc = self._data.session_counters
        if not sc.session_start:
            return dict.fromkeys(self._SESSION_COUNTER_FIELDS, 0.0)
        try:
            started = datetime.fromisoformat(sc.session_start)
        except (ValueError, TypeError):
            return dict.fromkeys(self._SESSION_COUNTER_FIELDS, 0.0)
        uptime_hours = (datetime.now(UTC) - started).total_seconds() / 3600.0
        uptime_hours = max(uptime_hours, 0.001)  # avoid division by near-zero
        return {
            f: round(getattr(sc, f) / uptime_hours, 2)
            for f in self._SESSION_COUNTER_FIELDS
        }

    # --- session persistence ---

    @property
    def _sessions_path(self) -> Path:
        return self._path.parent / "sessions.jsonl"

    def _load_sessions_deduped(self) -> dict[str, SessionLog]:
        """Read sessions.jsonl and return a deduped dict keyed by session ID.

        Uses last-write-wins: later entries for the same ID overwrite earlier ones.
        Returns empty dict if the file does not exist.
        """
        if not self._sessions_path.exists():
            return {}
        seen: dict[str, SessionLog] = {}
        try:
            with open(self._sessions_path) as f:
                for line_num, raw_line in enumerate(f, 1):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        session = SessionLog.model_validate_json(stripped)
                    except ValidationError:
                        logger.warning(
                            "Skipping corrupt session line %d in %s",
                            line_num,
                            self._sessions_path,
                            exc_info=True,
                        )
                        continue
                    seen[session.id] = session
        except (OSError, UnicodeDecodeError):
            logger.warning(
                "Could not open sessions file %s",
                self._sessions_path,
                exc_info=True,
            )
            return {}
        return seen

    def _write_sessions(self, sessions: list[SessionLog]) -> None:
        """Atomically rewrite sessions.jsonl with the given sessions.

        Sessions are written sorted by started_at (oldest first).
        """
        result = sorted(sessions, key=lambda s: s.started_at)
        content = "\n".join(s.model_dump_json() for s in result)
        if content:
            content += "\n"
        atomic_write(self._sessions_path, content)

    def save_session(self, session: SessionLog) -> None:
        """Append a session log entry to sessions.jsonl."""
        try:
            self._sessions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._sessions_path, "a") as f:
                f.write(session.model_dump_json() + "\n")
                f.flush()
        except OSError:
            logger.warning(
                "Could not save session to %s",
                self._sessions_path,
                exc_info=True,
            )

    def load_sessions(
        self, repo: str | None = None, limit: int = 50
    ) -> list[SessionLog]:
        """Read sessions from JSONL, optionally filtered by repo.

        Returns up to *limit* entries sorted newest-first.
        Deduplicates by session ID, keeping the last-written (most complete) entry.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return []
        sessions = [s for s in seen.values() if repo is None or s.repo == repo]
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions[:limit]

    def get_session(self, session_id: str) -> SessionLog | None:
        """Return a single session by ID, or None.

        Scans the full file and returns the last-written entry for the given ID
        so that a session updated on close (status=completed) takes precedence
        over the initial entry written at session start (status=active).
        """
        return self._load_sessions_deduped().get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a single session by ID from sessions.jsonl.

        Returns True if the session was found and deleted, False otherwise.
        Raises ValueError if the session is currently active.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return False

        target = seen.get(session_id)
        if target is None:
            return False
        if target.status == SessionStatus.ACTIVE:
            msg = f"Cannot delete active session {session_id}"
            raise ValueError(msg)

        del seen[session_id]
        self._write_sessions(list(seen.values()))
        return True

    def prune_sessions(self, repo: str, max_keep: int) -> None:
        """Remove oldest sessions for *repo* beyond *max_keep*.

        Sessions from other repos are preserved. Uses atomic rewrite.
        """
        seen = self._load_sessions_deduped()
        if not seen:
            return

        all_sessions = list(seen.values())
        repo_sessions = [s for s in all_sessions if s.repo == repo]
        other_sessions = [s for s in all_sessions if s.repo != repo]

        repo_sessions.sort(key=lambda s: s.started_at, reverse=True)
        kept = repo_sessions[:max_keep]

        self._write_sessions(other_sessions + kept)
