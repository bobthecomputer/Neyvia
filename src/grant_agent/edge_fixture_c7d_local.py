"""Owned local completion fixtures, with exact invariant/effect bindings.

These are production calls and durable readbacks, never a rendered UI claim.
Workers run hidden with the existing credential guard and explicit proof port.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .edge_fixture_local import require, refused, sha, _parallel, replacement_fault

CATEGORIES = ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
MODULE = "grant_agent.edge_fixture_c7d_local"


def _snapshot(service):
    with service.bus.connect() as db:
        return {"state": [list(row) for row in db.execute("SELECT key,value FROM state ORDER BY key")],
                "events": [list(row) for row in db.execute("SELECT id,ts,action,payload FROM events ORDER BY id")]}


@contextmanager
def _deny_child_creation(folder, root, *, deny_access_mask=0x6, inherit_children=False):
    """Temporarily deny explicit rights in one owned disposable directory.

    The default denies child creation. Receipt publishers can instead permit
    tempfile staging and deny inherited DELETE at the actual rename boundary.
    """
    import ctypes
    folder.resolve().relative_to(root.resolve())
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security.GetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    security.SetFileSecurityW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    security.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
    security.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint32)]
    security.SetNamedSecurityInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    size = ctypes.c_uint32()
    security.GetFileSecurityW(str(folder), 4, None, 0, ctypes.byref(size))
    require(size.value > 0, "Owned directory ACL snapshot unavailable")
    previous = ctypes.create_string_buffer(size.value)
    require(security.GetFileSecurityW(str(folder), 4, previous, size.value, ctypes.byref(size)), "Owned directory ACL read failed")
    present, defaulted, old_dacl = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
    old_control, revision = ctypes.c_uint16(), ctypes.c_uint32()
    require(security.GetSecurityDescriptorDacl(previous, ctypes.byref(present), ctypes.byref(old_dacl), ctypes.byref(defaulted)) and security.GetSecurityDescriptorControl(previous, ctypes.byref(old_control), ctypes.byref(revision)), "Owned directory original DACL unavailable")
    old_acl = ctypes.string_at(old_dacl, ctypes.c_uint16.from_address(old_dacl.value + 2).value)
    descriptor = ctypes.c_void_p()
    inheritance = "OICI" if inherit_children else ""
    sddl = f"D:(D;{inheritance};0x{int(deny_access_mask):x};;;WD)(A;{inheritance};FA;;;WD)"
    require(security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None), "Owned directory deny descriptor invalid")
    try:
        require(security.SetFileSecurityW(str(folder), 4, descriptor), "Owned directory child creation denial failed")
        yield
    finally:
        try:
            information = 4 | (0x80000000 if old_control.value & 0x1000 else 0x20000000)
            require(security.SetNamedSecurityInfoW(str(folder), 1, information, None, None, old_dacl, None) == 0, "Owned directory ACL restoration failed")
            restored_size = ctypes.c_uint32()
            security.GetFileSecurityW(str(folder), 4, None, 0, ctypes.byref(restored_size))
            restored = ctypes.create_string_buffer(restored_size.value)
            require(security.GetFileSecurityW(str(folder), 4, restored, restored_size.value, ctypes.byref(restored_size)), "Restored owned directory ACL read failed")
            current_dacl, current_control = ctypes.c_void_p(), ctypes.c_uint16()
            security.GetSecurityDescriptorDacl(restored, ctypes.byref(present), ctypes.byref(current_dacl), ctypes.byref(defaulted))
            security.GetSecurityDescriptorControl(restored, ctypes.byref(current_control), ctypes.byref(revision))
            restored_acl = ctypes.string_at(current_dacl, ctypes.c_uint16.from_address(current_dacl.value + 2).value)
            require(restored_acl == old_acl and (current_control.value & 0x1000) == (old_control.value & 0x1000), "Restored owned directory DACL entries/inheritance differ from the original")
        finally:
            kernel.LocalFree(descriptor)


def _settings(root, category):
    from .neyvia_workspace_tools import workspace_for
    from . import neyvia_settings as settings
    from .neyvia_view_tools import call as view
    service = workspace_for(root)
    before = settings.get(service)
    initial = _snapshot(service)
    denied = None
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        for operation in ("settings", "theme", "ambient", "transparency"):
            process = subprocess.run([sys.executable, "-m", MODULE, "--root", str(root), "--port", os.environ["NEYVIA_C7_PORT"], "--crash-operation", operation],
                                     capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
            require(process.returncode == 23, "Settings/view worker did not exit inside its SQLite transaction: " + operation)
            require(_snapshot(service) == initial, "Interrupted Settings/view transaction committed partial state/events: " + operation)
    elif category == "permissions":
        from .edge_fixture_core import denied as sharing
        with sharing(service.bus.path):
            denied = refused(lambda: settings.update(service, {"theme": "morning"}, before["revision"]), sqlite3.Error)
            refused(lambda: view(service, "view.theme", {"theme": "night"}), sqlite3.Error)
            refused(lambda: view(service, "view.ambient", {"on": False}), sqlite3.Error)
            refused(lambda: view(service, "view.transparency", {"level": "minimal"}), sqlite3.Error)
        require(_snapshot(service) == initial, "OS-denied Settings transaction changed state/events")
    # Every category first exercises real rejected input and independently reads
    # all durable state and events. Empty/huge/unicode use the declared bounds.
    invalid = {} if category == "empty" else {"projectInitiative": {str(root / str(i)): "suggest" for i in range(201)}} if category == "huge" else {"theme": "forest\x00雪"} if category == "unicode" else {"density": False}
    denied_patch = refused(lambda: settings.update(service, invalid, settings.get(service)["revision"]))
    require(_snapshot(service) == initial, "Rejected Settings input changed state or events")
    observed = settings.get(service)
    patch = {"theme": "morning", "density": "grove", "nightShift": {"paused": True}, "cleanup": {"autoArchive": False}}
    if category == "unicode":
        patch["projectInitiative"] = {str(root / "雪🙂"): "suggest"}
    elif category == "huge":
        patch["projectInitiative"] = {str(root / str(i)): "suggest" for i in range(200)}
    if category == "concurrency":
        def write(theme):
            try:
                return settings.update(service, {**patch, "theme": theme}, observed["revision"])
            except settings.SettingsConflict:
                return {"conflict": True}
        outcomes = _parallel(write, ["morning", "sunset"])
        require(sum(bool(row.get("conflict")) for row in outcomes) == 1, "Competing Settings writes did not yield one CAS conflict")
        result = next(row for row in outcomes if not row.get("conflict"))
    else:
        result = settings.update(service, patch, observed["revision"])
    require(result["revision"] == observed["revision"] + 1, "Canonical Settings revision increment differs")
    saved = settings.get(service)
    require(saved["settings"] == result["settings"], "Settings durable readback differs")
    require(service.bus.get("theme") == settings.THEMES[result["settings"]["theme"]]
            and service.bus.get("density") == {"level": "grove"}
            and service.bus.get("cleanupPolicy") == result["settings"]["cleanup"]
            and service.bus.get("nightshift.resources") == result["settings"]["nightShift"], "Canonical Settings mirror differs")
    with service.bus.connect() as db:
        for event in result["events"]:
            row = db.execute("SELECT action,payload FROM events WHERE id=?", (event["id"],)).fetchone()
            require(row["action"] == event["action"] and json.loads(row["payload"]) == event["payload"], "Settings event differs from durable receipt")
    require(sum(row["action"] == "nightshift.resources.updated" for row in result["events"]) == 1, "Night update event count differs")
    preserved = _snapshot(service)
    refused(lambda: settings.update(service, {"theme": "sunset"}, observed["revision"]), settings.SettingsConflict)
    require(_snapshot(service) == preserved, "Stale Settings write changed state/events")
    theme_result = view(service, "view.theme", {"theme": "night"})
    require(theme_result["ok"] and settings.get(service)["settings"]["theme"] == "night-green" and service.bus.get("theme") == "night", "Legacy theme did not reach canonical Settings")
    for level in ("everything", "summaries", "minimal"):
        require(view(service, "view.transparency", {"level": level})["ok"] and service.bus.get("transparency") == level, "Transparency durable value differs")
    for on in (True, False):
        require(view(service, "view.ambient", {"on": on})["ok"] and service.bus.get("ambient") is on, "Ambient durable value differs")
    if category == "concurrency":
        themes = _parallel(lambda theme: view(service, "view.theme", {"theme": theme}), ["light", "night"])
        require(len({row["revision"] for row in themes}) == 2, "Concurrent legacy themes did not commit separate canonical revisions")
        latest = max(themes, key=lambda row: row["revision"])
        require(settings.get(service)["settings"]["theme"] == latest["settings"]["theme"], "Concurrent legacy theme last durable revision differs")
        _parallel(lambda _: view(service, "view.ambient", {"on": True}), [0, 1])
        _parallel(lambda _: view(service, "view.transparency", {"level": "minimal"}), [0, 1])
        require(service.bus.get("ambient") is True and service.bus.get("transparency") == "minimal", "Concurrent identical view updates lost their exact durable choice")
    if category in {"empty", "huge", "unicode"}:
        invalid_choice = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂\x00"
        prior_view = _snapshot(service)
        refused(lambda: view(service, "view.theme", {"theme": invalid_choice}))
        refused(lambda: view(service, "view.transparency", {"level": invalid_choice}))
        refused(lambda: view(service, "view.ambient", {"on": invalid_choice}))
        require(_snapshot(service) == prior_view, "Invalid view control changed persisted values/events")
    return list(settings.CONTRACTS) if hasattr(settings, "CONTRACTS") else ["settings.revision-cas", "settings.invalid-preserves", "settings.canonical-mirrors", "settings.night-policy-event", "settings.legacy-theme", "settings.view-durable"], {"revision": settings.get(service)["revision"], "rejection": denied_patch, "osDenial": denied, "interruptedExit": 23 if category == "interrupted" else None, "durableFingerprint": sha(json.dumps(_snapshot(service), sort_keys=True).encode())}


def _gateway(root, category):
    from .proof_credential_guard import prepare_broker_fixture
    from .neyvia_agent import NeyviaToolGateway
    prepare_broker_fixture(root)
    gateway = NeyviaToolGateway(root, allow_mutations=False, permission_mode="read-only")
    body = "" if category == "empty" else "x" * (1024 * 1024 + 1) if category == "huge" else "雪🙂\x00" if category == "unicode" else "owned"
    target = root / "mutation-parent" / "forbidden.txt"
    call = lambda _: refused(lambda: gateway.call_native("workspace.write", {"path": "mutation-parent/forbidden.txt", "content": body}))
    results = _parallel(call, [0, 1]) if category == "concurrency" else [call(0)]
    require(not target.exists() and not target.parent.exists(), "Read-only gateway created parent/target")
    return ["c7.gateway.read-only"], {"denials": results, "targetAbsent": True, "parentAbsent": True}


def _workspace(root, category):
    from .native_tools import NativeToolRegistry
    registry = NativeToolRegistry(root, nas_root=root)
    target = root / "effect.txt"
    original = "keeper 雪🙂".encode()
    target.write_bytes(original)
    write = lambda: registry.call("workspace.write", {"path": "effect.txt", "content": "replacement", "expectedSha256": sha(original)})
    if category == "permissions":
        from .edge_fixture_core import denied
        with denied(target):
            result = refused(write, (OSError, ValueError))
    else:
        from . import native_tools
        with replacement_fault(native_tools, target, KeyboardInterrupt) as calls:
            result = refused(write, KeyboardInterrupt)
        require(calls, "Workspace commit replacement seam was never reached")
    require(target.read_bytes() == original, "Denied/interrupted workspace replacement changed bytes")
    require(write().get("ok") and target.read_bytes() == b"replacement", "Workspace replacement did not recover after denial/interruption")
    return ["c7.workspace.rejected-preserves"], {"refusal": result, "originalPreserved": True, "retryVerified": True}


def _impact(root, category):
    from . import neyvia_impact as impact
    # Parser scans an actual disposable source tree through its existing repo seam.
    def write(name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")
    count = 180 if category == "huge" else 0 if category == "empty" else 3
    commands = [f"owned_{i}_command" for i in range(count)]
    noise = "雪🙂 שלום" if category == "unicode" else "owned"
    write("web/src/neyvia/next/Owned.jsx", "// " + noise + "\n" + "\n".join("callBackend('" + name + "', {})" for name in commands))
    write("src/grant_agent/web_backend.py", "def dispatch(command):\n" + ("\n".join("    if command == '" + name + "':\n        return {}" for name in commands[:-1]) or "    return None"))
    write("src/grant_agent/desktop_bridge.py", "ALLOWED_DESKTOP_COMMANDS = " + repr(set(commands[:1])))
    write("src-tauri/src/main.rs", "#[tauri::command]\nfn unregistered_command() {}\ngenerate_handler![]")
    write("tests/owned.py", "# " + noise + " " + " ".join(commands[:1]))
    write("docs/manuals/owned.md", noise + " " + " ".join(commands[:1]))
    idx = impact.index(root)
    gaps = impact.find_gaps(idx)
    expected = {"uiWithoutHandler": commands[-1:] if commands else [], "nextUiMissingFromBridge": commands[1:-1], "bridgeWithoutHandler": [], "tauriNotRegistered": ["unregistered_command"], "handlerWithoutCaller": [], "handlerOnlyScriptsOrTests": [], "toolWithoutManual": []}
    require(all(gaps[name]["items"] == sorted(rows) for name, rows in expected.items()), "Parsed impact gap sets differ from generated source tree")
    def project(_):
        rows = [impact._command_row(idx, name) for name in commands]
        for i, row in enumerate(rows):
            require(row["ui"] == ["web/src/neyvia/next/Owned.jsx"] and bool(row["handler"]) == (i < count - 1) and row["bridge"] == (i == 0) and not row["tauri"], "Impact command ends differ from source tree")
            require(row["tests"] == (["tests/owned.py"] if i == 0 else []) and row["manuals"] == (["docs/manuals/owned.md"] if i == 0 else []), "Impact test/manual callers differ")
        return rows
    rows = _parallel(project, [0, 1]) if category == "concurrency" else [project(0)]
    if category == "stale":
        write("src/grant_agent/desktop_bridge.py", "ALLOWED_DESKTOP_COMMANDS = " + repr(set(commands)))
        refreshed = impact.index(root)
        require(refreshed["bridge"] == set(commands) and not impact.find_gaps(refreshed)["nextUiMissingFromBridge"]["items"], "Impact index reused stale file facts")
    return ["awareness.impact.gaps", "awareness.impact.command"], {"parsedCommands": count, "projectionSamples": len(rows), "exactSourceSetsVerified": True, "sourceRefresh": category == "stale"}


def _staleness(root, category):
    from . import neyvia_awareness as board
    if category in {"empty", "huge", "unicode"}:
        invalid_stamp = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂"
        projected = board._view({"since": invalid_stamp, "updatedAt": invalid_stamp})
        require(projected["ageMinutes"] == 0 and not projected["stale"], "Malformed/missing awareness date invented old activity")
    receipt = board.claim(root, {"files": ["雪/owned"], "agent": "owned", "intent": "Owned state"})
    path = board.board_path(root)
    saved = json.loads(path.read_text(encoding="utf8"))
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    saved["claims"][0].update(since=old, updatedAt=old)
    path.write_text(json.dumps(saved), encoding="utf8")
    observer = lambda _: board.board_list(root)
    samples = _parallel(observer, [0, 1]) if category == "concurrency" else [observer(0)]
    require(all(row["stale"] == 1 and row["claims"][0]["ageMinutes"] >= 780 for row in samples), "Old awareness claim did not project stale age")
    refreshed = board.claim(root, {"files": ["雪/owned"], "agent": "owned", "intent": "Refreshed owned state"})
    require(refreshed["claim"]["id"] == receipt["claim"]["id"] and refreshed["claim"]["since"] == old and not refreshed["claim"]["stale"] and refreshed["claim"]["ageMinutes"] >= 780, "Awareness refresh changed age or retained stale activity")
    return ["awareness.claim.staleness"], {"ageMinutes": refreshed["claim"]["ageMinutes"], "staleAfterRefresh": False}


def _recycle(root, category):
    from .neyvia_files_tools import parse_recycle_info
    text = "" if category == "empty" else "C:\\" + "x" * 32760 if category == "huge" else "C:\\owned\\雪🙂.txt" if category == "unicode" else "C:\\owned\\file.txt"
    size, deleted = 513, 133700000000000000
    raw_path = (text + "\0").encode("utf-16-le")
    record = struct.pack("<qqqi", 2, size, deleted, len(raw_path) // 2) + raw_path
    def decode(_):
        result = parse_recycle_info(record)
        require(result == {"path": text, "size": size, "deleted": deleted}, "Decoded recycle record differs from binary fields")
        return result
    results = _parallel(decode, [0, 1]) if category == "concurrency" else [decode(0)]
    for invalid in (b"", struct.pack("<qqqi", 2, size, deleted, len(raw_path) + 100) + raw_path, struct.pack("<qqqi", 2, size, deleted, -1) + raw_path):
        refused(lambda: parse_recycle_info(invalid), (ValueError, struct.error, UnicodeError))
    legacy_path = "C:\\owned\\雪🙂.txt" if category == "unicode" else "" if category == "empty" else "C:\\" + "v" * 250 if category == "huge" else "C:\\owned\\legacy.txt"
    legacy = struct.pack("<qqq", 1, size, deleted) + (legacy_path + "\0").encode("utf-16-le").ljust(520, b"\0")
    require(parse_recycle_info(legacy) == {"path": legacy_path, "size": size, "deleted": deleted}, "Legacy v1 recycle record differs from its independently packed fields")
    refused(lambda: parse_recycle_info(struct.pack("<qqq", 3, size, deleted)), ValueError)
    return ["files.recycle-record"], {"bytes": len(record), "sha256": sha(record), "samples": len(results), "versions": [1, 2], "malformedLengthsRefused": True, "boundary": "binary record parser only; no actual OS recycle operation inferred"}


def _delivery_action(root, operation, index=0):
    from . import delivery_receipt as delivery
    from .models import DeliveryReceipt, MissionEvent
    receipt = DeliveryReceipt(receipt_id="owned-0" if operation in {"update", "ack"} else f"owned-new-{index}", mission_id="owned", channel="local", destination="control-room", event_kind="progress", event_message=f"new owned event {index}", sent_at="2026-10-04T00:00:00Z", status="delivered")
    if operation == "append": return delivery._append_receipt(root, receipt)
    if operation == "update": return delivery._update_last_receipt(root, receipt)
    if operation == "tail-update": return delivery._update_receipt(root, receipt)
    if operation == "ack": return delivery.acknowledge_delivery_receipt(root, "owned-0")
    if operation == "observe": return delivery.load_receipts(root, mission_id="owned", limit=2)
    if operation == "browser": return delivery.record_browser_delivery_receipt(MissionEvent(mission_id="owned", kind="progress", message=f"new owned event {index}"), root=root)
    if operation == "skipped": return delivery.send_approval_escalation_receipt(mission_id="owned", prompt=f"new owned event {index}", risk_level="low", escalation_policy={"enabled": False}, root=root)
    raise ValueError(operation)


def _delivery(root, category):
    from . import delivery_receipt as delivery
    from .models import DeliveryReceipt
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from dataclasses import asdict
    operations = ("append", "update", "tail-update", "ack", "observe", "browser", "skipped")
    checked = []
    details = []
    for operation in operations:
        case = root / operation
        case.mkdir(parents=True, exist_ok=True)
        path = delivery.delivery_receipts_path(case)
        for index in range(3):
            delivery._append_receipt(case, DeliveryReceipt(receipt_id=f"owned-{index}", mission_id="owned" if index != 1 else "other", channel="local", destination="control-room", event_kind="progress", event_message=f"keeper {index}", sent_at="2026-10-04T00:00:00Z", status="delivered"))
        baseline = path.read_bytes()
        if category == "interrupted":
            if operation == "observe":
                continue
            process = subprocess.run([sys.executable, "-m", MODULE, "--root", str(case), "--port", os.environ["NEYVIA_C7_PORT"], "--crash-delivery", operation], capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
            require(process.returncode == 23, "Owned delivery worker did not exit at real journal commit: " + operation)
            require(path.read_bytes() == baseline, "Interrupted delivery journal lost retained prior rows: " + operation)
        elif category == "permissions":
            from .edge_fixture_core import denied
            with denied(path):
                refused(lambda: _delivery_action(case, operation), (OSError, ValueError))
            require(path.read_bytes() == baseline, "OS-denied delivery changed retained journal: " + operation)
        elif category == "stale":
            observed = delivery.load_receipts(case, limit=0)
            delivery._append_receipt(case, DeliveryReceipt(receipt_id="fresh-other", mission_id="other", channel="local", destination="control-room", event_kind="progress", event_message="fresh durable state", sent_at="2026-10-04T00:00:00Z", status="delivered"))
            require(len(delivery.load_receipts(case, limit=0)) == len(observed) + 1, "Existing delivery observer reused stale journal")
        if category == "concurrency":
            # For producers, two genuinely distinct effect-bearing invocations
            # race on one retained journal. Tail replacement is independently
            # checked for retained-prefix conservation; it is never ID replace.
            results = _parallel(lambda index: _delivery_action(case, operation, index), [0, 1])
        else:
            results = [_delivery_action(case, operation)]
        current = delivery.load_receipts(case, limit=0)
        records = [asdict(row) for row in current]
        initial_prefix = baseline.decode().splitlines()[:2]
        require(path.read_text(encoding="utf-8").splitlines()[:2] == initial_prefix if operation in {"tail-update", "append", "browser", "skipped", "observe"} else all(any(row["receipt_id"] == f"owned-{i}" and row["event_message"] == f"keeper {i}" for row in records) for i in (1, 2)), "Delivery mutation changed unrelated retained rows: " + operation)
        if operation == "observe":
            require(all([asdict(row) for row in result] == [row for row in records if row["mission_id"] == "owned"][-2:] for result in results), "Delivery observation filtered after limit")
        elif operation == "ack":
            require(next(row for row in records if row["receipt_id"] == "owned-0")["status"] == "acknowledged", "Delivery acknowledgement did not persist")
        elif operation in {"append", "browser", "skipped", "update"}:
            for result in results:
                expected = asdict(result)
                require(any(row == expected for row in records) if operation != "update" or category != "concurrency" else any(row["receipt_id"] == expected["receipt_id"] for row in records), "Delivery returned receipt absent from durable journal: " + operation)
        checked.append("delivery." + operation)
        details.append({"operation": operation, "retainedRows": len(current), "journalSha256": sha(path.read_bytes()), "osDenied": category == "permissions", "interruptedExit": 23 if category == "interrupted" else None})
    return checked, {"operations": details}


def _terminal(root, category):
    from .web_backend import _clean_terminal_text
    content = b"" if category == "empty" else b"x" * 200000 if category == "huge" else "雪🙂é שלום".encode() + b"\xff"
    cases = (content, b"\x1b[31m" + content + b"\x1b[0m\r\nend\r", b"\r\r\n" + content)
    expected = (content.decode("utf8", errors="replace"), content.decode("utf8", errors="replace") + "\nend\n", "\n\n" + content.decode("utf8", errors="replace"))
    actual = [_clean_terminal_text(value) for value in cases]
    require(actual == list(expected), "Terminal byte decoding/ANSI stripping/newline normalization changed readable content")
    return ["proofs-e-wz.terminal-text"], {"byteCases": len(cases), "inputBytes": len(content), "outputSha256": sha(json.dumps(actual).encode())}


def _budget(root, category):
    from .efficient_workflow import build_efficient_workflow
    text = "Owned budget fixture 雪🙂" if category == "unicode" else "x" * 12000 if category == "huge" else "Owned budget fixture"
    for seconds in (None, 120, 1800):
        payload = {"objective": text, **({"runtimeSeconds": seconds} if seconds is not None else {})}
        result = build_efficient_workflow(root, payload)
        expected = 180 if seconds is None else seconds
        require(result["preset"]["runtimeSeconds"] == expected and all(task["teamContract"]["budget"]["runtimeSeconds"] == expected for task in result["tasks"]), "Workflow stage budget differs from selected normalized number")
    invalid = "" if category == "empty" else 10 ** 50 if category == "huge" else "雪🙂" if category == "unicode" else 119
    refused(lambda: build_efficient_workflow(root, {"objective": text, "runtimeSeconds": invalid}))
    if category == "concurrency":
        results = _parallel(lambda seconds: build_efficient_workflow(root, {"objective": text, "runtimeSeconds": seconds}), [120, 1800])
        require([result["preset"]["runtimeSeconds"] for result in results] == [120, 1800] and all(all(task["teamContract"]["budget"]["runtimeSeconds"] == result["preset"]["runtimeSeconds"] for task in result["tasks"]) for result in results), "Concurrent workflow budgets leaked between caller-owned requests")
    return ["proofs-e-wz.workflow-budget"], {"acceptedSeconds": [180, 120, 1800], "invalidBudgetRefused": True, "planningOnly": True, "providerCalls": 0}


def _capture(root, category):
    from .web_backend import _run_process_capture
    source = root / "owned-child.py"
    text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned child failure"
    source.write_text("import sys,time\ntext=sys.stdin.buffer.read().decode('utf8')\nsys.stderr.write(text)\nsys.stderr.flush()\n" + ("time.sleep(30)\n" if category == "interrupted" else "raise SystemExit(3)\n"), encoding="utf8")
    def invoke(_):
        try:
            _run_process_capture([sys.executable, str(source)], cwd=root, timeout=1 if category == "interrupted" else 10, stdin_text=text)
        except Exception as error:
            require(getattr(error, "process_id", 0) > 0 and getattr(error, "elapsed_ms", -1) >= 0 and getattr(error, "started_at", "") and getattr(error, "ended_at", "") >= error.started_at, "Process failure lacks invocation-bound pid/time evidence")
            return {"pid": error.process_id, "elapsedMs": error.elapsed_ms, "startedAt": error.started_at, "endedAt": error.ended_at, "failureType": type(error).__name__, "diagnosticChars": len(str(error))}
        raise AssertionError("Failed/timed-out owned child returned completed")
    if category == "permissions":
        from .edge_fixture_core import denied
        with denied(source):
            results = [invoke(0)]
    else:
        results = _parallel(invoke, [0, 1]) if category == "concurrency" else [invoke(0)]
    require(len({row["pid"] for row in results}) == len(results), "Independent process failures shared an invocation pid")
    # Successful malformed child output has the same invocation diagnostics.
    malformed = root / "malformed.py"
    # Python's JSON integer digit bound is an actual parser refusal, whereas
    # ordinary plain terminal text is intentionally accepted by this adapter.
    malformed.write_text("print('9' * 5000)\n", encoding="utf8")
    malformed_pid = None
    try:
        _run_process_capture([sys.executable, str(malformed)], cwd=root, timeout=10)
    except Exception as error:
        require(getattr(error, "process_id", 0) > 0 and getattr(error, "elapsed_ms", -1) >= 0 and error.ended_at >= error.started_at, "Malformed successful child lost invocation timing")
        malformed_pid = error.process_id
    else:
        raise AssertionError("Malformed child output was admitted as model result")
    return ["proofs-e-wz.capture-failure"], {"invocations": results, "malformedFailurePid": malformed_pid, "malformedOutputRefused": True}


def _authored(root, category):
    """Actual reviewed local MCP stdio, manifest adoption and output checks."""
    from .proof_credential_guard import prepare_broker_fixture
    from .capability_service import CapabilityService
    from .tool_factory import AuthoredToolStore
    prepare_broker_fixture(root)
    definition = {"name": "echo", "description": "Owned fixture echo", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                  "outputSchema": {"type": "object", "properties": {"ok": {"type": "boolean"}, "text": {"type": "string"}}, "required": ["ok", "text"], "additionalProperties": False}}
    source = root / "owned_mcp.py"
    source.write_text("import json,sys,os\nfrom pathlib import Path\nsys.stdin.reconfigure(encoding='utf8')\nsys.stdout.reconfigure(encoding='utf8')\nfor line in sys.stdin:\n request=json.loads(line)\n if 'id' not in request: continue\n method=request.get('method')\n if method=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'owned-fixture','version':'1'}}\n elif method=='tools/list': result={'tools':[" + repr(definition) + "]}\n elif method=='tools/call':\n  text=request['params']['arguments']['text']\n  with Path(sys.argv[1]).open('a',encoding='utf8') as log: log.write(json.dumps({'text':text},ensure_ascii=False)+'\\n')\n  if text=='interrupt-owned-worker': os._exit(23)\n  value={'ok':True,'text':text} if text!='invalid-owned-output' else {'ok':True,'text':5}\n  result={'content':[{'type':'text','text':json.dumps(value)}],'structuredContent':value,'isError':False}\n else: result={}\n print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)\n", encoding="utf8")
    effect = root / "stdio-effects.jsonl"
    config = root / ".agent_control/mcp_broker.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"schema": "neyvia.mcp_broker_config.v1", "servers": {"owned-echo": {"transport": "stdio", "command": sys.executable, "args": [str(source), str(effect)], "framing": "newline", "authState": "authenticated", "tools": [definition]}}}), encoding="utf8")
    service = CapabilityService(root)
    try:
        payload = {"sourceType": "mcp", "toolId": "owned.echo", "adapterId": "mcp.owned-echo", "server": "owned-echo", "sourceMetadata": {"provider": "owned-local", "version": "1", "license": "MIT"}, "source": definition}
        draft = service.adapt_authored_tool(payload)
        manifest = draft["manifest"]
        if category == "permissions":
            manifest["permissions"] = ["tool.manage"]
        saved = service.save_authored_tool({"tool": manifest, "approved": True})
        require(saved["ok"] and AuthoredToolStore(root).describe("owned.echo")["provenance"] == saved["tool"]["provenance"], "Adapted saved provenance not durable")
        text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned stdio data"
        grants = {"approvedPermissions": ["tool.manage"]} if category == "permissions" else {}
        if category == "permissions":
            denied = service.execute_authored_tool({"toolId": "owned.echo", "arguments": {"text": text}})
            require(denied["ok"] is False and denied["status"] in {"approval_required", "permission_denied"} and not effect.exists(), "Unapproved authored permission launched real server effect")
        if category == "interrupted":
            crashed = service.execute_authored_tool({"toolId": "owned.echo", "arguments": {"text": "interrupt-owned-worker"}})
            require(crashed["ok"] is False and crashed["status"] != "completed" and json.loads(effect.read_text(encoding="utf-8").splitlines()[-1])["text"] == "interrupt-owned-worker", "Killed stdio server fabricated completed output")
        execute = lambda content: service.execute_authored_tool({"toolId": "owned.echo", "arguments": {"text": content}, **grants})
        values = [text + "-first", text + "-second"] if category == "concurrency" else [text]
        results = _parallel(execute, values) if category == "concurrency" else [execute(text)]
        for content, result in zip(values, results):
            require(result["ok"] and result["status"] == "completed" and result["authoredOutputValidation"]["valid"] and result["result"]["structuredContent"] == {"ok": True, "text": content}
                    and result["provenance"] == saved["tool"]["provenance"], "Real adapted MCP output lost bytes/provenance or validation")
        invalid = execute("invalid-owned-output")
        require(invalid["ok"] is False and invalid["status"] == "failed" and invalid["authoredOutputValidation"]["valid"] is False, "Invalid typed external output was completed")
        if category == "stale":
            changed = json.loads(json.dumps(saved["tool"]))
            changed["outputSchema"]["properties"]["text"]["minLength"] = 100
            fresh = service.save_authored_tool({"tool": changed, "approved": True})
            require(fresh["ok"], "Replacement authored schema refused")
            stale_output = execute("short")
            require(not stale_output["ok"] and not stale_output["authoredOutputValidation"]["valid"], "Execution reused stale authored output schema")
        observed = [json.loads(line)["text"] for line in effect.read_text(encoding="utf8").splitlines()]
        require(all(content in observed for content in values), "Successful stdio response has no independently recorded server effect")
        return ["proofs-c.models.authored-execute"], {"transport": "actual owned local stdio JSON-RPC", "successfulCalls": len(results), "effects": len(observed), "effectSha256": sha(effect.read_bytes()), "invalidOutputRefused": True, "provenanceVerified": True, "liveExternalProviderProved": False}
    finally:
        if service._model_tool_broker:
            service._model_tool_broker.close()


def _benchmark(root, category):
    from .proof_credential_guard import prepare_broker_fixture
    from .capability_service import CapabilityService
    prepare_broker_fixture(root)
    service = CapabilityService(root)
    try:
        faults = []
        if category in {"permissions", "interrupted"}:
            from . import capability_service as owner
            from .edge_fixture_core import denied
            original = owner._atomic_json
            def refused_publication(path, payload):
                path.parent.mkdir(parents=True, exist_ok=True)
                sentinel = b'{"ownedPriorReceipt":true}'
                path.write_bytes(sentinel)
                try:
                    if category == "permissions":
                        with denied(path):
                            original(path, payload)
                    else:
                        with replacement_fault(owner, path, KeyboardInterrupt) as calls:
                            original(path, payload)
                finally:
                    require(path.read_bytes() == sentinel, "Refused benchmark receipt publication corrupted the owned preexisting target")
                    faults.append({"path": str(path), "preservedSha256": sha(path.read_bytes())})
            owner._atomic_json = refused_publication
            try:
                refused(lambda: service.benchmark_model_tool_routing({"cases": [{"task": "Analyze Excel spreadsheet", "expected": "office.spreadsheet-analysis"}]}), (OSError, KeyboardInterrupt))
            finally:
                owner._atomic_json = original
            require(len(faults) == 1, "Benchmark receipt refusal did not reach durable publication boundary")
        task = "Analyze Excel spreadsheet " + ("雪🙂é שלום" if category == "unicode" else "x" * 70000 if category == "huge" else "owned data")
        cases = [] if category == "empty" else [{"task": task, "expected": "office.spreadsheet-analysis", "limit": 4}] * (101 if category == "huge" else 1)
        payload = {"cases": cases}
        results = _parallel(lambda index: service.benchmark_model_tool_routing({"cases": [{"task": task + str(index), "expected": "office.spreadsheet-analysis", "limit": 2 + index}]}), [0, 1]) if category == "concurrency" else [service.benchmark_model_tool_routing(payload)]
        require(len({result["receiptPath"] for result in results}) == len(results), "Concurrent routing benchmarks overwrote one receipt identity")
        for result in results:
            recorded = json.loads(Path(result["receiptPath"]).read_text(encoding="utf8"))
            require(recorded == {key: value for key, value in result.items() if key != "receiptPath"}, "Routing benchmark returned evidence differs from durable exact result")
            rows = result["cases"]
            require(len(rows) <= 100 and result["summary"]["cases"] == len(rows), "Routing benchmark case bound/count differs")
            for name, limit in (("top1", 1), ("top3", 3), ("topK", None)):
                hits = [row["expected"] in row["selected"][:limit] for row in rows]
                require([row[name] for row in rows] == hits and result["summary"][name + "Accuracy"] == round(sum(hits) / max(1, len(rows)), 4), "Routing benchmark accuracy differs from selected identities")
        if category == "stale":
            prior_bytes = Path(results[0]["receiptPath"]).read_bytes()
            current = service.benchmark_model_tool_routing({"cases": [{"task": task, "expected": "owned.changed.expectation", "limit": 1}]})
            require(current["receiptPath"] != results[0]["receiptPath"] and current["cases"][0]["expected"] == "owned.changed.expectation" and current["cases"][0]["topK"] is False and Path(results[0]["receiptPath"]).read_bytes() == prior_bytes, "Fresh benchmark reused previous expectation/receipt or changed historical evidence")
            results.append(current)
        return ["proofs-c.models.benchmark"], {"receipts": [result["receiptPath"] for result in results], "caseCounts": [len(result["cases"]) for result in results], "exactDurableEvidence": True, "refusedPublications": faults, "providerExecutionProved": False}
    finally:
        if service._model_tool_broker:
            service._model_tool_broker.close()


def _notes(root, category):
    from . import neyvia_notes_tools as notes
    from .ui_command_bus import bus_for
    from .edge_fixture_core import denied
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    folder = root / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    bus_for(root).put("notes:folder", str(folder))
    note = lambda operation, args: notes.call_notes(root, operation, args, "ui")
    body = "" if category == "empty" else "x" * notes.MAX_BYTES if category == "huge" else "# Idée 日本語 🧭\nCafé #Été #été שלום" if category == "unicode" else "# Owned note\nBody #fixture"
    created = note("write", {"path": "owned.md", "body": body})
    path = folder / "owned.md"
    raw = body.encode()
    require(path.read_bytes() == raw and created["modified"] == str(path.stat().st_mtime_ns), "Notes initial durable UTF8/stamp differs")
    read = note("read", {"path": "owned.md"})
    require(read["body"] == body and read["title"] == ("owned" if category in {"empty", "huge"} else "Idée 日本語 🧭" if category == "unicode" else "Owned note") and read["tags"] == (["été"] if category == "unicode" else [] if category in {"empty", "huge"} else ["fixture"]), "Notes prose metadata differs from independent generated expectation")
    for value in (True, False):
        note("pin", {"path": "owned.md", "pinned": value})
        meta = json.loads((folder / notes.META).read_text(encoding="utf8"))
        require(("owned.md" in meta["pinned"]) == value, "Notes pin mutation not durably exact")
    for payload in ({"path": "../escape.md", "body": body}, {"path": "escape.exe", "body": body}, {"path": "owned.md", "body": "x" * (notes.MAX_BYTES + 1)}):
        refused(lambda: note("write", payload))
        require(path.read_bytes() == raw and not (root / "escape.md").exists() and not (folder / "escape.exe").exists(), "Rejected Notes path/byte bound changed bytes or escaped folder")
    with replacement_fault(notes, path, KeyboardInterrupt) as calls:
        refused(lambda: note("write", {"path": path.name, "body": body, "expectedModified": created["modified"]}), KeyboardInterrupt)
    require(calls and path.read_bytes() == raw and not list(folder.glob('.~*.tmp')), "Interrupted Notes replacement lost original or leaked temporary contents")
    with denied(path):
        refused(lambda: note("write", {"path": path.name, "body": body}), (PermissionError, OSError))
    require(path.read_bytes() == raw and not list(folder.glob('.~*.tmp')), "OS-denied Notes write changed original or leaked temporary contents")
    current = note("write", {"path": path.name, "body": body, "expectedModified": created["modified"]})
    require(current["ok"] and current["modified"] != created["modified"] and path.read_bytes() == raw, "Notes retry did not preserve exact body and advance its revision")
    stale = note("write", {"path": path.name, "body": "lost", "expectedModified": created["modified"]})
    require(stale["status"] == "conflict" and path.read_bytes() == raw, "Stale Notes CAS overwrote current body")
    # Same category-specific body is raced by two actual guarded processes.
    # Both observe one saved stamp; one wins even when the body bytes are equal.
    race = note("write", {"path": "race.md", "body": body})
    (root / "race-body.txt").write_text(body, encoding="utf8")
    processes = [subprocess.Popen([sys.executable, "-m", MODULE, "--root", str(root), "--port", os.environ["NEYVIA_C7_PORT"], "--note-worker", identity, "--note-stamp", race["modified"]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf8", **hidden_windows_subprocess_kwargs()) for identity in ("first", "second")]
    outcomes = []
    try:
        deadline = time.monotonic() + 20
        while not all((root / (identity + ".ready")).exists() for identity in ("first", "second")):
            require(time.monotonic() < deadline and all(process.poll() is None for process in processes), "Owned Notes race workers missed barrier")
            time.sleep(.01)
        (root / "go").write_text("owned barrier", encoding="utf8")
        for process in processes:
            output, error = process.communicate(timeout=30)
            require(process.returncode == 0, "Owned Notes writer failed: " + error[-500:])
            outcomes.append(json.loads(output))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    require(sum(bool(row.get("ok")) for row in outcomes) == 1 and sum(row.get("status") == "conflict" for row in outcomes) == 1 and (folder / "race.md").read_bytes() == raw, "Cross-process same-stamp Notes writers lost single-winner/CAS conservation")
    found = note("list", {})
    require(found["total"] == 2 and note("read", {"path": "race.md"})["body"] == body, "Offline guarded Notes observer lost local persisted content")
    return ["notes.body-durable", "notes.prose-metadata", "notes.pin-durable", "notes.path-jail", "notes.write-bounded", "notes.atomic-interruption", "notes.permission-preserves", "notes.stale-preserves", "notes.concurrent-writes", "notes.local-offline"], {"bytes": len(raw), "sha256": sha(raw), "atomicInterruptionPreserved": True, "nativeShareDenied": True, "raceStatuses": [row.get("status", "written") for row in outcomes], "raceProcesses": 2, "socketAuditEnforced": True}


def _files_trash(root, category):
    """Recover only generated owned files using the actual silent shell API."""
    from . import neyvia_files_tools as files
    from .edge_fixture_core import denied
    from .ui_command_bus import bus_for
    raw = b"" if category == "empty" else b"x" * 1048576 if category == "huge" else "雪🙂é שלום".encode() if category == "unicode" else b"owned recoverable bytes"
    stem = "雪🙂" if category == "unicode" else "owned"
    path = root / (stem + ".txt")
    path.write_bytes(raw)
    call = lambda operation, args: files.call_files(root, operation, args, "ui")
    interrupted = []
    if category == "interrupted":
        import ctypes
        shell = ctypes.windll.shell32
        original = shell.SHFileOperationW
        def interrupt(operation):
            interrupted.append("SHFileOperationW")
            raise KeyboardInterrupt("Owned interruption before silent shell commit")
        shell.SHFileOperationW = interrupt
        try:
            refused(lambda: call("trash", {"path": str(path)}), KeyboardInterrupt)
        finally:
            shell.SHFileOperationW = original
        require(interrupted and path.read_bytes() == raw and bus_for(root).get("files:last") is None, "Interrupted native trash admission changed original/undo receipt")
    if category == "permissions":
        with denied(path):
            refused(lambda: call("trash", {"path": str(path)}), (OSError, RuntimeError))
        require(path.read_bytes() == raw and bus_for(root).get("files:last") is None, "Native denied trash lost bytes or produced undo receipt")
    paths = [path]
    if category == "concurrency":
        second = root / "second.txt"
        second.write_bytes(raw + b"-second")
        paths.append(second)
        # Each runtime owns its undo journal; files remain inside that runtime.
        other_root = root / "second-state"
        other_root.mkdir()
        second.rename(other_root / "second.txt")
        paths[1] = other_root / "second.txt"
        outcomes = _parallel(lambda item: files.call_files(root if item == path else other_root, "trash", {"path": str(item)}, "ui"), paths)
    else:
        outcomes = [call("trash", {"path": str(path)})]
    try:
        for index, target in enumerate(paths):
            expected = raw if index == 0 else raw + b"-second"
            require(outcomes[index]["ok"] and outcomes[index]["recycled"] and not target.exists(), "Actual silent shell trash did not remove the original")
            records = files.bin_records(target)
            require(records and records[0]["path"] == str(target) and records[0]["size"] == len(expected) and records[0]["data"].read_bytes() == expected, "Owned native recycle record/data not independently recoverable")
            state_root = root if index == 0 else target.parent
            if category == "stale":
                target.write_bytes(b"new occupant")
                refused(lambda: files.call_files(state_root, "undo", {}, "ui"))
                require(target.read_bytes() == b"new occupant" and records[0]["data"].read_bytes() == expected, "Occupied restore overwrote newer bytes or lost recycled original")
                # Move the generated occupant aside; preserve it instead of deleting.
                target.rename(target.with_suffix(".occupant"))
            restored = files.call_files(state_root, "undo", {}, "ui")
            require(restored["ok"] and restored["undone"] == "trash" and target.read_bytes() == expected and not records[0]["info"].exists() and not records[0]["data"].exists(), "Native trash undo failed exact byte/index conservation")
            refused(lambda: files.call_files(state_root, "undo", {}, "ui"))
            require(target.read_bytes() == expected, "Repeated trash undo changed recovered bytes")
    finally:
        # Always recover our exact generated original if a later assertion fails.
        for target in paths:
            if not target.exists():
                files.restore(target)
    return ["files.trash-recoverable"], {"files": len(paths), "bytes": len(raw), "sha256": sha(raw), "actualWindowsRecycleAndRestore": True, "shellFlagsSilent": True, "denial": category == "permissions", "interruptedBeforeNativeCommit": bool(interrupted), "occupiedRestoreRefused": category == "stale"}


def _files_completion(root, category):
    from . import neyvia_files_tools as files
    from .edge_fixture_core import denied
    from .ui_command_bus import bus_for
    folder = root / "files"
    folder.mkdir()
    call = lambda operation, args: files.call_files(root, operation, args, "ui")
    raw = b"" if category == "empty" else b"x" * 1048576 if category == "huge" else "雪🙂é שלום".encode() if category == "unicode" else b"owned conserved bytes"
    origin = folder / ("雪🙂.txt" if category == "unicode" else "origin.txt")
    target = folder / "moved.txt"
    occupied = folder / "occupied.txt"
    directory = folder / "new-folder"
    origin.write_bytes(raw)
    occupied.write_bytes(b"independent keeper")
    if category == "permissions":
        with denied(origin):
            refused(lambda: call("move", {"from": str(origin), "to": str(target)}), OSError)
        require(origin.read_bytes() == raw and not target.exists() and bus_for(root).get("files:last") is None, "OS-denied Files move lost original or invented undo")
        with _deny_child_creation(folder, root):
            refused(lambda: call("mkdir", {"path": str(directory)}), OSError)
        require(not directory.exists(), "Actual denied directory creation produced a folder")
    if category == "interrupted":
        original_rename, original_mkdir = os.rename, Path.mkdir
        commits = []
        def interrupt_rename(source, destination, *args, **kwargs):
            if Path(source).resolve() == origin.resolve():
                commits.append("move")
                raise KeyboardInterrupt("Owned move interruption before OS rename")
            return original_rename(source, destination, *args, **kwargs)
        def interrupt_mkdir(path, *args, **kwargs):
            if path.resolve() == directory.resolve():
                commits.append("mkdir")
                raise KeyboardInterrupt("Owned mkdir interruption before OS directory creation")
            return original_mkdir(path, *args, **kwargs)
        os.rename, Path.mkdir = interrupt_rename, interrupt_mkdir
        try:
            refused(lambda: call("move", {"from": str(origin), "to": str(target)}), KeyboardInterrupt)
            refused(lambda: call("mkdir", {"path": str(directory)}), KeyboardInterrupt)
        finally:
            os.rename, Path.mkdir = original_rename, original_mkdir
        require(commits == ["move", "mkdir"] and origin.read_bytes() == raw and not target.exists() and not directory.exists(), "Interrupted Files commits lost prior bytes or fabricated created state")
    if category == "concurrency":
        collision_results = _parallel(lambda _: refused(lambda: call("move", {"from": str(origin), "to": str(occupied)})), range(8))
        require(len(collision_results) == 8, "Competing occupied-target moves were not all refused")
        def create(_):
            try:
                return call("mkdir", {"path": str(directory)})
            except (ValueError, OSError) as error:
                return {"ok": False, "type": type(error).__name__}
        created = _parallel(create, range(8))
        require(sum(row.get("ok") is True for row in created) == 1 and directory.is_dir(), "Competing same-target mkdir lost single-winner durability")
        undo = call("undo", {})
        require(undo["ok"] and undo["undone"] == "mkdir" and not directory.exists(), "Concurrent mkdir winner's undo receipt lost created target")
    else:
        refused(lambda: call("move", {"from": str(origin), "to": str(occupied)}))
    require(origin.read_bytes() == raw and occupied.read_bytes() == b"independent keeper", "Rejected Files overwrite modified either exact byte set")
    moved = call("move", {"from": str(origin), "to": str(target)})
    require(moved["ok"] and not origin.exists() and target.read_bytes() == raw, "Files successful move lost exact path/byte conservation")
    if category == "stale":
        origin.write_bytes(b"new occupant")
        refused(lambda: call("undo", {}))
        require(origin.read_bytes() == b"new occupant" and target.read_bytes() == raw, "Old move undo overwrote newer occupant")
        origin.rename(folder / "retained-occupant.txt")
    if category == "permissions":
        with denied(target):
            refused(lambda: call("undo", {}), OSError)
        require(not origin.exists() and target.read_bytes() == raw and bus_for(root).get("files:last")["op"] == "move", "OS-denied move undo changed target or consumed its pending receipt")
    if category == "interrupted":
        original = os.rename
        def stop_undo(source, destination, *args, **kwargs):
            if Path(source).resolve() == target.resolve():
                raise KeyboardInterrupt("Owned undo interruption before actual rename")
            return original(source, destination, *args, **kwargs)
        os.rename = stop_undo
        try:
            refused(lambda: call("undo", {}), KeyboardInterrupt)
        finally:
            os.rename = original
        require(not origin.exists() and target.read_bytes() == raw and bus_for(root).get("files:last")["op"] == "move", "Interrupted undo consumed pending receipt or changed conserved bytes")
    restored = call("undo", {})
    require(restored["ok"] and restored["undone"] == "move" and origin.read_bytes() == raw and not target.exists() and bus_for(root).get("files:last") is None, "Move undo failed exact conservation/one-step consumption")
    refused(lambda: call("undo", {}))
    made = call("mkdir", {"path": str(directory)})
    require(made["ok"] and directory.is_dir(), "Files directory success was not durable")
    (directory / "retained.txt").write_bytes(raw)
    refused(lambda: call("undo", {}))
    require((directory / "retained.txt").read_bytes() == raw and bus_for(root).get("files:last")["op"] == "mkdir", "Nonempty directory undo lost newer contents or consumed pending intent")
    return ["files.move-conservation", "files.no-overwrite", "files.mkdir-durable", "files.undo-once"], {"bytes": len(raw), "sha256": sha(raw), "nativeFileDenial": category == "permissions", "temporaryOwnedDirectoryDaclRestored": category == "permissions", "osCommitInterruption": category == "interrupted", "socketAuditEnforced": True}


def _core_preparation(root, category):
    from . import neyvia_ecosystem as ecosystem
    from .neyvia_accounts import describe_device
    from .neyvia_agent import NeyviaAgentConfig
    text = "" if category == "empty" else "neutral " * 18000 if category == "huge" else "雪🙂é שלום\x00" if category == "unicode" else "owned local request"
    context = {key: text for key in ("scope", "ownership", "doNotTouch", "success", "constraints", "currentState")}
    labels = {"scope": "Owned scope", "ownership": "Ownership", "doNotTouch": "Do not modify", "success": "Success", "constraints": "Constraints", "currentState": "Current state"}
    def observe(index):
        subject = text + (" Analyze spreadsheet data " if index % 2 else " Read study architecture ")
        candidates = [(sum(word in (" " + subject.lower() + " ") for word in ecosystem.TASK_PROMPT_PROFILES[key]["keywords"]), -priority, key) for priority, key in enumerate(ecosystem.TASK_PROMPT_PRIORITY)]
        winner = max(candidates)
        expected = winner[2] if winner[0] else "general"
        chosen = ecosystem.infer_task_prompt_profile(subject)
        require(chosen["profileId"] == expected and chosen["selection"] == ("inferred" if winner[0] else "default"), "Core prompt selection disagrees with independent keyword/priority oracle")
        if not text:
            default = ecosystem.infer_task_prompt_profile("")
            require(default["profileId"] == "general" and default["selection"] == "default", "Empty subject fabricated matched profile")
        for profile, depth, maximum in (("study", "source-led", 4), ("ecosystem_architecture", "rich", 5), ("optimization", "measured", 4), ("communication", None, None), ("experimentation", None, None)):
            prepared = ecosystem.build_adaptive_task_prompt(subject, pack={}, requested_profile=profile, task_context=context)
            require(prepared["profile"]["profileId"] == profile and prepared["profile"]["selection"] == "explicit" and prepared["originalPrompt"] == subject and subject.strip() in prepared["prompt"], "Explicit domain precedence/original prompt lost")
            require(all(f"{labels[key]}: {value.strip()}" in prepared["prompt"] for key, value in context.items() if value.strip()) and "orchestration owns task division and sequence" in prepared["prompt"] and "harness owns permissions, budgets, receipts, and stop enforcement" in prepared["prompt"], "Supplied scope/ownership/constraints or layer boundary lost")
            if depth:
                require(prepared["profile"]["contextDepth"] == depth and prepared["profile"]["proofBudget"]["maximumChecks"] == maximum, "Domain policy metadata differs")
            if profile == "communication":
                require("sending, deleting, and unsubscribing remain per-action approvals" in prepared["prompt"], "Communication send/delete approvals missing")
            if profile == "experimentation":
                require("Observe, Simulate, or Act" in prepared["prompt"] and "retain failures" in prepared["prompt"].lower(), "Experiment mode/failure preservation missing")
        disabled = ecosystem.apply_silent_ecosystem_rewrite(subject, enabled=False, pack={})
        require(disabled["prompt"] == subject and disabled["rewritten"] is False, "Disabled rewrite changed exact caller request")
        image = ecosystem.build_image_generation_prompt({"instruction": text, "operation": text, "compositionIntent": text, "prompt": {key: text for key in ("style", "lighting", "palette", "camera", "materials", "exactText", "preserve", "negative")}})
        require(image["profile"]["profileId"] == "image_generation" and "Proof budget" not in image["prompt"] and all(f"{label}: {text.strip()}" in image["prompt"] for label in ("Subject and intent", "Operation", "Composition", "Style and art direction", "Lighting and atmosphere", "Palette", "Camera and framing", "Materials and texture", "Exact visible text", "Preservation constraints", "Avoid") if text.strip()), "Image visual fields lost or coding proof budget added")
        ua = text + " Mozilla/5.0 (Windows NT 10.0) Chrome/132.0.0.0 Safari/537.36"
        require(describe_device(ua) == "Chrome on Windows" and describe_device("") == "Unknown device", "Platform/browser labels differ from known generated user agents")
        valid = NeyviaAgentConfig(root=root, session_id="owned" + str(index), transport="auto", max_turns=64).validated()
        require(valid.root == root and valid.session_id == "owned" + str(index) and valid.max_turns == 64, "Validated native agent config changed selected root/session/bounds")
        for changes in ({"session_id": "" if category == "empty" else "x" * 129 if category == "huge" else "雪🙂"}, {"max_turns": 0}, {"max_turns": 65}, {"transport": "untrusted"}):
            refused(lambda: NeyviaAgentConfig(root=root, session_id=changes.get("session_id", "owned"), max_turns=changes.get("max_turns", 12), transport=changes.get("transport", "auto")).validated())
        return {"selected": chosen["profileId"], "promptSha256": sha(subject.encode())}
    results = _parallel(observe, list(range(12))) if category == "concurrency" else [observe(0)]
    return ["neyvia-core.prompt-selection", "neyvia-core.prompt-preservation", "neyvia-core.domain-policy", "neyvia-core.image-spec", "neyvia-core.account-devices", "neyvia-core.agent-config"], {"inputCharacters": len(text), "observations": results, "networkDenied": True, "agentExecuted": False, "imagesGenerated": False}


def _core_projection(root, category):
    from .neyvia_application_contract import _module_to_manifest
    text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned metadata"
    count = 180 if category == "huge" else 3
    capabilities = [{"operationId": f"owned.operation-{index}", "name": text} for index in range(count)]
    module = {"moduleId": "owned.projection", "name": text or "Owned projection", "summary": text, "state": "active", "manifest": {"neyvia": {"embedIn": ["marketplace", "marketplace"], "presentations": ["inline-card", "inline-card"], "provides": capabilities}}, "runtime": {"servedUrl": "/owned/"}}
    def observe(index):
        result = _module_to_manifest(module)
        require(result["valid"] and result["surfaces"] == ["marketplace"] and result["presentations"] == ["inline-card"] and [row["capabilityId"] for row in result["provides"]] == [row["operationId"] for row in capabilities] and result["entryPointUrl"] == "/owned/", "Native module projection lost typed surfaces or ordered capabilities")
        checked = []
        for state in ("active", "installed", "disabled"):
            for url in ("/owned/", "https://example.invalid/owned", "http://127.0.0.1:48743/owned", "file:///owned.html", "//example.invalid/owned", "http://example.invalid/owned"):
                value = _module_to_manifest({**module, "state": state, "runtime": {"servedUrl": url}})
                expected = url if state == "active" and url in {"/owned/", "https://example.invalid/owned", "http://127.0.0.1:48743/owned"} else None
                require(value["entryPointUrl"] == expected, "Projection bound inactive or unsafe hosted endpoint")
                checked.append(value["entryPointUrl"])
        return {"capabilities": len(result["provides"]), "endpointCases": len(checked)}
    observations = _parallel(observe, range(8)) if category == "concurrency" else [observe(0)]
    return ["neyvia-core.application-projection", "neyvia-core.hosted-entrypoint"], {"characters": len(text), "observations": observations, "networkContacts": 0, "moduleExecuted": False}


def _core_sdk(root, category):
    from . import neyvia_application_contract as apps
    from .edge_fixture_core import denied
    text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned sdk metadata"
    identity = "owned.sdk"
    initial = apps.register_sdk_application(root, {"applicationId": identity, "name": "Owned", "summary": text, "services": ["agents"]})
    target = apps._sdk_registry_path(root)
    require(initial["registered"] and json.loads(target.read_text(encoding="utf8"))["applications"] == [initial["manifest"]], "SDK declaration not exactly saved")
    prior = target.read_bytes()
    payload = {"applicationId": identity, "name": "Updated", "summary": text, "services": ["memory"]}
    if category == "permissions":
        with denied(target):
            refused(lambda: apps.register_sdk_application(root, payload), OSError)
        require(target.read_bytes() == prior, "OS-denied SDK registration lost prior services")
    if category == "interrupted":
        with replacement_fault(apps, target, KeyboardInterrupt) as calls:
            refused(lambda: apps.register_sdk_application(root, payload), KeyboardInterrupt)
        require(calls and target.read_bytes() == prior, "Interrupted SDK registration lost prior exact declarations")
    if category == "concurrency":
        results = _parallel(lambda index: apps.register_sdk_application(root, {"applicationId": f"owned.sdk-{index}", "name": f"Owned {index}", "services": ["memory"]}), range(8))
        durable = {row["applicationId"] for row in apps.load_sdk_applications(root)}
        require(durable == {identity, *(row["applicationId"] for row in results)}, "Simultaneous SDK registrations lost independently completed identities")
    updated = apps.register_sdk_application(root, payload)
    observed = next(row for row in apps.load_sdk_applications(root) if row["applicationId"] == identity)
    require(updated["registered"] and updated["updated"] and observed == updated["manifest"] and set(observed["services"]) == {"agents", "memory"} and observed["summary"] == text, "SDK update lost retained adopted services or metadata")
    if category == "stale":
        fresh = apps.register_sdk_application(root, {"applicationId": identity, "name": "Current", "services": ["tools"]})
        require(set(next(row for row in apps.load_sdk_applications(root) if row["applicationId"] == identity)["services"]) == {"agents", "memory", "tools"} and fresh["updated"], "Fresh SDK update lost previously adopted services")
    return ["neyvia-core.sdk-durable"], {"identity": identity, "storedSha256": sha(target.read_bytes()), "declaredServices": observed["services"], "runtimeExecuted": False}


def _core_bundled(root, category):
    from . import neyvia_application_contract as apps
    from .edge_fixture_core import denied
    text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned activation"
    sources = list(apps.BUNDLED_APPLICATIONS)
    eligible = [row for row in sources if row.get("installSource", "bundled") != "github-release"]
    require(len(eligible) >= 2, "Owned local bundled declarations unavailable")
    observed = apps.bundled_application_catalog(root)
    require(len(observed) == len(sources), "Bundled catalog lost an exact declaration")
    for source, actual in zip(sources, observed):
        require(all(actual[key] == source[key] for key in ("applicationId", "name", "launch", "provides", "permissions")) and actual["logoUrl"] == (source.get("logoUrl") or None) and actual["marketplaceEligible"], "Bundled catalog changed identity/route/logo/capability/permission metadata")
    first = apps.install_bundled_application(root, eligible[0]["applicationId"], requested_by=text)
    target = apps._bundled_registry_path(root)
    prior = target.read_bytes()
    second_id = eligible[1]["applicationId"]
    if category == "permissions":
        with denied(target):
            refused(lambda: apps.install_bundled_application(root, second_id, requested_by=text), OSError)
        require(target.read_bytes() == prior, "OS-denied bundled activation lost prior installed identities")
    if category == "interrupted":
        with replacement_fault(apps, target, KeyboardInterrupt) as calls:
            refused(lambda: apps.install_bundled_application(root, second_id, requested_by=text), KeyboardInterrupt)
        require(calls and target.read_bytes() == prior, "Interrupted bundled activation lost prior exact receipt")
    if category == "concurrency":
        identities = [row["applicationId"] for row in eligible[1:9]]
        results = _parallel(lambda item: apps.install_bundled_application(root, item, requested_by=text), identities)
        require(all(row["installed"] for row in results) and set(apps._load_bundled_installations(root)) == {first["applicationId"], *identities}, "Concurrent completed bundled activations lost independent identities")
    else:
        apps.install_bundled_application(root, second_id, requested_by=text)
    repeated = apps.install_bundled_application(root, first["applicationId"], requested_by="old caller")
    require(repeated["alreadyInstalled"] and repeated["launch"] == eligible[0]["launch"], "Repeated/current bundled installation lost stable route")
    fresh = apps.bundled_application_catalog(root)
    installed = apps._load_bundled_installations(root)
    require(all(row["installed"] == (row["applicationId"] in installed) and row["state"] == ("active" if row["applicationId"] in installed else "available") for row in fresh), "Fresh catalog activation differs from exact durable installation membership")
    return ["neyvia-core.bundled-catalog", "neyvia-core.bundled-durable"], {"declarations": len(sources), "installed": sorted(installed), "storedSha256": sha(target.read_bytes()), "externalPackagesInstalled": 0}


def _model_compilers(root, category):
    from .proof_credential_guard import prepare_broker_fixture
    from .neyvia_mcp import NeyviaMCPServer
    from .edge_fixture_core import denied
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .openai_adapter import resolve_compiled_tool_call
    prepare_broker_fixture(root)
    server = NeyviaMCPServer(root)
    service = server.capability_os
    try:
        intelligence = service._ensure_model_tool_intelligence()
        intelligence.feedback.aggregate()
        task = "Analyze this Excel spreadsheet " + ("x" * 70000 if category == "huge" else "雪🙂é שלום" if category == "unicode" else "owned data")
        request = lambda args: server.handle({"jsonrpc": "2.0", "id": 91, "method": "tools/call", "params": {"name": "model.tools.compile", "arguments": args}})
        if category == "empty":
            refused(lambda: service.compile_model_tool_belt({"task": ""}))
            refused(lambda: service.compile_openai_tool_belt({"task": ""}))
            empty = request({"task": ""})
            require("error" in empty or empty.get("result", {}).get("isError"), "Empty MCP compiler task was admitted")
        if category == "permissions":
            with denied(intelligence.feedback.index_path):
                refused(lambda: service.compile_model_tool_belt({"task": task}), sqlite3.Error)
                refused(lambda: service.compile_openai_tool_belt({"task": task}), sqlite3.Error)
                answer = request({"task": task})
                require("error" in answer or answer.get("result", {}).get("isError"), "OS-denied compiler feedback produced a successful MCP belt")
        exits = []
        if category == "interrupted":
            for operation in ("mcp", "openai"):
                child = subprocess.run([sys.executable, "-m", MODULE, "--root", str(root), "--port", os.environ["NEYVIA_C7_PORT"], "--crash-compiler", operation], capture_output=True, timeout=40, **hidden_windows_subprocess_kwargs())
                require(child.returncode == 23 and not child.stdout.strip(), "Compiler consumer did not exit at real indexed-feedback read before replying")
                exits.append(child.returncode)
        listed = server.handle({"jsonrpc": "2.0", "id": 90, "method": "tools/list", "params": {"includeSchemas": False}})
        tools = listed["result"]["tools"]
        require(any(row["name"] == "model.tools.compile" for row in tools) and all("inputSchema" not in row for row in tools), "Actual progressive MCP list lost compiler or leaked full schemas")
        def compile(index):
            payload = {"task": task + str(index), "limit": 4, "deferLoading": True}
            belt = service.compile_model_tool_belt(payload)
            require(belt["schema"] == "neyvia.model_tool_belt.v1" and belt["tools"][0]["name"] == "office.spreadsheet-analysis" and len(belt["tools"]) <= 4 and belt["policy"]["permissionAuthority"] == "existing execution surface", "Actual selected-source belt lost expected relevance/bound/authority")
            compiler = service.compile_openai_tool_belt(payload)
            require(compiler["belt"]["catalogHash"] == belt["catalogHash"] and compiler["callMap"] and compiler["tools"][-1]["type"] == "tool_search", "OpenAI compiler changed exact same-source belt or deferred search")
            for key, mapping in compiler["callMap"].items():
                namespace, name = key.split(".", 1)
                resolved = resolve_compiled_tool_call(compiler, {"namespace": namespace, "name": name, "arguments": {}})
                require(resolved["callTarget"] == mapping["callTarget"] and resolved["provenance"] == mapping["provenance"], "Compiled callable retargeted exact saved provenance")
            via_mcp = request(payload)
            require("error" not in via_mcp and not via_mcp["result"]["isError"] and via_mcp["result"]["structuredContent"]["catalogHash"] == belt["catalogHash"], "Actual MCP compiler dispatch lost the exact selected-source belt")
            return {"catalogHash": belt["catalogHash"], "task": belt["task"], "providerCallableCount": len(compiler["callMap"])}
        results = _parallel(compile, range(8)) if category == "concurrency" else [compile(0)]
        if category == "stale":
            new_task = "Test this native Android application in an emulator"
            fresh = service.compile_model_tool_belt({"task": new_task, "limit": 4})
            require(fresh["task"] == new_task and fresh["catalogHash"] != results[0]["catalogHash"] and "device.android-test" in [row["name"] for row in fresh["tools"]], "Compiler reused previous task relevance or catalog identity")
        return ["proofs-c.models.belt", "proofs-c.models.compiler", "proofs-c.models.mcp-compiler"], {"calls": len(results), "catalogHashes": [row["catalogHash"] for row in results], "compiledTaskCharacters": [len(row["task"]) for row in results], "indexedReadWorkerExits": exits, "progressiveSchemasOmitted": True, "providerInvoked": False}
    finally:
        server.mcp_broker.close()
        if service._model_tool_broker:
            service._model_tool_broker.close()


def _mobile(root, category):
    import http.client
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse
    from . import neyvia_mobile_studio as mobile
    from .neyvia_workspace_tools import WorkspaceTools
    from .edge_fixture_missions import exclusive
    port = int(os.environ["NEYVIA_C7_PORT"])
    project = root / "app"
    web = project / "screens"
    web.mkdir(parents=True)
    text = "" if category == "empty" else "x" * 70000 if category == "huge" else "雪🙂e\u0301 </script>" if category == "unicode" else "Owned mobile"
    name = text or "Empty metadata recovery"
    cap = project / "capacitor.config.json"
    cap.write_text(json.dumps({"appName": name, "appId": "com.fixture.mobile", "webDir": "screens"}), encoding="utf8")
    source = '<html><head><style>@media(prefers-color-scheme:dark){padding:env(safe-area-inset-top,4px)}</style></head><body>Owned mobile report</body></html>'
    (web / "index.html").write_text(source, encoding="utf8")
    (project / "private.txt").write_text("owned outside web export", encoding="utf8")
    info = mobile.project_info(project)
    require(info["name"] == name and info["webRoot"] == str(web) and info["iosBundleId"] == info["androidPackage"] == "com.fixture.mobile", "Actual project discovery lost explicit screens/name/identity")
    service = WorkspaceTools(root)
    token = mobile.preview_token(service, project)
    errors = []
    class Handler(BaseHTTPRequestHandler):
        def dispatch(self, method):
            try:
                mobile.serve_preview(root, self, urlparse(self.path), method)
            except BaseException as error:
                errors.append(type(error).__name__)
                self.send_error(500, type(error).__name__)
        def do_GET(self): self.dispatch("GET")
        def do_POST(self): self.dispatch("POST")
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(relative="", body=None, length=None, selected_token=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        headers = {"Content-Length": str(len(body or b"")) if length is None else length}
        conn.request("POST" if body is not None else "GET", mobile.PREVIEW_PREFIX + (selected_token or token) + "/" + relative, body=body, headers=headers)
        result = conn.getresponse()
        value = result.status, dict(result.getheaders()), result.read()
        conn.close()
        return value
    store_path = project / mobile.STORAGE
    try:
        require(request("__nx/storage")[0] == 200 and json.loads(request("__nx/storage")[2]) == {} and not store_path.parent.exists(), "Fresh HTTP storage read invented data or created parent state")
        for relative in ("../private.txt", "%2e%2e/private.txt", "%2e%2e%5cprivate.txt", "../../outside"):
            require(request(relative)[0] == 403, "Actual HTTP mobile preview escaped web root")
        require(request(selected_token="invalid-owned-capability")[0] == 404, "Unknown preview capability gained project access")
        for raw, length, status in ((b"{", None, 400), (b"[]", None, 400), (b'{"a":1}', None, 400), (b"", "-1", 400), (b"", "bad", 400), (b"", "2000001", 413)):
            require(request("__nx/storage", raw, length)[0] == status and not store_path.exists(), "Invalid actual HTTP storage request wrote data or changed size/type refusal")
        raw = json.dumps({"saved": text}, ensure_ascii=False).encode("utf8")
        require(request("__nx/storage", raw)[0] == 200 and json.loads(store_path.read_text(encoding="utf8")) == {"saved": text} and json.loads(request("__nx/storage")[2]) == {"saved": text}, "Actual HTTP storage response differs from independently saved string map")
        status, headers, page = request("settings/profile?dark=1")
        require(status == 200 and b"window.__NX_MOBILE__" in page and b"Owned mobile report" in page and "sandbox" in headers["Content-Security-Policy"].split() and "allow-same-origin" not in headers["Content-Security-Policy"].split() and request("missing.js")[0] == 404, "Actual HTTP injection/SPA/sandbox result changed")
        decoded = page.decode("utf8")
        begin = decoded.index("window.__NX_MOBILE__=") + len("window.__NX_MOBILE__=")
        config = json.loads(decoded[begin:decoded.index(";</script>", begin)])
        require(config["storage"] == {"saved": text} and config["dark"] and config["base"] == mobile.PREVIEW_PREFIX + token + "/" and "</script" not in decoded[begin:decoded.index(";</script>", begin)].lower(), "Real HTTP injected storage/device capsule lost exact values or safe script boundary")
        if category == "concurrency":
            def publish(index):
                value = {"writer": str(index), "body": str(index) * 1000000}
                status = request("__nx/storage", json.dumps(value).encode())[0]
                require(status == 200, "Concurrent actual HTTP storage publication failed")
                return value
            values = _parallel(publish, range(8))
            saved = json.loads(store_path.read_text(encoding="utf8"))
            require(saved in values and json.loads(request("__nx/storage")[2]) == saved, "Concurrent storage result is not an exact completed request")
            require(all(row["webRoot"] == str(web) and row["name"] == name for row in _parallel(lambda _: mobile.project_info(project), range(8))), "Concurrent project observers lost exact selected source")
        if category == "offline":
            from .edge_fixture_native import _offline
            before = store_path.read_bytes()
            with _offline() as attempted:
                refused(lambda: request("__nx/storage", b'{"offline":"write"}'), OSError)
            require(attempted and store_path.read_bytes() == before and json.loads(request("__nx/storage")[2]) == {"saved": text}, "Actual disconnected HTTP request changed stored map or fabricated acknowledgement")
        if category == "permissions":
            before = store_path.read_bytes()
            with exclusive(store_path):
                require(request("__nx/storage", b'{"denied":"write"}')[0] == 500 and json.loads(request("__nx/storage")[2]) == {}, "OS-denied mobile storage invented completed write or accessible map")
            require(store_path.read_bytes() == before and "PermissionError" in errors, "OS sharing denial changed prior storage bytes")
            with exclusive(cap):
                require(mobile.project_info(project)["kind"] == "web", "OS-denied project metadata invented recognized Capacitor config")
        if category == "interrupted":
            before = store_path.read_bytes()
            original = os.replace
            hit = []
            def interrupt(source, target, *args, **kwargs):
                if Path(target).resolve() == store_path.resolve():
                    hit.append(True)
                    raise KeyboardInterrupt("Owned preview storage commit interruption")
                return original(source, target, *args, **kwargs)
            os.replace = interrupt
            try:
                require(request("__nx/storage", b'{"interrupted":"write"}')[0] == 500, "HTTP storage missed real publication interruption")
            finally:
                os.replace = original
            require(hit and store_path.read_bytes() == before and "KeyboardInterrupt" in errors, "Interrupted preview storage changed prior durable bytes")
        if category in {"stale", "permissions", "interrupted"}:
            current = {"current": "fresh 🙂"}
            require(request("__nx/storage", json.dumps(current).encode())[0] == 200 and json.loads(request("__nx/storage")[2]) == current, "Fresh storage retry reused stale/failed request")
            cap.write_text(json.dumps({"appName": "Current app", "appId": "com.fixture.current", "webDir": "screens"}), encoding="utf8")
            require(mobile.project_info(project)["name"] == "Current app" and mobile.project_info(project)["iosBundleId"] == "com.fixture.current", "Project discovery reused stale cached config")
        if category == "stale":
            old_token = token
            service.bus.update(mobile.TOKENS_KEY, {old_token: str(root / "missing-current-project")})
            require(request(selected_token=old_token)[0] == 404, "Stale preview capability retained access to replaced project binding")
            token = mobile.preview_token(service, project)
            require(token != old_token and request()[0] == 200, "Fresh preview capability failed exact current project binding")
        ids = ["neyvia-core.mobile-" + name for name in ("project", "injection", "confinement", "storage")]
        if category == "interrupted":
            ids = ["neyvia-core.mobile-storage"]
        elif category in {"permissions", "offline", "stale"}:
            ids.remove("neyvia-core.mobile-injection")
            if category == "offline":
                ids.remove("neyvia-core.mobile-project")
        return ids, {"actualLoopbackPort": port, "requestTransport": "real HTTP sockets", "savedBytes": store_path.stat().st_size, "storageSha256": sha(store_path.read_bytes()), "publicationErrors": errors, "renderedProof": False, "deviceToolchainInvoked": False}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.close()


def _entry(root, category):
    from .neyvia_version import NEYVIA_AGENT_VERSION
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    suffix = "" if category == "empty" else "x" * 10000 if category == "huge" else "雪🙂" if category == "unicode" else "owned"
    program = "import sys; from grant_agent.neyvia_agent_cli import main; code=main(['--version',sys.argv[1]]); assert 'grant_agent.neyvia_agent' not in sys.modules; raise SystemExit(code)"
    def probe(_):
        result = subprocess.run([sys.executable, "-c", program, suffix], capture_output=True, text=True, encoding="utf8", timeout=30, **hidden_windows_subprocess_kwargs())
        require(result.returncode == 0 and result.stdout == f"Neyvia Agent {NEYVIA_AGENT_VERSION}\n" and not result.stderr, "Explicit version probe lost exact product/version or imported runtime")
        return result.stdout.strip()
    versions = _parallel(probe, range(8 if category == "concurrency" else 1))
    ports_program = "import json; from grant_agent.browser_obscura import proof_ports; print(json.dumps(sorted(proof_ports())))"
    port = int(os.environ["NEYVIA_C7_PORT"])
    valid = f"{port},{port}" if category != "huge" else ",".join([str(port)] * 1000)
    def selected(value):
        return subprocess.run([sys.executable, "-c", ports_program], capture_output=True, text=True, encoding="utf8", timeout=30,
                              env={**os.environ, "NEYVIA_BROWSER_PROOF_PORTS": value}, **hidden_windows_subprocess_kwargs())
    configured = _parallel(lambda _: selected(valid), range(8 if category == "concurrency" else 1))
    require(all(row.returncode == 0 and json.loads(row.stdout) == [port] for row in configured), "Explicit proof port parser lost deduplication or independent concurrent selections")
    invalid = " " if category == "empty" else "雪" if category == "unicode" else str(48750)
    denied = selected(invalid)
    require(denied.returncode != 0, "Malformed or unassigned proof port accepted")
    return ["neyvia-core.agent-version", "neyvia-core.browser-ports"], {"actualHiddenVersionProcesses": len(versions), "versions": versions, "explicitParsedPort": port, "invalidPortSelectionRefused": True, "socketsOpened": 0}


BUILDERS = {"settings": _settings, "gateway": _gateway, "workspace": _workspace, "impact": _impact, "staleness": _staleness, "recycle": _recycle, "delivery": _delivery,
            "terminal": _terminal, "budget": _budget, "capture": _capture}
BUILDERS["authored-execute"] = _authored
BUILDERS["routing-benchmark"] = _benchmark
BUILDERS["notes-completion"] = _notes
BUILDERS["files-trash"] = _files_trash
BUILDERS["files-completion"] = _files_completion
BUILDERS["core-preparation"] = _core_preparation
BUILDERS["core-projection"] = _core_projection
BUILDERS["core-sdk"] = _core_sdk
BUILDERS["core-bundled"] = _core_bundled
BUILDERS["model-compilers"] = _model_compilers
BUILDERS["core-entry"] = _entry
BUILDERS["core-mobile"] = _mobile
INTENDED = {"settings": ["settings.revision-cas", "settings.invalid-preserves", "settings.canonical-mirrors", "settings.night-policy-event", "settings.legacy-theme", "settings.view-durable"],
            "gateway": ["c7.gateway.read-only"], "workspace": ["c7.workspace.rejected-preserves"],
            "impact": ["awareness.impact.gaps", "awareness.impact.command"],
            "staleness": ["awareness.claim.staleness"], "recycle": ["files.recycle-record"]}
INTENDED["delivery"] = ["delivery." + operation for operation in ("append", "update", "tail-update", "ack", "observe", "browser", "skipped")]
INTENDED.update(terminal=["proofs-e-wz.terminal-text"], budget=["proofs-e-wz.workflow-budget"], capture=["proofs-e-wz.capture-failure"])
INTENDED["authored-execute"] = ["proofs-c.models.authored-execute"]
INTENDED["routing-benchmark"] = ["proofs-c.models.benchmark"]
INTENDED["notes-completion"] = ["notes." + name for name in ("body-durable", "prose-metadata", "pin-durable", "path-jail", "write-bounded", "atomic-interruption", "permission-preserves", "stale-preserves", "concurrent-writes", "local-offline")]
INTENDED["files-trash"] = ["files.trash-recoverable"]
INTENDED["files-completion"] = ["files.move-conservation", "files.no-overwrite", "files.mkdir-durable", "files.undo-once"]
INTENDED["core-preparation"] = ["neyvia-core." + name for name in ("prompt-selection", "prompt-preservation", "domain-policy", "image-spec", "account-devices", "agent-config")]
INTENDED["core-projection"] = ["neyvia-core.application-projection", "neyvia-core.hosted-entrypoint"]
INTENDED["core-sdk"] = ["neyvia-core.sdk-durable"]
INTENDED["core-bundled"] = ["neyvia-core.bundled-catalog", "neyvia-core.bundled-durable"]
INTENDED["model-compilers"] = ["proofs-c.models.belt", "proofs-c.models.compiler", "proofs-c.models.mcp-compiler"]
INTENDED["core-entry"] = ["neyvia-core.agent-version", "neyvia-core.browser-ports"]
INTENDED["core-mobile"] = ["neyvia-core.mobile-" + name for name in ("project", "injection", "confinement", "storage")]


def _isolate(root, port, *, allow_loopback=False):
    from .proof_ports import c7_port_block
    c7_port_block(port)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        target = root / "home" / name.lower()
        target.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(target)
    for name in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WEB_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(name, None)
    os.environ.update(NEYVIA_C7_PORT=str(port), NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0")
    from .proof_credential_guard import install
    install(root)
    def audit(event, args):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            address = args[1] if event != "socket.getaddrinfo" else (args[0], args[1])
            if allow_loopback and tuple(address[:2]) == ("127.0.0.1", port):
                return
            raise PermissionError("Owned local fixtures have no network authority")
    sys.addaudithook(audit)


def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    port = int(os.environ.get("NEYVIA_C7_PORT", "0"))
    from .proof_ports import c7_port_block
    c7_port_block(port)
    root = Path(root).resolve()
    def execute(pair):
        family, category = pair
        case_root = root / family / category
        command = [sys.executable, "-m", MODULE, "--root", str(case_root), "--port", str(port), "--family", family, "--category", category]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf8", timeout=120,
                                   env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs())
        try:
            value = json.loads(completed.stdout)
        except ValueError:
            value = {"contracts": INTENDED[family], "status": "failed", "detail": completed.stderr[-2500:]}
        row = {"id": f"local-completion:{family}:{category}", "category": category,
               "contracts": [identity for identity in value["contracts"] if identity in contracts],
               "status": value["status"], "detail": value["detail"], "scratchRoot": str(case_root),
               "boundary": "real owned production calls, durable readback and actual OS sharing denial/transaction worker exit; no rendered UI proof"}
        return row
    pairs = [(family, category) for family in BUILDERS for category in categories
             if family != "workspace" or category in {"permissions", "interrupted"}
             if family != "gateway" or category not in {"interrupted", "stale"}
             if family != "recycle" or category in {"empty", "huge", "unicode", "concurrency", "offline"}
             if family != "impact" or category in {"empty", "huge", "unicode", "concurrency", "offline", "stale"}
             if family != "staleness" or category in {"empty", "huge", "unicode", "concurrency", "offline"}]
    pairs = [(family, category) for family, category in pairs if family != "delivery" or category in {"concurrency", "interrupted", "permissions", "stale"}]
    pairs = [(family, category) for family, category in pairs
             if family != "terminal" or category in {"empty", "huge", "unicode"}
             if family != "budget" or category in {"empty", "huge", "unicode", "concurrency", "offline"}
             if family != "capture" or category != "stale"]
    pairs = [(family, category) for family, category in pairs if family not in {"core-preparation", "core-projection"} or category in {"empty", "huge", "unicode", "concurrency", "offline"}]
    pairs = [(family, category) for family, category in pairs if family != "core-entry" or category in {"empty", "huge", "unicode", "concurrency"}]
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(execute, [pair for pair in pairs if pair[0] != "core-mobile"]))
    rows.extend(execute(pair) for pair in pairs if pair[0] == "core-mobile")
    return rows


def blocker(contract, category):
    identity = contract["id"]
    if identity == "neyvia-core.mobile-injection" and category in {"permissions", "interrupted", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited neyvia_mobile_studio._scheme/_inject synchronously transform supplied HTML/config for media/safe-area/base/script boundaries. This invariant owns no transport, grant, worker, stored revision or filesystem access. Real HTTP injected bytes and parsed capsules prove the transform; project reads, capability confinement and durable storage have separate adverse fixtures. No API receipt counts as rendered phone-frame proof."}
    if identity == "neyvia-core.mobile-project" and category == "offline":
        return {"kind": "not_applicable", "reason": "Audited project_info reads selected local package/Capacitor/Expo metadata and checks local web-export files. It makes no network request and has no connectivity argument. Native denied metadata reads and fresh source discovery are exercised; HTTP transport failure belongs to serving/storage contracts."}
    if identity in INTENDED["core-mobile"] and category == "interrupted" and identity != "neyvia-core.mobile-storage":
        return {"kind": "not_applicable", "reason": f"Audited {identity} synchronously discovers supplied project metadata, injects bounded HTML/config or confines a requested path/capability before returning bytes. These read-only handlers own no resumable worker or durable publication. Actual interrupted storage publication is exercised separately; real HTTP injection is API proof, not rendered phone-frame proof."}
    if identity in INTENDED["core-entry"] and category in {"interrupted", "permissions", "offline", "stale"}:
        owner = "neyvia_agent_cli.main --version reads the immutable product version before importing the runtime" if identity.endswith("agent-version") else "browser_obscura.proof_ports parses an explicitly supplied port set against the assigned allowlist without binding or connecting a socket"
        return {"kind": "not_applicable", "reason": f"Audited {owner}. This synchronous metadata invariant accepts no mutable revision, worker continuation, grant or transport; actual hidden readiness invocations and independent concurrent explicit port parsers are checked. Agent execution and native browser navigation are separate invariants."}
    if identity in INTENDED["core-projection"] and category in {"interrupted", "permissions", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited neyvia_application_contract._module_to_manifest projects an explicit caller module snapshot and typed surfaces/capabilities. Hosted URL binding checks the supplied current state and URL syntax without contacting an endpoint. It owns no transport, grant, worker, writer or saved revision; eighteen active/inactive/unsafe URL combinations and supplied surface/capability collections are independently checked. Installation persistence and rendered routes are separate invariants."}
    if identity in INTENDED["core-preparation"] and category in {"interrupted", "permissions", "stale"}:
        owners = {"neyvia-core.prompt-selection": "infer_task_prompt_profile deterministic keyword/explicit policy selection", "neyvia-core.prompt-preservation": "build_adaptive_task_prompt/apply_silent_ecosystem_rewrite explicit request/context preparation with supplied pack", "neyvia-core.domain-policy": "prompt profile metadata and per-action boundaries retained in prepared text", "neyvia-core.image-spec": "build_image_generation_prompt supplied visual-field preparation", "neyvia-core.account-devices": "describe_device plain user-agent platform/browser label", "neyvia-core.agent-config": "NeyviaAgentConfig.validated immutable configuration admission"}
        return {"kind": "not_applicable", "reason": f"Audited {owners[identity]} runs synchronously over explicit caller values. This invariant owns no transport, durable publisher, grant decision, resumed worker or previously accepted revision. Native filesystem/root existence checks in agent config do not launch an agent. Empty/large/Unicode boundaries and twelve concurrent independent selected-root observations are exercised without network access; execution and rendered surfaces are separate contracts."}
    if identity == "proofs-e-wz.terminal-text" and category not in {"empty", "huge", "unicode"}:
        return {"kind": "not_applicable", "reason": "Audited web_backend._clean_terminal_text(value) decodes supplied bytes and synchronously replaces ANSI/CR sequences in caller-owned strings. It owns no transport, grant, worker, mutable revision or durable effect. Empty, 200000-byte and malformed UTF8/Unicode cases independently compare all returned text."}
    if identity == "proofs-e-wz.workflow-budget" and category in {"interrupted", "permissions", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited efficient_workflow.build_efficient_workflow runtimeSeconds validation and preset/stage budget freezing compute a caller-supplied integer in a returned planning capsule. That budget invariant owns no worker, grant or cached revision; no task/provider execution is inferred. Empty/invalid, max+1, Unicode and concurrent independent budgets exercise its actual input boundary."}
    if identity == "proofs-e-wz.capture-failure" and category == "stale":
        return {"kind": "not_applicable", "reason": "Audited web_backend._run_process_capture allocates one fresh owned child and stamps failures from that exact pid and invocation clock. It accepts no revision or prior receipt to become stale. Actual nonzero/malformed/timeout and owned-script OS denial retain their fresh invocation diagnostics."}
    if identity == "c7.gateway.read-only" and category in {"interrupted", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited NeyviaToolGateway.call_native refuses workspace.write under immutable read-only scope before starting an effect, worker, durable receipt or CAS lookup. No mutable revision or resumable in-progress state is reachable through this exact denial invariant; workspace commit interruption and stale CAS preservation are separately exercised under c7.workspace.rejected-preserves."}
    if identity == "files.recycle-record" and category in {"interrupted", "permissions", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited neyvia_files_tools.parse_recycle_info(data) decodes supplied immutable binary bytes synchronously. It has no filesystem, principal/grant, process checkpoint or revision argument. Exact v1/v2 field decoding and malformed v2 length refusal are parser obligations; actual Recycle Bin OS effects belong to files.trash-recoverable."}
    if identity in {"awareness.impact.command", "awareness.impact.gaps"} and category in {"interrupted", "permissions"}:
        return {"kind": "not_applicable", "reason": "Audited neyvia_impact._command_row/find_gaps project an already parsed dependency graph synchronously without mutation, principal/grant or durable checkpoint. Real source-tree parsing and file-version refresh are separately exercised; parser output never claims executable handler or rendered UI proof."}
    if identity == "awareness.claim.staleness" and category in {"permissions", "interrupted"}:
        return {"kind": "not_applicable", "reason": "Audited neyvia_awareness._view/_age_minutes compare supplied timestamps to UTC time; they write no store and read no target grant. Actual old persisted claim/refreshed activity is exercised; interrupted/denied board persistence belongs to awareness.claim.persisted/refresh."}
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--family", choices=tuple(BUILDERS))
    parser.add_argument("--category", choices=CATEGORIES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crash-operation", choices=("settings", "theme", "ambient", "transparency"))
    parser.add_argument("--crash-delivery", choices=("append", "update", "tail-update", "ack", "browser", "skipped"))
    parser.add_argument("--note-worker", choices=("first", "second"))
    parser.add_argument("--note-stamp")
    parser.add_argument("--crash-compiler", choices=("mcp", "openai"))
    args = parser.parse_args()
    root = args.root.resolve()
    _isolate(root, args.port, allow_loopback=args.family == "core-mobile")
    if args.crash_compiler:
        from .neyvia_mcp import NeyviaMCPServer
        server = NeyviaMCPServer(root)
        intelligence = server.capability_os._ensure_model_tool_intelligence()
        original_connect = sqlite3.connect
        def interrupted_connect(*positional, **kwargs):
            connection = original_connect(*positional, **kwargs)
            if Path(positional[0]).resolve() == intelligence.feedback.index_path.resolve():
                def trace(sql):
                    if sql.upper().startswith("SELECT") and "FEEDBACK_" in sql.upper():
                        os._exit(23)
                connection.set_trace_callback(trace)
            return connection
        sqlite3.connect = interrupted_connect
        if args.crash_compiler == "mcp":
            server.handle({"jsonrpc": "2.0", "id": 91, "method": "tools/call", "params": {"name": "model.tools.compile", "arguments": {"task": "Analyze Excel spreadsheet", "limit": 4}}})
        else:
            server.capability_os.compile_openai_tool_belt({"task": "Analyze Excel spreadsheet", "limit": 4})
        raise AssertionError("Compiler missed actual indexed-read process interruption")
    if args.note_worker:
        from .neyvia_notes_tools import call_notes
        (root / (args.note_worker + ".ready")).write_text("ready", encoding="utf8")
        deadline = time.monotonic() + 20
        while not (root / "go").exists():
            require(time.monotonic() < deadline, "Owned Notes race barrier expired")
            time.sleep(.01)
        result = call_notes(root, "write", {"path": "race.md", "body": (root / "race-body.txt").read_text(encoding="utf8"), "expectedModified": args.note_stamp}, "ui")
        print(json.dumps(result))
        return 0
    if args.crash_delivery:
        from .delivery_receipt import delivery_receipts_path
        target = delivery_receipts_path(root).resolve()
        original_write, original_replace = Path.write_text, os.replace
        def partial_write(path, text, *positional, **kwargs):
            if path.resolve() == target:
                with path.open("w", encoding="utf8") as handle:
                    handle.write(text[:8])
                    handle.flush()
                    os.fsync(handle.fileno())
                    os._exit(23)
            return original_write(path, text, *positional, **kwargs)
        def before_replace(source, destination):
            if Path(destination).resolve() == target:
                require(Path(source).is_file() and Path(source).stat().st_size > 8, "Atomic journal temporary contents were incomplete")
                os._exit(23)
            return original_replace(source, destination)
        Path.write_text, os.replace = partial_write, before_replace
        _delivery_action(root, args.crash_delivery)
        raise AssertionError("Delivery worker missed intended journal commit interruption")
    if args.crash_operation:
        from .neyvia_workspace_tools import workspace_for
        from .neyvia_settings import get, update
        service = workspace_for(root)
        original = service.bus.connect
        @contextmanager
        def interrupt_transaction():
            with original() as db:
                def trace(sql):
                    if args.crash_operation in {"settings", "theme"} and sql.startswith("INSERT OR REPLACE INTO state") and "density" in sql:
                        os._exit(23)
                    if args.crash_operation in {"ambient", "transparency"} and sql == "COMMIT":
                        os._exit(23)
                db.set_trace_callback(trace)
                yield db
        service.bus.connect = interrupt_transaction
        if args.crash_operation == "settings":
            update(service, {"theme": "sunset", "density": "grove"}, get(service)["revision"])
        else:
            from .neyvia_view_tools import call as view
            operation, payload = {"theme": ("view.theme", {"theme": "night"}), "ambient": ("view.ambient", {"on": False}), "transparency": ("view.transparency", {"level": "minimal"})}[args.crash_operation]
            view(service, operation, payload)
        raise AssertionError("Settings worker missed intended crash point")
    if args.family:
        try:
            identities, detail = BUILDERS[args.family](root, args.category)
            value = {"contracts": identities, "detail": detail, "status": "passed"}
        except BaseException as error:
            value = {"contracts": INTENDED[args.family], "detail": {"type": type(error).__name__, "error": str(error)}, "status": "failed"}
        if args.output:
            from .proof_contracts import REPO, source_digest
            value.update(explicitPort=args.port, family=args.family, category=args.category,
                         sourceBindings={name: source_digest(REPO / name) for name in ("src/grant_agent/edge_fixture_c7d_local.py", "src/grant_agent/delivery_receipt.py")})
            if args.family == "routing-benchmark":
                value["sourceBindings"]["src/grant_agent/capability_service.py"] = source_digest(REPO / "src/grant_agent/capability_service.py")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")
        print(json.dumps(value))
        return int(value["status"] != "passed")
    from .edge_contracts import inventory
    _, contracts = inventory()
    rows = run(root, contracts, CATEGORIES)
    report = {"schema": "neyvia.c7d.local-completion.v1", "explicitPort": args.port, "rows": rows,
              "ok": all(row["status"] == "passed" for row in rows),
              "passedPairs": len({(identity, row["category"]) for row in rows if row["status"] == "passed" for identity in row["contracts"]})}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"ok": report["ok"], "passedPairs": report["passedPairs"], "failures": [row for row in rows if row["status"] != "passed"]}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
