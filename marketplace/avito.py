"""Адаптер Avito — mock, search API, live fetch, JSON feed."""
from __future__ import annotations

import logging

import aiohttp

from avito_fetch import (
    AVITO_HTTP_HEADERS,
    fetch_feed_ads_for_key,
    fetch_mock_ads_for_key,
    fetch_search_ads_for_key,
)
from avito_live import fetch_live_ads_for_key
from config import (
    AVITO_DEV_MOCK,
    AVITO_ENABLED,
    AVITO_FEED_FILE,
    AVITO_FEED_URL,
    AVITO_LIVE_ENABLED,
    AVITO_SEARCH_URL,
)
from marketplace.keys import FetchKey
from marketplace.types import CURRENCY_RUB, NormalizedAd, SOURCE_AVITO

log = logging.getLogger(__name__)


class AvitoAdapter:
    source = SOURCE_AVITO

    def normalize(self, raw: dict) -> NormalizedAd | None:
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title") or raw.get("subject") or "").strip()
        link = str(raw.get("link") or raw.get("url") or "").strip()
        if not title or not link:
            return None
        price = raw.get("price")
        if price is not None:
            try:
                price = int(price)
            except (TypeError, ValueError):
                price = None
        ad: dict = {
            "title": title,
            "link": link.split("?")[0],
            "price": price,
            "location": str(raw.get("location") or "").strip(),
            "summary": str(raw.get("summary") or "").strip(),
            "description": str(raw.get("description") or "").strip(),
            "photo_urls": list(raw.get("photo_urls") or raw.get("images") or []),
            "list_time": raw.get("list_time") or raw.get("published_at"),
            "source": SOURCE_AVITO,
            "currency": CURRENCY_RUB,
        }
        if raw.get("region_id"):
            ad["region_id"] = str(raw.get("region_id"))
        if raw.get("city_id"):
            ad["city_id"] = str(raw.get("city_id"))
        return NormalizedAd(ad)

    async def fetch_for_key(
        self,
        key: FetchKey,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> list[NormalizedAd]:
        if not AVITO_ENABLED:
            log.debug("avito fetch skipped — AVITO_ENABLED=false key=%s", key[:4])
            return []
        if AVITO_DEV_MOCK:
            return [NormalizedAd(ad) for ad in fetch_mock_ads_for_key(key)]
        if AVITO_SEARCH_URL:
            async def _run_search(sess: aiohttp.ClientSession) -> list[NormalizedAd]:
                ads = await fetch_search_ads_for_key(key, sess)
                return [NormalizedAd(ad) for ad in ads]

            if session is not None:
                return await _run_search(session)
            connector = aiohttp.TCPConnector(limit=4)
            async with aiohttp.ClientSession(
                headers=AVITO_HTTP_HEADERS, connector=connector
            ) as own:
                return await _run_search(own)
        if AVITO_LIVE_ENABLED:
            async def _run_live(sess: aiohttp.ClientSession) -> list[NormalizedAd]:
                ads = await fetch_live_ads_for_key(key, sess)
                return [NormalizedAd(ad) for ad in ads]

            if session is not None:
                live_ads = await _run_live(session)
                if live_ads or not (AVITO_FEED_URL or AVITO_FEED_FILE):
                    return live_ads
                return [
                    NormalizedAd(ad)
                    for ad in await fetch_feed_ads_for_key(key, session)
                ]
            connector = aiohttp.TCPConnector(limit=4)
            async with aiohttp.ClientSession(
                headers=AVITO_HTTP_HEADERS, connector=connector
            ) as own:
                live_ads = await _run_live(own)
                if live_ads or not (AVITO_FEED_URL or AVITO_FEED_FILE):
                    return live_ads
                return [
                    NormalizedAd(ad)
                    for ad in await fetch_feed_ads_for_key(key, own)
                ]
        if AVITO_FEED_URL or AVITO_FEED_FILE:
            async def _run_feed(sess: aiohttp.ClientSession) -> list[NormalizedAd]:
                ads = await fetch_feed_ads_for_key(key, sess)
                return [NormalizedAd(ad) for ad in ads]

            if session is not None:
                return await _run_feed(session)
            connector = aiohttp.TCPConnector(limit=4)
            async with aiohttp.ClientSession(
                headers=AVITO_HTTP_HEADERS, connector=connector
            ) as own:
                return await _run_feed(own)
        raise NotImplementedError(
            "Avito adapter is not configured — enable AVITO_LIVE_ENABLED or set external URL"
        )


avito_adapter = AvitoAdapter()
