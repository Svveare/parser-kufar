"""Дерево «Товары»: модели Apple и Samsung из DEVICE_CATALOG."""
from __future__ import annotations

from config import DEVICE_CATALOG

# Короткие slug для callback (Telegram лимит 64 байта на callback_data)
LINE_BASIC = "b"
LINE_PRO = "p"
LINE_MAX = "m"
SAMSUNG_SERIES_S = "s"
SAMSUNG_SERIES_FLIP = "f"
SAMSUNG_SERIES_FOLD = "d"
SAMSUNG_LINE_BASE = "b"
SAMSUNG_LINE_PLUS = "p"
SAMSUNG_LINE_ULTRA = "u"
SAMSUNG_LINE_FLIP = "f"
SAMSUNG_LINE_FOLD = "d"

LINE_LABELS: dict[str, str] = {
    LINE_BASIC: "iPhone / mini / Plus / SE",
    LINE_PRO: "iPhone Pro",
    LINE_MAX: "iPhone Pro Max",
}

SAMSUNG_SERIES_LABELS: dict[str, str] = {
    SAMSUNG_SERIES_S: "Galaxy S",
    SAMSUNG_SERIES_FLIP: "Galaxy Z Flip",
    SAMSUNG_SERIES_FOLD: "Galaxy Z Fold",
}

SAMSUNG_LINE_LABELS: dict[str, str] = {
    SAMSUNG_LINE_BASE: "Galaxy S",
    SAMSUNG_LINE_PLUS: "Galaxy S+",
    SAMSUNG_LINE_ULTRA: "Galaxy S Ultra",
    SAMSUNG_LINE_FLIP: "Galaxy Z Flip",
    SAMSUNG_LINE_FOLD: "Galaxy Z Fold",
}

SAMSUNG_SERIES_LINES: dict[str, tuple[str, ...]] = {
    SAMSUNG_SERIES_S: (SAMSUNG_LINE_BASE, SAMSUNG_LINE_PLUS, SAMSUNG_LINE_ULTRA),
    SAMSUNG_SERIES_FLIP: (SAMSUNG_LINE_FLIP,),
    SAMSUNG_SERIES_FOLD: (SAMSUNG_LINE_FOLD,),
}

GOODS_PER_PAGE = 8


def line_slug_for_catalog_entry(device: str) -> str:
    """Отнести строку каталога к линейке: Pro Max, Pro (не Max), остальное — базовая линейка."""
    s = " ".join((device or "").lower().split())
    if "pro max" in s:
        return LINE_MAX
    parts = s.split()
    if parts and parts[-1] == "pro":
        return LINE_PRO
    return LINE_BASIC


def apple_lines_map() -> dict[str, tuple[str, ...]]:
    """Все модели из DEVICE_CATALOG, сгруппированные по линейке (порядок как в каталоге)."""
    buckets: dict[str, list[str]] = {LINE_BASIC: [], LINE_PRO: [], LINE_MAX: []}
    for d in DEVICE_CATALOG:
        if not d.lower().startswith("iphone"):
            continue
        buckets[line_slug_for_catalog_entry(d)].append(d)
    return {k: tuple(v) for k, v in buckets.items()}


def samsung_line_slug_for_catalog_entry(device: str) -> str | None:
    s = " ".join((device or "").lower().split())
    if s.startswith("samsung galaxy z flip"):
        return SAMSUNG_LINE_FLIP
    if s.startswith("samsung galaxy z fold"):
        return SAMSUNG_LINE_FOLD
    if not s.startswith("samsung galaxy s"):
        return None
    if " ultra" in s:
        return SAMSUNG_LINE_ULTRA
    if " plus" in s:
        return SAMSUNG_LINE_PLUS
    return SAMSUNG_LINE_BASE


def samsung_lines_map() -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {
        SAMSUNG_LINE_BASE: [],
        SAMSUNG_LINE_PLUS: [],
        SAMSUNG_LINE_ULTRA: [],
        SAMSUNG_LINE_FLIP: [],
        SAMSUNG_LINE_FOLD: [],
    }
    for d in DEVICE_CATALOG:
        slug = samsung_line_slug_for_catalog_entry(d)
        if slug is not None:
            buckets[slug].append(d)
    return {k: tuple(v) for k, v in buckets.items()}


APPLE_LINES: dict[str, tuple[str, ...]] = apple_lines_map()
SAMSUNG_LINES: dict[str, tuple[str, ...]] = samsung_lines_map()
