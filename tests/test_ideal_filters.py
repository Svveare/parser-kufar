"""Тесты VIP-потока «Идеальные (бета)»."""
import unittest

from filters import (
    REJECT_IDEAL_BAD_CONDITION,
    REJECT_IDEAL_BATTERY_LOW,
    REJECT_IDEAL_BATTERY_UNKNOWN,
    REJECT_IDEAL_DEFECT_TERM,
    REJECT_IDEAL_NO_CONDITION,
    REJECT_NOT_WHOLE_PHONE,
    filter_reject_reason,
    ideal_passes,
    ideal_reject_reason,
    is_whole_phone_listing,
    parse_battery_percents,
)


def _ad(
    *,
    title: str = "iPhone 13",
    summary: str = "Смартфон",
    description: str = "",
    condition_label: str = "",
    price: int = 500,
) -> dict:
    return {
        "title": title,
        "summary": summary,
        "description": description,
        "condition_label": condition_label,
        "phone_model": "iPhone 13",
        "phone_memory": "128 GB",
        "memory_gb": 128,
        "price": price,
        "link": "https://example.com/ad/1",
    }


class IdealBatteryParserTests(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(parse_battery_percents("акб 88%"), [88])
        self.assertEqual(parse_battery_percents("ёмкость 90"), [90])
        self.assertIn(82, parse_battery_percents("battery health 82"))


class IdealPreTests(unittest.TestCase):
    def test_excellent_pre_ok(self) -> None:
        ad = _ad(condition_label="Отличное")
        self.assertTrue(ideal_passes(ad, stage="pre"))

    def test_no_condition_pre_reject(self) -> None:
        ad = _ad()
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=False),
            REJECT_IDEAL_NO_CONDITION,
        )

    def test_satisfactory_pre_reject(self) -> None:
        ad = _ad(condition_label="Удовлетворительное")
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=False),
            REJECT_IDEAL_BAD_CONDITION,
        )

    def test_used_condition_pre_ok(self) -> None:
        ad = _ad(
            title="iPhone 14 Pro Max Идеальный",
            summary="Смартфон · Состояние: Б/у",
            condition_label="Б/у",
        )
        self.assertTrue(ideal_passes(ad, stage="pre"))

    def test_ideal_in_title_pre_ok_without_condition_field(self) -> None:
        ad = _ad(
            title="iPhone 14 Pro Max Идеальный",
            summary="Смартфон",
        )
        self.assertTrue(ideal_passes(ad, stage="pre"))


class IdealStrictTests(unittest.TestCase):
    def test_excellent_battery_strict_ok(self) -> None:
        ad = _ad(
            condition_label="Отличное",
            description="Состояние отличное, ёмкость АКБ 88%",
        )
        self.assertTrue(ideal_passes(ad, stage="strict"))

    def test_broken_screen_strict_reject(self) -> None:
        ad = _ad(
            condition_label="Хорошее",
            description="разбит экран, акб 90%",
        )
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=True),
            REJECT_IDEAL_DEFECT_TERM,
        )

    def test_low_battery_strict_reject(self) -> None:
        ad = _ad(
            condition_label="Отличное",
            description="акб 70%",
        )
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=True),
            REJECT_IDEAL_BATTERY_LOW,
        )

    def test_no_battery_strict_reject(self) -> None:
        ad = _ad(
            condition_label="Отличное",
            description="батарея отличная, без цифр",
        )
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=True),
            REJECT_IDEAL_BATTERY_UNKNOWN,
        )

    def test_scratches_allowed(self) -> None:
        ad = _ad(
            condition_label="Хорошее",
            description="царапины на рамке, акб 80%",
        )
        self.assertTrue(ideal_passes(ad, stage="strict"))

    def test_kufar_used_listing_strict_ok(self) -> None:
        ad = _ad(
            title="iPhone 14 Pro Max Идеальный",
            summary="Смартфон · Состояние: Б/у",
            condition_label="Б/у",
            description=(
                "Состояние идеальное. Аккумулятор оригинальный 87%. "
                "Никогда не вскрывался и не ремонтировался."
            ),
        )
        self.assertTrue(ideal_passes(ad, stage="strict"))

    def test_akb_without_percent_strict_ok(self) -> None:
        ad = _ad(
            condition_label="Б/у",
            description="все работает, АКБ 79, без ремонта",
        )
        self.assertTrue(ideal_passes(ad, stage="strict"))

    def test_replaced_display_strict_reject(self) -> None:
        ad = _ad(
            condition_label="Отличное",
            description="менял дисплей, акб 85%",
        )
        self.assertEqual(
            ideal_reject_reason(ad, require_full_text=True),
            REJECT_IDEAL_DEFECT_TERM,
        )


class IdealBaseFilterTests(unittest.TestCase):
    def test_box_not_whole_phone(self) -> None:
        ad = _ad(
            title="Коробка от телефона Apple iPhone 11",
            condition_label="Отличное",
            description="акб 90%",
        )
        self.assertFalse(is_whole_phone_listing(ad))
        self.assertEqual(
            filter_reject_reason(
                ad,
                99_999_999,
                ["iphone 11"],
                smart_filtering=True,
                device_filter=True,
                skip_new_phone=True,
            ),
            REJECT_NOT_WHOLE_PHONE,
        )


if __name__ == "__main__":
    unittest.main()
