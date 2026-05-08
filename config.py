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

KUFAR_QUERY = os.getenv("KUFAR_QUERY", "iphone")
KUFAR_REGION = int(os.getenv("KUFAR_REGION", "7"))
KUFAR_SIZE = int(os.getenv("KUFAR_SIZE", "30"))
