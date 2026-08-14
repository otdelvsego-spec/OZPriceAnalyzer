from __future__ import annotations

import tkinter as tk

from .cost_catalog_tab import CostCatalogTabOZPriceAnalyzerApp
from .display_modes import _button_with_text, resolve_ui_scale


class CatalogControlsVisibleOZPriceAnalyzerApp(CostCatalogTabOZPriceAnalyzerApp):
    """v0.5.8: keep all cost-catalog controls visible above the table splitter."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._catalog_splitter_base_upper = 225
        self._restore_catalog_control_layout()
        self._apply_catalog_minimum_height()
        self.after_idle(self._apply_catalog_minimum_height)

    def _restore_catalog_control_layout(self) -> None:
        """Place essential filter/XLSX controls before optional help text."""
        export_button = _button_with_text(self.cost_catalog_tab, "Выгрузить XLSX")
        if export_button is None:
            return

        filters = export_button.master
        try:
            filters.grid_configure(row=2, pady=(0, 6))
        except tk.TclError:
            pass

        if hasattr(self, "catalog_help_label"):
            try:
                self.catalog_help_label.grid_configure(row=3, pady=(0, 6))
            except tk.TclError:
                pass

    def _apply_catalog_minimum_height(self) -> None:
        if not hasattr(self, "_catalog_splitter"):
            return
        factor = resolve_ui_scale(
            self._saved_scale_preference(),
            int(self.winfo_screenheight()),
        )
        # Search/status/XLSX controls are essential and must never be clipped.
        self._catalog_splitter.min_upper = max(
            190,
            int(round(self._catalog_splitter_base_upper * factor)),
        )
        self._catalog_splitter._apply()

    def _apply_ui_scale(self, factor: float) -> None:
        super()._apply_ui_scale(factor)
        self._apply_catalog_minimum_height()


def run_app() -> None:
    app = CatalogControlsVisibleOZPriceAnalyzerApp()
    app.mainloop()
