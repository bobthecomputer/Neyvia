"""Native runtime semantic contracts and confined startup journeys.

Checks run in the feature's existing transaction or action boundary. The startup
journeys use real local storage and child processes; they grant no device/network
authority and do not import the removed test suite.
"""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import io
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def check_event(event, sequence, previous):
    from .native_event_stream import _canonical
    unsigned = {key: value for key, value in event.items() if key != "eventHash"}
    require(event["sequence"] == sequence and event["previousHash"] == previous
            and event["eventId"] == f"{event['runId']}:{sequence}"
            and event["eventHash"] == hashlib.sha256(_canonical(unsigned)).hexdigest(),
            "native.events.append", "event identity, order or digest differs")


def check_goal(connection, goal_id, expected):
    row = connection.execute("SELECT * FROM native_goals WHERE goal_id=?", (goal_id,)).fetchone()
    require(row is not None and all(row[key] == value for key, value in expected.items()),
            "native.goals.durable", "goal transaction differs from requested transition")


def check_goal_event(connection, goal_id, event_type, payload):
    row = connection.execute("SELECT event_type,payload_json FROM native_goal_events WHERE goal_id=? ORDER BY event_id DESC LIMIT 1", (goal_id,)).fetchone()
    require(row is not None and row["event_type"] == event_type and json.loads(row["payload_json"]) == payload,
            "native.goals.durable", "durable event differs from goal transition")


def check_pairing(connection, pairing_id, token, scopes):
    from .native_pairing import _digest
    row = connection.execute("SELECT * FROM pairing_requests WHERE pairing_id=?", (pairing_id,)).fetchone()
    require(row is not None and row["token_hash"] == _digest(token, row["token_salt"])
            and json.loads(row["scopes_json"]) == scopes and token not in tuple(row),
            "native.pairing.digest", "pairing token must be stored only as its salted digest with exact scopes")


def check_redemption(connection, pairing_id, device_id, secret):
    from .native_pairing import _digest
    pairing = connection.execute("SELECT * FROM pairing_requests WHERE pairing_id=?", (pairing_id,)).fetchone()
    device = connection.execute("SELECT * FROM paired_devices WHERE device_id=?", (device_id,)).fetchone()
    count = connection.execute("SELECT COUNT(*) FROM paired_devices WHERE pairing_id=?", (pairing_id,)).fetchone()[0]
    require(pairing is not None and device is not None and count == 1 and pairing["redeemed_at"]
            and device["pairing_id"] == pairing_id and device["target"] == pairing["target"]
            and device["scopes_json"] == pairing["scopes_json"]
            and device["secret_hash"] == _digest(secret, device["secret_salt"]) and secret not in tuple(device),
            "native.pairing.single-use", "redemption must create one scoped device with only a digest at rest")


def check_auth(row, secret, required_scope, valid):
    from .native_pairing import _digest
    import hmac
    expected = bool(row is not None and not row["revoked_at"]
                    and hmac.compare_digest(_digest(str(secret), row["secret_salt"]), row["secret_hash"])
                    and (not required_scope or required_scope in json.loads(row["scopes_json"])))
    require(valid is expected, "native.pairing.authority", "authentication differs from credential, scope or revocation")


def check_resource(profile, requested, memory_mb):
    expected = requested
    if requested == "auto":
        expected = ("eco" if 0 < memory_mb < 6144 else "memory-rich" if memory_mb >= 49152
                    else "maximal" if memory_mb >= 16384 else "balanced")
    require(profile["mode"] == expected and profile["requestedMode"] == requested
            and profile["detectedMemoryMb"] == memory_mb
            and 2 <= profile["verificationReserveTurns"] < profile["maximumTurns"],
            "native.resources.admission", "mode must follow memory thresholds and retain a verification reserve")
    if expected == "eco":
        require(profile["lowConsumption"] and profile["specialistLimit"] == 1 and profile["concurrencyLimit"] == 1,
                "native.resources.admission", "eco must serialize bounded specialists")
    if expected == "memory-rich":
        require(profile["contextBudgetBytes"] > 500000, "native.resources.admission", "memory-rich must retain larger context")


def check_routes(routes, requested_roles, overrides):
    require(list(routes) == list(dict.fromkeys(requested_roles)), "native.spawn.routes", "capsule order or resource limit changed")
    for role, route in routes.items():
        requested = overrides.get(role) or {}
        require(route.role == role and (role == "executor" or not route.allow_mutations)
                and 1 <= route.maximum_turns <= 16
                and (not requested.get("model") or route.model == str(requested["model"]).strip())
                and (not requested.get("effort") or route.effort == str(requested["effort"]).strip().lower()),
                "native.spawn.routes", "specialist identity, configured route or mutation boundary differs")


def check_spawn(connection, contract, receipt=None, path=None):
    row = connection.execute("SELECT * FROM spawn_contracts WHERE spawn_id=?", (contract["spawnId"],)).fetchone()
    require(row is not None and row["parent_session_id"] == contract["parentSessionId"]
            and row["child_session_id"] == contract["childSessionId"]
            and row["child_session_id"].startswith(f"{contract['parentSessionId']}.{contract['role']}.")
            and row["plan_hash"] == contract["planHash"],
            "native.spawn.lineage", "durable child lineage differs from the spawn contract")
    if receipt is not None:
        require(row["status"] == receipt["status"] and row["receipt_path"] == str(path)
                and row["output_hash"] == receipt["outputHash"]
                and json.loads(Path(path).read_text(encoding="utf-8")) == receipt,
                "native.spawn.lineage", "durable receipt and child terminal state differ")


def check_evaluation(receipt, result, parent, plan_hash):
    route = receipt.get("route") or {}
    role = receipt.get("role") or route.get("role")
    output = str(receipt.get("output") or "")
    admissible = (receipt.get("schema") == "neyvia.native-spawn-receipt/v1"
        and (not parent or receipt.get("parentSessionId") == parent)
        and (not plan_hash or receipt.get("planHash") == plan_hash)
        and receipt.get("status") == "completed" and receipt.get("contractHash") and receipt.get("receiptHash")
        and all(key in route for key in ("role", "provider", "model", "effort", "maximumTurns", "allowMutations"))
        and (role == "executor" or route.get("allowMutations") is not True)
        and output.strip() and receipt.get("outputHash") == hashlib.sha256(output.encode("utf-8")).hexdigest()
        and not receipt.get("error"))
    require(result["accepted"] is bool(admissible) and result["status"] == ("accepted" if admissible else "rejected")
            and (not result["accepted"] or not result["failures"]),
            "native.spawn.evaluate", "evaluation must follow lineage, route, completion and output integrity")


def check_hook(hook, authority, receipt, path):
    persisted = json.loads(Path(path).read_text(encoding="utf-8"))
    from .native_hooks import _hash
    require(persisted == receipt and persisted["receiptHash"] == _hash({key: value for key, value in persisted.items() if key != "receiptHash"}),
            "native.hooks.receipt", "hook receipt must preserve exact durable result and hash")
    if hook.allow_mutations and not authority:
        require(receipt["status"] == "approval_required" and not receipt["passed"] and "returnCode" not in receipt,
                "native.hooks.authority", "mutating hook without parent authority must not start")
    elif receipt["status"] in {"completed", "failed"}:
        require(receipt["passed"] is (receipt["returnCode"] == 0), "native.hooks.receipt", "hook result differs from process exit")


def observe(root):
    from .native_goals import NativeGoalStore
    from .native_pairing import NativePairingStore
    from .native_resource_profiles import resolve_resource_profile
    workspace = Path(root).resolve()
    return {"ok": True, "goals": NativeGoalStore(workspace).list(),
            "devices": NativePairingStore(workspace).list_devices(), "resourceProfile": resolve_resource_profile()}


def check_usage(payload, input_tokens, cached_tokens):
    require(payload["cachedInputTokens"] == cached_tokens and payload["uncachedInputTokens"] == max(0, input_tokens - cached_tokens)
            and payload["promptCacheHitRate"] == (round(cached_tokens / input_tokens, 4) if input_tokens else 0.0),
            "native.learning.usage", "usage normalization changed optional cache accounting")


def check_learning(connection, receipt):
    row = connection.execute("SELECT verified,status,proof_status FROM native_runs WHERE run_id=?", (receipt["runId"],)).fetchone()
    status = str(receipt.get("status") or "unknown")
    proof = str((receipt.get("proofAudit") or {}).get("status") or "not_audited")
    require(row is not None and row["status"] == status and row["proof_status"] == proof
            and bool(row["verified"]) is (status == "completed" and proof in {"verified", "completed_read_only"}),
            "native.learning.receipt-gate", "learned verification must follow receipt completion and audit status")


def check_recommendation(result):
    eligible = [row for row in result["candidates"] if row["attempts"] >= result["minimumSamples"]]
    require(result["eligible"] is bool(eligible) and result["applied"] is False
            and result["evidenceRuns"] == sum(row["attempts"] for row in result["candidates"])
            and (not result["eligible"] or result["recommendation"] in eligible),
            "native.learning.sample-floor", "learning must remain observational below its real sample floor")


def check_audit(result):
    refused = bool(not result["receiptAudit"]["accepted"]
        or (result["verificationRequired"] and (not result["verification"] or not result["verification"]["passed"]))
        or not result["finalWorkspaceFingerprintFresh"] or result["failures"])
    require(result["runStatus"] == ("blocked" if refused else "completed")
            and (not refused or result["status"] == "blocked"),
            "native.audit.failure-gate", "failure receipts, missing verification or stale workspace cannot complete a run")


def check_command(row, payload):
    require(payload["commandId"] == row["command_id"] and payload["status"] == row["status"]
            and payload["executionProven"] is (row["status"] == "succeeded") and payload["automaticRetry"] is False,
            "native.commands.receipt", "command observer must preserve exact state and never infer execution or retry")
    if row["status"] == "claimed":
        require(row["claim_id"] and row["approval_id"] and row["claim_expires_at"] <= row["expires_at"],
                "native.commands.deadline", "claim lease must not outlive its exact command authority")


def check_tool_receipt(payload, path, stored=None):
    # `stored` is the exact persisted bytes read back through the writing
    # handle before the atomic rename; without it the published file is read.
    require(payload["schema"] == "fluxio.native_tool_receipt.v1" and payload["receipt_path"] == str(path)
            and isinstance(payload.get("arguments"), dict) and payload.get("argument_snapshot_boundary")
            and payload.get("receiptHash") == hashlib.sha256(json.dumps(
                {key:value for key,value in payload.items() if key != "receiptHash"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            and json.loads(stored.decode("utf-8") if stored is not None else Path(path).read_text(encoding="utf-8")) == payload,
            "native.tools.receipt", "native action must return its exact digest-bound durable protocol receipt and admitted redacted argument snapshot")


def check_catalog(row, spec, include_schema):
    require(row["name"] == spec.name and row["schema_version"] == spec.schema_version
            and row["mutability_class"] == spec.mutability_class and tuple(row["capabilities"]) == spec.capabilities
            and ((row.get("inputSchema") == spec.input_schema) if include_schema else "inputSchema" not in row),
            "native.tools.catalog", "catalog projection differs from tool identity, schema or authority policy")


def check_preview(observed, content, offset):
    require(observed["text"] == content[offset:offset + 4000]
            and observed["reachable"] is (200 <= int(observed["status"]) < 400)
            and observed["contentSha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "native.tools.preview", "preview observer differs from fetched indexed content or HTTP status")


def check_inspiration(board, query, facets, enriched_query, payload):
    require(board["query"] == query and board["facets"] == facets and board["searchQuery"] == enriched_query
            and board["boardType"] == "ui-inspiration" and board["provider"] == payload["provider"]
            and board["results"] == payload["results"] and board["resultCount"] == len(payload["results"]),
            "native.tools.inspiration", "inspiration board must retain enriched query, facets and exact provider observations")
    # The underlying image provider's observed data remains its own evidence.


def check_annotation(annotation, rectangle, artifacts):
    require(annotation["@context"] == "http://www.w3.org/ns/anno.jsonld"
            and annotation["geometry"] == {"type": "RECTANGLE", "unit": "percent", **rectangle}
            and all(path.is_file() and path.stat().st_size > 0 for path in artifacts)
            and json.loads(artifacts[-1].read_text(encoding="utf-8")) == annotation,
            "native.tools.annotation", "annotation geometry or real screenshot artifacts differ from receipt")


def check_native_proposal(proposal):
    import urllib.parse
    target = proposal.args.get("tool")
    arguments = proposal.args.get("arguments")
    require(isinstance(target, str) and isinstance(arguments, dict)
            and proposal.requires_approval is (proposal.policy_decision == "requires_approval"),
            "native.tools.routing", "native route must carry typed arguments and preserve policy admission")
    if target == "preview.screenshot":
        require(urllib.parse.urlparse(arguments.get("url", "")).scheme in {"http", "https", "file"}
                and proposal.mutability_class == "verify", "native.tools.routing", "screenshot route lacks capture target or proof mutability")
    if target == "ui.inspiration.search":
        require(arguments.get("query") and proposal.mutability_class == "read", "native.tools.routing", "inspiration route lacks query or read-only policy")


def live_skill_journey(root):
    """Run in a child with a scratch CODEX_HOME, never against operator skills."""
    import os
    from .native_tools import NativeToolRegistry
    base = Path(root).resolve()
    _fixture_authority(base)
    codex_root = Path(os.environ["CODEX_HOME"]).resolve()
    codex_root.relative_to(base)
    workspace = base / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    skill = codex_root / "skills/native-proof/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    original = "---\nname: native-proof\ndescription: Inspect local bounded evidence.\n---\n\n# Native proof\n\nRead the receipt.\n"
    revised = original.replace("Read the receipt.", "Read the receipt and preserve its version.")
    skill.write_text(original, encoding="utf-8")
    registry = NativeToolRegistry(_fixture_root(workspace))
    current = registry.call("skill.live.read", {"skillId": "native-proof", "path": str(skill)})
    require(current["ok"], "native.tools.skill-revision", "scratch skill observer failed")
    result = registry.call("skill.live.iterate", {"skillId": "native-proof", "path": str(skill), "content": revised,
        "expectedSha256": current["result"]["sha256"], "sessionId": "native-live-proof", "request": "Preserve version evidence."})
    described = registry.describe("skill.live.iterate")
    require(result["ok"] and result["result"]["sessionId"] == "native-live-proof" and skill.read_text(encoding="utf-8") == revised
            and Path(result["receipt_path"]).is_file() and Path(result["result"]["receiptPath"]).is_file()
            and described["requires_approval"] and not described["parallel_safe"],
            "native.tools.skill-revision", "scratch skill action lacked content/version receipts or authority policy")
    return {"ok": True, "receiptPath": result["receipt_path"], "versionReceiptPath": result["result"]["receiptPath"]}


def self_check(root):
    """Actual storage/process journeys; a single scenario may cover several claims."""
    from .native_event_stream import NativeEventStream
    from .native_goals import NativeGoalStore
    from .native_pairing import NativePairingStore
    from .native_resource_profiles import normalize_resource_mode, resolve_resource_profile, _profile_for_memory
    from .native_spawn_contracts import NativeSpawnRegistry, build_specialist_routes
    from .native_spawn_evaluator import evaluate_spawn_receipt
    from .native_hooks import NativeHookRunner
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="native-", dir=base))
    cases = []

    def run(identity, contracts, action, *, prerequisites=()):
        from .contract_gate import wants
        if not wants([*contracts, *prerequisites]):
            return
        try:
            action()
            cases.append({"id": identity, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "error": str(error)})

    def refused(action, phrase=""):
        try:
            action()
        except (ValueError, KeyError, PermissionError) as error:
            require(not phrase or phrase in str(error), "native.rejection", "rejection reason changed")
        else:
            raise ValueError("Invalid operation was accepted")

    output = io.StringIO()
    stream = NativeEventStream(scratch, "native-proof", output=output)

    def events():
        first = stream.emit("run.started", {"mode": "scratch"})
        second = stream.emit("plan.compiled", {"planHash": "local-proof"})
        verification = stream.verify()
        require(first["sequence"] == 1 and second["previousHash"] == first["eventHash"]
                and verification["valid"] and verification["events"] == 2
                and [json.loads(line)["type"] for line in output.getvalue().splitlines()] == ["run.started", "plan.compiled"],
                "native.events.append", "stream observer differs from appended chain/output")

    def tampering():
        lines = stream.path.read_text(encoding="utf-8").splitlines()
        changed = json.loads(lines[0])
        changed["payload"] = {"corrupted": True}
        lines[0] = json.dumps(changed)
        stream.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rejected = stream.verify()
        require(not rejected["valid"] and any("hash mismatch" in failure for failure in rejected["failures"]),
                "native.events.integrity", "tampered chain was accepted")

    run("test_event_stream_is_hash_chained_and_streamable", ["native.events.append"], events)
    run("test_event_stream_detects_tampering", ["native.events.integrity"], tampering)
    goals = NativeGoalStore(scratch)
    goal = goals.create("Keep local proof durable", success_checks=["receipt"], milestones=["act", "observe", "receipt"], schedule_seconds=60)

    def heartbeat():
        saved = goals.heartbeat(goal["goalId"], run_id="native-proof", next_action="Observe local receipt", evidence={"receipt": "local.json"})
        require(saved["status"] == "active" and saved["lastRunId"] == "native-proof" and saved["lastHeartbeatAt"]
                and saved["nextAction"] == "Observe local receipt" and len(saved["milestones"]) == 3,
                "native.goals.durable", "heartbeat lost milestone or scheduling state")

    def due():
        unscheduled = goals.create("No schedule")
        with goals.connection() as db:
            db.execute("UPDATE native_goals SET next_due_at='2000-01-01T00:00:00Z' WHERE goal_id=?", (goal["goalId"],))
        require([item["goalId"] for item in goals.due()] == [goal["goalId"]]
                and unscheduled["goalId"] != goal["goalId"], "native.goals.due", "due observer includes unscheduled or misses due work")

    def completed():
        before = goals.get(goal["goalId"])
        refused(lambda: goals.complete(goal["goalId"], ""), "receipt")
        require(goals.get(goal["goalId"]) == before, "native.goals.complete", "receipt-free completion wrote state")
        saved = goals.complete(goal["goalId"], "proof/local.json")
        require(saved["status"] == "completed" and saved["completionReceipt"] == "proof/local.json" and not goals.due(),
                "native.goals.complete", "completed goal lacks receipt or remains due")

    run("test_goal_preserves_milestones_and_heartbeat", ["native.goals.durable"], heartbeat)
    run("test_due_query_returns_only_scheduled_active_goals", ["native.goals.due"], due)
    run("test_goal_completion_requires_receipt", ["native.goals.complete"], completed)
    pairing = NativePairingStore(scratch)
    paired = {}

    def pair():
        request = pairing.create("phone", scopes=["mission.read", "proof.read"], base_url="https://local.invalid")
        device = pairing.redeem(request["pairingId"], request["pairingToken"], "Scratch phone")
        paired.update(device)
        require(pairing.authenticate(device["deviceId"], device["deviceSecret"], "mission.read")
                and not pairing.authenticate(device["deviceId"], device["deviceSecret"], "workspace.write"),
                "native.pairing.authority", "scope gate changed")
        refused(lambda: pairing.redeem(request["pairingId"], request["pairingToken"], "Second device"), "already redeemed")
        with pairing.connection() as db:
            values = [dict(row) for table in ("pairing_requests", "paired_devices") for row in db.execute(f"SELECT * FROM {table}")]
        raw = json.dumps(values)
        require(request["pairingToken"] not in raw and device["deviceSecret"] not in raw,
                "native.pairing.digest", "plaintext pairing secrets persisted")

    def revoked():
        require(pairing.revoke(paired["deviceId"])["revoked"]
                and not pairing.authenticate(paired["deviceId"], paired["deviceSecret"]),
                "native.pairing.authority", "revoked device authenticated")

    def invalid_pair():
        before = pairing.list_devices()
        refused(lambda: pairing.create("spaceship"))
        refused(lambda: pairing.create("phone", scopes=["provider.secret.read"]))
        require(pairing.list_devices() == before, "native.pairing.scope-input", "invalid pairing changed devices")

    run("test_pairing_is_one_time_scoped_and_secret_free_at_rest", ["native.pairing.digest", "native.pairing.single-use", "native.pairing.authority"], pair)
    run("test_revoked_device_cannot_authenticate", ["native.pairing.authority"], revoked)
    run("test_pairing_rejects_unknown_scope_and_target", ["native.pairing.scope-input"], invalid_pair)
    run("test_eco_preserves_verification_reserve", ["native.resources.admission"], lambda: check_resource(_profile_for_memory("eco", 4096), "eco", 4096))
    run("test_auto_uses_memory_rich_profile_on_large_host", ["native.resources.admission"], lambda: check_resource(_profile_for_memory("auto", 65536), "auto", 65536))

    def aliases():
        require(normalize_resource_mode("low consumption") == "eco" and normalize_resource_mode("max") == "maximal", "native.resources.mode", "mode aliases changed")
        refused(lambda: normalize_resource_mode("infinite"))
        actual = resolve_resource_profile("auto")
        check_resource(actual, "auto", actual["detectedMemoryMb"])

    run("test_resource_mode_aliases_and_rejection", ["native.resources.mode", "native.resources.admission"], aliases)
    registry = NativeSpawnRegistry(scratch, "native-parent")
    routes = build_specialist_routes("default-model", raw_overrides={"planner": {"model": "planned-model", "effort": "medium"}, "verifier": {"effort": "xhigh"}},
        behavior_plan={"capsule": {"specialistRoles": ["planner", "verifier", "executor"]}}, resource_profile={"specialistLimit": 2})

    def capsule():
        require(list(routes) == ["planner", "verifier"] and routes["planner"].model == "planned-model"
                and routes["verifier"].effort == "xhigh" and all(not row.allow_mutations for row in routes.values()),
                "native.spawn.routes", "capsule and configured routes disagree")

    def mutation():
        selected = build_specialist_routes("default-model", raw_overrides={"planner": {"allowMutations": True}, "executor": {"allowMutations": True}},
            behavior_plan={"capsule": {"specialistRoles": ["planner", "executor"]}}, resource_profile={"specialistLimit": 2})
        require(not selected["planner"].allow_mutations and selected["executor"].allow_mutations, "native.spawn.routes", "mutation authority reached non-executor")

    def lineage():
        contract = registry.start(routes["verifier"], "Inspect local proof", "native-plan")
        receipt = registry.finish(contract, status="failed", error="local rejection")
        observed = registry.snapshot()
        require(receipt["parentSessionId"] == "native-parent" and receipt["childSessionId"].startswith("native-parent.verifier.")
                and receipt["receiptHash"] and observed["counts"]["failed"] == 1 and observed["children"][0]["receipt_path"],
                "native.spawn.lineage", "failed child lineage was lost")

    run("test_behavior_capsule_controls_spawned_specialist_team", ["native.spawn.routes"], capsule)
    run("test_only_executor_can_receive_mutation_authority", ["native.spawn.routes"], mutation)
    run("test_spawn_registry_preserves_parent_child_lineage_and_failure", ["native.spawn.lineage"], lineage)
    contract = registry.start(routes["planner"], "Plan local proof", "native-plan")
    accepted_receipt = registry.finish(contract, status="completed", output="dependency-aware plan with risks and proof gates", usage={"reportedByTransport": True}, run_items=["LocalProcedure"])

    def acceptance():
        result = evaluate_spawn_receipt(accepted_receipt, expected_parent_session_id="native-parent", expected_plan_hash="native-plan")
        require(result["accepted"] and result["contractValid"] and not result["explicitEvidenceLabelsAbsent"]
                and "general intelligence" in result["truthBoundary"], "native.spawn.evaluate", "valid local receipt rejected")

    def failed_child():
        changed = {**accepted_receipt, "status": "failed", "error": "local process failed"}
        result = evaluate_spawn_receipt(changed, expected_parent_session_id="native-parent", expected_plan_hash="native-plan")
        require(not result["accepted"] and any("not completed" in item for item in result["failures"]), "native.spawn.evaluate", "failed child accepted pleasant output")

    def unsafe_child():
        changed = {**accepted_receipt, "route": {**accepted_receipt["route"], "allowMutations": True}}
        result = evaluate_spawn_receipt(changed)
        require(not result["accepted"] and any("mutation authority" in item for item in result["failures"]), "native.spawn.evaluate", "unsafe route accepted")

    run("test_completed_child_with_matching_lineage_is_accepted", ["native.spawn.evaluate"], acceptance)
    run("test_pleasant_output_cannot_override_failed_status", ["native.spawn.evaluate"], failed_child)
    run("test_non_executor_mutation_authority_is_rejected", ["native.spawn.evaluate"], unsafe_child)
    hook_root = scratch / "hook-workspace"
    config = hook_root / ".neyvia/hooks.json"
    config.parent.mkdir(parents=True)

    def configure(row):
        config.write_text(json.dumps({"hooks": [row]}), encoding="utf-8")

    def hook_process():
        configure({"id": "observe", "event": "run.before", "argv": [sys.executable, "-c", "print('native-hook-proof')"], "blocking": True})
        result = NativeHookRunner(hook_root).run("run.before", {"runId": "native-proof"})
        require(result["passed"] and result["receipts"][0]["returnCode"] == 0
                and "native-hook-proof" in result["receipts"][0]["stdoutTail"]
                and Path(result["receiptPaths"][0]).is_file(), "native.hooks.receipt", "real hook process lacks successful durable receipt")

    def unauthorized_hook():
        configure({"id": "mutate", "event": "run.before", "argv": [sys.executable, "-c", "from pathlib import Path; Path('must-not-exist').write_text('bad')"], "blocking": True, "allowMutations": True})
        result = NativeHookRunner(hook_root).run("run.before")
        require(result["blocked"] and result["receipts"][0]["status"] == "approval_required" and not (hook_root / "must-not-exist").exists(),
                "native.hooks.authority", "unauthorized hook executed")

    def shell_string():
        configure({"id": "invalid", "event": "run.before", "argv": "echo unsafe"})
        refused(lambda: NativeHookRunner(hook_root), "string array")

    run("test_hook_runs_without_shell_and_writes_receipt", ["native.hooks.argv", "native.hooks.receipt"], hook_process)
    run("test_mutating_hook_requires_parent_authority", ["native.hooks.authority", "native.hooks.receipt"], unauthorized_hook)
    run("test_hook_schema_rejects_shell_string", ["native.hooks.argv"], shell_string)
    from .native_learning import NativeLearningStore, usage_payload, wilson_lower_bound
    from .native_proof_audit import NativeProofAuditor
    learning_root = scratch / "learning-workspace"
    learning_root.mkdir()
    auditor = NativeProofAuditor(learning_root)
    real_audit = auditor.audit(before=auditor.snapshot(), behavior_plan={"capsule": {"mutationExpected": False}}, allow_mutations=False)
    learning = NativeLearningStore(learning_root)
    common = {"status": real_audit["runStatus"], "proofAudit": real_audit,
              "behaviorPlan": {"planHash": "native-local", "capsule": {"id": "local-observe", "taskKinds": ["observation"]}},
              "resourceProfile": {"mode": "balanced"}, "model": "none-local", "usage": {}}

    def cache_usage():
        from types import SimpleNamespace
        normalized = usage_payload(SimpleNamespace(requests=2, input_tokens=100, output_tokens=30, total_tokens=130,
            input_tokens_details=SimpleNamespace(cached_tokens=40)))
        require(normalized["cachedInputTokens"] == 40 and normalized["uncachedInputTokens"] == 60
                and normalized["promptCacheHitRate"] == 0.4, "native.learning.usage", "cache details changed")

    def sample_floor():
        for index in range(3):
            learning.record_run({**common, "runId": f"observed-{index}"})
        recommendation = learning.recommend("observation", minimum_samples=8)
        adjustment = learning.behavior_adjustment("observation")
        require(not recommendation["eligible"] and not adjustment["applied"] and recommendation["evidenceRuns"] == 3,
                "native.learning.sample-floor", "three local receipts changed model behavior below sample floor")

    def failed_prose():
        other = NativeLearningStore(scratch / "learning-failed")
        other.record_run({**common, "runId": "positive"})
        other.record_run({**common, "runId": "negative", "status": "blocked", "proofAudit": {"status": "blocked"}})
        summary = other.summary()
        require(summary["attempts"] == 2 and summary["verifiedRuns"] == 1 and summary["verifiedRate"] == 0.5
                and wilson_lower_bound(1, 2) < 0.5, "native.learning.receipt-gate", "failed receipt counted as verified learning")

    run("test_usage_normalizes_optional_provider_cache_details", ["native.learning.usage"], cache_usage)
    run("test_learning_stays_observational_below_real_sample_floor", ["native.learning.sample-floor", "native.learning.receipt-gate"], sample_floor)
    run("test_failed_prose_never_counts_as_verified_learning", ["native.learning.receipt-gate"], failed_prose)

    def failed_audit():
        target = learning_root / "value.txt"
        target.write_text("before", encoding="utf-8")
        failed = learning_root / "failed.json"
        failed.write_text(json.dumps({"schema": "neyvia.native-local-receipt/v1", "status": "failed", "ok": False}), encoding="utf-8")
        before = auditor.snapshot()
        target.write_text("after", encoding="utf-8")
        result = auditor.audit(before=before, behavior_plan={"capsule": {"mutationExpected": True, "proofGates": ["workspace_delta", "receipt_integrity"]}},
                               allow_mutations=True, receipt_paths=[str(failed)])
        require(result["status"] == "blocked" and result["runStatus"] == "blocked" and result["workspaceDelta"]["changed"]
                and any("receipt" in failure.lower() for failure in result["failures"]), "native.audit.failure-gate", "failed receipt did not block changed workspace")

    def no_delta():
        result = auditor.audit(before=auditor.snapshot(), behavior_plan={"capsule": {"mutationExpected": True, "proofGates": ["workspace_delta"]}}, allow_mutations=True)
        require(result["runStatus"] == "blocked" and "expected a workspace delta" in " ".join(result["failures"]).lower(),
                "native.audit.delta", "prose completed a mutation without workspace delta")

    run("test_failed_receipt_blocks_even_when_workspace_changed", ["native.audit.failure-gate"], failed_audit)
    run("test_expected_mutation_without_delta_is_not_narrative_success", ["native.audit.delta", "native.audit.failure-gate"], no_delta)
    from .native_checkpoints import NativeCheckpointStore, RESTORE_TRANSACTION_SCHEMA

    def checkpoint_workspace(name):
        workspace = scratch / name
        workspace.mkdir()
        target = workspace / "value.txt"
        target.write_text("checkpoint", encoding="utf-8")
        store = NativeCheckpointStore(workspace)
        manifest = store.create(["value.txt", "created.txt"])
        target.write_text("current", encoding="utf-8")
        return workspace, target, store, manifest

    def restore_checkpoint():
        workspace, target, store, manifest = checkpoint_workspace("checkpoint-restore")
        new_file = workspace / "created.txt"
        new_file.write_text("new", encoding="utf-8")
        denied = store.restore(manifest["checkpointId"], approved=False)
        require(denied["status"] == "approval_required" and target.read_text(encoding="utf-8") == "current",
                "native.checkpoints.authority", "unapproved restore changed workspace")
        result = store.restore(manifest["checkpointId"], approved=True)
        require(result["status"] == "completed" and result["workspaceSafe"]
                and target.read_text(encoding="utf-8") == "checkpoint" and not new_file.exists()
                and Path(result["receiptPath"]).is_file(), "native.checkpoints.restore", "approved restore lost content or receipt")

    def checkpoint_dedup():
        workspace, target, store, _ = checkpoint_workspace("checkpoint-dedup")
        one, two = store.create(["value.txt"]), store.create(["value.txt"])
        require(one["entries"][0]["sha256"] == two["entries"][0]["sha256"]
                and len([path for path in store.blob_root.rglob("*") if path.is_file()]) == 2,
                "native.checkpoints.capture", "equal content was not deduplicated")

    def checkpoint_paths():
        _, _, store, _ = checkpoint_workspace("checkpoint-paths")
        refused(lambda: store.create([".env"]))
        refused(lambda: store.create(["../outside.txt"]))

    def checkpoint_preflight():
        workspace, target, store, manifest = checkpoint_workspace("checkpoint-preflight")
        digest = manifest["entries"][0]["sha256"]
        blob = store.blob_root / digest[:2] / digest
        blob.rename(blob.with_suffix(".unavailable"))
        result = store.restore(manifest["checkpointId"], approved=True)
        require(result["status"] == "failed_preflight" and result["workspaceSafe"]
                and result["recoveryAction"] == "none_required_no_mutation_started"
                and target.read_text(encoding="utf-8") == "current", "native.checkpoints.preflight", "missing blob partially restored workspace")

    def staged_recovery(name, state="applying", mutation="", missing=False, foreign=False):
        workspace, target, store, manifest = checkpoint_workspace("checkpoint-" + name)
        entries = store._validated_restore_entries(store.load(manifest["checkpointId"]))
        before = store._snapshot_workspace(entries)
        tx = {"schema": RESTORE_TRANSACTION_SCHEMA, "transactionId": "startup-interrupted", "checkpointId": manifest["checkpointId"],
              "status": state, "workspaceRoot": str(workspace / "foreign") if foreign else str(workspace),
              "targetEntries": entries, "beforeEntries": before, "workspaceSafe": state == "prepared", "createdAt": "2000-01-01T00:00:00Z"}
        store._write_transaction(tx)
        if state == "applying" and not foreign:
            store._apply_entries(entries)
        if mutation:
            target.write_text(mutation, encoding="utf-8")
        if missing:
            digest = before[0]["sha256"]
            blob = store.blob_root / digest[:2] / digest
            blob.rename(blob.with_suffix(".unavailable"))
        reopened = NativeCheckpointStore(workspace)
        if foreign:
            require(target.read_text(encoding="utf-8") == mutation and not reopened.recovery_status()["safeToRestore"]
                    and "different workspace" in reopened.recovery_status()["detail"], "native.checkpoints.recovery", "foreign journal replayed")
        elif missing:
            result = reopened.restore(manifest["checkpointId"], approved=True)
            require(not reopened.recovery_status()["safeToRestore"] and result["status"] == "recovery_failed"
                    and not result["workspaceSafe"] and result["recoveryAction"] == "manual_recovery_required",
                    "native.checkpoints.recovery", "unrecoverable rollback silently allowed restore")
        elif state == "prepared":
            journal = reopened._load_transaction(reopened.transaction_root / "startup-interrupted.json")
            require(target.read_text(encoding="utf-8") == mutation and journal["status"] == "aborted_before_apply"
                    and reopened.recovery_status()["status"] == "ready", "native.checkpoints.recovery", "prepared recovery overwrote later edit")
        elif mutation:
            journal = reopened._load_transaction(reopened.transaction_root / "startup-interrupted.json")
            require(target.read_text(encoding="utf-8") == mutation and not reopened.recovery_status()["safeToRestore"]
                    and journal["status"] == "recovery_failed" and journal["conflictPaths"] == ["value.txt"],
                    "native.checkpoints.recovery", "conflicting external edit was overwritten")
        else:
            journal = reopened._load_transaction(reopened.transaction_root / "startup-interrupted.json")
            require(target.read_text(encoding="utf-8") == "current" and journal["status"] == "rolled_back"
                    and list(reopened.restore_root.glob("restore-*.json")), "native.checkpoints.recovery", "interrupted transaction failed to recover durable before-image")

    run("test_checkpoint_restores_changed_and_new_files", ["native.checkpoints.authority", "native.checkpoints.restore"], restore_checkpoint)
    run("test_checkpoint_is_content_addressed_and_deduplicated", ["native.checkpoints.capture"], checkpoint_dedup)
    run("test_checkpoint_refuses_secret_and_escape_paths", ["native.checkpoints.scope"], checkpoint_paths)
    run("test_restore_preflight_failure_never_partially_mutates_workspace", ["native.checkpoints.preflight"], checkpoint_preflight)
    run("test_reopen_rolls_back_an_interrupted_restore_transaction", ["native.checkpoints.recovery", "native.checkpoints.restore"], lambda: staged_recovery("applying"))
    run("test_prepared_crash_preserves_later_workspace_edits_without_rollback", ["native.checkpoints.recovery"], lambda: staged_recovery("prepared", state="prepared", mutation="later-edit"))
    run("test_recovery_conflict_preserves_external_edit_instead_of_overwriting", ["native.checkpoints.recovery"], lambda: staged_recovery("conflict", mutation="external-edit"))
    run("test_unresolved_recovery_failure_degrades_restore_without_taking_down_store", ["native.checkpoints.recovery"], lambda: staged_recovery("missing", missing=True))
    run("test_restore_journal_from_different_workspace_is_never_replayed", ["native.checkpoints.recovery", "native.checkpoints.scope"], lambda: staged_recovery("foreign", mutation="preserved", foreign=True))
    from .neyvia_mcp_stdio import CompactNeyviaMCPServer
    mcp = CompactNeyviaMCPServer(_fixture_root(scratch / "read-only-mcp"), read_only=True)

    def mcp_call(name, arguments, identity=1):
        return mcp.handle({"jsonrpc": "2.0", "id": identity, "method": "tools/call", "params": {"name": name, "arguments": arguments}})

    def mcp_catalog():
        response = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {row["name"] for row in response["result"]["tools"]}
        require({"neyvia.cl", "neyvia.cl.describe", "neyvia.tools.search", "neyvia.tools.invoke"} <= names
                and response["result"]["catalogPolicy"]["mode"] == "manual-first"
                and not {"neyvia.workspace.prove", "neyvia.workspace.browser"} & names,
                "native.mcp.read-only", "read-only catalog exposes an unauthorized operation")
        described = mcp_call("neyvia.tools.describe", {"name": "neyvia.workspace.prove"})["result"]["structuredContent"]
        require("operation" in described["inputSchema"]["properties"] and described["callTarget"] == "neyvia.tools.invoke",
                "native.mcp.discovery", "manual-first deferred discovery lost callable target")
        denied = mcp_call(described["callTarget"], {**described["callArguments"], "arguments": {"operation": "click"}})
        require(denied.get("error", {}).get("code") == -32003, "native.mcp.read-only", "deferred invocation bypassed read-only gate")

    def mcp_search():
        response = mcp_call("neyvia.tools.search", {"query": "workspace"})
        require("error" not in response and "result" in response, "native.mcp.discovery", "progressive search is not callable")

    def mcp_denied():
        for name, arguments in (("neyvia.workspace.browser", {"operation": "click"}), ("unknown.tool", {})):
            response = mcp_call(name, arguments)
            require(response.get("error", {}).get("code") == -32003, "native.mcp.read-only", "unknown/mutating call bypassed authority")

    run("test_list_matches_read_only_allowlist", ["native.mcp.read-only", "native.mcp.discovery"], mcp_catalog)
    run("test_progressive_search_is_callable", ["native.mcp.discovery"], mcp_search)
    run("test_mutating_browser_and_unknown_calls_are_denied", ["native.mcp.read-only"], mcp_denied)
    run("test_prove_rejects_non_observational_operation", ["native.mcp.read-only"], lambda: require(mcp_call("neyvia.workspace.prove", {"operation": "click"}).get("error", {}).get("code") == -32003, "native.mcp.read-only", "prove accepted mutation"))
    from .native_device_commands import NativeDeviceCommandStore
    context = {"actor_id": "agent:native-proof", "session_id": "session:native-proof", "run_id": "run:native-proof"}

    def command_workspace(name):
        workspace = scratch / ("commands-" + name)
        pair = NativePairingStore(workspace)
        request = pair.create("phone", scopes=["device.commands"])
        device = pair.redeem(request["pairingId"], request["pairingToken"], "Local control-plane fixture")
        store = NativeDeviceCommandStore(workspace)
        store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open", "notification.show"])
        return pair, device, store

    def approval(store, device, arguments=None, ttl=300):
        result = store.request_approval(device["deviceId"], "app.open", arguments=arguments or {"route": "agent"}, ttl_seconds=ttl, **context)
        store.decide_approval(result["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True)
        return result

    def queued(store, device, key, arguments=None, ttl=300, approval_ttl=300):
        authorized = approval(store, device, arguments, approval_ttl)
        return store.enqueue(device["deviceId"], "app.open", arguments=arguments or {"route": "agent"}, idempotency_key=key,
                             approval_id=authorized["approvalId"], ttl_seconds=ttl, **context)

    def edit_command(store, command, fields):
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_commands SET " + ",".join(key + "=?" for key in fields) + " WHERE command_id=?",
                       (*fields.values(), command["commandId"]))

    def commands_scope():
        _, device, store = command_workspace("scope")
        published = store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open", "notification.show"])
        require(published["capabilities"] == ["app.open", "notification.show"] and not published["providerSecretsIncluded"],
                "native.commands.scope", "advertisement changed capability authority or exposed provider secrets")
        refused(lambda: store.request_approval(device["deviceId"], "camera.capture", **context), "advertised capability")
        refused(lambda: store.publish_capabilities(device["deviceId"], "wrong-secret", ["app.open"]), "credential")
        store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["notification.show"])
        refused(lambda: approval(store, device), "advertised capability")
        refused(lambda: store.claim(device["deviceId"], "wrong-secret"), "credential")

    def exact_approval():
        _, device, store = command_workspace("exact")
        authorized = approval(store, device)
        for mismatch in ({"arguments": {"route": "settings"}}, {"actor_id": "agent:other"}, {"session_id": "session:other"}, {"run_id": "run:other"}):
            args = {"arguments": {"route": "agent"}, **context, **mismatch}
            refused(lambda args=args: store.enqueue(device["deviceId"], "app.open", idempotency_key="exact-approval-0001", approval_id=authorized["approvalId"], **args), "match")
        first = store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="exact-approval-0001", approval_id=authorized["approvalId"], **context)
        require(first["humanApprovalBound"] and first["status"] == "queued"
                and all(first[field] == context[input_name] for field, input_name in (("actorId", "actor_id"), ("sessionId", "session_id"), ("runId", "run_id")))
                and store.get_approval(authorized["approvalId"])["status"] == "consumed",
                "native.commands.approval", "exact approval did not bind its durable context and single use")
        refused(lambda: store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="exact-approval-0002", approval_id=authorized["approvalId"], **context), "not executable")

    def explicit_decision():
        _, device, store = command_workspace("decision")
        requested = store.request_approval(device["deviceId"], "app.open", arguments={"route": "agent"}, **context)
        require(requested["status"] == "pending" and not requested["humanIdentityCryptographicallyVerified"], "native.commands.approval", "unsigned attestation fabricated cryptographic identity")
        refused(lambda: store.decide_approval(requested["approvalId"], decision="approved", decided_by="human:local", human_confirmed=False), "human confirmation")
        denied = store.decide_approval(requested["approvalId"], decision="denied", decided_by="human:local", human_confirmed=True)
        require(denied["status"] == "denied", "native.commands.approval", "denial failed")
        refused(lambda: store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="denial-native-0001", approval_id=requested["approvalId"], **context), "not executable")

    def idempotency():
        _, device, store = command_workspace("idempotent")
        authorized = approval(store, device)
        kwargs = {"arguments": {"route": "agent"}, "idempotency_key": "idempotent-native-0001", "approval_id": authorized["approvalId"], **context}
        one, two = store.enqueue(device["deviceId"], "app.open", **kwargs), store.enqueue(device["deviceId"], "app.open", **kwargs)
        require(one["commandId"] == two["commandId"], "native.commands.idempotency", "retry created duplicate command")
        refused(lambda: store.enqueue(device["deviceId"], "app.open", **{**kwargs, "arguments": {"route": "library"}}), "different device command")

    def tampered():
        _, device, store = command_workspace("tampered")
        command = queued(store, device, "tampered-native-0001")
        edit_command(store, command, {"request_hash": "0" * 64})
        require(store.claim(device["deviceId"], device["deviceSecret"]) is None, "native.commands.final-gate", "tampered command delivered")
        result = store.get(command["commandId"])
        require(result["status"] == "rejected" and result["errorCode"] == "authorization-invalid" and not result["executionProven"], "native.commands.final-gate", "tampered queue did not fail closed")

    def single_flight():
        _, device, store = command_workspace("single-flight")
        command = queued(store, device, "single-flight-native-0001")
        claimed = store.claim(device["deviceId"], device["deviceSecret"])
        other = NativeDeviceCommandStore(store.root)
        require(claimed["commandId"] == command["commandId"] and claimed["arguments"] == {"route": "agent"}
                and other.claim(device["deviceId"], device["deviceSecret"]) is None, "native.commands.single-flight", "second store replayed claimed command")
        kwargs = {"status": "succeeded", "result": {"handled": True}}
        first = other.complete(device["deviceId"], device["deviceSecret"], claimed["commandId"], claimed["claimId"], **kwargs)
        repeated = store.complete(device["deviceId"], device["deviceSecret"], claimed["commandId"], claimed["claimId"], **kwargs)
        require(first["executionProven"] and repeated["status"] == "succeeded", "native.commands.receipt", "matching terminal receipt retry failed")
        refused(lambda: store.complete(device["deviceId"], device["deviceSecret"], claimed["commandId"], claimed["claimId"], status="failed"), "already terminal")

    def cancellation(after_claim=False):
        _, device, store = command_workspace("cancel-after" if after_claim else "cancel-before")
        command = queued(store, device, "cancel-native-0001")
        kwargs = {**context, "cancelled_by": "human:local", "human_confirmed": True}
        if after_claim:
            store.claim(device["deviceId"], device["deviceSecret"])
            refused(lambda: store.cancel(command["commandId"], **kwargs), "only be cancelled before claim")
            require(store.get(command["commandId"])["status"] == "claimed", "native.commands.cancel", "cancel fabricated a stop")
        else:
            refused(lambda: store.cancel(command["commandId"], **{**kwargs, "human_confirmed": False}), "human confirmation")
            refused(lambda: store.cancel(command["commandId"], **{**kwargs, "run_id": "run:wrong"}), "context")
            result = store.cancel(command["commandId"], **kwargs)
            require(result["status"] == "cancelled" and not result["executionProven"]
                    and store.claim(device["deviceId"], device["deviceSecret"]) is None, "native.commands.cancel", "cancelled queued command delivered")

    def uncertainty(name, reason="lease", settle=False, successful=True):
        _, device, store = command_workspace(name)
        command = queued(store, device, "uncertain-native-0001")
        claimed = store.claim(device["deviceId"], device["deviceSecret"])
        now = datetime.now(timezone.utc)
        past, future = (now - timedelta(seconds=1)).isoformat(), (now + timedelta(minutes=4)).isoformat()
        if reason == "lease":
            edit_command(store, command, {"claim_expires_at": past})
            expected_error = "claim-lost"
        elif reason == "command":
            edit_command(store, command, {"expires_at": past, "claim_expires_at": future})
            expected_error = "command-expired-after-claim"
        else:
            store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["notification.show"])
            expected_error = "capability-withdrawn-after-claim"
        observed = store.get(command["commandId"])
        require(observed["status"] == "uncertain" and observed["errorCode"] == expected_error
                and not observed["automaticRetry"] and not observed["executionProven"]
                and store.claim(device["deviceId"], device["deviceSecret"]) is None,
                "native.commands.uncertainty", "lost authority fabricated success or replayed claimed command")
        if settle:
            refused(lambda: store.complete(device["deviceId"], device["deviceSecret"], claimed["commandId"], "claim_wrong", status="succeeded"), "already terminal")
            status = "succeeded" if successful else "failed"
            resolved = store.complete(device["deviceId"], device["deviceSecret"], claimed["commandId"], claimed["claimId"], status=status,
                                      result={"handled": successful}, error_code="" if successful else "capability-stopped")
            require(resolved["status"] == status and resolved["executionProven"] is successful,
                    "native.commands.receipt", "authenticated matching late receipt failed to reconcile uncertainty")

    def expired_queue():
        _, device, store = command_workspace("expiry")
        command = queued(store, device, "expiry-native-0001")
        edit_command(store, command, {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})
        require(store.claim(device["deviceId"], device["deviceSecret"]) is None and store.get(command["commandId"])["status"] == "expired",
                "native.commands.final-gate", "expired unclaimed command executed")

    def withdrawn(revoke=False):
        pair, device, store = command_workspace("revoked" if revoke else "withdrawn")
        first = queued(store, device, "withdraw-native-0001")
        claim = store.claim(device["deviceId"], device["deviceSecret"])
        second = queued(store, device, "withdraw-native-0002", arguments={"route": "library"})
        if revoke:
            pair.revoke(device["deviceId"])
            refused(lambda: store.claim(device["deviceId"], device["deviceSecret"]))
        else:
            store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["notification.show"])
        require(store.get(first["commandId"])["status"] == "uncertain" and store.get(second["commandId"])["status"] == "rejected",
                "native.commands.final-gate", "withdrawal/revocation retained queued authority or fabricated a claimed stop")
        if not revoke:
            refused(lambda: store.complete(device["deviceId"], device["deviceSecret"], claim["commandId"], "claim_wrong", status="succeeded"), "already terminal")
            settled = store.complete(device["deviceId"], device["deviceSecret"], claim["commandId"], claim["claimId"], status="succeeded", result={"handled": True})
            require(settled["executionProven"], "native.commands.receipt", "matching late withdrawal receipt refused")

    def secrets():
        _, device, store = command_workspace("secrets")
        refused(lambda: store.request_approval(device["deviceId"], "app.open", arguments={"apiToken": "local-sensitive-fixture"}, **context), "credential/secret")
        queued(store, device, "nonplaintext-native-0001")
        with store.connection() as db:
            values = [dict(row) for table in ("device_commands", "device_command_approvals", "paired_devices") for row in db.execute(f"SELECT * FROM {table}")]
        require(device["deviceSecret"] not in json.dumps(values) and "nonplaintext-native-0001" not in json.dumps(values),
                "native.commands.secret-free", "device secret or raw idempotency key persisted")

    def deadline(lease=False):
        _, device, store = command_workspace("lease-cap" if lease else "authority-cap")
        command = queued(store, device, "deadline-native-0001", ttl=3600, approval_ttl=30)
        authorized = store.get_approval(command["approvalId"])
        require(command["expiresAt"] <= authorized["expiresAt"], "native.commands.deadline", "command outlived human authority")
        if lease:
            edit_command(store, command, {"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat().replace("+00:00", "Z")})
            claim = store.claim(device["deviceId"], device["deviceSecret"], lease_seconds=300)
            require(claim["claimExpiresAt"] == claim["expiresAt"], "native.commands.deadline", "claim lease exceeded short command authority")

    def expired_approval():
        _, device, store = command_workspace("approval-expired")
        granted = approval(store, device)
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_command_approvals SET expires_at=? WHERE approval_id=?",
                       ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), granted["approvalId"]))
        refused(lambda: store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="expired-authority-0001", approval_id=granted["approvalId"], **context), "expired")
        require(store.get_approval(granted["approvalId"])["status"] == "expired", "native.commands.approval", "expired authority was consumed")

    def legacy_unbound():
        _, device, store = command_workspace("legacy-unbound")
        now = datetime.now(timezone.utc)
        with store.connection(immediate=True) as db:
            db.execute("INSERT INTO device_commands(command_id,device_id,action,arguments_json,idempotency_hash,request_hash,created_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?)",
                       ("legacy-unbound", device["deviceId"], "app.open", "{}", "legacy-idempotency", hashlib.sha256(b"app.open\0{}").hexdigest(), now.isoformat(), (now+timedelta(minutes=5)).isoformat(), "queued"))
        require(store.claim(device["deviceId"], device["deviceSecret"]) is None, "native.commands.final-gate", "legacy unbound command delivered")
        result = store.get("legacy-unbound")
        require(result["status"] == "rejected" and result["errorCode"] == "authorization-invalid" and not result["humanApprovalBound"] and not result["executionProven"],
                "native.commands.final-gate", "legacy command fabricated approval or execution")

    command_cases = [
        ("test_device_commands_require_authenticated_advertised_capability", ["native.commands.scope"], commands_scope),
        ("test_human_approval_is_exact_single_use_and_context_bound", ["native.commands.approval"], exact_approval),
        ("test_approval_decision_requires_explicit_human_confirmation_and_denial_fails_closed", ["native.commands.approval"], explicit_decision),
        ("test_command_idempotency_prevents_duplicate_side_effect_requests", ["native.commands.idempotency"], idempotency),
        ("test_final_claim_gate_rejects_tampered_command_without_delivery", ["native.commands.final-gate"], tampered),
        ("test_claim_is_single_flight_and_terminal_receipt_is_idempotent", ["native.commands.single-flight", "native.commands.receipt"], single_flight),
        ("test_human_cancel_before_claim_is_terminal_and_not_delivered", ["native.commands.cancel"], cancellation),
        ("test_cancel_after_claim_does_not_fabricate_a_stop", ["native.commands.cancel"], lambda: cancellation(True)),
        ("test_lost_claim_becomes_uncertain_and_is_never_replayed", ["native.commands.uncertainty"], lambda: uncertainty("lost-claim")),
        ("test_expired_unclaimed_command_does_not_execute", ["native.commands.final-gate"], expired_queue),
        ("test_device_revocation_rejects_queued_and_marks_claimed_uncertain", ["native.commands.final-gate"], lambda: withdrawn(True)),
        ("test_command_payload_rejects_secret_fields_and_device_secret_stays_out_of_db", ["native.commands.secret-free"], secrets),
        ("test_late_authenticated_receipt_resolves_uncertain_claim_without_replay", ["native.commands.uncertainty", "native.commands.receipt"], lambda: uncertainty("late-lease", settle=True)),
        ("test_capability_withdrawal_never_silently_executes_stale_commands", ["native.commands.final-gate", "native.commands.receipt"], withdrawn),
        ("test_command_deadline_never_outlives_human_approval", ["native.commands.deadline"], deadline),
        ("test_claim_lease_never_outlives_command_authority_window", ["native.commands.deadline"], lambda: deadline(True)),
        ("test_legacy_overlong_claim_becomes_uncertain_at_command_expiry_without_replay", ["native.commands.deadline", "native.commands.uncertainty"], lambda: uncertainty("overlong-claim", reason="command")),
        ("test_late_authenticated_receipt_can_reconcile_command_expiry_uncertainty", ["native.commands.uncertainty", "native.commands.receipt"], lambda: uncertainty("late-command", reason="command", settle=True)),
        ("test_capability_withdrawal_uncertainty_accepts_only_matching_late_receipt", ["native.commands.uncertainty", "native.commands.receipt"], lambda: uncertainty("late-withdrawal", reason="capability", settle=True, successful=False)),
        ("test_expired_human_approval_cannot_be_consumed_into_a_command", ["native.commands.approval"], expired_approval),
        ("test_legacy_unbound_queued_command_fails_closed_before_device_delivery", ["native.commands.final-gate"], legacy_unbound),
    ]
    for name, contract_ids, action in command_cases:
        run(name, contract_ids, action)
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from .native_device_operator_authority import OperatorAuthorizedDeviceCommandStore, OPERATOR_DECISION_SCHEMA
    from .native_device_operator_signing_wire import prepare_signing_request, inspect_signing_request, submit_operator_signature

    def authority_workspace(name, arguments=None):
        base = scratch / ("operator-" + name)
        workspace = base / "workspace"
        workspace.mkdir(parents=True)
        private = Ed25519PrivateKey.generate()
        public = private.public_key()
        public_path = base / "scratch-public.pem"
        public_path.write_bytes(public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        key_id = "sha256:" + hashlib.sha256(raw).hexdigest()
        pair = NativePairingStore(workspace)
        request = pair.create("phone", scopes=["device.commands"])
        device = pair.redeem(request["pairingId"], request["pairingToken"], "Cryptographic scratch fixture")
        store = OperatorAuthorizedDeviceCommandStore(workspace, operator_public_key_path=public_path, operator_key_id=key_id)
        store.publish_capabilities(device["deviceId"], device["deviceSecret"], ["app.open"])
        requested = store.request_approval(device["deviceId"], "app.open", arguments=arguments or {"route": "agent"}, **context)
        return store, device, private, public_path, key_id, requested

    def signature(private, inspected):
        return base64.b64encode(private.sign(inspected["signingBytes"])).decode("ascii")

    def envelope(private, key_id, payload):
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {"schema": OPERATOR_DECISION_SCHEMA, "algorithm": "ed25519", "keyId": key_id, "payload": payload,
                "signature": base64.b64encode(private.sign(raw)).decode("ascii")}

    def wire(store, requested):
        return prepare_signing_request(store, requested["approvalId"], decided_by="human:local")

    def pinning():
        store, _, _, public_path, key_id, _ = authority_workspace("pinning")
        status = store.operator_authority_status()
        require(status["ready"] and status["keyId"] == key_id and not status["privateKeyLoaded"]
                and status["publicKeyPinnedOutsideWorkspace"], "native.operator.pinned-verifier", "external public verifier status differs")
        inside = store.root / "scratch-public.pem"
        inside.write_bytes(public_path.read_bytes())
        refused(lambda: OperatorAuthorizedDeviceCommandStore(store.root, operator_public_key_path=inside, operator_key_id=key_id), "outside the mutable workspace")
        refused(lambda: OperatorAuthorizedDeviceCommandStore(store.root, operator_public_key_path=public_path, operator_key_id="sha256:" + "0" * 64), "fingerprint")

    def unsigned_decision():
        store, device, _, _, _, requested = authority_workspace("unsigned")
        refused(lambda: store.decide_approval(requested["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True), "externally signed")
        denied = store.decide_approval(requested["approvalId"], decision="denied", decided_by="human:local", human_confirmed=True)
        require(denied["status"] == "denied" and not denied["humanIdentityCryptographicallyVerified"], "native.operator.signature", "unsigned denial granted authority or identity")
        # Explicit blank configuration prevents consulting protected environment paths.
        unconfigured = OperatorAuthorizedDeviceCommandStore(store.root, operator_public_key_path=" ", operator_key_id=" ")
        require(not unconfigured.operator_authority_status()["ready"], "native.operator.signature", "missing verifier fabricated authority")
        pending = unconfigured.request_approval(device["deviceId"], "app.open", arguments={"route": "agent"}, **context)
        refused(lambda: unconfigured.decide_approval(pending["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True), "externally signed")

    def signed_restart():
        store, device, private, public_path, key_id, requested = authority_workspace("restart")
        request = wire(store, requested)
        decided = submit_operator_signature(store, request, signature_base64=signature(private, inspect_signing_request(request)))
        require(decided["status"] == "approved" and decided["operatorSignatureRecorded"] and decided["operatorDecisionSignatureVerified"]
                and decided["operatorAuthorityKeyId"] == key_id and not decided["humanIdentityCryptographicallyVerified"],
                "native.operator.signature", "signed decision lost its exact authority boundary")
        command = store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="operator-restart-0001", approval_id=requested["approvalId"], **context)
        reopened = OperatorAuthorizedDeviceCommandStore(store.root, operator_public_key_path=public_path, operator_key_id=key_id)
        require(reopened.get_approval(requested["approvalId"])["operatorDecisionSignatureVerified"], "native.operator.signature", "signature did not survive restart")
        claim = reopened.claim(device["deviceId"], device["deviceSecret"])
        require(claim["commandId"] == command["commandId"], "native.operator.final-gate", "exact signed command was not claimable")
        settled = reopened.complete(device["deviceId"], device["deviceSecret"], claim["commandId"], claim["claimId"], status="succeeded", result={"handled": True})
        with reopened.connection() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(device_command_operator_authority)")}
        require(settled["executionProven"] and not {"private_key", "private_key_pem"} & columns,
                "native.operator.signature", "completed authority persisted private signing material")

    def replay_signature():
        store, device, private, _, key_id, first = authority_workspace("replay")
        payload = store.build_operator_decision_payload(first["approvalId"], decision="approved", decided_by="human:local")
        signed = envelope(private, key_id, payload)
        store.decide_approval(first["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True, signed_decision=signed)
        second = store.request_approval(device["deviceId"], "app.open", arguments={"route": "agent"}, **context)
        refused(lambda: store.decide_approval(second["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True, signed_decision=signed), "approvalId")

    def cryptographic_tamper():
        store, device, private, _, _, requested = authority_workspace("database-tamper")
        request = wire(store, requested)
        submit_operator_signature(store, request, signature_base64=signature(private, inspect_signing_request(request)))
        command = store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="operator-tamper-0001", approval_id=requested["approvalId"], **context)
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_command_approvals SET decided_by=? WHERE approval_id=?", ("human:tampered", requested["approvalId"]))
        require(store.claim(device["deviceId"], device["deviceSecret"]) is None, "native.operator.final-gate", "tampered signed approver delivered command")
        result = store.get(command["commandId"])
        require(result["status"] == "rejected" and result["errorCode"] == "authorization-invalid"
                and "operator-signature-invalid" in result["errorMessage"] and not result["executionProven"],
                "native.operator.final-gate", "cryptographic final gate did not explain rejected tamper")

    def strict_arguments():
        store, _, private, _, key_id, requested = authority_workspace("json-types", {"confirmed": 1})
        payload = store.build_operator_decision_payload(requested["approvalId"], decision="approved", decided_by="human:local")
        payload["arguments"]["confirmed"] = True
        refused(lambda: store.decide_approval(requested["approvalId"], decision="approved", decided_by="human:local", human_confirmed=True, signed_decision=envelope(private, key_id, payload)), "arguments")

    def signed_denial():
        store, device, private, _, key_id, requested = authority_workspace("signed-denial")
        payload = store.build_operator_decision_payload(requested["approvalId"], decision="approved", decided_by="human:local")
        payload["decision"] = "denied"
        signed = envelope(private, key_id, payload)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with store.connection(immediate=True) as db:
            db.execute("UPDATE device_command_approvals SET status='approved',decided_at=?,decided_by=?,decision_note='' WHERE approval_id=?", (now, "human:local", requested["approvalId"]))
            db.execute("INSERT INTO device_command_operator_authority(approval_id,schema,key_id,payload_json,payload_hash,signature_base64,issued_at,verified_at) VALUES (?,?,?,?,?,?,?,?)",
                       (requested["approvalId"], OPERATOR_DECISION_SCHEMA, key_id, raw, hashlib.sha256(raw.encode("utf-8")).hexdigest(), signed["signature"], payload["issuedAt"], now))
        command = store.enqueue(device["deviceId"], "app.open", arguments={"route": "agent"}, idempotency_key="operator-denial-0001", approval_id=requested["approvalId"], **context)
        require(store.claim(device["deviceId"], device["deviceSecret"]) is None and store.get(command["commandId"])["status"] == "rejected",
                "native.operator.final-gate", "signed denial became execution authority after database tamper")

    def exact_wire():
        arguments = {"route": "agent", "label": "Résumé 😀", "enabled": True, "count": 1, "ratio": 1e-7}
        store, device, private, _, _, requested = authority_workspace("wire-exact", arguments)
        request = wire(store, requested)
        inspected = inspect_signing_request(request)
        require(inspected["signingRule"] == "sign-decoded-signingBytesBase64-exactly" and not request["privateKeyRequiredByNeyvia"]
                and inspected["review"]["arguments"] == arguments, "native.operator.wire", "review lost exact unicode/JSON transaction")
        decided = submit_operator_signature(store, request, signature_base64=signature(private, inspected))
        command = store.enqueue(device["deviceId"], "app.open", arguments=arguments, idempotency_key="operator-wire-0001", approval_id=requested["approvalId"], **context)
        require(decided["operatorDecisionSignatureVerified"] and store.claim(device["deviceId"], device["deviceSecret"])["commandId"] == command["commandId"],
                "native.operator.wire", "opaque exact bytes failed real sign/verify/claim journey")

    def invalid_wire(name, change):
        store, device, private, _, _, requested = authority_workspace(name)
        request = wire(store, requested)
        inspected = inspect_signing_request(request)
        if change == "review":
            request["review"]["action"] = "camera.capture"
            refused(lambda: inspect_signing_request(request), "review")
        elif change == "bytes":
            raw = json.dumps(inspected["payload"], ensure_ascii=False, indent=2).encode("utf-8")
            request["signingBytesBase64"] = base64.b64encode(raw).decode("ascii")
            request["signingBytesSha256"] = hashlib.sha256(raw).hexdigest()
            refused(lambda: inspect_signing_request(request), "server canonical form")
        elif change == "store":
            signed = signature(private, inspected)
            with store.connection(immediate=True) as db:
                db.execute("UPDATE device_command_approvals SET actor_id=? WHERE approval_id=?", ("agent:tampered", requested["approvalId"]))
            refused(lambda: submit_operator_signature(store, request, signature_base64=signed))
        else:
            submit_operator_signature(store, request, signature_base64=signature(private, inspected))
            second = store.request_approval(device["deviceId"], "app.open", arguments={"route": "agent"}, **context)
            request["approvalId"] = second["approvalId"]
            refused(lambda: inspect_signing_request(request), "approvalId")

    def interoperable():
        for index, (value, phrase) in enumerate(((float("nan"), "NaN and Infinity"), (float("inf"), "NaN and Infinity"), (9007199254740992, "safe range"))):
            store, _, _, _, _, requested = authority_workspace(f"noninterop-{index}", {"value": value})
            refused(lambda: wire(store, requested), phrase)

    def lost_ack():
        store, _, private, _, _, requested = authority_workspace("retry-ack")
        request = wire(store, requested)
        signed = signature(private, inspect_signing_request(request))
        first = submit_operator_signature(store, request, signature_base64=signed)
        repeated = submit_operator_signature(store, request, signature_base64=signed)
        require(first["status"] == repeated["status"] == "approved" and first["approvalId"] == repeated["approvalId"]
                and repeated["operatorDecisionSignatureVerified"] and store.get_approval(requested["approvalId"])["status"] == "approved",
                "native.operator.retry", "acknowledgement retry minted new authority or changed decision")

    authority_cases = [
        ("test_operator_verifier_requires_external_pinned_ed25519_key", ["native.operator.pinned-verifier"], pinning),
        ("test_approved_decision_fails_closed_without_external_signature_or_verifier", ["native.operator.signature"], unsigned_decision),
        ("test_signed_operator_decision_binds_exact_transaction_and_survives_restart", ["native.operator.signature", "native.operator.final-gate"], signed_restart),
        ("test_signed_decision_cannot_be_replayed_for_another_approval", ["native.operator.signature"], replay_signature),
        ("test_final_claim_gate_reverifies_operator_signature_after_database_tamper", ["native.operator.final-gate"], cryptographic_tamper),
        ("test_signed_arguments_are_json_type_strict", ["native.operator.signature"], strict_arguments),
        ("test_final_claim_gate_never_accepts_a_signed_denial_after_database_tamper", ["native.operator.final-gate"], signed_denial),
        ("test_external_signer_signs_exact_server_bytes_without_json_reserialization", ["native.operator.wire", "native.operator.signature"], exact_wire),
        ("test_review_projection_cannot_diverge_from_the_bytes_to_be_signed", ["native.operator.wire"], lambda: invalid_wire("wire-review", "review")),
        ("test_reserialized_or_whitespace_changed_payload_is_not_an_acceptable_signing_wire", ["native.operator.wire"], lambda: invalid_wire("wire-bytes", "bytes")),
        ("test_signing_wire_rejects_non_interoperable_json_values", ["native.operator.wire"], interoperable),
        ("test_submission_rebinds_server_bytes_to_current_durable_approval", ["native.operator.wire", "native.operator.signature"], lambda: invalid_wire("wire-store", "store")),
        ("test_signing_request_is_single_approval_authority_not_a_reusable_bearer_grant", ["native.operator.wire"], lambda: invalid_wire("wire-bearer", "bearer")),
        ("test_lost_approval_ack_can_retry_same_signature_without_minting_new_authority", ["native.operator.retry"], lost_ack),
    ]
    for name, contract_ids, action in authority_cases:
        run(name, contract_ids, action)
    from .native_tools import NativeToolRegistry
    native = mcp._gateway().native
    native_root = native.root
    (native_root / "README.md").write_text("Neyvia native tool proof\n", encoding="utf-8")

    def catalog_and_reads():
        matches = native.search("take a screenshot")
        described = native.describe("preview.inspect")
        require(matches[0]["name"] == "preview.screenshot" and "inputSchema" not in matches[0]
                and described["inputSchema"]["required"] == ["url"] and described["schema_version"] == "1.1"
                and described["mutability_class"] == "read" and "page.inspect" in described["capabilities"],
                "native.tools.catalog", "progressive catalog did not retain screenshot/inspect discovery semantics")
        search = native.call("workspace.search", {"query": "Neyvia"})
        read = native.call("workspace.read", {"path": "README.md"})
        escaped = native.call("workspace.read", {"path": "../outside.txt"})
        require(search["ok"] and search["result"]["count"] == 1 and read["ok"] and read["result"]["path"] == "README.md"
                and read["result"]["content"].splitlines() == ["Neyvia native tool proof"] and not escaped["ok"]
                and "inside the workspace root" in escaped["error"], "native.tools.workspace", "real read/search or path escape policy failed")

    def protocol_types():
        wrong = native.call("workspace.search", {"query": "Neyvia", "maxResults": "many"})
        outside = native.call("workspace.search", {"query": "Neyvia", "maxResults": 500})
        observed = native.snapshot()
        require(not wrong["ok"] and "$.maxResults" in wrong["error"] and "type" in wrong["error"]
                and not outside["ok"] and "$.maxResults" in outside["error"] and "maximum" in outside["error"]
                and all(row.get("failure", {}).get("stage") == "validation"
                        and row["failure"].get("kind") == "invalid_arguments" for row in (wrong, outside))
                and observed["protocolVersion"] == "1.1" and "validate" in observed["discovery"]["flow"],
                "native.tools.arguments", "invalid type/range bypassed native protocol validation")

    def native_skill():
        import os, subprocess
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        base = scratch / "skill-isolated-child"
        base.mkdir()
        env = dict(os.environ)
        env["CODEX_HOME"] = str(base / "codex-home")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        completed = subprocess.run([sys.executable, "-c", "import json,sys; from grant_agent.proofs_d_native import live_skill_journey; print(json.dumps(live_skill_journey(sys.argv[1])))", str(base)],
            capture_output=True, text=True, encoding="utf-8", timeout=60, env=env, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "native.tools.skill-revision", "isolated scratch skill process failed: " + completed.stderr[-600:])
        require(json.loads(completed.stdout)["ok"], "native.tools.skill-revision", "isolated skill journey lacked success receipt")

    run("test_catalog_search_describe_and_workspace_call_are_receipted", ["native.tools.catalog", "native.tools.workspace", "native.tools.receipt"], catalog_and_reads)
    run("test_tool_protocol_rejects_wrong_types_and_out_of_range_values", ["native.tools.arguments"], protocol_types)
    run("test_live_skill_iteration_is_a_receipted_native_tool", ["native.tools.skill-revision", "native.tools.receipt"], native_skill)
    from .action_executor import HybridExecutionAdapter
    from .models import PlannedStep

    def routing(target):
        adapter = HybridExecutionAdapter()
        scope = adapter.prepare_scope(native_root, "native-routing-proof", requested_scope="direct")
        step = PlannedStep(step_id="local-route", title="Capture screenshot" if target == "preview.screenshot" else "Find UI inspiration",
            description=proof_text("Take visual proof from http://127.0.0.1:48497/preview") if target == "preview.screenshot" else "Find calm approval queue and live preview interface references.")
        proposal = adapter.build_action_proposal(step, "Capture the preview screenshot." if target == "preview.screenshot" else "Research UI inspiration before implementing the review tools.",
            native_root, [], "hermes", scope, adapter.build_policy("builder"))
        require(proposal.kind == "native_tool" and proposal.args["tool"] == target, "native.tools.routing", "harness selected wrong native route")
        if target == "preview.screenshot":
            require(proposal.args["arguments"]["url"] == proof_text("http://127.0.0.1:48497/preview") and not proposal.requires_approval,
                    "native.tools.routing", "screenshot target/policy changed")

    run("test_harness_selects_screenshot_as_a_native_tool_action", ["native.tools.routing"], lambda: routing("preview.screenshot"))
    run("test_harness_selects_ui_inspiration_as_native_tool_action", ["native.tools.routing"], lambda: routing("ui.inspiration.search"))
    import queue, threading, subprocess, os
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    browser_observations = {}

    class PreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<!doctype html><html><head><title>Neyvia Preview</title></head><body><main>Native preview proof</main></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *arguments):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48497)), PreviewHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = proof_text("http://127.0.0.1:48497/preview")
    try:
        def local_http():
            receipt = native.call("preview.inspect", {"url": url})
            require(receipt["ok"] and receipt["result"]["reachable"] and receipt["result"]["title"] == "Neyvia Preview"
                    and "Native preview proof" in receipt["result"]["text"], "native.tools.preview", "real local HTTP title/text observer failed")

        def real_worker():
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (
                str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH", ""))))
            worker_root = _fixture_root(scratch / "worker")
            child_entry = ("import sys; from grant_agent.proofs_d_native import _fixture_authority; "
                           "_fixture_authority(sys.argv[1]); from grant_agent.native_tool_worker import main; "
                           "raise SystemExit(main(['--root',sys.argv[1], '--browser-transport','obscura', '--browser-port',sys.argv[2]]))")
            worker_errors = (scratch / "worker-stderr.log").open("w", encoding="utf-8")
            process = subprocess.Popen([sys.executable, "-c", child_entry, str(worker_root), str(proof_port(48498))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=worker_errors, text=True, encoding="utf-8", env=env, **hidden_windows_subprocess_kwargs())
            outputs = queue.Queue()

            def read_worker():
                for line in process.stdout:
                    outputs.put(line)

            reader = threading.Thread(target=read_worker, daemon=True)
            reader.start()

            def request(payload):
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
                try:
                    return json.loads(outputs.get(timeout=60))
                except queue.Empty as error:
                    raise TimeoutError("Native worker returned no response within 60 seconds; exit="
                                       + str(process.poll()) + "; stderr="
                                       + str(scratch / "worker-stderr.log")) from error

            try:
                first = request({"id": "screenshot", "tool": "preview.screenshot", "arguments": {"url": url, "width": 800, "height": 600, "fullPage": False, "delayMs": 0}})
                second = request({"id": "annotation", "tool": "preview.annotate", "arguments": {"url": url, "rectangle": {"x": 10, "y": 12, "width": 30, "height": 24},
                    "comment": "Real local worker proof", "viewport": {"width": 800, "height": 600}, "delayMs": 0}})
                shutdown_started = time.monotonic()
                stopped = request({"id": "shutdown", "command": "shutdown"})
                process.wait(timeout=10)
                require(time.monotonic() - shutdown_started < 10,
                        "native.worker.reuse", "owned worker shutdown exceeded ten seconds")
                require(first["ok"] and second["ok"] and stopped["data"]["shutdown"] and first["protocol"] == "neyvia.native_tool_worker.v1",
                        "native.worker.reuse", "owned worker failed real capture/annotation/shutdown")
                one, two = first["data"], second["data"]
                require(one.get("ok") is True and two.get("ok") is True,
                        "native.worker.reuse", "real worker native receipts failed: "
                        + json.dumps({"screenshot": one.get("error"), "annotation": two.get("error")}))
                require(isinstance(one.get("result", {}).get("browserRuntime"), dict)
                        and isinstance(two.get("result", {}).get("browserRuntime"), dict),
                        "native.worker.reuse", "successful native capture lost real browser runtime metadata")
                require(one["worker"]["requestIndex"] == 1 and two["worker"]["requestIndex"] == 2
                        and one["worker"]["pid"] == two["worker"]["pid"] and not one["result"]["browserRuntime"]["browserReused"]
                        and two["result"]["browserRuntime"]["browserReused"] and two["worker"]["browserStarts"] == 1 and two["worker"]["contextsCreated"] == 2,
                        "native.worker.reuse", "worker did not retain one browser with fresh contexts")
                browser_observations.update(screenshot=one, annotation=two,
                                            shutdownSeconds=time.monotonic() - shutdown_started)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                process.stdin.close()
                process.stdout.close()
                worker_errors.close()
                reader.join(timeout=2)

        def annotation():
            require("annotation" in browser_observations, "native.tools.annotation",
                    "Real worker annotation prerequisite failed; no annotation observation exists")
            normalized = NativeToolRegistry._normalize_percentage_rectangle({"x": 95, "y": -5, "width": 20, "height": 0})
            result = browser_observations["annotation"]["result"]
            require(normalized == {"x": 95.0, "y": 0.0, "width": 5.0, "height": 0.5}
                    and result["annotation"]["@context"] == "http://www.w3.org/ns/anno.jsonld"
                    and result["annotation"]["geometry"]["type"] == "RECTANGLE"
                    and "xywh=percent:10.0,12.0,30.0,24.0" in result["annotation"]["target"]["selector"]["value"]
                    and len(result["artifacts"]) == 4 and all(Path(path).is_file() for path in result["artifacts"]),
                    "native.tools.annotation", "real screenshot annotation differs from clamped W3C geometry/artifact contract")

        def visual_catalog():
            matches = native.search("find UI inspiration")
            require(matches[0]["name"] == "ui.inspiration.search",
                    "native.tools.catalog", "visual search tool is missing from the progressive catalog")

        def inspiration():
            require("screenshot" in browser_observations, "native.tools.inspiration",
                    "Real worker screenshot prerequisite failed; no visual search observation exists")
            args = {"query": "approval queue", "surface": "agent command center", "platform": "desktop web app", "style": "calm dark", "limit": 8}
            query, facets, enriched, search_args = NativeToolRegistry._inspiration_request(args)
            observed = browser_observations["screenshot"]["result"]
            provider_data = {"provider": "observed-local-http", "results": [{"title": "Neyvia Preview", "image": observed["path"], "url": url,
                              "sourceDomain": "127.0.0.1", "width": 800, "height": 600}]}
            board = NativeToolRegistry._inspiration_board(query, facets, enriched, provider_data)
            require(board["boardType"] == "ui-inspiration"
                    and board["provider"] == "observed-local-http" and "approval queue agent command center desktop web app calm dark" in board["searchQuery"]
                    and board["results"][0]["sourceDomain"] == "127.0.0.1" and search_args["limit"] == 8,
                    "native.tools.inspiration", "real observed image board lost query/source assembly")

        run("test_preview_inspect_reads_a_real_local_http_surface", ["native.tools.preview", "native.tools.receipt"], local_http)
        # The visual cases share this real worker prerequisite, including
        # focused selections that request only annotation or inspiration.
        run("test_worker_reuses_chromium_with_fresh_contexts", ["native.worker.reuse"], real_worker,
            prerequisites=("native.tools.annotation", "native.tools.inspiration"))
        run("test_annotation_rectangle_is_clamped_and_w3c_capture_is_real", ["native.tools.annotation"], annotation)
        run("test_visual_search_tool_is_discoverable_without_screenshot", ["native.tools.catalog"], visual_catalog)
        run("test_ui_inspiration_requires_real_observed_screenshot", ["native.tools.inspiration"], inspiration)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
    def actual_write_failure():
        import ctypes
        from ctypes import wintypes
        require(os.name == "nt", "native.checkpoints.rollback", "Windows sharing semantics are required for this real failure journey")
        workspace = scratch / "checkpoint-locked-write"
        workspace.mkdir()
        first, second = workspace / "a.txt", workspace / "b.txt"
        first.write_text("checkpoint-a", encoding="utf-8")
        second.write_text("checkpoint-b", encoding="utf-8")
        store = NativeCheckpointStore(workspace)
        manifest = store.create(["a.txt", "b.txt"])
        first.write_text("current-a", encoding="utf-8")
        second.write_text("current-b", encoding="utf-8")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(second), 0x80000000, 1, None, 3, 0x80, None)
        require(handle != ctypes.c_void_p(-1).value, "native.checkpoints.rollback", "could not hold real scratch file sharing lock")
        try:
            result = store.restore(manifest["checkpointId"], approved=True)
        finally:
            kernel.CloseHandle(handle)
        require(result["status"] == "failed_rolled_back" and result["workspaceSafe"] and result["recovered"]
                and first.read_text(encoding="utf-8") == "current-a" and second.read_text(encoding="utf-8") == "current-b",
                "native.checkpoints.rollback", "real locked-file apply failure did not restore exact before-images")

    def discovered_python_proof():
        workspace = scratch / "discovered-python-proof"
        (workspace / "scripts").mkdir(parents=True)
        target = workspace / "value.txt"
        target.write_text("before", encoding="utf-8")
        checker = workspace / "scripts/verify_proofs.py"
        checker.write_text("import argparse,json,sys\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()\n"
                           "ok=(Path(a.root)/'value.txt').read_text(encoding='utf-8')=='after'\nprint(json.dumps({'ok':ok,'contract':'value.persisted'}))\nsys.exit(0 if ok else 1)\n", encoding="utf-8")
        owner = NativeProofAuditor(workspace)
        before = owner.snapshot()
        target.write_text("after", encoding="utf-8")
        behavior = {"capsule": {"mutationExpected": True, "proofGates": ["workspace_delta", "deterministic_check", "receipt_integrity"]}}
        passed = owner.audit(before=before, behavior_plan=behavior, allow_mutations=True)
        require(passed["status"] == "verified" and passed["runStatus"] == "completed" and passed["workspaceDelta"]["changed"]
                and passed["verification"]["passed"] and not passed["verification"]["shell"]
                and passed["selectedVerification"]["id"] == "python:manual-contracts",
                "native.audit.proof-discovery", "real discovered Python proof command failed to gate changed workspace")
        before = owner.snapshot()
        target.write_text("contract-violated", encoding="utf-8")
        failed = owner.audit(before=before, behavior_plan=behavior, allow_mutations=True)
        require(failed["status"] == "blocked" and not failed["verification"]["passed"],
                "native.audit.proof-discovery", "failed real Python proof command did not block completion")

    run("test_restore_failure_rolls_back_files_already_replaced", ["native.checkpoints.rollback", "native.checkpoints.restore"], actual_write_failure)
    run("test_changed_workspace_requires_and_passes_discovered_python_check", ["native.audit.proof-discovery", "native.audit.failure-gate"], discovered_python_proof)
    contracts = sorted({contract for row in cases for contract in row["contracts"]})
    result = {"ok": all(row["ok"] for row in cases), "contracts": contracts, "cases": cases,
            "failures": [row for row in cases if not row["ok"]], "scratchRoot": str(scratch),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "browserEvidence": {"shutdownSeconds": browser_observations.get("shutdownSeconds"),
                "browserStarts": browser_observations.get("annotation", {}).get("worker", {}).get("browserStarts"),
                "contextsCreated": browser_observations.get("annotation", {}).get("worker", {}).get("contextsCreated")},
            "truthBoundary": "Real local storage, HTTP, explicitly admitted headless Obscura capture/reuse, in-memory Ed25519 signing and isolated skill actions; staged recovery journals are explicit local fixtures. Remote delivery, external image-provider freshness and model inference are not claimed."}
    # Retain the actual returned campaign and its observed evidence so CL can
    # verify completion afresh without running another destructive campaign.
    from .durability import atomic_write_json
    result["fileHashes"] = {path.relative_to(scratch).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(scratch.rglob("*")) if path.is_file() and '.chrome' not in path.relative_to(scratch).parts}
    receipt = scratch / "self-check-receipt.json"
    atomic_write_json(receipt, result)
    return {**result, "receiptPath": str(receipt)}


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root


def _fixture_authority(root):
    """Install the existing guard for the actual containing proof workspace."""
    from .proof_credential_guard import install
    root = Path(root).resolve()
    workspace = next((parent.parent for parent in root.parents
                      if parent.name == ".agent_control" and root.is_relative_to(parent / "proofs")), None)
    if workspace is None:
        raise ValueError("Native proof child must belong to disposable .agent_control/proofs state")
    install(workspace)
    return workspace
