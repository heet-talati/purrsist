import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
    spent_hours: float = 0.0
    archived_at: str | None = None
    delete_reason: str | None = None
    deadline: str | None = None

    @property
    def remaining_hours(self) -> float:
        return self.hours - self.spent_hours

    @property
    def days_since_created(self) -> float:
        created = datetime.fromisoformat(self.created_at)
        elapsed = datetime.now(UTC) - created
        return max(elapsed.total_seconds() / 86400, 0.0)

    @property
    def avg_hours_per_day(self) -> float:
        days = self.days_since_created
        return self.spent_hours / days if days > 0 else 0.0


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


class LockInStatus(NamedTuple):
    locked: bool
    goal_name: str | None
    recent_pace: float | None
    required_pace: float | None


def _priority_goal_row(conn: sqlite3.Connection) -> tuple | None:
    return conn.execute(
        "SELECT id, name, hours, deadline, "
        "COALESCE((SELECT SUM(focused_seconds) FROM sessions "
        "WHERE sessions.goal_id = goals.id "
        "AND sessions.status IN ('completed', 'cancelled')), 0) "
        "FROM goals WHERE active = 1 AND priority = 1 "
        "AND archived_at IS NULL AND deadline IS NOT NULL"
    ).fetchone()


def refresh_lock_in(db_path: Path | None = None) -> LockInStatus:
    """Recompute the lock-in trigger for the priority-1 active goal (if it
    has a deadline) and persist the result, auto-locking or auto-unlocking
    on a transition.

    Evaluated at most once per calendar day: re-checking on every call would
    immediately undo a same-day manual `unlock` the moment pace is still
    behind, defeating the point of an intentional override. The next
    automatic re-evaluation happens the following day.
    """
    conn = _connect(db_path)
    try:
        was_locked, checked_on = conn.execute(
            "SELECT lock_in_locked, lock_in_checked_on FROM app_settings WHERE id = 1"
        ).fetchone()
        was_locked = bool(was_locked)
        today = datetime.now(UTC).date().isoformat()

        row = _priority_goal_row(conn)
        if row is None:
            # Nothing to evaluate (no priority-1 goal with a deadline) --
            # clear a stale lock, but don't stamp lock_in_checked_on: no
            # real evaluation happened, so today's slot isn't used up. That
            # matters because `_refuse_if_locked` runs on every mutating
            # goal command, including the one that's still in the middle of
            # activating the very goal being evaluated here (not active
            # yet) -- an early no-op check must not suppress the real
            # evaluation once that goal is actually in place.
            if was_locked:
                conn.execute("UPDATE app_settings SET lock_in_locked = 0 WHERE id = 1")
                conn.commit()
            return LockInStatus(False, None, None, None)

        if checked_on == today:
            return LockInStatus(was_locked, row[1] if was_locked else None, None, None)

        goal_id, goal_name, hours, deadline, spent_seconds = row
        remaining_hours = hours - spent_seconds / 3600
        recent_pace = required_pace = None
        new_locked = False

        if remaining_hours > 0:
            days_left = (date.fromisoformat(deadline) - datetime.now(UTC).date()).days
            required_pace = (
                remaining_hours / days_left if days_left > 0 else float("inf")
            )

            cutoff = (datetime.now(UTC) - timedelta(days=4)).isoformat()
            recent_seconds = conn.execute(
                "SELECT COALESCE(SUM(focused_seconds), 0) FROM sessions "
                "WHERE goal_id = ? AND status IN ('completed', 'cancelled') "
                "AND started_at >= ?",
                (goal_id, cutoff),
            ).fetchone()[0]
            recent_pace = (recent_seconds / 3600) / 4
            new_locked = recent_pace < required_pace

        conn.execute(
            "UPDATE app_settings SET lock_in_locked = ?, lock_in_checked_on = ? "
            "WHERE id = 1",
            (int(new_locked), today),
        )
        conn.commit()
    finally:
        conn.close()

    if new_locked and not was_locked:
        set_mode("lock_in", db_path=db_path)

    return LockInStatus(
        new_locked, goal_name if new_locked else None, recent_pace, required_pace
    )


def unlock(reason: str, db_path: Path | None = None) -> None:
    reason = reason.strip()
    if not reason:
        raise GoalError("A reason is required to unlock.")

    conn = _connect(db_path)
    try:
        locked = conn.execute(
            "SELECT lock_in_locked FROM app_settings WHERE id = 1"
        ).fetchone()[0]
        if not locked:
            raise GoalError("Not currently locked.")

        conn.execute(
            "UPDATE app_settings SET lock_in_locked = 0, lock_in_checked_on = ? "
            "WHERE id = 1",
            (datetime.now(UTC).date().isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()


def add_goal(
    name: str, hours: float, deadline: str | None = None, db_path: Path | None = None
) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")
    if hours <= 0:
        raise GoalError("Hours must be a positive number.")

    created_at = datetime.now(UTC).isoformat()
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO goals (name, hours, active, priority, created_at, deadline) "
            "VALUES (?, ?, 0, NULL, ?, ?)",
            (name, hours, created_at, deadline),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise GoalError(f"A goal named '{name}' already exists.") from exc
    finally:
        conn.close()

    return Goal(
        id=cursor.lastrowid,
        name=name,
        hours=hours,
        created_at=created_at,
        deadline=deadline,
    )


def list_goals(db_path: Path | None = None) -> list[Goal]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, hours, active, priority, created_at, deadline, "
            "COALESCE((SELECT SUM(focused_seconds) FROM sessions "
            "WHERE sessions.goal_id = goals.id "
            "AND sessions.status IN ('completed', 'cancelled')), 0) "
            "FROM goals WHERE archived_at IS NULL "
            "ORDER BY active DESC, priority ASC"
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
            deadline=row[6],
            spent_hours=row[7] / 3600,
        )
        for row in rows
    ]


def list_archived_goals(db_path: Path | None = None) -> list[Goal]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, hours, created_at, archived_at, delete_reason "
            "FROM goals WHERE archived_at IS NOT NULL ORDER BY archived_at DESC"
        ).fetchall()
    finally:
        conn.close()

    return [
        Goal(
            id=row[0],
            name=row[1],
            hours=row[2],
            created_at=row[3],
            archived_at=row[4],
            delete_reason=row[5],
        )
        for row in rows
    ]


def delete_goal(name: str, reason: str, db_path: Path | None = None) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")
    reason = reason.strip()
    if not reason:
        raise GoalError("A reason is required to delete a goal.")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            "FROM goals WHERE name = ? COLLATE NOCASE AND archived_at IS NULL",
            (name,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal named '{name}' found.")
        if row[3]:  # active
            raise GoalError(
                f"'{row[1]}' is active. Deactivate it first with "
                f"'goal deactivate {row[1]}'."
            )

        archived_at = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE goals SET archived_at = ?, delete_reason = ? WHERE id = ?",
            (archived_at, reason, row[0]),
        )
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
        archived_at=archived_at,
        delete_reason=reason,
    )


def restore_goal(name: str, db_path: Path | None = None) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, created_at "
            "FROM goals WHERE name = ? COLLATE NOCASE AND archived_at IS NOT NULL",
            (name,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No archived goal named '{name}' found.")

        conn.execute(
            "UPDATE goals SET archived_at = NULL, delete_reason = NULL WHERE id = ?",
            (row[0],),
        )
        conn.commit()
    finally:
        conn.close()

    return Goal(id=row[0], name=row[1], hours=row[2], created_at=row[3])


_UPDATE_FIELDS = ("name", "hours", "deadline")


def update_goal(name: str, field: str, value: str, db_path: Path | None = None) -> Goal:
    name = name.strip()
    if not name:
        raise GoalError("Goal name cannot be empty.")
    if field not in _UPDATE_FIELDS:
        raise GoalError(
            f"Unknown field '{field}'. Choose from: {', '.join(_UPDATE_FIELDS)}."
        )

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at, deadline "
            "FROM goals WHERE name = ? COLLATE NOCASE AND archived_at IS NULL",
            (name,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal named '{name}' found.")
        goal_id, current_name, hours, active, priority, created_at, deadline = row

        if field == "name":
            new_name = value.strip()
            if not new_name:
                raise GoalError("Goal name cannot be empty.")
            try:
                conn.execute(
                    "UPDATE goals SET name = ? WHERE id = ?", (new_name, goal_id)
                )
            except sqlite3.IntegrityError as exc:
                raise GoalError(f"A goal named '{new_name}' already exists.") from exc
            current_name = new_name
        elif field == "hours":
            try:
                new_hours = float(value)
            except ValueError:
                raise GoalError(f"'{value}' is not a valid number of hours.") from None
            if new_hours <= 0:
                raise GoalError("Hours must be a positive number.")
            conn.execute(
                "UPDATE goals SET hours = ? WHERE id = ?", (new_hours, goal_id)
            )
            hours = new_hours
        else:  # deadline
            if value.strip().lower() == "none":
                new_deadline = None
            else:
                new_deadline = _parse_deadline_token(value.strip())
                if new_deadline is None:
                    raise GoalError(
                        f"'{value}' is not a valid deadline "
                        "(use a day count, YYYY-MM-DD, or 'none')."
                    )
            conn.execute(
                "UPDATE goals SET deadline = ? WHERE id = ?", (new_deadline, goal_id)
            )
            deadline = new_deadline

        # A pace-affecting edit (hours or deadline) to the goal the lock-in
        # trigger is currently watching must be reflected immediately --
        # otherwise the once-a-day cache in refresh_lock_in would keep
        # reporting yesterday's (now stale) lock state until tomorrow.
        force_recheck = (
            field in ("hours", "deadline") and bool(active) and priority == 1
        )
        if force_recheck:
            conn.execute(
                "UPDATE app_settings SET lock_in_checked_on = NULL WHERE id = 1"
            )

        conn.commit()
    finally:
        conn.close()

    if force_recheck:
        refresh_lock_in(db_path)

    return Goal(
        id=goal_id,
        name=current_name,
        hours=hours,
        active=bool(active),
        priority=priority,
        created_at=created_at,
        deadline=deadline,
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
            "FROM goals WHERE name = ? COLLATE NOCASE AND archived_at IS NULL",
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
            "FROM goals WHERE name = ? COLLATE NOCASE AND archived_at IS NULL",
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
            "SELECT id, priority, active FROM goals "
            "WHERE name = ? COLLATE NOCASE AND archived_at IS NULL",
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


def _parse_deadline_token(token: str) -> str | None:
    try:
        days = int(token)
    except ValueError:
        pass
    else:
        return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()

    try:
        return date.fromisoformat(token).isoformat()
    except ValueError:
        return None


def _parse_add_args(options: list[str]) -> tuple[str, str, str | None]:
    hours_raw, *rest = options
    name_tokens = rest
    deadline = None
    if len(rest) > 1:
        *candidate_name_tokens, last = rest
        parsed = _parse_deadline_token(last)
        if parsed is not None:
            deadline = parsed
            name_tokens = candidate_name_tokens
    return hours_raw, " ".join(name_tokens), deadline


def _handle_add(options: list[str]) -> None:
    if len(options) < 2:
        print_cli("[error] Usage: goal add <hours> <name> [days|date]")
        return

    hours_raw, name, deadline = _parse_add_args(options)

    try:
        hours = float(hours_raw)
    except ValueError:
        print_cli(f"[error] '{hours_raw}' is not a valid number of hours.")
        return

    try:
        goal = add_goal(name, hours, deadline)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    deadline_str = f", due {goal.deadline}" if goal.deadline else ""
    print_cli(f"✓ Added goal '{goal.name}' ({goal.hours}h{deadline_str})")


def _parse_update_args(options: list[str]) -> tuple[str, str, str] | None:
    # `field` is a reserved keyword rather than a fixed position, since the
    # goal name itself (before it) can be multiple tokens.
    for i in range(1, len(options)):
        if options[i].lower() in _UPDATE_FIELDS:
            name = " ".join(options[:i])
            field = options[i].lower()
            value = " ".join(options[i + 1 :])
            return name, field, value
    return None


def _handle_update(options: list[str]) -> None:
    usage = "[error] Usage: goal update <name> <name|hours|deadline> <value>"
    parsed = _parse_update_args(options)
    if parsed is None:
        print_cli(usage)
        return

    name, field, value = parsed
    if not value:
        print_cli(usage)
        return
    if field in ("hours", "deadline") and _refuse_if_locked():
        return

    try:
        goal = update_goal(name, field, value)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    if field == "name":
        print_cli(f"✓ Renamed '{name}' to '{goal.name}'")
    elif field == "hours":
        print_cli(f"✓ '{goal.name}' target updated to {goal.hours:.2f}h")
    else:
        print_cli(f"✓ '{goal.name}' deadline set to {goal.deadline or 'none'}")


def _refuse_if_locked(db_path: Path | None = None) -> bool:
    status = refresh_lock_in(db_path)
    if status.locked:
        print_cli(
            f"[error] Locked in on '{status.goal_name}' -- falling behind pace. "
            f"Use 'goal unlock <reason>' to override."
        )
    return status.locked


def _handle_list(options: list[str]) -> None:
    status = refresh_lock_in()
    all_goals = list_goals()
    archived_goals = list_archived_goals()
    if not all_goals and not archived_goals:
        print_cli("No goals yet. Add one with 'goal add <hours> <name>'.")
        return

    if status.locked:
        print_cli(
            f"🔒 Locked in on '{status.goal_name}' — falling behind pace. "
            f"Use 'goal unlock <reason>' to override."
        )

    active = [g for g in all_goals if g.active]
    inactive = [g for g in all_goals if not g.active]

    if active:
        print_cli("Active:")
        for goal in active:
            priority_str = f" [priority {goal.priority}]" if goal.priority else ""
            print_cli(
                f"- {_format_progress(goal)}{priority_str}{_format_pace(goal)}", 2
            )

    if inactive:
        print_cli("Inactive:")
        for goal in inactive:
            print_cli(f"- {_format_progress(goal)}{_format_pace(goal)}", 2)

    if archived_goals:
        print_cli("Archived:")
        for goal in archived_goals:
            print_cli(f"- {goal.name} — {goal.delete_reason}", 2)


def _format_progress(goal: Goal) -> str:
    return (
        f"{goal.name} ({goal.spent_hours:.2f}h / {goal.hours:.2f}h, "
        f"{goal.remaining_hours:.2f}h left)"
    )


def _format_pace(goal: Goal) -> str:
    if goal.remaining_hours <= 0:
        return " — goal reached"
    if goal.avg_hours_per_day <= 0:
        return " — no pace yet"

    projected_days = goal.remaining_hours / goal.avg_hours_per_day
    return f" — avg {goal.avg_hours_per_day:.2f}h/day, ~{projected_days:.1f} days to finish"


def _handle_delete(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal delete <name>")
        return

    name = " ".join(options)
    goal = next((g for g in list_goals() if g.name.lower() == name.lower()), None)
    if goal is None:
        print_cli(f"[error] No goal named '{name}' found.")
        return
    if goal.active:
        print_cli(
            f"[error] '{goal.name}' is active. "
            f"Deactivate it first with 'goal deactivate {goal.name}'."
        )
        return

    reason = input(f"  Reason for deleting '{goal.name}'? ").strip()
    if not reason:
        print_cli("[error] A reason is required. Cancelled.")
        return

    try:
        deleted = delete_goal(goal.name, reason)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Archived goal '{deleted.name}'")


def _handle_restore(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal restore <name>")
        return

    name = " ".join(options)
    try:
        goal = restore_goal(name)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Restored goal '{goal.name}' (inactive)")


def _handle_priority(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal priority <name>")
        return
    if _refuse_if_locked():
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
    if _refuse_if_locked():
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
    if _refuse_if_locked():
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


def _handle_unlock(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal unlock <reason>")
        return

    reason = " ".join(options)
    try:
        unlock(reason)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli("✓ Unlocked. You can change modes and priorities again today.")


def _handle_help(options: list[str]) -> None:
    print_cli("Available goal subcommands:")
    for name, subcommand in GOAL_SUBCOMMANDS.items():
        print_cli(f"- {name}: {subcommand.description}", 2)


class _Subcommand(NamedTuple):
    description: str
    handler: Callable[[list[str]], None]


GOAL_SUBCOMMANDS = {
    "add": _Subcommand(
        "Add a new goal: goal add <hours> <name> [days|date]", _handle_add
    ),
    "update": _Subcommand(
        "Edit a goal's name, hours, or deadline: "
        "goal update <name> <name|hours|deadline> <value>",
        _handle_update,
    ),
    "list": _Subcommand("List all goals", _handle_list),
    "delete": _Subcommand(
        "Archive an inactive goal (prompts for a reason): goal delete <name>",
        _handle_delete,
    ),
    "restore": _Subcommand(
        "Restore an archived goal to inactive: goal restore <name>", _handle_restore
    ),
    "priority": _Subcommand("Activate a goal: goal priority <name>", _handle_priority),
    "deactivate": _Subcommand(
        "Deactivate a goal: goal deactivate <name>", _handle_deactivate
    ),
    "move": _Subcommand("Reorder priority: goal move <name> <up|down>", _handle_move),
    "mode": _Subcommand(
        "View or set the active-goal mode: goal mode [lock_in|hardcore|relaxed]",
        _handle_mode,
    ),
    "unlock": _Subcommand(
        "Override the lock-in trigger for today: goal unlock <reason>", _handle_unlock
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
