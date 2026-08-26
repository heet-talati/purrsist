import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

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


def list_goals(db_path: Path | None = None) -> list[Goal]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals ORDER BY active DESC, priority ASC"
        ).fetchall()
    finally:
        conn.close()

    return [
        Goal(
            id=row[0],
            name=row[1],
            hours=row[2],
            active=bool(row[3]),
            priority=row[4],
            created_at=row[5],
        )
        for row in rows
    ]


def delete_goal(name: str, db_path: Path | None = None) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal named '{name}' found.")

        conn.execute("DELETE FROM goals WHERE id = ?", (row[0],))
        conn.commit()
    finally:
        conn.close()

    return Goal(
        id=row[0],
        name=row[1],
        hours=row[2],
        active=bool(row[3]),
        priority=row[4],
        created_at=row[5],
    )


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


def _handle_list(options: list[str]) -> None:
    all_goals = list_goals()
    if not all_goals:
        print_cli("No goals yet. Add one with 'goal add <hours> <name>'.")
        return

    active = [g for g in all_goals if g.active]
    inactive = [g for g in all_goals if not g.active]

    if active:
        print_cli("Active:")
        for goal in active:
            priority_str = f" [priority {goal.priority}]" if goal.priority else ""
            print_cli(f"- {goal.name} ({goal.hours}h){priority_str}", 2)

    if inactive:
        print_cli("Inactive:")
        for goal in inactive:
            print_cli(f"- {goal.name} ({goal.hours}h)", 2)


def _handle_delete(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal delete <name>")
        return

    name = " ".join(options)
    try:
        goal = delete_goal(name)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Deleted goal '{goal.name}'")


def _handle_help(options: list[str]) -> None:
    print_cli("Available goal subcommands:")
    for name, subcommand in GOAL_SUBCOMMANDS.items():
        print_cli(f"- {name}: {subcommand.description}", 2)


class _Subcommand(NamedTuple):
    description: str
    handler: Callable[[list[str]], None]


GOAL_SUBCOMMANDS = {
    "add": _Subcommand("Add a new goal: goal add <hours> <name>", _handle_add),
    "list": _Subcommand("List all goals", _handle_list),
    "delete": _Subcommand("Delete a goal: goal delete <name>", _handle_delete),
    "help": _Subcommand("List available goal subcommands", _handle_help),
}


def handle(options: list[str] | None = None) -> None:
    options = options or []
    if not options:
        print_cli(f"[error] Usage: goal <{'|'.join(GOAL_SUBCOMMANDS)}> ...")
        return

    subcommand_name, *rest = options
    subcommand = GOAL_SUBCOMMANDS.get(subcommand_name)
    if subcommand is None:
        print_cli(
            f"[error] Unknown goal subcommand '{subcommand_name}'. "
            f"Available: {', '.join(GOAL_SUBCOMMANDS)}"
        )
        return

    subcommand.handler(rest)
