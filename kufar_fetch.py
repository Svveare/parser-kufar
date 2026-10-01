"""Загрузка и нормализация объявлений с API Kufar."""

import asyncio
import heapq
import json
import logging
import re
import time
from typing import Any, Optional

import aiohttp

from config import (
    KUFAR_FETCH_RETRIES,
    KUFAR_FETCH_RETRY_DELAY,
    KUFAR_MAX_PAGES,
    KUFAR_SIZE,
)
from filters import parse_memory_gb_text
from kufar_catalog import catalog_search_params

log = logging.getLogger(__name__)


def _retry_delay(attempt: int) -> float:
    return min(KUFAR_FETCH_RETRY_DELAY * (2 ** (attempt - 1)), 30.0)

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
DESCRIPTION_CACHE_TTL_SECONDS = 3600
DESCRIPTION_CACHE_MAX = 500
_description_cache: dict[str, tuple[float, str]] = {}
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain_description(raw: str) -> str:
    text = _HTML_TAG_RE.sub(" ", raw or "")
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > 500:
        text = text[:500].rstrip() + "..."
    return text


def _cache_description(link: str, body: str) -> None:
    """Кэширует только непустое описание; ограничивает размер словаря."""
    body = (body or "").strip()
    if not link or not body:
        return
    _description_cache[link] = (time.time(), body)
    if len(_description_cache) <= DESCRIPTION_CACHE_MAX:
        return
    excess = len(_description_cache) - DESCRIPTION_CACHE_MAX
    oldest = heapq.nsmallest(
        excess,
        _description_cache.items(),
        key=lambda item: item[1][0],
    )
    for key, _ in oldest:
        _description_cache.pop(key, None)


def _param(params: list[dict], name: str) -> Optional[dict]:
    for p in params or []:
        if p.get("p") == name:
            return p
    return None


def _param_label(params: list[dict], *names: str) -> str:
    for name in names:
        p = _param(params, name)
        if not p:
            continue
        vl = p.get("vl")
        if isinstance(vl, str) and vl:
            return vl
        v = p.get("v")
        if v is not None:
            return str(v)
    return ""


def _build_location(ad_params: list[dict]) -> str:
    region = _param_label(ad_params, "region")
    area = _param_label(ad_params, "area")
    if region and area:
        return f"{region}, {area}"
    return region or area or ""


def _build_summary(ad_params: list[dict]) -> str:
    bits: list[str] = []
    for keys, prefix in (
        (("condition",), "Состояние"),
        (("phones_model", "phone_model"), "Модель"),
        (("phablet_phones_memory", "phone_memory"), "Память"),
        (("phones_color", "phone_color"), "Цвет"),
        (("computers_laptop_processor",), "Процессор"),
        (("phablet_tablet_brand",), "Планшет"),
        (("phablet_smart_watches_brand",), "Часы"),
    ):
        label = _param_label(ad_params, *keys)
        if label:
            bits.append(f"{prefix}: {label}")
    return " · ".join(bits)


def _price_from_cents(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value) // 100
    except (TypeError, ValueError):
        return None


def _photo_urls(raw: dict) -> list[str]:
    out: list[str] = []
    for image in raw.get("images") or []:
        if not isinstance(image, dict):
            continue
        path = str(image.get("path") or "").strip().lstrip("/")
        if path:
            out.append(f"https://rms.kufar.by/v1/gallery/{path}")
    return list(dict.fromkeys(out))


def normalize_listing(raw: dict) -> Optional[dict]:
    ad_id = raw.get("ad_id")
    link = raw.get("ad_link") or (f"https://www.kufar.by/item/{ad_id}" if ad_id else None)
    if not link:
        return None

    subject = (raw.get("subject") or "").strip()
    if not subject:
        return None

    ad_params = raw.get("ad_parameters") or []
    phone_model = _param_label(ad_params, "phones_model", "phone_model").strip()
    phone_memory = _param_label(
        ad_params, "phablet_phones_memory", "phone_memory"
    ).strip()
    summary = _build_summary(ad_params)
    condition_label = _param_label(ad_params, "condition").strip()
    memory_gb = parse_memory_gb_text(phone_memory) or parse_memory_gb_text(summary)
    raw_body = raw.get("body") or raw.get("body_short") or ""
    if not isinstance(raw_body, str):
        raw_body = str(raw_body) if raw_body else ""
    description = _plain_description(raw_body)
    return {
        "ad_id": ad_id,
        "title": subject,
        "price": _price_from_cents(raw.get("price_byn")),
        "price_usd": _price_from_cents(raw.get("price_usd")),
        "location": _build_location(ad_params),
        "summary": summary,
        "condition_label": condition_label,
        "phone_model": phone_model,
        "phone_memory": phone_memory,
        "memory_gb": memory_gb,
        "company_ad": bool(raw.get("company_ad")),
        "description": description,
        "link": link.split("?")[0],
        "list_time": raw.get("list_time"),
        "photo_urls": _photo_urls(raw),
    }


def _next_page_cursor(data: dict) -> str | None:
    pages = (data.get("pagination") or {}).get("pages") or []
    for page in pages:
        if page.get("label") == "next":
            token = page.get("token")
            if isinstance(token, str) and token.strip():
                return token.strip()
    return None


async def _fetch_search_page(
    session: aiohttp.ClientSession,
    params: dict[str, str],
    *,
    cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    """Одна страница листинга: объявления и cursor следующей страницы."""
    req = dict(params)
    if cursor:
        req["cursor"] = cursor
    label = req.get("query") or req.get("phm") or req.get("cat") or "search"
    last_err: str | None = None
    for attempt in range(1, KUFAR_FETCH_RETRIES + 1):
        try:
            async with session.get(
                SEARCH_URL, params=req, timeout=aiohttp.ClientTimeout(total=25)
            ) as r:
                if r.status >= 500 or r.status == 429:
                    body = (await r.text())[:200]
                    last_err = f"status={r.status} {body}"
                    log.warning(
                        "kufar search retry query=%r %s attempt=%s/%s",
                        label,
                        last_err,
                        attempt,
                        KUFAR_FETCH_RETRIES,
                    )
                    waited_retry_after = False
                    if r.status == 429 and attempt < KUFAR_FETCH_RETRIES:
                        retry_after = r.headers.get("Retry-After")
                        if retry_after:
                            try:
                                await asyncio.sleep(min(float(retry_after), 60.0))
                                waited_retry_after = True
                            except ValueError:
                                pass
                    if attempt < KUFAR_FETCH_RETRIES and not waited_retry_after:
                        await asyncio.sleep(_retry_delay(attempt))
                    continue
                elif r.status != 200:
                    log.error(
                        "kufar search failed query=%r status=%s",
                        label,
                        r.status,
                    )
                    return [], None
                else:
                    data = await r.json()
                    return data.get("ads") or [], _next_page_cursor(data)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = repr(e)
            log.warning(
                "kufar search network query=%r %s attempt=%s/%s",
                label,
                last_err,
                attempt,
                KUFAR_FETCH_RETRIES,
            )
        if attempt < KUFAR_FETCH_RETRIES:
            await asyncio.sleep(_retry_delay(attempt))
    if last_err:
        log.error(
            "kufar search exhausted query=%r attempts=%s err=%s",
            label,
            KUFAR_FETCH_RETRIES,
            last_err,
        )
    return [], None


async def _fetch_search_params(
    session: aiohttp.ClientSession, params: dict[str, str]
) -> list[dict]:
    """До KUFAR_MAX_PAGES страниц листинга по одному набору params."""
    all_raw: list[dict] = []
    cursor: str | None = None
    label = params.get("query") or params.get("phm") or params.get("cat") or "search"
    page_num = 0
    for page_num in range(1, KUFAR_MAX_PAGES + 1):
        batch, next_cursor = await _fetch_search_page(
            session, params, cursor=cursor
        )
        if batch:
            all_raw.extend(batch)
        if not next_cursor or page_num >= KUFAR_MAX_PAGES:
            break
        cursor = next_cursor
    if KUFAR_MAX_PAGES > 1 and len(all_raw) > KUFAR_SIZE:
        log.debug(
            "kufar paginated query=%r pages=%s raw=%d",
            label,
            page_num,
            len(all_raw),
        )
    return all_raw


async def _fetch_description(session: aiohttp.ClientSession, link: str) -> str:
    try:
        async with session.get(link, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                log.warning("kufar desc status=%s link=%s", r.status, link)
                return ""
            html = await r.text()
    except Exception as e:
        log.warning("kufar desc fetch failed link=%s: %s", link, e)
        return ""

    m = NEXT_DATA_RE.search(html)
    if not m:
        log.warning("kufar desc no __NEXT_DATA__ link=%s html_len=%s", link, len(html))
        return ""
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        log.warning("kufar desc bad __NEXT_DATA__ json link=%s", link)
        return ""

    ad_view = (
        data.get("props", {})
        .get("initialState", {})
        .get("adView", {})
        .get("data", {})
    ) or {}
    if not isinstance(ad_view, dict):
        ad_view = {}
    raw_body = ad_view.get("body") or ad_view.get("description") or ""
    if not isinstance(raw_body, str):
        raw_body = str(raw_body) if raw_body else ""
    body = _plain_description(raw_body)
    if not body:
        log.warning("kufar desc empty body link=%s", link)
    return body


async def _enrich_description(
    session: aiohttp.ClientSession, ad: dict, sem: asyncio.Semaphore
) -> None:
    async with sem:
        link = ad["link"]
        body = await _fetch_description(session, link)
        if body:
            _cache_description(link, body)
            ad["description"] = body


def _apply_cached_description(ad: dict) -> bool:
    link = ad.get("link")
    if not link or (ad.get("description") or "").strip():
        return False
    cached = _description_cache.get(link)
    if not cached:
        return False
    ts, body = cached
    if time.time() - ts >= DESCRIPTION_CACHE_TTL_SECONDS:
        _description_cache.pop(link, None)
        return False
    if not (body or "").strip():
        _description_cache.pop(link, None)
        return False
    ad["description"] = body
    return True


def _normalize_raw_ads(raw_ads: list[dict]) -> list[dict]:
    seen_ids: set[str] = set()
    ads: list[dict] = []
    for raw in raw_ads:
        raw_id = str(raw.get("ad_id") or raw.get("ad_link") or "")
        if raw_id and raw_id in seen_ids:
            continue
        if raw_id:
            seen_ids.add(raw_id)
        item = normalize_listing(raw)
        if item is not None:
            ads.append(item)
    return ads


async def enrich_ads_descriptions(
    ads: list[dict],
    *,
    session: aiohttp.ClientSession | None = None,
    concurrency: int = 5,
) -> None:
    """Параллельно подгружает описания; кэш по link снижает дубли HTTP."""
    need: list[dict] = []
    for ad in ads:
        if _apply_cached_description(ad):
            continue
        if not (ad.get("description") or "").strip() and ad.get("link"):
            need.append(ad)
    if not need:
        return

    async def _run(sess: aiohttp.ClientSession) -> None:
        sem = asyncio.Semaphore(max(1, concurrency))
        await asyncio.gather(*(_enrich_description(sess, ad, sem) for ad in need))

    if session is not None:
        await _run(session)
        return
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS, connector=connector
    ) as own:
        await _run(own)


def _catalog_request_params(facets: dict[str, str]) -> dict[str, str]:
    params = {
        "lang": "ru",
        "size": str(KUFAR_SIZE),
        "sort": "lst.d",
        "cur": "BYR",
    }
    params.update(facets)
    return params


async def fetch_ads_for_key(
    category: str,
    rgn: int,
    ar: int | None,
    models: list[str] | tuple[str, ...],
    memories: list[str] | tuple[str, ...],
    *,
    session: aiohttp.ClientSession | None = None,
) -> list[dict]:
    """Листинг по ключу: категория + rgn/ar + модели (+ память у смартфонов)."""
    facet_sets = catalog_search_params(
        int(rgn), ar, models, memories, category=category
    )
    if not facet_sets:
        return []

    async def _run(sess: aiohttp.ClientSession) -> list[dict]:
        batches = await asyncio.gather(
            *(
                _fetch_search_params(sess, _catalog_request_params(facets))
                for facets in facet_sets
            )
        )
        raw_ads: list[dict] = []
        for batch in batches:
            raw_ads.extend(batch)
        ads = _normalize_raw_ads(raw_ads)
        log.debug(
            "kufar catalog cat=%s rgn=%s ar=%s models=%s mem=%s raw=%d normalized=%d requests=%d",
            category,
            rgn,
            ar,
            len(models),
            list(memories),
            len(raw_ads),
            len(ads),
            len(facet_sets),
        )
        return ads

    if session is not None:
        return await _run(session)
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS, connector=connector
    ) as own:
        return await _run(own)
