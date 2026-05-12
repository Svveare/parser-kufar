import sqlite3
import time
from typing import Optional

from config import DEFAULT_MAX_PRICE, DEFAULT_KEYWORDS, VIP_SUBSCRIPTION_DAYS

DB_PATH = "bot.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


conn = _connect()


def _table_columns(name: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({name})")
    return {row[1] for row in cur.fetchall()}


def init_db() -> None:
    # Старая схема (с прошлых экспериментов) — сносим, чтобы создать заново
    existing = _table_columns("users")
    if existing and "active" not in existing:
        conn.execute("DROP TABLE users")

    conn.execute("DROP TABLE IF EXISTS ads")  # legacy

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id    INTEGER PRIMARY KEY,
            active     INTEGER NOT NULL DEFAULT 1,
            role       TEXT    NOT NULL DEFAULT 'regular',
            vip_until  INTEGER NOT NULL DEFAULT 0,
            max_price  INTEGER NOT NULL,
            keywords   TEXT    NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
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

        CREATE INDEX IF NOT EXISTS idx_seen_chat ON seen_ads(chat_id);
        CREATE INDEX IF NOT EXISTS idx_sent_prices_lookup ON sent_prices(chat_id, device_key);
        CREATE INDEX IF NOT EXISTS idx_market_prices_device ON market_prices(device_key);
        """
    )
    cols = _table_columns("users")
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'regular'")
    if "vip_until" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN vip_until INTEGER NOT NULL DEFAULT 0")


def add_user(chat_id: int) -> bool:
    """Добавить пользователя или реактивировать. True если это новый юзер."""
    cur = conn.execute("SELECT active FROM users WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (chat_id, active, role, vip_until, max_price, keywords, created_at) "
            "VALUES (?, 1, 'regular', 0, ?, ?, ?)",
            (
                chat_id,
                DEFAULT_MAX_PRICE,
                ",".join(DEFAULT_KEYWORDS),
                int(time.time()),
            ),
        )
        return True
    if row[0] == 0:
        conn.execute("UPDATE users SET active = 1 WHERE chat_id = ?", (chat_id,))
    return False


def set_active(chat_id: int, active: bool) -> None:
    conn.execute(
        "UPDATE users SET active = ? WHERE chat_id = ?",
        (1 if active else 0, chat_id),
    )


def get_user(chat_id: int) -> Optional[dict]:
    _expire_vip(chat_id)
    cur = conn.execute(
        "SELECT chat_id, active, role, vip_until, max_price, keywords, sent_count, created_at "
        "FROM users WHERE chat_id = ?",
        (chat_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "chat_id": row[0],
        "active": bool(row[1]),
        "role": row[2],
        "vip_until": int(row[3] or 0),
        "max_price": row[4],
        "keywords": [k.strip() for k in row[5].split(",") if k.strip()],
        "sent_count": row[6],
        "created_at": row[7],
    }


def count_users_total() -> int:
    cur = conn.execute("SELECT COUNT(*) FROM users")
    return int(cur.fetchone()[0])


def count_users_active() -> int:
    cur = conn.execute("SELECT COUNT(*) FROM users WHERE active = 1")
    return int(cur.fetchone()[0])


def count_users_vip() -> int:
    now = int(time.time())
    cur = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'vip' AND vip_until > ?",
        (now,),
    )
    return int(cur.fetchone()[0])


def list_users_page(*, offset: int, limit: int) -> list[dict]:
    cur = conn.execute(
        "SELECT chat_id, active, role, vip_until, max_price, keywords, sent_count, created_at "
        "FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            {
                "chat_id": r[0],
                "active": bool(r[1]),
                "role": r[2],
                "vip_until": int(r[3] or 0),
                "max_price": r[4],
                "keywords": [k.strip() for k in r[5].split(",") if k.strip()],
                "sent_count": r[6],
                "created_at": r[7],
            }
        )
    return rows


def clear_market_prices() -> int:
    cur = conn.execute("DELETE FROM market_prices")
    return cur.rowcount if cur.rowcount is not None else 0


def get_active_users() -> list[dict]:
    _expire_all_vip()
    cur = conn.execute(
        "SELECT chat_id, active, role, vip_until, max_price, keywords, sent_count, created_at "
        "FROM users WHERE active = 1"
    )
    return [
        {
            "chat_id": r[0],
            "active": bool(r[1]),
            "role": r[2],
            "vip_until": int(r[3] or 0),
            "max_price": r[4],
            "keywords": [k.strip() for k in r[5].split(",") if k.strip()],
            "sent_count": r[6],
            "created_at": r[7],
        }
        for r in cur.fetchall()
    ]


def update_max_price(chat_id: int, max_price: int) -> None:
    conn.execute(
        "UPDATE users SET max_price = ? WHERE chat_id = ?",
        (max_price, chat_id),
    )


def update_keywords(chat_id: int, keywords: list[str]) -> None:
    cleaned = [k.strip().lower() for k in keywords if k.strip()]
    conn.execute(
        "UPDATE users SET keywords = ? WHERE chat_id = ?",
        (",".join(cleaned), chat_id),
    )


def is_seen(chat_id: int, link: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM seen_ads WHERE chat_id = ? AND link = ?",
        (chat_id, link),
    )
    return cur.fetchone() is not None


def mark_seen(chat_id: int, link: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_ads (chat_id, link, seen_at) VALUES (?, ?, ?)",
        (chat_id, link, int(time.time())),
    )


def count_seen(chat_id: int) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM seen_ads WHERE chat_id = ?", (chat_id,))
    return int(cur.fetchone()[0])


def increment_sent(chat_id: int) -> None:
    conn.execute(
        "UPDATE users SET sent_count = sent_count + 1 WHERE chat_id = ?",
        (chat_id,),
    )


def save_sent_price(chat_id: int, link: str, device_key: str, price: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sent_prices (chat_id, link, device_key, price, sent_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, link, device_key, price, int(time.time())),
    )


def avg_sent_price(chat_id: int, device_key: str) -> int | None:
    cur = conn.execute(
        "SELECT AVG(price) FROM sent_prices WHERE chat_id = ? AND device_key = ?",
        (chat_id, device_key),
    )
    row = cur.fetchone()
    avg_value = row[0] if row else None
    if avg_value is None:
        return None
    return int(avg_value)


def save_market_price(link: str, device_key: str, price: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO market_prices (link, device_key, price, sent_at) "
        "VALUES (?, ?, ?, ?)",
        (link, device_key, price, int(time.time())),
    )


def avg_market_price(device_key: str) -> int | None:
    cur = conn.execute(
        "SELECT AVG(price) FROM market_prices WHERE device_key = ?",
        (device_key,),
    )
    row = cur.fetchone()
    avg_value = row[0] if row else None
    if avg_value is None:
        return None
    return int(avg_value)


def close() -> None:
    conn.close()


def set_vip(chat_id: int, *, days: int = VIP_SUBSCRIPTION_DAYS) -> None:
    now = int(time.time())
    add_seconds = max(1, days) * 24 * 60 * 60
    cur = conn.execute(
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
    conn.execute(
        "UPDATE users SET role = 'vip', vip_until = ? WHERE chat_id = ?",
        (vip_until, chat_id),
    )


def revoke_vip(chat_id: int) -> None:
    conn.execute(
        "UPDATE users SET role = 'regular', vip_until = 0 WHERE chat_id = ?",
        (chat_id,),
    )


def _expire_vip(chat_id: int) -> None:
    now = int(time.time())
    conn.execute(
        "UPDATE users SET role = 'regular', vip_until = 0 "
        "WHERE chat_id = ? AND role = 'vip' AND vip_until > 0 AND vip_until < ?",
        (chat_id, now),
    )


def _expire_all_vip() -> None:
    now = int(time.time())
    conn.execute(
        "UPDATE users SET role = 'regular', vip_until = 0 "
        "WHERE role = 'vip' AND vip_until > 0 AND vip_until < ?",
        (now,),
    )
