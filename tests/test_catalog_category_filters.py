from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ozon_app.catalog_category_filters import (
    apply_category_filter,
    category_filter_button_text,
    category_filter_scope_text,
    delete_catalog_product,
)
from ozon_app.database import Database
from ozon_app.models import Product
from ozon_app.ui import CATEGORY_EMPTY


class CategoryFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            SimpleNamespace(article="A", category="БРГС"),
            SimpleNamespace(article="B", category="ГС"),
            SimpleNamespace(article="C", category="Бант"),
            SimpleNamespace(article="D", category=""),
        ]

    def test_empty_selection_means_all_in_both_modes(self) -> None:
        self.assertEqual(
            [row.article for row in apply_category_filter(self.rows, set())],
            ["A", "B", "C", "D"],
        )
        self.assertEqual(
            [row.article for row in apply_category_filter(self.rows, set(), exclude=True)],
            ["A", "B", "C", "D"],
        )

    def test_include_mode_keeps_all_selected_categories(self) -> None:
        visible = apply_category_filter(self.rows, {"БРГС", "Бант"})
        self.assertEqual([row.article for row in visible], ["A", "C"])

    def test_exclude_mode_removes_all_selected_categories(self) -> None:
        visible = apply_category_filter(self.rows, {"БРГС", "Бант"}, exclude=True)
        self.assertEqual([row.article for row in visible], ["B", "D"])

    def test_empty_category_uses_visible_label(self) -> None:
        visible = apply_category_filter(self.rows, {CATEGORY_EMPTY})
        self.assertEqual([row.article for row in visible], ["D"])

    def test_filter_labels_are_clear(self) -> None:
        self.assertEqual(category_filter_button_text(set()), "Все категории")
        self.assertIn("3", category_filter_button_text({"БРГС", "ГС", "Бант"}))
        self.assertEqual(
            category_filter_scope_text({"БРГС"}, exclude=True),
            "кроме категорий: БРГС",
        )


class CatalogDeletionTests(unittest.TestCase):
    def test_delete_removes_only_current_catalog_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "app.db")
            database.save_products(
                [
                    Product(
                        article="SKU-1",
                        name="Товар 1",
                        material_cost=100,
                        labor_cost=20,
                        category="БРГС",
                    ),
                    Product(
                        article="SKU-2",
                        name="Товар 2",
                        material_cost=80,
                        labor_cost=10,
                        category="ГС",
                    ),
                ],
                source="Тест",
            )

            self.assertTrue(delete_catalog_product(database, "SKU-1"))
            self.assertEqual(
                [product.article for product in database.list_products()],
                ["SKU-2"],
            )
            self.assertFalse(delete_catalog_product(database, "SKU-1"))


if __name__ == "__main__":
    unittest.main()
