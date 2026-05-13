"""Правила отбора объявлений под подписку пользователя."""
import re

from config import (
    DEVICE_CATALOG,
    DEFAULT_EXCLUDE_TERMS,
    NOT_SALE_TERMS,
    PHONE_REQUIRED_TERMS,
)

# Объявления именно про обмен (ищем по всему тексту). «Без обмена» и т.п. — отсекаем.
EXCHANGE_NEGATIVE_TERMS: tuple[str, ...] = (
    "без обмена",
    "без обменов",
    "обмен не интересует",
    "обмен не нужен",
    "обмен не предлагать",
    "не на обмен",
    "не интересует обмен",
    "обмен не рассматриваю",
    "обмен не предлагаю",
)

EXCHANGE_HINT_TERMS: tuple[str, ...] = (
    "обмен",
    "меняю",
    "обменяю",
    "к обмену",
    "готов к обмену",
    "готов обмен",
    "рассмотрю обмен",
    "рассмотрю варианты обмена",
    "возможен обмен",
    "обмен возможен",
    "интересует обмен",
    "ищу обмен",
    "только обмен",
    "swap",
    "trade-in",
    "трейд-ин",
    "поменяю",
    "на обмен",
    "бартер",
    "обменяюсь",
    "обмен интересен",
    "рассмотрю трейд",
)

NEW_PHONE_TERMS: tuple[str, ...] = (
    "новый",
    "новые",
    "новая",
    "new",
    "brand new",
    "запечатан",
    "не активирован",
    "неактивирован",
)


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def ad_full_text(ad: dict) -> str:
    title = normalize(ad.get("title") or "")
    summary = normalize(ad.get("summary") or "")
    description = normalize(ad.get("description") or "")
    return f"{title} {summary} {description}".strip()


def is_new_phone_ad(ad: dict) -> bool:
    headline = normalize(f"{ad.get('title') or ''} {ad.get('summary') or ''}")
    return any(t in headline for t in NEW_PHONE_TERMS)


def ad_device_key(ad: dict) -> str | None:
    """
    Нормализованный ключ устройства из каталога.
    Важно: ищем самое длинное совпадение, чтобы 'iphone 12 pro max'
    не превращался в 'iphone 12'.
    """
    full_text = ad_full_text(ad)
    normalized_catalog = [
        re.sub(r"\s+", " ", normalize(k).strip())
        for k in DEVICE_CATALOG
        if normalize(k).strip()
    ]
    if not normalized_catalog:
        return None
    matched = [kw for kw in normalized_catalog if kw in full_text]
    if not matched:
        return None
    matched.sort(key=len, reverse=True)
    return matched[0]


def matches_filters(
    ad: dict, max_price: int, keywords: list[str], *, smart_filtering: bool
) -> bool:
    """
    Цена — по объявлению целиком.
    Аксессуары (стоп-слова) — только в названии.
    Признак телефона и «не продажа» — в названии + summary (параметры Kufar), не в описании.
    Ключевики пользователя — везде (название, summary, описание).
    """
    price = ad.get("price")
    if max_price > 0:
        if price is None or price > max_price:
            return False
    else:
        if price is None or price <= 0:
            return False

    title = normalize(ad.get("title") or "")
    summary = normalize(ad.get("summary") or "")
    description = normalize(ad.get("description") or "")

    headline = f"{title} {summary}".strip()
    full_text = f"{headline} {description}".strip()

    if smart_filtering:
        if not any(t in headline for t in PHONE_REQUIRED_TERMS):
            return False
        if any(normalize(t) in headline for t in NOT_SALE_TERMS):
            return False
        if any(normalize(t) in title for t in DEFAULT_EXCLUDE_TERMS):
            return False
        if is_new_phone_ad(ad):
            return False

    if keywords:
        selected_keys = {
            re.sub(r"\s+", " ", normalize(k).strip())
            for k in keywords
            if normalize(k).strip()
        }
        if not selected_keys:
            return False
        ad_key = ad_device_key(ad)
        if ad_key is None or ad_key not in selected_keys:
            return False

    return True


def is_exchange_ad(ad: dict) -> bool:
    """Объявление про обмен устройством (по формулировкам в тексте)."""
    full_text = ad_full_text(ad)
    if any(normalize(t) in full_text for t in EXCHANGE_NEGATIVE_TERMS):
        return False
    return any(normalize(t) in full_text for t in EXCHANGE_HINT_TERMS)
