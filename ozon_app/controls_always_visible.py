from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .catalog_controls_fix import CatalogControlsVisibleOZPriceAnalyzerApp


_INTERACTIVE_TYPES = (
    ttk.Button,
    ttk.Entry,
    ttk.Combobox,
    ttk.Checkbutton,
    ttk.Radiobutton,
    ttk.Spinbox,
    tk.Button,
    tk.Entry,
)


def _contains_interactive(widget: tk.Misc) -> bool:
    if isinstance(widget, _INTERACTIVE_TYPES):
        return True
    return any(_contains_interactive(child) for child in widget.winfo_children())


class ControlsAlwaysVisibleOZPriceAnalyzerApp(CatalogControlsVisibleOZPriceAnalyzerApp):
    """v0.5.9: resizing may scale controls, but must never clip action rows."""

    MIN_TABLE_HEIGHT = 90

    def __init__(self, *args, **kwargs) -> None:
        self._controls_guard_pending = False
        super().__init__(*args, **kwargs)
        self.bind("<Configure>", self._schedule_controls_guard, add="+")
        self.notebook.bind("<<NotebookTabChanged>>", self._schedule_controls_guard, add="+")
        self.after_idle(self._enforce_controls_visible)

    def _iter_tabs(self):
        for tab_id in self.notebook.tabs():
            try:
                yield self.nametowidget(tab_id)
            except (KeyError, tk.TclError):
                continue

    def _splitters(self):
        for name in (
            "_overview_splitter",
            "_scenario_splitter",
            "_catalog_splitter",
            "_settings_splitter",
        ):
            splitter = getattr(self, name, None)
            if splitter is not None and not getattr(splitter, "suspended", False):
                yield splitter

    def _schedule_controls_guard(self, _event=None) -> None:
        if self._controls_guard_pending:
            return
        self._controls_guard_pending = True
        self.after_idle(self._enforce_controls_visible)

    def _enforce_controls_visible(self) -> None:
        self._controls_guard_pending = False
        try:
            self.update_idletasks()
        except tk.TclError:
            return

        # Every currently visible tab row that contains an interactive control gets
        # a real minimum height equal to its requested height. This prevents a
        # Treeview or splitter from squeezing buttons/filters to a few pixels.
        for tab in self._iter_tabs():
            row_minimums: dict[int, int] = {}
            for child in tab.winfo_children():
                if child.winfo_manager() != "grid" or not _contains_interactive(child):
                    continue
                try:
                    row = int(child.grid_info().get("row", -1))
                    requested = int(child.winfo_reqheight())
                except (TypeError, ValueError, tk.TclError):
                    continue
                if row >= 0:
                    row_minimums[row] = max(row_minimums.get(row, 0), requested)

            for row, requested in row_minimums.items():
                try:
                    current = int(tab.grid_rowconfigure(row).get("minsize", 0) or 0)
                    if current != requested:
                        tab.rowconfigure(row, minsize=requested)
                except (TypeError, ValueError, tk.TclError):
                    pass

        # Protect every visible row above each draggable separator, not just a
        # hard-coded subset. The table is allowed to become smaller; controls are not.
        for splitter in self._splitters():
            protected: set[int] = set()
            for child in splitter.parent.winfo_children():
                if child.winfo_manager() != "grid":
                    continue
                try:
                    row = int(child.grid_info().get("row", -1))
                except (TypeError, ValueError, tk.TclError):
                    continue
                if 0 <= row < splitter.row:
                    protected.add(row)

            splitter.protected_rows = tuple(sorted(protected))
            splitter.min_table = self.MIN_TABLE_HEIGHT
            try:
                splitter._apply()
            except tk.TclError:
                pass

        # The cost-catalog toolbar is a nested frame. Lock its parent row to the
        # toolbar's full requested height so Search/XLSX/Clear cannot be clipped.
        if hasattr(self, "cost_catalog_tab"):
            try:
                top = next(
                    child
                    for child in self.cost_catalog_tab.winfo_children()
                    if child.winfo_manager() == "grid"
                    and int(child.grid_info().get("row", -1)) == 0
                )
                requested = int(top.winfo_reqheight())
                current = int(
                    self.cost_catalog_tab.grid_rowconfigure(0).get("minsize", 0) or 0
                )
                if current != requested:
                    self.cost_catalog_tab.rowconfigure(0, minsize=requested)
            except (StopIteration, TypeError, ValueError, tk.TclError):
                pass

    def _apply_ui_scale(self, factor: float) -> None:
        super()._apply_ui_scale(factor)
        if hasattr(self, "notebook"):
            self._schedule_controls_guard()


def run_app() -> None:
    app = ControlsAlwaysVisibleOZPriceAnalyzerApp()
    app.mainloop()
