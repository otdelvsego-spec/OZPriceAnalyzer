from __future__ import annotations

from dataclasses import dataclass

from .models import ProductResult, RunCalculation


@dataclass(slots=True)
class ComparisonMetric:
    first: float
    second: float

    @property
    def change(self) -> float:
        return self.second - self.first

    @property
    def change_percent(self) -> float | None:
        if self.first == 0:
            return None if self.second == 0 else float("inf")
        return self.change / abs(self.first)


@dataclass(slots=True)
class ProductComparison:
    article: str
    name: str
    units: ComparisonMetric
    revenue: ComparisonMetric
    net_profit: ComparisonMetric
    profitability: ComparisonMetric


@dataclass(slots=True)
class RunComparison:
    first_run_id: int
    second_run_id: int
    units: ComparisonMetric
    revenue: ComparisonMetric
    net_profit: ComparisonMetric
    unallocated: ComparisonMetric
    products: list[ProductComparison]


def compare_calculations(first: RunCalculation, second: RunCalculation) -> RunComparison:
    if first.run_id is None or second.run_id is None:
        raise ValueError("Для сравнения нужны сохраненные расчеты")
    first_totals = first.totals()
    second_totals = second.totals()
    first_products = {item.article: item for item in first.products}
    second_products = {item.article: item for item in second.products}
    rows: list[ProductComparison] = []
    for article in sorted(set(first_products) | set(second_products), key=str.casefold):
        left = first_products.get(article)
        right = second_products.get(article)
        name = (right or left).name  # type: ignore[union-attr]
        rows.append(
            ProductComparison(
                article=article,
                name=name,
                units=_metric(left, right, lambda item, _rate: item.units, first.tax_rate, second.tax_rate),
                revenue=_metric(
                    left,
                    right,
                    lambda item, _rate: item.revenue_including_points,
                    first.tax_rate,
                    second.tax_rate,
                ),
                net_profit=_metric(
                    left,
                    right,
                    lambda item, rate: item.net_profit(rate),
                    first.tax_rate,
                    second.tax_rate,
                ),
                profitability=_metric(
                    left,
                    right,
                    lambda item, rate: item.profitability(rate),
                    first.tax_rate,
                    second.tax_rate,
                ),
            )
        )
    return RunComparison(
        first_run_id=first.run_id,
        second_run_id=second.run_id,
        units=ComparisonMetric(first_totals["units"], second_totals["units"]),
        revenue=ComparisonMetric(first_totals["revenue"], second_totals["revenue"]),
        net_profit=ComparisonMetric(first_totals["net_profit"], second_totals["net_profit"]),
        unallocated=ComparisonMetric(first_totals["unallocated"], second_totals["unallocated"]),
        products=rows,
    )


def _metric(
    first: ProductResult | None,
    second: ProductResult | None,
    value,
    first_tax_rate: float,
    second_tax_rate: float,
) -> ComparisonMetric:
    return ComparisonMetric(
        value(first, first_tax_rate) if first is not None else 0.0,
        value(second, second_tax_rate) if second is not None else 0.0,
    )
