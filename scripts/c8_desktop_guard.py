"""Read-only desktop sampling for the owned C8 process tree. Never sends input."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime

LOG = Path('C:/Users/user/Projects/plans/logs/window-guard.jsonl')


class DesktopGuard:
    def __init__(self):
        self.offset = LOG.stat().st_size if LOG.exists() else 0
        self.owned = {os.getpid()}
        self.identities = {}
        self.started_at = time.time()
        self.samples = 0
        self.violations = []
        self.cursor_changes = self.foreground_changes = 0
        self.reused_parent_rejections = 0
        self.previous = None
        self.error = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, name='c8-desktop-observer', daemon=True)
        self.attached = {}

    def attach(self, pid):
        """Include a separately started task-owned service, bound to its birth."""
        import psutil
        process = psutil.Process(pid)
        self.attached[pid] = process.create_time()

    def sample(self):
        class Process(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                        ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                        ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                        ('exe', wintypes.WCHAR * 260)]
        kernel, user = ctypes.windll.kernel32, ctypes.windll.user32
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Process)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        def created(pid):
            process = kernel.OpenProcess(0x1000, False, pid)
            if not process:
                return None
            try:
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel.GetProcessTimes(process, *[ctypes.byref(t) for t in times]):
                    return None
                return times[0].dwLowDateTime | times[0].dwHighDateTime << 32
            finally:
                kernel.CloseHandle(process)
        handle = kernel.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError('Cannot inspect owned process tree')
        parents, executables = {}, {}
        try:
            row = Process(); row.size = ctypes.sizeof(row)
            valid = kernel.Process32FirstW(handle, ctypes.byref(row))
            while valid:
                parents[row.pid] = row.parent
                executables[row.pid] = row.exe
                valid = kernel.Process32NextW(handle, ctypes.byref(row))
        finally:
            kernel.CloseHandle(handle)
        current = {os.getpid()}
        births = {os.getpid(): created(os.getpid())}
        for pid, expected in list(self.attached.items()):
            birth = created(pid)
            if birth is not None and abs(birth / 10000000 - 11644473600 - expected) < .01:
                current.add(pid)
                births[pid] = birth
        if births[os.getpid()] is None:
            raise OSError('Cannot bind owned root process creation time')
        while True:
            descendants = set()
            for pid, parent in parents.items():
                if parent not in current or pid in current:
                    continue
                birth = created(pid)
                # Parent PIDs in Toolhelp outlive the parent process and may
                # refer to a reused PID. An older child is never ours.
                if birth is not None and birth >= births[parent]:
                    births[pid] = birth
                    descendants.add(pid)
                elif birth is not None:
                    self.reused_parent_rejections += 1
            if descendants <= current:
                break
            current.update(descendants)
        self.owned.update(current)
        now = time.time()
        for pid in current:
            identity = self.identities.setdefault((pid, births[pid]), {
                'pid': pid, 'creationTime': births[pid], 'exe': executables.get(pid, ''),
                'firstObservedAt': now, 'lastObservedAt': now})
            identity['lastObservedAt'] = now
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.GetForegroundWindow.restype = wintypes.HWND
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        visible = []
        def window(hwnd, _):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in current:
                cls = ctypes.create_unicode_buffer(256)
                user.GetClassNameW(hwnd, cls, len(cls))
                if user.IsWindowVisible(hwnd) or cls.value == 'PseudoConsoleWindow':
                    visible.append({'pid': pid.value, 'windowId': str(hwnd), 'class': cls.value,
                                    'visible': bool(user.IsWindowVisible(hwnd))})
            return True
        # EnumWindows enumerates the calling thread's desktop. Explicitly
        # inspect the input desktop even when this producer itself is private.
        user.OpenInputDesktop.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        user.OpenInputDesktop.restype = wintypes.HANDLE
        user.EnumDesktopWindows.argtypes = [wintypes.HANDLE,callback_type,wintypes.LPARAM]
        user.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user.CloseDesktop.argtypes = [wintypes.HANDLE]
        desktop = user.OpenInputDesktop(0,False,0x41)
        if not desktop:
            raise OSError('Cannot inspect the input desktop; containment fails closed')
        try:
            if not user.EnumDesktopWindows(desktop,callback_type(window),0):
                raise OSError('Input-desktop window enumeration failed')
        finally:
            user.CloseDesktop(desktop)
        foreground = user.GetForegroundWindow()
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(foreground, ctypes.byref(owner))
        point = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(point))
        state = (foreground, point.x, point.y)
        if self.previous:
            self.foreground_changes += state[0] != self.previous[0]
            self.cursor_changes += state[1:] != self.previous[1:]
        self.previous = state
        self.samples += 1
        if visible or owner.value in current:
            self.violations.append({'sample': self.samples, 'visibleOwnedWindows': visible,
                                    'ownedForeground': owner.value in current})

    def run(self):
        try:
            while not self.done.wait(.25):
                self.sample()
        except Exception as error:
            self.error = str(error)

    def start(self):
        self.sample()
        self.thread.start()

    def finish(self):
        self.done.set()
        self.thread.join(timeout=5)
        entries = []
        try:
            self.sample()
            if LOG.exists():
                if LOG.stat().st_size < self.offset:
                    raise ValueError('Lead guard log was truncated during the run')
                with LOG.open('rb') as log:
                    log.seek(self.offset)
                    for line in log:
                        entries.append(json.loads(line))
        except (OSError, ValueError) as error:
            self.error = str(error)
        owned_entries, historical_collisions = [], []
        for entry in entries:
            if entry.get('pid') not in self.owned:
                continue
            identities = [i for i in self.identities.values() if i['pid'] == entry['pid']]
            try:
                today = datetime.fromtimestamp(self.started_at)
                clock = datetime.strptime(entry['at'], '%H:%M:%S')
                event_at = today.replace(hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=0).timestamp()
                if event_at < self.started_at - 2:
                    event_at += 86400
                # The lead log has one-second precision; allow a full sampling
                # interval on either side. PID alone is never process identity.
                active = [i for i in identities if i['firstObservedAt'] - 1.5 <= event_at <= i['lastObservedAt'] + 1.5]
                if active:
                    owned_entries.append(entry)  # Fail closed even on an executable mismatch.
                else:
                    historical_collisions.append({'entry': entry, 'observedIdentities': identities,
                                                  'reason': 'Guard event falls outside every observed owned lifetime for this reused PID'})
            except (KeyError, TypeError, ValueError):
                owned_entries.append(entry)
        return {'passed': not self.violations and not owned_entries and not self.error,
                'samples': self.samples, 'ownedPids': sorted(self.owned), 'violations': self.violations,
                'guardLogOffsetBefore': self.offset, 'newGuardEntries': entries, 'ownedGuardEntries': owned_entries,
                'externalForegroundChangesObserved': self.foreground_changes,
                'cursorChangesObserved': self.cursor_changes, 'error': self.error,
                'staleParentPidEdgesRejected': self.reused_parent_rejections,
                'ownedProcessIdentities': list(self.identities.values()),
                'historicalPidCollisions': historical_collisions,
                'boundary': 'Explicit input-desktop owned-window enumeration (including hidden PseudoConsoleWindow), foreground and lead log; private desktop visibility is separate. No input or activation API is called.'}
