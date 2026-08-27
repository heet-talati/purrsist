import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from commands import db


class TrackError(ValueError):
    pass


@dataclass
class Session:
    goal_id: int
    goal_name: str
    planned_minutes: float
    started_at: str
    ended_at: str | None = None
    paused_seconds: int = 0
    status: str = "running"
    id: int | None = None
    focused_seconds: int | None = None


def sessions_db_path() -> Path:
    return Path.home() / ".purrsist" / "purrsist.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or sessions_db_path()
    return db.connect(path)


def _row_to_session(row: tuple) -> Session:
    return Session(
        id=row[0],
        goal_id=row[1],
        goal_name=row[2],
        planned_minutes=row[3],
        started_at=row[4],
        ended_at=row[5],
        paused_seconds=row[6],
        status=row[7],
        focused_seconds=row[8],
    )


_SESSION_SELECT = (
    "SELECT sessions.id, goal_id, goals.name, planned_minutes, started_at, "
    "ended_at, paused_seconds, status, focused_seconds FROM sessions "
    "JOIN goals ON goals.id = sessions.goal_id"
)


def start_session(
    goal_name: str, planned_minutes: float, db_path: Path | None = None
) -> Session:
    goal_name = goal_name.strip()
    if not goal_name:
        raise TrackError("Goal name cannot be empty.")
    if planned_minutes <= 0:
        raise TrackError("Minutes must be a positive number.")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, active FROM goals WHERE name = ? COLLATE NOCASE",
            (goal_name,),
        ).fetchone()
        if row is None:
            raise TrackError(f"No goal named '{goal_name}' found.")
        goal_id, stored_name, active = row
        if not active:
            raise TrackError(
                f"'{stored_name}' is not active. "
                f"Activate it first with 'goal priority {stored_name}'."
            )

        started_at = datetime.now(UTC).isoformat()
        cursor = conn.execute(
            "INSERT INTO sessions (goal_id, planned_minutes, started_at, status) "
            "VALUES (?, ?, ?, 'running')",
            (goal_id, planned_minutes, started_at),
        )
        conn.commit()
    finally:
        conn.close()

    return Session(
        id=cursor.lastrowid,
        goal_id=goal_id,
        goal_name=stored_name,
        planned_minutes=planned_minutes,
        started_at=started_at,
    )


def _get_running_session(conn: sqlite3.Connection, session_id: int) -> tuple:
    row = conn.execute(
        f"{_SESSION_SELECT} WHERE sessions.id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise TrackError(f"No session with id {session_id}.")
    if row[7] != "running":
        raise TrackError(f"Session {session_id} is not running (status: {row[7]}).")
    return row


def complete_session(session_id: int, db_path: Path | None = None) -> Session:
    conn = _connect(db_path)
    try:
        row = _get_running_session(conn, session_id)

        # Natural completion means the countdown ran out, so no time is left.
        planned_seconds = round(row[3] * 60)
        paused_seconds = row[6]
        focused_seconds = planned_seconds - paused_seconds

        ended_at = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'completed', "
            "focused_seconds = ? WHERE id = ?",
            (ended_at, focused_seconds, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.ended_at = ended_at
    session.status = "completed"
    session.focused_seconds = focused_seconds
    return session


def pause_session(session_id: int, db_path: Path | None = None) -> Session:
    conn = _connect(db_path)
    try:
        row = _get_running_session(conn, session_id)
        conn.execute(
            "UPDATE sessions SET status = 'paused' WHERE id = ?", (session_id,)
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.status = "paused"
    return session


def resume_session(
    session_id: int, paused_seconds_delta: int, db_path: Path | None = None
) -> Session:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"{_SESSION_SELECT} WHERE sessions.id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise TrackError(f"No session with id {session_id}.")
        if row[7] != "paused":
            raise TrackError(f"Session {session_id} is not paused (status: {row[7]}).")

        new_paused_seconds = row[6] + paused_seconds_delta
        conn.execute(
            "UPDATE sessions SET status = 'running', paused_seconds = ? WHERE id = ?",
            (new_paused_seconds, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.status = "running"
    session.paused_seconds = new_paused_seconds
    return session


def cancel_session(
    session_id: int,
    remaining_seconds: int = 0,
    total_paused_seconds: int | None = None,
    db_path: Path | None = None,
) -> Session:
    """Cancel a running/paused session.

    `total_paused_seconds`, when given, overrides the DB's `paused_seconds`
    column -- a quit while paused folds the in-progress pause segment into
    the countdown's in-memory total before `on_resume` ever fires to persist
    it, so the caller's live total is the authoritative one.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"{_SESSION_SELECT} WHERE sessions.id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise TrackError(f"No session with id {session_id}.")
        if row[7] not in ("running", "paused"):
            raise TrackError(f"Session {session_id} is not active (status: {row[7]}).")

        paused_seconds = (
            row[6] if total_paused_seconds is None else total_paused_seconds
        )
        planned_seconds = round(row[3] * 60)
        focused_seconds = planned_seconds - remaining_seconds - paused_seconds

        ended_at = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'cancelled', "
            "paused_seconds = ?, focused_seconds = ? WHERE id = ?",
            (ended_at, paused_seconds, focused_seconds, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.ended_at = ended_at
    session.status = "cancelled"
    session.paused_seconds = paused_seconds
    session.focused_seconds = focused_seconds
    return session
