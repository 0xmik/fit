"""Health Cockpit config — edit goals here. Secrets come from .env / environment."""
import os
from pathlib import Path

# --- goals (editable) --------------------------------------------------------
GOAL_KCAL = 1900          # daily calorie target
MAINTENANCE_KCAL = 2400   # Mifflin-St Jeor @38y/174cm/87.2kg (BMR ~1775) + office job,
                          # 6k steps, 1x padel → ~2440-2490; slightly conservative.
                          # Recalibrate after 3-4 weeks of real trend data.
DEFICIT_TARGET = 500      # kcal/day under maintenance ≈ 0.5 kg/week
PROTEIN_GOAL_G = 170      # protein floor, ~2 g/kg while cutting to preserve muscle
BODYWEIGHT_KG = 87.2      # baseline 2026-07-26, editable
GOAL_WEIGHT_KG = 80.0     # checkpoint, not final — reassess visually around here
TIMEZONE = "Europe/Zurich"

# --- reminders (bot pings you only when something is missing; "" disables) ----
REMINDER_MORNING = "08:30"  # progress photo / stale weight / stale waist
REMINDER_EVENING = "21:00"  # nothing logged yet, or protein far below floor
PROTEIN_REMINDER_GAP_G = 25 # evening ping if more than this many grams short

# --- paths -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "caltrack.db"
PHOTO_DIR = DATA_DIR / "photos"           # food photos
PROGRESS_DIR = DATA_DIR / "progress"      # daily progress photos
SEED_DIR = BASE_DIR / "seed"

# --- secrets / runtime (from environment, see .env.example) -------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
# single-user lock: set after first /start, or here directly
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))  # 0 = accept first /start

PHOTO_MAX_EDGE = 1080  # downscale saved photos to this long edge


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PHOTO_DIR.mkdir(exist_ok=True)
    PROGRESS_DIR.mkdir(exist_ok=True)
