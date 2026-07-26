"""Idempotent seed import — reads seed/*.csv and upserts. Safe to re-run."""
import csv

import config
import db


def _f(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def _i(v: str) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if v else None


def import_days(path) -> int:
    n = 0
    with open(path, newline="", encoding="utf-8") as fh, db.connect() as con:
        for row in csv.DictReader(fh):
            con.execute(
                """INSERT INTO days(date, weight_kg, waist_cm, progress_photo_path,
                                    workout_label, workout_kcal_burned, note)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(date) DO UPDATE SET
                     weight_kg=excluded.weight_kg, waist_cm=excluded.waist_cm,
                     progress_photo_path=excluded.progress_photo_path,
                     workout_label=excluded.workout_label,
                     workout_kcal_burned=excluded.workout_kcal_burned,
                     note=excluded.note""",
                (row["date"], _f(row["weight_kg"]), _f(row["waist_cm"]),
                 row["progress_photo_path"].strip() or None,
                 row["workout_label"].strip() or None,
                 _i(row["workout_kcal_burned"]), row.get("note", "").strip() or None),
            )
            n += 1
    return n


def import_food(path) -> int:
    """Upsert keyed on (date, meal, name, logged_at) — no duplicates on re-run."""
    n = 0
    with open(path, newline="", encoding="utf-8") as fh, db.connect() as con:
        for row in csv.DictReader(fh):
            db.ensure_day(con, row["date"])
            exists = con.execute(
                "SELECT id FROM food_items WHERE date=? AND meal=? AND name=? AND logged_at=?",
                (row["date"], row["meal"], row["name"], row["logged_at"]),
            ).fetchone()
            if exists:
                continue
            con.execute(
                """INSERT INTO food_items(date, meal, name, grams, raw_or_cooked,
                                          kcal, protein_g, logged_at, note)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (row["date"], row["meal"], row["name"], _f(row["grams"]),
                 row["raw_or_cooked"].strip() or None, _i(row["kcal"]),
                 _f(row["protein_g"]), row["logged_at"],
                 row.get("note", "").strip() or None),
            )
            n += 1
    return n


def main():
    db.init_db()
    d = import_days(config.SEED_DIR / "caltrack-seed-days.csv")
    f = import_food(config.SEED_DIR / "caltrack-seed-day0.csv")
    print(f"seed import done: {d} day rows upserted, {f} new food items")


if __name__ == "__main__":
    main()
