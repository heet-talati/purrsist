import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from commands import db
from purrsist.output import print_cli


class TrackError(ValueError):
    pass


DEFAULT_MINUTES = 25.0
TICK_SECONDS = 1


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
    )


_SESSION_SELECT = (
    "SELECT sessions.id, goal_id, goals.name, planned_minutes, started_at, "
    "ended_at, paused_seconds, status FROM sessions "
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
            "SELECT id, active FROM goals WHERE name = ? COLLATE NOCASE",
            (goal_name,),
        ).fetchone()
        if row is None:
            raise TrackError(f"No goal named '{goal_name}' found.")
        goal_id, active = row
        if not active:
            raise TrackError(
                f"'{goal_name}' is not active. "
                f"Activate it first with 'goal priority {goal_name}'."
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
        goal_name=goal_name,
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

        ended_at = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'completed' WHERE id = ?",
            (ended_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.ended_at = ended_at
    session.status = "completed"
    return session


def cancel_session(session_id: int, db_path: Path | None = None) -> Session:
    conn = _connect(db_path)
    try:
        row = _get_running_session(conn, session_id)

        ended_at = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'cancelled' WHERE id = ?",
            (ended_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    session = _row_to_session(row)
    session.ended_at = ended_at
    session.status = "cancelled"
    return session


def _format_remaining(seconds_left: int) -> str:
    minutes, seconds = divmod(max(seconds_left, 0), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _default_write(line: str) -> None:
    print(line, end="", flush=True)


def run_countdown(
    session: Session,
    sleep_fn: Callable[[float], None] | None = None,
    write_fn: Callable[[str], None] | None = None,
) -> None:
    # Resolved at call time (not bound as a default) so tests can
    # monkeypatch `tracking.time.sleep` and have it take effect here.
    sleep_fn = sleep_fn or time.sleep
    write_fn = write_fn or _default_write

    total_seconds = round(session.planned_minutes * 60)
    remaining = total_seconds
    while remaining > 0:
        write_fn(
            f"\r  {_format_remaining(remaining)} remaining — {session.goal_name}  "
        )
        sleep_fn(TICK_SECONDS)
        remaining -= TICK_SECONDS
    write_fn("\r" + " " * 60 + "\r")


def _parse_start_args(options: list[str]) -> tuple[str, float]:
    minutes = DEFAULT_MINUTES
    name_tokens = options
    if len(options) > 1:
        *rest, maybe_minutes = options
        try:
            minutes = float(maybe_minutes)
            name_tokens = rest
        except ValueError:
            pass
    return " ".join(name_tokens), minutes


def _handle_start(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: track start <goal_name> [minutes]")
        return

    name, minutes = _parse_start_args(options)

    try:
        session = start_session(name, minutes)
    except TrackError as exc:
        print_cli(f"[error] {exc}")
        return
    assert session.id is not None  # always set by start_session's INSERT

    print_cli(
        f"▶ Tracking '{session.goal_name}' for {minutes:g} min. Press Ctrl+C to stop early."
    )
    try:
        run_countdown(session)
    except KeyboardInterrupt:
        print()
        cancelled = cancel_session(session.id)
        print_cli(f"■ Stopped '{cancelled.goal_name}' early.")
        return

    completed = complete_session(session.id)
    print_cli(f"✓ Session complete for '{completed.goal_name}' ({minutes:g} min)")


def _handle_help(options: list[str]) -> None:
    print_cli("Available track subcommands:")
    for name, subcommand in TRACK_SUBCOMMANDS.items():
        print_cli(f"- {name}: {subcommand.description}", 2)


class _Subcommand(NamedTuple):
    description: str
    handler: Callable[[list[str]], None]


TRACK_SUBCOMMANDS = {
    "start": _Subcommand(
        "Start a timer for a goal: track start <goal_name> [minutes]", _handle_start
    ),
    "help": _Subcommand("List available track subcommands", _handle_help),
}


def handle(options: list[str] | None = None) -> None:
    options = options or []
    if not options:
        print_cli(f"[error] Usage: track <{'|'.join(TRACK_SUBCOMMANDS)}> ...")
        return

    subcommand_name, *rest = options
    subcommand = TRACK_SUBCOMMANDS.get(subcommand_name)
    if subcommand is None:
        print_cli(
            f"[error] Unknown track subcommand '{subcommand_name}'. "
            f"Available: {', '.join(TRACK_SUBCOMMANDS)}"
        )
        return

    subcommand.handler(rest)
