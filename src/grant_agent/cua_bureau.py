"""Hidden-first Windows virtual desktop fallback through maintained winvd.

Windows virtual desktops group existing HWNDs; they are not launch sandboxes.
The existing native CBT hook contains our job before CreateProcess resumes.
Only then may an owned, still-hidden HWND be assigned to a dedicated Bureau.
Installed application binaries may start suspended inside the owned job. Only
new hidden HWNDs with an existing movable Shell view can be admitted and moved.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
import queue
import threading

from .cua_desktop import DesktopIsolationError
from .cua_parked import ParkedContainment


RELEASE = "2024-12-16-windows11"
DLL_SHA256 = "8740c572a1c000e3b87ffeb1e4c397eae9af3bd4a2abdc3bcffacab4493f8ff5"
SOURCE_URL = "https://github.com/Ciantic/VirtualDesktopAccessor"
BROKER_FRONTIER = (
    "Bureau requires a new HWND, proven launch ownership and inactive membership; "
    "existing user windows and uncontained alias activation are excluded."
)


class _GUID(C.Structure):
    _fields_ = [("data1", W.DWORD), ("data2", W.WORD), ("data3", W.WORD), ("data4", W.BYTE * 8)]

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


class _DesktopCalls:
    """Keep maintained winvd's COM/cache state on one live MTA apartment."""
    def __init__(self,path,signatures):
        self.requests=queue.Queue();self.ready=threading.Event();self.error=None
        self.functions={};self.stopped=False
        self.thread=threading.Thread(target=self._run,args=(path,signatures),name='cua-bureau-com',daemon=True)
        self.thread.start()
        if not self.ready.wait(3) or self.error:
            raise DesktopIsolationError('Bureau COM lane unavailable: '+str(self.error))

    def _run(self,path,signatures):
        ole=C.OleDLL('ole32');user=C.WinDLL('user32')
        initialized=False;desktop=None
        try:
            user.OpenDesktopW.argtypes=[W.LPCWSTR,W.DWORD,W.BOOL,W.DWORD];user.OpenDesktopW.restype=W.HANDLE
            user.SetThreadDesktop.argtypes=[W.HANDLE];user.CloseDesktop.argtypes=[W.HANDLE]
            desktop=user.OpenDesktopW('Default',0,False,255)
            if not desktop or not user.SetThreadDesktop(desktop):
                raise DesktopIsolationError('Bureau COM lane must bind Explorer Default before COM')
            initialized=ole.CoInitializeEx(None,0)>=0
            if not initialized:raise DesktopIsolationError('Bureau MTA initialization failed')
            self.library=C.CDLL(str(path))
            for name,(args,result) in signatures.items():
                method=getattr(self.library,name);method.argtypes,method.restype=args,result
                self.functions[name]=method
            self.ready.set()
            while True:
                request=self.requests.get()
                if request is None:break
                name,args,done,result=request
                try:result.append(self.functions[name](*args))
                except BaseException as exc:result.append(exc)
                finally:done.set()
        except BaseException as exc:self.error=str(exc)
        finally:
            self.ready.set()
            if initialized:ole.CoUninitialize()
            if desktop:user.CloseDesktop(desktop)

    def __getattr__(self,name):
        if name not in self.functions:raise AttributeError(name)
        def call(*args):
            if self.stopped or not self.thread.is_alive():raise DesktopIsolationError('Bureau COM lane closed')
            done=threading.Event();result=[]
            self.requests.put((name,args,done,result))
            if not done.wait(3):raise DesktopIsolationError('Bureau COM call deadline; inspect before retry')
            if isinstance(result[0],BaseException):raise result[0]
            return result[0]
        return call

    def close(self):
        if self.stopped:return
        self.stopped=True;self.requests.put(None);self.thread.join(3)
        if self.thread.is_alive():raise DesktopIsolationError('Bureau COM lane close deadline')


class VirtualDesktopLibrary:
    """Only allowlisted exports; the desktop-switch export is never bound."""
    def __init__(self, path, profile_root):
        self.path = Path(path).resolve()
        if not self.path.is_relative_to(Path(profile_root).resolve()) or not self.path.is_file():
            raise DesktopIsolationError("VirtualDesktopAccessor must be a task-local DLL")
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != DLL_SHA256:
            raise DesktopIsolationError("VirtualDesktopAccessor DLL differs from the pinned release")
        if not (self.path.parent / "LICENSE.txt").is_file():
            raise DesktopIsolationError("VirtualDesktopAccessor MIT license must accompany the DLL")
        signatures = {
            "GetDesktopCount": ([], C.c_int),
            "GetCurrentDesktopNumber": ([], C.c_int),
            "GetDesktopIdByNumber": ([C.c_int], _GUID),
            "GetDesktopNumberById": ([_GUID], C.c_int),
            "CreateDesktop": ([], C.c_int),
            "RemoveDesktop": ([C.c_int, C.c_int], C.c_int),
            "SetDesktopName": ([C.c_int, C.c_char_p], C.c_int),
            "GetWindowDesktopNumber": ([W.HWND], C.c_int),
            "MoveWindowToDesktopNumber": ([W.HWND, C.c_int], C.c_int),
            "IsPinnedWindow": ([W.HWND], C.c_int),
            "IsPinnedApp": ([W.HWND], C.c_int),
        }
        self.dll = _DesktopCalls(self.path,signatures)
        self.desktop_id = None
        self.initial_current = self.current()
        self.initial_count = self.dll.GetDesktopCount()
        if self.initial_count < 1:
            raise DesktopIsolationError("Virtual desktop enumeration failed on this Windows build")
        self.cleanup = None
        self.last_assignment = None
        self.memberships = {}

    def current(self):
        value = self.dll.GetCurrentDesktopNumber()
        if value < 0:
            raise DesktopIsolationError("Current virtual desktop is unavailable")
        return value

    def create(self):
        if self.desktop_id is not None:
            return self.index()
        number = self.dll.CreateDesktop()
        if number < 0:
            raise DesktopIsolationError("Dedicated Bureau creation failed")
        self.desktop_id = self.dll.GetDesktopIdByNumber(number)
        if not any(bytes(self.desktop_id)):
            raise DesktopIsolationError("Dedicated Bureau identity could not be verified")
        if self.current() == number:
            raise DesktopIsolationError("Dedicated Bureau must not become the current desktop")
        self.dll.SetDesktopName(number, ("Neyvia Agent " + str(self.desktop_id)[:8]).encode())
        return number

    def index(self):
        if self.desktop_id is None:
            raise DesktopIsolationError("Dedicated Bureau is closed")
        number = self.dll.GetDesktopNumberById(self.desktop_id)
        if number < 0:
            raise DesktopIsolationError("Dedicated Bureau was removed outside this session")
        if number == self.current():
            raise DesktopIsolationError("Paul is viewing the agent Bureau; automation paused")
        return number

    def assign(self, hwnd, *, deadline=None):
        number = self.index()
        # Pinned applications are visible across desktops. Never change a
        # user's pin preferences, even when this individual process is ours.
        self.last_assignment = {"hwnd": int(hwnd), "requestedDesktop": number,
                                "windowDesktop": self.dll.GetWindowDesktopNumber(hwnd),
                                "pinnedWindow": self.dll.IsPinnedWindow(hwnd),
                                "pinnedApp": self.dll.IsPinnedApp(hwnd)}
        if self.last_assignment["pinnedWindow"] > 0 or self.last_assignment["pinnedApp"] > 0:
            raise DesktopIsolationError("Pinned window cannot enter the Bureau")
        deadline = deadline or time.monotonic() + 1
        self.last_assignment["refreshViews"] = self.refresh_views()
        while True:
            if self.dll.GetWindowDesktopNumber(hwnd) == number:
                return number
            moved = self.dll.MoveWindowToDesktopNumber(hwnd, number)
            self.last_assignment["moveReturn"] = moved
            if moved >= 0 and self.dll.GetWindowDesktopNumber(hwnd) == number:
                return number
            if time.monotonic() >= deadline:
                raise DesktopIsolationError("Hidden HWND has no movable shell application view; still contained")
            time.sleep(.02)

    @staticmethod
    def refresh_views():
        """Ask the existing Shell collection to discover contained new HWNDs.

        This is the maintained winvd collection's read/discovery operation;
        it neither activates an application nor selects a desktop.
        """
        ole = C.OleDLL("ole32")
        initialized = ole.CoInitializeEx(None, 0) >= 0
        provider, collection = C.c_void_p(), C.c_void_p()
        def guid(value): return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
        def method(pointer, slot, result, *arguments):
            table=C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p))).contents
            return C.WINFUNCTYPE(result,C.c_void_p,*arguments)(table[slot])
        try:
            cls=guid("c2f03a33-21f5-47fa-b4bb-156362a2f239")
            iid=guid("6d5140c1-7436-11ce-8034-00aa006009fa")
            ole.CoCreateInstance.argtypes=[C.POINTER(_GUID),C.c_void_p,W.DWORD,C.POINTER(_GUID),C.POINTER(C.c_void_p)]
            ole.CoCreateInstance.restype=C.c_long
            result=ole.CoCreateInstance(C.byref(cls),None,4,C.byref(iid),C.byref(provider))
            if result<0: return {"query":result}
            view_iid=guid("1841c6d7-4f9d-42c0-af41-8747538f10e5")
            result=method(provider,3,C.c_long,C.POINTER(_GUID),C.POINTER(_GUID),C.POINTER(C.c_void_p))(
                provider,C.byref(view_iid),C.byref(view_iid),C.byref(collection))
            if result<0: return {"query":result}
            return {"query":result,"refresh":method(collection,11,C.c_long)(collection)}
        finally:
            for pointer in (collection,provider):
                if pointer.value: method(pointer,2,W.ULONG)(pointer)
            if initialized: ole.CoUninitialize()

    def remove(self, user):
        if self.desktop_id is None:
            return self.cleanup
        number = self.dll.GetDesktopNumberById(self.desktop_id)
        if number < 0:
            self.cleanup = {"removed": True, "reason": "already removed externally"}
            self.desktop_id = None
            return self.cleanup
        current = self.current()
        residents = []
        visit_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        @visit_type
        def visit(hwnd, unused):
            if self.dll.GetWindowDesktopNumber(hwnd) == number:
                residents.append(int(hwnd))
            return True
        user.EnumWindows.argtypes, user.EnumWindows.restype = [visit_type, W.LPARAM], W.BOOL
        enumerated = bool(user.EnumWindows(visit, 0))
        if not enumerated or number == current or residents:
            self.cleanup = {"removed": False, "reason": "desktop current, inhabited, or unverifiable",
                            "residentCount": len(residents), "desktopId": str(self.desktop_id)}
        else:
            removed = self.dll.RemoveDesktop(number, current) >= 0
            self.cleanup = {"removed": removed, "desktopId": str(self.desktop_id)}
            if removed:
                self.desktop_id = None
        return self.cleanup

    def status(self):
        return {"library": SOURCE_URL, "release": RELEASE, "license": "MIT", "sha256": DLL_SHA256,
                "upstreamTestedBuild": "26200.8117", "runtimeBuild": sys.getwindowsversion().build,
                "desktopId": str(self.desktop_id) if self.desktop_id else None,
                "currentDesktopNumber": self.current(), "desktopCount": self.dll.GetDesktopCount(),
                "switchExportBound": False, "brokerLaunchImplemented": True,
                "brokerMembershipProven": bool(self.memberships),
                "provenMemberships":dict(self.memberships),
                "brokerFrontier": BROKER_FRONTIER, "cleanup": self.cleanup}


class BureauDesktop(ParkedContainment):
    """The parked hook remains authoritative, including after Bureau placement."""
    def __init__(self, desktop, guard, dll_path, *, vda_path=None, registration_probe=True):
        # Diagnostics stay on. Offscreen registration has focus vetoes; pixel
        # placement is released only after inactive membership + Shell cloak.
        self.registration_probe = True
        guard.observe_shell_desktop()
        self._windows_before = set()
        self._explorer_tokens = {}
        self._fixture_tokens = {}
        self.library = VirtualDesktopLibrary(vda_path or desktop.profile_root / "c11-bureau" /
                                             "VirtualDesktopAccessor.dll", desktop.profile_root)
        super().__init__(desktop, guard, dll_path, shell_desktop=True)
        try:
            visit_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
            @visit_type
            def remember(hwnd, unused):
                self._windows_before.add(int(hwnd))
                return True
            desktop.u.EnumDesktopWindows.argtypes = [W.HANDLE, visit_type, W.LPARAM]
            desktop.u.EnumDesktopWindows.restype = W.BOOL
            if not desktop.u.EnumDesktopWindows(self.handle, remember, 0):
                raise DesktopIsolationError("Cannot establish before-launch HWND ownership")
            self.dll.SetBureauMode.argtypes, self.dll.SetBureauMode.restype = [W.BOOL], W.BOOL
            if not self.dll.SetBureauMode(True):
                raise DesktopIsolationError("Bureau mode must be configured before any owned window exists")
            self.library.create()
        except BaseException:
            self.close()
            raise

    def verify_window(self, hwnd):
        user = self.desktop.u
        if int(hwnd) in self._windows_before:
            raise DesktopIsolationError("Bureau cannot adopt a preexisting HWND")
        pid = W.DWORD()
        user.GetWindowThreadProcessId(int(hwnd), C.byref(pid))
        if not self.desktop.owns_pid(pid.value):
            raise DesktopIsolationError("Bureau window is outside the owned job")
        if int(hwnd) in self.receipts:
            if self.library.dll.GetWindowDesktopNumber(hwnd) != self.library.index():
                raise DesktopIsolationError("Bureau membership changed; automation paused")
            return self.receipts[int(hwnd)]
        explorer_token = self._explorer_tokens.get(pid.value)
        if explorer_token:
            title = C.create_unicode_buffer(1024)
            user.GetWindowTextW(int(hwnd), title, len(title))
            if explorer_token not in title.value:
                raise DesktopIsolationError("New Explorer HWND has not exposed its disposable folder token; no move admitted")
        user.GetWindowLongPtrW.argtypes, user.GetWindowLongPtrW.restype = [W.HWND, C.c_int], C.c_ssize_t
        user.GetPropW.argtypes, user.GetPropW.restype = [W.HWND, W.LPCWSTR], W.HANDLE
        user.GetWindowRect.argtypes, user.GetWindowRect.restype = [W.HWND, C.POINTER(W.RECT)], W.BOOL
        extended = int(user.GetWindowLongPtrW(int(hwnd), -20))
        bounds = W.RECT()
        known = int(hwnd) in self.receipts
        if (not user.GetWindowRect(int(hwnd), C.byref(bounds)) or (user.IsWindowVisible(int(hwnd)) and not known)
                or not user.GetPropW(int(hwnd), "Neyvia.C11.Parked.OriginalProc")
                or extended & 0x08040000 != 0x08040000 or extended & 0x80
                or bounds.left != -32000 or bounds.top != -32000):
            raise DesktopIsolationError("Bureau window failed hidden previsibility verification")
        receipt = {"hwnd": int(hwnd), "pid": int(pid.value), "hidden": True, "previsibility": True,
                   "offscreen": True, "noactivate": True, "toolwindow": False,
                   "newHwnd": True, "newJobOwnedProcess": True,
                   "route": "agent-bureau", "cloaked": True, "taskbarRemovalPending": True}
        # HWND creation precedes some apps' lengthy initialization. Spend no
        # move lease until their UI thread answers a harmless message.
        user.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)]
        user.SendMessageTimeoutW.restype=W.LPARAM
        ready_until=time.monotonic()+8
        response=C.c_size_t()
        while not user.SendMessageTimeoutW(hwnd,0,0,0,2,100,C.byref(response)):
            if time.monotonic()>=ready_until:
                raise DesktopIsolationError('Hidden window UI thread is not ready; no move lease used')
            time.sleep(.05)
        lease = self.guard.begin_bureau_move(hwnd, pid.value)
        receipt.update(moveLease=lease, registrationUntil=lease['until'], offscreenRegistration=True)
        self.guard.register_parked_window(hwnd, pid.value, receipt)
        for name in ('RegisterPrevisibilityBureauWindow', 'AdmitBureauWindow'):
            method=getattr(self.dll,name)
            method.argtypes,method.restype=[W.HWND],W.BOOL
        deadline=time.monotonic()+2.5
        try:
            if not self.dll.RegisterPrevisibilityBureauWindow(hwnd):
                raise DesktopIsolationError("Native invisible Shell registration refused")
            receipt['registrationSafety']=self._visibility_state(hwnd)
            safety=receipt['registrationSafety']
            if not safety['zeroOpacity'] and not (safety['bounds'][:2]==[-32000,-32000]
                    and safety['bounds'][2]<-16000 and safety['bounds'][3]<-16000):
                raise DesktopIsolationError("Previsibility pixel containment readback failed")
            number=self.library.assign(hwnd,deadline=deadline)
            receipt.update(virtualDesktopNumber=number,virtualDesktopId=str(self.library.desktop_id),membershipVerified=True)
            # Do not relax alpha until Shell independently cloaks this HWND.
            while time.monotonic()<deadline and not self._visibility_state(hwnd)['cloak'] & 2:
                time.sleep(.01)
            if not self._visibility_state(hwnd)['cloak'] & 2:
                raise DesktopIsolationError("Moved HWND lacks inactive Shell cloak; paint stays blocked")
            # DeleteTab destroys the Shell view and therefore the membership
            # we just established. Keep its inactive-desktop Shell identity.
            receipt.update(delete_tab_ok=False,shellCloakVerified=True,
                           taskbarPolicy='inactive-bureau-shell-view-retained')
            receipt['taskbarRemovalPending']=False
            self.guard.register_parked_window(hwnd,pid.value,receipt)
            admit_until=time.monotonic()+5
            admitted=self.dll.AdmitBureauWindow(hwnd)
            while not admitted and time.monotonic()<admit_until:
                if self.library.dll.GetWindowDesktopNumber(hwnd)!=number or not self._visibility_state(hwnd)['cloak']&2:
                    break
                time.sleep(.05)
                admitted=self.dll.AdmitBureauWindow(hwnd)
            if not admitted:
                raise DesktopIsolationError("Native membership paint admission refused")
            receipt.update(hidden=False,pixelsReleasedAfterMembership=True,finalVisibility=self._visibility_state(hwnd))
            self.library.memberships[int(hwnd)]={'desktopId':str(self.library.desktop_id),'desktopNumber':number}
            self.receipts[int(hwnd)]=receipt
            self.guard.register_parked_window(hwnd,pid.value,receipt)
            return receipt
        except BaseException:
            user.ShowWindow.argtypes=[W.HWND,C.c_int]
            user.ShowWindow(hwnd,0)
            self.last_registration_failure={'receipt':receipt,'state':self._visibility_state(hwnd)}
            raise

    def _visibility_state(self,hwnd):
        user=self.desktop.u
        rectangle=W.RECT();user.GetWindowRect(hwnd,C.byref(rectangle))
        alpha,flags,cloak=W.BYTE(255),W.DWORD(),W.DWORD()
        user.GetLayeredWindowAttributes.argtypes=[W.HWND,C.POINTER(W.DWORD),C.POINTER(W.BYTE),C.POINTER(W.DWORD)]
        layered=user.GetLayeredWindowAttributes(hwnd,None,C.byref(alpha),C.byref(flags))
        dwm=C.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD]
        if dwm.DwmGetWindowAttribute(hwnd,14,C.byref(cloak),C.sizeof(cloak))<0:
            raise DesktopIsolationError('Bureau cloak observation unavailable')
        return {'visibleStyle':bool(user.IsWindowVisible(hwnd)),'zeroOpacity':bool(layered and flags.value&2 and alpha.value==0),
                'bounds':[rectangle.left,rectangle.top,rectangle.right,rectangle.bottom],'cloak':int(cloak.value),
                'desktopNumber':self.library.dll.GetWindowDesktopNumber(hwnd)}

    def windows(self):
        rows=[]
        user=self.desktop.u
        visit_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        @visit_type
        def visit(hwnd,unused):
            pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid))
            if not self.desktop.owns_pid(pid.value):return True
            title,cls=C.create_unicode_buffer(1024),C.create_unicode_buffer(256)
            user.GetWindowTextW(hwnd,title,len(title));user.GetClassNameW(hwnd,cls,len(cls))
            bounds=W.RECT();user.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)];user.GetWindowRect(hwnd,C.byref(bounds))
            token=self._fixture_tokens.get(pid.value)
            if (not title.value or bounds.right-bounds.left<250 or bounds.bottom-bounds.top<150
                    or cls.value in {'IME','MSCTFIME UI'} or (token and token not in title.value)):
                return True
            rows.append({'hwnd':int(hwnd),'windowId':str(int(hwnd)),'pid':pid.value,
                         'title':title.value,'className':cls.value,'visible':bool(user.IsWindowVisible(hwnd)),
                         'desktop':self.input_name,'isolation':'agent-bureau'})
            return True
        user.EnumDesktopWindows.argtypes=[W.HANDLE,visit_type,W.LPARAM]
        if not user.EnumDesktopWindows(self.handle,visit,0):raise DesktopIsolationError('Bureau window enumeration failed')
        for row in rows:
            receipt = self.verify_window(row["hwnd"])
            row.update(isolation="agent-bureau", virtualDesktopId=receipt["virtualDesktopId"],
                       virtualDesktopNumber=receipt["virtualDesktopNumber"])
        return rows

    def counters(self):
        state=[]
        if hasattr(self.dll,'BureauRegistrationState'):
            self.dll.BureauRegistrationState.argtypes=[C.c_int]
            self.dll.BureauRegistrationState.restype=W.LONG
            state=[int(self.dll.BureauRegistrationState(i)) for i in range(8)]
        return {**super().counters(), "bureau": self.library.status(), 'registrationState':state}

    def before_resume(self, process):
        super().before_resume(process)
        if Path(process.argv[0]).name.casefold() in {'notepad.exe','mspaint.exe'}:
            import re
            tokens=[m.group() for arg in process.argv[1:] for m in re.finditer(r'[a-f0-9]{32}',str(arg))]
            if tokens:self._fixture_tokens[process.pid]=tokens[-1]
        if Path(process.argv[0]).name.casefold() == 'explorer.exe':
            folder = next(str(arg)[3:] for arg in process.argv[1:] if str(arg).casefold().startswith('/n,'))
            self._explorer_tokens[process.pid] = Path(folder).name

    def close(self):
        if hasattr(self, "thread"):
            super().close()
        try:self.library.remove(self.desktop.u)
        finally:self.library.dll.close()
