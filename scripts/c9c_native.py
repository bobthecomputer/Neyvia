"""Launch the owned Neyvia browser on a verified separate Windows desktop.

Python's subprocess.STARTUPINFO does not marshal lpDesktop. Use the actual Win32
structure and verify the initial thread's desktop before admitting any browser work.
"""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import time
import uuid


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR),
               ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
               ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD),
               ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD),
               ("wShowWindow", w.WORD), ("cbReserved2", w.WORD), ("lpReserved2", ctypes.c_void_p),
               ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class PROCESSINFO(ctypes.Structure):
    _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


class NativeProcess:
    def __init__(self, executable, cwd, env):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
        self.user.CreateDesktopW.restype = w.HANDLE
        self.user.CloseDesktop.argtypes = [w.HANDLE]
        self.user.GetThreadDesktop.argtypes = [w.DWORD]
        self.user.GetThreadDesktop.restype = w.HANDLE
        self.user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        self.name = "NeyviaC9c-" + uuid.uuid4().hex
        self.desktop = self.user.CreateDesktopW(self.name, None, None, 0, 0x01ff, None)
        if not self.desktop: raise ctypes.WinError(ctypes.get_last_error())
        self.kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESSINFO)]
        self.kernel.CreateProcessW.restype = w.BOOL
        self.kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self.kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        si = STARTUPINFO(cb=ctypes.sizeof(STARTUPINFO), lpDesktop="winsta0\\" + self.name, dwFlags=1, wShowWindow=0)
        self.info = PROCESSINFO()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(Path(executable).resolve())]))
        environment = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda p:p[0].upper())) + "\0\0")
        ok = self.kernel.CreateProcessW(None, command, None, None, False, 0x08000000 | 0x400,
            environment, str(Path(cwd).resolve()), ctypes.byref(si), ctypes.byref(self.info))
        if not ok:
            self.user.CloseDesktop(self.desktop)
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = self.info.dwProcessId
        self.returncode = None
        # GetThreadDesktop/GetUserObjectInformation cannot reliably inspect a
        # foreign process's thread. Observe its actual HWND on the named desktop.
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.user.EnumDesktopWindows.argtypes = [w.HANDLE, callback_type, w.LPARAM]
        owned = []
        @callback_type
        def inspect(hwnd, _):
            pid = w.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid: owned.append(int(hwnd))
            return True
        deadline = time.monotonic() + 15
        while not owned and self.poll() is None and time.monotonic() < deadline:
            self.user.EnumDesktopWindows(self.desktop, inspect, 0)
            time.sleep(.05)
        if not owned:
            self.terminate(); self.wait(5); self.close()
            raise RuntimeError("Owned native HWND was not observed on the explicitly isolated desktop")
        self.verified_name = self.name
        self.verified_windows = owned

    def poll(self):
        code = w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = None if code.value == 259 else code.value
        return self.returncode

    def terminate(self):
        if self.poll() is None: self.kernel.TerminateProcess(self.info.hProcess, 1)
    kill = terminate

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline: raise subprocess.TimeoutExpired("owned native", timeout)
            time.sleep(.05)
        return self.returncode

    def close(self):
        self.kernel.CloseHandle(self.info.hThread); self.kernel.CloseHandle(self.info.hProcess)
        return bool(self.user.CloseDesktop(self.desktop))
