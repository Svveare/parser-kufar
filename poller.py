"""Фоновая рассылка: парсинг Kufar и отправка подходящих объявлений подписчикам."""
from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InputMediaPhoto

from config import (
    AVITO_CHECK_INTERVAL,
    AVITO_VIP_CHECK_INTERVAL,
    CHECK_INTERVAL,
    FEED_REFRESH_SECONDS,
    FIRST_RUN_LIMIT,
    MARKET_DISCOUNT_THRESHOLD,
    MAX_AD_PHOTOS,
    REGULAR_CHECK_INTERVAL,
    VIP_CHECK_INTERVAL,
)
from db import (
    avg_market_price,
    checkpoint_wal,
    expire_all_vip,
    get_active_users,
    has_seen_any,
    increment_sent,
    mark_seen,
    prune_price_tables,
    prune_seen_ads,
    prune_unknown_market_prices,
    save_market_prices,
    seen_links_for,
    set_active,
    set_poll_last_run,
    sql_metrics_snapshot,
)
from filters import ad_device_key, is_whole_phone_listing, matches_filters
from filters import ideal_passes
from formatter import format_ad, truncate_ad_caption
from logging_setup import log_exception
from marketplace.keys import (
    FetchKey,
    group_users_by_fetch_key,
    user_is_avito_pollable,
    user_is_kufar_pollable,
    user_primary_source,
)
from marketplace.registry import get_adapter
from marketplace.types import SOURCE_AVITO, SOURCE_KUFAR, normalize_country, normalize_primary_source
from kufar_fetch import (
    DEFAULT_HEADERS,
    enrich_ads_descriptions,
)
from product_catalog import is_phones_category
from user_matching import VIP_SPECIAL_MAX_PRICE, match_ads_for_user

log = logging.getLogger("kufar_bot.poller")

first_run_notified: set[int] = set()
_fetch_cache: dict[FetchKey, tuple[float, list[dict]]] = {}
FETCH_KEY_CONCURRENCY = 3
POLL_DUE_SLEEP_FLOOR = 1.0
_last_description_metrics = (0.0, 0.0, 0)
_source_failures: dict[str, int] = {}
_source_retry_after: dict[str, float] = {}


def _evict_stale_fetch_cache(now: float) -> None:
    stale = [
        key
        for key, (ts, _) in _fetch_cache.items()
        if now - ts >= FEED_REFRESH_SECONDS
    ]
    for key in stale:
        _fetch_cache.pop(key, None)

VIP_EXPIRED_MSG = (
    "⭐ <b>VIP закончился</b>\n\n"
    "Память сброшена на <b>64 ГБ</b>. "
    "Модели и лимит цены сохранены — при необходимости продлите VIP в меню."
)
FIRST_RUN_DIGEST_MSG_KUFAR = (
    "ℹ️ Показали первые <b>{n}</b> объявления. "
    "Остальные новые совпадения будут приходить по мере появления на Kufar."
)
FIRST_RUN_DIGEST_MSG_AVITO = (
    "ℹ️ Показали первые <b>{n}</b> объявления. "
    "Остальные новые совпадения будут приходить по мере появления на Avito."
)


def _first_run_digest_msg(user: dict) -> str:
    if user_primary_source(user) == SOURCE_AVITO:
        return FIRST_RUN_DIGEST_MSG_AVITO.format(n=FIRST_RUN_LIMIT)
    return FIRST_RUN_DIGEST_MSG_KUFAR.format(n=FIRST_RUN_LIMIT)


def _description_candidates(
    matched: list[dict],
    already_seen: set[str],
    *,
    first_run: bool,
) -> list[dict]:
    candidates = matched[:FIRST_RUN_LIMIT] if first_run else matched
    return [
        ad
        for ad in candidates
        if ad.get("link")
        and ad["link"] not in already_seen
        and not (ad.get("description") or "").strip()
    ]


def _ingest_market_prices_from_ads(ads: list[dict]) -> None:
    """Пополняет market_prices только целыми телефонами из батча листинга."""
    rows: list[tuple[str, str, int, str]] = []
    for ad in ads:
        if not is_whole_phone_listing(ad):
            continue
        if not matches_filters(
            ad,
            VIP_SPECIAL_MAX_PRICE,
            [],
            memory_volumes=None,
            smart_filtering=True,
            device_filter=False,
            memory_filter=False,
        ):
            continue
        dk = ad_device_key(ad)
        price = ad.get("price")
        link = ad.get("link")
        if not dk or not isinstance(price, int) or price <= 0:
            continue
        if not isinstance(link, str) or not link.strip():
            continue
        source = normalize_primary_source(ad.get("source"))
        rows.append((link, dk, price, source))
    save_market_prices(rows)


def _is_vip_user(user: dict) -> bool:
    return user.get("role") == "vip"


def _poll_source(user: dict) -> str:
    return user_primary_source(user)


def _user_interval(user: dict, source: str | None = None) -> float:
    src = normalize_primary_source(source or _poll_source(user))
    is_vip = _is_vip_user(user)
    if src == SOURCE_AVITO:
        return float(
            AVITO_VIP_CHECK_INTERVAL if is_vip else AVITO_CHECK_INTERVAL
        )
    return float(VIP_CHECK_INTERVAL if is_vip else REGULAR_CHECK_INTERVAL)


def _user_last_run(user: dict, source: str | None = None) -> float:
    src = normalize_primary_source(source or _poll_source(user))
    is_vip = _is_vip_user(user)
    if src == SOURCE_AVITO:
        if is_vip:
            return float(user.get("poll_last_avito_vip") or 0)
        return float(user.get("poll_last_avito_regular") or 0)
    if is_vip:
        return float(user.get("poll_last_vip") or 0)
    return float(user.get("poll_last_regular") or 0)


def _seconds_until_due(user: dict, now: float, source: str | None = None) -> float:
    prev = _user_last_run(user, source)
    if prev <= 0:
        return 0.0
    return max(0.0, _user_interval(user, source) - (now - prev))


def _should_process_user(
    user: dict,
    *,
    now: float | None = None,
    source: str | None = None,
) -> bool:
    t = time.time() if now is None else now
    return _seconds_until_due(user, t, source) <= 0.0


def _poll_sleep_seconds(
    users: list[dict],
    now: float,
    *,
    tick: float | None = None,
) -> float:
    """Сколько спать до следующего прохода: не дольше тика, не позже due."""
    cap = float(CHECK_INTERVAL if tick is None else tick)
    cap = max(0.05, cap)
    if not users:
        return cap
    pollable_users = []
    for user in users:
        source = _poll_source(user)
        if source == SOURCE_KUFAR and user_is_kufar_pollable(user):
            pollable_users.append(user)
        elif source == SOURCE_AVITO and user_is_avito_pollable(user):
            pollable_users.append(user)
    if not pollable_users:
        return cap
    soonest = min(
        max(
            _seconds_until_due(user, now, _poll_source(user)),
            _source_retry_after.get(_poll_source(user), 0.0) - now,
        )
        for user in pollable_users
    )
    if soonest <= 0:
        return min(cap, POLL_DUE_SLEEP_FLOOR)
    return min(cap, soonest)


def _due_users_by_source(users: list[dict], now: float) -> dict[str, list[dict]]:
    due = {SOURCE_KUFAR: [], SOURCE_AVITO: []}
    for user in users:
        source = _poll_source(user)
        pollable = user_is_kufar_pollable(user) if source == SOURCE_KUFAR else user_is_avito_pollable(user)
        if (
            pollable
            and now >= _source_retry_after.get(source, 0.0)
            and _should_process_user(user, now=now, source=source)
        ):
            due[source].append(user)
    return due


def _mark_user_polled(user: dict) -> None:
    is_vip = _is_vip_user(user)
    source = _poll_source(user)
    set_poll_last_run(user["chat_id"], is_vip=is_vip, source=source)
    stamped = int(time.time())
    if source == SOURCE_AVITO:
        if is_vip:
            user["poll_last_avito_vip"] = stamped
        else:
            user["poll_last_avito_regular"] = stamped
    elif is_vip:
        user["poll_last_vip"] = stamped
    else:
        user["poll_last_regular"] = stamped


async def _notify_vip_expired(bot: Bot, chat_ids: list[int]) -> None:
    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id, VIP_EXPIRED_MSG, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            set_active(chat_id, False)
        except Exception as exc:
            log_exception(log, "vip expired notify failed chat_id=%s: %s", chat_id, exc)


def _is_unreachable_chat(exc: TelegramBadRequest) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "chat not found",
            "user is deactivated",
            "peer_id_invalid",
            "bot was blocked",
        )
    )


async def _send_ad(
    bot: Bot,
    chat_id: int,
    ad: dict,
    *,
    market_avg_price: int | None = None,
    below_market: bool = False,
    ideal_feed: bool = False,
    include_photos: bool = False,
    compact: bool = False,
    country: str | None = None,
) -> tuple[bool, bool]:
    """(доставлено, пользователь отключён — блокировка бота)."""
    text = truncate_ad_caption(
        format_ad(
            ad,
            market_avg_price=market_avg_price,
            below_market=below_market,
            ideal_feed=ideal_feed,
            compact=compact,
            country=country,
        )
    )
    photos = [p for p in (ad.get("photo_urls") or []) if isinstance(p, str) and p.strip()]
    if include_photos and photos:
        photos = photos[:MAX_AD_PHOTOS]

    async def _deliver_text() -> None:
        await bot.send_message(chat_id, text, disable_web_page_preview=False)

    async def _deliver_media() -> None:
        media = [
            InputMediaPhoto(
                media=photo,
                caption=text if i == 0 else None,
                parse_mode=ParseMode.HTML if i == 0 else None,
            )
            for i, photo in enumerate(photos)
        ]
        await bot.send_media_group(chat_id=chat_id, media=media)

    async def _deliver() -> None:
        if include_photos and photos:
            await _deliver_media()
            return
        await _deliver_text()

    try:
        await _deliver()
        return True, False
    except TelegramRetryAfter as e:
        log.warning("send flood_wait chat_id=%s sec=%s", chat_id, e.retry_after)
        await asyncio.sleep(e.retry_after + 1)
        try:
            await _deliver()
            return True, False
        except Exception as exc:
            log_exception(log, "send retry failed chat_id=%s: %s", chat_id, exc)
            return False, False
    except TelegramForbiddenError:
        log.info("user blocked bot chat_id=%s — subscription off", chat_id)
        set_active(chat_id, False)
        return False, True
    except TelegramBadRequest as exc:
        if _is_unreachable_chat(exc):
            log.info("user unreachable chat_id=%s — subscription off", chat_id)
            set_active(chat_id, False)
            return False, True
        log.warning("send bad_request chat_id=%s: %s", chat_id, exc)
        if photos and include_photos:
            try:
                await _deliver_text()
                return True, False
            except Exception as fallback_exc:
                log_exception(
                    log, "send text fallback failed chat_id=%s: %s", chat_id, fallback_exc
                )
        return False, False
    except Exception as exc:
        log_exception(log, "send failed chat_id=%s: %s", chat_id, exc)
        return False, False


async def _process_user(
    bot: Bot,
    user: dict,
    ads: list[dict],
    market_cache: dict[str, int | None],
    *,
    matched: list[dict] | None = None,
    session: aiohttp.ClientSession | None = None,
) -> int:
    chat_id = user["chat_id"]
    is_vip = user.get("role") == "vip"
    feed_mode = (user.get("vip_feed_mode") or "normal") if is_vip else "normal"
    source = user_primary_source(user)

    if matched is None:
        matched = match_ads_for_user(user, ads, market_cache)
    if not matched:
        return 0

    if "_poll_first_run" in user:
        is_first_run = bool(user.pop("_poll_first_run"))
    else:
        is_first_run = not has_seen_any(chat_id)
    skipped_first_run = 0
    if is_first_run:
        to_send = matched[:FIRST_RUN_LIMIT]
        skipped_first_run = max(0, len(matched) - FIRST_RUN_LIMIT)
        for ad in matched[FIRST_RUN_LIMIT:]:
            mark_seen(chat_id, ad["link"], source=source)
    else:
        to_send = matched

    links = [ad["link"] for ad in to_send if ad.get("link")]
    already_seen = seen_links_for(chat_id, links, source=source)

    ideal_mode = is_vip and feed_mode == "ideal"
    if ideal_mode:
        strict_ok: list[dict] = []
        for ad in to_send:
            link = ad.get("link")
            if not link or link in already_seen:
                continue
            if ideal_passes(
                ad, stage="strict", skip_battery=not is_phones_category(user.get("product_category"))
            ):
                strict_ok.append(ad)
            else:
                mark_seen(chat_id, link, source=source)
                already_seen.add(link)
        to_send = strict_ok
        if not to_send:
            return 0

    delivered_count = 0
    for ad in to_send:
        link = ad.get("link")
        if not link or link in already_seen:
            continue

        device_key = ad_device_key(ad)
        price = ad.get("price")
        cache_key = f"{source}:{device_key}" if device_key else ""
        market_avg = market_cache.get(cache_key) if device_key else None
        if is_vip and device_key and market_avg is None:
            market_avg = avg_market_price(device_key, source=source)
            market_cache[cache_key] = market_avg

        below_market = feed_mode == "below_market"
        if (
            is_vip
            and not below_market
            and feed_mode != "ideal"
            and market_avg
            and isinstance(price, int)
            and price < int(market_avg * MARKET_DISCOUNT_THRESHOLD)
        ):
            below_market = True

        ok, deactivated = await _send_ad(
            bot,
            chat_id,
            ad,
            market_avg_price=market_avg if is_vip else None,
            below_market=below_market,
            ideal_feed=ideal_mode,
            include_photos=is_vip,
            compact=not is_vip,
            country=normalize_country(user.get("country")),
        )
        if ok:
            delivered_count += 1
            mark_seen(chat_id, link, source=source)
            already_seen.add(link)
            increment_sent(chat_id)
            await asyncio.sleep(0.05)
        elif deactivated:
            user["active"] = False
            break
        else:
            log.warning(
                "send not delivered chat_id=%s link=%s",
                chat_id,
                ad.get("link"),
            )

    if (
        is_first_run
        and skipped_first_run > 0
        and chat_id not in first_run_notified
    ):
        first_run_notified.add(chat_id)
        try:
            await bot.send_message(
                chat_id,
                _first_run_digest_msg(user),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            log_exception(log, "first-run digest failed chat_id=%s: %s", chat_id, exc)
    return delivered_count


async def _batch_enrich_vip_descriptions(
    due: list[dict],
    groups: dict[FetchKey, list[dict]],
    ads_by_key: dict[FetchKey, list[dict]],
    market_cache: dict[str, int | None],
    *,
    session: aiohttp.ClientSession,
) -> dict[int, list[dict]]:
    """Один HTTP-проход на link для VIP; возвращает matched по chat_id."""
    global _last_description_metrics
    matched_by_chat: dict[int, list[dict]] = {}
    by_link: dict[str, dict] = {}
    match_seconds = 0.0
    for key, group_users in groups.items():
        if key[0] == SOURCE_AVITO:
            continue
        ads = ads_by_key.get(key) or []
        if not ads:
            continue
        for user in group_users:
            if user.get("role") != "vip":
                continue
            user_match_started = time.perf_counter()
            matched = match_ads_for_user(user, ads, market_cache)
            match_seconds += time.perf_counter() - user_match_started
            chat_id = int(user["chat_id"])
            matched_by_chat[chat_id] = matched
            if not matched:
                continue
            source = user_primary_source(user)
            links = [ad["link"] for ad in matched if ad.get("link")]
            already_seen = seen_links_for(chat_id, links, source=source)
            first_run = not has_seen_any(chat_id)
            candidates = _description_candidates(
                matched,
                already_seen,
                first_run=first_run,
            )
            user["_poll_first_run"] = first_run
            for ad in candidates:
                link = ad["link"]
                by_link.setdefault(link, ad)
    enrich_started = time.perf_counter()
    if by_link:
        await enrich_ads_descriptions(list(by_link.values()), session=session)
    _last_description_metrics = (
        match_seconds,
        time.perf_counter() - enrich_started,
        len(by_link),
    )
    return matched_by_chat


async def _fetch_catalog_groups(
    groups: dict[FetchKey, list[dict]],
    *,
    session: aiohttp.ClientSession,
    fresh_keys: set[FetchKey] | None = None,
) -> dict[FetchKey, list[dict]]:
    keys = list(groups.keys())
    if not keys:
        return {}
    now = time.time()
    _evict_stale_fetch_cache(now)
    ads_by_key: dict[FetchKey, list[dict]] = {}
    keys_to_fetch: list[FetchKey] = []
    for key in keys:
        cached = _fetch_cache.get(key)
        if cached and now - cached[0] < FEED_REFRESH_SECONDS:
            ads_by_key[key] = cached[1]
        else:
            keys_to_fetch.append(key)

    if keys_to_fetch:
        sem = asyncio.Semaphore(FETCH_KEY_CONCURRENCY)

        async def _one(key: FetchKey) -> tuple[FetchKey, list[dict]]:
            async with sem:
                ads = await get_adapter(key[0]).fetch_for_key(key, session=session)
            return key, ads

        batches = await asyncio.gather(*(_one(key) for key in keys_to_fetch))
        for key, ads in batches:
            _fetch_cache[key] = (now, ads)
            ads_by_key[key] = ads
            if fresh_keys is not None:
                fresh_keys.add(key)

    return ads_by_key


async def _dispatch_due(
    bot: Bot,
    due: list[dict],
    *,
    source: str = SOURCE_KUFAR,
) -> None:
    if not due:
        return
    sql_metrics_snapshot(reset=True)
    src = normalize_primary_source(source)
    group_started = time.perf_counter()
    groups = group_users_by_fetch_key(due)
    group_seconds = time.perf_counter() - group_started
    http_counts = {"total": 0, "catalog": 0, "description": 0}
    fresh_keys: set[FetchKey] = set()

    async def on_request_start(_session, _trace_context, params) -> None:
        http_counts["total"] += 1
        if "/item/" in str(params.url):
            http_counts["description"] += 1
        else:
            http_counts["catalog"] += 1

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_start.append(on_request_start)
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(
        headers=DEFAULT_HEADERS, connector=connector, trace_configs=[trace_config]
    ) as session:
        fetch_started = time.perf_counter()
        ads_by_key = await _fetch_catalog_groups(
            groups, session=session, fresh_keys=fresh_keys
        )
        fetch_seconds = time.perf_counter() - fetch_started
        ingest_ads: list[dict] = []
        seen_links: set[str] = set()
        for key in fresh_keys:
            for ad in ads_by_key.get(key) or []:
                link = ad.get("link")
                if not isinstance(link, str) or not link or link in seen_links:
                    continue
                seen_links.add(link)
                ingest_ads.append(ad)
        await asyncio.to_thread(_ingest_market_prices_from_ads, ingest_ads)
        market_cache: dict[str, int | None] = {}
        matched_by_chat = await _batch_enrich_vip_descriptions(
            due, groups, ads_by_key, market_cache, session=session
        )
        match_seconds, enrich_seconds, description_candidates = _last_description_metrics
        delivery_started = time.perf_counter()
        sent_count = 0
        log.info(
            "poll %s metrics users=%d keys=%d ads=%d http=%d catalog_http=%d "
            "description_http=%d description_candidates=%d group_s=%.3f "
            "fetch_s=%.3f vip_match_s=%.3f enrich_s=%.3f",
            src,
            len(due),
            len(groups),
            len(ingest_ads),
            http_counts["total"],
            http_counts["catalog"],
            http_counts["description"],
            description_candidates,
            group_seconds,
            fetch_seconds,
            match_seconds,
            enrich_seconds,
        )
        for key, group_users in groups.items():
            ads = ads_by_key.get(key) or []
            for user in group_users:
                try:
                    chat_id = int(user["chat_id"])
                    prematched = matched_by_chat.get(chat_id)
                    if prematched is None:
                        user_match_started = time.perf_counter()
                        prematched = match_ads_for_user(user, ads, market_cache)
                        match_seconds += time.perf_counter() - user_match_started
                    sent_count += await _process_user(
                        bot,
                        user,
                        ads,
                        market_cache,
                        matched=prematched,
                        session=session,
                    )
                    _mark_user_polled(user)
                except Exception:
                    _mark_user_polled(user)
                    log_exception(
                        log, "poll user failed chat_id=%s", user["chat_id"]
                    )
        delivery_seconds = time.perf_counter() - delivery_started
        sql_count, sql_seconds = sql_metrics_snapshot(reset=True)
        log.info(
            "poll %s delivery_s=%.3f match_total_s=%.3f sent=%d sql_ops=%d sql_exec_s=%.3f",
            src,
            delivery_seconds,
            match_seconds,
            sent_count,
            sql_count,
            sql_seconds,
        )

async def poller(bot: Bot) -> None:
    # Тяжёлые операции (expire/prune) не обязательно делать каждый цикл.
    # Это снижает нагрузку на SQLite при большом количестве пользователей.
    last_expire_at = 0.0
    last_prune_at = 0.0
    expire_every_s = max(60.0, CHECK_INTERVAL)  # не чаще раза в минуту
    prune_every_s = max(600.0, CHECK_INTERVAL * 10)  # примерно раз в 10 минут

    while True:
        users: list[dict] = []
        try:
            now = time.time()
            if now - last_expire_at >= expire_every_s:
                expired = await asyncio.to_thread(expire_all_vip)
                last_expire_at = now
                if expired:
                    await _notify_vip_expired(bot, expired)

            if now - last_prune_at >= prune_every_s:
                pruned = await asyncio.to_thread(prune_price_tables)
                if pruned[0] or pruned[1]:
                    log.debug(
                        "price tables pruned market=%s sent=%s", pruned[0], pruned[1]
                    )
                seen_pruned = await asyncio.to_thread(prune_seen_ads)
                if seen_pruned:
                    log.debug("seen_ads pruned deleted=%s", seen_pruned)
                stale = await asyncio.to_thread(prune_unknown_market_prices)
                if stale:
                    log.debug("market_prices unknown models deleted=%s", stale)
                await asyncio.to_thread(checkpoint_wal)
                last_prune_at = now

            users_load_started = time.perf_counter()
            users = await asyncio.to_thread(get_active_users, expire_vip=False)
            users_load_seconds = time.perf_counter() - users_load_started
            now = time.time()
            due_by_source = _due_users_by_source(users, now)
            kufar_due = due_by_source[SOURCE_KUFAR]
            avito_due = due_by_source[SOURCE_AVITO]
            log.info(
                "poll users active=%d load_s=%.3f kufar_due=%d avito_due=%d",
                len(users),
                users_load_seconds,
                len(kufar_due),
                len(avito_due),
            )

            if not (kufar_due or avito_due):
                log.debug("poll skip — no due subscribers")
            else:
                for source, source_due in due_by_source.items():
                    if not source_due:
                        continue
                    try:
                        await _dispatch_due(bot, source_due, source=source)
                    except Exception:
                        failures = _source_failures.get(source, 0) + 1
                        _source_failures[source] = failures
                        delay = min(30.0 * (2 ** (failures - 1)), 300.0)
                        _source_retry_after[source] = time.time() + delay
                        log_exception(
                            log,
                            "poll %s dispatch failed; retry in %.0fs",
                            source,
                            delay,
                        )
                    else:
                        _source_failures.pop(source, None)
                        _source_retry_after.pop(source, None)
        except Exception:
            log_exception(log, "poll cycle failed")

        await asyncio.sleep(_poll_sleep_seconds(users, time.time()))
