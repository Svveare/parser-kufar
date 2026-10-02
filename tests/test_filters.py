"""Тесты правил отбора объявлений."""
import unittest

from filters import (
    REJECT_DEVICE_NOT_SELECTED,
    REJECT_MEMORY_NOT_SELECTED,
    REJECT_NOT_WHOLE_PHONE,
    REJECT_NO_KEYWORDS,
    REJECT_NOT_SALE,
    ad_device_key,
    ad_memory_gb,
    exchange_reject_reason,
    filter_reject_reason,
    is_exchange_ad,
    is_whole_phone_listing,
    matches_filters,
    memory_matches_ad,
    parse_memory_gb_text,
)


def _ad(
    *,
    title: str = "",
    summary: str = "",
    description: str = "",
    phone_model: str = "",
    phone_memory: str = "",
    memory_gb: int | None = None,
    price: int = 500,
) -> dict:
    ad = {
        "title": title,
        "summary": summary,
        "description": description,
        "phone_model": phone_model,
        "phone_memory": phone_memory,
        "price": price,
        "link": "https://example.com/ad/1",
    }
    if memory_gb is not None:
        ad["memory_gb"] = memory_gb
    return ad


class ExchangeAdTests(unittest.TestCase):
    def test_screenshot_refusal_not_exchange(self) -> None:
        """Типичный шаблон продавца: ОБМЕН НЕ ИНТЕРЕСЕН (не «интересует»)."""
        ad = _ad(
            title="iphone 11",
            description=(
                "Ассортимент обновляется. ОБМЕН НЕ ИНТЕРЕСЕН. Краткое описание:"
            ),
        )
        self.assertFalse(is_exchange_ad(ad))
        self.assertEqual(exchange_reject_reason(ad), "exchange_refusal")

    def test_refusal_obmen_ne_with_punctuation(self) -> None:
        ad = _ad(description="обмен не интересен.")
        self.assertFalse(is_exchange_ad(ad))

    def test_refusal_regex_obmen_ne(self) -> None:
        ad = _ad(description="мы работаем без скидок. обмен не рассматривается")
        self.assertFalse(is_exchange_ad(ad))

    def test_refusal_all_caps_multiline(self) -> None:
        ad = _ad(
            description=(
                "Мы работаем БЕЗ СКИДОК И ТОРГА.\n"
                "ОБМЕН НЕ ИНТЕРЕСЕН.\n"
                "Состояние Приемлемое"
            ),
        )
        self.assertFalse(is_exchange_ad(ad))

    def test_bez_obmena(self) -> None:
        ad = _ad(description="торг без обмена")
        self.assertFalse(is_exchange_ad(ad))

    def test_positive_gotov_k_obmenu(self) -> None:
        ad = _ad(description="продам, готов к обмену на 13 pro")
        self.assertTrue(is_exchange_ad(ad))

    def test_positive_tolko_obmen(self) -> None:
        ad = _ad(title="iphone 12", description="только обмен")
        self.assertTrue(is_exchange_ad(ad))

    def test_bare_obmen_word_not_enough(self) -> None:
        ad = _ad(description="продам iphone, без дополнительных условий обмен")
        self.assertFalse(is_exchange_ad(ad))

    def test_positive_interesuet_obmen(self) -> None:
        ad = _ad(description="интересует обмен на более новую модель")
        self.assertTrue(is_exchange_ad(ad))


class SmartFilterTests(unittest.TestCase):
    def test_strict_filtering_off_allows_junk_without_device_reject(self) -> None:
        """Обычный аккаунт: без smart_filtering коробка не режется по not_whole_phone."""
        ad = _ad(
            title="Коробка от телефона Apple iPhone 11",
            summary="Смартфон",
        )
        self.assertIsNone(
            filter_reject_reason(
                ad,
                1000,
                ["iphone 11"],
                smart_filtering=False,
                device_filter=True,
            )
        )

    def test_strict_filtering_on_rejects_box(self) -> None:
        ad = _ad(
            title="Коробка от телефона Apple iPhone 11",
            summary="Смартфон",
        )
        self.assertEqual(
            filter_reject_reason(
                ad,
                1000,
                ["iphone 11"],
                smart_filtering=True,
                device_filter=True,
            ),
            REJECT_NOT_WHOLE_PHONE,
        )

    def test_accessory_in_title_rejected(self) -> None:
        ad = _ad(title="чехол для iphone 11", summary="Смартфон")
        self.assertFalse(is_whole_phone_listing(ad))
        self.assertEqual(
            filter_reject_reason(
                ad, 1000, ["iphone 11"], smart_filtering=True, device_filter=True
            ),
            REJECT_NOT_WHOLE_PHONE,
        )

    def test_not_sale_ne_kuplu_not_rejected(self) -> None:
        ad = _ad(title="iphone 11", summary="не куплю б/у, только продажа")
        self.assertTrue(
            matches_filters(
                ad, 1000, ["iphone 11"], smart_filtering=True, device_filter=True
            )
        )

    def test_not_sale_kuplu_rejected(self) -> None:
        ad = _ad(title="куплю iphone 11", summary="срочно")
        self.assertFalse(
            matches_filters(
                ad, 1000, ["iphone 11"], smart_filtering=True, device_filter=True
            )
        )
        self.assertEqual(
            filter_reject_reason(
                ad, 1000, ["iphone 11"], smart_filtering=True, device_filter=True
            ),
            REJECT_NOT_SALE,
        )

    def test_empty_keywords_rejected(self) -> None:
        ad = _ad(title="iphone 11", summary="Смартфон")
        self.assertFalse(
            matches_filters(ad, 1000, [], smart_filtering=True, device_filter=True)
        )
        self.assertEqual(
            filter_reject_reason(
                ad, 1000, [], smart_filtering=True, device_filter=True
            ),
            REJECT_NO_KEYWORDS,
        )

    def test_vip_special_modes_respect_selected_devices(self) -> None:
        samsung = _ad(title="Samsung Galaxy S25", summary="Смартфон")
        iphone = _ad(title="iphone 11", summary="Смартфон")
        keywords = ["iphone 11"]
        self.assertFalse(
            matches_filters(
                samsung,
                99_999_999,
                keywords,
                smart_filtering=True,
                device_filter=True,
            )
        )
        self.assertEqual(
            filter_reject_reason(
                samsung,
                99_999_999,
                keywords,
                smart_filtering=True,
                device_filter=True,
            ),
            REJECT_DEVICE_NOT_SELECTED,
        )
        self.assertTrue(
            matches_filters(
                iphone,
                99_999_999,
                keywords,
                smart_filtering=True,
                device_filter=True,
            )
        )

    def test_parent_keyword_matches_variant(self) -> None:
        ad = _ad(title="Samsung Galaxy Z Flip 7", summary="Смартфон")
        self.assertTrue(
            matches_filters(
                ad,
                2000,
                ["samsung galaxy z flip"],
                smart_filtering=True,
                device_filter=True,
            )
        )

    def test_screenshot_boards_below_market_rejected(self) -> None:
        ad = _ad(
            title="Платы iPhone 12 Pro / 12 Mini (Заблокированные)",
            summary="Смартфон",
            description="для swap, unlocking, donor parts",
        )
        self.assertFalse(is_whole_phone_listing(ad))
        self.assertEqual(
            filter_reject_reason(
                ad, 99_999_999, [], smart_filtering=True, device_filter=False
            ),
            REJECT_NOT_WHOLE_PHONE,
        )

    def test_screenshot_parts_iphone11_rejected(self) -> None:
        ad = _ad(
            title="Запчасти для iPhone 11",
            summary="Смартфон",
            description="1 плата на icloud, 1акб, 2 корпуса, камеры",
        )
        self.assertEqual(
            filter_reject_reason(
                ad, 99_999_999, [], smart_filtering=True, device_filter=False
            ),
            REJECT_NOT_WHOLE_PHONE,
        )


class JunkListingTests(unittest.TestCase):
    """Кейсы по реальным ложным срабатываниям из рассылки."""

    def test_screen_protector_rejected(self) -> None:
        ad = _ad(
            title="Защитные стёкла для iPhone 12/12 Pro",
            summary="Смартфон",
            price=5,
        )
        self.assertFalse(is_whole_phone_listing(ad))

    def test_box_only_rejected(self) -> None:
        ad = _ad(
            title="Коробка от телефона Apple iPhone 11",
            summary="Смартфон",
            price=15,
        )
        self.assertFalse(is_whole_phone_listing(ad))

    def test_clone_rejected(self) -> None:
        ad = _ad(
            title="iphone 14 pro max clone",
            summary="Смартфон",
            description="копия, в пользовании неделю",
            price=200,
        )
        self.assertFalse(is_whole_phone_listing(ad))

    def test_battery_rejected(self) -> None:
        ad = _ad(
            title="Аккумулятор Apple iPhone усиленная батарея",
            summary="Смартфон",
            price=50,
        )
        self.assertFalse(is_whole_phone_listing(ad))

    def test_generic_iphone_title_with_model_in_summary(self) -> None:
        ad = _ad(
            title="Айфон",
            summary="Смартфон · Модель: iPhone 13 128Gb",
            phone_model="iPhone 13 128Gb",
            price=550,
        )
        self.assertEqual(ad_device_key(ad), "iphone 13")
        self.assertTrue(
            matches_filters(
                ad,
                1000,
                ["iphone 13"],
                memory_volumes=["128"],
                smart_filtering=True,
                device_filter=True,
            )
        )


class MemoryFilterTests(unittest.TestCase):
    def test_parse_128_gb_cyrillic(self) -> None:
        self.assertEqual(parse_memory_gb_text("Память: 128 Гб"), 128)

    def test_parse_256_gb_latin(self) -> None:
        self.assertEqual(parse_memory_gb_text("256GB"), 256)

    def test_parse_1_tb(self) -> None:
        self.assertEqual(parse_memory_gb_text("1 ТБ"), 1024)

    def test_512_plus_matches_1024(self) -> None:
        ad = _ad(memory_gb=1024, title="iphone 15", summary="Смартфон")
        self.assertTrue(memory_matches_ad(ad, {"512+"}))

    def test_unknown_memory_passes_any_selection(self) -> None:
        ad = _ad(title="iphone 11", summary="Смартфон")
        self.assertIsNone(ad_memory_gb(ad))
        self.assertTrue(memory_matches_ad(ad, {"128"}))

    def test_known_64_rejected_when_only_128_selected(self) -> None:
        ad = _ad(title="iphone 11", summary="Память: 64 Гб")
        self.assertEqual(ad_memory_gb(ad), 64)
        self.assertFalse(memory_matches_ad(ad, {"128"}))
        self.assertEqual(
            filter_reject_reason(
                ad,
                1000,
                ["iphone 11"],
                memory_volumes=["128"],
                smart_filtering=True,
                device_filter=True,
            ),
            REJECT_MEMORY_NOT_SELECTED,
        )

    def test_known_128_passes_when_128_selected(self) -> None:
        ad = _ad(title="iphone 11", summary="128 Гб")
        self.assertTrue(
            matches_filters(
                ad,
                1000,
                ["iphone 11"],
                memory_volumes=["128"],
                smart_filtering=True,
                device_filter=True,
            )
        )


class SamsungFilterTests(unittest.TestCase):
    def test_samsung_ultra_short_title_matches_catalog_key(self) -> None:
        ad = _ad(title="Samsung S23 Ultra", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy s23 ultra")

    def test_samsung_plus_symbol_matches_catalog_key(self) -> None:
        ad = _ad(title="Galaxy S24+", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy s24 plus")

    def test_samsung_selected_keyword_passes_filters(self) -> None:
        ad = _ad(title="Samsung Galaxy S25", summary="Смартфон")
        self.assertTrue(
            matches_filters(
                ad,
                1000,
                ["samsung galaxy s25"],
                smart_filtering=True,
                device_filter=True,
            )
        )

    def test_wrong_model_rejected(self) -> None:
        ad = _ad(title="Samsung Galaxy S24", summary="Смартфон")
        self.assertEqual(
            filter_reject_reason(
                ad,
                1000,
                ["samsung galaxy s25"],
                smart_filtering=True,
                device_filter=True,
            ),
            REJECT_DEVICE_NOT_SELECTED,
        )

    def test_samsung_flip_short_title_matches_catalog_key(self) -> None:
        ad = _ad(title="Z Flip 7", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy z flip 7")

    def test_samsung_fold_compact_title_matches_catalog_key(self) -> None:
        ad = _ad(title="Samsung zfold6", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy z fold 6")


if __name__ == "__main__":
    unittest.main()
