import asyncio
import json
import logging
import re
from typing import Optional

import aiohttp

from config import KUFAR_QUERY, KUFAR_REGION, KUFAR_SIZE

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.kufar.by/",
    "Origin": "https://www.kufar.by",
}

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)


def _param(params: list[dict], name: str) -> Optional[dict]:
    for p in params or []:
        if p.get("p") == name:
            return p
    return None


def _param_label(params: list[dict], name: str) -> str:
    p = _param(params, name)
    if not p:
        return ""
    vl = p.get("vl")
    if isinstance(vl, str) and vl:
        return vl
    v = p.get("v")
    return str(v) if v is not None else ""


def _build_location(ad_params: list[dict]) -> str:
    region = _param_label(ad_params, "region")
    area = _param_label(ad_params, "area")
    if region and area:
        return f"{region}, {area}"
    return region or area or ""


def _build_summary(ad_params: list[dict]) -> str:
    """Собирает короткое описание из значимых параметров объявления."""
    bits: list[str] = []
    for key, prefix in (
        ("condition", "Состояние"),
        ("phone_model", "Модель"),
        ("phone_memory", "Память"),
        ("phone_color", "Цвет"),
    ):
        label = _param_label(ad_params, key)
        if label:
            bits.append(f"{prefix}: {label}")
    return " · ".join(bits)


def _normalize_ad(raw: dict) -> Optional[dict]:
    ad_id = raw.get("ad_id")
    link = raw.get("ad_link") or (
        f"https://www.kufar.by/item/{ad_id}" if ad_id else None
    )
    if not link:
        return None

    subject = (raw.get("subject") or "").strip()
    if not subject:
        return None

    def _coerce_cents(value) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value) // 100
        except (TypeError, ValueError):
            return None

    price = _coerce_cents(raw.get("price_byn"))
    price_usd = _coerce_cents(raw.get("price_usd"))

    ad_params = raw.get("ad_parameters") or []
    location = _build_location(ad_params)
    summary = _build_summary(ad_params)

    return {
        "ad_id": ad_id,
        "title": subject,
        "price": price,
        "price_usd": price_usd,
        "location": location,
        "summary": summary,
        "description": "",
        "link": link.split("?")[0],
        "list_time": raw.get("list_time"),
    }


async def _fetch_search(session: aiohttp.ClientSession) -> list[dict]:
    params = {
        "lang": "ru",
        "size": str(KUFAR_SIZE),
        "sort": "lst.d",
        "rgn": str(KUFAR_REGION),
        "cur": "BYR",
        "query": KUFAR_QUERY,
    }
    async with session.get(SEARCH_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            text = await r.text()
            log.error("[PARSER] search API status=%s body=%s", r.status, text[:300])
            return []
        data = await r.json()
    return data.get("ads") or []


async def _fetch_description(session: aiohttp.ClientSession, link: str) -> str:
    try:
        async with session.get(link, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return ""
            html = await r.text()
    except Exception as e:
        log.debug("[PARSER] не удалось загрузить %s: %s", link, e)
        return ""

    m = NEXT_DATA_RE.search(html)
    if not m:
        return ""
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return ""

    ad_view = (
        data.get("props", {})
        .get("initialState", {})
        .get("adView", {})
        .get("data", {})
    )
    body = ad_view.get("body") or ""
    body = body.strip()
    if len(body) > 500:
        body = body[:500].rstrip() + "..."
    return body


async def _enrich(session: aiohttp.ClientSession, ad: dict, sem: asyncio.Semaphore) -> None:
    async with sem:
        ad["description"] = await _fetch_description(session, ad["link"])


async def fetch_ads(*, with_description: bool = True) -> list[dict]:
    """Возвращает список объявлений со страницы листинга Kufar.

    Поля: ad_id, title, price (BYN, int), price_usd, location, summary, description, link, list_time.
    """
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, connector=connector) as session:
        raw_ads = await _fetch_search(session)
        log.info("[PARSER] получено сырых объявлений: %d", len(raw_ads))

        ads: list[dict] = []
        for raw in raw_ads:
            normalized = _normalize_ad(raw)
            if normalized is not None:
                ads.append(normalized)

        if with_description and ads:
            sem = asyncio.Semaphore(5)
            await asyncio.gather(*(_enrich(session, ad, sem) for ad in ads))

    log.info("[PARSER] нормализовано объявлений: %d", len(ads))
    return ads


def matches_filters(ad: dict, max_price: int, keywords: list[str]) -> bool:
    """True если объявление подходит под фильтры пользователя."""
    if max_price > 0:
        price = ad.get("price")
        if price is None or price > max_price:
            return False

    if keywords:
        haystack = " ".join(
            [
                ad.get("title", ""),
                ad.get("summary", ""),
                ad.get("description", ""),
            ]
        ).lower()
        if not any(k.lower() in haystack for k in keywords):
            return False

    return True
