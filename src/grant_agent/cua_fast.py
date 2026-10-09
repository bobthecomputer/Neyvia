"""Deadline-bounded native CUA. COM objects never leave their owning MTA lane.

One persistent UIA client, one bounded MSAA lane, and Win32 discovery/delivery.
Observation timeouts are safe to degrade; a dispatched mutation is never replayed
on another route because the original provider may complete after the deadline.
"""
from __future__ import annotations

import copy
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path
import queue
import re
import threading
import time

SECRET_FIELD=re.compile(r"\b(password|passphrase|credential|secret|api.?key|access.?token|mot de passe)\b",re.I)


def protected(row):
    return bool(row.get("isPassword") or (row.get("role") in {"Edit","Document"} and
        SECRET_FIELD.search(str(row.get("name", ""))+" "+str(row.get("automationId", "")))))


class UndispatchedTimeout(TimeoutError):
    """The lane did not accept this call; a different action route is safe."""


class DeadlineLane:
    """At most one outstanding call; hung providers cannot grow threads/queues."""
    def __init__(self, factory, name, desktop=None):
        self.jobs = queue.Queue(maxsize=1)
        self.busy = threading.Lock()
        self.ready = threading.Event()
        self.error = None
        self.closed = False
        self.desktop = desktop
        self.thread = threading.Thread(target=self._run, args=(factory,), name=name, daemon=True)
        self.thread.start()

    def _run(self, factory):
        try:
            if self.desktop:
                self.desktop.bind_thread()
            C.OleDLL("ole32").CoInitializeEx(None, 0)
            backend = factory()
            owner = getattr(self.desktop, "desktop", self.desktop)
            if owner and hasattr(backend, "win"):
                backend.win.fixture_scope = owner.disposable_target
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
            C.OleDLL("ole32").CoUninitialize()
            if self.desktop:
                self.desktop.restore_thread()
            return
        self.ready.set()
        while not self.closed:
            item = self.jobs.get()
            if item is None:
                break
            method, args, deadline, completed, box = item
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Expired before dispatch")
                backend.deadline = deadline
                box.append(getattr(backend, method)(*args))
            except Exception as exc:
                box.append(exc)
            finally:
                completed.set()
                self.busy.release()
        try:
            backend.close()
            # COM references and callback objects belong to this initialized
            # apartment. Release them before CoUninitialize, not later during
            # Python's interpreter-wide teardown on an unrelated thread.
            del backend
        finally:
            C.OleDLL("ole32").CoUninitialize()
            if self.desktop:
                self.desktop.restore_thread()

    def call(self, method, *args, budget=.080):
        deadline = time.monotonic() + budget
        if self.closed or not self.ready.wait(max(0, deadline - time.monotonic())):
            raise UndispatchedTimeout("MTA client initializing")
        if self.error:
            raise RuntimeError(self.error)
        if not self.busy.acquire(blocking=False):
            raise UndispatchedTimeout("MTA provider still busy")
        completed, box = threading.Event(), []
        self.jobs.put_nowait((method, args, deadline, completed, box))
        if not completed.wait(max(0, deadline - time.monotonic())):
            raise TimeoutError("MTA provider deadline")
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]

    def close(self):
        self.closed = True
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not threading.current_thread():
            self.thread.join(.2)


class Win32:
    def __init__(self):
        self.u = C.WinDLL("user32", use_last_error=True)
        self.k = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "IsWindow": ([W.HWND], W.BOOL), "IsWindowVisible": ([W.HWND], W.BOOL),
            "IsHungAppWindow": ([W.HWND], W.BOOL), "IsIconic": ([W.HWND], W.BOOL),
            "IsChild": ([W.HWND, W.HWND], W.BOOL),
            "IsWindowEnabled": ([W.HWND], W.BOOL),
            "GetForegroundWindow": ([], W.HWND),
            "GetWindowTextW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            "GetClassNameW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            "GetWindowRect": ([W.HWND, C.POINTER(W.RECT)], W.BOOL),
            "PostMessageW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            "SendMessageTimeoutW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)], W.LPARAM),
            "GetWindowLongW": ([W.HWND, C.c_int], C.c_long),
            "ScreenToClient": ([W.HWND, C.POINTER(W.POINT)], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name); fn.argtypes = args; fn.restype = result
        self.enum_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        for name in ("EnumWindows", "EnumChildWindows"):
            fn = getattr(self.u, name)
            fn.argtypes = ([self.enum_type, W.LPARAM] if name == "EnumWindows" else [W.HWND, self.enum_type, W.LPARAM])
            fn.restype = W.BOOL
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
        self.identities = {}
        self.field_values = {}

    def last_input_tick(self):
        class Input(C.Structure):
            _fields_ = [("cbSize",W.UINT),("dwTime",W.DWORD)]
        item=Input(); item.cbSize=C.sizeof(item)
        if not self.u.GetLastInputInfo(C.byref(item)): raise ValueError("input_observation_unavailable")
        return item.dwTime

    def dispatch_guard(self,args):
        if args.get("_lastInputTick") is not None and self.last_input_tick()!=args["_lastInputTick"]:
            raise ValueError("host_takeover")

    def typing_guard(self,h):
        class Gui(C.Structure):
            _fields_=[("size",W.DWORD),("flags",W.DWORD),("active",W.HWND),("focus",W.HWND),
                ("capture",W.HWND),("menu",W.HWND),("move",W.HWND),("caret",W.HWND),("rect",W.RECT)]
        pid=W.DWORD();thread=self.u.GetWindowThreadProcessId(h,C.byref(pid))
        info=Gui();info.size=C.sizeof(info)
        self.u.GetGUIThreadInfo.argtypes=[W.DWORD,C.POINTER(Gui)]
        if not self.u.GetGUIThreadInfo(thread,C.byref(info)):
            if self.disposable(h): return
            raise ValueError("protection_unknown")
        focus=info.focus
        if focus and (focus==h or self.u.IsChild(h,focus)):
            if not hasattr(self,"field_metadata"):raise ValueError("protection_unknown")
            try: metadata=self.field_metadata(focus)
            except Exception:
                if self.disposable(h): return
                raise ValueError("protection_unknown")
            if metadata["isPassword"]:raise ValueError("protected_field")
            if metadata["role"] not in {42,15} and not self.disposable(h):raise ValueError("protection_unknown")

    def disposable(self, h):
        root = self.u.GetAncestor(int(h), 2)
        return bool(root and getattr(self, "fixture_scope", lambda unused: None)(int(root)))

    def foreground_action(self,h,row,action,args,status):
        """Last route, only for an explicit owner grant; restore in finally."""
        if not args.get("allowForeground"): raise NotImplementedError("Foreground fallback requires an owner grant")
        self.valid(h);self.dispatch_guard(args)
        previous=self.u.GetForegroundWindow()
        if not previous: raise ValueError("interactive_desktop_unavailable")
        cursor=W.POINT()
        if not self.u.GetCursorPos(C.byref(cursor)): raise ValueError("interactive_desktop_unavailable")
        # No AttachThreadInput or desktop switch: normal Windows focus policy
        # remains in force and denial is a concrete failed route.
        self.u.SetForegroundWindow.argtypes=[W.HWND]
        if not self.u.SetForegroundWindow(h) or self.u.GetForegroundWindow()!=h:
            raise ValueError("foreground_activation_denied")
        class Keyboard(C.Structure):
            _fields_=[("vk",W.WORD),("scan",W.WORD),("flags",W.DWORD),("time",W.DWORD),("extra",C.c_size_t)]
        class Mouse(C.Structure):
            _fields_=[("dx",W.LONG),("dy",W.LONG),("data",W.DWORD),("flags",W.DWORD),("time",W.DWORD),("extra",C.c_size_t)]
        class Payload(C.Union): _fields_=[("keyboard",Keyboard),("mouse",Mouse)]
        class Input(C.Structure): _fields_=[("type",W.DWORD),("payload",Payload)]
        self.u.SendInput.argtypes=[W.UINT,C.POINTER(Input),C.c_int];self.u.SendInput.restype=W.UINT
        items=[]
        def key(vk,up=False,scan=0,unicode=False):
            item=Input();item.type=1;item.payload.keyboard=Keyboard(vk,scan,(2 if up else 0)|(4 if unicode else 0),0,0);items.append(item)
        try:
            if row.get("isPassword"): raise ValueError("protected_field")
            if action in {"key","hotkey","text","value","valueAppend"}:self.typing_guard(h)
            if action in {"key","hotkey"}:
                names={"CTRL":17,"CONTROL":17,"ALT":18,"SHIFT":16,"WIN":91,"ENTER":13,"RETURN":13,"ESC":27,"ESCAPE":27,"TAB":9,"SPACE":32,"F1":112,"F5":116,"HOME":36,"END":35,"UP":38,"DOWN":40,"LEFT":37,"RIGHT":39}
                values=[]
                for part in str(args.get("key","")).upper().split("+"):
                    vk=names.get(part,ord(part) if len(part)==1 else 0)
                    if not vk: raise ValueError("Unsupported key")
                    values.append(vk)
                for vk in values: key(vk)
                for vk in reversed(values): key(vk,True)
            elif action in {"text","value","valueAppend"}:
                if row.get("role") not in {"Edit","Document"}: raise ValueError("No protected-field proof for focused text target")
                b=row["bounds"]
                if b["width"]<=0 or b["height"]<=0: raise ValueError("No verified target bounds")
                self.u.SetCursorPos(int(b["x"]+b["width"]/2),int(b["y"]+b["height"]/2))
                for flags in (2,4):
                    item=Input();item.type=0;item.payload.mouse=Mouse(0,0,0,flags,0,0);items.append(item)
                if action=="value":
                    key(17);key(65);key(65,True);key(17,True)
                raw=str(args.get("text",args.get("value",""))).encode("utf-16-le")
                for n in range(0,len(raw),2):
                    code=int.from_bytes(raw[n:n+2],"little");key(0,scan=code,unicode=True);key(0,True,code,True)
            elif action in {"click","pointClick"}:
                b=row["bounds"]
                x=int(args.get("x") if args.get("x") is not None else b["x"]+b["width"]/2)
                y=int(args.get("y") if args.get("y") is not None else b["y"]+b["height"]/2)
                if not (b["x"]<=x<b["x"]+b["width"] and b["y"]<=y<b["y"]+b["height"]): raise ValueError("invalid_coordinates")
                self.u.SetCursorPos(x,y)
                for flags in (2,4):
                    item=Input();item.type=0;item.payload.mouse=Mouse(0,0,0,flags,0,0);items.append(item)
            else: raise NotImplementedError("No SendInput route")
            self.dispatch_guard(args)
            if self.u.GetForegroundWindow()!=h: raise ValueError("host_takeover")
            array=(Input*len(items))(*items)
            delivered=int(self.u.SendInput(len(items),array,C.sizeof(Input)))
            if delivered!=len(items): raise TimeoutError("SendInput delivery partial; inspect before retry")
            return {"mechanism":"SendInput.focusRestore","effect":"unverifiable","delivery":"foreground",
                    "deliveredInputs":delivered}
        finally:
            # Do not take focus away from a new user-selected app.
            physical=status().get("inputGeneration")
            if physical==args.get("_physicalGeneration"):
                if self.u.GetForegroundWindow()==h: self.u.SetForegroundWindow(previous)
                self.u.SetCursorPos(cursor.x,cursor.y)

    def valid(self, h):
        if not h or not self.u.IsWindow(h):
            raise ValueError("window_target_not_found")
        if self.u.IsHungAppWindow(h):
            raise ValueError("target_hung; no input dispatched")
        return h

    def available(self, root, child):
        if self.u.IsWindowVisible(child):
            return True
        if not getattr(self, "contained_hidden", False):
            return False
        # Only the launcher-hidden top level is exempt; hidden controls and
        # inactive pages below it still cannot receive native messages.
        current = child
        self.u.GetParent.argtypes = [W.HWND]
        self.u.GetParent.restype = W.HWND
        while current and current != root:
            if not self.u.GetWindowLongW(current, -16) & 0x10000000:
                return False
            current = self.u.GetParent(current)
        return current == root

    def text(self, h, cls=False):
        b = C.create_unicode_buffer(4096)
        (self.u.GetClassNameW if cls else self.u.GetWindowTextW)(h, b, len(b))
        return b.value

    def message(self, h, msg, wp=0, lp=0, timeout=40):
        result = C.c_size_t()
        if not self.u.SendMessageTimeoutW(h, msg, wp, lp, 0x22, timeout, C.byref(result)):
            raise TimeoutError("Win32 message deadline or invalid target")
        return result.value

    def value(self, h):
        if self.u.GetWindowLongW(h, -16) & 0x20 and "edit" in self.text(h, True).lower():
            raise ValueError("protected_field")
        b = C.create_unicode_buffer(32768)
        self.message(h, 0xD, len(b), C.addressof(b))
        self.field_values[h]=b.value
        return b.value

    def identity(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ValueError("process_identity_unavailable")
        try:
            stamps = [W.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(handle, *(C.byref(x) for x in stamps)):
                raise ValueError("process_identity_unavailable")
            ticks = (stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime
            key = (pid, ticks)
            if key not in self.identities:
                buf = C.create_unicode_buffer(32768); n = W.DWORD(len(buf))
                if not self.k.QueryFullProcessImageNameW(handle, 0, buf, C.byref(n)):
                    raise ValueError("process_identity_unavailable")
                stamp = datetime.fromtimestamp(ticks / 1e7 - 11644473600, timezone.utc).isoformat()
                self.identities[key] = {"exe": buf.value, "processName": Path(buf.value).stem,
                                        "processStartTime": stamp}
            return self.identities[key]
        finally:
            self.k.CloseHandle(handle)

    def metadata(self, h):
        self.valid(h)
        pid, r = W.DWORD(), W.RECT()
        self.u.GetWindowThreadProcessId(h, C.byref(pid)); self.u.GetWindowRect(h, C.byref(r))
        return {"windowId": str(h), "pid": pid.value, "title": self.text(h),
                "className": self.text(h, True), **self.identity(pid.value),
                "bounds": {"x": r.left, "y": r.top, "width": r.right-r.left, "height": r.bottom-r.top},
                "minimized": bool(self.u.IsIconic(h))}

    def windows(self):
        rows = []
        @self.enum_type
        def callback(h, _):
            if self.u.IsWindowVisible(h) and not self.u.IsHungAppWindow(h):
                try:
                    row = self.metadata(h)
                    if row["title"]: rows.append(row)
                except (ValueError, OSError): pass
            return True
        self.u.EnumWindows(callback, 0)
        return rows

    def snapshot(self, h, maximum=256):
        window = self.metadata(h); rows = []; deadline = time.monotonic() + .080
        failures=[]
        def node(child, depth):
            cls = self.text(child, True)
            edit = "edit" in cls.lower()
            password = edit and bool(self.u.GetWindowLongW(child, -16) & 0x20)
            r = W.RECT(); self.u.GetWindowRect(child, C.byref(r))
            row = {"id": "win32:" + str(child), "parentId": None if child == h else "win32:" + str(h),
                "depth": depth, "name": self.text(child) if child == h else "", "role": "Window" if child == h else "Edit" if edit else "Button" if "button" in cls.lower() else "Text" if "static" in cls.lower() else "Pane",
                "className": cls, "nativeWindowHandle": child, "automationId": "", "enabled": bool(self.u.IsWindowEnabled(child)),
                "offscreen": not self.available(h, child), "isPassword": password,
                "patterns": ["value"] if edit and not password else ["invoke"] if "button" in cls.lower() else [],
                "bounds": {"x": r.left, "y": r.top, "width": r.right-r.left, "height": r.bottom-r.top}}
            row["readOnly"]=edit and bool(self.u.GetWindowLongW(child,-16)&0x800)
            # Classic ListBox exposes a focus-free, synchronous scroll route
            # even when the private-desktop UIA provider cannot connect.
            if "listbox" in cls.lower():
                row.update(role="List", patterns=["scroll"] if self.u.GetWindowLongW(child,-16)&0x200000 else [])
                row["scrollTopIndex"]=self.message(child,0x18E)
            if "button" in cls.lower():
                kind=self.u.GetWindowLongW(child,-16)&15
                if kind in {2,3,5,6}:
                    row.update(role="CheckBox",patterns=["toggle"])
                    row["toggleState"]=self.message(child,0xF0)
                elif kind in {4,9}:
                    row.update(role="RadioButton",patterns=["selectionItem"])
                    row["selected"]=bool(self.message(child,0xF0))
                elif kind==11 and hasattr(self,"field_metadata"):
                    try:
                        metadata=self.field_snapshot(child) if hasattr(self,"field_snapshot") else self.field_metadata(child)
                        row["metadataCached"]=bool(metadata.get("cached"))
                        if metadata["role"]==44:row.update(role="CheckBox",patterns=["toggle"],toggleState=metadata["toggleState"])
                        elif metadata["role"]==45:row.update(role="RadioButton",patterns=["selectionItem"],selected=metadata["selected"])
                    except Exception:pass
            if edit and hasattr(self,"field_metadata"):
                try:
                    metadata=self.field_snapshot(child) if hasattr(self,"field_snapshot") else self.field_metadata(child)
                    row.update(name=metadata["name"],isPassword=password or metadata["isPassword"],readOnly=row["readOnly"] or metadata["readOnly"])
                    row["metadataCached"]=bool(metadata.get("cached"))
                except Exception as exc:
                    row.update(isPassword=True,protectionUnknown=True,protectionUnknownReason=str(exc),patterns=[])
            row["isPassword"]=protected(row)
            password=row["isPassword"]
            if password or row["readOnly"]:row["patterns"]=[]
            if child != h and not password and not row["offscreen"] and row["role"] in {"Edit", "Button", "CheckBox", "RadioButton", "Text"}:
                try:
                    # Cached field policy never authorizes reading a new value.
                    # Returning the last observed value avoids leaking a field
                    # renamed to a secret without a provider notification.
                    value = self.field_values.get(child) if edit and row.get("metadataCached") else self.value(child)
                    if edit: row["value"] = value
                    else: row["name"] = value
                except TimeoutError: row["unavailable"] = True
            rows.append(row)
        node(h, 0)
        children = []
        @self.enum_type
        def callback(child, _):
            if len(children) >= maximum or time.monotonic() >= deadline: return False
            # IsHungAppWindow is a top-level admission check. Repeating it for
            # each child and sending WM_GETTEXT to composition bridges turns
            # the fallback itself into a slow provider walk.
            if self.available(h, child): children.append(child)
            return True
        self.u.EnumChildWindows(h, callback, 0)
        # Read cheap native labels/buttons before provider-backed edits. A
        # slow Edit policy must not permanently starve result labels from
        # every fresh bounded observation.
        def priority(child):
            cls = self.text(child, True).casefold()
            if cls=="systreeview32":return -1
            if "listbox" in cls:return 0
            # Owner-drawn buttons need an accessibility provider call, which
            # may consume the entire bounded fallback budget. Resolve ordinary
            # labels, buttons and edits before that optional semantic read.
            if "button" in cls and self.u.GetWindowLongW(child,-16)&15==11:return 3
            return 0 if "static" in cls or "button" in cls else 1 if "edit" in cls else 2 if "tabcontrol" in cls else 3
        children.sort(key=priority)
        for child in children:
            if len(rows) >= maximum or time.monotonic() >= deadline:
                break
            try:node(child, 1)
            except (ValueError,TimeoutError,OSError) as exc:
                failures.append(type(exc).__name__+': '+str(exc))
                continue
            if self.text(child, True)=="SysTreeView32":
                try:item=self.message(child,0x110A,0,0,timeout=20)
                except (ValueError,TimeoutError) as exc:
                    failures.append(type(exc).__name__+': '+str(exc))
                    continue
                pending=[(item,2)] if item else []
                while pending and len(rows)<maximum and time.monotonic()<deadline:
                    item,depth=pending.pop()
                    try: row=self.tree_item(child,item)
                    except (ValueError,TimeoutError) as exc:
                        failures.append(type(exc).__name__+': '+str(exc))
                        break
                    row.update(parentId="win32:"+str(child),depth=depth)
                    rows.append(row)
                    try:
                        sibling=self.message(child,0x110A,1,item,timeout=20)
                        nested=self.message(child,0x110A,4,item,timeout=20)
                    except (ValueError,TimeoutError) as exc:
                        failures.append(type(exc).__name__+': '+str(exc))
                        break
                    if sibling: pending.append((sibling,depth))
                    if nested and depth<8: pending.append((nested,depth+1))
        rows.extend(self.menu_items(h)[:max(0,maximum-len(rows))])
        return {"window": window, "tree": rows, "truncated": bool(failures) or time.monotonic() >= deadline or len(rows) >= maximum,
                "controlReadFailures":failures,
                "source": "Win32", "revision": time.monotonic_ns()}

    def tree_item(self, child, item):
        """Read an actual native tree item through a bounded remote TVITEMW."""
        class Item(C.Structure):
            _fields_=[("mask",W.UINT),("item",W.HANDLE),("state",W.UINT),("stateMask",W.UINT),
                ("text",C.c_void_p),("textMax",C.c_int),("image",C.c_int),("selectedImage",C.c_int),
                ("children",C.c_int),("param",W.LPARAM)]
        pid=W.DWORD();self.u.GetWindowThreadProcessId(child,C.byref(pid))
        signatures={"VirtualAllocEx":([W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD,W.DWORD],C.c_void_p),
            "VirtualFreeEx":([W.HANDLE,C.c_void_p,C.c_size_t,W.DWORD],W.BOOL),
            "WriteProcessMemory":([W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)],W.BOOL),
            "ReadProcessMemory":([W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)],W.BOOL)}
        for name,(types,result) in signatures.items():
            fn=getattr(self.k,name);fn.argtypes=types;fn.restype=result
        process=self.k.OpenProcess(0x1038,False,pid.value)
        if not process: raise ValueError("owned_tree_read_unavailable")
        memory=None
        try:
            memory=self.k.VirtualAllocEx(process,None,2048,0x3000,4)
            if not memory: raise ValueError("owned_tree_buffer_unavailable")
            value=Item();value.mask=0x49;value.item=item;value.stateMask=0x22
            value.text=memory+C.sizeof(Item);value.textMax=512
            count=C.c_size_t()
            if not self.k.WriteProcessMemory(process,memory,C.byref(value),C.sizeof(value),C.byref(count)):
                raise ValueError("owned_tree_request_unavailable")
            if not self.message(child,0x113E,0,memory,timeout=30): raise ValueError("stale_tree_item")
            if not self.k.ReadProcessMemory(process,memory,C.byref(value),C.sizeof(value),C.byref(count)):
                raise ValueError("owned_tree_state_unavailable")
            text=C.create_unicode_buffer(512)
            if not self.k.ReadProcessMemory(process,value.text,text,C.sizeof(text),C.byref(count)):
                raise ValueError("owned_tree_label_unavailable")
            bounds=self.metadata(child)["bounds"]
            return {"id":f"tree:{child}:{item}","name":text.value,"role":"TreeItem",
                "className":"SysTreeView32","nativeWindowHandle":child,"treeHandle":item,
                "enabled":bool(self.u.IsWindowEnabled(child)),"offscreen":not self.available(child,child),
                "isPassword":False,"readOnly":False,"selected":bool(value.state&2),
                "expandState":1 if value.state&0x20 else 0,"expandable":bool(value.children),
                "patterns":["selectionItem"]+(["expandCollapse"] if value.children else []),"bounds":bounds}
        finally:
            if memory:self.k.VirtualFreeEx(process,memory,0,0x8000)
            self.k.CloseHandle(process)

    def menu_items(self, h):
        self.u.GetMenu.argtypes=[W.HWND];self.u.GetMenu.restype=W.HMENU
        self.u.GetSubMenu.argtypes=[W.HMENU,C.c_int];self.u.GetSubMenu.restype=W.HMENU
        self.u.GetMenuItemCount.argtypes=[W.HMENU];self.u.GetMenuItemCount.restype=C.c_int
        self.u.GetMenuItemID.argtypes=[W.HMENU,C.c_int];self.u.GetMenuItemID.restype=W.UINT
        self.u.GetMenuStringW.argtypes=[W.HMENU,W.UINT,W.LPWSTR,C.c_int,W.UINT]
        self.u.GetMenuState.argtypes=[W.HMENU,W.UINT,W.UINT];self.u.GetMenuState.restype=W.UINT
        rows=[]
        def walk(menu,depth):
            for index in range(min(100,max(0,self.u.GetMenuItemCount(menu)))):
                text=C.create_unicode_buffer(256);self.u.GetMenuStringW(menu,index,text,len(text),0x400)
                command=int(self.u.GetMenuItemID(menu,index));state=self.u.GetMenuState(menu,index,0x400)
                if text.value and command not in {0,0xffffffff}:
                    rows.append({"id":f"menu:{h}:{command}","name":text.value.replace('&',''),"role":"MenuItem",
                        "className":self.text(h,True),"nativeWindowHandle":h,"menuCommand":command,
                        "enabled":not bool(state&3),"offscreen":False,"isPassword":False,
                        "patterns":["invoke"],"depth":depth,"parentId":"win32:"+str(h),"bounds":self.metadata(h)["bounds"]})
                submenu=self.u.GetSubMenu(menu,index)
                if submenu and depth<4:walk(submenu,depth+1)
        menu=self.u.GetMenu(h)
        if menu:walk(menu,1)
        return rows

    def capture(self,h):
        import base64
        import io
        from PIL import Image
        self.valid(h)
        if self.u.IsIconic(h):raise ValueError("Minimized window cannot be captured")
        bounds=self.metadata(h)["bounds"];width,height=bounds["width"],bounds["height"]
        if not (0<width<=16384 and 0<height<=16384 and width*height<=40000000):raise ValueError("Capture dimensions invalid")
        gdi=C.WinDLL("gdi32",use_last_error=True)
        self.u.GetDC.argtypes=[W.HWND];self.u.GetDC.restype=W.HDC
        self.u.ReleaseDC.argtypes=[W.HWND,W.HDC]
        self.u.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT];self.u.PrintWindow.restype=W.BOOL
        for name,args,result in (
            ("CreateCompatibleDC",[W.HDC],W.HDC),("CreateCompatibleBitmap",[W.HDC,C.c_int,C.c_int],W.HBITMAP),
            ("SelectObject",[W.HDC,W.HANDLE],W.HANDLE),("DeleteObject",[W.HANDLE],W.BOOL),("DeleteDC",[W.HDC],W.BOOL)):
            fn=getattr(gdi,name);fn.argtypes=args;fn.restype=result
        class Header(C.Structure):
            _fields_=[("size",W.DWORD),("width",W.LONG),("height",W.LONG),("planes",W.WORD),("bits",W.WORD),
                ("compression",W.DWORD),("imageSize",W.DWORD),("x",W.LONG),("y",W.LONG),("used",W.DWORD),("important",W.DWORD)]
        class Info(C.Structure):_fields_=[("header",Header),("colors",W.DWORD*3)]
        gdi.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.POINTER(Info),W.UINT]
        screen=self.u.GetDC(None);dc=None;bitmap=None;previous=None
        try:
            if not screen:raise ValueError("Capture DC unavailable")
            dc=gdi.CreateCompatibleDC(screen);bitmap=gdi.CreateCompatibleBitmap(screen,width,height)
            if not dc or not bitmap:raise ValueError("Capture bitmap unavailable")
            previous=gdi.SelectObject(dc,bitmap)
            info=Info();info.header=Header(C.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
            pixels=C.create_string_buffer(width*height*4)
            picture = None
            method = None
            # Some classic apps paint only WM_PRINT on inactive desktops.
            # These are bounded reads of the same validated window, never a
            # screen grab or a focus/visibility fallback.
            for candidate in ("PrintWindow.full-content", "PrintWindow", "WM_PRINT"):
                if candidate == "WM_PRINT":
                    self.message(h, 0x317, int(dc), 0x1E, timeout=40)
                elif not self.u.PrintWindow(h, dc, 2 if candidate.endswith("full-content") else 0):
                    continue
                gdi.SelectObject(dc,previous)
                try:
                    if gdi.GetDIBits(dc,bitmap,0,height,pixels,C.byref(info),0)!=height:
                        raise ValueError("Capture pixel read failed")
                    observed=Image.frombytes("RGB",(width,height),pixels.raw,"raw","BGRX")
                finally:
                    gdi.SelectObject(dc,bitmap)
                if not all(low==high for low,high in observed.getextrema()):
                    picture, method = observed, candidate
                    break
            if picture is None:raise ValueError("Validated window produced a blank capture through PrintWindow and WM_PRINT")
            stream=io.BytesIO();picture.save(stream,format="PNG");raw=stream.getvalue()
            if len(raw)>12*1024*1024:raise ValueError("Native capture exceeds response limit")
            return {"windowId":str(h),"width":width,"height":height,"mimeType":"image/png", "pngBase64":base64.b64encode(raw).decode(),"method":method}
        finally:
            if previous and dc:gdi.SelectObject(dc,previous)
            if bitmap:gdi.DeleteObject(bitmap)
            if dc:gdi.DeleteDC(dc)
            if screen:self.u.ReleaseDC(None,screen)

    def close(self):pass


class UiaBackend:
    def __init__(self):
        import sys
        sys.coinit_flags = 0
        import comtypes
        import comtypes.client
        from comtypes.automation import VARIANT
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
        self.U = U
        self.uia = comtypes.CoCreateInstance(U.CUIAutomation8._reg_clsid_, interface=U.IUIAutomation2,
                                            clsctx=comtypes.CLSCTX_INPROC_SERVER)
        self.uia.ConnectionTimeout = 50
        self.uia.TransactionTimeout = 80
        self.win = Win32()
        self.states = {}
        self.event_queue = queue.Queue(maxsize=1024)
        self.event_overflow = threading.Event()
        self.events = 0
        self.props = [30000, 30003, 30005, 30010, 30011, 30012, 30019, 30020, 30022, 30001,
                      30045, 30046, 30086, 30079, 30070]
        self.patterns = {"invoke": (10000, U.IUIAutomationInvokePattern), "value": (10002, U.IUIAutomationValuePattern),
            "toggle": (10015, U.IUIAutomationTogglePattern), "selectionItem": (10010, U.IUIAutomationSelectionItemPattern),
            "expandCollapse": (10005, U.IUIAutomationExpandCollapsePattern), "scroll": (10004, U.IUIAutomationScrollPattern)}
        self.availability = {"invoke":30031,"value":30043,"toggle":30041,
            "selectionItem":30036,"expandCollapse":30028,"scroll":30034}
        self.props.extend(self.availability.values())
        self.cache = self.make_cache(U.TreeScope_Subtree)
        self.event_cache = self.make_cache(U.TreeScope_Element)
        backend = self
        class PropertyHandler(comtypes.COMObject):
            _com_interfaces_ = [U.IUIAutomationPropertyChangedEventHandler]
            def HandlePropertyChangedEvent(self, sender, propertyId, newValue):
                try:
                    backend.enqueue(("property", backend.node(sender, 0, None), int(propertyId)))
                except Exception:
                    backend.enqueue(("invalidate", None, None))
                return 0
        class StructureHandler(comtypes.COMObject):
            _com_interfaces_ = [U.IUIAutomationStructureChangedEventHandler]
            def HandleStructureChangedEvent(self, sender, changeType, runtimeId):
                try:
                    backend.enqueue(("structure", (backend.node(sender, 0, None), sender), int(changeType)))
                except Exception:
                    backend.enqueue(("invalidate", None, None))
                return 0
        self.property_handler = PropertyHandler()
        self.structure_handler = StructureHandler()

    def enqueue(self,event):
        try:self.event_queue.put_nowait(event)
        except queue.Full:self.event_overflow.set()

    def make_cache(self, scope):
        cr = self.uia.CreateCacheRequest(); cr.TreeScope = scope
        cr.TreeFilter = self.uia.ControlViewCondition
        for prop in self.props: cr.AddProperty(prop)
        for pattern, _ in self.patterns.values(): cr.AddPattern(pattern)
        return cr

    def node(self, e, depth, parent):
        def prop(n, default=None):
            try: return e.GetCachedPropertyValue(n)
            except Exception: return default
        rid = prop(30000)
        if not rid:
            # Some real providers omit RuntimeId from the property cache.
            # Admit only the actual provider identity, never a fabricated ID.
            rid = e.GetRuntimeId()
        if not rid: raise ValueError("UIA runtime identity unavailable")
        bounds = prop(30001, (0, 0, 0, 0))
        role = int(prop(30003, 50025))
        roles = {50000:"Button",50001:"Calendar",50002:"CheckBox",50003:"ComboBox",50004:"Edit",50005:"Hyperlink",50006:"Image",50007:"ListItem",50008:"List",50009:"Menu",50010:"MenuBar",50011:"MenuItem",50012:"ProgressBar",50013:"RadioButton",50014:"ScrollBar",50015:"Slider",50016:"Spinner",50018:"Tab",50019:"TabItem",50020:"Text",50021:"ToolBar",50023:"Tree",50024:"TreeItem",50025:"Custom",50026:"Group",50028:"DataGrid",50029:"DataItem",50030:"Document",50032:"Window",50033:"Pane"}
        # Cached availability flags avoid six unsupported-pattern COM
        # exceptions for every ordinary text/decoration node.
        supported = [name for name, property_id in self.availability.items() if prop(property_id, False)]
        row = {"id": "uia:" + ".".join(map(str, rid)), "parentId": parent, "depth": depth,
            "name": prop(30005, ""), "role": roles.get(role, "Custom"), "automationId": prop(30011, ""),
            "className": prop(30012, ""), "nativeWindowHandle": prop(30020, 0),
            "enabled": bool(prop(30010, False)), "offscreen": bool(prop(30022, True)),
            "isPassword": bool(prop(30019, True)), "patterns": supported,
            "bounds": dict(zip(("x", "y", "width", "height"), bounds))}
        row["isPassword"]=protected(row)
        if "value" in supported:row["readOnly"]=bool(prop(30046,True))
        if not row["isPassword"] and "value" in supported: row["value"] = prop(30045, "")
        if "toggle" in supported: row["toggleState"] = prop(30086)
        if "selectionItem" in supported: row["selected"] = prop(30079)
        if "expandCollapse" in supported: row["expandState"] = prop(30070)
        return row

    def drain(self):
        if self.event_overflow.is_set():
            for state in self.states.values():state["dirty"]=True
            self.event_overflow.clear()
        count=0
        while count<128 and time.monotonic()<self.deadline:
            try:kind,row,_=self.event_queue.get_nowait()
            except queue.Empty:break
            count+=1;self.events+=1
            source = None
            if kind == "structure": row, source = row
            for state in self.states.values():
                if kind == "invalidate": state["dirty"] = True
                elif row and row["id"] in state["index"]:
                    if kind == "structure":
                        # Only the event's changed branch crosses the provider
                        # boundary. Other cached branches are left untouched.
                        old=state["rows"][row["id"]]
                        branch=source.BuildUpdatedCache(self.cache)
                        rows,index,truncated=self.project(branch,old["depth"],old["parentId"],*state["limits"])
                        removed={row["id"]}
                        while True:
                            descendants={r["id"] for r in state["rows"].values() if r["parentId"] in removed}
                            if descendants<=removed: break
                            removed |= descendants
                        for eid in removed:
                            state["rows"].pop(eid,None);state["index"].pop(eid,None)
                        state["rows"].update(rows);state["index"].update(index)
                        state["removed"].extend(removed-set(rows));state["changes"].extend(rows)
                        state["revision"]+=1;state["truncated"] |= truncated
                    else:
                        old = state["rows"][row["id"]]
                        row.update(depth=old["depth"], parentId=old["parentId"])
                        state["rows"][row["id"]] = row
                        state["revision"] += 1
                        state["changes"].append(row["id"])
        if not self.event_queue.empty():
            for state in self.states.values():state["dirty"]=True

    def project(self,root,level,parent,depth,maximum):
        stack=[(root,level,parent)];rows={};index={};truncated=False
        while stack and len(rows)<maximum:
            e,current,parent=stack.pop();row=self.node(e,current,parent)
            rows[row["id"]]=row;index[row["id"]]=e
            children=e.GetCachedChildren()
            if children:
                if current>=depth: truncated=True
                else:
                    for n in reversed(range(children.Length)):
                        stack.append((children.GetElement(n),current+1,row["id"]))
        return rows,index,truncated or bool(stack)

    def snapshot(self, h, depth, maximum):
        self.win.valid(h); self.drain()
        state = self.states.get(h)
        window = self.win.metadata(h)
        identity = (window["pid"], window["processStartTime"])
        if state and state["identity"] != identity:
            self.remove(h); state = None
        # Cache changes are event-driven. Unsubscribed providers get bounded
        # target-only refreshes; the desktop root is never obtained.
        if not state or state["dirty"] or state["limits"] != (depth, maximum) or (not state["subscribed"] and time.monotonic()-state["at"] > .25):
            root = self.uia.ElementFromHandleBuildCache(h, self.cache)
            rows,index,truncated=self.project(root,0,None,depth,maximum)
            previous = state
            state = {"identity": identity,"root":root,"rows":rows,"index":index,"dirty":False,"revision":(state["revision"]+1 if state else 1),
                "changes":list(rows),"removed":[],"at":time.monotonic(),"subscribed":False,"truncated":truncated,"limits":(depth,maximum)}
            if previous and previous["subscribed"]:
                state["subscribed"] = True
                state["root"] = previous["root"]
            self.states[h] = state
        changes = state["changes"][:]; state["changes"].clear()
        removed=state["removed"][:];state["removed"].clear()
        return {"window":window,"tree":copy.deepcopy(list(state["rows"].values())),"truncated":state["truncated"],
            "source":"UIA.CacheRequest","revision":state["revision"],"diff":{"changed":changes,"removed":removed},"events":self.events,
            "eventsSubscribed":state["subscribed"]}

    def subscribe(self, h):
        state = self.states.get(h)
        if state and not state["subscribed"]:
            root = state["root"]
            self.uia.AddStructureChangedEventHandler(root, self.U.TreeScope_Subtree, self.event_cache, self.structure_handler)
            try:
                self.uia.AddPropertyChangedEventHandlerNativeArray(root, self.U.TreeScope_Subtree, self.event_cache,
                    self.property_handler, (C.c_int*len(self.props))(*self.props), len(self.props))
            except Exception:
                self.uia.RemoveStructureChangedEventHandler(root, self.structure_handler)
                raise
            state["subscribed"] = True
        return bool(state and state["subscribed"])

    def read(self, h, ids):
        self.drain(); self.win.valid(h)
        state = self.states.get(h)
        if not state or state["dirty"]: raise ValueError("stale_element_token")
        rows = []
        for eid in ids:
            if eid not in state["index"]: raise ValueError("stale_element_token")
            e = state["index"][eid].BuildUpdatedCache(self.event_cache)
            old = state["rows"][eid]; row = self.node(e, old["depth"], old["parentId"])
            if row["id"] != eid: raise ValueError("stale_element_token")
            state["index"][eid] = e; state["rows"][eid] = row
            if old!=row: state["changes"].append(eid);state["revision"]+=1
            rows.append(row)
        return {"windowId":str(h),"tree":rows,"source":"UIA.BuildUpdatedCache"}

    def action(self, h, eid, action, args):
        self.win.valid(h)
        self.drain()
        state = self.states.get(h)
        if not state or state["dirty"]: raise ValueError("stale_element_token")
        row = self.read(h, [eid])["tree"][0]
        if row["isPassword"] or not row["enabled"] or (row["offscreen"] and not args.get("_containedHidden")):
            raise ValueError("protected_or_unavailable_field")
        for key, source in (("expectedName","name"),("expectedRole","role"),("expectedClass","className")):
            if key in args and args[key] != row[source]: raise ValueError("stale_element_token")
        e = state["index"][eid]
        name = {"click":"invoke","value":"value","valueAppend":"value","toggle":"toggle","select":"selectionItem","expand":"expandCollapse","collapse":"expandCollapse","scroll":"scroll"}.get(action)
        if not name or name not in row["patterns"]: raise NotImplementedError("Pattern unavailable")
        pattern, interface = self.patterns[name]
        p = e.GetCachedPattern(pattern).QueryInterface(interface)
        if time.monotonic() >= self.deadline:
            raise UndispatchedTimeout("Deadline expired before pattern dispatch")
        self.win.dispatch_guard(args)
        # Pattern dispatch is the final operation in this lane job. Readback is
        # separate, so a delayed read cannot cause an action to be replayed.
        if name == "invoke": p.Invoke()
        elif name == "value":
            if row.get("readOnly",True):raise ValueError("read_only_field")
            p.SetValue(str(row.get("value", "")) + str(args.get("text", "")) if action == "valueAppend" else str(args.get("text", args.get("value", ""))))
        elif name == "toggle": p.Toggle()
        elif name == "selectionItem": p.Select()
        elif action == "expand": p.Expand()
        elif action == "collapse": p.Collapse()
        elif name == "scroll":
            amounts = {"NoAmount":2,"SmallIncrement":4,"LargeIncrement":3,"SmallDecrement":1,"LargeDecrement":0}
            p.Scroll(amounts.get(args.get("horizontal"),2), amounts.get(args.get("vertical"),4))
        state["changes"].append(eid)
        return {"mechanism":"uia.cachedPattern","effect":"unverifiable","elementId":eid}

    def remove(self, h):
        state = self.states.pop(h, None)
        if state and state["subscribed"]:
            self.uia.RemoveStructureChangedEventHandler(state["root"], self.structure_handler)
            self.uia.RemovePropertyChangedEventHandler(state["root"], self.property_handler)

    def close(self):
        for h in list(self.states): self.remove(h)


class MsaaBackend:
    def __init__(self):
        import comtypes
        import comtypes.client
        from comtypes.automation import VARIANT
        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen.Accessibility import IAccessible
        self.interface = IAccessible
        self.acc = C.OleDLL("oleacc")
        self.acc.AccessibleObjectFromWindow.argtypes = [W.HWND,W.DWORD,C.POINTER(comtypes.GUID),C.POINTER(C.POINTER(IAccessible))]
        self.acc.AccessibleChildren.argtypes=[C.POINTER(IAccessible),W.LONG,W.LONG,C.POINTER(VARIANT),C.POINTER(W.LONG)]
        self.variant=VARIANT
        self.win = Win32()
        self.refs = {}

    def field(self,h):
        self.win.valid(h)
        ptr=C.POINTER(self.interface)()
        self.acc.AccessibleObjectFromWindow(h,0xFFFFFFFC,C.byref(self.interface._iid_),C.byref(ptr))
        state=int(ptr.accState[0]);name=ptr.accName[0] or ""
        return {"name":name,"isPassword":bool(state&0x20000000) or bool(SECRET_FIELD.search(name)),"readOnly":bool(state&0x40),
                "role":int(ptr.accRole[0]),"toggleState":1 if state&16 else 0,"selected":bool(state&2)}

    def snapshot(self, h, maximum):
        self.win.valid(h)
        ptr = C.POINTER(self.interface)()
        self.acc.AccessibleObjectFromWindow(h, 0xFFFFFFFC, C.byref(self.interface._iid_), C.byref(ptr))
        rows=[];refs={};pending=[(ptr,0,None,0,"root")]
        while pending and len(rows)<maximum:
            current,child,parent,depth,path=pending.pop(0)
            try:
                name = current.accName[child] or ""
                role = int(current.accRole[child]); state = int(current.accState[child])
                password = bool(state & 0x20000000)
                eid=f"msaa:{h}:{path}";refs[eid]=(current,child)
                row={"id":eid,"parentId":parent,"depth":depth,
                    "name":name,"role":{42:"Edit",43:"Button",44:"CheckBox",45:"RadioButton",37:"TabItem",9:"Window",10:"Client",35:"TreeItem",34:"Tree",33:"ListItem",32:"List",36:"Tab",15:"Document",46:"ComboBox"}.get(role,"Custom"),
                    "className":"MSAA","automationId":"","nativeWindowHandle":h if child==0 else 0,
                    "enabled":not bool(state&1),"offscreen":bool(state&0x18000),"isPassword":password,"patterns":[],
                    "bounds":{"x":0,"y":0,"width":0,"height":0}}
                row.update(selected=bool(state&2),toggleState=1 if state&16 else 0,
                           expandState=1 if state&512 else 0 if state&1024 else None,readOnly=bool(state&0x40))
                try:
                    left,top,width,height=current.accLocation(child)
                    row["bounds"]={"x":left,"y":top,"width":width,"height":height}
                except Exception:pass
                row["isPassword"]=protected(row)
                if not row["isPassword"]:
                    value=current.accValue[child]
                    if value is not None: row.update(value=value,patterns=["value"])
                    try:
                        if current.accDefaultAction[child]:row["patterns"].append("invoke")
                    except Exception:pass
                    if role in {37,35,33,45}:
                        row["patterns"].append("selectionItem")
                    if role==35 and row["expandState"] is not None:
                        row["patterns"].append("expandCollapse")
                rows.append(row)
                if child==0 and depth<12:
                    count=min(int(current.accChildCount),maximum-len(rows))
                    if count>0:
                        children=(self.variant*count)();actual=W.LONG()
                        self.acc.AccessibleChildren(current,0,count,children,C.byref(actual))
                        for n in range(actual.value):
                            value=children[n].value
                            if isinstance(value,int):
                                pending.append((current,value,eid,depth+1,path+".child"+str(value)))
                            elif value:
                                pending.append((value.QueryInterface(self.interface),0,eid,depth+1,path+".object"+str(n)))
            except Exception: continue
        self.refs[h]=refs
        return {"window":self.win.metadata(h),"tree":rows,"truncated":bool(pending),"source":"MSAA.AccessibleObjectFromWindow"}

    def read(self,h,ids):
        data=self.snapshot(h,256)
        rows=[r for r in data["tree"] if r["id"] in ids]
        if len(rows)!=len(ids): raise ValueError("stale_element_token")
        return {"windowId":str(h),"tree":rows,"source":data["source"]}

    def action(self,h,eid,action,args):
        row=self.read(h,[eid])["tree"][0]
        if protected(row) or not row["enabled"] or row["offscreen"]: raise ValueError("protected_or_unavailable_field")
        if row.get("readOnly") and action in {"value","valueAppend"}:raise ValueError("read_only_field")
        for key,source in (("expectedName","name"),("expectedRole","role"),("expectedClass","className")):
            if key in args and args[key]!=row[source]:raise ValueError("stale_element_token")
        if time.monotonic()>=self.deadline: raise UndispatchedTimeout("Deadline expired before MSAA dispatch")
        self.win.dispatch_guard(args)
        ptr,child=self.refs[h][eid]
        if action in {"value","valueAppend"}:
            value=str(args.get("text",args.get("value","")))
            if action=="valueAppend": value=row.get("value","")+value
            ptr.accValue[child]=value
        elif action=="click": ptr.accDoDefaultAction(child)
        elif action=="select": ptr.accSelect(2,child)
        elif action in {"expand","collapse"}:
            if row.get("expandState") not in {0,1}: raise NotImplementedError("MSAA expansion state unavailable")
            desired=1 if action=="expand" else 0
            if row["expandState"]!=desired: ptr.accDoDefaultAction(child)
        else: raise NotImplementedError("MSAA action unavailable")
        return {"mechanism":"MSAA.cachedAccessible","effect":"unverifiable"}

    def close(self): pass


class FastClient:
    def __init__(self, transport, desktop=None):
        self.transport = transport
        self.win = Win32()
        self.desktop = desktop or transport.desktop
        self.win.fixture_scope = transport.desktop.disposable_target
        self.win.contained_hidden = self.desktop is not transport.desktop
        self.uia = DeadlineLane(UiaBackend, "cua-persistent-mta", self.desktop)
        self.msaa = DeadlineLane(MsaaBackend, "cua-msaa-mta", self.desktop)
        # A whole-window accessibility provider may hang. Field protection
        # must have its own persistent bounded lane so that a subtree timeout
        # cannot erase every independently observable edit control.
        self.policy = DeadlineLane(MsaaBackend, "cua-field-policy-mta", self.desktop)
        # Independent fresh protection checks need the same 80 ms provider
        # budget as actions; 40 ms spuriously expired during normal scheduling.
        self.win.field_metadata=lambda child:self.policy.call("field",child,budget=.080)
        self.field_cache={}
        def field_snapshot(child):
            existing=self.field_cache.get(child)
            if existing and time.monotonic()-existing[0]<1:
                return {**existing[1],"cached":True}
            metadata=self.win.field_metadata(child)
            self.field_cache[child]=(time.monotonic(),metadata)
            return metadata
        self.win.field_snapshot=field_snapshot
        def capture_backend():
            # Codec imports belong to lane initialization, not the first
            # deadline-bounded capture. Initialization remains off the caller.
            from PIL import Image
            return Win32()
        self.capture = DeadlineLane(capture_backend, "cua-printwindow-deadline", self.desktop)
        self.lock = threading.RLock()
        self.snapshots = {}
        self.subscriptions = set()
        self.timeout_count = 0
        self.uncertain = set()
        self.seen_windows = set()
        self.uia_failures = {}

    def inspect(self, h, args):
        maximum = max(1, min(2000,int(args.get("maxNodes",500))))
        depth = max(0,min(20,int(args.get("maxDepth",12))))
        began = time.perf_counter()
        window = self.win.metadata(h)
        identity = (window["pid"], window["processStartTime"])
        try:
            unavailable = self.uia_failures.get(h)
            if unavailable and unavailable[0] == identity and time.monotonic() < unavailable[1]:
                raise ValueError(unavailable[2])
            # A cold provider connection is measurably slower than an atomic
            # warm operation. Give an unseen window one bounded discovery
            # budget, then keep ordinary observations at the hot-path budget.
            budget=.300 if h not in self.seen_windows else .080
            self.seen_windows.add(h)
            data = self.uia.call("snapshot",h,depth,maximum,budget=budget)
            self.uia_failures.pop(h, None)
            if h not in self.subscriptions:
                # Subscription has its own deadline and never repeats a tree read.
                try:
                    if self.uia.call("subscribe",h,budget=.020): self.subscriptions.add(h)
                except Exception: pass
        except Exception as exc:
            # A known absent provider must not consume its whole deadline at
            # every verification sample. Retry on the same process identity
            # after one second; Win32/MSAA observations remain freshly read.
            if not unavailable or unavailable[0] != identity or time.monotonic() >= unavailable[1]:
                self.uia_failures[h] = (identity, time.monotonic() + 1, type(exc).__name__ + ": " + str(exc)[:120])
            self.timeout_count += isinstance(exc, TimeoutError)
            data = self.win.snapshot(h,maximum)
            # Classic property sheets expose tab items through their tab HWND
            # even when the private-desktop top-level UIA provider is absent.
            # Read that bounded control, rather than walking the whole app.
            for control in list(data["tree"]):
                if control.get("className") not in {"SysTabControl32", "SysTreeView32", "SysListView32"}:
                    continue
                try:
                    tabs = self.msaa.call("snapshot", control["nativeWindowHandle"],
                        min(64, maximum - len(data["tree"])), budget=.035)
                    data["tree"].extend({**row, "depth": control["depth"] + 1,
                        "parentId": control["id"]} for row in tabs["tree"]
                        if row["role"] in {"TabItem", "TreeItem", "ListItem"})
                    data["truncated"] |= tabs["truncated"]
                except Exception:
                    pass
            usable = any(r.get("enabled") and not r.get("isPassword") and r.get("role") in {
                "Edit", "Button", "CheckBox", "RadioButton", "TreeItem", "ListItem", "TabItem"}
                for r in data["tree"])
            if not usable:
                try:
                    msaa = self.msaa.call("snapshot",h,maximum,budget=.025)
                    if len(msaa["tree"]) > 1: data = msaa
                except Exception: pass
            data["degradedReason"] = self.uia_failures[h][2]
        data["elapsedMs"]=(time.perf_counter()-began)*1000
        self.snapshots[h]=copy.deepcopy(data)
        return data

    def read(self, h, ids):
        if not isinstance(ids,list) or not 1<=len(ids)<=8: raise ValueError("Element read limits out of range")
        if all(eid.startswith("msaa:") for eid in ids):
            return self.msaa.call("read", self.msaa_target(h, ids), ids, budget=.035)
        if all(eid.startswith("uia:") for eid in ids):
            try: return self.uia.call("read",h,ids,budget=.035)
            except Exception:
                # A new Win32 token must be resolved; never silently equate an
                # old UIA token with a coordinate or different child window.
                return self.cached_native_read(h,ids)
        return self.cached_native_read(h,ids)

    def msaa_target(self, h, ids):
        targets = {int(eid.split(":", 2)[1]) for eid in ids}
        if len(targets) != 1:
            raise ValueError("mixed_accessibility_scopes")
        target = targets.pop()
        if target != h and not self.win.u.IsChild(h, target):
            raise ValueError("stale_element_token")
        return target

    def cached_native_read(self,h,ids):
        snapshot = self.snapshots.get(h)
        if not snapshot: raise ValueError("stale_element_token")
        current=self.win.metadata(h)
        if any(current[k]!=snapshot["window"][k] for k in ("pid","processStartTime")):
            raise ValueError("stale_window_identity")
        rows=[]
        for eid in ids:
            found=[x for x in snapshot["tree"] if x["id"]==eid]
            if len(found)!=1: raise ValueError("stale_element_token")
            row=copy.deepcopy(found[0]); child=int(row.get("nativeWindowHandle") or 0)
            if not child or not (child==h or self.win.u.IsChild(h,child)): raise ValueError("stale_element_token")
            if self.win.text(child,True)!=row["className"]: raise ValueError("stale_element_token")
            if row.get("treeHandle"):
                row.update(self.win.tree_item(child,row["treeHandle"]))
                rows.append(row)
                continue
            if row.get("menuCommand"):
                matches=[r for r in self.win.menu_items(h) if r["id"]==eid]
                if len(matches)!=1:raise ValueError("stale_element_token")
                rows.append(matches[0])
                continue
            if row.get("protectionUnknown") and self.win.disposable(h):
                row["isPassword"] = False
                row.pop("protectionUnknown", None)
                row.pop("protectionUnknownReason", None)
            style=self.win.u.GetWindowLongW(child,-16)
            row.update(enabled=bool(self.win.u.IsWindowEnabled(child)),offscreen=not self.win.available(h,child),
                       isPassword=protected(row) or (row["role"]=="Edit" and bool(style&0x20)),readOnly=row["role"]=="Edit" and bool(style&0x800))
            if row["role"]=="Edit" and not self.win.disposable(h):
                try:
                    metadata=self.win.field_metadata(child)
                    if metadata["role"] not in {42, 15}:
                        raise ValueError("protection_unknown")
                    row.update(name=metadata["name"],isPassword=bool(style&0x20) or metadata["isPassword"],
                               readOnly=bool(style&0x800) or metadata["readOnly"])
                    row["isPassword"]=protected(row)
                    row.pop("protectionUnknown", None)
                except Exception as exc:
                    row.update(isPassword=True,protectionUnknown=True,
                               protectionUnknownReason=type(exc).__name__ + ": " + str(exc)[:100])
            elif row["role"] in {"CheckBox","RadioButton"}:
                if style&15==11:
                    metadata=self.win.field_metadata(child)
                    row.update(toggleState=metadata["toggleState"],selected=metadata["selected"])
                elif row["role"]=="CheckBox":row["toggleState"]=self.win.message(child,0xF0)
                else:row["selected"]=bool(self.win.message(child,0xF0))
            bounds=W.RECT();self.win.u.GetWindowRect(child,C.byref(bounds))
            row["bounds"]={"x":bounds.left,"y":bounds.top,"width":bounds.right-bounds.left,"height":bounds.bottom-bounds.top}
            if row["isPassword"]:row.pop("value",None)
            if row["role"] == "Edit":
                if not row["isPassword"]:
                    row["value"] = self.win.value(child)
            elif child != h and not row["isPassword"]:
                row["name"] = self.win.value(child)
            rows.append(row)
        return {"windowId":str(h),"tree":rows,"source":"Win32.readback"}

    def native_action(self,h,row,action,args):
        self.win.valid(h); child=int(row.get("nativeWindowHandle") or 0)
        if not child or not (h==child or self.win.u.IsChild(h,child)): raise NotImplementedError("No validated background message target")
        cls=self.win.text(child,True)
        if cls!=row["className"]: raise ValueError("stale_element_token")
        if protected(row) or not self.win.u.IsWindowEnabled(child) or not self.win.available(h,child):
            raise ValueError("protected_or_unavailable_field: " + str(row.get("protectionUnknownReason") or
                "protected, disabled or invisible control"))
        style=self.win.u.GetWindowLongW(child,-16)
        if "edit" in cls.lower() and style&0x20:raise ValueError("protected_field")
        if "edit" in cls.lower() and style&0x800 and action in {"value","editSetValue","valueAppend","editAppend","text"}:
            raise ValueError("read_only_field")
        self.win.dispatch_guard(args)
        if row.get("treeHandle") and action in {"select","expand","collapse"}:
            fresh=self.win.tree_item(child,row["treeHandle"])
            if fresh["name"]!=row["name"]:raise ValueError("stale_element_token")
            try:
                if action=="select":self.win.message(child,0x110B,9,row["treeHandle"],timeout=80)
                else:self.win.message(child,0x1102,2 if action=="expand" else 1,row["treeHandle"],timeout=80)
                readback=self.win.tree_item(child,row["treeHandle"])
            except TimeoutError:
                self.uncertain.add(h)
                return {"effect":"uncertain","mechanism":"Win32.TreeView.deadline","noRetry":True,
                    "reconciliation":{"id":fresh["id"],"name":fresh["name"],"className":fresh["className"],
                        "action":action,"selected":fresh["selected"],"expandState":fresh["expandState"]}}
            return {"effect":"unverifiable","mechanism":"Win32.TreeView","readbackNode":readback}
        if row.get("menuCommand") and action in {"click","buttonClick"}:
            self.win.message(h,0x111,row["menuCommand"],0,timeout=80)
            return {"effect":"unverifiable","mechanism":"Win32.MenuCommand"}
        if action in {"value","editSetValue","valueAppend","editAppend"}:
            if "edit" not in cls.lower(): raise NotImplementedError("No native edit target")
            text=str(args.get("text",args.get("value","")))
            if action in {"valueAppend","editAppend"}: text=self.win.value(child)+text
            buf=C.create_unicode_buffer(text)
            self.win.message(child,0xC,0,C.addressof(buf),timeout=80)
            effect="confirmed" if self.win.value(child)==text else "partial"
            return {"mechanism":"Win32.WM_SETTEXT","effect":effect,"readback":self.win.value(child)}
        if action in {"click","buttonClick","toggle","select"} and "button" in cls.lower():
            self.win.message(child,0xF5,timeout=80)
            return {"mechanism":"Win32.BM_CLICK","effect":"unverifiable"}
        if action=="scroll" and "listbox" in cls.lower():
            if args.get("horizontal", "NoAmount") != "NoAmount":
                raise NotImplementedError("ListBox background route supports vertical scrolling only")
            command={"SmallDecrement":0,"SmallIncrement":1,"LargeDecrement":2,"LargeIncrement":3}.get(args.get("vertical"))
            if command is None: raise ValueError("Invalid vertical scroll amount")
            if not self.win.u.PostMessageW(child,0x115,command,0):
                raise ValueError("ListBox background scroll delivery failed")
            # Scroll processing may synchronously repaint the window. Enqueue
            # once without focus; callers must observe the native postcondition.
            return {"mechanism":"Win32.ListBox.PostMessage.WM_VSCROLL","effect":"unverifiable"}
        if action in {"click","pointClick"}:
            b=row["bounds"]
            x=int(args.get("x") if args.get("x") is not None else b["x"]+b["width"]/2)
            y=int(args.get("y") if args.get("y") is not None else b["y"]+b["height"]/2)
            if not (b["x"]<=x<b["x"]+b["width"] and b["y"]<=y<b["y"]+b["height"]): raise ValueError("invalid_coordinates")
            p=W.POINT(x,y); self.win.u.ScreenToClient(child,C.byref(p))
            packed=(p.y<<16)|(p.x&0xFFFF)
            if not self.win.u.PostMessageW(child,0x201,1,packed) or not self.win.u.PostMessageW(child,0x202,0,packed): raise ValueError("PostMessage delivery failed")
            return {"mechanism":"Win32.PostMessage","effect":"unverifiable"}
        if action=="key":
            self.win.typing_guard(h)
            keys={"ENTER":13,"RETURN":13,"ESC":27,"ESCAPE":27,"TAB":9,"SPACE":32,"F1":112,"F5":116,"HOME":36,"END":35,"UP":38,"DOWN":40,"LEFT":37,"RIGHT":39}
            key=str(args.get("key","")).upper(); vk=keys.get(key,ord(key) if len(key)==1 else 0)
            if not vk: raise NotImplementedError("Unsupported background key; owner foreground route required")
            if not self.win.u.PostMessageW(child,0x100,vk,0) or not self.win.u.PostMessageW(child,0x101,vk,0xC0000000): raise ValueError("PostMessage delivery failed")
            return {"mechanism":"Win32.PostMessage.key","effect":"unverifiable"}
        raise NotImplementedError("No supported background route")

    def action(self,h,args):
        self.win.valid(h)
        if h in self.uncertain: raise ValueError("Previous dispatch uncertain; verify before retry")
        eid=args.get("elementId",""); action=args.get("action","")
        guard=self.transport.guard
        if guard is None: raise ValueError("isolated_guard_required")
        guard_before=guard.check()
        if not guard_before["ok"]: raise ValueError("zero_disturbance_guard_failed")
        before=self.transport.request("status",timeout=2)
        # A private/contained app is independent of Paul's real input activity.
        # Never copy physical-input timestamps into its dispatch preconditions.
        args={k:v for k,v in args.items() if k not in {
            "_lastInputTick","_physicalGeneration","inputGeneration","allowForeground","_containedHidden"}}
        if self.win.contained_hidden:
            self.desktop.verify_window(h)
            args["_containedHidden"] = True
        if not eid:
            observed=self.inspect(h,args)
            eid=observed["tree"][0]["id"];args={**args,"elementId":eid}
        row=self.read(h,[eid])["tree"][0]
        for key, source in (("expectedName","name"),("expectedRole","role"),("expectedClass","className")):
            if key in args and args[key]!=row[source]: raise ValueError("stale_element_token")
        try:
            if eid.startswith("uia:") and action not in {"editSetValue","editAppend","buttonClick","key","pointClick"}:
                try: result=self.uia.call("action",h,eid,action,args,budget=.080)
                except (NotImplementedError, UndispatchedTimeout): result=self.native_action(h,row,action,args)
                except TimeoutError:
                    self.uncertain.add(h)
                    result={"effect":"uncertain","mechanism":"uia.deadline","noRetry":True}
            elif eid.startswith("msaa:"):
                result=self.msaa.call("action",self.msaa_target(h,[eid]),eid,action,args,budget=.080)
            else: result=self.native_action(h,row,action,args)
        except NotImplementedError:
            raise NotImplementedError("No verified background route; foreground input is disabled")
        except TimeoutError:
            self.uncertain.add(h)
            result={"effect":"uncertain","mechanism":"Win32.deadline","noRetry":True}
        after=self.transport.request("status",timeout=2)
        guard_after=guard.check()
        fields=("foreground_changes","new_visible_windows","injected_mouse_events","injected_keyboard_events")
        deltas={key:guard_after[key]-guard_before[key] for key in fields}
        observable=all(g.get("input_desktop_bound") and g.get("input_hooks_installed")
                       for g in (guard_before,guard_after))
        preserved=observable and guard_after["ok"] and all(value==0 for value in deltas.values())
        result.update(foregroundPreserved=preserved,
            cursorPreserved=preserved,preservationObservable=observable,
            preservationPolicy="agent-attribution",attributedGuard={
                "before":{key:guard_before[key] for key in fields},
                "after":{key:guard_after[key] for key in fields},"deltas":deltas,
                "unownedActivity":guard_after.get("unowned_activity",{}),
                "violations":guard_after["violations"]},
            before=before,after=after,elementId=eid,delivery="background")
        if action in {"value","editSetValue","valueAppend","editAppend"} and result["effect"]!="uncertain":
            try:
                value=self.read(h,[eid])["tree"][0].get("value")
                if action in {"value","editSetValue"}: result.update(readback=value,effect="confirmed" if value==str(args.get("text",args.get("value",""))) else "partial")
            except Exception: pass
        return result

    @staticmethod
    def check(tree, expectations):
        checks=[]
        for rule in expectations:
            selector=rule.get("selector",{})
            if not selector or not set(rule)<= {"selector","value_equals","name_contains","selected_equals","toggle_equals","expand_equals"}:
                checks.append({"status":"unknown","reason":"unsupported_check"});continue
            matches=[r for r in tree if all(str(r.get(k,""))==str(v) for k,v in selector.items())]
            if len(matches)!=1: checks.append({"status":"unsatisfied","matches":len(matches)});continue
            row=matches[0]; predicates=[]
            for op,key in (("value_equals","value"),("selected_equals","selected"),("toggle_equals","toggleState"),("expand_equals","expandState")):
                if op in rule: predicates.append(row.get(key)==rule[op] and key in row)
            if "name_contains" in rule: predicates.append(rule["name_contains"] in row["name"])
            checks.append({"status":"satisfied" if predicates and all(predicates) else "unsatisfied","observed":row})
        return {"status":"satisfied" if checks and all(c["status"]=="satisfied" for c in checks) else "unsatisfied","checks":checks}

    def cycle(self,h,args):
        started=time.perf_counter()
        if args.get("elementId") and h in self.snapshots:
            observed=self.read(h,[args["elementId"]])
            observation={"window":self.win.metadata(h),"tree":observed["tree"],"source":observed["source"],"truncated":False}
        else:observation=self.inspect(h,args)
        if "selector" in args:
            matches=[r for r in observation["tree"] if all(str(r.get(k,""))==str(v) for k,v in args["selector"].items())]
            if len(matches)!=1: raise ValueError("selector_missing_or_ambiguous")
            args={**args,"elementId":matches[0]["id"]}
        result=self.action(h,args)
        pending=result.get("reconciliation")
        if pending and self.win.disposable(h):
            try:
                actual=self.read(h,[pending["id"]])["tree"][0]
                key="selected" if pending["action"]=="select" else "expandState"
                predicate="selected_equals" if key=="selected" else "expand_equals"
                desired=True if key=="selected" else 1 if pending["action"]=="expand" else 0
                rules=args.get("expect",[])
                exact=(all(actual.get(k)==pending[k] for k in ("id","name","className"))
                    and pending[key]!=desired and actual.get(key)==desired and len(rules)==1
                    and rules[0].get("selector",{}).get("id")==pending["id"]
                    and rules[0].get(predicate)==desired)
                check=self.check([actual],rules)
                if exact and check["status"]=="satisfied":
                    self.uncertain.discard(h)
                    return {**result,"effect":"confirmed","reconciledBy":"Win32.TreeView.readback",
                        "check":check,"observation":{**observation,"tree":[actual],"source":"Win32.readback"},
                        "elapsedMs":(time.perf_counter()-started)*1000}
            except (ValueError,TimeoutError,OSError) as exc:
                result["reconciliationError"]=str(exc)
        if result.get("readbackNode"):
            check=self.check([result["readbackNode"]],args.get("expect",[]))
            if check["status"]=="satisfied":
                return {**result,"effect":"confirmed","check":check,"observation":observation,
                    "elapsedMs":(time.perf_counter()-started)*1000}
        # WM_SETTEXT's own fresh WM_GETTEXT readback is already the exact
        # affected-control verifier. A slower unrelated tree refresh must not
        # erase that real observation or turn a completed edit into a failure.
        if result.get("mechanism")=="Win32.WM_SETTEXT" and result.get("effect")=="confirmed":
            rules=args.get("expect",[])
            if rules and all(r.get("selector",{}).get("id")==args["elementId"] and
                set(r)=={"selector","value_equals"} and r["value_equals"]==result.get("readback") for r in rules):
                return {**result,"check":{"status":"satisfied","source":"Win32.WM_GETTEXT","readback":result["readback"]},
                    "observation":observation,"elapsedMs":(time.perf_counter()-started)*1000}
        deadline=time.monotonic()+.2; check={"status":"unsatisfied"}
        while True:
            try:
                # Re-read the actual affected control even if a provider omits
                # property events; use events for the rest of the window.
                try:
                    self.read(h,[args["elementId"]])
                except ValueError as exc:
                    # A structure event invalidates the cached token before
                    # readback. Re-observe; never replay the dispatched action.
                    if str(exc) != "stale_element_token":
                        raise
                observation=self.inspect(h,args)
                check=self.check(observation["tree"],args.get("expect",[]))
                if check["status"]!="satisfied":
                    # Invoke frequently changes a sibling label rather than
                    # its button. Some real providers omit Name events. Read
                    # only bounded goal candidates, never trust stale cached
                    # siblings and never poll the full desktop tree.
                    candidates=[]
                    for rule in args.get("expect",[]):
                        selector=rule.get("selector",{})
                        stable={k:v for k,v in selector.items() if k!="name"}
                        if not stable: continue
                        candidates.extend(r["id"] for r in observation["tree"]
                            if all(str(r.get(k,""))==str(v) for k,v in stable.items()))
                    candidates=list(dict.fromkeys(candidates))
                    if candidates and len(candidates)<=8:
                        refreshed=self.read(h,candidates)["tree"]
                        replacements={r["id"]:r for r in refreshed}
                        observation["tree"]=[replacements.get(r["id"],r) for r in observation["tree"]]
                        check=self.check(observation["tree"],args.get("expect",[]))
            except Exception as exc: check={"status":"unknown","reason":str(exc)}
            if check["status"]=="satisfied" or time.monotonic()>=deadline: break
            time.sleep(.005)
        if check["status"]=="satisfied" and not (self.uia.busy.locked() or self.msaa.busy.locked()):
            self.uncertain.discard(h)
            result["effect"]="confirmed"
        elif check["status"]=="satisfied" and result["effect"]!="uncertain":
            # An unrelated observation lane can be busy without making a
            # successfully verified Win32 action uncertain.
            result["effect"]="confirmed"
        return {**result,"check":check,"observation":observation,"elapsedMs":(time.perf_counter()-started)*1000}

    def request(self,op,args):
        with self.lock:
            if op=="windows":
                rows=[]
                for window in self.desktop.windows():
                    h=int(window.get("windowId") or window.get("hwnd"))
                    try:
                        if window.get("visible", True) or self.win.contained_hidden:
                            rows.append({**self.win.metadata(h), "isolation": window.get("isolation", "agent-desktop")})
                    except (ValueError, OSError): pass
                return rows
            h=int(args.get("windowId",0)); self.win.valid(h)
            if not self.desktop.owns(h):
                raise ValueError("isolated_desktop_required: target is outside the agent desktop")
            if args.get("allowForeground"):
                raise ValueError("foreground_route_disabled: use preview input on the agent desktop")
            document=self.transport.browser_document(h)
            if document and op in {"inspect","inspectElements","action","remoteAction","cycle"}:
                guard_before=self.transport.guard.check()
                value=document.request(op,args,self.win.metadata(h))
                guard_after=self.transport.guard.check()
                if op in {"action","remoteAction","cycle"}:
                    deltas={k:guard_after[k]-guard_before[k] for k in
                        ("foreground_changes","new_visible_windows","injected_mouse_events","injected_keyboard_events")}
                    value.update(foregroundPreserved=not deltas["foreground_changes"],
                        cursorPreserved=not deltas["injected_mouse_events"],focusRestored=False,
                        preservationObservable=bool(guard_after["input_desktop_bound"] and guard_after["input_hooks_installed"]),
                        preservation={"policy":"agent-attribution","attributedDeltas":deltas})
                return value
            if op=="window": return self.win.metadata(h)
            if op=="capture":return self.capture.call("capture",h,budget=.2)
            if op=="remoteGuard": return {"safe":True,"protection":"per_field"}
            if op=="inspect": return self.inspect(h,args)
            if op=="inspectElements": return self.read(h,args.get("elementIds"))
            if op in {"action","remoteAction"}:
                result=self.action(h,args)
                if op=="remoteAction": return {k:result.get(k) for k in ("effect","mechanism","foregroundPreserved","cursorPreserved","focusRestored","delivery","preservationObservable","noRetry")}
                return result
            if op=="cycle": return self.cycle(h,args)
            if op=="remoteObserve":
                return {"observation":self.inspect(h,args),"capture":self.capture.call("capture",h,budget=.2) if args.get("image") else None}
            raise ValueError("Unsupported fast operation")

    def close(self):
        self.uia.close(); self.msaa.close(); self.policy.close(); self.capture.close()
