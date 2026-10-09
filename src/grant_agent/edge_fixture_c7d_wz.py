"""Exact local WZ boundary fixtures; generated inputs never imply remote proof."""
from __future__ import annotations

import gzip
import faulthandler
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "owned bounded input " * 2048, "unicode": "雪 café e\u0301 العربية"}
PURE = {"assistant-selection", "chat-route", "hidden-options"}
HTTP = {"auth-artifact", "desktop-shell", "desktop-update", "http-json", "http-request", "http-io-timeout"}
CONVERSATION = {"conversation-bootstrap", "conversation-revision", "conversation-save"}
REPAIR = {"repair-blocked", "repair-bounds", "repair-receipt", "worker-repair"}
X = {"x-artifacts", "x-following", "x-public-timelines"}
NAMES = PURE | HTTP | CONVERSATION | REPAIR | X | {"hidden-default", "chat-recording"}
IDS = {"proofs-e-wz." + name for name in NAMES}


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def _rejected(action):
    try:
        action()
    except Exception:
        return
    raise AssertionError("Invalid or denied supplied input was accepted")


def _conversation(root, category, name):
    from . import web_backend as owner
    session = {"id": "owned", "title": TEXT.get(category, "owned"), "workspaceId": "scratch"}
    count = 180 if category == "huge" else 4
    turns = [{"id": "t" + str(i), "role": "assistant", "title": TEXT.get(category, "owned"), "createdAt": f"2026-10-05T10:{i // 60:02d}:{i % 60:02d}Z"} for i in range(count)]
    payload = {"chatSessions": [session], "chatSessionTranscripts": {"owned": turns}}
    if category == "empty":
        empty = owner._save_conversation_state(root, {})
        require(not empty["chatSessions"] and not empty["chatSessionTranscripts"], "Empty conversation save invented data")
        _rejected(lambda: owner._conversation_session_state(root, session_id=""))
    state = owner._save_conversation_state(root, payload)
    path = owner._conversation_state_path(root)
    if category == "empty":
        require(not state["chatSessionTranscripts"] and not owner._conversation_session_state(root, session_id="owned")["turns"] and not owner._conversation_state_bootstrap(root, active_session_id="owned")["chatSessionTranscripts"], "Blank supplied conversation turns became accepted transcript text")
        return {"actualEmptySaveReadback": True, "blankTurnsDiscarded": True, "emptySessionIdRefused": True}
    require(len(state["chatSessionTranscripts"]["owned"]) == min(count, 160), "Conversation turn cap differs from current persisted input")
    require(json.loads(path.read_bytes())["chatSessionTranscripts"] == state["chatSessionTranscripts"], "Persisted conversation differs from returned state")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = path.read_bytes()
        with _deny_read(path):
            if name == "conversation-save":
                _rejected(lambda: owner._save_conversation_state(root, {**payload, "mergeExistingTranscripts": True}))
            else:
                result = owner._conversation_state_bootstrap(root, active_session_id="owned") if name == "conversation-bootstrap" else owner._conversation_session_state(root, session_id="owned")
                require(not result.get("turns") and not result.get("chatSessionTranscripts"), "Denied conversation read returned protected transcript")
        require(path.read_bytes() == before, "Denied conversation operation changed keeper")
        return {"actualWindowsSourceReadDenied": True, "keeperUnchanged": True}
    if category == "concurrency":
        def writer(index):
            return owner._save_conversation_state(root, {"mergeExistingTranscripts": True, "chatSessions": [session], "chatSessionTranscripts": {"owned": [{"id": "parallel" + str(index), "role": "assistant", "title": str(index)}]}})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, range(8)))
        current = owner._conversation_session_state(root, session_id="owned")
        require({"parallel" + str(i) for i in range(8)} <= {row["id"] for row in current["turns"]}, "Serialized concurrent conversation merge lost a real turn")
    first = owner._conversation_session_state(root, session_id="owned")
    compact = owner._conversation_session_state(root, session_id="owned", if_revision=first["revision"])
    require(compact["notModified"] and "turns" not in compact, "Matching semantic revision echoed transcript")
    if category == "stale":
        owner._save_conversation_state(root, {"mergeExistingTranscripts": True, "chatSessions": [session], "chatSessionTranscripts": {"owned": [{"id": "fresh", "role": "user", "title": "fresh bytes"}]}})
        changed = owner._conversation_session_state(root, session_id="owned", if_revision=first["revision"])
        require(not changed.get("notModified") and changed["revision"] != first["revision"] and any(row["id"] == "fresh" for row in changed["turns"]), "Stale revision masked changed current state")
    bootstrap = owner._conversation_state_bootstrap(root, active_session_id="owned", turn_limit=2)
    require(bootstrap["performance"]["returnedTurnCount"] == 2 and len(bootstrap["chatSessionTranscripts"]["owned"]) == 2, "Bootstrap did not return bounded active tail")
    receipt = owner._save_conversation_state(root, {**payload, "returnState": False})
    require(receipt["saved"] and "chatSessionTranscripts" not in receipt, "Receipt-only save echoed retained transcripts")
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        code = "import sys,os;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.web_backend import _save_conversation_state;_save_conversation_state(r,{'chatSessions':[{'id':'crash','title':'completed'}]});os._exit(23)"
        child = subprocess.run([sys.executable, "-c", code, str(root)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, timeout=30, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23 and owner._conversation_state_bootstrap(root)["chatSessions"][0]["id"] == "crash", "Completed atomic save was lost at real process-exit boundary")
    return {"actualConversationReadback": True, "semanticRevisionReadback": True, "localStorageOnly": True}


def _chat(root, category, name):
    from .web_backend import FluxioWebBackend
    owner = FluxioWebBackend(root, root)
    text = TEXT.get(category, "owned answer")
    command = "node owned-command.cjs"
    if name == "chat-route":
        for provider in ("glm", "minimax-oauth", "claude-code"):
            route = owner._chat_route({"provider": provider, "model": text, "effort": "high"})
            require(route["provider"] and route["effort"] == "high", "Prepared route lost supplied nonexecuting identity")
        return {"actualRouteProjection": True, "providerExecuted": False}
    selected = owner._normalize_receipt_assistant_message([command, "Command: " + command, text], command)
    require(selected == text.strip(), "Answer normalization confused command trace with supplied model answer")
    if name == "assistant-selection":
        return {"actualCandidateProjection": True, "providerExecuted": False}
    def write(index=0):
        identity = "owned-" + str(index)
        result = owner._save_chat_compartment({"sessionId": identity, "message": text, "runtime": "hermes"}, {"sessionId": identity, "runtime": "hermes", "command": command, "openRuntimeMessage": text, "reply": command, "filesChanged": [], "toolTimeline": [], "elapsedMs": 8})
        require(result["turnReceipt"]["assistantMessage"] == text.strip(), "Chat recording selected command instead of model candidate")
        return result
    first = write()
    path = owner._chat_compartment_path("owned-0")
    require(json.loads(path.read_bytes())["turnReceipt"] == first["turnReceipt"], "Persisted chat receipt differs from actual current result")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = path.read_bytes()
        with _deny_read(path):
            _rejected(write)
        require(path.read_bytes() == before, "Denied chat replacement changed keeper")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(write, range(1, 9)))
        require(len(values) == 8, "Parallel separate chat sessions lost receipts")
    if category == "stale":
        text = "fresh supplied answer"
        fresh = write()
        require(fresh["turnReceipt"]["assistantMessage"] != first["turnReceipt"]["assistantMessage"], "Current answer recording reused stale candidate")
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        code = "import sys,os;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.web_backend import FluxioWebBackend;b=FluxioWebBackend(r,r);b._save_chat_compartment({'sessionId':'crash','message':'owned','runtime':'hermes'},{'sessionId':'crash','runtime':'hermes','openRuntimeMessage':'completed supplied answer','filesChanged':[],'toolTimeline':[]});os._exit(23)"
        child = subprocess.run([sys.executable, "-c", code, str(root)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, timeout=30, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23 and json.loads(owner._chat_compartment_path("crash").read_bytes())["turnReceipt"]["assistantMessage"] == "completed supplied answer", "Durable completed chat record disappeared at owned process-exit boundary")
    return {"actualDurableChatRecording": True, "providerExecuted": False, "renderedProof": False}


def _hidden(root, category, name):
    from .subprocess_utils import hidden_windows_subprocess_kwargs, install_hidden_subprocess_default
    for grouped in (False, True):
        kwargs = hidden_windows_subprocess_kwargs(new_process_group=grouped)
        require(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW and kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE, "Actual Windows spawn policy could expose a window")
    if name == "hidden-options":
        return {"actualWindowsOptions": True}
    require(install_hidden_subprocess_default(), "Windows hidden subprocess default did not install")
    installed = subprocess.Popen.__init__
    require(install_hidden_subprocess_default() and subprocess.Popen.__init__ is installed, "Repeat hidden-default install changed installed wrapper")
    script = root / "console.cjs"
    script.write_text("process.stdout.write(" + json.dumps(TEXT.get(category, "actual owned child")) + ")", encoding="utf-8")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=20)
    require(result.returncode == 0 and result.stdout == TEXT.get(category, "actual owned child"), "Actual hidden child lost supplied stdout")
    return {"actualHiddenNodeChild": True, "installedWrapperRetained": True}


def _repair(root, category, name):
    from .self_repair import execute_self_repair_job, queue_self_repair_job, SELF_REPAIR_JOB_KIND, MAX_REPAIR_ATTEMPTS
    script = root / "app.cjs"; script.write_text("process.exit(9)")
    text = TEXT.get(category, "owned repaired bytes")
    healthy = "process.stdout.write(" + json.dumps(text) + ")"
    repair_script = root / "repair.cjs"
    repair_script.write_text("require('node:fs').writeFileSync('app.cjs'," + json.dumps(healthy) + ")", encoding="utf-8")
    repair = ["node", str(repair_script)]
    contract = {"repairId": "owned", "detectCommand": ["node", str(script)], "repairCommand": repair, "verifyCommand": ["node", str(script)], "trackedPaths": ["app.cjs"], "maxAttempts": 999 if category == "huge" else 1}
    if name == "repair-blocked" or category == "empty":
        for bad in ({}, {**contract, "detectCommand": []}, {**contract, "trackedPaths": ["../outside"]}):
            result = execute_self_repair_job({"jobId": uuid.uuid4().hex, "jobKind": SELF_REPAIR_JOB_KIND, "payload": {"selfRepair": bad}}, workspace=root, env=dict(os.environ), timeout_seconds=20)
            require(result["status"] == "blocked" and not result["repairReceipt"]["phases"] and not result["repairReceipt"]["proof"]["finalVerificationPassed"], "Invalid repair executed phases or acquired completion")
        if name == "repair-blocked":
            return {"invalidContractRefusedBeforeNodeExecution": True, "durableBlockedReceipt": True}
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = script.read_bytes()
        with _deny_read(script):
            result = execute_self_repair_job({"jobId": "denied", "payload": {"selfRepair": contract}}, workspace=root, env=dict(os.environ), timeout_seconds=20)
        require(result["status"] == "failed" and not result["repairReceipt"]["proof"]["finalVerificationPassed"] and script.read_bytes() == before, "Denied source read became completed repair or changed keeper")
        return {"actualNodeSourceDenied": True, "failedRepairRetained": True}
    if name == "worker-repair":
        from .cluster import ClusterRegistry, current_host_id
        from .worker import run_local_worker_once
        registry = ClusterRegistry(root)
        job = queue_self_repair_job(registry, workspace=root, detect_command=contract["detectCommand"], repair_command=repair, verify_command=contract["verifyCommand"], tracked_paths=["app.cjs"], mission_id="owned", workspace_id="scratch", max_attempts=contract["maxAttempts"], total_timeout_seconds=20)
        result = run_local_worker_once(root, host_id=current_host_id())
        require(result["claimed"] and result["result"]["status"] == "completed" and registry.get_job(job["jobId"])["status"] == "completed", "Actual local worker did not persist real repair completion")
        receipt = result["result"]["repairReceipt"]
    else:
        result = execute_self_repair_job({"jobId": "owned", "payload": {"selfRepair": contract}}, workspace=root, env=dict(os.environ), timeout_seconds=20)
        receipt = result["repairReceipt"]
        require(result["status"] == "completed", "Actual detect/repair/verify Node phases did not complete")
    require(script.read_text(encoding="utf-8") == healthy and receipt["bounds"]["attemptsUsed"] == 1 and receipt["bounds"]["maxAttempts"] <= MAX_REPAIR_ATTEMPTS and receipt["proof"]["trackedPathChanges"] == ["app.cjs"], "Repair byte effect or hard attempt bound differs from receipt")
    require(json.loads(Path(result.get("repairReceiptPath", result.get("result", {}).get("repairReceiptPath"))).read_bytes()) == receipt, "Durable repair receipt differs from actual result")
    return {"actualNodeRepairPhases": True, "independentChangedBytes": True, "pytestTestsExecuted": 0}


def _x(root, category, name):
    from .x_following_sources import fetch_following_accounts, collect_following_digest_sources, write_following_source_bundle, XFollowingSourceError
    text = TEXT.get(category, "owned supplied row")
    calls = []
    # Provider protocol values are explicit inputs to the existing projection seam.
    # They never stand in for an observed remote provider or current public data.
    def supplied(url, **kwargs):
        calls.append(url)
        if "following?" in url:
            return {"code": 200, "results": [{"screen_name": "alice", "name": text}, {"screen_name": "ALICE", "name": "duplicate"}, {"screen_name": "private", "protected": True}], "cursor": {}}
        return {"code": 0, "data": {"feed": {}, "entries": [{"title": text, "url": "https://x.com/alice/status/1"}]}}
    if category == "empty":
        _rejected(lambda: fetch_following_accounts("", request_json=supplied))
    if category == "offline":
        def unavailable(url, **kwargs):
            raise XFollowingSourceError("Explicit unavailable supplied transport")
        _rejected(lambda: collect_following_digest_sources("owned", request_json=unavailable))
        require(not (root / "sources").exists(), "Unavailable source invented artifact bundle")
        return {"actualFailClosedCollector": True, "remoteProviderObserved": False}
    snapshot = fetch_following_accounts("owned", max_accounts=999999 if category == "huge" else 8, request_json=supplied)
    require(snapshot["accountCount"] == 2 and [row["screenName"] for row in snapshot["accounts"]] == ["alice", "private"], "Following projection lost input order or casefold dedupe")
    bundle = collect_following_digest_sources("owned", request_json=supplied, workers=999 if category == "huge" else 2)
    require(bundle["summary"]["protectedAccounts"] == 1 and bundle["summary"]["timelinesRequested"] == 1 and bundle["summary"]["postsCollected"] == 1 and all("private" not in url for url in calls), "Collector requested protected account or lost actual input summary")
    if name != "x-artifacts":
        return {"actualSuppliedProtocolProjection": True, "remoteProviderObserved": False, "remotePublicFreshnessProven": False}
    target = root / "sources"
    def write(index=0):
        result = write_following_source_bundle(bundle, target if index == 0 else root / ("sources-" + str(index)))
        manifest = json.loads(Path(result["manifestPath"]).read_bytes())
        for row in manifest["artifacts"]:
            path = Path(result["outputDir"]) / row["path"]
            require(hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], "Durable supplied protocol artifact hash differs")
        return result
    first = write()
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        path = target / "following_snapshot.json"; before = path.read_bytes()
        with _deny_read(path):
            _rejected(write)
        require(path.read_bytes() == before, "Denied artifact replacement changed keeper")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            require(len(list(pool.map(write, range(1, 9)))) == 8, "Independent concurrent source destinations lost receipts")
    if category == "stale":
        bundle["following"]["accounts"][0]["name"] = "fresh supplied row"
        write()
        require(json.loads((target / "following_snapshot.json").read_bytes())["accounts"][0]["name"] == "fresh supplied row", "Artifact replacement reused old supplied snapshot")
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        supplied_path = root / "supplied-bundle.json"; supplied_path.write_text(json.dumps(bundle), encoding="utf-8")
        code = "import sys,os,json;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.x_following_sources import write_following_source_bundle;write_following_source_bundle(json.loads((r/'supplied-bundle.json').read_bytes()),r/'crash-sources');os._exit(23)"
        child = subprocess.run([sys.executable, "-c", code, str(root)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, timeout=30, **hidden_windows_subprocess_kwargs())
        manifest = json.loads((root / "crash-sources/free_api_source_manifest.json").read_bytes())
        require(child.returncode == 23 and all(hashlib.sha256((root / "crash-sources" / row["path"]).read_bytes()).hexdigest() == row["sha256"] for row in manifest["artifacts"]), "Completed source bundle did not survive owned process exit with matching bytes")
    return {"actualArtifactReadback": True, "generatedProtocolInputs": True, "remoteProviderObserved": False, "renderedProof": False}


def _http(root, category, name):
    from . import web_backend as owner
    from .proof_ports import c7_port_block
    port = int(os.environ["NEYVIA_C7_PORT"]); c7_port_block(port)
    static = root / "dist"; (static / "assets").mkdir(parents=True)
    text = TEXT.get(category, "owned transport bytes")
    shell = static / "index.html"; shell.write_text("<!doctype html><title>Owned</title>" + text, encoding="utf-8")
    (static / "assets/index-Owned.js").write_text("export const owned=1")
    (static / "desktop-entry.json").write_text(json.dumps({"js": "/assets/index-Owned.js", "css": []}))
    update = owner.desktop_updates_dir(root); update.mkdir(parents=True)
    feed = update / "latest.json"; feed.write_text(json.dumps({"version": "owned", "text": text}), encoding="utf-8")
    media = root / ".agent_control/generated_image_artifacts/owned.txt"; media.parent.mkdir(parents=True); media.write_text(text, encoding="utf-8")
    env_values = {"SYNTELOS_ACCOUNT_USER": "c7d-owned", "SYNTELOS_ACCOUNT_PASSWORD": "Generated-Disposable-42"}
    previous = {k: os.environ.get(k) for k in env_values}; os.environ.update(env_values)
    backend = owner.FluxioWebBackend(root, static)
    base = owner.make_handler(backend)
    events = []
    event_lock = threading.Lock()
    started = time.monotonic()
    def record(phase, **values):
        # Transport metadata only: never log headers, account values or bodies.
        with event_lock:
            events.append({"elapsedMs": round((time.monotonic() - started) * 1000, 3),
                           "thread": threading.get_ident(), "phase": phase, **values})
    class Handler(base):
        def send_response(self, code, message=None):
            record("response", code=code, path=self.path, clientPort=self.client_address[1])
            return super().send_response(code, message)
        def end_headers(self):
            result = super().end_headers()
            record("headers-sent", path=self.path, clientPort=self.client_address[1])
            return result
        def do_POST(self):
            if self.path == "/c7d-owned-request":
                try:
                    value = owner._read_json_body(self)
                    owner._json_response(self, 200, {"actualRequest": value})
                except Exception as error:
                    owner._json_response(self, 400, {"error": type(error).__name__})
            else:
                super().do_POST()
        def do_GET(self):
            if self.path == "/c7d-owned-io":
                owner._extend_io_timeout(self)
                owner._json_response(self, 200, {"actualSocketTimeout": self.connection.gettimeout(), "text": text})
            else:
                super().do_GET()
    class ObservedServer(owner._HandshakeSafeThreadingHTTPServer):
        def get_request(self):
            value = super().get_request()
            record("accepted", clientPort=value[1][1])
            return value
        def process_request_thread(self, request, client_address):
            record("thread-enter", clientPort=client_address[1])
            try:
                return super().process_request_thread(request, client_address)
            finally:
                record("thread-exit", clientPort=client_address[1])
    server = ObservedServer(("127.0.0.1", port), Handler)
    stack_path = root / "http-thread-stacks.txt"
    stack_file = stack_path.open("w", encoding="utf-8")
    faulthandler.dump_traceback_later(5, repeat=True, file=stack_file)
    diagnostics = {"eventsPath": str(root / "http-request-events.json"), "threadStacksPath": str(stack_path)}
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    cookie = ""
    def request(method, path, data=None, headers=None, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            outgoing = {"Content-Type": "application/json", **(headers or {})}
            if authenticated and cookie:
                outgoing["Cookie"] = cookie
            connection.request(method, path, data, outgoing); response = connection.getresponse()
            return response.status, response.read(), response.headers
        finally:
            connection.close()
    try:
        login = request("POST", "/api/auth/login", json.dumps({"username": "c7d-owned", "password": env_values["SYNTELOS_ACCOUNT_PASSWORD"]}).encode())
        require(login[0] == 200, "Actual disposable account login failed")
        cookie = login[2].get("Set-Cookie", "").split(";", 1)[0]
        artifact_url = "/api/artifact?path=" + urllib.parse.quote(str(media))
        require(request("GET", artifact_url, authenticated=False)[0] == 401, "Unsigned caller acquired private artifact")
        mapping = {"auth-artifact": (artifact_url, media), "desktop-shell": ("/", shell), "desktop-update": ("/updates/desktop/latest.json", feed)}
        def observe():
            if name in mapping:
                route, path = mapping[name]; status, body, headers = request("GET", route)
                require(status == 200 and body == path.read_bytes(), "Actual served artifact/shell/update differs from owned current bytes")
                return len(body)
            if name == "http-request":
                value = {"text": text}; wire = json.dumps(value, ensure_ascii=False).encode()
                status, body, headers = request("POST", "/c7d-owned-request", gzip.compress(wire), {"Content-Encoding": "gzip"})
                require(status == 200 and json.loads(body)["actualRequest"] == value, "Actual gzip request decoder changed supplied Unicode/empty/large JSON")
                malformed = request("POST", "/c7d-owned-request", b"incomplete gzip", {"Content-Encoding": "gzip"})
                require(malformed[0] == 400, "Malformed compressed request acquired accepted JSON")
                return len(body)
            plain = request("GET", "/c7d-owned-io")
            compressed = request("GET", "/c7d-owned-io", headers={"Accept-Encoding": "gzip"})
            body = gzip.decompress(compressed[1]) if compressed[2].get("Content-Encoding") == "gzip" else compressed[1]
            require(plain[0] == compressed[0] == 200 and body == plain[1] and json.loads(body)["text"] == text, "Actual negotiated HTTP JSON changed logical bytes")
            require(json.loads(body)["actualSocketTimeout"] > 10, "Actual request transfer retained short socket accept timeout")
            if category == "huge":
                require(compressed[2].get("Content-Encoding") == "gzip", "Large actual JSON response skipped accepted compression")
            return len(body)
        observed = observe()
        if category == "permissions" and name in mapping:
            from .edge_fixture_models import _deny_read
            route, path = mapping[name]; before = path.read_bytes()
            with _deny_read(path):
                try:
                    status = request("GET", route)[0]
                except http.client.RemoteDisconnected:
                    status = 0
            require(status != 200 and path.read_bytes() == before, "Denied source read acquired served bytes or changed keeper")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                require(all(value == observed for value in pool.map(lambda _: observe(), range(8))), "Concurrent real HTTP transfers diverged")
        if category == "stale" and name in mapping:
            route, path = mapping[name]; path.write_bytes(b"fresh current owned bytes")
            require(request("GET", route)[1] == b"fresh current owned bytes", "Actual current file transfer used stale cached bytes")
        if category == "stale" and name == "auth-artifact":
            require(request("POST", "/api/auth/logout", b"{}")[0] == 200 and request("GET", artifact_url)[0] == 401, "Revoked session retained private artifact authority")
        return {"actualOwnedHTTPTransport": True, "explicitPort": port, "actualTransferredBytes": observed, "renderedProof": False, "desktopInstallerExecuted": False, "diagnostics": diagnostics}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        faulthandler.cancel_dump_traceback_later()
        stack_file.close()
        event_path = root / "http-request-events.json"
        event_path.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
        diagnostics.update(eventsSha256=hashlib.sha256(event_path.read_bytes()).hexdigest(),
                           threadStacksSha256=hashlib.sha256(stack_path.read_bytes()).hexdigest(),
                           threadStacksBytes=stack_path.stat().st_size)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def blocker(contract, category):
    identity = contract.get("id", ""); name = identity.removeprefix("proofs-e-wz.")
    if name not in NAMES:
        return None
    if name in PURE and category not in TEXT:
        return {"kind": "not_applicable", "reason": f"Exact {identity} is a synchronous projection of supplied candidates/route descriptor/Windows option booleans. It holds no OS grant, endpoint session, shared mutable store or worker; remote execution and hidden child behavior have separate owners."}
    if category == "offline" and name not in {"x-following", "x-public-timelines"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} operates on root-local files, supplied message values or explicitly owned Node processes; no remote endpoint/provider operation exists in this invariant."}
    if category == "interrupted" and name in HTTP | {"conversation-bootstrap", "conversation-revision", "hidden-default", "x-following", "x-public-timelines"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} has no resumable accepted operation or durable interruption receipt; a killed read/projection has no returned proof. Chat recording is one synchronous persisted turn; completed atomic conversation saves are exercised under their writer owner."}
    if category == "permissions" and name in {"http-json", "http-request", "http-io-timeout", "x-following", "x-public-timelines", "hidden-default"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} does not admit an OS capability or read a selected protected artifact: it transforms bytes on an already accepted socket, supplied protocol input, default spawn options or a supplied message record. Authenticated artifact and actual source-read denial owners are covered independently."}
    if category in {"concurrency", "stale", "interrupted"} and name in REPAIR:
        return {"kind": "not_applicable", "reason": f"Exact {identity} evaluates one explicitly identified repair job's phase/attempt/byte-effect receipt. It provides no CAS/shared-revision or resumable crash admission. Registry single-claim concurrency and bounded-process interruption are separate owners; new requests are distinct jobs."}
    if category in {"concurrency", "stale"} and name in {"x-following", "x-public-timelines", "hidden-default"}:
        return {"kind": "not_applicable", "reason": f"Exact {identity} projects one supplied protocol snapshot or installs an idempotent process-wide wrapper without cache/revision admission; independent calls have no shared writer state. Collector-internal parallel public timeline projection is exercised in each supplied bundle."}
    return None


def run(root, contracts, categories):
    rows = []
    builder_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for identity in sorted(IDS & contracts.keys()):
        name = identity.removeprefix("proofs-e-wz.")
        for category in categories:
            if blocker(contracts[identity], category):
                continue
            area = Path(root) / (name + "-" + category + "-" + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            row = {"id": "c7d-wz." + name + "." + category, "contracts": [identity], "category": category, "boundary": "Exact root-local production owner; no rendered, physical desktop, remote-provider or public-data freshness proof"}
            started = time.perf_counter()
            try:
                builder = _conversation if name in CONVERSATION else _http if name in HTTP else _repair if name in REPAIR else _x if name in X else _hidden if name.startswith("hidden-") else _chat
                row.update(status="passed", detail=builder(area, category, name))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()[-3500:]})
                if name in HTTP:
                    row["detail"]["diagnostics"] = [
                        {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in (area / "http-request-events.json", area / "http-thread-stacks.txt") if path.is_file()]
            row["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
            with (Path(root) / "case-progress.jsonl").open("a", encoding="utf-8") as progress:
                progress.write(json.dumps({"diagnostic": True, "completionReceipt": False,
                                           "builderSourceSha256": builder_sha, "case": row},
                                          ensure_ascii=True) + "\n")
            rows.append(row)
    return rows
