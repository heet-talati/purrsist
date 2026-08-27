import sqlite3
from pathlib import Path

DEFAULT_MODE = "relaxed"


def connect(path: Path) -> sqlite3.Connection:
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
            archived_at TEXT,
            delete_reason TEXT,
            deadline TEXT,
            CHECK (priority IS NULL OR priority BETWEEN 1 AND 3)
        )
        """
    )
    goal_columns = {row[1] for row in conn.execute("PRAGMA table_info(goals)")}
    if "archived_at" not in goal_columns:
        conn.execute("ALTER TABLE goals ADD COLUMN archived_at TEXT")
    if "delete_reason" not in goal_columns:
        conn.execute("ALTER TABLE goals ADD COLUMN delete_reason TEXT")
    if "deadline" not in goal_columns:
        conn.execute("ALTER TABLE goals ADD COLUMN deadline TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL CHECK (mode IN ('lock_in', 'hardcore', 'relaxed')),
            lock_in_locked INTEGER NOT NULL DEFAULT 0,
            lock_in_checked_on TEXT
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_settings (id, mode) VALUES (1, ?)", (DEFAULT_MODE,)
    )
    app_settings_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(app_settings)")
    }
    if "lock_in_locked" not in app_settings_columns:
        conn.execute(
            "ALTER TABLE app_settings ADD COLUMN lock_in_locked INTEGER NOT NULL DEFAULT 0"
        )
    if "lock_in_checked_on" not in app_settings_columns:
        conn.execute("ALTER TABLE app_settings ADD COLUMN lock_in_checked_on TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES goals(id),
            planned_minutes REAL NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            paused_seconds INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'paused', 'completed', 'cancelled')),
            focused_seconds INTEGER
        )
        """
    )
    session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "focused_seconds" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN focused_seconds INTEGER")
    conn.commit()
    return conn
