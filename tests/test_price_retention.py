"""Тесты retention таблиц цен (market_prices, sent_prices)."""
import importlib
import os
import sqlite3
import tempfile
import time
import unittest

import config
import db


def _reload_db(path: str) -> None:
    os.environ["DB_PATH"] = path
    importlib.reload(config)
    try:
        db.close()
    except (sqlite3.Error, AttributeError):
        pass
    importlib.reload(db)
    db.init_db()


class PriceRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmpdir.name, "test.db")
        _reload_db(self._db_path)

    def tearDown(self) -> None:
        try:
            db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()
        os.environ.pop("DB_PATH", None)
        importlib.reload(config)
        importlib.reload(db)

    def test_prune_removes_old_market_prices(self) -> None:
        old_ts = int(time.time()) - 20 * 86400
        fresh_ts = int(time.time())
        db._execute(
            "INSERT INTO market_prices (link, device_key, price, sent_at) "
            "VALUES (?, ?, ?, ?)",
            ("https://kufar.by/old", "iphone|15", 100, old_ts),
        )
        db._execute(
            "INSERT INTO market_prices (link, device_key, price, sent_at) "
            "VALUES (?, ?, ?, ?)",
            ("https://kufar.by/new", "iphone|15", 200, fresh_ts),
        )
        deleted = db.prune_price_tables(14)
        self.assertEqual(deleted[0], 1)
        avg = db.avg_market_price("iphone|15")
        self.assertEqual(avg, 200)

    def test_avg_ignores_stale_without_prune(self) -> None:
        old_ts = int(time.time()) - 20 * 86400
        fresh_ts = int(time.time())
        db._execute(
            "INSERT INTO market_prices (link, device_key, price, sent_at) "
            "VALUES (?, ?, ?, ?)",
            ("https://kufar.by/a", "samsung|s24", 300, old_ts),
        )
        db._execute(
            "INSERT INTO market_prices (link, device_key, price, sent_at) "
            "VALUES (?, ?, ?, ?)",
            ("https://kufar.by/b", "samsung|s24", 500, fresh_ts),
        )
        avg = db.avg_market_price("samsung|s24")
        self.assertEqual(avg, 500)

    def test_prune_sent_prices(self) -> None:
        old_ts = int(time.time()) - 30 * 86400
        db._execute(
            "INSERT INTO sent_prices (chat_id, link, device_key, price, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "https://kufar.by/x", "iphone|14", 50, old_ts),
        )
        deleted = db.prune_price_tables(14)
        self.assertEqual(deleted[1], 1)
        cur = db._execute("SELECT COUNT(*) FROM sent_prices")
        self.assertEqual(int(cur.fetchone()[0]), 0)


if __name__ == "__main__":
    unittest.main()
