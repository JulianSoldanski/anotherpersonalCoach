from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def get_profile(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = conn.execute(
            "SELECT max_hr, ftp_watts, updated_at FROM athlete_profile WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        return {"max_hr": None, "ftp_watts": None, "updated_at": None}
    if not row:
        return {"max_hr": None, "ftp_watts": None, "updated_at": None}
    return {
        "max_hr": row["max_hr"],
        "ftp_watts": row["ftp_watts"],
        "updated_at": row["updated_at"],
    }


def save_profile(
    conn: sqlite3.Connection,
    max_hr: float | None,
    ftp_watts: float | None,
) -> None:
    conn.execute(
        """
        UPDATE athlete_profile
        SET max_hr = ?, ftp_watts = ?, updated_at = ?
        WHERE id = 1
        """,
        (max_hr, ftp_watts, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
    )
    conn.commit()
