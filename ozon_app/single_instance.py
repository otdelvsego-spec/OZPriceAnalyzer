from __future__ import annotations

import sys
import time
from typing import Callable, Protocol, TypeVar

from .config import APP_NAME, APP_TITLE


ERROR_ALREADY_EXISTS = 183
_App = TypeVar("_App")


class InstanceBackend(Protocol):
    def acquire(self) -> bool: ...

    def activate_existing(self) -> bool: ...

    def close(self) -> None: ...


class _NoopInstanceBackend:
    def acquire(self) -> bool:
        return True

    def activate_existing(self) -> bool:
        return False

    def close(self) -> None:
        return None


class _WindowsInstanceBackend:
    SW_SHOW = 5
    SW_RESTORE = 9
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040

    def __init__(
        self,
        application_id: str,
        window_title_prefix: str,
        *,
        activation_timeout: float = 10.0,
        poll_interval: float = 0.1,
    ) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.window_title_prefix = window_title_prefix
        self.activation_timeout = activation_timeout
        self.poll_interval = poll_interval
        self.mutex_name = f"Local\\{application_id}.SingleInstance"
        self.handle = None

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        ctypes = self.ctypes
        wintypes = self.wintypes

        self.kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

        self._enum_callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        self.user32.EnumWindows.argtypes = [self._enum_callback_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindowAsync.restype = wintypes.BOOL
        self.user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self.user32.BringWindowToTop.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.FlashWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.user32.FlashWindow.restype = wintypes.BOOL

    def acquire(self) -> bool:
        self.ctypes.set_last_error(0)
        handle = self.kernel32.CreateMutexW(None, False, self.mutex_name)
        if not handle:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        self.handle = handle
        if self.ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            return True
        self.close()
        return False

    def activate_existing(self) -> bool:
        deadline = time.monotonic() + self.activation_timeout
        while True:
            window = self._find_window()
            if window:
                return self._restore_and_activate(window)
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.poll_interval)

    def _find_window(self):
        found = []
        ctypes = self.ctypes

        @self._enum_callback_type
        def callback(window, _parameter):
            length = self.user32.GetWindowTextLengthW(window)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(window, buffer, len(buffer))
            if buffer.value.startswith(self.window_title_prefix):
                found.append(window)
                return False
            return True

        self.user32.EnumWindows(callback, 0)
        return found[0] if found else None

    def _restore_and_activate(self, window) -> bool:
        if not self.user32.IsWindow(window):
            return False
        command = self.SW_RESTORE if self.user32.IsIconic(window) else self.SW_SHOW
        self.user32.ShowWindowAsync(window, command)

        flags = self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_SHOWWINDOW
        topmost = self.wintypes.HWND(-1)
        not_topmost = self.wintypes.HWND(-2)
        self.user32.SetWindowPos(window, topmost, 0, 0, 0, 0, flags)
        self.user32.SetWindowPos(window, not_topmost, 0, 0, 0, 0, flags)
        self.user32.BringWindowToTop(window)
        if not self.user32.SetForegroundWindow(window):
            self.user32.FlashWindow(window, True)
        return True

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


class SingleInstanceGuard:
    def __init__(self, backend: InstanceBackend | None = None) -> None:
        self.backend = backend or _default_backend()
        self.is_primary = False
        self.activated_existing_window = False

    def __enter__(self) -> SingleInstanceGuard:
        self.is_primary = self.backend.acquire()
        if not self.is_primary:
            self.activated_existing_window = self.backend.activate_existing()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.backend.close()


def _default_backend() -> InstanceBackend:
    if sys.platform != "win32":
        return _NoopInstanceBackend()
    return _WindowsInstanceBackend(APP_NAME, APP_TITLE)


def launch_single_instance(
    app_factory: Callable[[], _App],
    *,
    guard: SingleInstanceGuard | None = None,
) -> bool:
    instance_guard = guard or SingleInstanceGuard()
    with instance_guard as instance:
        if not instance.is_primary:
            return False
        app = app_factory()
        app.mainloop()
        return True
