from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ozon_app.calculator import calculate_run, discover_unknown_products
from ozon_app.database import Database
from ozon_app.excel_reader import REPORT_REALIZATION, ReportFormatError, parse_report


@unittest.skipUnless(os.environ.get("OZON_REPORTS_DIR"), "OZON_REPORTS_DIR не задан")
class UploadedReportRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(os.environ["OZON_REPORTS_DIR"])

    def test_july_breakdown_and_realization_validation(self) -> None:
        july = parse_report(self.root / "Отчет по начислениям_01.07.2026-29.07.2026.xlsx")
        valid = parse_report(self.root / "RealizationReportCIS-12439885000000.xlsx")
        self.assertEqual(valid.report_type, REPORT_REALIZATION)
        self.assertEqual(sum(row.quantity for row in valid.realization_rows), 8)
        self.assertAlmostEqual(sum(row.amount for row in valid.realization_rows), 1_613.68)

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.sqlite3")
            products = database.product_map(active_only=True)
            unknown = discover_unknown_products([july], products)
            calculation = calculate_run(
                [july],
                products,
                0.04,
                skipped_articles={item.article for item in unknown},
            )
        self.assertAlmostEqual(calculation.unallocated_total, -25_050)
        self.assertAlmostEqual(sum(value[1] for value in calculation.unallocated.values()), -25_050)
        self.assertEqual(
            calculation.unallocated["Обеспечение материалами для упаковки товара"],
            (4, -20),
        )
        self.assertEqual(
            calculation.accrual_stats["Обеспечение материалами для упаковки товара"],
            (8, 4),
        )

        with self.assertRaises(ReportFormatError):
            parse_report(self.root / "RealizationReportCIS-124398851.xlsx")


if __name__ == "__main__":
    unittest.main()
