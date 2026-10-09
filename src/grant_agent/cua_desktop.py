"""Private desktop and previsibility-contained fallback; never switches input.

The only GUI launch path uses CreateProcessW.lpDesktop and a kill-on-close job.
Private launch refuses brokers that may ignore lpDesktop. The explicit Bureau
route admits installed binaries only under new-job and hidden-HWND checks.
"""
from __future__ import annotations

import ctypes as C
import hashlib
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import threading
import uuid


class DesktopIsolationError(RuntimeError):
    pass


class _STARTUPINFO(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
                ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
                ("dwXSize", W.DWORD), ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
                ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", C.POINTER(W.BYTE)), ("hStdInput", W.HANDLE),
                ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class _PROCESSINFO(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class _BASICLIMIT(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_longlong), ("PerJobUserTimeLimit", C.c_longlong),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", C.c_size_t),
                ("MaximumWorkingSetSize", C.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", C.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _IOLIMIT(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _EXTLIMIT(C.Structure):
    _fields_ = [("BasicLimitInformation", _BASICLIMIT), ("IoInfo", _IOLIMIT),
                ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]


class DesktopProcess:
    def __init__(self, kernel, handle, pid):
        self._kernel, self._handle, self.pid = kernel, handle, pid
        self.returncode = None

    def poll(self):
        if self.returncode is None:
            if self._kernel.WaitForSingleObject(self._handle, 0) == 0:
                code = W.DWORD()
                if not self._kernel.GetExitCodeProcess(self._handle, C.byref(code)):
                    raise C.WinError(C.get_last_error())
                self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout=None):
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = self._kernel.WaitForSingleObject(self._handle, milliseconds)
        if result == 0x102:
            raise subprocess.TimeoutExpired(str(self.pid), timeout)
        if result != 0:
            raise C.WinError(C.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is None and not self._kernel.TerminateProcess(self._handle, 1):
            raise C.WinError(C.get_last_error())

    kill = terminate

    def close_handle(self):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


class AgentDesktop:
    """Own private processes and an explicitly guarded hidden fallback."""
    DIRECT_FAMILIES = frozenset({
        "charmap.exe", "mmc.exe", "perfmon.exe", "msinfo32.exe", "git-gui.exe",
        "colorcpl.exe", "odbcad32.exe", "dxdiag.exe", "winword.exe", "excel.exe",
        "chrome.exe", "msedge.exe", "firefox.exe", "code.exe",
        "powershell_ise.exe", "mstsc.exe",
        "xournalpp.exe",
        "cursor.exe", "antigravity.exe",
    })
    def __init__(self, name=None, *, profile_root=None):
        if os.name != "nt":
            raise DesktopIsolationError("Agent desktop requires Windows")
        self.u = C.WinDLL("user32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self._configure()
        station = self._object_name(self.u.GetProcessWindowStation())
        self.desktop_name = name or "Neyvia-C11-" + uuid.uuid4().hex
        if not self.desktop_name.startswith("Neyvia-C11-") or any(c in self.desktop_name for c in "\\/:\0"):
            raise DesktopIsolationError("Desktop name must be a fresh Neyvia-C11 name")
        self.name = station + "\\" + self.desktop_name
        self.profile_root = Path(profile_root or Path(__file__).resolve().parents[2] / ".agent_control").resolve()
        self.processes = []
        self._pinned_console_commands = {}
        self.fixtures = {}
        self.parked = None
        self._bound = {}
        self._lock = threading.RLock()
        existing = self.u.OpenDesktopW(self.desktop_name, 0, False, 1)
        if existing:
            self.u.CloseDesktop(existing)
            raise DesktopIsolationError("A private desktop must be freshly created, never reused")
        self.handle = self.u.CreateDesktopW(self.desktop_name, None, None, 0, 0xFF, None)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        self.job = None
        try:
            self._assert_private()
            self.job_name = "Local\\" + self.desktop_name + "-Job"
            self.job = self.k.CreateJobObjectW(None, self.job_name)
            if not self.job:
                raise C.WinError(C.get_last_error())
            limits = _EXTLIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not self.k.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)):
                raise C.WinError(C.get_last_error())
        except BaseException:
            self.close()
            raise

    def _configure(self):
        signatures = {
            "CreateDesktopW": ([W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, W.DWORD, C.c_void_p], W.HANDLE),
            "CloseDesktop": ([W.HANDLE], W.BOOL), "OpenInputDesktop": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "OpenDesktopW": ([W.LPCWSTR, W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "GetProcessWindowStation": ([], W.HANDLE), "GetThreadDesktop": ([W.DWORD], W.HANDLE),
            "SetThreadDesktop": ([W.HANDLE], W.BOOL),
            "GetUserObjectInformationW": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
            "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            "GetAncestor": ([W.HWND, W.UINT], W.HWND),
            "GetWindowTextW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            "GetClassNameW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            "IsWindowVisible": ([W.HWND], W.BOOL), "PostMessageW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name); fn.argtypes = args; fn.restype = result
        for name, args, result in (
            ("GetCurrentThreadId", [], W.DWORD), ("CreateJobObjectW", [C.c_void_p, W.LPCWSTR], W.HANDLE),
            ("CloseHandle", [W.HANDLE], W.BOOL),
            ("SetInformationJobObject", [W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
            ("AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL),
            ("OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            ("IsProcessInJob", [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)], W.BOOL),
            ("TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL),
            ("TerminateProcess", [W.HANDLE, W.UINT], W.BOOL),
            ("ResumeThread", [W.HANDLE], W.DWORD),
            ("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            ("GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            ("CreateProcessW", [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                                C.c_void_p, W.LPCWSTR, C.POINTER(_STARTUPINFO), C.POINTER(_PROCESSINFO)], W.BOOL),
        ):
            fn = getattr(self.k, name); fn.argtypes = args; fn.restype = result

    def _object_name(self, handle):
        buffer = C.create_unicode_buffer(256); needed = W.DWORD()
        if not handle or not self.u.GetUserObjectInformationW(handle, 2, buffer, C.sizeof(buffer), C.byref(needed)):
            raise C.WinError(C.get_last_error())
        return buffer.value

    def _assert_private(self):
        if not self.handle:
            raise DesktopIsolationError("Agent desktop is closed")
        current = self.u.OpenInputDesktop(0, False, 1)
        if not current:
            raise DesktopIsolationError("Cannot verify input desktop")
        try:
            if self._object_name(current).casefold() == self.desktop_name.casefold():
                raise DesktopIsolationError("Agent desktop must never be the input desktop")
        finally:
            self.u.CloseDesktop(current)

    def bind_thread(self):
        """Call on a fresh thread before creating COM/UIA objects or windows."""
        with self._lock:
            self._assert_private()
            thread = self.k.GetCurrentThreadId()
            previous = self.u.GetThreadDesktop(thread)
            if self._object_name(previous) == self.desktop_name:
                return self.name
            if not self.u.SetThreadDesktop(self.handle):
                raise DesktopIsolationError("Cannot bind CUA thread before COM: " + str(C.WinError(C.get_last_error())))
            self._bound[thread] = previous
            return self.name

    def restore_thread(self):
        with self._lock:
            thread = self.k.GetCurrentThreadId()
            previous = self._bound.get(thread)
            if previous and not self.u.SetThreadDesktop(previous):
                raise C.WinError(C.get_last_error())
            self._bound.pop(thread, None)

    def owns(self, hwnd):
        if not self.handle:
            return False
        root = self.u.GetAncestor(int(hwnd), 2)
        if not root:
            return False
        if self.parked and int(root) in self.parked.receipts:
            pid = W.DWORD()
            self.u.GetWindowThreadProcessId(root, C.byref(pid))
            return self.owns_pid(pid.value) and int(pid.value) == self.parked.receipts[int(root)]["pid"]
        try:
            # GetThreadDesktop of a foreign process can return a handle that is
            # not valid in this process. Enumeration uses our real HDESK and
            # confirms the same boundary without relying on foreign handles.
            self._assert_private()
            found = []
            callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            @callback_type
            def visit(candidate, unused):
                if int(candidate) == int(root):
                    pid = W.DWORD()
                    self.u.GetWindowThreadProcessId(candidate, C.byref(pid))
                    found.append(int(pid.value))
                    return False
                return True
            self.u.EnumDesktopWindows.argtypes = [W.HANDLE, callback_type, W.LPARAM]
            self.u.EnumDesktopWindows.restype = W.BOOL
            self.u.EnumDesktopWindows(self.handle, visit, 0)
            return len(found) == 1 and self.owns_pid(found[0])
        except (OSError, DesktopIsolationError):
            return False

    def owns_pid(self, pid):
        if not self.job:
            return False
        process = self.k.OpenProcess(0x1000, False, int(pid))
        if not process:
            return False
        try:
            contained = W.BOOL()
            return bool(self.k.IsProcessInJob(process, self.job, C.byref(contained)) and contained.value)
        finally:
            self.k.CloseHandle(process)

    def register_fixture(self, hwnd, path, token):
        """Bind a disposable target to an already independently owned HWND.

        A caller cannot use this to adopt a broker or a user's window. Ownership
        must already follow the suspended-launch job and desktop boundary.
        """
        import re
        target = Path(path).resolve()
        if (not re.fullmatch(r"[a-f0-9]{32}", token) or token not in str(target)
                or not target.is_relative_to(self.profile_root) or not target.exists()
                or not self.owns(int(hwnd))):
            raise DesktopIsolationError("Disposable target lacks path, token or independent window ownership")
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(int(hwnd), C.byref(pid))
        title = C.create_unicode_buffer(1024)
        self.u.GetWindowTextW(int(hwnd), title, len(title))
        if token not in title.value:
            # Only a new job-owned HWND is relabelled; existing windows can
            # never reach here. Utilities have no document title of their own.
            self.u.SetWindowTextW.argtypes = [W.HWND, W.LPCWSTR]
            self.u.SetWindowTextW.restype = W.BOOL
            if not self.u.SetWindowTextW(int(hwnd), title.value + " [" + token + "]"):
                raise DesktopIsolationError("Owned fixture title could not be labelled")
            self.u.GetWindowTextW(int(hwnd), title, len(title))
        if token not in title.value:
            raise DesktopIsolationError("Disposable target token was not observed in the new window title")
        stat = target.stat()
        receipt = {"hwnd": int(hwnd), "pid": int(pid.value), "path": str(target),
                   "token": token, "title": title.value,
                   "fileIdentity": [stat.st_dev, stat.st_ino, stat.st_ctime_ns]}
        self.fixtures[int(hwnd)] = receipt
        return receipt

    def disposable_target(self, hwnd):
        receipt = self.fixtures.get(int(hwnd))
        if not receipt or not self.owns(int(hwnd)):
            return None
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(int(hwnd), C.byref(pid))
        try:
            stat = Path(receipt["path"]).stat()
        except OSError:
            return None
        if (int(pid.value) != receipt["pid"] or
                [stat.st_dev, stat.st_ino, stat.st_ctime_ns] != receipt["fileIdentity"]):
            return None
        return receipt

    def windows(self):
        self._assert_private()
        result = []
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        @callback_type
        def visit(hwnd, unused):
            pid = W.DWORD(); thread = self.u.GetWindowThreadProcessId(hwnd, C.byref(pid))
            title = C.create_unicode_buffer(512); cls = C.create_unicode_buffer(256)
            self.u.GetWindowTextW(hwnd, title, len(title)); self.u.GetClassNameW(hwnd, cls, len(cls))
            result.append({"windowId": str(int(hwnd)), "hwnd": int(hwnd), "pid": int(pid.value),
                           "threadId": int(thread), "title": title.value, "className": cls.value,
                           "visible": bool(self.u.IsWindowVisible(hwnd)), "desktop": self.name})
            return True
        self.u.EnumDesktopWindows.argtypes = [W.HANDLE, callback_type, W.LPARAM]
        self.u.EnumDesktopWindows.restype = W.BOOL
        C.set_last_error(0)
        if not self.u.EnumDesktopWindows(self.handle, visit, 0) and C.get_last_error():
            raise C.WinError(C.get_last_error())
        if self.parked:
            result.extend(self.parked.windows())
        return result

    def admit_pinned_console(self, argv, expected_sha256):
        """Host-only admission of a reviewed console command; never exposed to models."""
        executable = Path(argv[0]).resolve()
        if not executable.is_relative_to(self.profile_root) or not executable.is_file():
            raise DesktopIsolationError("Pinned console executable must be task-local")
        with executable.open('rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != expected_sha256:
            raise DesktopIsolationError("Pinned console executable hash changed")
        self._pinned_console_commands[tuple(str(a) for a in argv)] = expected_sha256

    def _validate_launch(self, argv, *, bureau=False):
        if not argv:
            raise DesktopIsolationError("Executable is required")
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_file():
            raise DesktopIsolationError("Launch requires an installed absolute executable")
        base = executable.name.casefold()
        pin = self._pinned_console_commands.get(tuple(str(a) for a in argv))
        if pin and not bureau:
            with executable.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != pin:
                    raise DesktopIsolationError("Pinned console executable hash changed")
            return str(executable)
        if bureau and base in {"mspaint.exe", "calculatorapp.exe", "notepad.exe", "photos.exe", "snippingtool.exe", "windowsterminal.exe", "explorer.exe"}:
            # Actual installed x64 binaries, never app-execution aliases. A
            # suspended new process is inside our job before the CBT hook runs.
            if executable.stat().st_size == 0:
                raise DesktopIsolationError("Bureau requires the installed executable, not a broker alias")
            if base == "explorer.exe":
                targets = [str(a)[3:] for a in argv[1:] if str(a).startswith('/n,')]
                if len(targets) != 1 or '/separate' not in [str(a).casefold() for a in argv[1:]]:
                    raise DesktopIsolationError("Explorer requires /n,<disposable folder> and a separate process")
                import re
                folder = Path(targets[0]).resolve()
                if not folder.is_dir() or not folder.is_relative_to(self.profile_root) or not re.search(r'[a-f0-9]{32}', folder.name):
                    raise DesktopIsolationError("Explorer requires a token-named task-local folder")
            if base == "notepad.exe":
                # /newWindow behavior varies between inbox versions. Preserve
                # any existing Notepad window by declining this instance route.
                import psutil
                if any(p.info['name'] and p.info['name'].casefold() == 'notepad.exe'
                       for p in psutil.process_iter(['name'])):
                    raise DesktopIsolationError("Existing Notepad instance: explicit new-window route has not been proven")
            return str(executable)
        if "windowsapps" in str(executable).casefold() or base in {
            "explorer.exe", "control.exe", "taskmgr.exe", "calc.exe", "notepad.exe",
            "applicationframehost.exe", "runtimebroker.exe", "mspaint.exe", "dfrgui.exe", "powerpnt.exe",
        }:
            raise DesktopIsolationError("Brokered or singleton app cannot be proven private; launch refused")
        probe = (base.endswith("probe.exe") and executable.resolve().is_relative_to(self.profile_root))
        if base not in self.DIRECT_FAMILIES and not probe:
            raise DesktopIsolationError("Unknown executable family has no verified private launch route")
        flags = [str(a).casefold() for a in argv[1:]]
        if base in {"winword.exe", "excel.exe"} and "/x" not in flags:
            raise DesktopIsolationError("Office requires /x for an independent instance")
        if base in {"chrome.exe", "msedge.exe", "code.exe", "firefox.exe", "cursor.exe", "antigravity.exe"}:
            profile = None
            for index, value in enumerate(argv[1:], 1):
                if str(value).startswith("--user-data-dir="):
                    profile = str(value).split("=", 1)[1]
                elif str(value) in {"--user-data-dir", "-profile"} and index + 1 < len(argv):
                    profile = argv[index + 1]
            if not profile or not Path(profile).resolve().is_relative_to(self.profile_root):
                raise DesktopIsolationError("Browser/Electron requires a disposable task-local profile")
            if not Path(profile).is_dir():
                raise DesktopIsolationError("Disposable profile directory must be created before launch")
            if base == "firefox.exe" and "-no-remote" not in flags:
                raise DesktopIsolationError("Firefox requires -no-remote")
        return str(executable)

    def launch_policy(self, argv):
        """Expose the fallback ladder as gates; no tier can silently show an app."""
        ladder = [
            {"tier": 0, "route": "agent-desktop", "status": "eligible", "requires": "private HWND and own job proof"},
            {"tier": 1, "route": "agent-bureau", "status": "native_preflight_required", "allowed": False,
             "requires": "maintained task-local library, previsibility ownership, verified noncurrent desktop membership"},
            {"tier": 2, "route": "needs-permission", "allowed": False,
             "requires": "Both containment layers failed; no visible launch in this session"},
        ]
        try:
            executable = self._validate_launch([str(a) for a in argv])
            return {"allowed": True, "status": "eligible", "route": "agent-desktop",
                    "executable": executable, "fallbackLadder": ladder}
        except DesktopIsolationError as exc:
            ladder[0].update(status="refused", allowed=False, reason=str(exc))
            return {"allowed": False, "status": "needs-permission", "permissionRequired": True,
                    "appKey": Path(str(argv[0])).name.casefold() if argv else "unknown", "route": None,
                    "reason": str(exc), "fallbackLadder": ladder}

    def launch_parked(self, argv, cwd=None, *, env=None, guard, dll_path):
        """Explicit fallback; broker routes fail before CreateProcess is called."""
        from .cua_parked import ParkedContainment, require_x64
        with self._lock:
            argv = [str(value) for value in argv]
            executable = self._validate_launch(argv)
            require_x64(executable)
            if self.parked is None:
                self.parked = ParkedContainment(self, guard, dll_path)
            elif self.parked.guard is not guard:
                raise DesktopIsolationError("Parked route cannot change its attribution owner")
            return self._launch(argv, cwd, env=env, parked=True)

    def launch_bureau(self, argv, cwd=None, *, env=None, guard, dll_path, vda_path=None):
        """Start hidden before resume, then admit only verified Bureau HWNDs."""
        from .cua_bureau import BureauDesktop
        from .cua_parked import require_x64
        with self._lock:
            argv = [str(value) for value in argv]
            executable = self._validate_launch(argv, bureau=True)
            require_x64(executable)
            if self.parked is None:
                self.parked = BureauDesktop(self, guard, dll_path, vda_path=vda_path)
            elif not isinstance(self.parked, BureauDesktop) or self.parked.guard is not guard:
                raise DesktopIsolationError("Bureau route cannot replace another containment owner")
            return self._launch(argv, cwd, env=env, parked=True)

    def launch(self, argv, cwd=None, *, env=None):
        return self._launch(argv, cwd, env=env, parked=False)

    def _launch(self, argv, cwd=None, *, env=None, parked=False):
        with self._lock:
            self._assert_private()
            argv = [str(a) for a in argv]
            executable = self._validate_launch(argv, bureau=parked and hasattr(self.parked, 'library'))
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            startup = _STARTUPINFO(); startup.cb = C.sizeof(startup)
            startup.lpDesktop = self.parked.input_name if parked else self.name
            startup.dwFlags = 1; startup.wShowWindow = 0 if parked else 4
            process = _PROCESSINFO()
            environment = None
            if env is not None:
                values = {**os.environ, **env}
                environment = C.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(values.items())) + "\0\0")
            # Suspended until assigned to our job: descendants cannot escape containment.
            flags = 0x08000000 | 0x00000004 | 0x00000400
            if not self.k.CreateProcessW(executable, command, None, None, False, flags,
                                         environment, str(cwd) if cwd else None, C.byref(startup), C.byref(process)):
                raise C.WinError(C.get_last_error())
            owned = DesktopProcess(self.k, process.hProcess, int(process.dwProcessId))
            owned.argv = tuple(argv)
            try:
                if not self.k.AssignProcessToJobObject(self.job, process.hProcess):
                    raise DesktopIsolationError("Private launch cannot be contained in its job: " + str(C.WinError(C.get_last_error())))
                if parked:
                    self.parked.before_resume(owned)
                if self.k.ResumeThread(process.hThread) == 0xFFFFFFFF:
                    raise C.WinError(C.get_last_error())
                self.processes.append(owned)
                return owned
            except BaseException:
                owned.terminate(); owned.wait(3); owned.close_handle()
                raise
            finally:
                self.k.CloseHandle(process.hThread)

    def close(self):
        """Close only owned job processes; leave live-thread desktop handles safe."""
        with self._lock:
            if self.handle and not self.parked:
                # Bureau enumeration performs admission. Cleanup must never
                # acquire a new lease, register a view, or retry a failed move.
                # The job below owns and terminates all fallback processes.
                try:
                    for window in self.windows():
                        if self.owns_pid(window["pid"]):
                            self.u.PostMessageW(window["hwnd"], 0x10, 0, 0)
                except (OSError, DesktopIsolationError):
                    pass
            if self.job:
                self.k.TerminateJobObject(self.job, 0)
                self.k.CloseHandle(self.job); self.job = None
            for process in self.processes:
                try:
                    process.wait(3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                process.close_handle()
            self.processes.clear()
            if self.parked:
                self.parked.close()
                self.parked = None
            closed = True
            if self.handle:
                closed = bool(self.u.CloseDesktop(self.handle))
                if closed:
                    self.handle = None
            return {"desktop": self.name, "handleClosed": closed, "boundThreadCount": len(self._bound)}

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
