"""Дерево «Товары»: линейки Apple из DEVICE_CATALOG (для мастера выбора)."""
from __future__ import annotations

from config import DEVICE_CATALOG

# Короткие slug для callback (Telegram лимит 64 байта на callback_data)
LINE_BASIC = "b"
LINE_PRO = "p"
LINE_MAX = "m"

LINE_LABELS: dict[str, str] = {
    LINE_BASIC: "iPhone / mini / Plus / SE",
    LINE_PRO: "iPhone Pro",
    LINE_MAX: "iPhone Pro Max",
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
        buckets[line_slug_for_catalog_entry(d)].append(d)
    return {k: tuple(v) for k, v in buckets.items()}


APPLE_LINES: dict[str, tuple[str, ...]] = apple_lines_map()
