"""SQLite schema + queries. Plain SQL, no ORM."""
from __future__ import annotations  # Python 3.9 compat for `X | None` hints

import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    date TEXT PRIMARY KEY,              -- YYYY-MM-DD
    weight_kg REAL,
    waist_cm REAL,
    progress_photo_path TEXT,
    workout_label TEXT,
    workout_kcal_burned INTEGER,
    note TEXT
);
CREATE TABLE IF NOT EXISTS food_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL REFERENCES days(date),
    meal TEXT NOT NULL DEFAULT 'none',  -- breakfast/lunch/dinner/snack/none
    name TEXT NOT NULL,
    grams REAL,
    raw_or_cooked TEXT,
    kcal INTEGER NOT NULL,
    protein_g REAL NOT NULL,
    logged_at TEXT NOT NULL,
    photo_path TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_food_date ON food_items(date);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def today_str() -> str:
    return now_local().date().isoformat()


def ensure_day(con: sqlite3.Connection, day: str) -> None:
    con.execute("INSERT OR IGNORE INTO days(date) VALUES (?)", (day,))


def set_day_field(day: str, field: str, value) -> None:
    assert field in {"weight_kg", "waist_cm", "progress_photo_path",
                     "workout_label", "workout_kcal_burned", "note"}
    with connect() as con:
        ensure_day(con, day)
        con.execute(f"UPDATE days SET {field} = ? WHERE date = ?", (value, day))


def set_workout(day: str, label: str, kcal: int | None) -> None:
    with connect() as con:
        ensure_day(con, day)
        con.execute(
            "UPDATE days SET workout_label = ?, workout_kcal_burned = ? WHERE date = ?",
            (label, kcal, day),
        )


def add_food_item(day: str, meal: str, name: str, grams: float | None,
                  raw_or_cooked: str | None, kcal: int, protein_g: float,
                  logged_at: str | None = None, photo_path: str | None = None,
                  note: str | None = None) -> int:
    with connect() as con:
        ensure_day(con, day)
        cur = con.execute(
            """INSERT INTO food_items(date, meal, name, grams, raw_or_cooked,
                                      kcal, protein_g, logged_at, photo_path, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (day, meal or "none", name, grams, raw_or_cooked, int(round(kcal)),
             float(protein_g), logged_at or now_local().isoformat(timespec="seconds"),
             photo_path, note),
        )
        return cur.lastrowid


def day_row(con: sqlite3.Connection, day: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()


def day_items(con: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM food_items WHERE date = ? ORDER BY logged_at, id", (day,)
    ).fetchall()


def day_totals(day: str) -> dict:
    """Computed on the fly — never stored."""
    with connect() as con:
        row = con.execute(
            "SELECT COALESCE(SUM(kcal),0) AS kcal, COALESCE(SUM(protein_g),0) AS protein_g, "
            "COUNT(*) AS items FROM food_items WHERE date = ?", (day,)
        ).fetchone()
        d = day_row(con, day)
    workout_kcal = (d["workout_kcal_burned"] or 0) if d else 0
    eaten = row["kcal"]
    protein = round(row["protein_g"], 1)
    deficit = (config.MAINTENANCE_KCAL + workout_kcal) - eaten
    return {
        "date": day,
        "kcal_eaten": eaten,
        "protein_g": protein,
        "items": row["items"],
        "workout_kcal_burned": workout_kcal,
        "deficit": deficit,
        "goal_kcal": config.GOAL_KCAL,
        "maintenance_kcal": config.MAINTENANCE_KCAL,
        "protein_goal_g": config.PROTEIN_GOAL_G,
        "on_target": eaten <= config.GOAL_KCAL and protein >= config.PROTEIN_GOAL_G,
        "weight_kg": d["weight_kg"] if d else None,
        "waist_cm": d["waist_cm"] if d else None,
        "workout_label": d["workout_label"] if d else None,
    }


def last_n_days(n: int = 7) -> list[dict]:
    end = date.fromisoformat(today_str())
    return [day_totals((end - timedelta(days=i)).isoformat()) for i in range(n - 1, -1, -1)]


def _trailing_avg(points: list[dict], key: str, window_days: int = 7) -> list[dict]:
    """Trailing N-day mean over the points that exist — the honest weight signal.
    Needs at least 3 measurements overall, otherwise it just echoes the raw line."""
    if len(points) < 3:
        return []
    out = []
    for p in points:
        end = date.fromisoformat(p["date"])
        start = end - timedelta(days=window_days - 1)
        vals = [q[key] for q in points if start <= date.fromisoformat(q["date"]) <= end]
        out.append({"date": p["date"], key: round(sum(vals) / len(vals), 2)})
    return out


def progress_series() -> dict:
    with connect() as con:
        rows = con.execute(
            "SELECT date, weight_kg, waist_cm, progress_photo_path FROM days "
            "WHERE weight_kg IS NOT NULL OR waist_cm IS NOT NULL "
            "OR progress_photo_path IS NOT NULL ORDER BY date"
        ).fetchall()
    weight = [{"date": r["date"], "kg": r["weight_kg"]} for r in rows if r["weight_kg"]]
    return {
        "weight": weight,
        "weight_avg": _trailing_avg(weight, "kg"),
        "waist": [{"date": r["date"], "cm": r["waist_cm"]} for r in rows if r["waist_cm"]],
        "photos": [{"date": r["date"], "path": r["progress_photo_path"]}
                   for r in rows if r["progress_photo_path"]],
    }


def workouts_last_n(n: int = 30) -> list[dict]:
    """One entry per day in the window; label is None on rest days."""
    end = date.fromisoformat(today_str())
    start = end - timedelta(days=n - 1)
    with connect() as con:
        rows = {r["date"]: r for r in con.execute(
            "SELECT date, workout_label, workout_kcal_burned FROM days "
            "WHERE date BETWEEN ? AND ? AND workout_label IS NOT NULL",
            (start.isoformat(), end.isoformat()))}
    out = []
    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        r = rows.get(d)
        out.append({"date": d,
                    "label": r["workout_label"] if r else None,
                    "kcal": (r["workout_kcal_burned"] or 0) if r else 0})
    return out


def week_summary(n: int = 7) -> dict:
    """Aggregates for the weekly report — averages ignore days with no food logged."""
    days = last_n_days(n)
    logged = [d for d in days if d["items"] > 0]
    workouts = [d for d in days if d["workout_label"]]
    weights = [d["weight_kg"] for d in days if d["weight_kg"]]
    waists = [d["waist_cm"] for d in days if d["waist_cm"]]
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0
    return {
        "days": n,
        "logged_days": len(logged),
        "avg_kcal": avg([d["kcal_eaten"] for d in logged]),
        "avg_protein": avg([d["protein_g"] for d in logged]),
        "avg_deficit": avg([d["deficit"] for d in logged]),
        "on_target_days": sum(1 for d in logged if d["on_target"]),
        "workouts": len(workouts),
        "workout_kcal": sum(d["workout_kcal_burned"] for d in workouts),
        "weight_first": weights[0] if weights else None,
        "weight_last": weights[-1] if weights else None,
        "waist_last": waists[-1] if waists else None,
    }
