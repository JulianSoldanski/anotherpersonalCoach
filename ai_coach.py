"""
AI Coach: reads recent triathlon activities from SQLite and requests a daily workout
recommendation from the Google Gemini API (default: gemini-2.5-flash).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

LOG_FILE = os.getenv("AI_COACH_LOG_FILE", "ai_coach_run.log")
DB_PATH = os.getenv("TRIATHLON_DB_PATH", "triathlon_data.db")
GEMINI_MODEL = os.getenv("GEMINI_COACH_MODEL", "gemini-2.5-flash")
PLAN_DAYS = int(os.getenv("AI_COACH_PLAN_DAYS", "7"))
SYSTEM_INSTRUCTION = (
    "You are an expert triathlon coach. Be concise, specific, and safety-aware. "
    "Use metric units unless the athlete data suggests otherwise."
)
TRIATHLON_TYPES = ("Run", "Ride", "Swim")


def fetch_athlete_profile(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Load single-row athlete profile if table exists."""
    try:
        row = conn.execute(
            "SELECT max_hr, ftp_watts FROM athlete_profile WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {"max_hr": row[0], "ftp_watts": row[1]}


def fetch_upcoming_races(
    conn: sqlite3.Connection, limit: int = 10
) -> list[dict[str, Any]]:
    """Planned races on or after today."""
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
    except sqlite3.Error:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def format_profile_block(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "Athlete profile: not configured (save Max HR and FTP in the web UI)."
    max_hr = profile.get("max_hr")
    ftp = profile.get("ftp_watts")
    if max_hr is None and ftp is None:
        return "Athlete profile: not configured (save Max HR and FTP in the web UI)."
    parts: list[str] = []
    if max_hr is not None:
        parts.append(f"Max HR: {float(max_hr):.0f} bpm")
    if ftp is not None:
        parts.append(f"FTP (bike): {float(ftp):.0f} W")
    return "Athlete profile:\n" + "\n".join(parts)


def format_races_block(races: list[dict[str, Any]]) -> str:
    if not races:
        return "Upcoming races: none recorded (add races in the web UI)."
    lines: list[str] = []
    for r in races:
        gv = r.get("goal_value")
        gv_s = str(gv).strip() if gv not in (None, "") else "(not specified)"
        notes = r.get("notes") or ""
        lines.append(
            f"- {r.get('race_date')}: {r.get('name')} | discipline: {r.get('discipline')} | "
            f"goal_type: {r.get('goal_type')} | goal: {gv_s}"
            + (f" | notes: {notes}" if notes else "")
        )
    return "Upcoming races and goals:\n" + "\n".join(lines)


def configure_logging() -> None:
    """Attach file + stderr handlers; idempotent for repeated calls in tests."""
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


def connect_db(path: str) -> sqlite3.Connection:
    """Open SQLite read-only where possible."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")
    uri = f"file:{p.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def fetch_last_days_activities(
    conn: sqlite3.Connection,
    days: int = 7,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """
    Load activities from the last `days` calendar days (inclusive of end_date).
    Expects table `activities` with columns: id, name, type, distance_km, time_min, date.
    """
    end = end_date or date.today()
    start = end - timedelta(days=days - 1)
    start_s = start.isoformat()
    end_s = end.isoformat()

    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(activities)").fetchall()
    }
    has_avg_hr = "avg_hr" in existing_columns
    has_max_hr = "max_hr" in existing_columns
    has_avg_watts = "avg_watts" in existing_columns

    types_placeholders = ",".join("?" * len(TRIATHLON_TYPES))
    select_avg_hr = "avg_hr" if has_avg_hr else "NULL AS avg_hr"
    select_max_hr = "max_hr" if has_max_hr else "NULL AS max_hr"
    select_avg_watts = "avg_watts" if has_avg_watts else "NULL AS avg_watts"
    query = f"""
        SELECT id, name, type, distance_km, time_min, date,
               {select_avg_hr},
               {select_max_hr},
               {select_avg_watts}
        FROM activities
        WHERE type IN ({types_placeholders})
          AND date(date) >= date(?)
          AND date(date) <= date(?)
        ORDER BY date(date) ASC, id ASC
    """
    cursor = conn.execute(query, (*TRIATHLON_TYPES, start_s, end_s))
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def format_training_block(rows: list[dict[str, Any]]) -> str:
    """Human-readable block for the LLM prompt."""
    if not rows:
        return "No triathlon activities (Run/Ride/Swim) recorded in the selected window."

    lines: list[str] = []
    for r in rows:
        hr_part = ""
        if r.get("avg_hr") is not None or r.get("max_hr") is not None:
            avg_hr = f"{r.get('avg_hr'):.0f}" if r.get("avg_hr") is not None else "-"
            max_hr = f"{r.get('max_hr'):.0f}" if r.get("max_hr") is not None else "-"
            hr_part = f" | HR avg/max: {avg_hr}/{max_hr} bpm"
        watts_part = ""
        if r.get("avg_watts") is not None:
            watts_part = f" | Avg watts: {r.get('avg_watts'):.1f} W"
        lines.append(
            f"- {r.get('date')}: {r.get('type')} | {r.get('name')} | "
            f"{r.get('distance_km')} km | {r.get('time_min')} min"
            f"{hr_part}{watts_part} (id={r.get('id')})"
        )
    return "\n".join(lines)


def build_coach_prompt(
    training_text: str,
    today: date,
    plan_days: int,
    profile_block: str,
    races_block: str,
) -> str:
    """Structured user prompt for the coach."""
    return f"""You are an elite triathlon coach. Use the athlete profile and upcoming races to align intensity and recovery.

{profile_block}

{races_block}

Training history from the last 7 days (Run, Ride, Swim only):

{training_text}

Today is {today.isoformat()}. Create a structured training plan for the next {plan_days} days.

Constraints:
- Align intensity with FTP (bike) and heart-rate zones implied by Max HR when relevant.
- Respect taper or priority sessions leading up to upcoming races.
- Return exactly one workout recommendation per day for the next {plan_days} days.
- For each day include: discipline, session structure, target duration, and intensity guidance.
- Include recovery/rest day(s) if needed based on recent load.
- Keep it practical for one athlete and avoid generic advice.

Output format:
Day 1 (YYYY-MM-DD): ...
Day 2 (YYYY-MM-DD): ...
...
Day {plan_days} (YYYY-MM-DD): ...
"""


def get_coaching_recommendation(
    client: genai.Client,
    user_prompt: str,
    model: str,
) -> str:
    """Call Gemini generate_content; raise on API failure, block, or empty text."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.4,
            ),
        )
    except Exception:
        logging.exception("Gemini API request failed")
        raise

    try:
        text = (response.text or "").strip()
    except Exception as e:
        logging.error("Could not read response text: %s", e)
        raise ValueError("Gemini returned no readable text (blocked or empty candidates)") from e

    if not text:
        raise ValueError("Gemini returned empty content")
    return text


def resolve_gemini_api_key() -> str | None:
    """Prefer GEMINI_API_KEY; fall back to GOOGLE_API_KEY (AI Studio / Client default)."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def generate_coaching_plan_text() -> tuple[str | None, str | None]:
    """
    Build prompt from DB and call Gemini. Returns (plan_text, error_message).
    Used by CLI and web UI.
    """
    api_key = resolve_gemini_api_key()
    if not api_key:
        return None, "Set GEMINI_API_KEY or GOOGLE_API_KEY for Gemini"

    try:
        conn = connect_db(DB_PATH)
    except FileNotFoundError as e:
        return None, str(e)

    try:
        rows = fetch_last_days_activities(conn, days=7)
        profile = fetch_athlete_profile(conn)
        races = fetch_upcoming_races(conn)
    except sqlite3.Error as e:
        return None, f"SQLite error: {e}"
    finally:
        conn.close()

    today = date.today()
    training_block = format_training_block(rows)
    profile_block = format_profile_block(profile)
    races_block = format_races_block(races)
    user_prompt = build_coach_prompt(
        training_block, today, PLAN_DAYS, profile_block, races_block
    )

    client = genai.Client(api_key=api_key)
    try:
        recommendation = get_coaching_recommendation(client, user_prompt, GEMINI_MODEL)
    except Exception as e:
        return None, str(e)
    return recommendation, None


def main() -> int:
    configure_logging()
    log = logging.getLogger("ai_coach")

    recommendation, err = generate_coaching_plan_text()
    if err:
        log.error("%s", err)
        return 1

    log.info("Using Gemini model %s", GEMINI_MODEL)
    log.info("Generating plan for next %d days", PLAN_DAYS)
    log.info("Coach recommendation:\n%s", recommendation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
