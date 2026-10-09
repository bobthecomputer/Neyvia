"""Project-scoped live editor bridges and durable, affinity-bound receipts.

Editors own their native scene operations; this service never simulates success.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import os
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .subprocess_utils import hidden_windows_subprocess_kwargs

ENGINES = ("unity", "roblox", "blender", "godot", "babylon")
TEXT = {"type": "string"}
DEFINITIONS = [
    ("gamedev.status", "Detect editors and read live bridge status; installation is not connection.", {}, []),
    ("gamedev.sessions", "List exact editor sessions, project, context and capabilities; optional selectors bind one native session for CL actions.", {"engine": {"type": "string", "enum": list(ENGINES)}, "projectPath": TEXT, "context": {"type": "string", "enum": ["Edit", "Play", "Client", "Server"]}}, []),
    ("gamedev.setup", "Copy a bridge into an installed editor's selected workspace project without overwriting files.", {"engine": {"type": "string", "enum": list(ENGINES)}, "projectPath": TEXT}, ["engine", "projectPath"]),
    ("gamedev.project_status", "Observe project bridge configuration and installed package hashes without exposing its capability token.", {"engine": {"type": "string", "enum": list(ENGINES)}, "projectPath": TEXT}, ["engine", "projectPath"]),
    ("gamedev.action", "Queue one native editor action on an exact session. Poll receipt; reuse requestId only for identical intent.", {"sessionId": TEXT, "action": TEXT, "args": {"type": "object"}, "requestId": TEXT}, ["sessionId", "action"]),
    ("gamedev.receipt", "Read a durable native operation receipt, including errors and elapsed time.", {"requestId": TEXT}, ["requestId"]),
    ("gamedev.receipts", "List shared UI and bot action receipts, newest first, optionally for one exact session.", {"sessionId": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, []),
    ("gamedev.state", "Read the screen's reported selection separately from verified native bridge state.", {}, []),
    ("gamedev.asset_validate", "Validate a project-local glTF/GLB with Khronos glTF Validator; never load invalid assets.", {"path": TEXT}, ["path"]),
]
COMMANDS = frozenset("gamedev_" + name.split(".")[1] + "_command" for name, *_ in DEFINITIONS)
SOURCE = Path(__file__).resolve().parents[2]
PACKAGES = SOURCE / "scripts" / "gamedev"
LIVE_SECONDS = 15
ACTION_SECONDS = 180
MAX_BYTES = 32 * 1024 * 1024
_services = {}
_services_lock = threading.Lock()


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def trusted_origin(handler):
    """A local IPC caller or this task's exact backend/UI origins, including Vite."""
    if handler.client_address[0] not in {"127.0.0.1", "::1"}:
        return False
    origin = handler.headers.get("Origin")
    if not origin:
        return not handler.headers.get("Sec-Fetch-Site")
    page = urlparse(origin)
    if page.scheme not in {"http", "https"} or page.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    allowed = {f"http://127.0.0.1:{int(os.environ.get('NEYVIA_WEB_PORT', '48261'))}",
               os.environ.get("NEYVIA_GAMEDEV_UI_ORIGIN", "http://127.0.0.1:48262")}
    return origin in allowed or page.netloc.casefold() == handler.headers.get("Host", "").casefold()


def installed_editor(engine):
    names = {"unity": ("Unity",), "godot": ("godot", "godot4", "Godot"),
             "blender": ("blender",), "roblox": ("RobloxStudioBeta",)}
    if engine == "babylon":
        return "browser"
    # Explicit process-local override also supports portable editors; no system settings.
    override = os.environ.get("NEYVIA_GAMEDEV_" + engine.upper())
    if override and Path(override).is_file():
        return str(Path(override).resolve())
    for name in names[engine]:
        found = shutil.which(name)
        if found:
            return found
    pf = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    local = Path(os.environ.get("LOCALAPPDATA", "C:/Users/user/AppData/Local"))
    patterns = {"unity": (pf / "Unity/Hub/Editor", "*/Editor/Unity.exe"),
                "blender": (pf / "Blender Foundation", "Blender */blender.exe"),
                "roblox": (local / "Roblox/Versions", "*/RobloxStudioBeta.exe"),
                "godot": (pf / "Godot", "*.exe")}
    base, pattern = patterns[engine]
    return next((str(p) for p in base.glob(pattern) if p.is_file()), None)


def _safe_workspace_path(workspace, value, *, project=None):
    base = Path(project).resolve() if project else workspace
    path = Path(str(value)).expanduser()
    path = (path if path.is_absolute() else base / path).resolve()
    if not path.is_relative_to(base) or not path.is_relative_to(workspace):
        raise ValueError("Path must stay inside the selected workspace/project")
    return path


def _sessions_projection(rows, *, live=True, last_seen=None):
    result = []
    for row in rows:
        data = json.loads(row['data'])
        heartbeat = (last_seen or {}).get(data['sessionId'], row['last'])
        data.update(lastSeen=heartbeat, status='needs_inspection' if data.get('requiresInspection') else 'connected' if live and time.time()-heartbeat < LIVE_SECONDS else 'disconnected')
        result.append(data)
    return {'sessions': result}


def sessions_snapshot(root):
    """Observe saved bridges without creating, reconciling or starting a bridge.

    A prior process's heartbeat is retained as data; only this process's live
    service can assert a current connection.
    """
    root = Path(root).resolve()
    with _services_lock:
        owner = _services.get(str(root))
    if owner is not None:
        return owner.sessions()
    path = root / '.neyvia/gamedev/bridges.sqlite3'
    if not path.is_file():
        return {'sessions': []}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return _sessions_projection(db.execute('SELECT data,last FROM sessions'), live=False)


def validate_asset(root, path, *, workspace=None):
    """Run the real validator independently of editor bridge initialization."""
    workspace = Path(workspace or os.environ.get('NEYVIA_GAMEDEV_WORKSPACE') or root).resolve()
    asset = _safe_workspace_path(workspace, path)
    if asset.suffix.lower() not in {'.gltf', '.glb'} or not asset.is_file():
        raise ValueError('Select an existing workspace .gltf or .glb')
    if asset.stat().st_size > MAX_BYTES:
        raise ValueError('Asset exceeds the 32 MB validation limit')
    completed = subprocess.run(['node', str(PACKAGES / 'validate-asset.cjs'), str(asset), str(workspace)], capture_output=True, text=True, timeout=60, check=False, **hidden_windows_subprocess_kwargs())
    if completed.returncode:
        raise RuntimeError('Asset validator failed: ' + completed.stderr[:500])
    report = json.loads(completed.stdout)
    report.update(path=str(asset), format=asset.suffix[1:], sha256=hashlib.sha256(asset.read_bytes()).hexdigest(), bytes=asset.stat().st_size)
    return report


class GameDev:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.workspace = Path(os.environ.get("NEYVIA_GAMEDEV_WORKSPACE") or self.root).resolve()
        self.directory = self.root / ".neyvia/gamedev"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Heartbeats describe this process's live connection. Persisting every
        # poll blocks readers on disk flushes; a restart disconnects all sessions.
        self.last_seen = {}
        self.db = sqlite3.connect(self.directory / "bridges.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT, token TEXT, last REAL);
          CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, fingerprint TEXT, data TEXT);
          CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, project TEXT, engine TEXT);
        """)
        # Old sessions are disconnected; uncertain actions must never be replayed.
        self.db.execute("UPDATE sessions SET last=0")
        for row in self.db.execute("SELECT id,data FROM requests").fetchall():
            value = json.loads(row["data"])
            if value["status"] in {"queued", "running"}:
                value.update(status="failed", error="Backend restarted during this action; inspect native state before retrying.", finishedAt=stamp())
                self.save(value)
        self.db.commit()
        self.ws_started = False
        self.ws_error = ""
        self.start_websocket()

    def safe_path(self, value, *, project=None):
        return _safe_workspace_path(self.workspace, value, project=project)

    def save(self, value, fingerprint=None):
        encoded = json.dumps(value, ensure_ascii=False)
        if fingerprint:
            self.db.execute("INSERT INTO requests VALUES (?,?,?)", (value["requestId"], fingerprint, encoded))
        else:
            self.db.execute("UPDATE requests SET data=? WHERE id=?", (encoded, value["requestId"]))
        self.db.commit()

    def issue_token(self, project, engine):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        self.db.execute("INSERT INTO tokens VALUES (?,?,?)", (digest, str(project), engine))
        self.db.commit()
        return token

    def authorize(self, token):
        digest = hashlib.sha256(str(token).encode()).hexdigest()
        row = self.db.execute("SELECT * FROM tokens WHERE hash=?", (digest,)).fetchone()
        if not row:
            raise PermissionError("Invalid project bridge capability")
        return row

    def urls(self):
        port = int(os.environ.get("NEYVIA_WEB_PORT", "48261"))
        ws_port = int(os.environ.get("NEYVIA_GAMEDEV_WS_PORT", "48263"))
        return {"httpUrl": f"http://127.0.0.1:{port}", "websocketUrl": f"ws://127.0.0.1:{ws_port}"}

    def start_websocket(self):
        if self.ws_started:
            return
        self.ws_started = True
        def run():
            try:
                from websockets.sync.server import serve
                def connection(socket):
                    for message in socket:
                        try:
                            data = json.loads(message)
                            result = self.bridge(data.get("op"), data, data.get("token"))
                            socket.send(json.dumps({"ok": True, "data": result}))
                        except Exception as exc:
                            socket.send(json.dumps({"ok": False, "error": str(exc)[:500]}))
                with serve(connection, "127.0.0.1", int(os.environ.get("NEYVIA_GAMEDEV_WS_PORT", "48263")), max_size=2*1024*1024, origins=[None]) as server:
                    server.serve_forever()
            except Exception as exc:
                self.ws_error = str(exc)[:300]
        threading.Thread(target=run, name="gamedev-websocket", daemon=True).start()

    def sessions(self):
        with self.lock:
            return _sessions_projection(self.db.execute('SELECT data,last FROM sessions'), last_seen=self.last_seen)

    def status(self):
        sessions = self.sessions()["sessions"]
        engines = []
        for engine in ENGINES:
            executable = installed_editor(engine)
            active = [s for s in sessions if s["engine"] == engine]
            connected = any(s["status"] == "connected" for s in active)
            engines.append({"engine": engine, "installed": bool(executable), "executable": executable,
                            "status": "connected" if connected else "disconnected" if executable else "needs_editor",
                            "sessions": active, "needsPaul": [] if executable else [f"Install {engine}'s editor; no automatic download."]})
        return {"engines": engines, **self.sessions(), "bridge": {**self.urls(), "websocketError": self.ws_error},
                "browserUrl": "/api/gamedev/browser", "browserStandaloneUrl": self.urls()["httpUrl"] + "/api/gamedev/browser"}

    def setup(self, args):
        engine = args.get("engine")
        if engine not in ENGINES:
            raise ValueError("Unknown engine")
        project = self.safe_path(args.get("projectPath", ""))
        if not project.is_dir():
            raise ValueError("Select an existing project directory")
        if engine != "babylon" and not installed_editor(engine):
            raise ValueError(f"Needs Paul: install {engine}'s editor first")
        config = project / ".neyvia/gamedev-bridge.json"
        if config.exists():
            value = json.loads(config.read_text(encoding="utf-8"))
            self.authorize(value.get("token"))
            if value.get("projectPath") != str(project) or value.get("engine") != engine:
                raise ValueError("Project already configured for another bridge")
        else:
            value = {**self.urls(), "engine": engine, "projectPath": str(project), "token": self.issue_token(project, engine)}
        destinations = {"unity": project / "Packages/com.neyvia.bridge", "godot": project,
                        "blender": project / ".neyvia/blender", "roblox": project / ".neyvia/roblox", "babylon": project / ".neyvia/babylon"}
        copies = []
        if engine != "babylon":
            for source in sorted((PACKAGES / engine).rglob("*")):
                if source.is_file() and source.suffix not in {".pyc"} and "__pycache__" not in source.parts:
                    relative = source.relative_to(PACKAGES / engine)
                    if engine == "godot" and relative.parts[0] != "addons":
                        continue
                    if engine == "unity" and relative.parts[0] == "OptionalTests":
                        manifest = project / "Packages/manifest.json"
                        dependencies = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {}) if manifest.is_file() else {}
                        if "com.unity.test-framework" not in dependencies:
                            continue
                        relative = Path("Editor/Tests") / source.name.removesuffix(".template")
                    target = self.safe_path(destinations[engine] / relative, project=project)
                    data = source.read_bytes()
                    if engine == "roblox" and source.suffix in {".lua", ".luau"}:
                        if "]==]" in json.dumps(value):
                            raise ValueError("Project configuration contains a Lua template delimiter")
                        data = data.replace(b"__NEYVIA_CONFIG_JSON__", json.dumps(value).encode())
                    if target.exists() and target.read_bytes() != data:
                        raise ValueError("Preserving existing file: " + str(target))
                    copies.append((target, data))
        for target, data in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
        config.parent.mkdir(parents=True, exist_ok=True)
        ignore = config.parent / ".gitignore"
        ignored = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        additions = [entry for entry in ("gamedev-bridge.json", "roblox/") if entry not in ignored.splitlines()]
        if additions:
            ignore.write_text(ignored.rstrip() + "\n" + "\n".join(additions) + "\n", encoding="utf-8")
        if not config.exists():
            config.write_text(json.dumps(value, indent=2), encoding="utf-8")
        instructions = {"unity": ["Open this Unity project; the embedded editor package starts automatically."],
                        "godot": ["Enable Neyvia in Project Settings > Plugins; it adds the native Play bridge autoload.", "Run a main scene, then select its separate Play session for interaction."],
                        "blender": ["Install the project-local Blender add-on and set its bridge config path."],
                        "roblox": ["Install this project-local plugin in Studio and enable localhost HTTP requests.", "Select the exact studio_id and Edit/Client/Server context."],
                        "babylon": ["Open browserUrl in the owner's signed-in backend tab."]}[engine]
        return {"engine": engine, "projectPath": str(project), "files": [str(t) for t, _ in copies], "bridgeConfigPath": str(config), "instructions": instructions,
                "browserUrl": "/api/gamedev/browser?project=" + __import__("urllib.parse", fromlist=["quote"]).quote(str(project))}

    def project_status(self, args):
        """Fresh configuration/package observation; installation is not connection."""
        engine = args.get('engine')
        if engine not in ENGINES:
            raise ValueError('Unknown engine')
        project = self.safe_path(args.get('projectPath', ''))
        config = project / '.neyvia/gamedev-bridge.json'
        result = {'engine': engine, 'projectPath': str(project), 'configured': False, 'files': []}
        if not config.is_file():
            return result
        value = json.loads(config.read_text(encoding='utf-8'))
        grant = self.authorize(value.get('token'))
        if (value.get('engine') != engine or value.get('projectPath') != str(project)
                or grant['engine'] != engine or grant['project'] != str(project)
                or any(value.get(key) != url for key, url in self.urls().items())):
            return result
        destination = {'unity': project / 'Packages/com.neyvia.bridge', 'godot': project,
                       'blender': project / '.neyvia/blender', 'roblox': project / '.neyvia/roblox', 'babylon': project / '.neyvia/babylon'}[engine]
        for source in sorted((PACKAGES / engine).rglob('*')) if engine != 'babylon' else []:
            if not source.is_file() or source.suffix == '.pyc' or '__pycache__' in source.parts:
                continue
            relative = source.relative_to(PACKAGES / engine)
            if engine == 'godot' and relative.parts[0] != 'addons':
                continue
            if engine == 'unity' and relative.parts[0] == 'OptionalTests':
                manifest = project / 'Packages/manifest.json'
                dependencies = json.loads(manifest.read_text(encoding='utf-8')).get('dependencies', {}) if manifest.is_file() else {}
                if 'com.unity.test-framework' not in dependencies:
                    continue
                relative = Path('Editor/Tests') / source.name.removesuffix('.template')
            expected = source.read_bytes()
            if engine == 'roblox' and source.suffix in {'.lua', '.luau'}:
                expected = expected.replace(b'__NEYVIA_CONFIG_JSON__', json.dumps(value).encode())
            target = self.safe_path(destination / relative, project=project)
            if not target.is_file() or target.read_bytes() != expected:
                return result
            result['files'].append({'path': str(target), 'sha256': hashlib.sha256(expected).hexdigest()})
        result['configured'] = True
        return result

    def bridge(self, op, args, token):
        with self.lock:
            grant = self.authorize(token)
            if op == "register":
                project = self.safe_path(args.get("projectPath", ""))
                if str(project) != grant["project"] or args.get("engine") != grant["engine"]:
                    raise PermissionError("Bridge capability belongs to a different engine/project")
                context = args.get("context", "Edit")
                if context not in {"Edit", "Client", "Server", "Play"}:
                    raise ValueError("Unsupported native context")
                capabilities = args.get("capabilities", [])
                if not isinstance(capabilities, list) or len(capabilities) > 30 or not all(isinstance(c, str) and len(c) < 60 for c in capabilities):
                    raise ValueError("Invalid bridge capabilities")
                if args["engine"] == "roblox" and not args.get("studio_id"):
                    raise ValueError("Roblox studio_id affinity is required")
                client_id = args.get("clientId")
                if client_id is not None:
                    if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", client_id):
                        raise ValueError("Native clientId must be a bounded instance identity")
                    for prior in self.db.execute("SELECT id,data,token FROM sessions WHERE token=?", (grant["hash"],)):
                        previous = json.loads(prior["data"])
                        if previous.get("clientId") != client_id:
                            continue
                        if (previous["engine"] != args["engine"] or previous["projectPath"] != str(project)
                                or previous["context"] != context or previous.get("studio_id") != args.get("studio_id")
                                or previous["capabilities"] != capabilities):
                            raise ValueError("Native clientId was reused for different registration intent")
                        self.last_seen[prior['id']] = time.time()
                        return {"sessionId": prior["id"]}
                identity = uuid.uuid4().hex
                data = {"sessionId": identity, "engine": args["engine"], "projectPath": str(project), "context": context,
                        "capabilities": capabilities, "studio_id": args.get("studio_id"), "registeredAt": stamp(),
                        "environment": str(args.get("environment") or "native-editor")[:100]}
                if client_id is not None:
                    data["clientId"] = client_id
                self.db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (identity, json.dumps(data), grant["hash"], time.time()))
                self.db.commit()
                self.last_seen[identity] = time.time()
                return {"sessionId": identity}
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (args.get("sessionId"),)).fetchone()
            if not row or not hmac.compare_digest(row["token"], grant["hash"]):
                raise PermissionError("Unknown session or wrong project capability")
            self.last_seen[row['id']] = time.time()
            if op == "poll":
                if json.loads(row["data"]).get("requiresInspection"):
                    return {"request": None, "needsInspection": "Inspect native state and reconnect after the timed-out action"}
                if args.get("busy") is True:
                    return {"request": None}
                pending = [json.loads(r["data"]) for r in self.db.execute("SELECT data FROM requests")]
                for value in pending:
                    if value["sessionId"] == row["id"] and value["status"] == "running":
                        state = self.receipt(value["requestId"])["status"]
                        if state == "running":
                            return {"request": None}
                        if state == "timed_out":
                            return {"request": None, "needsInspection": "Native action timed out; inspect and reconnect"}
                for value in pending:
                    if value["sessionId"] == row["id"] and value["status"] == "queued":
                        if self.receipt(value["requestId"])["status"] != "queued":
                            continue
                        value.update(status="running", startedAt=stamp())
                        self.save(value)
                        return {"request": {k: value[k] for k in ("requestId", "action", "args")}}
                return {"request": None}
            if op == "complete":
                value = self.receipt(args.get("requestId"))
                if value["sessionId"] != row["id"]:
                    raise PermissionError("Receipt belongs to a different native session")
                if value["status"] != "running":
                    if value["status"] in {"succeeded", "failed"} and value["status"] == args.get("status") and value.get("result") == args.get("result", {}) and value.get("error", "") == str(args.get("error", ""))[:2000]:
                        return value  # Lost response: identical completion is safe to repeat.
                    raise ValueError("Only an assigned running request can complete")
                if args.get("status") not in {"succeeded", "failed"}:
                    raise ValueError("Invalid completion status")
                result = args.get("result", {})
                if len(json.dumps(result)) > 1024*1024:
                    raise ValueError("Use paths/handles for large native results")
                value.update(status=args["status"], result=result, error=str(args.get("error", ""))[:2000], finishedAt=stamp(), elapsedMs=round((time.time()-value["createdEpoch"])*1000, 2))
                self.save(value)
                return value
            raise ValueError("Unknown bridge operation")

    def receipt(self, request_id):
        with self.lock:
            row = self.db.execute("SELECT data FROM requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise ValueError("Unknown requestId")
            value = json.loads(row["data"])
            deadline = 660 if value.get("action") == "test" else ACTION_SECONDS
            if value["status"] in {"queued", "running"} and time.time()-value["createdEpoch"] > deadline:
                if value["status"] == "running":
                    row = self.db.execute("SELECT data FROM sessions WHERE id=?", (value["sessionId"],)).fetchone()
                    if row:
                        native = json.loads(row["data"])
                        native["requiresInspection"] = True
                        self.db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(native), value["sessionId"]))
                value.update(status="timed_out", error="Native editor did not finish before the deadline; inspect before retrying.", finishedAt=stamp())
                self.save(value)
            value["elapsedMs"] = value.get("elapsedMs", round((time.time()-value["createdEpoch"])*1000, 2))
            return value

    def receipts(self, args):
        limit = args.get("limit", 40)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("Receipt limit must be an integer from 1 to 200")
        rows = self.db.execute("SELECT id,data FROM requests ORDER BY rowid DESC").fetchall()
        ids = [row["id"] for row in rows if not args.get("sessionId") or json.loads(row["data"])["sessionId"] == args["sessionId"]]
        return {"receipts": [self.receipt(identity) for identity in ids[:limit]]}

    def action(self, args):
        with self.lock:
            identity = args.get("requestId") or uuid.uuid4().hex
            if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
                raise ValueError("requestId must be 1–128 characters")
            intent = json.loads(json.dumps({k: args.get(k, {} if k == "args" else "") for k in ("sessionId", "action", "args")}))
            fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
            old = self.db.execute("SELECT fingerprint FROM requests WHERE id=?", (identity,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("requestId already belongs to a different action")
                return self.receipt(identity)
            session = next((s for s in self.sessions()["sessions"] if s["sessionId"] == args.get("sessionId")), None)
            if not session or session["status"] != "connected":
                raise ValueError("Select a connected editor session")
            if args.get("action") not in session["capabilities"]:
                raise ValueError("Native session does not support this action/context")
            if not isinstance(intent["args"], dict) or len(json.dumps(intent)) > 1024*1024:
                raise ValueError("args must be a bounded object")
            engine = session["engine"]
            for key in ("path", "outputPath", "assetPath", "scriptPath"):
                raw = intent["args"].get(key)
                if not raw or engine == "roblox":
                    continue  # Roblox paths are Instance paths, not filesystem paths.
                if engine == "unity" and key == "path" and not (raw.replace("\\", "/").startswith("Assets/") or Path(raw).is_absolute()):
                    continue  # Unity object hierarchy paths stay native.
                local = raw.removeprefix("res://") if engine == "godot" else raw
                resolved = self.safe_path(local, project=session["projectPath"])
                if engine == "godot":
                    intent["args"][key] = "res://" + resolved.relative_to(Path(session["projectPath"])).as_posix()
                elif engine == "unity":
                    intent["args"][key] = resolved.relative_to(Path(session["projectPath"])).as_posix()
                else:
                    intent["args"][key] = str(resolved)
            if intent["args"].get("context", session["context"]) != session["context"]:
                raise ValueError("Action context differs from the selected native session")
            if intent["args"].get("studio_id", session.get("studio_id")) != session.get("studio_id"):
                raise ValueError("Action studio_id differs from the selected Studio")
            if args.get("action") == "load_asset":
                asset = intent["args"].get("path") or intent["args"].get("assetPath")
                check_path = self.safe_path(str(asset).removeprefix("res://"), project=session["projectPath"]) if asset else None
                if not check_path or not self.validate(check_path)["valid"]:
                    raise ValueError("Asset must pass validation before engine load")
            value = {**intent, "requestId": identity, "receiptId": identity, "engine": session["engine"], "context": session["context"],
                     "studio_id": session.get("studio_id"), "status": "queued", "result": {}, "createdAt": stamp(), "createdEpoch": time.time()}
            self.save(value, fingerprint)
            return value

    def validate(self, path):
        return validate_asset(self.root, path, workspace=self.workspace)


def service_for(root):
    key = str(Path(root).resolve())
    with _services_lock:
        if key not in _services:
            _services[key] = GameDev(root)
        return _services[key]


def handle_command(root_or_backend, command, payload):
    # pathlib.Path.root is the drive root ("\\"), not an owning backend root.
    # Native gateway callers pass Path; treating it as a backend loses affinity.
    root = root_or_backend if isinstance(root_or_backend, (str, Path)) else root_or_backend.root
    if command not in COMMANDS:
        raise ValueError("Unknown game-dev command")
    expected = payload.get("_expectedStateRoot")
    if expected and Path(expected).resolve() != Path(root).resolve():
        raise ValueError("Game-dev service belongs to a different state root")
    op = command[len('gamedev_'):-len('_command')]
    if op == 'sessions':
        observed = sessions_snapshot(root)
        if payload.get('projectPath'):
            workspace = Path(os.environ.get('NEYVIA_GAMEDEV_WORKSPACE') or root).resolve()
            selected = str(_safe_workspace_path(workspace, payload['projectPath']))
        else:
            selected = None
        return {'sessions': [row for row in observed['sessions']
                if (not payload.get('engine') or row['engine'] == payload['engine'])
                and (not selected or row['projectPath'] == selected)
                and (not payload.get('context') or row['context'] == payload['context'])]}
    if op == 'asset_validate':
        return validate_asset(root, payload.get('path'))
    service = service_for(root)
    with service.lock:
        op = command[len("gamedev_"):-len("_command")]
        if op == "status":
            return service.status()
        if op == "project_status":
            return service.project_status(payload)
        if op == "sessions":
            return service.sessions()
        if op == "setup":
            return service.setup(payload)
        if op == "action":
            return service.action(payload)
        if op == "receipt":
            return service.receipt(payload.get("requestId"))
        if op == "receipts":
            return service.receipts(payload)
        if op == "state":
            from .ui_command_bus import bus_for
            return {"ui": bus_for(root).get("app:game-dev"), "sessions": service.sessions()["sessions"]}
        return service.validate(payload.get("path"))


def report_state(root, state, client):
    from .ui_command_bus import bus_for
    if not isinstance(state, dict) or len(json.dumps(state)) > 65536:
        raise ValueError("Game Dev screen state must be a bounded object")
    tab = state.get("tab")
    if tab not in {*ENGINES, "assets"}:
        raise ValueError("Unknown Game Dev screen tab")
    picked = state.get("picked", {})
    if not isinstance(picked, dict) or not all(key in ENGINES and isinstance(value, str) and len(value) <= 128 for key, value in picked.items()):
        raise ValueError("Invalid Game Dev screen selection")
    value = {"tab": tab, "picked": picked, "clientId": str(client)[:128], "observedAt": stamp(), "source": "ui"}
    bus_for(root).put("app:game-dev", value)
    return {"ok": True, "state": value}


def call(service, name, args):
    return handle_command(service.backend or service.bus.root, "gamedev_" + name.split(".")[1] + "_command", args)


def forward_command(root, name, payload):
    from .connected_sessions.forward import forward_connected_command
    return forward_connected_command(root, name, payload)


def serve_http(backend, handler, parsed, method):
    from .web_backend import _json_response, _read_json_body
    service = service_for(backend.root)
    try:
        if parsed.path.startswith("/api/gamedev/bridge/"):
            if method != "POST" or handler.client_address[0] not in {"127.0.0.1", "::1"}:
                raise PermissionError("Editor bridges accept localhost POST only")
            if not trusted_origin(handler):
                raise PermissionError("Bridge request origin is not this local app/proxy")
            token = handler.headers.get("Authorization", "").removeprefix("Bearer ")
            with service.lock:
                service.authorize(token)
            if not 0 <= int(handler.headers.get("Content-Length", "0")) <= 2 * 1024 * 1024:
                raise ValueError("Bridge request exceeds 2 MB")
            body = _read_json_body(handler)
            result = service.bridge(parsed.path.rsplit("/", 1)[-1], body, token)
            _json_response(handler, 200, {"ok": True, "data": result})
            return
        session = backend.authenticated_session(handler)
        if not session or str(session.get("username", "")).casefold() != backend.username.casefold():
            raise PermissionError("The PC owner's authenticated session is required")
        query = parse_qs(parsed.query)
        if parsed.path == "/api/gamedev/browser" and method == "GET":
            from .web_backend import _html_response
            project = service.safe_path((query.get("project") or [str(service.workspace)])[0])
            setup = service.setup({"engine": "babylon", "projectPath": str(project)})
            config = json.loads(Path(setup["bridgeConfigPath"]).read_text(encoding="utf-8"))
            html = (PACKAGES / "browser.html").read_text(encoding="utf-8").replace("__NEYVIA_CONFIG_JSON__", json.dumps(config).replace("<", "\\u003c"))
            _html_response(handler, 200, html, frame_options="SAMEORIGIN")
            return
        if parsed.path == "/api/gamedev/asset" and method == "GET":
            asset = service.safe_path((query.get("path") or [""])[0])
            # Only validated glTF payloads and their bounded local buffers are served.
            if asset.suffix.lower() not in {".glb", ".gltf", ".bin", ".png", ".jpg", ".jpeg"} or not asset.is_file() or asset.stat().st_size > MAX_BYTES:
                raise ValueError("Unsupported asset resource")
            data = asset.read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", "model/gltf-binary" if asset.suffix == ".glb" else "application/octet-stream")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        if parsed.path == "/api/gamedev/browser-state" and method == "GET":
            project = service.safe_path((query.get("project") or [str(service.workspace)])[0])
            scene = service.safe_path(project / ".neyvia/scene.babylon", project=project)
            if scene.is_file():
                if scene.stat().st_size > MAX_BYTES:
                    raise ValueError("Persisted scene exceeds 32 MB")
                data = scene.read_bytes()
                _json_response(handler, 200, {"ok": True, "data": {"scene": json.loads(data), "sha256": hashlib.sha256(data).hexdigest()}})
            else:
                _json_response(handler, 200, {"ok": True, "data": {"scene": None, "sha256": None}})
            return
        if parsed.path == "/api/gamedev/browser-save" and method == "POST":
            import base64
            if not trusted_origin(handler):
                raise PermissionError("Scene writes require the owner's local app origin")
            if not 0 <= int(handler.headers.get("Content-Length", "0")) <= 44 * 1024 * 1024:
                raise ValueError("Scene export request exceeds its bounded size")
            body = _read_json_body(handler)
            project = service.safe_path(body.get("projectPath", ""))
            asset = service.safe_path(body.get("path", ""), project=project)
            if asset.suffix.lower() not in {".glb", ".babylon"}:
                raise ValueError("Browser export supports GLB or Babylon scene only")
            data = base64.b64decode(body.get("data", ""), validate=True)
            if len(data) > MAX_BYTES:
                raise ValueError("Export exceeds 32 MB")
            expected = body.get("expectedSha256")
            if asset.exists() and (not expected or hashlib.sha256(asset.read_bytes()).hexdigest() != expected):
                raise ValueError("Existing export needs its current expectedSha256")
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(data)
            _json_response(handler, 200, {"ok": True, "data": {"path": str(asset), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}})
            return
        if parsed.path.startswith("/api/gamedev/static/") and method == "GET":
            name = parsed.path.rsplit("/", 1)[-1]
            allow = {"babylon.js", "babylonjs.loaders.min.js", "babylonjs.serializers.min.js", "scene-runtime.js"}
            if name not in allow:
                raise ValueError("Unknown runtime resource")
            path = PACKAGES / ("vendor" if name != "scene-runtime.js" else "") / name
            data = path.read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/javascript")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return
        raise ValueError("Unknown game-dev route")
    except PermissionError as exc:
        _json_response(handler, 403, {"ok": False, "error": str(exc)})
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        _json_response(handler, 400, {"ok": False, "error": str(exc)[:500]})
