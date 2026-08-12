from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from ozon_app.calculator import (
    accrual_category,
    calculate_run,
    calculate_scenario,
    distribution_status,
)
from ozon_app.models import AccrualRow, ParsedSource, Product, ProductResult


def accrual(
    row: int,
    accrual_type: str,
    article: str,
    amount: float,
    quantity: float = 0,
    price: float = 0,
) -> AccrualRow:
    return AccrualRow(
        source_name="test.xlsx",
        sheet_name="Начисления",
        row_number=row,
        accrual_id=f"order-{row}",
        accrual_date=date(2026, 7, 1),
        accrual_type=accrual_type,
        article=article,
        sku="100" if article else "",
        product_name="Товар",
        quantity=quantity,
        seller_price=price,
        amount=amount,
    )


class CalculatorTests(unittest.TestCase):
    def test_mixed_type_is_distributed_by_each_row(self) -> None:
        source = ParsedSource(
            path=Path("test.xlsx"),
            file_hash="abc",
            report_type="ACCRUAL",
            sheet_name="Начисления",
            header_row=1,
            accrual_rows=[
                accrual(2, "Обеспечение материалами для упаковки товара", "A-1", -5),
                accrual(3, "Обеспечение материалами для упаковки товара", "", -5),
            ],
        )
        result = calculate_run([source], {"A-1": Product("A-1", "Товар", 10, 2)}, 0.04)

        self.assertEqual(result.products[0].packaging, -5)
        self.assertEqual(result.unallocated_total, -5)
        self.assertEqual(
            result.unallocated["Обеспечение материалами для упаковки товара"],
            (1, -5),
        )
        self.assertEqual(result.accrual_stats["Обеспечение материалами для упаковки товара"], (1, 1))
        self.assertEqual(distribution_status(1, 1), "СМЕШАННОЕ РАСПРЕДЕЛЕНИЕ")

    def test_new_type_uses_other_for_article_and_breakdown_without_article(self) -> None:
        source = ParsedSource(
            path=Path("test.xlsx"),
            file_hash="abc",
            report_type="ACCRUAL",
            sheet_name="Начисления",
            header_row=1,
            accrual_rows=[
                accrual(2, "Новый тип Ozon", "A-1", -30),
                accrual(3, "Новый тип Ozon", "", 12),
            ],
        )
        result = calculate_run([source], {"A-1": Product("A-1", "Товар", 10, 2)}, 0.04)

        self.assertEqual(accrual_category("Новый тип Ozon")[0], "other")
        self.assertEqual(result.products[0].other, -30)
        self.assertEqual(result.unallocated_total, 12)
        self.assertEqual(result.unallocated["Новый тип Ozon"], (1, 12))

    def test_skipped_unknown_article_is_not_moved_to_unallocated(self) -> None:
        source = ParsedSource(
            path=Path("test.xlsx"),
            file_hash="abc",
            report_type="ACCRUAL",
            sheet_name="Начисления",
            header_row=1,
            accrual_rows=[accrual(2, "Логистика", "UNKNOWN", -100)],
        )
        result = calculate_run([source], {"A-1": Product("A-1", "Товар", 10, 2)}, 0.04, {"UNKNOWN"})

        self.assertEqual(result.unallocated_total, 0)
        self.assertIn("UNKNOWN", result.skipped_articles)

    def test_scenario_matches_v11_formula_chain(self) -> None:
        product = ProductResult(
            article="A-1",
            name="Товар",
            material_cost=60,
            labor_cost=40,
            units=10,
            revenue_no_points=1_800,
            points=200,
            commission=-400,
            logistics=-300,
            financial_result=1_300,
        )
        scenario = calculate_scenario(product, tax_rate=0.04, planned_price=220)

        self.assertAlmostEqual(scenario.commission_rate or 0, 0.2)
        self.assertAlmostEqual(scenario.planned_revenue or 0, 2_200)
        self.assertAlmostEqual(scenario.planned_commission or 0, -440)
        self.assertAlmostEqual(scenario.planned_points or 0, 220)
        self.assertAlmostEqual(scenario.taxable_base or 0, 1_980)
        self.assertAlmostEqual(scenario.tax or 0, 79.2)
        self.assertAlmostEqual(scenario.net_profit_per_unit or 0, 38.08)
        self.assertAlmostEqual(scenario.profitability or 0, 0.3808)


if __name__ == "__main__":
    unittest.main()
