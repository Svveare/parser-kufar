"""Тесты спринта 2: пагинация Kufar, prune seen_ads, poll timestamps."""
import importlib
import os
import sqlite3
import tempfile
import time
import unittest

import config
import db
from kufar_fetch import _next_page_cursor


def _reload_db(path: str) -> None:
    os.environ["DB_PATH"] = path
    importlib.reload(config)
    try:
        db.close()
    except (sqlite3.Error, AttributeError):
        pass
    importlib.reload(db)
    db.init_db()


class Sprint2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        _reload_db(os.path.join(self._tmpdir.name, "test.db"))

    def tearDown(self) -> None:
        try:
            db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()
        os.environ.pop("DB_PATH", None)
        importlib.reload(config)
        importlib.reload(db)

    def test_next_page_cursor(self) -> None:
        data = {
            "pagination": {
                "pages": [
                    {"label": "self", "token": None},
                    {"label": "next", "token": "abc123"},
                ]
            }
        }
        self.assertEqual(_next_page_cursor(data), "abc123")
        self.assertIsNone(_next_page_cursor({"pagination": {"pages": []}}))

    def test_prune_seen_ads(self) -> None:
        old_ts = int(time.time()) - 100 * 86400
        db._execute(
            "INSERT INTO seen_ads (chat_id, link, seen_at) VALUES (?, ?, ?)",
            (1, "https://kufar.by/old", old_ts),
        )
        db._execute(
            "INSERT INTO seen_ads (chat_id, link, seen_at) VALUES (?, ?, ?)",
            (1, "https://kufar.by/new", int(time.time())),
        )
        deleted = db.prune_seen_ads(90)
        self.assertEqual(deleted, 1)
        cur = db._execute("SELECT link FROM seen_ads WHERE chat_id = 1")
        links = {row[0] for row in cur.fetchall()}
        self.assertEqual(links, {"https://kufar.by/new"})

    def test_new_user_empty_keywords_phones_category(self) -> None:
        db.add_user(7, username="u")
        user = db.get_user(7)
        assert user is not None
        self.assertEqual(user["product_category"], "phones")
        self.assertEqual(user["keywords"], [])

    def test_update_product_category_resets_keywords(self) -> None:
        db.add_user(8, username="u")
        db.set_vip(8, days=7)
        db.update_keywords(8, ["iphone 15", "iphone 16"])
        user = db.get_user(8)
        assert user is not None
        self.assertEqual(user["keywords"], ["iphone 15", "iphone 16"])
        db.update_product_category(8, "watches")
        user = db.get_user(8)
        assert user is not None
        self.assertEqual(user["product_category"], "watches")
        self.assertEqual(user["keywords"], [])

    def test_poll_last_run_columns(self) -> None:
        db.add_user(42, username="u")
        db.set_poll_last_run(42, is_vip=True)
        user = db.get_user(42)
        assert user is not None
        self.assertGreater(user["poll_last_vip"], 0)
        self.assertEqual(user["poll_last_regular"], 0)
        db.set_poll_last_run(42, is_vip=False)
        user = db.get_user(42)
        assert user is not None
        self.assertGreater(user["poll_last_regular"], 0)


if __name__ == "__main__":
    unittest.main()
