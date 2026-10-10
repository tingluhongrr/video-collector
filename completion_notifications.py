"""Short-lived Windows task notifications without optional packages.

All methods must be called on the Tk main thread.  A successful ``show``
means the Windows Shell accepted the request; notification preferences or
quiet time can still prevent a banner from appearing.

Win32 contracts:
https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw
https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01
NIIF_RESPECT_QUIET_TIME = 0x80
NOTIFYICON_VERSION_4 = 4


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


class _TimeoutVersion(ctypes.Union):
    _fields_ = [("uTimeout", ctypes.c_uint32), ("uVersion", ctypes.c_uint32)]


class _NOTIFYICONDATAW(ctypes.Structure):
    # DWORD/UINT are always 32 bits; HWND/HICON are pointer-sized on x64.
    _anonymous_ = ("timeout_version",)
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint32),
        ("dwStateMask", ctypes.c_uint32),
        ("szInfo", ctypes.c_wchar * 256),
        ("timeout_version", _TimeoutVersion),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint32),
        ("guidItem", _GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


def _fit_utf16(text: str, capacity: int) -> str:
    """Keep space for the Windows WCHAR buffer's NUL, including emoji."""
    cleaned = str(text).replace("\x00", "")
    encoded = cleaned.encode("utf-16-le", errors="replace")
    return encoded[: (capacity - 1) * 2].decode("utf-16-le", errors="ignore")


class _WindowsAPI:
    """Small typed boundary, replaced by mocks in the backend tests."""

    def __init__(self):
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32.Shell_NotifyIconW.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(_NOTIFYICONDATAW)
        ]
        self.shell32.Shell_NotifyIconW.restype = ctypes.c_int
        self.user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.user32.GetAncestor.restype = ctypes.c_void_p
        self.user32.LoadImageW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
        ]
        self.user32.LoadImageW.restype = ctypes.c_void_p
        self.user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.LoadIconW.restype = ctypes.c_void_p
        self.user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        self.user32.DestroyIcon.restype = ctypes.c_int

    def root_handle(self, tk_handle: int) -> int:
        # Tk's winfo_id may identify the inner window rather than its wrapper.
        return self.user32.GetAncestor(tk_handle, 2) or tk_handle

    def load_icon(self, icon_path: str | None) -> tuple[int, bool]:
        if icon_path:
            icon = self.user32.LoadImageW(None, icon_path, 1, 0, 0, 0x10 | 0x40)
            if icon:
                return icon, True
        # The system icon is shared and must never be passed to DestroyIcon.
        return self.user32.LoadIconW(None, ctypes.c_void_p(32512)) or 0, False

    def notify(self, command: int, data: _NOTIFYICONDATAW) -> bool:
        return bool(self.shell32.Shell_NotifyIconW(command, ctypes.byref(data)))

    def destroy_icon(self, icon: int) -> None:
        self.user32.DestroyIcon(icon)


class DesktopNotifier:
    """Temporarily own a tray icon while showing a task-completion banner.

    ``show(title, message)`` returns False for unsupported systems/API errors,
    so callers can use an application-local, non-modal fallback.  ``close``
    is idempotent and prevents any subsequent notification.
    """

    DISPLAY_LIFETIME_MS = 30_000

    def __init__(self, root, icon_path: str | Path | None = None):
        self.root = root
        self.icon_path = str(icon_path) if icon_path else None
        self._api: _WindowsAPI | None = None
        self._data: _NOTIFYICONDATAW | None = None
        self._icon = 0
        self._owns_icon = False
        self._active = False
        self._closed = False
        self._cleanup_job = None
        self._generation = 0
        self._destroy_binding = None
        try:
            self._destroy_binding = root.bind("<Destroy>", self._on_destroy, add="+")
        except Exception:
            # A closing/unavailable Tk root must never break a completed task.
            pass

    def show(self, title: str, message: str) -> bool:
        if self._closed or sys.platform != "win32":
            return False
        try:
            if self._api is None:
                self._api = _WindowsAPI()
            if not self._active:
                hwnd = self._api.root_handle(int(self.root.winfo_id()))
                if not hwnd:
                    return False
                self._icon, self._owns_icon = self._api.load_icon(self.icon_path)
                if not self._icon:
                    return False
                data = _NOTIFYICONDATAW()
                data.cbSize = ctypes.sizeof(data)
                data.hWnd = hwnd
                data.uID = 1
                data.uFlags = NIF_ICON | NIF_TIP
                data.hIcon = self._icon
                data.szTip = "视频采集器"
                self._data = data
                if not self._api.notify(NIM_ADD, data):
                    self._release()
                    return False
                self._active = True
                data.uVersion = NOTIFYICON_VERSION_4
                # Failure to change callback semantics does not block a banner;
                # we intentionally install no window procedure or click handler.
                self._api.notify(NIM_SETVERSION, data)

            data = self._data
            data.uFlags = NIF_INFO
            data.szInfoTitle = _fit_utf16(title or "视频采集器", 64)
            data.szInfo = _fit_utf16(message, 256)
            data.dwInfoFlags = NIIF_INFO | NIIF_RESPECT_QUIET_TIME
            if not self._api.notify(NIM_MODIFY, data):
                self._release()
                return False

            self._cancel_cleanup()
            generation = self._generation

            def expire():
                if generation == self._generation:
                    self._cleanup_job = None
                    self._release()

            self._cleanup_job = self.root.after(self.DISPLAY_LIFETIME_MS, expire)
            return True
        except Exception:
            self._release()
            return False

    def _cancel_cleanup(self) -> None:
        self._generation += 1
        job, self._cleanup_job = self._cleanup_job, None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def _release(self) -> None:
        self._cancel_cleanup()
        active, self._active = self._active, False
        data, self._data = self._data, None
        icon, self._icon = self._icon, 0
        owned, self._owns_icon = self._owns_icon, False
        if active and self._api is not None and data is not None:
            try:
                self._api.notify(NIM_DELETE, data)
            except Exception:
                pass
        if owned and icon and self._api is not None:
            try:
                self._api.destroy_icon(icon)
            except Exception:
                pass

    def _on_destroy(self, event) -> None:
        if event.widget is self.root:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._release()
        binding, self._destroy_binding = self._destroy_binding, None
        if binding:
            try:
                self.root.unbind("<Destroy>", binding)
            except Exception:
                pass
