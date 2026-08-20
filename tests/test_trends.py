from __future__ import annotations

import unittest

from ozon_app.models import RunSummary
from ozon_app.trends import build_trend_points, chart_bounds


def summary(
    run_id: int,
    start: str,
    revenue: float,
    net: float = 0,
    *,
    commission_share: float = 0,
    logistics_share: float = 0,
    points_share: float = 0,
    net_margin: float = 0,
) -> RunSummary:
    return RunSummary(
        id=run_id,
        created_at=f"{start} 12:00:00",
        period_start=start,
        period_end=start,
        source_count=1,
        units=float(run_id),
        revenue=revenue,
        net_profit=net,
        unallocated_total=-run_id,
        status="Готов",
        commission_share=commission_share,
        logistics_share=logistics_share,
        points_share=points_share,
        net_margin=net_margin,
    )


class TrendTests(unittest.TestCase):
    def test_points_are_sorted_by_report_period(self) -> None:
        points = build_trend_points(
            [summary(3, "2026-07-01", 300), summary(1, "2026-03-01", 100), summary(2, "2026-05-01", 200)]
        )

        self.assertEqual([point.run_id for point in points], [1, 2, 3])
        self.assertEqual([point.revenue for point in points], [100, 200, 300])
        self.assertEqual(points[0].label, "01.03.2026")

    def test_chart_bounds_include_zero_and_negative_values(self) -> None:
        points = build_trend_points([summary(1, "2026-03-01", 100, -50), summary(2, "2026-05-01", 200, 75)])

        minimum, maximum = chart_bounds(points, "net_profit")
        self.assertLess(minimum, -50)
        self.assertGreater(maximum, 75)
        self.assertLessEqual(minimum, 0)
        self.assertGreaterEqual(maximum, 0)

    def test_percentage_metrics_are_available_for_chart_and_table(self) -> None:
        point = build_trend_points([
            summary(
                1,
                "2026-03-01",
                100,
                commission_share=0.21,
                logistics_share=0.12,
                points_share=0.08,
                net_margin=0.19,
            )
        ])[0]

        self.assertAlmostEqual(point.value("commission_share"), 0.21)
        self.assertAlmostEqual(point.value("logistics_share"), 0.12)
        self.assertAlmostEqual(point.value("points_share"), 0.08)
        self.assertAlmostEqual(point.value("net_margin"), 0.19)


if __name__ == "__main__":
    unittest.main()
