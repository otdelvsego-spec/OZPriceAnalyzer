from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import display_modes as _display_modes
from .heading_tooltips import FullColumnHeadingsOZPriceAnalyzerApp


_OriginalDetachedTableWindow = _display_modes._DetachedTableWindow


def detached_filter_key(owner: object, source: object) -> str | None:
    """Return the category-filter scope that belongs to a detached table."""
    if source is getattr(owner, "overview_tree", None):
        return "overview"
    if source is getattr(owner, "scenario_tree", None):
        return "scenario"
    return None


class FixedDetachedTableWindow(_OriginalDetachedTableWindow):
    """Detached table with reliable closing and mirrored category controls."""

    def __init__(self, owner, source, title, **kwargs) -> None:
        self._filter_key = detached_filter_key(owner, source)
        super().__init__(owner, source, title, **kwargs)
        self._install_category_filter_bar()

    def _install_category_filter_bar(self) -> None:
        key = self._filter_key
        if key is None:
            return

        label_var = getattr(self.owner, f"{key}_category_filter_label_var", None)
        exclude_var = getattr(self.owner, f"{key}_category_exclude_var", None)
        choose = getattr(self.owner, "_choose_categories", None)
        mode_changed = getattr(self.owner, "_on_category_mode_changed", None)
        if label_var is None or exclude_var is None or not callable(choose) or not callable(mode_changed):
            return

        table_container = None
        for child in self.window.winfo_children():
            if child.winfo_manager() != "grid":
                continue
            try:
                if int(child.grid_info().get("row", -1)) == 1:
                    table_container = child
                    break
            except (TypeError, ValueError, tk.TclError):
                continue

        if table_container is None:
            return

        try:
            table_container.grid_configure(row=2)
            self.window.rowconfigure(1, weight=0)
            self.window.rowconfigure(2, weight=1)
        except tk.TclError:
            return

        bar = ttk.Frame(self.window, padding=(10, 0, 10, 8))
        bar.grid(row=1, column=0, sticky="ew")
        bar.columnconfigure(3, weight=1)

        ttk.Label(bar, text="Категория:").grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            bar,
            textvariable=label_var,
            command=self._choose_categories,
            width=24,
        ).grid(row=0, column=1, padx=(0, 10))
        ttk.Checkbutton(
            bar,
            text="Исключить выбранные",
            variable=exclude_var,
            command=self._category_mode_changed,
        ).grid(row=0, column=2, sticky="w")
        ttk.Label(
            bar,
            text="Фильтр синхронизирован с основной таблицей",
            style="Muted.TLabel",
        ).grid(row=0, column=3, sticky="e", padx=(16, 0))

    def _choose_categories(self) -> None:
        key = self._filter_key
        callback = getattr(self.owner, "_choose_categories", None)
        if key is None or not callable(callback):
            return
        callback(key)
        try:
            self.refresh(force=True)
        except tk.TclError:
            pass

    def _category_mode_changed(self) -> None:
        key = self._filter_key
        callback = getattr(self.owner, "_on_category_mode_changed", None)
        if key is None or not callable(callback):
            return
        callback(key)
        try:
            self.refresh(force=True)
        except tk.TclError:
            pass

    def _clear_controller_reference(self) -> None:
        controllers = getattr(self.owner, "_table_modes", {})
        for controller in controllers.values():
            if getattr(controller, "_detached", None) is self:
                controller._detached = None

    def close(self) -> None:
        """Close immediately and make the controller forget this window."""
        if getattr(self, "_closed", False):
            return
        self._closed = True

        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            self.window.withdraw()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            # Fallback for a partially torn-down Toplevel path.
            try:
                self.window.tk.call("destroy", self.window._w)
            except tk.TclError:
                pass
        finally:
            self._clear_controller_reference()


# _TableModeController.open_detached resolves this module global at call time,
# so replacing it here fixes every existing controller, including the cost catalog.
_display_modes._DetachedTableWindow = FixedDetachedTableWindow


class DetachedTableFixOZPriceAnalyzerApp(FullColumnHeadingsOZPriceAnalyzerApp):
    """v0.5.12: reliable detached-window closing and mirrored category filters."""


def run_app() -> None:
    app = DetachedTableFixOZPriceAnalyzerApp()
    app.mainloop()
