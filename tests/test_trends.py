from __future__ import annotations

import unittest

from ozon_app.models import RunSummary
from ozon_app.trends import build_trend_points, chart_bounds


def summary(run_id: int, start: str, revenue: float, net: float = 0) -> RunSummary:
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


if __name__ == "__main__":
    unittest.main()
