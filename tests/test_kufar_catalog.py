"""Каталожные запросы Kufar: фасеты, ключ fetch, группировка пользователей."""
import unittest

from filters import (
    REJECT_COMPANY_AD,
    REJECT_THIN_JUNK,
    filter_reject_reason,
    matches_filters,
)
from kufar_catalog import (
    CITY_RGN,
    DEFAULT_CITY,
    KUFAR_PHONE_CAT,
    KUFAR_PRIVATE_OT,
    catalog_search_params,
    city_rgn,
    or_facet,
)
from kufar_fetch import normalize_listing
from marketplace.keys import fetch_key_for_user, group_users_by_fetch_key


class CatalogParamsTests(unittest.TestCase):
    def test_or_facet(self) -> None:
        self.assertEqual(or_facet((6085, 6087)), "v.or:6085,6087")
        self.assertEqual(or_facet((25,)), "v.or:25")
        self.assertEqual(or_facet([]), "")

    def test_city_rgn_live_api(self) -> None:
        self.assertEqual(city_rgn("minsk"), 7)
        self.assertEqual(city_rgn("brest"), 1)
        self.assertEqual(city_rgn("mogilev"), 4)
        self.assertEqual(city_rgn("vitebsk"), 6)
        self.assertEqual(city_rgn("gomel"), 2)
        self.assertEqual(city_rgn("grodno"), 3)
        self.assertEqual(city_rgn(None), CITY_RGN[DEFAULT_CITY])
        self.assertEqual(
            catalog_search_params(2, None, ["iphone 15"], ["256"])[0]["rgn"],
            "2",
        )
        self.assertEqual(
            catalog_search_params(3, None, ["iphone 15"], ["256"])[0]["rgn"],
            "3",
        )

    def test_ar_facet_for_settlement(self) -> None:
        rows = catalog_search_params(1, 37, ["iphone 15"], ["256"])
        self.assertEqual(rows[0]["rgn"], "1")
        self.assertEqual(rows[0]["ar"], "37")

    def test_iphone_15_and_pro_256_one_request(self) -> None:
        rows = catalog_search_params(
            7,
            None,
            ["iphone 15", "iphone 15 pro"],
            ["256"],
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["cat"], str(KUFAR_PHONE_CAT))
        self.assertEqual(row["ot"], str(KUFAR_PRIVATE_OT))
        self.assertEqual(row["rgn"], "7")
        self.assertEqual(row["ppm"], "v.or:25")
        self.assertIn("6085", row["phm"])
        self.assertIn("6087", row["phm"])
        self.assertTrue(row["phm"].startswith("v.or:"))
        self.assertNotIn("query", row)

    def test_several_memory_volumes_or(self) -> None:
        rows = catalog_search_params(7, None, ["iphone 15"], ["128", "256"])
        self.assertEqual(rows[0]["ppm"], "v.or:20,25")

    def test_512_plus_includes_tb(self) -> None:
        rows = catalog_search_params(7, None, ["iphone 15"], ["512+"])
        ppm = rows[0]["ppm"]
        self.assertIn("30", ppm)
        self.assertIn("35", ppm)

    def test_unmapped_model_skipped_no_query(self) -> None:
        rows = catalog_search_params(
            7,
            None,
            ["iphone 15", "not-a-real-phone"],
            ["64"],
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("phm", rows[0])
        self.assertNotIn("query", rows[0])
        self.assertEqual(
            catalog_search_params(7, None, ["not-a-real-phone"], ["64"]),
            [],
        )

    def test_full_catalog_one_phm_request(self) -> None:
        from product_catalog import PHONE_MODELS

        rows = catalog_search_params(7, None, PHONE_MODELS, ["256"])
        self.assertEqual(len(rows), 1)
        self.assertNotIn("query", rows[0])
        self.assertTrue(rows[0]["phm"].startswith("v.or:"))
        self.assertIn("4500", rows[0]["phm"])

    def test_laptops_apple_silicon_no_query_no_ppm(self) -> None:
        rows = catalog_search_params(
            7,
            None,
            ["macbook air m1", "macbook pro 14"],
            ["256"],
            category="laptops",
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["cat"], "16040")
        self.assertEqual(row["clb"], "5")
        self.assertTrue(row["clp"].startswith("v.or:"))
        self.assertNotIn("query", row)
        self.assertNotIn("ppm", row)
        self.assertNotIn("phm", row)

    def test_tablets_apple_no_query_no_ppm(self) -> None:
        rows = catalog_search_params(
            7,
            None,
            ["ipad air 4", "ipad pro 11"],
            ["256"],
            category="tablets",
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["cat"], "17050")
        self.assertEqual(row["phtbr"], "1")
        self.assertEqual(row["phto"], "5")
        self.assertNotIn("query", row)
        self.assertNotIn("ppm", row)
        self.assertNotIn("phm", row)

    def test_watches_apple_brand_no_query(self) -> None:
        rows = catalog_search_params(
            7,
            None,
            ["apple watch series 7"],
            ["64"],
            category="watches",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cat"], "17090")
        self.assertEqual(rows[0]["phswbr"], "5")
        self.assertNotIn("query", rows[0])
        self.assertNotIn("ppm", rows[0])


class FetchKeyTests(unittest.TestCase):
    def test_same_filters_same_key(self) -> None:
        a = {
            "keywords": ["iphone 15 pro", "iphone 15"],
            "memory_volumes": ["256"],
        }
        b = {
            "keywords": ["iphone 15", "iphone 15 pro"],
            "memory_volumes": ["256"],
        }
        self.assertEqual(fetch_key_for_user(a), fetch_key_for_user(b))
        self.assertEqual(fetch_key_for_user(a)[0], "kufar")
        self.assertEqual(fetch_key_for_user(a)[1], "phones")
        self.assertEqual(fetch_key_for_user(a)[2], "7")

    def test_same_model_different_city_two_keys(self) -> None:
        minsk = {
            "keywords": ["iphone 15"],
            "memory_volumes": ["256"],
            "city_rgn": 7,
            "city_ar": None,
        }
        brest = {
            "keywords": ["iphone 15"],
            "memory_volumes": ["256"],
            "city_rgn": 1,
            "city_ar": None,
        }
        key_m = fetch_key_for_user(minsk)
        key_b = fetch_key_for_user(brest)
        self.assertEqual(key_m[3], key_b[3])
        self.assertEqual(key_m[4], key_b[4])
        self.assertEqual(key_m[2], "7")
        self.assertEqual(key_b[2], "1")
        self.assertNotEqual(key_m, key_b)

    def test_settlement_ar_differs_from_region_only(self) -> None:
        region = {
            "keywords": ["iphone 15"],
            "memory_volumes": ["256"],
            "city_rgn": 1,
            "city_ar": None,
        }
        town = {
            "keywords": ["iphone 15"],
            "memory_volumes": ["256"],
            "city_rgn": 1,
            "city_ar": 37,
        }
        self.assertNotEqual(fetch_key_for_user(region), fetch_key_for_user(town))

    def test_group_two_users_one_key(self) -> None:
        users = [
            {"chat_id": 1, "keywords": ["iphone 15"], "memory_volumes": ["256"]},
            {"chat_id": 2, "keywords": ["iphone 15"], "memory_volumes": ["256"]},
            {"chat_id": 3, "keywords": ["iphone 14"], "memory_volumes": ["256"]},
            {"chat_id": 4, "keywords": [], "memory_volumes": ["256"]},
        ]
        groups = group_users_by_fetch_key(users)
        self.assertEqual(len(groups), 2)
        sizes = sorted(len(v) for v in groups.values())
        self.assertEqual(sizes, [1, 2])

    def test_phones_vs_watches_different_keys(self) -> None:
        phones = {
            "keywords": ["iphone 15"],
            "memory_volumes": ["256"],
            "product_category": "phones",
        }
        watches = {
            "keywords": ["apple watch series 7"],
            "memory_volumes": ["256"],
            "product_category": "watches",
        }
        key_p = fetch_key_for_user(phones)
        key_w = fetch_key_for_user(watches)
        self.assertEqual(key_p[0], "kufar")
        self.assertEqual(key_w[0], "kufar")
        self.assertEqual(key_p[1], "phones")
        self.assertEqual(key_w[1], "watches")
        self.assertEqual(key_w[5], ())
        self.assertNotEqual(key_p, key_w)


class CatalogFilterTests(unittest.TestCase):
    def test_company_ad_rejected(self) -> None:
        ad = {
            "title": "iPhone 15 256",
            "summary": "",
            "price": 800,
            "company_ad": True,
        }
        self.assertEqual(
            filter_reject_reason(
                ad,
                2000,
                ["iphone 15"],
                device_filter=False,
                memory_filter=False,
                company_filter=True,
                thin_junk=True,
            ),
            REJECT_COMPANY_AD,
        )

    def test_thin_junk_case_rejected(self) -> None:
        ad = {
            "title": "Чехол на iPhone 15",
            "summary": "",
            "price": 20,
            "company_ad": False,
        }
        self.assertEqual(
            filter_reject_reason(
                ad,
                2000,
                ["iphone 15"],
                device_filter=False,
                memory_filter=False,
                company_filter=True,
                thin_junk=True,
            ),
            REJECT_THIN_JUNK,
        )

    def test_private_phone_passes_without_device_filter(self) -> None:
        ad = {
            "title": "iPhone 15 256",
            "summary": "",
            "price": 800,
            "company_ad": False,
        }
        self.assertTrue(
            matches_filters(
                ad,
                2000,
                ["iphone 15"],
                device_filter=False,
                memory_filter=False,
                company_filter=True,
                thin_junk=True,
            )
        )


class CatalogMatchSafetyTests(unittest.TestCase):
    def test_other_brands_rejected_when_apple_samsung_selected(self) -> None:
        from user_matching import match_ads_for_user

        user = {
            "chat_id": 1,
            "role": "regular",
            "keywords": list(
                [
                    "iphone 15",
                    "samsung galaxy s24",
                ]
            ),
            "memory_volumes": ["256"],
            "max_price": 2000,
        }
        ads = [
            {
                "title": "Xiaomi Redmi Note 13 256",
                "summary": "",
                "price": 400,
                "company_ad": False,
            },
            {
                "title": "Honor 90 256Gb",
                "summary": "",
                "price": 350,
                "company_ad": False,
            },
            {
                "title": "iPhone 15 256",
                "summary": "Модель: iPhone 15",
                "price": 800,
                "company_ad": False,
            },
        ]
        matched = match_ads_for_user(user, ads, {})
        self.assertEqual([ad["title"] for ad in matched], ["iPhone 15 256"])

    def test_macbook_selected_rejects_phone(self) -> None:
        from user_matching import match_ads_for_user

        user = {
            "chat_id": 1,
            "role": "regular",
            "product_category": "laptops",
            "keywords": ["macbook air m1"],
            "memory_volumes": ["64"],
            "max_price": 4000,
        }
        ads = [
            {
                "title": "MacBook Air M1 8/256",
                "summary": "",
                "price": 1200,
                "company_ad": False,
            },
            {
                "title": "iPhone 15 256",
                "summary": "",
                "price": 800,
                "company_ad": False,
            },
        ]
        matched = match_ads_for_user(user, ads, {})
        self.assertEqual([ad["title"] for ad in matched], ["MacBook Air M1 8/256"])


class NormalizeListingTests(unittest.TestCase):
    def test_reads_phones_model_and_company_flag(self) -> None:
        raw = {
            "ad_id": 1,
            "ad_link": "https://www.kufar.by/item/1",
            "subject": "iPhone 15",
            "price_byn": "80000",
            "company_ad": False,
            "ad_parameters": [
                {"p": "phones_model", "vl": "iPhone 15", "v": "6085"},
                {"p": "phablet_phones_memory", "vl": "256 ГБ", "v": "25"},
                {"p": "condition", "vl": "Б/у", "v": "1"},
            ],
        }
        ad = normalize_listing(raw)
        assert ad is not None
        self.assertEqual(ad["phone_model"], "iPhone 15")
        self.assertEqual(ad["phone_memory"], "256 ГБ")
        self.assertEqual(ad["memory_gb"], 256)
        self.assertFalse(ad["company_ad"])
        self.assertIn("Модель: iPhone 15", ad["summary"])


if __name__ == "__main__":
    unittest.main()
