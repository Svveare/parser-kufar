"""Тесты правил отбора объявлений."""
import unittest

from filters import ad_device_key, is_exchange_ad, matches_filters


def _ad(
    *,
    title: str = "",
    summary: str = "",
    description: str = "",
) -> dict:
    return {
        "title": title,
        "summary": summary,
        "description": description,
        "price": 500,
        "link": "https://example.com/ad/1",
    }


class ExchangeAdTests(unittest.TestCase):
    def test_screenshot_refusal_not_exchange(self) -> None:
        """Типичный шаблон продавца: ОБМЕН НЕ ИНТЕРЕСЕН (не «интересует»)."""
        ad = _ad(
            title="iphone 11",
            description="Ассортимент обновляется. ОБМЕН НЕ ИНТЕРЕСЕН. Краткое описание:",
        )
        self.assertFalse(is_exchange_ad(ad))

    def test_refusal_obmen_ne_with_punctuation(self) -> None:
        ad = _ad(description="обмен не интересен.")
        self.assertFalse(is_exchange_ad(ad))

    def test_refusal_regex_obmen_ne(self) -> None:
        ad = _ad(description="мы работаем без скидок. обмен не рассматривается")
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
        """Одно слово «обмен» без позитивной формулировки не считаем обменным."""
        ad = _ad(description="продам iphone, без дополнительных условий обмен")
        self.assertFalse(is_exchange_ad(ad))

    def test_positive_interesuet_obmen(self) -> None:
        ad = _ad(description="интересует обмен на более новую модель")
        self.assertTrue(is_exchange_ad(ad))


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
            )
        )

    def test_samsung_flip_short_title_matches_catalog_key(self) -> None:
        ad = _ad(title="Z Flip 7", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy z flip 7")

    def test_samsung_fold_compact_title_matches_catalog_key(self) -> None:
        ad = _ad(title="Samsung zfold6", summary="Смартфон")
        self.assertEqual(ad_device_key(ad), "samsung galaxy z fold 6")


if __name__ == "__main__":
    unittest.main()
