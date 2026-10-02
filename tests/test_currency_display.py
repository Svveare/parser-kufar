"""Тройное отображение цен."""
import math
import unittest
from unittest.mock import patch

from currency_display import (
    format_triple_price,
    format_vip_checkout_price,
    format_vip_plan_price,
)
from marketplace.types import COUNTRY_BY, COUNTRY_RU


class CurrencyDisplayTests(unittest.TestCase):
    def test_by_order_byn_usd_rub(self) -> None:
        text = format_triple_price(1000, country=COUNTRY_BY, price_usd_hint=320)
        self.assertTrue(text.startswith("1 000 Br"))
        self.assertIn("≈ 320$", text)
        self.assertIn("₽", text)

    def test_by_usd_fallback_without_hint(self) -> None:
        text = format_triple_price(1000, country=COUNTRY_BY)
        self.assertIn("Br", text)
        self.assertIn("$", text)
        self.assertIn("₽", text)

    def test_ru_order_rub_byn_usd(self) -> None:
        text = format_triple_price(100_000, country=COUNTRY_RU)
        self.assertTrue(text.endswith("$"))
        self.assertIn("₽", text.split("·")[0])
        self.assertIn("Br", text)

    def test_rounding(self) -> None:
        text = format_triple_price(5000, country=COUNTRY_BY, price_usd_hint=1600)
        self.assertIn("5 000 Br", text)
        self.assertIn("≈ 1600$", text)

    def test_converts_ceil_not_round_half(self) -> None:
        with patch("currency_display.BYN_TO_RUB", 28.1):
            text = format_triple_price(10, country=COUNTRY_BY, price_usd_hint=3)
        self.assertIn("≈ 281 ₽", text)
        with patch("currency_display.BYN_TO_RUB", 28.01):
            text = format_triple_price(10, country=COUNTRY_BY, price_usd_hint=3)
        self.assertIn("≈ 281 ₽", text)
        self.assertEqual(math.ceil(10 * 28.01), 281)

    def test_zero_is_negotiable(self) -> None:
        self.assertEqual(format_triple_price(0, country=COUNTRY_BY), "договорная")
        self.assertEqual(format_triple_price(-1, country=COUNTRY_RU), "договорная")

    def test_vip_plan_by_leads_with_byn(self) -> None:
        text = format_vip_plan_price(3, country=COUNTRY_BY)
        self.assertTrue(text.startswith("≈ "))
        self.assertIn("Br", text.split("·")[0])
        self.assertIn("$3", text)
        self.assertIn("₽", text)

    def test_vip_plan_ru_leads_with_rub(self) -> None:
        text = format_vip_plan_price(3, country=COUNTRY_RU)
        self.assertIn("₽", text.split("·")[0])
        self.assertIn("$3", text)

    def test_vip_checkout_by(self) -> None:
        text = format_vip_checkout_price(3, "271.50", country=COUNTRY_BY)
        self.assertIn("Br", text.split("·")[0])
        self.assertIn("$3", text)
        self.assertIn("271.5 ₽", text)


if __name__ == "__main__":
    unittest.main()
