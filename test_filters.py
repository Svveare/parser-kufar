"""Тесты правил отбора объявлений."""
import unittest

from filters import is_exchange_ad


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


if __name__ == "__main__":
    unittest.main()
