from __future__ import annotations

import sqlite3
from typing import Any


def list_all_races(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        cur = conn.execute(
            """
            SELECT id, name, race_date, discipline, goal_type, goal_value, notes, status
            FROM race_goals
            ORDER BY race_date DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error:
        return []


def get_race(conn: sqlite3.Connection, race_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, race_date, discipline, goal_type, goal_value, notes, status
        FROM race_goals WHERE id = ?
        """,
        (race_id,),
    ).fetchone()
    return dict(row) if row else None


def create_race(
    conn: sqlite3.Connection,
    name: str,
    race_date: str,
    discipline: str,
    goal_type: str,
    goal_value: str | None,
    notes: str | None,
    status: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO race_goals (name, race_date, discipline, goal_type, goal_value, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, race_date, discipline, goal_type, goal_value or None, notes or None, status),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_race(
    conn: sqlite3.Connection,
    race_id: int,
    name: str,
    race_date: str,
    discipline: str,
    goal_type: str,
    goal_value: str | None,
    notes: str | None,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE race_goals SET
            name = ?, race_date = ?, discipline = ?, goal_type = ?,
            goal_value = ?, notes = ?, status = ?
        WHERE id = ?
        """,
        (
            name,
            race_date,
            discipline,
            goal_type,
            goal_value or None,
            notes or None,
            status,
            race_id,
        ),
    )
    conn.commit()


def delete_race(conn: sqlite3.Connection, race_id: int) -> None:
    conn.execute("DELETE FROM race_goals WHERE id = ?", (race_id,))
    conn.commit()
