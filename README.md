# caltrack 🥩

Single-user calorie + protein tracker: **Telegram bot** for logging, **dark web
dashboard** for viewing, **progress-photo timeline**. One app, one SQLite DB,
one folder. Macro numbers come from the Anthropic API and are **estimates** —
good for trend and awareness, not lab precision.

## Layout

```
config.py        goals + paths (edit your targets here)
db.py            SQLite schema + queries (plain SQL)
estimator.py     Anthropic API food estimation (text/photo → strict JSON)
bot.py           Telegram bot (logging)
dashboard.py     FastAPI backend (JSON API + static page)
static/index.html  the dashboard (Chart.js, dark telemetry theme)
import_seed.py   idempotent seed import from seed/*.csv
data/            created at runtime: caltrack.db, photos/, progress/  (gitignored)
```

## Setup (VPS)

```bash
git clone <this repo> caltrack && cd caltrack
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # fill in bot token + Anthropic key
set -a; source .env; set +a

python import_seed.py       # loads seed/*.csv — safe to re-run
```

Goals (kcal target, maintenance, protein floor, goal weight, timezone) live in
`config.py` — edit and restart.

## Run

**Bot** (long-polling, no ports needed):

```bash
python bot.py
```

**Dashboard** (bind to localhost and put nginx/caddy or an SSH tunnel in front —
there is deliberately no auth):

```bash
uvicorn dashboard:app --host 127.0.0.1 --port 8077
```

Then open http://127.0.0.1:8077 (or `ssh -L 8077:127.0.0.1:8077 vps` from your laptop).

To keep both alive, either run them in `tmux` or add two tiny systemd units /
`@reboot` cron entries — both are plain foreground processes.

## Bot usage

| Input | Effect |
|---|---|
| `beef stir-fry 263g cooked` (any food text) | estimates kcal/protein, logs items, replies with day total |
| food **photo** (optional caption) | same, via vision |
| photo captioned `me` / `progress` / `body` | saves as today's progress photo (overwrites) |
| `/me` then a photo | same as above |
| `/weight 85.3` | sets today's weight |
| `/waist 84.5` | sets today's waist |
| `/workout upper body (PT), 300` | sets workout label + kcal burned |
| `/today` | today's summary + item list |
| `/del` | list today's items numbered; `/del 3` deletes item 3 |
| `/undo` | delete the last logged item |
| `/start` | shows your chat id (pin it via `TELEGRAM_CHAT_ID` in `.env`) |

Deficit = `(maintenance + workout kcal) − eaten`. A day is *on target* when
eaten ≤ goal **and** protein ≥ floor. Photos are downscaled to ~1080 px and
stay local in `data/` — nothing leaves the box except the API calls for
estimation.

## Env vars

See `.env.example`: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`,
`ANTHROPIC_MODEL` (Sonnet-tier), `TELEGRAM_CHAT_ID`.
