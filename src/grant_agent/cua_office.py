"""Hidden, new-instance Office automation on token-owned disposable documents.

No running-object lookup, UI input, foreground activation or visible preview is
used. A COM object is admitted only when its HWND identifies a process absent
from the preactivation process snapshot. This matters for PowerPoint's singleton
server: a reused instance is refused without changing it or calling Quit.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import statistics
import time
import uuid
import zipfile
from xml.etree import ElementTree as ET

import psutil


APPS = {
    "Microsoft Word": ("Word.Application", "WINWORD.EXE", ".docx"),
    "Microsoft Excel": ("Excel.Application", "EXCEL.EXE", ".xlsx"),
    "Microsoft PowerPoint": ("PowerPoint.Application", "POWERPNT.EXE", ".pptx"),
}
TASKS = (
    {"id": "word-memo", "app": "Microsoft Word", "goal": "Draft and revise a project memo, save it and read it back", "title": "Project memo"},
    {"id": "word-minutes", "app": "Microsoft Word", "goal": "Write meeting minutes and an owner checklist, save and reopen", "title": "Meeting minutes"},
    {"id": "excel-budget", "app": "Microsoft Excel", "goal": "Calculate a household budget with a SUM formula and persist it", "title": "Household budget"},
    {"id": "excel-invoice", "app": "Microsoft Excel", "goal": "Calculate invoice line totals and a formula total, save and reopen", "title": "Project invoice"},
    {"id": "powerpoint-agenda", "app": "Microsoft PowerPoint", "goal": "Create a three-slide meeting deck, revise its agenda, save and reopen", "title": "Meeting deck"},
)


def _identities():
    return {(p.info["pid"], p.info["create_time"]) for p in psutil.process_iter(["pid", "create_time"])}


def _artifact(path):
    """Independent package inspection, after the application has saved it."""
    with zipfile.ZipFile(path) as archive:
        values = []
        for name in archive.namelist():
            if name.endswith(".xml") and (name.startswith("word/") or name.startswith("xl/") or name.startswith("ppt/slides/")):
                values.extend(node.text or "" for node in ET.fromstring(archive.read(name)).iter() if node.text)
    return {"path": str(path), "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "xmlText": "\n".join(values)}


class OfficeSession:
    """One newly created hidden application; call only from its COM thread."""
    def __init__(self, app, root, guard):
        import pythoncom
        from win32com.client import dynamic
        self.app_name = app
        self.root = Path(root).resolve()
        self.guard = guard
        self.application = None
        self.owned = False
        self.pid = None
        self.documents = []
        self.cleanup = {"quitOnlyOwnedInstance": True, "ok": False}
        self.pythoncom = pythoncom
        self.before = _identities()
        pythoncom.CoInitialize()
        self.com_initialized = True
        started = time.perf_counter()
        activation_at = time.time()
        try:
            progid, executable, _ = APPS[app]
            # CLSCTX_LOCAL_SERVER + CoCreateInstance is DispatchEx semantics.
            # Dynamic Dispatch avoids generating type caches outside this tree.
            pointer = pythoncom.CoCreateInstance(progid, None,
                pythoncom.CLSCTX_LOCAL_SERVER, pythoncom.IID_IDispatch)
            self.application = dynamic.Dispatch(pointer)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            ownership_probe = "COM HWND"
            try:
                handle = self.application.HWND
                hwnd = int(handle() if callable(handle) else handle)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process = psutil.Process(pid.value)
            except (AttributeError, pythoncom.com_error):
                # Word's Application has no HWND. CoCreateInstance has returned
                # its server; require one uniquely new WINWORD process born
                # during that call and a hidden, new-process OpusApp window.
                candidates = [p for p in psutil.process_iter(["pid", "name", "create_time"])
                    if (p.info["name"] or "").casefold() == executable.casefold()
                    and (p.pid, p.info["create_time"]) not in self.before
                    and activation_at - .1 <= p.info["create_time"] <= time.time() + .1]
                if len(candidates) != 1:
                    raise RuntimeError("COM activation has no uniquely new application process")
                process = candidates[0]
                handles = []
                callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                @callback_type
                def visit(handle, _):
                    owner = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
                    name = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(handle, name, 128)
                    wanted_class = "OpusApp" if app == "Microsoft Word" else "PPTFrameClass"
                    if owner.value == process.pid and name.value == wanted_class and not user32.IsWindowVisible(handle):
                        handles.append(int(handle))
                    return True
                user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
                user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                user32.IsWindowVisible.argtypes = [wintypes.HWND]
                user32.EnumWindows(visit, 0)
                if len(handles) > 1 or (app == "Microsoft Word" and len(handles) != 1):
                    raise RuntimeError("COM activation has no unique hidden application HWND")
                hwnd = handles[0] if handles else 0
                ownership_probe = "unique new application process born during CoCreateInstance; hidden application HWND where available"
            identity = (process.pid, process.create_time())
            if identity in self.before or process.name().casefold() != executable.casefold():
                raise RuntimeError("COM instance did not identify a new application process; existing instance untouched")
            self.pid, self.birth = identity
            self.owned = True
            guard.register_pid(self.pid)
            # PowerPoint refuses explicitly hiding the application in some
            # versions; its default is hidden and we verify that instead.
            if app != "Microsoft PowerPoint":
                self.application.Visible = False
                self.application.DisplayAlerts = 0 if app == "Microsoft Word" else False
            else:
                self.application.DisplayAlerts = 1  # ppAlertsNone
            if bool(self.application.Visible):
                raise RuntimeError("New COM application unexpectedly visible")
            self.application.AutomationSecurity = 3  # Disable document macros.
            self.launch_ms = round((time.perf_counter() - started) * 1000, 3)
            self.ownership = {"pid": self.pid, "birth": self.birth, "hwnd": hwnd,
                "newProcess": True, "method": "CoCreateInstance(CLSCTX_LOCAL_SERVER,IID_IDispatch)",
                "ownershipProbe": ownership_probe,
                "visible": False, "existingInstancesUntouched": True, "windowLease": "not needed: hidden COM has no visible window"}
        except Exception:
            self.close()
            raise

    def observe(self):
        started = time.perf_counter()
        value = {"app": self.app_name, "version": str(self.application.Version),
            "visible": bool(self.application.Visible), "pid": self.pid,
            "documents": len(self.documents), "source": "Office COM object model"}
        value["elapsedMs"] = round((time.perf_counter() - started) * 1000, 3)
        if value["visible"]:
            raise RuntimeError("Owned Office instance became visible")
        return value

    def _checked(self):
        if not self.guard.snapshot()["ok"]:
            raise RuntimeError("Zero-disturbance guard failed")

    def run_task(self, task, replay=0):
        self._checked()
        token = self.root.name
        path = self.root / (task["id"] + "-" + token + "-" + str(replay) + APPS[self.app_name][2])
        actions = []
        before = self.observe()
        started = time.perf_counter()
        if self.app_name == "Microsoft Word":
            document = self.application.Documents.Add()
        elif self.app_name == "Microsoft Excel":
            document = self.application.Workbooks.Add()
        else:
            document = self.application.Presentations.Add(False)
        self.documents.append(document)
        if self.app_name == "Microsoft Excel":
            sheet = document.Worksheets(1)
            sheet.Range("A2:A5").Value = (("Supplies",), ("Transport",), ("Food",), ("Total",))
            sheet.Range("B3:B4").Value = ((25,), (38,))
            sheet.Range("B5").Formula = "=SUM(B2:B4)"
            title_range, amount_range, total_range = sheet.Range("A1"), sheet.Range("B2"), sheet.Range("B5")
            if task["id"] == "excel-invoice":
                sheet.Range("A2:A5").Value = (("Design hours",), ("Transport",), ("Supplies",), ("Invoice total",))
                sheet.Range("C2").Value = 2
                sheet.Range("D2").Formula = "=B2*C2"
                sheet.Range("D3:D4").Value = ((25,), (38,))
                sheet.Range("D5").Formula = "=SUM(D2:D4)"
                total_range = sheet.Range("D5")
        elif self.app_name == "Microsoft PowerPoint":
            for title in (task["title"], "Decisions", "Next steps"):
                slide = document.Slides.Add(document.Slides.Count + 1, 12)
                slide.Shapes.AddTextbox(1, 36, 36, 600, 120).TextFrame.TextRange.Text = title
            textbox = document.Slides(1).Shapes(1).TextFrame.TextRange
        create_ms = (time.perf_counter() - started) * 1000
        try:
            for index in range(5):
                started = time.perf_counter()
                marker = task["title"] + " revision " + str(index + 1) + " " + token
                if self.app_name == "Microsoft Word":
                    body = marker + "\rAgenda: review the disposable draft.\rOwner: Alex; next action: check the saved notes."
                    document.Content.Text = body
                    readback = str(document.Content.Text)
                    # Word keeps a mandatory final paragraph mark, which is
                    # not supplied by the requested body text.
                    ok = body + "\r" == readback
                elif self.app_name == "Microsoft Excel":
                    title_range.Value = marker
                    amount_range.Value = 12 + index
                    self.application.Calculate()
                    readback = {"title": str(title_range.Value), "total": float(total_range.Value)}
                    expected_total = 87 + 2 * index if task["id"] == "excel-invoice" else 75 + index
                    ok = readback == {"title": marker, "total": float(expected_total)}
                else:
                    textbox.Text = marker + "\rDiscuss the draft, assign an owner, agree the next step."
                    readback = str(textbox.Text)
                    ok = marker in readback
                actions.append({"step": "revise-and-readback", "revision": index + 1, "ok": ok,
                    "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "readback": readback, "modelTokens": 0})
                if not ok:
                    raise RuntimeError("Application readback differs: " + repr(readback) + " expected " + repr(body if self.app_name == "Microsoft Word" else marker))
            started = time.perf_counter()
            if self.app_name == "Microsoft Word":
                document.SaveAs2(str(path), 16)
                document.Close(False)
                self.documents.remove(document)
                document = self.application.Documents.Open(str(path), False, True, False)
                self.documents.append(document)
                reopened = str(document.Content.Text)
                reopen_ok = reopened == body + "\r"
            elif self.app_name == "Microsoft Excel":
                document.SaveAs(str(path), 51)
                document.Close(False)
                self.documents.remove(document)
                document = self.application.Workbooks.Open(str(path), 0, True)
                self.documents.append(document)
                total_cell = "D5" if task["id"] == "excel-invoice" else "B5"
                formula = "=SUM(D2:D4)" if task["id"] == "excel-invoice" else "=SUM(B2:B4)"
                reopened = {"title": str(document.Worksheets(1).Range("A1").Value),
                    "formula": str(document.Worksheets(1).Range(total_cell).Formula),
                    "total": float(document.Worksheets(1).Range(total_cell).Value)}
                reopen_ok = reopened == {"title": marker, "formula": formula,
                    "total": 95.0 if task["id"] == "excel-invoice" else 79.0}
            else:
                document.SaveAs(str(path), 24)
                document.Close()
                self.documents.remove(document)
                document = self.application.Presentations.Open(str(path), True, False, False)
                self.documents.append(document)
                reopened = {"text": str(document.Slides(1).Shapes(1).TextFrame.TextRange.Text), "slides": int(document.Slides.Count)}
                reopen_ok = marker in reopened["text"] and reopened["slides"] == 3
            persistence_ms = round((time.perf_counter() - started) * 1000, 3)
            artifact = _artifact(path)
            artifact["markerPresent"] = marker in artifact.pop("xmlText")
            self._checked()
            return {"id": task["id"], "app": self.app_name, "goal": task["goal"],
                "ok": bool(reopen_ok and artifact["markerPresent"]), "replay": replay,
                "firstObservation": before, "createDocumentMs": round(create_ms, 3), "actions": actions,
                "persistAndReopenMs": persistence_ms, "applicationReopen": reopened,
                "artifact": artifact, "modelTokens": 0,
                "replayMechanism": "fixed Office object-model steps, replayed with fresh readback; not a learned manual-compiler flow"}
        finally:
            # Release cached children before Quit; PowerPoint keeps its server
            # alive while a slide or text-range COM proxy is referenced.
            sheet = title_range = amount_range = total_range = slide = textbox = None
            if document in self.documents:
                if self.app_name == "Microsoft PowerPoint":
                    document.Close()
                else:
                    document.Close(False)
                self.documents.remove(document)

    def close(self):
        if self.application is not None and self.owned:
            try:
                live = psutil.Process(self.pid)
                if live.create_time() != self.birth:
                    raise RuntimeError("Office PID identity changed before cleanup")
                for document in list(self.documents):
                    document.Close() if self.app_name == "Microsoft PowerPoint" else document.Close(False)
                self.documents.clear()
                self.application.Quit()
                self.application = None
                gc.collect()
                try:
                    live.wait(8)
                    exited = True
                except psutil.TimeoutExpired:
                    exited = False
                self.cleanup = {"ok": exited, "pid": self.pid, "birth": self.birth,
                    "quitOnlyOwnedInstance": True, "processExited": exited, "closedDocuments": True}
            except Exception as exc:
                self.cleanup["error"] = type(exc).__name__ + ": " + str(exc)
        elif self.application is not None:
            self.application = None
            self.cleanup = {"ok": True, "quitOnlyOwnedInstance": True, "reusedInstanceUntouched": True}
        if getattr(self, "com_initialized", False):
            self.pythoncom.CoUninitialize()
            self.com_initialized = False
        return self.cleanup


def run_office_tasks(root, guard=None, apps=None):
    """Run five distinct everyday document tasks, then zero-token replays."""
    from .cua_guard import ZeroDisturbanceGuard
    root = Path(root).resolve()
    target = root / ".agent_control" / "c11f-office" / uuid.uuid4().hex
    target.mkdir(parents=True)
    own_guard = guard is None
    guard = guard or ZeroDisturbanceGuard().start()
    result = {"schema": "neyvia.c11f.office.v1", "at": datetime.now(timezone.utc).isoformat(),
        "token": target.name, "boundary": "new hidden COM applications; disposable documents only",
        "apps": [], "tasks": [], "modelTokens": 0, "launchLatencyExcludedFromObservation": True}
    result["sourceSha256"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("src/grant_agent/cua_office.py", "src/grant_agent/cua_guard.py",
                     "scripts/prove_c11f_office.py")}
    try:
        if not guard.snapshot()["ok"]:
            raise RuntimeError("Guard is not ready")
        for app in (apps or APPS):
            row = {"app": app, "ok": False}
            session = None
            try:
                session = OfficeSession(app, target, guard)
                row.update(ownership=session.ownership, launchMs=session.launch_ms, firstObservation=session.observe())
                for replay in range(2):
                    for task in TASKS:
                        if task["app"] == app:
                            result["tasks"].append(session.run_task(task, replay))
                row["ok"] = True
            except Exception as exc:
                row["error"] = type(exc).__name__ + ": " + str(exc)
            finally:
                if session:
                    row["cleanup"] = session.close()
                    row["ok"] = row["ok"] and row["cleanup"]["ok"]
                result["apps"].append(row)
        result["guard"] = guard.close() if own_guard else guard.snapshot()
    finally:
        if own_guard and "guard" not in result:
            result["guard"] = guard.close()
    timings = [step["elapsedMs"] for task in result["tasks"] for step in task["actions"]]
    result["actionAndReadbackP50Ms"] = statistics.median(timings) if timings else None
    result["distinctTasksCompleted"] = len({t["id"] for t in result["tasks"] if t["ok"] and not t["replay"]})
    result["appsCompleted"] = sum(row["ok"] for row in result["apps"])
    result["deterministicReplayTasksCompleted"] = sum(t["ok"] and t["replay"] > 0 for t in result["tasks"])
    result["ok"] = bool(result["apps"] and all(row["ok"] for row in result["apps"]) and
        all(t["ok"] for t in result["tasks"]) and result["guard"]["ok"])
    return result
