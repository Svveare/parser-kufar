import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN", "").strip()

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
]

# Стоп-слова по смыслу объявления: проверяются только в названии (subject),
# чтобы «чехол в подарок» в описании не отсекало продажу телефона.
DEFAULT_EXCLUDE_TERMS: tuple[str, ...] = (
    "чехол",
    "чехлы",
    "защитное стекло",
    "стекло",
    "пленка",
    "плёнка",
    "гидрогель",
    "бампер",
    "кейс",
    "case",
    "кабель",
    "зарядка",
    "блок питания",
    "адаптер",
    "ремонт",
    "замена аккумулятора",
    "замена акб",
    "замена батареи",
    "аккумулятор",
    "акб",
    "дисплей",
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
