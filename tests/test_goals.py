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
