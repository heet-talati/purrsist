import sys
import time
from collections.abc import Callable
from typing import NamedTuple

from commands import goals
from purrsist.output import print_cli

from .tracking_data import (
    Session,
    TrackError,
    cancel_session,
    complete_session,
    current_streak_days,
    pause_session,
    resume_session,
    sessions_db_path,
    start_session,
)

__all__ = [
    "Session",
    "TrackError",
    "cancel_session",
    "complete_session",
    "current_streak_days",
    "handle",
    "pause_session",
    "resume_session",
    "run_countdown",
    "sessions_db_path",
    "start_session",
]

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


DEFAULT_MINUTES = 25.0
TICK_SECONDS = 1

PRESETS: dict[str, float] = {
    "pomodoro": DEFAULT_MINUTES,
    "short": 15.0,
}


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
        *rest, last = options
        preset_minutes = PRESETS.get(last.lower())
        if preset_minutes is not None:
            minutes = preset_minutes
            name_tokens = rest
        else:
            try:
                minutes = float(last)
                name_tokens = rest
            except ValueError:
                pass
    return " ".join(name_tokens), minutes


def _handle_start(options: list[str]) -> None:
    if not options:
        print_cli(
            f"[error] Usage: track start <goal_name> [{'|'.join(PRESETS)}|minutes]"
        )
        return

    name, minutes = _parse_start_args(options)

    goals.refresh_lock_in()

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
    planned_str = _format_remaining(planned_seconds)

    if outcome.stopped_early:
        cancelled = cancel_session(
            session_id, outcome.remaining_seconds, outcome.total_paused_seconds
        )
        actual_str = _format_remaining(cancelled.focused_seconds or 0)
        print_cli(
            f"■ Stopped '{cancelled.goal_name}' early — "
            f"{actual_str} focused (planned {planned_str})"
        )
    else:
        completed = complete_session(session_id)
        actual_str = _format_remaining(completed.focused_seconds or 0)
        _print_completion_banner(completed.goal_name, actual_str, planned_str)


def _print_completion_banner(goal_name: str, actual_str: str, planned_str: str) -> None:
    """Bell + bordered banner on natural completion, distinct from the
    early-stop summary line, so it's noticeable even away from the screen."""
    print("\a", end="", flush=True)
    border = "=" * 50
    print_cli(border, 0)
    print_cli(f"\U0001f514 TIME'S UP! Session complete for '{goal_name}'", 0)
    print_cli(f"{actual_str} focused (planned {planned_str})", 0)
    print_cli(border, 0)


def _handle_help(options: list[str]) -> None:
    print_cli("Available track subcommands:")
    for name, subcommand in TRACK_SUBCOMMANDS.items():
        print_cli(f"- {name}: {subcommand.description}", 2)


class _Subcommand(NamedTuple):
    description: str
    handler: Callable[[list[str]], None]


TRACK_SUBCOMMANDS = {
    "start": _Subcommand(
        "Start a timer for a goal: track start <goal_name> "
        f"[{'|'.join(PRESETS)}|minutes] (default: pomodoro, {DEFAULT_MINUTES:g} min)",
        _handle_start,
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
