from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from schema_web import ensure_web_tables

load_dotenv()

LOG_FILE = os.getenv("ETL_LOG_FILE", "etl_run.log")
DB_PATH = os.getenv("TRIATHLON_DB_PATH", "triathlon_data.db")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
TRIATHLON_TYPES = {"Run", "Ride", "Swim"}
MAX_HEARTRATE = 200.0
STREAM_KEYS = "time,heartrate,watts"


def configure_logging() -> None:
    """Configure file + stderr logging once."""
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def validate_env() -> None:
    """Validate required Strava credentials."""
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        raise EnvironmentError(
            "Missing Strava credentials. Please set CLIENT_ID, CLIENT_SECRET and REFRESH_TOKEN."
        )


def get_fresh_access_token() -> str:
    """Refresh Strava access token using a refresh token."""
    auth_url = "https://www.strava.com/api/v3/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }

    response = requests.post(auth_url, data=payload, timeout=30)
    response.raise_for_status()
    access_token = response.json().get("access_token")
    if not access_token:
        raise ValueError("Strava token response does not contain access_token")
    return access_token


def extract_latest_activities(access_token: str, per_page: int = 50) -> list[dict[str, Any]]:
    """Fetch latest activities from Strava."""
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"per_page": per_page, "page": 1}

    response = requests.get(activities_url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected Strava activities response format")
    return data


def transform_activities(raw_activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter triathlon disciplines and normalize units."""
    def normalize_hr(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return min(float(value), MAX_HEARTRATE)
        except (TypeError, ValueError):
            return None

    transformed: list[dict[str, Any]] = []
    for activity in raw_activities:
        activity_type = activity.get("type")
        if activity_type not in TRIATHLON_TYPES:
            continue

        start_date = activity.get("start_date_local") or activity.get("start_date")
        if not start_date:
            continue

        transformed.append(
            {
                "id": activity.get("id"),
                "name": activity.get("name", "Unnamed activity"),
                "type": activity_type,
                "distance_km": round(float(activity.get("distance", 0.0)) / 1000.0, 3),
                "time_min": round(float(activity.get("moving_time", 0.0)) / 60.0, 2),
                "date": str(start_date)[:10],
                "avg_hr": normalize_hr(activity.get("average_heartrate")),
                "max_hr": normalize_hr(activity.get("max_heartrate")),
                "avg_watts": (
                    round(float(activity.get("average_watts")), 1)
                    if activity.get("average_watts") is not None
                    else None
                ),
            }
        )
    return transformed


def extract_activity_streams(access_token: str, activity_id: int) -> list[dict[str, Any]]:
    """
    Fetch per-sample streams for a single activity and normalize to rows.
    Each row represents one point in time with optional heartrate/watts.
    """
    streams_url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "keys": STREAM_KEYS,
        "key_by_type": "true",
    }
    response = requests.get(streams_url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError(f"Unexpected stream payload for activity {activity_id}")

    time_stream = (data.get("time") or {}).get("data") or []
    hr_stream = (data.get("heartrate") or {}).get("data") or []
    watts_stream = (data.get("watts") or {}).get("data") or []

    size = max(len(time_stream), len(hr_stream), len(watts_stream))
    rows: list[dict[str, Any]] = []
    for idx in range(size):
        second_offset = (
            int(time_stream[idx]) if idx < len(time_stream) and time_stream[idx] is not None else idx
        )

        hr_value = None
        if idx < len(hr_stream) and hr_stream[idx] is not None:
            try:
                hr_value = min(float(hr_stream[idx]), MAX_HEARTRATE)
            except (TypeError, ValueError):
                hr_value = None

        watts_value = None
        if idx < len(watts_stream) and watts_stream[idx] is not None:
            try:
                watts_value = float(watts_stream[idx])
            except (TypeError, ValueError):
                watts_value = None

        rows.append(
            {
                "activity_id": activity_id,
                "second_offset": second_offset,
                "heartrate": hr_value,
                "watts": watts_value,
            }
        )

    return rows


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create activities and stream tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            distance_km REAL NOT NULL,
            time_min REAL NOT NULL,
            date TEXT NOT NULL,
            avg_hr REAL,
            max_hr REAL,
            avg_watts REAL
        )
        """
    )
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()
    }
    if "avg_hr" not in existing_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN avg_hr REAL")
    if "max_hr" not in existing_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN max_hr REAL")
    if "avg_watts" not in existing_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN avg_watts REAL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_streams (
            activity_id INTEGER NOT NULL,
            second_offset INTEGER NOT NULL,
            heartrate REAL,
            watts REAL,
            PRIMARY KEY (activity_id, second_offset),
            FOREIGN KEY (activity_id) REFERENCES activities(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_streams_activity
        ON activity_streams(activity_id)
        """
    )
    ensure_web_tables(conn)
    conn.commit()


def upsert_activities(conn: sqlite3.Connection, activities: list[dict[str, Any]]) -> int:
    """Upsert activity rows into SQLite."""
    if not activities:
        return 0

    conn.executemany(
        """
        INSERT INTO activities (id, name, type, distance_km, time_min, date, avg_hr, max_hr, avg_watts)
        VALUES (:id, :name, :type, :distance_km, :time_min, :date, :avg_hr, :max_hr, :avg_watts)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            type = excluded.type,
            distance_km = excluded.distance_km,
            time_min = excluded.time_min,
            date = excluded.date,
            avg_hr = excluded.avg_hr,
            max_hr = excluded.max_hr,
            avg_watts = excluded.avg_watts
        """,
        activities,
    )
    conn.commit()
    return len(activities)


def replace_activity_streams(conn: sqlite3.Connection, stream_rows: list[dict[str, Any]]) -> int:
    """
    Replace stream data for all activities present in stream_rows.
    Strategy: delete existing rows for each affected activity, then bulk insert.
    """
    if not stream_rows:
        return 0

    activity_ids = sorted({row["activity_id"] for row in stream_rows})
    conn.executemany(
        "DELETE FROM activity_streams WHERE activity_id = ?",
        [(activity_id,) for activity_id in activity_ids],
    )
    conn.executemany(
        """
        INSERT INTO activity_streams (activity_id, second_offset, heartrate, watts)
        VALUES (:activity_id, :second_offset, :heartrate, :watts)
        """,
        stream_rows,
    )
    conn.commit()
    return len(stream_rows)


def run_etl() -> int:
    """Run complete ETL pipeline."""
    log = logging.getLogger("etljob")
    try:
        validate_env()
        log.info("Starting ETL job")

        token = get_fresh_access_token()
        log.info("Access token refresh successful")

        raw_activities = extract_latest_activities(token)
        log.info("Fetched %d raw activities from Strava", len(raw_activities))

        clean_activities = transform_activities(raw_activities)
        log.info("Transformed %d triathlon activities", len(clean_activities))

        stream_rows: list[dict[str, Any]] = []
        for activity in clean_activities:
            activity_id = activity["id"]
            if activity_id is None:
                continue
            try:
                rows = extract_activity_streams(token, int(activity_id))
                stream_rows.extend(rows)
            except requests.HTTPError:
                log.warning(
                    "Failed to fetch streams for activity %s (HTTP error). "
                    "Continuing without streams for this activity.",
                    activity_id,
                )
            except requests.RequestException:
                log.warning(
                    "Failed to fetch streams for activity %s (network error). "
                    "Continuing without streams for this activity.",
                    activity_id,
                )
            except Exception:
                log.warning(
                    "Failed to parse streams for activity %s. "
                    "Continuing without streams for this activity.",
                    activity_id,
                )
        log.info("Prepared %d per-second stream rows", len(stream_rows))

        with sqlite3.connect(DB_PATH) as conn:
            ensure_schema(conn)
            upserted = upsert_activities(conn, clean_activities)
            stream_upserted = replace_activity_streams(conn, stream_rows)

        log.info(
            "ETL job completed successfully, upserted %d activities and %d stream rows",
            upserted,
            stream_upserted,
        )
        return 0
    except requests.HTTPError:
        log.exception("HTTP error while calling Strava API")
    except requests.RequestException:
        log.exception("Network error while calling Strava API")
    except sqlite3.Error:
        log.exception("SQLite error during load step")
    except Exception:
        log.exception("Unhandled ETL error")
    return 1


if __name__ == "__main__":
    configure_logging()
    sys.exit(run_etl())
