"""Consent-driven, single-window remote control for the installed Codex/Claude apps.

This deliberately exposes a selected app window, not the desktop. Every input is tied
to the most recently returned frame so stale coordinates cannot be replayed.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
import os
from pathlib import Path
import threading
import time
import uuid
import re
from contextlib import contextmanager


_LOCK = threading.RLock()
class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

_APPS = {
    "codex": ("OpenAI.Codex_2p2nqsd0c76g0", "Codex"),
    "claude": ("Claude_pzs8sxrjxfjjc", "Claude"),
}
_LATEST: dict[str, tuple[str, int, tuple[int, int, int, int], str, float]] = {}


def _windows():
    if os.name != "nt":
        raise RuntimeError("Live app-window control is available only on Windows.")
    user32, kernel32, gdi32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.gdi32
    # ctypes otherwise truncates HWND/HDC/HBITMAP values to 32-bit ints on x64.
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetFocus.argtypes = [wintypes.HWND]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [_POINT]
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.SendInput.restype = wintypes.UINT
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    return user32, kernel32, gdi32


@contextmanager
def _physical_coordinates():
    user32, _, _ = _windows()
    previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))  # PER_MONITOR_AWARE_V2
    if not previous:
        raise RuntimeError("Windows could not enable physical-pixel coordinates for safe app control.")
    try:
        yield
    finally:
        user32.SetThreadDpiAwarenessContext(previous)


def _require_unlocked_desktop():
    user32, _, _ = _windows()
    DESKTOP_READOBJECTS, UOI_NAME = 0x0001, 2
    desktop = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not desktop:
        raise RuntimeError("The Windows input desktop is unavailable. Unlock the device to control its apps.")
    try:
        required = wintypes.DWORD()
        user32.GetUserObjectInformationW(desktop, UOI_NAME, None, 0, ctypes.byref(required))
        if required.value <= 2 or required.value > 1024:
            raise RuntimeError("Windows could not confirm the active input desktop.")
        name = ctypes.create_unicode_buffer(required.value // ctypes.sizeof(ctypes.c_wchar))
        if not user32.GetUserObjectInformationW(desktop, UOI_NAME, name, required.value, ctypes.byref(required)):
            raise RuntimeError("Windows could not confirm the active input desktop.")
        if name.value.casefold() != "default":
            raise RuntimeError("Unlock the Windows desktop before viewing or controlling app windows.")
    finally:
        user32.CloseDesktop(desktop)


def _exe_path(pid: int) -> str:
    _, kernel32, _ = _windows()
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return str(Path(buffer.value).resolve()).casefold()
    finally:
        kernel32.CloseHandle(handle)


def _package_for_path(path: str) -> str | None:
    normalized = path.replace("/", "\\").casefold()
    windowsapps = str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps").replace("/", "\\").casefold().rstrip("\\") + "\\"
    if normalized.startswith(windowsapps):
        package, _, remainder = normalized[len(windowsapps):].partition("\\")
        if (re.fullmatch(r"claude_[0-9][a-z0-9._-]*__pzs8sxrjxfjjc", package)
                and remainder == "app\\claude.exe"):
            return "claude"
        if (re.fullmatch(r"openai\.codex_[0-9][a-z0-9._-]*__2p2nqsd0c76g0", package)
                and remainder == "app\\chatgpt.exe"):
            return "codex"
        return None
    return None


def _enum_windows():
    user32, kernel32, _ = _windows()
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(min(length + 1, 2048))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = _exe_path(pid.value)
        app = _package_for_path(path)
        if not app:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 320 or height < 240:
            return True
        found.append({"id": app, "title": title_buffer.value[:300], "width": width,
                      "height": height, "_hwnd": int(hwnd), "_pid": pid.value,
                      "_path": path, "_rect": (rect.left, rect.top, rect.right, rect.bottom)})
        return True

    user32.EnumWindows(callback, 0)
    return found


def _select(app_id: str):
    if app_id not in _APPS:
        raise ValueError("Choose Codex or Claude.")
    matches = [window for window in _enum_windows() if window["id"] == app_id]
    if not matches:
        raise RuntimeError(f"The installed {app_id.title()} app has no visible window on this device.")
    foreground = int(ctypes.windll.user32.GetForegroundWindow())
    return next((w for w in matches if w["_hwnd"] == foreground), matches[0])


def _activate(window):
    user32, kernel32, _ = _windows()
    hwnd = window["_hwnd"]
    if not user32.IsWindow(hwnd):
        raise RuntimeError("The selected app window closed. Refresh the app list.")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # HTTP request threads have no message queue until their first USER message
    # call. AttachThreadInput otherwise silently fails for these fresh threads.
    message = wintypes.MSG()
    user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
    current_tid = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_pid = wintypes.DWORD()
    foreground_tid = user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid)) if foreground else 0
    target_pid = wintypes.DWORD()
    target_tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
    attached = []
    try:
        for other_tid in dict.fromkeys((foreground_tid, target_tid)):
            if other_tid and other_tid != current_tid and user32.AttachThreadInput(current_tid, other_tid, True):
                attached.append(other_tid)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        for _ in range(20):
            if int(user32.GetForegroundWindow()) == hwnd:
                break
            time.sleep(0.025)
    finally:
        for other_tid in reversed(attached):
            user32.AttachThreadInput(current_tid, other_tid, False)
    if int(user32.GetForegroundWindow()) != hwnd:
        raise RuntimeError("Windows would not focus the selected app. Try again when the desktop is available.")


def _capture(window) -> tuple[bytes, int, int]:
    user32, kernel32, gdi32 = _windows()
    from PIL import Image

    hwnd = window["_hwnd"]
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Could not read the selected app window bounds.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if not (320 <= width <= 10000 and 240 <= height <= 10000):
        raise RuntimeError("The selected app window has unsupported dimensions.")
    screen = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        # PW_RENDERFULLCONTENT is supported by the installed Chromium/Electron apps.
        if not user32.PrintWindow(hwnd, memory, 2):
            raise RuntimeError("Windows could not capture this app window. Its window may be locked or unavailable.")
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        raw = ctypes.create_string_buffer(width * height * 4)
        rows = gdi32.GetDIBits(memory, bitmap, 0, height, raw, ctypes.byref(info), 0)
        if rows != height:
            raise RuntimeError("The selected app frame could not be read completely.")
        image = Image.frombuffer("RGB", (width, height), raw.raw, "raw", "BGRX", 0, 1)
        if image.getbbox() is None:
            raise RuntimeError("Windows returned a blank app frame. The desktop may be locked or the window unavailable.")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=78, optimize=True)
        return output.getvalue(), width, height
    finally:
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd, screen)


def _fresh_frame(app_id: str, *, activate: bool = False) -> dict:
    window = _select(app_id)
    if activate:
        _activate(window)
    data, width, height = _capture(window)
    frame_id = uuid.uuid4().hex
    current = _select(app_id)
    if current["_hwnd"] != window["_hwnd"] or current["_path"] != window["_path"] or current["_rect"] != window["_rect"]:
        raise RuntimeError("The selected app window changed during capture. Refresh and retry.")
    _LATEST[app_id] = (frame_id, window["_hwnd"], window["_rect"], window["_path"], time.monotonic())
    return {"app": app_id, "title": window["title"], "frameId": frame_id,
            "width": width, "height": height, "capturedAt": time.time(),
            "mimeType": "image/jpeg", "image": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")}


class ConnectedAppWindow:
    """Operate one actual installed app window at a time, on the current device."""

    def list_apps(self) -> dict:
        with _LOCK, _physical_coordinates():
            apps = []
            for window in _enum_windows():
                item = {key: window[key] for key in ("id", "title", "width", "height")}
                if item["id"] not in {existing["id"] for existing in apps}:
                    apps.append(item)
            return {"apps": apps, "control": "single-window", "available": bool(apps)}

    def frame(self, app_id: str, *, activate: bool = False) -> dict:
        with _LOCK, _physical_coordinates():
            _require_unlocked_desktop()
            return _fresh_frame(str(app_id), activate=bool(activate))

    def action(self, app_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("An app-window action object is required.")
        app_id = str(app_id)
        with _LOCK, _physical_coordinates():
            _require_unlocked_desktop()
            latest = _LATEST.get(app_id)
            if not latest or payload.get("frameId") != latest[0] or time.monotonic() - latest[4] > 10:
                _LATEST.pop(app_id, None)
                raise ValueError("This app frame is out of date. Refresh it before interacting.")
            window = _select(app_id)
            if window["_hwnd"] != latest[1] or window["_path"] != latest[3] or window["_rect"] != latest[2]:
                _LATEST.pop(app_id, None)
                raise ValueError("The app window changed. Refresh before interacting.")
            _activate(window)
            # Consume the frame before the side effect. If capture/network fails after
            # input, retrying the old frame must not duplicate text or clicks.
            _LATEST.pop(app_id, None)
            action = payload.get("action")
            if action == "click":
                self._click(payload, latest[2], latest[1])
            elif action == "type":
                self._type(payload)
            elif action == "key":
                self._key(payload)
            elif action == "scroll":
                self._scroll(payload, latest[2], latest[1])
            else:
                raise ValueError("Supported actions are click, type, key, and scroll.")
            return _fresh_frame(app_id, activate=False)

    @staticmethod
    def _coordinate(payload, field, maximum):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < maximum:
            raise ValueError(f"{field} must be inside the selected app frame.")
        return int(value)

    @classmethod
    def _click(cls, payload, rect, target_hwnd):
        user32, _, _ = _windows()
        x = cls._coordinate(payload, "x", rect[2] - rect[0]) + rect[0]
        y = cls._coordinate(payload, "y", rect[3] - rect[1]) + rect[1]
        button = payload.get("button", "left")
        events = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}
        if button not in events:
            raise ValueError("Choose a left or right click.")
        clicks = payload.get("clicks", 1)
        if clicks not in (1, 2):
            raise ValueError("Choose one click or a double click.")
        user32.SetCursorPos(x, y)
        clicked_hwnd = user32.WindowFromPoint(_POINT(x, y))
        target_root = user32.GetAncestor(wintypes.HWND(target_hwnd), 2)
        clicked_root = user32.GetAncestor(clicked_hwnd, 2) if clicked_hwnd else None
        if int(clicked_root or 0) != int(target_root):
            raise RuntimeError("The click is covered by another window. Move or uncover the selected app and refresh.")
        for _ in range(clicks):
            user32.mouse_event(events[button][0], 0, 0, 0, 0)
            user32.mouse_event(events[button][1], 0, 0, 0, 0)

    @staticmethod
    def _type(payload):
        value = payload.get("text")
        if not isinstance(value, str) or not value or len(value) > 12000 or "\x00" in value:
            raise ValueError("Text must contain 1 to 12,000 characters.")
        user32, _, _ = _windows()
        KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]
        class INPUTUNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        if ctypes.sizeof(INPUT) != expected_size:
            raise RuntimeError("Windows input layout is unsupported on this device.")
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        inputs = []
        for char in value:
            code = ord(char)
            units = (code,) if code <= 0xFFFF else (0xD800 + ((code - 0x10000) >> 10), 0xDC00 + ((code - 0x10000) & 0x3FF))
            for unit in units:
                inputs.extend((INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, None))),
                               INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))))
        array = (INPUT * len(inputs))(*inputs)
        if user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
            raise RuntimeError("Windows accepted only part of the text input.")

    @staticmethod
    def _key(payload):
        user32, _, _ = _windows()
        key = payload.get("key")
        keys = {"Enter": 0x0D, "Escape": 0x1B, "Backspace": 0x08, "Tab": 0x09,
                "Delete": 0x2E, "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
                "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
                "Ctrl+A": (0x11, 0x41), "Ctrl+C": (0x11, 0x43), "Ctrl+V": (0x11, 0x56),
                "Ctrl+X": (0x11, 0x58), "Ctrl+Z": (0x11, 0x5A), "Ctrl+Y": (0x11, 0x59),
                "Ctrl+N": (0x11, 0x4E), "Ctrl+Enter": (0x11, 0x0D),
                "Shift+Enter": (0x10, 0x0D)}
        aliases = {"ENTER": "Enter", "ESC": "Escape", "BACKSPACE": "Backspace", "TAB": "Tab",
                   "DELETE": "Delete", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
                   "HOME": "Home", "END": "End", "PAGEUP": "PageUp", "PAGEDOWN": "PageDown",
                   "CTRL+A": "Ctrl+A", "CTRL+C": "Ctrl+C", "CTRL+V": "Ctrl+V", "CTRL+X": "Ctrl+X",
                   "CTRL+Z": "Ctrl+Z", "CTRL+Y": "Ctrl+Y", "CTRL+N": "Ctrl+N",
                   "CTRL+ENTER": "Ctrl+Enter", "SHIFT+ENTER": "Shift+Enter"}
        key = aliases.get(key, key)
        if key not in keys:
            raise ValueError("That key is unavailable for remote app control.")
        sequence = keys[key] if isinstance(keys[key], tuple) else (keys[key],)
        for code in sequence:
            user32.keybd_event(code, 0, 0, 0)
        for code in reversed(sequence):
            user32.keybd_event(code, 0, 0x0002, 0)

    @classmethod
    def _scroll(cls, payload, rect, target_hwnd):
        user32, _, _ = _windows()
        x = cls._coordinate(payload, "x", rect[2] - rect[0]) + rect[0]
        y = cls._coordinate(payload, "y", rect[3] - rect[1]) + rect[1]
        delta = payload.get("deltaY", 0)
        if isinstance(delta, bool) or not isinstance(delta, int) or not -1200 <= delta <= 1200 or delta == 0:
            raise ValueError("deltaY must be a nonzero whole value between -1200 and 1200.")
        user32.SetCursorPos(x, y)
        hovered = user32.WindowFromPoint(_POINT(x, y))
        if int(user32.GetAncestor(hovered, 2) if hovered else 0) != int(user32.GetAncestor(wintypes.HWND(target_hwnd), 2)):
            raise RuntimeError("The scroll point is covered by another window. Refresh the selected app and retry.")
        # Browser style: positive deltaY means scroll down. Win32 wheel polarity is inverse.
        user32.mouse_event(0x0800, 0, 0, ctypes.c_uint(-delta).value, 0)

