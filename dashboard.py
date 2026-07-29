"""Health Cockpit dashboard — FastAPI backend serving JSON + the static dark HTML page."""
from datetime import date, datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import db

app = FastAPI(title="Health Cockpit", docs_url=None, redoc_url=None)

db.init_db()
config.ensure_dirs()

app.mount("/photos", StaticFiles(directory=config.DATA_DIR), name="photos")


@app.get("/")
def index():
    # no-cache so browsers always pick up UI updates without a hard reload
    return FileResponse(config.BASE_DIR / "static" / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def api_config():
    with db.connect() as con:
        first = con.execute("SELECT MIN(date) AS d FROM days").fetchone()["d"]
    return {
        "tracking_since": first,
        "goal_kcal": config.GOAL_KCAL,
        "maintenance_kcal": config.MAINTENANCE_KCAL,
        "deficit_target": config.DEFICIT_TARGET,
        "protein_goal_g": config.PROTEIN_GOAL_G,
        "protein_min_g": config.PROTEIN_MIN_G,
        "bodyweight_kg": config.BODYWEIGHT_KG,
        "goal_weight_kg": config.GOAL_WEIGHT_KG,
        "today": db.today_str(),
    }


@app.get("/api/week")
def api_week(days: int = 7):
    return db.last_n_days(max(1, min(days, 90)))


@app.get("/api/day/{day}")
def api_day(day: str):
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "bad date")
    totals = db.day_totals(day)
    with db.connect() as con:
        items = db.day_items(con, day)
    def hhmm(ts: str) -> str:
        try:
            return datetime.fromisoformat(ts).strftime("%H:%M")
        except ValueError:
            return ""
    totals["food"] = [{
        "meal": r["meal"], "name": r["name"], "grams": r["grams"],
        "raw_or_cooked": r["raw_or_cooked"], "kcal": r["kcal"],
        "protein_g": r["protein_g"], "time": hhmm(r["logged_at"]),
        "photo_path": r["photo_path"],
    } for r in items]
    return totals


@app.get("/api/workouts")
def api_workouts(days: int = 30):
    return db.workouts_last_n(max(7, min(days, 120)))


@app.get("/api/progress")
def api_progress():
    series = db.progress_series()
    out = {**series, "baseline": None, "latest": None, "delta_kg": None, "days_elapsed": None}
    if series["photos"]:
        first, last = series["photos"][0], series["photos"][-1]
        out["baseline"], out["latest"] = first, last
        out["days_elapsed"] = (date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days
    if series["weight"]:
        w0, w1 = series["weight"][0], series["weight"][-1]
        out["delta_kg"] = round(w1["kg"] - w0["kg"], 2)
    return out
