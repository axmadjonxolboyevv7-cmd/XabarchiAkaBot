import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "30"))
DEFAULT_PRICE = int(os.getenv("DEFAULT_PRICE", "15000"))
TEZCHECK_BASE = os.getenv("TEZCHECK_BASE", "https://tezcheck.uz/api")
DATA_DIR = os.getenv("DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "bot.db")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)
