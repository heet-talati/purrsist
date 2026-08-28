from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from rich.console import RenderableType
from rich.progress_bar import ProgressBar
from rich.prompt import Prompt
from rich.table import Table

from purrsist.output import (
    ICON_LOCKED,
    MUTED_STYLE,
    PRIMARY_STYLE,
    make_console,
    print_cli,
    print_help_table,
    print_muted,
    print_warning_panel,
    render,
)

from .goals_data import (
    DEFAULT_MODE,
    MODE_LIMITS,
    Goal,
    GoalError,
    LockInStatus,
    SlotsFullError,
    _parse_deadline_token,
    activate_goal,
    add_goal,
    deactivate_goal,
    delete_goal,
    find_goal,
    get_mode,
    goals_db_path,
    list_archived_goals,
    list_goals,
    move_goal,
    refresh_lock_in,
    restore_goal,
    set_mode,
    unlock,
    update_goal,
)

__all__ = [
    "DEFAULT_MODE",
    "MODE_LIMITS",
    "Goal",
    "GoalError",
    "LockInStatus",
    "SlotsFullError",
    "activate_goal",
    "add_goal",
    "deactivate_goal",
    "delete_goal",
    "find_goal",
    "get_mode",
    "goals_db_path",
    "handle",
    "list_archived_goals",
    "list_goals",
    "move_goal",
    "refresh_lock_in",
    "restore_goal",
    "set_mode",
    "unlock",
    "update_goal",
]


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
    usage = (
        "[error] Usage: goal add <hours> <name> <days|date> -- a deadline is required."
    )
    if len(options) < 2:
        print_cli(usage)
        return

    hours_raw, name, deadline = _parse_add_args(options)

    try:
        hours = float(hours_raw)
    except ValueError:
        print_cli(f"[error] '{hours_raw}' is not a valid number of hours.")
        return

    if deadline is None:
        print_cli(usage)
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
    # goal identifier (before it) can be multiple tokens (a multi-word name).
    for i in range(1, len(options)):
        if options[i].lower() in _UPDATE_FIELDS:
            identifier = " ".join(options[:i])
            field = options[i].lower()
            value = " ".join(options[i + 1 :])
            return identifier, field, value
    return None


_UPDATE_FIELDS = ("name", "hours", "deadline")


def _handle_update(options: list[str]) -> None:
    usage = "[error] Usage: goal update <name|id> <name|hours|deadline> <value>"
    parsed = _parse_update_args(options)
    if parsed is None:
        print_cli(usage)
        return

    identifier, field, value = parsed
    if not value:
        print_cli(usage)
        return
    if field in ("hours", "deadline") and _refuse_if_locked():
        return

    try:
        goal = update_goal(identifier, field, value)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    if field == "name":
        print_cli(f"✓ Renamed '{identifier}' to '{goal.name}'")
    elif field == "hours":
        print_cli(f"✓ '{goal.name}' target updated to {goal.hours:.2f}h")
    else:
        print_cli(f"✓ '{goal.name}' deadline set to {goal.deadline or 'none'}")


def _refuse_if_locked(db_path: Path | None = None) -> bool:
    status = refresh_lock_in(db_path)
    if status.locked:
        print_cli(
            f"{ICON_LOCKED} Locked in on '{status.goal_name}' -- falling behind pace. "
            f"Use 'goal unlock <reason>' to override."
        )
    return status.locked


def _handle_list(options: list[str]) -> None:
    status = refresh_lock_in()
    all_goals = list_goals()
    archived_goals = list_archived_goals()
    if not all_goals and not archived_goals:
        print_muted("No goals yet. Add one with 'goal add <hours> <name> <days|date>'.")
        return

    if status.locked:
        print_warning_panel(
            f"{ICON_LOCKED} Locked in on '{status.goal_name}' — falling behind pace. "
            f"Use 'goal unlock <reason>' to override."
        )

    active = [g for g in all_goals if g.active]
    inactive = [g for g in all_goals if not g.active]

    if active:
        render(_build_goal_table("Active:", active, include_priority=True))

    if inactive:
        render(_build_goal_table("Inactive:", inactive, include_priority=False))

    if archived_goals:
        table = Table(title="Archived:", title_style=PRIMARY_STYLE, box=None)
        table.add_column("ID", style=MUTED_STYLE, justify="right")
        table.add_column("Name", style=PRIMARY_STYLE)
        table.add_column("Reason", style=MUTED_STYLE)
        for goal in archived_goals:
            table.add_row(str(goal.id), goal.name, goal.delete_reason or "")
        render(table)


def _build_goal_table(
    title: str, goals_list: list[Goal], *, include_priority: bool
) -> Table:
    table = Table(title=title, title_style=PRIMARY_STYLE, box=None)
    table.add_column("ID", style=MUTED_STYLE, justify="right")
    table.add_column("Name", style=PRIMARY_STYLE)
    table.add_column("Progress")
    table.add_column("Hours", style=MUTED_STYLE)
    if include_priority:
        table.add_column("Pri", style=MUTED_STYLE, justify="center")
    table.add_column("Pace", style=MUTED_STYLE)

    for goal in goals_list:
        completed = min(goal.spent_hours, goal.hours) if goal.hours > 0 else 0.0
        bar = ProgressBar(total=goal.hours or 1.0, completed=completed, width=18)
        hours_text = (
            f"{goal.spent_hours:.2f}h / {goal.hours:.2f}h "
            f"({goal.remaining_hours:.2f}h left)"
        )
        row: list[RenderableType] = [str(goal.id), goal.name, bar, hours_text]
        if include_priority:
            row.append(str(goal.priority) if goal.priority else "")
        row.append(_format_pace(goal))
        table.add_row(*row)

    return table


def _format_pace(goal: Goal) -> str:
    if goal.remaining_hours <= 0:
        return "goal reached"
    if goal.avg_hours_per_day <= 0:
        return "no pace yet"

    projected_days = goal.remaining_hours / goal.avg_hours_per_day
    return (
        f"avg {goal.avg_hours_per_day:.2f}h/day, ~{projected_days:.1f} days to finish"
    )


def _handle_delete(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal delete <name|id>")
        return

    identifier = " ".join(options)
    goal = find_goal(identifier)
    if goal is None:
        print_cli(f"[error] No goal '{identifier}' found.")
        return
    if goal.active:
        print_cli(
            f"[error] '{goal.name}' is active. "
            f"Deactivate it first with 'goal deactivate {goal.name}'."
        )
        return

    reason = Prompt.ask(
        f"  Reason for deleting '{goal.name}'", console=make_console()
    ).strip()
    if not reason:
        print_cli("[error] A reason is required. Cancelled.")
        return

    try:
        deleted = delete_goal(str(goal.id), reason)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Archived goal '{deleted.name}'")


def _handle_restore(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal restore <name|id>")
        return

    identifier = " ".join(options)
    try:
        goal = restore_goal(identifier)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Restored goal '{goal.name}' (inactive)")


def _handle_priority(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal priority <name|id>")
        return
    if _refuse_if_locked():
        return

    identifier = " ".join(options)
    try:
        goal = activate_goal(identifier)
    except SlotsFullError as exc:
        print_cli(f"[error] {exc}")
        for idx, active_goal in enumerate(exc.active_goals, start=1):
            print_cli(f"{idx}. {active_goal.name} (priority {active_goal.priority})", 2)

        choice = Prompt.ask(
            "  Deactivate which one to make room? (number, or 'n' to cancel)",
            console=make_console(),
        ).strip()
        if choice.lower() == "n":
            print_cli("Cancelled.")
            return

        try:
            target = exc.active_goals[int(choice) - 1]
        except (ValueError, IndexError):
            print_cli("[error] Invalid selection. Cancelled.")
            return

        deactivate_goal(str(target.id))
        goal = activate_goal(identifier)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ '{goal.name}' is now active (priority {goal.priority})")


def _handle_deactivate(options: list[str]) -> None:
    if not options:
        print_cli("[error] Usage: goal deactivate <name|id>")
        return
    if _refuse_if_locked():
        return

    identifier = " ".join(options)
    try:
        goal = deactivate_goal(identifier)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ '{goal.name}' is now inactive")


def _handle_move(options: list[str]) -> None:
    if len(options) < 2:
        print_cli("[error] Usage: goal move <name|id> <up|down>")
        return

    *identifier_parts, direction = options
    identifier = " ".join(identifier_parts)

    try:
        move_goal(identifier, direction)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    print_cli(f"✓ Moved '{identifier}' {direction}")


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


_UNLOCK_FIELDS = ("hours", "deadline")


def _parse_unlock_args(options: list[str]) -> tuple[str, str | None, str | None]:
    # Mirrors _parse_update_args' reserved-keyword scan: an optional
    # trailing "hours <value>" or "deadline <value>" pair lets goal unlock
    # also fix the pace problem in the same audited command.
    for i in range(1, len(options)):
        if options[i].lower() in _UNLOCK_FIELDS:
            reason = " ".join(options[:i])
            field = options[i].lower()
            value = " ".join(options[i + 1 :])
            return reason, field, value
    return " ".join(options), None, None


def _handle_unlock(options: list[str]) -> None:
    usage = "[error] Usage: goal unlock <reason> [hours <value>|deadline <value>]"
    if not options:
        print_cli(usage)
        return

    reason, field, value = _parse_unlock_args(options)
    if field is not None and not value:
        print_cli(usage)
        return

    try:
        goal = unlock(reason, field=field, value=value)
    except GoalError as exc:
        print_cli(f"[error] {exc}")
        return

    message = "✓ Unlocked. You can change modes and priorities again today."
    if goal is not None:
        if field == "hours":
            message += f" '{goal.name}' target updated to {goal.hours:.2f}h"
        else:
            message += f" '{goal.name}' deadline set to {goal.deadline}"
    print_cli(message)


def _handle_help(options: list[str]) -> None:
    print_help_table(
        "Available goal subcommands:",
        {name: subcommand.description for name, subcommand in GOAL_SUBCOMMANDS.items()},
    )


class _Subcommand(NamedTuple):
    description: str
    handler: Callable[[list[str]], None]


GOAL_SUBCOMMANDS = {
    "add": _Subcommand(
        "Add a new goal: goal add <hours> <name> <days|date>", _handle_add
    ),
    "update": _Subcommand(
        "Edit a goal's name, hours, or deadline: "
        "goal update <name|id> <name|hours|deadline> <value>",
        _handle_update,
    ),
    "list": _Subcommand("List all goals", _handle_list),
    "delete": _Subcommand(
        "Archive an inactive goal (prompts for a reason): goal delete <name|id>",
        _handle_delete,
    ),
    "restore": _Subcommand(
        "Restore an archived goal to inactive: goal restore <name|id>", _handle_restore
    ),
    "priority": _Subcommand(
        "Activate a goal: goal priority <name|id>", _handle_priority
    ),
    "deactivate": _Subcommand(
        "Deactivate a goal: goal deactivate <name|id>", _handle_deactivate
    ),
    "move": _Subcommand(
        "Reorder priority: goal move <name|id> <up|down>", _handle_move
    ),
    "mode": _Subcommand(
        "View or set the active-goal mode: goal mode [lock_in|hardcore|relaxed]",
        _handle_mode,
    ),
    "unlock": _Subcommand(
        "Override the lock-in trigger for today, optionally rescoping the "
        "goal: goal unlock <reason> [hours <value>|deadline <value>]",
        _handle_unlock,
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
