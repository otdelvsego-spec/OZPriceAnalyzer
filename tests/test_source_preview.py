from __future__ import annotations

import unittest

from ozon_app.ui import OZPriceAnalyzerApp


class _Variable:
    def __init__(self, value):
        self.value = value

    def set(self, value) -> None:
        self.value = value


class _Combo(dict):
    pass


class _SourceTree:
    def __init__(self) -> None:
        self.removed: tuple[str, ...] = ()

    @staticmethod
    def selection() -> tuple[str, ...]:
        return ("17",)

    def selection_remove(self, *items: str) -> None:
        self.removed = items


class _Master:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _PreviewTree:
    def __init__(self) -> None:
        self.master = _Master()


class _Button:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class SourcePreviewTests(unittest.TestCase):
    def test_clear_preview_resets_the_entire_preview_block_only(self) -> None:
        class AppStub:
            preview_path = "C:/reports/report.xlsx"
            preview_headers = ["Строка", "A"]
            preview_rows = [["1", "значение"]]
            preview_search_var = _Variable("значение")
            sheet_var = _Variable("Лист1")
            sheet_combo = _Combo(values=("Лист1",))
            preview_file_var = _Variable("Файл: report.xlsx")
            source_tree = _SourceTree()
            preview_tree = _PreviewTree()
            clear_preview_button = _Button()

        app = AppStub()
        old_master = app.preview_tree.master
        OZPriceAnalyzerApp.clear_xlsx_preview(app)

        self.assertIsNone(app.preview_path)
        self.assertEqual(app.preview_headers, [])
        self.assertEqual(app.preview_rows, [])
        self.assertEqual(app.preview_search_var.value, "")
        self.assertEqual(app.sheet_var.value, "")
        self.assertEqual(app.sheet_combo["values"], ())
        self.assertEqual(app.preview_file_var.value, "Файл не выбран")
        self.assertEqual(app.source_tree.removed, ("17",))
        self.assertTrue(old_master.destroyed)
        self.assertIsNone(app.preview_tree)
        self.assertEqual(app.clear_preview_button.state, "disabled")


if __name__ == "__main__":
    unittest.main()
