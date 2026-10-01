import logging
import secrets
import shutil
import sqlite3
import string
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config import (
    DB_PATH as DB_PATH_OVERRIDE,
    DEFAULT_KEYWORDS,
    DEFAULT_MAX_PRICE,
    DEFAULT_MEMORY_VOLUMES,
    MEMORY_VOLUME_OPTIONS,
    map_max_price_on_country_switch,
    PRICE_DATA_RETENTION_DAYS,
    REFERRAL_VIP_DAYS_PER_FRIEND,
    REGULAR_MAX_KEYWORDS,
    SEEN_ADS_RETENTION_DAYS,
    SQLITE_BUSY_TIMEOUT,
    SQLITE_SYNCHRONOUS,
    VIP_SUBSCRIPTION_DAYS,
)
from kufar_catalog import CITY_RGN, CITY_LABELS, DEFAULT_CITY, normalize_city, RGN_TO_SLUG
from marketplace.types import (
    COUNTRY_BY,
    COUNTRY_RU,
    COUNTRIES,
    SOURCE_AVITO,
    SOURCE_KUFAR,
    default_source_for_country,
    normalize_country,
    normalize_primary_source,
)
from product_catalog import (
    DEFAULT_CATEGORY,
    DEVICE_CATALOG_SET,
    normalize_category,
)

log = logging.getLogger(__name__)

_SQLITE_SYNC_NUM = {"OFF": 0, "NORMAL": 1, "FULL": 2, "EXTRA": 3}[SQLITE_SYNCHRONOUS]
TRIAL_PROMO_CODE = "VIPTRIAL7"
TRIAL_PROMO_DAYS = 7


def _norm_username(username: str | None) -> str:
    if not username:
        return ""
    return username.strip().lstrip("@")[:64]


def _norm_promo_code(code: str | None) -> str:
    if not code:
        return ""
    return code.strip().upper()[:64]


def _norm_memory_volumes(volumes: list[str] | None) -> list[str]:
    allowed = set(MEMORY_VOLUME_OPTIONS)
    cleaned: list[str] = []
    for v in volumes or []:
        s = str(v).strip()
        if s in allowed and s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        return list(DEFAULT_MEMORY_VOLUMES)
    return cleaned


def _memory_csv(volumes: list[str]) -> str:
    return ",".join(_norm_memory_volumes(volumes))


def _keywords_csv(keywords: list[str]) -> str:
    cleaned = [k.strip().lower() for k in keywords if k and str(k).strip()]
    # preserve order, unique
    out: list[str] = []
    for k in cleaned:
        if k not in out:
            out.append(k)
    return ",".join(out)


def _trim_keywords_for_regular(keywords: list[str] | None) -> list[str]:
    cleaned = [k.strip().lower() for k in (keywords or []) if k and str(k).strip()]
    out: list[str] = []
    for k in cleaned:
        if k not in out:
            out.append(k)
        if len(out) >= REGULAR_MAX_KEYWORDS:
            break
    return out


def _regular_search_limits_sql(
    keywords: list[str] | None,
) -> tuple[str, str]:
    """keywords CSV + memory CSV for demoted regular user."""
    return (
        _keywords_csv(_trim_keywords_for_regular(keywords)),
        _memory_csv(list(DEFAULT_MEMORY_VOLUMES)),
    )


def _parse_memory_csv(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_MEMORY_VOLUMES)
    return _norm_memory_volumes([p.strip() for p in raw.split(",") if p.strip()])


def _generate_referral_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(32):
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        cur = _execute("SELECT 1 FROM users WHERE referral_code = ?", (code,))
        if cur.fetchone() is None:
            return code
    return "".join(secrets.choice(alphabet) for _ in range(12))


_USER_SELECT = (
    "chat_id, active, role, vip_until, max_price, keywords, sent_count, created_at, "
    "vip_feed_mode, username, memory_volumes, referral_code, referred_by, "
    "poll_last_vip, poll_last_regular, city, product_category, "
    "city_rgn, city_ar, city_label, country, primary_source, "
    "avito_city_id, avito_region_id, avito_city_label, "
    "poll_last_avito_vip, poll_last_avito_regular"
)

def _row_to_user(row: tuple) -> dict:
    return {
        "chat_id": row[0],
        "active": bool(row[1]),
        "role": row[2],
        "vip_until": int(row[3] or 0),
        "max_price": row[4],
        "keywords": [k.strip() for k in row[5].split(",") if k.strip()],
        "sent_count": row[6],
        "created_at": row[7],
        "vip_feed_mode": row[8] or "normal",
        "username": (row[9] or "").strip() if len(row) > 9 else "",
        "memory_volumes": _parse_memory_csv(row[10] if len(row) > 10 else None),
        "referral_code": (row[11] or "").strip() if len(row) > 11 else "",
        "referred_by": int(row[12]) if len(row) > 12 and row[12] is not None else None,
        "poll_last_vip": int(row[13] or 0) if len(row) > 13 else 0,
        "poll_last_regular": int(row[14] or 0) if len(row) > 14 else 0,
        "city": normalize_city(row[15] if len(row) > 15 else None),
        "product_category": normalize_category(row[16] if len(row) > 16 else None),
        "city_rgn": int(row[17] if len(row) > 17 and row[17] is not None else CITY_RGN[DEFAULT_CITY]),
        "city_ar": (
            int(row[18])
            if len(row) > 18 and row[18] is not None
            else None
        ),
        "city_label": (
            (row[19] or "").strip()
            if len(row) > 19 and row[19]
            else CITY_LABELS[DEFAULT_CITY]
        ),
        "country": normalize_country(row[20] if len(row) > 20 else None),
        "primary_source": normalize_primary_source(
            row[21] if len(row) > 21 else None
        ),
        "avito_city_id": (row[22] or "").strip() if len(row) > 22 else "",
        "avito_region_id": (row[23] or "").strip() if len(row) > 23 else "",
        "avito_city_label": (row[24] or "").strip() if len(row) > 24 else "",
        "poll_last_avito_vip": int(row[25] or 0) if len(row) > 25 else 0,
        "poll_last_avito_regular": int(row[26] or 0) if len(row) > 26 else 0,
    }


def _migrate_legacy_db(target: Path) -> None:
    """Переносит старый bot.db из корня проекта в постоянную папку data (один раз)."""
    if target.exists():
        return
    project_dir = Path(__file__).resolve().parent
    legacy = project_dir / "bot.db"
    if not legacy.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    log.info("[DB] перенесена база %s → %s", legacy, target)
    for suffix in ("-wal", "-shm"):
        side = Path(str(legacy) + suffix)
        if side.is_file():
            try:
                shutil.copy2(side, Path(str(target) + suffix))
            except OSError:
                log.warning("[DB] не удалось скопировать %s", side, exc_info=True)


def _sqlite_path() -> str:
    """
    Абсолютный путь к SQLite (не зависит от cwd).

    Приоритет:
    1) DB_PATH из .env / панели BotHost
    2) /app/data/bot.db — персистентное хранилище BotHost (не затирается при git deploy)
    3) <проект>/data/bot.db локально (с миграцией из старого bot.db в корне)
    """
    if DB_PATH_OVERRIDE:
        p = Path(DB_PATH_OVERRIDE).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)

    bothost_data = Path("/app/data")
    if bothost_data.is_dir():
        db_file = bothost_data / "bot.db"
        _migrate_legacy_db(db_file)
        bothost_data.mkdir(parents=True, exist_ok=True)
        return str(db_file)

    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = data_dir / "bot.db"
    _migrate_legacy_db(db_file)
    return str(db_file)


SQLITE_PATH = _sqlite_path()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
        SQLITE_PATH,
        timeout=SQLITE_BUSY_TIMEOUT,
        check_same_thread=False,
        isolation_level=None,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA synchronous={_SQLITE_SYNC_NUM}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


conn = _connect()
_db_lock = threading.RLock()
_sql_metrics = {"queries": 0, "seconds": 0.0}


def _execute(sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
    with _db_lock:
        started = time.perf_counter()
        try:
            return conn.execute(sql, params)
        finally:
            _sql_metrics["queries"] += 1
            _sql_metrics["seconds"] += time.perf_counter() - started


def _executemany(sql: str, seq: list[tuple]) -> None:
    if not seq:
        return
    with _db_lock:
        started = time.perf_counter()
        conn.execute("BEGIN")
        try:
            conn.executemany(sql, seq)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            _sql_metrics["queries"] += 1
            _sql_metrics["seconds"] += time.perf_counter() - started


def sql_metrics_snapshot(*, reset: bool = False) -> tuple[int, float]:
    with _db_lock:
        snapshot = (int(_sql_metrics["queries"]), float(_sql_metrics["seconds"]))
        if reset:
            _sql_metrics.update(queries=0, seconds=0.0)
        return snapshot


def _executescript(script: str) -> None:
    with _db_lock:
        conn.executescript(script)


def _table_columns(name: str) -> set[str]:
    cur = _execute(f"PRAGMA table_info({name})")
    return {row[1] for row in cur.fetchall()}


def init_db() -> None:
    log.debug("sqlite path=%s", SQLITE_PATH)
    # Старая схема (с прошлых экспериментов) — сносим, чтобы создать заново
    existing = _table_columns("users")
    if existing and "active" not in existing:
        _execute("DROP TABLE users")

    _executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id    INTEGER PRIMARY KEY,
            active     INTEGER NOT NULL DEFAULT 1,
            role       TEXT    NOT NULL DEFAULT 'regular',
            vip_until  INTEGER NOT NULL DEFAULT 0,
            max_price  INTEGER NOT NULL,
            keywords   TEXT    NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            city       TEXT    NOT NULL DEFAULT 'minsk',
            product_category TEXT NOT NULL DEFAULT 'phones'
        );

        CREATE TABLE IF NOT EXISTS seen_ads (
            chat_id INTEGER NOT NULL,
            link    TEXT    NOT NULL,
            seen_at INTEGER NOT NULL,
            PRIMARY KEY (chat_id, link)
        );
        
        CREATE TABLE IF NOT EXISTS sent_prices (
            chat_id    INTEGER NOT NULL,
            link       TEXT    NOT NULL,
            device_key TEXT    NOT NULL,
            price      INTEGER NOT NULL,
            sent_at    INTEGER NOT NULL,
            PRIMARY KEY (chat_id, link)
        );
        
        CREATE TABLE IF NOT EXISTS market_prices (
            link       TEXT PRIMARY KEY,
            device_key TEXT    NOT NULL,
            price      INTEGER NOT NULL,
            sent_at    INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            code       TEXT PRIMARY KEY,
            vip_days   INTEGER NOT NULL,
            max_uses   INTEGER NOT NULL DEFAULT 0,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_activations (
            chat_id INTEGER NOT NULL,
            code    TEXT    NOT NULL,
            used_at INTEGER NOT NULL,
            PRIMARY KEY (chat_id, code),
            FOREIGN KEY (code) REFERENCES promo_codes(code) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_seen_chat ON seen_ads(chat_id);
        CREATE INDEX IF NOT EXISTS idx_seen_seen_at ON seen_ads(seen_at);
        CREATE INDEX IF NOT EXISTS idx_sent_prices_lookup ON sent_prices(chat_id, device_key);
        CREATE INDEX IF NOT EXISTS idx_market_prices_device ON market_prices(device_key);
        CREATE INDEX IF NOT EXISTS idx_market_prices_sent_at ON market_prices(sent_at);
        CREATE INDEX IF NOT EXISTS idx_sent_prices_sent_at ON sent_prices(sent_at);
        CREATE INDEX IF NOT EXISTS idx_promo_activations_code ON promo_activations(code);
        """
    )
    cols = _table_columns("users")
    if "role" not in cols:
        _execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'regular'")
    if "vip_until" not in cols:
        _execute("ALTER TABLE users ADD COLUMN vip_until INTEGER NOT NULL DEFAULT 0")
    if "vip_feed_mode" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN vip_feed_mode TEXT NOT NULL DEFAULT 'normal'"
        )
    if "username" not in cols:
        _execute("ALTER TABLE users ADD COLUMN username TEXT NOT NULL DEFAULT ''")
    cols = _table_columns("users")
    if "memory_volumes" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN memory_volumes TEXT NOT NULL DEFAULT '64'"
        )
    if "referral_code" not in cols:
        _execute("ALTER TABLE users ADD COLUMN referral_code TEXT NOT NULL DEFAULT ''")
    if "referred_by" not in cols:
        _execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
    cols = _table_columns("users")
    if "poll_last_vip" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN poll_last_vip INTEGER NOT NULL DEFAULT 0"
        )
    if "poll_last_regular" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN poll_last_regular INTEGER NOT NULL DEFAULT 0"
        )
    cols = _table_columns("users")
    if "city" not in cols:
        _execute(
            f"ALTER TABLE users ADD COLUMN city TEXT NOT NULL DEFAULT '{DEFAULT_CITY}'"
        )
    cols = _table_columns("users")
    if "product_category" not in cols:
        _execute(
            f"ALTER TABLE users ADD COLUMN product_category TEXT NOT NULL DEFAULT '{DEFAULT_CATEGORY}'"
        )
    cols = _table_columns("users")
    geo_added = False
    if "city_rgn" not in cols:
        _execute("ALTER TABLE users ADD COLUMN city_rgn INTEGER NOT NULL DEFAULT 7")
        geo_added = True
    if "city_ar" not in cols:
        _execute("ALTER TABLE users ADD COLUMN city_ar INTEGER")
        geo_added = True
    if "city_label" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN city_label TEXT NOT NULL DEFAULT 'Минск'"
        )
        geo_added = True
    if geo_added:
        _backfill_city_geo_from_slug()
    cols = _table_columns("users")
    if "country" not in cols:
        _execute(
            f"ALTER TABLE users ADD COLUMN country TEXT NOT NULL DEFAULT '{COUNTRY_BY}'"
        )
    if "primary_source" not in cols:
        _execute(
            f"ALTER TABLE users ADD COLUMN primary_source TEXT NOT NULL DEFAULT '{SOURCE_KUFAR}'"
        )
    seen_cols = _table_columns("seen_ads")
    if "source" not in seen_cols:
        _execute(
            f"ALTER TABLE seen_ads ADD COLUMN source TEXT NOT NULL DEFAULT '{SOURCE_KUFAR}'"
        )
    market_cols = _table_columns("market_prices")
    if "source" not in market_cols:
        _execute(
            f"ALTER TABLE market_prices ADD COLUMN source TEXT NOT NULL DEFAULT '{SOURCE_KUFAR}'"
        )
    sent_cols = _table_columns("sent_prices")
    if "source" not in sent_cols:
        _execute(
            f"ALTER TABLE sent_prices ADD COLUMN source TEXT NOT NULL DEFAULT '{SOURCE_KUFAR}'"
        )
    cols = _table_columns("users")
    if "avito_city_id" not in cols:
        _execute("ALTER TABLE users ADD COLUMN avito_city_id TEXT NOT NULL DEFAULT ''")
    if "avito_region_id" not in cols:
        _execute("ALTER TABLE users ADD COLUMN avito_region_id TEXT NOT NULL DEFAULT ''")
    if "avito_city_label" not in cols:
        _execute("ALTER TABLE users ADD COLUMN avito_city_label TEXT NOT NULL DEFAULT ''")
    cols = _table_columns("users")
    if "poll_last_avito_vip" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN poll_last_avito_vip INTEGER NOT NULL DEFAULT 0"
        )
    if "poll_last_avito_regular" not in cols:
        _execute(
            "ALTER TABLE users ADD COLUMN poll_last_avito_regular INTEGER NOT NULL DEFAULT 0"
        )
    _executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_market_prices_lookup
            ON market_prices(device_key, source, sent_at);

        CREATE TABLE IF NOT EXISTS referrals (
            referred_chat_id  INTEGER PRIMARY KEY,
            referrer_chat_id  INTEGER NOT NULL,
            created_at        INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_chat_id);

        CREATE TABLE IF NOT EXISTS vip_payments (
            order_id     TEXT PRIMARY KEY,
            chat_id      INTEGER NOT NULL,
            plan         TEXT NOT NULL,
            days         INTEGER NOT NULL,
            amount_usd   REAL NOT NULL,
            amount_rub   TEXT NOT NULL,
            payment_id   TEXT,
            pay_url      TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   INTEGER NOT NULL,
            paid_at      INTEGER
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vip_payments_payment_id
            ON vip_payments(payment_id) WHERE payment_id IS NOT NULL AND payment_id != '';
        CREATE INDEX IF NOT EXISTS idx_vip_payments_status ON vip_payments(status);
        CREATE INDEX IF NOT EXISTS idx_vip_payments_chat ON vip_payments(chat_id);
        """
    )
    _backfill_referral_codes()
    promo_cols = _table_columns("promo_codes")
    if "max_uses" not in promo_cols:
        _execute("ALTER TABLE promo_codes ADD COLUMN max_uses INTEGER NOT NULL DEFAULT 0")
    _execute(
        "INSERT OR IGNORE INTO promo_codes (code, vip_days, max_uses, is_active, created_at) VALUES (?, ?, 0, 1, ?)",
        (TRIAL_PROMO_CODE, TRIAL_PROMO_DAYS, int(time.time())),
    )
    _cleanup_used_up_promo_codes()
    deleted = prune_price_tables()
    if deleted[0] or deleted[1]:
        log.info(
            "price tables pruned on init market=%s sent=%s retention_days=%s",
            deleted[0],
            deleted[1],
            PRICE_DATA_RETENTION_DAYS,
        )
    seen_deleted = prune_seen_ads()
    if seen_deleted:
        log.info(
            "seen_ads pruned on init deleted=%s retention_days=%s",
            seen_deleted,
            SEEN_ADS_RETENTION_DAYS,
        )
    stale = prune_unknown_market_prices()
    if stale:
        log.info("market_prices pruned unknown models deleted=%s", stale)
    checkpoint_wal()


def _backfill_city_geo_from_slug() -> None:
    for slug, rgn in CITY_RGN.items():
        label = CITY_LABELS[slug]
        _execute(
            "UPDATE users SET city_rgn = ?, city_ar = NULL, city_label = ? WHERE city = ?",
            (rgn, label, slug),
        )


def _backfill_referral_codes() -> None:
    cur = _execute(
        "SELECT chat_id FROM users WHERE referral_code IS NULL OR referral_code = ''"
    )
    for (chat_id,) in cur.fetchall():
        _execute(
            "UPDATE users SET referral_code = ? WHERE chat_id = ?",
            (_generate_referral_code(), chat_id),
        )


def update_user_username(chat_id: int, username: str | None) -> None:
    """Telegram @username без «@»; пусто — сброс. Без записи, если значение не изменилось."""
    new = _norm_username(username)
    _execute(
        "UPDATE users SET username = ? WHERE chat_id = ? AND IFNULL(username, '') != ?",
        (new, chat_id, new),
    )


def add_user(chat_id: int, *, username: str | None = None) -> bool:
    """Добавить пользователя или реактивировать. True если это новый юзер."""
    u = _norm_username(username)
    cur = _execute(
        "SELECT active, username FROM users WHERE chat_id = ?", (chat_id,)
    )
    row = cur.fetchone()
    if row is None:
        ref_code = _generate_referral_code()
        _execute(
            "INSERT INTO users (chat_id, active, role, vip_until, max_price, keywords, "
            "created_at, vip_feed_mode, username, memory_volumes, referral_code, city, "
            "product_category) "
            "VALUES (?, 1, 'regular', 0, ?, ?, ?, 'normal', ?, ?, ?, ?, ?)",
            (
                chat_id,
                DEFAULT_MAX_PRICE,
                ",".join(DEFAULT_KEYWORDS),
                int(time.time()),
                u,
                _memory_csv(list(DEFAULT_MEMORY_VOLUMES)),
                ref_code,
                DEFAULT_CITY,
                DEFAULT_CATEGORY,
            ),
        )
        return True
    active, old_username = row[0], (row[1] or "")
    if active == 0:
        _execute(
            "UPDATE users SET active = 1, username = ? WHERE chat_id = ?",
            (u, chat_id),
        )
    elif old_username != u:
        _execute(
            "UPDATE users SET username = ? WHERE chat_id = ?",
            (u, chat_id),
        )
    return False


def set_active(chat_id: int, active: bool) -> None:
    _execute(
        "UPDATE users SET active = ? WHERE chat_id = ?",
        (1 if active else 0, chat_id),
    )


def get_user(chat_id: int) -> Optional[dict]:
    cur = _execute(
        f"SELECT {_USER_SELECT} FROM users WHERE chat_id = ?",
        (chat_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    user = _row_to_user(row)
    now = int(time.time())
    if user.get("role") == "vip" and 0 < int(user.get("vip_until") or 0) < now:
        kw_csv, memory = _regular_search_limits_sql(user.get("keywords"))
        _execute(
            "UPDATE users SET role = 'regular', vip_until = 0, vip_feed_mode = 'normal', "
            "keywords = ?, memory_volumes = ? WHERE chat_id = ?",
            (kw_csv, memory, chat_id),
        )
        user["role"] = "regular"
        user["vip_until"] = 0
        user["vip_feed_mode"] = "normal"
        user["keywords"] = _trim_keywords_for_regular(user.get("keywords"))
        user["memory_volumes"] = list(DEFAULT_MEMORY_VOLUMES)
    elif user.get("role") != "vip":
        kw = user.get("keywords") or []
        mem = user.get("memory_volumes") or []
        need_kw = len(kw) > REGULAR_MAX_KEYWORDS
        need_mem = len(mem) > 1
        if need_kw or need_mem:
            kw_csv, memory = _regular_search_limits_sql(kw)
            if not need_mem:
                memory = _memory_csv(mem)
            if not need_kw:
                kw_csv = _keywords_csv(kw)
            _execute(
                "UPDATE users SET keywords = ?, memory_volumes = ? WHERE chat_id = ?",
                (kw_csv, memory, chat_id),
            )
            user["keywords"] = (
                _trim_keywords_for_regular(kw) if need_kw else list(kw)
            )
            user["memory_volumes"] = (
                list(DEFAULT_MEMORY_VOLUMES) if need_mem else list(mem)
            )
    return user


def count_users_total() -> int:
    cur = _execute("SELECT COUNT(*) FROM users")
    return int(cur.fetchone()[0])


def count_users_active() -> int:
    cur = _execute("SELECT COUNT(*) FROM users WHERE active = 1")
    return int(cur.fetchone()[0])


def count_users_vip() -> int:
    expire_all_vip()
    now = int(time.time())
    cur = _execute(
        "SELECT COUNT(*) FROM users WHERE role = 'vip' AND vip_until > ?",
        (now,),
    )
    return int(cur.fetchone()[0])


def list_users_page(*, offset: int, limit: int) -> list[dict]:
    expire_all_vip()
    cur = _execute(
        f"SELECT {_USER_SELECT} FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    return [_row_to_user(r) for r in cur.fetchall()]


def clear_market_prices() -> int:
    cur = _execute("DELETE FROM market_prices")
    return cur.rowcount if cur.rowcount is not None else 0


def get_active_users(*, expire_vip: bool = True) -> list[dict]:
    if expire_vip:
        expire_all_vip()
    cur = _execute(f"SELECT {_USER_SELECT} FROM users WHERE active = 1")
    return [_row_to_user(r) for r in cur.fetchall()]


def update_max_price(chat_id: int, max_price: int) -> int:
    _execute(
        "UPDATE users SET max_price = ? WHERE chat_id = ?",
        (max_price, chat_id),
    )
    return int(max_price)


def update_keywords(chat_id: int, keywords: list[str]) -> list[str]:
    cleaned = [k.strip().lower() for k in keywords if k.strip()]
    _execute(
        "UPDATE users SET keywords = ? WHERE chat_id = ?",
        (",".join(cleaned), chat_id),
    )
    return cleaned


def update_memory_volumes(chat_id: int, volumes: list[str]) -> list[str]:
    normalized = _norm_memory_volumes(volumes)
    _execute(
        "UPDATE users SET memory_volumes = ? WHERE chat_id = ?",
        (_memory_csv(normalized), chat_id),
    )
    return normalized


def update_city(chat_id: int, city: str) -> str:
    slug = (city or "").strip().lower().replace("ё", "е")
    if slug not in CITY_RGN:
        cur = _execute("SELECT city FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return normalize_city(row[0] if row else None)
    rgn = CITY_RGN[slug]
    label = CITY_LABELS[slug]
    update_geo(chat_id, rgn, None, label)
    return slug


def update_country(chat_id: int, country: str) -> dict[str, str | int]:
    c = normalize_country(country)
    if c not in COUNTRIES:
        cur = _execute("SELECT country, primary_source FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        if row is None:
            return {"country": COUNTRY_BY, "primary_source": SOURCE_KUFAR}
        return {
            "country": normalize_country(row[0]),
            "primary_source": normalize_primary_source(row[1]),
        }
    user = get_user(chat_id)
    old_country = normalize_country((user or {}).get("country"))
    old_price = int((user or {}).get("max_price") or DEFAULT_MAX_PRICE)
    source = default_source_for_country(c)
    _execute(
        "UPDATE users SET country = ?, primary_source = ? WHERE chat_id = ?",
        (c, source, chat_id),
    )
    out: dict[str, str | int] = {"country": c, "primary_source": source}
    if user and old_country != c:
        new_price = map_max_price_on_country_switch(old_price, old_country, c)
        if new_price != old_price:
            out["max_price"] = update_max_price(chat_id, new_price)
    return out


def update_geo(
    chat_id: int,
    rgn: int,
    ar: int | None,
    label: str,
) -> dict[str, object]:
    rgn_i = int(rgn)
    ar_val = int(ar) if ar is not None else None
    label_clean = (label or "").strip()
    slug = RGN_TO_SLUG.get(rgn_i, DEFAULT_CITY)
    _execute(
        "UPDATE users SET city_rgn = ?, city_ar = ?, city_label = ?, city = ? "
        "WHERE chat_id = ?",
        (rgn_i, ar_val, label_clean, slug, chat_id),
    )
    return {
        "city_rgn": rgn_i,
        "city_ar": ar_val,
        "city_label": label_clean,
        "city": slug,
    }


def update_avito_geo(
    chat_id: int,
    region_id: str,
    city_id: str,
    label: str,
) -> dict[str, str]:
    region_clean = str(region_id or "").strip()
    city_clean = str(city_id or "").strip()
    label_clean = (label or "").strip()
    _execute(
        "UPDATE users SET avito_region_id = ?, avito_city_id = ?, avito_city_label = ? "
        "WHERE chat_id = ?",
        (region_clean, city_clean, label_clean, chat_id),
    )
    return {
        "avito_region_id": region_clean,
        "avito_city_id": city_clean,
        "avito_city_label": label_clean,
    }


def update_product_category(chat_id: int, category: str, *, reset_keywords: bool = True) -> str:
    slug = normalize_category(category)
    if reset_keywords:
        _execute(
            "UPDATE users SET product_category = ?, keywords = '' WHERE chat_id = ?",
            (slug, chat_id),
        )
    else:
        _execute(
            "UPDATE users SET product_category = ? WHERE chat_id = ?",
            (slug, chat_id),
        )
    return slug


def ensure_referral_code(chat_id: int, *, user: dict | None = None) -> str:
    """Реферальный код пользователя; при необходимости создаёт без полного get_user."""
    if user is not None:
        code = (user.get("referral_code") or "").strip()
        if code:
            return code
    else:
        cur = _execute(
            "SELECT referral_code FROM users WHERE chat_id = ?",
            (chat_id,),
        )
        row = cur.fetchone()
        if row is None:
            return ""
        code = (row[0] or "").strip()
        if code:
            return code
    code = _generate_referral_code()
    _execute(
        "UPDATE users SET referral_code = ? WHERE chat_id = ?",
        (code, chat_id),
    )
    if user is not None:
        user["referral_code"] = code
    return code


def get_user_by_referral_code(code: str) -> Optional[dict]:
    ref = (code or "").strip().upper()
    if not ref:
        return None
    cur = _execute(
        f"SELECT {_USER_SELECT} FROM users WHERE referral_code = ?",
        (ref,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_user(row)


def count_referrals(referrer_chat_id: int) -> int:
    cur = _execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_chat_id = ?",
        (referrer_chat_id,),
    )
    return int(cur.fetchone()[0])


def grant_vip_days(chat_id: int, days: int) -> None:
    set_vip(chat_id, days=max(1, int(days)))


def process_referral_signup(new_chat_id: int, ref_code: str) -> int | None:
    """Начисляет VIP-дни пригласившему. Возвращает chat_id пригласившего или None."""
    referrer = get_user_by_referral_code(ref_code)
    if referrer is None:
        return None
    referrer_id = int(referrer["chat_id"])
    if referrer_id == new_chat_id:
        return None
    cur = _execute(
        "SELECT 1 FROM referrals WHERE referred_chat_id = ?",
        (new_chat_id,),
    )
    if cur.fetchone() is not None:
        return None
    now = int(time.time())
    try:
        _execute(
            "INSERT INTO referrals (referred_chat_id, referrer_chat_id, created_at) "
            "VALUES (?, ?, ?)",
            (new_chat_id, referrer_id, now),
        )
    except sqlite3.IntegrityError:
        return None
    _execute(
        "UPDATE users SET referred_by = ? WHERE chat_id = ? AND referred_by IS NULL",
        (referrer_id, new_chat_id),
    )
    grant_vip_days(referrer_id, REFERRAL_VIP_DAYS_PER_FRIEND)
    log.info(
        "referral bonus referrer=%s new_user=%s days=%s",
        referrer_id,
        new_chat_id,
        REFERRAL_VIP_DAYS_PER_FRIEND,
    )
    return referrer_id


def seen_links_for(
    chat_id: int,
    links: list[str],
    *,
    source: str = SOURCE_KUFAR,
) -> set[str]:
    """Ссылки из links, уже отмеченные как просмотренные для chat_id."""
    unique = [l for l in dict.fromkeys(links) if isinstance(l, str) and l.strip()]
    if not unique:
        return set()
    src = normalize_primary_source(source)
    placeholders = ",".join("?" * len(unique))
    cur = _execute(
        f"SELECT link FROM seen_ads WHERE chat_id = ? AND source = ? AND link IN ({placeholders})",
        (chat_id, src, *unique),
    )
    return {row[0] for row in cur.fetchall()}


def mark_seen(chat_id: int, link: str, *, source: str = SOURCE_KUFAR) -> None:
    src = normalize_primary_source(source)
    _execute(
        "INSERT OR IGNORE INTO seen_ads (chat_id, link, seen_at, source) VALUES (?, ?, ?, ?)",
        (chat_id, link, int(time.time()), src),
    )


def prune_seen_ads(retention_days: int | None = None) -> int:
    """Удаляет просмотренные объявления старше retention_days."""
    days = retention_days if retention_days is not None else SEEN_ADS_RETENTION_DAYS
    cutoff = int(time.time()) - max(1, int(days)) * 86400
    cur = _execute("DELETE FROM seen_ads WHERE seen_at < ?", (cutoff,))
    return cur.rowcount if cur.rowcount is not None else 0


def set_poll_last_run(
    chat_id: int,
    *,
    is_vip: bool,
    source: str = SOURCE_KUFAR,
) -> None:
    now = int(time.time())
    src = normalize_primary_source(source)
    if src == SOURCE_AVITO:
        if is_vip:
            _execute(
                "UPDATE users SET poll_last_avito_vip = ? WHERE chat_id = ?",
                (now, chat_id),
            )
        else:
            _execute(
                "UPDATE users SET poll_last_avito_regular = ? WHERE chat_id = ?",
                (now, chat_id),
            )
        return
    if is_vip:
        _execute(
            "UPDATE users SET poll_last_vip = ? WHERE chat_id = ?",
            (now, chat_id),
        )
    else:
        _execute(
            "UPDATE users SET poll_last_regular = ? WHERE chat_id = ?",
            (now, chat_id),
        )


def has_seen_any(chat_id: int) -> bool:
    cur = _execute(
        "SELECT 1 FROM seen_ads WHERE chat_id = ? LIMIT 1", (chat_id,)
    )
    return cur.fetchone() is not None


def increment_sent(chat_id: int) -> None:
    _execute(
        "UPDATE users SET sent_count = sent_count + 1 WHERE chat_id = ?",
        (chat_id,),
    )


def save_market_prices(rows: list[tuple[str, str, int] | tuple[str, str, int, str]]) -> None:
    if not rows:
        return
    now = int(time.time())
    normalized: list[tuple[str, str, int, str, int]] = []
    for row in rows:
        if len(row) >= 4:
            link, device_key, price, source = row[0], row[1], row[2], row[3]
        else:
            link, device_key, price = row[0], row[1], row[2]
            source = SOURCE_KUFAR
        normalized.append(
            (
                link,
                device_key,
                price,
                normalize_primary_source(source),
                now,
            )
        )
    _executemany(
        "INSERT OR IGNORE INTO market_prices (link, device_key, price, source, sent_at) "
        "VALUES (?, ?, ?, ?, ?)",
        normalized,
    )


def _price_retention_cutoff(retention_days: int | None = None) -> int:
    days = retention_days if retention_days is not None else PRICE_DATA_RETENTION_DAYS
    return int(time.time()) - max(1, int(days)) * 86400


def prune_price_tables(retention_days: int | None = None) -> tuple[int, int]:
    """Удаляет записи market_prices и sent_prices старше retention_days."""
    cutoff = _price_retention_cutoff(retention_days)
    cur_m = _execute("DELETE FROM market_prices WHERE sent_at < ?", (cutoff,))
    cur_s = _execute("DELETE FROM sent_prices WHERE sent_at < ?", (cutoff,))
    deleted_m = cur_m.rowcount if cur_m.rowcount is not None else 0
    deleted_s = cur_s.rowcount if cur_s.rowcount is not None else 0
    return deleted_m, deleted_s


def prune_unknown_market_prices() -> int:
    """Цены по моделям, которых больше нет в каталоге."""
    if not DEVICE_CATALOG_SET:
        return 0
    placeholders = ",".join("?" for _ in DEVICE_CATALOG_SET)
    cur = _execute(
        f"DELETE FROM market_prices WHERE device_key NOT IN ({placeholders})",
        tuple(DEVICE_CATALOG_SET),
    )
    return cur.rowcount if cur.rowcount is not None else 0


def avg_market_price(device_key: str, *, source: str = SOURCE_KUFAR) -> int | None:
    cutoff = _price_retention_cutoff()
    src = normalize_primary_source(source)
    cur = _execute(
        "SELECT AVG(price) FROM market_prices WHERE device_key = ? AND source = ? AND sent_at >= ?",
        (device_key, src, cutoff),
    )
    row = cur.fetchone()
    avg_value = row[0] if row else None
    if avg_value is None:
        return None
    return int(avg_value)


def update_vip_feed_mode(chat_id: int, mode: str) -> None:
    if mode not in ("normal", "below_market", "exchange", "ideal"):
        return
    _execute(
        "UPDATE users SET vip_feed_mode = ? WHERE chat_id = ? AND role = 'vip'",
        (mode, chat_id),
    )


def checkpoint_wal() -> None:
    """Сброс WAL на диск (безопаснее при копировании bot.db и при остановке процесса)."""
    try:
        _execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        log.debug("wal_checkpoint skipped", exc_info=True)


def close() -> None:
    try:
        checkpoint_wal()
    finally:
        with _db_lock:
            conn.close()


def set_vip(chat_id: int, *, days: int = VIP_SUBSCRIPTION_DAYS) -> None:
    cur_ref = _execute(
        "SELECT referral_code FROM users WHERE chat_id = ?", (chat_id,)
    )
    ref_row = cur_ref.fetchone()
    if ref_row is not None and not (ref_row[0] or "").strip():
        ensure_referral_code(chat_id)
    now = int(time.time())
    add_seconds = max(1, days) * 24 * 60 * 60
    cur = _execute(
        "SELECT role, vip_until FROM users WHERE chat_id = ?", (chat_id,)
    )
    row = cur.fetchone()
    if row is None:
        return
    role, vip_until_raw = row[0], int(row[1] or 0)
    if role == "vip" and vip_until_raw > now:
        vip_until = max(now, vip_until_raw) + add_seconds
    else:
        vip_until = now + add_seconds
    _execute(
        "UPDATE users SET role = 'vip', vip_until = ? WHERE chat_id = ?",
        (vip_until, chat_id),
    )


def _vip_payment_row(row: tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "order_id": row[0],
        "chat_id": int(row[1]),
        "plan": row[2],
        "days": int(row[3]),
        "amount_usd": float(row[4]),
        "amount_rub": str(row[5]),
        "payment_id": row[6] or "",
        "pay_url": row[7] or "",
        "status": row[8],
        "created_at": int(row[9] or 0),
        "paid_at": int(row[10]) if row[10] is not None else None,
    }


_VIP_PAYMENT_SELECT = (
    "SELECT order_id, chat_id, plan, days, amount_usd, amount_rub, "
    "payment_id, pay_url, status, created_at, paid_at FROM vip_payments"
)


def create_vip_payment_row(
    *,
    order_id: str,
    chat_id: int,
    plan: str,
    days: int,
    amount_usd: float,
    amount_rub: str,
) -> dict[str, Any]:
    now = int(time.time())
    _execute(
        "INSERT INTO vip_payments "
        "(order_id, chat_id, plan, days, amount_usd, amount_rub, payment_id, "
        "pay_url, status, created_at, paid_at) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, '', 'pending', ?, NULL)",
        (order_id, chat_id, plan, days, float(amount_usd), str(amount_rub), now),
    )
    row = get_vip_payment_by_order(order_id)
    assert row is not None
    return row


def update_vip_payment_provider(
    order_id: str, *, payment_id: str, pay_url: str
) -> None:
    _execute(
        "UPDATE vip_payments SET payment_id = ?, pay_url = ? WHERE order_id = ?",
        (payment_id, pay_url, order_id),
    )


def get_vip_payment_by_order(order_id: str) -> dict[str, Any] | None:
    cur = _execute(f"{_VIP_PAYMENT_SELECT} WHERE order_id = ?", (order_id,))
    return _vip_payment_row(cur.fetchone())


def get_vip_payment_by_payment_id(payment_id: str) -> dict[str, Any] | None:
    pid = (payment_id or "").strip()
    if not pid:
        return None
    cur = _execute(f"{_VIP_PAYMENT_SELECT} WHERE payment_id = ?", (pid,))
    return _vip_payment_row(cur.fetchone())


def mark_vip_payment_status(order_id: str, status: str) -> None:
    _execute(
        "UPDATE vip_payments SET status = ? WHERE order_id = ? AND status = 'pending'",
        (status, order_id),
    )


def mark_vip_payment_paid(
    order_id: str, *, payment_id: str | None = None
) -> bool:
    """Return True if this call transitioned pending → paid."""
    now = int(time.time())
    if payment_id:
        cur = _execute(
            "UPDATE vip_payments SET status = 'paid', paid_at = ?, payment_id = ? "
            "WHERE order_id = ? AND status = 'pending'",
            (now, payment_id, order_id),
        )
    else:
        cur = _execute(
            "UPDATE vip_payments SET status = 'paid', paid_at = ? "
            "WHERE order_id = ? AND status = 'pending'",
            (now, order_id),
        )
    return cur.rowcount > 0


def list_pending_vip_payments(*, limit: int = 40) -> list[dict[str, Any]]:
    cur = _execute(
        f"{_VIP_PAYMENT_SELECT} WHERE status = 'pending' "
        "AND payment_id IS NOT NULL AND payment_id != '' "
        "ORDER BY created_at ASC LIMIT ?",
        (max(1, limit),),
    )
    return [r for r in (_vip_payment_row(row) for row in cur.fetchall()) if r]


def redeem_promo_code(chat_id: int, code: str) -> tuple[str, int | None]:
    _cleanup_used_up_promo_codes()
    promo = _norm_promo_code(code)
    if not promo:
        return "not_found", None

    cur = _execute(
        "SELECT vip_days, is_active, max_uses FROM promo_codes WHERE code = ?",
        (promo,),
    )
    row = cur.fetchone()
    if row is None or int(row[1] or 0) != 1:
        return "not_found", None

    max_uses = int(row[2] or 0)
    if max_uses > 0 and _promo_uses_count(promo) >= max_uses:
        _execute("DELETE FROM promo_codes WHERE code = ?", (promo,))
        return "exhausted", None

    try:
        _execute(
            "INSERT INTO promo_activations (chat_id, code, used_at) VALUES (?, ?, ?)",
            (chat_id, promo, int(time.time())),
        )
    except sqlite3.IntegrityError:
        return "already_used", None

    days = max(1, int(row[0] or 0))
    if max_uses > 0 and _promo_uses_count(promo) >= max_uses:
        _execute("DELETE FROM promo_codes WHERE code = ?", (promo,))
    return "ok", days


def create_promo_code(code: str, *, vip_days: int, max_uses: int) -> bool:
    promo = _norm_promo_code(code)
    if not promo:
        return False
    try:
        _execute(
            "INSERT INTO promo_codes (code, vip_days, max_uses, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (promo, max(1, int(vip_days)), max(0, int(max_uses)), int(time.time())),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def find_users_by_username(username: str, *, limit: int = 10) -> list[dict]:
    un = _norm_username(username)
    if not un:
        return []
    cur = _execute(
        f"SELECT {_USER_SELECT} FROM users WHERE LOWER(username) = LOWER(?) "
        "ORDER BY created_at DESC LIMIT ?",
        (un, max(1, int(limit))),
    )
    return [_row_to_user(row) for row in cur.fetchall()]


def delete_user_completely(chat_id: int) -> bool:
    cur = _execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
    if cur.fetchone() is None:
        return False
    _execute("DELETE FROM seen_ads WHERE chat_id = ?", (chat_id,))
    _execute("DELETE FROM sent_prices WHERE chat_id = ?", (chat_id,))
    _execute("DELETE FROM promo_activations WHERE chat_id = ?", (chat_id,))
    _execute(
        "DELETE FROM referrals WHERE referred_chat_id = ? OR referrer_chat_id = ?",
        (chat_id, chat_id),
    )
    _execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
    return True


def delete_promo_code(code: str) -> bool:
    promo = _norm_promo_code(code)
    if not promo:
        return False
    cur = _execute("SELECT 1 FROM promo_codes WHERE code = ?", (promo,))
    if cur.fetchone() is None:
        return False
    _execute("DELETE FROM promo_activations WHERE code = ?", (promo,))
    _execute("DELETE FROM promo_codes WHERE code = ?", (promo,))
    return True


def list_active_promo_codes() -> list[dict]:
    _cleanup_used_up_promo_codes()
    cur = _execute(
        """
        SELECT p.code, p.vip_days, p.max_uses, p.created_at,
               COALESCE(a.uses, 0) AS uses
        FROM promo_codes p
        LEFT JOIN (
            SELECT code, COUNT(*) AS uses
            FROM promo_activations
            GROUP BY code
        ) a ON a.code = p.code
        WHERE p.is_active = 1
        ORDER BY p.created_at DESC
        """
    )
    rows = []
    for code, vip_days, max_uses, created_at, uses in cur.fetchall():
        rows.append(
            {
                "code": code,
                "vip_days": int(vip_days or 0),
                "max_uses": int(max_uses or 0),
                "uses": int(uses or 0),
                "created_at": int(created_at or 0),
            }
        )
    return rows


def _regular_defaults_sql_values() -> tuple:
    return (
        DEFAULT_MAX_PRICE,
        ",".join(DEFAULT_KEYWORDS),
        _memory_csv(list(DEFAULT_MEMORY_VOLUMES)),
    )


def revoke_vip(chat_id: int) -> None:
    user = get_user(chat_id)
    max_price, _default_kw, _memory = _regular_defaults_sql_values()
    kw_csv, memory = _regular_search_limits_sql((user or {}).get("keywords"))
    _execute(
        "UPDATE users SET role = 'regular', vip_until = 0, vip_feed_mode = 'normal', "
        "max_price = ?, keywords = ?, memory_volumes = ? "
        "WHERE chat_id = ?",
        (max_price, kw_csv, memory, chat_id),
    )


def _vip_expiry_memory_sql() -> str:
    return _memory_csv(list(DEFAULT_MEMORY_VOLUMES))


def expire_all_vip() -> list[int]:
    """Снимает VIP у всех с истёкшим сроком. Возвращает chat_id затронутых пользователей."""
    now = int(time.time())
    cur = _execute(
        "SELECT chat_id, keywords FROM users "
        "WHERE role = 'vip' AND vip_until > 0 AND vip_until < ?",
        (now,),
    )
    rows = cur.fetchall()
    if not rows:
        return []
    expired: list[int] = []
    for row in rows:
        chat_id = int(row[0])
        raw_kw = row[1] or ""
        keywords = [k.strip() for k in raw_kw.split(",") if k.strip()]
        kw_csv, memory = _regular_search_limits_sql(keywords)
        _execute(
            "UPDATE users SET role = 'regular', vip_until = 0, vip_feed_mode = 'normal', "
            "keywords = ?, memory_volumes = ? WHERE chat_id = ?",
            (kw_csv, memory, chat_id),
        )
        expired.append(chat_id)
    return expired


def _promo_uses_count(code: str) -> int:
    cur = _execute(
        "SELECT COUNT(*) FROM promo_activations WHERE code = ?",
        (_norm_promo_code(code),),
    )
    return int(cur.fetchone()[0])


def _cleanup_used_up_promo_codes() -> None:
    _execute(
        """
        DELETE FROM promo_codes
        WHERE max_uses > 0
          AND (
              SELECT COUNT(*)
              FROM promo_activations
              WHERE promo_activations.code = promo_codes.code
          ) >= max_uses
        """
    )
