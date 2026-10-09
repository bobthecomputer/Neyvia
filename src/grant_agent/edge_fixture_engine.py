"""Generated local engine, journal and adapter fixtures; no enrolled credentials.

Model receipts establish actual helper behavior, not a rendered browser journey.
Each shared builder binds only inspected production claims and adverse boundaries.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

TEXT = {"empty", "huge", "unicode"}


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def text(category):
    return {"empty": "", "huge": "local observed content " * 14000,
            "unicode": "café 東京 🧭 e\u0301"}.get(category, "local observed content")


def rejected(action, errors=(ValueError, KeyError, RuntimeError, PermissionError)):
    try:
        action()
    except errors as error:
        return type(error).__name__
    raise AssertionError("Unsafe or empty operation was accepted")


def parallel(action, count=16):
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(action, range(count)))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def child(code, *arguments):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    result = subprocess.run([sys.executable, "-c", code, *map(str, arguments)],
                            capture_output=True, text=True, timeout=30,
                            **hidden_windows_subprocess_kwargs())
    require(result.returncode == 23, f"Owned interruption child did not return 23: {result.stderr}")
    return result.returncode


def _account(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    payload = {"route": "file-import", "state": "connected", "accountId": "owned",
               "label": text(category), "permissions": ["read", "send", "read"],
               "configuration": {"description": text(category)}}
    if category == "empty":
        rejected(lambda: owner.register_communication_account({}))
    if category == "permissions":
        rejected(lambda: owner.register_communication_account({**payload, "configuration": {"password": "synthetic-invalid-input"}}))
        rejected(lambda: owner.register_communication_account({**payload, "permissions": ["administrator"]}))
        require(owner.communication_snapshot()["accounts"] == [], "Rejected account mutated storage")
    if category == "concurrency":
        parallel(lambda i: owner.register_communication_account({**payload, "accountId": f"owned-{i}"}))
        rows = NeyviaEcosystemFabric(root).communication_snapshot()["accounts"]
        require(len(rows) == 16 and len({r["accountId"] for r in rows}) == 16, "Concurrent registrations lost account rows")
    else:
        first = owner.register_communication_account(payload)
        if category == "stale":
            owner.register_communication_account({**payload, "state": "not-configured", "permissions": ["read"]})
            rows = NeyviaEcosystemFabric(root).communication_snapshot()["accounts"]
            require(len(rows) == 1 and rows[0]["state"] == "not-configured" and rows[0]["perActionApprovals"] == [], "Old account permissions remained after replacement")
        else:
            rows = NeyviaEcosystemFabric(root).communication_snapshot()["accounts"]
            require(rows == [first], "Account receipt differs after SQLite reopen")
    require(all(not set(row["configuration"]) & {"password", "token", "apiKey"} for row in rows), "Account configuration leaked synthetic forbidden keys")
    return {"accounts": len(rows), "inputCharacters": len(text(category)), "sqliteSha256": digest(owner.database_path)}


def _presentation(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    prompt = text(category)
    if not prompt:
        rejected(lambda: owner.compile_presentation_prompt({"prompt": prompt}))
        return {"emptyRejected": True}
    plan = owner.compile_presentation_prompt({"prompt": prompt, "context": {"selected": prompt}})
    require(plan["original"] == prompt.strip() and plan["compiled"].startswith(prompt.strip() + "\n\n"), "Prompt original lost exact characters")
    require(plan["requiresExplicitInsert"] and not plan["automatedLogin"] and not plan["transcriptHarvesting"], "Compilation widened authority")
    if category == "stale":
        later = owner.compile_presentation_prompt({"prompt": "changed selected context"})
        require(later["compiled"] != plan["compiled"] and plan["original"] == prompt, "Prompt mutation reused previous result")
    return {"inputCharacters": len(prompt), "compiledSha256": hashlib.sha256(plan["compiled"].encode()).hexdigest()}


def _capture(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    content = text(category)
    payload = {"source": "file:///explicit-owned-export", "userInitiated": True, "content": content}
    if category == "empty":
        rejected(lambda: owner.capture_presentation_content(payload))
    elif category == "permissions":
        rejected(lambda: owner.capture_presentation_content({**payload, "userInitiated": False}))
    else:
        if category == "concurrency":
            records = parallel(lambda i: owner.capture_presentation_content({**payload, "content": {"index": i, "text": content}}))
        else:
            records = [owner.capture_presentation_content(payload)]
        import sqlite3
        with sqlite3.connect(owner.database_path) as db:
            rows = db.execute("SELECT capture_id, content_json, content_sha256, lineage_json FROM presentation_captures").fetchall()
        require(len(rows) == len(records), "Concurrent capture lost durable records")
        for identity, encoded, recorded, lineage in rows:
            require(hashlib.sha256(encoded.encode()).hexdigest() == recorded and json.loads(lineage)["userInitiated"], "Capture disk digest or authority differs")
        return {"captures": len(rows), "inputCharacters": len(content), "sqliteSha256": digest(owner.database_path)}
    import sqlite3
    with sqlite3.connect(owner.database_path) as db:
        require(db.execute("SELECT COUNT(*) FROM presentation_captures").fetchone()[0] == 0, "Rejected capture mutated SQLite")
    return {"rejectedWithoutMutation": True}


def _capsule(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    if category == "permissions":
        rejected(lambda: owner.build_share_capsule({"content": {"text": "sk-syntheticProofInput0123456789"}}))
        require(not list((root / ".agent_control" / "share_capsules").glob("*.json")), "Blocked share wrote a capsule")
    records = parallel(lambda i: owner.build_share_capsule({"content": {"index": i, "text": text(category)}})) if category == "concurrency" else [owner.build_share_capsule({"content": {"text": text(category)}})]
    for record in records:
        path = Path(record["recordPath"])
        require(json.loads(path.read_bytes()) == {k: v for k, v in record.items() if k != "recordPath"}, "Capsule differs from actual disk bytes")
        require(record["transportState"] == "prepared-not-sent" and record["requiresExplicitShare"], "Preparation claimed sending")
    require(len({r["capsuleId"] for r in records}) == len(records), "Concurrent capsule overwrote a distinct export")
    return {"capsules": len(records), "durableBytes": sum(Path(r["recordPath"]).stat().st_size for r in records)}


def _experiment(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    if category == "empty":
        rejected(lambda: owner.create_experiment({"title": "", "hypothesis": ""}))
    value = text(category).strip() or "owned observation"
    created = owner.create_experiment({"title": "Owned experiment", "hypothesis": value, "lifetime": {"kind": "session"}})
    eid = created["experimentId"]
    if category == "concurrency":
        parallel(lambda i: owner.record_experiment_observation({"experimentId": eid, "observation": f"independent-observation-{i}", "evidence": {"index": i}}), 32)
        observed = NeyviaEcosystemFabric(root).experiment_snapshot()["experiments"][0]
        require(len(observed["journal"]) == 32 and {row["evidence"]["index"] for row in observed["journal"]} == set(range(32)), f"Concurrent observation loss: expected32 actual{len(observed['journal'])}")
    else:
        owner.record_experiment_observation({"experimentId": eid, "observation": value, "evidence": {"sha256": hashlib.sha256(value.encode()).hexdigest()}})
        if category == "stale":
            owner.conclude_experiment({"experimentId": eid, "verdict": "failed: observed negative result"})
        observed = NeyviaEcosystemFabric(root).experiment_snapshot()["experiments"][0]
        require(observed["journal"][0]["observation"] == value and observed["lifetime"] == {"kind": "session"}, "Experiment lost observation or lifetime after reopen")
        if category == "stale":
            require(observed["state"] == "concluded" and observed["verdict"].startswith("failed:"), "Negative verdict disappeared on reobserve")
    return {"journalEntries": len(observed["journal"]), "sqliteSha256": digest(owner.database_path)}


def _authorization(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    target = text(category).strip()
    missing = owner.create_experiment({"title": "No grant", "hypothesis": "reject act without recorded authorization"})
    rejected(lambda: owner.plan_experiment_action({"experimentId": missing["experimentId"], "tier": "act", "target": target}))
    granted = owner.create_experiment({"title": "Local grant", "hypothesis": "only plan", "authorizationContext": "owned local fixture"})
    if not target:
        rejected(lambda: owner.plan_experiment_action({"experimentId": granted["experimentId"], "tier": "act", "target": ""}))
        return {"emptyTargetRejected": True}
    result = owner.plan_experiment_action({"experimentId": granted["experimentId"], "tier": "act", "target": target})
    require(result["target"] == target and result["executable"] is False and result["approval"] == "per-action" and result["state"] == "approval-required", "Plan performed or silently authorized operation")
    return {"targetCharacters": len(target), "actExecuted": False, "missingGrantRejected": True}


def _benchmark(root, category):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    owner = NeyviaEcosystemFabric(root)
    count = 32 if category in {"huge", "concurrency"} else 2
    subjects = [{"subjectId": f"subject-{i}-{text(category) if category == 'unicode' else ''}"} for i in range(count)]
    if category == "empty":
        rejected(lambda: owner.create_benchmark_run({"subjects": [], "budget": {}, "taskContract": {}}))
    run = owner.create_benchmark_run({"subjects": subjects, "budget": {"maxTurns": 2}, "taskContract": {"objective": "same local measured task"}})
    rid = run["runId"]
    require(run["claim"].get("eligible") is not True, "Missing subjects admitted comparative claim")
    def record(i):
        return owner.record_benchmark_result(rid, {"subjectId": subjects[i]["subjectId"], "comparableContext": True, "budgetExceeded": False, "observed": i})
    if category == "concurrency":
        parallel(record, count)
    else:
        for i in range(count):
            record(i)
    observed = NeyviaEcosystemFabric(root).get_benchmark_run(rid)
    require(len(observed["results"]) == count and observed["claim"]["eligible"], f"Concurrent benchmark loss: expected{count} actual{len(observed['results'])}")
    if category == "stale":
        owner.record_benchmark_result(rid, {"subjectId": subjects[0]["subjectId"], "budgetExceeded": True})
        observed = NeyviaEcosystemFabric(root).get_benchmark_run(rid)
        require(not observed["claim"]["eligible"] and any(x["reason"] == "budget-exceeded" for x in observed["claim"]["exclusions"]), "Stale valid result concealed newer budget violation")
    require(observed["claim"]["interpretation"] == "not-reported", "Recorded measurements implied superiority")
    return {"subjectCount": count, "resultCount": len(observed["results"]), "eligible": observed["claim"]["eligible"]}


def _recorder(root, category):
    from .flight_recorder import MissionFlightRecorder, read_flight_recorder_events
    owner = MissionFlightRecorder(root, "owned-recording")
    count = 240 if category == "huge" else 32 if category == "concurrency" else 1
    def append(i):
        return owner.append_event(kind=f"step-{i}", message=text(category), payload={str(k): text(category) for k in range(30 if category == "huge" else 1)})
    if category == "concurrency":
        events = parallel(append, count)
    elif category == "huge":
        seed = append(0)
        owner.events_path.write_text("\n".join(json.dumps({**seed, "eventId": f"seed-event-{i}", "kind": f"step-{i}"}) for i in range(200)) + "\n", encoding="utf-8")
        events = [append(i) for i in range(200, count)]
    else:
        events = [append(i) for i in range(count)]
    if category == "interrupted":
        child("import sys,os;from pathlib import Path;from grant_agent.flight_recorder import MissionFlightRecorder;r=MissionFlightRecorder(Path(sys.argv[1]),'owned-recording');r.append_event(kind='child-complete',message='before crash');f=r.events_path.open('ab');f.write(b'{partial-crash');f.flush();os.fsync(f.fileno());os._exit(23)", root)
        # A truncated final record is skipped when read; all completed writes survive.
        restored = read_flight_recorder_events(owner.events_path)
        require(len(restored) == 2 and restored[-1]["kind"] == "child-complete", "Journal crash lost completed child event")
    elif category == "stale":
        old = owner.snapshot(current_phase="first")
        owner.append_event(kind="new-revision", message="later event")
        require(owner.snapshot(current_phase="later")["eventCount"] == old["eventCount"] + 1, "Recorder reused old snapshot")
    rows = read_flight_recorder_events(owner.events_path)
    require(len(rows) == min(200, count + (1 if category in {"interrupted", "stale"} else 0)), "Recorder missing durable events")
    if category == "concurrency":
        require({row["eventId"] for row in rows} == {event["eventId"] for event in events}, "Concurrent recorder lost unique IDs")
    snapshot = owner.snapshot(current_phase="verify", process_ids=list(range(30)))
    require(json.loads(owner.snapshot_path.read_bytes()) == snapshot and len(snapshot["processIds"]) == 20, "Recorder snapshot differs after disk reread")
    return {"generated": count, "retained": len(rows), "snapshotSha256": digest(owner.snapshot_path)}


def _handoff(root, category):
    from .efficient_workflow import compact_dependency_context
    value = text(category)
    completed = {} if category == "empty" else {"selected-reader": {"routeSelection": {"role": "reader"}, "result": {"reply": value, "raw": {"privateDump": value}}}}
    result = compact_dependency_context(completed)
    require(len(result) == len(completed), "Handoff omitted dependency")
    if result:
        observed = json.loads(result[0]["content"])
        require(observed["summary"] == value[:4000] and observed["sha256"] == hashlib.sha256(value.encode()).hexdigest() and observed["truncated"] == (len(value) > 4000) and "raw" not in observed, "Handoff lost exact byte lineage or bound")
    return {"inputCharacters": len(value), "dependencies": len(result)}


def _routing(root, category):
    from types import SimpleNamespace
    from .models import ModelRouteConfig
    from .fluxio_harness import recommended_model_routes, FluxioHarness
    model = text(category).strip() or "selected-model"
    override = {"role": "executor", "provider": "local-fixture", "model": model, "effort": "medium"}
    overrides = [] if category == "empty" else [override] * (10000 if category == "huge" else 1)
    routes = recommended_model_routes("builder", route_overrides=overrides)
    require(len({r.role for r in routes}) == len(routes) and {"planner", "executor", "verifier"} <= {r.role for r in routes}, "Routing lost independent core roles")
    if overrides:
        selected = next(r for r in routes if r.role == "executor")
        require(selected.provider == override["provider"] and selected.model == model, "Explicit route was silently substituted")
    phase = text(category)
    session = SimpleNamespace(target_phase=phase, target_provider="openai-codex", target_model=model, target_effort="medium")
    require(FluxioHarness._delegated_route_mismatch(session, desired_phase=phase, desired_route=ModelRouteConfig(role="executor", provider="openai", model=model, effort="medium")) is False, "Equivalent selected OpenAI route caused repeated handoff")
    return {"overrideRows": len(overrides), "modelCharacters": len(model), "routeRoles": [r.role for r in routes], "providerInvoked": False}


def _autotune(root, category):
    from .fluxio_harness import resolve_efficiency_autotune_policy
    snapshot = {} if category == "empty" else {"efficiency": {"totalRuns": 10**9 if category == "huge" else 3, "completionRate": 100}, "sessionHealth": {"staleHeartbeatCount": 4 if category == "stale" else 0}}
    strategy = text(category) if category == "unicode" else "budget_first"
    enabled = category != "permissions"
    result = resolve_efficiency_autotune_policy(harness_lab_snapshot=snapshot, auto_optimize_routing=enabled, requested_strategy=strategy)
    require(result["eligible"] == (category != "empty") and result["enabled"] == enabled, "Autotune ignored evidence threshold or disabled permission")
    if category in {"empty", "permissions"}:
        require(result["appliedPolicy"] == {}, "Routing changed without enough evidence or permission")
    if category == "stale":
        require(result["routingStrategy"] == "uniform_quality" and result["forcePauseOnFailure"], "Stale heartbeat bypassed safety route")
    if category == "unicode":
        require(result["requestedStrategy"] == strategy.strip().lower(), "Unicode selected strategy lost characters")
    return {"eligible": result["eligible"], "enabled": enabled, "selectedStrategy": result["routingStrategy"], "providerInvoked": False}


def _suggestions(root, category):
    from .feature_suggester import suggest_features_from_text, FEATURE_LIBRARY
    value = text(category)
    result = suggest_features_from_text(value, top_k=100000 if category == "huge" else 6)
    ids = {row["id"] for row in FEATURE_LIBRARY}
    require(len({row["id"] for row in result}) == len(result) and all(row["id"] in ids for row in result), "Suggestion invented or duplicated feature")
    require([row["score"] for row in result] == sorted((row["score"] for row in result), reverse=True) and len(result) <= len(ids), "Huge suggestion request bypassed finite catalog or ranking")
    return {"inputCharacters": len(value), "suggestions": len(result), "catalogSize": len(ids)}


def _verdict(root, category):
    from .efficient_workflow import verification_result
    path = root / "selected.txt"
    path.write_text(text(category), encoding="utf-8")
    expected = digest(path)
    evidence = [{"path": path.name, "sha256": expected}]
    reply = json.dumps({"verdict": "pass", "evidence": evidence})
    if category == "empty":
        require(verification_result('{"verdict":"pass","evidence":[]}', root=root)["status"] == "unverified", "Evidence-free pass accepted")
    if category == "stale":
        path.write_text("changed bytes after reported hash", encoding="utf-8")
    if category == "permissions":
        outside = root.parent / "outside-claim.txt"
        outside.write_text("unowned claim", encoding="utf-8")
        denied = verification_result(json.dumps({"verdict": "pass", "evidence": [{"path": "../outside-claim.txt", "sha256": digest(outside)}]}), root=root)
        require(denied["status"] == "unverified", "Verifier inspected out-of-workspace authority as pass")
    actual = verification_result(reply, root=root)
    require(actual["status"] == ("unverified" if category == "stale" else "completed"), "Verifier accepted stale hash or rejected matching actual bytes")
    require(verification_result('{"verdict":"fail","evidence":["observed failure"]}', root=root)["status"] == "failed", "Failure verdict changed status")
    return {"artifactBytes": path.stat().st_size, "expectedSha256": expected, "actualSha256": digest(path), "status": actual["status"]}


def _delivery(root, category):
    from .delivery_receipt import _append_receipt, _update_last_receipt, _update_receipt, load_receipts, acknowledge_delivery_receipt, delivery_receipts_path, record_browser_delivery_receipt, send_approval_escalation_receipt
    from .models import DeliveryReceipt, MissionEvent
    def receipt(i):
        return DeliveryReceipt(receipt_id=f"owned-{i}", mission_id="chosen" if isinstance(i, int) and i % 2 == 0 else "other", channel="local", destination="control-room", event_kind="progress", event_message=text(category)[:4096], sent_at="2026-10-04T00:00:00Z", status="delivered")
    count = 520 if category == "huge" else 32 if category == "concurrency" else 6
    if category == "concurrency":
        parallel(lambda i: _append_receipt(root, receipt(i)), count)
    elif category == "huge":
        delivery_receipts_path(root).write_text("\n".join(json.dumps(asdict(receipt(i))) for i in range(500)) + "\n", encoding="utf-8")
        for i in range(500, count):
            _append_receipt(root, receipt(i))
    else:
        for i in range(count):
            _append_receipt(root, receipt(i))
    path = delivery_receipts_path(root)
    rows = load_receipts(root, limit=0)
    require(len(rows) == min(count, 500), "Journal retention or concurrent appends lost rows")
    if category == "concurrency":
        require({r.receipt_id for r in rows} == {f"owned-{i}" for i in range(count)}, "Concurrent append receipt identity loss")
        parallel(lambda i: _update_last_receipt(root, DeliveryReceipt(**{**asdict(receipt(i)), "event_message": f"updated-{i}"})), count)
        require(all(r.event_message == f"updated-{r.receipt_id.split('-')[-1]}" for r in load_receipts(root, limit=0)), "Concurrent identity update lost other receipts")
        parallel(lambda i: acknowledge_delivery_receipt(root, f"owned-{i}"), count)
        require(all(r.status == "acknowledged" for r in load_receipts(root, limit=0)), "Concurrent acknowledgement lost status")
    else:
        selected = rows[0]
        prior = path.read_text(encoding="utf-8").splitlines()
        selected.event_message = "new exact receipt revision"
        _update_last_receipt(root, selected)
        require(load_receipts(root, limit=0)[0].event_message == selected.event_message, "Receipt ID update changed wrong row")
        _update_receipt(root, receipt("legacy-tail"))
        require(load_receipts(root, limit=0)[-1].receipt_id == "owned-legacy-tail", "Legacy tail update did not replace tail")
        require(acknowledge_delivery_receipt(root, selected.receipt_id), "Eligible receipt acknowledgement refused")
        require(load_receipts(root, limit=0)[0].status == "acknowledged", "Acknowledgement not persisted")
    if category == "interrupted":
        child("import sys,os;from pathlib import Path;from grant_agent.delivery_receipt import record_browser_delivery_receipt,delivery_receipts_path;from grant_agent.models import MissionEvent;r=Path(sys.argv[1]);record_browser_delivery_receipt(MissionEvent(mission_id='child',kind='child-progress',message='before crash'),root=r);f=delivery_receipts_path(r).open('ab');f.write(b'{partial-crash');f.flush();os.fsync(f.fileno());os._exit(23)", root)
        require(any(r.mission_id == "child" for r in load_receipts(root, limit=0)), "Crash lost completed delivery")
        before = path.read_text(encoding="utf-8").splitlines()
        _update_last_receipt(root, receipt("missing-delayed"))
        require(path.read_text(encoding="utf-8").splitlines()[-2] == before[-1], "Delayed ID update discarded crash row")
    filtered = load_receipts(root, mission_id="chosen", limit=2)
    all_chosen = [r for r in load_receipts(root, limit=0) if r.mission_id == "chosen"]
    require([r.receipt_id for r in filtered] == [r.receipt_id for r in all_chosen[-2:]], "Mission filtering occurs after limit")
    before = path.read_bytes()
    require(not acknowledge_delivery_receipt(root, "unknown") and path.read_bytes() == before, "Unknown acknowledgement mutated journal")
    browser = record_browser_delivery_receipt(MissionEvent(mission_id="browser", kind="browser-progress", message=text(category)), root=root)
    require(browser.status == "delivered" and browser.destination == "control-room" and browser.event_message == text(category), "Browser progress changed caller event")
    skipped = send_approval_escalation_receipt(mission_id="local-skip", prompt=text(category), risk_level="low", escalation_policy={"enabled": False}, root=root)
    require(skipped.status == "skipped" and skipped.error_message == "escalation_disabled", "Disabled escalation tried provider delivery")
    return {"journalLines": len(path.read_text(encoding="utf-8").splitlines()), "validRows": len(load_receipts(root, limit=0)), "bytes": path.stat().st_size, "sha256": digest(path)}


def _message(root, category):
    from html import escape
    from .delivery_receipt import _format_telegram_message
    from .models import MissionEvent
    value = text(category) + "<script>& caller markup"
    result = _format_telegram_message(MissionEvent(mission_id=value, kind="approval", message=value, metadata={"note": value}))
    require(result == "\n".join(["<b>Neyvia approval</b>", f"Mission: <code>{escape(value)}</code>", escape(value), f"Note: {escape(value)}"]), "Message did not independently escape each caller field")
    return {"inputCharacters": len(value), "outputCharacters": len(result)}


def _ocr(root, category):
    from .capability_adapters import CapabilityAdapterRegistry as Owner
    value = text(category)
    methods = [Owner._repair_glm_renderer_duplicate, Owner._repair_glm_table_boundary, Owner._repair_glm_formula_boundary]
    for method in methods:
        actual, evidence = method(value)
        require(actual == value and evidence is None, "Nonmatching OCR text changed")
    if category != "empty":
        renderer = value + " enough repeated observed content to cross threshold"
        table = f"<table><tr><td>{value}</td></tr></table>"
        formula = "$$" + value + "x=observed$$"
        for method, source, expected in [(methods[0], renderer + "\n```markdown\n" + renderer, renderer), (methods[1], table + " unrelated", table), (methods[2], formula + formula, formula)]:
            actual, evidence = method(source)
            require(actual == expected and evidence["removedCharacters"] == len(source) - len(expected), "Evidenced OCR boundary differs from independently constructed prefix")
        for method, incomplete in [(methods[0], renderer + "\n```markdown\nnot repeated"), (methods[1], "<table><tr><td>unfinished"), (methods[2], "$$unfinished")]:
            require(method(incomplete) == (incomplete, None), "Unfinished OCR specimen repaired without evidence")
    return {"inputCharacters": len(value), "repairOwners": len(methods)}


def _release(root, category):
    from .github_release_source import select_release, select_platform_asset, find_checksum_for, parse_github_ref, normalize_version
    require(parse_github_ref("https://example.invalid/owner/repo") is None, "Non-GitHub reference accepted")
    require(parse_github_ref("owner/repo").slug == "owner/repo", "Recognized GitHub ref rejected")
    require(normalize_version("v1.2.3") == "1.2.3", "Numeric version prefix retained")
    count = 3000 if category == "huge" else 1
    releases = [{"tag_name": f"v{i + 1}.2.3", "draft": True, "assets": []} for i in range(count)]
    stable = {"tag_name": "v1.2.3", "assets": [{"name": "local-windows-x64.zip", "size": 12}, {"name": "checksums.txt"}], "prerelease": False}
    beta = {"tag_name": "v2.0.0", "prerelease": True, "assets": []}
    releases += [beta, stable]
    if category == "empty":
        require(select_release([]) is None, "Empty releases invented update")
    require(select_release(releases) == stable and select_release(releases, channel="beta") == beta, "Draft or beta release offered as stable")
    require(select_release(releases, version="v1.2.3") == stable, "Version filter lost prefix normalization")
    asset = select_platform_asset(stable, platform_tag="windows-x64")
    require(asset == stable["assets"][0] and find_checksum_for(stable, asset) == stable["assets"][1], "Platform or checksum metadata mismatched")
    if category == "unicode":
        require(select_platform_asset({"assets": [{"name": "café-東京.zip"}]}, platform_tag="東京")["name"] == "café-東京.zip", "Unicode asset identity lost")
    if category == "stale":
        stable["draft"] = True
        require(select_release(releases) is None, "New draft state reused old selected release")
    return {"metadataRows": len(releases), "packageBytesDownloaded": 0}


def _html(root, category):
    from .html_site_benchmark import grade_html, combine_score
    path = root / "index.html"
    path.write_text(text(category), encoding="utf-8")
    observed = grade_html(path)
    require(observed["score"] == sum(r["points"] for r in observed["checks"]) and observed["bytes"] == len(text(category).encode()), "HTML ledger differs from actual input bytes or earned points")
    require(not combine_score({"score": 80}, {"score": 0})["passed"], "Static score fabricated browser acceptance")
    if category == "stale":
        path.write_text("<h1>one</h1><h1>two</h1>", encoding="utf-8")
        changed = grade_html(path)
        require(not next(c for c in changed["checks"] if c["id"] == "heading")["passed"], "Regrade did not observe changed actual file")
    return {"fileBytes": path.stat().st_size, "staticScore": observed["score"], "renderedBehavior": "not observed; this claim is static scoring only"}


def _staging(root, category):
    from .proof_ports import c7_port_block
    port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[-2]
    from .github_release_source import download_asset
    payload = text(category).encode()
    source = root / "publisher-café-東京.zip"
    source.write_bytes(payload)
    target = root / "selected-stage.zip"
    expected = digest(source)
    asset = {"name": source.name, "size": len(payload), "browser_download_url": source.as_uri()}
    target.write_bytes(b"previous valid target")
    prior = target.read_bytes()
    rejected(lambda: download_asset(asset, target, expected_sha256="0" * 64))
    require(target.read_bytes() == prior, "Checksum refusal replaced prior valid bytes")
    if category == "offline":
        from http.server import HTTPServer, BaseHTTPRequestHandler
        endpoint = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
        endpoint.server_close()
        rejected(lambda: download_asset({**asset, "browser_download_url": f"http://127.0.0.1:{port}/owned-closed-package"}, target, expected_sha256=expected, timeout=2))
        require(target.read_bytes() == prior, "Real closed loopback transport replaced valid target")
    if category == "interrupted":
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading
        class TruncatedTransfer(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload) * 2))
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
                self.close_connection = True
            def log_message(self, *_arguments):
                pass
        endpoint = HTTPServer(("127.0.0.1", port), TruncatedTransfer)
        endpoint.timeout = 5
        worker = threading.Thread(target=endpoint.handle_request)
        worker.start()
        try:
            rejected(lambda: download_asset({**asset, "browser_download_url": f"http://127.0.0.1:{port}/owned-truncated-package"}, target, timeout=3))
            require(target.read_bytes() == prior, "Real interrupted HTTP framing replaced valid staged bytes")
        finally:
            worker.join(timeout=6)
            endpoint.server_close()
        require(not worker.is_alive(), "Owned interrupted transfer service did not stop")
    records = parallel(lambda i: download_asset(asset, target, expected_sha256=expected), 16) if category == "concurrency" else [download_asset(asset, target, expected_sha256=expected)]
    require(target.read_bytes() == payload and all(r["bytes"] == len(payload) and r["sha256"] == expected and r["verified"] for r in records), "Staging bytes or checksum authority differs")
    if category == "stale":
        source.write_bytes(b"changed publisher bytes")
        rejected(lambda: download_asset(asset, target, expected_sha256=expected))
        require(target.read_bytes() == payload, "Stale publisher checksum replaced selected artifact")
    require(not list(root.glob("*.partial")), "Completed/refused transfer leaked partial bytes")
    return {"inputBytes": len(payload), "stagingWrites": len(records), "sha256": digest(target),
            "offlineLoopbackPort": port if category == "offline" else None,
            "interruptedHTTPDeclaredBytes": len(payload) * 2 if category == "interrupted" else None,
            "interruptedHTTPReceivedBytes": len(payload) if category == "interrupted" else None,
            "priorTargetPreservedOnRefusal": True,
            "transport": "actual selected local file URL and, for outage/framing categories, real owned loopback HTTP; no GitHub connection"}


def _update(root, category):
    from .proof_ports import c7_port_block
    port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[-1]
    from .github_release_source import check_for_update, GitHubSource
    listing = root / "selected-release-metadata.json"
    rows = [] if category == "empty" else [{"tag_name": "v2.0.0", "prerelease": False, "assets": [{"name": "café-windows-x64.zip", "size": 8}]}]
    if category == "huge":
        rows = [{"tag_name": f"v{i}.0.0", "draft": True} for i in range(5000)] + rows
    listing.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    def selected_file(_url, **_arguments):
        return listing.read_bytes()
    result = check_for_update("1.0.0", GitHubSource("owned", "metadata"), platform_tag="windows-x64", fetch=selected_file)
    require(result["state"] == ("unknown" if category == "empty" else "update_available"), "Local update metadata observation lost certainty distinction")
    require(result.get("downloadedBytes", 0) == 0, "Metadata check downloaded package bytes")
    if category == "offline":
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.request import urlopen
        endpoint = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
        endpoint.server_close()
        def unavailable_metadata(_url, **_arguments):
            with urlopen(f"http://127.0.0.1:{port}/owned-closed-metadata", timeout=2) as response:
                return response.read()
        result = check_for_update("1.0.0", GitHubSource("owned", "metadata"), fetch=unavailable_metadata)
        require(result["state"] == "unknown", "Real refused loopback metadata transport claimed current")
    if category == "stale":
        listing.write_text('[{"tag_name":"v0.1.0","assets":[]}]', encoding="utf-8")
        result = check_for_update("1.0.0", GitHubSource("owned", "metadata"), fetch=selected_file)
        require(result["state"] == "current", "Changed old publisher metadata caused downgrade")
    return {"metadataBytes": listing.stat().st_size, "state": result["state"], "packageBytesDownloaded": 0,
            "offlineLoopbackPort": port if category == "offline" else None,
            "transport": "actual caller-selected file metadata and real owned loopback refusal for offline; GitHub connectivity unobserved"}


def _publication(root, category):
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "scripts/check_workflow_publication_integrity.py"
    spec = importlib.util.spec_from_file_location("c7b_publication_owner", path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True)
    if category == "empty":
        require(owner.audit_workflows(root) == [], "Empty workflow directory fabricated finding")
        return {"workflowCount": 0}
    specimen = folder / "café-東京.yml"
    filler = "# selected local workflow text\n" * (14000 if category == "huge" else 1)
    specimen.write_text("permissions: read-all\n" + filler + "run: git status\n", encoding="utf-8")
    require(owner.audit_workflows(root) == [], "Read-only workflow refused")
    dangerous = [("run: git \\\n push\n", "git-push"), ("run: gh pr merge 7\n", "pull-request-mutation"), ("run: gh api repos/owned/repo -X POST\n", "write-api-call"), ("permissions: write-all\n", "write-all-permissions")]
    for body, rule in dangerous:
        specimen.write_text(filler + body, encoding="utf-8")
        findings = owner.audit_workflows(root)
        require(any(r["rule"] == rule and r["path"] == ".github/workflows/café-東京.yml" for r in findings), "Actual unsafe workflow mutation escaped audit: " + rule)
    if category == "stale":
        specimen.write_text("permissions: read-all\nrun: git status\n", encoding="utf-8")
        require(owner.audit_workflows(root) == [], "Auditor reused stale unsafe finding after disk edit")
    return {"mutatingWorkflowVariantsRejected": len(dangerous), "selectedWorkflowBytes": specimen.stat().st_size, "sourceSha256": digest(specimen)}


def _git(root, category):
    import shutil
    from .git_reference_adapter import GitReferenceAdapter, GitReferenceError
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    executable = shutil.which("git")
    require(bool(executable), "Installed local Git required; no download performed")
    repository = root / "owned-repository"
    repository.mkdir()
    def command(*args):
        completed = subprocess.run([executable, "-c", "core.hooksPath=" + os.devnull, "-C", str(repository), *args],
                                   env=GitReferenceAdapter._env(), capture_output=True, text=True,
                                   timeout=20, **hidden_windows_subprocess_kwargs())
        require(completed.returncode == 0, "Owned Git preparation failed: " + completed.stderr)
        return completed.stdout.strip()
    command("init")
    command("config", "user.name", "C7b local fixture")
    command("config", "user.email", "fixture@example.invalid")
    source = repository / "café-東京.txt"
    source.write_text(text(category) + "\n", encoding="utf-8")
    command("add", source.name)
    command("commit", "-m", "owned local object")
    head = command("rev-parse", "HEAD")
    owner = GitReferenceAdapter(root, executable=executable)
    if category == "empty":
        rejected(lambda: owner.execute({"repository": "", "operation": "repository.inspect"}), (GitReferenceError, ValueError, PermissionError))
    if category == "permissions":
        command("config", "filter.owned.clean", "should-never-execute")
        rejected(lambda: owner.execute({"repository": repository.name, "operation": "repository.inspect"}), (GitReferenceError, PermissionError))
        require(not list((root / ".agent_control").rglob("*receipt*.json")), "Denied helper/filter config issued success receipt")
        command("config", "--unset", "filter.owned.clean")
    payload = {"repository": repository.name, "operation": "repository.inspect"}
    records = parallel(lambda i: owner.execute(payload), 12) if category == "concurrency" else [owner.execute(payload)]
    for result in records:
        receipt = result["receipt"]
        file = root / receipt["path"]
        persisted = json.loads(file.read_bytes())
        require(result["head"] == head and digest(file) == receipt["sha256"] and persisted["lineage"]["sources"][0]["head"] == head, "Git receipt differs from independently inspected HEAD or bytes")
        require(not result["networkAccessed"] and result["policy"]["network"] == "denied" and result["consistency"]["before"] == result["consistency"]["after"], "Object adapter escaped network or accepted inconsistent snapshot")
    shown = owner.execute({**payload, "operation": "repository.show", "ref": "HEAD", "paths": [source.name]})
    require((text(category)[:128] in shown["content"]) if text(category) else ("+" in shown["content"].splitlines()), "Git object did not retain selected Unicode/path bytes")
    if category == "stale":
        source.write_text("changed later object\n", encoding="utf-8")
        command("commit", "-am", "new owned object")
        newer = command("rev-parse", "HEAD")
        observed = owner.execute(payload)
        require(newer != head and observed["head"] == newer and all(r["head"] == head for r in records), "Git reused stale HEAD or mutated earlier receipt")
    return {"initialHead": head, "objectBytes": source.stat().st_size, "receiptCount": len(records), "networkAccessed": False}


NODE_CODE = r'''
import assert from 'node:assert/strict';
import * as A from './web/src/neyvia/next/nxAccountsModel.js';
import * as F from './web/src/neyvia/neyviaEcosystemFabricModel.js';
const c=process.argv[1], t=c==='empty'?'':c==='huge'?'Abcd123!'.repeat(18000):'café 東京 🧭';
const out=[]; function observe(id, action){try{out.push({contract:id,status:'passed',detail:action()});}catch(e){out.push({contract:id,status:'failed',detail:e.message});}}
observe('accounts.initials',()=>{ const x=A.initials(t); assert.equal(x,c==='empty'?'?':c==='huge'?'A':'C🧭'); return {characters:t.length,result:x}; });
observe('accounts.avatar',()=>{const first=A.avatarHue(t), second=A.avatarHue(t.toUpperCase());assert.equal(first,second); assert.ok(first>=4&&first<=169&&!(first>=54&&first<90));return {characters:t.length,hue:first};});
observe('accounts.strength',()=>{const actual=A.passwordStrength(t);assert.equal(actual,c==='empty'?0:c==='huge'?3:1);assert.equal(A.passwordStrength('short'),0);return {characters:t.length,strength:actual};});
observe('accounts.last-seen',()=>{const now=Date.parse('2026-10-04T12:00:00Z'); const source=c==='empty'?'':c==='huge'?'invalid'.repeat(14000):t;assert.equal(A.lastSeen(source,now),'');return {sourceCharacters:source.length};});
observe('accounts.form',()=>{const actual=A.newAccountProblem({username:t,password:t},['Already']); assert.ok(actual); assert.match(A.newAccountProblem({username:'aLrEaDy',password:'Strong123!'},['Already']),/already an account/);assert.equal(A.newAccountProblem({username:'valid',password:'Strong123!'},[]),'');return {characters:t.length,problem:actual.slice(0,120)};});
observe('accounts.device',()=>{assert.equal(A.deviceKind(t),'computer');assert.equal(A.deviceKind('Android'),'phone');assert.equal(A.deviceKind('iPad'),'tablet');assert.equal(A.deviceKind('desktop app'),'app');return {characters:t.length};});
if(c==='huge')observe('accounts.generated-password',()=>{let calls=0;for(let i=0;i<4096;i++){const result=A.generatePassword(limit=>{calls++;return limit-1;});assert.equal(result,'zuzu-zuzu-99-zuzu');}assert.equal(calls,13*4096);return {passwords:4096,randomDraws:calls};});
observe('fabric.account',()=>{const input={label:t,permissions:['SEND','read','read'],password:'synthetic-only',configuration:{token:'synthetic-only'}};const result=F.buildCommunicationAccountPayload(input);assert.deepEqual(result.configuration,{});assert.ok(!('password'in result));assert.deepEqual(result.permissions,['read','send']);return {labelCharacters:result.label.length,configurationKeys:0};});
observe('fabric.normalize',()=>{const records=Array.from({length:c==='huge'?4000:1},(_,i)=>({accountId:i,label:t}));const source=c==='empty'?null:{accounts:records,imports:[],permissionLadder:[]};const result=F.normalizeCommunicationFabric(source);assert.equal(result.accounts.length,c==='empty'?0:records.length);assert.deepEqual(result.imports,[]);return {accounts:result.accounts.length};});
observe('fabric.insert',()=>{assert.equal(F.canInsertPresentationPrompt({compiled:t,requiresExplicitInsert:true,automatedLogin:false,transcriptHarvesting:false}),Boolean(t));for(const field of ['requiresExplicitInsert','automatedLogin','transcriptHarvesting']){const input={compiled:t||'owned',requiresExplicitInsert:true,automatedLogin:false,transcriptHarvesting:false};delete input[field];assert.equal(F.canInsertPresentationPrompt(input),false);}return {characters:t.length,missingSafeClaimsRejected:3};});
observe('fabric.approval',()=>{assert.equal(F.permissionApprovalLabel(t),'Approve for this account');for(const p of ['send','delete','unsubscribe'])assert.equal(F.permissionApprovalLabel(p),'Confirm each action');return {characters:t.length};});
observe('fabric.tone',()=>{assert.equal(F.communicationStateTone(t),'neutral');assert.equal(F.communicationStateTone('CONNECTED'),'good');assert.equal(F.communicationStateTone('blocked-by-organization'),'blocked');return {characters:t.length};});
console.log(JSON.stringify(out));
'''


FAMILIES = {
    "account": (_account, {"proofs-b.engine.account"}, TEXT | {"concurrency", "stale", "permissions"}),
    "presentation": (_presentation, {"proofs-b.engine.presentation"}, TEXT | {"stale"}),
    "capture": (_capture, {"proofs-b.engine.capture"}, TEXT | {"concurrency", "permissions"}),
    "capsule": (_capsule, {"proofs-b.engine.capsule"}, TEXT | {"concurrency", "permissions"}),
    "experiment": (_experiment, {"proofs-b.engine.experiment"}, TEXT | {"concurrency", "stale"}),
    "authorization": (_authorization, {"proofs-b.engine.authorization"}, TEXT | {"permissions"}),
    "benchmark": (_benchmark, {"proofs-b.engine.benchmark"}, TEXT | {"concurrency", "stale"}),
    "recorder": (_recorder, {"proofs-b.engine.recorder", "proofs-b.engine.event-tail"}, TEXT | {"concurrency", "interrupted", "stale"}),
    "handoff": (_handoff, {"proofs-b.engine.handoff"}, TEXT),
    "routing": (_routing, {"proofs-b.engine.routes", "proofs-b.engine.route-equivalence"}, TEXT),
    "autotune": (_autotune, {"proofs-b.engine.autotune"}, TEXT | {"permissions", "stale"}),
    "suggestions": (_suggestions, {"proofs-b.engine.suggestions"}, TEXT),
    "verdict": (_verdict, {"proofs-b.engine.verdict"}, TEXT | {"stale", "permissions"}),
    "delivery": (_delivery, {"delivery.append", "delivery.update", "delivery.tail-update", "delivery.observe", "delivery.ack", "delivery.browser", "delivery.skipped"}, TEXT | {"concurrency", "interrupted"}),
    "message": (_message, {"delivery.message"}, TEXT),
    "ocr": (_ocr, {"adapters.ocr.boundaries"}, TEXT),
    "release": (_release, {"adapters.release.selection"}, TEXT | {"stale"}),
    "html": (_html, {"adapters.html.scoring"}, TEXT | {"stale"}),
    "staging": (_staging, {"adapters.release.staging"}, TEXT | {"concurrency", "stale", "offline", "interrupted"}),
    "update": (_update, {"adapters.release.update"}, TEXT | {"stale", "offline"}),
    "publication": (_publication, {"adapters.workflow.publication"}, TEXT | {"permissions", "stale"}),
    "git": (_git, {"adapters.git.objects", "adapters.git.safety"}, TEXT | {"permissions", "concurrency", "stale"}),
}
PURE_NAMES = {"presentation", "handoff", "message", "ocr", "release", "routing", "autotune", "suggestions"}
NODE_IDS = {"accounts.initials", "accounts.avatar", "accounts.last-seen", "accounts.strength", "accounts.form", "accounts.device", "accounts.generated-password", "fabric.account", "fabric.normalize", "fabric.insert", "fabric.approval", "fabric.tone"}


def run(root, contracts, categories):
    rows = []
    for name, (builder, claimed, supported) in FAMILIES.items():
        ids = sorted(claimed & contracts.keys())
        for category in categories:
            if not ids or category not in supported:
                continue
            scratch = root / f"engine-{name}-{category}"
            scratch.mkdir(parents=True, exist_ok=False)
            bound = ids
            if name == "delivery" and category == "concurrency":
                bound = [i for i in ids if i in {"delivery.append", "delivery.update", "delivery.ack", "delivery.observe"}]
            elif name == "delivery" and category == "interrupted":
                bound = [i for i in ids if i in {"delivery.update", "delivery.observe"}]
            row = {"id": f"engine:{name}:{category}", "category": category, "contracts": bound,
                   "boundary": "Actual production local owner; independent durable rows, byte hashes or model output observation"}
            try:
                row.update(status="passed", detail=builder(scratch, category))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error), "scratch": str(scratch)})
            rows.append(row)
    repository = Path(__file__).resolve().parents[2]
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    for category in categories:
        if category not in TEXT:
            continue
        result = subprocess.run(["node", "--input-type=module", "-e", NODE_CODE, category], cwd=repository,
                                capture_output=True, text=True, timeout=45, **hidden_windows_subprocess_kwargs())
        if result.returncode:
            rows.append({"id": f"engine:node:{category}", "category": category, "contracts": sorted(NODE_IDS & contracts.keys()), "status": "failed", "detail": result.stderr})
            continue
        for value in json.loads(result.stdout):
            identity = value.pop("contract")
            if identity in contracts:
                rows.append({"id": f"engine:node:{identity}:{category}", "category": category, "contracts": [identity], **value,
                             "boundary": "Actual Node Accounts/Fabric production helper call; model behavior only, no rendered UI proof"})
    return rows


def blocker(contract, category):
    identity = contract["id"]
    if identity == "accounts.generated-password" and category in {"empty", "unicode"}:
        return {"kind": "not_applicable", "reason": "The inspected generator accepts only a randomness callback and thirteen finite numeric draws, not text or an empty collection. Huge repeated fresh draws are generated; empty/unicode user strings do not enter this claim."}
    if identity in {"delivery.browser", "delivery.skipped"} and category in {"concurrency", "stale", "interrupted"}:
        return {"kind": "fixture_gap", "reason": f"{identity} needs its own adverse {category} producer run; the shared journal adverse fixture covers journal mutators without claiming this producer executed concurrently or during a crash."}
    if identity == "delivery.tail-update" and category in {"concurrency", "interrupted"}:
        return {"kind": "fixture_gap", "reason": f"{identity} legacy tail mutator still needs a direct {category} fixture; identity updates and concurrent append receipts are distinct behavior."}
    if identity in NODE_IDS and category not in TEXT:
        return {"kind": "not_applicable", "reason": f"{identity} is a synchronous in-memory account/fabric helper, with caller supplied values and no worker, persistent revision, network or grant. {category} is not a boundary of this exact model claim; browser/account service effects require their own contracts."}
    for name, (_, ids, supported) in FAMILIES.items():
        if identity not in ids or category in supported:
            continue
        if category == "offline":
            return {"kind": "not_applicable", "reason": f"{identity} at its inspected owner operates on selected local data or explicitly disabled escalation without any provider request; a network outage is not an operation boundary of this exact claim."}
        if name in PURE_NAMES and category in {"concurrency", "interrupted", "stale", "permissions"}:
            return {"kind": "not_applicable", "reason": f"{identity} concerns an in-memory {name} transformation/plan without a background worker or mutation transaction. The audited owner has no {category} boundary except categories explicitly generated above."}
        return {"kind": "fixture_gap", "reason": f"{identity} still needs an actual {category} {name} fixture. Successful local disk rows cannot prove a missing adverse boundary."}
    if identity.startswith("adapters.sync.") and identity not in {"adapters.sync.policy", "adapters.sync.compatibility"}:
        path = Path(__file__).resolve().parents[2] / ".agent_control/proofs-b/native-syncthing/syncthing-windows-amd64-v2.1.5/syncthing.exe"
        return {"kind": "fixture_gap", "reason": f"{identity} still needs real pinned native Syncthing adverse runs. Audited _native_sync_check requires {path.as_posix()}; prepared executable present={path.is_file()}. This builder does not download dependencies or read enrolled credential files. Missing fixtures/runtime preparation are remaining work, not impossibility or new external authority."}
    return None
