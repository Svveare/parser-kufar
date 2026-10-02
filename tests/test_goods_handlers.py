"""Проверка, что ветка «Товары» не падает с NameError."""
import unittest
from unittest.mock import patch

from bot_ui import country_keyboard, home_keyboard, home_text
from handlers.goods_ui import (
    _goods_categories_keyboard,
    _goods_categories_text,
    _goods_mobile_brands_keyboard,
    _goods_mobile_brands_text,
)
from product_catalog import model_label


class GoodsUiImportTests(unittest.TestCase):
    def test_category_root_builds(self):
        text = _goods_categories_text({"product_category": "phones"})
        kb = _goods_categories_keyboard({"role": "regular", "keywords": []})
        self.assertIn("категори", text.lower())
        self.assertIn("Смартфоны", text)
        self.assertTrue(kb.inline_keyboard)
        last_row = kb.inline_keyboard[-1]
        self.assertEqual(last_row[0].callback_data, "nav:home")

    def test_mobile_brands_screen_builds(self):
        text = _goods_mobile_brands_text()
        kb = _goods_mobile_brands_keyboard({"role": "regular", "keywords": []})
        self.assertIn("Смартфоны", text)
        self.assertTrue(kb.inline_keyboard)
        last_row = kb.inline_keyboard[-1]
        self.assertEqual(last_row[0].callback_data, "nav:goods")


class HomeUiTests(unittest.TestCase):
    def test_country_keyboard_has_flags(self) -> None:
        with patch("bot_ui.AVITO_ENABLED", True):
            kb = country_keyboard({"country": "by"})
        by_btn = kb.inline_keyboard[0][0].text
        ru_btn = kb.inline_keyboard[1][0].text
        self.assertIn("🇧🇾", by_btn)
        self.assertIn("🇷🇺", ru_btn)
        self.assertIn("Kufar", by_btn)

    def test_home_card_is_compact(self) -> None:
        user = {
            "active": True,
            "product_category": "phones",
            "keywords": ["iphone 15"],
            "max_price": 500,
            "city": "minsk",
            "memory_volumes": ["128"],
            "role": "regular",
        }
        text = home_text(user, is_new=False)
        self.assertIn("<b>Kufi</b>", text)
        self.assertIn("Kufar", text)
        self.assertIn("🔔 вкл.", text)
        self.assertIn("Смартфоны", text)
        self.assertNotIn("поиск телефонов", text)

    def test_home_filters_layout(self) -> None:
        user = {"active": True, "product_category": "phones"}
        kb = home_keyboard(is_admin=False, user=user)
        labels = [[btn.text for btn in row] for row in kb.inline_keyboard]
        self.assertIn(["⭐ VIP", "💡 Помощь"], labels)
        self.assertIn(["📱 Товары", "💰 Цена", "💾 Память"], labels)
        self.assertIn(["🌍 Страна", "📍 Город"], labels)


class ModelLabelTests(unittest.TestCase):
    def test_iphone_and_macbook(self) -> None:
        self.assertEqual(model_label("iphone 15 pro"), "iPhone 15 Pro")
        self.assertEqual(model_label("iphone se"), "iPhone SE")
        self.assertEqual(model_label("macbook air m1"), "MacBook Air M1")
        self.assertEqual(model_label("ipad pro 12.9"), "iPad Pro 12.9")
        self.assertEqual(model_label("apple watch series 7"), "Apple Watch Series 7")
        self.assertEqual(model_label("samsung galaxy s24 ultra"), "Galaxy S24 Ultra")
        self.assertEqual(model_label("samsung galaxy z flip 7 fe"), "Galaxy Z Flip 7 FE")


if __name__ == "__main__":
    unittest.main()
