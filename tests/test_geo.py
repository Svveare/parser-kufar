"""Geo lookup: search_places and local filter."""
import unittest

from kufar_geo import search_places
from user_matching import geo_location_matches


class GeoSearchTests(unittest.TestCase):
    def test_baranovichi(self) -> None:
        hits = search_places("барановичи")
        self.assertTrue(hits)
        self.assertEqual(hits[0].label, "Барановичи")
        self.assertEqual(hits[0].rgn, 1)
        self.assertEqual(hits[0].ar, 37)

    def test_bobruisk(self) -> None:
        hits = search_places("бобруйск")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].label, "Бобруйск")
        self.assertEqual(hits[0].ar, 12)

    def test_minsk_shortcut(self) -> None:
        hits = search_places("минск")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].rgn, 7)
        self.assertIsNone(hits[0].ar)


class GeoLocationFilterTests(unittest.TestCase):
    def test_whole_region_skips_filter(self) -> None:
        user = {"city_ar": None, "city_label": "Брест"}
        ad = {"title": "iPhone", "location": "Пинск"}
        self.assertTrue(geo_location_matches(ad, user))

    def test_small_city_requires_token(self) -> None:
        user = {"city_ar": 37, "city_label": "Барановичи"}
        ok = {"title": "iPhone 15", "location": "Брестская область, Барановичи"}
        bad = {"title": "iPhone 15", "location": "Брестская область, Брест"}
        self.assertTrue(geo_location_matches(ok, user))
        self.assertFalse(geo_location_matches(bad, user))


if __name__ == "__main__":
    unittest.main()
