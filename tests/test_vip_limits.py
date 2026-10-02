"""Regular keyword/memory limits and VIP demotion trim."""
from __future__ import annotations

import os
import tempfile
import time
import unittest

import db
from config import REGULAR_MAX_KEYWORDS


class VipDemotionLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.SQLITE_PATH
        path = os.path.join(self._tmp.name, "test.db")
        db.SQLITE_PATH = path
        db.conn = db._connect()
        db.init_db()
        self.chat_id = 880011
        db.add_user(self.chat_id)

    def tearDown(self) -> None:
        db.conn.close()
        db.SQLITE_PATH = self._old_path
        db.conn = db._connect()
        self._tmp.cleanup()

    def test_regular_max_keywords_is_one(self) -> None:
        self.assertEqual(REGULAR_MAX_KEYWORDS, 1)

    def test_revoke_vip_trims_keywords_and_memory(self) -> None:
        db.set_vip(self.chat_id, days=30)
        db.update_keywords(
            self.chat_id, ["iphone 15", "iphone 14", "iphone 13"]
        )
        db.update_memory_volumes(self.chat_id, ["128", "256"])
        db.revoke_vip(self.chat_id)
        user = db.get_user(self.chat_id)
        assert user is not None
        self.assertEqual(user["role"], "regular")
        self.assertEqual(len(user["keywords"]), 1)
        self.assertEqual(user["keywords"][0], "iphone 15")
        self.assertEqual(user["memory_volumes"], ["64"])

    def test_expire_all_vip_trims_keywords(self) -> None:
        db.set_vip(self.chat_id, days=30)
        db.update_keywords(self.chat_id, ["iphone 15", "iphone 14"])
        db.update_memory_volumes(self.chat_id, ["256", "512"])
        past = int(time.time()) - 10
        db._execute(
            "UPDATE users SET vip_until = ? WHERE chat_id = ?",
            (past, self.chat_id),
        )
        expired = db.expire_all_vip()
        self.assertIn(self.chat_id, expired)
        user = db.get_user(self.chat_id)
        assert user is not None
        self.assertEqual(user["role"], "regular")
        self.assertEqual(user["keywords"], ["iphone 15"])
        self.assertEqual(user["memory_volumes"], ["64"])

    def test_get_user_normalizes_regular_over_limit(self) -> None:
        db.update_keywords(self.chat_id, ["iphone 15", "iphone 14"])
        db._execute(
            "UPDATE users SET memory_volumes = ? WHERE chat_id = ?",
            ("128,256", self.chat_id),
        )
        user = db.get_user(self.chat_id)
        assert user is not None
        self.assertEqual(user["keywords"], ["iphone 15"])
        self.assertEqual(user["memory_volumes"], ["64"])


if __name__ == "__main__":
    unittest.main()
