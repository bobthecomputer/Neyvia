"""Independent, read-only Win32 readback of an agent-desktop window.

Runs in its own process. It shares no code, UI Automation client or driver
state with the CUA service: it opens the private desktop by name, enumerates
that desktop's top-level windows, picks the one owned by the given process,
reads its child Edit controls with WM_GETTEXT, and confirms that the process
has no window on the input desktop Paul sees. Nothing is clicked, typed,
focused or shown.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import sys

u = C.WinDLL("user32", use_last_error=True)
ENUM = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
u.OpenDesktopW.argtypes = [W.LPCWSTR, W.DWORD, W.BOOL, W.DWORD]
u.OpenDesktopW.restype = W.HANDLE
u.OpenInputDesktop.argtypes = [W.DWORD, W.BOOL, W.DWORD]
u.OpenInputDesktop.restype = W.HANDLE
u.CloseDesktop.argtypes = [W.HANDLE]
u.EnumDesktopWindows.argtypes = [W.HANDLE, ENUM, W.LPARAM]
u.EnumChildWindows.argtypes = [W.HWND, ENUM, W.LPARAM]
u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.IsWindowVisible.argtypes = [W.HWND]
u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
u.SendMessageTimeoutW.restype = C.c_size_t
WM_GETTEXT, WM_GETTEXTLENGTH, SMTO_ABORTIFHUNG = 0x000D, 0x000E, 0x0002


def windows(desktop):
    found = []

    @ENUM
    def visit(hwnd, _):
        found.append(int(hwnd))
        return True
    u.EnumDesktopWindows(desktop, visit, 0)
    return found


def owner(hwnd):
    pid = W.DWORD()
    u.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return int(pid.value)


def text_of(hwnd):
    length = C.c_size_t()
    if not u.SendMessageTimeoutW(hwnd, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, 2000, C.byref(length)):
        return None
    buffer = C.create_unicode_buffer(length.value + 1)
    copied = C.c_size_t()
    if not u.SendMessageTimeoutW(hwnd, WM_GETTEXT, length.value + 1, C.cast(buffer, C.c_void_p).value or 0,
                                 SMTO_ABORTIFHUNG, 2000, C.byref(copied)):
        return None
    return buffer.value


def class_of(hwnd):
    buffer = C.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def title_of(hwnd):
    buffer = C.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def readback(desktop_name, pid):
    name = desktop_name.split("\\")[-1]
    if not name.startswith("Neyvia-C11-"):
        raise SystemExit("Only a Neyvia private agent desktop can be read")
    desktop = u.OpenDesktopW(name, 0, False, 0x0001 | 0x0040)  # READOBJECTS | ENUMERATE
    if not desktop:
        raise C.WinError(C.get_last_error())
    try:
        private = [h for h in windows(desktop) if owner(h) == pid]
        rows = []
        for top in private:
            children = []

            @ENUM
            def child(hwnd, _):
                children.append(int(hwnd))
                return True
            u.EnumChildWindows(top, child, 0)
            edits = [{"hwnd": h, "class": class_of(h), "text": text_of(h)} for h in children if class_of(h) in {"Edit", "RICHEDIT50W"}]
            rows.append({"hwnd": top, "class": class_of(top), "title": title_of(top), "edits": edits})
    finally:
        u.CloseDesktop(desktop)
    current = u.OpenInputDesktop(0, False, 0x0001 | 0x0040)
    try:
        visible_on_input = [h for h in windows(current) if owner(h) == pid and u.IsWindowVisible(h)] if current else None
    finally:
        if current:
            u.CloseDesktop(current)
    return {"desktop": desktop_name, "pid": pid, "privateWindows": rows,
            "windowsOnInputDesktop": visible_on_input,
            "method": "separate process; OpenDesktopW + EnumDesktopWindows + WM_GETTEXT (SMTO_ABORTIFHUNG); no UI Automation, no driver"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", required=True)
    parser.add_argument("--pid", required=True, type=int)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(readback(args.desktop, args.pid), ensure_ascii=True))
