"""Тесты разбиения каталога по линейкам товаров."""
import unittest

from config import DEVICE_CATALOG
from goods_tree import (
    APPLE_LINES,
    LINE_BASIC,
    LINE_MAX,
    LINE_PRO,
    SAMSUNG_LINE_BASE,
    SAMSUNG_LINE_FLIP,
    SAMSUNG_LINE_FOLD,
    SAMSUNG_LINE_PLUS,
    SAMSUNG_LINE_ULTRA,
    SAMSUNG_LINES,
    line_slug_for_catalog_entry,
    samsung_line_slug_for_catalog_entry,
)


class GoodsTreeTests(unittest.TestCase):
    def test_partition_covers_full_catalog(self) -> None:
        union = set()
        for slug in (LINE_BASIC, LINE_PRO, LINE_MAX):
            union.update(APPLE_LINES[slug])
        for slug in (
            SAMSUNG_LINE_BASE,
            SAMSUNG_LINE_PLUS,
            SAMSUNG_LINE_ULTRA,
            SAMSUNG_LINE_FLIP,
            SAMSUNG_LINE_FOLD,
        ):
            union.update(SAMSUNG_LINES[slug])
        self.assertEqual(union, set(DEVICE_CATALOG))

    def test_partitions_disjoint(self) -> None:
        a, p, m = (
            set(APPLE_LINES[LINE_BASIC]),
            set(APPLE_LINES[LINE_PRO]),
            set(APPLE_LINES[LINE_MAX]),
        )
        self.assertTrue(a.isdisjoint(p))
        self.assertTrue(a.isdisjoint(m))
        self.assertTrue(p.isdisjoint(m))

    def test_pro_max_vs_pro(self) -> None:
        self.assertEqual(line_slug_for_catalog_entry("iphone 12 pro max"), LINE_MAX)
        self.assertEqual(line_slug_for_catalog_entry("iphone 12 pro"), LINE_PRO)
        self.assertEqual(line_slug_for_catalog_entry("iphone 12"), LINE_BASIC)

    def test_samsung_base_plus_ultra(self) -> None:
        self.assertEqual(samsung_line_slug_for_catalog_entry("samsung galaxy s24"), SAMSUNG_LINE_BASE)
        self.assertEqual(samsung_line_slug_for_catalog_entry("samsung galaxy s24 plus"), SAMSUNG_LINE_PLUS)
        self.assertEqual(samsung_line_slug_for_catalog_entry("samsung galaxy s24 ultra"), SAMSUNG_LINE_ULTRA)

    def test_samsung_flip_fold(self) -> None:
        self.assertEqual(samsung_line_slug_for_catalog_entry("samsung galaxy z flip 7"), SAMSUNG_LINE_FLIP)
        self.assertEqual(samsung_line_slug_for_catalog_entry("samsung galaxy z fold 7"), SAMSUNG_LINE_FOLD)


if __name__ == "__main__":
    unittest.main()
