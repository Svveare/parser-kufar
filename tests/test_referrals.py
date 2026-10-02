"""Тесты реферальной системы (in-memory SQLite)."""
import importlib
import os
import sqlite3
import tempfile
import unittest

import config
import db
from config import REFERRAL_VIP_DAYS_PER_FRIEND


def _reload_db(path: str) -> None:
    os.environ["DB_PATH"] = path
    importlib.reload(config)
    try:
        db.close()
    except (sqlite3.Error, AttributeError):
        pass
    importlib.reload(db)
    db.init_db()


class ReferralTests(unittest.TestCase):
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

    def test_new_friend_grants_vip_to_referrer(self) -> None:
        db.add_user(100, username="alice")
        referrer = db.get_user(100)
        assert referrer is not None
        code = referrer["referral_code"]
        self.assertTrue(db.add_user(200, username="bob"))
        self.assertEqual(db.process_referral_signup(200, code), 100)
        self.assertEqual(db.count_referrals(100), 1)
        friend = db.get_user(200)
        assert friend is not None
        self.assertEqual(friend["referred_by"], 100)
        updated = db.get_user(100)
        assert updated is not None
        self.assertEqual(updated["role"], "vip")
        self.assertGreater(int(updated["vip_until"]), 0)

    def test_repeat_signup_no_double_bonus(self) -> None:
        db.add_user(100)
        code = db.get_user(100)["referral_code"]  # type: ignore[index]
        db.add_user(200)
        self.assertEqual(db.process_referral_signup(200, code), 100)
        self.assertIsNone(db.process_referral_signup(200, code))
        self.assertEqual(db.count_referrals(100), 1)

    def test_self_referral_rejected(self) -> None:
        db.add_user(100)
        code = db.get_user(100)["referral_code"]  # type: ignore[index]
        self.assertIsNone(db.process_referral_signup(100, code))
        self.assertEqual(db.count_referrals(100), 0)

    def test_invalid_code(self) -> None:
        db.add_user(100)
        db.add_user(200)
        self.assertIsNone(db.process_referral_signup(200, "NO_SUCH_CODE"))
        self.assertEqual(db.count_referrals(100), 0)

    def test_grant_vip_days_extends_existing(self) -> None:
        db.add_user(100)
        db.set_vip(100, days=5)
        before = int(db.get_user(100)["vip_until"])  # type: ignore[index]
        db.grant_vip_days(100, REFERRAL_VIP_DAYS_PER_FRIEND)
        after = int(db.get_user(100)["vip_until"])  # type: ignore[index]
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
