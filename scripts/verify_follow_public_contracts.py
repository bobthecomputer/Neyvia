"""Current public contracts through reviewed direct cases and real owned HTTP.

No model calls, optional harness execution, downloads, production promotion or
test runner. Git uses the installed pinned launcher and disposable repositories.
"""
from __future__ import annotations
import argparse
import ast
import asyncio
import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import runpy
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SCRATCH = REPO / ".agent_control/follow-public-contracts"
STATE = SCRATCH / "http"
PORT = 48445
OUTPUT = REPO / "scripts/evidence/FOLLOW-public-contracts.json"
BASE = "6e25a2e4"

def isolate():
    import verify_follow_failures as proof
    proof.SCRATCH = SCRATCH
    proof.isolate()
    os.environ["PYTHONPATH"] = str(REPO / "src")

def load(name):
    spec = importlib.util.spec_from_file_location("follow_" + name, REPO / "tests" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def preserved():
    old = json.loads(subprocess.check_output(["git", "show", BASE + ":config/tool_suite_lock.json"], cwd=REPO))
    new = json.loads((REPO / "config/tool_suite_lock.json").read_text())
    old_git = next(t for t in old["tools"] if t["toolId"] == "tool.git")
    new_git = next(t for t in new["tools"] if t["toolId"] == "tool.git")
    assert [t for t in old["tools"] if t["toolId"] != "tool.git"] == [t for t in new["tools"] if t["toolId"] != "tool.git"]
    assert {k:v for k,v in old.items() if k != "tools"} == {k:v for k,v in new.items() if k != "tools"}
    for key in old_git:
        if key not in {"state", "selectedVersion", "health", "operations"}:
            assert old_git[key] == new_git[key]
    assert hashlib.sha256(Path(new_git["installPath"]).read_bytes()).hexdigest() == new_git["packageSha256"]
    source_guards = []
    for name in ("git_reference_adapter", "prompt_contract"):
        path = "src/grant_agent/"+name+".py"
        original = subprocess.check_output(["git","show",BASE+":"+path],cwd=REPO)
        current = (REPO/path).read_bytes()
        assert original.replace(b"\r\n",b"\n")==current.replace(b"\r\n",b"\n")
        source_guards.append(path)
    original_catalog = json.loads(subprocess.check_output(["git","show",BASE+":config/capability_packs.json"],cwd=REPO))
    current_catalog = json.loads((REPO/"config/capability_packs.json").read_text())
    for pack in current_catalog["packs"]:
        pack["capabilities"] = [row for row in pack["capabilities"] if row["capabilityId"] not in {"game.godot-project","game.roblox-project"}]
    assert current_catalog == original_catalog
    original_asserts = []
    owned_cases = {
        "test_model_tool_intelligence":{"test_adapted_mcp_tool_is_callable_and_provider_arguments_are_nested"},
        "test_p2p_cache":{"test_remote_fetch_is_hash_bound_allowlisted_and_admitted_atomically"},
        "test_capability_os":{"test_tool_suite_lock_inventory_is_valid_and_operations_are_deferred"},
        "test_agent_vision":{"test_image_tool_delivers_pixels_and_chat_transport_preserves_them","test_vision_filter_keeps_only_two_latest_images_on_the_wire"},
    }
    for name, selected in owned_cases.items():
        path = "tests/"+name+".py"
        original = ast.parse(subprocess.check_output(["git","show",BASE+":"+path],cwd=REPO).decode())
        current = ast.parse((REPO/path).read_text())
        before = [ast.dump(node,include_attributes=False) for fn in original.body if isinstance(fn,ast.FunctionDef) and fn.name in selected for node in ast.walk(fn) if isinstance(node,ast.Assert)]
        after = [ast.dump(node,include_attributes=False) for fn in current.body if isinstance(fn,ast.FunctionDef) and fn.name in selected for node in ast.walk(fn) if isinstance(node,ast.Assert)]
        assert all(statement in after for statement in before), "Original business/security assertion removed: "+path
        original_asserts.append({"path":path,"allOriginalAssertNodesPreserved":True,"originalAssertCount":len(before)})
    return {"unrelatedToolEntriesAndTopLevelConfigUnchanged": True, "gitLauncherSha256": new_git["packageSha256"],
            "gitVersion": new_git["selectedVersion"], "pinScope": "local launcher executable, not package distribution", "productionValidated": False,
            "gitAndPromptProductGuardsUnchanged":source_guards,"originalCapabilityRowsUnchanged":True,"assertionPreservation":original_asserts}

def replay():
    import pytest
    checks = []
    def run(identifier, callback):
        try:
            callback()
        except Exception as exc:
            checks.append({"id": identifier, "passed": False, "exceptionType": type(exc).__name__})
        else:
            checks.append({"id": identifier, "passed": True})
        print(identifier + ": " + str(checks[-1]["passed"]), flush=True)
    # Windows asyncio's wake socket uses TCP. Give that internal channel an
    # explicit allowed task port rather than permitting ephemeral destinations.
    def owned_socketpair(*args, **kwargs):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 48448)); listener.listen(1)
        writer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            writer.connect(("127.0.0.1",48448))
            reader, _ = listener.accept()
            return reader, writer
        except BaseException:
            writer.close(); raise
        finally: listener.close()
    for module_name, names in [
        ("test_neyvia_mcp", ["test_initialize_and_tool_list_are_mcp_shaped_and_deterministic", "test_time_budget_tool_is_synchronous"]),
        ("test_agent_vision", ["test_image_tool_delivers_pixels_and_chat_transport_preserves_them", "test_vision_filter_keeps_only_two_latest_images_on_the_wire"]),
        ("test_git_reference_adapter", ["test_service_executes_and_registers_verified_receipt", "test_real_manifest_is_live_evaluated_and_object_only", "test_real_object_only_workflow_is_bounded_redacted_and_receipted", "test_artifact_registration_rejects_bad_hash_and_lineage"]),
        ("test_model_tool_intelligence", ["test_adapted_mcp_tool_is_callable_and_provider_arguments_are_nested"]),
        ("test_p2p_cache", ["test_remote_fetch_is_hash_bound_allowlisted_and_admitted_atomically"]),
        ("test_capability_os", ["test_tool_suite_lock_inventory_is_valid_and_operations_are_deferred"]),
    ]:
        import inspect
        module = load(module_name)
        for name in names:
            with tempfile.TemporaryDirectory(prefix="public-case-") as folder:
                arguments = {"tmp_path": Path(folder)}
                if "repository" in inspect.signature(getattr(module,name)).parameters:
                    arguments["repository"] = module.repository.__wrapped__(Path(folder))
                fn = getattr(module, name)
                with pytest.MonkeyPatch.context() as patch:
                    arguments["monkeypatch"] = patch
                    if module_name == "test_agent_vision": patch.setattr(socket, "socketpair", owned_socketpair)
                    run("tests/" + module_name + ".py::" + name, lambda: fn(**{k:arguments[k] for k in inspect.signature(fn).parameters}))
    harness = load("test_harness_registry").HarnessRegistryTests()
    run("tests/test_harness_registry.py::HarnessRegistryTests::test_catalog_exposes_the_full_truthful_harness_set", harness.test_catalog_exposes_the_full_truthful_harness_set)
    product = load("test_product_catalog").ProductCatalogTests()
    run("tests/test_product_catalog.py::ProductCatalogTests::test_snapshot_counts_real_native_managed_and_agent_products", product.test_snapshot_counts_real_native_managed_and_agent_products)
    # Replay the unchanged lazy-export assertions in a child with isolation
    # installed before any grant_agent import. No unguarded import subprocess.
    package = load("test_package_init")
    real_run = subprocess.run
    def guarded_run(command, **kwargs):
        assert command[:2] == [sys.executable, "-c"]
        prefix = "import sys; sys.path.insert(0," + repr(str(REPO / "scripts")) + "); import verify_follow_public_contracts as p; p.isolate();\n"
        return real_run([*command[:2], prefix + command[2]], **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(package.subprocess, "run", guarded_run)
        run("tests/test_package_init.py::test_package_exports_are_lazy_and_backwards_compatible", package.test_package_exports_are_lazy_and_backwards_compatible)
    return {"passed": all(c["passed"] for c in checks), "cases": checks, "testRunner": "none; reviewed original functions called directly"}

def cache_lifecycle():
    import pytest
    cache = load("test_p2p_cache")
    handles = []
    original = cache.P2PCacheService._connect
    def tracked(service, **kwargs):
        connection = original(service, **kwargs); handles.append(connection); return connection
    with tempfile.TemporaryDirectory(prefix="cache-lifecycle-") as directory, pytest.MonkeyPatch.context() as patch:
        root = Path(directory); service = cache._service(root)
        patch.setattr(cache.P2PCacheService,"_connect",tracked)
        # Retain every connection object so garbage collection cannot hide leaks.
        with service._database(create=True) as database:
            database.execute("CREATE TABLE follow_commit (value TEXT)")
            database.execute("INSERT INTO follow_commit VALUES ('committed')")
        try:
            with service._database(create=True) as database:
                database.execute("INSERT INTO follow_commit VALUES ('rolled-back')")
                raise ValueError("bounded rollback fixture")
        except ValueError: pass
        def early_return():
            with service._database(create=False) as database:
                return [row[0] for row in database.execute("SELECT value FROM follow_commit")]
        assert early_return() == ["committed"]
        source = root / "proof.txt"; source.write_text("real cache lifecycle proof",encoding="utf-8")
        receipt = service.import_object(service.plan_import(source),approved=True)
        assert service.read_text(receipt["objectHash"])["text"] == source.read_text()
        service._object_rows()
        for connection in handles:
            try: connection.execute("SELECT 1")
            except sqlite3.ProgrammingError: pass
            else: raise AssertionError("An owned SQLite handle remains open")
        moved = service.index_path.with_suffix(".retained.sqlite3")
        service.index_path.rename(moved); moved.rename(service.index_path)
        assert service.read_text(receipt["objectHash"])["text"] == source.read_text()
        for connection in handles:
            try: connection.execute("SELECT 1")
            except sqlite3.ProgrammingError: pass
            else: raise AssertionError("A reloaded SQLite handle remains open")
    return {"passed":True,"commitRollbackAndEarlyReturnPreserved":True,"retainedConnectionsClosed":len(handles),"windowsRenameAndReload":True,"disposableCleanupCompleted":True}

def http_proof():
    gitcases = load("test_git_reference_adapter")
    fixture = Path(tempfile.mkdtemp(prefix="http-git-",dir=STATE))
    workspace, repository, first, second = gitcases.repository.__wrapped__(fixture)
    # The server root is the same contained workspace as this real repository.
    server_root = workspace
    cache = load("test_p2p_cache")._service(server_root)
    config = server_root / "config"; config.mkdir()
    (config / "neyvia_p2p_cache.json").write_text(json.dumps(cache.config),encoding="utf-8")
    (server_root / "cache-proof.txt").write_text("real HTTP local cache proof",encoding="utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}" + path, data=data, headers={"Content-Type":"application/json"})
        try: response = opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc: response = exc
        with response: return response.status, json.load(response)
    checks = []
    def check(name, value):
        assert value, name
        checks.append({"name":name,"passed":True})
    def command(name, payload):
        status, value = request("/api/backend", {"command":name,"payload":payload})
        assert status == 200, name
        return value["data"]
    def mcp(method, params=None):
        status, value = request("/mcp", {"jsonrpc":"2.0","id":len(checks)+1,"method":method,"params":params or {}})
        assert status == 200
        return value
    process = None
    try:
        with (SCRATCH / "backend.log").open("w",encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable,"-B",str(Path(__file__).resolve()),"--serve","--root",str(server_root)],cwd=REPO,env=os.environ.copy(),stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            deadline = time.monotonic()+60
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError("Owned public-contract backend exited")
                try:
                    if request("/api/health")[1].get("ok"): break
                except OSError: pass
                time.sleep(.1)
            else: raise TimeoutError("Owned public-contract backend not ready")
            check("unauthenticated MCP rejected",request("/mcp",{"jsonrpc":"2.0","id":1,"method":"tools/list"})[0]==401)
            check("owned local session admitted",request("/api/auth/local-session",{})[0]==200)
            for capability in ("game.godot-project","game.roblox-project"):
                value = command("describe_capability_command",{"capabilityId":capability})
                check("planned capability visible without callable bridge "+capability,value["capabilityId"]==capability and value["available"] is False and value["adapterDescriptor"]["supportsExecution"] is False)
            plan = command("plan_p2p_cache_import_command",{"path":"cache-proof.txt","kind":"context-chunk"})
            value = command("import_p2p_cache_object_command",{"plan":plan,"approved":False})
            check("local cache write requires explicit approval",value["status"]=="approval_required")
            value = command("import_p2p_cache_object_command",{"plan":plan,"approved":True})
            digest = value["objectHash"]
            check("real BLAKE3-bound local file imported",value["integrityVerified"] is True)
            value = command("read_p2p_cache_text_command",{"objectHash":digest})
            check("actual local cache bytes read back",value["text"]=="real HTTP local cache proof")
            path = cache._object_path(digest); path.write_bytes(b"actual cache corruption")
            status, value = request("/api/backend",{"command":"read_p2p_cache_text_command","payload":{"objectHash":digest}})
            check("actual changed cache bytes rejected",status>=400 or value.get("ok") is False)
            full = mcp("tools/list")["result"]["tools"]
            names = [tool["name"] for tool in full]
            check("full MCP catalog sorted deterministic and unique",names==sorted(names) and len(names)==len(set(names)) and full==mcp("tools/list")["result"]["tools"])
            thin = mcp("tools/list",{"includeSchemas":False})["result"]["tools"]
            check("progressive catalog preserves names and omits schemas",[tool["name"] for tool in thin]==names and all("inputSchema" not in tool for tool in thin))
            value = mcp("tools/call",{"name":"neyvia.time.budget","arguments":{"deadlineAt":"2999-01-01T00:00:00Z","optional":True}})["result"]
            check("native budget synchronous unwrapped result",value["structuredContent"]["shouldContinue"] is True and "task" not in value and value["isError"] is False)
            value = mcp("tools/call",{"name":"neyvia.time.budget","arguments":{"deadlineAt":"2000-01-01T00:00:00Z","optional":False}})["result"]
            check("expired advisory does not stop required work",value["structuredContent"]["shouldContinue"] is True)
            value = mcp("tools/call",{"name":"neyvia.time.budget","arguments":{"deadlineAt":"invalid"}})["result"]
            check("native validation failure preserves isError and failure receipt",value["isError"] is True and value["structuredContent"]["ok"] is False)
            before = gitcases._git(repository,"rev-parse","HEAD")
            for name, args in [("repository.inspect",{}),("repository.history",{"maxCommits":2}),("repository.show",{"ref":"HEAD","paths":["tracked.txt"]}),("commit.ancestry-verify",{"ancestor":first,"descendant":second})]:
                value = command("execute_tool_suite_command",{"toolId":"tool.git","operationId":name,"arguments":{"repository":"source",**args},"permissionMode":"workspace_safe"})
                check("real HTTP Git operation "+name,value["ok"] and value["outputValidation"]["valid"] and value["result"]["networkAccessed"] is False and value["result"]["policy"]["readOnly"] is True)
                artifacts = value["artifactReceipt"]["artifacts"]
                check("hash and lineage registered "+name,len(artifacts)==1 and bool(artifacts[0]["metadata"]["declaredSha256"]) and bool(artifacts[0]["metadata"]["derivedFrom"]))
            check("all operations preserve repository HEAD",before==gitcases._git(repository,"rev-parse","HEAD"))
            value = command("execute_tool_suite_command",{"toolId":"tool.git","operationId":"repository.inspect","arguments":{"repository":"source"},"permissionMode":"review_only"})
            check("receipt write authority denied in review-only mode",not value["ok"] and value["status"]=="permission_denied")
            value = command("execute_tool_suite_command",{"toolId":"tool.git","operationId":"repository.inspect","arguments":{"repository":"../outside"},"permissionMode":"workspace_safe"})
            check("workspace escape denied through HTTP",not value["ok"])
            gitcases._git(repository,"config","core.sshCommand","fixture-forbidden-helper")
            value = command("execute_tool_suite_command",{"toolId":"tool.git","operationId":"repository.inspect","arguments":{"repository":"source"},"permissionMode":"workspace_safe"})
            check("configured helper denied without executing helper",not value["ok"])
            gitcases._git(repository,"config","--unset","core.sshCommand")
            # A separate real service must refuse a mismatched locked launcher;
            # state=verified never stands in for measured executable identity.
            with tempfile.TemporaryDirectory(prefix="wrong-git-pin-") as directory:
                from grant_agent.capability_service import CapabilityService
                root = Path(directory); config = root / "config"; config.mkdir()
                lock = json.loads((REPO / "config/tool_suite_lock.json").read_text())
                next(tool for tool in lock["tools"] if tool["toolId"]=="tool.git")["packageSha256"] = "0"*64
                (config / "tool_suite_lock.json").write_text(json.dumps(lock),encoding="utf-8")
                service = CapabilityService(root)
                readiness = service.tool_manifests.describe("tool.git")
                check("wrong Git launcher hash prevents executable admission",readiness["executionReady"] is False and readiness["readiness"]["runtimeEvidence"]["runtimeIdentityVerified"] is False and service.adapters.descriptor("code.git").available is False)
        return {"passed":True,"port":PORT,"checks":checks,"gitRepositoryOnlyDisposable":True,"networkAccessedByGit":False,"productionReady":False}
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
            assert process.poll() is not None

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--serve",action="store_true"); parser.add_argument("--root"); args=parser.parse_args()
    isolate()
    if args.serve:
        sys.argv=[str(REPO/"scripts/run_web_backend.py"),"--host","127.0.0.1","--port",str(PORT),"--root",args.root,"--skip-runtime-auto-update"]
        runpy.run_path(sys.argv[0],run_name="__main__"); return
    SCRATCH.mkdir(parents=True,exist_ok=True); STATE.mkdir(parents=True,exist_ok=True)
    evidence={"schema":"neyvia.FOLLOW.public-contracts.v1","preservation":preserved(),"replay":replay(),"cacheLifecycle":cache_lifecycle(),
              "boundaries":{"stdioEcho":"Real owned Python JSONL process; no provider/model/network call; closed on all fixture paths.",
                            "p2pCase":"Pinned isolated sidecar substitute proves cache admission, missing/wrong pin refusals and atomic integrity. Real Iroh transport is not claimed.",
                            "catalog":"Exact current source inventory coverage; Godot/Roblox are declared planned with no callable editor bridge."}}
    try:
        evidence["http"]=http_proof(); evidence["ownedServerStopped"]=True
    finally:
        OUTPUT.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    OUTPUT.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    assert evidence["replay"]["passed"],"An owned original case failed; see scoped receipt"
    print("Public contracts and real HTTP completed",flush=True)

if __name__=="__main__": main()
