"""Cross-process resource guards for bounded contract workers.

Heavy-work leases are process-reentrant so a trace bootstrap and its explicit
start in the same PID consume one slot. Captured workers get a separate lease.
All persistent locks, logs and memory-limit markers live under the P22 D-drive
scratch root; this module never writes into the source tree.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid
from typing import Iterator

_SCRATCH = Path("D:/NeyviaRuns/P22")
_SLOT_DIR = _SCRATCH / "resource-slots"
_SLOT_COUNT = 2
_MEMORY_LIMIT = 3 * 1024**3
_TAIL_BYTES = 64 * 1024
_LEASE_LOCK = threading.RLock()
_SLOT_ACQUIRE_LOCK = threading.Lock()
_RAW_HELD: set[int] = set()
_LEASE_PID = os.getpid()
_LEASE_DEPTH = 0
_LEASE_FD: int | None = None
_LEASE_SLOT: int | None = None
_WINDOWS_ROOT_BIRTHS: dict[int, int] = {}
_WINDOWS_SAMPLE = threading.local()


def memory_limit_exceeded(private_bytes: int, working_set_bytes: int, limit_bytes: int = _MEMORY_LIMIT) -> bool:
    """Pure cutoff predicate, injectable with tiny thresholds in contract cases."""
    if min(private_bytes, working_set_bytes) < 0 or limit_bytes <= 0:
        raise ValueError("Memory measurements must be non-negative and limit must be positive")
    return private_bytes > limit_bytes or working_set_bytes > limit_bytes


def _after_fork_child() -> None:
    """Forget copied local reservations; closing a child FD must not unlock its parent."""
    global _LEASE_LOCK, _SLOT_ACQUIRE_LOCK, _RAW_HELD
    global _LEASE_PID, _LEASE_DEPTH, _LEASE_FD, _LEASE_SLOT
    inherited_fd = _LEASE_FD
    _LEASE_LOCK = threading.RLock()
    _SLOT_ACQUIRE_LOCK = threading.Lock()
    _RAW_HELD = set()
    _LEASE_PID, _LEASE_DEPTH, _LEASE_FD, _LEASE_SLOT = os.getpid(), 0, None, None
    if inherited_fd is not None:
        try:
            os.close(inherited_fd)
        except OSError:
            pass


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


def _reset_after_fork() -> None:
    """Drop a copied lease handle in a forked child without unlocking its parent."""
    global _LEASE_PID, _LEASE_DEPTH, _LEASE_FD, _LEASE_SLOT
    pid = os.getpid()
    if pid != _LEASE_PID:
        if _LEASE_FD is not None:
            try:
                os.close(_LEASE_FD)
            except OSError:
                pass
        _LEASE_PID, _LEASE_DEPTH, _LEASE_FD, _LEASE_SLOT = pid, 0, None, None


def _try_lock(fd: int) -> bool:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                return False
            raise
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _acquire_slot(timeout: float | None) -> tuple[int, int]:
    _SLOT_DIR.mkdir(parents=True, exist_ok=True)
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    while True:
        with _SLOT_ACQUIRE_LOCK:
            for slot in range(_SLOT_COUNT):
                if slot in _RAW_HELD:
                    continue
                path = _SLOT_DIR / f"heavy-{slot}.lock"
                fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                    os.fsync(fd)
                try:
                    if _try_lock(fd):
                        _RAW_HELD.add(slot)
                        return slot, fd
                except BaseException:
                    os.close(fd)
                    raise
                os.close(fd)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("No P22 heavy-work slot became available")
        time.sleep(0.1)


def _release_slot(slot: int, fd: int, owner_pid: int) -> None:
    if os.getpid() != owner_pid:
        # On POSIX flock handles are shared across fork; unlocking in the child
        # would release the parent's live permit. close only this inherited FD.
        try:
            os.close(fd)
        finally:
            _RAW_HELD.discard(slot)
        return
    with _SLOT_ACQUIRE_LOCK:
        try:
            _unlock(fd)
        finally:
            os.close(fd)
            _RAW_HELD.discard(slot)


@contextmanager
def heavy_slot(*, timeout: float | None = None, reentrant: bool = True) -> Iterator[int]:
    """Acquire a slot; trace bootstrap is PID-reentrant, concurrent commands are not."""
    global _LEASE_DEPTH, _LEASE_FD, _LEASE_SLOT
    _reset_after_fork()
    if not reentrant:
        owner_pid = os.getpid()
        slot, fd = _acquire_slot(timeout)
        try:
            yield slot
        finally:
            _release_slot(slot, fd, owner_pid)
        return
    owner_pid = os.getpid()
    with _LEASE_LOCK:
        if _LEASE_DEPTH:
            _LEASE_DEPTH += 1
            slot = _LEASE_SLOT
        else:
            slot, fd = _acquire_slot(timeout)
            _LEASE_SLOT, _LEASE_FD, _LEASE_DEPTH = slot, fd, 1
    try:
        yield int(slot)
    finally:
        if os.getpid() != owner_pid:
            _after_fork_child()
            return
        with _LEASE_LOCK:
            _reset_after_fork()
            _LEASE_DEPTH -= 1
            if _LEASE_DEPTH == 0:
                fd, _LEASE_FD = _LEASE_FD, None
                slot, _LEASE_SLOT = _LEASE_SLOT, None
                if fd is not None:
                    _release_slot(int(slot), fd, owner_pid)


def _windows_query_handle(pid):
    """Pin an observed lifetime for one watcher; retain granted query rights."""
    import ctypes
    from ctypes import wintypes
    handles = getattr(_WINDOWS_SAMPLE, 'handles', None)
    if handles is not None and pid in handles:
        return handles[pid], False
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    opened = kernel32.OpenProcess
    opened.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    opened.restype = wintypes.HANDLE
    handle = opened(0x00100000 | 0x0400 | 0x0010, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}: return None, False
        raise ctypes.WinError(error)
    wait = kernel32.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    if wait(handle, 0) == 0:
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        return None, False
    if handles is not None:
        handles[pid] = handle
        return handle, False
    return handle, True


def _windows_created(pid: int, handle=None) -> int | None:
    """Read a process lifetime, using an owned Popen handle when available."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    opened = False
    if handle is None:
        handle, opened = _windows_query_handle(pid)
        if handle is None: return None
    times = [wintypes.FILETIME() for _ in range(4)]
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
    get_times.restype = wintypes.BOOL
    try:
        if not get_times(handle, *[ctypes.byref(value) for value in times]):
            raise ctypes.WinError(ctypes.get_last_error())
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        if opened:
            close = kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            close(handle)


def _created_descendants(parents, root_pid, root_birth, created):
    """A Windows PPID alone is not ownership: the parent PID may be recycled."""
    result, frontier = set(), {root_pid: root_birth}
    while frontier:
        children = {}
        for pid, parent in parents.items():
            if parent not in frontier or pid == root_pid or pid in result:
                continue
            birth = created(pid)
            if birth is not None and birth >= frontier[parent]:
                children[pid] = birth
        result.update(children)
        frontier = children
    return sorted(result)


def _descendant_pids(root_pid: int) -> list[int]:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_snapshot = kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        create_snapshot.restype = wintypes.HANDLE
        snap = create_snapshot(0x00000002, 0)
        invalid = ctypes.c_void_p(-1).value
        if not snap or snap == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            first = kernel32.Process32FirstW
            next_item = kernel32.Process32NextW
            first.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            first.restype = wintypes.BOOL
            next_item.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            next_item.restype = wintypes.BOOL
            parents: dict[int, int] = {}
            ok = first(snap, ctypes.byref(entry))
            while ok:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = next_item(snap, ctypes.byref(entry))
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            close_handle(snap)
        birth = _WINDOWS_ROOT_BIRTHS.get(root_pid)
        if birth is None:
            birth = _windows_created(root_pid)
        if birth is None:
            return []
        return _created_descendants(parents, root_pid, birth, _windows_created)
    else:
        parents = {}
        groups = {}
        proc = Path("/proc")
        for item in proc.iterdir():
            if not item.name.isdecimal():
                continue
            try:
                stat = (item / "stat").read_text(encoding="ascii")
                tail = stat[stat.rfind(")") + 2 :].split()
                parents[int(item.name)] = int(tail[1])
                groups[int(item.name)] = int(tail[2])
            except (OSError, ValueError, IndexError):
                continue
    result = set()
    if os.name != "nt" and groups.get(root_pid) == root_pid:
        # capture_resource_bounded starts an isolated session. Its process group
        # remains the ownership boundary even if the leader exits before a child.
        result.update(pid for pid, group in groups.items() if group == root_pid and pid != root_pid)
    frontier = {root_pid}
    while frontier:
        children = {pid for pid, parent in parents.items() if parent in frontier and pid != root_pid}
        children -= result
        result.update(children)
        frontier = children
    return sorted(result)


def _windows_memory(pid: int) -> tuple[int, int] | None:
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    close = kernel32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    get_info = psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    wait_for = kernel32.WaitForSingleObject
    wait_for.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for.restype = wintypes.DWORD
    handle, opened = _windows_query_handle(pid)
    if handle is None: return None
    try:
        expected = _WINDOWS_ROOT_BIRTHS.get(pid)
        if expected is not None and _windows_created(pid, handle) != expected:
            return None
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        if not get_info(handle, ctypes.byref(counters), counters.cb):
            code = ctypes.get_last_error()
            wait = wait_for(handle, 0)
            if wait == 0:
                return None
            raise OSError(code, "GetProcessMemoryInfo failed for a live owned P22 process")
        return int(counters.PrivateUsage), int(counters.WorkingSetSize)
    finally:
        if opened: close(handle)


def _posix_memory(pid: int) -> tuple[int, int] | None:
    base = Path("/proc") / str(pid)
    try:
        status = (base / "status").read_text(encoding="ascii", errors="replace")
        working = 0
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                working = int(line.split()[1]) * 1024
                break
        private = 0
        for line in (base / "smaps_rollup").read_text(encoding="ascii", errors="replace").splitlines():
            if line.startswith(("Private_Clean:", "Private_Dirty:", "Private_Hugetlb:")):
                private += int(line.split()[1]) * 1024
        return private, working
    except (OSError, ValueError, IndexError) as error:
        # A disappearing /proc entry is a normal process-exit race. A live
        # process whose counters cannot be read is different: fail closed.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        except OSError as probe_error:
            if probe_error.errno == errno.ESRCH:
                return None
            raise
        raise OSError(f"Cannot sample memory for live owned process {pid}") from error


def _sample_owned_tree(root_pid: int) -> tuple[list[dict], str | None]:
    rows = []
    try:
        # Tree enumeration is part of sampling too: if it fails, the caller
        # must treat the guard as unavailable and stop its just-started child.
        pids = [root_pid, *_descendant_pids(root_pid)]
        sample = _windows_memory if os.name == "nt" else _posix_memory
        for pid in pids:
            values = sample(pid)
            if values is not None:
                rows.append({"pid": pid, "privateBytes": values[0], "workingSetBytes": values[1]})
    except (OSError, PermissionError) as error:
        return [], f"owned process memory is inaccessible: {type(error).__name__}"
    if not rows:
        return rows, "process memory APIs returned no owned-process samples"
    return rows, None


def _kill_owned_tree(pid: int, process: subprocess.Popen | None = None) -> bool:
    """Kill only the process tree rooted at a caller-owned process."""
    if os.name == "nt":
        # taskkill /T follows unqualified PPIDs too. Use the same lifetime
        # boundary for termination as sampling, including a handle check
        # immediately before terminating each child.
        import ctypes
        from ctypes import wintypes
        previous = getattr(_WINDOWS_SAMPLE, 'handles', None)
        temporary = previous is None
        handles = {} if temporary else previous
        _WINDOWS_SAMPLE.handles = handles
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        opened = kernel.OpenProcess
        opened.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        opened.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        terminate = kernel.TerminateProcess
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        wait = kernel.WaitForSingleObject
        wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait.restype = wintypes.DWORD
        previous_birth = _WINDOWS_ROOT_BIRTHS.get(pid)
        try:
            birth = previous_birth
            if process is not None or birth is None:
                birth = _windows_created(pid, getattr(process, '_handle', None))
            if birth is None:
                return process is not None and process.poll() is not None
            _WINDOWS_ROOT_BIRTHS[pid] = birth
            children = _descendant_pids(pid)
            targets = [(child, _windows_created(child)) for child in reversed(children)]
            if process is None or process.poll() is None:
                targets.append((pid, birth))
            stopped = True
            for target, expected in targets:
                if expected is None:
                    continue  # Exited between enumeration and observation.
                handle = opened(0x00100000 | 0x1000 | 0x0001, False, target)
                if not handle:
                    if ctypes.get_last_error() not in {87, 1168}: stopped = False
                    continue
                try:
                    if _windows_created(target, handle) != expected:
                        stopped = False  # A reused PID never grants authority.
                    elif wait(handle, 0) != 0:
                        stopped = bool(terminate(handle, 1) and wait(handle, 2000) == 0) and stopped
                finally:
                    close(handle)
            return stopped
        except OSError:
            return False
        finally:
            if previous_birth is None:
                _WINDOWS_ROOT_BIRTHS.pop(pid, None)
            else:
                _WINDOWS_ROOT_BIRTHS[pid] = previous_birth
            _WINDOWS_SAMPLE.handles = previous
            if temporary:
                for handle in handles.values(): close(handle)
    try:
        os.killpg(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False


@dataclass
class MemoryWatch:
    pid: int
    limit_bytes: int = _MEMORY_LIMIT
    poll_interval: float = 0.2
    logs_root: Path | None = None
    run_id: str | None = None
    process: subprocess.Popen | None = None
    reason: str | None = None
    offending_pid: int | None = None
    peak_private_bytes: int = 0
    peak_working_set_bytes: int = 0
    error: str | None = None
    process_tree_stopped: bool | None = None
    _stop: threading.Event | None = None
    _thread: threading.Thread | None = None
    available: bool = False
    _root_birth: int | None = None
    _windows_handles: dict | None = None

    def _sample(self):
        previous = getattr(_WINDOWS_SAMPLE, 'handles', None)
        if os.name == 'nt':
            if self._windows_handles is None: self._windows_handles = {}
            # Retain live query grants, but release exited process objects:
            # keeping them alive would prevent positive dead-PID observations.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            wait = kernel.WaitForSingleObject
            wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait.restype = wintypes.DWORD
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            for pid, handle in list(self._windows_handles.items()):
                if wait(handle, 0) == 0:
                    close(handle)
                    del self._windows_handles[pid]
            _WINDOWS_SAMPLE.handles = self._windows_handles
        try:
            return _sample_owned_tree(self.pid)
        finally:
            _WINDOWS_SAMPLE.handles = previous

    def _close_query_handles(self):
        if not self._windows_handles: return
        import ctypes
        from ctypes import wintypes
        close = ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        for handle in self._windows_handles.values(): close(handle)
        self._windows_handles.clear()

    def start(self) -> "MemoryWatch":
        if self.pid <= 0 or self.limit_bytes <= 0 or self.poll_interval <= 0:
            raise ValueError("Invalid memory watcher bounds")
        if os.name == 'nt':
            # Retain the original lifetime after exit, while real orphaned
            # children drain. Popen's handle cannot refer to a recycled PID.
            self._root_birth = _windows_created(self.pid, getattr(self.process, '_handle', None))
            if self._root_birth is not None:
                _WINDOWS_ROOT_BIRTHS[self.pid] = self._root_birth
        try:
            rows, error = self._sample()
        except BaseException:
            self.stop()
            raise
        if not rows:
            if self.process is not None and self.process.poll() is not None:
                self.reason = "completed-before-sample"
                self.error = "Owned process exited before its first memory sample"
                return self
            self.stop()
            raise RuntimeError(error or "Memory watcher could not sample the owned process tree")
        self.available = True
        self.error = error
        for row in rows:
            self.peak_private_bytes = max(self.peak_private_bytes, row["privateBytes"])
            self.peak_working_set_bytes = max(self.peak_working_set_bytes, row["workingSetBytes"])
            if memory_limit_exceeded(row["privateBytes"], row["workingSetBytes"], self.limit_bytes):
                self.reason, self.offending_pid = "memorylimit", row["pid"]
                self._write_limit_marker(row)
                self.process_tree_stopped = _kill_owned_tree(self.pid, self.process)
                self._write_limit_marker(row)
                return self
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"p22-memory-{self.pid}", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            self._monitor()
        finally:
            self._close_query_handles()

    def _monitor(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                rows, error = self._sample()
                if error:
                    if self.process is not None and self.process.poll() is not None:
                        return
                    if self.process is None and not rows:
                        # With only a PID, absence means it may have exited and
                        # been reused. Fail the observation, but never kill it.
                        self.reason = "memorywatch-unavailable"
                        self.error = error
                        self._write_failure_marker()
                        return
                    self.error = error
                    self.reason = "memorywatch-unavailable"
                    self._write_failure_marker()
                    self.process_tree_stopped = _kill_owned_tree(self.pid, self.process)
                    return
                if rows:
                    self.available = True
                for row in rows:
                    private, working = row["privateBytes"], row["workingSetBytes"]
                    self.peak_private_bytes = max(self.peak_private_bytes, private)
                    self.peak_working_set_bytes = max(self.peak_working_set_bytes, working)
                    if memory_limit_exceeded(private, working, self.limit_bytes):
                        self.reason, self.offending_pid = "memorylimit", row["pid"]
                        self._write_limit_marker(row)
                        self.process_tree_stopped = _kill_owned_tree(self.pid, self.process)
                        self._write_limit_marker(row)
                        return
            except Exception as error:
                self.error = f"memory-watch-error:{type(error).__name__}"
                self.reason = "memorywatch-unavailable"
                self._write_failure_marker()
                if self.process is not None and self.process.poll() is None:
                    self.process_tree_stopped = _kill_owned_tree(self.pid, self.process)
                return
            self._stop.wait(self.poll_interval)

    def _write_limit_marker(self, row: dict) -> None:
        if self.logs_root is None:
            return
        try:
            self.logs_root.mkdir(parents=True, exist_ok=True)
            path = self.logs_root / f"memorylimit-{self.pid}-{self.run_id or 'manual'}.json"
            path.write_text(json.dumps({
                "schema": "neyvia.contract-resource-limit.v1", "reason": "memorylimit",
                "rootPid": self.pid, "runId": self.run_id, "offendingPid": row["pid"], "limitBytes": self.limit_bytes,
                "privateBytes": row["privateBytes"], "workingSetBytes": row["workingSetBytes"],
                "terminationRequested": True, "processTreeStopped": self.process_tree_stopped,
            }, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            self.error = "memory-limit marker could not be written"

    def _write_failure_marker(self) -> None:
        if self.logs_root is None:
            return
        try:
            self.logs_root.mkdir(parents=True, exist_ok=True)
            path = self.logs_root / f"resourcewatch-failed-{self.pid}-{self.run_id or 'manual'}.json"
            path.write_text(json.dumps({
                "schema": "neyvia.contract-resource-limit.v1", "reason": "memorywatch-unavailable",
                "rootPid": self.pid, "runId": self.run_id, "error": self.error,
            }, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(1.0, self.poll_interval * 4))
        if self._thread is None or not self._thread.is_alive():
            self._close_query_handles()
        if self._root_birth is not None and _WINDOWS_ROOT_BIRTHS.get(self.pid) == self._root_birth:
            _WINDOWS_ROOT_BIRTHS.pop(self.pid, None)


@contextmanager
def memory_watch(
    pid: int | subprocess.Popen,
    *,
    limit_bytes: int = _MEMORY_LIMIT,
    poll_interval: float = 0.2,
    logs_root: str | os.PathLike[str] | None = None,
    run_id: str | None = None,
) -> Iterator[MemoryWatch]:
    """Watch an owned PID and its descendants; stop its tree over either 3 GiB measure."""
    logs = Path(logs_root or os.environ.get("NEYVIA_CONTRACT_RESOURCE_LOGS_ROOT", "")) if (logs_root or os.environ.get("NEYVIA_CONTRACT_RESOURCE_LOGS_ROOT")) else None
    marker_id = run_id or os.environ.get("NEYVIA_CONTRACT_RESOURCE_RUN_ID")
    process = pid if isinstance(pid, subprocess.Popen) else None
    watcher = MemoryWatch(int(pid.pid if process else pid), int(limit_bytes), float(poll_interval), logs,
                          marker_id, process).start()
    try:
        yield watcher
    finally:
        watcher.stop()


def _tail(path: Path, limit: int = _TAIL_BYTES) -> tuple[str, bool]:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - limit), os.SEEK_SET)
        raw = stream.read(limit)
    return raw.decode("utf-8", errors="replace"), size > limit


def _stop_process_tree(process: subprocess.Popen) -> bool:
    if process.poll() is not None:
        try:
            if not _descendant_pids(process.pid):
                return True
        except OSError:
            # The Popen handle is still authoritative for the root, but an
            # exited root's PID cannot safely be reused to target unknown kids.
            return False
    stopped = _kill_owned_tree(process.pid, process)
    if process.poll() is None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                stopped = False
    return stopped


def capture_resource_bounded(
    args,
    *,
    cwd,
    env,
    input_text,
    timeout: float,
    logs_root: str | os.PathLike[str],
    acquire_slot: bool = True,
    limit_bytes: int = _MEMORY_LIMIT,
) -> dict:
    """Run one command with its own permit, D-backed logs, and a bounded tree cutoff."""
    logs = Path(logs_root)
    logs.mkdir(parents=True, exist_ok=True)
    root = _SCRATCH.resolve()
    resolved_logs = logs.resolve()
    if not resolved_logs.is_relative_to(root):
        raise ValueError("Resource logs must stay under D:/NeyviaRuns/P22")
    if timeout <= 0 or limit_bytes <= 0 or limit_bytes > _MEMORY_LIMIT:
        raise ValueError("timeout and memory limit must be positive")
    started = time.monotonic()
    deadline = started + timeout
    run_id = uuid.uuid4().hex
    stdout_path, stderr_path = logs / f"{run_id}.stdout.log", logs / f"{run_id}.stderr.log"

    def execute() -> dict:
        timed_out = False
        tree_stopped = None
        watch = None
        watch_error = None
        child_env = dict(env if env is not None else os.environ)
        child_env["NEYVIA_CONTRACT_RESOURCE_RUN_ID"] = run_id
        child_env["NEYVIA_CONTRACT_RESOURCE_LOGS_ROOT"] = str(logs.resolve())
        process = None
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                args, cwd=str(cwd), env=child_env, stdin=subprocess.PIPE,
                stdout=stdout_file, stderr=stderr_file, start_new_session=os.name != "nt",
                **_hidden_process_kwargs(),
            )
            try:
                watch = MemoryWatch(process.pid, limit_bytes, 0.2, logs, run_id, process).start()
            except RuntimeError as error:
                watch_error = str(error)
                tree_stopped = _stop_process_tree(process)
            try:
                if process.stdin is not None:
                    try:
                        if input_text is not None:
                            process.stdin.write(input_text.encode("utf-8") if isinstance(input_text, str) else input_text)
                            process.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    finally:
                        process.stdin.close()
                while watch_error is None and (process.poll() is None or _descendant_pids(process.pid)):
                    if watch.reason is not None:
                        tree_stopped = watch.process_tree_stopped
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        tree_stopped = _stop_process_tree(process)
                        break
                    if process.poll() is not None:
                        time.sleep(min(0.2, remaining))
                        continue
                    try:
                        process.wait(timeout=min(0.2, remaining))
                    except subprocess.TimeoutExpired:
                        continue
                if process.poll() is None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        tree_stopped = _stop_process_tree(process)
                else:
                    try:
                        if _descendant_pids(process.pid):
                            tree_stopped = False
                    except OSError:
                        # Preserve a prior successful owned-tree kill result;
                        # otherwise report unknown cleanup instead of raising.
                        if tree_stopped is None:
                            tree_stopped = False
            finally:
                if watch is not None:
                    watch.stop()
                    if watch.reason in {"memorylimit", "memorywatch-unavailable"}:
                        # The worker can exit between the watcher kill and the
                        # first polling-loop observation. Preserve the kill
                        # result from the watcher instead of leaving None.
                        tree_stopped = watch.process_tree_stopped
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
        stdout, stdout_truncated = _tail(stdout_path)
        stderr, stderr_truncated = _tail(stderr_path)
        marker_path = logs / f"memorylimit-{process.pid}-{run_id}.json"
        marker = None
        if marker_path.is_file():
            try:
                candidate = json.loads(marker_path.read_text(encoding="utf-8"))
                if candidate.get("runId") == run_id:
                    marker = candidate
            except (OSError, ValueError, AttributeError):
                pass
        failure_path = logs / f"resourcewatch-failed-{process.pid}-{run_id}.json"
        failure_marker = None
        if failure_path.is_file():
            try:
                candidate = json.loads(failure_path.read_text(encoding="utf-8"))
                if candidate.get("runId") == run_id:
                    failure_marker = candidate
            except (OSError, ValueError, AttributeError):
                pass
        reason = ("memorylimit" if (watch is not None and watch.reason == "memorylimit")
                  or (marker is not None and marker.get("reason") == "memorylimit") else
                  "memorywatch-unavailable" if watch_error or (watch is not None and watch.reason == "memorywatch-unavailable")
                  or failure_marker is not None else
                  "timeout" if timed_out else None)
        process_returncode = process.poll()
        # A killed child can still surface exit code zero (for example when
        # termination races its normal exit). The resource violation is the
        # outcome; never let that OS exit code make the bounded run pass.
        effective_returncode = (125 if reason in {"memorylimit", "memorywatch-unavailable"}
                                else process_returncode)
        result = {
            "stdout": stdout, "stderr": stderr, "returncode": effective_returncode,
            "processReturncode": process_returncode,
            "memoryExceeded": reason == "memorylimit",
            "rootProcessStopped": process.poll() is not None,
            "peakPrivateBytes": watch.peak_private_bytes if watch else 0,
            "peakWorkingSetBytes": watch.peak_working_set_bytes if watch else 0,
            "timedOut": timed_out, "processTreeStopped": tree_stopped,
            "reason": reason, "stdoutTruncated": stdout_truncated, "stderrTruncated": stderr_truncated,
            "logs": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
            "memory": {"limitBytes": limit_bytes,
                       "peakPrivateBytes": watch.peak_private_bytes if watch else 0,
                       "peakWorkingSetBytes": watch.peak_working_set_bytes if watch else 0,
                       "offendingPid": (watch.offending_pid if watch and watch.offending_pid else
                                        marker.get("offendingPid") if marker else None),
                       "watchError": watch_error or (watch.error if watch else None)
                       or (failure_marker.get("error") if failure_marker else None)},
            "durationMs": round((time.monotonic() - started) * 1000),
        }
        if reason == "memorylimit":
            result["resourceLimitReceipt"] = str(marker_path)
        elif reason == "memorywatch-unavailable" and failure_marker is not None:
            result["resourceLimitReceipt"] = str(failure_path)
        return result

    if acquire_slot:
        try:
            with heavy_slot(timeout=max(0.0, deadline - time.monotonic()), reentrant=False):
                if time.monotonic() >= deadline:
                    raise TimeoutError("P22 worker deadline expired while acquiring its slot")
                return execute()
        except TimeoutError:
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)
            return {
                "stdout": "", "stderr": "", "returncode": None,
                "processReturncode": None, "memoryExceeded": False,
                "rootProcessStopped": None,
                "peakPrivateBytes": 0, "peakWorkingSetBytes": 0,
                "timedOut": True, "processTreeStopped": None, "reason": "slot-timeout",
                "stdoutTruncated": False, "stderrTruncated": False,
                "logs": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
                "memory": {"limitBytes": limit_bytes, "peakPrivateBytes": 0,
                           "peakWorkingSetBytes": 0, "offendingPid": None,
                           "watchError": None},
                "durationMs": round((time.monotonic() - started) * 1000),
            }
    return execute()


def _hidden_process_kwargs() -> dict:
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startup.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {"creationflags": flags, "startupinfo": startup}
