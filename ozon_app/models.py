from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Product:
    article: str
    name: str
    material_cost: float = 0.0
    labor_cost: float = 0.0
    active: bool = True
    sort_order: int | None = None

    @property
    def total_cost(self) -> float:
        return self.material_cost + self.labor_cost


@dataclass(slots=True)
class AccrualRow:
    source_name: str
    sheet_name: str
    row_number: int
    accrual_id: str
    accrual_date: date | None
    accrual_type: str
    article: str
    sku: str
    product_name: str
    quantity: float
    seller_price: float
    amount: float


@dataclass(slots=True)
class RealizationRow:
    source_name: str
    sheet_name: str
    row_number: int
    raw_article: str
    sku: str
    product_name: str
    shipment: str
    unit_price: float
    quantity: float
    amount: float


@dataclass(slots=True)
class ParsedSource:
    path: Path
    file_hash: str
    report_type: str
    sheet_name: str
    header_row: int
    accrual_rows: list[AccrualRow] = field(default_factory=list)
    realization_rows: list[RealizationRow] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    duplicate_run_ids: list[int] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.accrual_rows) + len(self.realization_rows)

    @property
    def total_amount(self) -> float:
        if self.accrual_rows:
            return sum(row.amount for row in self.accrual_rows)
        return sum(row.amount for row in self.realization_rows)


@dataclass(slots=True)
class UnknownProduct:
    article: str
    name: str
    sku: str
    source_names: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ProductResult:
    article: str
    name: str
    material_cost: float
    labor_cost: float
    units: float = 0.0
    revenue_no_points: float = 0.0
    partner_programs: float = 0.0
    points: float = 0.0
    commission: float = 0.0
    processing: float = 0.0
    delivery: float = 0.0
    logistics: float = 0.0
    reverse_logistics: float = 0.0
    returns_cancels: float = 0.0
    acquiring: float = 0.0
    stars: float = 0.0
    packaging: float = 0.0
    compensation: float = 0.0
    other: float = 0.0
    financial_result: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.material_cost + self.labor_cost

    @property
    def material_sold(self) -> float:
        return self.material_cost * self.units

    @property
    def labor_sold(self) -> float:
        return self.labor_cost * self.units

    @property
    def cost_sold(self) -> float:
        return self.total_cost * self.units

    @property
    def revenue_including_points(self) -> float:
        return self.revenue_no_points + self.partner_programs + self.points

    @property
    def taxable_income(self) -> float:
        return self.revenue_no_points + self.partner_programs

    def tax(self, rate: float) -> float:
        return self.taxable_income * rate

    def net_profit(self, rate: float) -> float:
        return self.financial_result - self.cost_sold - self.tax(rate)

    def average_price(self) -> float | None:
        return self.revenue_including_points / self.units if self.units else None

    def profit_per_unit(self) -> float:
        return self.financial_result / self.units if self.units else 0.0

    def net_profit_per_unit(self, rate: float) -> float:
        return self.net_profit(rate) / self.units if self.units else 0.0

    def profitability(self, rate: float) -> float:
        return self.net_profit_per_unit(rate) / self.total_cost if self.total_cost else 0.0


@dataclass(slots=True)
class RunCalculation:
    run_id: int | None
    period_start: date | None
    period_end: date | None
    tax_rate: float
    products: list[ProductResult]
    unallocated_total: float
    unallocated: dict[str, tuple[int, float]]
    accrual_stats: dict[str, tuple[int, int]]
    source_files: list[ParsedSource] = field(default_factory=list)
    skipped_articles: dict[str, str] = field(default_factory=dict)
    sku_conflicts: set[str] = field(default_factory=set)
    duplicate_realization_rows: int = 0
    already_accrued_realization_rows: int = 0
    realization_revenue: float = 0.0
    realization_units: float = 0.0

    def totals(self) -> dict[str, float]:
        return {
            "units": sum(item.units for item in self.products),
            "revenue": sum(item.revenue_including_points for item in self.products),
            "financial_result": sum(item.financial_result for item in self.products),
            "cost_sold": sum(item.cost_sold for item in self.products),
            "tax": sum(item.tax(self.tax_rate) for item in self.products),
            "net_profit": sum(item.net_profit(self.tax_rate) for item in self.products),
            "unallocated": self.unallocated_total,
        }


@dataclass(slots=True)
class ScenarioRow:
    article: str
    name: str
    unit_cost: float
    units: float
    current_price: float | None
    planned_price: float | None
    price_change: float | None
    profitability: float | None
    ozon_costs_without_commission: float | None
    planned_revenue: float | None
    commission_rate: float | None
    planned_commission: float | None
    planned_points: float | None
    taxable_base: float | None
    tax: float | None
    profit: float | None
    profit_per_unit_before_cost: float | None
    net_profit_per_unit: float | None


@dataclass(slots=True)
class RunSummary:
    id: int
    created_at: str
    period_start: str | None
    period_end: str | None
    source_count: int
    units: float
    revenue: float
    net_profit: float
    unallocated_total: float
    status: str
    report_name: str = ""


def as_serializable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
