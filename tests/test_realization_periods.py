from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from ozon_app.database import Database
from ozon_app.models import AccrualRow, ParsedSource, RunCalculation
from ozon_app.service import ImportSession


def _accrual_source(*dates: date) -> ParsedSource:
    return ParsedSource(
        path=Path("Отчет по начислениям.xlsx"),
        file_hash="accrual",
        report_type="ACCRUAL",
        sheet_name="Начисления",
        header_row=1,
        accrual_rows=[
            AccrualRow(
                source_name="Отчет по начислениям.xlsx",
                sheet_name="Начисления",
                row_number=index + 2,
                accrual_id=str(index),
                accrual_date=value,
                accrual_type="Выручка",
                article="A",
                sku="1",
                product_name="Товар",
                quantity=1,
                seller_price=100,
                amount=100,
            )
            for index, value in enumerate(dates)
        ],
        period_start=min(dates),
        period_end=max(dates),
    )


def _realization_source(start: date | None, end: date | None) -> ParsedSource:
    return ParsedSource(
        path=Path("RealizationReportCIS.xlsx"),
        file_hash="realization",
        report_type="REALIZATION",
        sheet_name="Отчет о выкупленных товарах",
        header_row=11,
        period_start=start,
        period_end=end,
    )


class RealizationPeriodTests(unittest.TestCase):
    def test_partial_period_in_same_month_is_compatible(self) -> None:
        session = ImportSession(
            sources=[
                _accrual_source(date(2026, 6, 1), date(2026, 6, 30)),
                _realization_source(date(2026, 6, 1), date(2026, 6, 15)),
            ],
            unknown_products=[],
        )
        self.assertEqual(session.realization_period_warnings(), [])

    def test_different_month_requires_confirmation(self) -> None:
        session = ImportSession(
            sources=[
                _accrual_source(date(2026, 7, 1), date(2026, 7, 29)),
                _realization_source(date(2026, 6, 1), date(2026, 6, 15)),
            ],
            unknown_products=[],
        )
        warnings = session.realization_period_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("01.06.2026–15.06.2026", warnings[0])
        self.assertIn("07.2026", warnings[0])

    def test_unknown_or_cross_month_realization_period_requires_confirmation(self) -> None:
        accrual = _accrual_source(date(2026, 6, 1), date(2026, 6, 30))
        unknown = ImportSession(
            sources=[accrual, _realization_source(None, None)],
            unknown_products=[],
        )
        crossing = ImportSession(
            sources=[
                accrual,
                _realization_source(date(2026, 6, 20), date(2026, 7, 5)),
            ],
            unknown_products=[],
        )
        self.assertIn("не удалось определить", unknown.realization_period_warnings()[0])
        self.assertIn("несколько месяцев", crossing.realization_period_warnings()[0])

    def test_accepted_mismatch_is_stored_in_quality_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "app.sqlite3")
            message = "RealizationReportCIS.xlsx: период выкупов не совпадает"
            calculation = RunCalculation(
                run_id=None,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 29),
                tax_rate=0.04,
                products=[],
                unallocated_total=0,
                unallocated={},
                accrual_stats={},
                source_period_warnings=[message],
            )
            run_id = database.save_run(calculation, {})

            events = database.list_quality_events(run_id)
            matching = [event for event in events if event["event_type"] == "Несовпадение периодов"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["message"], message)
            self.assertEqual(database.load_calculation(run_id).source_period_warnings, [message])


if __name__ == "__main__":
    unittest.main()
