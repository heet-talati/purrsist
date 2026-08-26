import sqlite3

import pytest

from commands import goals, tracking


def _add_active_goal(db_path, name="Learn Rust", hours=20):
    goals.add_goal(name, hours, db_path=db_path)
    return goals.activate_goal(name, db_path=db_path)


def test_start_session_creates_row(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)

    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    assert session.goal_name == "Learn Rust"
    assert session.planned_minutes == 25
    assert session.status == "running"
    assert session.ended_at is None
    assert session.id is not None

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT planned_minutes, status FROM sessions WHERE id = ?", (session.id,)
    ).fetchone()
    conn.close()
    assert row == (25, "running")


def test_start_session_rejects_empty_name(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(tracking.TrackError):
        tracking.start_session("   ", 25, db_path=db_path)


def test_start_session_rejects_non_positive_minutes(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    with pytest.raises(tracking.TrackError):
        tracking.start_session("Learn Rust", 0, db_path=db_path)


def test_start_session_rejects_missing_goal(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(tracking.TrackError):
        tracking.start_session("Nonexistent", 25, db_path=db_path)


def test_start_session_rejects_inactive_goal(tmp_path):
    db_path = tmp_path / "test.db"
    goals.add_goal("Learn Rust", 20, db_path=db_path)
    with pytest.raises(tracking.TrackError):
        tracking.start_session("Learn Rust", 25, db_path=db_path)


def test_complete_session_marks_completed(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    completed = tracking.complete_session(session.id, db_path=db_path)

    assert completed.status == "completed"
    assert completed.ended_at is not None

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, ended_at FROM sessions WHERE id = ?", (session.id,)
    ).fetchone()
    conn.close()
    assert row[0] == "completed"
    assert row[1] is not None


def test_complete_session_rejects_missing_session(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(tracking.TrackError):
        tracking.complete_session(999, db_path=db_path)


def test_complete_session_rejects_already_completed(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.complete_session(session.id, db_path=db_path)

    with pytest.raises(tracking.TrackError):
        tracking.complete_session(session.id, db_path=db_path)


def test_cancel_session_marks_cancelled(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    cancelled = tracking.cancel_session(session.id, db_path=db_path)

    assert cancelled.status == "cancelled"
    assert cancelled.ended_at is not None


def test_run_countdown_ticks_down_to_zero():
    session = tracking.Session(
        goal_id=1, goal_name="Learn Rust", planned_minutes=0.05, started_at="now"
    )
    sleeps = []
    writes = []

    tracking.run_countdown(session, sleep_fn=sleeps.append, write_fn=writes.append)

    assert sleeps == [1, 1, 1]
    assert len(writes) == 4  # 3 ticks + final clear line
    assert "00:03" in writes[0]
    assert "00:01" in writes[2]


def test_parse_start_args_defaults_minutes():
    name, minutes = tracking._parse_start_args(["Learn", "Rust"])
    assert name == "Learn Rust"
    assert minutes == tracking.DEFAULT_MINUTES


def test_parse_start_args_reads_trailing_minutes():
    name, minutes = tracking._parse_start_args(["Learn", "Rust", "45"])
    assert name == "Learn Rust"
    assert minutes == 45


def test_parse_start_args_single_token_is_name():
    name, minutes = tracking._parse_start_args(["Rust"])
    assert name == "Rust"
    assert minutes == tracking.DEFAULT_MINUTES


def test_handle_missing_subcommand(capsys):
    tracking.handle([])
    captured = capsys.readouterr()
    assert "[error] Usage: track" in captured.out


def test_handle_unknown_subcommand(capsys):
    tracking.handle(["frobnicate"])
    captured = capsys.readouterr()
    assert "Unknown track subcommand" in captured.out


def test_handle_help_lists_subcommands(capsys):
    tracking.handle(["help"])
    captured = capsys.readouterr()
    assert "start:" in captured.out
    assert "help:" in captured.out


def test_handle_start_missing_args(capsys):
    tracking.handle(["start"])
    captured = capsys.readouterr()
    assert "[error] Usage: track start" in captured.out


def test_handle_start_rejects_missing_goal(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(tracking, "sessions_db_path", lambda: tmp_path / "test.db")
    tracking.handle(["start", "Nonexistent", "25"])
    captured = capsys.readouterr()
    assert "No goal named 'Nonexistent' found" in captured.out


def test_handle_start_runs_countdown_to_completion(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    monkeypatch.setattr(tracking.time, "sleep", lambda _: None)
    tracking.handle(["start", "Learn", "Rust", "0.02"])

    captured = capsys.readouterr()
    assert "Tracking 'Learn Rust'" in captured.out
    assert "Session complete for 'Learn Rust'" in captured.out

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM sessions").fetchone()[0]
    conn.close()
    assert status == "completed"


def test_handle_start_ctrl_c_cancels_session(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    def _raise(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(tracking.time, "sleep", _raise)
    tracking.handle(["start", "Learn", "Rust", "25"])

    captured = capsys.readouterr()
    assert "Stopped 'Learn Rust' early" in captured.out

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM sessions").fetchone()[0]
    conn.close()
    assert status == "cancelled"
