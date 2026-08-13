from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .excel_reader import all_rows, normalize_text
from .models import ParsedSource, Product, ProductResult, RunCalculation, ScenarioRow, UnknownProduct


class CalculationError(ValueError):
    pass


def _type_key(value: str) -> str:
    return normalize_text(value).replace("ё", "е")


def distribution_status(with_article: int, without_article: int, empty: str = "НЕТ ДАННЫХ") -> str:
    if with_article > 0 and without_article > 0:
        return "СМЕШАННОЕ РАСПРЕДЕЛЕНИЕ"
    if with_article > 0:
        return "ПО АРТИКУЛУ"
    if without_article > 0:
        return "НЕРАСПРЕДЕЛЕННЫЕ ДОХОДЫ/РАСХОДЫ"
    return empty


def accrual_category(accrual_type: str) -> tuple[str, str]:
    key = _type_key(accrual_type)
    if key in {_type_key("Выручка"), _type_key("Возврат выручки")}:
        return "revenue_no_points", "Выручка без баллов"
    if key == _type_key("Программы партнёров"):
        return "partner_programs", "Программы партнёров"
    if key == _type_key("Баллы за скидки"):
        return "points", "Баллы за скидки"
    if key in {_type_key("Вознаграждение за продажу"), _type_key("Возврат вознаграждения")}:
        return "commission", "Комиссия Ozon"
    if key.startswith(_type_key("Обработка отправления")):
        return "processing", "Обработка отправления Drop-off"
    if key.startswith(_type_key("Доставка до места выдачи")):
        return "delivery", "Доставка до места выдачи"
    if key == _type_key("Логистика"):
        return "logistics", "Логистика"
    if key == _type_key("Обратная логистика"):
        return "reverse_logistics", "Обратная логистика"
    if (
        key.startswith(_type_key("Обработка возвратов"))
        or key.startswith(_type_key("Обработка возврата"))
        or key in {
            _type_key("Обработка отменённых и невостребованных товаров"),
            _type_key("Обработка частичного невыкупа"),
        }
    ):
        return "returns_cancels", "Возвраты, отмены и невыкупы"
    if key == _type_key("Эквайринг"):
        return "acquiring", "Эквайринг"
    if key == _type_key("Звёздные товары"):
        return "stars", "Продвижение «Звёздные товары»"
    if key in {
        _type_key("Упаковка товара партнёрами"),
        _type_key("Обеспечение материалами для упаковки товара"),
    }:
        return "packaging", "Упаковка и материалы"
    if key in {
        _type_key("Потеря по вине Ozon в логистике"),
        _type_key("Брак по вине Ozon на складе"),
    }:
        return "compensation", "Компенсации Ozon"
    return "other", "Прочие начисления по товару"


def guide_target(accrual_type: str) -> str:
    return f"С артикулом → {accrual_category(accrual_type)[1]}; без артикула → нераспределенные"


def build_sku_map(accrual_rows, allowed_articles: set[str] | None = None) -> tuple[dict[str, str], set[str]]:
    mapping: dict[str, str] = {}
    conflicts: set[str] = set()
    for row in accrual_rows:
        if not row.sku or not row.article:
            continue
        if allowed_articles is not None and row.article not in allowed_articles:
            continue
        if row.sku in conflicts:
            continue
        existing = mapping.get(row.sku)
        if existing and existing != row.article:
            mapping.pop(row.sku, None)
            conflicts.add(row.sku)
        else:
            mapping[row.sku] = row.article
    return mapping, conflicts


def discover_unknown_products(sources: list[ParsedSource], products: dict[str, Product]) -> list[UnknownProduct]:
    accrual_rows, realization_rows = all_rows(sources)
    provisional_map, conflicts = build_sku_map(accrual_rows)
    unknown: dict[str, UnknownProduct] = {}

    def register(article: str, name: str, sku: str, source_name: str) -> None:
        if not article or article in products:
            return
        item = unknown.setdefault(article, UnknownProduct(article=article, name=name or article, sku=sku))
        if item.name == item.article and name:
            item.name = name
        if not item.sku and sku:
            item.sku = sku
        item.source_names.add(source_name)

    for row in accrual_rows:
        register(row.article, row.product_name, row.sku, row.source_name)

    known_or_pending = set(products) | set(unknown)
    for row in realization_rows:
        mapped = provisional_map.get(row.sku, "") if row.sku not in conflicts else ""
        if mapped and mapped in known_or_pending:
            continue
        if row.raw_article in products:
            continue
        register(row.raw_article, row.product_name, row.sku, row.source_name)
    return sorted(unknown.values(), key=lambda item: item.article.casefold())


def calculate_run(
    sources: list[ParsedSource],
    products: dict[str, Product],
    tax_rate: float,
    skipped_articles: set[str] | None = None,
) -> RunCalculation:
    skipped_articles = skipped_articles or set()
    active_products = {key: value for key, value in products.items() if value.active}
    results = {
        article: ProductResult(
            article=product.article,
            name=product.name,
            material_cost=product.material_cost,
            labor_cost=product.labor_cost,
            category=product.category,
        )
        for article, product in active_products.items()
    }
    accrual_rows, realization_rows = all_rows(sources)
    sku_map, sku_conflicts = build_sku_map(accrual_rows, set(active_products))
    current_stats: dict[str, list[object]] = {}
    breakdown: dict[str, list[object]] = {}
    skipped_detail: dict[str, str] = {}
    sales_orders: dict[tuple[str, str], list[float]] = {}
    returns_by_article: dict[str, float] = defaultdict(float)
    accrual_revenue_keys: set[tuple[str, str]] = set()
    unallocated_total = 0.0

    dates = [row.accrual_date for row in accrual_rows if row.accrual_date]
    period_start: date | None = min(dates) if dates else None
    period_end: date | None = max(dates) if dates else None

    for row in accrual_rows:
        type_key = _type_key(row.accrual_type)
        stat = current_stats.setdefault(type_key, [row.accrual_type, 0, 0])
        stat[1 if row.article else 2] = int(stat[1 if row.article else 2]) + 1

        if row.article:
            if row.article not in results or row.article in skipped_articles:
                skipped_detail.setdefault(
                    row.article,
                    f"{row.article} — {row.product_name or row.article} ({row.source_name}, строка {row.row_number})",
                )
                continue
            result = results[row.article]
            result.financial_result += row.amount
            field_name, _ = accrual_category(row.accrual_type)
            setattr(result, field_name, getattr(result, field_name) + row.amount)

            if row.sku and row.sku not in sku_conflicts:
                existing = sku_map.get(row.sku)
                if existing and existing != row.article:
                    sku_map.pop(row.sku, None)
                    sku_conflicts.add(row.sku)
                elif not existing:
                    sku_map[row.sku] = row.article

            key = _type_key(row.accrual_type)
            if key in {_type_key("Выручка"), _type_key("Программы партнёров"), _type_key("Баллы за скидки")}:
                if row.accrual_id and row.sku:
                    accrual_revenue_keys.add((row.sku, normalize_text(row.accrual_id)))
                order_id = row.accrual_id or f"{row.source_name}#{row.row_number}"
                order_key = (order_id, row.article)
                order = sales_orders.setdefault(order_key, [0.0, 0.0, 0.0])
                order[0] += row.amount
                if abs(row.seller_price) > 0:
                    order[1] = abs(row.seller_price)
                if key == _type_key("Выручка"):
                    order[2] += abs(row.quantity)
            elif key == _type_key("Возврат выручки"):
                returns_by_article[row.article] += abs(row.quantity)
        else:
            unallocated_total += row.amount
            item = breakdown.setdefault(type_key or "без типа начисления", [row.accrual_type or "Без типа начисления", 0, 0.0])
            item[1] = int(item[1]) + 1
            item[2] = float(item[2]) + row.amount

    for (_, article), (amount, seller_price, source_quantity) in sales_orders.items():
        if article not in results:
            continue
        if seller_price > 0:
            units = _round_half_up(abs(amount) / seller_price)
        else:
            units = source_quantity
        results[article].units += units

    for article, quantity in returns_by_article.items():
        if article in results:
            results[article].units -= quantity

    realization_keys: dict[tuple[str, str], tuple[float, float, str]] = {}
    duplicate_rows = 0
    already_accrued_rows = 0
    realization_revenue = 0.0
    realization_units = 0.0
    for row in realization_rows:
        shipment = normalize_text(row.shipment) or f"{row.source_name}#{row.row_number}"
        row_key = (row.sku, shipment)
        if row_key in accrual_revenue_keys:
            already_accrued_rows += 1
            continue
        if row_key in realization_keys:
            old_amount, old_quantity, _ = realization_keys[row_key]
            if abs(old_amount - row.amount) <= 0.05 and abs(old_quantity - row.quantity) <= 0.0001:
                duplicate_rows += 1
                continue
            raise CalculationError(
                f"Противоречивый дубль выкупленного товара для отправления {row.shipment}."
            )
        realization_keys[row_key] = (row.amount, row.quantity, row.source_name)

        article = ""
        if row.sku and row.sku not in sku_conflicts:
            mapped = sku_map.get(row.sku, "")
            if mapped in results:
                article = mapped
        if not article and row.raw_article in results:
            article = row.raw_article
        if not article or article in skipped_articles:
            candidate = article or row.raw_article
            skipped_detail.setdefault(
                candidate,
                f"{candidate} — {row.product_name or candidate} ({row.source_name}, строка {row.row_number})",
            )
            continue
        result = results[article]
        result.units += row.quantity
        result.revenue_no_points += row.amount
        result.financial_result += row.amount
        realization_revenue += row.amount
        realization_units += row.quantity

    stats = {
        str(values[0]): (int(values[1]), int(values[2]))
        for values in sorted(current_stats.values(), key=lambda value: str(value[0]).casefold())
    }
    unallocated = {
        str(values[0]): (int(values[1]), float(values[2]))
        for values in sorted(breakdown.values(), key=lambda value: str(value[0]).casefold())
    }
    return RunCalculation(
        run_id=None,
        period_start=period_start,
        period_end=period_end,
        tax_rate=tax_rate,
        products=sorted(results.values(), key=lambda item: item.article.casefold()),
        unallocated_total=unallocated_total,
        unallocated=unallocated,
        accrual_stats=stats,
        source_files=sources,
        skipped_articles=skipped_detail,
        sku_conflicts=sku_conflicts,
        duplicate_realization_rows=duplicate_rows,
        already_accrued_realization_rows=already_accrued_rows,
        realization_revenue=realization_revenue,
        realization_units=realization_units,
    )


def calculate_scenario(result: ProductResult, tax_rate: float, planned_price: float | None = None) -> ScenarioRow:
    current_price = result.average_price()
    if planned_price is None:
        planned_price = current_price
    if not result.units or planned_price is None:
        return ScenarioRow(
            article=result.article,
            name=result.name,
            category=result.category,
            unit_cost=result.total_cost,
            units=result.units,
            current_price=current_price,
            planned_price=planned_price,
            price_change=None,
            profitability=None,
            ozon_costs_without_commission=None,
            planned_revenue=None,
            commission_rate=None,
            planned_commission=None,
            planned_points=None,
            taxable_base=None,
            tax=None,
            profit=None,
            profit_per_unit_before_cost=None,
            net_profit_per_unit=None,
        )
    price_change = planned_price / current_price - 1 if current_price else None
    ozon_costs_without_commission = (
        result.revenue_including_points - result.financial_result + result.commission
    )
    planned_revenue = planned_price * result.units
    commission_rate = -result.commission / result.revenue_including_points if result.revenue_including_points else 0.0
    planned_commission = -planned_revenue * commission_rate
    planned_points = (
        result.points / result.revenue_including_points * planned_revenue
        if result.revenue_including_points
        else 0.0
    )
    taxable_base = planned_revenue - planned_points
    tax = taxable_base * tax_rate
    profit = planned_revenue - ozon_costs_without_commission + planned_commission - tax
    profit_per_unit_before_cost = profit / result.units
    net_profit_per_unit = profit_per_unit_before_cost - result.total_cost
    profitability = net_profit_per_unit / result.total_cost if result.total_cost else 0.0
    return ScenarioRow(
        article=result.article,
        name=result.name,
        category=result.category,
        unit_cost=result.total_cost,
        units=result.units,
        current_price=current_price,
        planned_price=planned_price,
        price_change=price_change,
        profitability=profitability,
        ozon_costs_without_commission=ozon_costs_without_commission,
        planned_revenue=planned_revenue,
        commission_rate=commission_rate,
        planned_commission=planned_commission,
        planned_points=planned_points,
        taxable_base=taxable_base,
        tax=tax,
        profit=profit,
        profit_per_unit_before_cost=profit_per_unit_before_cost,
        net_profit_per_unit=net_profit_per_unit,
    )


def _round_half_up(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clone_result(result: ProductResult) -> ProductResult:
    return replace(result)
