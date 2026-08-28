import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from commands import goals, goals_data


def test_add_goal_creates_row(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    assert goal.name == "Learn Rust"
    assert goal.hours == 20
    assert goal.active is False
    assert goal.priority is None
    assert goal.id is not None

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT name, hours, active, priority FROM goals WHERE id = ?", (goal.id,)
    ).fetchone()
    conn.close()
    assert row == ("Learn Rust", 20, 0, None)


def test_add_goal_rejects_empty_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("   ", 20, _days_from_now(30), db_path=db_path)


def test_add_goal_rejects_non_positive_hours(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("Learn Rust", 0, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.add_goal("Learn Rust", -5, _days_from_now(30), db_path=db_path)


def test_add_goal_requires_a_deadline(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("Learn Rust", 20, db_path=db_path)


def test_add_goal_rejects_empty_name_before_checking_deadline(tmp_path):
    # Name/hours validation must fire before the deadline check, so callers
    # get the specific error instead of a generic "deadline required" one.
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError, match="name"):
        goals.add_goal("   ", 20, _days_from_now(30), db_path=db_path)


def test_add_goal_rejects_duplicate_name_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.add_goal("learn rust", 5, _days_from_now(30), db_path=db_path)


def test_handle_missing_subcommand(capsys):
    goals.handle([])
    captured = capsys.readouterr()
    assert "[error] Usage: goal" in captured.out


def test_handle_unknown_subcommand(capsys):
    goals.handle(["frobnicate"])
    captured = capsys.readouterr()
    assert "Unknown goal subcommand" in captured.out


def test_handle_help_lists_subcommands(capsys):
    goals.handle(["help"])
    captured = capsys.readouterr()
    for name in goals.GOAL_SUBCOMMANDS:
        assert name in captured.out


def test_handle_add_missing_args(capsys):
    goals.handle(["add", "20"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal add" in captured.out


def test_handle_add_requires_a_deadline(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal add" in captured.out
    assert "deadline" in captured.out


def test_handle_add_invalid_hours(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "abc", "Learn", "Rust", "30"])
    captured = capsys.readouterr()
    assert "is not a valid number of hours" in captured.out


def test_handle_add_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    captured = capsys.readouterr()
    assert "Added goal 'Learn Rust'" in captured.out


def test_handle_add_duplicate(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()
    goals.handle(["add", "5", "Learn", "Rust", "30"])
    captured = capsys.readouterr()
    assert "already exists" in captured.out


def test_delete_goal_archives_row(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    deleted = goals.delete_goal("Learn Rust", "lost interest", db_path=db_path)
    assert deleted.id == goal.id
    assert deleted.delete_reason == "lost interest"
    assert deleted.archived_at is not None

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT archived_at, delete_reason FROM goals WHERE id = ?", (goal.id,)
    ).fetchone()
    conn.close()
    assert row[0] is not None
    assert row[1] == "lost interest"


def test_delete_goal_is_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    deleted = goals.delete_goal("learn rust", "reason", db_path=db_path)
    assert deleted.name == "Learn Rust"


def test_delete_goal_rejects_missing_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.delete_goal("Nonexistent", "reason", db_path=db_path)


def test_delete_goal_rejects_blank_reason(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.delete_goal("Learn Rust", "   ", db_path=db_path)


def test_delete_goal_rejects_active_goal(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.delete_goal("Learn Rust", "reason", db_path=db_path)


def test_delete_goal_rejects_already_archived(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "first reason", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.delete_goal("Learn Rust", "second reason", db_path=db_path)


def test_list_goals_excludes_archived(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "reason", db_path=db_path)

    assert goals.list_goals(db_path=db_path) == []


def test_list_archived_goals_returns_reason(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "lost interest", db_path=db_path)

    archived = goals.list_archived_goals(db_path=db_path)
    assert len(archived) == 1
    assert archived[0].name == "Learn Rust"
    assert archived[0].delete_reason == "lost interest"


def test_restore_goal_moves_back_to_inactive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "reason", db_path=db_path)

    restored = goals.restore_goal("Learn Rust", db_path=db_path)
    assert restored.active is False

    assert goals.list_archived_goals(db_path=db_path) == []
    visible = goals.list_goals(db_path=db_path)
    assert len(visible) == 1
    assert visible[0].name == "Learn Rust"
    assert visible[0].archived_at is None


def test_restore_goal_rejects_non_archived_name(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.restore_goal("Learn Rust", db_path=db_path)


def test_restore_goal_rejects_missing_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.restore_goal("Nonexistent", db_path=db_path)


def test_activate_goal_rejects_archived_name(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "reason", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.activate_goal("Learn Rust", db_path=db_path)


def test_handle_delete_missing_args(capsys):
    goals.handle(["delete"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal delete" in captured.out


def test_handle_delete_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda: "lost interest")
    goals.handle(["delete", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "Archived goal 'Learn Rust'" in captured.out


def test_handle_delete_not_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["delete", "Nonexistent"])
    captured = capsys.readouterr()
    assert "No goal 'Nonexistent' found" in captured.out


def test_handle_delete_blocks_active_goal_without_prompting(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    goals.handle(["priority", "Learn", "Rust"])
    capsys.readouterr()

    def _fail_if_called():
        raise AssertionError("should not prompt for a reason on a blocked delete")

    monkeypatch.setattr("builtins.input", _fail_if_called)
    goals.handle(["delete", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "is active" in captured.out
    assert "deactivate" in captured.out


def test_handle_delete_blank_reason_cancels(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda: "   ")
    goals.handle(["delete", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "A reason is required" in captured.out
    assert goals.list_goals(db_path=tmp_path / "test.db")[0].name == "Learn Rust"


def test_handle_restore_missing_args(capsys):
    goals.handle(["restore"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal restore" in captured.out


def test_handle_restore_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    monkeypatch.setattr("builtins.input", lambda: "reason")
    goals.handle(["delete", "Learn", "Rust"])
    capsys.readouterr()

    goals.handle(["restore", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "Restored goal 'Learn Rust'" in captured.out


def test_handle_restore_not_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["restore", "Nonexistent"])
    captured = capsys.readouterr()
    assert "No archived goal 'Nonexistent' found" in captured.out


def test_list_goals_empty(tmp_path):
    db_path = tmp_path / "test.db"
    assert goals.list_goals(db_path=db_path) == []


def test_list_goals_orders_active_before_inactive_and_by_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Low", 10, _days_from_now(30), db_path=db_path)
    goals.add_goal("High", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("Inactive", 3, _days_from_now(30), db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET active = 1, priority = 2 WHERE name = 'Low'")
    conn.execute("UPDATE goals SET active = 1, priority = 1 WHERE name = 'High'")
    conn.commit()
    conn.close()

    result = [g.name for g in goals.list_goals(db_path=db_path)]
    assert result == ["High", "Low", "Inactive"]


def _insert_session(
    db_path, goal_id, status, focused_seconds, started_at="2026-01-01T00:00:00"
):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sessions (goal_id, planned_minutes, started_at, status, "
        "focused_seconds) VALUES (?, 25, ?, ?, ?)",
        (goal_id, started_at, status, focused_seconds),
    )
    conn.commit()
    conn.close()


def test_list_goals_sums_completed_and_cancelled_session_time(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 10, _days_from_now(30), db_path=db_path)
    _insert_session(db_path, goal.id, "completed", 3600)
    _insert_session(db_path, goal.id, "cancelled", 1800)

    result = goals.list_goals(db_path=db_path)[0]
    assert result.spent_hours == 1.5
    assert result.remaining_hours == 8.5


def test_list_goals_ignores_running_and_paused_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 10, _days_from_now(30), db_path=db_path)
    _insert_session(db_path, goal.id, "running", 0)
    _insert_session(db_path, goal.id, "paused", 0)

    result = goals.list_goals(db_path=db_path)[0]
    assert result.spent_hours == 0.0


def test_list_goals_defaults_spent_hours_to_zero_with_no_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 10, _days_from_now(30), db_path=db_path)

    result = goals.list_goals(db_path=db_path)[0]
    assert result.spent_hours == 0.0
    assert result.remaining_hours == 10


def _insert_goal_with_created_at(db_path, name, hours, created_at):
    goal = goals.add_goal(name, hours, _days_from_now(30), db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET created_at = ? WHERE id = ?", (created_at, goal.id))
    conn.commit()
    conn.close()


def test_avg_hours_per_day_divides_spent_by_elapsed_days(tmp_path):
    db_path = tmp_path / "test.db"
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _insert_goal_with_created_at(db_path, "Learn Rust", 10, two_days_ago)
    goal_id = goals.list_goals(db_path=db_path)[0].id
    _insert_session(db_path, goal_id, "completed", 4 * 3600)  # 4h spent

    goal = goals.list_goals(db_path=db_path)[0]
    assert goal.avg_hours_per_day == pytest.approx(2.0, rel=0.01)


def test_avg_hours_per_day_is_zero_with_no_time_spent(tmp_path):
    db_path = tmp_path / "test.db"
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _insert_goal_with_created_at(db_path, "Learn Rust", 10, two_days_ago)

    goal = goals.list_goals(db_path=db_path)[0]
    assert goal.avg_hours_per_day == 0.0


def test_avg_hours_per_day_floors_elapsed_days_at_one_for_brand_new_goal(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 10, _days_from_now(30), db_path=db_path)
    _insert_session(
        db_path, goal.id, "completed", 72
    )  # 0.02h, goal created moments ago

    result = goals.list_goals(db_path=db_path)[0]
    # Without a same-day floor, dividing by a near-zero elapsed-days window
    # inflates this into an absurd double-digit hours/day pace.
    assert result.avg_hours_per_day == pytest.approx(0.02, rel=0.01)


def test_handle_list_shows_pace_and_projected_completion(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _insert_goal_with_created_at(db_path, "Learn Rust", 10, two_days_ago)
    goal_id = goals.list_goals(db_path=db_path)[0].id
    _insert_session(db_path, goal_id, "completed", 4 * 3600)  # 4h spent, 2h/day avg

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "avg 2.00h/day" in captured.out
    assert "~3.0 days to finish" in captured.out.replace(
        "\n", " "
    )  # 6h remaining / 2h/day


def test_handle_list_shows_no_pace_yet_with_no_sessions(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "10", "Learn", "Rust", "30"])
    capsys.readouterr()

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "no pace yet" in captured.out


def test_handle_list_shows_goal_reached_when_target_met(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.handle(["add", "1", "Learn", "Rust", "30"])
    capsys.readouterr()
    goal_id = goals.list_goals(db_path=db_path)[0].id
    _insert_session(db_path, goal_id, "completed", 3600)  # 1h spent == 1h target

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "goal reached" in captured.out


def test_handle_list_empty(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["list"])
    captured = capsys.readouterr()
    assert "No goals yet" in captured.out


def test_handle_list_shows_active_and_inactive_sections(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.add_goal("Learn Go", 10, _days_from_now(30), db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET active = 1, priority = 1 WHERE name = 'Learn Rust'")
    conn.commit()
    conn.close()

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "Active:" in captured.out
    active_line = next(
        line for line in captured.out.splitlines() if "Learn Rust" in line
    )
    assert "0.00h / 20.00h (20.00h left)" in active_line
    assert "no pace yet" in active_line

    assert "Inactive:" in captured.out
    inactive_line = next(
        line for line in captured.out.splitlines() if "Learn Go" in line
    )
    assert "0.00h / 10.00h (10.00h left)" in inactive_line


def test_handle_list_shows_archived_section(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "lost interest", db_path=db_path)

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "Archived:" in captured.out
    archived_line = next(
        line for line in captured.out.splitlines() if "Learn Rust" in line
    )
    assert "lost interest" in archived_line


def test_handle_list_shows_only_archived_without_no_goals_message(
    monkeypatch, capsys, tmp_path
):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal("Learn Rust", "lost interest", db_path=db_path)

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "No goals yet" not in captured.out


def test_get_mode_defaults_to_relaxed(tmp_path):
    db_path = tmp_path / "test.db"
    assert goals.get_mode(db_path=db_path) == "relaxed"


def test_set_mode_rejects_unknown_mode(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.set_mode("chaotic", db_path=db_path)


def test_set_mode_succeeds_within_limit(tmp_path):
    db_path = tmp_path / "test.db"
    goals.set_mode("hardcore", db_path=db_path)
    assert goals.get_mode(db_path=db_path) == "hardcore"


def test_set_mode_downgrade_deactivates_overflow_and_retains_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("C", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)
    goals.activate_goal("C", db_path=db_path)

    deactivated, reactivated = goals.set_mode("hardcore", db_path=db_path)

    assert [g.name for g in deactivated] == ["C"]
    assert reactivated == []

    by_name = {g.name: g for g in goals.list_goals(db_path=db_path)}
    assert by_name["A"].active is True
    assert by_name["B"].active is True
    assert by_name["C"].active is False
    assert by_name["C"].priority == 3


def test_set_mode_upgrade_reactivates_retained_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("C", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)
    goals.activate_goal("C", db_path=db_path)
    goals.set_mode("lock_in", db_path=db_path)

    deactivated, reactivated = goals.set_mode("relaxed", db_path=db_path)

    assert deactivated == []
    assert {g.name for g in reactivated} == {"B", "C"}

    by_name = {g.name: g for g in goals.list_goals(db_path=db_path)}
    assert by_name["A"].active is True
    assert by_name["B"].active is True
    assert by_name["B"].priority == 2
    assert by_name["C"].active is True
    assert by_name["C"].priority == 3


def test_activate_goal_fills_gap_left_by_manual_deactivate(tmp_path):
    # A(1) manually deactivated while C(3) sits dormant from a mode
    # downgrade, then mode is raised enough to reactivate C(2) but not
    # A -- active priorities are {2}, so a new activation must not
    # naively assume "count + 1" and collide with the existing rank 2.
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("C", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)
    goals.activate_goal("C", db_path=db_path)
    goals.set_mode("lock_in", db_path=db_path)
    goals.deactivate_goal("A", db_path=db_path)
    goals.set_mode("hardcore", db_path=db_path)

    by_name = {g.name: g for g in goals.list_goals(db_path=db_path)}
    assert by_name["A"].active is False
    assert by_name["A"].priority is None
    assert by_name["B"].active is True
    assert by_name["B"].priority == 2
    assert by_name["C"].active is False

    goals.add_goal("D", 5, _days_from_now(30), db_path=db_path)
    activated = goals.activate_goal("D", db_path=db_path)
    assert activated.priority == 1

    by_name = {g.name: g for g in goals.list_goals(db_path=db_path)}
    assert by_name["D"].active is True
    assert by_name["D"].priority == 1
    assert by_name["B"].priority == 2


def test_activate_goal_assigns_next_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)

    first = goals.activate_goal("A", db_path=db_path)
    second = goals.activate_goal("B", db_path=db_path)

    assert first.active is True
    assert first.priority == 1
    assert second.priority == 2


def test_activate_goal_rejects_already_active(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.activate_goal("A", db_path=db_path)


def test_activate_goal_rejects_missing_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.activate_goal("Nonexistent", db_path=db_path)


def test_activate_goal_raises_slots_full(tmp_path):
    db_path = tmp_path / "test.db"
    goals.set_mode("lock_in", db_path=db_path)
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)

    with pytest.raises(goals.SlotsFullError) as excinfo:
        goals.activate_goal("B", db_path=db_path)
    assert [g.name for g in excinfo.value.active_goals] == ["A"]


def test_deactivate_goal_renumbers_remaining(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("C", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)
    goals.activate_goal("C", db_path=db_path)

    goals.deactivate_goal("A", db_path=db_path)

    active = {g.name: g.priority for g in goals.list_goals(db_path=db_path) if g.active}
    assert active == {"B": 1, "C": 2}


def test_deactivate_goal_rejects_inactive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.deactivate_goal("A", db_path=db_path)


def test_move_goal_swaps_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)

    goals.move_goal("B", "up", db_path=db_path)

    active = {g.name: g.priority for g in goals.list_goals(db_path=db_path)}
    assert active == {"B": 1, "A": 2}


def test_move_goal_rejects_past_edge(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.move_goal("A", "up", db_path=db_path)


def test_move_goal_rejects_inactive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.move_goal("A", "down", db_path=db_path)


def test_handle_priority_activates_goal(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    goals.handle(["priority", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "'Learn Rust' is now active (priority 1)" in captured.out


def test_handle_priority_slots_full_cancel(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "lock_in"])
    goals.handle(["add", "5", "A", "30"])
    goals.handle(["add", "5", "B", "30"])
    goals.handle(["priority", "A"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda: "n")
    goals.handle(["priority", "B"])
    captured = capsys.readouterr()
    assert "Cancelled." in captured.out
    assert goals.list_goals()[0].name == "A"
    assert goals.list_goals()[0].active is True


def test_handle_priority_slots_full_swap(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "lock_in"])
    goals.handle(["add", "5", "A", "30"])
    goals.handle(["add", "5", "B", "30"])
    goals.handle(["priority", "A"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda: "1")
    goals.handle(["priority", "B"])
    captured = capsys.readouterr()
    assert "'B' is now active (priority 1)" in captured.out

    active = {g.name: g.active for g in goals.list_goals()}
    assert active == {"A": False, "B": True}


def test_handle_deactivate_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    goals.handle(["priority", "Learn", "Rust"])
    capsys.readouterr()

    goals.handle(["deactivate", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "'Learn Rust' is now inactive" in captured.out


def test_handle_move_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "5", "A", "30"])
    goals.handle(["add", "5", "B", "30"])
    goals.handle(["priority", "A"])
    goals.handle(["priority", "B"])
    capsys.readouterr()

    goals.handle(["move", "B", "up"])
    captured = capsys.readouterr()
    assert "Moved 'B' up" in captured.out


def test_handle_mode_shows_current_mode(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode"])
    captured = capsys.readouterr()
    assert "Current mode: relaxed" in captured.out


def test_handle_mode_sets_mode(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "hardcore"])
    captured = capsys.readouterr()
    assert "Mode set to 'hardcore'" in captured.out


# --- goal add: deadline parsing ---


def test_parse_add_args_no_deadline():
    hours_raw, name, deadline = goals._parse_add_args(["20", "Learn", "Rust"])
    assert hours_raw == "20"
    assert name == "Learn Rust"
    assert deadline is None


def test_parse_add_args_relative_days_deadline():
    _hours_raw, name, deadline = goals._parse_add_args(["20", "Learn", "Rust", "30"])
    assert name == "Learn Rust"
    expected = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert deadline == expected


def test_parse_add_args_explicit_date_deadline():
    _hours_raw, name, deadline = goals._parse_add_args(
        ["20", "Learn", "Rust", "2026-12-01"]
    )
    assert name == "Learn Rust"
    assert deadline == "2026-12-01"


def test_parse_add_args_single_name_token_not_treated_as_deadline():
    # Only one token after hours -- must be the name, not a deadline, even
    # though "30" would otherwise parse as one.
    _hours_raw, name, deadline = goals._parse_add_args(["20", "30"])
    assert name == "30"
    assert deadline is None


def test_parse_add_args_non_date_trailing_token_stays_part_of_name():
    _hours_raw, name, deadline = goals._parse_add_args(["20", "Learn", "Rust", "Extra"])
    assert name == "Learn Rust Extra"
    assert deadline is None


def test_add_goal_stores_deadline(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, "2026-12-01", db_path=db_path)
    assert goal.deadline == "2026-12-01"
    assert goals.list_goals(db_path=db_path)[0].deadline == "2026-12-01"


def test_handle_add_with_deadline_shows_due_date(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "2026-12-01"])
    captured = capsys.readouterr()
    assert "due 2026-12-01" in captured.out


# --- lock-in trigger ---


def _days_from_now(n):
    return (datetime.now(UTC).date() + timedelta(days=n)).isoformat()


def _set_lock_in_checked_on(db_path, iso_date):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_settings SET lock_in_checked_on = ?", (iso_date,))
    conn.commit()
    conn.close()


def _backdate_created_at(db_path, name, days_ago):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE goals SET created_at = ? WHERE name = ?",
        ((datetime.now(UTC) - timedelta(days=days_ago)).isoformat(), name),
    )
    conn.commit()
    conn.close()


def test_refresh_lock_in_skips_freshly_created_goal(tmp_path):
    db_path = tmp_path / "test.db"
    # A goal activated moments ago hasn't had any real time to fall behind
    # yet -- it shouldn't lock in on its very first evaluation.
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)

    status = goals.refresh_lock_in(db_path=db_path)

    assert status.locked is False


def test_refresh_lock_in_locks_when_falling_behind(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)

    status = goals.refresh_lock_in(db_path=db_path)

    assert status.locked is True
    assert status.goal_name == "Learn Rust"
    assert goals.get_mode(db_path=db_path) == "lock_in"


def test_refresh_lock_in_deactivates_other_goals_on_lock(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.set_mode("hardcore", db_path=db_path)
    goals.add_goal("Side Project", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("Side Project", db_path=db_path)

    goals.refresh_lock_in(db_path=db_path)

    by_name = {g.name: g.active for g in goals.list_goals(db_path=db_path)}
    assert by_name["Learn Rust"] is True
    assert by_name["Side Project"] is False


def test_refresh_lock_in_not_locked_with_sufficient_pace(tmp_path):
    db_path = tmp_path / "test.db"
    # 20h target, 60 days to the deadline: after 2h spent, required pace is
    # 18h / 60d = 0.3h/day. A 2h session in the last 4 days averages to
    # 0.5h/day over that window -- comfortably ahead of the requirement.
    goals.add_goal("Learn Rust", 20, _days_from_now(60), db_path=db_path)
    goal = goals.activate_goal("Learn Rust", db_path=db_path)
    _insert_session(
        db_path,
        goal.id,
        "completed",
        2 * 3600,
        started_at=datetime.now(UTC).isoformat(),
    )

    status = goals.refresh_lock_in(db_path=db_path)

    assert status.locked is False
    assert goals.get_mode(db_path=db_path) == "relaxed"


def test_refresh_lock_in_ignores_goal_without_deadline(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)

    status = goals.refresh_lock_in(db_path=db_path)

    assert status.locked is False


def test_refresh_lock_in_ignores_non_priority_goals(tmp_path):
    db_path = tmp_path / "test.db"
    goals.set_mode("hardcore", db_path=db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)  # priority 1, no deadline
    goals.add_goal("Side Project", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Side Project", db_path=db_path)  # priority 2, tight deadline

    status = goals.refresh_lock_in(db_path=db_path)

    assert status.locked is False


def test_refresh_lock_in_auto_unlocks_when_goal_no_longer_qualifies(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    # Simulate the next day and remove the goal's deadline -- nothing left
    # for the trigger to enforce.
    _set_lock_in_checked_on(db_path, _days_from_now(-1))
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET deadline = NULL WHERE name = 'Learn Rust'")
    conn.commit()
    conn.close()

    status = goals.refresh_lock_in(db_path=db_path)
    assert status.locked is False


def test_refresh_lock_in_caches_within_same_day(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goal = goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    # Even though pace now easily clears the requirement, the same-day
    # cache should keep reporting locked until the next evaluation day.
    _insert_session(
        db_path,
        goal.id,
        "completed",
        20 * 3600,
        started_at=datetime.now(UTC).isoformat(),
    )
    status = goals.refresh_lock_in(db_path=db_path)
    assert status.locked is True

    _set_lock_in_checked_on(db_path, _days_from_now(-1))
    status = goals.refresh_lock_in(db_path=db_path)
    assert status.locked is False


def test_refresh_lock_in_does_not_consume_days_slot_when_nothing_to_evaluate(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    # Not active yet -- an early check (as happens mid-activation via
    # _refuse_if_locked) must not burn today's real evaluation slot.
    assert goals.refresh_lock_in(db_path=db_path).locked is False

    goals.activate_goal("Learn Rust", db_path=db_path)
    status = goals.refresh_lock_in(db_path=db_path)
    assert status.locked is True


def test_unlock_requires_reason(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    goals.refresh_lock_in(db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.unlock("   ", db_path=db_path)


def test_unlock_requires_currently_locked(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.unlock("taking a break", db_path=db_path)


def test_unlock_preserves_for_rest_of_day(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    goals.unlock("taking a break", db_path=db_path)

    # Same-day re-check must not immediately re-lock, even though pace is
    # still objectively behind.
    status = goals.refresh_lock_in(db_path=db_path)
    assert status.locked is False


def test_unlock_can_update_hours_of_the_locked_goal(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    updated = goals.unlock("scaling back", field="hours", value="5", db_path=db_path)

    assert updated.hours == 5
    assert goals.list_goals(db_path=db_path)[0].hours == 5


def test_unlock_can_update_deadline_of_the_locked_goal(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    updated = goals.unlock(
        "pushing it back", field="deadline", value="200", db_path=db_path
    )

    assert updated.deadline == _days_from_now(200)
    assert goals.list_goals(db_path=db_path)[0].deadline == _days_from_now(200)


def test_unlock_rejects_invalid_hours_override(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.unlock("scaling back", field="hours", value="-5", db_path=db_path)


def test_handle_mode_blocked_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["mode", "relaxed"])
    captured = capsys.readouterr()
    assert "Locked in on 'Learn Rust'" in captured.out
    assert goals.get_mode(db_path=db_path) == "lock_in"


def test_handle_mode_read_only_allowed_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["mode"])
    captured = capsys.readouterr()
    assert "Current mode: lock_in" in captured.out


def test_handle_priority_blocked_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.add_goal("Side Project", 5, _days_from_now(30), db_path=db_path)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["priority", "Side", "Project"])
    captured = capsys.readouterr()
    assert "Locked in on 'Learn Rust'" in captured.out
    assert goals.list_goals(db_path=db_path)[1].active is False


def test_handle_deactivate_blocked_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["deactivate", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "Locked in on 'Learn Rust'" in captured.out
    assert goals.list_goals(db_path=db_path)[0].active is True


def test_handle_list_shows_lock_banner(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)

    goals.handle(["list"])
    captured = capsys.readouterr()
    assert "Locked in on 'Learn Rust'" in captured.out


def test_handle_unlock_missing_args(capsys):
    goals.handle(["unlock"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal unlock <reason>" in captured.out


def test_handle_unlock_not_locked(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["unlock", "reason"])
    captured = capsys.readouterr()
    assert "Not currently locked" in captured.out


def test_handle_unlock_success(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["unlock", "taking", "a", "break"])
    captured = capsys.readouterr()
    assert "Unlocked" in captured.out

    goals.handle(["mode", "relaxed"])
    captured = capsys.readouterr()
    assert "Mode set to 'relaxed'" in captured.out


def test_handle_unlock_with_hours_override(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["unlock", "scaling", "back", "hours", "5"])
    captured = capsys.readouterr()

    assert "Unlocked" in captured.out
    assert "target updated to 5.00h" in captured.out
    assert goals.list_goals(db_path=db_path)[0].hours == 5


def test_handle_unlock_with_deadline_override(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["unlock", "pushing", "it", "back", "deadline", "200"])
    captured = capsys.readouterr()

    assert "Unlocked" in captured.out
    assert f"deadline set to {_days_from_now(200)}" in captured.out
    assert goals.list_goals(db_path=db_path)[0].deadline == _days_from_now(200)


# --- goal update ---


def test_update_goal_renames(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    updated = goals.update_goal("Learn Rust", "name", "Learn Zig", db_path=db_path)
    assert updated.name == "Learn Zig"
    assert goals.list_goals(db_path=db_path)[0].name == "Learn Zig"


def test_update_goal_rename_rejects_empty(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "   ", db_path=db_path)


def test_update_goal_rename_rejects_duplicate_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.add_goal("Learn Zig", 5, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "learn zig", db_path=db_path)


def test_update_goal_changes_hours(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    updated = goals.update_goal("Learn Rust", "hours", "30", db_path=db_path)
    assert updated.hours == 30
    assert goals.list_goals(db_path=db_path)[0].hours == 30


def test_update_goal_hours_rejects_non_positive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "hours", "0", db_path=db_path)


def test_update_goal_hours_rejects_invalid_number(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "hours", "abc", db_path=db_path)


def test_update_goal_sets_deadline(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    updated = goals.update_goal("Learn Rust", "deadline", "2026-12-01", db_path=db_path)
    assert updated.deadline == "2026-12-01"


def test_update_goal_rejects_clearing_deadline_with_none(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, "2026-12-01", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "deadline", "none", db_path=db_path)


def test_update_goal_deadline_rejects_invalid_token(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "deadline", "not-a-date", db_path=db_path)


def test_update_goal_rejects_unknown_field(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "priority", "1", db_path=db_path)


def test_update_goal_rejects_missing_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.update_goal("Nonexistent", "hours", "10", db_path=db_path)


def test_update_goal_hours_forces_lock_in_recheck(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    # Same-day cache would normally keep reporting locked -- but lowering
    # the target down to what's already been spent (goal effectively met)
    # should unlock immediately.
    _insert_session(db_path, goal.id, "completed", 2 * 3600)
    goals.update_goal("Learn Rust", "hours", "2", db_path=db_path)
    assert goals.refresh_lock_in(db_path=db_path).locked is False


def test_update_goal_deadline_change_forces_lock_in_recheck(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    assert goals.refresh_lock_in(db_path=db_path).locked is True

    # Same-day cache would normally keep reporting locked -- but pushing the
    # deadline out after logging some time drops the required pace below
    # the recent pace, which should unlock immediately.
    _insert_session(
        db_path,
        goal.id,
        "completed",
        2 * 3600,
        started_at=datetime.now(UTC).isoformat(),
    )
    goals.update_goal("Learn Rust", "deadline", "200", db_path=db_path)
    assert goals.refresh_lock_in(db_path=db_path).locked is False


def test_parse_update_args_splits_multi_word_name():
    parsed = goals._parse_update_args(["Learn", "Rust", "hours", "30"])
    assert parsed == ("Learn Rust", "hours", "30")


def test_parse_update_args_joins_multi_word_value_for_name_field():
    parsed = goals._parse_update_args(["Learn", "Rust", "name", "Learn", "Zig"])
    assert parsed == ("Learn Rust", "name", "Learn Zig")


def test_parse_update_args_returns_none_without_field_keyword():
    assert goals._parse_update_args(["Learn", "Rust"]) is None


def test_handle_update_missing_args(capsys):
    goals.handle(["update", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal update" in captured.out


def test_handle_update_missing_value(capsys):
    goals.handle(["update", "Learn", "Rust", "hours"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal update" in captured.out


def test_handle_update_rename_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    goals.handle(["update", "Learn", "Rust", "name", "Learn", "Zig"])
    captured = capsys.readouterr()
    assert "Renamed 'Learn Rust' to 'Learn Zig'" in captured.out


def test_handle_update_hours_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    goals.handle(["update", "Learn", "Rust", "hours", "30"])
    captured = capsys.readouterr()
    assert "'Learn Rust' target updated to 30.00h" in captured.out


def test_handle_update_deadline_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    capsys.readouterr()

    goals.handle(["update", "Learn", "Rust", "deadline", "2026-12-01"])
    captured = capsys.readouterr()
    assert "'Learn Rust' deadline set to 2026-12-01" in captured.out


def test_handle_update_not_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["update", "Nonexistent", "hours", "10"])
    captured = capsys.readouterr()
    assert "No goal 'Nonexistent' found" in captured.out


def test_handle_update_hours_blocked_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    _backdate_created_at(db_path, "Learn Rust", 2)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["update", "Learn", "Rust", "hours", "0.01"])
    captured = capsys.readouterr()
    assert "Locked in on 'Learn Rust'" in captured.out
    assert goals.list_goals(db_path=db_path)[0].hours == 20


def test_handle_update_rename_allowed_when_locked(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    goals.refresh_lock_in(db_path=db_path)
    capsys.readouterr()

    goals.handle(["update", "Learn", "Rust", "name", "Learn", "Zig"])
    captured = capsys.readouterr()
    assert "Renamed 'Learn Rust' to 'Learn Zig'" in captured.out


# --- goal ids & numeric name guard ---


def test_add_goal_rejects_numeric_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("123", 20, _days_from_now(30), db_path=db_path)


def test_update_goal_rename_rejects_numeric_name(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "42", db_path=db_path)


def test_add_goal_rejects_reserved_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("help", 20, _days_from_now(30), db_path=db_path)


def test_add_goal_rejects_reserved_name_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("HELP", 20, _days_from_now(30), db_path=db_path)


def test_update_goal_rename_rejects_reserved_name(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "help", db_path=db_path)


def test_add_goal_rejects_reserved_name_log(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("log", 20, _days_from_now(30), db_path=db_path)


def test_update_goal_rename_rejects_reserved_name_log(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "log", db_path=db_path)


def test_add_goal_rejects_reserved_name_list(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("list", 20, _days_from_now(30), db_path=db_path)


def test_update_goal_rename_rejects_reserved_name_list(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.update_goal("Learn Rust", "name", "list", db_path=db_path)


def test_find_goal_by_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    found = goals.find_goal(str(goal.id), db_path=db_path)
    assert found is not None
    assert found.name == "Learn Rust"


def test_find_goal_by_name_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    found = goals.find_goal("learn rust", db_path=db_path)
    assert found is not None
    assert found.name == "Learn Rust"


def test_find_goal_returns_none_when_missing(tmp_path):
    db_path = tmp_path / "test.db"
    assert goals.find_goal("999", db_path=db_path) is None
    assert goals.find_goal("Nonexistent", db_path=db_path) is None


def test_delete_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    deleted = goals.delete_goal(str(goal.id), "reason", db_path=db_path)
    assert deleted.name == "Learn Rust"


def test_restore_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.delete_goal(str(goal.id), "reason", db_path=db_path)
    restored = goals.restore_goal(str(goal.id), db_path=db_path)
    assert restored.name == "Learn Rust"


def test_activate_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    activated = goals.activate_goal(str(goal.id), db_path=db_path)
    assert activated.active is True


def test_deactivate_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    goals.activate_goal(str(goal.id), db_path=db_path)
    deactivated = goals.deactivate_goal(str(goal.id), db_path=db_path)
    assert deactivated.active is False


def test_move_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    a = goals.add_goal("A", 5, _days_from_now(30), db_path=db_path)
    goals.add_goal("B", 5, _days_from_now(30), db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)

    goals.move_goal(str(a.id), "down", db_path=db_path)

    active = {g.name: g.priority for g in goals.list_goals(db_path=db_path)}
    assert active == {"B": 1, "A": 2}


def test_update_goal_accepts_id(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)
    updated = goals.update_goal(str(goal.id), "hours", "30", db_path=db_path)
    assert updated.hours == 30


def test_handle_list_shows_goal_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goal = goals.add_goal("Learn Rust", 20, _days_from_now(30), db_path=db_path)

    goals.handle(["list"])
    captured = capsys.readouterr()
    goal_line = next(line for line in captured.out.splitlines() if "Learn Rust" in line)
    assert str(goal.id) in goal_line


def test_handle_delete_accepts_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    goal = goals.list_goals(db_path=db_path)[0]
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda: "reason")
    goals.handle(["delete", str(goal.id)])
    captured = capsys.readouterr()
    assert "Archived goal 'Learn Rust'" in captured.out


def test_handle_priority_accepts_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    goal = goals.list_goals(db_path=db_path)[0]
    capsys.readouterr()

    goals.handle(["priority", str(goal.id)])
    captured = capsys.readouterr()
    assert "'Learn Rust' is now active (priority 1)" in captured.out


def test_handle_update_accepts_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    goals.handle(["add", "20", "Learn", "Rust", "30"])
    goal = goals.list_goals(db_path=db_path)[0]
    capsys.readouterr()

    goals.handle(["update", str(goal.id), "hours", "30"])
    captured = capsys.readouterr()
    assert "'Learn Rust' target updated to 30.00h" in captured.out


def test_handle_add_rejects_numeric_name(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "123", "30"])
    captured = capsys.readouterr()
    assert "cannot be a number" in captured.out
