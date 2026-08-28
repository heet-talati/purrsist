import sys
import time
from collections.abc import Callable
from typing import NamedTuple

from rich.console import Group, NewLine, RenderableType
from rich.live import Live
from rich.padding import Padding
from rich.progress_bar import ProgressBar
from rich.text import Text

from commands import goals
from purrsist.output import (
    ERROR_STYLE,
    ICON_BELL,
    ICON_PAUSE,
    ICON_PLAY,
    ICON_STOP,
    MUTED_STYLE,
    SUCCESS_STYLE,
    WARNING_STYLE,
    make_console,
    print_cli,
    print_help_table,
)

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


PAUSE_KEY = "p"
QUIT_KEY = "q"

_URGENT_SECONDS = 60
_CRITICAL_SECONDS = 15


class CountdownOutcome(NamedTuple):
    stopped_early: bool
    remaining_seconds: int
    total_paused_seconds: int


def _countdown_style(remaining: int, paused: bool) -> str:
    if paused:
        return MUTED_STYLE
    if remaining <= _CRITICAL_SECONDS:
        return ERROR_STYLE
    if remaining <= _URGENT_SECONDS:
        return WARNING_STYLE
    return SUCCESS_STYLE


def _countdown_renderable(
    remaining: int, total: int, paused: bool, goal_name: str
) -> RenderableType:
    style = _countdown_style(remaining, paused)
    elapsed = max(total - remaining, 0)
    bar = ProgressBar(
        total=total or 1, completed=elapsed, complete_style=style, finished_style=style
    )

    timer_style = style if style.startswith("bold") else f"bold {style}"
    digits = " ".join(_format_remaining(remaining))
    timer = Padding(Text(digits, style=timer_style, justify="center"), (1, 0))

    if paused:
        label = f"{ICON_PAUSE} PAUSED — {goal_name} (press 'p' to resume, 'q' to stop)"
    else:
        label = f"remaining — {goal_name}"
    return Group(
        timer, bar, NewLine(), Text(label, style=MUTED_STYLE, justify="center")
    )


def _make_default_render(
    total_seconds: int, goal_name: str
) -> tuple[Callable[[int, bool], None], Callable[[bool], None]]:
    """Build the default per-tick renderer, gated on a real terminal.

    Returns (render_fn, close_fn); close_fn must be called once when the
    countdown ends. On a real terminal it drives a transient Live progress
    bar (with a brief 100%-pulse flourish on natural completion); otherwise
    it falls back to one printed line per tick, since there's no cursor to
    animate in piped/redirected/captured output.
    """
    if not sys.stdout.isatty():

        def _plain_render(remaining: int, paused: bool) -> None:
            if paused:
                print_cli(
                    f"{ICON_PAUSE} PAUSED — {goal_name} "
                    f"({_format_remaining(remaining)} left, press 'p' to resume, "
                    f"'q' to stop)"
                )
            else:
                print_cli(f"{_format_remaining(remaining)} remaining — {goal_name}")

        return _plain_render, lambda _completed_naturally: None

    live = Live(console=make_console(), transient=True, refresh_per_second=10)
    live.start()

    def _render(remaining: int, paused: bool) -> None:
        live.update(_countdown_renderable(remaining, total_seconds, paused, goal_name))

    def _close(completed_naturally: bool) -> None:
        if completed_naturally:
            live.update(_countdown_renderable(0, total_seconds, False, goal_name))
            time.sleep(0.3)
        live.stop()

    return _render, _close


def run_countdown(
    session: Session,
    sleep_fn: Callable[[float], None] | None = None,
    render_fn: Callable[[int, bool], None] | None = None,
    poll_keypress_fn: Callable[[], str | None] | None = None,
    on_pause: Callable[[], None] | None = None,
    on_resume: Callable[[int], None] | None = None,
) -> CountdownOutcome:
    """Run the countdown to completion or an early stop.

    All callables are resolved at call time (not bound as defaults) so
    tests can monkeypatch `tracking.time.sleep` etc. and have it take
    effect here. `render_fn` is called once per tick with
    (remaining_seconds, paused); when omitted, the default renderer (and
    its `close_fn`, invoked once the countdown ends) is built internally.
    """
    sleep_fn = sleep_fn or time.sleep
    poll_keypress_fn = poll_keypress_fn or _default_poll_keypress
    on_pause = on_pause or (lambda: None)
    on_resume = on_resume or (lambda _delta: None)

    total_seconds = round(session.planned_minutes * 60)
    remaining = total_seconds
    paused = False
    segment_paused = 0
    total_paused = 0
    stopped_early = False

    close_fn: Callable[[bool], None] | None = None
    if render_fn is None:
        render_fn, close_fn = _make_default_render(total_seconds, session.goal_name)

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

            render_fn(remaining, paused)

            if paused:
                sleep_fn(TICK_SECONDS)
                segment_paused += TICK_SECONDS
                continue

            sleep_fn(TICK_SECONDS)
            remaining -= TICK_SECONDS
    except KeyboardInterrupt:
        stopped_early = True

    if paused:
        # Quit while paused: the in-progress pause segment never got folded
        # into total_paused via on_resume, so fold it in now.
        total_paused += segment_paused

    if close_fn is not None:
        close_fn(not stopped_early)

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
        f"{ICON_PLAY} Tracking '{session.goal_name}' for {minutes:g} min. "
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
            f"{ICON_STOP} Stopped '{cancelled.goal_name}' early — "
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
    print_cli(f"{ICON_BELL} TIME'S UP! Session complete for '{goal_name}'", 0)
    print_cli(f"{actual_str} focused (planned {planned_str})", 0)
    print_cli(border, 0)


def _handle_help(options: list[str]) -> None:
    print_help_table(
        "track usage:",
        {
            f"track <goal_name> [{'|'.join(PRESETS)}|minutes]": (
                f"Start a timer for a goal (default: pomodoro, {DEFAULT_MINUTES:g} min)"
            ),
            "track help": "Show this help",
        },
    )


def handle(options: list[str] | None = None) -> None:
    options = options or []
    if not options:
        print_cli(f"[error] Usage: track <goal_name> [{'|'.join(PRESETS)}|minutes]")
        return

    if options[0] == "help":
        _handle_help(options[1:])
        return

    _handle_start(options)
