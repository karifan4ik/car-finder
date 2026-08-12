"""Все настройки поиска читаются из .env и отсюда."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


AUTO_DEV_API_KEY = os.getenv("AUTO_DEV_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Тестовый режим: присылать всего несколько машин, чтобы проверить,
# что агент вообще работает и присылает то, что нужно.
TEST_MODE = _env_bool("TEST_MODE", True)
MAX_TEST_CARS = _env_int("MAX_TEST_CARS", 3)

# Сколько машин максимум присылать за один обычный (не тестовый) прогон.
MAX_CARS_PER_RUN = _env_int("MAX_CARS_PER_RUN", 15)

# Защита от перерасхода лимита API (1000 запросов/мес на тарифе Starter).
MAX_API_PAGES = _env_int("MAX_API_PAGES", 10)

# --- Параметры поиска (заданы в брифе) ---
SEARCH_ZIP = os.getenv("SEARCH_ZIP", "33069")
SEARCH_DISTANCE = _env_int("SEARCH_DISTANCE", 50)
SEARCH_MAKES = ["BMW", "Mercedes-Benz", "Infiniti", "Lexus", "Land Rover"]
SEARCH_YEAR_MIN = _env_int("SEARCH_YEAR_MIN", 2019)
SEARCH_MILEAGE_MAX = _env_int("SEARCH_MILEAGE_MAX", 85000)
SEARCH_PRICE_MAX = _env_int("SEARCH_PRICE_MAX", 50000)

# --- Признаки "интересных" комплектаций по маркам ---
# Ключевые слова ищем в trim, options и описании (без учёта регистра).
INTERESTING_TRIM_KEYWORDS = {
    "BMW": ["m sport", "m package", "m340i", "m550i", "x3 m40i", " m40i", " m3", " m4", " m5", " m8", "competition"],
    "Mercedes-Benz": ["amg", "amg line"],
    "Lexus": ["f sport"],
    "Infiniti": ["red sport 400", "red sport"],
    "Land Rover": ["r-dynamic", "r dynamic", "hse", "autobiography"],
}

# Слова, которые намекают на прокатную/перекупную машину.
RENTAL_DEALER_KEYWORDS = [
    "auto group export", "wholesale", "auction", "export llc", "auto exporters",
    "rental", "fleet",
]
RENTAL_DESCRIPTION_KEYWORDS = ["rental", "fleet vehicle", "corporate lease", "former rental"]

# Порог для пометки "подозрительно дёшево" (возможна авария/salvage).
PRICE_ANOMALY_MIN_DOLLARS = _env_int("PRICE_ANOMALY_MIN_DOLLARS", 3000)
PRICE_ANOMALY_MIN_PERCENT = _env_int("PRICE_ANOMALY_MIN_PERCENT", 12)

# Для heuristики "похожие машины": год ±1, пробег в пределах этого коридора.
SIMILAR_YEAR_RANGE = 1
SIMILAR_MILEAGE_DELTA = 25000

# Пробег/год выше этого значения — повод заподозрить бывшую прокатную машину.
RENTAL_MILEAGE_PER_YEAR = 18000
