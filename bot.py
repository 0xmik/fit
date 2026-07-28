"""Health Cockpit Telegram bot — log food (text/photo), weight, waist, workout, progress photos."""
from __future__ import annotations  # Python 3.9 compat for `X | None` hints

import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from telegram import Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import config
import db
import estimator

log = logging.getLogger("caltrack.bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# httpx logs every Telegram API request URL — which contains the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)

PROGRESS_CAPTIONS = {"me", "progress", "body"}


def allowed(update: Update) -> bool:
    """Single-user lock. If TELEGRAM_CHAT_ID is unset (0), accept anyone
    but log the chat id so it can be pinned in .env."""
    cid = update.effective_chat.id
    if config.TELEGRAM_CHAT_ID and cid != config.TELEGRAM_CHAT_ID:
        log.warning("ignoring message from foreign chat %s", cid)
        return False
    return True


def msg_time(update: Update) -> datetime:
    """When the message was SENT, in local time — Telegram queues messages
    while the bot is offline, so processing time can be hours later."""
    return update.message.date.astimezone(ZoneInfo(config.TIMEZONE))


def fmt_int(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")  # thin-space thousands


def day_summary_line(day: str) -> str:
    t = db.day_totals(day)
    check = "✓" if t["deficit"] >= config.DEFICIT_TARGET else ""
    return (f"today: {fmt_int(t['kcal_eaten'])} / {fmt_int(t['goal_kcal'])} kcal · "
            f"{t['protein_g']:g}g P · deficit {fmt_int(t['deficit'])} {check}").strip()


def save_downscaled(image_bytes: bytes, dest_dir, stem: str) -> str:
    """Downscale to ~PHOTO_MAX_EDGE long edge, save as JPEG, return path relative to DATA_DIR."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")
    img.thumbnail((config.PHOTO_MAX_EDGE, config.PHOTO_MAX_EDGE))
    path = dest_dir / f"{stem}.jpg"
    img.save(path, "JPEG", quality=85)
    return str(path.relative_to(config.DATA_DIR))


# --- commands -----------------------------------------------------------------

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    log.info("chat id: %s", cid)
    await update.message.reply_text(
        f"Health Cockpit ready. Your chat id is {cid} — set TELEGRAM_CHAT_ID in .env to lock the bot to you.\n"
        "Log food as text or photo. Commands: /weight /waist /workout /me /today /del /undo\n"
        "Macro numbers are estimates — good for trends, not lab precision.")


async def cmd_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    try:
        kg = float(ctx.args[0].replace(",", "."))
    except (IndexError, ValueError):
        await update.message.reply_text("usage: /weight 85.3")
        return
    day = msg_time(update).date().isoformat()
    db.set_day_field(day, "weight_kg", kg)
    await update.message.reply_text(f"✅ weight {kg:g} kg saved for {day}")


async def cmd_waist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    try:
        cm = float(ctx.args[0].replace(",", "."))
    except (IndexError, ValueError):
        await update.message.reply_text("usage: /waist 84.5")
        return
    day = msg_time(update).date().isoformat()
    db.set_day_field(day, "waist_cm", cm)
    await update.message.reply_text(f"✅ waist {cm:g} cm saved for {day}")


async def cmd_workout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    raw = " ".join(ctx.args)
    if not raw:
        await update.message.reply_text("usage: /workout upper body (PT), 300")
        return
    label, kcal = raw, None
    if "," in raw:
        head, _, tail = raw.rpartition(",")
        try:
            kcal = int(tail.strip())
            label = head.strip()
        except ValueError:
            pass
    day = msg_time(update).date().isoformat()
    db.set_workout(day, label, kcal)
    kcal_txt = f" · {kcal} kcal burned" if kcal else ""
    await update.message.reply_text(f"✅ workout: {label}{kcal_txt}\n{day_summary_line(day)}")


async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    ctx.user_data["awaiting_progress_photo"] = True
    await update.message.reply_text("send the progress photo 📸 (next photo will be saved as today's)")


async def cmd_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/del → numbered list of today's items; /del 3 → delete item 3."""
    if not allowed(update):
        return
    day = msg_time(update).date().isoformat()
    with db.connect() as con:
        items = db.day_items(con, day)
    if not items:
        await update.message.reply_text("nothing logged today")
        return
    if not ctx.args:
        lines = [f"{i + 1}. {it['name']} — {it['kcal']} kcal · {it['protein_g']:g}g P"
                 for i, it in enumerate(items)]
        lines.append("\ndelete with /del <number>")
        await update.message.reply_text("\n".join(lines))
        return
    try:
        idx = int(ctx.args[0]) - 1
        item = items[idx]
        if idx < 0:
            raise IndexError
    except (ValueError, IndexError):
        await update.message.reply_text(f"usage: /del 1..{len(items)} (see /del for the list)")
        return
    with db.connect() as con:
        con.execute("DELETE FROM food_items WHERE id = ?", (item["id"],))
    await update.message.reply_text(
        f"🗑 removed: {item['name']} ({item['kcal']} kcal · {item['protein_g']:g}g P)\n"
        f"{day_summary_line(day)}")


async def cmd_undo(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """Delete the most recently logged item of today."""
    if not allowed(update):
        return
    day = msg_time(update).date().isoformat()
    with db.connect() as con:
        items = db.day_items(con, day)
    if not items:
        await update.message.reply_text("nothing logged today")
        return
    item = items[-1]
    with db.connect() as con:
        con.execute("DELETE FROM food_items WHERE id = ?", (item["id"],))
    await update.message.reply_text(
        f"🗑 removed last item: {item['name']} ({item['kcal']} kcal · {item['protein_g']:g}g P)\n"
        f"{day_summary_line(day)}")


async def cmd_today(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    day = db.today_str()
    t = db.day_totals(day)
    with db.connect() as con:
        items = db.day_items(con, day)
    lines = [f"📊 {day}"]
    if t["workout_label"]:
        lines.append(f"🏋️ {t['workout_label']} ({t['workout_kcal_burned'] or 0} kcal)")
    if t["weight_kg"]:
        lines.append(f"⚖️ {t['weight_kg']:g} kg")
    lines.append(f"🔥 {fmt_int(t['kcal_eaten'])} / {fmt_int(t['goal_kcal'])} kcal")
    p_check = "✓" if t["protein_g"] >= t["protein_goal_g"] else ""
    lines.append(f"💪 {t['protein_g']:g} / {t['protein_goal_g']}g protein {p_check}")
    d_check = "✓" if t["deficit"] >= config.DEFICIT_TARGET else ""
    lines.append(f"📉 deficit {fmt_int(t['deficit'])} kcal {d_check}")
    if items:
        lines.append("")
        for it in items:
            g = f" {it['grams']:g}g" if it["grams"] else ""
            lines.append(f"· {it['name']}{g} — {it['kcal']} kcal · {it['protein_g']:g}g P")
    await update.message.reply_text("\n".join(lines))


# --- food + photos --------------------------------------------------------------

async def store_items(items: list[dict], photo_path: str | None, when: datetime) -> str:
    day = when.date().isoformat()
    lines = []
    for it in items:
        db.add_food_item(day, it["meal"], it["name"], it["grams"],
                         it["raw_or_cooked"], it["kcal"], it["protein_g"],
                         logged_at=when.isoformat(timespec="seconds"),
                         photo_path=photo_path)
        g = f" {it['grams']:g}g" if it["grams"] else ""
        lines.append(f"✅ {it['name']}{g} → {it['kcal']} kcal · {it['protein_g']:g}g P")
    return "\n".join(lines) + f"\n{day_summary_line(day)}"


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = update.message.text.strip()
    when = msg_time(update)
    await update.message.chat.send_action("typing")
    try:
        items = estimator.estimate(text, None, when.strftime("%H:%M"))
    except ValueError:
        await update.message.reply_text("🤔 couldn't parse that — try rephrasing (e.g. `beef stir-fry 263g cooked`)")
        return
    if not items:
        await update.message.reply_text("that didn't look like food — nothing logged")
        return
    await update.message.reply_text(await store_items(items, None, when))


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    caption = (update.message.caption or "").strip()
    is_progress = (caption.lower() in PROGRESS_CAPTIONS
                   or ctx.user_data.pop("awaiting_progress_photo", False))
    file = await update.message.photo[-1].get_file()
    image_bytes = bytes(await file.download_as_bytearray())
    when = msg_time(update)
    day = when.date().isoformat()

    if is_progress:
        rel = save_downscaled(image_bytes, config.PROGRESS_DIR, day)
        db.set_day_field(day, "progress_photo_path", rel)  # overwrite if exists
        await update.message.reply_text(f"📸 progress photo saved for {day}")
        return

    # food photo
    await update.message.chat.send_action("typing")
    stem = when.strftime("%Y-%m-%d_%H%M%S")
    rel = save_downscaled(image_bytes, config.PHOTO_DIR, stem)
    try:
        items = estimator.estimate(caption or None, image_bytes, when.strftime("%H:%M"))
    except ValueError:
        await update.message.reply_text("🤔 couldn't read that photo — add a caption describing the food and resend")
        return
    if not items:
        await update.message.reply_text("no food detected in the photo — nothing logged")
        return
    await update.message.reply_text(await store_items(items, rel, when))


# --- reminders ------------------------------------------------------------------

def _days_since_last(field: str) -> int | None:
    """Days since `field` was last recorded; None if never."""
    with db.connect() as con:
        row = con.execute(
            f"SELECT date FROM days WHERE {field} IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    from datetime import date as _date
    return (_date.fromisoformat(db.today_str()) - _date.fromisoformat(row["date"])).days


async def job_morning(context):
    if not config.TELEGRAM_CHAT_ID:
        return
    gaps = []
    for field, cmd, label in (("progress_photo_path", "photo captioned `me`", "📸 progress photo"),
                              ("weight_kg", "/weight", "⚖️ weigh-in"),
                              ("waist_cm", "/waist", "📏 waist")):
        since = _days_since_last(field)
        if since is None or since >= 7:
            gaps.append(f"{label} — last {'never' if since is None else f'{since}d ago'} ({cmd})")
    if gaps:
        await context.bot.send_message(
            config.TELEGRAM_CHAT_ID, "🌅 morning check — still open:\n" + "\n".join(gaps))


async def job_evening(context):
    if not config.TELEGRAM_CHAT_ID:
        return
    t = db.day_totals(db.today_str())
    if t["items"] == 0:
        await context.bot.send_message(
            config.TELEGRAM_CHAT_ID,
            "🌙 nothing logged today — forgot to track? Send it now, I'll book it to today.")
        return
    protein_gap = t["protein_goal_g"] - t["protein_g"]
    if protein_gap > config.PROTEIN_REMINDER_GAP_G:
        kcal_left = t["goal_kcal"] - t["kcal_eaten"]
        await context.bot.send_message(
            config.TELEGRAM_CHAT_ID,
            f"🌙 protein check: {t['protein_g']:g}g of {t['protein_goal_g']}g — "
            f"{protein_gap:g}g short, {max(kcal_left, 0)} kcal left in budget.\n"
            "Quick fix: skyr/quark (~11g P per 100g) or a can of tuna (~25g P).")


async def job_weekly(context):
    """Sunday evening: how the week actually went."""
    if not config.TELEGRAM_CHAT_ID:
        return
    s = db.week_summary(7)
    if s["logged_days"] == 0:
        return
    lines = [f"📈 week in review — {s['logged_days']}/7 days logged", ""]
    lines.append(f"🔥 Ø {fmt_int(s['avg_kcal'])} kcal/day (goal {fmt_int(config.GOAL_KCAL)})")
    p_mark = "✓" if s["avg_protein"] >= config.PROTEIN_GOAL_G else ""
    lines.append(f"💪 Ø {s['avg_protein']}g protein (floor {config.PROTEIN_GOAL_G}) {p_mark}".strip())
    lines.append(f"📉 Ø deficit {fmt_int(s['avg_deficit'])} kcal/day")
    lines.append(f"🎯 {s['on_target_days']}/{s['logged_days']} days fully on target")
    lines.append(f"🏋️ {s['workouts']} workouts · {fmt_int(s['workout_kcal'])} kcal burned")
    if s["weight_first"] is not None and s["weight_last"] is not None:
        delta = round(s["weight_last"] - s["weight_first"], 2)
        arrow = "↓" if delta < 0 else ("↑" if delta > 0 else "→")
        lines.append(f"⚖️ {s['weight_last']:g} kg ({arrow} {abs(delta):g} kg this week)")
    elif s["weight_last"] is not None:
        lines.append(f"⚖️ {s['weight_last']:g} kg")
    if s["waist_last"] is not None:
        lines.append(f"📏 waist {s['waist_last']:g} cm")
    # ~7700 kcal per kg of fat — a rough but useful weekly expectation
    lines += ["", f"expected from deficit alone: ~{s['avg_deficit'] * 7 / 7700:.1f} kg/week."
                  " Scale moves slower or faster short-term — the trend is what counts."]
    await context.bot.send_message(config.TELEGRAM_CHAT_ID, "\n".join(lines))


def _parse_hhmm(s: str):
    from datetime import time as _time
    h, m = s.split(":")
    return _time(int(h), int(m), tzinfo=ZoneInfo(config.TIMEZONE))


def schedule_reminders(app) -> None:
    if app.job_queue is None:
        log.warning("reminders disabled — install: pip install 'python-telegram-bot[job-queue]'")
        return
    if config.REMINDER_MORNING:
        app.job_queue.run_daily(job_morning, _parse_hhmm(config.REMINDER_MORNING))
    if config.REMINDER_EVENING:
        app.job_queue.run_daily(job_evening, _parse_hhmm(config.REMINDER_EVENING))
    if config.WEEKLY_REPORT:
        app.job_queue.run_daily(job_weekly, _parse_hhmm(config.WEEKLY_REPORT), days=(0,))  # 0 = Sunday
    log.info("reminders scheduled: morning %s, evening %s, weekly report sun %s (%s)",
             config.REMINDER_MORNING or "off", config.REMINDER_EVENING or "off",
             config.WEEKLY_REPORT or "off", config.TIMEZONE)


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
    db.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("weight", cmd_weight))
    app.add_handler(CommandHandler("waist", cmd_waist))
    app.add_handler(CommandHandler("workout", cmd_workout))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    schedule_reminders(app)
    log.info("health cockpit bot polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
