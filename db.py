import sqlite3
import time
from typing import Optional

from config import DEFAULT_MAX_PRICE, DEFAULT_KEYWORDS

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

        CREATE INDEX IF NOT EXISTS idx_seen_chat ON seen_ads(chat_id);
        """
    )


def add_user(chat_id: int) -> bool:
    """Добавить пользователя или реактивировать. True если это новый юзер."""
    cur = conn.execute("SELECT active FROM users WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (chat_id, active, max_price, keywords, created_at) "
            "VALUES (?, 1, ?, ?, ?)",
            (chat_id, DEFAULT_MAX_PRICE, ",".join(DEFAULT_KEYWORDS), int(time.time())),
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
    cur = conn.execute(
        "SELECT chat_id, active, max_price, keywords, sent_count, created_at "
        "FROM users WHERE chat_id = ?",
        (chat_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "chat_id": row[0],
        "active": bool(row[1]),
        "max_price": row[2],
        "keywords": [k.strip() for k in row[3].split(",") if k.strip()],
        "sent_count": row[4],
        "created_at": row[5],
    }


def get_active_users() -> list[dict]:
    cur = conn.execute(
        "SELECT chat_id, active, max_price, keywords, sent_count, created_at "
        "FROM users WHERE active = 1"
    )
    return [
        {
            "chat_id": r[0],
            "active": bool(r[1]),
            "max_price": r[2],
            "keywords": [k.strip() for k in r[3].split(",") if k.strip()],
            "sent_count": r[4],
            "created_at": r[5],
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


def close() -> None:
    conn.close()
