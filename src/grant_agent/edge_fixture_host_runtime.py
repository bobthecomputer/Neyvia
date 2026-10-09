"""Generated host/runtime journeys with confined files, SQLite and real HTTP.

No fixture starts an installed provider or reads an operator account. Native
device completions below attest the local control-plane result only; remote
device execution is deliberately never claimed.
"""
from __future__ import annotations
from .subprocess_utils import hidden_windows_subprocess_kwargs

import copy
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TEXT = {"empty": "", "huge": "fixture " * 20000, "unicode": "雪🙂e\u0301 العربية\u202e"}
from .proof_ports import c7_port_block
PORT = c7_port_block(int(os.environ.get('NEYVIA_C7_PORT', '48743')))[-2]


def _check(value, message):
    if not value:
        raise AssertionError(message)


def _reject(action, classes=(ValueError, PermissionError, KeyError, OSError)):
    try:
        action()
    except classes as error:
        return type(error).__name__
    raise AssertionError("Actual production owner admitted refused action")


@contextmanager
def _sharing(path):
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path.resolve()), 0x80000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Exclusive fixture source handle failed")
    try:
        _reject(path.read_bytes, (PermissionError,))
        yield
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def _environment(values):
    before = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _native(root):
    from .native_tools import NativeToolRegistry
    from .proof_credential_guard import prepare_broker_fixture
    # run() installs the guard for the enclosing scratch workspace. This root
    # belongs to its explicit .agent_control/proofs state, including home paths.
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return NativeToolRegistry(root, nas_root=root / "no-network-mapping", allow_local_nas_root=False)


def _projection(root, category):
    from .web_backend_workspace import decorate_mission_events
    from .agent_delta import merge_agent_deltas, synthesize_agent_deltas
    from .neyvia_runtime_invocation import build_selected_context_packet
    text = TEXT[category]
    count = 128 if category == "huge" else 3
    source = {"events": [{"missionId": f"fixture-{i}", "timestamp": "2026-01-01T00:00:00Z", "kind": "observation", "actor": "fixture", "message": text} for i in range(count)]}
    original = copy.deepcopy(source)
    digest_text = lambda value: hashlib.sha256(value.encode()).hexdigest()
    actual = decorate_mission_events(source, sha256_hex=digest_text)
    _check(source == original and len(actual["events"]) == count, "event projection mutated source or lost events")
    for row, event in zip(actual["events"], original["events"]):
        identity = {"missionId": event["missionId"], "at": event["timestamp"], "kind": event["kind"], "actor": event["actor"], "message": event["message"] or None}
        wanted = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:24]
        _check(row["eventId"] == wanted, "canonical observed identity differs")
    retained = decorate_mission_events({"events": [{"eventId": text or "caller", "message": text}]}, sha256_hex=digest_text)
    _check(retained["events"] == [{"eventId": text or "caller", "message": text}], "caller event identity overwritten")
    first = {"claims": [{"id": "same", "value": "older"}], "evidence": [{"id": str(i), "value": text} for i in range(count)], "notes": [text]}
    last = {"claims": [{"id": "same", "value": text}], "blockers": [{"id": "block", "value": text}], "notes": [text]}
    merged = merge_agent_deltas(first, last).as_dict()
    _check(merged["claims"] == last["claims"] and merged["evidence"] == first["evidence"] and merged["blockers"] == last["blockers"], "delta replaced evidence or changed later-wins identity")
    synthesis = synthesize_agent_deltas([{"nodeId": "one", "resultSummary": {"delta": first}, "transcript": "must not appear"}, {"nodeId": "two", "resultSummary": {"delta": last}}])
    _check(synthesis["status"] == "blocked" and synthesis["merged"] == merged and not synthesis["transcriptsIncluded"] and "must not appear" not in json.dumps(synthesis), "synthesis used transcript or lost typed blockers")
    rows = [{"sourceId": str(i), "content": text, "sourceSha256": "b" * 64, "importId": "fixture-import"} for i in range(count)]
    packet = build_selected_context_packet(rows, max_items=2, max_chars=81)
    expected = text.strip()[:81]
    _check(len(packet["selected"]) <= 2 and sum(len(r["content"]) for r in packet["selected"]) <= 81, "selected context exceeded real bounds")
    _check((packet["selected"][0]["content"] if packet["selected"] else "") == expected, "context changed selected source bytes")
    for item in packet["selected"]:
        _check(item["contentHash"] == hashlib.sha256(item["content"].encode()).hexdigest(), "selected row digest lost")
    return {"events": count, "evidenceItems": len(merged["evidence"]), "contextItems": packet["itemCount"], "transcriptsIncluded": False}


def _profile_platform(root, category):
    from .profiles import ProfileRegistry
    from .platform_config import PlatformConfig
    text = TEXT[category]
    path = root / "profiles.json"
    payload = {"default_profile": "default", "profiles": {"explicit": {"description": text, "agent": {"max_tokens": 9001}}, "workspace": {"agent": {"max_tokens": 7001}}, "default": {"agent": {"max_tokens": 5001}}}, "workspace_profiles": [{"pattern": "*owned*", "profile": "workspace"}]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    profiles = ProfileRegistry(path)
    _check(profiles.resolve("explicit", root / "owned") is profiles.profiles["explicit"] and profiles.resolve("missing", root / "owned") is profiles.profiles["workspace"] and profiles.resolve(None, root / "unmatched") is profiles.profiles["default"], "profile explicit/workspace/default precedence changed")
    values = {"FLUXIO_NAS_VOLUME_ROOT": str(root / "hypothetical-remote"), "FLUXIO_WINDOWS_NAS_VOLUME_MIRROR": str(root / "hypothetical-mirror"), "FLUXIO_NAS_PROJECT_NAME": text[:16000].strip() or "fixture-project"}
    with _environment(values):
        platform = PlatformConfig.from_env(root)
    _check(platform.workspace_root == root and platform.nas_project_name == values["FLUXIO_NAS_PROJECT_NAME"], "explicit platform roots/name lost")
    selected = platform.nas_project_root / "part.txt"
    candidates = platform.path_candidates(selected.as_posix())
    _check(root / "part.txt" in candidates and platform.windows_nas_project_root / "part.txt" in candidates and len({str(p).lower() for p in candidates}) == len(candidates), "pure path candidates lost local projection or duplicate identity")
    _check(platform.coerce_path("prefix:C:/fixture/" + text, posix=True).as_posix() == Path("/mnt/c/fixture/" + text.strip()).as_posix(), "explicit POSIX drive coercion lost text")
    _check(not platform.nas_volume_root.exists() and not platform.windows_nas_volume_mirror.exists(), "pure path projection performed storage activity")
    return {"profileBudget": profiles.resolve("explicit").agent.max_tokens, "pathCandidates": [p.as_posix() for p in candidates], "networkActivity": False}


def _cache(root, category):
    import blake3
    from .p2p_cache import P2PCacheService
    text = TEXT.get(category, "fixture cache")
    path = root / "cache.json"
    config = {"schema": "neyvia.p2p-cache-config/v1", "transport": {"name": "Iroh", "version": "1.0.3", "executable": str(root / "absent-sidecar.exe"), "executableSha256": "0" * 64, "stateRoot": str(root / "sidecar-state"), "storeRoot": str(root / "sidecar-store")}, "cache": {"root": ".agent_control/cache-objects", "maxImportBytes": 2000000, "maxTextReadBytes": 65536}, "policy": {"allowedKinds": ["artifact", "context-chunk"], "peers": [], "publicDiscoveryDefault": False, "publicRelayDefault": False}}
    path.write_text(json.dumps(config), encoding="utf-8")
    service = P2PCacheService(root, config_path=path)
    boot = service.bootstrap(); compatibility = service.compatibility_snapshot()
    _check(compatibility["transport"]["version"] == "1.0.3" and compatibility["transport"]["sidecarConfigured"] and not compatibility["transport"]["sidecarExecutablePresent"] and not compatibility["transport"]["sidecarAvailable"] and compatibility["policy"]["approvedPeers"] == 0 and not compatibility["policy"]["publicDiscoveryDefault"] and not compatibility["policy"]["publicRelayDefault"] and not compatibility["limitations"]["remoteFetchConfigured"] and not compatibility["limitations"]["remotePublishImplemented"], "cache compatibility invented configured remote availability/publication")
    _check(boot["objects"] == boot["bytes"] == boot["pinned"] == 0 and not boot["remoteLookupReady"] and not service.index_path.exists(), "empty bootstrap allocated index or invented objects/transport")
    source = root / "source.txt"; source.write_text(text, encoding="utf-8")
    raw = source.read_bytes(); digest = blake3.blake3(raw).hexdigest()
    if category == "permissions":
        with _sharing(source):
            _reject(lambda: service.plan_import(source), (PermissionError,))
        _check(not service.index_path.exists(), "denied source observation allocated cache index")
    plan = service.plan_import(source, kind="context-chunk", pin=True)
    _check(plan["objectHash"] == digest and plan["sourceSize"] == len(raw) and not plan["summary"]["networkRequired"] and not plan["summary"]["remotePublish"], "cache plan lost real source/hash/publication boundary")
    refused = service.import_object(plan, approved=False)
    _check(refused["status"] == "approval_required" and not service.index_path.exists() and not service._object_path(digest).exists(), "unapproved import admitted source bytes")
    if category == "stale":
        source.write_text(text + " changed", encoding="utf-8")
        _reject(lambda: service.import_object(plan, approved=True))
        _check(not service._object_path(digest).exists(), "stale source imported under old digest")
        source.write_bytes(raw)
        plan = service.plan_import(source, kind="context-chunk", pin=True)
    interrupted_worker = None
    if category == "interrupted":
        marker = root / "staged.json"
        plan_path = root / "admitted-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        child_code = """import json,sys,threading
from pathlib import Path
from grant_agent.p2p_cache import P2PCacheService
root=Path(sys.argv[1]); config=Path(sys.argv[2]); marker=Path(sys.argv[3]); plan=Path(sys.argv[4])
class InterruptedOwner(P2PCacheService):
 def _copy_source_to_descriptor(self,*args,**kwargs):
  result=super()._copy_source_to_descriptor(*args,**kwargs)
  marker.write_text(json.dumps({'copiedRealSource':True}),encoding='utf-8')
  threading.Event().wait(60)
  return result
InterruptedOwner(root,config_path=config).import_object(json.loads(plan.read_text(encoding='utf-8')),approved=True)
"""
        process = subprocess.Popen([sys.executable, "-c", child_code, str(root), str(path), str(marker), str(plan_path)], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, **hidden_windows_subprocess_kwargs())
        try:
            deadline = time.monotonic() + 30
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            _check(marker.exists(), "owned cache worker did not reach actual staged-byte interruption boundary")
            staged = list(service._object_path(digest).parent.glob(f".{digest}.*.tmp"))
            _check(len(staged) == 1 and staged[0].read_bytes() == raw and not service._object_path(digest).exists(), "interrupted staging fabricated committed CAS object")
        finally:
            if process.poll() is None:
                process.terminate()
            stdout, stderr = process.communicate(timeout=10)
        interrupted_worker = {"pid": process.pid, "returnCode": process.returncode, "realStagedBytes": len(raw)}
        _check(process.returncode != 0 and not service.bootstrap()["objects"], "terminated cache worker left uncommitted bytes admitted")
        _reject(lambda: P2PCacheService(root, config_path=path).read_text(digest))
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: P2PCacheService(root, config_path=path).import_object(plan, approved=True), range(12)))
    else:
        receipts = [service.import_object(plan, approved=True)]
    target = service._object_path(digest)
    _check(target.read_bytes() == raw and all(r["objectHash"] == digest and r["integrityVerified"] and not r["networkUsed"] for r in receipts), "cache import returned before admitting exact verified bytes")
    repeat = P2PCacheService(root, config_path=path).import_object(plan, approved=True)
    _check(repeat["deduplicated"] and not repeat["copied"], "reopened duplicate import recopied source")
    observed = P2PCacheService(root, config_path=path).read_text(digest, offset=0, length=23)
    _check(observed["bytesRead"] == len(raw[:23]) and observed["text"] == raw[:23].decode("utf-8", errors="replace") and observed["truncated"] == (len(raw) > 23) and not observed["networkUsed"], "cache read changed actual admitted byte range")
    summary = service.bootstrap()
    _check(summary["objects"] == 1 and summary["bytes"] == len(raw) and summary["pinned"] == 1, "fresh cache summary disagrees with real object bytes")
    # Integrity metadata is proved with an owned inert file. It is never
    # launched and grants no peer connection; configured is not reachable.
    sidecar = root / "absent-sidecar.exe"
    sidecar.write_bytes(raw)
    config["transport"]["executableSha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(config), encoding="utf-8")
    metadata_owner = P2PCacheService(root, config_path=path)
    actual_metadata = metadata_owner.compatibility_snapshot()
    _check(actual_metadata["transport"]["sidecarExecutablePresent"] and actual_metadata["transport"]["sidecarHashMatch"] and actual_metadata["transport"]["sidecarAvailable"] and not metadata_owner.bootstrap()["remoteLookupReady"], "actual pinned file integrity invented approved peer reachability")
    if category == "permissions":
        with _sharing(sidecar):
            denied_metadata = metadata_owner.compatibility_snapshot()
        _check(not denied_metadata["transport"]["sidecarAvailable"], "unreadable pinned file retained verified integrity")
    if category == "stale":
        sidecar.write_bytes(raw + b" changed")
        _check(not metadata_owner.compatibility_snapshot()["transport"]["sidecarHashMatch"], "changed pinned file retained original admission hash")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            snapshots = list(pool.map(lambda _: metadata_owner.compatibility_snapshot(), range(12)))
        _check(all(row == actual_metadata for row in snapshots), "concurrent immutable integrity observations diverged")
    _reject(lambda: service.read_text(digest, offset=-1))
    target.write_bytes(raw + b"tampered")
    _reject(lambda: service.read_text(digest), (RuntimeError,))
    return {"objectHash": digest, "bytes": len(raw), "concurrentImports": len(receipts), "deduplicated": repeat["deduplicated"], "tamperedReadRefused": True, "transportObservedMissing": not boot["remoteLookupReady"], "interruptedWorker": interrupted_worker}


def _tools(root, category):
    text = TEXT.get(category, "selected source")
    registry = _native(root)
    source = root / "selected.txt"; source.write_text(text, encoding="utf-8")
    raw = source.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    before = raw
    payload = {"path": "selected.txt", "maxChars": 17}
    def read(_):
        return registry.call("workspace.read", payload)
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(read, range(12)))
    else:
        receipts = [read(0)]
    for receipt in receipts:
        _check(receipt["ok"] and receipt["result"]["content"] == text[:17] and receipt["result"]["sha256"] == digest and json.loads(Path(receipt["receipt_path"]).read_text(encoding="utf-8")) == receipt, "actual Native read/protocol receipt changed source content or durable result")
    invalid = registry.call("workspace.read", {"path": "selected.txt", "maxChars": "wrong"})
    _check(not invalid["ok"] and invalid["proofs"]["phase"] == "validation" and source.read_bytes() == before, "typed invalid argument reached dispatcher or changed source")
    escaped = registry.call("workspace.read", {"path": "../outside.txt"})
    _check(not escaped["ok"], "Native selected-root containment escaped")
    if category == "permissions":
        with _sharing(source):
            denied = read(0)
        _check(not denied["ok"] and "Permission" in denied["failure"].get("exceptionType", denied["error"]), "actual OS source denial did not yield failed receipt")
    if category == "stale":
        source.write_text(text + " replacement", encoding="utf-8")
        stale = registry.call("workspace.read", {**payload, "expectedSha256": digest})
        _check(not stale["ok"] and registry.call("workspace.read", payload)["result"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest(), "old source digest admitted a changed range")
    spec = registry._specs["workspace.read"]
    described = registry.describe("workspace.read")
    _check(described["inputSchema"] == spec.input_schema and described["name"] == spec.name and described["requires_approval"] == spec.requires_approval, "Native actual specification projection changed")
    # Check the real catalog; explicit owned NAS projection cannot contact NAS.
    listed = registry.list_tools(include_unavailable=True, include_schemas=False)
    _check(all("inputSchema" not in r for r in listed) and {r["name"] for r in listed} == set(registry._specs), "progressive Native catalog omitted spec or leaked schemas")
    found = registry.search("workspace read", limit=2)
    _check(len(found) <= 2 and all(r["name"] in registry._specs for r in found), "Native search invented tool identity or ignored bound")
    return {"receiptPaths": [r["receipt_path"] for r in receipts], "sourceSha256": digest, "actualCatalogTools": len(listed), "typedRefusal": invalid["proofs"]["phase"]}


def _commands(root, category):
    from .native_pairing import NativePairingStore
    from .native_device_commands import NativeDeviceCommandStore
    text = TEXT.get(category, "command fixture")
    pairing = NativePairingStore(root)
    pair = pairing.create("phone", scopes=["device.commands"])
    device = pairing.redeem(pair["pairingId"], pair["pairingToken"], "Owned control-plane fixture")
    store = NativeDeviceCommandStore(root)
    device_id, credential = device["deviceId"], device["deviceSecret"]
    context = {"actor_id": "agent:fixture", "session_id": "session:fixture", "run_id": "run:fixture"}
    advertised = store.publish_capabilities(device_id, credential, ["app.open", "notification.show"])
    _check(advertised["capabilities"] == ["app.open", "notification.show"] and not advertised["providerSecretsIncluded"], "paired capabilities widened or exposed provider secret")
    _reject(lambda: store.publish_capabilities(device_id, "wrong", ["app.open"]))
    _reject(lambda: store.request_approval(device_id, "unadvertised.operation", **context))
    # Rejected huge frames have no approved or queued command side effects.
    if category == "huge":
        _reject(lambda: store.request_approval(device_id, "app.open", arguments={"message": text}, **context))
        text = text[:2000]
    args = {"route": "agent", "message": text}
    def queued(index):
        approval = store.request_approval(device_id, "app.open", arguments=args, **context)
        _reject(lambda: store.decide_approval(approval["approvalId"], decision="approved", decided_by="human:fixture", human_confirmed=False))
        store.decide_approval(approval["approvalId"], decision="approved", decided_by="human:fixture", human_confirmed=True)
        values = {"arguments": args, "idempotency_key": f"fixture-command-{index:04d}", "approval_id": approval["approvalId"], **context}
        _reject(lambda: store.enqueue(device_id, "app.open", **{**values, "run_id": "run:foreign"}))
        result = store.enqueue(device_id, "app.open", **values)
        _check(store.enqueue(device_id, "app.open", **values)["commandId"] == result["commandId"], "idempotent observer minted a second command")
        _reject(lambda: store.enqueue(device_id, "app.open", **{**values, "arguments": {"route": "changed"}}))
        _reject(lambda: store.enqueue(device_id, "app.open", **{**values, "idempotency_key": f"different-{index:04d}"}))
        return result
    primary = queued(0)
    if category == "concurrency":
        def claim(_):
            return NativeDeviceCommandStore(root).claim(device_id, credential)
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = [r for r in pool.map(claim, range(12)) if r]
        _check(len(claims) == 1, "fresh consumers delivered duplicate device claim")
        claim = claims[0]
    else:
        claim = store.claim(device_id, credential)
    _check(claim and store.claim(device_id, credential) is None and claim["claimExpiresAt"] <= claim["expiresAt"], "single-flight or bounded human claim lease failed")
    # Produce a real local handling artifact then attest its control-plane result.
    effect = root / "handled.json"; effect.write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
    actual = {"localEffectSha256": hashlib.sha256(effect.read_bytes()).hexdigest(), "remoteExecutionClaimed": False}
    completion = store.complete(device_id, credential, claim["commandId"], claim["claimId"], status="succeeded", result=actual)
    reopened = NativeDeviceCommandStore(root).get(primary["commandId"])
    _check(reopened == completion and completion["status"] == "succeeded" and completion["result"] == actual and json.loads(effect.read_text(encoding="utf-8")) == args, "completion changed actual local result or fresh lifecycle state")
    cancelled = queued(1)
    _reject(lambda: store.cancel(cancelled["commandId"], **context, cancelled_by="human:fixture", human_confirmed=False))
    store.cancel(cancelled["commandId"], **context, cancelled_by="human:fixture", human_confirmed=True)
    _check(store.claim(device_id, credential) is None and store.get(cancelled["commandId"])["status"] == "cancelled", "cancelled queued command later delivered")
    pending = queued(2)
    store.publish_capabilities(device_id, credential, ["notification.show"])
    _check(store.claim(device_id, credential) is None and store.get(pending["commandId"])["status"] == "rejected", "withdrawn advertised capability retained delivery authority")
    store.publish_capabilities(device_id, credential, ["app.open"])
    uncertain = queued(3); active = store.claim(device_id, credential)
    with store.connection(immediate=True) as db:
        db.execute("UPDATE device_commands SET claim_expires_at='2000-01-01T00:00:00Z' WHERE command_id=?", (uncertain["commandId"],))
    terminal = NativeDeviceCommandStore(root).get(uncertain["commandId"])
    _check(terminal["status"] == "uncertain" and not terminal["automaticRetry"] and not terminal["executionProven"] and store.claim(device_id, credential) is None, "expired in-flight claim replayed or invented completion")
    _reject(lambda: store.request_approval(device_id, "app.open", arguments={"apiToken": "synthetic-secret-field"}, **context))
    with sqlite3.connect(store.path) as db:
        serialized = " ".join(str(row) for row in db.execute("SELECT * FROM device_commands").fetchall())
    _check(credential not in serialized and pair["pairingToken"] not in serialized and "fixture-command-0000" not in serialized, "device authority or raw idempotency string persisted")
    return {"completedCommand": completion["commandId"], "result": actual, "uncertainCommand": terminal["commandId"], "singleFlight": True, "remoteExecutionProven": False}


def _preview(root, category):
    text = TEXT.get(category, "offline fixture")
    registry = _native(root)
    body = ("<html><title>Fixture</title><body>" + text + "</body></html>").encode()
    observations = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observations.append(self.path)
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    url = f"http://127.0.0.1:{PORT}/fixture"
    try:
        receipt = registry.call("preview.inspect", {"url": url, "mode": "bytes", "offset": 0})
        _check(receipt["ok"] and receipt["result"]["contentSha256"] == hashlib.sha256(body).hexdigest() and receipt["result"]["status"] == 200 and observations, "real preview HTTP bytes/status/digest changed")
        _check(json.loads(Path(receipt["receipt_path"]).read_text(encoding="utf-8")) == receipt, "preview receipt differs from actual persisted result")
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=10)
    if category == "offline":
        denied = registry.call("preview.inspect", {"url": url, "mode": "bytes", "offset": 0})
        _check(not denied["ok"] and len(observations) == 1, "closed endpoint fabricated HTTP observation")
    return {"port": PORT, "actualRequests": observations, "bodyBytes": len(body), "httpDigest": hashlib.sha256(body).hexdigest(), "closedEndpointRefused": category == "offline"}


def _gateway(root, category):
    from . import desktop_gateway as gateway
    from .cluster import ClusterRegistry
    text = TEXT.get(category, "gateway fixture")
    host_id = "owned-pc"
    receipt = gateway.record_desktop_gateway_heartbeat(root, host_id=host_id, label=text)
    registry = ClusterRegistry(root)
    host = registry.get_host(host_id)
    _check(host["hostType"] == "pc_gateway" and host["online"] and host["label"] == (text or host_id) and host["maxConcurrentJobs"] == 0 and set(host["capabilities"]) == set(receipt["capabilities"]), "durable heartbeat differs from actual gateway identity/capabilities")
    heartbeat_rows = [json.loads(line) for line in (root / gateway.DESKTOP_GATEWAY_HEARTBEATS_PATH).read_text(encoding="utf-8").splitlines()]
    _check(heartbeat_rows == [receipt], "heartbeat did not persist exact admitted result")
    controller = gateway.route_gateway_job(root, job_kind=text, required_capabilities=["artifact.write"])
    selected = gateway.route_gateway_job(root, job_kind=text, required_capabilities=["browser.verify", "frontend.build"])
    refused = gateway.route_gateway_job(root, job_kind=text, required_capabilities=["browser.verify", "unowned.feature"])
    _check(controller["decision"] == "controller" and not controller["assignedHost"] and selected["decision"] == "pc_gateway" and selected["assignedHost"] == host_id and refused["decision"] == "queued_proof_gap", "actual gateway capability route widened authority")
    job_id = "owned-proof-job"
    registry.upsert_job(job_id=job_id, job_kind="browser.verify", required_capabilities=["browser.verify"], payload={"request": text})
    def event(index):
        return gateway.record_gateway_event(root, host_id=host_id, job_id=job_id, event_kind="observed", message=text, payload={"index": index})
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            events = list(pool.map(event, range(12)))
    else:
        events = [event(0)]
    journal = gateway.load_gateway_events(root, job_id=job_id, limit=100)
    _check(len(journal) == len(events) and all(row in journal for row in events), "concurrent admitted event missing from real UTF-8 journal")
    cluster_events = registry.list_events(job_id=job_id, limit=100)
    _check(sum(r["kind"] == "gateway.observed" for r in cluster_events) == len(events), "gateway journal differs from durable cluster event count")
    if category == "permissions":
        path = root / gateway.DESKTOP_GATEWAY_EVENTS_PATH
        before = path.read_bytes()
        with _sharing(path):
            _reject(lambda: event(99), (PermissionError,))
        _check(path.read_bytes() == before, "denied gateway append changed admitted journal")
    with registry._connect() as db:
        db.execute("UPDATE jobs SET status='running', assigned_host=? WHERE job_id=?", (host_id, job_id))
        db.execute("UPDATE hosts SET last_heartbeat_at='2000-01-01T00:00:00Z' WHERE host_id=?", (host_id,))
    disappeared = gateway.route_gateway_job(root, job_kind=text, required_capabilities=["browser.verify"])
    converted = gateway.reconcile_disappeared_gateway_jobs(root)
    actual = ClusterRegistry(root).get_job(job_id)
    _check(disappeared["decision"] == "queued_proof_gap" and converted["convertedCount"] == 1 and actual["status"] == "queued" and "Queued proof gap" in actual["statusDetail"], "expired gateway retained execution/proof authority")
    _check(gateway.reconcile_disappeared_gateway_jobs(root)["convertedCount"] == 0, "reopened reconciliation requeued completed conversion")
    _check(any(r["kind"] == "gateway.proof_gap_queued" for r in registry.list_events(job_id=job_id, limit=100)), "proof gap conversion did not persist causal event")
    return {"hostId": host_id, "admittedEvents": len(events), "jobId": job_id, "freshConsumerStatus": actual["status"], "gatewayDisappearedRefused": True, "remoteExecutionClaimed": False}


def _stages(root, category):
    from .native_tools import register_with_progressive_surface
    from .progressive_tools import ProgressiveToolSurface
    from .neyvia_stage_scheduler import build_progressive_step_handler, execute_neyvia_stages, default_step_handler
    text = TEXT.get(category, "real stage content")
    registry = _native(root)
    source = root / "input.txt"; source.write_text(text, encoding="utf-8")
    surface = ProgressiveToolSurface(); register_with_progressive_surface(surface, registry)
    handler = build_progressive_step_handler(root, progressive=surface)
    read_step = {"step_id": "observed-read", "action": "tool", "tool": "workspace.read", "risk": "read", "arguments": {"path": "input.txt", "maxChars": 11}}
    read = handler(read_step, {})
    _check(read["ok"] and read["metadata"]["routed"] == "progressive" and read["metadata"]["result"]["result"]["content"] == text[:11], "compiled handler did not observe real Native workspace bytes")
    write_step = {"step_id": "denied-write", "action": "tool", "tool": "workspace.write", "risk": "workspace_write", "arguments": {"path": "written.txt", "content": text}}
    denied = handler(write_step, {})
    _check(not denied["ok"] and denied["metadata"].get("approval_required") and not (root / "written.txt").exists(), "stage authority admitted unapproved Native workspace mutation")
    accepted = handler({**write_step, "step_id": "accepted-write"}, {"approved": True})
    _check(accepted["ok"] and (root / "written.txt").read_bytes() == text.encode(), "approved stage did not admit exact actual Native mutation")
    if category == "stale":
        old = hashlib.sha256(text.encode()).hexdigest()
        (root / "written.txt").write_text(text + " replaced", encoding="utf-8")
        refused = handler({**write_step, "step_id": "stale-write", "arguments": {**write_step["arguments"], "expectedSha256": old}}, {"approved": True})
        _check(not refused["ok"] and (root / "written.txt").read_text(encoding="utf-8") == text + " replaced", "stage overwrote an unobserved revision")
    if category == "permissions":
        with _sharing(source):
            refused = handler({**read_step, "step_id": "denied-os-read"}, {})
        _check(not refused["ok"], "real OS sharing denial disappeared at stage boundary")
    refused = default_step_handler({"step_id": "unknown", "action": text or "unknown", "arguments": {}}, {})
    _check(not refused["ok"] and refused["metadata"]["error"] == "no_handler", "unknown stage action fabricated execution")
    header = 'NEYVIA/1\nGOAL text="Observed stage repair"\nBUDGET repairs=2\nLANE worker runtime=neyvia-native model=none effort=none permissions=read\n'
    program = header + 'STEP initial lane=worker action=checkpoint risk=read\nVERIFY first lane=worker after=initial args=\'{"verificationScore":0.9}\'\nSTEP repair lane=worker action=repair after=first risk=read args=\'{"verificationScore":0.4}\'\nVERIFY final lane=worker after=repair args=\'{"verificationScore":0.9}\'\n'
    receipt = execute_neyvia_stages(root, program, mission_id="owned-stage", initial_context={"selected_fixture_text": text})
    _check(receipt["ok"] and receipt["bestVerificationScore"] == .9 and len(receipt["rollbacks"]) == 1 and any(r["rolled_back"] for r in receipt["outcomes"]), "actual stage scheduler did not roll back inferior repair")
    _check(json.loads(Path(receipt["receiptPath"]).read_text(encoding="utf-8")) == receipt and all(Path(r["path"]).is_file() for r in receipt["checkpoints"]), "actual stage/checkpoint receipt is not durable")
    parallel = None
    if category == "concurrency":
        barrier = threading.Barrier(2); workers = []
        specification = surface._specs["workspace.read"]
        def observed_read(args):
            workers.append(threading.get_ident()); barrier.wait(timeout=10)
            return registry.call("workspace.read", args)
        surface.register(specification, handler=observed_read)
        arguments = json.dumps({"path": "input.txt", "maxChars": 11})
        program = header + f"STEP left lane=worker action=tool tool=workspace.read risk=read args='{arguments}'\nSTEP right lane=worker action=tool tool=workspace.read risk=read args='{arguments}'\n"
        parallel = execute_neyvia_stages(root, program, mission_id="owned-parallel", step_handler=handler)
        _check(parallel["ok"] and parallel["parallelStagesRun"] >= 1 and parallel["completedStepIds"] == ["left", "right"] and len(set(workers)) == 2, "independent Native reads did not overlap and durably complete")
    return {"writtenSha256": hashlib.sha256((root / "written.txt").read_bytes()).hexdigest(), "receiptPath": receipt["receiptPath"], "rollbackCount": len(receipt["rollbacks"]), "parallelReceiptPath": parallel["receiptPath"] if parallel else None, "realNativeDispatch": True}


FAMILIES = {
    "projection": (_projection, {"d.host.event-identity", "d.host.delta-merge", "d.host.delta-synthesis", "d.host.selected-context"}, set(TEXT)),
    "profile-platform": (_profile_platform, {"d.runtime.profile.resolve", "d.runtime.platform.roots", "d.runtime.platform.candidates", "d.runtime.platform.coerce"}, set(TEXT)),
    "cache": (_cache, {"d.runtime.cache.compatibility", "d.runtime.cache.bootstrap", "d.runtime.cache.plan", "d.runtime.cache.import", "d.runtime.cache.read"}, set(TEXT) | {"concurrency", "permissions", "stale", "interrupted"}),
    "tools": (_tools, {"native.tools.receipt", "native.tools.catalog", "native.tools.workspace", "native.tools.arguments"}, set(TEXT) | {"concurrency", "permissions", "stale"}),
    "commands": (_commands, {"native.commands." + name for name in ("scope", "approval", "idempotency", "final-gate", "single-flight", "receipt", "cancel", "uncertainty", "deadline", "secret-free")}, set(TEXT) | {"concurrency", "permissions", "stale"}),
    "preview": (_preview, {"native.tools.preview", "native.tools.receipt"}, set(TEXT) | {"offline"}),
    "gateway": (_gateway, {"desktop.gateway.heartbeat", "desktop.gateway.route", "desktop.gateway.reconcile", "desktop.gateway.event"}, set(TEXT) | {"concurrency", "permissions", "stale"}),
    "stages": (_stages, {"d.host.stage-receipt", "d.host.stage-refusal", "d.host.stage-tool-authority"}, set(TEXT) | {"concurrency", "permissions", "stale"}),
}

ADVERSE_BINDINGS = {
    ("cache", "permissions"): {"d.runtime.cache.plan", "d.runtime.cache.compatibility"},
    ("cache", "concurrency"): {"d.runtime.cache.import", "d.runtime.cache.compatibility"},
    ("cache", "stale"): {"d.runtime.cache.import", "d.runtime.cache.compatibility", "d.runtime.cache.read"},
    ("cache", "interrupted"): {"d.runtime.cache.import", "d.runtime.cache.bootstrap", "d.runtime.cache.read"},
    ("tools", "permissions"): {"native.tools.receipt", "native.tools.workspace"},
    ("tools", "stale"): {"native.tools.receipt", "native.tools.workspace"},
    ("tools", "concurrency"): {"native.tools.receipt", "native.tools.workspace"},
    ("commands", "concurrency"): {"native.commands.single-flight"},
    ("commands", "permissions"): {"native.commands.scope", "native.commands.approval", "native.commands.final-gate", "native.commands.cancel"},
    ("commands", "stale"): {"native.commands.final-gate", "native.commands.uncertainty", "native.commands.deadline"},
    ("gateway", "concurrency"): {"desktop.gateway.event"},
    ("gateway", "permissions"): {"desktop.gateway.event"},
    ("gateway", "stale"): {"desktop.gateway.route", "desktop.gateway.reconcile"},
    ("stages", "permissions"): {"d.host.stage-tool-authority"},
    ("stages", "stale"): {"d.host.stage-tool-authority"},
}


def run(root, contracts, categories):
    from .proof_credential_guard import install
    base = Path(root).resolve(); base.mkdir(parents=True, exist_ok=True)
    install(base)
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        bindings = sorted(identities & set(contracts))
        if not bindings:
            continue
        for category in categories:
            if category not in supported:
                continue
            scratch = base / ".agent_control/proofs" / f"host-runtime-{family}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            home = scratch / "home"; home.mkdir()
            environment = {"CODEX_HOME": str(home / ".codex"), "NEYVIA_MCP_BROKER_CONFIG": str(scratch / "config/mcp.json"), "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "FLUXIO_CLUSTER_ROOT": str(scratch), "FLUXIO_CONTROL_PROJECT_ROOT": str(scratch)}
            selected = ADVERSE_BINDINGS.get((family, category), set(bindings))
            row = {"id": f"host-runtime.{family}.{category}", "category": category, "contracts": sorted(set(bindings) & selected), "boundary": "Actual owned production file/cache/registry/control-plane/HTTP effects, with independently inspected bytes and lifecycle"}
            if family == "stages":
                row["contracts"] = [identity for identity in row["contracts"] if identity != "d.host.stage-refusal" or category in TEXT]
                if category == "concurrency" and "d.host.stage-parallel" in contracts:
                    row["contracts"].append("d.host.stage-parallel")
            try:
                with _environment(environment):
                    row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "traceback": traceback.format_exc()[-5000:], "scratch": str(scratch)})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity == "d.host.stage-refusal" and category not in TEXT:
        return {"kind": "not_applicable", "reason": "Audited default_step_handler refuses an unknown explicit action in memory. That refusal owns no network, authorization, durable revision, worker interruption or shared mutation operation."}
    for family, (_, identities, supported) in FAMILIES.items():
        if identity not in identities or category in supported:
            continue
        if family == "projection" and identity != "d.host.selected-context":
            return {"kind": "not_applicable", "reason": f"Audited {identity} owner projects explicit event/delta objects in memory. It owns no durable revision, interrupted worker, network or authorization operation for {category}."}
        if family == "profile-platform" and identity.startswith("d.runtime.platform."):
            return {"kind": "not_applicable", "reason": f"Audited {identity} constructs and normalizes explicit path configuration only; it performs no NAS/filesystem/network action and owns no permission or durable revision for {category}."}
        if category == "offline" and family in {"cache", "tools", "commands", "profile-platform"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} covers selected-root local cache/files/SQLite control-plane or loaded profile selection. Transport execution belongs to a separate owner; no remote device execution or provider reachability is claimed."}
        return {"kind": "fixture_gap", "reason": f"No implemented {category} adversarial journey at exact {identity} owner {contract.get('checkedAt', [])}; remaining work, not impossibility."}
    if identity.startswith(("d.runtime.bridge.", "d.runtime.transfer.")):
        return {"kind": "fixture_gap", "reason": "No real local-only bridge/transfer fixture is implemented here. This task prohibits NAS sync, so an implementation must confine all protocol files to owned scratch and prove no NAS activity before this pair can pass."}
    return None
