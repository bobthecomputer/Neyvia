"""Fail-closed input-desktop fallback, contained before any window visibility.

The injected CBT hook acts only on this desktop's named job. Top-level windows
remain hidden, off-screen and non-activating; this is intentionally stricter
than parking a visible window. Brokered/Store processes are never admitted.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import struct
import threading


def parked_hook_path(profile_root):
    """Task-local immutable build selection avoids overwriting injected DLLs."""
    import hashlib,json
    area=Path(profile_root).resolve()/'c11-parked'
    manifest=area/'parked-hook-build.json'
    if not manifest.is_file():return area/'parked-hook.dll'
    build=json.loads(manifest.read_text(encoding='utf-8-sig'))
    path=(area/build['file']).resolve()
    source=Path(__file__).resolve().parents[2]/'tools/cua-driver-win/parked-hook.cpp'
    if (not path.is_relative_to(area) or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest()!=build['sha256']
            or hashlib.sha256(source.read_bytes()).hexdigest()!=build['sourceSha256']):
        raise DesktopIsolationError('Containment hook build is stale or modified; rebuild it')
    return path

from .cua_desktop import DesktopIsolationError


class _GUID(C.Structure):
    _fields_ = [("data1", W.DWORD), ("data2", W.WORD), ("data3", W.WORD), ("data4", W.BYTE * 8)]

    @classmethod
    def parse(cls, value):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def require_x64(executable):
    """A 64-bit global hook cannot guarantee in-process guarding of x86 apps."""
    with Path(executable).open("rb") as source:
        if source.read(2) != b"MZ":
            raise DesktopIsolationError("Parked launch requires an x64 PE executable")
        source.seek(0x3C)
        offset = struct.unpack("<I", source.read(4))[0]
        source.seek(offset)
        header = source.read(6)
    if header != b"PE\0\0\x64\x86":
        raise DesktopIsolationError("Parked launch requires native x64 hook coverage; x86/AnyCPU needs permission")


class ParkedContainment:
    def __init__(self, desktop, guard, dll_path, *, shell_desktop=False):
        if guard is None:
            raise DesktopIsolationError("Parked launch requires live disturbance attribution")
        baseline = guard.snapshot()
        if not all(baseline.get(key) for key in ("ok", "input_hooks_installed", "input_desktop_bound")):
            raise DesktopIsolationError("Input desktop attribution is not ready; parked launch refused")
        self.desktop, self.guard = desktop, guard
        self.shell_desktop = shell_desktop
        self.path = Path(dll_path).resolve()
        if not self.path.is_relative_to(desktop.profile_root) or not self.path.is_file():
            raise DesktopIsolationError("Parked hook must be a compiled task-local DLL")
        self.ready, self.stop = threading.Event(), threading.Event()
        self.error, self.dll, self.thread_id = None, None, None
        self.receipts = {}
        self._bound = {}
        self._lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, name="c11-previsibility-hook", daemon=True)
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            self.close()
            raise DesktopIsolationError("Previsibility hook unavailable: " + str(self.error or "readiness timeout"))

    def _run(self):
        user, kernel = self.desktop.u, self.desktop.k
        mutex, input_desktop = None, None
        try:
            kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
            kernel.CreateMutexW.restype = W.HANDLE
            kernel.ReleaseMutex.argtypes = [W.HANDLE]
            mutex = kernel.CreateMutexW(None, False, "Local\\Neyvia.C11.ParkedHook")
            if not mutex or kernel.WaitForSingleObject(mutex, 0) != 0:
                raise DesktopIsolationError("A different parked containment session is active")
            input_desktop = (user.OpenDesktopW('Default',0,False,0xFF) if self.shell_desktop
                             else user.OpenInputDesktop(0, False, 0xFF))
            previous = user.GetThreadDesktop(kernel.GetCurrentThreadId())
            if not input_desktop or not user.SetThreadDesktop(input_desktop):
                raise C.WinError(C.get_last_error())
            self.thread_id = int(kernel.GetCurrentThreadId())
            self.handle = input_desktop
            self.dll = C.CDLL(str(self.path), use_last_error=True)
            self.dll.InstallParked.argtypes, self.dll.InstallParked.restype = [W.LPCWSTR], W.BOOL
            self.dll.UninstallParked.argtypes, self.dll.UninstallParked.restype = [], W.BOOL
            self.dll.ParkedCounter.argtypes, self.dll.ParkedCounter.restype = [C.c_int], W.LONG
            message = W.MSG()
            user.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
            user.PeekMessageW.restype = W.BOOL
            user.DispatchMessageW.argtypes, user.DispatchMessageW.restype = [C.POINTER(W.MSG)], C.c_ssize_t
            # Create the queue before signalling readiness; close can post immediately.
            user.PeekMessageW(C.byref(message), None, 0, 0, 0)
            if not self.dll.InstallParked(self.desktop.job_name):
                raise C.WinError(C.get_last_error())
            self.input_name = self.desktop._object_name(input_desktop)
            self.name = self.desktop.name.rsplit("\\", 1)[0] + "\\" + self.input_name
            self.ready.set()
            while not self.stop.is_set():
                while user.PeekMessageW(C.byref(message), None, 0, 0, 1):
                    user.TranslateMessage(C.byref(message))
                    user.DispatchMessageW(C.byref(message))
                self.stop.wait(.005)
        except BaseException as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            if self.dll:
                self.dll.UninstallParked()
            if input_desktop:
                user.SetThreadDesktop(previous)
                user.CloseDesktop(input_desktop)
            if mutex:
                kernel.ReleaseMutex(mutex)
                kernel.CloseHandle(mutex)

    def before_resume(self, process):
        if self.error or not self.ready.is_set() or self.stop.is_set():
            raise DesktopIsolationError("Previsibility containment is not live")
        self.guard.register_pid(process.pid)
        state = self.guard.snapshot()
        if not all(state.get(key) for key in ("ok", "input_hooks_installed", "input_desktop_bound")):
            raise DesktopIsolationError("Input attribution failed before resume; process remains suspended")

    def bind_thread(self):
        """A fresh UIA lane may bind here without switching Paul's desktop."""
        with self._lock:
            if self.stop.is_set() or self.error:
                raise DesktopIsolationError("Parked containment is closed")
            user, kernel = self.desktop.u, self.desktop.k
            thread = kernel.GetCurrentThreadId()
            previous = user.GetThreadDesktop(thread)
            if self.desktop._object_name(previous) == self.input_name:
                return self.name
            if not user.SetThreadDesktop(self.handle):
                raise DesktopIsolationError("Parked lane must bind before COM/windows")
            self._bound[thread] = previous
            return self.name

    def restore_thread(self):
        with self._lock:
            previous = self._bound.pop(self.desktop.k.GetCurrentThreadId(), None)
            if previous and not self.desktop.u.SetThreadDesktop(previous):
                raise C.WinError(C.get_last_error())

    def owns_pid(self, pid):
        return self.desktop.owns_pid(pid)

    def owns(self, hwnd):
        root = self.desktop.u.GetAncestor(int(hwnd), 2)
        return bool(root and int(root) in self.receipts and self.desktop.owns(root))

    def windows(self):
        user = self.desktop.u
        result = []
        visit_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        @visit_type
        def visit(hwnd, unused):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if self.desktop.owns_pid(pid.value):
                user.GetPropW.argtypes, user.GetPropW.restype = [W.HWND, W.LPCWSTR], W.HANDLE
                if not user.GetPropW(hwnd, "Neyvia.C11.Parked.OriginalProc") and not user.IsWindowVisible(hwnd):
                    # OS-owned helper/IME/message windows are never action
                    # targets. Any visible escape is still rejected below and
                    # independently caught by the continuously running guard.
                    return True
                title, cls = C.create_unicode_buffer(512), C.create_unicode_buffer(256)
                user.GetWindowTextW(hwnd, title, len(title))
                user.GetClassNameW(hwnd, cls, len(cls))
                result.append({"hwnd": int(hwnd), "windowId": str(int(hwnd)), "pid": int(pid.value),
                               "title": title.value, "className": cls.value, "visible": bool(user.IsWindowVisible(hwnd)),
                               "desktop": self.input_name, "isolation": "parked-hidden"})
            return True
        user.EnumDesktopWindows.argtypes, user.EnumDesktopWindows.restype = [W.HANDLE, visit_type, W.LPARAM], W.BOOL
        user.EnumDesktopWindows(self.handle, visit, 0)
        for row in result:
            if row["hwnd"] not in self.receipts:
                self.verify_window(row["hwnd"])
        return result

    def verify_window(self, hwnd):
        user = self.desktop.u
        pid = W.DWORD(); user.GetWindowThreadProcessId(int(hwnd), C.byref(pid))
        if not self.desktop.owns_pid(pid.value):
            raise DesktopIsolationError("Parked window is outside the owned job")
        user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [W.HWND, C.c_int], C.c_ssize_t
        user.GetPropW.argtypes, user.GetPropW.restype = [W.HWND, W.LPCWSTR], W.HANDLE
        user.GetWindowRect.argtypes, user.GetWindowRect.restype = [W.HWND, C.POINTER(W.RECT)], W.BOOL
        extended = int(user.GetWindowLongPtrW(int(hwnd), -20))
        rectangle = W.RECT(); user.GetWindowRect(int(hwnd), C.byref(rectangle))
        if (user.IsWindowVisible(int(hwnd)) or not user.GetPropW(int(hwnd), "Neyvia.C11.Parked.OriginalProc")
                or extended & 0x08000080 != 0x08000080 or extended & 0x00040000
                or rectangle.left != -32000 or rectangle.top != -32000):
            raise DesktopIsolationError("Window failed previsibility containment verification: "
                + str({"hwnd": int(hwnd), "visible": bool(user.IsWindowVisible(int(hwnd))),
                    "subclass": bool(user.GetPropW(int(hwnd), "Neyvia.C11.Parked.OriginalProc")),
                    "extendedStyle": extended, "bounds": [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]}))
        receipt = {"hwnd": int(hwnd), "pid": int(pid.value), "hidden": True, "previsibility": True,
                   "offscreen": True, "noactivate": True, "toolwindow": True,
                   "delete_tab_ok": self._delete_tab(hwnd), "route": "parked-hidden"}
        if not receipt["delete_tab_ok"]:
            raise DesktopIsolationError("Taskbar removal was not acknowledged")
        self.guard.register_parked_window(hwnd, pid.value, receipt)
        self.receipts[int(hwnd)] = receipt
        return receipt

    @staticmethod
    def _delete_tab(hwnd):
        ole = C.OleDLL("ole32")
        initialized = ole.CoInitializeEx(None, 0) >= 0
        pointer = C.c_void_p()
        try:
            clsid = _GUID.parse("56fdf344-fd6d-11d0-958a-006097c9a090")
            iid = _GUID.parse("56fdf342-fd6d-11d0-958a-006097c9a090")
            ole.CoCreateInstance.argtypes = [C.POINTER(_GUID), C.c_void_p, W.DWORD, C.POINTER(_GUID), C.POINTER(C.c_void_p)]
            ole.CoCreateInstance.restype = C.c_long
            if ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(pointer)) < 0:
                return False
            table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
            initialize = C.WINFUNCTYPE(C.c_long, C.c_void_p)(table[3])
            delete = C.WINFUNCTYPE(C.c_long, C.c_void_p, W.HWND)(table[5])
            return initialize(pointer) >= 0 and delete(pointer, int(hwnd)) >= 0
        finally:
            if pointer.value:
                table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
                C.WINFUNCTYPE(W.ULONG, C.c_void_p)(table[2])(pointer)
            if initialized:
                ole.CoUninitialize()

    def counters(self):
        values=dict(zip(("created", "activationVetoes", "positionEnforcements", "creationRefusals"),
                        (int(self.dll.ParkedCounter(index)) for index in range(4))))
        if hasattr(self.dll,'ParkedLastFailure'):
            text=C.create_unicode_buffer(256)
            self.dll.ParkedLastFailure.argtypes=[W.LPWSTR,C.c_int]
            self.dll.ParkedLastFailure.restype=W.BOOL
            if self.dll.ParkedLastFailure(text,len(text)):values['lastFailureClass']=text.value
        return values

    def close(self):
        # The owner must terminate its contained processes before removing hooks.
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(3)
        if self.thread.is_alive():
            raise DesktopIsolationError("Previsibility hook thread did not close")
