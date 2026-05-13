"""
SQLite DDL for web UI tables (athlete profile, race goals).
Called from ETL ensure_schema and webapp startup.
"""
from __future__ import annotations

import sqlite3


def ensure_web_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS athlete_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            max_hr REAL,
            ftp_watts REAL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO athlete_profile (id, max_hr, ftp_watts, updated_at)
        VALUES (1, NULL, NULL, datetime('now'))
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS race_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            race_date TEXT NOT NULL,
            discipline TEXT NOT NULL,
            goal_type TEXT NOT NULL,
            goal_value TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'planned'
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_race_goals_date
        ON race_goals(race_date)
        """
    )
