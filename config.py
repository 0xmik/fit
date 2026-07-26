"""caltrack config — edit goals here. Secrets come from .env / environment."""
import os
from pathlib import Path

# --- goals (editable) --------------------------------------------------------
GOAL_KCAL = 1900          # daily calorie target
MAINTENANCE_KCAL = 2400   # maintenance; deficit is measured against this
DEFICIT_TARGET = 500      # kcal/day under maintenance I aim for
PROTEIN_GOAL_G = 152      # protein floor (2 g/kg at 87.2 kg would be ~174 g)
BODYWEIGHT_KG = 87.2      # baseline 2026-07-26, editable
GOAL_WEIGHT_KG = 80.0     # where the dashed projection line points
TIMEZONE = "Europe/Zurich"

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
