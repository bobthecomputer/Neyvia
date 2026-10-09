"""Generated native action attempts, durable replay and receipt projection."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from .edge_fixture_local import require, refused
from .edge_fixture_c7d_sessions import REPO, _isolate

MODULE = "grant_agent.edge_fixture_c7d_host_actions"
PAIRS = {"proofs-e-host.action-once": {"empty", "huge", "permissions"}, "proofs-e-host.action-sanitization": {"empty", "huge", "interrupted", "permissions"}}
MARKER = "GENERATED-EXCLUDED-NONSECRET-MARKER"

def blocker(contract, category): return None

def _case(root, identity, category):
    from .action_receipts import NativeActionStore
    from .edge_fixture_preferences_skills import denied_file
    store = NativeActionStore(root, "owned-host-actions")
    target = root / "actual-outcome.txt"
    action_id = "owned-action" + ("-" + "x" * 147 if category == "huge" else "")
    require(len(action_id) <= 160, "Generated intended action ID exceeded owner limit")
    arguments = {} if category == "empty" else {"path": str(target), "selection": "雪🙂"}
    payload = {"ok": True, "status": "success", "rawCallback": MARKER,
               "toolResult": {"safe": [{"value": index, "accessToken": MARKER, "cookie": MARKER} for index in range(128 if category == "huge" else 1)], "secret": MARKER},
               "verification": {"checked": True, "apiKey": MARKER}, "failure": {"message": "owned", "password": MARKER}}
    if category == "empty": payload = {"ok": True, "rawCallback": MARKER, "toolResult": {}}
    def effect():
        with target.open("a", encoding="utf8") as stream: stream.write("actual owned effect\n")
        return payload
    if category == "interrupted":
        program = "import sys,os,json;from pathlib import Path;from grant_agent.proof_credential_guard import install;root=Path(sys.argv[1]);install(root);from grant_agent.action_receipts import NativeActionStore;target=root/'actual-outcome.txt';p=json.loads(sys.argv[2]);args=json.loads(sys.argv[3]);def_marker=0\ndef effect():\n with target.open('a',encoding='utf8') as f:f.write('actual owned effect\\n')\n return p\nr=NativeActionStore(root,'owned-host-actions').execute('owned-action','owned.file.write',args,effect);assert r['ok'];os._exit(23)"
        child = subprocess.run([sys.executable, "-c", program, str(root), json.dumps(payload), json.dumps(arguments)], capture_output=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23, "Actual host action child did not exit after durable completion")
        first = store.inspect(action_id); require(first["status"] == "completed", "Caller exit lost durable sanitized completion")
    else:
        first = store.execute(action_id, "owned.file.write", arguments, effect)
        require(first["ok"] and first["duplicateSuppressed"] is False, "First actual action was suppressed or refused")
    expected = target.read_bytes(); stamp = target.stat().st_mtime_ns
    receipt_path = store._path(action_id); result_path = receipt_path.with_suffix(".result")
    receipt_before = receipt_path.read_bytes(); result_before = result_path.read_bytes()
    require(MARKER not in result_before.decode("utf8") and MARKER not in receipt_before.decode("utf8"), "Callback-only fields escaped durable projection")
    if category == "permissions":
        with denied_file(receipt_path if identity.endswith("action-once") else result_path):
            if identity.endswith("action-once"): refused(lambda: store.execute(action_id, "owned.file.write", arguments, effect), (OSError,))
            else:
                uncertain = store.execute(action_id, "owned.file.write", arguments, effect)
                require(uncertain["ok"] is False and uncertain["status"] == "action_uncertain", "Unreadable selected result silently replayed mutation")
        require(receipt_path.read_bytes() == receipt_before and result_path.read_bytes() == result_before and target.read_bytes() == expected, "Read-denied replay changed prior target/receipts")
    replay = NativeActionStore(root, "owned-host-actions").execute(action_id, "owned.file.write", arguments, effect)
    require(replay["ok"] and replay["duplicateSuppressed"] and target.stat().st_mtime_ns == stamp and target.read_bytes() == expected, "Reopened action store repeated actual effect")
    require(MARKER not in json.dumps(replay), "Replayed result exposed excluded callback marker")
    conflict = store.execute(action_id, "owned.file.write", {"changed": True}, effect)
    require(conflict["status"] == "action_conflict" and target.stat().st_mtime_ns == stamp, "Changed request identity repeated action")
    invalid = "" if category == "empty" else "x" * 161
    refused(lambda: store.execute(invalid, "owned.file.write", {}, effect), (ValueError,))
    require(target.read_bytes() == expected, "Invalid action identity executed handler")
    return {"actualEffects": len(expected.splitlines()), "duplicateSuppressed": True, "conflictingIntentRefused": True,
            "targetSha256": hashlib.sha256(expected).hexdigest(), "sanitizedResultSha256": hashlib.sha256(result_before).hexdigest(),
            "excludedCallbackMarkerAbsent": True, "callerExit": 23 if category == "interrupted" else None,
            "proofScope": "local_semantic", "rendered": False, "externalEffects": False}

def run(root, contracts, categories):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    rows = []
    for identity in sorted(PAIRS.keys() & contracts.keys()):
        for category in categories:
            if category not in PAIRS[identity]: continue
            area = Path(root) / (identity + "-" + category + "-" + uuid.uuid4().hex[:8]); area.mkdir(parents=True)
            child = subprocess.run([sys.executable, "-m", MODULE, "--port", os.environ["NEYVIA_C7_PORT"], "--case", str(area), identity, category], capture_output=True, text=True, encoding="utf8", timeout=60, **hidden_windows_subprocess_kwargs())
            try: value = json.loads(child.stdout)
            except ValueError: value = {"status": "failed", "detail": child.stderr[-2500:]}
            rows.append({"id": "c7d-host-actions:" + identity + ":" + category, "contracts": [identity], "category": category, **value, "scratchRoot": str(area), "proofScope": "local_semantic"})
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--port", required=True, type=int); parser.add_argument("--case", nargs=3); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.case:
        root, identity, category = args.case; _isolate(Path(root), args.port)
        try: result = {"status": "passed", "detail": _case(Path(root), identity, category)}
        except Exception as error: result = {"status": "failed", "detail": {"error": str(error), "type": type(error).__name__}}
        print(json.dumps(result)); return
    if args.output is None: parser.error("--output required")
    from .edge_contracts import inventory, CATEGORIES
    from .proof_contracts import source_digest
    root = REPO / ".agent_control/proofs/c7d-host-actions" / uuid.uuid4().hex; _isolate(root, args.port)
    names = ["edge_fixture_c7d_host_actions", "edge_fixture_c7d_sessions", "action_receipts", "proofs_e_host", "harness_jobs", "durability", "edge_fixture_preferences_skills", "subprocess_utils"]
    bindings = {"src/grant_agent/" + name + ".py": source_digest(REPO / ("src/grant_agent/" + name + ".py")) for name in names}
    rows = run(root, inventory()[1], CATEGORIES)
    stable = all(source_digest(REPO / path) == digest for path, digest in bindings.items())
    output = args.output.resolve(); output.relative_to(REPO)
    output.write_text(json.dumps({"schema": "neyvia.c7d-host-actions.raw.v1", "root": str(root), "explicitPort": args.port, "sourceBindings": bindings, "sourceStable": stable, "rows": rows}, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": sum(row["status"] == "passed" for row in rows), "failed": sum(row["status"] == "failed" for row in rows), "sourceStable": stable}))

if __name__ == "__main__": main()
