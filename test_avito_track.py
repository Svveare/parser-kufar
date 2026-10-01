"""Avito adapter, mock/feed fetch, and poll eligibility."""
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from avito_catalog import live_search_params_from_key, search_params_from_key
from avito_fetch import (
    filter_ads_for_key,
    fetch_feed_ads_for_key,
    fetch_mock_ads_for_key,
    fetch_search_ads_for_key,
    load_feed_snapshot,
    reset_feed_snapshot_for_tests,
)
from avito_live import fetch_live_ads_for_key, parse_live_item
from marketplace.avito import AvitoAdapter
from marketplace.keys import user_is_avito_pollable, user_is_kufar_pollable
from marketplace.registry import get_adapter
from marketplace.types import COUNTRY_RU, SOURCE_AVITO, SOURCE_KUFAR

_FEED_SAMPLE = Path(__file__).resolve().parent / "geo" / "avito_feed_sample.json"
_LIVE_SAMPLE = Path(__file__).resolve().parent / "geo" / "avito_live_sample.json"


class AvitoAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_returns_empty_when_disabled(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch("marketplace.avito.AVITO_ENABLED", False):
            ads = await adapter.fetch_for_key(key)
        self.assertEqual(ads, [])

    async def test_fetch_raises_when_enabled_without_mock_search_or_feed(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch("marketplace.avito.AVITO_ENABLED", True):
            with patch("marketplace.avito.AVITO_DEV_MOCK", False):
                with patch("marketplace.avito.AVITO_SEARCH_URL", ""):
                    with patch("marketplace.avito.AVITO_LIVE_ENABLED", False):
                        with patch("marketplace.avito.AVITO_FEED_URL", ""):
                            with patch("marketplace.avito.AVITO_FEED_FILE", ""):
                                with self.assertRaises(NotImplementedError):
                                    await adapter.fetch_for_key(key)

    async def test_adapter_live_default(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        live_ad = {
            "title": "Apple iPhone 15 256 GB",
            "link": "https://www.avito.ru/moskva/telefony/live_default",
            "price": 72000,
            "source": SOURCE_AVITO,
        }
        with patch("marketplace.avito.AVITO_ENABLED", True):
            with patch("marketplace.avito.AVITO_DEV_MOCK", False):
                with patch("marketplace.avito.AVITO_SEARCH_URL", ""):
                    with patch("marketplace.avito.AVITO_LIVE_ENABLED", True):
                        with patch(
                            "marketplace.avito.fetch_live_ads_for_key",
                            new_callable=AsyncMock,
                            return_value=[live_ad],
                        ) as mock_live:
                            ads = await adapter.fetch_for_key(key)
        self.assertEqual(len(ads), 1)
        mock_live.assert_awaited_once()
        self.assertIn("live_default", ads[0].get("link", ""))

    async def test_adapter_search_priority_over_feed(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        search_ad = {
            "title": "Apple iPhone 15 256 GB",
            "link": "https://www.avito.ru/moskva/telefony/search_priority",
            "price": 70000,
            "source": SOURCE_AVITO,
        }
        with patch("marketplace.avito.AVITO_ENABLED", True):
            with patch("marketplace.avito.AVITO_DEV_MOCK", False):
                with patch(
                    "marketplace.avito.AVITO_SEARCH_URL",
                    "https://example.com/search",
                ):
                    with patch(
                        "marketplace.avito.AVITO_FEED_URL",
                        "https://example.com/feed.json",
                    ):
                        with patch(
                            "marketplace.avito.fetch_search_ads_for_key",
                            new_callable=AsyncMock,
                            return_value=[search_ad],
                        ) as mock_search:
                            with patch(
                                "marketplace.avito.fetch_feed_ads_for_key",
                                new_callable=AsyncMock,
                            ) as mock_feed:
                                ads = await adapter.fetch_for_key(key)
        self.assertEqual(len(ads), 1)
        mock_search.assert_awaited_once()
        mock_feed.assert_not_awaited()
        self.assertIn("search_priority", ads[0].get("link", ""))

    async def test_fetch_mock_returns_moscow_iphone(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch("marketplace.avito.AVITO_ENABLED", True):
            with patch("marketplace.avito.AVITO_DEV_MOCK", True):
                ads = await adapter.fetch_for_key(key)
        self.assertGreaterEqual(len(ads), 1)
        self.assertEqual(ads[0].get("source"), SOURCE_AVITO)
        self.assertIn("iphone 15", ads[0].get("title", "").lower())

    async def test_fetch_feed_from_file(self) -> None:
        adapter = AvitoAdapter()
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        reset_feed_snapshot_for_tests()
        with patch("marketplace.avito.AVITO_ENABLED", True):
            with patch("marketplace.avito.AVITO_DEV_MOCK", False):
                with patch("marketplace.avito.AVITO_SEARCH_URL", ""):
                    with patch("marketplace.avito.AVITO_FEED_URL", ""):
                        with patch("marketplace.avito.AVITO_FEED_FILE", str(_FEED_SAMPLE)):
                            with patch("avito_fetch.AVITO_FEED_FILE", str(_FEED_SAMPLE)):
                                with patch(
                                    "marketplace.avito.fetch_live_ads_for_key",
                                    new_callable=AsyncMock,
                                    return_value=[],
                                ):
                                    ads = await adapter.fetch_for_key(key)
        self.assertEqual(len(ads), 1)
        self.assertIn("iphone 15", ads[0].get("title", "").lower())


class AvitoMockFetchTests(unittest.TestCase):
    def test_mock_geo_mismatch_empty(self) -> None:
        key = (SOURCE_AVITO, "phones", "653430", "653430", ("iphone 15",), ("256",))
        reset_feed_snapshot_for_tests()
        ads = fetch_mock_ads_for_key(key)
        titles = [a["title"].lower() for a in ads]
        self.assertTrue(all("iphone 15" in t for t in titles))
        self.assertFalse(any("galaxy" in t for t in titles))

    def test_mock_spb_galaxy(self) -> None:
        key = (SOURCE_AVITO, "phones", "653240", "653240", ("galaxy",), ("256",))
        reset_feed_snapshot_for_tests()
        ads = fetch_mock_ads_for_key(key)
        self.assertEqual(len(ads), 1)
        self.assertIn("galaxy", ads[0]["title"].lower())


class AvitoFeedFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_feed_snapshot_from_file(self) -> None:
        reset_feed_snapshot_for_tests()
        session = MagicMock()
        with patch("avito_fetch.AVITO_FEED_URL", ""):
            with patch("avito_fetch.AVITO_FEED_FILE", str(_FEED_SAMPLE)):
                items = await load_feed_snapshot(session, force=True)
        self.assertEqual(len(items), 2)

    async def test_filter_ads_for_key_on_feed_items(self) -> None:
        reset_feed_snapshot_for_tests()
        raw = json.loads(_FEED_SAMPLE.read_text(encoding="utf-8"))
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        ads = filter_ads_for_key(raw, key)
        self.assertEqual(len(ads), 1)

    async def test_fetch_feed_http(self) -> None:
        reset_feed_snapshot_for_tests()
        payload = json.loads(_FEED_SAMPLE.read_text(encoding="utf-8"))
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ads": payload})
        mock_resp.text = AsyncMock(return_value="")
        mock_resp.headers = {}

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.get = MagicMock(return_value=mock_get)

        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch("avito_fetch.AVITO_FEED_URL", "https://example.com/feed.json"):
            with patch("avito_fetch.AVITO_FEED_FILE", ""):
                ads = await fetch_feed_ads_for_key(key, session)
        self.assertEqual(len(ads), 1)


class AvitoCatalogTests(unittest.TestCase):
    def test_search_params_from_key_moscow_phones(self) -> None:
        key = (
            SOURCE_AVITO,
            "phones",
            "637640",
            "637640",
            ("iphone 15", "iphone 15 pro"),
            ("256",),
        )
        params = search_params_from_key(key)
        self.assertEqual(
            params,
            {
                "city_id": "637640",
                "region_id": "637640",
                "category": "phones",
                "models": "iphone 15,iphone 15 pro",
                "memory_gb": "256",
            },
        )

    def test_search_params_from_key_laptops_no_memory(self) -> None:
        key = (SOURCE_AVITO, "laptops", "637640", "637640", ("macbook air",), ())
        params = search_params_from_key(key)
        self.assertEqual(
            params,
            {
                "city_id": "637640",
                "region_id": "637640",
                "category": "laptops",
                "models": "macbook air",
            },
        )

    def test_search_params_from_key_no_models(self) -> None:
        key = (SOURCE_AVITO, "phones", "637640", "637640", (), ("256",))
        self.assertIsNone(search_params_from_key(key))


    def test_live_search_params_from_key(self) -> None:
        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        params = live_search_params_from_key(key)
        self.assertEqual(
            params,
            {
                "locationId": "637640",
                "categoryId": "110",
                "q": "iphone 15",
                "page": "1",
                "limit": "50",
                "presentationType": "full",
            },
        )

    def test_parse_live_item(self) -> None:
        raw = {
            "id": 42,
            "title": "Apple iPhone 15 256 GB",
            "url": "/moskva/telefony/test_live",
            "priceDetailed": {"value": 75000},
            "description": "Тест",
            "geo": {"formattedAddress": "Москва"},
        }
        parsed = parse_live_item(
            raw,
            city_id="637640",
            region_id="637640",
            category="phones",
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "Apple iPhone 15 256 GB")
        self.assertIn("avito.ru", parsed["url"])


class AvitoLiveFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_live_ads_for_key(self) -> None:
        payload = json.loads(_LIVE_SAMPLE.read_text(encoding="utf-8"))
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=payload)
        mock_resp.text = AsyncMock(return_value="")
        mock_resp.headers = {}

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.get = MagicMock(return_value=mock_get)

        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        ads = await fetch_live_ads_for_key(key, session)
        self.assertEqual(len(ads), 1)
        self.assertIn("iphone 15", ads[0]["title"].lower())

    async def test_fetch_live_ads_queries_each_selected_model(self) -> None:
        payload = json.loads(_LIVE_SAMPLE.read_text(encoding="utf-8"))
        parsed_items = [
            parse_live_item(
                item,
                city_id="637640",
                region_id="637640",
                category="phones",
            )
            for item in payload["ads"]
        ]
        key = (
            SOURCE_AVITO,
            "phones",
            "637640",
            "637640",
            ("iphone 15", "galaxy s24"),
            ("256",),
        )
        with patch(
            "avito_live._fetch_live_http",
            new_callable=AsyncMock,
            side_effect=[parsed_items[:1], parsed_items[1:]],
        ) as mock_fetch:
            ads = await fetch_live_ads_for_key(key, MagicMock())
        self.assertEqual(len(ads), 2)
        self.assertEqual(mock_fetch.await_count, 2)
        requested_models = {
            call.args[1]["q"] for call in mock_fetch.await_args_list
        }
        self.assertEqual(requested_models, {"iphone 15", "galaxy s24"})


class AvitoSearchFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_search_http(self) -> None:
        reset_feed_snapshot_for_tests()
        payload = json.loads(_FEED_SAMPLE.read_text(encoding="utf-8"))
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ads": payload})
        mock_resp.text = AsyncMock(return_value="")
        mock_resp.headers = {}

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.get = MagicMock(return_value=mock_get)

        key = (SOURCE_AVITO, "phones", "637640", "637640", ("iphone 15",), ("256",))
        with patch(
            "avito_fetch.AVITO_SEARCH_URL",
            "https://example.com/avito/search",
        ):
            ads = await fetch_search_ads_for_key(key, session)
        self.assertEqual(len(ads), 2)
        session.get.assert_called_once()
        call_kwargs = session.get.call_args
        self.assertEqual(call_kwargs[0][0], "https://example.com/avito/search")
        self.assertEqual(call_kwargs[1]["params"]["city_id"], "637640")
        self.assertEqual(call_kwargs[1]["params"]["models"], "iphone 15")
        self.assertEqual(call_kwargs[1]["params"]["memory_gb"], "256")


class AvitoRegistryTests(unittest.TestCase):
    def test_get_adapter_avito(self) -> None:
        adapter = get_adapter(SOURCE_AVITO)
        self.assertEqual(adapter.source, SOURCE_AVITO)

    def test_user_is_kufar_pollable(self) -> None:
        user = {"country": "by", "primary_source": "kufar"}
        self.assertTrue(user_is_kufar_pollable(user))
        self.assertFalse(user_is_avito_pollable(user))

    def test_user_is_avito_pollable_requires_enabled_and_city(self) -> None:
        user = {
            "country": COUNTRY_RU,
            "primary_source": SOURCE_AVITO,
            "avito_city_id": "637640",
        }
        with patch("marketplace.keys.AVITO_ENABLED", False):
            self.assertFalse(user_is_avito_pollable(user))
        with patch("marketplace.keys.AVITO_ENABLED", True):
            self.assertTrue(user_is_avito_pollable(user))


if __name__ == "__main__":
    unittest.main()
