import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from purrsist.output import print_cli


class GoalError(ValueError):
    pass


@dataclass
class Goal:
    name: str
    hours: float
    active: bool = False
    priority: int | None = None
    created_at: str = ""
    id: int | None = None


def goals_db_path() -> Path:
    return Path.home() / ".purrsist" / "purrsist.db"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or goals_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            hours REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            priority INTEGER,
            created_at TEXT NOT NULL,
            CHECK (priority IS NULL OR priority BETWEEN 1 AND 3)
        )
        """
    )
    conn.commit()
    return conn


def add_goal(name: str, hours: float, db_path: Path | None = None) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")
    if hours <= 0:
        raise GoalError("Hours must be a positive number.")

    created_at = datetime.now(UTC).isoformat()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO goals (name, hours, active, priority, created_at) "
            "VALUES (?, ?, 0, NULL, ?)",
            (name, hours, created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise GoalError(f"A goal named '{name}' already exists.") from exc
    finally:
        conn.close()

    return Goal(id=cursor.lastrowid, name=name, hours=hours, created_at=created_at)


def _handle_add(options: list[str]) -> None:
    if len(options) < 2:
        print_cli("[error] Usage: goal add <hours> <name>")
        return

    hours_raw, *name_parts = options
    name = " ".join(name_parts)

    try:
        hours = float(hours_raw)
    except ValueError:
        print_cli(f"[error] '{hours_raw}' is not a valid number of hours.")
        return

    try:
        goal = add_goal(name, hours)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Added goal '{goal.name}' ({goal.hours}h)")


GOAL_SUBCOMMANDS = {
    "add": _handle_add,
}


def handle(options: list[str] | None = None) -> None:
    options = options or []
    if not options:
        print_cli(f"[error] Usage: goal <{'|'.join(GOAL_SUBCOMMANDS)}> ...")
        return

    subcommand, *rest = options
    subcommand_handler = GOAL_SUBCOMMANDS.get(subcommand)
    if subcommand_handler is None:
        print_cli(
            f"[error] Unknown goal subcommand '{subcommand}'. "
            f"Available: {', '.join(GOAL_SUBCOMMANDS)}"
        )
        return

    subcommand_handler(rest)
