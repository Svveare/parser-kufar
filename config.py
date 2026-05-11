import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN", "").strip()

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

FIRST_RUN_LIMIT = int(os.getenv("FIRST_RUN_LIMIT", "3"))

DEFAULT_MAX_PRICE = int(os.getenv("DEFAULT_MAX_PRICE", "500"))

DEFAULT_KEYWORDS = [
    "iphone x",
    "iphone xs",
    "iphone xs max",
    "iphone xr",
    "iphone 11",
    "iphone 11 pro",
    "iphone 12",
    "iphone 12 mini",
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
