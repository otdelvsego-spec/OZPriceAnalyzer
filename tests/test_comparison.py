from __future__ import annotations

import unittest

from ozon_app.comparison import compare_calculations
from ozon_app.models import ProductResult, RunCalculation


def calculation(run_id: int, products: list[ProductResult], unallocated: float = 0) -> RunCalculation:
    return RunCalculation(
        run_id=run_id,
        period_start=None,
        period_end=None,
        tax_rate=0.04,
        products=products,
        unallocated_total=unallocated,
        unallocated={},
        accrual_stats={},
    )


class ComparisonTests(unittest.TestCase):
    def test_compares_union_of_products_and_run_totals(self) -> None:
        first = calculation(
            1,
            [ProductResult("A", "Товар A", 60, 40, units=10, revenue_no_points=2_000, financial_result=1_200)],
            -100,
        )
        second = calculation(
            2,
            [
                ProductResult("A", "Товар A", 60, 40, units=12, revenue_no_points=2_640, financial_result=1_700),
                ProductResult("B", "Товар B", 50, 20, units=2, revenue_no_points=500, financial_result=350),
            ],
            -40,
        )

        result = compare_calculations(first, second)

        self.assertEqual([row.article for row in result.products], ["A", "B"])
        self.assertEqual(result.units.change, 4)
        self.assertEqual(result.revenue.change, 1_140)
        self.assertEqual(result.unallocated.change, 60)
        row_a = result.products[0]
        self.assertEqual(row_a.units.change, 2)
        self.assertAlmostEqual(row_a.revenue.change_percent or 0, 0.32)
        row_b = result.products[1]
        self.assertEqual(row_b.units.first, 0)
        self.assertEqual(row_b.units.second, 2)
        self.assertEqual(row_b.units.change_percent, float("inf"))


if __name__ == "__main__":
    unittest.main()
