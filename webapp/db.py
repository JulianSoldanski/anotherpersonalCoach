from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from schema_web import ensure_web_tables

DB_PATH = os.getenv("TRIATHLON_DB_PATH", "triathlon_data.db")


def get_db_path() -> Path:
    return Path(DB_PATH)


def connect_rw() -> sqlite3.Connection:
    """Read-write connection for forms."""
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_web_tables(conn)
    conn.commit()
    return conn


def init_schema() -> None:
    """Ensure web tables exist (call on app startup)."""
    with connect_rw():
        pass
