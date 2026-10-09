"""C7d owned desktop, runtime and installer adversarial observations.

These are local product calls and durable artifact observations. HTML generation,
provider coordination labels and release signing fixtures never attest rendering,
provider authentication, device execution or publication.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .edge_fixture_host_runtime import _check, _reject, _sharing, _environment

TEXT = {"empty": "", "huge": "owned material " * 4096, "unicode": "雪 café e\u0301 العربية"}
CATEGORIES = {"empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale"}
REPO = Path(__file__).resolve().parents[2]


def _script(name):
    spec = importlib.util.spec_from_file_location("c7d_" + name, REPO / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _interrupted_write(path, content):
    """A real owned child exits after flushing a prefix, before the record ends."""
    code = "import os,sys;from pathlib import Path;p=Path(sys.argv[1]);f=p.open('w',encoding='utf8');f.write(sys.argv[2]);f.flush();os.fsync(f.fileno());os._exit(23)"
    child = subprocess.run([sys.executable, "-c", code, str(path), content], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=20)
    _check(child.returncode == 23 and path.read_text(encoding="utf-8") == content, "owned interrupted writer did not establish exact durable prefix")


def _stop_at_marker(root, label, code, *arguments):
    """Stop an actual owner after its instrumented effect, before delivery."""
    marker = root / (label + "-stopped.json")
    child = subprocess.Popen([sys.executable, "-c", code, str(root), str(marker), *map(str, arguments)],
        env={**os.environ, "PYTHONPATH": str(REPO / "src")}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 20
        observed = None
        while time.monotonic() < deadline:
            try:
                observed = json.loads(marker.read_text(encoding="utf-8"))
                break
            except (FileNotFoundError, json.JSONDecodeError):
                if child.poll() is not None: break
                time.sleep(.02)
        if observed is None:
            if child.poll() is None: child.terminate()
            out, err = child.communicate(timeout=10)
            raise AssertionError(label + " owner did not reach its real effect: " + err.decode("utf8",errors="replace")[-1800:])
        child.terminate(); child.communicate(timeout=10)
        _check(child.returncode != 0, label + " owner returned normally before interruption")
        return {"pid": child.pid, "returnCode": child.returncode, "observed": observed}
    finally:
        if child.poll() is None: child.kill(); child.communicate(timeout=10)


def _pure(root, category):
    """Only explicit in-memory strings; no remote setup or saved credentials."""
    from .runtime_lane_cycle import normalize_lane_routes
    from .neyvia_remote import _url, RemoteError
    repair = _script("repair_nas_opencode_go_auth")
    users = _script("nas_setup")
    stack = _script("install_nas_runtime_stack")
    https = _script("setup_nas_https")
    text = TEXT.get(category, "owned export")
    other = "export OPENAI_API_KEY='fixture-other'\n# " + text.replace("\n", " ") + "\n"
    original = other + "OPENCODE_API_KEY=obsolete\nexport OPENCODE_API_KEY='old'\n"
    key = "owned'\\value" + text
    merged = repair.merge_provider_env(original, key)
    _check(other in merged and merged.count("OPENCODE_API_KEY=") == 1, "merge changed unrelated provider data")
    import shlex
    line = next(x for x in merged.splitlines() if x.startswith("export OPENCODE_API_KEY="))
    _check(shlex.split(line)[1].split("=", 1)[1] == key.strip(), "shell quoting changed normalized in-memory value")
    _reject(lambda: repair.merge_provider_env(other, " "))
    redacted = repair._redact("prefix " + key + " suffix " + text, key)
    _check(key not in redacted and len(redacted) <= 8000, "redactor retained supplied text or exceeded limit")
    _check(users.collect_add_users(["one", "one", "", "three"], "one,two") == ["one", "three", "two"], "username ordering/dedup changed")
    _check(users.collect_add_users([], "") == [], "empty users invented identities")
    hosts = https.split_hosts(["example.test", "example.test.", "127.0.0.1", "127.0.0.1", "::1"])
    _check(hosts == (["example.test"], ["127.0.0.1", "::1"]), "DNS/IP partition lost exact unique identities")
    for cpu, arch in (("x86_64", "x64"), ("aarch64", "arm64")):
        _check(stack.node_platform_arch(cpu) == arch and arch in stack.node_dist_url("22.1.0", arch), "planned archive architecture wrong")
    _reject(lambda: stack.node_platform_arch(text + "unsupported"), (SystemExit,))
    _reject(lambda: stack.node_dist_url("", "x64"), (SystemExit,))
    command = https.backend_start_command("/owned/root", "/owned/cert", "/owned/key", port=48741)
    _check("48741" in command and "/owned/cert" in command and "/owned/key" in command and "/owned/root" in command, "TLS command lost explicit inputs")
    routes = normalize_lane_routes([], default_runtime="open-code")
    _check([r["role"] for r in routes] == ["context-reader", "planner", "executor", "verifier"], "lane role order changed")
    _check(routes[0]["runtimeId"] == "neyvia-context" and all(r["runtimeId"] == "opencode" for r in routes[1:]), "runtime alias substituted owning route")
    with _environment({"NEYVIA_REMOTE_PROOF_LOOPBACK": "1", "NEYVIA_REMOTE_PROOF_PORTS": "48741"}):
        _check(_url("http://127.0.0.1:48741/") == "http://127.0.0.1:48741", "authorized numeric URL refused")
        for value in ["http://127.0.0.1:48742", "http://user:fixture@127.0.0.1:48741", "http://localhost:48741", "http://127.0.0.1:48741/" + text + "path", "http://127.0.0.1:48741/?q=" + text]:
            _reject(lambda value=value: _url(value), (RemoteError,))
    return {"inputCharacters": len(text), "mergeBytes": len(merged), "redactedCharacters": len(redacted), "routes": routes, "networkActivity": False}


def _bridge_refusal(root, category):
    from .desktop_bridge import dispatch_desktop_command, DesktopBridgeError
    text = TEXT[category]
    _reject(lambda: dispatch_desktop_command(root / "must-remain-absent", text + "unknown_command", {"text": text}), (DesktopBridgeError,))
    _check(not (root / "must-remain-absent").exists(), "allowlist rejection resolved/allocated root")
    return {"rejectedBeforeRootAllocation": True, "inputCharacters": len(text)}


def _impact(root, category):
    from . import neyvia_impact as owner
    text = TEXT.get(category, "owned")
    padding = "# " + text + "\n"
    a = root / "src/grant_agent/a.py"; a.parent.mkdir(parents=True)
    b = a.with_name("b.py")
    a.write_text(padding + "COMMANDS = {'owned_command'}\n", encoding="utf-8")
    b.write_text("COMMANDS = {'unrelated_command'}\n", encoding="utf-8")
    trees = {a: ast.parse(a.read_text(encoding="utf-8")), b: ast.parse(b.read_text(encoding="utf-8"))}
    code = "from grant_agent.a import COMMANDS as ALLOWED\ndef dispatch(command):\n if command in ALLOWED | {'other_command'}:\n  return True\n if command != 'false_command':\n  return False\n"
    tree = ast.parse(code)
    named = owner._imported_sets(tree, trees, root)
    _check(named == {"ALLOWED": {"owned_command"}}, "import merged unrelated registry")
    matches = owner._compares(tree, "command", named)
    _check(len(matches) == 1 and matches[0][2] == {"owned_command", "other_command"}, "dispatch mistaken inequality/display evidence")
    ui = "// callBackend('comment_command')\nconst label='display_command';\nconst COMMANDS: string[]=['owned_command'];\ncallBackend('other_command');\n" + "/* " + text + " */"
    _check(owner._ui_commands(ui) == {"owned_command", "other_command"}, "UI parser accepted display/comments or dropped typed registry")
    route = a.with_name("web_backend.py"); route.write_text(code, encoding="utf-8")
    web = root / "web/src/owned.js"; web.parent.mkdir(parents=True); web.write_text(ui, encoding="utf-8")
    if category == "permissions":
        with _sharing(web):
            _check(owner._read(web) == "", "denied UI source invented evidence")
    first = owner.index(root)
    _check("owned_command" in first["handled"], "index lost actual branch")
    if category == "stale":
        web.write_text("callBackend('new_command');\n", encoding="utf-8")
        actual = owner.index(root)
        _check("new_command" in actual["ui"] and "other_command" not in actual["ui"], "cached index retained stale UI evidence")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: owner.index(root), range(8)))
        _check(all(row == rows[0] for row in rows), "immutable source observations diverged")
    if category == "interrupted":
        _interrupted_write(web, "callBackend('owned_command');\ncallBackend('unfinished")
        current = owner.index(root)
        _check("owned_command" in current["ui"] and "unfinished" not in current["ui"], "partial UI source invented an unfinished command")
    return {"branchCommands": sorted(matches[0][2]), "uiCommands": sorted(owner._ui_commands(ui)), "indexedHandlers": len(first["handled"]), "renderedProof": False}


def _diagnostics(root, category):
    from .debugger_bundle import write_debugger_bundle, build_diagnostic_summary, _compact_text
    from .doc_ingestion import ingest_docs
    text = TEXT.get(category, "Owned evidence")
    source = root / "notes.txt"; source.write_text(text, encoding="utf-8")
    if category == "interrupted":
        text = text[:7]; _interrupted_write(source, text)
    docs = ["notes.txt", "missing.txt"] if category != "empty" else []
    if category == "permissions":
        with _sharing(source):
            records = ingest_docs(docs, root, root)
        _check(records[0].status == "error" and records[0].chars == 0, "denied document reported success")
        with _sharing(source):
            _reject(lambda: write_debugger_bundle(root=root, mission_id="denied", evidence_paths=["notes.txt"]), (PermissionError,))
        _check(not list((root / ".agent_control/mission_runs/denied").rglob("manifest.json")), "denied debugger source gained a successful manifest")
    else:
        records = ingest_docs(docs, root, root)
        _check(not docs or records[0].chars == len(text), "document count differs from observed text")
    _check(json.loads((root / "docs_evidence.json").read_text(encoding="utf-8")) == [asdict(r) for r in records], "durable ordered doc evidence differs")
    if category == "stale":
        source.write_text(text + " changed", encoding="utf-8")
        _check(ingest_docs(["notes.txt"], root, root)[0].chars == len(text) + 8, "document observation reused stale bytes")
    bundle = write_debugger_bundle(root=root, mission_id="owned", evidence_paths=[] if category == "empty" else ["notes.txt", "missing.txt"], registry_snapshot={"note": text})
    persisted = json.loads(Path(bundle["manifestPath"]).read_text(encoding="utf-8"))
    _check(persisted == {k: v for k, v in bundle.items() if k != "manifestPath"}, "debugger returned manifest differs from durable manifest")
    for item in bundle["copiedFiles"]:
        _check(Path(item["bundlePath"]).read_bytes() == Path(item["source"]).read_bytes(), "copied evidence differs")
    _check(bundle["nextAction"] and len(bundle["registrySnapshot"].get("note", "")) <= 300, "bundle lacked next action or exceeded compact text")
    old = {"status": "failed", "summary": "older", "phase": "planner"}
    new = {"status": "failed", "summary": text or "newer", "phase": "verifier", "nextAction": "inspect", "proofPaths": [str(source), str(source)]}
    result = build_diagnostic_summary(mission_id="owned", latest_receipts=[old, new])
    _check(result["whatFailed"] == _compact_text(new["summary"], 400) and result["whereFailed"] == "verifier" and len(result["proofPaths"]) == 1, "diagnostics did not choose newest concrete failure/dedup")
    empty = build_diagnostic_summary(mission_id="unknown")
    _check(empty["status"] == "insufficient_evidence" and not empty["proofPaths"], "absent evidence invented diagnostic")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            bundles = list(pool.map(lambda _: write_debugger_bundle(root=root, mission_id="owned", evidence_paths=["notes.txt"]), range(8)))
        _check(len({b["bundleId"] for b in bundles}) == 8 and all(Path(b["copiedFiles"][0]["bundlePath"]).read_bytes() == source.read_bytes() for b in bundles), "concurrent debugger bundles collided")
        with ThreadPoolExecutor(max_workers=4) as pool:
            observations = list(pool.map(lambda _: ingest_docs(["notes.txt"], root, root), range(8)))
        _check(all(r[0].chars == len(text) for r in observations) and json.loads((root / "docs_evidence.json").read_text(encoding="utf-8")) == [asdict(x) for x in observations[-1]], "concurrent document observations lost ordered durable evidence")
    return {"documentCount": len(records), "bundleManifest": bundle["manifestPath"], "copyCount": len(bundle["copiedFiles"]), "summaryStatus": result["status"]}


def _demo(root, category):
    from . import demo_runner as owner
    from .challenge_presets import ChallengePresetRegistry
    from .dashboard import load_proof_bundles, write_proof_dashboard
    text = TEXT.get(category, "owned export")
    preset = ChallengePresetRegistry(REPO / "config/challenge_presets.json").get("hackaprompt")
    before = owner.summarize_run("before", "fast", {"remaining_steps": [text], "verification_failures": [text]})
    after = owner.summarize_run("after", "careful", {"remaining_steps": []})
    comparison = owner.compare_training(before, after)
    _check(comparison["improved"] and comparison["score_delta"] > 0 and not owner.compare_training(after, before)["improved"], "comparison hid regression")
    probe = owner.run_adversarial_probe(preset, text)
    blocked = sum(x["outcome"] == "blocked" for x in probe["attempts"])
    _check(probe["attempt_count"] == len(probe["attempts"]) and probe["blocked_attempt_count"] == blocked and probe["resistance_score"] == round(blocked/max(1,len(probe["attempts"]))*100), "probe aggregates not derived from attempts")
    exported = owner.export_report_bundle(bundle_root=root / "bundles", preset=preset, navigator=after, before=before, after=after, comparison=comparison, probe=probe, findings=[text], export_zip=False)
    folder = Path(exported["bundle_path"])
    payload = json.loads((folder / "proof_payload.json").read_text(encoding="utf-8"))
    _check(payload["training_before"] == before and payload["training_after"] == after and payload["top_findings"] == [text], "export changed evidence")
    for actual, expected in zip(payload["probe"]["attempts"], probe["attempts"]):
        _check(actual["prompt_sha256"] == hashlib.sha256(expected["prompt"].encode()).hexdigest() and actual["prompt_length"] == len(expected["prompt"]), "redacted prompt lost source identity")
    corrupt = folder.parent / "bundle_corrupt"; corrupt.mkdir(); (corrupt / "proof_payload.json").write_text("{", encoding="utf-8")
    _check(len(load_proof_bundles(folder.parent)) == 1, "dashboard counted corrupt bundle")
    dashboard = write_proof_dashboard(folder.parent, root / "dashboard.html")
    html = dashboard.read_text(encoding="utf-8")
    _check("<html" in html.lower() and "href=" in html and "hackaprompt" in html, "generated dashboard missing parsed navigation/evidence")
    if category == "permissions":
        with _sharing(folder / "proof_payload.json"):
            _check(load_proof_bundles(folder.parent) == [], "denied bundle payload invented dashboard evidence")
        with _sharing(dashboard):
            _reject(lambda: write_proof_dashboard(folder.parent, dashboard), (PermissionError,))
    if category == "interrupted":
        _interrupted_write(corrupt / "proof_payload.json", '{"preset":')
        _check(len(load_proof_bundles(folder.parent)) == 1, "interrupted export gained dashboard evidence")
    if category == "stale":
        payload["top_findings"] = ["owned replacement"]
        (folder / "proof_payload.json").write_text(json.dumps(payload), encoding="utf-8")
        _check(load_proof_bundles(folder.parent)[0]["top_findings"] == ["owned replacement"], "dashboard reused stale proof payload")
    if category == "concurrency":
        def export(_):
            return owner.export_report_bundle(bundle_root=root / "parallel-bundles", preset=preset, navigator=after, before=before, after=after, comparison=comparison, probe=probe, findings=[text], export_zip=False)
        with ThreadPoolExecutor(max_workers=4) as pool: reports = list(pool.map(export, range(8)))
        _check(len({r["bundle_path"] for r in reports}) == 8 and len(load_proof_bundles(root / "parallel-bundles")) == 8, "concurrent export identity collided")
        with ThreadPoolExecutor(max_workers=4) as pool:
            dashboards = list(pool.map(lambda i: write_proof_dashboard(root / "parallel-bundles", root / f"dashboard-{i}.html"), range(8)))
        _check(all("hackaprompt" in p.read_text(encoding="utf-8") for p in dashboards), "concurrent dashboard lost exported evidence")
    return {"dashboardPath": str(dashboard), "bundlePath": str(folder), "attempts": len(probe["attempts"]), "blocked": blocked, "renderedProof": False, "liveModelProof": False}


def _auth_queue(root, category):
    from .provider_auth_queue import ProviderAuthQueue, AUTH_QUEUE_SCHEMA
    text = TEXT.get(category, "owned metadata")
    root.mkdir(parents=True, exist_ok=True)
    presence = {"openai-codex": False, "minimax-portal": False, "anthropic": False}
    factory = lambda: ProviderAuthQueue(root, presence=lambda ids: {p: presence.get(p, False) for p in ids})
    q = factory()
    _reject(lambda: q.start(["unsupported" + text]), (ValueError,))
    state = q.start(["openai-codex", "minimax-portal"] * (1024 if category == "huge" else 1))
    _check(len(state["items"]) == 2 and state["activeProviderId"] == "openai-codex", "ordered unique queue admission changed")
    claim = getattr(state, "_flow_start_claim_id", "")
    _check(claim and all("flowStartClaim" not in item for item in state["items"]) and state["secretMaterialStored"] is False, "startup claim leaked or secret policy lost")
    observer = factory()
    _check(observer.status(refresh_presence=False)["nextAction"] is None and observer._lock is q._lock, "independent observer repeated reserved startup")
    session = "owned-session" + text
    q.record_flow("openai-codex", {"sessionId": session, "status": "waiting", "relayToken": "private-in-memory", "helperSecret": "private-in-memory"}, startup_claim_id=claim)
    before = q.path.read_bytes()
    _check(b"private-in-memory" not in before, "private flow fields persisted")
    observer.record_flow("openai-codex", {"status": "not_found"})
    _check(q.path.read_bytes() == before, "sessionless observation erased owning flow")
    _reject(lambda: observer.record_flow("openai-codex", {"sessionId": "different-session"}), (RuntimeError,))
    _check(q.path.read_bytes() == before and json.loads(before)["items"][0]["flow"]["sessionId"] == session, "refusal changed owner bytes")
    q.mark_connected("openai-codex")
    nxt = observer.status(refresh_presence=False)
    next_claim = getattr(nxt, "_flow_start_claim_id", "")
    _check(next_claim and nxt["activeProviderId"] == "minimax-portal", "completed flow did not advance to an exclusive consumer")
    observer.release_flow_start_claim("minimax-portal", next_claim)
    successor = q.status(refresh_presence=False)
    successor_claim = getattr(successor, "_flow_start_claim_id", "")
    _check(successor_claim and successor_claim != next_claim, "released startup was not reissued")
    _reject(lambda: observer.record_flow("minimax-portal", {"sessionId": "stale"}, startup_claim_id=next_claim), (RuntimeError,))
    q.record_flow("minimax-portal", {"sessionId": "successor"}, startup_claim_id=successor_claim)
    q.cancel(); q.mark_connected("minimax-portal")
    durable = json.loads(q.path.read_text(encoding="utf-8"))
    _check(durable["status"] == "cancelled" and q.status(refresh_presence=False)["items"][1]["state"] == "cancelled", "late callback resurrected terminal queue")
    if category == "concurrency":
        race = root / "race"; race.mkdir()
        import threading
        barrier = threading.Barrier(2)
        def contend(_):
            obj = ProviderAuthQueue(race, presence=lambda ids: dict.fromkeys(ids, False)); barrier.wait()
            try:
                return obj.start(["openai-codex"])["queueId"]
            except RuntimeError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contend, range(2)))
        _check(sum(bool(x) for x in results) == 1, "two concurrent callers replaced one startup owner")
    if category == "permissions":
        with _sharing(q.path):
            _reject(lambda: q.status(refresh_presence=False), (PermissionError, OSError, RuntimeError))
        _check(q.path.read_bytes() == json.dumps(durable, indent=2, ensure_ascii=False).encode() or json.loads(q.path.read_text(encoding="utf-8")) == durable, "denied queue read changed durable state")
    if category == "stale":
        invalid = copy.deepcopy(durable); invalid["schema"] = AUTH_QUEUE_SCHEMA + ".future"
        q.path.write_text(json.dumps(invalid), encoding="utf-8")
        before_invalid = q.path.read_bytes()
        _reject(lambda: q.status(refresh_presence=False), (ValueError, RuntimeError))
        _reject(lambda: q.start(["anthropic"]), (ValueError, RuntimeError))
        _check(q.path.read_bytes() == before_invalid, "future state overwritten")
    if category == "interrupted":
        _interrupted_write(q.path, '{"schema":')
        before_invalid = q.path.read_bytes()
        _reject(lambda: factory().status(refresh_presence=False), (ValueError, RuntimeError))
        _check(q.path.read_bytes() == before_invalid, "interrupted durable queue state was replaced")
    official_root = root / "official"; official_root.mkdir()
    official = ProviderAuthQueue(official_root, presence=lambda ids: dict.fromkeys(ids, False)).start(["anthropic"])
    _check(official["nextAction"]["manualRequired"] and official["items"][0]["credentialPolicy"] == "official-only", "Anthropic public projection substituted a proxy")
    return {"queueId": durable["queueId"], "flowCharacters": len(session), "finalState": durable["status"], "startupOwnershipObserved": True, "liveAuthenticationProof": False}


def _circuit(root, category):
    from .cluster import ClusterRegistry, classify_provider_result
    from .worker import run_local_worker_once, build_worker_doctor
    text = TEXT.get(category, "owned")
    r = ClusterRegistry(root, use_configured_root=False)
    host = {"hostId": "C7D-PC", "hostType": "workstation", "role": "worker", "runtimes": ["hermes"], "capabilities": ["runtime.launch"], "workspaceMappings": {"workspace": str(root)}, "maxConcurrentJobs": 4, "currentLoad": 0, "workspaceRoot": str(root)}
    def job(name):
        return r.upsert_job(job_id=name, mission_id="c7d", workspace_id="workspace", runtime_id="hermes", target_provider="OpenAI-Codex", target_model="owned", preferred_host="C7D-PC", required_capabilities=["runtime.launch"], payload={"text": text})
    j = job("source")
    auth = {"status": "failed", "returnCode": 1, "stderr": "HTTP 401 unauthorized " + text}
    classified = classify_provider_result(j, auth)
    _check(classified["kind"] == "auth" and "雪" not in json.dumps(classified), "classification retained output rather than bounded categories")
    success = classify_provider_result(j, {"status": "completed", "returnCode": 0, "stderr": "401 unauthorized " + text})
    _check(success["kind"] == "success", "explicit process success overridden by authentication words")
    opened = r.record_provider_result(job=j, lease_id="", host_id="C7D-PC", result=auth)["circuit"]
    job("waiting"); _check(not r.claim_next_job(host)["job"], "open route admitted work")
    _check(not r._create_lease("waiting", "C7D-PC", lease_ttl_seconds=60), "direct lease bypassed circuit gate")
    reset = r.reset_provider_circuit(host_id="C7D-PC", runtime_id="hermes", provider="OpenAI-Codex", actor="token=in-memory-private", reason="password=in-memory-private")
    _check("in-memory-private" not in json.dumps(reset), "circuit reset retained private assignment")
    job("second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        trials = list(pool.map(lambda _: r.claim_next_job(host), range(2)))
    admitted = [x for x in trials if x.get("job")]
    _check(len(admitted) == 1, "half-open route reserved more than one canary")
    trial = admitted[0]
    wrong = r.record_provider_result(job=trial["job"], lease_id=trial["lease"]["leaseId"], host_id="another-PC", result=auth)
    _check(wrong.get("error") == "provider_result_lease_mismatch", "wrong host reported live lease")
    closed = r.record_provider_result(job=trial["job"], lease_id=trial["lease"]["leaseId"], host_id="C7D-PC", result={"status": "completed", "returnCode": 0})
    _check(closed["circuit"]["state"] == "closed", "owned successful canary did not close")
    r.complete_job(job_id=trial["job"]["jobId"], lease_id=trial["lease"]["leaseId"], host_id="C7D-PC", status="completed")
    late = r.record_provider_result(job=trial["job"], lease_id=trial["lease"]["leaseId"], host_id="C7D-PC", result=auth)
    _check(late.get("error") == "provider_result_lease_mismatch", "completed lease accepted a stale provider result")
    _check(ClusterRegistry(root, use_configured_root=False).list_provider_circuits() == r.list_provider_circuits(), "circuit state did not survive fresh registry")
    if category == "permissions":
        import sqlite3
        before_circuits = r.list_provider_circuits()
        with _sharing(r.db_path):
            for action in (lambda: r.claim_next_job(host), lambda: r._create_lease("waiting", "C7D-PC", lease_ttl_seconds=60),
                           lambda: r.record_provider_result(job=j, lease_id="", host_id="C7D-PC", result=auth),
                           lambda: r.reset_provider_circuit(host_id="C7D-PC",runtime_id="hermes",provider="OpenAI-Codex",actor="owned",reason="denied")):
                _reject(action, (sqlite3.Error, OSError, RuntimeError))
        _check(r.list_provider_circuits() == before_circuits, "denied circuit mutation changed durable route state")
    if category == "interrupted":
        marker = root / "circuit-transaction.json"
        code = """from pathlib import Path
import sys,threading
from contextlib import contextmanager
from grant_agent.cluster import ClusterRegistry
r=ClusterRegistry(Path(sys.argv[1]),use_configured_root=False);original=r._connect
@contextmanager
def stopped_commit():
 with original() as db:
  yield db
  Path(sys.argv[2]).write_text('actual reset mutation before commit')
  threading.Event().wait(60)
r._connect=stopped_commit
r.reset_provider_circuit(host_id='C7D-PC',runtime_id='hermes',provider='OpenAI-Codex',actor='owned',reason='interrupted')
"""
        child = subprocess.Popen([sys.executable,"-c",code,str(root),str(marker)],env={**os.environ,"PYTHONPATH":str(REPO / "src")},stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            deadline = time.monotonic()+15
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline: time.sleep(.02)
            _check(marker.exists(), "circuit child did not reach real uncommitted transaction")
            child.terminate(); child.communicate(timeout=10)
            _check(ClusterRegistry(root,use_configured_root=False).list_provider_circuits() == r.list_provider_circuits() and r.list_provider_circuits()[0]["state"] == "closed", "stopped circuit writer admitted an uncommitted route mutation")
        finally:
            if child.poll() is None: child.kill();child.communicate(timeout=10)
    worker_root = root / "worker"; worker_root.mkdir()
    with _environment({"FLUXIO_CLUSTER_ROOT": str(worker_root), "FLUXIO_CONTROL_PROJECT_ROOT": str(worker_root), "FLUXIO_HOST_ID": "C7D-PC", "FLUXIO_WORKSPACE_MAPPINGS": ""}):
        wr = ClusterRegistry(worker_root, use_configured_root=False)
        worker_host = {**host, "workspaceRoot": str(worker_root), "workspaceMappings": {"workspace": str(worker_root)}}
        work = wr.upsert_job(job_id="owned-child", mission_id="c7d", workspace_id="workspace", runtime_id="hermes", target_provider="OpenAI-Codex", preferred_host="C7D-PC", required_capabilities=["runtime.launch"], payload={"command": [sys.executable, "-c", "print('HTTP 401 unauthorized: C7d local child');raise SystemExit(1)"], "workspacePath": str(worker_root)})
        environment = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"), "PATH": str(Path(sys.executable).parent), "TEMP": str(worker_root), "TMP": str(worker_root)}
        if category == "permissions":
            import sqlite3
            with _sharing(wr.db_path):
                _reject(lambda: run_local_worker_once(worker_root,host_id="C7D-PC",observed_capabilities=worker_host,process_environment=environment), (sqlite3.Error,OSError,RuntimeError))
            _check(wr.get_job(work["jobId"])["status"] == "queued", "denied worker database admitted job execution")
        observed = run_local_worker_once(worker_root, host_id="C7D-PC", observed_capabilities=worker_host, process_environment=environment)
        _check(observed["claimed"] and wr.get_job(work["jobId"])["status"] == "failed" and wr.list_provider_circuits()[0]["state"] == "open", "real failed child omitted circuit before completion")
        doctor = build_worker_doctor(worker_root, host_id="C7D-PC", observed_capabilities=worker_host)
        _check(doctor["status"] == "warn" and doctor["circuitIssues"], "doctor omitted durable provider circuit")
    return {"initialState": opened["state"], "successfulCanaryState": closed["circuit"]["state"], "admittedCanaries": len(admitted), "realChildStatus": "failed", "liveProviderProof": False}


def _wrapper(root, category):
    from . import runtime_wrapper as owner
    from .replay import build_lineage_timeline
    from datetime import datetime, timezone
    text = TEXT.get(category, "observed")
    stdout, stderr, events = root / "out.txt", root / "err.txt", root / "events.jsonl"
    stdout.write_text(text + "tail", encoding="utf-8"); stderr.write_text("warning", encoding="utf-8")
    if category == "interrupted": _interrupted_write(stdout, text[:4])
    if category == "stale": stdout.write_text(text + " replacement", encoding="utf-8")
    spec = owner.build_runtime_wrapper_spec(runtime_id="codex", command=[sys.executable, "-c", "print('owned')"], cwd=root, environment={"OWNED_TOKEN": "in-memory-value"}, stdout_tail_path=str(stdout), stderr_tail_path=str(stderr), event_stream_path=str(events), timeout_seconds=120)
    _check("in-memory-value" not in json.dumps(owner.runtime_wrapper_payload(spec)), "spec leaked environment value")
    _reject(lambda: owner.build_runtime_wrapper_spec(runtime_id="unknown", command=["x"], cwd=root), (ValueError,))
    if category == "permissions":
        with _sharing(stdout):
            state = owner.build_runtime_wrapper_state(spec, tail_bytes=16)
        _check(not state.stdout_tail, "denied tail was invented")
    else:
        state = owner.build_runtime_wrapper_state(spec, env_status={"OWNED_TOKEN": "present_masked"}, process_tree=[{"pid": os.getpid()}], heartbeat_at=datetime.now(timezone.utc).isoformat(), tail_bytes=16)
        _check(state.stdout_tail == stdout.read_bytes()[-16:].decode("utf-8", errors="replace"), "bounded real tail differs")
    event = owner.build_runtime_wrapper_phase_event(spec, mission_id="owned", mission_run_id="owned-run", phase="executor", status="completed", message=text)
    _check(event["message"] == text and event["phase"] == "executor", "phase projection lost association")
    receipt = owner.build_runtime_wrapper_execution_receipt(spec, state, receipt_id="owned", mission_id="owned", mission_run_id="owned-run", host="C7D-PC", workspace=str(root), status="completed", summary=text, changed_files=["out.txt"])
    receipt_path = root / "receipt.json"; receipt_path.write_text(json.dumps(asdict(receipt)), encoding="utf-8")
    events.write_text(json.dumps({**event, "status": "running"}) + "\n{broken}\n" + json.dumps(event) + "\n[]\n", encoding="utf-8")
    if category == "interrupted":
        _interrupted_write(events, events.read_text(encoding="utf-8") + '{"status":')
    replay = owner.replay_runtime_wrapper(event_stream_path=events, receipt_paths=[receipt_path, root / "missing.json"])
    _check(replay["eventCount"] == 2 and replay["receiptCount"] == 1 and replay["latestStatus"] == "completed", "replay invented malformed rows or lost valid rows")
    if category == "permissions":
        with _sharing(events):
            _reject(lambda: owner.replay_runtime_wrapper(event_stream_path=events, receipt_paths=[receipt_path]), (PermissionError,))
    if category == "stale":
        with events.open("a", encoding="utf-8") as stream: stream.write(json.dumps({**event, "status": "failed"}) + "\n")
        _check(owner.replay_runtime_wrapper(event_stream_path=events)["latestStatus"] == "failed", "replay retained stale latest status")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            projections = list(pool.map(lambda _: owner.replay_runtime_wrapper(event_stream_path=events, receipt_paths=[receipt_path]), range(8)))
        _check(all(r == projections[0] for r in projections), "independent immutable replay readers diverged")
        with ThreadPoolExecutor(max_workers=4) as pool:
            states = list(pool.map(lambda _: owner.build_runtime_wrapper_state(spec, tail_bytes=16), range(8)))
        _check(all(s.stdout_tail == stdout.read_bytes()[-16:].decode("utf8",errors="replace") for s in states), "concurrent wrapper state lost observed tail bytes")
    for name in ("one", "two"):
        folder = root / name; folder.mkdir(); (folder / "timeline.jsonl").write_text(json.dumps({"message": text, "kind": name}) + "\n{broken}\n[]\n", encoding="utf-8")
    timeline = build_lineage_timeline(root, ["one", "missing", "two"])
    _check([r["session_id"] for r in timeline] == ["one", "two"] and all(r["message"] == text for r in timeline), "lineage lost source order/session provenance")
    timeline_path = root / "one/timeline.jsonl"
    if category == "interrupted":
        _interrupted_write(timeline_path, timeline_path.read_text(encoding="utf-8") + '{"kind":')
        _check(build_lineage_timeline(root, ["one","two"]) == timeline, "interrupted JSONL prefix invented lineage")
    if category == "permissions":
        with _sharing(timeline_path): _reject(lambda: build_lineage_timeline(root,["one","two"]), (PermissionError,))
    if category == "stale":
        with timeline_path.open("a") as stream: stream.write(json.dumps({"message":"replacement"})+"\n")
        fresh = build_lineage_timeline(root,["one","two"])
        _check(len(fresh) == 3 and fresh[1]["message"] == "replacement", "lineage reused stale source rows")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            timelines = list(pool.map(lambda _: build_lineage_timeline(root,["one","two"]), range(8)))
        _check(all(r == timeline for r in timelines), "concurrent source lineage readers diverged")
    return {"eventCount": replay["eventCount"], "receiptCount": replay["receiptCount"], "lineageSessions": [r["session_id"] for r in timeline], "tailBytes": len(state.stdout_tail.encode())}


def _onboarding_catalog(root, category):
    from . import neyvia_onboarding as owner
    text = TEXT.get(category, "owned choices")
    catalog = owner.load_catalog()
    apps = set(owner._known_apps()); packs = set(owner._known_packs())
    _check(all(set(r.get("apps", [])) <= apps and set(r.get("packs", [])) <= packs for r in catalog["interests"]), "catalog references unregistered choices")
    chosen = [r["id"] for r in catalog["interests"]] if category == "huge" else ([] if category == "empty" else [catalog["interests"][0]["id"]])
    recommendation = owner.recommend(catalog, chosen + chosen)
    expected = []
    for interest in catalog["interests"]:
        if interest["id"] in chosen:
            for app in interest.get("apps", []):
                if app not in expected: expected.append(app)
    _check(recommendation["apps"] == expected and 60 <= recommendation["tourSeconds"] <= 90, "recommendation order/tour bounds differ from catalog union")
    _reject(lambda: owner.recommend(catalog, ["unsupported" + text]), (ValueError,))
    _check(owner.read_state(root)["firstRun"], "fresh choice state did not disclose first run")
    path = owner._dir(root) / "state.json"
    _reject(lambda: owner.save_state(root, {"interests": ["unsupported" + text]}), (ValueError,))
    _check(not path.exists(), "refused choices allocated durable choice state")
    saved = owner.save_state(root, {"interests": chosen + chosen, "apps": expected, "completed": True})
    actual = owner.read_state(root)
    _check(actual == saved and not actual["firstRun"] and actual["completed"] and actual["interests"] == chosen, "normalized choices did not survive real reread")
    before = path.read_bytes()
    _reject(lambda: owner.save_state(root, {"apps": ["unsupported" + text]}), (ValueError,))
    _check(path.read_bytes() == before, "refused choice overwrote prior state")
    if category == "permissions":
        with _sharing(path):
            _reject(lambda: owner.save_state(root, {"interests": chosen, "completed": True}), (PermissionError,))
        _check(path.read_bytes() == before, "denied choices replaced durable state")
    if category == "interrupted":
        _interrupted_write(path, '{"interests":')
        _check(owner.read_state(root)["firstRun"], "interrupted choices invented valid completed state")
        repaired = owner.save_state(root, {"interests": chosen, "completed": True})
        _check(owner.read_state(root) == repaired, "explicit retry after interrupted choices lost durable identity")
    if category == "stale":
        replacement = owner.save_state(root, {"interests": [], "completed": False})
        _check(owner.read_state(root) == replacement and not replacement["completed"] and not replacement["interests"], "fresh choice read reused replaced selections")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            saved_rows = list(pool.map(lambda _: owner.save_state(root, {"interests": chosen, "completed": True}), range(8)))
        actual = owner.read_state(root)
        _check(actual in saved_rows and actual["interests"] == chosen and actual["completed"], "parallel choice writers lost admitted state")
        owner.save_state(root, {"completed": False, "dismissed": False, "tier": "", "tour": {"seen": False}})
        patches = [{"completed": True}, {"dismissed": True}, {"tier": "beginner"}, {"tour": {"seen": True}}]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda patch: owner.save_state(root, patch), patches))
        actual = owner.read_state(root)
        _check(actual["completed"] and actual["dismissed"] and actual["tier"] == "beginner" and actual["tour"]["seen"],
               "parallel disjoint onboarding patches lost a completed choice")
    return {"interests": len(chosen), "registeredApps": len(apps), "registeredPacks": len(packs), "recommendationApps": expected, "durableFirstRun": actual["firstRun"]}


def _manifest(root, category):
    from . import neyvia_onboarding as owner
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    text = TEXT.get(category, "owned signature")
    body = text.encode(); source = root / "payload.txt"; source.write_bytes(body)
    data = {"schema": owner.MANIFEST_SCHEMA, "packId": "base", "version": "1", "description": text, "channel": "stable", "baseUrl": root.as_uri() + "/", "files": [{"path": "payload.txt", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}]}
    parsed = owner.parse_manifest(json.dumps(data, ensure_ascii=False), str(root / "manifest.json"))
    _check(parsed["totalSize"] == len(body) and parsed["files"][0]["url"] == source.as_uri(), "local manifest changed declared bytes/source")
    for bad_path in ("../escape", "/absolute", "C:/escape", "a/./b", "payload.part"):
        changed = copy.deepcopy(data); changed["files"][0]["path"] = bad_path
        _reject(lambda changed=changed: owner.parse_manifest(json.dumps(changed), str(root / "manifest.json")), (ValueError,))
    for size in (True, -1, "1"):
        changed = copy.deepcopy(data); changed["files"][0]["size"] = size
        _reject(lambda changed=changed: owner.parse_manifest(json.dumps(changed), str(root / "manifest.json")), (ValueError,))
    remote = {**data, "baseUrl": "https://fixture.invalid/"}
    _reject(lambda: owner.parse_manifest(json.dumps(remote), "https://fixture.invalid/manifest.json"), (ValueError,))
    private = Ed25519PrivateKey.generate(); public = private.public_key().public_bytes_raw()
    signature = private.sign(owner._canonical_manifest(remote))
    signed = {**remote, "signature": {"keyId": "c7d-public", "ed25519": base64.b64encode(signature).decode()}}
    policy = root / "public-trust.json"
    key = {"provisioned": True, "publicKeyBase64": base64.b64encode(public).decode(), "fingerprintSha256": hashlib.sha256(public).hexdigest()}
    policy.write_text(json.dumps({"signing": {"trustedKeys": {"c7d-public": key}}}), encoding="utf-8")
    admitted = owner.parse_manifest(json.dumps(signed, ensure_ascii=False), "https://fixture.invalid/manifest.json", trusted_policy=policy)
    _check(admitted["totalSize"] == len(body), "canonical signed Unicode admission changed content")
    if category == "permissions":
        with _sharing(policy):
            _reject(lambda: owner.parse_manifest(json.dumps(signed), "https://fixture.invalid/manifest.json", trusted_policy=policy), (ValueError, PermissionError))
    if category == "interrupted":
        _interrupted_write(policy, '{"signing":')
        _reject(lambda: owner.parse_manifest(json.dumps(signed), "https://fixture.invalid/manifest.json", trusted_policy=policy), (ValueError,))
        policy.write_text(json.dumps({"signing": {"trustedKeys": {"c7d-public": key}}}), encoding="utf-8")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: owner.parse_manifest(json.dumps(signed), "https://fixture.invalid/manifest.json", trusted_policy=policy), range(8)))
        _check(all(row == admitted for row in rows), "independent signed manifest observers diverged")
    _reject(lambda: owner.parse_manifest(json.dumps({**signed, "version": "changed"}), "https://fixture.invalid/manifest.json", trusted_policy=policy), (ValueError,))
    policy.write_text(json.dumps({"signing": {"trustedKeys": {"c7d-public": {**key, "provisioned": False}}}}), encoding="utf-8")
    _reject(lambda: owner.parse_manifest(json.dumps(signed), "https://fixture.invalid/manifest.json", trusted_policy=policy), (ValueError,))
    return {"manifestBytes": len(json.dumps(data).encode()), "payloadBytes": len(body), "signedCanonicalUnicode": True, "privateKeyPersisted": False, "networkActivity": False}


def _staging(root, category):
    from . import neyvia_onboarding as owner
    text = TEXT.get(category, "owned staging bytes")
    body = text.encode() if category == "empty" else (text.encode() or b"owned") + b"tail"
    source_dir = root / "source"; source_dir.mkdir(); source = source_dir / "payload.bin"; source.write_bytes(body)
    manifest = owner.parse_manifest(json.dumps({"schema": owner.MANIFEST_SCHEMA, "packId": "base", "version": "1", "channel": "test", "baseUrl": source_dir.as_uri() + "/", "files": [{"path": "payload.bin", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}]}), str(source_dir / "manifest.json"))
    stage = root / "stage"; stage.mkdir()
    target = owner._pack_dir(stage) / "base/1/payload.bin"
    partial = target.with_name(target.name + ".part"); partial.parent.mkdir(parents=True)
    prefix = len(body)//2
    partial.write_bytes(body[:prefix])
    if category == "permissions":
        with _sharing(source):
            failed = owner.run_download(stage, manifest)
        _check(failed["state"] == "failed" and not target.exists(), "denied payload staging invented complete bytes")
    if category == "interrupted":
        plan_path = root / "interrupted-download.json"; plan_path.write_text(json.dumps(manifest), encoding="utf-8")
        marker = root / "download-progress.json"
        code = """import json,sys,threading,os
from pathlib import Path
from grant_agent import neyvia_onboarding as owner
root=Path(sys.argv[1]); plan=Path(sys.argv[2]); marker=Path(sys.argv[3]); original=owner._fetch
def observed(url,partial,have,size,progress,throttle,sleep):
 def durable(count):
  progress(count)
  with partial.open('r+b') as stream:os.fsync(stream.fileno())
  marker.write_text(json.dumps({'path':str(partial),'bytes':partial.stat().st_size}),encoding='utf8')
  threading.Event().wait(60)
 return original(url,partial,have,size,durable,throttle,sleep)
owner._fetch=observed
owner.run_download(root,json.loads(plan.read_text()))
"""
        child = subprocess.Popen([sys.executable, "-c", code, str(stage), str(plan_path), str(marker)], env={**os.environ,"PYTHONPATH":str(REPO / "src")}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        try:
            deadline = time.monotonic()+15
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline: time.sleep(.02)
            _check(marker.exists() and not target.exists(), "actual downloader did not retain uncommitted progress before interruption")
            prefix = partial.stat().st_size
            _check(partial.read_bytes() == body[:prefix], "interrupted downloader prefix differs from actual source bytes")
            child.terminate(); child.communicate(timeout=10)
            _check(child.returncode != 0, "owned downloader did not stop before admission")
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=10)
    if category in {"huge", "unicode", "empty"}:
        signal = owner._pack_dir(stage) / "pause"; signal.write_text("pause", encoding="utf-8")
        paused = owner.run_download(stage, manifest)
        if body:
            _check(paused["state"] == "paused" and partial.exists() and not target.exists() and not signal.exists(), "pause did not retain resumable progress boundary")
        else:
            _check(paused["state"] == "done", "zero-byte staging invented a stream progress boundary")
    result = owner.run_download(stage, manifest)
    _check(result["state"] == "done" and target.read_bytes() == body and result["doneBytes"] == len(body), "staging failed exact byte/hash completion")
    if category == "interrupted":
        _check(result["resumedBytes"] == prefix, "stopped lease holder did not recover exact retained source prefix")
    _check(json.loads((owner._pack_dir(stage) / "status.json").read_text(encoding="utf-8")) == result, "reported staging status differs from durable status")
    if category == "concurrency":
        race = root / "concurrent-stage"; race.mkdir()
        owner._pack_dir(race).mkdir(parents=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            attempts = list(pool.map(lambda _: owner.run_download(race, manifest), range(8)))
        race_target = owner._pack_dir(race) / "base/1/payload.bin"
        _check(all(row["state"] == "done" for row in attempts) and race_target.read_bytes() == body, "concurrent downloader returned failures or unverified bytes: " + repr([(r["state"],r.get("error")) for r in attempts]))
        paused_root = root / "concurrent-pause"; paused_root.mkdir(); pause_dir = owner._pack_dir(paused_root); pause_dir.mkdir(parents=True); (pause_dir / "pause").write_text("pause")
        paused = owner.run_download(paused_root, manifest)
        _check(paused["state"] == "paused", "concurrent download observation ignored pause boundary")
        with ThreadPoolExecutor(max_workers=4) as pool:
            resumed = list(pool.map(lambda _: owner.run_download(paused_root, manifest), range(4)))
        _check(all(row["state"] == "done" for row in resumed), "concurrent resume lost retained progress")
    before = target.stat().st_mtime_ns
    reused = owner.run_download(stage, manifest)
    _check(reused["state"] == "done" and target.stat().st_mtime_ns == before, "verified reuse copied bytes again")
    if category == "stale":
        target.write_bytes(b"tampered")
        fixed = owner.run_download(stage, manifest)
        _check(fixed["state"] == "done" and target.read_bytes() == body, "stale verified index masked corrupted actual bytes")
    broken = copy.deepcopy(manifest); broken["files"][0]["sha256"] = "0" * 64
    bad_stage = root / "bad"; bad_stage.mkdir()
    bad = owner.run_download(bad_stage, broken)
    bad_target = owner._pack_dir(bad_stage) / "base/1/payload.bin"
    _check(bad["state"] == "failed" and not bad_target.exists() and not bad_target.with_name("payload.bin.part").exists(), "corrupt source admitted bytes or retained corrupt partial")
    return {"target": str(target), "sourceBytes": len(body), "resumedPrefix": prefix, "doneBytes": result["doneBytes"], "reusedWithoutWriting": True, "stagedOnly": True}


def _addon(root, category):
    from . import neyvia_onboarding as owner
    text = TEXT.get(category, "owned addon")
    source_dir = root / "sources"; source_dir.mkdir(); source = source_dir / "payload.txt"; source.write_text(text, encoding="utf-8")
    body = source.read_bytes(); identity = "pack.ocr-local"
    data = {"schema": owner.MANIFEST_SCHEMA, "packId": identity, "version": "1", "channel": "test", "baseUrl": source_dir.as_uri() + "/", "files": [{"path": "payload.txt", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}]}
    manifest_path = source_dir / "manifest.json"
    if category == "interrupted": _interrupted_write(manifest_path, '{"schema":')
    else: manifest_path.write_text("{", encoding="utf-8")
    with _environment({"NEYVIA_ONBOARDING_PACK_MANIFESTS": json.dumps({identity: str(manifest_path)})}):
        _reject(lambda: owner.install_pack(root, "../../escape", spawn=False), (ValueError,))
        broken = owner.install_pack(root, identity, spawn=False)["packs"][0]
        _check(broken["state"] == "failed" and "target" not in broken, "broken addon manifest gained a target")
        manifest_path.write_text(json.dumps({**data, "packId": "base"}), encoding="utf-8")
        wrong = owner.install_pack(root, identity, spawn=False)["packs"][0]
        _check(wrong["state"] == "failed" and "packId" in wrong["error"], "mismatched addon gained admission")
        manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if category == "permissions":
            with _sharing(manifest_path):
                denied = owner.install_pack(root, identity, spawn=False)["packs"][0]
            _check(denied["state"] == "failed" and "target" not in denied, "denied add-on manifest admitted staged target")
        base_before = owner.base_pack_status(root)
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                admissions = list(pool.map(lambda _: owner.install_pack(root, identity, spawn=True)["packs"][0], range(8)))
            _check(all(r["state"] in {"queued","installing","installed"} for r in admissions), "concurrent add-on callers lost verified staging admission")
            queued = admissions[0]
        else: queued = owner.install_pack(root, identity, spawn=True)["packs"][0]
        _check(queued["state"] in {"queued", "installing", "installed"}, "repaired addon could not stage")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = owner.pack_status(root, identity)["packs"][0]
            if row["state"] in {"installed", "failed"}: break
            time.sleep(.02)
        _check(row["state"] == "installed" and row["stagedOnly"] and Path(row["receipt"]).is_file(), "detached addon worker did not finish verified staging: " + row.get("error", ""))
        _check((Path(row["target"]) / "payload.txt").read_bytes() == body and owner.base_pack_status(root) == base_before, "addon modified base status or changed staged source")
        (Path(row["target"]) / "payload.txt").write_bytes(b"tampered")
        _check(owner.pack_status(root, identity)["packs"][0]["state"] == "failed", "installed addon projection ignored actual corrupted bytes")
    return {"packId": identity, "receipt": row["receipt"], "detachedWorkerFinished": True, "stagedOnly": True, "baseUnchanged": True}


def _policy(root, category):
    import socket
    import threading
    from . import local_network_policy as policy
    from .neyvia_workspace_tools import WorkspaceTools, workspace_for
    from .neyvia_settings import get, update, SettingsConflict
    from .connected_sessions.claude_terminal import spawn_terminal
    first, second = workspace_for(root), WorkspaceTools(root)
    extra = root / "existing"; extra.mkdir()
    absent = root / "absent"
    policy.install(extra); policy.install(absent)
    try:
        policy.enabled()
        _check(extra in policy._roots and absent not in policy._roots, "missing/live policy roots were not rechecked")
        ready = threading.Event()
        def socket_worker():
            with socket.socket(): ready.set()
        with policy.child_start():
            thread = threading.Thread(target=socket_worker); thread.start()
            _check(ready.wait(3), "pending child prevented independent socket construction")
            def activation():
                with policy.transition(True): pass
            _reject(activation, (SettingsConflict,))
        thread.join(3); _check(not thread.is_alive(), "pending startup socket worker did not finish")
        old = get(first)
        saved = update(first, {"localOnly": True}, old["revision"])
        _check(policy.enabled() and policy._owners[first] == first.bus.root, "local-only settings did not register durable owning state")
        _reject(lambda: spawn_terminal(["must-not-launch"], str(root), {}), (policy.LocalOnlyError,))
        policy.release(first)
        _check(second in policy._owners and first not in policy._owners and policy.enabled(), "one owner release removed another policy")
        reopened = workspace_for(root)
        _check(get(reopened)["settings"]["localOnly"] is True and reopened in policy._owners, "reopened Settings lost persisted policy ownership")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda _: policy.enabled(), range(8)))
            _check(all(values), "parallel readers weakened local-only state")
        if category == "permissions":
            update(second, {"localOnly": False}, get(second)["revision"])
            database = second.bus.root / ".agent_control/ui_commands.sqlite3"
            with _sharing(database):
                _check(policy.enabled(), "unreadable durable policy granted network authority")
                _reject(lambda: spawn_terminal(["must-not-launch"], str(root), {}), (policy.LocalOnlyError,))
        if category == "stale":
            update(second, {"localOnly": False}, get(second)["revision"])
            _check(not policy.enabled(), "fresh policy retained removed local-only preference")
            update(second, {"localOnly": True}, get(second)["revision"])
            _check(policy.enabled(), "fresh policy ignored replacement local-only preference")
            retired = root / "retired-policy-root"; retired.mkdir(); policy.install(retired)
            retired.rename(root / "preserved-retired-policy-root")
            update(second, {"localOnly": False}, get(second)["revision"])
            policy.enabled(); _check(retired not in policy._roots, "removed registered policy root remained stale")
            retired.mkdir(); policy.install(retired); _check(retired in policy._roots, "recreated policy root could not register")
            policy._roots.discard(retired)
        if category == "interrupted":
            update(second, {"localOnly": False}, get(second)["revision"])
            code = """import json,sys,threading
from pathlib import Path
from contextlib import contextmanager
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.neyvia_settings import update,get
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);service=workspace_for(r);old=get(service);original=service.bus.connect
@contextmanager
def uncommitted():
 with original() as db:
  yield db
  if db.total_changes:
   marker.write_text(json.dumps({'actualSettingsWriteBeforeCommit':True}))
   threading.Event().wait(60)
service.bus.connect=uncommitted
update(service,{'localOnly':True},old['revision'])
"""
            stopped = _stop_at_marker(root, "policy", code)
            _check(not get(second)["settings"]["localOnly"] and not policy.enabled(), "stopped Settings writer committed an unobserved policy")
            update(second, {"localOnly": True}, get(second)["revision"])
            _check(policy.enabled() and workspace_for(root) in policy._owners, "fresh policy owner failed to observe committed retry")
        return {"settingsRevision": saved["revision"], "pendingChildRefusedActivation": True, "nativeLaunchRefusedBeforeLoadingLauncher": True, "ownerReleaseIndependent": True}
    finally:
        # Turn off only this disposable state before other families launch children.
        update(second, {"localOnly": False}, get(second)["revision"])
        policy.release(first); policy.release(second)
        policy._roots.discard(extra)


def _metadata(root, category):
    from .profiles import ProfileRegistry
    from .skills import SkillRegistry
    from .neyvia_runtime_invocation import build_selected_context_packet
    text = TEXT.get(category, "owned selected context")
    selected = [{"sourceId": "owned-" + str(i), "content": text, "importId": "owned-import", "sourceSha256": "b" * 64} for i in range(1024 if category == "huge" else 2)]
    packet = build_selected_context_packet(selected, max_items=2, max_chars=17)
    _check(len(packet["selected"]) <= 2 and sum(len(r["content"]) for r in packet["selected"]) <= 17, "selected content escaped exact bounds")
    for row in packet["selected"]:
        _check(row["importId"] == "owned-import" and row["contentHash"] == hashlib.sha256(row["content"].encode()).hexdigest(), "selection lost source provenance/content identity")
    profile = root / "profiles.json"
    payload = {"default_profile": "default", "profiles": {"default": {"agent": {"max_tokens": 5}}, "work": {"agent": {"max_tokens": 7}}, "explicit": {"description": text, "agent": {"max_tokens": 9}}}, "workspace_profiles": [{"pattern": "*owned*", "profile": "work"}]}
    profile.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    registry = ProfileRegistry(profile)
    _check(registry.resolve("explicit", root / "owned").agent.max_tokens == 9 and registry.resolve(None, root / "owned").agent.max_tokens == 7 and registry.resolve(None, root / "unmatched").agent.max_tokens == 5, "profile precedence or policy lost")
    if category == "permissions":
        with _sharing(profile): _reject(lambda: ProfileRegistry(profile), (PermissionError,))
    if category == "interrupted":
        _interrupted_write(profile, '{"profiles":')
        _reject(lambda: ProfileRegistry(profile), (ValueError,))
    if category == "stale":
        payload["profiles"]["explicit"]["agent"]["max_tokens"] = 13
        profile.write_text(json.dumps(payload), encoding="utf-8")
        _check(ProfileRegistry(profile).resolve("explicit").agent.max_tokens == 13, "fresh registry reused stale profile policy")
    skill_path = REPO / "config/skills.json"
    raw = json.loads(skill_path.read_text(encoding="utf-8")); skills = SkillRegistry(skill_path).skills
    names = {row.name for row in skills}
    required = {"design_taste_frontend", "premium_product_ui_visuals", "fluxio_supervision_shell", "fluxio_human_feel_audit", "user_path_validator"}
    _check(required <= names and len(skills) == len(raw), "canonical skill catalog lost required rows")
    for original, skill in zip(raw, skills):
        _check(skill.name == original["name"] and skill.execution_capable is bool(original.get("execution_capable", False)) and skill.guidance_only is bool(original.get("guidance_only", False)), "catalog invented execution provenance")
    owned_skills = root / "skills.json"; owned_skills.write_text(json.dumps(raw), encoding="utf-8")
    if category == "permissions":
        with _sharing(owned_skills): _reject(lambda: SkillRegistry(owned_skills), (PermissionError,))
    if category == "interrupted":
        _interrupted_write(owned_skills, '[{"name":')
        _reject(lambda: SkillRegistry(owned_skills), (ValueError,))
    if category == "stale":
        changed = copy.deepcopy(raw); changed[0]["description"] += " owned replacement"
        owned_skills.write_text(json.dumps(changed), encoding="utf-8")
        _check(SkillRegistry(owned_skills).skills[0].description == changed[0]["description"], "fresh skill catalog reused stale provenance")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            observations = list(pool.map(lambda _: (ProfileRegistry(profile).resolve("explicit").agent.max_tokens, [asdict(s) for s in SkillRegistry(owned_skills).skills]), range(8)))
        _check(all(r == observations[0] for r in observations) and observations[0][0] == 9, "concurrent loaded profile/skill projections diverged")
    return {"selectionCount": len(packet["selected"]), "profileBudget": registry.resolve("explicit").agent.max_tokens, "canonicalSkillCount": len(skills)}


def _package(root, category):
    text = TEXT[category]
    code = "import json,sys;import grant_agent;before='grant_agent.engine' in sys.modules;from grant_agent import AutonomousEngine,CapabilityService;print(json.dumps({'engineInitiallyLoaded':before,'exports':[AutonomousEngine.__name__,CapabilityService.__name__],'engineLoaded':'grant_agent.engine' in sys.modules,'capabilityLoaded':'grant_agent.capability_service' in sys.modules}))"
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "C7D_EXPLICIT_INPUT": text}
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _check(completed.returncode == 0, "fresh package child failed")
    result = json.loads(completed.stdout)
    _check(result == {"engineInitiallyLoaded": False, "exports": ["AutonomousEngine", "CapabilityService"], "engineLoaded": True, "capabilityLoaded": True}, "public lazy package identity changed")
    return result


def _local_copy(root, category):
    """Selected disposable local protocol roots only; no NAS discovery or sync."""
    from .nas_bridge import NasBridge
    from .nas_transfer import NasTransfer, NasTransferError
    text = TEXT.get(category, "owned local protocol bytes")
    sender = root / "sender"; receiver = root / "local-receiver/projects"
    sender.mkdir(); receiver.mkdir(parents=True)
    source = sender / "payload.txt"; source.write_text(text, encoding="utf-8")
    raw = source.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    bridge = NasBridge(sender, receiver)
    if category == "permissions":
        with _sharing(source): _reject(lambda: bridge.send_file(source), (PermissionError,))
        _check(not bridge._blob_path(digest).exists(), "denied blob source admitted bytes")
        with _sharing(source): _reject(lambda: bridge.send_message(sender="denied", recipient="reader", message="denied", attachments=[source]), (PermissionError,))
        _check(not list((bridge.message_root / "outbox").rglob("*.json")), "denied attachment gained a successful envelope")
    if category == "interrupted":
        target = bridge._blob_path(digest); target.parent.mkdir(parents=True)
        _interrupted_write(target.with_suffix(".partial"), text[:max(1,len(text)//2)])
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            attachments = list(pool.map(lambda _: NasBridge(sender, receiver).send_file(source), range(8)))
        _check(all(Path(row["blobPath"]).read_bytes() == raw for row in attachments), "parallel blob admission differed from source")
    first = bridge.send_message(sender="c7d-owned", recipient="c7d-reader", message=text, attachments=[source])
    second = bridge.send_message(sender="c7d-owned", recipient="c7d-reader", message=text, attachments=[source])
    for message in (first, second):
        inbox = json.loads(Path(message["inboxPath"]).read_text(encoding="utf-8")); outbox = json.loads(Path(message["outboxPath"]).read_text(encoding="utf-8"))
        _check(inbox == outbox and inbox["message"] == text.strip(), "local message envelopes differ")
    _check(second["transferredBytes"] == 0 and second["reusedBytes"] == len(raw), "second local blob admission did not deduplicate")
    received = bridge.receive_messages(recipient="c7d-reader", output_dir=sender / "received", acknowledge=True)
    _check(len(received["messages"]) == 2 and all(Path(row["receivedAttachments"][0]["path"]).read_bytes() == raw for row in received["messages"]), "local receive lost actual materialized identity")
    if category == "permissions":
        with _sharing(bridge._blob_path(digest)):
            _reject(lambda: bridge.receive_messages(recipient="c7d-reader", output_dir=sender / "denied-receive", acknowledge=False), (PermissionError,))
        _check(not list((sender / "denied-receive").rglob("payload.txt")), "denied blob materialized an acknowledged attachment")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent_messages = list(pool.map(lambda i: NasBridge(sender, receiver).send_message(sender="parallel", recipient="parallel", message=str(i), attachments=[source]), range(8)))
        _check(len({row["messageId"] for row in concurrent_messages}) == 8, "independent envelope producers reused message identity")
        for row in concurrent_messages:
            _check(json.loads(Path(row["inboxPath"]).read_text(encoding="utf-8")) == json.loads(Path(row["outboxPath"]).read_text(encoding="utf-8")), "parallel envelope pairs differ")
        with ThreadPoolExecutor(max_workers=4) as pool:
            receives = list(pool.map(lambda i: NasBridge(sender, receiver).receive_messages(recipient="parallel", output_dir=sender / f"parallel-receive-{i}", acknowledge=False), range(4)))
        _check(all(len(r["messages"]) == 8 and all(Path(x["receivedAttachments"][0]["path"]).read_bytes() == raw for x in r["messages"]) for r in receives), "independent receive readers lost bytes or messages")
    transfer = NasTransfer(sender, receiver, allow_local_nas_root=True)
    _reject(lambda: transfer.send(source, "../escape"), (NasTransferError,))
    if category == "permissions":
        with _sharing(source): _reject(lambda: transfer.send(source, "drops/denied.txt"), (OSError, NasTransferError))
        _check(not (receiver / "drops/denied.txt").exists(), "denied selected source transferred bytes")
    if category == "interrupted":
        partial = receiver / "drops/.payload.txt.neyvia-partial"; partial.parent.mkdir(parents=True)
        _interrupted_write(partial, text[:max(1,len(text)//2)])
    receipt = transfer.send(source, "drops/payload.txt")
    _check((receiver / "drops/payload.txt").read_bytes() == raw and receipt["verification"]["sha256"] == digest, "local transfer changed source/hash")
    _check(json.loads(Path(receipt["localReceiptPath"]).read_text(encoding="utf-8")) == receipt == json.loads(Path(receipt["nasReceiptPath"]).read_text(encoding="utf-8")), "local protocol receipts differ from returned payload")
    project = sender / "project"; (project / "src").mkdir(parents=True)
    (project / "src/item.txt").write_text(text, encoding="utf-8")
    (project / "node_modules").mkdir(); (project / "node_modules/generated.txt").write_text("excluded", encoding="utf-8")
    directory = transfer.send(project, "drops/project")
    _check(directory["files"] == 1 and (receiver / "drops/project/src/item.txt").read_bytes() == raw and not (receiver / "drops/project/node_modules").exists(), "local directory filter or observed bytes changed")
    repeated = transfer.send(project, "drops/project")
    _check(repeated["transferredFiles"] == 0 and repeated["skippedFiles"] == 1 and repeated["verification"]["sha256Manifest"] == [], "unchanged metadata invented transfer/hash work")
    if category == "stale":
        source.write_text(text + " changed", encoding="utf-8")
        changed = transfer.send(source, "drops/payload.txt")
        _check((receiver / "drops/payload.txt").read_bytes() == source.read_bytes() and changed["verification"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest(), "stale destination retained old source revision")
        newer = bridge.send_message(sender="fresh", recipient="fresh", message="changed", attachments=[source])
        newer_blob = Path(newer["attachments"][0]["blobPath"])
        _check(newer_blob.read_bytes() == source.read_bytes() and newer_blob != bridge._blob_path(digest), "changed source reused stale content identity")
        fresh = bridge.receive_messages(recipient="fresh", output_dir=sender / "fresh-receive", acknowledge=False)
        _check(Path(fresh["messages"][0]["receivedAttachments"][0]["path"]).read_bytes() == source.read_bytes(), "fresh receiver retained stale source revision")
        (project / "src/item.txt").write_text(text + " replacement", encoding="utf-8")
        revised = transfer.send(project, "drops/project")
        _check(revised["transferredFiles"] == 1 and (receiver / "drops/project/src/item.txt").read_bytes() == (project / "src/item.txt").read_bytes(), "directory retained stale metadata revision")
    if category == "permissions":
        with _sharing(project / "src/item.txt"):
            _reject(lambda: transfer.send(project, "drops/denied-project"), (OSError, NasTransferError, RuntimeError))
        _check(not (receiver / "drops/denied-project/src/item.txt").exists(), "denied directory source gained transferred bytes")
    if category == "concurrency":
        def independent(i):
            obj = NasTransfer(sender, receiver, allow_local_nas_root=True)
            file_row = obj.send(source, f"drops/parallel-{i}.txt")
            directory_row = obj.send(project, f"drops/parallel-project-{i}")
            _check((receiver / f"drops/parallel-{i}.txt").read_bytes() == raw and (receiver / f"drops/parallel-project-{i}/src/item.txt").read_bytes() == raw, "concurrent distinct destination bytes differ")
            _check(json.loads(Path(file_row["localReceiptPath"]).read_text(encoding="utf-8")) == file_row and json.loads(Path(directory_row["nasReceiptPath"]).read_text(encoding="utf-8")) == directory_row, "concurrent returned receipts lost durable identity")
            return file_row["transferId"]
        with ThreadPoolExecutor(max_workers=4) as pool: unique = list(pool.map(independent, range(8)))
        _check(len(set(unique)) == 8, "parallel transfer receipts collided")
    if category == "interrupted":
        bridge_code = """import json,sys,threading
from pathlib import Path
from grant_agent import nas_bridge as module
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);original=module._atomic_json
def committed_inbox(path,payload):
 original(path,payload)
 if path.parent.parent.name=='inbox':
  marker.write_text(json.dumps({'path':str(path),'messageId':payload['messageId']}));threading.Event().wait(60)
module._atomic_json=committed_inbox
module.NasBridge(r/'sender',r/'local-receiver/projects').send_message(sender='stopped',recipient='stopped',message='actual interrupted delivery',attachments=[r/'sender/payload.txt'])
"""
        stopped = _stop_at_marker(root,"bridge-envelope",bridge_code)
        observed_message = json.loads(Path(stopped["observed"]["path"]).read_text(encoding="utf-8"))
        _check(not (bridge.message_root / "outbox/stopped" / (observed_message["messageId"]+".json")).exists(), "stopped bridge unexpectedly delivered a complete pair")
        materialized = bridge.receive_messages(recipient="stopped",output_dir=sender/"stopped-receive",acknowledge=False)
        _check(len(materialized["messages"]) == 1 and Path(materialized["messages"][0]["receivedAttachments"][0]["path"]).read_bytes() == raw, "interrupted envelope receive invented or lost actual committed attachment")
        retried = bridge.send_message(sender="stopped",recipient="stopped",message="explicit retry",attachments=[source])
        _check(json.loads(Path(retried["inboxPath"]).read_text(encoding="utf-8")) == json.loads(Path(retried["outboxPath"]).read_text(encoding="utf-8")), "bridge retry lost complete envelope identity")
        transfer_code = """import json,sys,threading
from pathlib import Path
from grant_agent.nas_transfer import NasTransfer
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);kind=sys.argv[3];owner=NasTransfer(r/'sender',r/'local-receiver/projects',allow_local_nas_root=True)
def before_receipt(receipt,nas_root,destinations):
 marker.write_text(json.dumps({'transferId':receipt['transferId'],'destinations':destinations}));threading.Event().wait(60)
owner._write_receipt=before_receipt
owner.send(r/'sender'/('project' if kind=='directory' else 'payload.txt'),'drops/stopped-'+kind)
"""
        for kind in ("file","directory"):
            interrupted = _stop_at_marker(root,"transfer-"+kind,transfer_code,kind)
            transfer_id = interrupted["observed"]["transferId"]
            _check(not (sender/".agent_control/nas_transfers"/(transfer_id+".json")).exists(), "stopped transfer invented completed receipt")
            retry = transfer.send(project if kind=="directory" else source,"drops/stopped-"+kind)
            _check(json.loads(Path(retry["localReceiptPath"]).read_text(encoding="utf-8")) == json.loads(Path(retry["nasReceiptPath"]).read_text(encoding="utf-8")) == retry, "interrupted transfer retry lost identical durable receipts")
            target_path = receiver / ("drops/stopped-directory/src/item.txt" if kind=="directory" else "drops/stopped-file")
            _check(target_path.read_bytes() == raw, "interrupted transfer recovery lost actual source bytes")
    return {"senderRoot": str(sender), "localProtocolRoot": str(receiver), "sourceBytes": len(raw), "destinationSha256": digest, "receiptPath": receipt["localReceiptPath"], "nasAccess": False, "remoteDeviceProof": False}


RELEASE_NODE = r'''
import assert from 'node:assert/strict';
import {generateKeyPairSync,createHash,verify,createPublicKey} from 'node:crypto';
import {mkdirSync,writeFileSync,readFileSync,realpathSync,statSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const [repo,root,category]=process.argv.slice(1);
const text=category==='empty'?'':category==='huge'?'owned '.repeat(4096):'雪 café e\u0301 العربية';
const release=await import(pathToFileURL(join(repo,'scripts/prepare_slim_release.mjs')));
const gates=await import(pathToFileURL(join(repo,'scripts/release-contracts.mjs')));
const budget=await import(pathToFileURL(join(repo,'scripts/check_installer_size.mjs')));
const {privateKey,publicKey}=generateKeyPairSync('ed25519');
const signer=release.signerFromKey(privateKey),bytes=Buffer.from(text),comment='owned '+text;
const signed=signer.sign(bytes,comment),lines=signed.trimEnd().split('\n'),packet=Buffer.from(lines[1],'base64');
assert.ok(verify(null,bytes,publicKey,packet.subarray(10)));
assert.ok(verify(null,Buffer.concat([packet.subarray(10),Buffer.from(comment)]),publicKey,Buffer.from(lines[3],'base64')));
assert.throws(()=>gates.checkSignedEnvelope(Buffer.from(text+' changed'),comment,signer.pubkey,signed));
assert.throws(()=>gates.checkSignedEnvelope(bytes,comment+' changed',signer.pubkey,signed));
const registry=JSON.parse(readFileSync(join(repo,'config/onboarding_packs.json'),'utf8'));
const declarations=release.externalPackDeclarations(registry,repo);
for(const row of declarations){assert.equal(row.totalSize,row.files.reduce((a,f)=>a+f.size,0));assert.equal(row.deliveryStatus,'needs-paul');assert.ok(row.needsPaul.length);assert.ok(row.files.every(f=>f.source.version&&f.source.role==='source-input'))}
const ownedRegistry=JSON.parse(readFileSync(join(root,'declarations/registry.json'),'utf8'));
if(['permissions','interrupted','stale'].includes(category)){
 assert.throws(()=>release.externalPackDeclarations(ownedRegistry,join(root,'declarations')));
 assert.throws(()=>budget.inspectInstallerBudget({repository:join(root,'denied-budget'),slim:true,bundles:['nsis']}));
} else {
 assert.deepEqual(release.externalPackDeclarations(ownedRegistry,join(root,'declarations')),declarations);
}
assert.equal(gates.validateReleaseOutput(root,join(root,'src-tauri/target/fresh')),join(root,'src-tauri/target/fresh'));
mkdirSync(join(root,'src-tauri/target/existing'),{recursive:true});
assert.throws(()=>gates.validateReleaseOutput(root,join(root,'src-tauri/target/existing')));
assert.throws(()=>release.prepareRelease({repo:root,output:join(root,'outside')}));
assert.throws(()=>release.signer(join(root,'private.key'),root));
const config=join(root,'src-tauri/installer-budget.json');
writeFileSync(config,JSON.stringify({budgets:{nsis:{label:'Owned fixture',maxBytes:64},stagedResources:{label:'Owned files',maxBytes:64}},forbiddenContent:[{pattern:'forbidden',reason:'owned forbidden fixture'}]}));
const missing=budget.inspectInstallerBudget({repository:root,slim:true,bundles:['nsis']});assert.deepEqual(missing.reasons,['missing:nsis']);
const artifact=join(root,'src-tauri/target/release/bundle/nsis/owned.exe');mkdirSync(resolve(artifact,'..'),{recursive:true});writeFileSync(artifact,Buffer.alloc(64));
assert.ok(budget.inspectInstallerBudget({repository:root,slim:true,bundles:['nsis']}).ok);
writeFileSync(artifact,Buffer.alloc(65));assert.deepEqual(budget.inspectInstallerBudget({repository:root,slim:true,bundles:['nsis']}).reasons,['artifact-budget:nsis']);
writeFileSync(artifact,Buffer.alloc(64));const staged=join(root,'src-tauri/target/release/backend/forbidden.txt');mkdirSync(resolve(staged,'..'),{recursive:true});writeFileSync(staged,text||'x');
assert.deepEqual(budget.inspectInstallerBudget({repository:root,slim:true,bundles:['nsis']}).reasons,['slim-backend']);
assert.ok(budget.inspectInstallerBudget({repository:root,slim:false,bundles:['nsis']}).reasons.some(x=>x.startsWith('forbidden:')));
if(category==='concurrency'){
 const {spawn}=await import('node:child_process');
 const program="import {readFileSync} from 'node:fs';import {join} from 'node:path';import {pathToFileURL} from 'node:url';const [repo,root]=process.argv.slice(1);const r=await import(pathToFileURL(join(repo,'scripts/prepare_slim_release.mjs'))),b=await import(pathToFileURL(join(repo,'scripts/check_installer_size.mjs')));console.log(JSON.stringify({declarations:r.externalPackDeclarations(JSON.parse(readFileSync(join(root,'declarations/registry.json'))),join(root,'declarations')),budget:b.inspectInstallerBudget({repository:root,slim:false,bundles:['nsis']})}))";
 const observations=await Promise.all(Array.from({length:8},()=>new Promise((ok,no)=>{const child=spawn(process.execPath,['--input-type=module','-e',program,repo,root],{windowsHide:true});let out='',err='';child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);child.on('exit',code=>code===0?ok(JSON.parse(out)):no(Error(err)))})));
 assert.ok(observations.every(row=>JSON.stringify(row)===JSON.stringify(observations[0])));
 assert.deepEqual(observations[0].declarations,declarations);
}
const vite=(await import(pathToFileURL(join(repo,'vite.config.mjs')))).default;
const configuration=typeof vite==='function'?await vite({command:'serve',mode:'development'}):vite;
assert.equal(configuration.root,realpathSync(join(repo,'web')));assert.equal(configuration.resolve.alias['~'],join(realpathSync(join(repo,'web')),'src'));assert.equal(configuration.build.outDir,join(realpathSync(join(repo,'web')),'dist'));
console.log(JSON.stringify({signedBytes:bytes.length,externalPacks:declarations.length,artifactBytes:statSync(artifact).size,invalidByteCommentAndPrivatePathRefused:true,nativeInstallerProof:false,renderedProof:false}));
'''


def _release(root, category):
    env = {**os.environ, "TAURI_DEV_PORT": "48742", "FLUXIO_WEB_BACKEND_URL": "http://127.0.0.1:48741", "NEYVIA_TOOL_AUTO_UPDATE": "0"}
    registry = json.loads((REPO / "config/onboarding_packs.json").read_text(encoding="utf-8"))
    owned = copy.deepcopy(registry); selected = root / "declarations"; selected.mkdir()
    paths = []
    for identity, value in registry["packages"].items():
        if value.get("localComponents"): continue
        origin = REPO / registry["manifests"][identity]
        destination = selected / (identity + ".json"); destination.write_bytes(origin.read_bytes())
        owned["manifests"][identity] = destination.name; paths.append(destination)
    (selected / "registry.json").write_text(json.dumps(owned), encoding="utf-8")
    bad = root / "denied-budget/src-tauri/installer-budget.json"; bad.parent.mkdir(parents=True)
    bad.write_text('{"budgets":{}}', encoding="utf-8")
    if category == "interrupted":
        _interrupted_write(paths[0], '{"packId":'); _interrupted_write(bad, '{"budgets":')
    if category == "stale":
        changed = json.loads(paths[0].read_text(encoding="utf-8")); changed["totalSize"] += 1; paths[0].write_text(json.dumps(changed))
        bad.write_text('{"budgets":')
    def observe():
        return subprocess.run(["node", "--input-type=module", "-e", RELEASE_NODE, str(REPO), str(root), category], cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if category == "permissions":
        with _sharing(paths[0]), _sharing(bad): completed = observe()
    else: completed = observe()
    _check(completed.returncode == 0, "release artifact/signing observation failed: " + completed.stderr[-3000:])
    return json.loads(completed.stdout)


def _proof_boundary(root, category):
    from .proof_contracts import before_action, after_action, ContractViolation
    from .proof_credential_guard import check_access, install
    from .edge_fixture_host_runtime import _native
    from .proof_verifier import _local_arguments
    text = TEXT.get(category, "owned proof text")
    native = _native(root)
    (root / "input.txt").write_text(text, encoding="utf-8")
    rows = before_action("workspace.read", {"path": "input.txt"})
    _check(rows, "grounded onboarding schema not registered")
    _reject(lambda: before_action("workspace.read", {"path": 7}), (ContractViolation,))
    _reject(lambda: after_action(rows, {"ok": True}), (ContractViolation,))
    native_rows = native.call("neyvia.onboarding.save", {"interests": [], "completed": True})
    _check(native_rows["ok"], "valid grounded Native action did not reach production owner")
    invalid_native = native.call("neyvia.onboarding.save", {"interests": 7})
    _check(not invalid_native["ok"] and invalid_native["proofs"]["phase"] == "validation", "invalid grounded input reached the owner")
    # The forbidden location is deliberately nonexistent and only passed to
    # the admission guard; no saved credential path is ever opened or read.
    absent = REPO / "c7d-does-not-exist" / "auth.json"
    _check(not absent.exists(), "synthetic refused path unexpectedly exists")
    _reject(lambda: check_access(absent), (PermissionError,))
    if category == "concurrency":
        def refused(_):
            return _reject(lambda: absent.read_bytes(), (PermissionError,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(refused, range(8)))
        _check(outcomes == ["PermissionError"]*8, "parallel audit callbacks admitted a forbidden synthetic path")
    else:
        _reject(absent.read_bytes, (PermissionError,))
    if category == "interrupted":
        code = """import sys,json,threading
from pathlib import Path
from grant_agent.proof_credential_guard import install
r=Path(sys.argv[1]);install(r)
try:Path(sys.argv[3]).read_bytes()
except PermissionError:Path(sys.argv[2]).write_text(json.dumps({'refusedBeforeContentRead':True}));threading.Event().wait(60)
"""
        _stop_at_marker(root, "guard", code, absent)
    ordinary = root / "ordinary.txt"; ordinary.write_text(text, encoding="utf-8")
    install(root); check_access(ordinary)
    _check(ordinary.read_text(encoding="utf-8") == text, "guard refused ordinary owned data")
    if category == "permissions":
        (root / "denied-local-read.txt").write_text("owned ordinary data")
        with _sharing(root / "denied-local-read.txt"):
            denied = native.call("workspace.read", {"path":"denied-local-read.txt"})
        _check(not denied["ok"], "selected scratch dispatch invented denied local source bytes")
    _local_arguments({"path": "input.txt", "nested": {"folder": "."}}, root)
    _reject(lambda: _local_arguments({"path": "../outside"}, root), (ValueError,))
    _check(not (root.parent / "outside").exists(), "refused scratch argument created escaped state")
    from .proof_verifier import run_verification
    from .proof_ports import configure_ports, c7_port_block
    configure_ports(c7_port_block(int(os.environ['NEYVIA_C7_PORT'])))
    with _environment({"NEYVIA_UI_STATE_ROOT": str(root / "must-not-use"), "NEYVIA_UI_BACKEND_URL": "http://127.0.0.1:48749"}):
        report = run_verification(root, areas=["c7d-unknown-negative-area"], include_manuals=False, timeout_seconds=90)
    scratch = Path(report["scratchRoot"]).resolve(); scratch.relative_to(root.resolve() / ".agent_control/proofs")
    _check(report["complete"] is False and report["areas"][0].get("ok") is False and not (root / "must-not-use").exists(), "fresh proof worker inherited live UI state or invented complete area")
    _check(json.loads((scratch / "receipt.json").read_text(encoding="utf-8")) == report, "isolated child receipt differs from durable owned state")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=2) as pool:
            parallel = list(pool.map(lambda _: run_verification(root,areas=["c7d-unknown-negative-area"],include_manuals=False,timeout_seconds=90),range(2)))
        _check(len({r["scratchRoot"] for r in parallel}) == 2 and all(not r["complete"] for r in parallel), "parallel proof workers shared roots or invented complete areas")
    if category == "interrupted":
        _reject(lambda: run_verification(root,areas=["c7d-unknown-negative-area"],include_manuals=False,timeout_seconds=.01), (RuntimeError,))
        _check(not (root / "must-not-use").exists(), "stopped proof worker redirected into host UI state")
    return {"groundedAction": "neyvia.onboarding.save", "schemaRows": len(rows), "validOwnerEffect": native_rows["ok"], "savedCredentialOpened": False, "scratchEscapeRefused": True, "freshInterpreterReceipt": str(scratch / "receipt.json")}


def _coverage_gate(root, category):
    from .proof_coverage import revalidate_existing, retirement_gate, evidence_revalidated, coverage_source_current
    from .proof_contracts import declarations, source_bindings, source_binding_digest, file_digest
    from .neyvia_runtime_invocation import build_selected_context_packet
    text = TEXT.get(category, "owned coverage")
    live = declarations(); identity = "d.host.selected-context"
    source = source_bindings()
    packet = build_selected_context_packet([{"sourceId": "owned", "content": text}], max_items=1, max_chars=32)
    _check(sum(len(row["content"]) for row in packet["selected"]) <= 32, "actual coverage observation did not enforce its source invariant")
    area = "c7d-owned-source"
    receipt = root / "observed.json"; manifest = root / "manifest.json"
    report = {"sourceStable": source == source_bindings(), "sourceBindings": source, "areas": [{"area": area, "ok": True, "contracts": [identity], "procedures": [{"id": "bounded-selection", "status": "passed"}]}]}
    receipt.write_text(json.dumps(report), encoding="utf-8")
    manifest.write_text(json.dumps({"area": area, "contracts": [live[identity]]}), encoding="utf-8")
    case = {"id": "c7d-owned-case", "contract_ids": [identity], "checked_at": live[identity]["checkedAt"], "source_binding_sha256": source_binding_digest(source), "self_checks": [receipt.relative_to(REPO).as_posix() + "#areas/" + area + "/procedures/bounded-selection"], "manifest": manifest.relative_to(REPO).as_posix(), "receipt_sha256": file_digest(receipt), "manifest_sha256": file_digest(manifest)}
    _check(coverage_source_current(case, current_sources=source), "fresh exact-contract source-bound observation not admitted")
    corrupt = copy.deepcopy(case); corrupt["receipt_sha256"] = "0" * 64
    _check(not coverage_source_current(corrupt, current_sources=source), "tampered original receipt gained source authority")
    row = {"contracts": case["contract_ids"], "checkedAt": case["checked_at"], "priorBinding": case["source_binding_sha256"], "manifestSha256": case["manifest_sha256"], "originalReceiptSha256": case["receipt_sha256"]}
    _check(evidence_revalidated(case, {case["id"]: row}), "exact immutable revalidation correspondence refused")
    _check(not evidence_revalidated(case, {case["id"]: {**row, "originalReceiptSha256": "0" * 64}}), "different original evidence admitted revalidation")
    invalid = root / "invalid-renewal.json"; invalid.write_text(json.dumps({"sourceStable": False, "sourceBindings": source, "note": text}), encoding="utf-8")
    _reject(lambda: revalidate_existing(invalid), (ValueError,))
    _check(retirement_gate([]) == [], "empty retirement invented authorized paths")
    inventory = json.loads((REPO / "config/proofs/test-inventory.json").read_text(encoding="utf-8"))
    blocked = next(row for row in inventory["files"] if row["disposition"] != "covered")
    _reject(lambda: retirement_gate([blocked["path"]]), (ValueError,))
    if category == "permissions":
        with _sharing(invalid): _reject(lambda: revalidate_existing(invalid), (PermissionError,))
    if category == "interrupted":
        _interrupted_write(invalid, '{"sourceStable":')
        _reject(lambda: revalidate_existing(invalid), (ValueError,))
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: coverage_source_current(case, current_sources=source), range(8)))
        _check(all(values), "immutable same-source observations disagreed")
    return {"sourceBinding": source_binding_digest(source), "observedContract": identity, "sourceCurrent": True, "tamperedRevalidationRefused": True, "retirementRefusedPath": blocked["path"], "renderedProof": False}


def _cache_remaining(root, category):
    from .edge_fixture_host_runtime import _cache, TEXT as HOST_TEXT
    from .p2p_cache import P2PCacheService
    import blake3
    detail = _cache(root, category)
    owner = P2PCacheService(root, config_path=root / "cache.json")
    source = root / "source.txt"; raw = source.read_bytes()
    # _cache deliberately ends with corrupted object bytes. Restore only the
    # exact originally admitted source before additional independent readers.
    digest = detail["objectHash"]
    admitted = HOST_TEXT.get(category, "fixture cache").encode()
    owner._object_path(digest).write_bytes(admitted)
    if category == "permissions":
        with _sharing(owner._object_path(digest)):
            _reject(lambda: owner.read_text(digest, length=17), (OSError, RuntimeError))
        plan = owner.plan_import(source, kind="context-chunk")
        with _sharing(source): _reject(lambda: owner.import_object(plan, approved=True), (OSError, RuntimeError))
    if category == "concurrency":
        def observations(_):
            return owner.bootstrap(), owner.plan_import(source, kind="context-chunk"), owner.read_text(digest, length=17)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(observations, range(8)))
        _check(all(r[0]["objects"] == 1 and r[1]["objectHash"] == blake3.blake3(raw).hexdigest() and r[2]["text"] == admitted[:17].decode("utf-8", errors="replace") for r in rows), "parallel cache count/plan/read observations diverged")
    if category == "stale":
        plan = owner.plan_import(source, kind="context-chunk")
        source.write_bytes(raw + b" newer")
        fresh = owner.plan_import(source, kind="context-chunk")
        _check(fresh["objectHash"] != plan["objectHash"] and fresh["sourceSize"] == len(raw) + 6, "plan observation retained stale source identity")
    return detail


def _gateway_remaining(root, category):
    from .edge_fixture_host_runtime import _gateway
    from .desktop_gateway import record_desktop_gateway_heartbeat, load_desktop_gateway_heartbeats
    detail = _gateway(root, category)
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            heartbeats = list(pool.map(lambda i: record_desktop_gateway_heartbeat(root, host_id="c7d-heartbeat-" + str(i), local_workspace=str(root), nas_workspace="logical-no-remote-root"), range(8)))
        rows = load_desktop_gateway_heartbeats(root, limit=100)
        _check(all(row in rows for row in heartbeats), "concurrent admitted heartbeat absent from durable journal")
    if category == "interrupted":
        code = """import json,sys,threading
from pathlib import Path
from grant_agent import desktop_gateway as gateway,proofs_b_desktop as proofs
from grant_agent.cluster import ClusterRegistry
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);kind=sys.argv[3];original=proofs.check
def stopped(identity,arguments,result,capture):
 original(identity,arguments,result,capture)
 if identity=='desktop.gateway.'+kind:
  marker.write_text(json.dumps({'actualOwnerPostconditionPassed':True,'identity':identity}))
  threading.Event().wait(60)
proofs.check=stopped
if kind=='heartbeat':gateway.record_desktop_gateway_heartbeat(r,host_id='c7d-stopped-pc',local_workspace=str(r),nas_workspace='logical-no-remote-root')
elif kind=='event':gateway.record_gateway_event(r,host_id='owned-pc',job_id='owned-proof-job',event_kind='stopped-delivery',message='owned actual event',payload={'interrupted':True})
else:
 registry=ClusterRegistry(r);registry.upsert_job(job_id='c7d-stopped-reconcile',job_kind='browser.verify',required_capabilities=['browser.verify'])
 with registry._connect() as db:db.execute("UPDATE jobs SET status='running',assigned_host='owned-pc' WHERE job_id='c7d-stopped-reconcile'");db.execute("UPDATE hosts SET last_heartbeat_at='2000-01-01T00:00:00Z' WHERE host_id='owned-pc'")
 gateway.reconcile_disappeared_gateway_jobs(r)
"""
        for kind in ("heartbeat","event","reconcile"): _stop_at_marker(root, "gateway-"+kind, code, kind)
        from .desktop_gateway import load_gateway_events
        from .cluster import ClusterRegistry
        _check(any(x["hostId"] == "c7d-stopped-pc" for x in load_desktop_gateway_heartbeats(root,limit=100)), "stopped heartbeat delivery lost durable admitted row")
        _check(any(x["eventKind"] == "stopped-delivery" for x in load_gateway_events(root,job_id="owned-proof-job",limit=100)), "stopped event delivery lost actual journal row")
        _check(ClusterRegistry(root).get_job("c7d-stopped-reconcile")["status"] == "queued", "stopped reconciliation invented failure or lost durable proof gap")
    return detail


def _stages_remaining(root, category):
    from .edge_fixture_host_runtime import _stages, _native
    from .neyvia_stage_scheduler import execute_neyvia_stages, build_progressive_step_handler
    from .native_tools import register_with_progressive_surface
    from .progressive_tools import ProgressiveToolSurface
    import threading
    detail = _stages(root, category)
    if category == "interrupted":
        stopped_root = root / "stopped-stages"; stopped_root.mkdir(); (stopped_root / "input.txt").write_text("actual interrupted Native read")
        code = """import json,sys,threading
from pathlib import Path
from grant_agent.proof_credential_guard import install
from grant_agent.edge_fixture_host_runtime import _native
from grant_agent.native_tools import register_with_progressive_surface
from grant_agent.progressive_tools import ProgressiveToolSurface
from grant_agent.neyvia_stage_scheduler import execute_neyvia_stages,build_progressive_step_handler
r=Path(sys.argv[1]);marker=Path(sys.argv[2]);install(r);native=_native(r);surface=ProgressiveToolSurface();register_with_progressive_surface(surface,native);owner=build_progressive_step_handler(r,progressive=surface)
def observed(step,context):
 result=owner(step,context)
 if step.get('tool')=='workspace.read':
  marker.write_text(json.dumps({'actualNativeRead':result['ok']}));threading.Event().wait(60)
 return result
source='NEYVIA/1\\nGOAL text="Interrupted native stages"\\nBUDGET repairs=1\\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\\nSTEP left lane=worker action=tool tool=workspace.read risk=read args=\\'{\"path\":\"input.txt\"}\\'\\nSTEP right lane=worker action=tool tool=workspace.read risk=read args=\\'{\"path\":\"input.txt\"}\\'\\n'
execute_neyvia_stages(r,source,step_handler=observed,mission_id='stopped',stop_on_failure=False)
"""
        observed = _stop_at_marker(stopped_root,"stages",code)
        _check(observed["observed"]["actualNativeRead"] and not list(stopped_root.rglob("*stage_exec.json")), "stopped scheduler fabricated completed execution receipt")
    text = TEXT.get(category, "parallel owned material")
    source = root / "parallel.txt"; source.write_text(text, encoding="utf-8")
    registry = _native(root); surface = ProgressiveToolSurface(); register_with_progressive_surface(surface, registry)
    barrier = threading.Barrier(2); workers = []
    spec = surface._specs["workspace.read"]
    def observe(args):
        workers.append(threading.get_ident()); barrier.wait(timeout=10)
        result = registry.call("workspace.read", args)
        _check(result["result"]["content"] == text[:17], "parallel production read changed exact source bytes")
        return result
    surface.register(spec, handler=observe)
    handler = build_progressive_step_handler(root, progressive=surface)
    arguments = json.dumps({"path": "parallel.txt", "maxChars": 17})
    program = 'NEYVIA/1\nGOAL text="Observe owned parallel bytes"\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\n' + f"STEP first lane=worker action=tool tool=workspace.read risk=read args='{arguments}'\nSTEP second lane=worker action=tool tool=workspace.read risk=read args='{arguments}'\n"
    receipt = execute_neyvia_stages(root, program, mission_id="c7d-parallel", step_handler=handler)
    _check(receipt["ok"] and receipt["completedStepIds"] == ["first", "second"] and len(set(workers)) == 2 and receipt["parallelStagesRun"] >= 1, "actual parallel workers did not merge in compiled order")
    _check(json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8")) == receipt, "parallel order receipt not durable")
    detail["parallelReceiptPath"] = receipt["receiptPath"]
    return detail


def _host_state(root, category):
    from .nearby_send import NearbySendService, NEARBY_TRANSFER_STATE_SCHEMA, NEARBY_TRANSFER_RECEIPT_SCHEMA
    from .web_backend import FluxioWebBackend
    text = TEXT.get(category, "owned artifact")
    service = NearbySendService(root)
    service.nearby_root.mkdir(parents=True, exist_ok=True)
    state = {"schema": NEARBY_TRANSFER_STATE_SCHEMA, "transferId": "c7d-stopped", "status": "uploading", "ownerPid": 2_000_000_000, "recipient": {"endpoint": "https://private.invalid"}, "sessionId": "private-in-memory", "files": [], "summary": {}}
    service.active_state_path.write_text(json.dumps(state), encoding="utf-8")
    service.transfer_claim_path.write_text(json.dumps({"transferId": state["transferId"], "ownerPid": state["ownerPid"]}), encoding="utf-8")
    if category == "permissions":
        before = service.active_state_path.read_bytes()
        with _sharing(service.active_state_path): _reject(service.get_active_transfer, (OSError,))
        _check(service.active_state_path.read_bytes() == before, "denied state recovery overwrote shared state")
    if category == "interrupted":
        _interrupted_write(service.active_state_path, '{"schema":')
        corrupt_projection = service.get_active_transfer()
        _check(not corrupt_projection["active"] and not corrupt_projection.get("progress"), "interrupted state invented a live transfer")
        service.active_state_path.write_text(json.dumps(state))
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: recoveries = list(pool.map(lambda _: service.get_active_transfer(), range(8)))
        _check(all(not x["active"] for x in recoveries) and sum(x.get("recovery") == "stale_transfer_recovered" for x in recoveries) == 1, "concurrent recovery retained claims or recovered more than once")
        recovered = next(x for x in recoveries if x.get("recovery") == "stale_transfer_recovered")
    else: recovered = service.get_active_transfer()
    _check(not recovered["active"] and recovered["recovery"] == "stale_transfer_recovered" and "private-in-memory" not in json.dumps(recovered) and not service.transfer_claim_path.exists(), "dead owner retained claims/secrets")
    service.receipt_root.mkdir(parents=True, exist_ok=True)
    count = 128 if category == "huge" else 0 if category == "empty" else 3
    for i in range(count):
        row = {"schema": NEARBY_TRANSFER_RECEIPT_SCHEMA, "receiptId": f"nearby_receipt_{i}", "transferId": "c7d-" + str(i), "status": ["completed", "failed", "cancelled"][i%3], "ok": i%3==0, "recipient": {}, "files": [], "summary": {}, "cancellation": {}, "note": text}
        (service.receipt_root / f"nearby_receipt_{i}.json").write_text(json.dumps(row), encoding="utf-8")
    invalid = service.receipt_root / "nearby_receipt_corrupt.json"
    if category == "interrupted": _interrupted_write(invalid, '{"schema":')
    else: invalid.write_text("{", encoding="utf-8")
    history = service.list_transfer_history(limit=2)
    _check(len(history["transfers"]) == min(2,count) and history["summary"]["skippedInvalidReceipts"] == 1 and history["summary"]["transfers"] == min(2,count), "history bounds/counts/corrupt skipping differ")
    if category == "permissions":
        denied_receipt = service.receipt_root / "nearby_receipt_0.json"
        with _sharing(denied_receipt):
            denied = service.list_transfer_history(limit=100)
        _check(denied["summary"]["skippedInvalidReceipts"] == 2 and len(denied["transfers"]) == count-1, "denied history row invented valid receipt or incorrect counts")
    if category == "stale":
        changed_path = service.receipt_root / "nearby_receipt_0.json"; changed = json.loads(changed_path.read_text(encoding="utf-8"))
        changed.update(status="failed",ok=False); changed_path.write_text(json.dumps(changed))
        new = service.list_transfer_history(limit=100)
        _check(next(x for x in new["transfers"] if x["transferId"] == "c7d-0")["status"] == "failed", "history reused stale terminal status")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: histories = list(pool.map(lambda _: service.list_transfer_history(limit=2), range(8)))
        _check(all(r["transfers"] == history["transfers"] and r["summary"] == history["summary"] for r in histories), "parallel history readers diverged")
    backend = object.__new__(FluxioWebBackend); backend.root = root
    artifact = root / ".agent_control/mission_artifacts/owned.txt"; artifact.parent.mkdir(parents=True); artifact.write_text(text, encoding="utf-8")
    source = {"artifacts": [{"path": str(artifact)}, {"path": str(root / "missing.txt"), "safeEndpoint": "/api/artifact", "servedUrl": "/api/artifact?id=" + "a" * 24}]}
    decorated = backend._decorate_mission_artifacts(source)
    _check(decorated["artifacts"][0]["safeEndpoint"] == "/api/artifact" and decorated["artifacts"][0]["mediaType"] == "text/plain", "allowed physical artifact lost safe endpoint/media")
    _check(not decorated["artifacts"][1].get("safeEndpoint") and not decorated["artifacts"][1].get("servedUrl"), "missing artifact retained stale endpoint")
    _check("safeEndpoint" not in source["artifacts"][0], "artifact decoration mutated caller state")
    return {"recoveredStatus": recovered["progress"]["status"], "returnedHistory": len(history["transfers"]), "skippedCorrupt": 1, "artifactEndpoint": decorated["artifacts"][0]["servedUrl"], "renderedProof": False}


def _nearby(root, category):
    """Real sender plus owned loopback receiver, exact bytes and durable ACKs."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs
    from .nearby_send import NearbySendService, NEARBY_CHUNK_TRANSFER_SCHEMA, _canonical_hash, _TransferFailure
    import threading
    text = TEXT.get(category, "owned nearby bytes")
    body = text.encode()
    from .proof_ports import c7_port_block
    port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[-2]
    endpoint = f"http://127.0.0.1:{port}"
    config = json.loads((REPO / "config/neyvia_nearby_send.json").read_text(encoding="utf-8"))
    config["protocol"]["port"] = port
    config["limits"].update(chunkBytes=max(4, (len(body)+7)//8), maxParts=32, maxParallelUploads=1, requestTimeoutSeconds=10)
    folder = root / "config"; folder.mkdir(); (folder / "neyvia_nearby_send.json").write_text(json.dumps(config), encoding="utf-8")
    owner = NearbySendService(root)
    source = root / ("雪.txt" if category == "unicode" else "payload.txt"); source.write_bytes(body)
    control = root / "control.txt"; control.write_bytes(b"control bytes")
    _reject(lambda: owner.build_plan([], recipient_endpoint=endpoint), (ValueError,))
    if category == "permissions":
        with _sharing(source): _reject(lambda: owner.build_plan([source], recipient_endpoint=endpoint), (OSError,))
    plan = owner.build_plan([source, control], recipient_endpoint=endpoint)
    _check(plan["summary"]["totalBytes"] == len(body)+13 and plan["summary"]["fileCount"] == 2, "nearby plan counts differ from actual bytes")
    for item in plan["files"]:
        raw = Path(item["path"]).read_bytes()
        _check(item["sha256"] == hashlib.sha256(raw).hexdigest() and sum(c["size"] for c in item["chunks"]) == len(raw), "hash-bound plan did not cover every actual source byte")
    legacy = copy.deepcopy(plan["files"][0]); legacy.pop("chunks")
    if category == "permissions":
        with _sharing(source): _reject(lambda: owner._verify_planned_file(legacy), (OSError,))
    migrated = owner._verify_planned_file(legacy)
    _check(migrated["chunkManifestMigrated"] and migrated["chunks"] == plan["files"][0]["chunks"], "legacy preview not enriched from verified source bytes")
    if category == "stale":
        source.write_bytes(body+b" changed")
        _reject(lambda: owner._verify_planned_file(plan["files"][0]), (ValueError,))
        source.write_bytes(body)
        plan = owner.build_plan([source, control], recipient_endpoint=endpoint)
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            previews = list(pool.map(lambda _: owner.build_plan([source, control], recipient_endpoint=endpoint), range(8)))
        _check(all([(x["sha256"],x["chunks"]) for x in p["files"]] == [(x["sha256"],x["chunks"]) for x in plan["files"]] for p in previews), "concurrent source previews diverged")
    # Exercise the actual migration wire path, including each failed/recovered
    # transfer, rather than treating an enriched Python object as transport proof.
    legacy_plan = copy.deepcopy(plan)
    for value in legacy_plan["files"]: value.pop("chunks")
    legacy_plan.pop("planHash"); legacy_plan["planHash"] = _canonical_hash(legacy_plan)
    send_plan = legacy_plan
    item = plan["files"][1]
    valid_auth = {"token": "owned-wire-token", "chunkTransfer": {"schema": NEARBY_CHUNK_TRANSFER_SCHEMA, "offset": 0, "acknowledgedChunks": []}}
    _check(owner._parse_upload_authorization(item, valid_auth)["offset"] == 0, "valid exact empty resume prefix refused")
    invalid_auth = copy.deepcopy(valid_auth); invalid_auth["chunkTransfer"]["offset"] = 1
    _reject(lambda: owner._parse_upload_authorization(item, invalid_auth), (_TransferFailure,))
    if category == "offline":
        plan_path = root / "offline-plan.json"; plan_path.write_text(json.dumps(send_plan), encoding="utf-8")
        code = "import sys,json;from pathlib import Path;from grant_agent.nearby_send import NearbySendService;r=Path(sys.argv[1]);p=json.loads(Path(sys.argv[2]).read_text());attempts=[]\ndef audit(event,args):\n if event=='socket.connect':attempts.append(event);raise PermissionError('owned offline boundary')\nsys.addaudithook(audit);result=NearbySendService(r).send(p,approved=True);print(json.dumps({'result':result,'attempts':attempts}))"
        completed = subprocess.run([sys.executable, "-c", code, str(root), str(plan_path)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _check(completed.returncode == 0, "actual offline sender child failed before terminal observation")
        observed = json.loads(completed.stdout); result = observed["result"]
        _check(observed["attempts"] and result["status"] == "failed" and not result["ok"] and (root / result["receiptPath"]).is_file(), "offline sender invented completion or omitted durable failure")
        _check(result["summary"]["acknowledgedParts"] == 0 and not any(x["remoteHashVerified"] for x in result["files"]) and result["summary"]["migratedChunkManifests"] == 2, "offline sender invented ACK integrity or omitted real migration")
        inactive = owner.request_cancel_active_transfer()
        _check(not inactive["accepted"] and not inactive["cancelled"], "offline terminal sender invented cancellable live ownership")
        return {"explicitPort": port, "socketAttemptsRefused": len(observed["attempts"]), "receiptPath": str(root / result["receiptPath"]), "physicalDeviceProof": False}
    state = {"manifests": {}, "acks": {}, "bytes": {}, "attempts": [], "fault": "", "block": False, "blockAt": None, "abort": False, "cancelStatus": 204}
    ready = threading.Event(); release = threading.Event(); state_lock = threading.RLock()
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, status, value=None):
            raw = json.dumps(value).encode() if value is not None else b""
            try:
                self.send_response(status); self.send_header("Content-Length", str(len(raw))); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(raw)
            except OSError: pass
        def do_POST(self):
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            if parsed.path.endswith("/prepare-upload"):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if state["fault"] == "permission":
                    self.reply(403); return
                replies = {}
                with state_lock:
                    for identity, metadata in payload["files"].items():
                        contract = metadata["chunkTransfer"]; state["manifests"][identity] = contract
                        ack = state["acks"].setdefault(identity, [])
                        replies[identity] = {"token": "owned-wire-token", "chunkTransfer": {"schema": NEARBY_CHUNK_TRANSFER_SCHEMA, "offset": 1 if state["fault"] == "stale-prefix" else sum(r["size"] for r in ack), "acknowledgedChunks": [{**r, "integrityVerified": True} for r in ack]}}
                self.reply(200, {"sessionId": "owned-wire-session", "files": replies}); return
            if parsed.path.endswith("/cancel"):
                self.reply(state["cancelStatus"]); return
            if not parsed.path.endswith("/upload"):
                self.reply(404); return
            identity = query["fileId"][0]; part = int(query["part"][0]); offset = int(query["offset"][0]); length = int(self.headers["Content-Length"])
            raw = self.rfile.read(length); expected = state["manifests"][identity]["chunks"][part]
            if len(raw) != expected["size"] or hashlib.sha256(raw).hexdigest() != expected["sha256"] or offset != expected["offset"]:
                self.reply(400); return
            with state_lock: state["attempts"].append((identity, part, offset)); state["bytes"][(identity,part)] = raw
            if part:
                durable = json.loads(owner.active_state_path.read_text(encoding="utf-8"))
                current = next(row for row in durable["files"] if row["fileId"] == identity)
                if current["acknowledgedOffset"] != offset or len(current["acknowledgedChunks"]) != part:
                    self.reply(409); return
            if state["block"] and (state["blockAt"] is None or part == state["blockAt"]):
                ready.set(); release.wait(timeout=15)
                if state["abort"]: self.reply(503); return
            if state["fault"]:
                self.reply(200, {"acknowledged": True, "nextOffset": offset+length, "sha256": "0"*64, "integrityVerified": True}); return
            with state_lock:
                if not any(r["part"] == part for r in state["acks"][identity]): state["acks"][identity].append(dict(expected))
            self.reply(200, {"acknowledged": True, "nextOffset": offset+length, "sha256": hashlib.sha256(raw).hexdigest(), "integrityVerified": True})
    server = ThreadingHTTPServer(("127.0.0.1", port), Receiver); server.daemon_threads = True
    listener = threading.Thread(target=server.serve_forever, daemon=True); listener.start()
    def verify_receipt(result):
        path = root / result["receiptPath"]
        durable = json.loads(path.read_text(encoding="utf-8"))
        _check(durable["status"] == result["status"] and "owned-wire-token" not in json.dumps(result), "nearby durable result lost status or exposed wire token")
        return str(path)
    try:
        result = owner.send(send_plan, approved=True)
        _check(result["ok"] and result["status"] == "completed", "real receiver did not verify complete sender bytes")
        _check(result["summary"]["migratedChunkManifests"] == 2, "wire result omitted verified legacy migration")
        receipt_path = verify_receipt(result)
        for row in plan["files"]:
            actual = b"".join(state["bytes"].get((row["id"],c["part"]),b"") for c in row["chunks"])
            _check(actual == Path(row["path"]).read_bytes(), "independent receiver bytes differ from source")
        interruption = None
        if category == "interrupted":
            state["acks"].clear(); state["attempts"].clear(); state.update(block=True, blockAt=1, abort=True); ready.clear(); release.clear()
            path = root / "interrupted-plan.json"; path.write_text(json.dumps(send_plan), encoding="utf-8")
            code = "import json,sys;from pathlib import Path;from grant_agent.nearby_send import NearbySendService;r=Path(sys.argv[1]);print(json.dumps(NearbySendService(r).send(json.loads(Path(sys.argv[2]).read_text()),approved=True)))"
            child = subprocess.Popen([sys.executable, "-c", code, str(root), str(path)], env={**os.environ, "PYTHONPATH": str(REPO / "src")}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                _check(ready.wait(10), "child sender did not reach second chunk boundary")
                before = json.loads(owner.active_state_path.read_text(encoding="utf-8"))
                prefix = next(row for row in before["files"] if row.get("acknowledgedChunks"))
                _check(len(prefix["acknowledgedChunks"]) == 1 and prefix["acknowledgedOffset"] > 0, "sender ACK prefix not durable before next chunk")
                child.terminate(); child.communicate(timeout=10)
            finally:
                if child.poll() is None: child.kill(); child.communicate(timeout=10)
                release.set()
            _check(child.returncode != 0 and owner.get_active_transfer()["recovery"] == "stale_transfer_recovered", "stopped sender retained live transfer ownership")
            _check(not owner.request_cancel_active_transfer()["accepted"], "dead sender accepted a stale cancellation action")
            state.update(block=False, blockAt=None, abort=False); state["attempts"].clear()
            retry = owner.send(send_plan, approved=True)
            _check(retry["ok"] and any(row.get("resumedParts", 0) for row in retry["files"]), "retry omitted exact receiver-acknowledged prefix")
            verify_receipt(retry)
            interruption = {"pid": child.pid, "returnCode": child.returncode, "persistedAcknowledgedOffset": prefix["acknowledgedOffset"]}
        # New wire attempt with an invalid ACK must not inherit the passed one.
        if category in {"permissions", "stale"}:
            state["acks"].clear(); state["fault"] = "permission" if category == "permissions" else "stale-prefix"
            refused = owner.send(send_plan, approved=True)
            _check(not refused["ok"] and refused["status"] == "failed" and refused["summary"]["acknowledgedParts"] == 0 and not any(x["remoteHashVerified"] for x in refused["files"]), "peer authorization or stale prefix invented remote integrity")
            verify_receipt(refused)
            _check(not owner.request_cancel_active_transfer()["accepted"], "completed failure retained stale cancellation ownership")
        state["acks"].clear(); state["fault"] = "bad-hash"
        failed = owner.send(send_plan, approved=True)
        _check(not failed["ok"] and failed["status"] == "failed" and all(not r.get("remoteHashVerified", False) for r in failed["files"]), "invalid upload ACK gained remote integrity")
        verify_receipt(failed)
        state["fault"] = ""; state["acks"].clear(); state["block"] = True; state["blockAt"] = None; state["abort"] = True
        ready.clear(); release.clear(); outcomes = []
        sender = threading.Thread(target=lambda: outcomes.append(owner.send(send_plan, approved=True))); sender.start()
        _check(ready.wait(10), "real sender did not reach pending upload boundary")
        state["cancelStatus"] = 403 if category == "permissions" else 204
        pending = owner.request_cancel_active_transfer()
        _check(pending["accepted"] and pending["cancelled"] is False and pending["finalState"] == "pending", "request claimed cancellation before sender terminal state")
        if category == "permissions":
            _check(not pending["remoteCancelAcknowledged"] and pending["remoteCancelHttpStatus"] == 403, "rejected peer cancellation claimed acknowledgment")
        if category == "concurrency":
            _reject(lambda: NearbySendService(root).send(plan, approved=True), (RuntimeError, ValueError))
        release.set(); sender.join(15)
        _check(not sender.is_alive() and len(outcomes) == 1 and outcomes[0]["status"] == "cancelled", "cancelled sender did not durably terminate")
        verify_receipt(outcomes[0])
        return {"explicitPort": port, "sourceBytes": len(body), "actualReceiverBytesVerified": True, "receiptPath": receipt_path, "invalidAckFailed": True, "cancelRequestPendingUntilSenderEnded": True, "interruptedSender": interruption, "physicalDeviceProof": False}
    finally:
        release.set(); server.shutdown(); server.server_close(); listener.join(3)


PURE_IDS = {"d.runtime.go-env.merge", "d.runtime.go-env.redact", "d.runtime.nas-setup.hosts", "d.runtime.nas-setup.users", "d.runtime.nas-setup.node-plan", "d.runtime.nas-setup.tls-command", "d.runtime.lane.aliases", "d.host.remote-transport"}
FAMILIES = {
    "pure-plans": (_pure, PURE_IDS, set(TEXT)),
    "bridge-refusal": (_bridge_refusal, {"desktop.bridge.allowlist"}, set(TEXT)),
    "impact": (_impact, {"impact." + x for x in ("dispatch-membership", "import-provenance", "index-provenance", "ui-call-evidence")}, CATEGORIES - {"offline"}),
    "diagnostics": (_diagnostics, {"desktop.debugger.bundle", "desktop.debugger.summary", "desktop.docs.evidence"}, CATEGORIES - {"offline"}),
    "demo": (_demo, {"desktop.demo.comparison", "desktop.demo.probe", "desktop.demo.export", "desktop.dashboard.artifact"}, CATEGORIES - {"offline"}),
    "auth-queue": (_auth_queue, {"d.runtime.auth-queue." + x for x in ("state", "persisted", "flow", "projection", "startup", "transition")}, CATEGORIES - {"offline"}),
    "circuit": (_circuit, {"d.runtime.circuit." + x for x in ("classification", "admission", "reporting", "transition", "reset", "worker")}, CATEGORIES - {"offline"}),
    "wrapper": (_wrapper, {"d.runtime.wrapper." + x for x in ("spec", "state", "event", "receipt", "replay")} | {"d.runtime.lineage.source"}, set(TEXT) | {"permissions", "stale", "concurrency", "interrupted"}),
    "onboarding-catalog": (_onboarding_catalog, {"onboarding.catalog-integrity", "onboarding.ordered-recommendations", "onboarding.choices-durable"}, CATEGORIES - {"offline"}),
    "onboarding-manifest": (_manifest, {"onboarding.manifest-safety", "onboarding.signature-authority"}, CATEGORIES - {"offline"}),
    "onboarding-staging": (_staging, {"onboarding.verified-staging", "onboarding.resume-reuse", "onboarding.pause"}, set(TEXT) | {"permissions", "stale", "interrupted", "concurrency"}),
    "onboarding-addon": (_addon, {"onboarding.addon-isolation", "onboarding.addon-recovery"}, CATEGORIES - {"offline"}),
    "policy": (_policy, {"d.host.policy-owner", "d.host.policy-root", "d.host.policy-startup"}, CATEGORIES - {"offline"}),
    "metadata": (_metadata, {"d.runtime.profile.resolve", "d.host.skill-provenance", "d.host.selected-context"}, set(TEXT) | {"permissions", "stale", "interrupted", "concurrency"}),
    "package": (_package, {"d.runtime.package.export"}, set(TEXT)),
    "local-copy": (_local_copy, {"d.runtime.bridge." + x for x in ("bytes", "envelope", "receive")} | {"d.runtime.transfer." + x for x in ("file", "directory", "receipt")}, set(TEXT) | {"permissions", "stale", "interrupted", "concurrency"}),
    "release": (_release, {"release." + x for x in ("external-declarations", "installer-budget", "signed-envelope", "staging-boundary", "vite-physical-paths")}, CATEGORIES - {"offline"}),
    "proof-boundary": (_proof_boundary, {"proofs.manual-input", "proofs.manual-output", "proofs.saved-credential-boundary", "proofs.scratch-isolation"}, CATEGORIES - {"offline"}),
    "proof-coverage": (_coverage_gate, {"proofs.source-revalidation", "proofs.retirement-coverage"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "cache-remaining": (_cache_remaining, {"d.runtime.cache." + x for x in ("bootstrap", "compatibility", "plan", "import", "read")}, set(TEXT) | {"concurrency", "permissions", "stale", "interrupted"}),
    "gateway-remaining": (_gateway_remaining, {"desktop.gateway." + x for x in ("heartbeat", "route", "event", "reconcile")}, CATEGORIES - {"offline"}),
    "stages-remaining": (_stages_remaining, {"d.host.stage-parallel", "d.host.stage-receipt", "d.host.stage-tool-authority"}, CATEGORIES - {"offline"}),
    "host-state": (_host_state, {"d.host.nearby-history", "d.host.nearby-recovery", "d.host.artifact-serving"}, set(TEXT) | {"concurrency", "permissions", "interrupted", "stale"}),
    "nearby": (_nearby, {"d.nearby." + x for x in ("hash-bound-plan", "legacy-migration", "resume-integrity", "chunk-ack-integrity", "durable-ack-prefix", "terminal-receipt", "cancel-truth")}, CATEGORIES),
}

# A grouped builder runs several owners for economy. An adverse observation
# only binds the owners it actually perturbs; ordinary companion calls never
# turn an unrelated missing fixture into a passed invariant.
ADVERSE_BINDINGS = {
    **{("proof-boundary", category): {"proofs.saved-credential-boundary", "proofs.scratch-isolation"} for category in CATEGORIES - set(TEXT)},
    **{("release", category): {"release.external-declarations", "release.installer-budget"} for category in CATEGORIES - set(TEXT)},
    **{("onboarding-catalog", category): {"onboarding.choices-durable"} for category in CATEGORIES - set(TEXT)},
    **{("onboarding-manifest", category): {"onboarding.signature-authority"} for category in CATEGORIES - set(TEXT)},
    ("impact", "permissions"): {"impact.index-provenance"},
    ("impact", "stale"): {"impact.index-provenance"},
    ("impact", "concurrency"): {"impact.index-provenance"},
    ("impact", "interrupted"): {"impact.index-provenance"},
    **{("demo", category): {"desktop.demo.export", "desktop.dashboard.artifact"} for category in CATEGORIES - set(TEXT)},
    ("diagnostics", "permissions"): {"desktop.docs.evidence", "desktop.debugger.bundle"},
    ("diagnostics", "stale"): {"desktop.docs.evidence", "desktop.debugger.bundle"},
    ("diagnostics", "concurrency"): {"desktop.debugger.bundle", "desktop.docs.evidence"},
    ("diagnostics", "interrupted"): {"desktop.debugger.bundle", "desktop.docs.evidence"},
    ("metadata", "permissions"): {"d.runtime.profile.resolve", "d.host.skill-provenance"},
    ("metadata", "stale"): {"d.runtime.profile.resolve", "d.host.skill-provenance"},
    ("metadata", "interrupted"): {"d.runtime.profile.resolve", "d.host.skill-provenance"},
    ("metadata", "concurrency"): {"d.runtime.profile.resolve", "d.host.skill-provenance"},
    **{("wrapper", category): {"d.runtime.wrapper.state", "d.runtime.wrapper.replay", "d.runtime.lineage.source"} for category in CATEGORIES - set(TEXT)},
    ("local-copy", "permissions"): {"d.runtime.bridge.bytes", "d.runtime.bridge.envelope", "d.runtime.bridge.receive", "d.runtime.transfer.file", "d.runtime.transfer.directory", "d.runtime.transfer.receipt"},
    ("local-copy", "interrupted"): {"d.runtime.bridge.bytes", "d.runtime.bridge.envelope", "d.runtime.bridge.receive", "d.runtime.transfer.file", "d.runtime.transfer.directory", "d.runtime.transfer.receipt"},
    ("local-copy", "stale"): {"d.runtime.bridge.bytes", "d.runtime.bridge.envelope", "d.runtime.bridge.receive", "d.runtime.transfer.file", "d.runtime.transfer.directory", "d.runtime.transfer.receipt"},
    ("local-copy", "concurrency"): {"d.runtime.bridge.bytes", "d.runtime.bridge.envelope", "d.runtime.bridge.receive", "d.runtime.transfer.file", "d.runtime.transfer.directory", "d.runtime.transfer.receipt"},
    ("host-state", "permissions"): {"d.host.nearby-recovery", "d.host.nearby-history"},
    ("host-state", "interrupted"): {"d.host.nearby-history", "d.host.nearby-recovery"},
    ("host-state", "concurrency"): {"d.host.nearby-history", "d.host.nearby-recovery"},
    ("host-state", "stale"): {"d.host.nearby-recovery", "d.host.nearby-history", "d.host.artifact-serving"},
}


def run(root, contracts, categories):
    from .proof_credential_guard import install
    base = Path(root).resolve(); base.mkdir(parents=True, exist_ok=True); install(base)
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        selected = sorted(identities & set(contracts))
        if not selected:
            continue
        for category in categories:
            if category not in supported:
                continue
            bound = sorted(set(selected) & ADVERSE_BINDINGS.get((family, category), set(selected)))
            if not bound:
                continue
            scratch = base / ".agent_control/proofs" / ("c7d-desktop-" + family + "-" + category)
            scratch.mkdir(parents=True, exist_ok=False)
            row = {"id": "c7d-desktop." + family + "." + category, "category": category, "contracts": bound,
                   "boundary": "Owned local production calls with independent argument/artifact observations; no rendered, native, provider or public release proof"}
            try:
                with _environment({"FLUXIO_CLUSTER_ROOT": str(scratch), "FLUXIO_CONTROL_PROJECT_ROOT": str(scratch), "FLUXIO_NAS_VOLUME_ROOT": str(scratch / "no-network/volume"), "FLUXIO_WINDOWS_NAS_VOLUME_MIRROR": str(scratch / "no-network/mirror"), "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0"}):
                    row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "traceback": traceback.format_exc()[-5000:]})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if category in TEXT:
        return None
    pure_invariants = {
        "proofs.manual-input": "before_action validates explicit arguments against already-loaded grounded schemas before any dispatcher effect",
        "proofs.manual-output": "after_action validates an explicit returned value against already-loaded grounded result schemas before delivery",
        "release.signed-envelope": "checkSignedEnvelope verifies supplied manifest/signature/public-key/comment bytes synchronously in memory; key provisioning and artifact persistence have separate owners",
        "release.vite-physical-paths": "Vite configuration evaluates the selected checkout's physical root and returns path values; it starts no server, child, writer or persistent revision",
        "release.staging-boundary": "validateReleaseOutput and validateSigningKeyPath synchronously admit or refuse explicit paths before release copying or key reading; allocated staged releases and portable runtime execution have separate obligations",
        "d.runtime.package.export": "package __getattr__ exposes static service class identities through Python's import mechanism; this invariant has no mutable workspace input, saved state writer, child operation or authorization decision",
        "d.runtime.wrapper.receipt": "execution receipt construction projects an explicitly supplied wrapper state; reading and replaying logs belong to state/replay invariants",
        "d.host.artifact-serving": "artifact decoration applies path containment and existing-file metadata to supplied rows; serving file content and HTTP authorization have separate owners",
    }
    if identity in pure_invariants:
        return {"kind": "not_applicable", "reason": f"Audited exact {identity} applicability: {pure_invariants[identity]}. The {category} strategy has no corresponding operation at this invariant's site."}
    if identity == "desktop.gateway.route" and category == "interrupted":
        return {"kind":"not_applicable","reason":"Audited route_gateway_job reads a current registry and returns a routing decision synchronously. It does not claim a worker, write job state, launch a child, or own a resumable operation; stopped job mutations are separately covered by reconcile/event/heartbeat invariants."}
    if identity in PURE_IDS or identity == "desktop.bridge.allowlist" or identity in {"desktop.demo.comparison", "desktop.demo.probe", "desktop.debugger.summary", "d.host.selected-context", "d.runtime.wrapper.spec", "d.runtime.wrapper.event", "d.runtime.circuit.classification", "onboarding.catalog-integrity", "onboarding.ordered-recommendations", "onboarding.manifest-safety", "impact.dispatch-membership", "impact.import-provenance", "impact.ui-call-evidence"}:
        return {"kind": "not_applicable", "reason": f"Inspected {identity} receives explicit in-memory arguments and returns/refuses synchronously before external effects; {category} has no owned filesystem mutation, transport, process lifecycle or revision on this invariant."}
    if category == "offline" and identity in {"desktop.debugger.bundle", "desktop.demo.export", "desktop.dashboard.artifact", "impact.dispatch-membership", "impact.import-provenance", "impact.index-provenance", "impact.ui-call-evidence"}:
        return {"kind": "not_applicable", "reason": f"Inspected {identity} exclusively reads or writes selected local artifact/source paths; its production owner has no transport/network branch."}
    if category == "offline" and identity in set().union(*(entry[1] for name, entry in FAMILIES.items() if name != "nearby")):
        return {"kind": "not_applicable", "reason": f"Inspected exact local invariant {identity}: its declared effect uses explicit in-memory arguments or selected local files/SQLite/process observations. No operation at its owning site requires peer, provider or public-service connectivity; transport execution has separate invariants."}
    return None
