from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ozon_app.calculator import calculate_scenario
from ozon_app.database import Database
from ozon_app.models import Product, ProductResult
from ozon_app.ui import (
    CATEGORY_ALL,
    filter_product_results,
    filter_scenario_rows,
)


class CategoryFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = [
            ProductResult(
                "A-10",
                "Товар A",
                60,
                40,
                category="Горшки",
                units=2,
                revenue_no_points=500,
                financial_result=300,
            ),
            ProductResult(
                "B-20",
                "Товар B",
                40,
                10,
                category="Банты",
                units=5,
                revenue_no_points=900,
                financial_result=600,
            ),
            ProductResult(
                "A-30",
                "Без категории",
                20,
                10,
                units=1,
                revenue_no_points=100,
                financial_result=50,
            ),
        ]

    def test_overview_filters_category_and_article_then_sorts_metrics(self) -> None:
        filtered = filter_product_results(
            self.results,
            0.04,
            category="Горшки",
            article_query="a-",
            sort_metric="Выручка",
        )
        self.assertEqual([row.article for row in filtered], ["A-10"])

        descending = filter_product_results(
            self.results,
            0.04,
            category=CATEGORY_ALL,
            sort_metric="Количество продаж",
            descending=True,
        )
        self.assertEqual([row.article for row in descending], ["B-20", "A-10", "A-30"])

    def test_scenario_uses_planned_values_for_sorting(self) -> None:
        scenarios = [calculate_scenario(row, 0.04, None) for row in self.results]
        by_profit = filter_scenario_rows(
            scenarios,
            sort_metric="Чистая прибыль",
            descending=True,
        )
        self.assertEqual(by_profit[0].article, "B-20")
        self.assertEqual(by_profit[-1].article, "A-30")

    def test_category_is_persistent_and_catalog_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "app.sqlite3")
            database.save_product(Product("A", "Товар", 80, 20, category="Категория"))
            self.assertEqual(database.list_products()[0].category, "Категория")
            self.assertEqual(database.clear_products(), 1)
            self.assertEqual(database.list_products(), [])


if __name__ == "__main__":
    unittest.main()
