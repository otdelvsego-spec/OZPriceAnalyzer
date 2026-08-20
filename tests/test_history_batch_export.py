from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ozon_app.history_batch_export import available_export_path, ordered_selected_iids


class HistoryBatchExportTests(unittest.TestCase):
    def test_selected_rows_keep_history_table_order(self) -> None:
        visible = ("7", "4", "9", "2")
        selected = ("2", "7", "9")
        self.assertEqual(ordered_selected_iids(visible, selected), ["7", "9", "2"])

    def test_available_path_never_overwrites_existing_or_reserved_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "Отчет_OZON_01.01.2026-31.01.2026.xlsx").write_bytes(b"old")
            reserved: set[str] = set()

            first = available_export_path(
                folder,
                "Отчет_OZON_01.01.2026-31.01.2026.xlsx",
                reserved,
            )
            second = available_export_path(
                folder,
                "Отчет_OZON_01.01.2026-31.01.2026.xlsx",
                reserved,
            )

            self.assertEqual(first.name, "Отчет_OZON_01.01.2026-31.01.2026 (2).xlsx")
            self.assertEqual(second.name, "Отчет_OZON_01.01.2026-31.01.2026 (3).xlsx")


if __name__ == "__main__":
    unittest.main()
