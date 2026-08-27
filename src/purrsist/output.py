import sys

from rich.console import Console
from rich.panel import Panel
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
    return Console(
        highlight=False, force_terminal=sys.stdout.isatty(), legacy_windows=False
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
