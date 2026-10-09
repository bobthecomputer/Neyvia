"""Durable Notes/Files action contracts; also used at UI/direct-call boundaries.

Observers read the real files and command bus. Self-checks use disposable production
actions, never a substituted filesystem, command bus or recycle implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
import time
from pathlib import Path

CONTRACTS = (
    "notes.path-jail", "notes.prose-metadata", "notes.body-durable",
    "notes.stale-preserves", "notes.pin-durable", "files.no-overwrite",
    "files.move-conservation", "files.mkdir-durable", "files.undo-once",
    "files.recycle-record", "files.trash-recoverable",
    "notes.write-bounded", "notes.concurrent-writes", "notes.atomic-interruption",
    "notes.permission-preserves", "notes.local-offline",
)
COVERAGE = {
    "test_tags_skip_headings_code_links_and_hex_colours": ["notes.prose-metadata"],
    "test_recycle_info_v2_and_v1": ["files.recycle-record"],
    "test_note_write_refuses_a_stale_overwrite_and_appends": [
        "notes.path-jail", "notes.body-durable", "notes.stale-preserves", "notes.prose-metadata"],
    "test_move_never_overwrites_and_undo_moves_back": [
        "files.no-overwrite", "files.move-conservation", "files.undo-once"],
}


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def _expected_tags(body):
    prose = re.sub(r"```.*?(?:```|\Z)|`[^`\n]*`", " ", body, flags=re.S)
    tags = []
    for token in re.finditer(r"(?<![\w&/#'\"=])#([^\W\d_][\w-]{0,48})", prose):
        tag = token.group(1).rstrip("-").casefold()
        colour = len(tag) in (3, 6) and all(c in "0123456789abcdef" for c in tag) and any(c.isdigit() for c in tag)
        if tag and not colour and tag not in tags:
            tags.append(tag)
    return tags


def check_tags(body, result):
    require(result == _expected_tags(body), "notes.prose-metadata", "tags must be ordered unique prose tags, excluding code, anchors and hexadecimal colours")
    return result


def check_title(body, path, result):
    expected = Path(path).stem
    for line in body.splitlines()[:6]:
        heading = re.fullmatch(r"\s*#{1,2}\s+(.+?)\s*#*\s*", line)
        if heading:
            expected = heading.group(1).strip()[:120]
            break
    require(result == expected, "notes.prose-metadata", "title must use a first-six-line heading or filename stem")
    return result


def check_recycle_record(data, result):
    """Validate each decoded OS record against its binary layout, including v1."""
    version, size, deleted = struct.unpack_from("<qqq", data)
    if version == 1:
        text = data[24:544]
    elif version == 2:
        length = struct.unpack_from("<i", data, 24)[0]
        require(length >= 0 and 28 + length * 2 <= len(data), "files.recycle-record", "v2 length outside record")
        text = data[28:28 + length * 2]
    else:
        raise ValueError("Unknown Recycle Bin record")
    expected = {"path": text.decode("utf-16-le").split("\0", 1)[0], "size": size, "deleted": deleted}
    require(result == expected, "files.recycle-record", "decoded path, size or time differs from OS record")
    return result


def _fingerprint(path):
    path = Path(path)
    if path.is_symlink():
        return {"link": os.readlink(path)}
    if not path.exists():
        return None
    if path.is_dir():
        return {"directory": {p.name: _fingerprint(p) for p in sorted(path.iterdir())}}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _note_path(root, value):
    from .neyvia_notes_tools import notes_folder, NOTE_EXT
    folder = notes_folder(root)
    candidate = Path(str(value or "").strip().replace("\\", "/"))
    path = (candidate if candidate.is_absolute() else folder / candidate).resolve()
    require(folder in path.parents and path.suffix.lower() in NOTE_EXT,
            "notes.path-jail", "Notes live in the notes folder with a supported extension")
    return path


def before(tool, args, root):
    from .ui_command_bus import bus_for
    capture = {"contracts": []}
    if tool.startswith("neyvia.notes."):
        if args.get("path"):
            path = _note_path(root, args["path"])
            capture["path"] = path
            if tool.endswith(".write"):
                capture.update(fingerprint=_fingerprint(path), modified=str(path.stat().st_mtime_ns) if path.exists() else None)
                if path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
                    capture["body"] = path.read_text(encoding="utf-8", errors="replace", newline="")
        return capture
    if not tool.startswith("neyvia.files."):
        return capture
    from .neyvia_files_tools import guard
    op = tool.rsplit(".", 1)[-1]
    if op == "move":
        origin, target = guard(root, args["from"]), guard(root, args["to"])
        if target.is_dir() and os.path.normcase(str(target)) != os.path.normcase(str(origin)):
            target = guard(root, target / origin.name)
        require(not target.exists() or os.path.normcase(str(target)) == os.path.normcase(str(origin)),
                "files.no-overwrite", f"{target.name} already exists there")
        capture.update(origin=origin, target=target, fingerprint=_fingerprint(origin))
    elif op in {"mkdir", "trash"}:
        path = guard(root, args["path"])
        capture.update(path=path, fingerprint=_fingerprint(path))
    elif op == "undo":
        last = bus_for(root).get("files:last")
        require(bool(last), "files.undo-once", "Nothing to undo")
        capture["last"] = last
        if last["op"] == "move":
            origin, target = guard(root, last["to"]), guard(root, last["from"])
            require(not target.exists() or os.path.normcase(str(target)) == os.path.normcase(str(origin)),
                    "files.no-overwrite", "undo would overwrite an occupied original path")
            capture.update(origin=origin, target=target, fingerprint=_fingerprint(origin))
        elif last["op"] == "trash" and os.name == "nt":
            from .neyvia_files_tools import bin_records
            capture["fingerprint"] = next((_fingerprint(record["data"]) for record in bin_records(Path(last["path"])) if record["data"].exists()), None)
    return capture


def after(tool, args, result, root, capture):
    from .ui_command_bus import bus_for
    checked = []
    op = tool.rsplit(".", 1)[-1]
    if tool.startswith("neyvia.notes."):
        if op == "write":
            stale = args.get("expectedModified") and capture.get("modified") and str(args["expectedModified"]) != capture["modified"]
            if stale:
                require(result.get("status") == "conflict" and not result.get("ok") and _fingerprint(capture["path"]) == capture["fingerprint"],
                        "notes.stale-preserves", "stale write must report conflict and preserve all bytes")
                return ["notes.path-jail", "notes.stale-preserves"]
            if result.get("ok"):
                path = _note_path(root, result["path"])
                require(path.stat().st_size <= 2 * 1024 * 1024, "notes.write-bounded", "persisted note exceeds the UTF-8 byte limit")
                body = args["body"]
                if capture.get("modified") and args.get("mode") == "append":
                    old = capture["body"]
                    separator = "" if not old or old.endswith("\n\n") else "\n" if old.endswith("\n") else "\n\n"
                    body = old + separator + body
                elif not args.get("path") and str(args.get("title") or "").strip():
                    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
                    if not re.fullmatch(r"#{1,2}\s+(.+?)\s*#*\s*", first):
                        title = str(args["title"]).strip()
                        body = f"# {title}\n\n{body}" if body.strip() else f"# {title}\n\n"
                require(path.read_bytes() == body.encode("utf-8"), "notes.body-durable", "persisted UTF-8 bytes differ from requested creation/replace/append")
                require(result["modified"] == str(path.stat().st_mtime_ns), "notes.body-durable", "modified observer differs from filesystem")
                checked += ["notes.path-jail", "notes.body-durable", "notes.write-bounded"]
        elif op == "pin" and result.get("ok"):
            from .neyvia_notes_tools import notes_folder, META
            meta = json.loads((notes_folder(root) / META).read_text(encoding="utf-8"))
            wanted = args.get("pinned", True) is not False
            require(result["pinned"] == wanted and (result["path"] in meta.get("pinned", [])) == wanted,
                    "notes.pin-durable", "pin result and persisted metadata disagree")
            checked.append("notes.pin-durable")
        return checked
    if not tool.startswith("neyvia.files.") or not result.get("ok"):
        return checked
    if op == "move":
        require((not capture["origin"].exists() or os.path.normcase(str(capture["origin"])) == os.path.normcase(str(capture["target"]))) and _fingerprint(capture["target"]) == capture["fingerprint"],
                "files.move-conservation", "move must preserve bytes/tree and vacate source")
        last = bus_for(root).get("files:last")
        require(last["op"] == "move" and Path(last["to"]) == capture["target"], "files.undo-once", "move receipt must describe durable target")
        checked += ["files.no-overwrite", "files.move-conservation", "files.undo-once"]
    elif op == "mkdir":
        require(capture["fingerprint"] is None and capture["path"].is_dir(), "files.mkdir-durable", "mkdir must create an absent directory")
        last = bus_for(root).get("files:last")
        require(last and last["op"] == "mkdir" and Path(last["path"]) == capture["path"], "files.undo-once", "mkdir must retain its exact undo receipt")
        checked.append("files.mkdir-durable")
    elif op == "trash":
        from .neyvia_files_tools import bin_records
        require(not capture["path"].exists() and result.get("recycled"), "files.trash-recoverable", "trash must vacate source and report recycle")
        if os.name == "nt":
            require(any(_fingerprint(record["data"]) == capture["fingerprint"] for record in bin_records(capture["path"]) if record["data"].exists()),
                    "files.trash-recoverable", "OS recycle record must preserve original bytes/tree")
        last = bus_for(root).get("files:last")
        require(last and last["op"] == "trash" and Path(last["path"]) == capture["path"], "files.undo-once", "trash must retain its exact undo receipt")
        checked.append("files.trash-recoverable")
    elif op == "undo":
        last = capture["last"]
        require(result["undone"] == last["op"] and bus_for(root).get("files:last") is None,
                "files.undo-once", "undo must identify original action and consume its receipt")
        if last["op"] == "move":
            require(_fingerprint(capture["target"]) == capture["fingerprint"] and (not capture["origin"].exists() or os.path.normcase(str(capture["origin"])) == os.path.normcase(str(capture["target"]))),
                    "files.move-conservation", "undo must return unchanged bytes/tree and vacate moved location")
        elif last["op"] == "mkdir":
            require(not Path(last["path"]).exists(), "files.undo-once", "undo mkdir must remove the empty folder")
        elif last["op"] == "trash":
            require(Path(last["path"]).exists(), "files.trash-recoverable", "undo trash must restore its original path")
            if os.name == "nt":
                require(capture.get("fingerprint") is not None and _fingerprint(Path(last["path"])) == capture["fingerprint"],
                        "files.trash-recoverable", "undo trash must restore exact recycled bytes/tree")
        checked.append("files.undo-once")
    return checked


def self_check(root):
    """Run Notes observers and capture/tidy/undo procedures against scratch state."""
    from .neyvia_notes_tools import call_notes, tags_of, title_of
    from .neyvia_files_tools import call_files, parse_recycle_info
    from .ui_command_bus import bus_for
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="notes-files-", dir=base))
    folder = root / "notes"
    folder.mkdir(exist_ok=True)
    bus_for(root).put("notes:folder", str(folder))
    cases = []

    def run(identity, contracts, procedure):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            procedure()
            cases.append({"id": identity, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "error": str(error)})

    def note(op, args):
        return call_notes(root, op, args, "ui")

    def files(op, args):
        return call_files(root, op, args, "ui")

    def reject(action, text):
        try:
            action()
        except ValueError as error:
            require(text.casefold() in str(error).casefold(), "notes-files.rejection", str(error))
            return
        raise ValueError("Invalid action was accepted")

    def metadata():
        body = "# Heading\n#idée and #Work-Log, `#code` ```\n#fenced\n``` page#anchor #a1b2c3 #add"
        created = note("write", {"title": "Metadata", "body": body})
        observed = note("read", {"path": created["path"]})
        require(observed["tags"] == ["idée", "work-log", "add"] and observed["title"] == "Heading", "notes.prose-metadata", "prose observer conformance")
        require(title_of("no heading", folder / "Plain.md") == "Plain" and tags_of(body) == observed["tags"], "notes.prose-metadata", "standalone parser conformance")

    def records():
        original = str(folder / "Recycled.md")
        for version, size, deleted in [(1, 7, 1), (2, 42, 133000000000000000)]:
            header = struct.pack("<qqq", version, size, deleted)
            text = (original + "\0").encode("utf-16-le")
            data = header + (text.ljust(520, b"\0") if version == 1 else struct.pack("<i", len(original) + 1) + text)
            require(parse_recycle_info(data) == {"path": original, "size": size, "deleted": deleted}, "files.recycle-record", "v1/v2 binary format observer conformance")

    def writes():
        created = note("write", {"title": "Plan", "body": "first"})
        require(created["path"] == "Plan.md" and created["title"] == "Plan", "notes.body-durable", "creation title/path")
        changed = note("write", {"path": created["path"], "body": "second", "mode": "append", "expectedModified": created["modified"]})
        require(changed["ok"] and note("read", {"path": created["path"]})["body"].endswith("first\n\nsecond"), "notes.body-durable", "append separator and body")
        stale = note("write", {"path": created["path"], "body": "lost", "expectedModified": created["modified"]})
        require(stale["status"] == "conflict" and "lost" not in note("read", {"path": created["path"]})["body"], "notes.stale-preserves", "stale body not persisted")
        reject(lambda: note("read", {"path": "../outside.md"}), "notes folder")
        note("pin", {"path": created["path"], "pinned": True})
        listed = note("list", {})
        require(listed["notes"][0]["path"] == created["path"] and listed["notes"][0]["pinned"], "notes.pin-durable", "pinned note sorts first")
        note("search", {"query": "first second"})
        note("folder", {})
        note("open", {"path": created["path"]})

    def moves():
        a = note("write", {"title": "A", "body": "a"})
        b = note("write", {"title": "B", "body": "b"})
        origin, occupied = folder / a["path"], folder / b["path"]
        previous = (_fingerprint(origin), _fingerprint(occupied))
        reject(lambda: files("move", {"from": str(origin), "to": str(occupied)}), "already exists")
        require(previous == (_fingerprint(origin), _fingerprint(occupied)), "files.no-overwrite", "rejected collision preserves both files")
        target = folder / "Old"
        files("mkdir", {"path": str(target)})
        files("move", {"from": str(origin), "to": str(target)})
        require((target / origin.name).is_file(), "files.move-conservation", "destination folder resolved to filename")
        require(files("undo", {})["undone"] == "move" and origin.is_file() and not (target / origin.name).exists(), "files.undo-once", "move restored")
        reject(lambda: files("undo", {}), "Nothing to undo")
        files("list", {"path": str(folder)})
        files("stat", {"path": str(origin), "preview": True})

    def trash_restore():
        created = note("write", {"title": "Recycle proof", "body": "recover these exact bytes #proof"})
        path = folder / created["path"]
        original = _fingerprint(path)
        files("trash", {"path": str(path)})
        require(not path.exists(), "files.trash-recoverable", "trashed scratch note remains at source")
        files("undo", {})
        require(_fingerprint(path) == original, "files.trash-recoverable", "restored scratch note differs")

    manual_receipts = []

    def grounded_procedures():
        from .native_tools import NativeToolRegistry
        from .neyvia_workspace_tools import workspace_for
        from . import neyvia_manuals
        service, registry = workspace_for(root), NativeToolRegistry(root)

        def dispatch(tool, args, action_id=""):
            if tool.startswith("neyvia.notes."):
                return note(tool.rsplit(".", 1)[-1], args)
            if tool.startswith("neyvia.files."):
                return files(tool.rsplit(".", 1)[-1], args)
            raise ValueError("Notes/Files startup procedure contains an out-of-area action")

        def manual(identity, operation, args):
            return neyvia_manuals.call(service, operation, {"id": identity, **args}, dispatcher=dispatch, registry=registry)

        for identity in ("notes", "files"):
            _, _, data = neyvia_manuals.get_manual(identity, root / ".neyvia")
            for chapter, content in data["chapters"].items():
                for state, observer in content["state"].items():
                    # Both current Notes/Files observers have no required inputs.
                    require(not observer["inputs"].get("required"), "notes-files.startup-observer", "observer needs a startup input fixture")
                    observed = manual(identity, "manual.observe", {"chapter": chapter, "state": state, "inputs": {}})
                    require(observed.get("ok"), "notes-files.startup-observer", f"{identity}.{state} failed")
                    manual_receipts.append({"id": identity, "chapter": chapter, "observer": state, "ok": True})

        def procedure(identity, name, inputs, decision, option):
            first = manual(identity, "manual.run", {"chapter": "overview", "procedure": name, "inputs": inputs})
            require(first.get("status") == "judge" and first["judge"]["id"] == decision,
                    "notes-files.startup-procedure", f"{identity}.{name} did not expose its judgement point")
            finished = manual(identity, "manual.run", {"chapter": "overview", "procedure": name, "runId": first["runId"], "decisions": {decision: option}})
            require(finished.get("ok") and finished["status"] == "completed" and all(check["passed"] for check in finished["checks"]),
                    "notes-files.startup-procedure", f"{identity}.{name} failed: {finished.get('error')}")
            manual_receipts.append({"id": identity, "chapter": "overview", "procedure": name, "runId": finished["runId"], "checks": len(finished["checks"]), "ok": True})

        created = note("write", {"title": "Manual procedures", "body": "seed"})
        procedure("notes", "capture-tagged-idea", {"path": created["path"], "idea": "captured idea #manual", "tag": "manual"}, "capture", "append")
        current = note("read", {"path": created["path"]})
        procedure("notes", "write-and-pin", {"path": created["path"], "body": "replacement #manual", "expectedModified": current["modified"]}, "replace-note", "replace")
        source = folder / created["path"]
        destination = folder / "Manual renamed.md"
        procedure("files", "rename-and-check", {"from": str(source), "to": str(destination), "name": destination.name}, "tidy", "move")
        procedure("files", "undo-last-tidy", {"from": str(source), "to": str(destination), "originalName": source.name}, "retain", "undo")
        target = folder / "Manual destination"
        files("mkdir", {"path": str(target)})
        procedure("files", "tidy-with-undo", {"from": str(source), "to": str(target / source.name), "name": source.name}, "tidy", "move")
        files("undo", {})

    run("test_tags_skip_headings_code_links_and_hex_colours", COVERAGE["test_tags_skip_headings_code_links_and_hex_colours"], metadata)
    run("test_recycle_info_v2_and_v1", COVERAGE["test_recycle_info_v2_and_v1"], records)
    run("test_note_write_refuses_a_stale_overwrite_and_appends", COVERAGE["test_note_write_refuses_a_stale_overwrite_and_appends"] + ["notes.pin-durable"], writes)
    run("test_move_never_overwrites_and_undo_moves_back", COVERAGE["test_move_never_overwrites_and_undo_moves_back"] + ["files.mkdir-durable"], moves)
    run("procedure_recycle_and_restore", ["files.trash-recoverable", "files.recycle-record", "files.undo-once"], trash_restore)
    # The new adversarial contracts are exercised by edge_notes.run, rather than
    # relabelling ordinary grounded procedures as interruption/concurrency proof.
    run("grounded_manual_observers_and_procedures", list(CONTRACTS[:11]), grounded_procedures)
    return {"ok": all(case["ok"] for case in cases), "contracts": list(CONTRACTS), "cases": cases,
            "failures": [case for case in cases if not case["ok"]], "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "observers": ["notes.list", "notes.read", "notes.search", "notes.folder", "files.list", "files.stat", "files.recycle-record"],
            "procedures": ["notes.capture-tagged-idea", "notes.write-and-pin", "files.rename-and-check", "files.undo-last-tidy", "files.tidy-with-undo"],
            "manualReceipts": manual_receipts, "scratchRoot": str(root)}
