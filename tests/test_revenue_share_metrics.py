from __future__ import annotations

import unittest

from ozon_app.models import ProductResult, RunCalculation
from ozon_app.ui import _result_values


class RevenueShareMetricTests(unittest.TestCase):
    def test_product_and_report_shares_use_revenue_including_points(self) -> None:
        product = ProductResult(
            article="A",
            name="Товар",
            material_cost=50,
            labor_cost=50,
            units=2,
            revenue_no_points=800,
            partner_programs=100,
            points=100,
            commission=-200,
            logistics=-80,
            reverse_logistics=-20,
            financial_result=600,
        )
        calculation = RunCalculation(
            run_id=1,
            period_start=None,
            period_end=None,
            tax_rate=0.04,
            products=[product],
            unallocated_total=0,
            unallocated={},
            accrual_stats={},
        )

        self.assertAlmostEqual(product.commission_share(), 0.2)
        self.assertAlmostEqual(product.logistics_share(), 0.1)
        self.assertAlmostEqual(product.points_share(), 0.1)
        self.assertAlmostEqual(product.net_margin(0.04), 0.364)
        self.assertEqual(
            calculation.revenue_shares(),
            {
                "commission_share": 0.2,
                "logistics_share": 0.1,
                "points_share": 0.1,
                "net_margin": 0.364,
            },
        )
        self.assertEqual(
            _result_values(product, 0.04)[-4:],
            ("20.00%", "10.00%", "10.00%", "36.40%"),
        )

    def test_zero_revenue_returns_zero_shares(self) -> None:
        product = ProductResult("A", "Товар", 0, 0, commission=-10, logistics=-5)

        self.assertEqual(product.commission_share(), 0.0)
        self.assertEqual(product.logistics_share(), 0.0)
        self.assertEqual(product.points_share(), 0.0)
        self.assertEqual(product.net_margin(0.04), 0.0)


if __name__ == "__main__":
    unittest.main()
