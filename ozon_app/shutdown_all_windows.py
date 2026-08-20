from __future__ import annotations

import tkinter as tk

from .detached_table_fix import DetachedTableFixOZPriceAnalyzerApp


def close_detached_tables(owner: object) -> int:
    """Close every detached table registered in the application's table modes."""
    closed = 0
    controllers = getattr(owner, "_table_modes", {}) or {}
    for controller in list(controllers.values()):
        detached = getattr(controller, "_detached", None)
        if detached is None:
            continue
        try:
            detached.close()
            closed += 1
        except (tk.TclError, RuntimeError):
            # Shutdown must continue even when one child window is already half-destroyed.
            try:
                controller._detached = None
            except Exception:
                pass
    return closed


def _collect_toplevels(widget: tk.Misc) -> list[tk.Toplevel]:
    result: list[tk.Toplevel] = []
    try:
        children = list(widget.winfo_children())
    except tk.TclError:
        return result

    for child in children:
        result.extend(_collect_toplevels(child))
        if isinstance(child, tk.Toplevel):
            result.append(child)
    return result


def destroy_child_toplevels(root: tk.Misc) -> int:
    """Destroy all remaining Toplevel descendants, deepest first."""
    destroyed = 0
    seen: set[str] = set()
    for window in _collect_toplevels(root):
        key = str(window)
        if key in seen:
            continue
        seen.add(key)
        try:
            if window.winfo_exists():
                try:
                    window.grab_release()
                except tk.TclError:
                    pass
                window.destroy()
                destroyed += 1
        except tk.TclError:
            pass
    return destroyed


class ShutdownAllWindowsOZPriceAnalyzerApp(DetachedTableFixOZPriceAnalyzerApp):
    """v0.5.13: exiting the app always closes every auxiliary window as well."""

    def __init__(self, *args, **kwargs) -> None:
        self._shutdown_started = False
        super().__init__(*args, **kwargs)
        self.protocol("WM_DELETE_WINDOW", self.close_application)

    def close_application(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        # Make the main window disappear immediately, so no notebook/table remnants
        # remain visible while Tk tears down auxiliary windows.
        try:
            self.withdraw()
        except tk.TclError:
            pass

        try:
            grabbed = self.grab_current()
            if grabbed is not None:
                grabbed.grab_release()
        except tk.TclError:
            pass

        close_detached_tables(self)
        destroy_child_toplevels(self)

        try:
            self.quit()
        except tk.TclError:
            pass

        try:
            tk.Tk.destroy(self)
        except tk.TclError:
            pass

    def destroy(self) -> None:
        """Route direct root.destroy() calls through the same complete shutdown path."""
        if not getattr(self, "_shutdown_started", False):
            self.close_application()
            return
        try:
            tk.Tk.destroy(self)
        except tk.TclError:
            pass


def run_app() -> None:
    app = ShutdownAllWindowsOZPriceAnalyzerApp()
    app.mainloop()
