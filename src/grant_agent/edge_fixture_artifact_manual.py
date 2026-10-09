"""Owned host observations and local artifact/receipt fixtures.

Each binding invokes its named production owner. Transfer receipts here are
local persisted inputs, never claims of transport or physical-device success.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

TEXT = {"empty": "", "huge": "fixture " * 20000, "unicode": "雪🙂e\u0301 العربية\u202e"}
REPO = Path(__file__).resolve().parents[2]


def _check(value, detail):
    if not value:
        raise AssertionError(detail)


@contextmanager
def _environment(root):
    values = {key: str(root / "home" / key.lower()) for key in
              ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")}
    for directory in values.values():
        Path(directory).mkdir(parents=True, exist_ok=True)
    values.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                  FLUXIO_NAS_VOLUME_ROOT=str(root / "unconfigured-volume"), FLUXIO_WINDOWS_NAS_VOLUME_MIRROR=str(root / "unconfigured-mirror"),
                  FLUXIO_WORKSPACE_ROOT=str(root), FLUXIO_CONTROL_PROJECT_ROOT=str(root), FLUXIO_CLUSTER_ROOT=str(root),
                  NEYVIA_NAS_ROOT=str(root), FLUXIO_NAS_ROOT=str(root), PYTHONPATH=str(REPO / "src"))
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


def _pack(root, category):
    folder = root / "src/grant_agent"; folder.mkdir(parents=True)
    count = 140 if category == "huge" else 4
    paths = [f"src/grant_agent/module_{i}.py" for i in range(count)]
    (folder / "__init__.py").write_text("", encoding="utf-8")
    for index, name in enumerate(paths):
        source = (f"from .module_{index + 1} import value\n" if index + 1 < count else "value = 1\n")
        source += "# " + TEXT.get(category, "owned dependency") + "\n"
        (root / name).write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("c7c_owned_pack_closure", REPO / "scripts/package_onboarding_packs.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    inputs = [] if category == "empty" else [paths[0], paths[0]]
    result = module.import_closure(inputs, root=root)
    expected = ["src/grant_agent/__init__.py"] if not inputs else sorted(["src/grant_agent/__init__.py", *paths])
    _check(result == expected, "transitive import closure omitted/doubled actual local modules")
    _check(all((root / path).is_file() and "\\" not in path for path in result), "closure returned nonportable/missing path")
    if category == "permissions":
        from .edge_fixture_core import denied
        target = root / paths[1]
        prior = target.read_bytes()
        with denied(target):
            try:
                module.import_closure(inputs, root=root)
            except PermissionError:
                pass
            else:
                raise AssertionError("Import closure claimed complete dependencies through an unreadable owned imported source")
        _check(target.read_bytes() == prior and module.import_closure(inputs, root=root) == expected, "Unreadable import changed source or failed exact dependency recovery")
    return {"modules": count, "returned": len(result), "closureSha256": hashlib.sha256(json.dumps(result).encode()).hexdigest()}


def _writer(root, category):
    from .connected_sessions.codex_writer import active_writer
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    home = Path(os.environ["CODEX_HOME"])
    _check(active_writer("owned", None) is None, "legacy store fabricated ownership")
    directory = home / "thread-writer-locks"; directory.mkdir()
    if category == "empty":
        _check(active_writer("", None) is None and active_writer("owned", None) is False, "empty/missing writer observation differs")
        return {"invalidResult": None, "missingResult": False, "rolloutsRead": False}
    if category == "huge":
        _check(active_writer("x" * 40000, None) is None, "unreadable huge writer name fabricated absence/ownership")
        _check(active_writer("x" * 250, None) is False and active_writer("x" * 251, None) is None,
               "ASCII writer identity 250/251 byte boundary differs")
        _check(active_writer("雪" * 83 + "x", None) is False and active_writer("雪" * 83 + "xx", None) is None,
               "Unicode writer identity 250/251 byte boundary differs")
        _check(active_writer("\ud800", None) is None and active_writer(None, None) is None, "invalid writer identity type/UTF8 escaped")
        return {"unreadableResult": None, "asciiIdentityBoundary": [250, 251], "unicodeIdentityBoundary": [250, 251], "rolloutsRead": False}
    identity = "writer-雪🙂e\u0301" if category == "unicode" else "owned"
    path = directory / (identity + ".lock"); path.write_bytes(b"0")
    if category == "permissions":
        from .edge_fixture_host_runtime import _sharing
        with _sharing(path):
            denied = active_writer(identity, None)
            _check(denied is True or denied is None, "actual sharing-denied lock fabricated absent writer")
        _check(active_writer(identity, None) is False and path.read_bytes() == b"0", "sharing release changed writer bytes or did not clear ownership")
        return {"sharingDeniedResult": denied, "releasedResult": False, "sourcePreserved": True}
    holder = """import sys,msvcrt
f=open(sys.argv[1],'r+b'); msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
print('locked',flush=True); sys.stdin.readline(); f.close()
"""
    child = subprocess.Popen([sys.executable, "-u", "-c", holder, str(path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
    try:
        _check(child.stdout.readline().strip() == "locked", "owned writer failed OS lock acquisition")
        if category == "stale":
            os.utime(path, (1, 1))
        rollout = home / "sessions/day/owned.jsonl"
        _check(active_writer(identity, rollout) is True, "actual locked writer was reported inactive")
        if category == "concurrency":
            barrier = threading.Barrier(4)
            def probe(_):
                barrier.wait(timeout=10); return active_writer(identity, rollout)
            with ThreadPoolExecutor(max_workers=4) as pool:
                _check(list(pool.map(probe, range(4))) == [True] * 4, "concurrent read probes changed actual ownership")
        if category == "interrupted":
            child.terminate(); child.wait(timeout=10)
        else:
            child.stdin.write("release\n"); child.stdin.flush(); child.wait(timeout=10)
        _check(active_writer(identity, rollout) is False and path.read_bytes() == b"0" and not rollout.exists(),
               "released/crashed OS owner did not disappear or read probe mutated source")
        return {"locked": True, "released": False, "crashed": category == "interrupted", "rolloutsRead": False}
    finally:
        if child.poll() is None:
            child.terminate(); child.wait(timeout=10)
        child.stdin.close(); child.stdout.close(); child.stderr.close()


def _limits(root, category):
    from .connected_sessions.plan_limits import record_claude_statusline, claude_limits
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    first = record_claude_statusline({"rate_limits": {"five_hour": {"used_percentage": 37}, "seven_day": {"used_percentage": 62}}}, root)
    payload = {"rate_limits": {}, "irrelevant": TEXT.get(category, "excluded")}
    if category == "huge":
        payload["rate_limits"] = {"five_hour": {"used_percentage": 10 ** 200, "resets_at": 10 ** 200}, "unapproved": {"used_percentage": 2}}
    elif category == "unicode":
        payload["rate_limits"] = {"five_hour": {"used_percentage": TEXT[category], "resets_at": TEXT[category]}}
    actual = record_claude_statusline(payload, root)
    if category != "huge":
        _check(actual == first, "missing/invalid input erased last-known windows")
    saved = json.loads((root / ".neyvia/plan-limits.json").read_text(encoding="utf-8"))
    _check(set(saved) == {"five_hour", "seven_day"} and "irrelevant" not in saved,
           "undocumented windows/raw input persisted")
    if category in {"interrupted", "permissions"}:
        from .connected_sessions import plan_limits as owner
        from .edge_fixture_core import denied
        from .edge_fixture_local import replacement_fault
        target = root / ".neyvia/plan-limits.json"
        prior = target.read_bytes()
        update = {"rate_limits": {"five_hour": {"used_percentage": 48}}}
        if category == "permissions":
            with denied(target):
                try:
                    record_claude_statusline(update, root)
                except OSError:
                    pass
                else:
                    raise AssertionError("OS-denied plan-limit write produced successful durable observation")
        else:
            with replacement_fault(owner, target, KeyboardInterrupt) as commits:
                try:
                    record_claude_statusline(update, root)
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError("Limit writer missed actual replacement interruption")
            _check(commits, "Limit interruption occurred before actual publication")
        _check(target.read_bytes() == prior and not list(target.parent.glob('plan-limits-*.tmp')), "OS-denied/interrupted windows lost prior usage or leaked temporary payload")
        resumed = {row["window"]: row for row in record_claude_statusline(update, root)}
        _check(resumed["five_hour"]["usedPercent"] == 48 and resumed["seven_day"]["usedPercent"] == 62, "Retry lost independently stored other window")
    if category in {"stale", "concurrency"}:
        code = """import sys,time
from pathlib import Path
root=Path(sys.argv[1])
from grant_agent.proof_credential_guard import install
install(root)
from grant_agent.connected_sessions.plan_limits import record_claude_statusline
if sys.argv[3]=='concurrency':
 (root/(sys.argv[2]+'.ready')).write_bytes(b'1')
 deadline=time.monotonic()+20
 while not (root/'writers-go').exists():
  if time.monotonic()>deadline: raise RuntimeError('owned start gate timed out')
  time.sleep(.005)
record_claude_statusline({'rate_limits':{sys.argv[2]:{'used_percentage':48}}},root)
"""
        children = [subprocess.Popen([sys.executable, "-c", code, str(root), kind, category], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    **hidden_windows_subprocess_kwargs()) for kind in (["five_hour", "seven_day"] if category == "concurrency" else ["five_hour"])]
        if category == "concurrency":
            deadline = time.monotonic() + 20
            while not all((root / (kind + ".ready")).exists() for kind in ("five_hour", "seven_day")):
                if time.monotonic() > deadline:
                    for child in children:
                        child.terminate(); child.wait(timeout=10)
                    raise RuntimeError("Separate-process limit writers did not reach start gate")
                time.sleep(.01)
            (root / "writers-go").write_bytes(b"1")
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            _check(child.returncode == 0, "separate-process limit write failed: " + stderr.decode(errors="replace")[-500:])
        refreshed = {row["window"]: row for row in claude_limits(root)}
        _check(refreshed["five_hour"]["usedPercent"] == 48 and refreshed["seven_day"]["usedPercent"] == (48 if category == "concurrency" else 62),
               "second-process status observations lost a window or did not refresh local cache")
    return {"savedSha256": hashlib.sha256((root / ".neyvia/plan-limits.json").read_bytes()).hexdigest(), "windows": sorted(saved), "secondProcess": category in {"stale", "concurrency"}}


def _nearby(root, category):
    from .nearby_send import NearbySendService, NEARBY_TRANSFER_RECEIPT_SCHEMA, NEARBY_TRANSFER_STATE_SCHEMA
    service = NearbySendService(root)
    service.nearby_root.mkdir(parents=True, exist_ok=True)
    text = TEXT.get(category, "fixture")
    count = 105 if category == "huge" else 0 if category == "empty" else 3
    files = [{"fileId": str(i), "fileName": text or "empty.txt", "path": str(root / "private.txt"),
              "sourceRef": "safe/雪.txt" if i == 0 else "../private.txt", "size": 1, "sha256": "a" * 64} for i in range(count)]
    receipt = {"schema": NEARBY_TRANSFER_RECEIPT_SCHEMA, "receiptId": "nearby_receipt_fixture", "transferId": "owned", "status": "completed", "ok": True,
               "recipient": {"endpoint": "https://synthetic.invalid"}, "sessionId": "fixture-private-capability", "files": files,
               "summary": {"fileCount": count, "totalBytes": count}, "cancellation": {}}
    public = service._public_receipt(receipt, artifacts=True)
    raw = json.dumps(public, ensure_ascii=False)
    _check("fixture-private-capability" not in raw and "synthetic.invalid" not in raw and str(root / "private.txt") not in raw,
           "local receipt projection leaked raw transport/source capabilities")
    _check(len(public["files"]) == min(100, count) and public["summary"]["filesTruncated"] == max(0, count - 100), "receipt truncation/count differs")
    _check(all(not Path(row["path"]).is_absolute() for row in public["artifacts"]), "public artifacts retained absolute host path")
    service.receipt_root.mkdir()
    histories = 105 if category == "huge" else 0 if category == "empty" else 3
    for index in range(histories):
        record = {**receipt, "receiptId": f"nearby_receipt_{index:03d}"}
        # Files need only be large in the single direct projection, not repeated in every history entry.
        if category == "huge":
            record = {**record, "files": [], "summary": {"fileCount": 0, "totalBytes": 0}}
        path = service.receipt_root / (record["receiptId"] + ".json")
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    corrupt = service.receipt_root / "nearby_receipt_corrupt.json"; corrupt.write_bytes(b"{broken")
    history = service.list_transfer_history(limit=500)
    _check(len(history["transfers"]) == min(histories, 100) and history["summary"]["skippedInvalidReceipts"] == 1,
           "history lost bounded receipt count or corrupt-state disclosure")
    _check(corrupt.read_bytes() == b"{broken", "history observer mutated corrupt source receipt")
    state = {"schema": NEARBY_TRANSFER_STATE_SCHEMA, "transferId": "owned", "status": "uploading", "active": True,
             "ownerPid": 2_000_000_000, "recipient": receipt["recipient"], "sessionId": receipt["sessionId"], "files": [], "summary": {}}
    service.active_state_path.write_text(json.dumps(state), encoding="utf-8")
    service.transfer_claim_path.write_text(json.dumps({"transferId": "owned", "ownerPid": state["ownerPid"]}), encoding="utf-8")
    recovered = NearbySendService(root).get_active_transfer()
    durable = json.loads(service.active_state_path.read_text(encoding="utf-8"))
    _check(recovered["recovery"] == "stale_transfer_recovered" and durable["status"] == "interrupted" and durable["recipient"] == {} and durable["sessionId"] == "" and not service.transfer_claim_path.exists(),
           "dead local owner did not durably recover with capability removal")
    broken = b"" if category == "empty" else b"{" + b"x" * (4 * 1024 * 1024) if category == "huge" else b"\xff\xfe"
    service.active_state_path.write_bytes(broken)
    recovered = service.get_active_transfer()
    _check(recovered.get("recovery") == "corrupt_state_discarded" and not service.active_state_path.exists() and not recovered["active"], "invalid/oversized/UTF8 local state did not recover")
    return {"projectedFiles": len(public["files"]), "returnedHistory": len(history["transfers"]), "corruptSkipped": 1,
            "deadOwnerRecovered": True, "invalidStateDiscarded": True, "transportInvoked": False}


def _artifacts(root, category):
    from .web_backend import FluxioWebBackend
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    backend = FluxioWebBackend(root, root)
    folder = root / ".agent_control/mission_artifacts/owned"; folder.mkdir(parents=True)
    name = "雪🙂e\u0301.pdf" if category == "unicode" else "report.pdf"
    source = folder / name; source.write_bytes(TEXT.get(category, "fixture").encode())
    outside = root / "outside.pdf"; outside.write_bytes(b"outside fixture")
    before = source.read_bytes()
    payload = {"artifacts": [{"path": str(source), "label": TEXT.get(category, "fixture")},
                             {"path": str(outside), "servedUrl": "/api/artifact?id=" + "0" * 24, "safeEndpoint": "/api/artifact"}]}
    result = backend._decorate_mission_artifacts(payload)
    accepted, denied = result["artifacts"]
    expected_id = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:24]
    _check(accepted["servedUrl"] == "/api/artifact?id=" + expected_id and accepted["mediaType"] == "application/pdf" and backend._resolve_artifact_id(expected_id) == source.resolve(), "real artifact gate returned wrong serving identity/media/path")
    _check(denied["servedUrl"] == "" and "safeEndpoint" not in denied and denied["path"] == str(outside), "unapproved local path retained endpoint authority")
    _check(source.read_bytes() == before and outside.read_bytes() == b"outside fixture" and payload["artifacts"][1]["safeEndpoint"] == "/api/artifact", "read-only gate mutated source bytes/input object")
    if category == "empty":
        empty = backend._decorate_mission_artifacts({"artifacts": [{"path": "", "servedUrl": "/api/artifact?id=" + expected_id, "safeEndpoint": "/api/artifact"}]})["artifacts"][0]
        _check(empty.get("servedUrl") == "" and "safeEndpoint" not in empty,
               "empty unapproved artifact path retained stale serving authority")
    if category == "huge":
        oversized = backend._decorate_mission_artifacts({"artifacts": [{"path": "x" * 40000 + ".pdf", "servedUrl": "/api/artifact?id=" + expected_id, "safeEndpoint": "/api/artifact"}]})["artifacts"][0]
        _check(oversized.get("servedUrl") == "" and "safeEndpoint" not in oversized,
               "oversized unapproved artifact path retained stale serving authority")
    if category == "stale":
        source.rename(folder / "new.pdf")
        newer = backend._decorate_mission_artifacts({"artifacts": [accepted]})["artifacts"][0]
        _check(newer["servedUrl"] == "" and "safeEndpoint" not in newer, "missing stale source retained serving authority")
    return {"artifactId": expected_id, "observedBytes": len(before), "sourceSha256": hashlib.sha256(before).hexdigest(), "outsideRefused": True}


def _nearby_owner(root, category):
    from .nearby_send import NearbySendService, NEARBY_TRANSFER_STATE_SCHEMA
    from .durability import atomic_write_json
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    service = NearbySendService(root)
    service.nearby_root.mkdir(parents=True, exist_ok=True)
    state = {"schema": NEARBY_TRANSFER_STATE_SCHEMA, "transferId": "owned", "status": "uploading", "active": True,
             "ownerPid": 2_000_000_000, "recipient": {"endpoint": "https://synthetic.invalid"}, "sessionId": "fixture-private-capability", "files": [], "summary": {}}
    crashed_pid = None
    if category == "interrupted":
        code = """import json,os,sys
from pathlib import Path
root=Path(sys.argv[1])
from grant_agent.proof_credential_guard import install
install(root)
from grant_agent.nearby_send import NearbySendService
from grant_agent.durability import atomic_write_json
service=NearbySendService(root)
state=json.loads(sys.argv[2]);state['ownerPid']=os.getpid()
atomic_write_json(service.active_state_path,state)
atomic_write_json(service.transfer_claim_path,{'transferId':'owned','ownerPid':os.getpid()})
print('state-durable',flush=True);sys.stdin.readline()
"""
        child = subprocess.Popen([sys.executable, "-u", "-c", code, str(root), json.dumps(state)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_windows_subprocess_kwargs())
        try:
            _check(child.stdout.readline().strip() == "state-durable", "owned transfer-state worker failed before durable marker")
            live = service.get_active_transfer()
            _check(live["active"] and "recovery" not in live, "live owned worker fabricated stale recovery")
            crashed_pid = child.pid
            child.terminate(); child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=10)
            child.stdin.close(); child.stdout.close(); child.stderr.close()
    else:
        atomic_write_json(service.active_state_path, state)
        atomic_write_json(service.transfer_claim_path, {"transferId": "owned", "ownerPid": state["ownerPid"]})
        if category == "stale":
            os.utime(service.active_state_path, (1, 1))
    if category == "concurrency":
        barrier = threading.Barrier(4)
        def recover(_):
            observed = NearbySendService(root)
            barrier.wait(timeout=10)
            return observed.get_active_transfer()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(recover, range(4)))
        _check(sum(row.get("recovery") == "stale_transfer_recovered" for row in results) == 1,
               "same dead owner recovered concurrently more than once")
    else:
        results = [NearbySendService(root).get_active_transfer()]
        _check(results[0].get("recovery") == "stale_transfer_recovered", "stopped/aged owner did not recover")
    durable = json.loads(service.active_state_path.read_text(encoding="utf-8"))
    _check(all(not row["active"] and row["progress"]["status"] == "interrupted" for row in results)
           and durable["status"] == "interrupted" and not durable["recipient"] and not durable["sessionId"]
           and not service.transfer_claim_path.exists(), "recovered local state retained owner/transport authority")
    _check("fixture-private-capability" not in json.dumps(results) and "synthetic.invalid" not in json.dumps(results), "recovery projection leaked transport capabilities")
    return {"observers": len(results), "recoveries": 1, "killedOwnedPid": crashed_pid, "localStateSha256": hashlib.sha256(service.active_state_path.read_bytes()).hexdigest(), "transportInvoked": False}


def _nearby_history_permissions(root, category):
    from .nearby_send import NearbySendService, NEARBY_TRANSFER_RECEIPT_SCHEMA
    from .edge_fixture_host_runtime import _sharing
    service = NearbySendService(root); service.receipt_root.mkdir(parents=True)
    path = service.receipt_root / "nearby_receipt_owned.json"
    value = {"schema": NEARBY_TRANSFER_RECEIPT_SCHEMA, "receiptId": "nearby_receipt_owned", "status": "completed", "ok": True, "files": [], "summary": {}}
    path.write_text(json.dumps(value), encoding="utf-8")
    before = path.read_bytes()
    with _sharing(path):
        history = service.list_transfer_history(limit=10)
        _check(history["transfers"] == [] and history["summary"]["skippedInvalidReceipts"] == 1,
               "sharing-denied receipt fabricated completed history or omitted skipped count")
    restored = service.list_transfer_history(limit=10)
    _check(path.read_bytes() == before and len(restored["transfers"]) == 1 and restored["summary"]["completed"] == 1
           and restored["summary"]["skippedInvalidReceipts"] == 0, "sharing-denied observation mutated durable receipt or failed released read")
    return {"osSharingDenied": True, "deniedSkipped": 1, "releasedCompleted": 1, "sourceSha256": hashlib.sha256(before).hexdigest()}


def _manual(root, category):
    from .cl.schema import SchemaGraph, schema_to_type, type_to_schema
    fields = {"zeta": {"type": "string"}, "alpha": {"type": "integer"}}
    schemas = [{"type": "object", "properties": props, "required": list(fields)}
               for props in (fields, dict(reversed(list(fields.items()))))]
    graph = SchemaGraph()
    names = [graph.add(schema) for schema in schemas]
    _check(names[0] != names[1], "CL deduplication merged different positional parameter orders")
    for name, schema in zip(names, schemas):
        restored = type_to_schema(schema_to_type(graph.schema(name)))
        _check(list(restored["properties"]) == list(schema["properties"]), "CL round trip changed positional parameter order")
    from . import neyvia_manuals as manuals
    from .native_tools import NativeToolRegistry
    from .neyvia_workspace_tools import workspace_for
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    registry = NativeToolRegistry(root, nas_root=root / "unused-local-label")
    previous = os.environ.get("NEYVIA_UI_STATE_ROOT")
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
    service = workspace_for(root)
    try:
        index = manuals.call(service, "manual.index", {}, registry=registry)
        indexed = next(row for row in index["manuals"] if row["id"] == "agents")
        record, digest, data = manuals.get_manual("agents", root / ".neyvia")
        source = (REPO / record.get("clSource", record["path"])).read_bytes()
        _check(digest == hashlib.sha256(source).hexdigest() and "agents" in manuals.prompt_index(), "manual discovery/hash differs from current actual source")
        rendered = manuals.render(data["chapters"]["overview"], data["schemas"], data.get("proofs"), layer="agents", source_version="1.1" if record.get("clSource") else "1.0")
        invalid = {"empty": {"id": ""}, "huge": {"id": "agents", "maxChars": 20001}, "unicode": {"id": "agents", "chapter": TEXT["unicode"]}}
        if category in invalid:
            try:
                manuals.call(service, "manual.load", invalid[category], registry=registry)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid manual selector/bounds admitted")
        loaded = manuals.call(service, "manual.load", {"id": "agents", "maxChars": 512}, registry=registry)
        _check(loaded["ok"] and loaded["sha256"] == digest and loaded["text"] == rendered[:512], "grounded real manual load changed rendered content or hash")
        checked = manuals.call(service, "manual.validate", {"id": "agents"}, registry=registry)
        _check(checked["manuals"][0]["grounded"] and indexed["chapters"] == list(data["chapters"]), "manual is ungrounded or chapters differ from discovery")
        assembled = loaded["text"]
        while loaded["nextOffset"] is not None:
            loaded = manuals.call(service, "manual.load", {"id": "agents", "offset": loaded["nextOffset"], "maxChars": 20000}, registry=registry)
            assembled += loaded["text"]
        _check(assembled == rendered and source == (REPO / record.get("clSource", record["path"])).read_bytes(), "pagination lost text or read journey modified actual manual source")
        if category == "concurrency":
            barrier = threading.Barrier(4)
            def load(_):
                barrier.wait(timeout=10)
                return manuals.call(service, "manual.load", {"id": "agents", "maxChars": 512}, registry=registry)
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(load, range(4)))
            _check(all(row["sha256"] == digest and row["text"] == rendered[:512] for row in rows), "concurrent grounded manual reads diverged")
        return {"sourceSha256": digest, "renderedChars": len(rendered), "grounded": True, "pagesConserved": True}
    finally:
        service.close()
        if previous is None:
            os.environ.pop("NEYVIA_UI_STATE_ROOT", None)
        else:
            os.environ["NEYVIA_UI_STATE_ROOT"] = previous


FAMILIES = {
    "pack": (_pack, {"proofs-e-host.pack-closure"}, set(TEXT) | {"permissions"}),
    "writer": (_writer, {"proofs-e-host.writer"}, set(TEXT) | {"stale", "concurrency", "interrupted", "permissions"}),
    "limits": (_limits, {"proofs-e-host.limits"}, set(TEXT) | {"stale", "concurrency", "interrupted", "permissions"}),
    "nearby": (_nearby, {"d.host.nearby-redaction", "d.host.nearby-history", "d.host.nearby-recovery"}, set(TEXT)),
    "nearby-owner": (_nearby_owner, {"d.host.nearby-recovery"}, {"stale", "concurrency", "interrupted"}),
    "nearby-history-permissions": (_nearby_history_permissions, {"d.host.nearby-history"}, {"permissions"}),
    "artifact": (_artifacts, {"d.host.artifact-serving"}, set(TEXT) | {"stale"}),
    "manual": (_manual, {"control.agents-manual"}, set(TEXT) | {"concurrency"}),
}


def run(root, contracts, categories):
    from .proof_credential_guard import install
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    install(root)
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        bindings = sorted(identities & set(contracts))
        if not bindings:
            continue
        for category in categories:
            if category not in supported:
                continue
            scratch = root / ".agent_control/proofs" / f"artifact-manual-{family}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            row = {"id": f"artifact-manual.{family}.{category}", "category": category, "contracts": bindings,
                   "boundary": "Actual production host/receipt/artifact owner; independently checked local state, never remote transport success"}
            try:
                with _environment(scratch):
                    row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"error": str(error), "type": type(error).__name__, "traceback": traceback.format_exc()[-4500:], "scratch": str(scratch)})
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    for family, (_, identities, supported) in FAMILIES.items():
        if identity not in identities or category in supported:
            continue
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"Audited {identity} owner only observes selected local lock/module/status/receipt/artifact paths. No network reachability operation exists at this contract; actual remote transfer is a separate contract."}
        if identity == "d.host.nearby-redaction" or family == "pack" and category in {"stale", "concurrency", "interrupted"}:
            return {"kind": "not_applicable", "reason": f"Audited {identity} transforms explicit local input into a projection/closure without durable effect, revision token, or replay. The {category} operation has no corresponding claim at this owner."}
        return {"kind": "fixture_gap", "reason": f"No implemented {category} journey at exact {identity}; its local host source remains available for further fixtures."}
    return None
