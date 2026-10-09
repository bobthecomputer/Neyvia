"""Fail-closed input-desktop observation for isolated computer-use sessions.

The observer binds a fresh thread to the input desktop. It never switches the
desktop, sends input, activates a window, or reads window titles. Its sole
mutation is emergency hiding of an owned window that escaped containment.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import copy
import json
import os
from pathlib import Path
import queue
import threading
import time
import psutil


def _process_birth(pid):
    """Process identity; stale Toolhelp parent PIDs never grant ownership."""
    try:
        # Existing psutil also reads system process metadata when Windows
        # sandbox ACLs deny OpenProcess; no privilege or token change.
        return psutil.Process(int(pid)).create_time()
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied as exc:
        raise RuntimeError("process_identity_unavailable") from exc


# Upper bound for one observation barrier (see snapshot).
SNAPSHOT_BARRIER_S = 10.0


class ZeroDisturbanceGuard:
    def __init__(self, owner_pid=None, external_log=None, poll_ms=10):
        self.owner_pid = int(owner_pid or os.getpid())
        self.external_log = Path(external_log or
            r"C:\Users\user\Projects\plans\logs\window-guard.jsonl")
        self.poll_ms = max(1, int(poll_ms))
        self._roots = {self.owner_pid}
        self._owned = set(self._roots)
        self._births = {self.owner_pid: _process_birth(self.owner_pid)}
        self._rejected_parent_edges = {}
        self._lock = threading.RLock()
        self._requests = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._ready = threading.Event()
        self._tree_dirty = threading.Event()
        self._thread = None
        self._violations = {}
        self._samples = 0
        self._foreground_events = 0
        self._cursor_events = 0
        self._injected_keyboard_events = 0
        self._physical_mouse_events = 0
        self._physical_keyboard_events = 0
        self._unowned_foreground_events = 0
        self._observed_cursor_moves = 0
        self._unowned_windows = set()
        self._known_event_pids = set()
        self._last_foreground = None
        self._hooks_ready = False
        self._new_windows = set()
        self._hidden = set()
        self._containment_log = []
        self._parked = {}
        self._bureau_leases = {}
        self._parked_observed = set()
        self._cloaked_observed = set()
        self._baseline = None
        self._current = None
        self._external_entries = 0
        self._external_unowned_entries = 0
        self._external_unattributed_entries = 0
        self._log_offset = 0
        self._initial_log_offset = 0
        self._log_remainder = b""
        self._started = None
        self._closed = False
        self._shell_thread = None
        self._shell_ready = threading.Event()
        self._shell_samples = 0
        self._slowest_barrier_ms = 0.0

    def _fail(self, reason):
        with self._lock:
            self._violations[reason] = self._violations.get(reason, 0) + 1

    def _owns_live_pid(self, pid):
        return pid in self._owned and _process_birth(pid) == self._births.get(pid)

    def start(self):
        if self._thread:
            return self
        self._started = time.monotonic()
        try:
            self._log_offset = self.external_log.stat().st_size
        except FileNotFoundError:
            self._log_offset = 0
        except OSError:
            self._fail("external_guard_log_unreadable")
        self._thread = threading.Thread(target=self._run, name="cua-input-guard", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self._fail("input_guard_start_timeout")
        return self

    def register_pid(self, pid):
        birth = _process_birth(pid)
        if birth is None:
            self._fail("registered_process_identity_unavailable")
            return
        with self._lock:
            self._roots.add(int(pid))
            self._owned.add(int(pid))
            self._births[int(pid)] = birth
            self._tree_dirty.set()

    def observe_shell_desktop(self):
        """Observe Explorer's desktop too, including when input is locked."""
        if self._shell_thread is None:
            self._shell_thread=threading.Thread(target=self._run_shell,name='cua-shell-guard',daemon=True)
            self._shell_thread.start()
        if not self._shell_ready.wait(3) or not self._shell_thread.is_alive():
            self._fail('shell_desktop_observation_unavailable')
        if not self.snapshot()['ok']:
            raise RuntimeError('shell_desktop_observation_failed')

    def register_parked_window(self, hwnd, pid, receipt):
        """Register previsibility containment; never modify or activate a HWND.

        DeleteTab must have succeeded in the launcher. Geometry and styles are
        independently checked here on every sample, including subsequent moves.
        """
        hwnd, pid = int(hwnd), int(pid)
        with self._lock:
            if not hwnd or not self._owns_live_pid(pid) or not isinstance(receipt, dict):
                raise ValueError("parked_window_requires_owned_pid")
            pending = (receipt.get("route") == "agent-bureau" and receipt.get("cloaked") is True
                and receipt.get("previsibility") is True and receipt.get("taskbarRemovalPending") is True)
            member = (receipt.get('route')=='agent-bureau' and receipt.get('membershipVerified') is True
                      and receipt.get('shellCloakVerified') is True)
            if receipt.get("delete_tab_ok") is not True and not pending and not member:
                raise ValueError("parked_window_requires_delete_tab_receipt")
            if int(receipt.get("hwnd", hwnd)) != hwnd or int(receipt.get("pid", pid)) != pid:
                raise ValueError("parked_window_receipt_owner_mismatch")
            self._parked[hwnd] = {"pid": pid, "receipt": copy.deepcopy(receipt)}

    def begin_bureau_move(self, hwnd, pid):
        """Single HWND lease; never renew or lease a private desktop window."""
        hwnd, pid = int(hwnd), int(pid)
        with self._lock:
            if not hwnd or not self._owns_live_pid(pid) or hwnd in self._bureau_leases:
                raise ValueError("bureau_move_requires_new_owned_hwnd_lease")
            now = time.time()
            lease = {"hwnd": hwnd, "pid": pid, "from": now, "until": now + 3,
                     "owner": "C11g-Bureau-move", "renewable": False}
            self._bureau_leases[hwnd] = lease
            allow = self.external_log.with_name("window-guard-allow.jsonl")
            with allow.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(lease) + "\n")
            return copy.deepcopy(lease)

    def _receipt(self):
        with self._lock:
            return {
                "ok": bool(self._baseline and self._hooks_ready and not self._violations),
                "contract": "zero-disturbance-attributed-v3",
                "input_desktop_bound": bool(self._baseline),
                "observation": "continuous-events-and-samples",
                "violations": dict(self._violations),
                "baseline": copy.deepcopy(self._baseline),
                "current": copy.deepcopy(self._current),
                "samples": self._samples,
                "foreground_changes": self._foreground_events,
                "cursor_moves": self._cursor_events,
                "injected_mouse_events": self._cursor_events,
                "injected_keyboard_events": self._injected_keyboard_events,
                "input_hooks_installed": self._hooks_ready,
                "unowned_activity": {
                    "foreground_changes": self._unowned_foreground_events,
                    "new_visible_windows": len(self._unowned_windows),
                    "observed_cursor_moves": self._observed_cursor_moves,
                    "physical_mouse_events": self._physical_mouse_events,
                    "physical_keyboard_events": self._physical_keyboard_events,
                    "external_guard_entries": self._external_unowned_entries,
                    "external_guard_unattributed_entries": self._external_unattributed_entries,
                },
                "new_visible_windows": len(self._new_windows),
                "owned_escaped_windows_hidden": len(self._hidden),
                "containment_log": list(self._containment_log),
                "parked_window_registrations": copy.deepcopy(self._parked),
                "bureau_move_leases": copy.deepcopy(self._bureau_leases),
                "visibility_diagnostics_enabled": True,
                "shell_desktop_observed": bool(self._shell_ready.is_set() and self._shell_thread),
                "shell_desktop_samples": self._shell_samples,
                "parked_windows_observed": len(self._parked_observed),
                "contained_cloaked_windows_observed": len(self._cloaked_observed),
                "owned_process_count": len(self._owned),
                "ownership": {"identity": "pid-and-creation-time", "births": dict(self._births),
                    "rejectedParentEdges": list(self._rejected_parent_edges.values()), "psutilVersion": psutil.__version__},
                "external_guard_entries": self._external_entries,
                "external_guard_log_baseline_bytes": self._initial_log_offset,
                "elapsed_ms": round((time.monotonic() - self._started) * 1000, 2) if self._started else 0,
                "slowest_barrier_ms": self._slowest_barrier_ms,
                "closed": self._closed,
            }

    def snapshot(self):
        if not self._thread:
            self.start()
        if self._closed or not self._thread.is_alive():
            self._fail("input_guard_not_running")
            return self._receipt()
        if self._thread.is_alive() and not self._closed:
            done = threading.Event()
            self._requests.put(done)
            self._wake.set()
            started = time.monotonic()
            # Hooks record continuously; a barrier only waits for one more full
            # observation pass. On a loaded PC that pass can exceed 2 s while
            # nothing was missed, so a slow pass is measured, not a violation.
            if not done.wait(SNAPSHOT_BARRIER_S):
                self._fail("input_guard_snapshot_timeout")
            waited = round((time.monotonic() - started) * 1000, 2)
            with self._lock:
                self._slowest_barrier_ms = max(self._slowest_barrier_ms, waited)
        return self._receipt()

    check = snapshot

    def close(self):
        if not self._thread:
            self.start()
        self._stop.set()
        self._wake.set()
        self._thread.join(3)
        if self._shell_thread:
            self._shell_thread.join(3)
            if self._shell_thread.is_alive():self._fail('shell_guard_close_timeout')
        if self._thread.is_alive():
            self._fail("input_guard_close_timeout")
        self._closed = True
        return self._receipt()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()

    def _record_input(self, device, flags):
        """Flags are observed by LL hooks; this never generates input."""
        with self._lock:
            if device == "mouse":
                if int(flags) & 0x01:  # LLMHF_INJECTED (includes lower-integrity input).
                    self._cursor_events += 1
                    self._fail("injected_mouse_input")
                else:
                    self._physical_mouse_events += 1
            elif device == "keyboard":
                if int(flags) & 0x10:  # LLKHF_INJECTED.
                    self._injected_keyboard_events += 1
                    self._fail("injected_keyboard_input")
                else:
                    self._physical_keyboard_events += 1

    def _record_foreground(self, hwnd, pid):
        with self._lock:
            owned = self._owns_live_pid(pid)
            if self._last_foreground is None and owned:
                self._fail("owned_foreground_at_start")
            elif self._last_foreground is not None and hwnd != self._last_foreground:
                if owned:
                    self._foreground_events += 1
                    self._fail("owned_foreground_change")
                else:
                    self._unowned_foreground_events += 1
            self._last_foreground = hwnd

    def _record_state(self, value, hide_window):
        with self._lock:
            self._record_foreground(value["foreground"], value["foreground_pid"])
            if self._baseline is None:
                self._baseline = value
            elif self._current and value["cursor"] != self._current["cursor"]:
                # Position alone cannot attribute a move; the LL hooks do that.
                self._observed_cursor_moves += 1
            for hwnd, pid in value["visible"].items():
                if self._owns_live_pid(pid):
                    if self._contained_cloak(hwnd, pid, value.get("window_details", {}).get(hwnd, {})):
                        continue
                    self._record_visible_event(hwnd, pid, hide_window)
                elif hwnd not in self._baseline["visible"]:
                    self._unowned_windows.add(hwnd)
            self._current = value
            self._samples += 1

    def _contained_cloak(self, hwnd, pid, details):
        registration = self._parked.get(hwnd, {})
        receipt = registration.get("receipt", {})
        rect = details.get("rect", [])
        if (registration.get("pid") == pid and receipt.get("route") == "agent-bureau"
                and receipt.get("membershipVerified") is True
                and details.get("cloak", 0) & 2 and details.get("nativeContainment") is True):
            self._cloaked_observed.add(hwnd)
            return True
        if (registration.get("pid") == pid and receipt.get("route") == "agent-bureau"
                and receipt.get("registrationUntil", 0) >= time.time()
                and details.get("zeroOpacity") is True and details.get("nativeContainment") is True
                and len(rect) == 4):
            self._cloaked_observed.add(hwnd)
            return True
        if (registration.get("pid") == pid and receipt.get("route") == "agent-bureau"
                and receipt.get("offscreenRegistration") is True
                and receipt.get("registrationUntil", 0) >= time.time()
                and len(rect) == 4 and rect[:2] == [-32000, -32000]
                and rect[2] < -16000 and rect[3] < -16000
                and details.get("nativeContainment") is True):
            self._cloaked_observed.add(hwnd)
            return True
        contained = (registration.get("pid") == pid and receipt.get("route") == "agent-bureau"
            and receipt.get("cloaked") is True
            and (details.get("cloak", 0) != 0 or (receipt.get("taskbarRemovalPending") is True
                and receipt.get("registrationUntil", 0) >= time.time()
                and details.get("zeroOpacity") is True))
            and (details.get("extended_style", 0) & 0x08000000
                or (receipt.get("taskbarRemovalPending") is True and details.get("zeroOpacity") is True
                    and details.get("nativeContainment") is True))
            and (details.get("rect", [])[:2] == [-32000, -32000]
                or (receipt.get("taskbarRemovalPending") is True and details.get("zeroOpacity") is True)))
        if contained:
            self._cloaked_observed.add(hwnd)
        return bool(contained)

    def _record_visible_event(self, hwnd, pid, hide_window):
        """Retain transient owned visibility without rescanning in a callback."""
        with self._lock:
            if not self._owns_live_pid(pid):
                self._unowned_windows.add(hwnd)
                return
            if hwnd not in self._new_windows:
                self._new_windows.add(hwnd)
                self._fail("new_owned_visible_input_window")
            hide_window(hwnd)
            if hwnd not in self._hidden:
                identity = {}
                try:
                    process = psutil.Process(pid)
                    process_name = process.name()
                    identity = {"processBirth": process.create_time(),
                                "parentPid": process.ppid()}
                    # Paths and executable/script basenames only. Never retain
                    # raw arguments, prompts, account data or terminal output.
                    lineage = []
                    for ancestor in [process, *process.parents()][:8]:
                        command = ancestor.cmdline()
                        lineage.append({'pid': ancestor.pid, 'name': ancestor.name(),
                            'birth': ancestor.create_time(), 'parentPid': ancestor.ppid(),
                            'program': Path(command[0]).name if command else None,
                            'scripts': [Path(value).name for value in command[1:] if
                                value.lower().endswith(('.py', '.mjs', '.js', '.ps1')) and
                                not any(char in value for char in ('\n', '\r'))]})
                    identity['lineage'] = lineage
                except psutil.Error:
                    process_name = None
                class_name = C.create_unicode_buffer(256)
                user = C.WinDLL("user32", use_last_error=True)
                user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
                user.GetClassNameW(hwnd, class_name, len(class_name))
                self._containment_log.append({"pid": pid, "hwnd": hwnd,
                    "processName": process_name,
                    **identity,
                    "windowClass": class_name.value,
                    "action": "hide-and-fail", "elapsed_ms": round(
                        (time.monotonic() - self._started) * 1000, 2)})
                self._fail("owned_visible_input_window_hidden")
            self._hidden.add(hwnd)

    def _record_external_entry(self, line):
        try:
            entry = json.loads(line)
            pid = int(entry["pid"])
        except (ValueError, KeyError, TypeError):
            self._external_unattributed_entries += 1
            return
        if pid in self._owned:
            self._external_entries += 1
            self._fail("external_guard_hid_owned_window")
        else:
            self._external_unowned_entries += 1

    def _read_external_log(self):
        try:
            if not self.external_log.exists():
                if self._log_offset:
                    self._fail("external_guard_log_removed")
                return
            with self.external_log.open("rb") as stream:
                stream.seek(0, 2)
                if stream.tell() < self._log_offset:
                    self._fail("external_guard_log_truncated")
                    return
                stream.seek(self._log_offset)
                data = stream.read(65537)
                self._log_offset = stream.tell()
            if len(data) > 65536:
                self._fail("external_guard_log_overflow")
                return
            lines = (self._log_remainder + data).split(b"\n")
            self._log_remainder = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                self._record_external_entry(line)
        except OSError:
            self._fail("external_guard_log_unreadable")

    def _run_shell(self):
        """Additional event + polling lane, never selects or activates Default."""
        desktop=None;hooks=[]
        try:
            u=C.WinDLL('user32',use_last_error=True);dwm=C.WinDLL('dwmapi')
            u.OpenDesktopW.argtypes=[W.LPCWSTR,W.DWORD,W.BOOL,W.DWORD];u.OpenDesktopW.restype=W.HANDLE
            u.SetThreadDesktop.argtypes=[W.HANDLE];u.SetThreadDesktop.restype=W.BOOL
            u.CloseDesktop.argtypes=[W.HANDLE]
            desktop=u.OpenDesktopW('Default',0,False,255)
            if not desktop or not u.SetThreadDesktop(desktop):raise RuntimeError('shell_guard_binding_failed')
            enum=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
            event=C.WINFUNCTYPE(None,W.HANDLE,W.DWORD,W.HWND,W.LONG,W.LONG,W.DWORD,W.DWORD)
            u.EnumDesktopWindows.argtypes=[W.HANDLE,enum,W.LPARAM];u.EnumDesktopWindows.restype=W.BOOL
            u.IsWindowVisible.argtypes=[W.HWND];u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
            u.IsWindow.argtypes=[W.HWND];u.IsWindow.restype=W.BOOL
            u.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)];u.ShowWindow.argtypes=[W.HWND,C.c_int]
            u.GetWindowLongPtrW.argtypes=[W.HWND,C.c_int];u.GetWindowLongPtrW.restype=C.c_ssize_t
            u.GetPropW.argtypes=[W.HWND,W.LPCWSTR];u.GetPropW.restype=W.HANDLE
            u.GetLayeredWindowAttributes.argtypes=[W.HWND,C.POINTER(W.DWORD),C.POINTER(W.BYTE),C.POINTER(W.DWORD)]
            dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
            u.GetAncestor.argtypes=[W.HWND,W.UINT];u.GetAncestor.restype=W.HWND
            u.SetWinEventHook.argtypes=[W.DWORD,W.DWORD,W.HMODULE,event,W.DWORD,W.DWORD,W.DWORD];u.SetWinEventHook.restype=W.HANDLE
            u.UnhookWinEvent.argtypes=[W.HANDLE];u.GetForegroundWindow.restype=W.HWND
            u.PeekMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
            u.DispatchMessageW.argtypes=[C.POINTER(W.MSG)];u.DispatchMessageW.restype=C.c_ssize_t
            def inspect(hwnd):
                pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
                with self._lock:
                    if not self._owns_live_pid(pid.value):return
                    rect,cloak,alpha,flags=W.RECT(),W.DWORD(),W.BYTE(255),W.DWORD()
                    if not u.GetWindowRect(hwnd,C.byref(rect)):
                        if not u.IsWindow(hwnd):return
                        raise RuntimeError('shell_guard_bounds_failed')
                    if dwm.DwmGetWindowAttribute(hwnd,14,C.byref(cloak),4)<0:
                        if not u.IsWindow(hwnd):return
                        raise RuntimeError('shell_guard_cloak_failed')
                    layered=u.GetLayeredWindowAttributes(hwnd,None,C.byref(alpha),C.byref(flags))
                    details={'rect':[rect.left,rect.top,rect.right,rect.bottom],'cloak':cloak.value,
                        'zeroOpacity':bool(layered and flags.value&2 and alpha.value==0),
                        'extended_style':u.GetWindowLongPtrW(hwnd,-20),
                        'nativeContainment':bool(u.GetPropW(hwnd,'Neyvia.C11.Parked.OriginalProc'))}
                    if not self._contained_cloak(int(hwnd),pid.value,details):
                        self._containment_log.append({'hwnd':int(hwnd),'pid':pid.value,
                            'action':'shell-visibility-diagnostic','observed':details,
                            'registered':copy.deepcopy(self._parked.get(int(hwnd)))})
                        self._record_visible_event(int(hwnd),pid.value,lambda h:u.ShowWindow(h,0))
            @event
            def on_event(_,kind,hwnd,obj,child,tid,at):
                try:
                    if hwnd and kind==3:
                        pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
                        if self._owns_live_pid(pid.value):self._fail('owned_shell_foreground_change')
                    elif hwnd and obj==0 and u.GetAncestor(hwnd,2)==hwnd and u.IsWindowVisible(hwnd):inspect(hwnd)
                except Exception:self._fail('shell_event_observation_failed')
            for kind in (3,0x8000,0x8002):
                hook=u.SetWinEventHook(kind,kind,None,on_event,0,0,0)
                if not hook:raise RuntimeError('shell_event_hook_failed')
                hooks.append(hook)
            @enum
            def each(hwnd,_):
                try:
                    if u.IsWindowVisible(hwnd):inspect(hwnd)
                except Exception:self._fail('shell_sample_observation_failed')
                return True
            msg=W.MSG()
            self._shell_ready.set()
            while True:
                for _ in range(64):
                    if not u.PeekMessageW(C.byref(msg),None,0,0,1):break
                    u.TranslateMessage(C.byref(msg));u.DispatchMessageW(C.byref(msg))
                if not u.EnumDesktopWindows(desktop,each,0):raise RuntimeError('shell_enumeration_failed')
                foreground=u.GetForegroundWindow();pid=W.DWORD()
                if foreground:
                    u.GetWindowThreadProcessId(foreground,C.byref(pid))
                    if self._owns_live_pid(pid.value):self._fail('owned_shell_foreground')
                self._shell_samples+=1
                if self._stop.is_set():break
                self._stop.wait(self.poll_ms/1000)
        except Exception as exc:self._fail(str(exc) if isinstance(exc,RuntimeError) else 'shell_guard_internal_error')
        finally:
            self._shell_ready.set()
            for hook in hooks:u.UnhookWinEvent(hook)
            if desktop:u.CloseDesktop(desktop)

    def _run(self):
        self._initial_log_offset = self._log_offset
        desktop = None
        hooks = []
        mouse_hook = None
        keyboard_hook = None
        try:
            if os.name != "nt":
                raise RuntimeError("windows_required")
            u = C.WinDLL("user32", use_last_error=True)
            k = C.WinDLL("kernel32", use_last_error=True)
            dwm = C.WinDLL("dwmapi")
            dwm.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]
            dwm.DwmGetWindowAttribute.restype = C.c_long
            # Binding precedes every observation and hook, on a window-free thread.
            u.OpenInputDesktop.argtypes = [W.DWORD, W.BOOL, W.DWORD]
            u.OpenInputDesktop.restype = W.HANDLE
            u.SetThreadDesktop.argtypes = [W.HANDLE]
            u.SetThreadDesktop.restype = W.BOOL
            u.CloseDesktop.argtypes = [W.HANDLE]
            desktop = u.OpenInputDesktop(0, False, 0x01 | 0x08 | 0x40 | 0x80)
            if not desktop or not u.SetThreadDesktop(desktop):
                raise RuntimeError("input_desktop_binding_failed")

            enum_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            event_type = C.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND,
                                      W.LONG, W.LONG, W.DWORD, W.DWORD)
            input_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
            class MouseInput(C.Structure):
                _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD),
                            ("flags", W.DWORD), ("time", W.DWORD),
                            ("dwExtraInfo", C.c_size_t)]
            class KeyboardInput(C.Structure):
                _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD),
                            ("flags", W.DWORD), ("time", W.DWORD),
                            ("dwExtraInfo", C.c_size_t)]
            u.EnumDesktopWindows.argtypes = [W.HANDLE, enum_type, W.LPARAM]
            u.EnumDesktopWindows.restype = W.BOOL
            u.IsWindowVisible.argtypes = [W.HWND]
            u.IsWindowVisible.restype = W.BOOL
            u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
            u.GetAncestor.argtypes, u.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
            u.GetForegroundWindow.restype = W.HWND
            u.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
            u.GetWindowRect.restype = W.BOOL
            u.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
            u.GetWindowLongPtrW.restype = C.c_ssize_t
            u.GetSystemMetrics.argtypes = [C.c_int]
            u.GetSystemMetrics.restype = C.c_int
            u.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
            u.GetCursorPos.restype = W.BOOL
            u.ShowWindow.argtypes = [W.HWND, C.c_int]
            u.GetLayeredWindowAttributes.argtypes = [W.HWND, C.POINTER(W.DWORD), C.POINTER(W.BYTE), C.POINTER(W.DWORD)]
            u.GetLayeredWindowAttributes.restype = W.BOOL
            u.GetPropW.argtypes, u.GetPropW.restype = [W.HWND, W.LPCWSTR], W.HANDLE
            u.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, event_type,
                                          W.DWORD, W.DWORD, W.DWORD]
            u.SetWinEventHook.restype = W.HANDLE
            u.UnhookWinEvent.argtypes = [W.HANDLE]
            u.SetWindowsHookExW.argtypes = [C.c_int, input_type, W.HINSTANCE, W.DWORD]
            u.SetWindowsHookExW.restype = W.HANDLE
            u.CallNextHookEx.argtypes = [W.HANDLE, C.c_int, W.WPARAM, W.LPARAM]
            u.CallNextHookEx.restype = C.c_ssize_t
            u.UnhookWindowsHookEx.argtypes = [W.HANDLE]
            u.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
            u.PeekMessageW.restype = W.BOOL
            u.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
            u.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
            u.DispatchMessageW.restype = C.c_ssize_t
            k.GetModuleHandleW.argtypes = [W.LPCWSTR]
            k.GetModuleHandleW.restype = W.HMODULE

            class ProcessEntry(C.Structure):
                _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                            ("th32ProcessID", W.DWORD), ("th32DefaultHeapID", C.c_size_t),
                            ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                            ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", W.LONG),
                            ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]
            k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
            k.CreateToolhelp32Snapshot.restype = W.HANDLE
            k.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
            k.Process32NextW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
            k.CloseHandle.argtypes = [W.HANDLE]

            def owned_processes():
                handle = k.CreateToolhelp32Snapshot(2, 0)
                if not handle or handle == C.c_void_p(-1).value:
                    raise RuntimeError("process_tree_observation_failed")
                parents = {}
                try:
                    entry = ProcessEntry()
                    entry.dwSize = C.sizeof(entry)
                    if not k.Process32FirstW(handle, C.byref(entry)):
                        raise RuntimeError("process_tree_observation_failed")
                    while True:
                        parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                        if not k.Process32NextW(handle, C.byref(entry)):
                            if C.get_last_error() != 18:
                                raise RuntimeError("process_tree_observation_failed")
                            break
                finally:
                    k.CloseHandle(handle)
                with self._lock:
                    births = {pid: _process_birth(pid) for pid in self._births if pid in parents}
                    live = {pid for pid, birth in births.items()
                            if birth is not None and birth == self._births[pid]}
                    if self.owner_pid not in live:
                        raise RuntimeError("owner_process_identity_unavailable")
                    changed = True
                    while changed:
                        before = len(live)
                        for pid, parent in parents.items():
                            if pid in live or parent not in live:
                                continue
                            birth = _process_birth(pid)
                            if birth is None:
                                continue  # Exited candidate grants no ownership.
                            if birth < births[parent]:
                                self._rejected_parent_edges[(pid, parent)] = {
                                    "pid": pid, "parentPid": parent, "reason": "child-predates-parent"}
                                continue
                            births[pid] = birth
                            live.add(pid)
                        changed = len(live) != before
                    self._owned = live
                    self._births = {pid: births[pid] for pid in live}

            def window_details(hwnd):
                rect, cloak, alpha, alpha_flags = W.RECT(), W.DWORD(), W.BYTE(255), W.DWORD()
                if not u.GetWindowRect(hwnd, C.byref(rect)):
                    self._fail("window_bounds_observation_failed")
                if dwm.DwmGetWindowAttribute(hwnd, 14, C.byref(cloak), C.sizeof(cloak)) < 0:
                    self._fail("window_cloak_observation_failed")
                extended = int(u.GetWindowLongPtrW(hwnd, -20))
                zero = bool(extended & 0x80000 and u.GetLayeredWindowAttributes(hwnd, None,
                    C.byref(alpha), C.byref(alpha_flags)) and alpha_flags.value & 2 and alpha.value == 0)
                return {"rect": [rect.left, rect.top, rect.right, rect.bottom],
                    "extended_style": extended, "cloak": int(cloak.value), "zeroOpacity": zero,
                    "nativeContainment": bool(u.GetPropW(hwnd, "Neyvia.C11.Parked.OriginalProc"))}

            def state():
                windows = {}
                details = {}
                @enum_type
                def each(hwnd, _):
                    if u.IsWindowVisible(hwnd):
                        pid = W.DWORD()
                        if not u.GetWindowThreadProcessId(hwnd, C.byref(pid)):
                            self._fail("window_owner_observation_failed")
                        windows[int(hwnd)] = int(pid.value)
                        if int(pid.value) in self._owned:
                            details[int(hwnd)] = window_details(hwnd)
                    return True
                if not u.EnumDesktopWindows(desktop, each, 0):
                    raise RuntimeError("input_window_enumeration_failed_" + str(C.get_last_error()))
                foreground = u.GetForegroundWindow()
                foreground_pid = W.DWORD()
                if foreground and not u.GetWindowThreadProcessId(foreground, C.byref(foreground_pid)):
                    raise RuntimeError("foreground_owner_observation_failed")
                point = W.POINT()
                # A desktop transition may temporarily have no foreground
                # HWND. It is not an agent activation; hooks still attribute
                # the next foreground owner and all injected input.
                if not u.GetCursorPos(C.byref(point)):
                    raise RuntimeError("input_state_observation_failed")
                ml, mt = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
                return {"visible": windows, "window_details": details,
                        "monitor_bounds": [ml, mt, ml + u.GetSystemMetrics(78), mt + u.GetSystemMetrics(79)],
                        "foreground": int(foreground or 0),
                        "foreground_pid": int(foreground_pid.value),
                        "cursor": [int(point.x), int(point.y)]}

            def record(value):
                self._record_state(value, lambda hwnd: u.ShowWindow(hwnd, 0))

            @event_type
            def on_event(_, event, hwnd, obj, child, tid, at):
                try:
                    if self._baseline is None or not hwnd:
                        return
                    pid = W.DWORD()
                    if not u.GetWindowThreadProcessId(hwnd, C.byref(pid)):
                        # A queued destroy notification may outlive the HWND.
                        return
                    if pid.value not in self._owned and pid.value not in self._known_event_pids:
                        owned_processes()
                        self._known_event_pids.add(pid.value)
                    if event == 3:
                        self._record_foreground(int(hwnd or 0), int(pid.value))
                    elif event in (0x8000, 0x8002) and obj == 0 and u.GetAncestor(hwnd, 2) == hwnd and u.IsWindowVisible(hwnd):
                        with self._lock:
                            contained = self._contained_cloak(int(hwnd), int(pid.value), window_details(hwnd))
                        if not contained:
                            self._record_visible_event(int(hwnd), int(pid.value), lambda window: u.ShowWindow(window, 0))
                except Exception:
                    self._fail("input_event_observation_failed")

            @input_type
            def on_mouse(code, message, data):
                try:
                    if code >= 0:
                        self._record_input("mouse", C.cast(data, C.POINTER(MouseInput)).contents.flags)
                except Exception:
                    self._fail("mouse_event_observation_failed")
                return u.CallNextHookEx(None, code, message, data)

            @input_type
            def on_keyboard(code, message, data):
                try:
                    if code >= 0:
                        self._record_input("keyboard", C.cast(data, C.POINTER(KeyboardInput)).contents.flags)
                except Exception:
                    self._fail("keyboard_event_observation_failed")
                return u.CallNextHookEx(None, code, message, data)

            for event in (3, 0x8000, 0x8002):
                hook = u.SetWinEventHook(event, event, None, on_event, 0, 0, 0)
                if not hook:
                    raise RuntimeError("input_event_hook_failed")
                hooks.append(hook)
            mouse_hook = u.SetWindowsHookExW(14, on_mouse, k.GetModuleHandleW(None), 0)
            if not mouse_hook:
                raise RuntimeError("mouse_hook_failed_" + str(C.get_last_error()))
            keyboard_hook = u.SetWindowsHookExW(13, on_keyboard, k.GetModuleHandleW(None), 0)
            if not keyboard_hook:
                raise RuntimeError("keyboard_hook_failed_" + str(C.get_last_error()))
            self._hooks_ready = True
            owned_processes()
            record(state())
            self._known_event_pids.update(self._baseline["visible"].values())
            self._ready.set()
            message = W.MSG()
            tree_at = time.monotonic()
            while True:
                self._wake.clear()
                # A continuous WinEvent stream must not starve visibility
                # samples or queued proof barriers. Hooks stay enabled and
                # remaining notifications stay queued for the next pass.
                for _ in range(64):
                    if not u.PeekMessageW(C.byref(message), None, 0, 0, 1):break
                    u.TranslateMessage(C.byref(message))
                    u.DispatchMessageW(C.byref(message))
                    if self._stop.is_set():
                        break
                if self._tree_dirty.is_set() or time.monotonic() - tree_at >= .25:
                    owned_processes()
                    tree_at = time.monotonic()
                    self._tree_dirty.clear()
                record(state())
                self._read_external_log()
                while not self._requests.empty():
                    self._requests.get_nowait().set()
                if self._stop.is_set():
                    break
                # A proof barrier wakes the observer immediately; normal idle
                # polling still bounds window discovery without busy-spinning.
                self._wake.wait(self.poll_ms / 1000)
            # The close receipt covers final state, not only the last loop tick.
            for _ in range(1024):
                if not u.PeekMessageW(C.byref(message), None, 0, 0, 1):
                    break
                u.TranslateMessage(C.byref(message))
                u.DispatchMessageW(C.byref(message))
            owned_processes()
            record(state())
            self._read_external_log()
            if self._log_remainder.strip():
                # A concurrent writer may still be finishing an unrelated entry.
                self._external_unattributed_entries += 1
        except Exception as exc:
            reason = str(exc) if isinstance(exc, RuntimeError) else "input_guard_internal_error"
            self._fail(reason)
        finally:
            self._ready.set()
            while not self._requests.empty():
                self._requests.get_nowait().set()
            if desktop:
                for hook in hooks:
                    u.UnhookWinEvent(hook)
                if mouse_hook:
                    u.UnhookWindowsHookEx(mouse_hook)
                if keyboard_hook:
                    u.UnhookWindowsHookEx(keyboard_hook)
                u.CloseDesktop(desktop)
