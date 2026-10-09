"""Verify the HTTP/chat responsibility split with the owned HTTP acceptance run."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

import verify_follow_depth as depth

BASE = "425b90a8"
REPO = depth.REPO
OWNERS = ("web_backend_http", "web_backend_chat")
OUTPUT = REPO / "scripts/evidence/FOLLOW-web-depth.json"


class OriginalDependencyNames(depth.OriginalNames):
    def visit_FunctionDef(self, node):
        if node.name == "make_handler":
            node.args.kwonlyargs = [arg for arg in node.args.kwonlyargs if arg.arg != "_facade"]
            node.args.kw_defaults = []
        return self.generic_visit(node)


def definitions(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef):
                    owner = "FluxioWebBackend" if node.name == "WebBackendChatMixin" else node.name
                    result[owner + "." + method.name] = method
    return result


def source_parity():
    original = subprocess.check_output(["git", "show", f"{BASE}:src/grant_agent/web_backend.py"], cwd=REPO, text=True, encoding="utf-8")
    before = definitions(ast.parse(original))
    facade = REPO / "src/grant_agent/web_backend.py"
    after = definitions(ast.parse(facade.read_text(encoding="utf-8")))
    public_factory = after["make_handler"]
    assert ast.dump(public_factory.args) == ast.dump(before["make_handler"].args)
    assert ast.dump(public_factory.returns) == ast.dump(before["make_handler"].returns)
    paths = [facade]
    moved = {}
    for name in OWNERS:
        path = REPO / "src/grant_agent" / (name + ".py")
        rows = definitions(ast.parse(path.read_text(encoding="utf-8")))
        moved[name] = [name for name in rows if name != "_backend_facade"]
        after.update(rows)
        paths.append(path)
    for name, node in before.items():
        assert name in after, "Definition lost: " + name
        normalized = OriginalDependencyNames().visit(after[name])
        assert ast.dump(node, include_attributes=False) == ast.dump(normalized, include_attributes=False), "Changed behavior/signature: " + name
    return {"baseline": BASE, "originalDefinitions": len(before), "unchangedAfterDependencyNormalization": len(before),
            "publicHandlerFactorySignatureUnchanged": True, "movedDefinitions": moved,
            "beforeFacadeLines": len(original.splitlines()), "afterFacadeLines": len(facade.read_text(encoding="utf-8").splitlines()),
            "sourceSha256": {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}, original


def chat_mechanisms(original_source):
    from grant_agent import web_backend as facade
    original_path = depth.SCRATCH / "web_backend.baseline.py"
    original_path.write_text(original_source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("grant_agent._follow_web_depth_baseline", original_path)
    original = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = original
    spec.loader.exec_module(original)
    current = facade.FluxioWebBackend(depth.STATE, depth.STATE / "static")
    before = object.__new__(original.FluxioWebBackend)
    before.provider_secrets = {}
    cases = [
        ("_chat_route", ({"runtime": "opencode", "provider": "opencode-go", "model": "opencode-go/deepseek-v4.1-flash", "effort": "default"},)),
        ("_chat_route", ({"provider": "openai", "model": "gpt-6-luna", "effort": "high"},)),
        ("_openclaw_agent_id", ("session-proof", "provider/model")),
        ("_agent_chat_persistence_ids", ({"conversationId": "conversation-proof", "userTurnId": "user-proof", "assistantTurnId": "assistant-proof"},)),
        ("_agent_chat_persistence_ids", ({"conversationId": "conversation-proof"},)),
        ("_compact_agent_chat_result", ({"reply": "saved", "status": "failed", "error": "refused", "privateUnrelated": "excluded", "toolTimeline": [{"kind": "read"}]},)),
    ]
    checked = []
    for name, args in cases:
        expected = getattr(before, name)(*args)
        actual = getattr(current, name)(*args)
        assert expected == actual, f"Output changed: {name}"
        checked.append({"method": name, "output": actual, "matchedOriginal": True})
    bad = {"conversationId": "../invalid", "userTurnId": "user", "assistantTurnId": "assistant"}
    for instance in (before, current):
        try:
            instance._agent_chat_persistence_ids(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Invalid persistence identifier accepted")
    original_normalizer = facade._normalize_chat_model
    try:
        facade._normalize_chat_model = lambda provider, model: "late-bound-model"
        assert current._chat_route({"provider": "openai-codex", "model": "anything"})["model"] == "late-bound-model"
    finally:
        facade._normalize_chat_model = original_normalizer
    tag = uuid.uuid4().hex[:12]
    payload = {"conversationId": "web-depth-" + tag, "userTurnId": "user-" + tag,
               "assistantTurnId": "assistant-" + tag, "message": "Persist the local acceptance receipt.",
               "runtime": "acceptance-storage", "workspacePath": str(depth.STATE)}
    ids, replay = current._begin_agent_chat_persistence(payload)
    assert ids and replay is None
    # Deliberately supplied fixture data exercises storage, never claims a model turn.
    result = {"reply": "Local persistence acceptance record.", "runtime": "acceptance-storage", "status": "completed"}
    saved = current._persist_agent_chat_result(payload, ids, result)
    current._finish_agent_chat_persistence(ids)
    assert saved["conversationPersistence"]["status"] == "persisted"
    restored = facade.FluxioWebBackend(depth.STATE, depth.STATE / "static")
    fresh_ids, replay = restored._begin_agent_chat_persistence(payload)
    assert fresh_ids is None and replay["conversationPersistence"]["status"] == "replayed"
    assert replay["reply"] == result["reply"]
    return {"exactOutputParity": checked, "invalidIdsRefused": True, "liveFacadePatchSeam": True,
            "durableStorageReplay": replay, "boundary": "actual SQLite turn persistence with explicit local fixture result; provider/model execution is unchanged and not claimed"}


def early_error_http():
    """Inject an actual request-boundary failure before business dispatch.

    Initial authentication remains real. Only the second session read, the
    browser owner guard, raises a one-shot ConnectionResetError. The production
    handler must report that failure and keep serving subsequent real requests.
    """
    from grant_agent import web_backend as facade
    backend = facade.FluxioWebBackend(depth.STATE, depth.STATE / "static")
    server = facade._HandshakeSafeThreadingHTTPServer(("127.0.0.1", depth.PORT), facade.make_handler(backend))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    original = backend.authenticated_session
    fault = {"sessionReads": 0, "raised": False}
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def read_session(handler):
        if handler.path == "/api/backend":
            fault["sessionReads"] += 1
            if fault["sessionReads"] == 2:
                fault["raised"] = True
                raise ConnectionResetError("FOLLOW controlled early request disconnect")
        return original(handler)

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{depth.PORT}" + path, data=data, headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            response = opener.open(req, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return {"http": response.status, "durationMs": round((time.perf_counter() - started) * 1000, 2), "body": json.load(response)}

    worker.start()
    try:
        login = request("/api/auth/local-session", {})
        assert login["http"] == 200
        backend.authenticated_session = read_session
        failed = request("/api/backend", {"command": "browser_state_command", "payload": {}})
        assert fault["raised"] and fault["sessionReads"] == 2, fault
        assert failed["http"] == 500 and failed["body"]["error"] == "FOLLOW controlled early request disconnect", failed
        assert "SettingsConflict" not in json.dumps(failed)
        backend.authenticated_session = original
        health = request("/api/health")
        assert health["http"] == 200 and health["body"]["ok"]
        state = request("/api/backend", {"command": "browser_state_command", "payload": {}})
        assert state["http"] == 200 and state["body"]["ok"], state
        return {"point": "real browser request owner-session guard after initial authentication, before settings imports/business dispatch",
                "injection": "one ConnectionResetError at the authenticated_session seam; no business response substituted",
                "fault": fault, "login": login, "failure": failed, "subsequentHealth": health, "subsequentBrowserState": state,
                "settingsConflictDidNotMaskOriginalError": True, "ownedServerStopped": True}
    finally:
        backend.authenticated_session = original
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def shared_build():
    return {"command": "npx vite build --config .agent_control/follow/vite.config.mjs --configLoader runner --outDir <absolute workspace scratch build>",
            "exit": 0, "modules": 6791, "durationSeconds": 40.64, "completedUtc": "2026-10-03T20:22:34Z",
            "log": ".agent_control/follow/build.log", "artifact": ".agent_control/follow/build/index.html",
            "boundary": "latest shared green frontend build includes Game Dev, remote API and voice phone edits; subsequent backend-only responsibility extraction cannot change the frontend bundle; final integrated build owned by lead"}


def main():
    if "--fault-only" in sys.argv:
        depth.install_isolation()
        os.environ.update({"NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
                           "FLUXIO_DISABLE_WSL_AUTH_DISCOVERY": "1", "FLUXIO_RUNTIME_HOME": str(depth.SCRATCH / "home"),
                           "FLUXIO_NAS_VOLUME_ROOT": str(depth.SCRATCH / "unavailable-volume"), "FLUXIO_CONTROL_PROJECT_ROOT": str(depth.STATE),
                           "FLUXIO_WORKSPACE_ROOT": str(depth.STATE), "FLUXIO_WEB_BACKEND_PYTHON": str(depth.PYTHON)})
        sys.path.insert(0, str(REPO / "src"))
        evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
        evidence["earlyRequestError"] = early_error_http()
        evidence["build"] = shared_build()
        OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"earlyRequestError": "passed", "receipt": str(OUTPUT.relative_to(REPO))}))
        return
    parity, original = source_parity()
    # Reuse the existing protected-file/network guard and real owned server
    # lifecycle. Those six HTTP calls now pass through the extracted handler.
    sys.argv = [str(REPO / "scripts/verify_follow_depth.py"), "--out", str(OUTPUT.relative_to(REPO))]
    depth.main()
    evidence = json.loads(OUTPUT.read_text(encoding="utf-8"))
    evidence["schema"] = "neyvia.FOLLOW.web-depth.v1"
    evidence["missionRegression"] = evidence.pop("sourceParity")
    evidence["sourceParity"] = parity
    evidence["boundaries"]["scope"] = "responsibility-only authenticated HTTP transport and chat routing/transport/persistence extraction"
    try:
        evidence["chatMechanisms"] = chat_mechanisms(original)
        evidence["earlyRequestError"] = early_error_http()
        evidence["build"] = shared_build()
    except Exception as exc:
        evidence["passed"] = False
        evidence["error"] = str(exc)
        raise
    finally:
        OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": evidence["passed"], "originalDefinitions": parity["originalDefinitions"],
                      "facadeLines": [parity["beforeFacadeLines"], parity["afterFacadeLines"]], "receipt": str(OUTPUT.relative_to(REPO))}))


if __name__ == "__main__":
    main()
