"""Replay current runtime contracts without providers or child programs."""
from __future__ import annotations
import ast
import hashlib
import importlib.util
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
import urllib.error
import urllib.request
import verify_follow_failures as failures

CASES = {
 "tests/test_web_backend.py": ["test_agent_chat_runtime_timeout_expands_for_xhigh_without_becoming_unbounded", "test_agent_chat_command_uses_codex_cli_when_runtime_is_codex", "test_openai_codex_route_continues_through_codex_when_delegated_runtime_fails", "test_hermes_auth_store_does_not_own_codex_oauth"],
 "tests/test_neyvia_harnesses.py": ["test_managed_cli_uses_explicit_clamped_runtime_timeout"],
 "tests/test_neyvia_agent.py": ["test_agent_exposes_progressive_gateways_and_real_specialists"],
}

def task_socketpair(*args, **kwargs):
    listener = socket.socket()
    client = socket.socket()
    try:
        listener.bind(("127.0.0.1", 48443))
        listener.listen(1)
        client.connect(("127.0.0.1", 48443))
        server, _ = listener.accept()
        return server, client
    except BaseException:
        client.close()
        raise
    finally:
        listener.close()

def main():
    failures.SCRATCH = failures.REPO / ".agent_control/follow-runtime-current"
    failures.isolate()
    home = failures.SCRATCH / "home"
    home.mkdir(exist_ok=True)
    os.environ.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / ".codex"), NEYVIA_STREAM_EVENTS="0")
    def guard(event, args):
        if event == "subprocess.Popen":
            raise PermissionError("Runtime contract replay denies child launches")
        if event == "socket.bind" and isinstance(args[1], tuple) and args[1][1] != 48443:
            raise PermissionError("Runtime contract replay binds only 48443")
        if event == "socket.connect" and isinstance(args[1], tuple) and (args[1][0] not in {"127.0.0.1", "::1", "localhost"} or args[1][1] != 48443):
            raise PermissionError("Runtime contract replay connects only to 48443")
    sys.addaudithook(guard)
    results = []
    source_hashes = {}
    for relative, names in CASES.items():
        path = failures.REPO / relative
        spec = importlib.util.spec_from_file_location("follow_current_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.name in names:
                source_hashes[relative+"::"+node.name]=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
        if hasattr(module, "REPO_ROOT"):
            module.REPO_ROOT = failures.SCRATCH
        for name in names:
            identifier = relative + "::" + name
            try:
                with patch("socket.socketpair", task_socketpair):
                    if relative == "tests/test_neyvia_harnesses.py":
                        getattr(module, name)()
                    else:
                        owner = next(cls for cls in vars(module).values() if isinstance(cls, type) and hasattr(cls, name))
                        identifier = relative + "::" + owner.__name__ + "::" + name
                        getattr(owner(name), name)()
            except Exception as exc:
                frames = [{"path": str(Path(frame.filename).relative_to(failures.REPO)), "line": frame.lineno}
                    for frame in traceback.extract_tb(exc.__traceback__) if Path(frame.filename).is_relative_to(failures.REPO)]
                results.append({"id": identifier, "passed": False, "exceptionType": type(exc).__name__, "locations": frames})
            else:
                results.append({"id": identifier, "passed": True})
    from grant_agent import web_backend
    root = failures.SCRATCH / "runtime"
    root.mkdir(exist_ok=True)
    backend = web_backend.FluxioWebBackend(root, root)
    server = web_backend._HandshakeSafeThreadingHTTPServer(("127.0.0.1", 48443), web_backend.make_handler(backend))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request("http://127.0.0.1:48443"+path, data=data, headers={"Content-Type":"application/json"})
        try: response = opener.open(req, timeout=20)
        except urllib.error.HTTPError as exc: response = exc
        with response: return {"http": response.status, "body": json.load(response)}
    http_observations = []
    thread.start()
    try:
        assert request("/api/auth/local-session", {})["http"] == 200
        with patch.object(web_backend, "_provider_presence", return_value={"openai-codex":False}), patch.object(web_backend, "_codex_loopback_broker_binding", return_value=None), patch.object(web_backend, "_codex_cli_login_status", return_value={"authenticated":False,"source":None}):
            oauth = request("/api/backend", {"command":"get_openai_codex_oauth_status_command", "payload":{}})
        assert oauth["http"] == 200 and oauth["body"]["data"]["authenticated"] is False
        assert oauth["body"]["data"]["consumerBindings"]["hermes"] == "loopback-openai-broker"
        http_observations.append({"contract":"isolated OAuth consumer ownership", "http":oauth["http"],"passed":True})
        def capture(args, **kwargs):
            Path(args[args.index("--output-last-message")+1]).write_text("Explicit transport fixture",encoding="utf-8")
            observations.append(kwargs["timeout"])
            return {}, "", "", 1
        observations=[]
        with patch.object(web_backend,"_resolve_codex_cli",return_value="codex"), patch.object(web_backend,"_run_process_capture",side_effect=capture), patch.object(backend,"_provider_env",return_value={}):
            for budget in (None, 180, 900):
                payload={"runtime":"codex","message":"Inspect transport budget", "workspacePath":str(root),"route":{"provider":"openai-codex","model":"gpt-6-sol","effort":"high"}}
                if budget is not None: payload["runtimeTimeoutSeconds"]=budget
                result=request("/api/backend",{"command":"send_agent_chat_command","payload":{"payload":payload}})
                assert result["http"]==200 and result["body"]["data"]["reply"]=="Explicit transport fixture"
                assert observations[-1]==budget
                http_observations.append({"contract":"caller budget forwarded", "budget":budget,"http":result["http"],"passed":True})
        fallback_result={"reply":"Explicit fallback transport fixture", "runtime":"codex", "sessionId":"fallback-fixture", "route":{"provider":"openai-codex","model":"gpt-6-sol","effort":"high"},"toolTimeline":[],"filesChanged":[]}
        with patch.object(backend,"_run_hermes_chat",side_effect=RuntimeError("Controlled expired delegated session")), patch.object(backend,"_run_codex_chat",return_value=fallback_result) as codex, patch.object(web_backend,"_codex_cli_login_status",return_value={"authenticated":True,"source":"isolated-fixture"}), patch.object(backend,"_provider_env",return_value={}):
            for allowed in (False, True):
                before=codex.call_count
                result=request("/api/backend",{"command":"send_agent_chat_command","payload":{"payload":{"runtime":"hermes","message":"Inspect explicit fallback admission","workspacePath":str(root),"allowRuntimeFallback":allowed,"route":{"provider":"openai-codex","model":"gpt-6-sol","effort":"high"}}}})
                assert result["http"]==200
                assert codex.call_count-before==(1 if allowed else 0)
                if allowed:
                    assert result["body"]["data"]["runtimeFallback"]["from"]=="hermes"
                else:
                    assert result["body"]["data"]["status"]=="failed" and result["body"]["data"]["exactRoute"] is True
                http_observations.append({"contract":"explicit fallback admission", "allowed":allowed,"http":200,"passed":True})
    finally:
        server.shutdown();server.server_close();thread.join(2)
        assert not thread.is_alive()
    receipt={"schema":"neyvia.FOLLOW.runtime-current.v1","passed":all(row["passed"] for row in results),"cases":results,"http":http_observations,"actualHttpPort":48443,"ownedServerStopped":True,"sourceMethodSha256":source_hashes,
     "auditDenialScopes":["all subprocess launches before execution","all listeners and connections outside owned loopback port 48443","protected project trees and credential/runbook reads before file open"],
     "boundary":"production methods, SDK tool-description loading and authenticated HTTP; controlled absent-auth and captured transport fixtures; no child/provider/model execution, credential files or NAS; original case IDs retained by terminal method name"}
    (failures.REPO/"scripts/evidence/FOLLOW-runtime-current.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt))
    if not receipt["passed"]: raise SystemExit(1)

if __name__=="__main__": main()
