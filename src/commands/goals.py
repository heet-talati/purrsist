import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from commands import db
from purrsist.output import print_cli


class GoalError(ValueError):
    pass


MODE_LIMITS = {"lock_in": 1, "hardcore": 2, "relaxed": 3}
DEFAULT_MODE = db.DEFAULT_MODE


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
    return db.connect(path)


def get_mode(db_path: Path | None = None) -> str:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT mode FROM app_settings WHERE id = 1").fetchone()
    finally:
        conn.close()
    mode: str = row[0]
    return mode


def set_mode(mode: str, db_path: Path | None = None) -> tuple[list[Goal], list[Goal]]:
    """Switch mode, auto-(de)activating goals to fit the new limit.

    Priority is retained (not cleared) across the flip, so a goal demoted by
    a stricter mode comes back automatically if a looser mode is set later.
    Returns (deactivated, reactivated) goals for the caller to report.
    """
    if mode not in MODE_LIMITS:
        raise GoalError(f"Unknown mode '{mode}'. Choose from: {', '.join(MODE_LIMITS)}")

    limit = MODE_LIMITS[mode]
    conn = _connect(db_path)
    try:
        deactivated_rows = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals WHERE active = 1 AND priority > ?",
            (limit,),
        ).fetchall()
        for row in deactivated_rows:
            conn.execute("UPDATE goals SET active = 0 WHERE id = ?", (row[0],))

        reactivated_rows = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals WHERE active = 0 AND priority IS NOT NULL AND priority <= ?",
            (limit,),
        ).fetchall()
        for row in reactivated_rows:
            conn.execute("UPDATE goals SET active = 1 WHERE id = ?", (row[0],))

        conn.execute("UPDATE app_settings SET mode = ? WHERE id = 1", (mode,))
        conn.commit()
    finally:
        conn.close()

    deactivated = [
        Goal(
            id=r[0], name=r[1], hours=r[2], active=False, priority=r[4], created_at=r[5]
        )
        for r in deactivated_rows
    ]
    reactivated = [
        Goal(
            id=r[0], name=r[1], hours=r[2], active=True, priority=r[4], created_at=r[5]
        )
        for r in reactivated_rows
    ]
    return deactivated, reactivated


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
        if row[3]:  # was active: close the priority gap it leaves behind
            _renumber_active(conn)
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


class SlotsFullError(GoalError):
    def __init__(self, message: str, active_goals: list[Goal]):
        super().__init__(message)
        self.active_goals = active_goals


def _row_to_goal(row: tuple) -> Goal:
    return Goal(
        id=row[0],
        name=row[1],
        hours=row[2],
        active=bool(row[3]),
        priority=row[4],
        created_at=row[5],
    )


def activate_goal(name: str, db_path: Path | None = None) -> Goal:
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

        goal = _row_to_goal(row)
        if goal.active:
            raise GoalError(f"'{goal.name}' is already active.")

        mode = conn.execute("SELECT mode FROM app_settings WHERE id = 1").fetchone()[0]
        limit = MODE_LIMITS[mode]

        active_rows = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals WHERE active = 1 ORDER BY priority ASC"
        ).fetchall()

        if len(active_rows) >= limit:
            raise SlotsFullError(
                f"All {limit} active slot(s) are full in '{mode}' mode.",
                [_row_to_goal(r) for r in active_rows],
            )

        # Gaps can appear below `limit` (e.g. a goal manually deactivated
        # while another sat dormant above it from an earlier mode switch),
        # so pick the lowest open rank rather than assuming active ranks
        # are contiguous.
        active_priorities = {r[4] for r in active_rows}
        next_priority = next(
            p for p in range(1, limit + 1) if p not in active_priorities
        )

        conn.execute(
            "UPDATE goals SET active = 1, priority = ? WHERE id = ?",
            (next_priority, goal.id),
        )
        conn.commit()
    finally:
        conn.close()

    goal.active = True
    goal.priority = next_priority
    return goal


def _renumber_active(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM goals WHERE active = 1 ORDER BY priority ASC"
    ).fetchall()
    for rank, (goal_id,) in enumerate(rows, start=1):
        conn.execute("UPDATE goals SET priority = ? WHERE id = ?", (rank, goal_id))


def deactivate_goal(name: str, db_path: Path | None = None) -> Goal:
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
        if not row[3]:
            raise GoalError(f"'{row[1]}' is not active.")

        conn.execute(
            "UPDATE goals SET active = 0, priority = NULL WHERE id = ?", (row[0],)
        )
        _renumber_active(conn)
        conn.commit()
    finally:
        conn.close()

    return Goal(
        id=row[0],
        name=row[1],
        hours=row[2],
        active=False,
        priority=None,
        created_at=row[5],
    )


def move_goal(name: str, direction: str, db_path: Path | None = None) -> None:
    if direction not in ("up", "down"):
        raise GoalError("Direction must be 'up' or 'down'.")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, priority, active FROM goals WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal named '{name}' found.")

        goal_id, priority, active = row
        if not active:
            raise GoalError(f"'{name}' is not active.")

        neighbor_priority = priority - 1 if direction == "up" else priority + 1
        neighbor = conn.execute(
            "SELECT id FROM goals WHERE active = 1 AND priority = ?",
            (neighbor_priority,),
        ).fetchone()
        if neighbor is None:
            edge = "top" if direction == "up" else "bottom"
            raise GoalError(f"'{name}' is already at the {edge}.")

        conn.execute(
            "UPDATE goals SET priority = ? WHERE id = ?", (neighbor_priority, goal_id)
        )
        conn.execute(
            "UPDATE goals SET priority = ? WHERE id = ?", (priority, neighbor[0])
        )
        conn.commit()
    finally:
        conn.close()


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


def _handle_priority(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal priority <name>")
        return

    name = " ".join(options)
    try:
        goal = activate_goal(name)
    except SlotsFullError as exc:
        print_cli(f"[error] {exc}")
        for idx, active_goal in enumerate(exc.active_goals, start=1):
            print_cli(f"{idx}. {active_goal.name} (priority {active_goal.priority})", 2)

        choice = input(
            "  Deactivate which one to make room? (number, or 'n' to cancel): "
        ).strip()
        if choice.lower() == "n":
            print_cli("Cancelled.")
            return

        try:
            target = exc.active_goals[int(choice) - 1]
        except (ValueError, IndexError):
            print_cli("[error] Invalid selection. Cancelled.")
            return

        deactivate_goal(target.name)
        goal = activate_goal(name)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ '{goal.name}' is now active (priority {goal.priority})")


def _handle_deactivate(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal deactivate <name>")
        return

    name = " ".join(options)
    try:
        goal = deactivate_goal(name)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ '{goal.name}' is now inactive")


def _handle_move(options: list[str]) -> None:
    if len(options) < 2:
        print_cli("[error] Usage: goal move <name> <up|down>")
        return

    *name_parts, direction = options
    name = " ".join(name_parts)

    try:
        move_goal(name, direction)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Moved '{name}' {direction}")


def _handle_mode(options: list[str]) -> None:
    if not options:
        mode = get_mode()
        print_cli(f"Current mode: {mode} (max {MODE_LIMITS[mode]} active goal(s))")
        return

    mode = options[0]
    try:
        deactivated, reactivated = set_mode(mode)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Mode set to '{mode}' (max {MODE_LIMITS[mode]} active goal(s))")
    for goal in deactivated:
        print_cli(f"- '{goal.name}' deactivated (priority {goal.priority})", 2)
    for goal in reactivated:
        print_cli(f"- '{goal.name}' reactivated (priority {goal.priority})", 2)


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
    "priority": _Subcommand("Activate a goal: goal priority <name>", _handle_priority),
    "deactivate": _Subcommand(
        "Deactivate a goal: goal deactivate <name>", _handle_deactivate
    ),
    "move": _Subcommand("Reorder priority: goal move <name> <up|down>", _handle_move),
    "mode": _Subcommand(
        "View or set the active-goal mode: goal mode [lock_in|hardcore|relaxed]",
        _handle_mode,
    ),
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
