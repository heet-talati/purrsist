import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from commands import goals, goals_data, tracking, tracking_data


def _add_active_goal(db_path, name="Learn Rust", hours=20):
    goals.add_goal(name, hours, db_path=db_path)
    return goals.activate_goal(name, db_path=db_path)


def _days_from_now(n):
    return (datetime.now(UTC).date() + timedelta(days=n)).isoformat()


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


def test_start_session_normalizes_goal_name_case(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path, name="Learn Rust")

    session = tracking.start_session("LEARN rust", 25, db_path=db_path)

    assert session.goal_name == "Learn Rust"


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
    assert completed.focused_seconds == 25 * 60

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, ended_at, focused_seconds FROM sessions WHERE id = ?",
        (session.id,),
    ).fetchone()
    conn.close()
    assert row[0] == "completed"
    assert row[1] is not None
    assert row[2] == 25 * 60


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


def test_complete_session_subtracts_paused_seconds_from_focused_time(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)
    tracking.resume_session(session.id, 90, db_path=db_path)

    completed = tracking.complete_session(session.id, db_path=db_path)

    assert completed.focused_seconds == 25 * 60 - 90


def test_cancel_session_marks_cancelled(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    cancelled = tracking.cancel_session(session.id, db_path=db_path)

    assert cancelled.status == "cancelled"
    assert cancelled.ended_at is not None
    assert cancelled.focused_seconds == 25 * 60


def test_cancel_session_accounts_for_remaining_and_paused_time(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)
    tracking.resume_session(session.id, 60, db_path=db_path)

    cancelled = tracking.cancel_session(session.id, 300, db_path=db_path)

    assert cancelled.focused_seconds == 25 * 60 - 300 - 60


def test_cancel_session_total_paused_seconds_overrides_db_column(tmp_path):
    # A quit-while-paused folds the in-progress pause segment into the
    # countdown's in-memory total before it's ever persisted via resume, so
    # the caller's live total must win over the (stale) DB column.
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)  # never resumed

    cancelled = tracking.cancel_session(session.id, 0, 10, db_path=db_path)

    assert cancelled.paused_seconds == 10
    assert cancelled.focused_seconds == 25 * 60 - 10


def test_run_countdown_ticks_down_to_zero():
    session = tracking.Session(
        goal_id=1, goal_name="Learn Rust", planned_minutes=0.05, started_at="now"
    )
    sleeps = []
    renders = []

    outcome = tracking.run_countdown(
        session,
        sleep_fn=sleeps.append,
        render_fn=lambda remaining, paused: renders.append((remaining, paused)),
        poll_keypress_fn=lambda: None,
    )

    assert sleeps == [1, 1, 1]
    assert renders == [(3, False), (2, False), (1, False)]
    assert outcome.stopped_early is False
    assert outcome.remaining_seconds == 0
    assert outcome.total_paused_seconds == 0


def test_run_countdown_pause_then_resume_accumulates_paused_seconds():
    session = tracking.Session(
        goal_id=1, goal_name="Learn Rust", planned_minutes=0.05, started_at="now"
    )
    keys = iter(["p", None, "p", None, None])
    pauses = []
    resumes = []

    outcome = tracking.run_countdown(
        session,
        sleep_fn=lambda _: None,
        render_fn=lambda *_: None,
        poll_keypress_fn=lambda: next(keys),
        on_pause=lambda: pauses.append(True),
        on_resume=lambda delta: resumes.append(delta),
    )

    assert outcome.total_paused_seconds == 2
    assert outcome.stopped_early is False
    assert pauses == [True]
    assert resumes == [2]


def test_run_countdown_quit_key_stops_early():
    session = tracking.Session(
        goal_id=1, goal_name="Learn Rust", planned_minutes=0.05, started_at="now"
    )
    keys = iter(["q"])

    outcome = tracking.run_countdown(
        session,
        sleep_fn=lambda _: None,
        render_fn=lambda *_: None,
        poll_keypress_fn=lambda: next(keys),
    )

    assert outcome.stopped_early is True
    assert outcome.remaining_seconds == 3  # nothing ticked yet
    assert outcome.total_paused_seconds == 0


def test_run_countdown_quit_key_while_paused_counts_segment_as_paused():
    session = tracking.Session(
        goal_id=1, goal_name="Learn Rust", planned_minutes=0.05, started_at="now"
    )
    keys = iter(["p", "q"])

    outcome = tracking.run_countdown(
        session,
        sleep_fn=lambda _: None,
        render_fn=lambda *_: None,
        poll_keypress_fn=lambda: next(keys),
    )

    assert outcome.stopped_early is True
    assert outcome.total_paused_seconds == 1


def test_run_countdown_render_fn_receives_paused_state():
    session = tracking.Session(
        goal_id=1, goal_name="X", planned_minutes=0.05, started_at="now"
    )
    keys = iter(["p", "p", None, None, None])
    renders = []

    tracking.run_countdown(
        session,
        sleep_fn=lambda _: None,
        render_fn=lambda remaining, paused: renders.append((remaining, paused)),
        poll_keypress_fn=lambda: next(keys),
    )

    assert renders[0] == (3, True)
    assert renders[1] == (3, False)


def _seed_session(conn, goal_id, days_ago, status="completed", focused_seconds=60):
    started = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO sessions (goal_id, planned_minutes, started_at, status, "
        "focused_seconds) VALUES (?, 25, ?, ?, ?)",
        (goal_id, started, status, focused_seconds),
    )


def test_current_streak_days_zero_when_no_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    assert tracking_data.current_streak_days(db_path) == 0


def test_current_streak_days_counts_consecutive_days_including_today(tmp_path):
    db_path = tmp_path / "test.db"
    goal = _add_active_goal(db_path)
    conn = sqlite3.connect(db_path)
    for days_ago in (0, 1, 2):
        _seed_session(conn, goal.id, days_ago)
    conn.commit()
    conn.close()

    assert tracking_data.current_streak_days(db_path) == 3


def test_current_streak_days_continues_through_missed_today(tmp_path):
    db_path = tmp_path / "test.db"
    goal = _add_active_goal(db_path)
    conn = sqlite3.connect(db_path)
    for days_ago in (1, 2):
        _seed_session(conn, goal.id, days_ago)
    conn.commit()
    conn.close()

    assert tracking_data.current_streak_days(db_path) == 2


def test_current_streak_days_stops_at_gap(tmp_path):
    db_path = tmp_path / "test.db"
    goal = _add_active_goal(db_path)
    conn = sqlite3.connect(db_path)
    for days_ago in (0, 2):  # gap at day 1
        _seed_session(conn, goal.id, days_ago)
    conn.commit()
    conn.close()

    assert tracking_data.current_streak_days(db_path) == 1


def test_current_streak_days_ignores_zero_focus_sessions(tmp_path):
    db_path = tmp_path / "test.db"
    goal = _add_active_goal(db_path)
    conn = sqlite3.connect(db_path)
    _seed_session(conn, goal.id, 0, status="cancelled", focused_seconds=0)
    conn.commit()
    conn.close()

    assert tracking_data.current_streak_days(db_path) == 0


def test_upsert_log_inserts_new_row(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    tracking_data.upsert_log(session.id, "read chapter 3", db_path=db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT session_id, content, created_at, updated_at FROM logs "
        "WHERE session_id = ?",
        (session.id,),
    ).fetchone()
    conn.close()
    assert row[0] == session.id
    assert row[1] == "read chapter 3"
    assert row[2] is not None
    assert row[3] is not None


def test_upsert_log_rejects_missing_session(tmp_path):
    db_path = tmp_path / "test.db"
    with pytest.raises(tracking.TrackError):
        tracking_data.upsert_log(999, "read chapter 3", db_path=db_path)


def test_upsert_log_overwrites_existing_row_for_same_session(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking_data.upsert_log(session.id, "read chapter 3", db_path=db_path)

    conn = sqlite3.connect(db_path)
    original_created_at = conn.execute(
        "SELECT created_at FROM logs WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    conn.close()

    tracking_data.upsert_log(session.id, "actually chapter 4", db_path=db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT content, created_at, updated_at FROM logs WHERE session_id = ?",
        (session.id,),
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    content, created_at, _updated_at = rows[0]
    assert content == "actually chapter 4"
    assert created_at == original_created_at


def test_pause_session_marks_paused(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    paused = tracking.pause_session(session.id, db_path=db_path)
    assert paused.status == "paused"


def test_pause_session_rejects_not_running(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)

    with pytest.raises(tracking.TrackError):
        tracking.pause_session(session.id, db_path=db_path)


def test_resume_session_restores_running_and_accumulates_paused(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)

    resumed = tracking.resume_session(session.id, 5, db_path=db_path)
    assert resumed.status == "running"
    assert resumed.paused_seconds == 5

    tracking.pause_session(session.id, db_path=db_path)
    resumed_again = tracking.resume_session(session.id, 3, db_path=db_path)
    assert resumed_again.paused_seconds == 8


def test_resume_session_rejects_not_paused(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)

    with pytest.raises(tracking.TrackError):
        tracking.resume_session(session.id, 5, db_path=db_path)


def test_cancel_session_from_paused_state(tmp_path):
    db_path = tmp_path / "test.db"
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    tracking.pause_session(session.id, db_path=db_path)

    cancelled = tracking.cancel_session(session.id, db_path=db_path)
    assert cancelled.status == "cancelled"


def test_parse_start_args_defaults_minutes():
    name, minutes = tracking._parse_start_args(["Learn", "Rust"])
    assert name == "Learn Rust"
    assert minutes == tracking.DEFAULT_MINUTES


def test_parse_start_args_reads_trailing_minutes():
    name, minutes = tracking._parse_start_args(["Learn", "Rust", "45"])
    assert name == "Learn Rust"
    assert minutes == 45


def test_parse_start_args_reads_pomodoro_preset():
    name, minutes = tracking._parse_start_args(["Learn", "Rust", "pomodoro"])
    assert name == "Learn Rust"
    assert minutes == 25


def test_parse_start_args_reads_short_preset():
    name, minutes = tracking._parse_start_args(["Learn", "Rust", "short"])
    assert name == "Learn Rust"
    assert minutes == 15


def test_parse_start_args_preset_is_case_insensitive():
    name, minutes = tracking._parse_start_args(["Learn", "Rust", "SHORT"])
    assert name == "Learn Rust"
    assert minutes == 15


def test_parse_start_args_single_token_is_name():
    name, minutes = tracking._parse_start_args(["Rust"])
    assert name == "Rust"
    assert minutes == tracking.DEFAULT_MINUTES


def test_handle_missing_goal_name(capsys):
    tracking.handle([])
    captured = capsys.readouterr()
    assert "[error] Usage: track" in captured.out


def test_handle_help_shows_usage(capsys):
    tracking.handle(["help"])
    captured = capsys.readouterr()
    assert "track <goal_name>" in captured.out
    assert "track help" in captured.out
    assert "track log" in captured.out


def test_handle_start_rejects_missing_goal(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: tmp_path / "test.db")
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: tmp_path / "test.db")
    tracking.handle(["Nonexistent", "25"])
    captured = capsys.readouterr()
    assert "No goal named 'Nonexistent' found" in captured.out


def test_handle_start_refuses_non_priority_goal_once_locked(
    monkeypatch, capsys, tmp_path
):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)

    goals.add_goal("Learn Rust", 20, _days_from_now(2), db_path=db_path)
    goals.activate_goal("Learn Rust", db_path=db_path)
    goals.set_mode("hardcore", db_path=db_path)
    goals.add_goal("Side Project", 5, db_path=db_path)
    goals.activate_goal("Side Project", db_path=db_path)
    capsys.readouterr()

    # Starting a session on the neglected priority goal's sibling is what
    # should trigger the lock-in check and deactivate the sibling.
    tracking.handle(["Side", "Project", "25"])
    captured = capsys.readouterr()

    assert "is not active" in captured.out
    assert goals.list_goals(db_path=db_path)[1].active is False


def test_handle_start_runs_countdown_to_completion(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    monkeypatch.setattr(tracking.time, "sleep", lambda _: None)
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: None)
    tracking.handle(["Learn", "Rust", "0.02"])

    captured = capsys.readouterr()
    assert "Tracking 'Learn Rust'" in captured.out
    assert "Session complete for 'Learn Rust'" in captured.out
    assert "\a" in captured.out  # terminal bell on natural completion
    assert "TIME'S UP" in captured.out

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM sessions").fetchone()[0]
    conn.close()
    assert status == "completed"


def test_handle_start_accepts_preset_name(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    monkeypatch.setattr(tracking.time, "sleep", lambda _: None)
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: None)
    tracking.handle(["Learn", "Rust", "short"])

    captured = capsys.readouterr()
    assert "Tracking 'Learn Rust' for 15 min" in captured.out

    conn = sqlite3.connect(db_path)
    planned_minutes = conn.execute("SELECT planned_minutes FROM sessions").fetchone()[0]
    conn.close()
    assert planned_minutes == 15


def test_handle_start_ctrl_c_has_no_bell_or_completion_banner(
    monkeypatch, capsys, tmp_path
):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    def _raise(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(tracking.time, "sleep", _raise)
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: None)
    tracking.handle(["Learn", "Rust", "25"])

    captured = capsys.readouterr()
    assert "\a" not in captured.out
    assert "TIME'S UP" not in captured.out


def test_handle_start_ctrl_c_cancels_session(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    def _raise(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(tracking.time, "sleep", _raise)
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: None)
    tracking.handle(["Learn", "Rust", "25"])

    captured = capsys.readouterr()
    assert "Stopped 'Learn Rust' early" in captured.out

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM sessions").fetchone()[0]
    conn.close()
    assert status == "cancelled"


def test_handle_start_quit_key_cancels_session_with_summary(
    monkeypatch, capsys, tmp_path
):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    keys = iter(["q"])
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: next(keys))
    monkeypatch.setattr(tracking.time, "sleep", lambda _: None)

    tracking.handle(["Learn", "Rust", "0.05"])

    captured = capsys.readouterr()
    assert "Stopped 'Learn Rust' early" in captured.out
    assert "focused (planned 00:03)" in captured.out

    conn = sqlite3.connect(db_path)
    status = conn.execute("SELECT status FROM sessions").fetchone()[0]
    conn.close()
    assert status == "cancelled"


def test_handle_start_pause_then_resume_completes(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)

    keys = iter(["p", "p", None, None, None])
    monkeypatch.setattr(tracking, "_default_poll_keypress", lambda: next(keys))
    monkeypatch.setattr(tracking.time, "sleep", lambda _: None)

    tracking.handle(["Learn", "Rust", "0.05"])

    captured = capsys.readouterr()
    assert "Session complete for 'Learn Rust'" in captured.out

    conn = sqlite3.connect(db_path)
    status, paused_seconds = conn.execute(
        "SELECT status, paused_seconds FROM sessions"
    ).fetchone()
    conn.close()
    assert status == "completed"
    assert paused_seconds == 1


def test_handle_log_writes_entry(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: db_path)
    monkeypatch.setattr(goals_data, "goals_db_path", lambda: db_path)
    _add_active_goal(db_path)
    session = tracking.start_session("Learn Rust", 25, db_path=db_path)
    capsys.readouterr()

    tracking.handle(["log", str(session.id), "did", "the", "thing"])

    captured = capsys.readouterr()
    assert "Logged" in captured.out

    conn = sqlite3.connect(db_path)
    content = conn.execute(
        "SELECT content FROM logs WHERE session_id = ?", (session.id,)
    ).fetchone()[0]
    conn.close()
    assert content == "did the thing"


def test_handle_log_rejects_missing_args(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: tmp_path / "test.db")

    tracking.handle(["log"])
    assert "Usage: track log" in capsys.readouterr().out

    tracking.handle(["log", "1"])
    assert "Usage: track log" in capsys.readouterr().out


def test_handle_log_rejects_non_numeric_session_id(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: tmp_path / "test.db")

    tracking.handle(["log", "abc", "did", "the", "thing"])

    assert "[error]" in capsys.readouterr().out


def test_handle_log_rejects_missing_session(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(tracking_data, "sessions_db_path", lambda: tmp_path / "test.db")

    tracking.handle(["log", "999", "did", "the", "thing"])

    assert "No session with id 999" in capsys.readouterr().out
