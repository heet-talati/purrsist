import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from commands import db
from purrsist.output import print_cli

if sys.platform == "win32":
    import msvcrt

    def _default_poll_keypress() -> str | None:
        if msvcrt.kbhit():
            return msvcrt.getch().decode(errors="ignore").lower()
        return None
else:
    import select
    import termios
    import tty

    def _default_poll_keypress() -> str | None:
        if not sys.stdin.isatty():
            return None
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                return None
            return sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


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


def cancel_session(session_id: int, db_path: Path | None = None) -> Session:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"{_SESSION_SELECT} WHERE sessions.id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise TrackError(f"No session with id {session_id}.")
        if row[7] not in ("running", "paused"):
            raise TrackError(f"Session {session_id} is not active (status: {row[7]}).")

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


PAUSE_KEY = "p"
QUIT_KEY = "q"


class CountdownOutcome(NamedTuple):
    stopped_early: bool
    remaining_seconds: int
    total_paused_seconds: int


def run_countdown(
    session: Session,
    sleep_fn: Callable[[float], None] | None = None,
    write_fn: Callable[[str], None] | None = None,
    poll_keypress_fn: Callable[[], str | None] | None = None,
    on_pause: Callable[[], None] | None = None,
    on_resume: Callable[[int], None] | None = None,
) -> CountdownOutcome:
    """Run the countdown to completion or an early stop.

    All callables are resolved at call time (not bound as defaults) so
    tests can monkeypatch `tracking.time.sleep` etc. and have it take
    effect here.
    """
    sleep_fn = sleep_fn or time.sleep
    write_fn = write_fn or _default_write
    poll_keypress_fn = poll_keypress_fn or _default_poll_keypress
    on_pause = on_pause or (lambda: None)
    on_resume = on_resume or (lambda _delta: None)

    total_seconds = round(session.planned_minutes * 60)
    remaining = total_seconds
    paused = False
    segment_paused = 0
    total_paused = 0
    stopped_early = False
    last_len = 0

    def _write_line(content: str) -> None:
        nonlocal last_len
        write_fn("\r" + content.ljust(last_len))
        last_len = len(content)

    try:
        while remaining > 0:
            key = poll_keypress_fn()
            if key == QUIT_KEY:
                stopped_early = True
                break
            if key == PAUSE_KEY:
                paused = not paused
                if paused:
                    segment_paused = 0
                    on_pause()
                else:
                    on_resume(segment_paused)
                    total_paused += segment_paused

            if paused:
                _write_line(
                    f"  PAUSED — {session.goal_name} "
                    f"({_format_remaining(remaining)} left, press 'p' to resume, "
                    f"'q' to stop)"
                )
                sleep_fn(TICK_SECONDS)
                segment_paused += TICK_SECONDS
                continue

            _write_line(
                f"  {_format_remaining(remaining)} remaining — {session.goal_name}"
            )
            sleep_fn(TICK_SECONDS)
            remaining -= TICK_SECONDS
    except KeyboardInterrupt:
        stopped_early = True

    if paused:
        # Quit while paused: the in-progress pause segment never got folded
        # into total_paused via on_resume, so fold it in now.
        total_paused += segment_paused

    write_fn("\r" + " " * last_len + "\r")
    return CountdownOutcome(
        stopped_early=stopped_early,
        remaining_seconds=remaining,
        total_paused_seconds=total_paused,
    )


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
    session_id: int = session.id

    def _on_pause() -> None:
        pause_session(session_id)

    def _on_resume(delta: int) -> None:
        resume_session(session_id, delta)

    print_cli(
        f"▶ Tracking '{session.goal_name}' for {minutes:g} min. "
        f"Press '{PAUSE_KEY}' to pause, '{QUIT_KEY}' to stop early "
        f"(Ctrl+C also works)."
    )
    outcome = run_countdown(session, on_pause=_on_pause, on_resume=_on_resume)

    planned_seconds = round(minutes * 60)
    actual_seconds = (
        planned_seconds - outcome.remaining_seconds - outcome.total_paused_seconds
    )
    actual_str = _format_remaining(actual_seconds)
    planned_str = _format_remaining(planned_seconds)

    if outcome.stopped_early:
        cancelled = cancel_session(session_id)
        print_cli(
            f"■ Stopped '{cancelled.goal_name}' early — "
            f"{actual_str} focused (planned {planned_str})"
        )
    else:
        completed = complete_session(session_id)
        print_cli(
            f"✓ Session complete for '{completed.goal_name}' — "
            f"{actual_str} focused (planned {planned_str})"
        )


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
