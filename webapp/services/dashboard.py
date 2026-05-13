from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any


def recent_activities(conn: sqlite3.Connection, limit: int = 12) -> list[dict[str, Any]]:
    try:
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()
        }
    except sqlite3.Error:
        return []
    has_avg_hr = "avg_hr" in existing_columns
    has_avg_watts = "avg_watts" in existing_columns
    select_extra = ""
    if has_avg_hr:
        select_extra += ", avg_hr"
    if has_avg_watts:
        select_extra += ", avg_watts"
    try:
        cur = conn.execute(
            f"""
            SELECT id, name, type, distance_km, time_min, date{select_extra}
            FROM activities
            ORDER BY date(date) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error:
        return []


def upcoming_races(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    try:
        cur = conn.execute(
            """
            SELECT id, name, race_date, discipline, goal_type, goal_value, notes, status
            FROM race_goals
            WHERE race_date >= ? AND status = 'planned'
            ORDER BY race_date ASC
            LIMIT ?
            """,
            (today, limit),
        )
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error:
        return []


def weekly_totals(conn: sqlite3.Connection, days: int = 7) -> dict[str, Any]:
    """Sum distance (km) and time (min) by type for last `days` calendar days."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    try:
        cur = conn.execute(
            """
            SELECT type,
                   SUM(distance_km) AS km,
                   SUM(time_min) AS minutes,
                   COUNT(*) AS sessions
            FROM activities
            WHERE date(date) >= date(?) AND date(date) <= date(?)
            GROUP BY type
            """,
            (start.isoformat(), end.isoformat()),
        )
        by_type: dict[str, dict[str, float]] = {}
        for row in cur.fetchall():
            by_type[row["type"]] = {
                "km": row["km"] or 0,
                "minutes": row["minutes"] or 0,
                "sessions": row["sessions"] or 0,
            }
        return {"start": start.isoformat(), "end": end.isoformat(), "by_type": by_type}
    except sqlite3.Error:
        return {"start": start.isoformat(), "end": end.isoformat(), "by_type": {}}
