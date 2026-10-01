"""DB geo columns and update_geo."""
import os
import tempfile
import unittest

import db
from marketplace.types import COUNTRY_BY, COUNTRY_RU, SOURCE_AVITO, SOURCE_KUFAR


class GeoDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.SQLITE_PATH
        path = os.path.join(self._tmp.name, "test.db")
        db.SQLITE_PATH = path
        db.conn = db._connect()
        db.init_db()

    def tearDown(self) -> None:
        db.conn.close()
        db.SQLITE_PATH = self._old_path
        db.conn = db._connect()
        self._tmp.cleanup()

    def test_update_geo_sets_fields(self) -> None:
        chat_id = 424242
        db.add_user(chat_id)
        geo = db.update_geo(chat_id, 1, 37, "Барановичи")
        self.assertEqual(geo["city_rgn"], 1)
        self.assertEqual(geo["city_ar"], 37)
        self.assertEqual(geo["city_label"], "Барановичи")
        user = db.get_user(chat_id)
        assert user is not None
        self.assertEqual(user["city_rgn"], 1)
        self.assertEqual(user["city_ar"], 37)
        self.assertEqual(user["city_label"], "Барановичи")

    def test_update_country_by(self) -> None:
        chat_id = 525252
        db.add_user(chat_id)
        geo = db.update_country(chat_id, COUNTRY_BY)
        self.assertEqual(geo["country"], COUNTRY_BY)
        self.assertEqual(geo["primary_source"], SOURCE_KUFAR)
        user = db.get_user(chat_id)
        assert user is not None
        self.assertEqual(user["country"], COUNTRY_BY)
        self.assertEqual(user["primary_source"], SOURCE_KUFAR)

    def test_mark_seen_with_source(self) -> None:
        chat_id = 535353
        db.add_user(chat_id)
        db.mark_seen(chat_id, "https://www.kufar.by/item/x", source=SOURCE_KUFAR)
        seen = db.seen_links_for(
            chat_id,
            ["https://www.kufar.by/item/x"],
            source=SOURCE_KUFAR,
        )
        self.assertIn("https://www.kufar.by/item/x", seen)
        other = db.seen_links_for(
            chat_id,
            ["https://www.kufar.by/item/x"],
            source=SOURCE_AVITO,
        )
        self.assertEqual(other, set())

    def test_save_market_prices_with_source(self) -> None:
        db.save_market_prices(
            [("https://www.kufar.by/item/p", "iphone|15", 400, SOURCE_KUFAR)]
        )
        avg = db.avg_market_price("iphone|15", source=SOURCE_KUFAR)
        self.assertEqual(avg, 400)
        self.assertIsNone(db.avg_market_price("iphone|15", source=SOURCE_AVITO))

    def test_hot_lookup_queries_use_composite_indexes(self) -> None:
        market_plan = db.conn.execute(
            "EXPLAIN QUERY PLAN SELECT AVG(price) FROM market_prices "
            "WHERE device_key = ? AND source = ? AND sent_at >= ?",
            ("iphone|15", SOURCE_KUFAR, 0),
        ).fetchall()
        self.assertIn("idx_market_prices_lookup", " ".join(str(row) for row in market_plan))

    def test_update_country_ru_sets_avito_source(self) -> None:
        chat_id = 545454
        db.add_user(chat_id)
        geo = db.update_country(chat_id, COUNTRY_RU)
        self.assertEqual(geo["country"], COUNTRY_RU)
        self.assertEqual(geo["primary_source"], SOURCE_AVITO)

    def test_update_country_ru_converts_max_price_from_by(self) -> None:
        chat_id = 646464
        db.add_user(chat_id)
        db.update_max_price(chat_id, 5000)
        geo = db.update_country(chat_id, COUNTRY_RU)
        self.assertEqual(geo.get("max_price"), 50000)
        user = db.get_user(chat_id)
        assert user is not None
        self.assertEqual(user["max_price"], 50000)

    def test_update_country_by_from_ru_maps_preset(self) -> None:
        chat_id = 747474
        db.add_user(chat_id)
        db.update_max_price(chat_id, 25000)
        db.update_country(chat_id, COUNTRY_RU)
        geo = db.update_country(chat_id, COUNTRY_BY)
        self.assertEqual(geo.get("max_price"), 1500)


if __name__ == "__main__":
    unittest.main()
