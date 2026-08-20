from __future__ import annotations

import unittest

from ozon_app.models import ProductResult, RunCalculation, is_compensation_accrual_type
from ozon_app.report_totals import report_total_value


class CompensationTaxTests(unittest.TestCase):
    def test_unallocated_compensation_is_taxable_but_not_product_revenue_or_profit(self) -> None:
        product = ProductResult(
            article="A",
            name="Товар",
            material_cost=100,
            labor_cost=0,
            units=1,
            revenue_no_points=1_000,
            financial_result=600,
        )
        calculation = RunCalculation(
            run_id=1,
            period_start=None,
            period_end=None,
            tax_rate=0.04,
            products=[product],
            unallocated_total=100.78,
            unallocated={
                "Брак по вине Ozon на складе": (1, 120.78),
                "Подписка": (1, -20.0),
            },
            accrual_stats={},
        )

        self.assertEqual(product.revenue_including_points, 1_000)
        self.assertEqual(product.taxable_income, 1_000)
        self.assertEqual(product.net_profit(0.04), 460)
        self.assertAlmostEqual(calculation.unallocated_compensation_income, 120.78)
        self.assertAlmostEqual(calculation.compensation_tax, 4.8312)
        self.assertAlmostEqual(calculation.totals()["taxable_income"], 1_120.78)
        self.assertAlmostEqual(calculation.totals()["tax"], 44.8312)
        self.assertAlmostEqual(calculation.report_net_profit, 555.9488)
        self.assertAlmostEqual(report_total_value(calculation), 555.9488)
        self.assertAlmostEqual(calculation.revenue_shares()["net_margin"], 0.5559488)

    def test_current_and_generic_compensation_names_are_recognized(self) -> None:
        self.assertTrue(is_compensation_accrual_type("Потеря по вине Ozon в логистике"))
        self.assertTrue(is_compensation_accrual_type("Брак по вине Ozon на складе"))
        self.assertTrue(is_compensation_accrual_type("Компенсация за повреждение"))
        self.assertFalse(is_compensation_accrual_type("Программа Premium"))


if __name__ == "__main__":
    unittest.main()
