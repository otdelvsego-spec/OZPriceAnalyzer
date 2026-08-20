from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ozon_app.calculator import calculate_run
from ozon_app.excel_reader import REPORT_ACCRUAL, REPORT_ADDITIONAL_INCOME, REPORT_REALIZATION
from ozon_app.models import (
    AdditionalIncomeRow,
    AccrualRow,
    ParsedSource,
    Product,
    RealizationRow,
    RunCalculation,
)
from ozon_app.service import AppService, split_import_sources


def _accrual_source(path: Path, value_date: date, article: str = "A") -> ParsedSource:
    return ParsedSource(
        path=path,
        file_hash=f"accrual-{value_date:%Y%m%d}",
        report_type=REPORT_ACCRUAL,
        sheet_name="Начисления",
        header_row=1,
        accrual_rows=[
            AccrualRow(
                source_name=path.name,
                sheet_name="Начисления",
                row_number=2,
                accrual_id=f"accrual-{value_date:%Y%m%d}",
                accrual_date=value_date,
                accrual_type="Логистика",
                article=article,
                sku=f"SKU-{article}",
                product_name="Товар",
                quantity=0,
                seller_price=0,
                amount=-10,
            )
        ],
        period_start=value_date,
        period_end=value_date,
    )


def _realization_source(
    path: Path,
    start: date | None,
    end: date | None,
    article: str = "A",
) -> ParsedSource:
    rows = []
    if start is not None:
        rows.append(
            RealizationRow(
                source_name=path.name,
                sheet_name="Выкупы",
                row_number=12,
                raw_article=article,
                sku=f"SKU-{article}",
                product_name="Товар",
                shipment=f"shipment-{start:%Y%m%d}",
                unit_price=55,
                quantity=1,
                amount=55,
            )
        )
    return ParsedSource(
        path=path,
        file_hash=f"realization-{path.name}",
        report_type=REPORT_REALIZATION,
        sheet_name="Выкупы",
        header_row=11,
        realization_rows=rows,
        period_start=start,
        period_end=end,
    )


def _additional_income_source(path: Path, value_date: date) -> ParsedSource:
    return ParsedSource(
        path=path,
        file_hash=f"income-{value_date:%Y%m%d}",
        report_type=REPORT_ADDITIONAL_INCOME,
        sheet_name="PDF",
        header_row=0,
        additional_income_rows=[
            AdditionalIncomeRow(
                source_name=path.name,
                page_number=1,
                document_number="848264",
                income_date=value_date,
                income_type="Премия за расчеты баллами",
                amount=61.40,
            )
        ],
        period_start=value_date,
        period_end=value_date,
    )


class BatchImportTests(unittest.TestCase):
    def test_additional_income_pdf_is_matched_to_accrual_month(self) -> None:
        january = _accrual_source(Path("january.xlsx"), date(2026, 1, 29))
        premium = _additional_income_source(Path("premium.pdf"), date(2026, 1, 31))

        sessions = split_import_sources([premium, january])

        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].has_additional_income)
        self.assertEqual(
            [source.path.name for source in sessions[0].sources],
            ["january.xlsx", "premium.pdf"],
        )
        calculation = calculate_run(
            sessions[0].sources,
            {"A": Product("A", "Товар")},
            0.04,
        )
        self.assertAlmostEqual(calculation.unallocated_total, 61.40)
        self.assertAlmostEqual(calculation.taxable_unallocated_income, 61.40)
        self.assertAlmostEqual(calculation.unallocated_income_tax, 2.456)
        self.assertAlmostEqual(calculation.report_net_profit, 48.944)

    def test_each_accrual_file_becomes_a_separate_chronological_session(self) -> None:
        april = _accrual_source(Path("april.xlsx"), date(2026, 4, 30))
        may = _accrual_source(Path("may.xlsx"), date(2026, 5, 31))
        april_sales = _realization_source(
            Path("sales-april.xlsx"), date(2026, 4, 1), date(2026, 4, 15)
        )
        may_sales = _realization_source(
            Path("sales-may.xlsx"), date(2026, 5, 1), date(2026, 5, 20)
        )

        sessions = split_import_sources([may_sales, may, april_sales, april])

        self.assertEqual(len(sessions), 2)
        self.assertEqual([session.period_start.month for session in sessions], [4, 5])
        self.assertEqual(
            [[source.path.name for source in session.sources] for session in sessions],
            [["april.xlsx", "sales-april.xlsx"], ["may.xlsx", "sales-may.xlsx"]],
        )

    def test_unmatched_realization_stops_multi_month_import(self) -> None:
        april = _accrual_source(Path("april.xlsx"), date(2026, 4, 30))
        may = _accrual_source(Path("may.xlsx"), date(2026, 5, 31))
        june_sales = _realization_source(
            Path("sales-june.xlsx"), date(2026, 6, 1), date(2026, 6, 15)
        )

        with self.assertRaisesRegex(ValueError, "не найден отчет по начислениям за 06.2026"):
            split_import_sources([april, may, june_sales])

    def test_ambiguous_realization_stops_import(self) -> None:
        may_first = _accrual_source(Path("may-first.xlsx"), date(2026, 5, 10))
        may_second = _accrual_source(Path("may-second.xlsx"), date(2026, 5, 31))
        may_sales = _realization_source(
            Path("sales-may.xlsx"), date(2026, 5, 1), date(2026, 5, 20)
        )

        with self.assertRaisesRegex(ValueError, "нельзя распределить однозначно"):
            split_import_sources([may_first, may_second, may_sales])

    def test_single_accrual_keeps_manual_mismatch_confirmation(self) -> None:
        may = _accrual_source(Path("may.xlsx"), date(2026, 5, 31))
        june_sales = _realization_source(
            Path("sales-june.xlsx"), date(2026, 6, 1), date(2026, 6, 15)
        )

        sessions = split_import_sources([may, june_sales])

        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].has_realization)
        self.assertIn("не относится", sessions[0].realization_period_warnings()[0])

    def test_saved_runs_keep_realization_in_matching_month(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AppService(root / "storage")
            service.db.save_product(Product(article="A", name="Товар"))
            april_path = root / "april.xlsx"
            may_path = root / "may.xlsx"
            sales_path = root / "sales-may.xlsx"
            for path in (april_path, may_path, sales_path):
                path.write_bytes(path.name.encode("utf-8"))
            sessions = split_import_sources(
                [
                    _accrual_source(april_path, date(2026, 4, 30)),
                    _accrual_source(may_path, date(2026, 5, 31)),
                    _realization_source(
                        sales_path,
                        date(2026, 5, 1),
                        date(2026, 5, 20),
                    ),
                ]
            )

            calculations = service.complete_import_batch(sessions)

            self.assertEqual([item.period_start.month for item in calculations], [4, 5])
            self.assertEqual([item.realization_revenue for item in calculations], [0, 55])
            runs = service.db.list_runs()
            self.assertEqual([run.source_count for run in runs], [1, 2])
            april_files = service.db.list_source_files(runs[0].id)
            may_files = service.db.list_source_files(runs[1].id)
            self.assertEqual([row["original_name"] for row in april_files], ["april.xlsx"])
            self.assertEqual(
                [row["original_name"] for row in may_files],
                ["may.xlsx", "sales-may.xlsx"],
            )

    def test_later_calculation_error_does_not_save_earlier_month(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AppService(Path(directory) / "storage")
            sessions = split_import_sources(
                [
                    _accrual_source(Path("april.xlsx"), date(2026, 4, 30)),
                    _accrual_source(Path("may.xlsx"), date(2026, 5, 31)),
                ]
            )
            first_result = RunCalculation(
                run_id=None,
                period_start=date(2026, 4, 30),
                period_end=date(2026, 4, 30),
                tax_rate=0.04,
                products=[],
                unallocated_total=0,
                unallocated={},
                accrual_stats={},
                source_files=sessions[0].sources,
            )

            with patch(
                "ozon_app.service.calculate_run",
                side_effect=[first_result, ValueError("Ошибка мая")],
            ):
                with self.assertRaisesRegex(ValueError, "Ошибка мая"):
                    service.complete_import_batch(
                        sessions,
                        created_products=[Product(article="A", name="Товар")],
                    )

            self.assertEqual(service.db.list_runs(), [])
            self.assertNotIn("A", service.db.product_map(active_only=False))


if __name__ == "__main__":
    unittest.main()
