import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from commands import db


class GoalError(ValueError):
    pass


MODE_LIMITS = {"lock_in": 1, "hardcore": 2, "relaxed": 3}
DEFAULT_MODE = db.DEFAULT_MODE

# Goal names double as `track <goal_name>` arguments, so a name matching a
# track subcommand (currently just "help") would be ambiguous at dispatch time.
_RESERVED_NAMES = {"help"}


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


def _identifier_clause(identifier: str) -> tuple[str, str | int]:
    """A goal identifier is its id if purely numeric, else its name.

    Goal names are barred from being purely numeric (see `add_goal`), so
    there's no ambiguity between the two.
    """
    if identifier.isdigit():
        return "id = ?", int(identifier)
    return "name = ? COLLATE NOCASE", identifier


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
    if name.isdigit():
        raise GoalError("Goal name cannot be a number -- numbers are used as goal ids.")
    if name.lower() in _RESERVED_NAMES:
        raise GoalError(f"'{name}' is a reserved name and can't be used for a goal.")
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


def find_goal(identifier: str, db_path: Path | None = None) -> Goal | None:
    identifier = identifier.strip()
    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at, deadline, "
            "COALESCE((SELECT SUM(focused_seconds) FROM sessions "
            "WHERE sessions.goal_id = goals.id "
            "AND sessions.status IN ('completed', 'cancelled')), 0) "
            f"FROM goals WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return Goal(
        id=row[0],
        name=row[1],
        hours=row[2],
        active=bool(row[3]),
        priority=row[4],
        created_at=row[5],
        deadline=row[6],
        spent_hours=row[7] / 3600,
    )


def delete_goal(identifier: str, reason: str, db_path: Path | None = None) -> Goal:
    identifier = identifier.strip()
    if not identifier:
        raise GoalError("Goal name cannot be empty.")
    reason = reason.strip()
    if not reason:
        raise GoalError("A reason is required to delete a goal.")

    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            f"FROM goals WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal '{identifier}' found.")
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


def restore_goal(identifier: str, db_path: Path | None = None) -> Goal:
    identifier = identifier.strip()
    if not identifier:
        raise GoalError("Goal name cannot be empty.")

    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, created_at "
            f"FROM goals WHERE {clause} AND archived_at IS NOT NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No archived goal '{identifier}' found.")

        conn.execute(
            "UPDATE goals SET archived_at = NULL, delete_reason = NULL WHERE id = ?",
            (row[0],),
        )
        conn.commit()
    finally:
        conn.close()

    return Goal(id=row[0], name=row[1], hours=row[2], created_at=row[3])


_UPDATE_FIELDS = ("name", "hours", "deadline")


def update_goal(
    identifier: str, field: str, value: str, db_path: Path | None = None
) -> Goal:
    identifier = identifier.strip()
    if not identifier:
        raise GoalError("Goal name cannot be empty.")
    if field not in _UPDATE_FIELDS:
        raise GoalError(
            f"Unknown field '{field}'. Choose from: {', '.join(_UPDATE_FIELDS)}."
        )

    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at, deadline "
            f"FROM goals WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal '{identifier}' found.")
        goal_id, current_name, hours, active, priority, created_at, deadline = row

        if field == "name":
            new_name = value.strip()
            if not new_name:
                raise GoalError("Goal name cannot be empty.")
            if new_name.isdigit():
                raise GoalError(
                    "Goal name cannot be a number -- numbers are used as goal ids."
                )
            if new_name.lower() in _RESERVED_NAMES:
                raise GoalError(
                    f"'{new_name}' is a reserved name and can't be used for a goal."
                )
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


def activate_goal(identifier: str, db_path: Path | None = None) -> Goal:
    identifier = identifier.strip()
    if not identifier:
        raise GoalError("Goal name cannot be empty.")

    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            f"FROM goals WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal '{identifier}' found.")

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


def deactivate_goal(identifier: str, db_path: Path | None = None) -> Goal:
    identifier = identifier.strip()
    if not identifier:
        raise GoalError("Goal name cannot be empty.")

    clause, param = _identifier_clause(identifier)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, hours, active, priority, created_at "
            f"FROM goals WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal '{identifier}' found.")
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


def move_goal(identifier: str, direction: str, db_path: Path | None = None) -> None:
    if direction not in ("up", "down"):
        raise GoalError("Direction must be 'up' or 'down'.")

    clause, param = _identifier_clause(identifier.strip())
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, priority, active FROM goals "
            f"WHERE {clause} AND archived_at IS NULL",
            (param,),
        ).fetchone()
        if row is None:
            raise GoalError(f"No goal '{identifier}' found.")

        goal_id, priority, active = row
        if not active:
            raise GoalError(f"'{identifier}' is not active.")

        neighbor_priority = priority - 1 if direction == "up" else priority + 1
        neighbor = conn.execute(
            "SELECT id FROM goals WHERE active = 1 AND priority = ?",
            (neighbor_priority,),
        ).fetchone()
        if neighbor is None:
            edge = "top" if direction == "up" else "bottom"
            raise GoalError(f"'{identifier}' is already at the {edge}.")

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
