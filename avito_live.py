"""Live fetch Avito через публичный JSON API (без внешнего collector)."""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from avito_catalog import live_search_params_for_model
from avito_fetch import (
    AVITO_HTTP_HEADERS,
    filter_ads_for_key,
)
from config import (
    AVITO_FEED_RETRIES,
    AVITO_FEED_RETRY_DELAY,
    AVITO_FEED_TIMEOUT_SECONDS,
)
from filters_avito import avito_thin_junk_reason
from marketplace.keys import FetchKey

log = logging.getLogger(__name__)

AVITO_LIVE_ITEMS_URL = "https://www.avito.ru/web/1/main/items"


def _absolute_url(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path.split("?")[0]
    if path.startswith("/"):
        return f"https://www.avito.ru{path.split('?')[0]}"
    return f"https://www.avito.ru/{path.split('?')[0]}"


def _extract_price(raw: dict) -> int | None:
    price_detailed = raw.get("priceDetailed")
    if isinstance(price_detailed, dict):
        value = price_detailed.get("value")
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    price = raw.get("price")
    if price is not None:
        try:
            return int(price)
        except (TypeError, ValueError):
            return None
    return None


def _extract_photos(raw: dict) -> list[str]:
    images = raw.get("images") or raw.get("gallery") or []
    if not isinstance(images, list):
        return []
    out: list[str] = []
    for item in images:
        if isinstance(item, str) and item:
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("640x480") or item.get("636x476")
        if url:
            out.append(str(url))
            continue
        for val in item.values():
            if isinstance(val, str) and val.startswith("http"):
                out.append(val)
                break
    return out


def parse_live_item(
    raw: dict,
    *,
    city_id: str,
    region_id: str,
    category: str,
) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or raw.get("name") or "").strip()
    link = _absolute_url(str(raw.get("url") or raw.get("uri") or ""))
    if not title or not link:
        return None
    geo = raw.get("geo") if isinstance(raw.get("geo"), dict) else {}
    location = str(
        raw.get("location")
        or geo.get("formattedAddress")
        or geo.get("address")
        or ""
    ).strip()
    item_id = raw.get("id") or raw.get("itemId") or link
    description = str(
        raw.get("description")
        or raw.get("shortDescription")
        or raw.get("descriptionPreview")
        or ""
    ).strip()
    published = raw.get("sortTimeStamp") or raw.get("sortDate") or raw.get("date")
    return {
        "id": str(item_id),
        "title": title,
        "price_rub": _extract_price(raw),
        "url": link,
        "city_id": str(raw.get("locationId") or city_id).strip(),
        "region_id": region_id,
        "category": category,
        "description": description,
        "location": location,
        "photos": _extract_photos(raw),
        "published_at": published,
    }


def _parse_live_payload(
    data: object,
    *,
    city_id: str,
    region_id: str,
    category: str,
) -> list[dict]:
    if not isinstance(data, dict):
        return []
    ads = data.get("ads") or data.get("items") or []
    if not isinstance(ads, list):
        return []
    out: list[dict] = []
    for raw in ads:
        if not isinstance(raw, dict):
            continue
        parsed = parse_live_item(
            raw,
            city_id=city_id,
            region_id=region_id,
            category=category,
        )
        if parsed is not None:
            out.append(parsed)
    return out


async def _fetch_live_http(
    session: aiohttp.ClientSession,
    params: dict[str, str],
    *,
    category: str,
    region_id: str,
) -> list[dict]:
    headers = dict(AVITO_HTTP_HEADERS)
    headers.setdefault("Referer", "https://www.avito.ru/")
    headers.setdefault("Origin", "https://www.avito.ru")
    last_err: str | None = None
    city_id = params.get("locationId", "")

    for attempt in range(1, AVITO_FEED_RETRIES + 1):
        try:
            async with session.get(
                AVITO_LIVE_ITEMS_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=AVITO_FEED_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status >= 500 or resp.status == 429:
                    body = (await resp.text())[:200]
                    last_err = f"status={resp.status} {body}"
                    log.warning(
                        "avito live retry %s attempt=%s/%s params=%s",
                        last_err,
                        attempt,
                        AVITO_FEED_RETRIES,
                        params,
                    )
                    if resp.status == 429 and attempt < AVITO_FEED_RETRIES:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            try:
                                await asyncio.sleep(float(retry_after))
                            except ValueError:
                                pass
                    if attempt < AVITO_FEED_RETRIES:
                        await asyncio.sleep(AVITO_FEED_RETRY_DELAY * attempt)
                    continue
                if resp.status != 200:
                    log.error(
                        "avito live failed status=%s url=%s params=%s",
                        resp.status,
                        AVITO_LIVE_ITEMS_URL,
                        params,
                    )
                    return []
                data = await resp.json(content_type=None)
                items = _parse_live_payload(
                    data,
                    city_id=city_id,
                    region_id=region_id,
                    category=category,
                )
                log.info(
                    "avito live loaded ads=%d url=%s params=%s",
                    len(items),
                    AVITO_LIVE_ITEMS_URL,
                    params,
                )
                return items
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            last_err = repr(exc)
            log.warning(
                "avito live network attempt=%s/%s err=%s params=%s",
                attempt,
                AVITO_FEED_RETRIES,
                last_err,
                params,
            )
        if attempt < AVITO_FEED_RETRIES:
            await asyncio.sleep(AVITO_FEED_RETRY_DELAY * attempt)
    if last_err:
        log.error(
            "avito live exhausted url=%s err=%s params=%s",
            AVITO_LIVE_ITEMS_URL,
            last_err,
            params,
        )
    return []


async def fetch_live_ads_for_key(
    key: FetchKey,
    session: aiohttp.ClientSession,
) -> list[dict]:
    source, category, geo_a, geo_b, models, _memories = key
    if source != "avito" or not models:
        return []
    city_id = str(geo_b or geo_a or "").strip()
    region_id = str(geo_a or city_id).strip()
    cat = category
    semaphore = asyncio.Semaphore(3)

    async def _fetch_model(model: str) -> list[dict]:
        params = live_search_params_for_model(key, model)
        if params is None:
            return []
        async with semaphore:
            return await _fetch_live_http(
                session,
                params,
                category=cat,
                region_id=region_id,
            )

    batches = await asyncio.gather(*(_fetch_model(model) for model in models))
    normalized_raw: list[dict] = []
    seen_ids: set[str] = set()
    for raw in (item for batch in batches for item in batch):
        raw = dict(raw)
        raw["city_id"] = city_id
        raw["region_id"] = region_id
        raw["category"] = cat
        item_id = str(raw.get("id") or raw.get("itemId") or raw.get("url") or "")
        if item_id and item_id in seen_ids:
            continue
        if item_id:
            seen_ids.add(item_id)
        normalized_raw.append(raw)
    matched = filter_ads_for_key(normalized_raw, key)
    out: list[dict] = []
    for ad in matched:
        if avito_thin_junk_reason(ad):
            continue
        out.append(ad)
    return out
