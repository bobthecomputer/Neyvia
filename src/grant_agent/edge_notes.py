"""Adversarial Notes/Files journeys on disposable production state, not a test suite."""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _reject(action, kind=ValueError):
    try:
        action()
    except kind as error:
        return str(error)
    raise ValueError("Invalid action was accepted")


def _worker(root, identity, stamp):
    from .neyvia_notes_tools import call_notes
    base = Path(root)
    (base / (identity + ".ready")).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 15
    while not (base / "go").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("Concurrent start barrier expired")
        time.sleep(0.01)
    result = call_notes(base, "write", {"path": "race.md", "body": identity,
                                        "expectedModified": stamp}, "ui")
    print(json.dumps({"pid": os.getpid(), "result": result}))


def _offline(root):
    from .neyvia_notes_tools import call_notes
    from .neyvia_files_tools import call_files
    attempts = []

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            attempts.append(event)
            raise PermissionError("Offline journey forbids network access")

    sys.addaudithook(audit)
    note = call_notes(Path(root), "write", {"path": "offline.md", "body": "local #offline"}, "ui")
    read = call_notes(Path(root), "read", {"path": note["path"]}, "ui")
    found = call_notes(Path(root), "search", {"query": "#offline"}, "ui")
    listed = call_files(Path(root), "list", {"path": str(Path(root) / "notes")}, "ui")
    _require(read["body"] == "local #offline" and found["total"] == 1 and listed["ok"], "Offline local journey failed")
    _require(not attempts, "Network access attempted during local journey")
    print(json.dumps({"networkAttempts": attempts, "socketAuditEnforced": True, "actions": 4}))


def run(root):
    from . import neyvia_notes_tools as notes
    from .neyvia_files_tools import call_files
    from .ui_command_bus import bus_for
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="edge-notes-", dir=base))
    folder = scratch / "notes"
    folder.mkdir()
    bus_for(scratch).put("notes:folder", str(folder))
    rows = []

    def note(op, args):
        return notes.call_notes(scratch, op, args, "ui")

    def files(op, args):
        return call_files(scratch, op, args, "ui")

    def case(category, contracts, action):
        started = time.perf_counter()
        try:
            detail = action()
            status = "passed"
        except NotImplementedError as error:
            detail, status = {"reason": str(error)}, "blocked"
        except Exception as error:
            detail, status = {"error": str(error), "type": type(error).__name__}, "failed"
        rows.append({"id": "notes-files." + category, "category": category, "contracts": contracts,
                     "status": status, "detail": detail, "scratchRoot": str(scratch),
                     "durationMs": round((time.perf_counter() - started) * 1000, 3)})

    def empty():
        _require(note("list", {})["total"] == 0, "Fresh Notes list is not empty")
        _require(files("list", {"path": str(folder)})["entries"] == [], "Fresh Files list is not empty")
        note("write", {"path": "empty.md", "body": ""})
        _require(note("read", {"path": "empty.md"})["body"] == "", "Empty note changed")
        _require((folder / "empty.md").read_bytes() == b"", "Empty bytes changed")
        return {"bytes": 0, "invalidSearch": _reject(lambda: note("search", {"query": ""})),
                "invalidPath": _reject(lambda: note("read", {"path": "../outside.md"}))}

    def huge():
        note("write", {"path": "large.md", "body": "x" * notes.MAX_BYTES})
        path = folder / "large.md"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        replacement = _reject(lambda: note("write", {"path": "large.md", "body": "é" * (notes.MAX_BYTES // 2 + 1)}))
        append = _reject(lambda: note("write", {"path": "large.md", "body": "x", "mode": "append"}))
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, "Rejected oversized action changed bytes")
        preview = files("stat", {"path": str(path), "preview": True})
        return {"acceptedBytes": path.stat().st_size, "sha256": digest,
                "replacementRejected": replacement, "appendRejected": append, "filePreviewOk": preview["ok"]}

    def unicode():
        body = "# Idée 日本語 🧭\r\n\r\nCafé #été שלום\rline\n"
        note("write", {"path": "日本語 🧭.md", "body": body})
        read = note("read", {"path": "日本語 🧭.md"})
        _require(read["body"] == body, "Read normalized Unicode or line endings")
        note("write", {"path": read["path"], "body": "fin 🦉", "mode": "append", "expectedModified": read["modified"]})
        expected = (body + "\n" + "fin 🦉").encode("utf-8")
        _require((folder / read["path"]).read_bytes() == expected, "Unicode append bytes differ")
        _require(read["tags"] == ["été"], "Unicode tag was lost")
        target = folder / "Renommé 🧭.md"
        files("move", {"from": str(folder / read["path"]), "to": str(target)})
        _require(target.read_bytes() == expected, "Files move changed Unicode bytes")
        files("undo", {})
        _require((folder / read["path"]).read_bytes() == expected, "Files undo changed bytes")
        return {"utf8Bytes": len(expected), "sha256": hashlib.sha256(expected).hexdigest(),
                "exactLineEndings": True, "moveUndo": True}

    def concurrency():
        created = note("write", {"path": "race.md", "body": "seed"})
        commands = [[sys.executable, "-m", "grant_agent.edge_notes", "worker", str(scratch), who, created["modified"]]
                    for who in ("writer-a", "writer-b")]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8", **hidden_windows_subprocess_kwargs()) for command in commands]
        try:
            deadline = time.monotonic() + 15
            while not all((scratch / (who + ".ready")).exists() for who in ("writer-a", "writer-b")):
                _require(time.monotonic() < deadline and all(p.poll() is None for p in processes), "Concurrent workers did not reach barrier")
                time.sleep(0.01)
            (scratch / "go").write_text("go", encoding="utf-8")
            receipts = []
            for process in processes:
                output, error = process.communicate(timeout=20)
                _require(process.returncode == 0, "Concurrent worker failed: " + error)
                receipts.append(json.loads(output))
            accepted = [r for r in receipts if r["result"].get("ok")]
            conflicts = [r for r in receipts if r["result"].get("status") == "conflict"]
            _require(len(accepted) == len(conflicts) == 1, "Same-stamp concurrent writes must yield one winner and one conflict")
            _require((folder / "race.md").read_text(encoding="utf-8") in {"writer-a", "writer-b"}, "Concurrent body lost")
            _require(accepted[0]["result"]["modified"] != created["modified"], "Winner reused original modification stamp")
            return {"sameExpectedModified": created["modified"], "workers": receipts, "processes": 2}
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def interrupted():
        note("write", {"path": "interrupt.md", "body": "keeper"})
        path = folder / "interrupt.md"
        original = path.read_bytes()
        original_replace = notes.os.replace
        invoked = []

        def interrupt(source, destination):
            if Path(destination) == path:
                invoked.append({"temporaryBytes": Path(source).stat().st_size, "destination": str(destination)})
                raise KeyboardInterrupt("C7 explicit fault at atomic replacement boundary")
            return original_replace(source, destination)

        notes.os.replace = interrupt
        try:
            error = _reject(lambda: note("write", {"path": path.name, "body": "replacement"}), KeyboardInterrupt)
        finally:
            notes.os.replace = original_replace
        _require(invoked and path.read_bytes() == original and not list(folder.glob(".~*.tmp")), "Interrupted atomic write lost bytes or leaked temporary file")
        note("write", {"path": path.name, "body": "retry succeeds"})
        return {"faultKind": "explicit KeyboardInterrupt at os.replace", "fault": error,
                "boundary": invoked, "originalPreserved": True, "tempFiles": 0, "retrySucceeded": True}

    def permissions():
        if os.name != "nt":
            raise NotImplementedError("Target-specific Windows sharing-denial proof requires Windows")
        note("write", {"path": "permission.md", "body": "keeper"})
        path = folder / "permission.md"
        original = path.read_bytes()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                           ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        create.restype = ctypes.c_void_p
        close = kernel.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = ctypes.c_int
        # Permit readers, deny delete/replace only for this disposable target.
        handle = create(str(path), 0x80000000, 1, None, 3, 0, None)
        _require(handle not in (None, ctypes.c_void_p(-1).value), "Cannot acquire target sharing lock")
        try:
            error = _reject(lambda: note("write", {"path": path.name, "body": "forbidden"}), PermissionError)
            _require(path.read_bytes() == original and not list(folder.glob(".~*.tmp")), "Permission failure changed target or leaked temp")
        finally:
            close(handle)
        note("write", {"path": path.name, "body": "released"})
        return {"nativeDenial": error, "method": "CreateFileW FILE_SHARE_READ denies replacement", "targetOnly": True,
                "originalPreserved": True, "tempFiles": 0, "retrySucceeded": True}

    def offline():
        command = [sys.executable, "-m", "grant_agent.edge_notes", "offline", str(scratch)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20, **hidden_windows_subprocess_kwargs())
        _require(result.returncode == 0, result.stderr)
        return json.loads(result.stdout)

    def stale():
        first = note("write", {"path": "stale.md", "body": "first"})
        second = note("write", {"path": first["path"], "body": "second", "expectedModified": first["modified"]})
        path = folder / first["path"]
        original = path.read_bytes()
        rejected = note("write", {"path": first["path"], "body": "lost", "expectedModified": first["modified"]})
        _require(rejected.get("status") == "conflict" and path.read_bytes() == original, "Stale writer overwrote newer bytes")
        occupied = folder / "occupied.md"
        occupied.write_bytes(b"other keeper")
        collision = _reject(lambda: files("move", {"from": str(path), "to": str(occupied)}))
        _require(path.read_bytes() == original and occupied.read_bytes() == b"other keeper", "Move collision changed bytes")
        target = folder / "moved.md"
        files("move", {"from": str(path), "to": str(target)})
        files("undo", {})
        consumed = _reject(lambda: files("undo", {}))
        return {"oldStamp": first["modified"], "newStamp": second["modified"], "conflict": rejected,
                "moveCollision": collision, "secondUndo": consumed, "preservedBytes": True}

    case("empty", ["notes.path-jail", "notes.body-durable"], empty)
    case("huge", ["notes.body-durable", "notes.write-bounded"], huge)
    case("unicode", ["notes.body-durable", "notes.prose-metadata", "files.move-conservation", "files.undo-once"], unicode)
    case("concurrency", ["notes.stale-preserves", "notes.concurrent-writes"], concurrency)
    case("interrupted", ["notes.atomic-interruption"], interrupted)
    case("permissions", ["notes.permission-preserves"], permissions)
    case("offline", ["notes.local-offline", "notes.body-durable"], offline)
    case("stale", ["notes.stale-preserves", "files.no-overwrite", "files.undo-once"], stale)
    return rows


if __name__ == "__main__":
    if sys.argv[1] == "worker":
        _worker(*sys.argv[2:])
    elif sys.argv[1] == "offline":
        _offline(sys.argv[2])
    else:
        result = run(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1 if any(row["status"] != "passed" for row in result) else 0)
