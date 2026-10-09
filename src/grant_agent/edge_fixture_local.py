"""Generated, disposable feature fixtures for local semantic contract families.

Bindings name the invariants actually observed. Merely running a family never
counts every contract/category as covered. Workers install the credential guard
before constructing product services and offline workers deny actual sockets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager


def require(value, message):
    if not value:
        raise AssertionError(message)


def refused(call, kind=ValueError):
    try:
        result = call()
    except kind as error:
        return {"exception": type(error).__name__, "message": str(error)}
    require(isinstance(result, dict) and result.get("ok") is False, "Rejected operation succeeded")
    return {"status": result.get("status"), "error": result.get("error")}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def replacement_fault(module, target, kind):
    """Fault injection at a real production commit boundary, never a handler mock."""
    original = module.os.replace
    calls = []
    def replace(source, destination):
        if Path(destination).resolve() == target.resolve():
            calls.append({"destination": str(destination), "temporaryBytes": Path(source).stat().st_size})
            raise kind("Owned fixture fault before durable replacement")
        return original(source, destination)
    module.os.replace = replace
    try:
        yield calls
    finally:
        module.os.replace = original


def _body(category, *, maximum=1024 * 1024):
    if category == "empty":
        return ""
    if category == "huge":
        return "x" * maximum
    if category == "unicode":
        return "# Idée 日本語 🧭\r\nCafé #Été #été `#hidden` page#anchor #a1b2c3 שלום\rline\n"
    return "# Owned fixture\nBody #fixture\n"


def _parallel(action, values):
    barrier = threading.Barrier(len(values))
    def invoke(value):
        barrier.wait(timeout=15)
        return action(value)
    with ThreadPoolExecutor(max_workers=len(values)) as pool:
        return list(pool.map(invoke, values))


def _workspace(root, category):
    from .native_tools import NativeToolRegistry
    registry = NativeToolRegistry(root, nas_root=root)
    root.mkdir(parents=True, exist_ok=True)
    body = _body(category)
    write = lambda payload: registry.call("workspace.write", payload)
    result = write({"path": "effect.txt", "content": body})
    require(result.get("ok"), str(result))
    raw = (root / "effect.txt").read_bytes()
    require(raw == body.encode("utf-8"), "Workspace persisted bytes differ")
    contracts = ["c7.workspace.rejected-preserves"]
    detail = {"bytes": len(raw), "sha256": sha(raw), "readbackVerified": result["result"].get("readbackVerified")}
    if category in {"empty", "huge", "unicode"}:
        invalid = ({"content": "x" * (1024 * 1024 + 1)} if category == "huge" else
                   {"content": "a\x00b"} if category == "unicode" else {"content": "replacement", "expectedSha256": "a" * 64})
        detail["refusal"] = refused(lambda: write({"path": "missing-parent/refused.txt", **invalid}))
        require(not (root / "missing-parent").exists(), "Rejected workspace write created parent")
    elif category == "stale":
        newer = write({"path": "effect.txt", "content": "newer", "expectedSha256": sha(raw)})
        require(newer.get("ok"), "Fresh workspace CAS was rejected")
        detail["refusal"] = refused(lambda: write({"path": "effect.txt", "content": "lost", "expectedSha256": sha(raw)}))
        require((root / "effect.txt").read_bytes() == b"newer", "Stale workspace request changed bytes")
    elif category == "concurrency":
        outcomes = _parallel(lambda content: write({"path": "effect.txt", "content": content, "expectedSha256": sha(raw)}), ["writer-a", "writer-b"])
        require(sum(bool(row.get("ok")) for row in outcomes) == 1, "Workspace same-hash race requires one winner")
        require((root / "effect.txt").read_bytes() in {b"writer-a", b"writer-b"}, "Workspace race bytes lost")
        detail["outcomes"] = outcomes
    elif category == "permissions":
        from .neyvia_agent import NeyviaToolGateway
        from .proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(root)
        gateway = NeyviaToolGateway(root, allow_mutations=False, permission_mode="read-only")
        detail["refusal"] = refused(lambda: gateway.call_native("workspace.write", {"path": "forbidden.txt", "content": "lost"}))
        require(not (root / "forbidden.txt").exists(), "Read-only gateway created file")
        contracts = ["c7.gateway.read-only"]
    elif category == "interrupted":
        raise NotImplementedError("Workspace interruption has no audited commit fault seam; use Notes/action-store atomic interruption fixtures")
    if category != "permissions":
        observed_raw = (root / "effect.txt").read_bytes()
        observed_text = observed_raw.decode("utf-8")
        read = registry.call("workspace.read", {"path": "effect.txt", "maxChars": 31})
        require(read.get("ok") and read["result"]["content"] == observed_text[:31]
                and read["result"]["sha256"] == sha(observed_raw), "Bounded workspace read differs from bytes")
        refused(lambda: registry.call("workspace.read", {"path": "../outside.txt"}))
        search_text = "owned-marker-雪🙂\n"
        require(write({"path": "search.txt", "content": search_text}).get("ok"), "Search fixture write failed")
        search = registry.call("workspace.search", {"query": "owned-marker", "includeGlob": "search.txt", "maxResults": 2})
        require(search.get("ok") and search["result"]["count"] == 1
                and search["result"]["matches"][0]["path"] == "search.txt"
                and search["result"]["matches"][0]["snippet"] == search_text.strip(), "Workspace search projection differs")
        contracts.append("native.tools.workspace")
        detail["readSearchVerified"] = True
    return contracts, detail


def _notes_files(root, category):
    from . import neyvia_notes_tools as notes
    from .neyvia_files_tools import call_files
    from .ui_command_bus import bus_for
    folder = root / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    bus_for(root).put("notes:folder", str(folder))
    note = lambda operation, args: notes.call_notes(root, operation, args, "ui")
    files = lambda operation, args: call_files(root, operation, args, "ui")
    name = "日本語 🧭.md" if category == "unicode" else "effect.md"
    body = _body(category, maximum=notes.MAX_BYTES)
    created = note("write", {"path": name, "body": body})
    path = folder / name
    raw = path.read_bytes()
    require(raw == body.encode("utf-8"), "Notes persisted bytes differ")
    contracts = ["notes.body-durable"]
    detail = {"bytes": len(raw), "sha256": sha(raw)}
    if category in {"empty", "huge", "unicode", "offline"}:
        read = note("read", {"path": name})
        require(read["body"] == body and read["modified"] == created["modified"], "Notes read body/stamp changed")
        require(read["title"] == ("Idée 日本語 🧭" if category == "unicode" else "effect" if category in {"empty", "huge"} else "Owned fixture"), "Notes title projection differs")
        require(read["tags"] == (["été"] if category == "unicode" else ["fixture"] if category == "offline" else []), "Notes prose tags differ")
        contracts.append("notes.prose-metadata")
        note("pin", {"path": name, "pinned": True})
        require(name in json.loads((folder / notes.META).read_text(encoding="utf-8"))["pinned"], "Notes pin not persisted")
        note("pin", {"path": name, "pinned": False})
        require(name not in json.loads((folder / notes.META).read_text(encoding="utf-8"))["pinned"], "Notes unpin not persisted")
        contracts.append("notes.pin-durable")
        refused(lambda: note("read", {"path": "../outside.md"}))
        refused(lambda: note("read", {"path": "effect.exe"}))
        contracts.append("notes.path-jail")
        replaced = note("write", {"path": name, "body": body, "expectedModified": read["modified"]})
        require(path.read_bytes() == raw and replaced["modified"] != read["modified"], "Notes replacement bytes/stamp differ")
        if category == "huge":
            refused(lambda: note("write", {"path": name, "body": "x", "mode": "append"}))
            refused(lambda: note("write", {"path": name, "body": "é" * (notes.MAX_BYTES // 2 + 1)}))
            require(path.read_bytes() == raw, "Rejected huge note changed bytes")
            contracts.append("notes.write-bounded")
        else:
            suffix = "" if category == "empty" else "fin 🦉"
            note("write", {"path": name, "body": suffix, "mode": "append", "expectedModified": replaced["modified"]})
            expected = ("" if category == "empty" else body + "\n" + suffix).encode("utf-8")
            require(path.read_bytes() == expected and note("read", {"path": name})["body"].encode("utf-8") == expected, "Notes append/read bytes differ")
            raw = expected
        target = folder / "moved.md"
        occupied = folder / "occupied.md"
        occupied.write_bytes(b"keeper")
        refused(lambda: files("move", {"from": str(path), "to": str(occupied)}))
        require(path.read_bytes() == raw and occupied.read_bytes() == b"keeper", "Move collision changed bytes")
        files("move", {"from": str(path), "to": str(target)})
        require(not path.exists() and target.read_bytes() == raw, "Files move lost bytes")
        files("undo", {})
        require(path.read_bytes() == raw and not target.exists(), "Files undo lost bytes")
        refused(lambda: files("undo", {}))
        contracts += ["files.no-overwrite", "files.move-conservation", "files.undo-once"]
        directory = folder / "new-folder"
        files("mkdir", {"path": str(directory)})
        require(directory.is_dir(), "Files mkdir did not persist")
        files("undo", {})
        require(not directory.exists(), "Mkdir undo did not restore absence")
        contracts.append("files.mkdir-durable")
        if category == "offline":
            note("search", {"query": "#fixture"})
            require(files("list", {"path": str(folder)})["ok"], "Offline Files listing failed")
            contracts.append("notes.local-offline")
    elif category in {"stale", "concurrency"}:
        if category == "concurrency":
            outcomes = _parallel(lambda content: note("write", {"path": name, "body": content, "expectedModified": created["modified"]}), ["writer-a", "writer-b"])
            require(sum(bool(row.get("ok")) for row in outcomes) == 1 and sum(row.get("status") == "conflict" for row in outcomes) == 1, "Concurrent Notes same-stamp race requires one winner/conflict")
            detail["outcomes"] = outcomes
            # Cross-process race proof is supplied by edge_notes; this thread
            # fixture binds only the stale-preservation invariant.
        else:
            note("write", {"path": name, "body": "newer", "expectedModified": created["modified"]})
            before = path.read_bytes()
            answer = note("write", {"path": name, "body": "lost", "expectedModified": created["modified"]})
            require(answer.get("status") == "conflict" and path.read_bytes() == before, "Stale Notes write overwrote bytes")
        contracts = ["notes.stale-preserves", "notes.body-durable"]
    elif category in {"interrupted", "permissions"}:
        kind = KeyboardInterrupt if category == "interrupted" else PermissionError
        with replacement_fault(notes, path, kind) as calls:
            refused(lambda: note("write", {"path": name, "body": "lost"}), kind)
        require(calls and path.read_bytes() == raw and not list(folder.glob(".~*.tmp")), "Notes replacement fault lost bytes or leaked temporary file")
        note("write", {"path": name, "body": "retry"})
        require(path.read_bytes() == b"retry", "Notes fault retry failed")
        contracts = ["notes.atomic-interruption"] if category == "interrupted" else []
        # Permission injection proves cleanup but is not an OS denial. The
        # Windows sharing-lock journey is the authority for permission-preserves.
        detail.update(boundary=calls, injection=kind.__name__, originalPreserved=True)
    return contracts, detail


def _settings(root, category):
    from .neyvia_workspace_tools import workspace_for
    from .neyvia_settings import get, update, SettingsConflict, THEMES
    service = workspace_for(root)
    before = get(service)
    contracts = []
    if category in {"empty", "huge", "unicode"}:
        patch = {} if category == "empty" else {"projectInitiative": {str(root / str(i)): "suggest" for i in range(201)}} if category == "huge" else {"theme": "forest\x00🙂"}
        refused(lambda: update(service, patch, before["revision"]))
        require(get(service) == before, "Invalid settings patch changed state")
        contracts = ["settings.invalid-preserves"]
    elif category == "stale":
        update(service, {"theme": "morning"}, before["revision"])
        newer = get(service)
        refused(lambda: update(service, {"theme": "sunset"}, before["revision"]), SettingsConflict)
        require(get(service) == newer, "Stale settings patch changed canonical state")
        contracts = ["settings.revision-cas"]
    elif category == "concurrency":
        def contender(theme):
            try:
                return update(service, {"theme": theme}, before["revision"])
            except SettingsConflict:
                return {"conflict": True}
        outcomes = _parallel(contender, ["morning", "sunset"])
        require(sum(bool(row.get("conflict")) for row in outcomes) == 1, "Settings race lost CAS winner/conflict")
        require(get(service)["revision"] == before["revision"] + 1, "Settings race incremented revision twice")
        contracts = ["settings.revision-cas", "settings.canonical-mirrors"]
    elif category == "offline":
        result = update(service, {"theme": "morning", "density": "grove", "nightShift": {"paused": True}}, before["revision"])
        require(result["revision"] == before["revision"] + 1, "Settings update revision differs")
        require(service.bus.get("theme") == THEMES[result["settings"]["theme"]] and service.bus.get("density")["level"] == "grove", "Settings canonical mirrors differ")
        require(service.bus.get("nightshift.resources") == result["settings"]["nightShift"], "Night policy mirror differs")
        with service.bus.connect() as db:
            durable = [(row["action"], json.loads(row["payload"])) for row in db.execute("SELECT action,payload FROM events ORDER BY id")]
        expected = [(row["action"], row["payload"]) for row in result["events"]]
        require(durable[-len(expected):] == expected and sum(action == "nightshift.resources.updated" for action, _ in expected) == 1, "Settings durable event projection differs")
        contracts = ["settings.revision-cas", "settings.canonical-mirrors", "settings.night-policy-event"]
    else:
        raise NotImplementedError("Canonical Settings has no target OS denial/interruption fixture; process-global policy makes fabricated permission rows invalid")
    return contracts, {"beforeRevision": before["revision"], "afterRevision": get(service)["revision"], "durableState": get(service)["settings"]}


def _awareness(root, category):
    from . import neyvia_awareness as awareness
    from datetime import datetime, timedelta, timezone
    root.mkdir(parents=True, exist_ok=True)
    claim = lambda args: awareness.claim(root, args)
    path = awareness.board_path(root)
    contracts = []
    if category == "empty":
        require(awareness.board_list(root)["count"] == 0, "Fresh board nonempty")
        refused(lambda: claim({"files": [], "intent": "owned"}))
        require(not path.exists(), "Invalid awareness input created durable board")
        contracts.append("awareness.list.projection")
    if category == "huge":
        refused(lambda: claim({"files": [str(i) for i in range(101)], "intent": "owned"}))
        huge_paths = ["large/" + str(i) for i in range(100)]
        receipt = claim({"files": huge_paths, "agent": "bounded", "intent": "x" * 300})
        durable = json.loads(path.read_text(encoding="utf-8"))
        require(durable["claims"][0]["files"] == huge_paths and durable["claims"][0]["intent"] == "x" * 300, "Maximum-size board claim differs")
        projection = awareness.board_list(root, {"files": ["large/99"]})
        require(projection["count"] == 1 and projection["claims"][0]["files"] == huge_paths, "Huge claim list projection differs")
        refreshed = claim({"files": huge_paths, "agent": "bounded", "intent": "y" * 300})
        require(refreshed["refreshed"] and refreshed["claim"]["id"] == receipt["claim"]["id"] and refreshed["claim"]["since"] == receipt["claim"]["since"], "Bounded claim refresh lost original identity/age")
        overlapping = claim({"files": ["large/99/file.txt"], "agent": "other", "intent": "Bounded overlap"})
        require([row["id"] for row in overlapping["overlaps"]] == [receipt["claim"]["id"]] and awareness.overlaps("large/99", "large/99/file.txt") and not awareness.overlaps("large/99", "large/990/file.txt"), "Large claim overlap lost exact path boundary")
        awareness.release(root, {"id": overlapping["claim"]["id"]})
        release = awareness.release(root, {"id": receipt["claim"]["id"]})
        require(release["files"] == huge_paths and awareness.board_list(root)["count"] == 0, "Huge claim release differs")
        return ["awareness.claim.persisted", "awareness.claim.refresh", "awareness.claim.overlaps", "awareness.paths.overlap", "awareness.list.projection", "awareness.release.persisted"], {"acceptedPaths": 100, "acceptedIntentChars": 300, "overBoundRefused": True}
    prefix = "雪/café" if category == "unicode" else "src/owned"
    a = claim({"files": [prefix, prefix], "agent": "a", "chat": "first", "intent": "Owned fixture 🙂"})
    require(a["claim"]["files"] == [prefix], "Claim normalization differs")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    require(persisted["claims"][0]["id"] == a["claim"]["id"] and persisted["claims"][0]["intent"] == "Owned fixture 🙂", "Claim persistence differs")
    contracts += ["awareness.claim.persisted"]
    if category == "concurrency":
        rows = _parallel(lambda index: claim({"files": [prefix + "/" + str(index)], "agent": str(index), "intent": "Concurrent owned claim"}), [1, 2])
        require(awareness.board_list(root)["count"] == 3, "Concurrent board claims lost")
        require(all(row["overlaps"] for row in rows), "Concurrent overlap omitted original claim")
    if category == "stale":
        old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        persisted["claims"][0].update(since=old, updatedAt=old)
        path.write_text(json.dumps(persisted), encoding="utf-8")
        observed = awareness.board_list(root)
        require(observed["stale"] == 1 and observed["claims"][0]["ageMinutes"] >= 780, "Board stale age projection differs")
    first = json.loads(path.read_text(encoding="utf-8"))["claims"][0]
    refreshed = claim({"files": [prefix], "agent": "a", "chat": "first", "intent": "Refreshed fixture"})
    require(refreshed["refreshed"] and refreshed["claim"]["id"] == a["claim"]["id"] and refreshed["claim"]["since"] == first["since"] and not refreshed["claim"]["stale"], "Board refresh lost original age/id or remained stale")
    contracts += ["awareness.claim.refresh"]
    if category == "stale":
        contracts.append("awareness.claim.staleness")
    b = claim({"files": [prefix + "/file.txt"], "agent": "b", "intent": "Overlap fixture"})
    require({row["id"] for row in b["overlaps"]} == {row["id"] for row in json.loads(path.read_text(encoding="utf-8"))["claims"] if row["id"] != b["claim"]["id"] and any(awareness.overlaps(file, prefix + "/file.txt") for file in row["files"])}, "Board overlap receipt differs")
    require(awareness.overlaps(prefix, prefix + "/file.txt") and not awareness.overlaps(prefix, prefix + "-other/file.txt"), "Path overlap accepted incomplete boundary")
    contracts += ["awareness.claim.overlaps", "awareness.paths.overlap"]
    projection = awareness.board_list(root, {"agent": "b"})
    require(projection["count"] == 1 and projection["claims"][0]["id"] == b["claim"]["id"], "Board filter projection differs")
    contracts += ["awareness.list.projection"]
    if category == "interrupted":
        before = path.read_bytes()
        with replacement_fault(awareness, path, KeyboardInterrupt) as calls:
            refused(lambda: claim({"files": ["interrupted/file"], "agent": "crash", "intent": "Interrupted fixture"}), KeyboardInterrupt)
        require(calls and path.read_bytes() == before, "Interrupted awareness write changed durable board")
    elif category == "permissions":
        from .edge_fixture_missions import exclusive
        before = path.read_bytes()
        with exclusive(path):
            refused(lambda: claim({"files": [prefix], "agent": "a", "chat": "first", "intent": "Denied refresh"}), OSError)
            refused(lambda: awareness.release(root, {"id": b["claim"]["id"]}), (OSError, ValueError))
            denied_view = awareness.board_list(root)
            require(denied_view["count"] == 0, "Denied board reader invented accessible claims")
        require(path.read_bytes() == before, "Native sharing denial changed durable claims/archive")
        refreshed_after_denial = claim({"files": [prefix], "agent": "a", "chat": "first", "intent": "Recovered refresh"})
        require(refreshed_after_denial["refreshed"] and refreshed_after_denial["claim"]["id"] == a["claim"]["id"], "Released native sharing denial lost claim identity")
    release = awareness.release(root, {"id": b["claim"]["id"]})
    durable = json.loads(path.read_text(encoding="utf-8"))
    require(release["files"] == [prefix + "/file.txt"] and all(row["id"] != b["claim"]["id"] for row in durable["claims"]) and durable["released"][0]["id"] == b["claim"]["id"], "Release changed wrong claims or omitted archive")
    contracts.append("awareness.release.persisted")
    return contracts, {"claimId": a["claim"]["id"], "releasedId": b["claim"]["id"], "activeClaims": len(durable["claims"]), "persistedSha256": sha(path.read_bytes())}


def _actions(root, category):
    from .action_receipts import NativeActionStore
    store = NativeActionStore(root, "owned-fixture")
    identity = "" if category == "empty" else "x" * 161 if category == "huge" else "action-雪🙂" if category == "unicode" else "action"
    count = []
    effect = root / "effect.txt"
    content = b"" if category == "empty" else b"x" * 131072 if category == "huge" else "雪🙂é שלום".encode() if category == "unicode" else b"one owned effect"
    def action():
        count.append(True)
        effect.write_bytes(content)
        return {"ok": True, "sha256": sha(effect.read_bytes()), "rawBody": "unapproved body", "toolResult": {"status": "written", "password": "synthetic forbidden", "nested": {"api_key": "synthetic forbidden", "bytes": effect.stat().st_size}}}
    if category in {"empty", "huge"}:
        refused(lambda: store.execute(identity, "workspace.write", {"path": "effect.txt"}, action))
        require(not count and not effect.exists() and not list(store.base.glob("*.json")), "Rejected action id executed effect")
        # Recover with a valid identity and actual category-specific effect;
        # admission alone never establishes at-most-once or sanitization.
        identity = "x" * 160 if category == "huge" else "empty-body-action"
    if category == "permissions":
        refused(lambda: store.execute(identity, "workspace.write", {}, action, preflight=lambda: (_ for _ in ()).throw(PermissionError("Owned mutation grant denied"))), PermissionError)
        require(not count and not effect.exists() and not list(store.base.glob("*.json")), "Denied preflight persisted pending or invoked effect")
        # A separately allowed real action below proves durable completion and
        # suppression after the rejected precondition leaves no pending record.
    if category == "interrupted":
        def interrupted():
            action()
            raise KeyboardInterrupt("Owned interruption after real effect")
        refused(lambda: store.execute(identity, "workspace.write", {}, interrupted), KeyboardInterrupt)
        answer = NativeActionStore(root, "owned-fixture").execute(identity, "workspace.write", {}, action)
        require(answer.get("status") == "action_uncertain" and len(count) == 1 and effect.read_bytes() == content, "Interrupted effect implicitly replayed")
        # Interrupt the actual sanitized result publication as a distinct
        # identity, then independently inspect every published receipt.
        from . import durability
        safe_identity = "interrupted-sanitized-result"
        result_path = store._path(safe_identity).with_suffix(".result")
        with replacement_fault(durability, result_path, KeyboardInterrupt) as commits:
            refused(lambda: store.execute(safe_identity, "workspace.write", {}, action), KeyboardInterrupt)
        safe_replay = NativeActionStore(root, "owned-fixture").execute(safe_identity, "workspace.write", {}, action)
        require(commits and safe_replay["status"] == "action_uncertain" and len(count) == 2 and not result_path.exists(), "Interrupted sanitized result publication replayed effect or fabricated completion")
        published = "\n".join(path.read_text(encoding="utf8") for path in store.base.glob("*.json"))
        require("synthetic forbidden" not in published and "unapproved body" not in published, "Interrupted receipts leaked raw/credential fields")
        return ["proofs-e-host.action-once", "proofs-e-host.action-sanitization"], {"resumeStatus": answer["status"], "effects": len(count), "effectSha256": sha(effect.read_bytes()), "sanitizedResultPublicationInterrupted": True}
    if category == "concurrency":
        results = _parallel(lambda _: store.execute(identity, "workspace.write", {"path": "effect.txt"}, action), [1, 2])
        require(sum(bool(row.get("duplicateSuppressed")) for row in results) == 1, "Concurrent action produced wrong replay outcome")
        first = next(row for row in results if not row.get("duplicateSuppressed"))
    else:
        first = store.execute(identity, "workspace.write", {"path": "effect.txt"}, action)
    replay = NativeActionStore(root, "owned-fixture").execute(identity, "workspace.write", {"path": "effect.txt"}, action)
    require(replay.get("duplicateSuppressed") and len(count) == 1 and effect.read_bytes() == content, "Completed action replayed effect")
    require(first["sha256"] == replay["sha256"] and first["toolResult"] == replay["toolResult"], "Durable replay changed exact semantic result")
    result_path = Path(first["actionReceiptPath"]).with_suffix(".result")
    saved = result_path.read_text(encoding="utf-8")
    require("synthetic forbidden" not in saved and "unapproved body" not in saved, "Receipt leaked prohibited nested fields/raw body")
    if category == "stale":
        conflict = store.execute(identity, "workspace.write", {"path": "different.txt"}, action)
        require(conflict.get("ok") is False and len(count) == 1 and not (root / "different.txt").exists(), "Changed request reused completed action identity")
    return ["proofs-e-host.action-once", "proofs-e-host.action-sanitization"], {"effects": len(count), "savedResultSha256": sha(result_path.read_bytes()), "replaySuppressed": True, "sanitized": True}


BUILDERS = {"workspace": _workspace, "notes-files": _notes_files, "settings": _settings, "awareness": _awareness, "actions": _actions}


def intended_bindings(family, category):
    """Retain exact intended obligations when a feature fails before readback."""
    if family == "workspace":
        return ["c7.gateway.read-only"] if category == "permissions" else [] if category == "interrupted" else ["c7.workspace.rejected-preserves", "native.tools.workspace"]
    if family == "notes-files":
        if category in {"stale", "concurrency"}:
            return ["notes.stale-preserves", "notes.body-durable"]
        if category == "interrupted":
            return ["notes.atomic-interruption"]
        if category == "permissions":
            return []
        return ["notes.body-durable", "notes.prose-metadata", "notes.pin-durable", "notes.path-jail", "files.no-overwrite", "files.move-conservation", "files.undo-once", "files.mkdir-durable", *(["notes.write-bounded"] if category == "huge" else []), *(["notes.local-offline"] if category == "offline" else [])]
    if family == "settings":
        if category in {"empty", "huge", "unicode"}:
            return ["settings.invalid-preserves"]
        return {"stale": ["settings.revision-cas"], "concurrency": ["settings.revision-cas", "settings.canonical-mirrors"], "offline": ["settings.revision-cas", "settings.canonical-mirrors", "settings.night-policy-event"]}.get(category, [])
    if family == "awareness":
        return ["awareness.claim.persisted", "awareness.claim.refresh", "awareness.claim.overlaps", "awareness.paths.overlap", "awareness.list.projection", "awareness.release.persisted", *(["awareness.claim.staleness"] if category == "stale" else [])]
    if family == "actions":
        return ["proofs-e-host.action-once", "proofs-e-host.action-sanitization"]
    return []


def _worker(root, family, category):
    root = Path(root).resolve()
    # Direct invocations need the same host isolation as the outer proof CLI.
    # No inherited owner/provider discovery or UI state root may escape this pair.
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / key.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(directory)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WEB_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", NEYVIA_NAS_ROOT=str(root))
    from .proof_credential_guard import install
    install(root)
    attempts = []
    if category == "offline":
        def audit(event, args):
            if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
                attempts.append(event)
                raise PermissionError("Offline semantic fixture refuses actual sockets")
        sys.addaudithook(audit)
    contracts, detail = BUILDERS[family](Path(root), category)
    if category == "offline":
        require(not attempts, "Local fixture unexpectedly attempted network")
        detail.update(socketAuditEnforced=True, networkAttempts=attempts)
    return {"contracts": contracts, "detail": detail}


def run(root, contracts, categories):
    """Generate one fresh real feature workflow per family/category.

    Each owned worker isolates process-global network policy/SQLite caches and
    installs credential protection before importing feature handlers.
    """
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    def execute(pair):
        family, category = pair
        target = root / family / category
        target.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "grant_agent.edge_fixture_local", str(target), family, category]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=90,
                                       env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
                                       **hidden_windows_subprocess_kwargs())
        except subprocess.TimeoutExpired:
            value = {"status": "failed", "contracts": intended_bindings(family, category),
                     "detail": {"error": "Owned feature worker exceeded 90 second deadline", "kind": "worker-timeout; not a diagnosed feature defect"}}
        else:
            try:
                value = json.loads(completed.stdout)
            except ValueError:
                value = {"status": "failed", "contracts": intended_bindings(family, category), "detail": {"error": completed.stderr[-2000:], "exitCode": completed.returncode}}
            if value.get("status") == "failed" and not value.get("contracts"):
                value["contracts"] = intended_bindings(family, category)
            value.setdefault("status", "passed" if completed.returncode == 0 else "failed")
        row = {"id": f"local:{family}:{category}", "category": category,
               "contracts": list(dict.fromkeys(identity for identity in value.get("contracts", []) if identity in contracts)),
               "status": value["status"],
               "detail": value.get("detail", {}), "scratchRoot": str(target),
               "boundary": "actual production feature handlers and durable effect readback in guarded owned process"}
        if not row["contracts"]:
            # An unsupported legacy family/category is migration information,
            # not a semantic case. Keep the worker diagnostic reviewable without
            # inventing a binding or letting an empty row affect coverage.
            diagnostic = {"schema": "neyvia.edge_fixture.unbound_diagnostic.v1",
                          "semanticCase": False, "intendedBindings": intended_bindings(family, category),
                          "workerDiagnostic": row}
            (target / "unbound-diagnostic.json").write_text(json.dumps(diagnostic, ensure_ascii=True, indent=2), encoding="utf-8")
            return None
        (target / "fixture-receipt.json").write_text(json.dumps(row, ensure_ascii=True, indent=2), encoding="utf-8")
        return row
    # Each pair has a disjoint state root and independent process-global policy.
    # Four bounded workers reduce startup cost without sharing feature objects.
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [row for row in pool.map(execute, [(family, category) for family in BUILDERS for category in categories]) if row is not None]


def blocked_reason(identity, category):
    """Family-specific reasons used by the exhaustive pair ledger."""
    if identity.startswith(("notes.", "files.")):
        return "This Notes/Files invariant needs its specific effect under this category; recycle contracts require owned Windows Recycle Bin records, not a parser witness or handler mock"
    if identity.startswith("settings."):
        return "This Settings invariant needs the owner command/UI adapter or an audited target interruption/OS grant fixture; direct canonical updates do not establish that boundary"
    if identity.startswith("awareness."):
        return "This awareness invariant needs its exact parsed impact graph or real board condition under this category; another board workflow is not coverage"
    if identity.startswith("proofs-e-host.action-"):
        return "No effect-bearing action-store workflow establishes this invariant for the requested category; invalid IDs and denied preflight are admission only"
    if identity in {"c7.workspace.rejected-preserves", "native.tools.workspace", "c7.gateway.read-only"}:
        return "Workspace read/search, replacement interruption or the target-specific permission boundary is not established by this generated write fixture"
    return None


if __name__ == "__main__":
    try:
        print(json.dumps(_worker(*sys.argv[1:]), ensure_ascii=True))
    except NotImplementedError as error:
        print(json.dumps({"status": "blocked", "contracts": [], "detail": {"reason": str(error)}}))
    except BaseException as error:
        print(json.dumps({"status": "failed", "contracts": [], "detail": {"type": type(error).__name__, "error": str(error)}}))
        sys.exit(1)
