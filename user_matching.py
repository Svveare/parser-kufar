"""Сопоставление объявлений Kufar с фильтрами пользователя (ядро рассылки)."""
from __future__ import annotations

from collections.abc import Callable

from config import FILTER_DEBUG_LOG, MARKET_DISCOUNT_THRESHOLD
from db import avg_market_price
from marketplace.keys import user_primary_source
from marketplace.types import SOURCE_AVITO
from filters_avito import avito_thin_junk_reason
from filters import (
    ad_device_key,
    exchange_reject_reason,
    filter_reject_reason,
    ideal_passes,
    ideal_reject_reason,
    log_filter_reject,
    matches_filters,
)
from product_catalog import is_phones_category

# VIP-потоки «ниже рынка» / «обмен» — без лимита цены из профиля
VIP_SPECIAL_MAX_PRICE = 99_999_999


def _is_avito_user(user: dict) -> bool:
    return user_primary_source(user) == SOURCE_AVITO


def _memory_filter_for(user: dict) -> bool:
    return is_phones_category(user.get("product_category"))


def _avito_junk_reject(ad: dict, user: dict) -> bool:
    if not _is_avito_user(user):
        return False
    return avito_thin_junk_reason(ad) is not None


def geo_location_matches(ad: dict, user: dict) -> bool:
    """Локальный safety-фильтр по городу (Kufar ar или Avito city)."""
    if _is_avito_user(user):
        city_id = str(user.get("avito_city_id") or "").strip()
        if not city_id:
            return True
        ad_city = str(ad.get("city_id") or "").strip()
        ad_region = str(ad.get("region_id") or "").strip()
        region_id = str(user.get("avito_region_id") or "").strip()
        if ad_city and ad_city == city_id:
            return True
        if ad_region and region_id and ad_region == region_id:
            return True
        label = (user.get("avito_city_label") or "").strip()
        if not label:
            return True
        token = " ".join(label.lower().replace("ё", "е").split())
        hay = f"{ad.get('title') or ''} {ad.get('location') or ''}"
        hay_norm = " ".join(hay.lower().replace("ё", "е").split())
        return token in hay_norm

    if user.get("city_ar") is None:
        return True
    label = (user.get("city_label") or "").strip()
    if not label:
        return True
    token = " ".join(label.lower().replace("ё", "е").split())
    hay = f"{ad.get('title') or ''} {ad.get('location') or ''}"
    hay_norm = " ".join(hay.lower().replace("ё", "е").split())
    return token in hay_norm


def _passes_base(ad: dict, user: dict, *, max_price: int, skip_new_phone: bool = False) -> bool:
    if not matches_filters(
        ad,
        max_price,
        user["keywords"],
        memory_volumes=user.get("memory_volumes"),
        smart_filtering=False,
        basic_filtering=False,
        device_filter=True,
        memory_filter=_memory_filter_for(user),
        skip_new_phone=skip_new_phone,
        company_filter=True,
        thin_junk=True,
    ):
        return False
    if _avito_junk_reject(ad, user):
        return False
    return geo_location_matches(ad, user)


def _log_reject(ad: dict, user: dict, *, max_price: int, feed_mode: str) -> None:
    if not FILTER_DEBUG_LOG:
        return
    reason = filter_reject_reason(
        ad,
        max_price,
        user["keywords"],
        memory_volumes=user.get("memory_volumes"),
        smart_filtering=False,
        basic_filtering=False,
        device_filter=True,
        memory_filter=_memory_filter_for(user),
        company_filter=True,
        thin_junk=True,
    )
    if reason:
        log_filter_reject(ad, reason, chat_id=user["chat_id"], feed_mode=feed_mode)


def _market_cache_key(device_key: str, source: str) -> str:
    return f"{source}:{device_key}"


def _market_avg(
    device_key: str,
    cache: dict[str, int | None],
    user: dict,
) -> int | None:
    source = user_primary_source(user)
    ck = _market_cache_key(device_key, source)
    if ck in cache:
        return cache[ck]
    value = avg_market_price(device_key, source=source)
    cache[ck] = value
    return value


def _match_vip_ads(
    user: dict,
    ads: list[dict],
    market_cache: dict[str, int | None],
    feed_mode: str,
    *,
    accept: Callable[[dict, dict, dict[str, int | None]], bool],
) -> list[dict]:
    matched: list[dict] = []
    skip_new = feed_mode == "ideal"
    for ad in ads:
        if not _passes_base(
            ad, user, max_price=VIP_SPECIAL_MAX_PRICE, skip_new_phone=skip_new
        ):
            _log_reject(ad, user, max_price=VIP_SPECIAL_MAX_PRICE, feed_mode=feed_mode)
            continue
        if accept(ad, user, market_cache):
            matched.append(ad)
    return matched


def _below_market_accept(ad: dict, user: dict, market_cache: dict[str, int | None]) -> bool:
    dk = ad_device_key(ad)
    price = ad.get("price")
    if not dk or not isinstance(price, int) or price <= 0:
        return False
    mavg = _market_avg(dk, market_cache, user)
    return bool(mavg and price < int(mavg * MARKET_DISCOUNT_THRESHOLD))


def _ideal_pre_accept(ad: dict, user: dict, market_cache: dict[str, int | None]) -> bool:
    del market_cache
    if not ideal_passes(ad, stage="pre"):
        reason = ideal_reject_reason(ad, require_full_text=False)
        if reason:
            log_filter_reject(
                ad,
                reason,
                chat_id=user["chat_id"],
                feed_mode="ideal",
            )
        return False
    return True


def _exchange_accept(ad: dict, user: dict, market_cache: dict[str, int | None]) -> bool:
    reason = exchange_reject_reason(ad)
    if reason:
        log_filter_reject(
            ad,
            reason,
            chat_id=user["chat_id"],
            feed_mode=(user.get("vip_feed_mode") or "normal"),
        )
        return False
    return True


def match_ads_for_user(
    user: dict,
    ads: list[dict],
    market_cache: dict[str, int | None],
) -> list[dict]:
    """Возвращает объявления, подходящие пользователю под его VIP-поток и фильтры."""
    is_vip = user.get("role") == "vip"
    feed_mode = (user.get("vip_feed_mode") or "normal") if is_vip else "normal"

    if is_vip and feed_mode == "below_market":
        return _match_vip_ads(
            user,
            ads,
            market_cache,
            feed_mode,
            accept=_below_market_accept,
        )

    if is_vip and feed_mode == "exchange":
        return _match_vip_ads(
            user,
            ads,
            market_cache,
            feed_mode,
            accept=_exchange_accept,
        )

    if is_vip and feed_mode == "ideal":
        return _match_vip_ads(
            user,
            ads,
            market_cache,
            feed_mode,
            accept=_ideal_pre_accept,
        )

    max_price = int(user.get("max_price") or 0)
    out: list[dict] = []
    for ad in ads:
        if _passes_base(ad, user, max_price=max_price):
            out.append(ad)
        else:
            _log_reject(ad, user, max_price=max_price, feed_mode=feed_mode)
    return out
