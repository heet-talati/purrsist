import sys
import time
from collections.abc import Mapping

from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

SUCCESS_STYLE = "bold #4FD1AE"
ERROR_STYLE = "bold #E8676B"
WARNING_STYLE = "bold #F0A857"
BRAND_STYLE = "bold #F0A857"
PRIMARY_STYLE = "bold"
MUTED_STYLE = "#7A7668"

ICON_SUCCESS = "✓"
ICON_ERROR = "[error]"
ICON_LOCKED = "🔒"
ICON_PLAY = "▶"
ICON_PAUSE = "▮▮"
ICON_STOP = "■"
ICON_BELL = "🔔"
ICON_STREAK = "🔥"

_ERROR_PREFIX = ICON_ERROR
_SUCCESS_PREFIX = ICON_SUCCESS
_WARNING_PREFIX = ICON_LOCKED


def _console() -> Console:
    # Rich probes the real Windows console handle for color support, which
    # ignores a Python-level sys.stdout swap (e.g. pytest's capsys) — force
    # terminal detection off of sys.stdout.isatty() instead so redirected
    # or captured output stays plain.
    is_tty = sys.stdout.isatty()
    return Console(
        highlight=False,
        # We never use Rich's `[style]...[/style]` markup syntax -- only
        # explicit `style=` kwargs and Text.stylize(). Disabling it means
        # arbitrary data (goal names, descriptions, delete reasons) can't
        # have literal square brackets like "[lock_in|hardcore|relaxed]"
        # silently swallowed as (invalid) markup tags.
        markup=False,
        force_terminal=is_tty,
        legacy_windows=False,
        # Non-tty output (piped, redirected, captured in tests) can't report a
        # real terminal width -- pick a generous fixed one so table/panel
        # content doesn't wrap mid-word at Rich's narrow fallback default.
        width=None if is_tty else 200,
    )


def print_cli(text, padding=1):
    indent = "  " * padding
    line = Text(indent + text)
    if text.startswith(_ERROR_PREFIX):
        line.stylize(ERROR_STYLE, len(indent), len(indent) + len(_ERROR_PREFIX))
    elif text.startswith(_SUCCESS_PREFIX):
        line.stylize(SUCCESS_STYLE, len(indent), len(indent) + len(_SUCCESS_PREFIX))
    elif text.startswith(_WARNING_PREFIX):
        line.stylize(WARNING_STYLE, len(indent), len(indent) + len(_WARNING_PREFIX))
    _console().print(line, soft_wrap=True)


def print_panel(content: str, *, subtitle: str | None = None) -> None:
    _console().print(Panel(content, border_style=BRAND_STYLE, subtitle=subtitle))


def render(renderable: RenderableType) -> None:
    """Print any Rich renderable (Table, Panel, ...) through the shared console."""
    _console().print(renderable)


def make_console() -> Console:
    """Public accessor for the shared console config, for callers (e.g. a
    Live-driven renderer) that need a Console instance directly rather than
    a one-shot print."""
    return _console()


def print_muted(text: str, padding: int = 1) -> None:
    indent = "  " * padding
    _console().print(Text(indent + text, style=f"{MUTED_STYLE} italic"))


def print_help_table(title: str, items: Mapping[str, str]) -> None:
    """2-column (command, description) help table shared by every `help` subcommand."""
    table = Table(title=title, title_style=PRIMARY_STYLE, box=None)
    table.add_column("Command", style=PRIMARY_STYLE)
    table.add_column("Description", style=MUTED_STYLE)
    for name, description in items.items():
        table.add_row(name, description)
    render(table)


_LOCK_IN_REVEAL_STYLES = ["#5C4526", "#A97A3D", WARNING_STYLE]


def print_warning_panel(content: str) -> None:
    """Warning-tier Panel with a brief reveal pulse on a real terminal.

    The lock-in trigger is a rare, meaningful moment (falling behind pace),
    so it earns a short animated reveal -- skipped entirely when not a real
    terminal (piped/redirected/tests) to avoid adding latency there.
    """
    if not sys.stdout.isatty():
        _console().print(Panel(content, border_style=WARNING_STYLE))
        return

    console = _console()
    with Live(console=console, transient=True, refresh_per_second=30) as live:
        for style in _LOCK_IN_REVEAL_STYLES:
            live.update(Panel(content, border_style=style))
            time.sleep(0.1)
    console.print(Panel(content, border_style=WARNING_STYLE))
