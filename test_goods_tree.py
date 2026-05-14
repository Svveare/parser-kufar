"""Тесты разбиения каталога по линейкам Apple."""
import unittest

from config import DEVICE_CATALOG
from goods_tree import (
    APPLE_LINES,
    LINE_BASIC,
    LINE_MAX,
    LINE_PRO,
    line_slug_for_catalog_entry,
)


class GoodsTreeTests(unittest.TestCase):
    def test_partition_covers_full_catalog(self) -> None:
        union = set()
        for slug in (LINE_BASIC, LINE_PRO, LINE_MAX):
            union.update(APPLE_LINES[slug])
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


if __name__ == "__main__":
    unittest.main()
