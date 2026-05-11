"""Правила отбора объявлений под подписку пользователя."""

from config import (
    DEFAULT_EXCLUDE_TERMS,
    NOT_SALE_TERMS,
    PHONE_REQUIRED_TERMS,
)


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def matches_filters(ad: dict, max_price: int, keywords: list[str]) -> bool:
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

    if not any(t in headline for t in PHONE_REQUIRED_TERMS):
        return False

    if any(normalize(t) in headline for t in NOT_SALE_TERMS):
        return False

    if any(normalize(t) in title for t in DEFAULT_EXCLUDE_TERMS):
        return False

    if keywords:
        kw_list = [normalize(k).strip() for k in keywords if k.strip()]
        if not kw_list:
            return False
        if not any(k in full_text for k in kw_list):
            return False

    return True
