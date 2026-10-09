"""Always-on action contracts and bounded local proofs for the PROOFS-b engine slice.

The checks operate on production results, not source strings. Scratch procedures
use the existing local engines; no provider, account, scheduler or live UI is used.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import time
from functools import wraps
from pathlib import Path


def require(ok, identity, message):
    if not ok:
        raise ValueError(f"Contract {identity}: {message}")


def checked(identity):
    """Preserve the wrapped public signature and check every successful call."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def call(*args, **kwargs):
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            result = function(*args, **kwargs)
            check(identity, arguments.arguments, result)
            return result
        return call
    return decorate


def check(identity, args, result):
    if identity == "proofs-b.engine.account":
        from .ecosystem_fabric import SENSITIVE_CONFIGURATION_KEYS, PER_ACTION_COMMUNICATION_PERMISSIONS
        require(not set(result["configuration"]) & SENSITIVE_CONFIGURATION_KEYS
                and result["perActionApprovals"] == sorted(set(result["permissions"]) & PER_ACTION_COMMUNICATION_PERMISSIONS), identity, "account stored secrets or lost approvals")
    elif identity == "proofs-b.engine.presentation":
        require(result["requiresExplicitInsert"] is True and result["automatedLogin"] is False
                and result["transcriptHarvesting"] is False and result["compiled"].startswith(result["original"] + "\n\n"), identity, "prompt handoff changed original or bypassed insertion")
    elif identity == "proofs-b.engine.capture":
        payload = args["payload"]
        digest = hashlib.sha256(json.dumps(payload["content"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        require(result["lineage"]["userInitiated"] is True and result["lineage"]["source"] == str(payload["source"]).strip()
                and result["contentSha256"] == digest, identity, "capture lineage or content digest differs")
    elif identity == "proofs-b.engine.capsule":
        require(result["requiresExplicitShare"] is True and result["transportState"] == "prepared-not-sent", identity, "preparation implied transmission")
        require(json.loads(Path(result["recordPath"]).read_text(encoding="utf-8")) == {k: v for k, v in result.items() if k != "recordPath"}, identity, "capsule receipt differs from durable record")
    elif identity == "proofs-b.engine.experiment":
        row = args["row"]
        require(result["journal"] == json.loads(row["journal_json"]) and result["verdict"] == (row["verdict"] or None)
                and result["state"] == row["state"] and result["lifetime"] == json.loads(row["lifetime_json"]), identity, "experiment observer lost recorded evidence, verdict or lifetime")
    elif identity == "proofs-b.engine.authorization":
        act = result["tier"] == "act"
        require(result["executable"] is False and result["simulated"] is (result["tier"] == "simulate")
                and (not act or bool(result["target"]) and result["authorizationContextRecorded"] is True
                     and result["approval"] == "per-action" and result["state"] == "approval-required"), identity, "action plan bypassed recorded scope/approval")
    elif identity == "proofs-b.engine.benchmark":
        subjects, results = args["subjects"], args["results"]
        latest = {str(r.get("subjectId") or ""): r for r in results if isinstance(r, dict) and r.get("subjectId")}
        exclusions = []
        for subject in subjects:
            sid = str(subject.get("subjectId") if isinstance(subject, dict) else subject)
            row = latest.get(sid)
            if not row:
                exclusions.append({"subjectId": sid, "reason": "not-reported"})
            else:
                exclusions.extend({"subjectId": sid, "reason": reason} for field, forbidden, reason in
                                  (("budgetExceeded", True, "budget-exceeded"), ("comparableContext", False, "context-not-comparable")) if row.get(field) is forbidden)
        require(result["exclusions"] == exclusions and result["eligible"] is (not exclusions and len(latest) == len(subjects))
                and result["interpretation"] == "not-reported" and result["equalBudget"] == args["budget"]
                and result["measuredFacts"] == results, identity, "comparison eligibility or recorded facts differ")
    elif identity == "proofs-b.engine.workflow":
        tasks = result["tasks"]
        require([t["role"] for t in tasks] == ["reader", "planner", "executor", "verifier"]
                and len({t["id"] for t in tasks}) == 4 and result["maxParallel"] == 1, identity, "workflow stage identity differs")
        for index, task in enumerate(tasks):
            authority = task["teamContract"]["authority"]
            require(authority["allowWorkspaceMutation"] is (task["role"] == "executor" and not result["preset"]["readOnly"])
                    and task["dependencies"] == ([tasks[index - 1]["id"]] if index else []), identity, "workflow widened authority or changed dependencies")
            handback = task["teamContract"]["handback"]
            require(handback["promptHash"] == hashlib.sha256(handback["systemPrompt"].encode()).hexdigest(), identity, "role prompt digest differs")
    elif identity == "proofs-b.engine.handoff":
        for (node_id, node), row in zip(args["completed"].items(), result):
            brief = json.loads(row["content"])
            receipt = node.get("result") or {}
            text = str(receipt.get("reply") or receipt.get("output") or "")
            bound = 4000 if node.get("routeSelection", {}).get("role") == "reader" else 5000
            require(brief["summary"] == text[:bound] and brief["truncated"] is (len(text) > bound)
                    and brief["sha256"] == hashlib.sha256(text.encode()).hexdigest()
                    and brief["fullResultRef"] == f"agent-node:{node_id}:result" and "raw" not in brief, identity, "bounded handoff lost lineage or leaked raw dump")
        require(len(result) == len(args["completed"]), identity, "handoff omitted dependency")
    elif identity == "proofs-b.engine.verdict":
        value = result["verification"]
        require(result["status"] == {"pass": "completed", "fail": "failed", "unverified": "unverified"}[value["verdict"]], identity, "verdict/status disagree")
        if result["status"] == "completed":
            require(bool(value.get("evidence")), identity, "pass without evidence")
            if args["root"] is not None:
                require(bool(value.get("artifactChecks")) and all(r["status"] == "matched" for r in value["artifactChecks"]), identity, "pass without inspected artifact digests")
    elif identity == "proofs-b.engine.recorder":
        if "eventCount" in result:
            require(result["eventCount"] == len(result["events"]) <= 200 and len(result["stdoutTail"]) <= 2000
                    and len(result["stderrTail"]) <= 2000 and len(result["processIds"]) <= 20, identity, "recorder bounds differ")
            require(json.loads(json.dumps(result)) == result, identity, "snapshot is not a serializable receipt")
        else:
            require(result["missionId"] == args["self"].mission_id and len(result["message"]) <= 500
                    and len(result["kind"]) <= 120 and len(result["payload"]) <= 24, identity, "event identity or bounds differ")
    elif identity == "proofs-b.engine.event-tail":
        require(len(result) <= max(1, min(int(args["limit"] or 1), 200)) and all(isinstance(r, dict) for r in result), identity, "corrupt event escaped or event tail unbounded")
    elif identity == "proofs-b.engine.suggestions":
        from .feature_suggester import FEATURE_LIBRARY
        require(len({r["id"] for r in result}) == len(result) and all(r["id"] in {f["id"] for f in FEATURE_LIBRARY} for r in result)
                and [r["score"] for r in result] == sorted((r["score"] for r in result), reverse=True), identity, "suggestions invented identities or lost ranking")
    elif identity == "proofs-b.engine.summary":
        count = result["total_sessions"]
        require(isinstance(count, int) and count >= 0 and 0 <= result["sessions_with_handoff"] <= count
                and 0 <= result["verification_failures"] <= result["verification_commands"]
                and 0 <= result["blocked_commands"] <= result["verification_commands"], identity, "run aggregation counts inconsistent")
    elif identity == "proofs-b.engine.autotune":
        total = int(args["harness_lab_snapshot"].get("efficiency", {}).get("totalRuns", 0) or 0)
        require(result["eligible"] is (total >= 3) and result["enabled"] is bool(args["auto_optimize_routing"])
                and (result["eligible"] and result["enabled"] or not result["appliedPolicy"]), identity, "routing adapted without enough local evidence")
        if result["appliedPolicy"].get("policy") == "safety_bias":
            require(result["routingStrategy"] == "uniform_quality" and result["forcePauseOnFailure"] is True, identity, "unsafe safety route")
    elif identity == "proofs-b.engine.routes":
        from .fluxio_harness import normalize_route_overrides
        routes = {r.role: r for r in result}
        require(len(routes) == len(result) and {"planner", "executor", "verifier"} <= set(routes), identity, "route roles missing or duplicated")
        for override in normalize_route_overrides(args["route_overrides"] or []):
            require(override["role"] in routes and routes[override["role"]].provider == override["provider"]
                    and routes[override["role"]].model == override["model"], identity, "explicit model route was replaced")
    elif identity == "proofs-b.engine.route-equivalence":
        session, desired = args["session"], args["desired_route"]
        if desired and getattr(session, "target_phase", "") == args["desired_phase"] and getattr(session, "target_model", "") == desired.model and getattr(session, "target_effort", "") == desired.effort:
            equivalent = {getattr(session, "target_provider", ""), desired.provider} <= {"openai", "openai-codex"}
            if equivalent:
                require(result is False, identity, "equivalent OpenAI route caused repeated delegation")
    elif identity == "proofs-b.engine.run":
        if result["status"] == "blocked":
            require(bool(result.get("preflight_failures")), identity, "blocked run lost preflight reason")
        elif result["status"] == "ok":
            state = json.loads((Path(result["session_path"]) / "state.json").read_text(encoding="utf-8"))
            fields = ("session_lineage", "autopilot_status", "autopilot_pause_reason", "parallel_agents", "merge_policy", "worker_merge_events")
            require(all(result[k] == state[k] for k in fields), identity, "run receipt differs from saved resumable state")
            require(all(Path(p).is_file() for p in result["handoff_packets"] + result["checkpoints"]), identity, "missing durable handoff/checkpoint")
            parent = args["resume_from_session_id"]
            require(not parent or parent in result["session_lineage"], identity, "resume lost parent lineage")
    elif identity == "proofs-b.engine.watchdog":
        if result is not None:
            mission = args["mission"]
            require(mission.state.status in {"running", "launching"} and not mission.proof.changed_files and not mission.proof.artifacts
                    and result["elapsedMinutes"] >= max(1, args["threshold_minutes"]), identity, "watchdog flagged a recent or evidenced mission")
    elif identity == "proofs-b.engine.watchdog-enforce":
        from .mission_receipts import load_mission_receipts
        from .mission_watchdog import FAKE_RUNNING_STOP_REASON
        missions = {m.mission_id: m for m in args["missions"]}
        for row in result:
            mission = missions[row["missionId"]]
            receipts = load_mission_receipts(args["root"], mission_id=row["missionId"])
            require(mission.state.status == "blocked" and mission.state.stop_reason == FAKE_RUNNING_STOP_REASON
                    and any(r["receipt_id"] == row["receiptId"] and r["decision"] == "blocked" for r in receipts), identity, "watchdog blocking lacked durable state or stuck receipt")
    elif identity == "proofs-b.engine.chat-plan":
        service = args["self"]
        require(result["planHash"] == service._plan_hash(result) and result["encryptionRequired"] is True
                and result["summary"]["attachments"] == len(result["attachments"]), identity, "chat plan missing encryption or hash-bound attachments")
    elif identity == "proofs-b.engine.chat-public":
        service = args["self"]
        text = json.dumps(result)
        for account in service._accounts():
            private = [str(account.get(k) or "") for k in ("userId", "deviceId", "credentialsPath", "storePath")]
            private.extend(str(r.get("roomId") or "") for r in account.get("rooms") or [])
            require(all(not value or value not in text for value in private), identity, "private chat identity or protected path exposed")
    elif identity == "proofs-b.engine.skill-load":
        require(isinstance(result, list) and all(isinstance(row, dict) for row in result), identity, "skill records must be an object list")
    else:
        raise ValueError("Unknown PROOFS-b engine contract: " + identity)


def self_check(root):
    started = time.monotonic()
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    checks, rejections = [], []
    def observed(identity, ok=True, **details):
        require(ok, identity, "scratch procedure did not establish contract")
        checks.append({"contract": identity, "ok": True, **details})
    def rejected(identity, action, errors=(ValueError,)):
        try:
            action()
        except errors:
            rejections.append({"contract": identity, "rejected": True})
        else:
            raise ValueError(f"Contract {identity}: unsafe action accepted")
    _ecosystem(root / "ecosystem", observed, rejected)
    _local_workflow(root / "workflow", observed, rejected)
    _recorder(root / "recorder", observed, rejected)
    _engine(root / "engine", observed, rejected)
    _watchdog(root / "watchdog", observed, rejected)
    _routes(root / "routes", observed, rejected)
    _chat(root / "chat", observed, rejected)
    return {"area": "proofs-b-engine", "ok": True, "contracts": sorted({r["contract"] for r in checks}),
            "checks": checks, "rejections": rejections, "elapsedMs": round((time.monotonic() - started) * 1000, 3),
            "frontier": ["Provider-backed efficient workflow question/resume requires a real configured route; no provider response is fabricated.",
                         "Fluxio delegated provider execution, skill promotion and route changes need a provider runtime; local route policy checks do not establish execution.",
                         "Matrix send/history/encryption needs Matrix SDK and enrolled local account; no credential file is read and no message is sent."]}


def _ecosystem(root, observed, rejected):
    from .ecosystem_fabric import NeyviaEcosystemFabric
    service = NeyviaEcosystemFabric(root)
    account = service.register_communication_account({"accountId": "proof-local", "route": "file-import", "state": "connected", "permissions": ["read", "send"], "configuration": {"format": "mbox"}})
    observed("proofs-b.engine.account", account["perActionApprovals"] == ["send"] and service.communication_snapshot()["accounts"][0] == account)
    rejected("proofs-b.engine.account", lambda: service.register_communication_account({"route": "file-import", "configuration": {"password": "synthetic-invalid-input"}}))
    prompt = service.compile_presentation_prompt({"profile": "research", "prompt": "Compare observed facts", "context": {"scope": "public"}})
    observed("proofs-b.engine.presentation", prompt["original"] == "Compare observed facts")
    capture = service.capture_presentation_content({"userInitiated": True, "source": "file:///proof-selected-export", "content": {"text": "selected proof"}})
    observed("proofs-b.engine.capture", capture["lineage"]["userInitiated"] is True)
    rejected("proofs-b.engine.capture", lambda: service.capture_presentation_content({"source": "file:///proof", "content": {"text": "unselected"}}))
    rejected("proofs-b.engine.capsule", lambda: service.build_share_capsule({"content": {"text": "credential sk-syntheticProofInput0123456789"}}), (RuntimeError,))
    capsule = service.build_share_capsule({"content": {"text": "public observed result"}})
    observed("proofs-b.engine.capsule", capsule["transportState"] == "prepared-not-sent")
    experiment = service.create_experiment({"title": "Local measured file", "hypothesis": "Its digest persists", "lifetime": {"kind": "session"}})
    eid = experiment["experimentId"]
    rejected("proofs-b.engine.authorization", lambda: service.plan_experiment_action({"experimentId": eid, "tier": "act", "target": "scratch-file"}))
    service.record_experiment_observation({"experimentId": eid, "observation": "Digest recorded", "evidence": {"sha256": capsule["capsuleId"]}})
    service.conclude_experiment({"experimentId": eid, "verdict": "failed: deliberately retained negative verdict"})
    snapshot = service.experiment_snapshot()["experiments"][0]
    observed("proofs-b.engine.experiment", snapshot["journal"][0]["observation"] == "Digest recorded" and snapshot["verdict"].startswith("failed:") and snapshot["lifetime"] == {"kind": "session"})
    authorized = service.create_experiment({"title": "Scoped local action", "hypothesis": "The target is scoped", "authorizationContext": "Disposable local fixture"})
    plan = service.plan_experiment_action({"experimentId": authorized["experimentId"], "tier": "act", "target": "scratch-file"})
    observed("proofs-b.engine.authorization", plan["executable"] is False and plan["state"] == "approval-required")
    for excluded, reason in (({"comparableContext": False}, "context-not-comparable"), ({"budgetExceeded": True}, "budget-exceeded")):
        run = service.create_benchmark_run({"subjects": [{"subjectId": "a"}, {"subjectId": "b"}], "budget": {"maxTurns": 2}, "taskContract": {"objective": "Same observed task"}})
        service.record_benchmark_result(run["runId"], {"subjectId": "a", "success": True, "comparableContext": True})
        result = service.record_benchmark_result(run["runId"], {"subjectId": "b", "success": True, **excluded})
        observed("proofs-b.engine.benchmark", result["claim"]["eligible"] is False and result["claim"]["exclusions"] == [{"subjectId": "b", "reason": reason}], excludedReason=reason)
    # A bad result must be rejected by the host checker, not merely documented.
    rejected("proofs-b.engine.authorization", lambda: check("proofs-b.engine.authorization", {}, {**plan, "executable": True}))


def _local_workflow(root, observed, rejected):
    from .efficient_workflow import build_efficient_workflow, compact_dependency_context, verification_result
    from .agent_prompt_library import save_prompt_library
    from .neyvia_mcp_stdio import CompactNeyviaMCPServer
    root.mkdir(parents=True, exist_ok=True)
    first = build_efficient_workflow(root, {"objective": "Inspect selected file"})
    save_prompt_library(root, {"expectedRevision": 0, "roles": {"reader": {"instructions": "Read exact evidence."}}})
    second = build_efficient_workflow(root, {"objective": "Inspect selected file", "readOnly": False})
    from .neyvia_conversations import NeyviaConversationStore
    conversations = NeyviaConversationStore(root)
    saved = []
    for workflow in (first, second):
        conversation = conversations.create_conversation(kind="orchestration", title="Owned local workflow", metadata={"workflowPreset": workflow["preset"]})
        graph = conversations.create_concurrency_plan(conversation["conversationId"], tasks=workflow["tasks"], max_parallel=workflow["maxParallel"], preset=workflow["preset"])
        saved.append((conversation["conversationId"], graph))
    require(conversations.agent_graph(saved[0][0])["nodes"] == saved[0][1]["nodes"]
            and len(saved[0][1]["nodes"]) == len(saved[1][1]["nodes"]) == 4,
            "proofs-b.engine.workflow", "preparing another workflow changed the existing graph")
    observed("proofs-b.engine.workflow", not {r["id"] for r in first["tasks"]} & {r["id"] for r in second["tasks"]}
             and "Read exact evidence." in second["tasks"][0]["teamContract"]["handback"]["systemPrompt"]
             and "Read exact evidence." not in first["tasks"][0]["teamContract"]["handback"]["systemPrompt"])
    rejected("proofs-b.engine.workflow", lambda: build_efficient_workflow(root, {"objective": "Inspect", "routes": {"reader": {"runtimeId": "neyvia-agent", "provider": "opencode-go", "model": "glm-5.3-flash", "effort": "medium"}}}))
    file = root / "selected.txt"
    file.write_text("Observed local input\n", encoding="utf-8")
    reply = file.read_text(encoding="utf-8") * 600
    handoff = compact_dependency_context({"selected-reader": {"routeSelection": {"role": "reader"}, "result": {"reply": reply, "raw": {"privateDump": reply}}}})
    observed("proofs-b.engine.handoff", len(json.loads(handoff[0]["content"])["summary"]) == 4000)
    good = verification_result(json.dumps({"verdict": "pass", "evidence": [{"path": "selected.txt", "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}]}), root=root)
    absent = verification_result('{"verdict":"pass","evidence":[]}', root=root)
    bad = verification_result('{"verdict":"fail","evidence":["Observed failure"]}', root=root)
    unformatted = verification_result("Everything passed", root=root)
    observed("proofs-b.engine.verdict", good["status"] == "completed" and absent["status"] == "unverified" and bad["status"] == "failed" and unformatted["status"] == "unverified")
    server = CompactNeyviaMCPServer(_fixture_root(root), read_only=True, session_id="local-proof")
    def call(name, arguments):
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    read = call("neyvia.native.call", {"toolId": "workspace.read", "arguments": {"path": "selected.txt"}})
    write = call("neyvia.native.call", {"toolId": "context.compact", "arguments": {}})
    nested = call("model.tools.run", {"calls": [{"callTarget": "neyvia.workspace.browser", "arguments": {"operation": "click"}}]})
    question = call("neyvia.ask_user", {"question": "Select output", "options": ["JSON", "Text"]})
    paused = call("neyvia.native.call", {"toolId": "workspace.read", "arguments": {"path": "selected.txt"}})
    observed("proofs-b.engine.mcp-authority", "Observed local input" in json.dumps(read) and "approval_required" in json.dumps(write)
             and nested["error"]["code"] == -32003 and "pending" in json.dumps(question) and paused["error"]["code"] == -32003)


def _recorder(root, observed, rejected):
    from .flight_recorder import MissionFlightRecorder, read_flight_recorder_events
    from .feature_suggester import suggest_features_from_text
    root.mkdir(parents=True, exist_ok=True)
    stdout, stderr = root / "stdout.log", root / "stderr.log"
    stdout.write_text("Observed output\n" * 220, encoding="utf-8")
    stderr.write_text("Observed diagnostic\n", encoding="utf-8")
    recorder = MissionFlightRecorder(root, "proof-local")
    for index in range(205):
        recorder.append_event(kind=f"checkpoint.{index}", message="Observed checkpoint")
    with recorder.events_path.open("a", encoding="utf-8") as stream:
        stream.write("corrupt interrupted write\n")
    snapshot = recorder.snapshot(current_phase="verify", process_ids=[1, 2], stdout_path=stdout, stderr_path=stderr, changed_files=["selected.txt"])
    observed("proofs-b.engine.recorder", json.loads(recorder.snapshot_path.read_text(encoding="utf-8")) == snapshot and snapshot["eventCount"] == 200 and snapshot["events"][0]["kind"] == "checkpoint.5" and snapshot["events"][-1]["kind"] == "checkpoint.204"
             and snapshot["processIds"] == [1, 2] and snapshot["stderrTail"] == stderr.read_text(encoding="utf-8") and snapshot["changedFiles"] == ["selected.txt"])
    observed("proofs-b.engine.event-tail", len(read_flight_recorder_events(recorder.events_path)) == 200)
    rejected("proofs-b.engine.event-tail", lambda: check("proofs-b.engine.event-tail", {"limit": 1}, [{}, {}]))
    suggestions = suggest_features_from_text("memory context continuity budget model routing", top_k=4)
    observed("proofs-b.engine.suggestions", len(suggestions) >= 2 and "memory_long_horizon" in {r["id"] for r in suggestions})


def _engine(root, observed, rejected):
    from .constitution import AgentConstitution
    from .context_manager import ContextWindowManager
    from .engine import AutonomousEngine
    from .memory import MemoryStore
    from .persona import PersonaRegistry
    from .session_store import SessionStore
    from .skills import SkillRegistry
    from .verification import VerificationRunner
    from .checkpoints import CheckpointStore
    from .eval import summarize_runs
    import sys
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Local engine proof\nRead this selected document and persist recoverable state.\n", encoding="utf-8")
    registry = root / "skills.json"
    registry.write_text("[]", encoding="utf-8")
    def engine(tokens=600):
        return AutonomousEngine(AgentConstitution(), PersonaRegistry(root / "personas.json"), ContextWindowManager(max_tokens=tokens),
                                SessionStore(root / "runs"), VerificationRunner(), SkillRegistry(registry), MemoryStore(root / "memory.json"))
    def run(instance, **overrides):
        return instance.run(**{"objective": "Review selected local evidence and persist the result", "docs": ["README.md"], "persona": "balanced_builder", "iterations": 2,
                              "repo_path": root, "verify_commands": [], "project_profile": "Local proof", "max_handoffs": 4, "max_runtime_seconds": 20, **overrides})
    first = run(engine(), objective="Local consensus merge", iterations=1, parallel_agents=3, merge_policy="consensus")
    state = json.loads((Path(first["session_path"]) / "state.json").read_text(encoding="utf-8"))
    observed("proofs-b.engine.run", first["status"] == "ok" and len(state["completed_steps"]) >= 3 and bool(state["worker_merge_events"]), scenario="parallel-consensus")
    timeline = [json.loads(line) for line in (Path(first["session_path"]) / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
    require({"worker_iteration", "worker_merge"} <= {r["kind"] for r in timeline}, "proofs-b.engine.run", "parallel execution lost timeline events")
    sid = Path(first["session_path"]).name
    checkpoint = CheckpointStore.latest(Path(first["session_path"]))
    require(checkpoint is not None, "proofs-b.engine.run", "no recoverable checkpoint")
    resumed = run(engine(), docs=[], iterations=1, resume_from_session_id=sid)
    observed("proofs-b.engine.run", sid in resumed["session_lineage"] and resumed["readable_docs"] == 1, scenario="resume-session")
    resumed_checkpoint = run(engine(), docs=[], iterations=1, resume_from_session_id=sid, resume_from_checkpoint_path=str(checkpoint))
    observed("proofs-b.engine.run", resumed_checkpoint["status"] == "ok" and sid in resumed_checkpoint["session_lineage"], scenario="resume-checkpoint")
    blocked = run(engine(), docs=["missing-selected.md"])
    observed("proofs-b.engine.run", blocked["status"] == "blocked" and bool(blocked["preflight_failures"]), scenario="unreadable-document")
    rolled = run(engine(50), iterations=8)
    observed("proofs-b.engine.run", bool(rolled["handoff_packets"]) and bool(rolled["checkpoints"]) and bool(rolled["vibe_next_steps"])
             and Path(rolled["report_path"]).is_file() and rolled["autopilot_pause_reason"] in {"context_rollover", "context_hard_stop"}, scenario="bounded-context-rollover")
    cautious = run(engine(), iterations=1, parallel_agents=4, merge_policy="risk_averse")
    observed("proofs-b.engine.run", "verification" not in cautious["worker_merge_events"][0]["winner"]["step"].lower(), scenario="risk-averse-merge")
    measured = run(engine(), iterations=1, verify_commands=[f'"{sys.executable}" -c "print(3 * 7)"', f'"{sys.executable}" -c "raise SystemExit(1)"'])
    require(len(measured["verification_failures"]) == 1, "proofs-b.engine.summary", "failed verification command omitted")
    summary = summarize_runs(root / "runs")
    observed("proofs-b.engine.summary", summary["total_sessions"] >= 7 and summary["sessions_with_handoff"] >= 1 and summary["runs_with_checkpoints"] >= 1 and summary["verification_failures"] == 1)
    rejected("proofs-b.engine.summary", lambda: check("proofs-b.engine.summary", {"base_dir": root / "runs"}, {**summary, "total_sessions": -1}))


def _watchdog(root, observed, rejected):
    from datetime import datetime, timedelta, timezone
    from .mission_control import ControlRoomStore
    from .mission_watchdog import build_mission_watchdog_report, enforce_fake_running_missions, evaluate_fake_running_mission, _mission_event_stats_by_mission
    from .mission_receipts import load_mission_receipts
    from .models import DelegatedRuntimeSession, MissionEvent
    store = ControlRoomStore(root)
    workspace = store.load_workspaces()[0]
    mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="hermes", objective="Inspect owned local evidence", success_checks=["Selected output exists"], mode="Autopilot", verification_commands=[], max_runtime_seconds=12000)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=4)).isoformat()
    mission.created_at = old
    mission.state.status = "running"
    mission.proof.changed_files, mission.proof.artifacts = [], []
    mission.delegated_runtime_sessions = [DelegatedRuntimeSession(delegated_id="proof-idle", runtime_id="hermes", launch_command="not-launched", mission_id=mission.mission_id, status="queued", pid=0)]
    store.save_missions([mission])
    for index in range(3):
        store.append_event(MissionEvent(mission_id=mission.mission_id, kind="mission.output-missing", message="Selected output absent", metadata={"artifactGateStatus": "missing_required_output", "attempt": index}))
    stats = _mission_event_stats_by_mission(root)
    result = evaluate_fake_running_mission(mission, stats=stats, now=now, threshold_minutes=120)
    observed("proofs-b.engine.watchdog", result is not None and result["missingOutputStreak"] == 3, scenario="no-output-no-worker")
    mission.created_at = (now - timedelta(minutes=30)).isoformat()
    require(evaluate_fake_running_mission(mission, stats=stats, now=now, threshold_minutes=120) is None, "proofs-b.engine.watchdog", "recent mission wrongly flagged")
    mission.created_at = old
    mission.proof.changed_files = ["observed-result.txt"]
    require(evaluate_fake_running_mission(mission, stats=stats, now=now, threshold_minutes=120) is None, "proofs-b.engine.watchdog", "evidenced mission wrongly flagged")
    mission.proof.changed_files = []
    session = mission.delegated_runtime_sessions[0]
    session.status, session.assigned_host, session.lease_status, session.worker_heartbeat_at = "running", "local-protocol-worker", "active", now.isoformat()
    require(evaluate_fake_running_mission(mission, stats=stats, now=now, threshold_minutes=120) is None, "proofs-b.engine.watchdog", "fresh lease wrongly flagged")
    session.status, session.lease_status, session.worker_heartbeat_at = "queued", "", ""
    store.save_missions([mission])
    report = build_mission_watchdog_report(root=root, missions=store.load_missions(), workspaces=store.load_workspaces(), stale_minutes=60, fake_running_minutes=120)
    require(any(r["kind"] == "fake_running_mission" for r in report["issues"]), "proofs-b.engine.watchdog", "fake-running issue omitted")
    observed("proofs-b.engine.watchdog", True, scenario="recent-evidence-fresh-lease-exemptions")
    logs = root / ".agent_control" / "mission_async"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"mission_{mission.mission_id}_proof.log").write_text("Observed missing output diagnosis\n", encoding="utf-8")
    records = enforce_fake_running_missions(root=root, store=store, now=now)
    receipts = load_mission_receipts(root, mission_id=mission.mission_id)
    again = enforce_fake_running_missions(root=root, store=store, now=now)
    observed("proofs-b.engine.watchdog-enforce", len(records) == len(receipts) == 1 and not again and receipts[0]["missing_output_event_count"] == 3
             and "Observed missing output diagnosis" in receipts[0]["last_stdout"], scenario="block-receipt-idempotence")
    blocked = build_mission_watchdog_report(root=root, missions=store.load_missions(), workspaces=store.load_workspaces(), stale_minutes=60)
    issues = {r["kind"]: r for r in blocked["issues"]}
    observed("proofs-b.engine.watchdog-enforce", "fake_running_mission" not in issues and "stuck-mission receipt" in issues["mission_blocked_or_failed"]["firstStep"], scenario="repair-step")


def _routes(root, observed, rejected):
    from types import SimpleNamespace
    from .models import ModelRouteConfig
    from .fluxio_harness import FluxioHarness, recommended_model_routes, resolve_efficiency_autotune_policy
    routes = recommended_model_routes("builder", routing_strategy_override="uniform_quality", route_overrides=[{"role": "executor", "provider": "minimax", "model": "MiniMax-M2.7-highspeed", "effort": "medium"}])
    observed("proofs-b.engine.routes", next(r for r in routes if r.role == "executor").model == "MiniMax-M3")
    equivalent = SimpleNamespace(target_phase="execute", target_provider="openai-codex", target_model="gpt-5.4-mini", target_effort="medium")
    mismatch = FluxioHarness._delegated_route_mismatch(equivalent, desired_phase="execute", desired_route=ModelRouteConfig(role="executor", provider="openai", model="gpt-5.4-mini", effort="medium"))
    observed("proofs-b.engine.route-equivalence", mismatch is False)
    for count, completion, expected in ((2, 100, "budget_first"), (5, 40, "uniform_quality")):
        policy = resolve_efficiency_autotune_policy(harness_lab_snapshot={"efficiency": {"totalRuns": count, "completionRate": completion}, "sessionHealth": {"staleHeartbeatCount": 0}}, auto_optimize_routing=True, requested_strategy="budget_first")
        observed("proofs-b.engine.autotune", policy["routingStrategy"] == expected and policy["eligible"] is (count >= 3), sampleCount=count)
    from .skill_library import SkillLibrary
    root.mkdir(parents=True, exist_ok=True)
    path = root / "learned.json"
    path.write_text("", encoding="utf-8")
    observed("proofs-b.engine.skill-load", SkillLibrary._load_skill_rows(None, path) == [])


def _chat(root, observed, rejected):
    from .encrypted_chat import EncryptedChatService
    import sys
    root.mkdir(parents=True, exist_ok=True)
    secret_root = root / "opaque-local-paths"
    secret_root.mkdir()
    opaque = secret_root / "opaque-handle"
    # An empty availability handle is never opened/read by these procedures.
    opaque.touch()
    store = secret_root / "store"
    store.mkdir()
    local_binary = {"name": "Local Python integrity fixture", "installPath": sys.executable, "executableSha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}
    config = {"stack": {"agentTransport": local_binary, "desktopClient": local_binary}, "policy": {"secretRoot": str(secret_root), "accounts": [{"accountId": "proof", "userId": "@proof:local.invalid", "deviceId": "PROOFLOCAL", "credentialsPath": str(opaque), "storePath": str(store), "rooms": [{"roomId": "!proof:local.invalid", "agentWritable": True, "agentReadable": True, "agentAttachments": True}]}]}}
    path = root / "public-path-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    service = EncryptedChatService(root, config_path=path)
    catalog = service.account_catalog()
    compatibility = service.compatibility_snapshot()
    observed("proofs-b.engine.chat-public", catalog["summary"]["rooms"] == 1 and catalog["accounts"][0]["rooms"][0]["roomRef"].startswith("room-")
             and compatibility["agentTransport"]["hashVerified"] is True and compatibility["desktopClient"]["hashVerified"] is True,
             boundary="file-integrity and public identity projection; no Matrix runtime claim")
    room = catalog["accounts"][0]["rooms"][0]["roomRef"]
    attachment = root / "selected.txt"
    attachment.write_text("Selected public artifact", encoding="utf-8")
    plan = service.build_message_plan(account_id="proof", room_ref=room, actor="Local proof", message="Selected public result", attachments=[attachment], format="markdown")
    observed("proofs-b.engine.chat-plan", plan["message"].startswith("Neyvia · Local proof\n") and plan["attachments"][0]["sha256"] == hashlib.sha256(attachment.read_bytes()).hexdigest())
    rejected("proofs-b.engine.chat-plan", lambda: service.build_message_plan(account_id="proof", room_ref=room, actor="Local proof", message="password = synthetic-invalid-input"))
    rejected("proofs-b.engine.chat-plan", lambda: service.build_message_plan(account_id="proof", room_ref=room, actor="Local proof", attachments=[root.parent / "outside-owned-scope.txt"]))
    service.config["policy"]["accounts"][0]["rooms"][0]["agentWritable"] = False
    rejected("proofs-b.engine.chat-plan", lambda: service.build_message_plan(account_id="proof", room_ref=room, actor="Local proof", message="permission denied"), (PermissionError,))
    require(service.send(plan)["status"] == "approval_required", "proofs-b.engine.chat-plan", "message sent without approval")


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
