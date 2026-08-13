from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ozon_app.database import Database
from ozon_app.models import RunCalculation
from ozon_app.ui import OZPriceAnalyzerApp


class HistoryManagementTests(unittest.TestCase):
    def test_history_selection_requests_quality_for_highlighted_run(self) -> None:
        class SelectedTree:
            @staticmethod
            def selection() -> tuple[str, ...]:
                return ("27",)

        class AppStub:
            history_tree = SelectedTree()

            def __init__(self) -> None:
                self.requested: tuple[int | None, bool] | None = None

            def _populate_quality(self, run_id=None, *, use_current=True) -> None:
                self.requested = (run_id, use_current)

        app = AppStub()
        OZPriceAnalyzerApp._on_history_selected(app)
        self.assertEqual(app.requested, (27, False))

    def test_existing_database_gets_report_names_without_losing_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute(
                    """
                    CREATE TABLE runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        period_start TEXT,
                        period_end TEXT,
                        tax_rate REAL NOT NULL,
                        source_count INTEGER NOT NULL,
                        units REAL NOT NULL,
                        revenue REAL NOT NULL,
                        financial_result REAL NOT NULL,
                        cost_sold REAL NOT NULL,
                        tax REAL NOT NULL,
                        net_profit REAL NOT NULL,
                        unallocated_total REAL NOT NULL,
                        realization_revenue REAL NOT NULL DEFAULT 0,
                        realization_units REAL NOT NULL DEFAULT 0,
                        duplicate_realization_rows INTEGER NOT NULL DEFAULT 0,
                        already_accrued_realization_rows INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'Готов'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO runs(
                        period_start, period_end, tax_rate, source_count, units, revenue,
                        financial_result, cost_sold, tax, net_profit, unallocated_total
                    ) VALUES ('2026-07-01', '2026-07-29', 0.04, 0, 0, 0, 0, 0, 0, 0, 0)
                    """
                )
                db.commit()

            runs = Database(path).list_runs()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].report_name, "Отчет Ozon за 01.07.2026–29.07.2026")

    def test_report_name_can_be_changed_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            database = Database(path)
            run_id = database.save_run(
                RunCalculation(
                    run_id=None,
                    period_start=None,
                    period_end=None,
                    tax_rate=0.04,
                    products=[],
                    unallocated_total=0,
                    unallocated={},
                    accrual_stats={},
                ),
                {},
            )
            self.assertEqual(database.list_runs()[0].report_name, f"Отчет Ozon #{run_id}")

            database.rename_run(run_id, "  Июльский   отчет  ")
            self.assertEqual(Database(path).list_runs()[0].report_name, "Июльский отчет")
            with self.assertRaises(ValueError):
                database.rename_run(run_id, "   ")

    def test_delete_cascades_and_keeps_shared_source_until_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "app.sqlite3")
            source = root / "source_files" / "shared.xlsx"
            source.parent.mkdir()
            source.write_bytes(b"same source")

            with database.transaction() as db:
                first_id = self._insert_run(db, "Первый")
                second_id = self._insert_run(db, "Второй")
                for run_id in (first_id, second_id):
                    db.execute(
                        """
                        INSERT INTO source_files(
                            run_id, original_name, original_path, stored_path, file_hash,
                            report_type, sheet_name, header_row, row_count, total_amount
                        ) VALUES (?, 'shared.xlsx', 'C:\\source.xlsx', ?, 'same-hash',
                                  'ACCRUAL', 'Начисления', 1, 1, 10)
                        """,
                        (run_id, str(source)),
                    )
                db.execute("INSERT INTO unallocated VALUES (?, 'Подписка', 1, -10)", (first_id,))
                db.execute("INSERT INTO accrual_stats VALUES (?, 'подписка', 'Подписка', 0, 1)", (first_id,))
                db.execute(
                    "INSERT INTO quality_events(run_id, severity, event_type, message) "
                    "VALUES (?, 'Предупреждение', 'Проверка', 'Сообщение')",
                    (first_id,),
                )
                db.execute("INSERT INTO scenario_prices(run_id, article, planned_price) VALUES (?, 'A', 100)", (first_id,))

            self.assertEqual(database.delete_run(first_id), 0)
            self.assertTrue(source.is_file())
            with database.read() as db:
                for table in ("source_files", "unallocated", "accrual_stats", "quality_events", "scenario_prices"):
                    self.assertEqual(
                        db.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (first_id,)).fetchone()[0],
                        0,
                    )
            self.assertEqual([run.id for run in database.list_runs()], [second_id])

            self.assertEqual(database.delete_run(second_id), 1)
            self.assertFalse(source.exists())
            self.assertEqual(database.list_runs(), [])

    @staticmethod
    def _insert_run(db: sqlite3.Connection, report_name: str) -> int:
        return int(
            db.execute(
                """
                INSERT INTO runs(
                    report_name, period_start, period_end, tax_rate, source_count,
                    units, revenue, financial_result, cost_sold, tax, net_profit,
                    unallocated_total, realization_revenue, realization_units,
                    duplicate_realization_rows, already_accrued_realization_rows, status
                ) VALUES (?, '2026-07-01', '2026-07-29', 0.04, 1,
                          0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'Готов')
                """,
                (report_name,),
            ).lastrowid
        )


if __name__ == "__main__":
    unittest.main()
