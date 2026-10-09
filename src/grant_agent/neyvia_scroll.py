"""One workspace store for the Scroll Study generator, UI and model tools."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

from .durability import atomic_write_json

TEXT = {"type": "string", "minLength": 1}
PACK = {"pack": TEXT}
OPS = ("import", "concepts", "generate", "job", "validate", "review", "pack", "preview", "send", "stats", "state")
COMMANDS = frozenset("scroll_" + op + "_command" for op in OPS)
DEFINITIONS = [
    ("scroll.import", "Hash Markdown/text study notes and create a workspace pack draft using zero-token ingest/split/candidate scripts.", {"paths": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 20}, "packId": TEXT, "title": TEXT, "subject": TEXT}, ["paths"]),
    ("scroll.concepts", "Confirm concepts through the validated Luna cascade; graph-sanity is the only large graph judgement.", PACK, ["pack"]),
    ("scroll.generate", "Start a durable cards/answer-check job. Reuse requestId for transport retries; models cannot run arbitrary tools.", {**PACK, "scope": {"type": "object", "properties": {"chapters": {"type": "array", "items": TEXT}, "concepts": {"type": "array", "items": TEXT}}, "additionalProperties": False}, "requestId": TEXT}, ["pack", "requestId"]),
    ("scroll.job", "Observe a persisted job and its last stage, progress and actionable failure.", {"requestId": TEXT}, ["requestId"]),
    ("scroll.validate", "Run schema/DAG/source/maths/card-mix checks without model calls.", PACK, ["pack"]),
    ("scroll.review", "Approve, drop or edit real draft cards. Flagged answers need an explicit individual decision.", {**PACK, "decisions": {"type": "array", "items": {"type": "object", "properties": {"cardId": TEXT, "action": {"enum": ["approve", "drop", "edit"]}, "card": {"type": "object"}}, "required": ["cardId", "action"], "additionalProperties": False}}, "chapter": TEXT, "action": {"const": "approve"}}, ["pack"]),
    ("scroll.pack", "Validate and zip an entirely reviewed pack and its hashed source texts; pending/flagged cards block export.", PACK, ["pack"]),
    ("scroll.preview", "Copy the approved generated pack into the real phone prototype and open Mobile Studio on the same state.", {**PACK, "device": TEXT}, ["pack"]),
    ("scroll.send", "Create a single-download 15-minute capability for this approved archive; requires explicit backend URL.", PACK, ["pack"]),
    ("scroll.stats", "Read actual generation usage, price-qualified card/hour costs and review approval rate.", PACK, ["pack"]),
    ("scroll.state", "Read the exact pack/graph/review/job state shown to the user.", PACK, []),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError("Use a pack/request ID of 1–100 letters, digits, dots, underscores or dashes")
    return value


@contextmanager
def store(root):
    directory = Path(root).resolve() / ".neyvia" / "scroll"
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "state.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS packs(id TEXT PRIMARY KEY, value TEXT NOT NULL, sources TEXT NOT NULL, review TEXT NOT NULL, updated TEXT NOT NULL, revision INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, pack TEXT, payload TEXT, state TEXT, stage TEXT, done INTEGER, total INTEGER, pid INTEGER, created TEXT, error TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS links(token TEXT PRIMARY KEY, path TEXT, sha256 TEXT, expires REAL, consumed INTEGER)")
    try:
        with db:
            yield db, directory
    finally:
        db.close()


def load(root, pack):
    with store(root) as (db, _):
        row = db.execute("SELECT * FROM packs WHERE id=?", (identity(pack),)).fetchone()
    if not row:
        raise ValueError("Unknown study pack; import your notes first")
    result = dict(row)
    for key in ("value", "sources", "review"):
        result[key] = json.loads(result[key])
    return result


def save(root, row):
    with store(root) as (db, _):
        changed = db.execute("UPDATE packs SET value=?,sources=?,review=?,updated=?,revision=revision+1 WHERE id=? AND revision=?", (canonical(row["value"]), canonical(row["sources"]), canonical(row["review"]), now(), row["id"], row["revision"])).rowcount
        if changed != 1:
            raise ValueError("Pack changed during this operation; observe fresh state before retrying")


def idle(root, pack):
    with store(root) as (db, _):
        if db.execute("SELECT 1 FROM jobs WHERE pack=? AND state IN ('queued','running')", (pack,)).fetchone():
            raise ValueError("This pack is generating; wait for its job before editing")


def logger(root, pack, run):
    def log(row):
        value = {"run": run, "pack": pack, "cardIds": [], "model": None, "inTokens": 0, "outTokens": 0, "cachedTokens": 0, "ms": 0, "ok": True, **row}
        with store(root) as (db, directory):
            db.execute("BEGIN IMMEDIATE")
            folder = directory / identity(pack)
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "generation.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(canonical(value) + "\n")
    return log


def stats(root, row):
    from .scroll_cost import derive_stats
    with store(root) as (_, directory):
        file = directory / row["id"] / "generation.jsonl"
        rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()] if file.exists() else []
    prices_file = Path(__file__).resolve().parents[2] / "config" / "scroll-study-prices.json"
    prices = json.loads(prices_file.read_text(encoding="utf-8")) if prices_file.exists() else None
    cards = [card for card in row["value"].get("cards", []) if row["review"].get(card["id"], {}).get("status") != "dropped"]
    return derive_stats(rows, cards, review=row["review"], prices=prices)


def validate(root, row):
    from .scroll_pack import validate_pack
    value = {**row["value"], "cards": [c for c in row["value"].get("cards", []) if row["review"].get(c["id"], {}).get("status") != "dropped"]}
    return validate_pack(value, row["sources"]["source_texts"], media_root=Path(root) / ".neyvia" / "scroll" / row["id"])


def job(root, request_id):
    with store(root) as (db, _):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (identity(request_id),)).fetchone()
    if not row:
        raise ValueError("Unknown generation job")
    item = dict(row)
    item["payload"] = json.loads(item["payload"])
    item["progress"] = {"done": item.pop("done"), "total": item.pop("total")}
    return {"ok": True, "job": item}


def generate(root, args):
    request_id = identity(args["requestId"])
    row = load(root, args["pack"])
    payload = canonical({"pack": row["id"], "scope": args.get("scope") or {}})
    with store(root) as (db, directory):
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT payload FROM jobs WHERE id=?", (request_id,)).fetchone()
        if prior:
            if prior["payload"] != payload:
                raise ValueError("requestId is already bound to different generation arguments")
            return {**job(root, request_id), "replayed": True}
        if not row["value"].get("concepts"):
            raise ValueError("Confirm concepts first with scroll.concepts")
        if db.execute("SELECT 1 FROM jobs WHERE pack=? AND state IN ('queued','running')", (row["id"],)).fetchone():
            raise ValueError("This pack already has an active generation job")
        from .neyvia_settings import _state
        from .ui_command_bus import bus_for
        with bus_for(Path(root)).connect() as settings_db:
            _, settings = _state(settings_db)
        if settings["localOnly"]:
            raise ValueError("Generation requires the configured Luna CLI; local-only is enabled")
        db.execute("INSERT INTO jobs VALUES(?,?,?,'queued','cards',0,?,NULL,?,NULL)", (request_id, row["id"], payload, len(row["value"]["concepts"]), now()))
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0"}
    try:
        with (directory / (request_id + ".log")).open("ab") as stream:
            process = subprocess.Popen([sys.executable, "-m", "grant_agent.neyvia_scroll", "--worker", str(Path(root).resolve()), request_id], stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with store(root) as (db, _):
            db.execute("UPDATE jobs SET pid=? WHERE id=?", (process.pid, request_id))
    except OSError:
        with store(root) as (db, _):
            db.execute("UPDATE jobs SET state='failed',error='Worker could not start; inspect the task-local job log' WHERE id=?", (request_id,))
        raise ValueError("Generation worker could not start; retry with a new request after fixing the local runtime")
    return job(root, request_id)


def worker(root, request_id):
    from .local_network_policy import install
    install(Path(root))
    from .scroll_generation import generate_cards
    current = job(root, request_id)["job"]
    with store(root) as (db, _):
        if db.execute("UPDATE jobs SET state='running' WHERE id=? AND state='queued'", (request_id,)).rowcount != 1:
            raise ValueError("Job has already been claimed; duplicate execution refused")
    def progress(*args, **kwargs):
        value = args[0] if args and isinstance(args[0], dict) else {"stage": args[0] if args else kwargs.get("stage", "cards"), "done": args[1] if len(args) > 1 else kwargs.get("done", 0), "total": args[2] if len(args) > 2 else kwargs.get("total", current["progress"]["total"])}
        with store(root) as (db, _):
            db.execute("UPDATE jobs SET stage=?,done=?,total=? WHERE id=?", (str(value.get("stage", "cards")), int(value.get("done", 0)), int(value.get("total", current["progress"]["total"])), request_id))
    try:
        row = load(root, current["pack"])
        row["value"] = generate_cards(Path(root), row["value"], row["sources"], current["payload"]["scope"], request_id, logger(root, row["id"], request_id), progress=progress)
        for card in row["value"]["cards"]:
            row["review"][card["id"]] = {"status": "flagged" if card.get("flag") else "pending", **({"flag": card["flag"]} if card.get("flag") else {})}
        row["value"]["status"] = "review"
        save(root, row)
        began = time.monotonic()
        compiled_path = Path(root) / ".neyvia" / "scroll" / "validation-script.json"
        compiled = json.loads(compiled_path.read_text(encoding="utf-8")) if compiled_path.is_file() else None
        if compiled and compiled.get("pack") == row["id"]:
            from .native_tools import NativeToolRegistry
            replay = NativeToolRegistry(Path(root)).call("neyvia.manual.script.run", {"scriptId": compiled["scriptId"], "inputs": {"pack": row["id"]}})
            result = replay.get("result", {})
            if not replay.get("ok") or result.get("status") != "completed":
                raise ValueError("Compiled validation refused the current pack; inspect its grounded verifier receipt")
            check = result["results"]["validation"]
            logger(root, row["id"], request_id)({"stage": "validate", "tier": "script", "compiledScriptId": compiled["scriptId"], "receiptPath": replay.get("receipt_path"), "ms": (time.monotonic() - began) * 1000, "ok": check["ok"]})
        else:
            check = validate(root, load(root, row["id"]))
            logger(root, row["id"], request_id)({"stage": "validate", "tier": "script", "ms": (time.monotonic() - began) * 1000, "ok": check["ok"]})
        with store(root) as (db, directory):
            atomic_write_json(directory / row["id"] / "last-validation.json", check)
            db.execute("UPDATE jobs SET state='completed',stage='review',done=total WHERE id=?", (request_id,))
    except Exception as error:
        with store(root) as (db, directory):
            atomic_write_json(directory / (request_id + ".failure.json"), {"type": type(error).__name__, "message": str(error)})
            db.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", ("Generation failed: " + str(error)[:600] + ". Inspect the retained receipt; correct the source or retry with a new requestId.", request_id))


def state(root, selected=None):
    with store(root) as (db, directory):
        ids = [r[0] for r in db.execute("SELECT id FROM packs ORDER BY updated DESC")]
        jobs = [dict(r) for r in db.execute("SELECT id,pack,state,stage,done,total,error FROM jobs ORDER BY created DESC LIMIT 100")]
    packs = []
    active = None
    for name in ids:
        row = load(root, name)
        pack, review = row["value"], row["review"]
        types = {}
        for card in pack.get("cards", []):
            types[card["type"]] = types.get(card["type"], 0) + 1
        cost = stats(root, row)
        packs.append({"id": name, "title": pack["meta"]["title"], "subjects": pack["meta"]["subjects"], "status": "generating" if any(j["pack"] == name and j["state"] in {"queued", "running"} for j in jobs) else pack.get("status", "draft"), "updated": row["updated"], "counts": {"concepts": len(pack.get("concepts", [])), "cards": len(pack.get("cards", [])), "byType": types, **{status: sum(r.get("status") == status for r in review.values()) for status in ("approved", "dropped", "flagged")}}, "cost": cost, "sources": [{k: src[k] for k in ("id", "title", "kind")} for src in pack.get("sources", [])]})
        if selected == name:
            chapters = {}
            for card in pack.get("cards", []):
                chapters.setdefault(card["chapter"], []).append({"id": card["id"], "type": card["type"], "title": card.get("body", ""), **review.get(card["id"], {"status": "pending"}), "card": card})
            last = directory / name / "last-validation.json"
            active = {"id": name, "graph": {"concepts": pack.get("concepts", []), "edges": [[p, c["id"]] for c in pack.get("concepts", []) for p in c.get("prereqs", [])]}, "review": {"chapters": [{"id": ch, "name": ch, "cards": cards} for ch, cards in chapters.items()]}, "lastValidation": json.loads(last.read_text(encoding="utf-8")) if last.exists() else None}
    if selected and active is None:
        raise ValueError("Unknown study pack")
    for item in jobs:
        item["progress"] = {"done": item.pop("done"), "total": item.pop("total")}
    return {"ok": True, "packs": packs, **({"active": active} if active else {}), "jobs": jobs}


def export(root, row):
    from .scroll_pack import write_scrollpack
    cards = row["value"].get("cards", [])
    if not cards or any(row["review"].get(c["id"], {}).get("status") not in {"approved", "dropped"} for c in cards):
        raise ValueError("Review every card before exporting; pending and flagged answers cannot ship")
    check = validate(root, row)
    if not check["ok"]:
        raise ValueError("Pack validation failed: " + canonical(check["errors"][:5]))
    value = {**row["value"], "cards": [c for c in cards if row["review"][c["id"]]["status"] == "approved"]}
    value.pop("status", None)
    for card in value["cards"]:
        card.pop("flag", None)
    value["generation"]["costs"] = stats(root, row)
    with store(root) as (_, directory):
        folder = directory / row["id"]
        folder.mkdir(exist_ok=True)
        archive = folder / (row["id"] + ".scrollpack")
        temporary = archive.with_suffix(".tmp")
        write_scrollpack(temporary, value, row["sources"]["source_texts"], media_root=folder)
        temporary.replace(archive)
        atomic_write_json(folder / "pack.json", value)
    row["value"]["status"] = "ready"
    save(root, row)
    return {"ok": True, "path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size, "cards": len(value["cards"])}


def call(service, name, args):
    root = service.bus.root
    operation = name.removeprefix("scroll.")
    if operation not in OPS:
        raise ValueError("Unknown scroll operation")
    from jsonschema import Draft202012Validator
    definition = next(d for d in DEFINITIONS if d[0] == "scroll." + operation)
    error = next(Draft202012Validator({"type": "object", "properties": definition[2], "required": definition[3], "additionalProperties": False}).iter_errors(args), None)
    if error:
        raise ValueError("Invalid study argument " + ".".join(map(str, error.absolute_path)) + ": " + error.message)
    if operation == "state":
        return state(root, args.get("pack"))
    if operation == "job":
        return job(root, args["requestId"])
    if operation == "import":
        from .scroll_generation import import_sources
        paths = [service.safe_path(p) for p in args["paths"]]
        for path in paths:
            if path.suffix.lower() not in {".md", ".markdown", ".txt"} or any(re.search(r"credential|password|secret|nas_access_runbook", part, re.I) for part in path.parts):
                raise ValueError("Import supports study Markdown/text only; extract PDF/OCR text through its existing app first")
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("Each study source must be an existing file of at most 1 MiB")
        pack_id = identity(args.get("packId") or "study-" + secrets.token_hex(6))
        idle(root, pack_id)
        result = import_sources(paths, args.get("title") or paths[0].stem, args.get("subject") or "study", pack_id)
        value, sources = result["pack"], result["sources"]
        value["status"] = "draft"
        with store(root) as (db, directory):
            old = db.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone()
            if old:
                old_value, old_sources = json.loads(old["value"]), json.loads(old["sources"])
                known = set(old_sources["source_texts"])
                fresh = set(sources["source_texts"]) - known
                if not fresh:
                    return {"ok": True, "pack": old_value, "replayed": True}
                backup = directory / pack_id / "history"
                backup.mkdir(parents=True, exist_ok=True)
                atomic_write_json(backup / (str(old["revision"]) + ".json"), {"pack": old_value, "sources": old_sources, "review": json.loads(old["review"])})
                old_sources["source_texts"].update(sources["source_texts"])
                old_sources["records"].extend(r for r in sources["records"] if r["id"] in fresh)
                old_sources["sections"].extend(s for s in sources["sections"] if s["doc"] in fresh)
                old_value["sources"] = old_sources["records"]
                old_value["status"] = "draft"
                db.execute("UPDATE packs SET value=?,sources=?,updated=?,revision=revision+1 WHERE id=?", (canonical(old_value), canonical(old_sources), now(), pack_id))
                value = old_value
            else:
                db.execute("INSERT INTO packs VALUES(?,?,?,?,?,1)", (pack_id, canonical(value), canonical(sources), "{}", now()))
        logger(root, pack_id, "import-" + pack_id)({"stage": "ingest-split-candidates", "tier": "script"})
        return {"ok": True, "pack": value}
    if operation == "generate":
        return generate(root, args)
    row = load(root, args["pack"])
    if operation == "stats":
        return {"ok": True, "pack": row["id"], **stats(root, row)}
    if operation == "validate":
        check = validate(root, row)
        with store(root) as (_, directory):
            folder = directory / row["id"]
            folder.mkdir(exist_ok=True)
            atomic_write_json(folder / "last-validation.json", check)
        return check
    idle(root, row["id"])
    if operation == "concepts":
        from .neyvia_settings import _state
        with service.bus.connect() as db:
            _, settings = _state(db)
        if settings["localOnly"]:
            raise ValueError("Concept wording needs the configured Luna CLI; local-only is enabled")
        from .scroll_generation import build_concepts
        row["value"] = build_concepts(root, row["value"], row["sources"], logger(root, row["id"], "concepts-" + row["id"]))
        save(root, row)
        return {"ok": True, "graph": {"concepts": row["value"]["concepts"], "edges": [[p, c["id"]] for c in row["value"]["concepts"] for p in c.get("prereqs", [])]}}
    if operation == "review":
        if bool(args.get("decisions")) == bool(args.get("action")):
            raise ValueError("Choose individual decisions or chapter approve-all")
        decisions = args.get("decisions") or [{"cardId": c["id"], "action": "approve"} for c in row["value"]["cards"] if c["chapter"] == args.get("chapter") and row["review"].get(c["id"], {}).get("status") not in {"flagged", "dropped"}]
        if not decisions:
            raise ValueError("No cards matched this review")
        cards = {c["id"]: c for c in row["value"]["cards"]}
        for decision in decisions:
            key, action = decision["cardId"], decision["action"]
            if key not in cards:
                raise ValueError("Unknown card in review: " + key)
            previous = row["review"].get(key, {})
            if action == "edit":
                replacement = decision.get("card")
                if not replacement or replacement.get("id") != key:
                    raise ValueError("Editing must preserve the stable card ID")
                row["value"]["cards"] = [replacement if c["id"] == key else c for c in row["value"]["cards"]]
                row["review"][key] = {"status": "approved", "edited": True, "reviewedAt": now()}
            else:
                row["review"][key] = {"status": "approved" if action == "approve" else "dropped", "edited": previous.get("edited", False), "reviewedAt": now(), **({"resolvedFlag": previous["flag"]} if previous.get("flag") else {})}
        if any(d["action"] == "edit" for d in decisions):
            check = validate(root, row)
            errors = [error for error in check["errors"] if error.get("cardId") is None or error.get("cardId") in {d["cardId"] for d in decisions}]
            if errors:
                raise ValueError("Edited card failed validation: " + canonical(errors))
        save(root, row)
        return state(root, row["id"])
    if operation == "pack":
        return export(root, row)
    if operation == "preview":
        receipt = export(root, row)
        with store(root) as (_, directory):
            project = directory / row["id"] / "phone"
            template = Path(__file__).resolve().parents[2] / "apps" / "scroll-study"
            shutil.copytree(template / "www", project / "www", dirs_exist_ok=True)
            shutil.copy2(template / "package.json", project / "package.json")
            for name in ("neyvia.app.json", "manual.cl", "host-contract.json"):
                if (template / name).is_file():
                    shutil.copy2(template / name, project / name)
            shutil.copy2(directory / row["id"] / "pack.json", project / "www" / "generated-pack.json")
            source_path = project / "www" / "generated-sources.json"
            atomic_write_json(source_path, row["sources"]["source_texts"])
        from .neyvia_mobile_studio import preview
        result = preview(service, {"project": str(project), **({"device": args["device"]} if args.get("device") else {})})
        result.update(pack=row["id"], archive=receipt, project=str(project))
        return result
    if operation == "send":
        from urllib.parse import urlsplit
        base = os.environ.get("NEYVIA_UI_BACKEND_URL", "")
        url = urlsplit(base)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or not url.port:
            raise ValueError("Set an explicit reachable backend URL and port before Send to phone")
        receipt = export(root, row)
        token = secrets.token_urlsafe(24)
        expires = time.time() + 900
        with store(root) as (db, _):
            db.execute("INSERT INTO links VALUES(?,?,?,?,0)", (token, receipt["path"], receipt["sha256"], expires))
        link = base.rstrip("/") + "/api/ui/scroll/download/" + token
        result = {"ok": True, "url": link, "expires": expires, "downloads": 1, "lanReachable": url.hostname not in {"127.0.0.1", "localhost", "::1"}}
        try:
            try:
                import qrcode
            except ImportError:
                # The checked-in pure Python SVG dependency needs no installation.
                vendor = str(Path(__file__).resolve().parents[2] / "scripts" / "scroll_vendor" / "python")
                sys.path.insert(0, vendor)
                try:
                    import qrcode
                finally:
                    sys.path.remove(vendor)
            import qrcode.image.svg
            import io
            image = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage)
            out = io.BytesIO(); image.save(out)
            result["qrSvg"] = out.getvalue().decode()
        except ImportError:
            result["qrUnavailable"] = "QR dependency is unavailable; open the one-time link directly"
        return result
    raise ValueError("Unsupported scroll operation")


def handle_command(root, command, payload):
    if command not in COMMANDS:
        raise ValueError("Unknown scroll command")
    expected = payload.get("_expectedStateRoot")
    if expected and Path(expected).resolve() != Path(root).resolve():
        raise ValueError("Scroll Study belongs to another workspace")
    from .neyvia_workspace_tools import workspace_for
    return call(workspace_for(Path(root)), "scroll." + command.removeprefix("scroll_").removesuffix("_command"), {k: v for k, v in payload.items() if k != "_expectedStateRoot"})


def download(root, handler, parsed):
    from .web_backend import _json_response
    token = parsed.path.rsplit("/", 1)[-1]
    with store(root) as (db, _):
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM links WHERE token=? AND consumed=0 AND expires>?", (token, time.time())).fetchone()
        if not row:
            _json_response(handler, 410, {"ok": False, "error": "Link expired or already downloaded; make a new phone link"})
            return
        path = Path(row["path"])
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != row["sha256"]:
            _json_response(handler, 409, {"ok": False, "error": "Pack changed; make a fresh link"})
            return
        db.execute("UPDATE links SET consumed=1 WHERE token=?", (token,))
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", 'attachment; filename="' + path.name + '"')
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Use --worker ROOT REQUEST_ID")
    worker(Path(sys.argv[2]), sys.argv[3])
