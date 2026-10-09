"""Executable runtime contracts; checks use real state, not result schemas."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import json
import os
import time
from dataclasses import asdict, replace
from pathlib import Path


def require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_catalog(registry, result):
    packages = registry.packages
    for tier in ("core", "optional"):
        wanted = {k for k, v in packages.items() if v["tier"] == tier}
        rows = result[tier]
        require({r["packageId"] for r in rows} == wanted and len(rows) == len(wanted)
                and all(r == registry._package_summary(packages[r["packageId"]]) for r in rows),
                "runtime.install.catalog", "catalog changed package tier or delivery state")
        require(result["summary"][tier + "Packages"] == len(wanted),
                "runtime.install.catalog", "catalog totals differ from package inventory")


def check_plan(registry, result):
    rows = result["packages"]
    ids = [r["packageId"] for r in rows]
    wanted = {k for k, v in registry.packages.items() if v["tier"] == "core"}
    wanted.update(result["selectedOptional"])
    while True:
        closure = wanted | {d for k in wanted for d in registry.packages[k]["dependsOn"]}
        if closure == wanted:
            break
        wanted = closure
    require(set(ids) == wanted and len(ids) == len(wanted), "runtime.install.plan", "dependency closure differs")
    for row in rows:
        package = registry.packages[row["packageId"]]
        require(all(ids.index(d) < ids.index(row["packageId"]) for d in package["dependsOn"]),
                "runtime.install.plan", "dependency appears after dependent")
        require(row["readyNow"] == (package["deliveryState"] in {"bundled", "verified"}),
                "runtime.install.plan", "unfinished package reported ready")
    blocked = {r["packageId"] for r in rows if not r["readyNow"]}
    require({r["packageId"] for r in result["blockedBy"]} == blocked
            and result["readyToInstall"] == (not blocked) and result["executionAllowed"] is False
            and result["summary"]["blockedCount"] == len(blocked),
            "runtime.install.plan", "planning bypassed an installation gate")


def check_memory_saved(store):
    expected = [asdict(item) for item in store.items]
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    require(persisted == expected and len({i["id"] for i in persisted}) == len(persisted),
            "runtime.memory.durable", "memory save lost content, provenance, ordering or unique ids")


def check_memory_search(store, query, limit, result):
    import re
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    def score(item):
        words = set(re.findall(r"[a-z0-9]+", (item.content + " " + " ".join(item.tags) + " " + item.objective).lower()))
        return len(tokens & words), len(item.tags)
    positive = sorted((i for i in store.items if score(i)[0]), key=score, reverse=True)
    expected = (positive if positive else sorted(store.items, key=lambda i: i.created_at, reverse=True))[:limit]
    require(result == expected, "runtime.memory.search", "search lost positive overlap, ranking or recent fallback")


def check_ingested(memory, session_id, state, previous, inserted):
    requested = [(s, "decision", ["decision", "autonomy"]) for s in state.get("decisions", [])[-3:]]
    requested += [(s, "risk", ["risk", "safety"]) for s in state.get("risks", [])[-2:]]
    requested += [(s, "next_action", ["next_action", "resume"]) for s in state.get("next_actions", [])[:2]]
    added = memory.items[len(previous):]
    require(memory.items[:len(previous)] == previous and inserted == [i.id for i in added]
            and [(i.content, i.kind, i.tags) for i in added] == requested
            and all(i.source_session_id == session_id and i.objective == state.get("objective", "") for i in added),
            "runtime.memory.ingest", "ingest changed bounded selection or provenance")


def check_service_status(spec, result):
    if result["status"] == "running":
        require(result["healthy"] and result["executableMatches"] and result["specMatches"] and result["pid"] > 0,
                "runtime.service.identity", "running requires live PID, executable, spec and health identity")
    if result["status"] == "foreign_pid":
        require(result["pid"] > 0 and not result["executableMatches"],
                "runtime.service.identity", "foreign process identity was not preserved")
    require(result["specHash"] == spec.spec_hash, "runtime.service.identity", "observer returned another service specification")


def check_service_started(result):
    require(result["status"] == "running" and result["pid"] > 0 and result["healthy"]
            and result["executableMatches"] and result["specMatches"],
            "runtime.service.lifecycle", "start returned without the exact healthy process")


def check_service_stopped(result):
    require(result["status"] == "stopped" and result["pid"] == 0,
            "runtime.service.lifecycle", "stop returned with an active or unstopped PID")


def check_node_env(original, directory, result):
    if directory is None:
        require(result == original, "runtime.node.environment", "missing runtime altered environment")
        return
    require(result["PATH"].split(os.pathsep)[0] == str(directory)
            and result["NEYVIA_MANAGED_NODE_BIN"] == str(directory)
            and all(result[k] == v for k, v in original.items() if k not in {"PATH", "NEYVIA_MANAGED_NODE_BIN"}),
            "runtime.node.environment", "resolved runtime not first or unrelated environment changed")


def check_node_version(version, result):
    if version is None:
        expected = False
    else:
        major, minor, patch = version
        expected = ((major == 22 and (minor, patch) >= (22, 3))
                    or (major == 24 and (minor, patch) >= (15, 0))
                    or (major == 25 and (minor, patch) >= (9, 0)) or major > 25)
    require(result == expected, "runtime.node.versions", "unsupported Node version advertised compatible")


def check_mcp_compact(state, row):
    require("tools" not in row and "inputSchema" not in row and row["authState"] == state.auth_state
            and row["callable"] == state.callable and row["transport"] == state.transport,
            "runtime.mcp.discovery", "compact discovery exposed schema or changed authorization")
    if state.transport == "sse":
        require(not row["callable"] and any("sse_not_wired" in note for note in row["notes"]),
                "runtime.mcp.discovery", "unsupported SSE advertised callable")


def check_mcp_search(rows):
    require(all("inputSchema" not in r and "outputSchema" not in r for r in rows),
            "runtime.mcp.discovery", "progressive search leaked schemas")


def check_mcp_described(state, name, spec, result, requires):
    require(result["qualifiedName"] == f"mcp.{state.name}.{name}"
            and result["inputSchema"] == (spec.get("inputSchema") or spec.get("input_schema") or {})
            and result["requiresApproval"] == requires,
            "runtime.mcp.discovery", "description changed schema, identity or approval policy")


def check_mcp_receipt(state, payload, dispatched):
    from .mcp_broker import TOOL_RECEIPT_SCHEMA, PROVIDER
    disk = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
    require(disk == payload and payload["tool"].startswith(f"mcp.{state.name}.")
            and payload["result"]["authState"] == state.auth_state
            and payload["schema"] == TOOL_RECEIPT_SCHEMA and payload["provider"] == PROVIDER,
            "runtime.mcp.receipt", "receipt differs from durable action or authorization state")
    if payload["status"] in {"auth_required", "approval_required"}:
        require(not dispatched and not payload["ok"], "runtime.mcp.authorization", "blocked action was dispatched")
    if payload["ok"]:
        result = payload["result"]
        require(dispatched and payload["status"] == "completed" and state.auth_state == "authenticated"
                and (not result["approvalRequired"] or result["approvalGranted"])
                and result["inputValidation"]["valid"] is not False and result["outputValidation"]["valid"] is not False,
                "runtime.mcp.authorization", "success bypassed dispatch/auth/approval/schema gates")


def check_toolchain_integrity(result):
    rows = result["tools"]
    require(result["healthy"] == all(r["healthy"] for r in rows.values())
            and result["invalidTools"] == sorted(k for k, v in rows.items() if not v["healthy"]),
            "runtime.toolchain.integrity", "integrity summary hides invalid tools")
    for row in rows.values():
        if row["state"] != "platform-managed":
            path = Path(row["path"])
            actual = _file_digest(path) if path.is_file() else ""
            require(row["actualSha256"] == actual and row["hashVerified"] == bool(actual and actual == row["expectedSha256"]),
                    "runtime.toolchain.integrity", "tool bytes do not match integrity receipt")


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_toolchain_discovery(manager, result):
    rows = result["tools"]
    summary = {"checked": sum(r["state"] != "platform-managed" for r in rows.values()),
        "current": sum(r["state"] == "current" for r in rows.values()),
        "updatesAvailable": sum(bool(r["updateAvailable"]) for r in rows.values()),
        "errors": sum(r["state"] == "check-failed" for r in rows.values())}
    require(result["summary"] == summary and result["activationPolicy"] == str(manager.policy.get("candidateActivation") or "signed-neyvia-release"),
            "runtime.toolchain.discovery", "discovery summary or activation authority differs")
    for name, row in rows.items():
        if "candidate" not in row:
            continue
        configured = manager.toolchain["tools"][name]
        update = configured["update"]
        candidate = row["candidate"]
        prefix = f"https://github.com/{update['repository']}/releases/download/"
        digest = candidate["assetSha256"]
        require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
                and 0 < candidate["assetBytes"] <= int(update.get("maxDownloadBytes") or 250_000_000)
                and candidate["assetName"] == update["assetTemplate"].format(version=row["latestVersion"], tag=row["latestTag"])
                and candidate["downloadUrl"].startswith(prefix),
                "runtime.toolchain.discovery", "candidate violates official asset name, size, digest or URL binding")


def self_check(root):
    """Run isolated production actions, real subprocesses and adverse requests."""
    import sys
    from .install_profiles import InstallProfileRegistry
    from .managed_local_service import ManagedServiceSpec, ManagedLocalService
    from .managed_node_runtime import node_supports_current_openclaw, prepend_openclaw_node_to_env
    from .memory import MemoryStore, ingest_state_into_memory
    from .mcp_broker import McpOutboundBroker, StubTransport, register_with_progressive_surface
    from .progressive_tools import ProgressiveToolSurface
    from .marketplace_toolchain import MarketplaceToolchainUpdateManager
    started = time.perf_counter()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    checks, rejections = [], []
    def passed(identity, procedure):
        checks.append({"contract": identity, "ok": True, "procedure": procedure})
    def rejects(identity, action, phrase):
        try:
            action()
        except (ValueError, RuntimeError) as exc:
            require(phrase in str(exc), identity, "adverse request failed for a different reason")
            rejections.append({"contract": identity, "rejected": True, "reason": phrase})
        else:
            raise ValueError(f"Contract {identity}: adverse request was accepted")

    registry = InstallProfileRegistry(root)
    catalog = registry.catalog_snapshot()
    require(catalog["summary"]["corePackages"] == 9 and catalog["summary"]["optionalPackages"] == 15
            and any(r["packageId"] == "core.update-client" and r["deliveryState"] == "foundation" for r in catalog["core"])
            and any(r["packageId"] == "pack.ocr-local" and r["deliveryState"] == "verified" for r in catalog["optional"]),
            "runtime.install.catalog", "current bundled inventory changed")
    recommended = registry.resolve("recommended")
    require(recommended["selectedOptional"] == ["pack.nas-worker", "pack.ocr-local"]
            and recommended["summary"]["optionalCount"] == 2 and not recommended["readyToInstall"]
            and {"core.module-host", "core.update-client", "core.mesh-identity-client"} <= {r["packageId"] for r in recommended["blockedBy"]},
            "runtime.install.plan", "recommended plan concealed unfinished core")
    private = registry.resolve("private-cloud", excluded_optional=["pack.folder-sync"])
    ids = {r["packageId"] for r in private["packages"]}
    require({"pack.ocr-local", "pack.mesh-control-plane", "core.mesh-identity-client"} <= ids
            and "pack.folder-sync" not in ids, "runtime.install.plan", "inheritance/exclusion lost")
    cycle = {"schema": "neyvia.install-profiles/v1", "packages": [
        {"packageId": "core.a", "tier": "core", "deliveryState": "bundled", "installMode": "bundled", "resourceClass": "light", "dependsOn": ["core.b"]},
        {"packageId": "core.b", "tier": "core", "deliveryState": "bundled", "installMode": "bundled", "resourceClass": "light", "dependsOn": ["core.a"]}],
        "profiles": [{"profileId": "minimal", "optionalPackages": []}]}
    cycle_path = root / "cyclic-profiles.json"
    cycle_path.write_text(json.dumps(cycle), encoding="utf-8")
    rejects("runtime.install.cycles", lambda: InstallProfileRegistry(root, registry_path=cycle_path), "package dependency cycle")
    passed("runtime.install.cycles", "constructor rejects cyclic dependency graph")
    passed("runtime.install.catalog", "real bundled catalog observer")
    passed("runtime.install.plan", "recommended and inherited/excluded private-cloud plans")

    store = MemoryStore(root / "memory.json")
    # A fresh subroot makes repeated startup checks safe without deleting memory.
    store.add("proof-runtime", "Build verification loop", "Decision: always run proof checks after edits", ["decision", "verify"], "decision")
    result = store.search("verification checks", limit=5)
    require(result and result[0].source_session_id == "proof-runtime", "runtime.memory.search", "positive memory disappeared")
    ids = ingest_state_into_memory(store, "proof-ingest", {"objective": "Improve safety",
        "decisions": ["Use budget caps", "Block risky commands"], "risks": ["Context overflow"], "next_actions": ["Add replay"]})
    require(len(ids) == 4 and [asdict(i) for i in MemoryStore(store.path).items] == [asdict(i) for i in store.items],
            "runtime.memory.durable", "reopened memory lost ingested state")
    store.search("", 2)
    store.search("no lexical match", 2)
    for identity in ("runtime.memory.durable", "runtime.memory.search", "runtime.memory.ingest"):
        passed(identity, "add/search/ingest/reopen durable scratch memory")
    rejects("runtime.memory.search", lambda: check_memory_search(store, "verification checks", 5, []), "Contract runtime.memory.search")

    versions = [(None, False), ((22, 18, 0), False), ((22, 22, 3), True), ((23, 9, 0), False), ((24, 15, 0), True), ((25, 9, 0), True)]
    require(all(node_supports_current_openclaw(v) == expected for v, expected in versions),
            "runtime.node.versions", "OpenClaw compatibility ranges changed")
    env = {"PATH": os.pathsep.join(("first", "second")), "PROOF": "kept"}
    directory = root / "resolved-node-bin"
    updated = prepend_openclaw_node_to_env(env, resolved_bin=directory)
    require(env["PATH"].startswith("first") and updated["PATH"].split(os.pathsep)[1:] == ["first", "second"],
            "runtime.node.environment", "original PATH was mutated or truncated")
    passed("runtime.node.versions", "supported and excluded major/minor/patch boundaries")
    passed("runtime.node.environment", "resolved runtime prepended without installation or download")

    executable = Path(sys.executable).resolve()
    executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    server = root / "health_service.py"
    server.write_text(proof_text('''import json\nfrom http.server import BaseHTTPRequestHandler,HTTPServer\nclass Handler(BaseHTTPRequestHandler):\n def do_GET(self):\n  body=json.dumps({"status":"ok","identity":"proofs-c-runtime"}).encode()\n  self.send_response(200);self.end_headers();self.wfile.write(body)\n def log_message(self,*args): pass\nHTTPServer(("127.0.0.1",48488),Handler).serve_forever()\n'''), encoding="utf-8")
    spec = ManagedServiceSpec(service_id="proofs-c.runtime", executable=executable, executable_sha256=executable_hash,
        argv=("-I", str(server)), state_root=root / "service", health_url=proof_text("http://127.0.0.1:48488/health"),
        health_expected={"status": "ok"}, identity_url=proof_text("http://127.0.0.1:48488/identity"), identity_value="proofs-c-runtime",
        required_files=((server, hashlib.sha256(server.read_bytes()).hexdigest()),), startup_timeout_seconds=8, stop_timeout_seconds=3)
    rejects("runtime.service.spec", lambda: replace(spec, health_url=proof_text("http://example.invalid:48488/health")), "loopback")
    rejects("runtime.service.spec", lambda: replace(spec, executable_sha256="invalid"), "SHA-256")
    first = replace(spec, environment={"PROOF_MODEL_STORE": "a"})
    second = replace(spec, environment={"PROOF_MODEL_STORE": "b"})
    require(first.spec_hash != second.spec_hash and replace(spec, inherit_environment=False).spec_hash != spec.spec_hash,
            "runtime.service.spec", "environment values or inheritance excluded from service identity")
    rejects("runtime.service.installation", lambda: ManagedLocalService(replace(spec, executable_sha256="0" * 64)).start(), "hash mismatch")
    rejects("runtime.service.installation", lambda: ManagedLocalService(replace(spec, required_files=((server, "f" * 64),))).start(), "required file hash mismatch")
    # Observe the verifier itself as a foreign PID; refusal happens before any signal.
    foreign_binary = root / "foreign-declaration.exe"
    foreign_binary.write_bytes(b"unrelated executable declaration")
    foreign = replace(spec, executable=foreign_binary, executable_sha256=hashlib.sha256(foreign_binary.read_bytes()).hexdigest(), state_root=root / "foreign-service")
    foreign.state_root.mkdir(parents=True, exist_ok=True)
    foreign.state_path.write_text(json.dumps({"pid": os.getpid(), "specHash": foreign.spec_hash}), encoding="utf-8")
    foreign_service = ManagedLocalService(foreign)
    require(foreign_service.status()["status"] == "foreign_pid", "runtime.service.identity", "live foreign PID not detected")
    rejects("runtime.service.identity", foreign_service.stop, "unverified PID")
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", proof_port(48488)))
    service = ManagedLocalService(spec)
    try:
        launched = service.start()
        require(launched["status"] == "running" and not launched["reused"], "runtime.service.lifecycle", "new healthy process not started")
        reused = ManagedLocalService(spec).start()
        require(reused["reused"] and reused["pid"] == launched["pid"], "runtime.service.lifecycle", "healthy matching process was replaced")
        stopped = service.stop()
        require(stopped["status"] == "stopped" and not stopped["pid"], "runtime.service.lifecycle", "owned process did not stop")
    finally:
        # No unverified process may be stopped even during cleanup.
        state = service.status()
        if state["status"] == "running":
            service.stop()
    for identity in ("runtime.service.spec", "runtime.service.installation", "runtime.service.identity", "runtime.service.lifecycle"):
        passed(identity, "hash-pinned real HTTP child start/reuse/stop; foreign PID and tampering refused")

    binary = root / "pinned-tool.exe"
    binary.write_bytes(b"proof-runtime-pinned-binary")
    config = root / "toolchain.json"
    configured_tool = {"version": "1.0.0", "path": str(binary), "executableSha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "update": {"repository": "proofs-c/runtime", "tagPrefix": "v", "assetTemplate": "runtime_{version}.zip", "maxDownloadBytes": 1000}}
    config.write_text(json.dumps({"schema": "neyvia.marketplace-toolchain/v1", "policy": {"candidateActivation": "signed-neyvia-release"}, "tools": {
        "proof": configured_tool,
        "platform": {"version": "platform-current", "path": "auto", "executableSha256": "dynamic-platform-update"}}}), encoding="utf-8")
    manager = MarketplaceToolchainUpdateManager(root, toolchain_path=config, cache_path=root / "toolchain-cache.json")
    integrity = manager.local_integrity()
    require(integrity["healthy"] and integrity["tools"]["proof"]["hashVerified"] and integrity["tools"]["platform"]["state"] == "platform-managed",
            "runtime.toolchain.integrity", "pinned integrity not verified")
    binary.write_bytes(b"tampered")
    require(manager.local_integrity()["invalidTools"] == ["proof"], "runtime.toolchain.integrity", "tampering was not surfaced")
    passed("runtime.toolchain.integrity", "streamed real bytes then tampered pinned binary")
    _toolchain_self_check(root, manager, configured_tool, passed, rejects)

    _mcp_self_check(root / "mcp", passed, rejects)
    contracts = sorted({r["contract"] for r in checks})
    return {"ok": True, "contracts": contracts, "checks": checks, "rejections": rejections,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 3), "frontier": [
            "Marketplace OCI positive authenticated verifier/activation/rollback/crash journeys remain protected by retained tests.",
            proof_text("Official upstream GitHub availability is not claimed: discovery self-check serves declared release metadata on owned loopback48487, runs the production parser and real persisted cache; no package downloads.")]}


def _toolchain_self_check(root, manager, configured, passed, rejects):
    """Observed protocol bytes, production metadata guards and persisted cache."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import urlopen
    release = {"tag_name": "v1.0.1", "draft": False, "prerelease": False,
        "html_url": "https://github.com/proofs-c/runtime/releases/tag/v1.0.1",
        "assets": [{"name": "runtime_1.0.1.zip", "size": 500, "digest": "sha256:" + "a" * 64,
            "browser_download_url": "https://github.com/proofs-c/runtime/releases/download/v1.0.1/runtime_1.0.1.zip"}]}
    metadata_path = root / "declared-release-metadata.json"
    metadata_path.write_text(json.dumps(release), encoding="utf-8")
    requests = []
    class MetadataHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = metadata_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48487)), MetadataHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(proof_text("http://127.0.0.1:48487/releases/latest"), timeout=3) as response:
            observed = json.loads(response.read(4096))
        row = manager._release_candidate("proof", configured, configured["update"], observed)
        first = manager._publish_discovery({"proof": row})
        second = manager.check_latest()
        require(first["summary"] == {"checked": 1, "current": 0, "updatesAvailable": 1, "errors": 0}
                and first["tools"]["proof"]["candidate"]["assetSha256"] == "a" * 64
                and first["activationPolicy"] == "signed-neyvia-release" and second["cache"] == "hit"
                and second["tools"] == first["tools"] and len(requests) == 1,
                "runtime.toolchain.discovery", "metadata binding or fresh disk cache failed")
        observed["assets"][0]["digest"] = None
        metadata_path.write_text(json.dumps(observed), encoding="utf-8")
        with urlopen(proof_text("http://127.0.0.1:48487/releases/latest"), timeout=3) as response:
            adverse = json.loads(response.read(4096))
        rejects("runtime.toolchain.discovery", lambda: manager._release_candidate("proof", configured, configured["update"], adverse), "no valid SHA-256 digest")
        failed = manager._publish_discovery({"proof": {"installedVersion": "1.0.0", "state": "check-failed",
            "updateAvailable": False, "error": "GitHub release asset has no valid SHA-256 digest"}})
        require(failed["summary"]["errors"] == 1 and failed["tools"]["proof"]["state"] == "check-failed", "runtime.toolchain.discovery", "failed discovery was hidden")
        for identity in ("runtime.toolchain.discovery", "runtime.toolchain.cache"):
            passed(identity, proof_text("loopback48487 metadata acquisition, production release parser, exact digest/official URL guards, refusal and persistent cache hit"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _mcp_self_check(root, passed, rejects):
    import sys
    from .mcp_broker import McpOutboundBroker, StubTransport, register_with_progressive_surface
    from .progressive_tools import ProgressiveToolSurface
    root.mkdir(parents=True, exist_ok=True)
    worker = root / "notes_mcp.py"
    worker.write_text('''import json,sys\nfrom pathlib import Path\npath=Path(sys.argv[1])\ndef read():\n headers={}\n while True:\n  line=sys.stdin.buffer.readline()\n  if not line:return None\n  if line in (b"\\r\\n",b"\\n"):break\n  key,value=line.decode().split(":",1);headers[key.lower()]=value.strip()\n return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))\ndef send(item):\n body=json.dumps(item).encode();sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode()+body);sys.stdout.buffer.flush()\ntools=[{"name":"read_note","description":"Read scratch note","inputSchema":{"type":"object"},"annotations":{"readOnlyHint":True}},{"name":"write_note","description":"Write scratch note","inputSchema":{"type":"object","properties":{"note":{"type":"string"}},"required":["note"]},"annotations":{"readOnlyHint":False}}]\nwhile True:\n msg=read()\n if msg is None:break\n if "id" not in msg:continue\n method=msg["method"]\n if method=="initialize":result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"proofs-c-notes","version":"1"}}\n elif method=="tools/list":result={"tools":tools}\n elif method=="tools/call":\n  params=msg["params"]\n  if params["name"]=="write_note":path.write_text(params["arguments"]["note"],encoding="utf-8")\n  result={"content":[],"isError":False,"structuredContent":{"note":path.read_text(encoding="utf-8") if path.exists() else ""}}\n else:result={}\n send({"jsonrpc":"2.0","id":msg["id"],"result":result})\n''', encoding="utf-8")
    note = root / "note.txt"
    note.write_text("initial", encoding="utf-8")
    broker = McpOutboundBroker(root, config={"servers": {
        "notes": {"transport": "stdio", "command": sys.executable, "args": ["-I", str(worker), str(note)], "authState": "authenticated"},
        "sse": {"transport": "sse", "url": "https://example.invalid/sse"}}}, include_default_demo=False)
    indexed = McpOutboundBroker(root / "indexed", config={"mcp_servers": {
        "filesystem": {"command": sys.executable, "env": {"PROOF_ONLY": "x"}}, "git": {"command": sys.executable}}}, include_default_demo=False)
    try:
        configured = {r["name"]: r for r in indexed.list_servers()}
        require(configured["filesystem"]["configured"] and configured["filesystem"]["hasEnvironment"]
                and configured["filesystem"]["transport"] == "stdio" and configured["filesystem"]["callable"]
                and "stdio_jsonrpc_mvp" in configured["filesystem"]["notes"],
                "runtime.mcp.discovery", "Codex command-index normalization lost stdio or environment")
    finally:
        indexed.close()
    try:
        compact = {r["name"]: r for r in broker.list_servers()}
        require(compact["notes"]["callable"] and not compact["sse"]["callable"], "runtime.mcp.discovery", "stdio/SSE availability changed")
        found = broker.search("note write", limit=10)
        require({r["name"] for r in found} == {"read_note", "write_note"}, "runtime.mcp.discovery", "real stdio catalog missing")
        described = broker.describe("notes", "read_note")
        require(described["inputSchema"] == {"type": "object"} and not described["requiresApproval"], "runtime.mcp.discovery", "described read schema/approval changed")
        receipt = broker.call("notes", "read_note", {}, mission_id="runtime-proof")
        require(receipt["ok"] and receipt["result"]["structuredContent"]["note"] == "initial", "runtime.mcp.receipt", "real stdio read did not return persisted note")
        blocked = broker.call("notes", "write_note", {"note": "blocked"})
        require(blocked["status"] == "approval_required" and note.read_text(encoding="utf-8") == "initial", "runtime.mcp.authorization", "unapproved remote mutation occurred")
        allowed = broker.call("notes", "write_note", {"note": "approved"}, approved=True, approval_id="proof-approved")
        require(allowed["ok"] and allowed["result"]["approvalId"] == "proof-approved" and note.read_text(encoding="utf-8") == "approved", "runtime.mcp.authorization", "approved real stdio mutation not durable")
        broker.set_auth_state("notes", "unauthenticated")
        locked = broker.call("notes", "read_note", {})
        require(locked["status"] == "auth_required" and not broker.list_servers()[0]["callable"], "runtime.mcp.authorization", "revoked authorization dispatched")
        broker.set_auth_state("notes", "authenticated")
        require(broker.call("notes", "read_note", {})["ok"], "runtime.mcp.authorization", "restored auth did not recover")
        surface = ProgressiveToolSurface()
        names = register_with_progressive_surface(surface, broker)
        require(set(names) == {"mcp.servers", "mcp.search", "mcp.describe", "mcp.call"}
                and all("inputSchema" not in r for r in surface.list_tools(include_schemas=False))
                and any(r["name"] == "mcp.call" for r in surface.search("mcp call broker", limit=10))
                and "inputSchema" in surface.describe("mcp.call"), "runtime.mcp.progressive", "progressive registration/discovery lost")
        response = surface.call("mcp.call", {"server": "notes", "tool": "read_note", "arguments": {}})
        require(response["ok"] and response["result"]["structuredContent"]["note"] == "approved", "runtime.mcp.progressive", "progressive call did not reach real broker")
        direct = StubTransport(tools=[{"name": "add", "inputSchema": {"type": "object"}}], handlers={"add": lambda a: {"sum": a["a"] + a["b"]}})
        require(direct.call_tool("add", {"a": 2, "b": 3})["structuredContent"]["sum"] == 5, "runtime.mcp.progressive", "explicit simulation custom handler lost")
        for identity in ("runtime.mcp.discovery", "runtime.mcp.authorization", "runtime.mcp.receipt", "runtime.mcp.progressive"):
            passed(identity, "real Content-Length stdio note observer/mutation, auth/approval refusal, progressive dispatch and closure")
        rejects("runtime.mcp.discovery", lambda: check_mcp_search([{ "inputSchema": {}}]), "Contract runtime.mcp.discovery")
    finally:
        broker.close()
    # Host entrypoint uses this same real stdio service through its normal saved config.
    from .mcp_broker import ENV_CONFIG
    from .neyvia_mcp import NeyviaMCPServer
    host_root = root / "host"
    host_config = host_root / ".agent_control" / "mcp_broker.json"
    host_config.parent.mkdir(parents=True, exist_ok=True)
    host_config.write_text(json.dumps({"servers": {"notes": {"transport": "stdio", "command": sys.executable,
        "args": ["-I", str(worker), str(note)], "authState": "authenticated"}}}), encoding="utf-8")
    previous_config = os.environ.get(ENV_CONFIG)
    os.environ[ENV_CONFIG] = str(host_config)
    host = None
    try:
        host = NeyviaMCPServer(_fixture_root(host_root))
        def request(name, arguments):
            response = host.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            require(response is not None and "result" in response, "runtime.mcp.host", "host returned no result")
            return response["result"]
        found = request("neyvia.tools.search", {"query": "mcp call outbound", "limit": 10})
        require({"mcp.call", "mcp.search"} <= {r["name"] for r in found["structuredContent"]["tools"]},
                "runtime.mcp.host", "host progressive tools missing")
        listed = host.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"includeSchemas": False}})
        rows = [r for r in listed["result"]["tools"] if r["name"].startswith("mcp.")]
        require(rows and all("inputSchema" not in r for r in rows), "runtime.mcp.host", "host schema deferral missing")
        blocked = request("mcp.call", {"server": "notes", "tool": "write_note", "arguments": {"note": "host-blocked"}})
        require(blocked["isError"] and blocked["structuredContent"]["status"] == "approval_required"
                and note.read_text(encoding="utf-8") == "approved", "runtime.mcp.host", "host unapproved mutation passed")
        read = request("mcp.call", {"name": "mcp.notes.read_note", "arguments": {}})
        require(not read["isError"] and read["structuredContent"]["ok"]
                and read["structuredContent"]["result"]["structuredContent"]["note"] == "approved",
                "runtime.mcp.host", "qualified host call did not reach real stdio service")
        passed("runtime.mcp.host", "Neyvia MCP JSON-RPC host search/list/blocked mutation/qualified read")
    finally:
        if host is not None:
            host.mcp_broker.close()
            if getattr(host.capability_os, "_model_tool_broker", None) is not None:
                host.capability_os._model_tool_broker.close()
        if previous_config is None:
            os.environ.pop(ENV_CONFIG, None)
        else:
            os.environ[ENV_CONFIG] = previous_config


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
