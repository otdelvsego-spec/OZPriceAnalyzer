from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from ozon_app.database import Database
from ozon_app.models import AccrualRow, ParsedSource, RunCalculation
from ozon_app.service import AppService, ImportSession


def _accrual_row(source_name: str, row_number: int, value_date: date) -> AccrualRow:
    return AccrualRow(
        source_name=source_name,
        sheet_name="Начисления",
        row_number=row_number,
        accrual_id=str(row_number),
        accrual_date=value_date,
        accrual_type="Подписка Premium",
        article="",
        sku="",
        product_name="",
        quantity=0,
        seller_price=0,
        amount=-10,
    )


def _source(path: Path, file_hash: str, start: date, end: date) -> ParsedSource:
    return ParsedSource(
        path=path,
        file_hash=file_hash,
        report_type="ACCRUAL",
        sheet_name="Начисления",
        header_row=1,
        accrual_rows=[
            _accrual_row(path.name, 2, start),
            _accrual_row(path.name, 3, end),
        ],
        period_start=start,
        period_end=end,
    )


def _calculation(source: ParsedSource, amount: float) -> RunCalculation:
    return RunCalculation(
        run_id=None,
        period_start=source.period_start,
        period_end=source.period_end,
        tax_rate=0.04,
        products=[],
        unallocated_total=amount,
        unallocated={"Подписка Premium": (1, amount)},
        accrual_stats={"Подписка Premium": (0, 1)},
        source_files=[source],
    )


class ReportReplacementTests(unittest.TestCase):
    def test_same_period_is_detected_even_when_file_contents_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AppService(root)
            start = date(2026, 6, 1)
            end = date(2026, 6, 30)
            old_source = _source(root / "old.xlsx", "old-hash", start, end)
            old_source.path.write_bytes(b"old")
            old_id = service.db.save_run(
                _calculation(old_source, -10),
                {str(old_source.path): old_source.path},
            )

            new_source = _source(root / "changed.xlsx", "new-hash", start, end)
            session = ImportSession(sources=[new_source], unknown_products=[])

            self.assertEqual(service.replacement_run_ids(session), [old_id])

    def test_file_from_another_period_is_not_silently_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AppService(root)
            old_source = _source(
                root / "old.xlsx",
                "same-hash",
                date(2026, 6, 1),
                date(2026, 6, 30),
            )
            old_source.path.write_bytes(b"old")
            old_id = service.db.save_run(
                _calculation(old_source, -10),
                {str(old_source.path): old_source.path},
            )
            reused_source = _source(
                root / "reused.xlsx",
                "same-hash",
                date(2026, 7, 1),
                date(2026, 7, 31),
            )
            reused_source.duplicate_run_ids = [old_id]
            session = ImportSession(
                sources=[reused_source],
                unknown_products=[],
                duplicate_sources=[reused_source],
            )

            with self.assertRaisesRegex(ValueError, "другой период"):
                service.replacement_run_ids(session)

    def test_replacement_is_atomic_preserves_name_and_does_not_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "app.sqlite3")
            stored_root = root / "source_files"
            stored_root.mkdir()
            start = date(2026, 6, 1)
            end = date(2026, 6, 30)

            old_stored = stored_root / "old.xlsx"
            old_stored.write_bytes(b"old")
            old_source = _source(root / "incoming-old.xlsx", "old-hash", start, end)
            old_id = database.save_run(
                _calculation(old_source, -100),
                {str(old_source.path): old_stored},
            )
            database.rename_run(old_id, "Мой отчет за июнь")

            new_stored = stored_root / "new.xlsx"
            new_stored.write_bytes(b"new")
            new_source = _source(root / "incoming-new.xlsx", "new-hash", start, end)
            new_source.duplicate_run_ids = [old_id]
            new_id = database.save_run(
                _calculation(new_source, -25),
                {str(new_source.path): new_stored},
                replace_run_ids=[old_id],
            )

            runs = database.list_runs()
            self.assertEqual([run.id for run in runs], [new_id])
            self.assertEqual(runs[0].report_name, "Мой отчет за июнь")
            self.assertEqual(database.load_calculation(new_id).unallocated_total, -25)
            self.assertFalse(old_stored.exists())
            self.assertTrue(new_stored.exists())
            self.assertNotIn(
                "Повторный файл",
                [event["event_type"] for event in database.list_quality_events(new_id)],
            )

    def test_failed_new_save_leaves_old_report_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "app.sqlite3")
            start = date(2026, 6, 1)
            end = date(2026, 6, 30)
            old_source = _source(root / "old.xlsx", "old-hash", start, end)
            old_id = database.save_run(
                _calculation(old_source, -100),
                {str(old_source.path): root / "old-stored.xlsx"},
            )
            new_source = _source(root / "new.xlsx", "new-hash", start, end)

            with self.assertRaises(KeyError):
                database.save_run(
                    _calculation(new_source, -25),
                    {},
                    replace_run_ids=[old_id],
                )

            self.assertEqual([run.id for run in database.list_runs()], [old_id])
            self.assertEqual(database.load_calculation(old_id).unallocated_total, -100)


if __name__ == "__main__":
    unittest.main()
