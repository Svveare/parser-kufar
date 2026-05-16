import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN", "").strip()

# Путь к SQLite. Пусто = файл bot.db в папке проекта (рядом с db.py), не зависит от cwd.
# На Docker/PaaS без постоянного диска задайте путь на volume, например /data/bot.db
DB_PATH = os.getenv("DB_PATH", "").strip()

# Ожидание блокировки SQLite, сек. (параметр timeout в sqlite3.connect).
# Жёсткость записи на диск: SQLITE_SYNCHRONOUS = NORMAL | FULL | EXTRA (см. документацию SQLite).
SQLITE_BUSY_TIMEOUT = float(os.getenv("SQLITE_BUSY_TIMEOUT", "30"))
_sqlite_sync = os.getenv("SQLITE_SYNCHRONOUS", "NORMAL").strip().upper()
SQLITE_SYNCHRONOUS = _sqlite_sync if _sqlite_sync in ("OFF", "NORMAL", "FULL", "EXTRA") else "NORMAL"

# Повтор запроса к Kufar при сетевых ошибках / 5xx
KUFAR_FETCH_RETRIES = max(1, int(os.getenv("KUFAR_FETCH_RETRIES", "3")))
KUFAR_FETCH_RETRY_DELAY = float(os.getenv("KUFAR_FETCH_RETRY_DELAY", "2"))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
REGULAR_CHECK_INTERVAL = int(os.getenv("REGULAR_CHECK_INTERVAL", "600"))
VIP_CHECK_INTERVAL = int(os.getenv("VIP_CHECK_INTERVAL", "60"))

FIRST_RUN_LIMIT = int(os.getenv("FIRST_RUN_LIMIT", "3"))
VIP_SUBSCRIPTION_DAYS = int(os.getenv("VIP_SUBSCRIPTION_DAYS", "30"))
VIP_PRICE_USD = int(os.getenv("VIP_PRICE_USD", "2"))
MARKET_DISCOUNT_THRESHOLD = float(os.getenv("MARKET_DISCOUNT_THRESHOLD", "0.85"))
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DEFAULT_MAX_PRICE = int(os.getenv("DEFAULT_MAX_PRICE", "500"))

MAX_PRICE_PRESETS: tuple[int, ...] = tuple(
    int(x.strip())
    for x in os.getenv("MAX_PRICE_PRESETS", "300,500,800,1000,1500,2000,3000,5000").split(",")
    if x.strip().isdigit()
) or (300, 500, 800, 1000, 1500, 2000, 3000, 5000)

DEFAULT_KEYWORDS = [
    "iphone x",
    "iphone xs",
    "iphone xs max",
    "iphone xr",
    "iphone 11",
]
DEVICE_CATALOG = [
    "iphone se",
    "iphone x",
    "iphone xs",
    "iphone xs max",
    "iphone xr",
    "iphone 11",
    "iphone 11 pro",
    "iphone 11 pro max",
    "iphone 12",
    "iphone 12 mini",
    "iphone 12 pro",
    "iphone 12 pro max",
    "iphone 13",
    "iphone 13 mini",
    "iphone 13 pro",
    "iphone 13 pro max",
    "iphone 14",
    "iphone 14 plus",
    "iphone 14 pro",
    "iphone 14 pro max",
    "iphone 15",
    "iphone 15 plus",
    "iphone 15 pro",
    "iphone 15 pro max",
    "iphone 16",
    "iphone 16 plus",
    "iphone 16 pro",
    "iphone 16 pro max",
    "iphone 17",
    "iphone 17 pro",
    "iphone 17 pro max"
]

# Стоп-слова по смыслу объявления: проверяются только в названии (subject),
# чтобы «чехол в подарок» в описании не отсекало продажу телефона.
DEFAULT_EXCLUDE_TERMS: tuple[str, ...] = (
    "адаптер",
    "акб",
    "аккумулятор",
    "бампер",
    "блок питания",
    "для ремонта",
    "дисплей",
    "донор",
    "донорский",
    "дубликат",
    "замена акб",
    "замена аккумулятора",
    "замена батареи",
    "зарядка",
    "заднее стекло",
    "защитное стекло",
    "кабель",
    "камера",
    "камеры",
    "кейс",
    "копия",
    "корпус",
    "макет",
    "матрица",
    "MagSafe",
    "муляж",
    "на запчасти",
    "плата",
    "плёнка",
    "пленка",
    "подделка",
    "ремонт",
    "реплика",
    "стекло",
    "чехол",
    "чехлы",
    "шлейф",
    "шлейфы",
    "экран",
)

# В названии или кратких параметрах (summary) должно быть явно про телефон.
PHONE_REQUIRED_TERMS: tuple[str, ...] = (
    "iphone",
    "айфон",
    "телефон",
    "смартфон",
    "mobile phone",
)

# Услуги / скупка: смотрим название + summary (без длинного описания).
NOT_SALE_TERMS: tuple[str, ...] = (
    "выкуп",
    "скупка",
    "скупаем",
    "куплю",
    "купим",
    "покупаем",
    "срочный выкуп",
)

KUFAR_QUERY = os.getenv("KUFAR_QUERY", "iphone")
KUFAR_REGION = int(os.getenv("KUFAR_REGION", "7"))
KUFAR_SIZE = int(os.getenv("KUFAR_SIZE", "30"))
