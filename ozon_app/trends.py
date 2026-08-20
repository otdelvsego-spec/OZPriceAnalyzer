from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import RunSummary


@dataclass(slots=True)
class TrendPoint:
    run_id: int
    label: str
    sort_key: tuple[str, int]
    units: float
    revenue: float
    net_profit: float
    profitability: float
    unallocated: float
    commission_share: float
    logistics_share: float
    points_share: float
    net_margin: float

    def value(self, metric: str) -> float:
        if metric == "units":
            return self.units
        if metric == "revenue":
            return self.revenue
        if metric == "net_profit":
            return self.net_profit
        if metric == "profitability":
            return self.profitability
        if metric == "unallocated":
            return self.unallocated
        if metric == "commission_share":
            return self.commission_share
        if metric == "logistics_share":
            return self.logistics_share
        if metric == "points_share":
            return self.points_share
        if metric == "net_margin":
            return self.net_margin
        raise KeyError(f"Неизвестный показатель: {metric}")


def build_trend_points(runs: list[RunSummary]) -> list[TrendPoint]:
    points = [
        TrendPoint(
            run_id=run.id,
            label=_period_label(run),
            sort_key=(run.period_start or run.created_at, run.id),
            units=run.units,
            revenue=run.revenue,
            net_profit=run.net_profit,
            profitability=run.profitability,
            unallocated=run.unallocated_total,
            commission_share=run.commission_share,
            logistics_share=run.logistics_share,
            points_share=run.points_share,
            net_margin=run.net_margin,
        )
        for run in runs
    ]
    return sorted(points, key=lambda point: point.sort_key)


def chart_bounds(points: list[TrendPoint], metric: str) -> tuple[float, float]:
    values = [point.value(metric) for point in points]
    if not values:
        return 0.0, 1.0
    minimum = min(min(values), 0.0)
    maximum = max(max(values), 0.0)
    if minimum == maximum:
        padding = abs(minimum) * 0.1 or 1.0
        return minimum - padding, maximum + padding
    padding = (maximum - minimum) * 0.08
    return minimum - padding, maximum + padding


def _period_label(run: RunSummary) -> str:
    if run.period_start and run.period_end:
        start = _display_date(run.period_start)
        end = _display_date(run.period_end)
        return start if start == end else f"{start}–{end}"
    try:
        return datetime.fromisoformat(run.created_at).strftime("%d.%m.%Y")
    except ValueError:
        return run.report_name or "Период не определен"


def _display_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return value
