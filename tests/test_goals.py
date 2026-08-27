import sqlite3

import pytest

from commands import goals


def test_add_goal_creates_row(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, db_path=db_path)

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
        goals.add_goal("   ", 20, db_path=db_path)


def test_add_goal_rejects_non_positive_hours(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.add_goal("Learn Rust", 0, db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.add_goal("Learn Rust", -5, db_path=db_path)


def test_add_goal_rejects_duplicate_name_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.add_goal("learn rust", 5, db_path=db_path)


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
    assert "add:" in captured.out
    assert "list:" in captured.out
    assert "delete:" in captured.out
    assert "priority:" in captured.out
    assert "deactivate:" in captured.out
    assert "move:" in captured.out
    assert "mode:" in captured.out
    assert "help:" in captured.out


def test_handle_add_missing_args(capsys):
    goals.handle(["add", "20"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal add" in captured.out


def test_handle_add_invalid_hours(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "abc", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "is not a valid number of hours" in captured.out


def test_handle_add_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "Added goal 'Learn Rust'" in captured.out


def test_handle_add_duplicate(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    capsys.readouterr()
    goals.handle(["add", "5", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "already exists" in captured.out


def test_delete_goal_removes_row(tmp_path):
    db_path = tmp_path / "test.db"
    goal = goals.add_goal("Learn Rust", 20, db_path=db_path)

    deleted = goals.delete_goal("Learn Rust", db_path=db_path)
    assert deleted.id == goal.id

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id FROM goals WHERE id = ?", (goal.id,)).fetchone()
    conn.close()
    assert row is None


def test_delete_goal_is_case_insensitive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, db_path=db_path)
    deleted = goals.delete_goal("learn rust", db_path=db_path)
    assert deleted.name == "Learn Rust"


def test_delete_goal_rejects_missing_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(goals.GoalError):
        goals.delete_goal("Nonexistent", db_path=db_path)


def test_delete_active_goal_closes_priority_gap(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 10, db_path=db_path)
    goals.add_goal("B", 10, db_path=db_path)
    goals.add_goal("C", 10, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)  # priority 1
    goals.activate_goal("B", db_path=db_path)  # priority 2
    goals.activate_goal("C", db_path=db_path)  # priority 3

    goals.delete_goal("B", db_path=db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name, priority FROM goals WHERE active = 1 ORDER BY priority"
    ).fetchall()
    conn.close()
    assert rows == [("A", 1), ("C", 2)]


def test_delete_inactive_goal_does_not_touch_active_priorities(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 10, db_path=db_path)
    goals.add_goal("B", 10, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)  # priority 1

    goals.delete_goal("B", db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT priority FROM goals WHERE name = 'A'").fetchone()
    conn.close()
    assert row == (1,)


def test_handle_delete_missing_args(capsys):
    goals.handle(["delete"])
    captured = capsys.readouterr()
    assert "[error] Usage: goal delete" in captured.out


def test_handle_delete_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    capsys.readouterr()
    goals.handle(["delete", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "Deleted goal 'Learn Rust'" in captured.out


def test_handle_delete_not_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["delete", "Nonexistent"])
    captured = capsys.readouterr()
    assert "No goal named 'Nonexistent' found" in captured.out


def test_list_goals_empty(tmp_path):
    db_path = tmp_path / "test.db"
    assert goals.list_goals(db_path=db_path) == []


def test_list_goals_orders_active_before_inactive_and_by_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Low", 10, db_path=db_path)
    goals.add_goal("High", 5, db_path=db_path)
    goals.add_goal("Inactive", 3, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET active = 1, priority = 2 WHERE name = 'Low'")
    conn.execute("UPDATE goals SET active = 1, priority = 1 WHERE name = 'High'")
    conn.commit()
    conn.close()

    result = [g.name for g in goals.list_goals(db_path=db_path)]
    assert result == ["High", "Low", "Inactive"]


def test_handle_list_empty(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["list"])
    captured = capsys.readouterr()
    assert "No goals yet" in captured.out


def test_handle_list_shows_active_and_inactive_sections(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(goals, "goals_db_path", lambda: db_path)
    goals.add_goal("Learn Rust", 20, db_path=db_path)
    goals.add_goal("Learn Go", 10, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE goals SET active = 1, priority = 1 WHERE name = 'Learn Rust'")
    conn.commit()
    conn.close()

    goals.handle(["list"])
    captured = capsys.readouterr()

    assert "Active:" in captured.out
    assert "Learn Rust (20.0h) [priority 1]" in captured.out
    assert "Inactive:" in captured.out
    assert "Learn Go (10.0h)" in captured.out


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
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.add_goal("C", 5, db_path=db_path)
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
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.add_goal("C", 5, db_path=db_path)
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
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.add_goal("C", 5, db_path=db_path)
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

    goals.add_goal("D", 5, db_path=db_path)
    activated = goals.activate_goal("D", db_path=db_path)
    assert activated.priority == 1

    by_name = {g.name: g for g in goals.list_goals(db_path=db_path)}
    assert by_name["D"].active is True
    assert by_name["D"].priority == 1
    assert by_name["B"].priority == 2


def test_activate_goal_assigns_next_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)

    first = goals.activate_goal("A", db_path=db_path)
    second = goals.activate_goal("B", db_path=db_path)

    assert first.active is True
    assert first.priority == 1
    assert second.priority == 2


def test_activate_goal_rejects_already_active(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
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
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)

    with pytest.raises(goals.SlotsFullError) as excinfo:
        goals.activate_goal("B", db_path=db_path)
    assert [g.name for g in excinfo.value.active_goals] == ["A"]


def test_deactivate_goal_renumbers_remaining(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.add_goal("C", 5, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)
    goals.activate_goal("C", db_path=db_path)

    goals.deactivate_goal("A", db_path=db_path)

    active = {g.name: g.priority for g in goals.list_goals(db_path=db_path) if g.active}
    assert active == {"B": 1, "C": 2}


def test_deactivate_goal_rejects_inactive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.deactivate_goal("A", db_path=db_path)


def test_move_goal_swaps_priority(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    goals.add_goal("B", 5, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)
    goals.activate_goal("B", db_path=db_path)

    goals.move_goal("B", "up", db_path=db_path)

    active = {g.name: g.priority for g in goals.list_goals(db_path=db_path)}
    assert active == {"B": 1, "A": 2}


def test_move_goal_rejects_past_edge(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    goals.activate_goal("A", db_path=db_path)

    with pytest.raises(goals.GoalError):
        goals.move_goal("A", "up", db_path=db_path)


def test_move_goal_rejects_inactive(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("A", 5, db_path=db_path)
    with pytest.raises(goals.GoalError):
        goals.move_goal("A", "down", db_path=db_path)


def test_handle_priority_activates_goal(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    capsys.readouterr()

    goals.handle(["priority", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "'Learn Rust' is now active (priority 1)" in captured.out


def test_handle_priority_slots_full_cancel(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "lock_in"])
    goals.handle(["add", "5", "A"])
    goals.handle(["add", "5", "B"])
    goals.handle(["priority", "A"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _: "n")
    goals.handle(["priority", "B"])
    captured = capsys.readouterr()
    assert "Cancelled." in captured.out
    assert goals.list_goals()[0].name == "A"
    assert goals.list_goals()[0].active is True


def test_handle_priority_slots_full_swap(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "lock_in"])
    goals.handle(["add", "5", "A"])
    goals.handle(["add", "5", "B"])
    goals.handle(["priority", "A"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _: "1")
    goals.handle(["priority", "B"])
    captured = capsys.readouterr()
    assert "'B' is now active (priority 1)" in captured.out

    active = {g.name: g.active for g in goals.list_goals()}
    assert active == {"A": False, "B": True}


def test_handle_deactivate_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "20", "Learn", "Rust"])
    goals.handle(["priority", "Learn", "Rust"])
    capsys.readouterr()

    goals.handle(["deactivate", "Learn", "Rust"])
    captured = capsys.readouterr()
    assert "'Learn Rust' is now inactive" in captured.out


def test_handle_move_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["add", "5", "A"])
    goals.handle(["add", "5", "B"])
    goals.handle(["priority", "A"])
    goals.handle(["priority", "B"])
    capsys.readouterr()

    goals.handle(["move", "B", "up"])
    captured = capsys.readouterr()
    assert "Moved 'B' up" in captured.out


def test_handle_mode_shows_current_mode(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode"])
    captured = capsys.readouterr()
    assert "Current mode: relaxed" in captured.out


def test_handle_mode_sets_mode(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(goals, "goals_db_path", lambda: tmp_path / "test.db")
    goals.handle(["mode", "hardcore"])
    captured = capsys.readouterr()
    assert "Mode set to 'hardcore'" in captured.out
