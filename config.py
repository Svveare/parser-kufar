import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from product_catalog import DEFAULT_KEYWORDS, DEVICE_CATALOG

load_dotenv()

# Часовой пояс для дат в сообщениях (Минск = UTC+3, как МСК).
_display_tz_name = os.getenv("DISPLAY_TIMEZONE", "Europe/Minsk").strip() or "Europe/Minsk"
try:
    DISPLAY_TZ = ZoneInfo(_display_tz_name)
except Exception:
    # Без пакета tzdata (часто Windows) — UTC; pip install tzdata для Europe/Minsk.
    DISPLAY_TZ = timezone.utc


def format_local_datetime(ts: int | float, *, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Момент времени (Unix UTC) → строка в DISPLAY_TZ."""
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(DISPLAY_TZ)
    return dt.strftime(fmt)

TOKEN = os.getenv("TOKEN", "").strip()

# Путь к SQLite. Пусто = авто (см. db._sqlite_path): data/bot.db локально, /app/data/bot.db на BotHost.
# На BotHost в панели можно явно: DB_PATH=/app/data/bot.db
DB_PATH = os.getenv("DB_PATH", "").strip()

# Ожидание блокировки SQLite, сек. (параметр timeout в sqlite3.connect).
# Жёсткость записи на диск: SQLITE_SYNCHRONOUS = NORMAL | FULL | EXTRA (см. документацию SQLite).
SQLITE_BUSY_TIMEOUT = float(os.getenv("SQLITE_BUSY_TIMEOUT", "30"))
_sqlite_sync = os.getenv("SQLITE_SYNCHRONOUS", "NORMAL").strip().upper()
SQLITE_SYNCHRONOUS = _sqlite_sync if _sqlite_sync in ("OFF", "NORMAL", "FULL", "EXTRA") else "NORMAL"

# Повтор запроса к Kufar при сетевых ошибках / 5xx
KUFAR_FETCH_RETRIES = max(1, int(os.getenv("KUFAR_FETCH_RETRIES", "3")))
KUFAR_FETCH_RETRY_DELAY = float(os.getenv("KUFAR_FETCH_RETRY_DELAY", "2"))

VIP_CHECK_INTERVAL = max(1, int(os.getenv("VIP_CHECK_INTERVAL", "30")))
REGULAR_CHECK_INTERVAL = max(1, int(os.getenv("REGULAR_CHECK_INTERVAL", "420")))
# Тик poller: не длиннее VIP, иначе VIP не попадёт в свой интервал.
_raw_check = int(os.getenv("CHECK_INTERVAL", "10"))
CHECK_INTERVAL = max(1, min(_raw_check, VIP_CHECK_INTERVAL))

FIRST_RUN_LIMIT = int(os.getenv("FIRST_RUN_LIMIT", "3"))
VIP_SUBSCRIPTION_DAYS = int(os.getenv("VIP_SUBSCRIPTION_DAYS", "30"))
VIP_PRICE_USD = int(os.getenv("VIP_PRICE_USD", "3"))
REFERRAL_VIP_DAYS_PER_FRIEND = max(1, int(os.getenv("REFERRAL_VIP_DAYS_PER_FRIEND", "1")))
REGULAR_MAX_KEYWORDS = max(1, int(os.getenv("REGULAR_MAX_KEYWORDS", "1")))

# RollyPay VIP checkout
_rolly_enabled = os.getenv("ROLLYPAY_ENABLED", "false").strip().lower()
ROLLYPAY_ENABLED = _rolly_enabled in ("1", "true", "yes", "on")
ROLLYPAY_API_KEY = os.getenv("ROLLYPAY_API_KEY", "").strip()
ROLLYPAY_SIGNING_SECRET = os.getenv("ROLLYPAY_SIGNING_SECRET", "").strip()
ROLLYPAY_TERMINAL_ID = os.getenv(
    "ROLLYPAY_TERMINAL_ID", "dd737481-bbfd-46a9-992c-feb99069bb23"
).strip()
ROLLYPAY_API_URL = (
    os.getenv("ROLLYPAY_API_URL", "https://api.rollypay.io").strip().rstrip("/")
    or "https://api.rollypay.io"
)
ROLLYPAY_CALLBACK_PATH = "/webhooks/rollypay"
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEBHOOK_PORT = max(1, int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "8080"))))
_public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
if not _public_base:
    _domain = os.getenv("DOMAIN", "").strip().rstrip("/")
    if _domain:
        if _domain.startswith("http://") or _domain.startswith("https://"):
            _public_base = _domain
        else:
            _public_base = f"https://{_domain}"
PUBLIC_BASE_URL = _public_base
ROLLYPAY_CALLBACK_URL = (
    f"{PUBLIC_BASE_URL}{ROLLYPAY_CALLBACK_PATH}" if PUBLIC_BASE_URL else ""
)
VIP_PAYMENT_POLL_SECONDS = max(15, int(os.getenv("VIP_PAYMENT_POLL_SECONDS", "45")))

# plan_id -> (days, usd). Optional RUB overrides: VIP_PRICE_RUB_7 / _30 / _90
VIP_PLANS: dict[str, dict[str, int | float]] = {
    "week": {"days": 7, "usd": 1},
    "month": {"days": 30, "usd": 3},
    "quarter": {"days": 90, "usd": 7},
}
_rub_override_env = {
    "week": "VIP_PRICE_RUB_7",
    "month": "VIP_PRICE_RUB_30",
    "quarter": "VIP_PRICE_RUB_90",
}
VIP_PLAN_RUB_OVERRIDE: dict[str, str | None] = {}
for _plan_id, _env_name in _rub_override_env.items():
    _raw = os.getenv(_env_name, "").strip()
    VIP_PLAN_RUB_OVERRIDE[_plan_id] = _raw if _raw else None


def get_vip_plan(plan_id: str) -> dict[str, int | float] | None:
    plan = VIP_PLANS.get(str(plan_id or "").strip().lower())
    return dict(plan) if plan else None

# Объёмы памяти для фильтра (строки в БД: "64", "128", …, "512+")
MEMORY_VOLUME_OPTIONS: tuple[str, ...] = ("64", "128", "256", "512", "512+")
DEFAULT_MEMORY_VOLUMES: tuple[str, ...] = ("64",)
MEMORY_TIER_512_PLUS_GB = 512
MEMORY_TOKEN_512_PLUS = "512+"


def format_memory_volume(vol: str, *, short: bool = False) -> str:
    """Подпись объёма для UI (в БД по-прежнему токен 512+)."""
    if vol == MEMORY_TOKEN_512_PLUS:
        return "более" if short else "от 512 ГБ"
    return f"{vol} ГБ"


# Белорусский рубль (BYN). Международное обозначение — Br (не ₽).
CURRENCY_SIGN = "Br"


def format_price(amount: int | float | None) -> str:
    """Цена в белорусских рублях для отображения в боте."""
    if amount is None:
        return "не указана"
    n = int(amount)
    return f"{n:,}".replace(",", " ") + f" {CURRENCY_SIGN}"


MARKET_DISCOUNT_THRESHOLD = float(os.getenv("MARKET_DISCOUNT_THRESHOLD", "0.85"))
PRICE_DATA_RETENTION_DAYS = max(
    1, int(os.getenv("PRICE_DATA_RETENTION_DAYS", "14"))
)
SEEN_ADS_RETENTION_DAYS = max(1, int(os.getenv("SEEN_ADS_RETENTION_DAYS", "90")))
KUFAR_MAX_PAGES = max(1, int(os.getenv("KUFAR_MAX_PAGES", "2")))
IDEAL_MIN_BATTERY_PERCENT = max(1, min(100, int(os.getenv("IDEAL_MIN_BATTERY_PERCENT", "75"))))
IDEAL_ALLOWED_CONDITIONS: tuple[str, ...] = tuple(
    normalize_label
    for raw in os.getenv("IDEAL_ALLOWED_CONDITIONS", "Отличное,Хорошее").split(",")
    if (normalize_label := raw.strip().lower().replace("ё", "е"))
) or ("отличное", "хорошее")
FILTER_DEBUG_LOG = os.getenv("FILTER_DEBUG_LOG", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
_log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = _log_level if _log_level in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"
# Owner Telegram id (always admin even if Bothost env ADMIN_IDS is empty)
_OWNER_ADMIN_IDS = frozenset({7938175227})
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
} | set(_OWNER_ADMIN_IDS)

DEFAULT_MAX_PRICE = int(os.getenv("DEFAULT_MAX_PRICE", "500"))

MAX_PRICE_PRESETS: tuple[int, ...] = tuple(
    int(x.strip())
    for x in os.getenv("MAX_PRICE_PRESETS", "300,500,800,1000,1500,2000,3000,5000").split(",")
    if x.strip().isdigit()
) or (300, 500, 800, 1000, 1500, 2000, 3000, 5000)

MAX_PRICE_PRESETS_RUB: tuple[int, ...] = tuple(
    int(x.strip())
    for x in os.getenv(
        "MAX_PRICE_PRESETS_RUB",
        "5000,10000,15000,20000,25000,30000,40000,50000",
    ).split(",")
    if x.strip().isdigit()
) or (5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000)

DEFAULT_MAX_PRICE_RUB = max(
    1000,
    int(os.getenv("DEFAULT_MAX_PRICE_RUB", "25000")),
)


def _nearest_preset(price: int, presets: tuple[int, ...]) -> int:
    if not presets:
        return price
    if price <= presets[0]:
        return presets[0]
    if price >= presets[-1]:
        return presets[-1]
    return min(presets, key=lambda p: abs(p - price))


def map_max_price_on_country_switch(
    old_price: int,
    from_country: str | None,
    to_country: str | None,
) -> int:
    """Сопоставление лимита по индексу пресета (не по курсу валют)."""
    from_c = str(from_country or "").strip().lower()
    to_c = str(to_country or "").strip().lower()
    if from_c == to_c:
        return old_price
    if from_c == "by" and to_c == "ru":
        if old_price in MAX_PRICE_PRESETS:
            idx = MAX_PRICE_PRESETS.index(old_price)
            return MAX_PRICE_PRESETS_RUB[min(idx, len(MAX_PRICE_PRESETS_RUB) - 1)]
        return _nearest_preset(old_price, MAX_PRICE_PRESETS_RUB)
    if from_c == "ru" and to_c == "by":
        if old_price in MAX_PRICE_PRESETS_RUB:
            idx = MAX_PRICE_PRESETS_RUB.index(old_price)
            return MAX_PRICE_PRESETS[min(idx, len(MAX_PRICE_PRESETS) - 1)]
        return _nearest_preset(old_price, MAX_PRICE_PRESETS)
    return old_price


def format_price_for_country(
    amount: int | float | None,
    country: str | None = None,
    *,
    primary_source: str | None = None,
) -> str:
    """Цена для UI: BY — Br, RU / Avito — ₽."""
    if amount is None:
        return "не указана"
    n = int(amount)
    text = f"{n:,}".replace(",", " ")
    if str(primary_source or "").strip().lower() == "avito":
        return f"{text} ₽"
    if str(country or "").strip().lower() == "ru":
        return f"{text} ₽"
    return f"{text} {CURRENCY_SIGN}"


def format_price_for_user(
    amount: int | float | None,
    user: dict | None,
) -> str:
    if not user:
        return format_price(amount)
    return format_price_for_country(
        amount,
        user.get("country"),
        primary_source=user.get("primary_source"),
    )

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
    "чехлов",
    "шлейф",
    "шлейфы",
    "экран",
    "микрофон",
)

# Запчасти / платы / разбор: в названии + summary + описании (не целый телефон).
PARTS_EXCLUDE_TERMS: tuple[str, ...] = (
    "запчасти",
    "запчасть",
    "запчастей",
    "платы",
    "плата",
    "плату",
    "плат ",
    "платам",
    "материнск",
    "motherboard",
    "logic board",
    "mainboard",
    "заблокирован",
    "заблокир",
    "icloud lock",
    "на icloud",
    "плата на icloud",
    "донор",
    "донорск",
    "donor parts",
    "разбор",
    "разборка",
    "комплектующ",
    "б/у плата",
    "только плата",
    "продаю плату",
    "продам плату",
    "корпуса",
    "корпусов",
    "без экрана",
    "без дисплея",
    "отдельно экран",
    "отдельно дисплей",
    "на запчасти",
    "для запчаст",
)

# В названии или кратких параметрах (summary) должно быть явно про телефон.
PHONE_REQUIRED_TERMS: tuple[str, ...] = (
    "iphone",
    "айфон",
    "samsung s",
    "самсунг s",
    "galaxy s",
    "z flip",
    "z fold",
    "флип",
    "фолд",
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
    "без торга",
    "без скидок",
    "без скидки",
    "ассортимент обновляется",
    "подписавшись на наш профиль",
    "работаем без скидок",
)

KUFAR_SIZE = int(os.getenv("KUFAR_SIZE", "40"))

# Общий TTL кэша fetch: Kufar по FetchKey, снимок Avito JSON feed.
_feed_refresh_env = os.getenv("FEED_REFRESH_SECONDS")
if _feed_refresh_env:
    FEED_REFRESH_SECONDS = max(1, int(_feed_refresh_env))
else:
    _legacy_fetch_ttl = os.getenv("FETCH_CACHE_TTL_SECONDS")
    _default_refresh = max(VIP_CHECK_INTERVAL, 60)
    FEED_REFRESH_SECONDS = max(
        _default_refresh,
        int(_legacy_fetch_ttl) if _legacy_fetch_ttl else _default_refresh,
    )
MAX_AD_PHOTOS = max(1, int(os.getenv("MAX_AD_PHOTOS", "3")))
AD_DESCRIPTION_MAX_CHARS = max(50, int(os.getenv("AD_DESCRIPTION_MAX_CHARS", "350")))

# Курсы для тройного отображения цен (настраиваются в .env).
BYN_TO_RUB = float(os.getenv("BYN_TO_RUB", "28.5"))
BYN_TO_USD = float(os.getenv("BYN_TO_USD", "0.32"))
RUB_TO_BYN = float(os.getenv("RUB_TO_BYN", "0.035"))
RUB_TO_USD = float(os.getenv("RUB_TO_USD", "0.011"))

# Avito track (Фаза 4): fetch только при AVITO_ENABLED и легальном фиде.
_avito_enabled = os.getenv("AVITO_ENABLED", "false").strip().lower()
AVITO_ENABLED = _avito_enabled in ("1", "true", "yes", "on")
AVITO_CHECK_INTERVAL = max(1, int(os.getenv("AVITO_CHECK_INTERVAL", "420")))
AVITO_VIP_CHECK_INTERVAL = max(1, int(os.getenv("AVITO_VIP_CHECK_INTERVAL", "60")))
_avito_dev_mock = os.getenv("AVITO_DEV_MOCK", "false").strip().lower()
AVITO_DEV_MOCK = _avito_dev_mock in ("1", "true", "yes", "on")
if AVITO_DEV_MOCK and not AVITO_ENABLED:
    AVITO_DEV_MOCK = False

# Фаза 4.2: per-key search API collector (optional override).
AVITO_SEARCH_URL = os.getenv("AVITO_SEARCH_URL", "").strip()

_avito_live_env = os.getenv("AVITO_LIVE_ENABLED", "").strip().lower()
if _avito_live_env:
    AVITO_LIVE_ENABLED = _avito_live_env in ("1", "true", "yes", "on")
else:
    AVITO_LIVE_ENABLED = AVITO_ENABLED

# Фаза 4.1: JSON feed партнёра (fallback если search/live пуст).
AVITO_FEED_URL = os.getenv("AVITO_FEED_URL", "").strip()
AVITO_FEED_AUTH = os.getenv("AVITO_FEED_AUTH", "").strip()
AVITO_FEED_FILE = os.getenv("AVITO_FEED_FILE", "").strip()
AVITO_FEED_TIMEOUT_SECONDS = max(
    5, int(os.getenv("AVITO_FEED_TIMEOUT_SECONDS", "25"))
)
AVITO_FEED_RETRIES = max(1, int(os.getenv("AVITO_FEED_RETRIES", "3")))
AVITO_FEED_RETRY_DELAY = float(os.getenv("AVITO_FEED_RETRY_DELAY", "2"))

# Не целый телефон: проверка по title + summary (стемы ловят стекла/стёкла).
ACCESSORY_HEADLINE_STEMS: tuple[str, ...] = (
    "коробк",
    "стекл",
    "стёкл",
    "защитн",
    "пленк",
    "плёнк",
    "чехол",
    "чехл",
    "аккумулятор",
    "акб",
    "батаре",
    "модул",
    "glass shield",
    "ceramic",
    "film",
)

WHOLE_PHONE_EXCLUDE_HEADLINE: tuple[str, ...] = (
    "клон",
    "clone",
    "replica",
    "реплик",
    "копия",
    "копии",
    "муляж",
    "подделк",
    "дубликат",
    "на запчаст",
    "для запчаст",
    "запчаст",
)
