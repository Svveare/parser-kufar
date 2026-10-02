"""Формат карточки объявления."""
import unittest

from formatter import format_ad


class FormatAdTests(unittest.TestCase):
    def _sample_ad(self) -> dict:
        return {
            "title": "iPhone 15 256",
            "price": 5000,
            "price_usd": 1600,
            "location": "Минск",
            "summary": "256 GB",
            "description": "x" * 200,
            "link": "https://www.kufar.by/item/1",
            "list_time": "2024-08-24T10:49:00Z",
        }

    def test_compact_hides_description_and_date(self) -> None:
        ad = self._sample_ad()
        text = format_ad(ad, compact=True, country="by")
        self.assertNotIn("Опубликовано", text)
        self.assertIn("iPhone 15", text)
        self.assertNotIn("x" * 20, text)

    def test_vip_shows_date_and_description(self) -> None:
        ad = self._sample_ad()
        text = format_ad(ad, compact=False, country="by")
        self.assertIn("Опубликовано", text)
        self.assertIn("xxx", text)

    def test_triple_price_in_card(self) -> None:
        ad = self._sample_ad()
        text = format_ad(ad, compact=True, country="by")
        self.assertIn("Br", text)
        self.assertIn("$", text)
        self.assertIn("₽", text)

    def test_market_avg_triple(self) -> None:
        ad = self._sample_ad()
        text = format_ad(
            ad,
            market_avg_price=4200,
            compact=False,
            country="by",
        )
        self.assertIn("Средняя", text)
        self.assertIn("4 200 Br", text)

    def test_zero_price_is_negotiable(self) -> None:
        ad = self._sample_ad()
        ad["price"] = 0
        text = format_ad(ad, compact=True, country="by")
        self.assertIn("договорная", text)
        self.assertNotIn("≈ 1$", text)

    def test_missing_price_is_negotiable(self) -> None:
        ad = self._sample_ad()
        ad["price"] = None
        text = format_ad(ad, compact=True, country="by")
        self.assertIn("договорная", text)


if __name__ == "__main__":
    unittest.main()
