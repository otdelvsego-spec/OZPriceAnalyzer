from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk

from .controls_always_visible import ControlsAlwaysVisibleOZPriceAnalyzerApp


def _tree_columns(tree: ttk.Treeview) -> tuple[str, ...]:
    configured = tree.cget("displaycolumns")
    if configured in ("#all", ("#all",)):
        return tuple(str(column) for column in tree.cget("columns"))
    if isinstance(configured, (tuple, list)):
        return tuple(str(column) for column in configured)
    return tuple(str(column) for column in tree.tk.splitlist(configured))


class _HeadingTooltipManager:
    """Keep Treeview headings readable and show the full title on hover."""

    HORIZONTAL_PADDING = 34
    TOOLTIP_DELAY_MS = 250

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._tooltip: tk.Toplevel | None = None
        self._tooltip_label: tk.Label | None = None
        self._tooltip_after: str | None = None
        self._current_heading: tuple[str, str] | None = None
        self._fit_pending: set[str] = set()

        root.bind_class("Treeview", "<Map>", self._schedule_fit, add="+")
        root.bind_class("Treeview", "<Configure>", self._schedule_fit, add="+")
        root.bind_class("Treeview", "<Motion>", self._on_motion, add="+")
        root.bind_class("Treeview", "<Leave>", self._hide_tooltip, add="+")
        root.bind_class("Treeview", "<ButtonPress-1>", self._hide_tooltip, add="+")
        root.bind_class("Treeview", "<MouseWheel>", self._hide_tooltip, add="+")
        root.after_idle(self.fit_all)

    def _heading_font(self, tree: ttk.Treeview) -> tkfont.Font:
        style = ttk.Style(tree)
        font_spec = style.lookup("Treeview.Heading", "font") or "TkHeadingFont"
        try:
            return tkfont.Font(root=tree, font=font_spec)
        except tk.TclError:
            return tkfont.nametofont("TkHeadingFont", root=tree)

    def fit_tree(self, tree: ttk.Treeview) -> None:
        if not tree.winfo_exists():
            return
        try:
            heading_font = self._heading_font(tree)
            for column in _tree_columns(tree):
                text = str(tree.heading(column).get("text", "") or "")
                if not text:
                    continue
                required = max(70, heading_font.measure(text) + self.HORIZONTAL_PADDING)
                config = tree.column(column)
                width = int(config.get("width", 0) or 0)
                minwidth = int(config.get("minwidth", 0) or 0)
                changes = {}
                if width < required:
                    changes["width"] = required
                if minwidth < required:
                    changes["minwidth"] = required
                if changes:
                    tree.column(column, **changes)
        except tk.TclError:
            return

    def fit_all(self) -> None:
        for tree in self._iter_treeviews(self.root):
            self.fit_tree(tree)

    def _iter_treeviews(self, widget: tk.Misc):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Treeview):
                yield child
            yield from self._iter_treeviews(child)

    def _schedule_fit(self, event=None) -> None:
        tree = getattr(event, "widget", None)
        if not isinstance(tree, ttk.Treeview):
            return
        key = str(tree)
        if key in self._fit_pending:
            return
        self._fit_pending.add(key)

        def apply() -> None:
            self._fit_pending.discard(key)
            self.fit_tree(tree)

        try:
            tree.after_idle(apply)
        except tk.TclError:
            self._fit_pending.discard(key)

    def _on_motion(self, event) -> None:
        tree = event.widget
        if not isinstance(tree, ttk.Treeview):
            self._hide_tooltip()
            return
        try:
            if tree.identify_region(event.x, event.y) != "heading":
                self._hide_tooltip()
                return
            token = tree.identify_column(event.x)
            if not token.startswith("#"):
                self._hide_tooltip()
                return
            index = int(token[1:]) - 1
            columns = _tree_columns(tree)
            if index < 0 or index >= len(columns):
                self._hide_tooltip()
                return
            column = columns[index]
            text = str(tree.heading(column).get("text", "") or "").strip()
        except (ValueError, tk.TclError):
            self._hide_tooltip()
            return

        if not text:
            self._hide_tooltip()
            return

        key = (str(tree), column)
        if self._current_heading == key and self._tooltip is not None:
            return

        self._cancel_pending_tooltip()
        self._hide_tooltip_window()
        self._current_heading = key
        x = int(event.x_root) + 14
        y = int(event.y_root) + 18
        try:
            self._tooltip_after = tree.after(
                self.TOOLTIP_DELAY_MS,
                lambda: self._show_tooltip(text, x, y),
            )
        except tk.TclError:
            self._tooltip_after = None

    def _show_tooltip(self, text: str, x: int, y: int) -> None:
        self._tooltip_after = None
        try:
            tip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except tk.TclError:
                pass
            label = tk.Label(
                tip,
                text=text,
                justify="left",
                relief="solid",
                borderwidth=1,
                padx=7,
                pady=4,
                background="#fffde7",
                foreground="#111111",
                font="TkDefaultFont",
            )
            label.pack()
            tip.geometry(f"+{x}+{y}")
            self._tooltip = tip
            self._tooltip_label = label
        except tk.TclError:
            self._tooltip = None
            self._tooltip_label = None

    def _cancel_pending_tooltip(self) -> None:
        if self._tooltip_after is None:
            return
        try:
            self.root.after_cancel(self._tooltip_after)
        except tk.TclError:
            pass
        self._tooltip_after = None

    def _hide_tooltip_window(self) -> None:
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except tk.TclError:
                pass
        self._tooltip = None
        self._tooltip_label = None

    def _hide_tooltip(self, _event=None) -> None:
        self._cancel_pending_tooltip()
        self._hide_tooltip_window()
        self._current_heading = None


class FullColumnHeadingsOZPriceAnalyzerApp(ControlsAlwaysVisibleOZPriceAnalyzerApp):
    """v0.5.11: full column headings and heading tooltips everywhere."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._heading_tooltips = _HeadingTooltipManager(self)
        self.after_idle(self._heading_tooltips.fit_all)

    def _apply_ui_scale(self, factor: float) -> None:
        super()._apply_ui_scale(factor)
        if hasattr(self, "_heading_tooltips"):
            self.after_idle(self._heading_tooltips.fit_all)


def run_app() -> None:
    app = FullColumnHeadingsOZPriceAnalyzerApp()
    app.mainloop()
