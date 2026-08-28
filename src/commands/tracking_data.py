import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
    log_content: str | None = None


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


def list_sessions(
    goal_id: int | None = None, db_path: Path | None = None
) -> list[Session]:
    query = (
        "SELECT sessions.id, goal_id, goals.name, planned_minutes, "
        "started_at, ended_at, paused_seconds, status, focused_seconds, "
        "logs.content FROM sessions "
        "JOIN goals ON goals.id = sessions.goal_id "
        "LEFT JOIN logs ON logs.session_id = sessions.id "
    )
    params: tuple[int, ...] = ()
    if goal_id is not None:
        query += "WHERE sessions.goal_id = ? "
        params = (goal_id,)
    query += "ORDER BY sessions.id"

    conn = _connect(db_path)
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    sessions = []
    for row in rows:
        session = _row_to_session(row)
        session.log_content = row[9]
        sessions.append(session)
    return sessions


def upsert_log(session_id: int, content: str, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        session_row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session_row is None:
            raise TrackError(f"No session with id {session_id}.")

        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO logs (session_id, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET content = excluded.content, "
            "updated_at = excluded.updated_at",
            (session_id, content, now, now),
        )
        conn.commit()
    finally:
        conn.close()


_STREAK_MIN_FOCUSED_SECONDS = 900  # 15 minutes


def current_streak_days(db_path: Path | None = None) -> int:
    """Consecutive calendar days (UTC) that qualify for the streak: the
    "cat stays hungry" mechanic -- a day only counts if it has at least one
    logged session AND >= 15 focused minutes total across that day's
    sessions (a daily total, not a single session's minimum).

    A missed *today* doesn't break the streak until the day actually ends --
    it's counted from yesterday backward if today has no qualifying day yet.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT sessions.started_at, sessions.focused_seconds, logs.id "
            "FROM sessions LEFT JOIN logs ON logs.session_id = sessions.id "
            "WHERE sessions.status IN ('completed', 'cancelled')"
        ).fetchall()
    finally:
        conn.close()

    focused_by_date: dict[date, int] = {}
    logged_dates: set[date] = set()
    for started_at, focused_seconds, log_id in rows:
        day = datetime.fromisoformat(started_at).date()
        focused_by_date[day] = focused_by_date.get(day, 0) + (focused_seconds or 0)
        if log_id is not None:
            logged_dates.add(day)

    active_dates = {
        day
        for day, total_focused in focused_by_date.items()
        if day in logged_dates and total_focused >= _STREAK_MIN_FOCUSED_SECONDS
    }
    if not active_dates:
        return 0

    today = datetime.now(UTC).date()
    cursor_date = today if today in active_dates else today - timedelta(days=1)

    streak = 0
    while cursor_date in active_dates:
        streak += 1
        cursor_date -= timedelta(days=1)
    return streak
