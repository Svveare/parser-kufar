"""Query params для Avito collector search API (Фаза 4.2) и live web API."""
from __future__ import annotations

from product_catalog import (
    CAT_LAPTOPS,
    CAT_PHONES,
    CAT_TABLETS,
    CAT_WATCHES,
    is_phones_category,
    normalize_category,
)

_SOURCE_AVITO = "avito"

FetchKey = tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]]

# Avito categoryId (витрина)
AVITO_CATEGORY_IDS: dict[str, int] = {
    CAT_PHONES: 110,
    CAT_LAPTOPS: 98,
    CAT_TABLETS: 96,
    CAT_WATCHES: 114,
}

AVITO_QUICK_CITIES: tuple[tuple[str, str, str], ...] = (
    ("Москва", "637640", "637640"),
    ("Санкт-Петербург", "653240", "653240"),
    ("Смоленск", "653430", "653430"),
)


def search_params_from_key(key: FetchKey) -> dict[str, str] | None:
    source, category, geo_a, geo_b, models, memories = key
    if source != _SOURCE_AVITO or not models:
        return None
    city_id = str(geo_b or geo_a or "").strip()
    if not city_id:
        return None
    cat = normalize_category(category)
    params: dict[str, str] = {
        "city_id": city_id,
        "category": cat,
        "models": ",".join(models),
    }
    region_id = str(geo_a or "").strip()
    if region_id:
        params["region_id"] = region_id
    if is_phones_category(cat) and memories:
        params["memory_gb"] = ",".join(memories)
    return params


def live_search_params_for_model(
    key: FetchKey,
    model: str,
) -> dict[str, str] | None:
    """GET query для одной модели на https://www.avito.ru/web/1/main/items."""
    source, category, geo_a, geo_b, models, _memories = key
    if source != _SOURCE_AVITO or not models:
        return None
    city_id = str(geo_b or geo_a or "").strip()
    if not city_id:
        return None
    cat = normalize_category(category)
    category_id = AVITO_CATEGORY_IDS.get(cat)
    if category_id is None:
        return None
    q = str(model or "").strip()
    if not q:
        return None
    return {
        "locationId": city_id,
        "categoryId": str(category_id),
        "q": q,
        "page": "1",
        "limit": "50",
        "presentationType": "full",
    }


def live_search_params_from_key(key: FetchKey) -> dict[str, str] | None:
    """Совместимый query для первой модели ключа."""
    if not key[4]:
        return None
    return live_search_params_for_model(key, key[4][0])
