from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ai_coach import PLAN_DAYS, generate_coaching_plan_text

from webapp.db import DB_PATH, connect_rw, init_schema
from webapp.services import dashboard, profile as profile_svc
from webapp.services import races as races_svc

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DISCIPLINES = ("Triathlon", "Run", "Ride", "Swim")
GOAL_TYPES = ("completion", "time", "power", "hr")
RACE_STATUSES = ("planned", "completed", "cancelled")

WEB_LOG_FILE = os.getenv("WEB_LOG_FILE", "webapp_run.log")


def configure_logging() -> None:
    log_path = Path(WEB_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(WEB_LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def parse_optional_float(raw: str | None, label: str, low: float, high: float) -> tuple[float | None, str | None]:
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        v = float(str(raw).strip())
    except ValueError:
        return None, f"{label} must be a number."
    if v < low or v > high:
        return None, f"{label} must be between {low} and {high}."
    return v, None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    init_schema()
    yield


app = FastAPI(title="Triathlon Coach", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db_exists = Path(DB_PATH).is_file()
    activities: list[dict[str, Any]] = []
    races_up: list[dict[str, Any]] = []
    weekly: dict[str, Any] = {}
    profile_row: dict[str, Any] = {}
    if db_exists:
        with connect_rw() as conn:
            activities = dashboard.recent_activities(conn)
            races_up = dashboard.upcoming_races(conn)
            weekly = dashboard.weekly_totals(conn)
            profile_row = profile_svc.get_profile(conn)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": "Dashboard",
            "db_exists": db_exists,
            "db_path": DB_PATH,
            "activities": activities,
            "upcoming_races": races_up,
            "weekly": weekly,
            "profile": profile_row,
        },
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile_get(request: Request, error: str | None = None, saved: str | None = None):
    with connect_rw() as conn:
        prof = profile_svc.get_profile(conn)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "title": "Athlete profile",
            "profile": prof,
            "error": error,
            "saved": saved == "1",
        },
    )


@app.post("/profile")
async def profile_post(
    max_hr: str = Form(""),
    ftp_watts: str = Form(""),
):
    max_v, err1 = parse_optional_float(max_hr, "Max HR", 100, 220)
    if err1:
        return RedirectResponse(f"/profile?error={quote(err1)}", status_code=303)
    ftp_v, err2 = parse_optional_float(ftp_watts, "FTP", 50, 600)
    if err2:
        return RedirectResponse(f"/profile?error={quote(err2)}", status_code=303)
    with connect_rw() as conn:
        profile_svc.save_profile(conn, max_v, ftp_v)
    log = logging.getLogger("webapp")
    log.info("Profile updated max_hr=%s ftp=%s", max_v, ftp_v)
    return RedirectResponse("/profile?saved=1", status_code=303)


@app.get("/races", response_class=HTMLResponse)
async def races_list(request: Request):
    with connect_rw() as conn:
        races = races_svc.list_all_races(conn)
    return templates.TemplateResponse(
        request,
        "races.html",
        {"title": "Races & goals", "races": races},
    )


@app.get("/races/new", response_class=HTMLResponse)
async def races_new_get(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "race_form.html",
        {
            "title": "New race",
            "race": None,
            "form_action": "/races/new",
            "disciplines": DISCIPLINES,
            "goal_types": GOAL_TYPES,
            "statuses": RACE_STATUSES,
            "error": error,
        },
    )


@app.post("/races/new")
async def races_new_post(
    name: str = Form(...),
    race_date: str = Form(...),
    discipline: str = Form(...),
    goal_type: str = Form(...),
    goal_value: str = Form(""),
    notes: str = Form(""),
    status: str = Form("planned"),
):
    if discipline not in DISCIPLINES:
        return RedirectResponse("/races/new?error=Invalid+discipline", status_code=303)
    if goal_type not in GOAL_TYPES:
        return RedirectResponse("/races/new?error=Invalid+goal+type", status_code=303)
    if status not in RACE_STATUSES:
        status = "planned"
    with connect_rw() as conn:
        rid = races_svc.create_race(
            conn,
            name.strip(),
            race_date,
            discipline,
            goal_type,
            goal_value.strip() or None,
            notes.strip() or None,
            status,
        )
    logging.getLogger("webapp").info("Created race id=%s name=%s", rid, name)
    return RedirectResponse("/races", status_code=303)


@app.get("/races/{race_id}/edit", response_class=HTMLResponse)
async def races_edit_get(
    request: Request,
    race_id: int,
    error: str | None = None,
):
    with connect_rw() as conn:
        race = races_svc.get_race(conn, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    return templates.TemplateResponse(
        request,
        "race_form.html",
        {
            "title": "Edit race",
            "race": race,
            "form_action": f"/races/{race_id}/edit",
            "disciplines": DISCIPLINES,
            "goal_types": GOAL_TYPES,
            "statuses": RACE_STATUSES,
            "error": error,
        },
    )


@app.post("/races/{race_id}/edit")
async def races_edit_post(
    race_id: int,
    name: str = Form(...),
    race_date: str = Form(...),
    discipline: str = Form(...),
    goal_type: str = Form(...),
    goal_value: str = Form(""),
    notes: str = Form(""),
    status: str = Form("planned"),
):
    if discipline not in DISCIPLINES:
        return RedirectResponse(f"/races/{race_id}/edit?error=Invalid+discipline", status_code=303)
    if goal_type not in GOAL_TYPES:
        return RedirectResponse(f"/races/{race_id}/edit?error=Invalid+goal+type", status_code=303)
    if status not in RACE_STATUSES:
        status = "planned"
    with connect_rw() as conn:
        if not races_svc.get_race(conn, race_id):
            raise HTTPException(status_code=404)
        races_svc.update_race(
            conn,
            race_id,
            name.strip(),
            race_date,
            discipline,
            goal_type,
            goal_value.strip() or None,
            notes.strip() or None,
            status,
        )
    return RedirectResponse("/races", status_code=303)


@app.post("/races/{race_id}/delete")
async def races_delete(race_id: int):
    with connect_rw() as conn:
        if not races_svc.get_race(conn, race_id):
            raise HTTPException(status_code=404)
        races_svc.delete_race(conn, race_id)
    return RedirectResponse("/races", status_code=303)


@app.get("/coach", response_class=HTMLResponse)
async def coach_get(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "coach.html",
        {
            "title": "AI training plan",
            "plan": None,
            "error": error,
            "plan_days": PLAN_DAYS,
        },
    )


@app.post("/coach/generate", response_class=HTMLResponse)
async def coach_generate(request: Request):
    text, err = generate_coaching_plan_text()
    if err:
        return RedirectResponse(f"/coach?error={quote(err)}", status_code=303)
    return templates.TemplateResponse(
        request,
        "coach.html",
        {
            "title": "AI training plan",
            "plan": text,
            "error": None,
            "plan_days": PLAN_DAYS,
        },
    )
