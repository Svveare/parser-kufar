"""Marketplace layer: types, registry, Kufar adapter."""
import unittest
from unittest.mock import patch

from marketplace.kufar import KufarAdapter
from marketplace.registry import get_adapter
from marketplace.types import CURRENCY_BYN, SOURCE_AVITO, SOURCE_KUFAR


class MarketplaceNormalizeTests(unittest.TestCase):
    def test_normalize_adds_source_and_currency(self) -> None:
        adapter = KufarAdapter()
        raw = {
            "ad_id": 1,
            "subject": "iPhone 15",
            "price_byn": 500,
            "list_time": "2024-01-01T12:00:00Z",
            "ad_link": "https://www.kufar.by/item/1",
            "images": [],
            "account_parameters": [],
            "ad_parameters": [],
        }
        ad = adapter.normalize(raw)
        self.assertIsNotNone(ad)
        assert ad is not None
        self.assertEqual(ad["source"], SOURCE_KUFAR)
        self.assertEqual(ad["currency"], CURRENCY_BYN)
        self.assertEqual(ad["title"], "iPhone 15")


class MarketplaceRegistryTests(unittest.IsolatedAsyncioTestCase):
    def test_get_adapter_kufar(self) -> None:
        adapter = get_adapter(SOURCE_KUFAR)
        self.assertEqual(adapter.source, SOURCE_KUFAR)

    def test_get_adapter_avito(self) -> None:
        adapter = get_adapter(SOURCE_AVITO)
        self.assertEqual(adapter.source, SOURCE_AVITO)

    async def test_avito_fetch_empty_when_disabled(self) -> None:
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch("marketplace.avito.AVITO_ENABLED", False):
            ads = await get_adapter(SOURCE_AVITO).fetch_for_key(key)
        self.assertEqual(ads, [])


if __name__ == "__main__":
    unittest.main()
