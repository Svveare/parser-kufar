"""RollyPay webhook signature and VIP payment DB flow."""
from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
import time
import unittest
from decimal import Decimal

import db
from config import get_vip_plan
from payments.fulfillment import fulfill_vip_payment, usd_to_rub_amount
from payments.rollypay import format_amount_rub, verify_webhook_signature


class RollyPaySignatureTests(unittest.TestCase):
    def test_verify_ok(self) -> None:
        secret = "test-secret"
        body = b'{"event":"payment.paid","order_id":"x"}'
        ts = str(int(time.time()))
        sig = hmac.new(
            secret.encode(), ts.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(
            verify_webhook_signature(body, ts, sig, signing_secret=secret)
        )

    def test_verify_bad_sig(self) -> None:
        secret = "test-secret"
        body = b"{}"
        ts = str(int(time.time()))
        self.assertFalse(
            verify_webhook_signature(body, ts, "deadbeef", signing_secret=secret)
        )

    def test_verify_stale_timestamp(self) -> None:
        secret = "test-secret"
        body = b"{}"
        ts = str(int(time.time()) - 10_000)
        sig = hmac.new(
            secret.encode(), ts.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertFalse(
            verify_webhook_signature(body, ts, sig, signing_secret=secret)
        )


class VipPlanTests(unittest.TestCase):
    def test_plans(self) -> None:
        self.assertEqual(get_vip_plan("week"), {"days": 7, "usd": 1})
        self.assertEqual(get_vip_plan("month"), {"days": 30, "usd": 3})
        self.assertEqual(get_vip_plan("quarter"), {"days": 90, "usd": 7})
        self.assertIsNone(get_vip_plan("nope"))

    def test_usd_to_rub(self) -> None:
        self.assertEqual(usd_to_rub_amount(3, Decimal("90.5")), Decimal("271.50"))

    def test_format_amount(self) -> None:
        self.assertEqual(format_amount_rub("10.5"), "10.50")


class VipPaymentDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.SQLITE_PATH
        path = os.path.join(self._tmp.name, "test.db")
        db.SQLITE_PATH = path
        db.conn = db._connect()
        db.init_db()
        self.chat_id = 900001
        db.add_user(self.chat_id)

    def tearDown(self) -> None:
        db.conn.close()
        db.SQLITE_PATH = self._old_path
        db.conn = db._connect()
        self._tmp.cleanup()

    def test_idempotent_fulfill(self) -> None:
        order_id = "vip_900001_week_1"
        db.create_vip_payment_row(
            order_id=order_id,
            chat_id=self.chat_id,
            plan="week",
            days=7,
            amount_usd=1.0,
            amount_rub="90.00",
        )
        db.update_vip_payment_provider(
            order_id, payment_id="pay-1", pay_url="https://pay.example/1"
        )
        first = fulfill_vip_payment(order_id=order_id, payment_id="pay-1")
        self.assertIsNotNone(first)
        user = db.get_user(self.chat_id)
        assert user is not None
        self.assertEqual(user["role"], "vip")
        second = fulfill_vip_payment(order_id=order_id, payment_id="pay-1")
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
