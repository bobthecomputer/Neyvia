"""C7d exact control/runtime boundaries on owned data.

These calls exercise production code; values, bytes and refused operations are
checked independently. No frontend model or receipt is rendered/provider proof.
Applicability belongs to the named invariant, never to a whole tool prefix.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TEXT = {"empty": "", "huge": "owned payload " * 10000,
        "unicode": "é›ªðŸ™‚e\u0301 Ø§Ù„Ø¹Ø±Ø¨ÙŠØ©\u202e\x00"}
PURE = {
    "control.attachments-message": "with_files formats supplied text/path values without opening paths",
    "control.context-budget": "status observes the caller-owned event/token object without changing it",
    "control.context-compaction": "compact_window copies caller-owned event values without durable mutation",
    "control.context-cache": "emit_prompt_cache_control maps supplied provider/key values without a provider request",
    "control.context-cache-wire": "assemble_prompt_with_cache and attached cache adapters map supplied messages/key values",
    "control.tools-deferred-schema": "list_tools/search/describe project an already constructed caller-owned catalog",
    "control.vision-wire": "chat_completions_vision_input projects supplied SDK image observations without model execution",
    "control.result-compaction": "_compartment_without_session_window copies an explicitly supplied result object",
    "control.execution-phase": "delegated_cycle_phase_for_step classifies supplied step/role values without execution",
    "runtime.service.spec": "ManagedServiceSpec validates declaration values and computes identity without launching or opening the declaration paths",
    "runtime.memory.search": "MemoryStore.search ranks the already loaded caller-owned items; persistence and reload are separate invariants",
    "native.registry": "create_adapter constructs a wrapper around exactly the supplied backend object without discovering any backend",
    "native.tools.routing": "HybridExecutionAdapter._proposal preserves explicit typed values and classifies policy; execution/capture remain separate contracts",
    "control.plan-dashboard": "dashboard._row projects explicit session/page/run objects; it does not poll a broker or provider",
    "native.tools.arguments": "prepare_arguments normalizes and validates explicit JSON against the selected loaded specification before any handler/authority/filesystem dispatch",
    "a-cli.continuity.gpu-label": "classify_gpu_control_action classifies the supplied literal label only; GPU inspection/start/stop and approval are separate owners",
    "a-cli.continuity.verification": "proportional_verification projects declared verification requirements from the supplied action; it does not perform or verify the transfer itself",
    "adapters.comparison.grading": "grade_output compares supplied marked JSON against fixed declared expected fields without reading receipts or executing a harness",
    "adapters.comparison.leader": "eligibility/capability_coverage/summarize_attempts/select_leader project supplied catalog and already observed attempt records; receipt collection and harness execution are separate owners",
    "a-cli.preferences.pid": "_tasklist_has_pid compares one supplied CompletedProcess CSV result with an exact PID field; tasklist execution and process liveness are separate owners",
    "a-cli.preferences.continue": "_mission_should_continue_after_result classifies one supplied mission and result; it does not start a continuation, provider, poll, or durable operation",
    "a-cli.preferences.poll": "_mission_poll_interval_seconds derives a scalar interval from the supplied mission and current explicit environment; sleeping and persisted polling state are separate owners",
    "a-cli.preferences.budget": "_mission_budget_settings computes scalar duration and deadline from explicit objective, budget, relative duration and time; persistence and runtime enforcement are separate owners",
    "a-cli.assets.config": "CodexAssetImporter._safe_config projects an explicitly supplied parsed dictionary through a public allowlist; home/config discovery and asset import are separate owners",
    "a-cli.archive.summary": "_message_summary projects one supplied parsed MIME message and source reference; archive filesystem parsing and durable import are separate owners",
    "a-cli.scheduler.roles": "_cluster_required_capabilities classifies the supplied delegated role and phase strings; host admission, lease ownership and runtime execution are separate owners",
    "sessions.broker.options": "ConnectedBroker._turn_options validates supplied option/image values into TurnOptions; provider execution and permission grants are separate owners",
    "sessions.broker.registry": "Registry._check validates the methods and reported app identity of an explicitly supplied adapter object; loading, discovery, availability and provider execution are separate owners",
    "a-cli.crash.time": "CrashProofStore.time_snapshot computes deadline/reserve/optional-work admission from explicit times and costs; it does not read/write the SQLite store or execute the admitted work",
    "a-cli.scheduler.root": "resolve_cluster_root projects supplied path strings and explicit current environment to one resolved Path; it opens no registry/database, dispatches no worker and owns no saved root revision",
    "a-cli.preferences.mark-dispatch": "_mark_mission_resume_dispatched mutates only the explicitly supplied mission object from the supplied dispatch receipt; it neither launches a child nor persists or grants dispatch authority",
}
STATIC = {
    "sessions.api.allowlist": "The exact invariant is the declaration inclusion CONNECTED_COMMANDS <= ALLOWED_DESKTOP_COMMANDS. Its checker takes no submitted value and reads no mutable state, permissions, revision, endpoint, durable writer, or interrupted worker. Runtime dispatch, API authority, polling and response handlers are separately applicable owners.",
}
LOCAL_COORDINATION = {
    "a-cli.scheduler.job": "upsert_job persists a declared local queued job/deduplication row; no worker dispatch or host-network admission occurs",
    "a-cli.scheduler.claim": "claim_next_job selects local SQLite job/host rows and establishes ownership in one transaction; physical host connectivity is separately observed by choose/heartbeat/expiry",
    "a-cli.scheduler.lease": "_create_lease binds a supplied job/host identity to local SQLite rows inside the caller's admission transaction; it performs no transport to the supplied host",
    "a-cli.scheduler.load": "_refresh_host_load_db derives and persists local load from active local lease rows; it makes no host-network request",
    "a-cli.scheduler.stale": "mark_stale_hosts derives local offline rows from recorded heartbeat timestamps; it never probes or contacts hosts",
    "a-cli.scheduler.expire": "expire_stale_leases atomically updates recorded expired SQLite leases/jobs/load and has no remote transport",
}


def require(value, detail):
    if not value:
        raise AssertionError(detail)


def _run_child(*args, **kwargs):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    return subprocess.run(*args, **kwargs, **hidden_windows_subprocess_kwargs())


def refusal(action, classes=(ValueError, KeyError, RuntimeError, OSError)):
    try:
        action()
    except classes as error:
        return {"type": type(error).__name__, "detail": str(error)[:240]}
    raise AssertionError("Adverse operation was admitted")


def _pure(root, category, identity):
    text = TEXT[category]
    if identity == "a-cli.scheduler.root":
        from .cluster import resolve_cluster_root
        from .proofs_a_cli_scheduler import environment
        label = "owned-é›ª" if category == "unicode" else "owned" if category == "empty" else "owned" * 20
        declared = root / label
        cluster = root / "selected-cluster"; control = root / "selected-control"
        with environment(FLUXIO_CLUSTER_ROOT=None, FLUXIO_CONTROL_PROJECT_ROOT=None):
            require(resolve_cluster_root(declared) == declared.resolve(), "unconfigured scheduler invented a different root")
            with environment(FLUXIO_CONTROL_PROJECT_ROOT=str(control)):
                require(resolve_cluster_root(declared) == control.resolve(), "scheduler dropped current explicit control root")
                with environment(FLUXIO_CLUSTER_ROOT=str(cluster)):
                    require(resolve_cluster_root(declared) == cluster.resolve() and resolve_cluster_root(declared, use_configured_root=False) == declared.resolve(), "scheduler lost cluster precedence or caller's configured-root refusal")
        require(not declared.exists() and not cluster.exists() and not control.exists(), "root projection created scheduler state")
        return {"rootPrecedenceBoundaries": 4, "registriesOpened": 0}
    if identity == "sessions.broker.options":
        from .connected_sessions.broker import ConnectedBroker, MAX_IMAGES
        from .connected_sessions.registry import ConnectedError
        model = text.strip()[:200] or None
        images = [{"data": base64.b64encode((text or "owned").encode()).decode(), "mime": "image/png", "name": text}]
        supplied = {"model": text, "effort": text, "permissionMode": text, "forkFrom": text, "transport": "print", "images": images}
        before = copy.deepcopy(supplied)
        options = ConnectedBroker._turn_options(supplied)
        require(options.model == options.effort == options.permission_mode == options.fork_from == model
                and options.transport == "print" and options.images == [{**images[0], "name": text[:200]}]
                and supplied == before, "typed options lost bounds, literal image data or changed supplied values")
        for invalid in ({"transport": "unknown-" + text}, {"images": [{}]}, {"images": [{"data": "a"}] * (MAX_IMAGES + 1)}):
            refusal(lambda invalid=invalid: ConnectedBroker._turn_options(invalid), (ConnectedError,))
        require(ConnectedBroker._turn_options(None).images == [], "absent options invented image inputs")
        return {"validatedImages": 1, "refusedOptions": 3, "providerCalls": 0, "authorityGranted": False}
    if identity == "sessions.broker.registry":
        from types import SimpleNamespace
        from .connected_sessions.registry import Registry
        from .connected_sessions.neyvia import NeyviaAdapter
        adapter = NeyviaAdapter(SimpleNamespace(root=root, literal=text))
        selected, error = Registry._check("neyvia", adapter)
        require(selected is adapter and error is None, "registry discarded exact complete production adapter")
        missing, why = Registry._check("neyvia", object())
        foreign, reason = Registry._check("claude-code", adapter)
        require(missing is foreign is None and "incomplete" in why and "different app" in reason,
                "registry admitted missing-method or wrong-app adapter identity")
        return {"selectedProductionAdapter": "NeyviaAdapter", "refusedAdapterShapes": 2, "providerCalls": 0}
    if identity == "a-cli.assets.config":
        from .codex_import import CodexAssetImporter
        source = {"model": text, "service_tier": "priority", "unknown": "private-sentinel", "desktop": {"followUpQueueMode": text, "unknown": "private-sentinel"},
                  "features": {"enabled": True, "invalid": text}, "plugins": {"owned": {"enabled": False, "command": "private-sentinel"}, "invalid": {"enabled": text}},
                  "marketplaces": {"owned": {"source_type": text, "url": "private-sentinel"}}, "mcp_servers": {"owned": {"command": "private-sentinel", "env": {"generated": text}}},
                  "projects": {"one": {}, "two": {}}}
        before = copy.deepcopy(source)
        safe = CodexAssetImporter(root, root / "declared-home")._safe_config(source)
        require(safe == {"model": text, "service_tier": "priority", "desktop": {"followUpQueueMode": text}, "features": {"enabled": True},
                         "plugins": {"owned": {"enabled": False}}, "marketplaces": {"owned": {"sourceType": text, "configured": True}},
                         "mcpServers": [{"name": "owned", "configured": True, "hasEnvironment": True}], "projectCount": 2}
                and source == before and "private-sentinel" not in json.dumps(safe), "safe config changed public facts or exposed excluded values")
        return {"publicAllowlistExact": True, "configFilesRead": 0}
    if identity == "a-cli.archive.summary":
        from email.message import EmailMessage
        from .communication_archive import _message_summary, MAX_BODY_PREVIEW
        msg = EmailMessage(); msg["From"] = "owned@example.invalid"; msg["Subject"] = text[:200] or "Owned empty"
        msg.set_content(text); payload = (text or "owned").encode()
        msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename="owned-é›ª.bin")
        result = _message_summary(msg, source_ref=text)
        expected_identity = "\n".join(["", "", str(msg["From"]), str(msg["Subject"]), text])
        require(result["messageId"] == hashlib.sha256(expected_identity.encode("utf8", "replace")).hexdigest()
                and result["sourceRef"] == text and result["bodyPreview"] == " ".join(text.split())[:MAX_BODY_PREVIEW]
                and result["attachments"] == [{"filename": "owned-é›ª.bin", "mediaType": "application/octet-stream", "bytes": len(payload)}], "MIME summary lost source identity, bounded body or decoded attachment length")
        return {"decodedAttachmentBytes": len(payload), "archiveFilesOpened": 0}
    if identity == "a-cli.scheduler.roles":
        from .runtime_supervisor import _cluster_required_capabilities
        from .models import DelegatedRuntimeSession
        session = DelegatedRuntimeSession(delegated_id="owned", runtime_id="local", launch_command="", workspace_root=str(root), execution_root=str(root), target_role=text, target_phase=text)
        require(_cluster_required_capabilities(session) == ["runtime.launch"], "unclassified role manufactured browser capability")
        for role in ("browser", "playwright", "frontend", "ui"):
            session.target_role = role + " " + text
            require(_cluster_required_capabilities(session) == ["browser.verify", "runtime.launch"], "browser role lost unique sorted required capabilities")
        return {"roleBoundaries": 5, "hostsAdmitted": 0, "runtimeCalls": 0}
    if identity == "a-cli.crash.time":
        from .crashproof import CrashProofStore
        store = CrashProofStore(root)
        now = "2026-10-04T12:00:00Z"
        no_deadline = store.time_snapshot(deadline_at=None, now=now)
        cost = 1e100 if category == "huge" else 2
        optional = store.time_snapshot(deadline_at="2026-10-04T12:00:01Z", now=now, estimated_next_seconds=cost, verification_reserve_seconds=3, optional=True)
        required = store.time_snapshot(deadline_at="2026-10-04T12:00:01Z", now=now, estimated_next_seconds=cost, verification_reserve_seconds=3, optional=False)
        require(no_deadline["shouldContinue"] and no_deadline["reason"] == "no_deadline" and no_deadline["remainingSeconds"] is None
                and optional["remainingSeconds"] == 1 and optional["requiredSeconds"] == cost + 3 and optional["skipOptional"] and not optional["shouldContinue"]
                and required["shouldContinue"] and required["deadlineRisk"] and not required["skipOptional"], "deadline/reserve calculator lost required/optional distinction or declared large cost")
        if category == "unicode":
            refusal(lambda: store.time_snapshot(deadline_at=text, now=now))
        return {"deadlineBoundaries": 3, "workExecuted": 0}
    if identity.startswith("a-cli.preferences."):
        from . import cli
        from .models import Mission
        from datetime import datetime, timezone, timedelta
        from .proofs_a_cli_scheduler import environment
        if identity.endswith("pid"):
            for code, output, expected in ((0, '"' + text + '","777","Console","1","1 K"', True),
                                           (0, '"' + text + '","1777","Console","1","1 K"', False),
                                           (1, '"' + text + '","777","Console","1","1 K"', False),
                                           (0, text, False)):
                observed = subprocess.CompletedProcess(["declared-tasklist"], code, stdout=output)
                require(cli._tasklist_has_pid(777, observed) is expected, "PID parser lost exact field or exit-status boundary")
            return {"suppliedProcessResults": 4, "processesInspected": 0}
        mission = Mission(mission_id="owned", workspace_id="scratch", runtime_id="local", objective=text, success_checks=[])
        mission.run_budget.run_until_behavior = "continue_until_blocked"
        if identity.endswith("mark-dispatch"):
            for blocked, skipped in ((True, False), (False, False), (False, True)):
                value = {"blocked": blocked, "skipped": skipped, "reason": text, "pid": 123, "queue": "cluster_registry"}
                original = copy.deepcopy(value)
                require(cli._mark_mission_resume_dispatched(mission, value) is None, "dispatch marker fabricated a dispatch result")
                expected = text or "mission_resume_blocked"
                require(mission.state.status == ("blocked" if blocked else "running")
                        and mission.state.last_error == (expected if blocked else None)
                        and mission.state.stop_reason == (expected if blocked else None)
                        and mission.state.planner_loop_status == ("blocked" if blocked else "running" if skipped else "launching")
                        and mission.proof.blocked_by == ([expected] if blocked else []) and value == original,
                        "supplied blocked/skipped receipt lost exact in-memory mission transition or modified source receipt")
            return {"suppliedTransitions": 3, "processesLaunched": 0, "durableWrites": 0}
        if identity.endswith("continue"):
            result = {"status": "ok", "autopilot_status": "paused", "remaining_steps": [text]}
            before = copy.deepcopy(result)
            require(cli._mission_should_continue_after_result(mission, result), "eligible unblocked continuation refused")
            for reason in ("approval_required", "verification_failed", "verification_failure", "delegated_runtime_running", "unknown-" + text):
                require(not cli._mission_should_continue_after_result(mission, {**result, "autopilot_pause_reason": reason}), "blocked/unknown pause started another continuation")
            for adverse in ({**result, "status": "failed"}, {**result, "autopilot_status": "completed"}, {**result, "remaining_steps": []}):
                require(not cli._mission_should_continue_after_result(mission, adverse), "failed/completed/empty continuation admitted")
            require(cli._mission_should_continue_after_result(mission, {**result, "autopilot_pause_reason": "context_budget"}), "context pause lost selected continuous mode")
            mission.run_budget.run_until_behavior = "pause_on_failure"
            require(not cli._mission_should_continue_after_result(mission, result) and result == before, "paused mode continued or changed caller result")
            return {"decisionBoundaries": 11, "continuationsStarted": 0, "literalCharacters": len(text)}
        if identity.endswith("poll"):
            configured = "" if category == "empty" else "1000000" if category == "huge" else text.replace("\x00", "")
            with environment(FLUXIO_MISSION_POLL_SECONDS=configured):
                require(cli._mission_poll_interval_seconds(mission) == (1000000 if category == "huge" else 15), "explicit polling setting/default changed")
                mission.run_budget.run_until_behavior = "pause_on_failure"
                require(cli._mission_poll_interval_seconds(mission) == 0, "paused mission retained polling interval")
            return {"configuredCharacters": len(configured), "pollsExecuted": 0}
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        computed = cli._mission_budget_settings(text, 2, "pause_on_failure", relative_stop_minutes=7, now=now)
        require(computed == {"max_runtime_seconds": 420, "deadline_at": (now + timedelta(minutes=7)).isoformat(), "run_until_behavior": "continue_until_blocked", "enforced": True}, "explicit relative duration lost precedence over objective/hour hint")
        absent = cli._mission_budget_settings(text, 0, "pause_on_failure", now=now)
        require(absent == {"max_runtime_seconds": 0, "deadline_at": None, "run_until_behavior": "pause_on_failure", "enforced": False}, "absent objective duration fabricated deadline or enforcement")
        return {"explicitRuntimeSeconds": 420, "durableWrites": 0}
    if identity.startswith("a-cli.continuity."):
        from .continuity_policy import classify_gpu_control_action, proportional_verification
        if identity.endswith("gpu-label"):
            for value, expected in ((text, "inspect_gpu"), ("START " + text, "start_instance"), ("resume " + text, "resume_instance"), ("close " + text, "stop_instance"), ("delete start resume stop " + text, "delete_instance")):
                require(classify_gpu_control_action(value) == expected, "GPU control label lost destructive/stop/resume/start precedence")
            return {"literalCharacters": len(text), "gpuActionsExecuted": 0}
        result = proportional_verification({"kind": "transfer", "literal": text})
        require(result["checks"] == ["target_exists", "size_or_hash_matches"] and result["risk"] == "standard"
                and result["avoid"] == ["unrelated_full_suite", "repetitive_polling"], "transfer verification requirements lost explicit existence/content checks")
        return {"verificationRequirements": 2, "transfersExecuted": 0}
    if identity == "adapters.comparison.grading":
        from .harness_comparison import grade_output
        expected = {"taskId": "manifest-reasoning", "project": "Aurora", "version": "4.7.2", "enabledCount": 3, "enabledWeight": 41, "firstDisabled": "boreal"}
        output = text + "\nHARNESS_BENCHMARK_RESULT=" + json.dumps(expected)
        grade = grade_output("manifest-reasoning", output)
        require(grade["parsed"] == expected and grade["correct"] and grade["points"] == grade["maxPoints"] == 6, "exact marked result was not graded against all expected fields")
        for field in expected:
            altered = {**expected, field: {"altered": text}}
            missing = {key: value for key, value in expected.items() if key != field}
            for adverse in (altered, missing):
                value = grade_output("manifest-reasoning", "HARNESS_BENCHMARK_RESULT=" + json.dumps(adverse))
                require(not value["correct"] and value["points"] == 5 and not value["checks"][field], "omitted/altered comparison field masked by passing siblings")
        require(not grade_output("manifest-reasoning", text)["correct"], "unmarked output manufactured parsed result")
        return {"fieldsChecked": 6, "independentMissingAndAlteredCases": 12, "harnessExecution": False}
    if identity == "adapters.comparison.leader":
        from .harness_comparison import eligibility, summarize_attempts, select_leader
        catalog = [{"harnessId": "complete", "label": text, "installed": True, "detected": True, "readiness": "ready", "capabilities": [{"key": "tools", "support": "native"}]},
                   {"harnessId": "ineligible", "installed": True, "detected": True, "readiness": "ready", "securityOnly": True}]
        attempts = [{"harnessId": "complete", "status": "completed", "grade": {"points": 6, "maxPoints": 6}, "receiptPresent": True, "providerSubstitution": False, "readOnlyEnforced": True, "metrics": {"executionDurationMs": duration}} for duration in (10, 20)]
        summaries = summarize_attempts(catalog, attempts)
        require(select_leader(summaries)["harnessId"] == "complete" and summaries[0]["medianExecutionMs"] == 15
                and eligibility(catalog[1])[0] is False, "leader admitted security harness or lost complete observed execution median")
        for field, bad in (("receiptPresent", False), ("providerSubstitution", True), ("readOnlyEnforced", False), ("status", "failed")):
            mutated = copy.deepcopy(attempts); mutated[0][field] = bad
            require(select_leader(summarize_attempts(catalog, mutated))["status"] == "inconclusive", "one altered observed attempt masked by complete siblings: " + field)
        require(select_leader(summarize_attempts(catalog, attempts[:1]))["status"] == "inconclusive", "missing expected attempt masked by passing sample")
        return {"observedAttemptRecords": 2, "executionMedianMs": 15, "adverseEligibilityCases": 5, "harnessExecution": False, "receiptCollection": False}
    if identity == "native.tools.arguments":
        from .edge_fixture_host_runtime import _native
        registry = _native(root)
        value = registry.prepare_arguments("workspace.read", {"path": text, "maxChars": "17", "offset": "0"})
        require(value == {"path": text, "maxChars": 17, "offset": 0}, "typed argument normalization changed literal path or numeric transport values")
        for raw in ([], "{}", {"maxChars": 1}, {"path": "owned", "maxChars": True}, {"path": "owned", "maxChars": 100001}, {"path": "owned", "offset": -1}):
            refusal(lambda raw=raw: registry.prepare_arguments("workspace.read", raw))
        return {"refusedFrames": 6, "handlerCalls": 0}
    if identity == "native.registry":
        from types import SimpleNamespace
        from .connected_sessions.neyvia import create_adapter
        backend = SimpleNamespace(root=root, literal=text)
        adapter = create_adapter(backend)
        require(adapter._backend is backend and adapter._root() == root and backend.literal == text,
                "native registry factory redirected the exact supplied backend identity")
        return {"backendIdentityPreserved": True, "providerCalls": 0}
    if identity == "native.tools.routing":
        from .action_executor import HybridExecutionAdapter
        from .models import PlannedStep, ExecutionScope
        adapter = HybridExecutionAdapter()
        scope = ExecutionScope(workspace_root=str(root), execution_root=str(root), isolated=False)
        step = PlannedStep(step_id="owned-step", title=text)
        args = {"tool": "preview.inspect", "arguments": {"url": "http://127.0.0.1:" + os.environ["NEYVIA_C7_PORT"] + "/owned", "literal": text}}
        proposal = adapter._proposal(action_id="owned", event_id="cursor", kind="native_tool", title=text, step=step, reason=text,
                                     execution_scope=scope, execution_policy=adapter.build_policy("builder"), args=args, target_path="preview.inspect")
        require(proposal.args == args and proposal.source_step_id == "owned-step" and proposal.event_id == proposal.replay_cursor == "cursor"
                and proposal.target_scope == "workspace" and proposal.target_path == "preview.inspect", "native proposal changed typed arguments, target or lineage")
        return {"typedArgumentsPreserved": True, "executedTools": 0, "renderedProof": False}
    if identity == "control.plan-dashboard":
        from .connected_sessions.dashboard import _row
        count = 0 if category == "empty" else 150 if category == "huge" else 3
        items = [{"kind": "tool", "id": f"call-{i}", "data": {"name": "Agent", "category": "agent", "title": text,
                  "status": "running", "agent": {"id": f"agent-{i}", "description": text}}} for i in range(count)]
        items.append({"kind": "reasoning", "data": {"summary": "private-literal-never-shown"}})
        source = {"id": "owned", "app": "claude-code", "status": "working", "status_since": "fallback", "title": text}
        row = _row(source, {"items": items, "context": {"used_tokens": 42}}, {"state": "running", "startedAt": "owner-start"}, None)
        require(row["id"] == "owned" and row["since"] == "owner-start" and row["tokens"] == 42
                and len(row["subagents"]) == count and "private-literal-never-shown" not in json.dumps(row),
                "dashboard lost actual agent counts/start precedence or exposed private reasoning")
        return {"declaredAgentCalls": count, "projectedAgents": len(row["subagents"]), "providerCalls": 0}
    if identity == "control.image-magic":
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "scripts/run_controlled_ai_safety_review.py"
        spec = importlib.util.spec_from_file_location("c7_image_magic", path)
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for index, (data, expected) in enumerate(((text.encode(), ""), (b"\x89PNG\r\n\x1a\n" + text.encode(), ".png"),
                               (b"\xff\xd8\xff" + text.encode(), ".jpg"), (b"RIFF0000WEBP" + text.encode(), ".webp"))):
            path = root / f"wrong-extension-{index}.txt"
            path.write_bytes(data)
            require(module.detected_image_extension(path) == expected, "magic does not match independently supplied signature")
        return {"signaturesChecked": 4, "payloadBytes": len(text.encode())}
    if identity == "control.attachments-message":
        from .connected_sessions.attachments import with_files
        paths = [root / "one.txt", root / "é›ªðŸ™‚.png"]
        require(with_files(text, []) == text, "path-free formatting changed authored text")
        result = with_files(text, paths)
        expected = (text.rstrip() or "Look at the attached files.") + "\n\n" + "\n".join("Attached file: " + str(p) for p in paths)
        require(result == expected and not any(p.exists() for p in paths), "attachment formatting changed path/text or opened a file")
        return {"pathCount": 2, "pathsOpened": 0}
    if identity in {"control.context-budget", "control.context-compaction"}:
        from .context_manager import ContextWindowManager
        manager = ContextWindowManager(100)
        if identity.endswith("budget"):
            for used, expected in ((0, "ok"), (69, "ok"), (70, "warn"), (85, "rollover"), (95, "hard_stop")):
                from .context_manager import ContextEvent
                manager.events = [ContextEvent("user", text, used)]
                manager.used_tokens = used
                require(manager.status() == expected and manager.used_tokens == used, "exact threshold/token conservation differs")
            return {"thresholds": [0, 69, 70, 85, 95]}
        for role in ("user", "assistant", "user", "tool"):
            manager.record(role, text)
        before = copy.deepcopy(manager.events)
        compact = manager.compact_window()
        require(compact[:2] == [{"role": "user", "content": text}] * 2 and len(compact) == 3
                and "events=2" in compact[-1]["content"] and manager.events == before,
                "compaction lost user bytes, non-user count or modified source")
        return {"userMessages": 2, "retainedEvents": len(manager.events)}
    if identity in {"control.context-cache", "control.context-cache-wire"}:
        from .context_microkernel import emit_prompt_cache_control, assemble_prompt_with_cache
        from .openai_adapter import apply_attached_cache_control
        for provider, supported in (("openai", True), ("anthropic", True), ("unknown-provider", False)):
            cache = emit_prompt_cache_control(stable_prefix_cache_key=text, provider=provider)
            require(cache["stable_prefix_cache_key"] == text.strip() and cache["supported"] is bool(text.strip() and supported), "cache provider/identity/support differs")
            if identity.endswith("wire"):
                messages = [{"role": "user", "content": text}]
                source = copy.deepcopy(messages)
                prompt = assemble_prompt_with_cache(messages=messages, provider=provider, stable_prefix_cache_key=text, cache_key="full")
                payload = apply_attached_cache_control({"model": "owned", "input": []}, cache)
                require(prompt["messages"] == source and messages == source and prompt["cache_key"] == "full"
                        and prompt["stable_prefix_cache_key"] == text.strip(), "prompt wire lost supplied messages/cache identity")
                if text.strip() and provider == "openai":
                    require(payload["prompt_cache_key"] == text.strip() and prompt["prompt_cache_key"] == text.strip(), "OpenAI cache wire lost key")
        return {"providers": 3, "providerCalls": 0}
    if identity == "control.tools-deferred-schema":
        from .progressive_tools import ProgressiveToolSurface, ProgressiveToolSpec
        count = 0 if category == "empty" else 160 if category == "huge" else 3
        schema = {"type": "object", "properties": {"literal": {"type": "string"}}, "required": ["literal"]}
        specs = [ProgressiveToolSpec(name=f"owned-{i:04d}", description=text, input_schema=schema) for i in range(count)]
        surface = ProgressiveToolSurface(specs)
        rows = surface.list_tools()
        require([r["name"] for r in rows] == [s.name for s in specs] and all("inputSchema" not in r for r in rows), "deferred catalog identity or schema omission differs")
        found = surface.search("", limit=20)
        require([r["name"] for r in found] == [s.name for s in specs[:20]], "bounded empty search differs")
        for spec in specs[:3]:
            require(surface.describe(spec.name)["inputSchema"] == schema, "description did not return exact selected schema")
        refusal(lambda: surface.describe("missing"))
        return {"tools": count, "searchRows": len(found)}
    if identity == "control.vision-wire":
        from agents.run_config import CallModelData, ModelInputData
        from .agent_vision import chat_completions_vision_input
        count = 0 if category == "empty" else 120 if category == "huge" else 4
        rows = [{"type": "function_call_output", "call_id": str(i), "output": [
            {"type": "input_text", "text": text}, {"type": "input_image", "image_url": f"data:image/png;base64,{i}"}]} for i in range(count)]
        before = copy.deepcopy(rows)
        result = chat_completions_vision_input(CallModelData(model_data=ModelInputData(input=rows, instructions=text), agent=None, context=None))
        require(rows == before and result.instructions == text, "vision filter altered source tool input or instructions")
        if count:
            images = [p["image_url"] for p in result.input[-1]["content"] if p["type"] == "input_image"]
            require(images == [f"data:image/png;base64,{i}" for i in range(max(0, count-2), count)] and result.input[-1]["role"] == "user", "vision filter lost latest two image identities")
            require(all(p["type"] != "input_image" for row in result.input[:-1] for p in row["output"]), "image remained in unsupported tool wire")
        else:
            require(result.input == [], "empty vision manufactured image")
        return {"observations": count, "modelCalls": 0, "renderedProof": False}
    if identity == "control.result-compaction":
        from .chat_run_control import _compartment_without_session_window
        compartment = {"messages": [text], "turnReceipts": [{"text": text}], "keeper": {"literal": text}}
        result = {"conversationPersistence": {"conversationId": "owned", "turnId": "turn"}}
        source = copy.deepcopy(compartment)
        require(_compartment_without_session_window(compartment, result) == {"keeper": {"literal": text}, "windowRef": {"conversationId": "owned", "turnId": "turn"}}
                and compartment == source, "compaction changed unrelated fields or source")
        return {"removedWindowKeys": 2, "keeperCharacters": len(text)}
    if identity == "control.execution-phase":
        from .action_executor import delegated_cycle_phase_for_step
        from .models import PlannedStep
        for roles, expected in ((["planner"], "plan"), (["executor"], "execute"), (["verifier"], "verify")):
            step = PlannedStep(step_id="owned", title="Implement smallest vertical slice", description=text)
            observed = delegated_cycle_phase_for_step(step, "After implementing verify all outcomes. " + text, [{"role": r} for r in roles])
            require(observed == expected, f"explicit {roles} role route became {observed}")
        return {"explicitRoleRoutes": 3, "executedActions": 0}
    if identity == "runtime.service.spec":
        from .edge_fixture_control_remaining import _service
        return _service(root, category, identity) or {"declarationOnly": True}
    if identity == "runtime.memory.search":
        from .edge_fixture_control_remaining import _memory
        return _memory(root, category, identity) or {"rankingAndFallback": True}
    raise ValueError("No reviewed pure owner: " + identity)


def _runtime_read(root, category, identity):
    from .edge_fixture_control_remaining import _registry, _toolchain
    from .edge_fixture_native import _sharing_denied
    if identity.startswith("runtime.install."):
        _registry(root, "unicode", identity)
        path = root / "owned-registry.json"
        before = path.read_bytes()
        from .install_profiles import InstallProfileRegistry
        with _sharing_denied(path):
            error = refusal(lambda: InstallProfileRegistry(root, registry_path=path))
        require(path.read_bytes() == before, "denied registry read changed file")
        return {"refusal": error, "sourceBytesPreserved": len(before)}
    if identity == "runtime.toolchain.integrity":
        _toolchain(root, "unicode", identity)
        return {"independentTamperReadback": True}
    raise ValueError(identity)


def _attachments(root, category, identity):
    from .connected_sessions.attachments import save_files, AttachmentError
    from .edge_fixture_native import _sharing_denied
    name = "nested/é›ªðŸ™‚.txt" if category == "unicode" else "nested/file.txt"
    data = TEXT.get(category, "owned attachment").encode()
    raw = [{"name": name, "data": base64.b64encode(data).decode()}]
    if category == "huge":
        error = refusal(lambda: save_files(raw * 11, directory=root / "files"), (AttachmentError,))
        require(not (root / "files").exists(), "too many files changed attachment folder")
    else:
        error = None
    paths = save_files(raw, directory=root / "files")
    require(len(paths) == 1 and paths[0].parent == root / "files" and paths[0].read_bytes() == data
            and paths[0].name.startswith(hashlib.sha256(data).hexdigest()[:16] + "-"), "attachment bytes/path/content identity differ")
    before = paths[0].read_bytes()
    if category == "stale":
        paths[0].write_bytes(b"tampered")
        error = refusal(lambda: save_files(raw, directory=root / "files"))
        require(paths[0].read_bytes() == b"tampered", "refused stale attachment modified newer file")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: save_files(raw, directory=root / "files"), range(8)))
        require(all(r == paths for r in results) and paths[0].read_bytes() == before, "repeated concurrent attachment identity or bytes differ")
    if category == "permissions":
        with _sharing_denied(paths[0]):
            error = refusal(lambda: save_files(raw, directory=root / "files"))
        require(paths[0].read_bytes() == before, "denied attachment read changed bytes")
    return {"refusal": error, "savedBytes": len(data), "savedSha256": hashlib.sha256(data).hexdigest()}


def _toolchain_cache(root, category, identity):
    from .marketplace_toolchain import MarketplaceToolchainUpdateManager
    from .edge_fixture_native import _sharing_denied
    binary = root / "owned.bin"; binary.write_bytes(b"owned")
    configured = {"version": "1.0.0", "path": str(binary), "executableSha256": hashlib.sha256(b"owned").hexdigest(),
                  "update": {"repository": "owned/fixture", "tagPrefix": "v", "assetTemplate": "fixture_{version}.zip", "maxDownloadBytes": 1000}}
    config = root / "toolchain.json"
    config.write_text(json.dumps({"schema": "neyvia.marketplace-toolchain/v1", "policy": {"candidateActivation": "signed-neyvia-release"}, "tools": {"owned": configured}}), encoding="utf8")
    cache = root / "cache.json"
    manager = MarketplaceToolchainUpdateManager(root, toolchain_path=config, cache_path=cache)
    release = {"tag_name": "v1.0.1", "draft": False, "prerelease": False,
               "assets": [{"name": "fixture_1.0.1.zip", "size": 500, "digest": "sha256:" + "a" * 64,
                           "browser_download_url": "https://github.com/owned/fixture/releases/download/v1.0.1/fixture_1.0.1.zip"}]}
    if identity.endswith("discovery"):
        # This row covers the metadata validator, not upstream availability.
        for field, value in (("size", 0), ("size", 1001), ("digest", ""), ("digest", TEXT.get(category, "bad")), ("browser_download_url", "http://127.0.0.1:48742/foreign")):
            adverse = copy.deepcopy(release); adverse["assets"][0][field] = value
            refusal(lambda: manager._release_candidate("owned", configured, configured["update"], adverse))
    candidate = manager._release_candidate("owned", configured, configured["update"], release)
    require(candidate["candidate"]["assetSha256"] == "a" * 64 and candidate["candidate"]["assetBytes"] == 500,
            "validated declared asset metadata differs")
    published = manager._publish_discovery({"owned": candidate})
    require(json.loads(cache.read_text(encoding="utf8")) == published, "published cache differs from returned metadata")
    if category == "stale":
        os.utime(cache, (time.time() - 30000, time.time() - 30000))
        require(manager._fresh_cache() is None, "expired cache admitted as fresh")
        cache.write_text(json.dumps({**published, "schema": "foreign"}), encoding="utf8")
        require(manager._fresh_cache() is None, "foreign cache schema admitted")
    elif category == "permissions":
        before = cache.read_bytes()
        with _sharing_denied(cache):
            require(manager._fresh_cache() is None, "unreadable cache became fresh")
            error = refusal(lambda: manager._publish_discovery({"owned": candidate}))
        require(cache.read_bytes() == before, "denied replacement changed cache")
        return {"refusal": error, "freshCache": None}
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: manager._fresh_cache(), range(12)))
        require(results == [published] * 12, "parallel exact metadata observations differ")
    else:
        require(manager.check_latest()["cache"] == "hit", "fresh durable cache did not short circuit upstream fetch")
    return {"metadataSource": "caller-owned bytes", "upstreamCalls": 0, "downloads": 0,
            "assetSha256": candidate["candidate"]["assetSha256"], "cacheBytes": cache.stat().st_size}


def _memory(root, category, identity):
    from dataclasses import asdict
    import threading
    from .memory import MemoryStore, ingest_state_into_memory
    from .edge_fixture_native import _sharing_denied
    path = root / "memory.json"
    store = MemoryStore(path)
    keeper = store.add("keeper", "keeper", "preserve keeper", ["keeper"], "note")
    before = path.read_bytes()
    def write(current, index):
        if identity.endswith("ingest"):
            return ingest_state_into_memory(current, f"writer-{index}", {"objective": f"owned-{index}", "decisions": [f"decision-{index}"], "risks": [f"risk-{index}"], "next_actions": [f"next-{index}"]})
        return [current.add(f"writer-{index}", f"owned-{index}", f"content-{index}", [str(index)], "note").id]
    if category == "concurrency":
        barrier = threading.Barrier(4)
        stores = [MemoryStore(path) for _ in range(4)]
        def compete(index):
            barrier.wait(timeout=10)
            return write(stores[index], index)
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(compete, range(4)))
        durable = MemoryStore(path).items
        expected = {keeper.id} | {value for group in ids for value in group}
        require({i.id for i in durable} == expected and durable[0] == keeper,
                f"Concurrent MemoryStore writers lost distinct durable rows: expected {len(expected)}, observed {len(durable)}")
        return {"writers": 4, "durableRows": len(durable), "distinctReturnedRows": len(expected)}
    if category == "permissions":
        with _sharing_denied(path):
            error = refusal(lambda: write(store, 0))
        require(path.read_bytes() == before and MemoryStore(path).items == [keeper], "denied memory write changed durable keeper")
        return {"refusal": error, "keeperPreserved": True}
    if category == "stale":
        stale = MemoryStore(path)
        current = store.add("fresh", "fresh", "newer", [], "note")
        fresh_bytes = path.read_bytes()
        if identity.endswith("ingest"):
            ids = write(stale, 0)
            durable = MemoryStore(path).items
            require(durable[:2] == [keeper, current] and {i.id for i in durable[2:]} == set(ids),
                    "ingestion from stale caller erased newer durable rows or added identities")
            return {"newerRowsPreserved": 2, "insertedRows": len(ids)}
        # Explicit replacement save must not overwrite a newer store snapshot.
        error = refusal(stale.save)
        require(path.read_bytes() == fresh_bytes and MemoryStore(path).items == [keeper, current], "stale explicit save overwrote newer state")
        return {"refusal": error, "newerRows": 2}
    if category == "interrupted":
        program = ("import os,sys;from pathlib import Path;from grant_agent.memory import MemoryStore,ingest_state_into_memory;"
                   "s=MemoryStore(Path(sys.argv[1]));"
                   "ingest_state_into_memory(s,'exit',{'objective':'owned','decisions':['committed']});os._exit(23)")
        result = _run_child([sys.executable, "-c", program, str(path)], capture_output=True,
                                timeout=30, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
        require(result.returncode == 23, "owned memory child failed to exit after committed ingestion: " + result.stderr.decode("utf8")[-300:])
        durable = MemoryStore(path).items
        require(durable[0] == keeper and len(durable) == 2 and durable[1].content == "committed", "committed ingestion did not survive abrupt child exit")
        return {"childExit": 23, "durableRows": 2, "durableSha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    ids = write(store, 0)
    durable = MemoryStore(path).items
    require(durable[0] == keeper and {i.id for i in durable[1:]} == set(ids), "local memory commit lost exact returned identities")
    return {"networkCalls": 0, "durableRows": len(durable)}


MCP_WORKER = r'''import json,os,sys
from pathlib import Path
path=Path(sys.argv[1])
def read():
    headers={}
    while True:
        line=sys.stdin.buffer.readline()
        if not line:return None
        if line in (b"\r\n",b"\n"):break
        key,value=line.decode().split(":",1);headers[key.lower()]=value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))
def send(item):
    body=json.dumps(item).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode()+body)
    sys.stdout.buffer.flush()
label=Path(sys.argv[2]).read_text(encoding="utf8")
tools=[{"name":"read_note","description":label,"inputSchema":{"type":"object"},"annotations":{"readOnlyHint":True}},
       {"name":"write_note","description":label,"inputSchema":{"type":"object","properties":{"note":{"type":"string"}},"required":["note"],"additionalProperties":False},"annotations":{"readOnlyHint":False}}]
while True:
    msg=read()
    if msg is None:break
    if "id" not in msg:continue
    method=msg["method"]
    if method=="initialize":result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"c7d-owned-notes","version":"1"}}
    elif method=="tools/list":result={"tools":tools}
    elif method=="tools/call":
        params=msg["params"]
        if params["name"]=="write_note":
            path.write_text(params["arguments"]["note"],encoding="utf8")
            if params["arguments"]["note"]=="exit-after-effect":os._exit(23)
        result={"content":[],"isError":False,"structuredContent":{"note":path.read_text(encoding="utf8") if path.exists() else ""}}
    else:result={}
    send({"jsonrpc":"2.0","id":msg["id"],"result":result})
'''


def _mcp(root, category, identity):
    from .mcp_broker import McpOutboundBroker, register_with_progressive_surface
    from .progressive_tools import ProgressiveToolSurface
    worker = root / "owned_mcp.py"; worker.write_text(MCP_WORKER, encoding="utf8")
    note = root / "note.txt"; note.write_text("keeper", encoding="utf8")
    metadata = root / "metadata.txt"; metadata.write_text(TEXT.get(category, category), encoding="utf8")
    config = {"servers": {"notes": {"transport": "stdio", "command": sys.executable,
              "args": [str(worker), str(note), str(metadata)], "authState": "authenticated", "requestTimeoutS": 3},
              "sse": {"transport": "sse", "url": "http://127.0.0.1:48742/never-called"}}}
    broker = McpOutboundBroker(root, config=config, include_default_demo=False)
    records = []
    def observe(receipt):
        path = Path(receipt["receipt_path"])
        path.resolve().relative_to(root.resolve())
        require(json.loads(path.read_text(encoding="utf8")) == receipt and receipt["simulation"] is False,
                "real stdio broker receipt differs from durable bytes or labelled simulation")
        records.append({"status": receipt["status"], "ok": receipt["ok"], "receiptPath": str(path)})
        return receipt
    try:
        found = broker.search("note", limit=10)
        require({r["name"] for r in found} == {"read_note", "write_note"} and all("inputSchema" not in r for r in found),
                "real stdio discovered catalog or schema deferral differs")
        describe = broker.describe("notes", "write_note")
        require(describe["inputSchema"]["required"] == ["note"] and describe["requiresApproval"]
                and describe["description"] == metadata.read_text(encoding="utf8"), "selected real mutating schema/metadata lost authority or text")
        servers = {r["name"]: r for r in broker.list_servers()}
        require(servers["notes"]["callable"] and not servers["sse"]["callable"], "stdio/SSE truthful capability differs")
        if identity == "runtime.mcp.host":
            from .neyvia_mcp import NeyviaMCPServer
            from .proof_credential_guard import prepare_broker_fixture
            host_root = root / "host"; host_root.mkdir()
            prepare_broker_fixture(host_root)
            host_config = host_root / ".agent_control/mcp_broker.json"
            host_config.parent.mkdir(parents=True, exist_ok=True); host_config.write_text(json.dumps(config), encoding="utf8")
            old = os.environ.get("NEYVIA_MCP_BROKER_CONFIG")
            os.environ["NEYVIA_MCP_BROKER_CONFIG"] = str(host_config)
            host = None
            try:
                host = NeyviaMCPServer(host_root)
                listed = host.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"includeSchemas": False}})
                rows = [r for r in listed["result"]["tools"] if r["name"].startswith("mcp.")]
                require(rows and all("inputSchema" not in r for r in rows), "host progressive catalog schema deferral differs")
                result = host.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "mcp.call", "arguments": {"server": "notes", "tool": "write_note", "arguments": {"note": TEXT.get(category, "blocked")}}}})["result"]
                require(result["isError"] and result["structuredContent"]["status"] == "approval_required" and note.read_text(encoding="utf8") == "keeper", "host mutation bypassed approval")
                if category == "concurrency":
                    def host_read(index):
                        request_id = f"parallel-{index}"
                        value = host.handle({"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "mcp.call", "arguments": {"server": "notes", "tool": "read_note", "arguments": {}}}})
                        require(value["id"] == request_id and not value["result"]["isError"]
                                and value["result"]["structuredContent"]["result"]["structuredContent"]["note"] == "keeper",
                                "concurrent MCP host call lost request/receipt/value identity")
                        return value
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        parallel = list(pool.map(host_read, range(8)))
                    require(len({row["id"] for row in parallel}) == 8, "concurrent host replies reused request identity")
                    return {"hostRequests": 11, "parallelCalls": 8, "blockedMutation": True, "providerExecution": False}
                if category in {"interrupted", "offline", "stale"}:
                    state = host.mcp_broker._servers["notes"]
                    if category == "interrupted":
                        interrupted = host.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mcp.call", "arguments": {"server": "notes", "tool": "write_note", "arguments": {"note": "exit-after-effect"}, "approved": True}}})
                        payload = interrupted.get("result", {}).get("structuredContent", {})
                        require(interrupted["id"] == 4 and interrupted["result"]["isError"] and payload["status"] == "failed"
                                and note.read_text(encoding="utf8") == "exit-after-effect"
                                and Path(payload["receipt_path"]).is_file(), "interrupted host call hid committed bytes or lacked a failed durable receipt")
                        return {"hostRequests": 4, "effectPersistedBeforeExit": True, "uncertainReply": True,
                                "receiptPath": payload["receipt_path"]}
                    if category == "offline":
                        state._transport_impl.close()
                        worker.rename(root / "host-unavailable-mcp.py")
                    if category == "stale":
                        host.mcp_broker.set_auth_state("notes", "unauthenticated")
                    failed = host.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "mcp.call", "arguments": {"server": "notes", "tool": "read_note", "arguments": {}}}})
                    require(failed["id"] == 4 and ("error" in failed or failed.get("result", {}).get("isError"))
                            and note.read_text(encoding="utf8") == "keeper", "unavailable/stale MCP peer claimed success or changed owned bytes: " + repr(failed)[:500])
                    if category == "stale":
                        payload = failed["result"]["structuredContent"]
                        require(payload["status"] == "auth_required", "stale host credentials did not receive an explicit fresh authorization refusal")
                    return {"hostRequests": 4, "peerAvailable": False, "preservedNote": True, "category": category}
                observed = host.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "mcp.call", "arguments": {"name": "mcp.notes.read_note", "arguments": {}}}})["result"]
                require(not observed["isError"] and observed["structuredContent"]["result"]["structuredContent"]["note"] == "keeper", "qualified host stdio call did not observe actual bytes")
                return {"hostRequests": 3, "stdioCalls": 1, "blockedMutation": True, "providerExecution": False}
            finally:
                if host:
                    host.mcp_broker.close()
                    if getattr(host.capability_os, "_model_tool_broker", None):
                        host.capability_os._model_tool_broker.close()
                if old is None: os.environ.pop("NEYVIA_MCP_BROKER_CONFIG", None)
                else: os.environ["NEYVIA_MCP_BROKER_CONFIG"] = old
        denied = observe(broker.call("notes", "write_note", {"note": "blocked"}))
        require(denied["status"] == "approval_required" and note.read_text(encoding="utf8") == "keeper", "unapproved stdio write changed keeper")
        broker.set_auth_state("notes", "unauthenticated")
        locked = observe(broker.call("notes", "read_note", {}))
        require(locked["status"] == "auth_required" and not locked["ok"], "auth revoked observer still dispatched")
        broker.set_auth_state("notes", "authenticated")
        surface = ProgressiveToolSurface()
        names = register_with_progressive_surface(surface, broker)
        require(set(names) == {"mcp.servers", "mcp.search", "mcp.describe", "mcp.call"}, "progressive broker registration differs")
        def call(tool, args, **options):
            if identity == "runtime.mcp.progressive":
                return surface.call("mcp.call", {"server": "notes", "tool": tool, "arguments": args, **options})
            return broker.call("notes", tool, args, **options)
        progressive_denied = observe(surface.call("mcp.call", {"server": "notes", "tool": "write_note", "arguments": {"note": "denied"}}))
        require(progressive_denied["status"] == "approval_required" and note.read_text(encoding="utf8") == "keeper", "progressive call bypassed broker authority")
        if category == "interrupted":
            result = observe(call("write_note", {"note": "exit-after-effect"}, approved=True))
            require(not result["ok"] and result["status"] == "failed" and note.read_text(encoding="utf8") == "exit-after-effect", "lost reply hid actual effect or claimed completion")
            require(not broker._servers["notes"].verified, "interrupted peer retained verified availability")
            return {"effectPersistedBeforeExit": True, "uncertainReply": True, "receipts": records}
        if category == "offline":
            state = broker._servers["notes"]
            state._transport_impl.close()
            # Remove only our generated peer; production transport sees a real
            # process-launch failure rather than a stubbed connection outcome.
            worker.rename(root / "unavailable_mcp.py")
            result = observe(call("read_note", {}))
            require(not result["ok"] and result["status"] == "failed" and note.read_text(encoding="utf8") == "keeper", "missing stdio peer claimed an observation or changed keeper")
            return {"peerAvailable": False, "receipts": records}
        literal = TEXT.get(category, "owned " + category)
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda _: call("read_note", {}), range(8)))
            for value in values:
                observe(value)
                require(value["ok"] and value["result"]["structuredContent"]["note"] == "keeper", "parallel stdio read lost response identity/value")
            require(len({v["receipt_id"] for v in values}) == 8, "parallel stdio receipts reused identity")
            with ThreadPoolExecutor(max_workers=4) as pool:
                catalogs = list(pool.map(lambda _: broker.search("", limit=10), range(8)))
            require(all({r["name"] for r in rows} == {"read_note", "write_note"} and all("inputSchema" not in r for r in rows) for rows in catalogs), "parallel catalog observers changed identity or schema deferral")
        else:
            allowed = observe(broker.call("notes", "write_note", {"note": literal}, approved=True, approval_id="owned-approval"))
            require(allowed["ok"] and note.read_bytes() == literal.encode(), "approved real stdio write changed exact payload bytes")
        result = observe(surface.call("mcp.call", {"server": "notes", "tool": "read_note", "arguments": {}}))
        require(result["ok"] and result["result"]["structuredContent"]["note"] == note.read_text(encoding="utf8"), "progressive call did not reach actual stdio peer")
        return {"receipts": records, "transport": "actual Content-Length stdio child", "providerExecution": False}
    finally:
        broker.close()


def _audit(root, category, identity):
    from .native_proof_audit import NativeProofAuditor
    from .edge_fixture_native import _sharing_denied
    root = root / "workspace"; root.mkdir()
    source = root / "owned.txt"; source.write_text("before", encoding="utf8")
    script = root / "scripts/verify_proofs.py"; script.parent.mkdir()
    exit_code = 7 if identity.endswith("failure-gate") else 23 if category == "interrupted" else 0
    text = TEXT.get(category, "owned " + category)
    program = "import sys\nprint(" + repr(text) + ")\nsys.exit(" + str(exit_code) + ")\n"
    if category == "stale":
        program = "from pathlib import Path\nPath('owned.txt').write_text('changed while verifier ran',encoding='utf8')\n" + program
    script.write_text(program, encoding="utf8")
    auditor = NativeProofAuditor(root)
    before = auditor.snapshot()
    source.write_text("after " + text, encoding="utf8")
    plan = {"capsule": {"mutationExpected": True, "proofGates": ["deterministic_check"]}}
    def check():
        return auditor.audit(before=before, behavior_plan=plan, allow_mutations=True)
    if category == "permissions":
        with _sharing_denied(script):
            result = check()
        require(result["status"] == "blocked" and result["verification"]["passed"] is False, "sharing-denied actual proof execution claimed success")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: check(), range(8)))
        require(all(r["status"] == ("blocked" if exit_code else "verified") and r["workspaceDelta"]["modified"] == ["owned.txt"] for r in results),
                "parallel audit observers changed proof verdict or exact workspace delta")
        result = results[0]
    else:
        result = check()
        expected = "blocked" if exit_code or category == "stale" else "verified"
        require(result["status"] == expected and result["runStatus"] == ("blocked" if expected == "blocked" else "completed"), "audit completion does not reflect actual failed/stale proof subprocess")
    require(result["workspaceDelta"]["modified"] == ["owned.txt"] and result["selectedVerification"]["argv"] == [sys.executable, str(script), "--root", str(root)],
            "automatic manual-proof discovery changed exact argv or supplied worktree delta")
    require(result["verification"]["returnCode"] != 0 if category == "permissions" else result["verification"]["returnCode"] == exit_code,
            "audit changed actual owned process exit status")
    if identity.endswith("delta"):
        unchanged = auditor.audit(before=auditor.snapshot(), behavior_plan={"capsule": {"mutationExpected": True}}, allow_mutations=True)
        require(unchanged["status"] == "blocked" and not unchanged["workspaceDelta"]["changed"], "absent requested delta was accepted")
    return {"actualExitCode": result["verification"]["returnCode"], "status": result["status"],
            "modified": ["owned.txt"], "subprocesses": 8 if category == "concurrency" else 1,
            "freshSeal": result["finalWorkspaceFingerprintFresh"], "renderedProof": False}


def _imports(root, category, identity):
    from . import context_import as c
    from .neyvia_runtime_invocation import build_selected_context_packet
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned " + category)
    if identity == "control.import-upload":
        if category == "empty":
            error = refusal(lambda: c.stage_upload(root, filename="owned.json", chunks=[]))
            require(not list((root / c._STAGED_UPLOADS_RELATIVE).glob("*/receipt.json")), "empty upload issued durable receipt")
            return {"refusal": error, "successfulUploads": 0}
        data = json.dumps([{"id": "u", "role": "user", "content": literal}], ensure_ascii=False).encode()
        def upload(_):
            receipt = c.stage_upload(root, filename="../../owned-é›ª.json", chunks=[data[:13], data[13:]])
            content = root / c._STAGED_UPLOADS_RELATIVE / receipt["uploadId"] / "content"
            require(content.read_bytes() == data and receipt["sizeBytes"] == len(data)
                    and receipt["sha256"] == hashlib.sha256(data).hexdigest(), "upload committed changed bytes/hash/count")
            return receipt
        if category == "permissions":
            source = root / "selected.json"; source.write_bytes(data)
            def chunks():
                yield b"prefix"
                yield source.read_bytes()
            with _sharing_denied(source):
                error = refusal(lambda: c.stage_upload(root, filename="owned.json", chunks=chunks()))
            require(not list((root / c._STAGED_UPLOADS_RELATIVE).glob("*/receipt.json")) and source.read_bytes() == data,
                    "source read refusal issued upload receipt or changed selected bytes")
            return {"refusal": error, "successfulUploads": 0}
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                receipts = list(pool.map(upload, range(8)))
            require(len({r["uploadId"] for r in receipts}) == 8, "simultaneous uploads reused durable identity")
            return {"uploads": 8, "bytesEach": len(data)}
        receipt = upload(0)
        return {"uploads": 1, "bytesEach": len(data), "sourceSha256": receipt["sha256"]}
    source = root / "explicit-rollout.jsonl"
    rows = [{"type": "response_item", "timestamp": "2026-10-04T00:00:00Z", "payload": {"type": "message", "id": "u", "role": "user", "content": "owned " + literal}},
            {"type": "response_item", "payload": {"type": "message", "id": "excluded", "role": "assistant", "content": "excluded"}},
            {"type": "response_item", "payload": {"type": "message", "id": "private", "role": "developer", "content": "do-not-import"}}]
    source.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    if category == "empty":
        if identity == "control.import-preview":
            source.write_text("", encoding="utf8")
            empty = c.preview_export("codex", source)
            require(empty["items"] == [] and empty["counts"]["available"] == 0 and empty["requiresExplicitSelection"], "empty preview manufactured content")
            return {"available": 0}
        if identity == "control.import-selection":
            error = refusal(lambda: c.import_selection(root, provider="codex", export_path=source, selected_item_ids=[]))
            require(not (root / c._IMPORTS_RELATIVE).exists(), "empty selection issued import")
            return {"refusal": error}
        if identity == "control.import-read":
            return {"refusal": refusal(lambda: c.read_import_selection(root, ""))}
        if identity == "control.import-packet":
            packet = build_selected_context_packet([], root=root)
            require(packet["selected"] == [] and packet["itemCount"] == 0, "empty selection packet manufactured context")
            return {"selected": 0}
    preview = c.preview_export("codex", source)
    require([r["itemId"] for r in preview["items"]] == ["u", "excluded"] and preview["items"][0]["content"] == "owned " + literal,
            "preview changed transcript text, role filtering or selected identity")
    original_sha = preview["source"]["sha256"]
    def selected():
        receipt = c.import_selection(root, provider="codex", export_path=source, selected_item_ids=["u"], expected_sha256=original_sha)
        loaded = c.read_import_selection(root, receipt["importId"])
        require(len(loaded["items"]) == 1 and loaded["items"][0]["content"] == "owned " + literal
                and loaded["items"][0]["sourceSha256"] == original_sha and loaded["items"][0]["sourceItemId"] == "u", "durable selection changed exact content/scope/provenance")
        return receipt
    if identity in {"control.import-preview", "control.import-selection"} and category == "permissions":
        before = source.read_bytes()
        with _sharing_denied(source):
            error = refusal(lambda: c.preview_export("codex", source) if identity.endswith("preview") else selected())
        require(source.read_bytes() == before and not (root / c._IMPORTS_RELATIVE).exists(), "denied source changed data or issued an import")
        return {"refusal": error}
    if identity == "control.import-selection" and category == "stale":
        source.write_text(source.read_text(encoding="utf8") + "\n", encoding="utf8")
        before = source.read_bytes()
        error = refusal(selected)
        require(source.read_bytes() == before and not (root / c._IMPORTS_RELATIVE).exists(), "stale preview source imported or changed newer bytes")
        return {"refusal": error, "observedSha256": original_sha}
    if identity == "control.import-preview" and category == "stale":
        data = source.read_bytes()
        upload = c.stage_upload(root, filename="owned.jsonl", chunks=[data])
        content = root / c._STAGED_UPLOADS_RELATIVE / upload["uploadId"] / "content"
        content.write_bytes(data + b"changed")
        error = refusal(lambda: c.preview_export("codex", root=root, staged_upload_id=upload["uploadId"]))
        return {"refusal": error, "changedUploadBytesPreserved": content.read_bytes() == data + b"changed"}
    receipt = selected(); content = Path(receipt["contentPath"])
    def observe():
        if identity == "control.import-preview":
            return c.preview_export("codex", source)
        if identity == "control.import-selection":
            return selected()
        if identity == "control.import-read":
            return c.read_import_selection(root, receipt["importId"])
        packet = build_selected_context_packet([{"importId": receipt["importId"]}], root=root, max_items=1, max_chars=12000)
        bounded = ("owned " + literal).strip()[:12000]
        require(packet["itemCount"] == 1 and packet["selected"][0]["content"] == bounded
                and packet["sourceSha256"] == original_sha and packet["importIds"] == [receipt["importId"]], "bounded selected packet lost lineage or exact selected prefix")
        return packet
    if category == "permissions":
        before = content.read_bytes()
        with _sharing_denied(content):
            error = refusal(observe)
        require(content.read_bytes() == before, "denied selected-content read changed import bytes")
        return {"refusal": error}
    if category == "stale":
        content.write_text(content.read_text(encoding="utf8") + content.read_text(encoding="utf8"), encoding="utf8")
        before = content.read_bytes()
        error = refusal(observe)
        require(content.read_bytes() == before, "invalid duplicate import read repaired or changed content")
        return {"refusal": error, "duplicateRowsRefused": True}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: observe(), range(8)))
        if identity.endswith("selection"):
            require(len({r["importId"] for r in values}) == 8, "simultaneous exact selections reused import identity")
        else:
            require(values == [values[0]] * 8, "parallel selected-context observations diverged")
        return {"observations": 8, "sourceSha256": original_sha}
    observe()
    return {"sourceSha256": original_sha, "importedItems": 1, "excludedItems": 1, "networkCalls": 0}


def _native_store_denial(root, category, identity):
    import sqlite3
    from .edge_fixture_native import _sharing_denied
    def snapshot(path):
        db = sqlite3.connect(path)
        try:
            return {table: sorted(db.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
    if identity.startswith("native.goals."):
        from .native_goals import NativeGoalStore
        store = NativeGoalStore(root)
        goal = store.create("owned", goal_id="owned", schedule_seconds=60)
        receipt = root / "completion.json"; receipt.write_text('{"status":"completed"}', encoding="utf8")
        with store.connection() as db:
            db.execute("UPDATE native_goals SET next_due_at='2000-01-01T00:00:00Z' WHERE goal_id='owned'")
        before = snapshot(store.path)
        if identity.endswith("complete"):
            action = lambda: store.complete("owned", str(receipt))
        elif identity.endswith("due"):
            action = store.due
        else:
            action = lambda: store.heartbeat("owned", next_action="refused")
    elif identity.startswith("native.pairing."):
        from .native_pairing import NativePairingStore
        store = NativePairingStore(root)
        pair = store.create("phone", scopes=["device.commands"])
        before = snapshot(store.path)
        action = lambda: store.redeem(pair["pairingId"], pair["pairingToken"], "owned")
    else:
        from .native_learning import NativeLearningStore
        store = NativeLearningStore(root)
        before = snapshot(store.path)
        action = lambda: store.recommend("owned", minimum_samples=1)
    with _sharing_denied(store.path):
        error = refusal(action, (sqlite3.Error, OSError, RuntimeError, ValueError))
    require(snapshot(store.path) == before, "OS-denied Native store operation changed unrelated or selected durable rows")
    return {"refusal": error, "durableTablesPreserved": len(before), "networkCalls": 0}


def _memory_existing(root, category, identity):
    from .edge_fixture_control_remaining import _memory as observe
    observe(root, category, identity)
    return {"exactOrderedRowsAndReopenedBytes": True, "existingFamilyBuilder": True, "networkCalls": 0}


def _broker_reads(root, category, identity):
    from .edge_fixture_providers import _adapter_read
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.broker import ConnectedBroker, TOOL_OUTPUT_PAGE_CHARS, FULL_TOOL_OUTPUT_CHARS
    from .connected_sessions.registry import ConnectedError
    from .connected_sessions.claude_items import image_token
    from .external_chat_inventory import _host
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    _adapter_read(root, category if category in TEXT else "unicode")
    config = root / "owned-config"; path = config / "projects/owned-project/owned-session.jsonl"
    original = json.loads(path.read_text(encoding="utf8").splitlines()[0])
    encoded_image = original["message"]["content"][1]["source"]["data"]
    image = base64.b64decode(encoded_image); token = image_token("image/png", encoded_image)
    literal = TEXT.get(category, "owned full tool output é›ª")
    rows = [{"type": "assistant", "uuid": "owned-tool-start", "sessionId": "owned-session", "timestamp": "2026-10-04T12:03:00Z",
             "message": {"id": "owned-tool-message", "content": [{"type": "tool_use", "id": "owned-tool", "name": "Read", "input": {"file_path": "owned.txt"}}]}},
            {"type": "user", "uuid": "owned-tool-result", "sessionId": "owned-session", "timestamp": "2026-10-04T12:04:00Z",
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "owned-tool", "content": literal}]}}]
    with path.open("a", encoding="utf8") as stream:
        for row in rows: stream.write(json.dumps(row, ensure_ascii=True) + "\n")
    before = path.read_bytes()
    adapter = ClaudeAdapter(state_root=root, config_dir=config, cli_path=[sys.executable, str(root / "inventory-peer.py")],
                            host=_host(), context_probe=False)
    broker = ConnectedBroker(root, adapters={"claude-code": adapter}, load_defaults=False, autostart=False)
    # The registry and adapter are production owners on an explicitly selected
    # generated transcript. No installed provider or backend handler is replaced.
    from .connected_sessions.registry import make_session_id
    sid = make_session_id("claude-code", broker.host["deviceId"], "owned-session")
    with environment(NEYVIA_UI_STATE_ROOT=str(root)):
        try:
            def observe():
                if identity.endswith("catalogue"):
                    result = broker.list_sessions(app="claude-code", force=True, include_harness=True, observe=False)
                    if category == "concurrency" and result["total"] == 0:
                        source = next(row for row in result["sources"] if row["app"] == "claude-code")
                        require(result["sessions"] == [] and source["available"] is False
                                and "earlier request" in source["reason"], "parallel inventory omission lacked its actual bounded adapter-busy refusal")
                        return result
                    require(result["total"] == len(result["sessions"]) == 1 and result["sessions"][0]["id"] == sid
                            and result["sessions"][0]["cwd"] == str(root), "broker inventory lost exact selected adapter/source identity or inserted another source")
                    return result
                if identity.endswith("media"):
                    value = broker.media(sid, token)
                    require(value[:2] == (image, "image/png"), "broker media changed source decoded bytes/type")
                    refusal(lambda: broker.media(sid, "../outside"), (ConnectedError,))
                    return value
                page = broker.read(sid, limit=200)
                tools = [item for item in page["items"] if item["kind"] == "tool" and item["data"]["name"] == "Read"]
                require(len(tools) == 1 and tools[0]["data"]["output"] == literal[:TOOL_OUTPUT_PAGE_CHARS]
                        and [row["seq"] for row in page["items"]] == sorted(row["seq"] for row in page["items"])
                        and page["run"] is None, "broker page lost ordered real source/tool content or fabricated running owner")
                full = broker.tool_output(sid, tools[0]["id"])
                require(full == {"itemId": tools[0]["id"], "output": literal[:FULL_TOOL_OUTPUT_CHARS], "truncated": len(literal) > FULL_TOOL_OUTPUT_CHARS},
                        "broker full tool output differs from exact original source result")
                return page
            if category == "interrupted":
                command = """import os,sys,json
from pathlib import Path
from grant_agent.connected_sessions.claude import ClaudeAdapter
from grant_agent.connected_sessions.broker import ConnectedBroker
from grant_agent.external_chat_inventory import _host
r=Path(sys.argv[1]);a=ClaudeAdapter(state_root=r,config_dir=r/'owned-config',cli_path=[sys.executable,str(r/'inventory-peer.py')],host=_host(),context_probe=False)
b=ConnectedBroker(r,adapters={'claude-code':a},load_defaults=False,autostart=False)
v=b.list_sessions(app='claude-code',force=True,include_harness=True,observe=False)
print(json.dumps({'total':v['total'],'id':v['sessions'][0]['id'],'updatedAt':v['sessions'][0]['updated_at']}),flush=True)
os._exit(23)
"""
                process = _run_child([sys.executable, "-c", command, str(root)], capture_output=True, text=True, encoding="utf8", timeout=45)
                require(process.returncode == 23, "actual catalogue caller did not exit after its completed baseline write: " + process.stderr[-2000:])
                value = json.loads(process.stdout)
                from .connected_sessions.seen import SeenStore
                reopened = SeenStore(root)
                require(value["total"] == 1 and value["id"] == sid
                        and reopened.get(sid)["updatedAt"] == value["updatedAt"]
                        and reopened.unread(sid, value["updatedAt"]) is False
                        and path.read_bytes() == before, "catalogue caller exit lost its committed exact source baseline or changed transcript")
                return {"callerExit": 23, "durableBaselineReopened": True, "providerExecution": False}
            if category == "permissions":
                with _sharing_denied(path):
                    if identity.endswith("catalogue"):
                        result = broker.list_sessions(app="claude-code", force=True, include_harness=True, observe=False)
                        require(result["total"] == 0 and result["sessions"] == [], "unreadable selected transcript advertised fabricated session summary")
                        error = {"unreadableSourceOmitted": True}
                    else:
                        error = refusal(observe, (ConnectedError, OSError))
                require(path.read_bytes() == before, "OS-denied broker read changed selected transcript bytes")
                return {"refusalOrOmission": error, "providerExecution": False}
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
                if identity.endswith("media"): require(values == [values[0]] * 8, "parallel broker media changed same selected source bytes")
                elif identity.endswith("read"): require([value["items"] for value in values] == [values[0]["items"]] * 8, "parallel broker pages changed observed source order/content")
                else: require(any(value["sessions"] for value in values) and all(not value["sessions"] or value["sessions"][0]["id"] == sid for value in values), "parallel inventory readers changed session owner or completed no actual inventory")
            elif category == "stale":
                observe()
                replacement = {"type": "user", "uuid": "new-current", "sessionId": "owned-session", "timestamp": "2026-10-04T12:10:00Z", "cwd": str(root),
                               "message": {"role": "user", "content": "New current transcript generation"}}
                path.write_text(json.dumps(replacement) + "\n", encoding="utf8")
                if identity.endswith("media"):
                    refusal(lambda: broker.media(sid, token), (ConnectedError,))
                elif identity.endswith("catalogue"):
                    fresh = broker.list_sessions(app="claude-code", force=True, include_harness=True, observe=False)
                    require(fresh["sessions"][0]["title"] == "New current transcript generation", "fresh broker inventory retained prior transcript title")
                else:
                    fresh = broker.read(sid)
                    require([item["id"] for item in fresh["items"]] == ["new-current"] and fresh["items"][0]["data"]["text"] == replacement["message"]["content"], "fresh broker page replayed old generation after selected source replacement")
            else:
                observe()
            require(category == "stale" or path.read_bytes() == before, "broker source observation changed original selected transcript")
            return {"selectedSourceBytes": len(before), "realBrokerAndAdapter": True, "providerExecution": False, "networkCalls": 0}
        finally:
            broker.close()


def _plugin_skills(root, category, identity):
    import importlib.util
    from .proofs_a_cli import check_plugin_skills
    from .edge_fixture_native import _sharing_denied
    script = Path(__file__).resolve().parents[2] / "scripts/build_claude_plugin_skills.py"
    spec = importlib.util.spec_from_file_location("c7d_owned_plugin_skill_builder", script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    literal = TEXT.get(category, "owned plugin manual description é›ª")
    manuals = {} if category == "empty" else {"owned-" + str(index): ("docs/manuals/neyvia.md", literal) for index in range(32 if category == "huge" else 1)}
    expected = {}
    for name, (manual, description) in manuals.items():
        text = module.render(name, manual, description)
        path = root / name / "SKILL.md"; path.parent.mkdir(); path.write_text(text, encoding="utf8", newline="\n")
        expected[path] = path.read_bytes()
        require("description: " + json.dumps(description) in text and name in text and "help(" in text,
                "actual plugin renderer lost supplied name/description or CL instruction index")
    def observe():
        check_plugin_skills(manuals, root, module.render)
    if category == "permissions":
        with _sharing_denied(next(iter(expected))): refusal(observe, (OSError, ValueError))
    elif category == "stale":
        path = next(iter(expected)); path.write_text("old mismatched skill generation", encoding="utf8")
        refusal(observe, (ValueError,))
        path.write_bytes(expected[path]); observe()
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda _: observe(), range(8)))
    else:
        observe()
    require(all(path.read_bytes() == value for path, value in expected.items()), "manual skill checker changed selected generated source bytes")
    return {"actualRenderedSkillsChecked": len(manuals), "pluginProcessesLaunched": 0, "renderedUiClaim": False}


def _first_run_state(root, category, identity):
    from . import progressive_setup as setup
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned setup completion é›ª")
    patch = {"goals": ["software", literal, "research"], "completedItemIds": [literal, "owned", "owned"], "skippedRuntimeIds": [literal], "permissionsReviewed": True}
    path = setup._state_path(root)
    expected = {"schema": setup.FIRST_RUN_SCHEMA, "goals": ["software", "research"], "completedItemIds": sorted({literal, "owned"} - {""}), "skippedRuntimeIds": [literal] if literal.strip() else [], "permissionsReviewed": True}
    def observe():
        value = setup.update_first_run_state(root, patch)
        require(value == expected and setup.load_first_run_state(root) == expected
                and json.loads(path.read_text(encoding="utf8")) == expected, "first-run selected choices differ from exact filtered durable state")
        return value
    if category == "concurrency":
        setup.update_first_run_state(root, {})
        original = setup.load_first_run_state
        def paced_load(selected):
            value = original(selected)
            # Delay only scheduling after the real read; never replace a value.
            time.sleep(.05)
            return value
        setup.load_first_run_state = paced_load
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(setup.update_first_run_state, root, part) for part in ({"permissionsReviewed": True}, {"completedItemIds": [literal]})]
                for future in futures: future.result()
        finally:
            setup.load_first_run_state = original
        fresh = original(root)
        require(fresh["permissionsReviewed"] is True and fresh["completedItemIds"] == [literal], "parallel disjoint first-run patches lost an independently supplied saved choice")
    elif category == "permissions":
        observe(); before = path.read_bytes()
        with _sharing_denied(path): refusal(lambda: setup.update_first_run_state(root, {"permissionsReviewed": False}), (OSError,))
        require(path.read_bytes() == before, "OS-denied setup mutation changed saved choices")
    elif category == "stale":
        observe(); path.write_text(json.dumps({**expected, "permissionsReviewed": False, "completedItemIds": ["new-selected"]}), encoding="utf8")
        current = setup.update_first_run_state(root, {"goals": ["writing"]})
        require(current["goals"] == ["writing"] and current["completedItemIds"] == ["new-selected"] and current["permissionsReviewed"] is False,
                "fresh setup patch overwrote an independently changed current generation")
    elif category == "interrupted":
        argument = root / "patch.json"; argument.write_text(json.dumps(patch), encoding="utf8")
        command = "import os,sys,json;from grant_agent.progressive_setup import update_first_run_state;update_first_run_state(sys.argv[1],json.load(open(sys.argv[2],encoding='utf8')));os._exit(23)"
        process = _run_child([sys.executable, "-c", command, str(root), str(argument)], capture_output=True, text=True, encoding="utf8", timeout=20)
        require(process.returncode == 23 and setup.load_first_run_state(root) == expected, "actual setup caller exit lost completed saved choices: " + process.stderr[-1000:])
    else:
        observe()
    return {"savedChoices": True, "setupOnly": True, "providerOrBrowserExecution": False}


def _crash_completion(root, category, identity):
    from .crashproof import CrashProofStore
    store = CrashProofStore(root); now = "2026-10-04T12:00:00Z"
    if identity.endswith("autonomy"):
        actions = ["owned." + str(index) for index in range(10000 if category == "huge" else 2)]
        policy = {"allowedActions": actions, "allowedRoots": [str(root / "allowed")], "maxSpend": 0}
        parent = store.create_autonomy_lease(mission_id="owned", policy=policy, duration_seconds=120, now=now)
        child = store.create_autonomy_lease(mission_id="owned", policy={"allowedActions": ["*"]}, duration_seconds=60, parent_lease_id=parent["leaseId"], now=now)
        def observe():
            for action, context, expected in ((actions[-1], {"path": str(root / "allowed/out")}, True),
                                             ("outside-action", {}, False), (actions[0], {"path": str(root / "outside")}, False),
                                             (actions[0], {"spend": 1}, False), (actions[0], {"destructive": True}, False),
                                             (actions[0], {"publicCommunication": True}, False)):
                require(store.autonomy_allows(child["leaseId"], action=action, context=context, now=now)["allowed"] is expected, "actual inherited autonomy lease escaped root/action/spend/destructive/public scope")
            return store.autonomy_allows(child["leaseId"], action=actions[-1], now=now)
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
            require(all(value["allowed"] for value in values), "parallel inherited grant readers changed current active decision")
        else: observe()
        store.revoke_autonomy_lease(parent["leaseId"], now=now)
        require(not CrashProofStore(root).autonomy_allows(child["leaseId"], action=actions[-1], now=now)["allowed"], "fresh child grant escaped durable parent revocation")
        return {"actualAllowedActionCount": len(actions), "inheritedScopeBoundaries": 6, "actionsExecuted": 0}
    task = store.submit_task(mission_id="owned", kind="local", idempotency_key="owned", payload={"literal": "owned"}, now=now)
    if identity.endswith("recover"):
        store.claim_next(worker_id="owned", lease_seconds=1, now=now)
        with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: CrashProofStore(root).recover_interrupted(now="2026-10-04T12:02:00Z"), range(8)))
        require([tid for value in values for tid in value] == [task["taskId"]]
                and len([event for event in store.task_events(task["taskId"]) if event["kind"] == "recovered.interrupted"]) == 1
                and store.get_task(task["taskId"])["status"] == "queued", "parallel crash recovery repeated one actual transition/event or lost durable queue state")
        return {"competingRecoveryCalls": 8, "actualRecoveredTasks": 1}
    if identity.endswith("transition"):
        store.claim_next(worker_id="owned", now=now)
        def transition(status):
            try: return CrashProofStore(root).transition_task(task["taskId"], status, result={"status": status}, now=now)
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=2) as pool: values = list(pool.map(transition, ("completed", "cancelled")))
        success = [value for value in values if value]
        fresh = store.get_task(task["taskId"])
        require(len(success) == 1 and fresh["status"] == success[0]["status"] and fresh["result"] == {"status": fresh["status"]}
                and fresh["workerId"] is None and fresh["leaseUntil"] is None, "competing incompatible terminal transitions both won or lost exact terminal effect")
        refusal(lambda: store.transition_task(task["taskId"], "working"), (ValueError,))
        return {"competingTerminalTransitions": 2, "terminalOwners": 1}
    result = store.create_result_set(mission_id="owned", kind="local")
    command = """import os,sys
from grant_agent.crashproof import CrashProofStore
s=CrashProofStore(sys.argv[1])
if sys.argv[2]=='submit': s.submit_task(mission_id='owned',kind='local',idempotency_key='after-exit',payload={'literal':'committed-after-exit'})
else: s.add_result_item(sys.argv[3],payload={'literal':'committed-after-exit'},dedupe_key='after-exit')
os._exit(23)
"""
    suffix = identity.rsplit(".", 1)[-1]
    process = _run_child([sys.executable, "-c", command, str(root), suffix, result["resultSetId"]], capture_output=True, text=True, encoding="utf8", timeout=20)
    reopened = CrashProofStore(root)
    require(process.returncode == 23, "actual crash-store caller failed before its committed write: " + process.stderr[-1000:])
    if suffix == "submit":
        rows = reopened.list_tasks(); require(len(rows) == 2 and any(row["idempotencyKey"] == "after-exit" and row["payload"] == {"literal": "committed-after-exit"} for row in rows), "actual submitting caller exit lost committed exact task identity/payload")
    else:
        summary = reopened.summarize_result_set(result["resultSetId"])
        require(summary["total"] == 1 and summary["samples"][0]["payload"] == {"literal": "committed-after-exit"}, "actual result caller exit lost selected committed result item")
    return {"actualCallerExit": 23, "committedEffectReopened": True}


def _mission_queue(root, category, identity):
    import sqlite3
    from . import cli
    from .mission_control import ControlRoomStore
    from .cluster import ClusterRegistry
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, FLUXIO_MISSION_DISPATCH_MODE="cluster_worker",
                     FLUXIO_MISSION_WORKER_HOST_ID="c7d-queue-owner", FLUXIO_WORKSPACE_MAPPINGS=None):
        store = ControlRoomStore(root); workspace = store.load_workspaces()[0]
        mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="local-owned", objective="Implement owned local feature",
                                       success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=0)
        if category == "empty" and identity.endswith("queue"): workspace.root_path = ""
        elif category in TEXT:
            workspace.name = TEXT[category]
            workspace.root_path = str(root / ("é›ª" if category == "unicode" else "selected-" * 10 if category == "huge" else "selected"))
        store.save_workspaces([workspace])
        registry = ClusterRegistry(root, use_configured_root=False)
        def observe():
            value = cli._queue_cluster_mission_resume(root, mission=mission, workspace=workspace) if identity.endswith("queue") else cli._launch_async_mission_resume(root, mission.mission_id)
            row = registry.get_job(value["jobId"]); payload = row["payload"]
            require(row["missionId"] == mission.mission_id and row["jobKind"] == "mission_resume" and row["status"] in {"queued", "leased", "running"}
                    and payload["controlProjectRoot"] == payload["executionRoot"] == str(root) and payload["workspaceRoot"] == workspace.root_path
                    and payload["command"][payload["command"].index("--root") + 1] == str(root) and payload["dispatchSource"] == "composer_arrow",
                    "actual queued resume lost exact mission/authoritative root/workspace/command binding")
            return value
        if category == "permissions":
            with registry._connect() as db: before = [dict(row) for row in db.execute("SELECT * FROM jobs")]
            with _sharing_denied(registry.db_path): refusal(observe, (sqlite3.Error, OSError))
            with registry._connect() as db: require([dict(row) for row in db.execute("SELECT * FROM jobs")] == before, "OS-denied resume queue changed durable job rows")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
            require(len({value["jobId"] for value in values}) == 1 and len(registry.list_jobs()) == 1,
                    "parallel mission resume calls queued duplicate active ownership for one mission")
        elif category == "stale":
            previous = observe()
            with registry._connect() as db: db.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (previous["jobId"],))
            workspace.root_path = str(root / "new-current-workspace"); store.save_workspaces([workspace])
            current = observe()
            require(current["jobId"] != previous["jobId"], "completed old resume job suppressed a fresh current queue generation")
        elif category == "interrupted":
            program = """import os,sys
from pathlib import Path
from grant_agent.cli import _queue_cluster_mission_resume,_launch_async_mission_resume
from grant_agent.mission_control import ControlRoomStore
r=Path(sys.argv[1]);s=ControlRoomStore(r);m=s.get_mission(sys.argv[2]);w=s.get_workspace(m.workspace_id)
if sys.argv[3]=='queue': _queue_cluster_mission_resume(r,mission=m,workspace=w)
else: _launch_async_mission_resume(r,m.mission_id)
os._exit(23)
"""
            process = _run_child([sys.executable, "-c", program, str(root), mission.mission_id, identity.rsplit(".", 1)[-1]], capture_output=True, text=True, encoding="utf8", timeout=30)
            require(process.returncode == 23 and len(registry.list_jobs()) == 1, "actual resume caller exit lost committed queue row: " + process.stderr[-1000:])
            existing = registry.list_jobs()[0]; current = observe()
            require(current["skipped"] and current["jobId"] == existing["jobId"], "restarted queue caller duplicated its completed durable admission")
        else:
            current = observe(); repeated = observe()
            require(repeated["skipped"] and repeated["jobId"] == current["jobId"], "actual repeated queue request changed current durable mission job")
        return {"queuedLocalRuntimeAdmission": True, "runtimeExecution": False, "ownedMission": mission.mission_id}


def _owned_worker(root, category, identity):
    from .worker import execute_job, run_local_worker_once, _start_unlimited_worker_attempt
    from .cluster import ClusterRegistry
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned worker bytes é›ª")
    original = root / "input.txt"; original.write_text(literal, encoding="utf8")
    program = root / "owned-command.py"
    program.write_text("""import os,json,sys,time
from pathlib import Path
time.sleep(.05)
value={'literal':Path('input.txt').read_text(encoding='utf8'),'control':os.environ.get('FLUXIO_CONTROL_PROJECT_ROOT'),'cluster':os.environ.get('FLUXIO_CLUSTER_ROOT')}
Path('effect.json').write_text(json.dumps(value,ensure_ascii=True),encoding='utf8')
raise SystemExit(int(sys.argv[1]))
""", encoding="utf8")
    cluster_root = root / "shared"
    control = root / "authority"
    payload = {"executionRoot": str(root), "controlProjectRoot": str(control), "command": [sys.executable, str(program), "23" if category == "interrupted" else "0"]}
    command_job = {"missionId": "owned", "workspaceId": "owned", "payload": payload}
    child_env = dict(os.environ); child_env.pop("FLUXIO_CLUSTER_ROOT", None); child_env.pop("FLUXIO_CONTROL_PROJECT_ROOT", None)
    effect = root / "effect.json"
    with environment(FLUXIO_CLUSTER_ROOT=str(cluster_root), FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_WORKSPACE_MAPPINGS=None):
        def observe_execute():
            value = execute_job(command_job, {}, root=root, process_environment=child_env)
            require(value["status"] == ("failed" if category == "interrupted" else "completed")
                    and value["returnCode"] == (23 if category == "interrupted" else 0)
                    and json.loads(effect.read_text(encoding="utf8")) == {"literal": original.read_text(encoding="utf8"), "control": str(control.resolve()), "cluster": str(cluster_root)},
                    "actual worker child changed exact input/effect/environment or falsely classified caller exit")
            return value
        if identity.endswith(("execute", "environment")):
            if category == "permissions" and identity.endswith("environment"):
                malicious = {**child_env, "FLUXIO_CLUSTER_ROOT": str(root / "unapproved")}
                refusal(lambda: execute_job(command_job, {}, root=root, process_environment=malicious), (ValueError,))
                require(not effect.exists(), "forbidden child environment override executed a local command")
            elif category == "permissions":
                with _sharing_denied(program):
                    denied = execute_job(command_job, {}, root=root, process_environment=child_env)
                    require(denied["status"] == "failed" and denied["returnCode"] != 0 and not effect.exists(), "OS-denied Python command was falsely completed or wrote its effect")
            elif category == "offline":
                if identity.endswith("environment"):
                    observe_execute()
                else:
                    payload["command"] = [str(root / "missing-owned-executable.exe")]
                    denied = execute_job(command_job, {}, root=root, process_environment=child_env)
                    require(denied["status"] == "failed" and denied["returnCode"] == -1 and not effect.exists(), "unavailable selected executable was falsely completed")
            elif category == "concurrency":
                def concurrent(index):
                    local = root / ("attempt-" + str(index)); local.mkdir()
                    (local / "input.txt").write_bytes(original.read_bytes())
                    job = {**command_job, "payload": {**payload, "executionRoot": str(local)}}
                    value = execute_job(job, {}, root=root, process_environment=child_env)
                    require(value["status"] == "completed" and json.loads((local / "effect.json").read_text(encoding="utf8")) == {"literal": literal, "control": str(control.resolve()), "cluster": str(cluster_root)}, "parallel actual child lost selected workspace/effect/environment binding")
                with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(concurrent, range(8)))
            elif category == "stale":
                observe_execute(); original.write_text("new current owned input", encoding="utf8"); control = root / "new-current-authority"; payload["controlProjectRoot"] = str(control)
                observe_execute()
            else: observe_execute()
            return {"actualOwnedPythonChild": True, "networkCalls": 0, "renderedUiClaim": False}
        registry = ClusterRegistry(root)
        queued = registry.upsert_job(dedupe_key="owned", mission_id="owned", workspace_id="owned", runtime_id="owned-local", required_capabilities=["command.run"], payload=payload)
        host = {"hostId": "c7d-owned-worker", "hostType": "workstation", "capabilities": ["command.run"], "maxConcurrentJobs": 1, "workspaceRoot": str(root), "workspaceMappings": {"owned": str(root)}, "runtimes": []}
        def attempt(observer=None):
            return run_local_worker_once(root, host_id=host["hostId"], observed_capabilities=host, process_environment=child_env, claim_observer=observer)
        def channels():
            completion, admission, thread = _start_unlimited_worker_attempt(attempt)
            admitted = admission.result(timeout=20); value = completion.result(timeout=30); thread.join(timeout=5)
            require(completion is not admission and admitted is value["claimed"] and not thread.is_alive(), "actual worker thread failed independent typed admission/completion channels")
            return value
        action = channels if identity.endswith("threads") else attempt
        if category == "permissions":
            with _sharing_denied(program): value = action()
            require(value["claimed"] and value["result"]["status"] == "failed" and not effect.exists(), "OS-denied owned worker child lost admitted failure state or fabricated artifact")
        elif category == "offline":
            payload["command"] = [str(root / "missing-owned-executable.exe")]
            with registry._connect() as db: db.execute("UPDATE jobs SET payload_json=? WHERE job_id=?", (json.dumps(payload), queued["jobId"]))
            value = action()
            require(value["claimed"] and value["result"]["status"] == "failed" and not effect.exists(), "unavailable executable lost actual worker admission/failure state")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: action(), range(8)))
            require(sum(value["claimed"] for value in values) == 1, "parallel local workers executed one actual queued job more than once")
            value = next(value for value in values if value["claimed"])
        else:
            value = action()
            require(value["claimed"] and value["result"]["returnCode"] == (23 if category == "interrupted" else 0), "actual worker did not report its exact owned child exit")
            require(json.loads(effect.read_text(encoding="utf8"))["literal"] == literal, "actual local worker child lost exact supplied bytes")
            if category == "stale":
                original.write_text("new current owned worker input", encoding="utf8")
                current = registry.upsert_job(dedupe_key="fresh", mission_id="owned", workspace_id="owned", runtime_id="owned-local", required_capabilities=["command.run"], payload=payload)
                fresh = action()
                require(fresh["claimed"] and fresh["job"]["jobId"] == current["jobId"] and json.loads(effect.read_text(encoding="utf8"))["literal"] == "new current owned worker input", "fresh worker generation reused a completed old input/admission")
        terminal = registry.get_job(queued["jobId"])
        expected_status = "failed" if category in {"permissions", "offline", "interrupted"} else "completed"
        require(terminal["status"] == expected_status and any(event["kind"] == "job." + expected_status for event in registry.list_events(job_id=queued["jobId"], limit=100)), "actual worker terminal state/event did not survive reopened durable observation")
        return {"actualOwnedPythonWorker": True, "terminalStatus": expected_status, "networkCalls": 0}


def _worker_lifecycle(root, category, identity):
    from .worker import _write_worker_state, _worker_state_path
    from .edge_fixture_native import _sharing_denied
    path = _worker_state_path(root)
    first = _write_worker_state(root, host_id="owned-host", status="starting", controller="", error="initial")
    def write(index):
        return _write_worker_state(root, host_id="owned-host", status="stopped", controller="", error="owned-error-" + str(index))
    if category == "permissions":
        before = path.read_bytes()
        with _sharing_denied(path): refusal(lambda: write(1), (OSError,))
        require(path.read_bytes() == before, "denied lifecycle publication changed saved state")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(write, range(8)))
        require(all(value["startedAt"] == first["startedAt"] and value["hostId"] == "owned-host" for value in values)
                and json.loads(path.read_text(encoding="utf8")) in values, "parallel lifecycle updates lost initial owner/start timestamp or published unknown state")
    elif category == "interrupted":
        program = "import os,sys;from pathlib import Path;from grant_agent.worker import _write_worker_state;_write_worker_state(Path(sys.argv[1]),host_id='owned-host',status='stopped',controller='',error='committed-exit');os._exit(23)"
        process = _run_child([sys.executable, "-c", program, str(root)], capture_output=True, text=True, encoding="utf8", timeout=20)
        value = json.loads(path.read_text(encoding="utf8"))
        require(process.returncode == 23 and value["lastError"] == "committed-exit" and value["startedAt"] == first["startedAt"] and value["status"] == "stopped", "actual lifecycle caller exit lost selected committed transition: " + process.stderr[-1000:])
    else:
        selected = {**first, "startedAt": "2000-01-01T00:00:00Z", "lastError": "old-generation"}
        path.write_text(json.dumps(selected), encoding="utf8")
        current = write(1)
        require(current["startedAt"] == selected["startedAt"] and current["lastError"] == "owned-error-1" and current["status"] == "stopped", "fresh lifecycle write reused old error/state or discarded original selected start time")
    return {"savedOwnedLifecycleState": True, "liveSupervisorTouched": False}


def _owned_installer(root, category, identity):
    import io
    import tarfile
    from . import cli_installer as installer
    from .cli_catalog import CATALOG
    from .edge_fixture_native import _sharing_denied
    entry = CATALOG["claude-code"]; literal = TEXT.get(category, "owned package bytes é›ª")
    archive = root / "owned-package.tgz"
    def package(value):
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in (("package/owned.cmd", b"@echo off\r\necho c7d-owned-packaging-peer-1.0\r\n"), ("package/payload.txt", value.encode("utf8"))):
                item = tarfile.TarInfo(name); item.size = len(data); item.mtime = 0; stream.addfile(item, io.BytesIO(data))
    package(literal)
    settings = root / "peer.json"; settings.write_text(json.dumps({"source": str(archive), "command": entry.command_name}), encoding="utf8")
    peer = root / "packaging-peer.py"
    peer.write_text("""import os,sys,json,tarfile
from pathlib import Path
a=sys.argv[2:];c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'));mode=os.environ.get('C7D_PACKAGING_FAILURE','')
if a[0]=='pack':
 if mode=='offline': raise SystemExit(17)
 p=Path(a[a.index('--pack-destination')+1])/'owned.tgz';p.write_bytes(Path(c['source']).read_bytes())
 if mode=='interrupted': os._exit(23)
 print(json.dumps([{'filename':p.name}]))
elif a[0]=='install':
 p=Path(a[a.index('--prefix')+1]);t=p/'node_modules'/'.bin'/(c['command']+'.cmd');t.parent.mkdir(parents=True,exist_ok=True)
 with tarfile.open(a[-1],'r:gz') as stream:
  t.write_bytes(stream.extractfile('package/owned.cmd').read());(p/'payload.txt').write_bytes(stream.extractfile('package/payload.txt').read())
 print('owned local archive installed')
else: raise SystemExit(19)
""", encoding="utf8")
    commands = []; probes = []
    def runner(command, **kwargs):
        commands.append(command if isinstance(command, str) else list(command))
        if isinstance(command, list) and len(command) > 1 and command[1] in {"pack", "install"}:
            command = [sys.executable, str(peer), str(settings), *command[1:]]
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        hidden = hidden_windows_subprocess_kwargs()
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | hidden['creationflags']
        kwargs.setdefault('startupinfo', hidden.get('startupinfo'))
        done = subprocess.run(command, **kwargs)
        if isinstance(command, str) or len(command) > 1 and command[1] == "/d": probes.append({"command": command, "returnCode": done.returncode, "stdout": done.stdout, "stderr": done.stderr})
        return done
    def release():
        return {"package": entry.package_name, "version": "1.0.0", "integrity": "sha512-" + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode(), "registry": "c7d-owned-packaging-peer", "tarball": "owned-generated-bytes", "downloadBytes": 0, "unpackedBytes": len(literal.encode("utf8"))}
    declared = release()
    if identity.endswith("integrity"):
        staging = root / "staging"; staging.mkdir()
        def verified(selected=staging, expected=declared):
            value = installer._verified_package_archive(sys.executable, entry, expected, staging=selected, workspace=root, runner=runner)
            require(value == (selected / "owned.tgz").resolve() and value.read_bytes() == archive.read_bytes(), "verified owned package bytes/path differ from selected staging source")
            return value
        if category == "empty":
            archive.write_bytes(b""); declared.update(release()); verified()
        elif category == "permissions":
            before = archive.read_bytes()
            with _sharing_denied(archive): refusal(verified, (RuntimeError, OSError))
            require(archive.read_bytes() == before, "denied package source was changed")
        elif category == "stale":
            package("changed actual owned generation")
            refusal(verified, (RuntimeError,)); verified(expected=release())
        elif category == "concurrency":
            def concurrent(index):
                selected = root / ("stage-" + str(index)); selected.mkdir(); return verified(selected)
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(concurrent, range(8)))
            require(len(set(values)) == 8, "parallel archive checks reused another caller's selected staging root")
        elif category in {"offline", "interrupted"}:
            from .proofs_a_cli_scheduler import environment
            with environment(C7D_PACKAGING_FAILURE=category): refusal(verified, (RuntimeError,))
        else: verified()
        return {"actualHiddenPackagingPeer": True, "sha512Checked": True, "officialNpmDownloadClaim": False}
    runtime = root / "managed"
    def install(**changes):
        return installer.perform_cli_action(root, "claude-code", "install", approved=True, approval_id="owned-action-time-grant",
                                            runtime_root=runtime, npm_path=sys.executable, resolver=lambda *a, **k: declared, runner=runner, **changes)
    first = install()
    require(first["status"] == "completed" and first["probeOutput"] == "c7d-owned-packaging-peer-1.0", "real installer did not publish/probe the explicitly owned package launcher: " + json.dumps({"receipt": first, "actualProbes": probes}))
    manifest = installer.load_manifest("claude-code", runtime_root=runtime)
    launcher = Path(manifest["launcherPath"]); manifest_path = installer._manifest_path(runtime, "claude-code")
    old_launcher = launcher.read_bytes(); old_manifest = manifest_path.read_bytes()
    require((Path(manifest["installDir"]) / "payload.txt").read_bytes() == literal.encode("utf8"), "managed installation changed actual generated package payload bytes")
    if category == "empty":
        count = len(commands)
        result = installer.perform_cli_action(root, "claude-code", "update", approved=False, approval_id="", runtime_root=runtime)
        require(result["status"] == "approval_required" and len(commands) == count, "missing action-time approval executed packaging/launcher mutation")
    elif category == "permissions":
        with _sharing_denied(archive): result = install()
        require(result["status"] == "failed", "OS-denied source was falsely installed")
    elif category in {"offline", "interrupted"}:
        from .proofs_a_cli_scheduler import environment
        with environment(C7D_PACKAGING_FAILURE=category): result = install()
        require(result["status"] == "failed", "unavailable/interrupted owned packaging child was falsely completed")
    elif category == "stale":
        package("untrusted changed actual source")
        result = install(); require(result["status"] == "failed", "changed archive bytes admitted old declared integrity")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: install(), range(8)))
        require(all(value["status"] == "completed" for value in values) and installer.load_manifest("claude-code", runtime_root=runtime)["state"] == "active", "parallel installer leases failed a truthful active publication")
    else:
        result = install(); require(result["status"] == "completed" and result["previousInstallRetained"], "fresh real installer publication lost retained previous generation")
    if category in {"empty", "permissions", "offline", "interrupted", "stale"}:
        require(launcher.read_bytes() == old_launcher and manifest_path.read_bytes() == old_manifest, "failed or unapproved package action replaced previous verified launcher/manifest")
    return {"actualHiddenPackagingPeer": True, "actualCmdLauncherProbe": True, "officialNpmDownloadClaim": False, "providerExecution": False}


def _mission_docs(root, category, identity):
    from .cli import _sync_mission_from_result
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, FLUXIO_CONTROL_ROOM_FAST="1", FLUXIO_MISSION_ACTION_COMPACT="1"):
        store = ControlRoomStore(root); workspace = store.load_workspaces()[0]
        mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="owned-local", objective="Implement an application feature",
                                       success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=0)
        files = [] if category == "empty" else ["docs/" + str(index) + ".md" for index in range(2000)] if category == "huge" else ["docs/é›ª.md"] if category == "unicode" else ["README.md", "docs/owned.md"]
        supplied = {"autopilot_status": "completed", "changed_files": files, "remaining_steps": [], "verification_failures": []}
        expected = "completed" if not files else "blocked"
        def observe():
            result = _sync_mission_from_result(store, mission.mission_id, supplied)
            fresh = ControlRoomStore(root).get_mission(mission.mission_id)
            require(not result.get("error") and fresh.state.status == expected
                    and fresh.state.last_error == ("docs_only_completion_without_product_changes" if files else None)
                    and result["result"] == supplied, "real mission result synchronization lost exact docs-only durable state or changed its supplied result")
            return result
        if category == "permissions":
            before = store.missions_path.read_bytes()
            with _sharing_denied(store.missions_path):
                try:
                    result = _sync_mission_from_result(store, mission.mission_id, supplied)
                except OSError:
                    result = {"error": "OS denied selected saved mission"}
                require(result.get("error"), "unreadable selected mission fabricated a synchronized completion")
            require(store.missions_path.read_bytes() == before, "OS-denied synchronization changed selected saved mission bytes")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
            require(len(values) == 8 and ControlRoomStore(root).get_mission(mission.mission_id).state.status == "blocked", "parallel docs-only completion escaped durable blocked state")
        elif category == "stale":
            observe()
            fresh = store.get_mission(mission.mission_id); fresh.objective = "Write documentation only"; store.update_mission(fresh)
            current = _sync_mission_from_result(store, mission.mission_id, supplied)
            require(current["mission"]["state"]["status"] == "completed" and ControlRoomStore(root).get_mission(mission.mission_id).state.status == "completed", "new docs-only mission objective reused an old product-required block")
        elif category == "interrupted":
            argument = root / "result.json"; argument.write_text(json.dumps(supplied), encoding="utf8")
            program = "import os,sys,json;from pathlib import Path;from grant_agent.cli import _sync_mission_from_result;from grant_agent.mission_control import ControlRoomStore;_sync_mission_from_result(ControlRoomStore(Path(sys.argv[1])),sys.argv[2],json.load(open(sys.argv[3],encoding='utf8')));os._exit(23)"
            process = _run_child([sys.executable, "-c", program, str(root), mission.mission_id, str(argument)], capture_output=True, text=True, encoding="utf8", timeout=30)
            fresh = ControlRoomStore(root).get_mission(mission.mission_id)
            require(process.returncode == 23 and fresh.state.status == "blocked" and fresh.state.last_error == "docs_only_completion_without_product_changes", "actual mission synchronization caller exit lost committed exact docs-only refusal: " + process.stderr[-1000:])
        else: observe()
        return {"actualDurableMissionSynchronization": True, "declaredChangedPathCount": len(files), "providerExecution": False}


def _owned_watchdog(root, category, identity):
    import argparse
    from . import cli
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .edge_fixture_native import _sharing_denied
    selected_path = os.pathsep.join([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
                                   str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0"), str(Path(sys.executable).parent)])
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, PATH=selected_path,
                     PLAYWRIGHT_BROWSERS_PATH=str(root / "owned-browser-cache"), PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=str(root / "absent-owned-browser.exe")):
        store = ControlRoomStore(root); workspaces=store.load_workspaces(); workspaces[0].name=TEXT.get(category, "owned scoped cadence"); store.save_workspaces(workspaces)
        state_path = root / ".agent_control/mission_watchdog_supervisor.json"
        loop_program = """import sys
from pathlib import Path
from grant_agent.proof_credential_guard import install
install(Path(sys.argv[1]))
def guard(event,args):
 if event in {'socket.connect','socket.bind','socket.getaddrinfo'}: raise PermissionError('Owned C7d watchdog permits no network')
sys.addaudithook(guard)
from grant_agent.cli import build_parser,cmd_mission_watchdog
raise SystemExit(cmd_mission_watchdog(build_parser().parse_args(['mission-watchdog','--root',sys.argv[1],'--loop','--max-runs','0','--interval-seconds','3600','--no-write-report'])))
"""
        error_path = root / "owned-loop-stderr.txt"
        with error_path.open("w", encoding="utf8") as error_handle:
            loop = subprocess.Popen([sys.executable, "-c", loop_program, str(root)], cwd=root, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=error_handle, **hidden_windows_subprocess_kwargs())
        try:
            deadline=time.monotonic()+30; baseline={}
            while time.monotonic() < deadline and loop.poll() is None:
                try: baseline=json.loads(state_path.read_text(encoding="utf8"))
                except (OSError, ValueError): baseline={}
                if baseline.get("processPid") == loop.pid and baseline.get("runsCompleted", 0) >= 1: break
                time.sleep(.05)
            require(baseline.get("loopMode") == "ongoing" and baseline.get("processPid") == loop.pid and loop.poll() is None, "actual owned watchdog loop failed to publish its current process identity: " + error_path.read_text(encoding="utf8")[-1800:])
            args=argparse.Namespace(root=str(root), no_write_report=True, interval_seconds=3600, stale_minutes=60, fake_running_minutes=120,
                                    advance_self_improvement=False, notify_telegram=False, notify_ntfy=False)
            def observe():
                payload=cli._run_mission_watchdog_pass(args=args, root=root, started_at="one-shot selected literal", runs_completed=555, loop_mode="one_shot")
                state=payload["supervisor"]; persisted=json.loads(state_path.read_text(encoding="utf8"))
                require(state["loopMode"] == "ongoing" and state["processPid"] == loop.pid and state["runsCompleted"] == baseline["runsCompleted"]
                        and state["oneShotProcessPid"] == os.getpid() and persisted == state and loop.poll() is None,
                        "actual one-shot pass replaced live owned loop identity/cadence or lost persisted state")
                require(payload["watchdog"]["browserDependencyPreflight"]["browserProofAvailable"] is False, "missing owned browser metadata claimed rendered capability")
                return payload
            caller_program = """import argparse,os,sys
from pathlib import Path
from grant_agent.proof_credential_guard import install
install(Path(sys.argv[1]))
def guard(event,args):
 if event in {'socket.connect','socket.bind','socket.getaddrinfo'}: raise PermissionError('Owned C7d pass permits no network')
sys.addaudithook(guard)
from grant_agent.cli import _run_mission_watchdog_pass
args=argparse.Namespace(root=sys.argv[1],no_write_report=True,interval_seconds=3600,stale_minutes=60,fake_running_minutes=120,advance_self_improvement=False,notify_telegram=False,notify_ntfy=False)
p=_run_mission_watchdog_pass(args=args,root=Path(sys.argv[1]),started_at='actual child caller',runs_completed=555,loop_mode='one_shot')
os._exit(23 if sys.argv[2]=='exit' else 0)
"""
            if category == "permissions":
                before=state_path.read_bytes()
                with _sharing_denied(state_path): refusal(observe, (OSError,))
                require(state_path.read_bytes() == before, "OS-denied one-shot pass altered current owned cadence")
            elif category in {"interrupted", "concurrency"}:
                def child(_): return _run_child([sys.executable,"-c",caller_program,str(root),"exit" if category == "interrupted" else "return"],capture_output=True,text=True,encoding="utf8",timeout=40)
                with ThreadPoolExecutor(max_workers=4) as pool: children=list(pool.map(child,range(8 if category == "concurrency" else 1)))
                require(all(child.returncode == (23 if category == "interrupted" else 0) for child in children), "actual concurrent/interrupted cadence caller failed: " + " | ".join(child.stderr[-700:] for child in children if child.returncode not in {0,23}))
                persisted=json.loads(state_path.read_text(encoding="utf8"));require(persisted["processPid"] == loop.pid and persisted["runsCompleted"] == baseline["runsCompleted"] and loop.poll() is None, "exited caller rewrote current live cadence identity")
            elif category == "stale": observe(); observe()
            else: observe()
        finally:
            if loop.poll() is None: loop.terminate()
            loop.wait(timeout=10)
        return {"actualOwnedWatchdogLoop": True, "preservedCurrentPID": True, "liveSupervisorTouched": False, "renderedBrowserProof": False, "networkCalls": 0}


def _prepare_owned_resume(root, objective, *, expire=True):
    from . import cli
    from .mission_control import ControlRoomStore
    root = Path(root); cli.bootstrap_project(root)
    (root / "README.md").write_text("# Owned real CLI resume boundary\n", encoding="utf8")
    store = ControlRoomStore(root); workspace = store.load_workspaces()[0]
    workspace.execution_target_preference = "workspace_root"; workspace.root_path = str(root); store.save_workspaces([workspace])
    mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="local-owned", objective=objective,
               success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=91,
               run_until_behavior="pause_on_failure", harness_id="legacy_autonomous_engine")
    cli._run_mission_engine_cycles(store=store, mission=mission, workspace=workspace, project_profile="C7d real bounded resume")
    mission = store.get_mission(mission.mission_id)
    require(mission.state.latest_session_id, "owned resume preparation did not create an actual legacy session")
    if expire:
        mission.created_at = "2000-01-01T00:00:00+00:00"; mission.run_budget.max_runtime_seconds = 1
        store.update_mission(mission)
    return store, mission


def _mission_spawn(root, category, identity):
    import contextlib
    import ctypes
    from . import cli
    from .proofs_a_cli_scheduler import environment, substitute
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, FLUXIO_MISSION_DISPATCH_MODE="local_process"):
        store, mission = _prepare_owned_resume(root, TEXT.get(category, "owned actual CLI child"), expire=category not in {"permissions", "offline"})
        real_popen = subprocess.Popen; processes=[]; observed=[]
        def actual_popen(command, **options):
            require(command[:3] == [sys.executable, "-m", "grant_agent.cli"] and "mission-action" in command and command[command.index("--root") + 1] == str(root), "spawn changed actual Neyvia CLI command or owned root")
            require(options["stdin"] == subprocess.DEVNULL and options["close_fds"] is True and options["start_new_session"] == (sys.platform != "win32"), "actual CLI child inherited interactive input or lost detached session")
            if os.name == "nt": require(options["creationflags"] & subprocess.CREATE_NO_WINDOW, "actual CLI child could open a desktop window")
            process = real_popen(command, **options); processes.append(process); observed.append(process.pid); return process
        def launch(): return cli._launch_async_mission_resume(root, mission.mission_id)
        if category == "interrupted":
            program = """import json,os,sys
from pathlib import Path
from grant_agent.cli import _launch_async_mission_resume
r=_launch_async_mission_resume(Path(sys.argv[1]),sys.argv[2]);Path(sys.argv[3]).write_text(json.dumps(r),encoding='utf8');os._exit(23)
"""
            receipt = root / "exited-spawn.json"
            parent = _run_child([sys.executable, "-c", program, str(root), mission.mission_id, str(receipt)], capture_output=True, text=True, encoding="utf8", timeout=30)
            require(parent.returncode == 23, "actual spawn caller failed before exit: " + parent.stderr[-800:]); value = json.loads(receipt.read_text(encoding="utf8"))
            if os.name == "nt":
                kernel = ctypes.WinDLL("kernel32", use_last_error=True); kernel.OpenProcess.restype = ctypes.c_void_p
                handle = kernel.OpenProcess(0x00100000, False, value["pid"])
                if handle:
                    try: require(kernel.WaitForSingleObject(ctypes.c_void_p(handle), 30000) == 0, "owned detached CLI child did not complete after caller exit")
                    finally: kernel.CloseHandle(ctypes.c_void_p(handle))
            require(store.get_mission(mission.mission_id).state.last_error == "runtime_budget", "spawn caller exit lost actual child budget refusal")
        else:
            denied = _sharing_denied(root / "config/constitution.json") if category == "permissions" else contextlib.nullcontext()
            if category == "offline": (root / "config/constitution.json").write_text("{ malformed unavailable local engine configuration", encoding="utf8")
            with denied, substitute(cli.subprocess, "Popen", actual_popen):
                if category == "concurrency":
                    with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: launch(), range(8)))
                    require(len({value["pid"] for value in values}) == 8, "independent actual CLI spawns reused one child process")
                else: values = [launch()]
                codes = [process.wait(timeout=35) for process in processes]
            require(len(observed) == len(values) and all(Path(value["logPath"]).is_file() and value["pid"] in observed for value in values), "actual spawn receipt lost owned child/log identity")
            if category in {"permissions", "offline"}: require(all(code != 0 for code in codes), "denied/unavailable selected engine was falsely completed")
            else:
                require(all(code == 0 for code in codes) and store.get_mission(mission.mission_id).state.last_error == "runtime_budget", "actual CLI spawn did not reach bounded durable budget refusal")
        return {"actualNeyviaCLIChild": True, "interactiveInputInherited": False, "visibleWindows": 0, "providerOrRenderedExecution": False}


def _start_owned_command(root, objective, minutes):
    import contextlib
    import io
    from . import cli
    from .mission_control import ControlRoomStore
    from .runtimes.managed_cli import ManagedCliSpec, ManagedCliRuntimeAdapter
    from .proofs_a_cli_scheduler import environment, substitute
    root = Path(root)
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, NEYVIA_MANAGED_RUNTIME_ROOT=str(root / "managed-runtime")):
        cli.bootstrap_project(root); store = ControlRoomStore(root); workspace = store.load_workspaces()[0]
        spec = ManagedCliSpec(runtime_id="c7d-owned", label="Owned unavailable local fixture command", command_name=str(root / "absent-owned-command.exe"),
                              default_model="none", install_command="", update_command="", login_hint="No provider authentication belongs to this fixture", docs_url="", supports_acp=False)
        adapter = ManagedCliRuntimeAdapter(spec)
        with substitute(cli, "runtime_adapter_map", lambda: {spec.runtime_id: adapter}):
            args = cli.build_parser().parse_args(["mission-start", "--root", str(root), "--workspace-id", workspace.workspace_id,
                    "--runtime", spec.runtime_id, "--objective", objective, "--relative-stop-minutes", str(minutes),
                    "--verification-command", "owned-unexecuted-verification", "--escalation-destination", "owned-no-notification", "--skip-snapshot"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = cli.cmd_mission_start(args)
        require(code == 0, "actual CLI refused durable unavailable-runtime mission admission")
        payload = json.loads(output.getvalue()); mission = store.get_mission(payload["mission"]["mission_id"])
        require("snapshot" not in payload and payload["runtimeStatus"]["runtime_id"] == "c7d-owned" and payload["runtimeStatus"]["detected"] is False
                and mission.state.status in {"blocked", "queued"} and mission.run_budget.max_runtime_seconds == minutes * 60
                and mission.run_budget.run_until_behavior == "continue_until_blocked" and mission.run_budget.deadline_at,
                "actual admitted mission dropped selected timer or claimed unavailable runtime execution")
        return payload


def _mission_started(root, category, identity):
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None):
        literal = TEXT.get(category, "owned durable start é›ª")
        baseline = _start_owned_command(root, literal, 2)
        store = ControlRoomStore(root)
        program = """import json,os,sys
from pathlib import Path
from grant_agent.edge_fixture_c7d_control import _start_owned_command
p=_start_owned_command(Path(sys.argv[1]),sys.argv[2],int(sys.argv[3]));Path(sys.argv[4]).write_text(json.dumps(p),encoding='utf8')
os._exit(23 if sys.argv[5]=='exit' else 0)
"""
        if category == "permissions":
            before = store.missions_path.read_bytes()
            with _sharing_denied(store.missions_path): refusal(lambda: _start_owned_command(root, "denied selected mission", 3), (OSError,))
            require(store.missions_path.read_bytes() == before, "denied mission start mutated saved admission")
        elif category in {"interrupted", "concurrency"}:
            def child(index):
                area = root / f"owned-caller-{index}"; receipt = root / f"owned-caller-{index}.json"
                process = _run_child([sys.executable, "-c", program, str(area), f"independent start {index}", str(index + 1), str(receipt), "exit" if category == "interrupted" else "return"], capture_output=True, text=True, encoding="utf8", timeout=40)
                require(process.returncode == (23 if category == "interrupted" else 0), "actual mission-start caller failed: " + process.stderr[-1000:])
                payload = json.loads(receipt.read_text(encoding="utf8")); fresh = ControlRoomStore(area).get_mission(payload["mission"]["mission_id"])
                require(fresh.run_budget.max_runtime_seconds == (index + 1) * 60 and fresh.run_budget.deadline_at, "caller exit/concurrent selected mission lost exact saved timer")
            with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(child, range(8 if category == "concurrency" else 1)))
        elif category == "stale":
            current = _start_owned_command(root, "fresh distinct selected timer", 3)
            require(current["mission"]["mission_id"] != baseline["mission"]["mission_id"] and store.get_mission(baseline["mission"]["mission_id"]).run_budget.max_runtime_seconds == 120, "fresh admission overwrote or reused prior timer identity")
        return {"actualCLICommand": "mission-start --skip-snapshot", "savedSelectedTimer": True, "ownedCommandActuallyUnavailable": True, "runtimeOrProviderExecution": False}


def _continuous_checkpoint_cycle(store, workspace, mission_id, first):
    from datetime import datetime, timedelta, timezone
    from . import cli
    from .proofs_a_cli_scheduler import substitute
    checkpoints = first["result"].get("checkpoints", [])
    require(checkpoints, "actual initial cycle produced no safe checkpoint to resume")
    checkpoint = Path(checkpoints[-1]); original_bytes = checkpoint.read_bytes()
    mission = store.get_mission(mission_id)
    mission.run_budget.run_until_behavior = "continue_until_blocked"
    mission.run_budget.max_runtime_seconds = 5
    mission.run_budget.deadline_at = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    store.update_mission(mission)
    calls = []; original = cli._invoke_engine
    def observe_actual(**kwargs):
        # Relay the real owner unchanged; observe its selected inputs/results.
        result = original(**kwargs); calls.append((kwargs, result)); return result
    with substitute(cli, "_invoke_engine", observe_actual):
        cli._run_mission_engine_cycles(store=store, mission=mission, workspace=workspace, project_profile="C7d actual continuous checkpoint resume",
                                       resume_from=mission.state.latest_session_id, resume_checkpoint=str(checkpoint))
    require(calls and calls[0][0]["resume_checkpoint"] == str(checkpoint) and checkpoint.read_bytes() == original_bytes,
            "continuous cycle omitted or mutated its actual safe saved checkpoint")
    require(all(kwargs["pause_on_handoff"] is False and result["effective_pause_on_handoff"] is False
                and result["effective_max_runtime_seconds"] == kwargs["max_runtime_override"]
                and 0 < kwargs["max_runtime_override"] <= 5 for kwargs, result in calls),
            "real continuous resume lost remaining deadline or handoff policy")
    return {"actualCheckpoint": str(checkpoint), "continuousEngineCalls": len(calls), "externalProviderExecution": False}


def _mission_cycles(root, category, identity):
    from . import cli
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None):
        def prepare(area, objective):
            area.mkdir(parents=True, exist_ok=True); cli.bootstrap_project(area)
            (area / "README.md").write_text("# Owned mission-cycle preference proof\n", encoding="utf8")
            store = ControlRoomStore(area); workspace = store.load_workspaces()[0]
            workspace.root_path = str(area); workspace.execution_target_preference = "workspace_root"; store.save_workspaces([workspace])
            mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="local-owned", objective=objective,
                       success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=91,
                       run_until_behavior="pause_on_failure", harness_id="legacy_autonomous_engine")
            return store, workspace, mission
        store, workspace, mission = prepare(root / "selected", TEXT.get(category, "Owned local cycle"))
        def observe():
            before = store.get_mission(mission.mission_id)
            selected_limit = before.run_budget.max_runtime_seconds
            result = cli._run_mission_engine_cycles(store=store, mission=before, workspace=workspace, project_profile="C7d actual legacy planning cycle")
            engine = result["result"]
            require(engine["effective_pause_on_handoff"] is True and 0 < engine["effective_max_runtime_seconds"] <= selected_limit
                    and engine["effective_harness"] == "legacy_autonomous_engine" and engine["effective_verify_commands"] == [],
                    "actual mission cycle lost saved handoff/budget/verification preferences")
            persisted = store.get_mission(mission.mission_id)
            require(persisted.state.latest_session_id and Path(engine["session_path"]).is_dir(), "actual saved mission cycle lost its durable selected session")
            result["continuousResumeObservation"] = _continuous_checkpoint_cycle(store, workspace, mission.mission_id, result)
            return result
        program = """import json,os,sys
from pathlib import Path
from grant_agent.cli import _run_mission_engine_cycles
from grant_agent.edge_fixture_c7d_control import _continuous_checkpoint_cycle
from grant_agent.mission_control import ControlRoomStore
s=ControlRoomStore(Path(sys.argv[1]));m=s.get_mission(sys.argv[2]);w=s.get_workspace(m.workspace_id)
r=_run_mission_engine_cycles(store=s,mission=m,workspace=w,project_profile='C7d actual legacy planning cycle')
r['continuousResumeObservation']=_continuous_checkpoint_cycle(s,w,m.mission_id,r)
Path(sys.argv[3]).write_text(json.dumps(r),encoding='utf8');os._exit(23 if sys.argv[4]=='exit' else 0)
"""
        if category == "permissions":
            before = store.missions_path.read_bytes()
            with _sharing_denied(Path(workspace.root_path) / "config/constitution.json"): refusal(observe, (OSError,))
            require(store.missions_path.read_bytes() == before, "OS-denied engine config changed cycle mission state")
        elif category == "concurrency":
            selections = [prepare(root / f"parallel-{index}", f"independent local cycle {index}") for index in range(8)]
            def child(index):
                selected, _, owned = selections[index]; receipt = root / f"parallel-{index}.json"
                process = _run_child([sys.executable, "-c", program, str(selected.root), owned.mission_id, str(receipt), "return"], capture_output=True, text=True, encoding="utf8", timeout=40)
                require(process.returncode == 0, "parallel actual mission cycle failed: " + process.stderr[-800:])
                value = json.loads(receipt.read_text(encoding="utf8")); require(value["result"]["effective_pause_on_handoff"] is True and selected.get_mission(owned.mission_id).state.latest_session_id, "parallel selected cycle lost durable session or handoff preference")
                return value["result"]["session_path"]
            with ThreadPoolExecutor(max_workers=4) as pool: paths = list(pool.map(child, range(8)))
            require(len(set(paths)) == 8, "parallel independently selected missions reused one session")
        elif category == "interrupted":
            receipt = root / "exited-cycle.json"; process = _run_child([sys.executable, "-c", program, str(store.root), mission.mission_id, str(receipt), "exit"], capture_output=True, text=True, encoding="utf8", timeout=40)
            require(process.returncode == 23 and store.get_mission(mission.mission_id).state.latest_session_id and receipt.is_file(), "actual cycle caller exit lost committed session/state: " + process.stderr[-800:])
        elif category == "stale":
            mission.run_budget.max_runtime_seconds = 61; store.update_mission(mission)
            result = observe(); require(result["result"]["effective_max_runtime_seconds"] <= 61, "cycle reused stale prior saved runtime limit")
        else: observe()
        return {"actualOwner": "_run_mission_engine_cycles", "savedLegacyCycle": True, "externalModelOrProductExecution": False}


def _unlimited_loop(root, category, identity):
    import concurrent.futures
    import contextlib
    import io
    import threading
    from . import worker
    from .cluster import ClusterRegistry
    from .proofs_a_cli_scheduler import environment, substitute
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None):
        registry = ClusterRegistry(root); release = root / "release"; program = root / "owned-loop-child.py"
        program.write_text("import sys,time\nfrom pathlib import Path\nrelease=Path(sys.argv[1]);end=time.monotonic()+30\nwhile not release.exists() and time.monotonic()<end: time.sleep(.02)\nPath(sys.argv[2]).write_text(sys.argv[3],encoding='utf8')\nraise SystemExit(int(sys.argv[4]))\n", encoding="utf8")
        count = 0 if category == "empty" else 12 if category in {"huge", "concurrency"} else 3
        literal = TEXT.get(category, "owned admission literal é›ª").replace("\x00", "")
        if category == "stale":
            stale = registry.upsert_job(mission_id="old", workspace_id="old", runtime_id="local-owned")
            with registry._connect() as db: db.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (stale["jobId"],))
            literal = "new current generation"
        jobs = []
        for index in range(count):
            effect = root / f"effect-{index}.txt"
            command = [sys.executable, str(program), str(release), str(effect), literal[:15000], "23" if category == "interrupted" else "0"]
            if category == "offline": command = [str(root / "absent-owned-executable.exe")]
            jobs.append(registry.upsert_job(mission_id=f"owned-{index}", workspace_id=f"isolated-{index}", runtime_id="local-owned",
                        required_capabilities=["command.run"], payload={"executionRoot": str(root), "command": command, "timeoutSeconds": 35}))
        host = {"hostId": "c7d-unlimited-owner", "hostType": "workstation", "capabilities": ["command.run"], "maxConcurrentJobs": 0,
                "workspaceRoot": str(root), "workspaceMappings": {f"isolated-{index}": str(root) for index in range(count)}, "runtimes": []}
        original = worker.run_local_worker_once; real_wait = concurrent.futures.wait; admissions=[]; guard=threading.Lock(); deadline=time.monotonic()+45
        terminal_deadline = None
        def actual_poll(*args, **kwargs):
            supplied = kwargs.pop("claim_observer", None)
            def admitted(value):
                with guard: admissions.append(bool(value))
                if supplied: supplied(value)
            return original(*args, **kwargs, observed_capabilities=host, process_environment=dict(os.environ), claim_observer=admitted)
        def bounded_wait(futures, **kwargs):
            nonlocal terminal_deadline
            if len(admissions) >= count + 1:
                release.write_text("release actual owned children", encoding="utf8")
                # Admission and child/journal settlement are separate bounded
                # phases. Time spent claiming jobs cannot consume the child's
                # declared execution allowance or its terminal observation.
                terminal_deadline = time.monotonic() + 45
                raise KeyboardInterrupt
            require(time.monotonic() < deadline, "actual unlimited admission loop did not finish bounded admissions")
            return real_wait(futures, timeout=.05, return_when=kwargs.get("return_when", concurrent.futures.FIRST_COMPLETED))
        denied = _sharing_denied(program) if category == "permissions" else contextlib.nullcontext()
        try:
            with denied, substitute(worker, "run_local_worker_once", actual_poll), substitute(concurrent.futures, "wait", bounded_wait), contextlib.redirect_stdout(io.StringIO()):
                code = worker.main(["--root", str(root), "--host-id", host["hostId"], "--max-jobs", "unlimited", "--poll-seconds", ".05"])
                release.write_text("release actual admitted children", encoding="utf8")
                # Keep an OS read denial in force until admitted children have
                # actually opened/refused the selected script and terminated.
                while terminal_deadline is not None and time.monotonic() < terminal_deadline and any(registry.get_job(job["jobId"])["status"] in {"queued", "leased", "running"} for job in jobs): time.sleep(.05)
            require(code == 130 and sum(admissions) == count and len(admissions) >= count + 1, f"actual unlimited loop admission receipt mismatch: code={code}, expected={count}, observed={admissions}")
        finally: release.write_text("release owned children on every path", encoding="utf8")
        while terminal_deadline is not None and time.monotonic() < terminal_deadline and any(registry.get_job(job["jobId"])["status"] in {"queued", "leased", "running"} for job in jobs): time.sleep(.05)
        expected = "failed" if category in {"offline", "permissions", "interrupted"} else "completed"
        require(all(registry.get_job(job["jobId"])["status"] == expected for job in jobs), "actual loop terminal job differs from child return/refusal")
        if category not in {"offline", "permissions"}:
            require(all((root / f"effect-{index}.txt").read_text(encoding="utf8") == literal[:15000] for index in range(count)), "actual concurrent loop child lost exact selected effect bytes")
        require(registry.get_host(host["hostId"])["maxConcurrentJobs"] == 0 and registry.get_host(host["hostId"])["currentLoad"] == 0, "unlimited loop retained a fixed capacity or terminal leases")
        return {"actualProductionLoop": True, "admittedOwnedJobs": count, "terminalStatus": expected, "externalProviderOrLiveSupervisor": False}


def _delegated_queue(root, category, identity):
    from dataclasses import asdict
    from .cluster import ClusterRegistry
    from .runtime_supervisor import DelegatedRuntimeSupervisor
    from .models import DelegatedRuntimeSession, PlanRevision, PlannedStep
    from .fluxio_harness import FluxioHarness
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    mission = root / "mission"; mission.mkdir()
    shared = root / "shared"
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=str(shared)):
        legacy = ClusterRegistry(mission, use_configured_root=False); registry = ClusterRegistry(shared, use_configured_root=False)
        literal = TEXT.get(category, "owned queued lane é›ª")
        session = DelegatedRuntimeSession(delegated_id="owned-queued", runtime_id="local-owned", launch_command=literal,
                   mission_id="owned-mission", status="queued", session_path=str(mission / ".agent_control/runtime_sessions/owned-queued.json"),
                   workspace_root=str(mission), execution_root=str(mission), source_step_id="work", target_phase="execute", target_role="executor", cluster_job_id="job_legacy")
        supervisor = DelegatedRuntimeSupervisor(mission); supervisor._write_session(session)
        legacy.upsert_job(job_id="job_legacy", mission_id=session.mission_id, workspace_id="owned-workspace", runtime_id="local-owned",
                          required_capabilities=["command.run"], payload={"command": literal, "sessionPath": session.session_path})
        before = legacy.get_job("job_legacy")
        def rehome():
            refreshed = supervisor._sync_cluster_state(copy.deepcopy(session))
            rows = registry.list_jobs()
            require(len(rows) == 1 and refreshed.cluster_job_id == rows[0]["jobId"] != "job_legacy"
                    and rows[0]["payload"]["legacyClusterJobId"] == "job_legacy" and rows[0]["payload"]["legacyClusterRoot"] == str(mission)
                    and legacy.get_job("job_legacy") == before, "rehome lost exact immutable legacy lineage/shared identity")
            return refreshed
        def queued():
            refreshed = rehome()
            attempts = 2000 if category == "huge" else 0 if category == "empty" else 3
            step = PlannedStep(step_id="work", title=literal, attempts=attempts)
            revision = PlanRevision(revision_id="owned", trigger="initial", summary=literal, steps=[step]); notes=[]; risks=[]
            rows, status, trigger = FluxioHarness._reconcile_delegated_sessions([asdict(refreshed)], [revision], supervisor, notes, risks, literal, [])
            require(status == "running" and trigger == "" and step.status == "in_progress" and step.attempts == attempts
                    and not rows[0]["acknowledged"] and not risks, "actual queued reconciliation consumed an attempt or acknowledged unfinished work")
            return refreshed
        observe = queued if identity.endswith("queued") else rehome
        if category == "permissions":
            with _sharing_denied(registry.db_path):
                current = supervisor._sync_cluster_state(copy.deepcopy(session))
                require(current.cluster_job_id == "job_legacy", "OS-denied registry admitted shared ownership")
            require(not registry.list_jobs() and legacy.get_job("job_legacy") == before, "denied shared queue changed source lineage or admitted a job")
            observe()
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
            require(len({value.cluster_job_id for value in values}) == 1, "parallel rehome minted duplicate shared jobs")
        elif category == "stale":
            observe(); current = supervisor._sync_cluster_state(copy.deepcopy(session)); require(current.cluster_job_id != "job_legacy" and len(registry.list_jobs()) == 1, "stale caller duplicated established shared ownership")
        elif category == "interrupted":
            argument = root / "session.json"; argument.write_text(json.dumps(asdict(session)), encoding="utf8")
            program = """import json,os,sys
from pathlib import Path
from grant_agent.models import DelegatedRuntimeSession,PlannedStep,PlanRevision
from grant_agent.runtime_supervisor import DelegatedRuntimeSupervisor
from grant_agent.fluxio_harness import FluxioHarness
from dataclasses import asdict
s=DelegatedRuntimeSession(**json.load(open(sys.argv[2],encoding='utf8')));owner=DelegatedRuntimeSupervisor(Path(sys.argv[1]));s=owner._sync_cluster_state(s)
if sys.argv[3]=='queued': FluxioHarness._reconcile_delegated_sessions([asdict(s)],[PlanRevision(revision_id='owned',trigger='initial',summary='owned',steps=[PlannedStep(step_id='work',title='owned',attempts=3)])],owner,[],[],'owned',[])
os._exit(23)
"""
            child = _run_child([sys.executable, "-c", program, str(mission), str(argument), identity.rsplit(".", 1)[-1]], capture_output=True, text=True, encoding="utf8", timeout=30)
            require(child.returncode == 23 and len(registry.list_jobs()) == 1, "actual queue caller exit lost committed shared ownership: " + child.stderr[-900:]); observe()
        else: observe()
        return {"actualSharedQueue": True, "legacyRowPreserved": True, "providerOrSupervisorProcesses": 0}


def _legacy_preferences(root, category, identity):
    from . import cli
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, FLUXIO_WATCHDOG_AUTOSTART="0"):
        cli.bootstrap_project(root)
        document = root / "README.md"; document.write_text("# Owned legacy planning boundary\nNo provider execution is claimed.\n", encoding="utf8")
        literal = TEXT.get(category, "owned local planning preferences")
        configured_profile = json.loads((root / "config/profiles.json").read_text(encoding="utf8"))["default_profile"]
        values = dict(root=root, objective=literal, docs=[str(document)], mode_name="autopilot", profile_name="builder", persona_override=None,
                      iterations=1, verify_commands=[], project_profile="C7d actual legacy planning boundary", resume_from=None, resume_checkpoint=None,
                      checkpoint_every=1, pause_on_verification_failure=True, max_runtime_override=37, parallel_agents_override=3,
                      runtime_id="local-owned", mission_id="c7d-prefs", harness_preference="legacy_autonomous_engine",
                      execution_target_preference="workspace_root", pause_on_handoff=True)
        def observe():
            result = cli._invoke_engine(**values)
            require(result["effective_verify_commands"] == [] and result["effective_harness"] == "legacy_autonomous_engine"
                    and result["effective_max_runtime_seconds"] == values["max_runtime_override"]
                    and result["effective_parallel_agents"] == (values["parallel_agents_override"] if values["parallel_agents_override"] is not None else max(1, values["mission_state"]["parallel_agents"]))
                    and result["effective_pause_on_handoff"] is True and result["execution_policy"]["profile_name"] == configured_profile,
                    "actual legacy engine preference receipt dropped explicit selected limits or harness")
            require(Path(result["session_path"]).is_dir(), "actual legacy planning call did not create its owned durable session")
            return result
        if category == "permissions":
            with _sharing_denied(root / "config/constitution.json"): refusal(observe, (OSError,))
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: observe(), range(8)))
            require(len({result["session_path"] for result in results}) == 8, "concurrent planning calls shared a session identity")
        elif category == "stale":
            previous = observe(); values.update(parallel_agents_override=None, mission_state={"parallel_agents": 2}, max_runtime_override=19)
            current = observe(); require(current["session_path"] != previous["session_path"] and current["effective_parallel_agents"] == 2, "fresh selected mission preferences reused a stale prior run")
        elif category == "interrupted":
            argument = root / "invoke.json"; argument.write_text(json.dumps({**values, "root": str(root)}), encoding="utf8")
            program = """import json,os,sys
from pathlib import Path
from grant_agent.cli import _invoke_engine
v=json.load(open(sys.argv[1],encoding='utf8'));v['root']=Path(v['root']);r=_invoke_engine(**v)
Path(sys.argv[2]).write_text(json.dumps(r),encoding='utf8');os._exit(23)
"""
            receipt = root / "interrupted-observation.json"
            child = _run_child([sys.executable, "-c", program, str(argument), str(receipt)], capture_output=True, text=True, encoding="utf8", timeout=40)
            require(child.returncode == 23, "actual legacy caller failed before planned exit: " + child.stderr[-1000:])
            saved = json.loads(receipt.read_text(encoding="utf8"))
            require(saved["effective_parallel_agents"] == 3 and saved["effective_max_runtime_seconds"] == 37 and Path(saved["session_path"]).is_dir(), "caller exit lost its selected preference observation/session")
        else: observe()
        return {"actualOwner": "_invoke_engine", "legacyPlanningBackend": True, "externalProviderOrProductExecution": False}


def _mission_stop(root, category, identity):
    import argparse
    import contextlib
    import io
    from dataclasses import asdict
    from . import cli
    from .mission_control import ControlRoomStore, DelegatedRuntimeSession
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None, FLUXIO_MISSION_ACTION_COMPACT="1"):
        store = ControlRoomStore(root); workspace = store.load_workspaces()[0]
        mission = store.create_mission(workspace_id=workspace.workspace_id, runtime_id="local-owned", objective="Owned terminal history",
                                       success_checks=[], mode="Autopilot", verification_commands=[], max_runtime_seconds=0)
        literal = TEXT.get(category, "owned terminal history é›ª")
        count = 600 if category == "huge" else 0 if category == "empty" else 3
        history = [DelegatedRuntimeSession(delegated_id=f"terminal-{index}", runtime_id="local-owned", launch_command=literal,
                   status=("completed", "failed", "stopped")[index % 3], detail=literal, changed_files=[literal]) for index in range(count)]
        mission.delegated_runtime_sessions = history; store.update_mission(mission)
        exact = [asdict(item) for item in history]
        def observe():
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = cli.cmd_mission_action(argparse.Namespace(root=str(root), mission_id=mission.mission_id, action="stop"))
            require(code == 0 and store.get_mission(mission.mission_id).state.status == "stopped"
                    and [asdict(item) for item in store.get_mission(mission.mission_id).delegated_runtime_sessions] == exact,
                    "actual stop rewrote terminal delegated history")
            return json.loads(output.getvalue())
        program = """import argparse,os,sys
from grant_agent.cli import cmd_mission_action
code=cmd_mission_action(argparse.Namespace(root=sys.argv[1],mission_id=sys.argv[2],action='stop'));sys.stdout.flush()
os._exit(23 if sys.argv[3]=='exit' and code==0 else code)
"""
        if category == "permissions":
            before = store.missions_path.read_bytes()
            with _sharing_denied(store.missions_path): refusal(observe, (OSError,))
            require(store.missions_path.read_bytes() == before, "OS-denied stop changed mission history")
        elif category in {"interrupted", "concurrency"}:
            def child(_): return _run_child([sys.executable, "-c", program, str(root), mission.mission_id, "exit" if category == "interrupted" else "return"], capture_output=True, text=True, encoding="utf8", timeout=40)
            with ThreadPoolExecutor(max_workers=4) as pool: children = list(pool.map(child, range(8 if category == "concurrency" else 1)))
            require(all(item.returncode == (23 if category == "interrupted" else 0) for item in children), "actual stop caller failed: " + " | ".join(item.stderr[-400:] for item in children if item.returncode not in {0, 23}))
            observe()
        elif category == "stale":
            mission.delegated_runtime_sessions[0].detail = "independently saved current terminal history"
            store.update_mission(mission); exact = [asdict(item) for item in mission.delegated_runtime_sessions]
            observe()
        else: observe()
        return {"actualCLICommand": "mission-action stop", "terminalHistoryRows": count, "runtimeOrSupervisorProcesses": 0}


def _workspace_command(root, category, identity):
    import argparse
    import contextlib
    import io
    from . import cli
    from .mission_control import ControlRoomStore
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_CLUSTER_ROOT=None):
        store = ControlRoomStore(root)
        base = dict(root=str(root), name="Owned CLI workspace é›ª", path=str(root / "selected"), default_runtime="local-owned",
                    user_profile="builder", preferred_harness="legacy_autonomous_engine", routing_strategy="uniform_quality",
                    route_overrides_json='[{"role":"planner","provider":"minimax","model":"MiniMax-M2.7","effort":"high"}]',
                    auto_optimize_routing="true", openai_codex_auth_mode="none", minimax_auth_mode="minimax-portal-oauth",
                    commit_message_style="detailed", execution_target_preference="isolated_worktree", workspace_id=None, skip_snapshot=True)
        def direct(values):
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = cli.cmd_workspace_save(argparse.Namespace(**values))
            require(code == 0, "actual workspace command refused its owned selected values")
            payload = json.loads(output.getvalue())
            require("snapshot" not in payload and payload["workspace"]["preferred_harness"] == values["preferred_harness"], "workspace compact command lost saved preferences")
            return payload["workspace"]
        saved = direct(base)
        program = """import json,os,sys,argparse
from grant_agent.cli import cmd_workspace_save
values=json.loads(sys.argv[1]); code=cmd_workspace_save(argparse.Namespace(**values))
sys.stdout.flush()
os._exit(23 if sys.argv[2]=='exit' and code==0 else code)
"""
        if category == "permissions":
            before = store.workspaces_path.read_bytes()
            with _sharing_denied(store.workspaces_path): refusal(lambda: direct({**base, "name": "denied replacement"}), (OSError,))
            require(store.workspaces_path.read_bytes() == before, "OS-denied workspace command altered saved profiles")
        elif category == "interrupted":
            values = {**base, "name": "persisted before caller exit23", "workspace_id": saved["workspace_id"]}
            child = _run_child([sys.executable, "-c", program, json.dumps(values), "exit"], capture_output=True, text=True, encoding="utf8", timeout=30)
            require(child.returncode == 23 and store.get_workspace(saved["workspace_id"]).name == values["name"], "abrupt actual CLI caller exit lost committed preferences: " + child.stderr[-800:])
        else:
            values = [{**base, "path": str(root / f"selected-{index}"), "name": f"independent profile {index}"} for index in range(8)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                children = list(pool.map(lambda value: _run_child([sys.executable, "-c", program, json.dumps(value), "return"], capture_output=True, text=True, encoding="utf8", timeout=40), values))
            require(all(child.returncode == 0 for child in children), "parallel actual CLI preference command failed: " + " | ".join(child.stderr[-400:] for child in children if child.returncode))
            current = {workspace.name: workspace for workspace in ControlRoomStore(root).load_workspaces()}
            require(all(value["name"] in current and current[value["name"]].root_path == value["path"] for value in values), "parallel independently selected workspace writes lost a saved profile")
        return {"actualCLICommand": "workspace-save", "savedSelectedPreferences": True, "providerOrSnapshotCalls": 0}


def _setup_catalog(root, category, identity):
    from dataclasses import asdict
    from .models import RuntimeInstallStatus
    from .snapshot_cache import save_persistent_snapshot_cache
    from .runtimes import invalidate_runtime_status_cache
    from .cli_catalog import build_catalog
    from .progressive_setup import update_first_run_state, build_progressive_setup, _state_path
    from .neyvia_browser import BrowserService
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned cached runtime metadata é›ª")
    statuses = [] if category == "empty" else [RuntimeInstallStatus(runtime_id="claude-code" if index == 0 else "declared-" + str(index), label=literal if category != "huge" else "owned " + str(index), detected=False, doctor_summary="Explicit generated cached declaration; no installed runtime observation") for index in range(1000 if category == "huge" else 2)]
    save_persistent_snapshot_cache(root, "runtime_statuses", [asdict(value) for value in statuses])
    update_first_run_state(root, {"permissionsReviewed": True, "skippedRuntimeIds": ["claude-code"], "goals": ["software"]})
    browser = BrowserService(root)
    if identity.endswith("selection"):
        def observe():
            value = build_catalog(root, force=False, with_sizes=True, size_runtime_ids={"claude-code"})
            require(value["optional"] and value["continueWithoutAny"] and len(value["entries"]) == len(statuses)
                    and [row["label"] for row in value["entries"]] == [row.label for row in statuses]
                    and all(("size" in row) == (row["runtimeId"] == "claude-code") for row in value["entries"]), "actual catalog expanded selected size lookup or changed cached declaration labels/optional continuation")
            for row in value["entries"]:
                if "size" in row: require(row["size"]["bytes"] is None, "enforced network refusal invented a verified package size")
            return value
    else:
        def observe():
            state = browser.view()
            require(state["runtime"]["connected"] is False and state["headless"]["connected"] is False, "fresh actual browser service fabricated a live native runtime")
            value = build_progressive_setup(root, force=False, provider_presence={}, browser_state=state)
            essentials = value["stages"][0]["items"]
            blocked = [row["itemId"] for row in essentials if row["requiredForMission"] and row["status"] != "ready"]
            require(value["shellCanOpen"] and value["resumable"] and value["blockingItemIds"] == blocked
                    and value["missionCanStart"] is (not blocked) and "model_or_runtime" in blocked
                    and value["browser"] == state and len(value["stages"]) == 3 and value["stages"][1]["continueWithoutAny"]
                    and all(row["selected"] is (row["itemId"] != "runtime:claude-code" or category == "permissions") for row in value["stages"][1]["items"]), "actual setup projection lost saved selection/gating or fabricated browser/provider readiness")
            return value
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: observe(), range(8)))
        require(len(values) == 8, "parallel catalog/setup observations failed to complete")
    elif category == "permissions" and identity.endswith("view"):
        before = _state_path(root).read_bytes()
        with _sharing_denied(_state_path(root)):
            value = observe()
            require("permission_review" in value["blockingItemIds"] and value["state"]["permissionsReviewed"] is False, "unreadable saved permission choices fabricated reviewed authority")
        require(_state_path(root).read_bytes() == before, "read-denied setup view changed saved choices")
    elif category == "stale":
        observe(); statuses[:] = [RuntimeInstallStatus(runtime_id="claude-code", label="new current cached declaration", detected=False)]
        invalidate_runtime_status_cache(root); save_persistent_snapshot_cache(root, "runtime_statuses", [asdict(value) for value in statuses])
        update_first_run_state(root, {"permissionsReviewed": False})
        value = observe()
        if identity.endswith("view"): require("permission_review" in value["blockingItemIds"], "fresh setup retained old reviewed permission state")
    else: observe()
    return {"actualCachedRuntimeCatalog": True, "installedDoctorCalled": False, "actualBrowserServiceDisconnected": True, "renderedUiClaim": False}


def _cluster_rows(root, category, identity):
    from .cluster import ClusterRegistry
    from .proofs_a_cli_scheduler import environment
    kind = identity.rsplit(".", 1)[-1]
    literal = TEXT.get(category, "owned scheduler boundary é›ª")
    with environment(FLUXIO_CLUSTER_ROOT=None, FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_HOST_ID="c7d-owned"):
        registry = ClusterRegistry(root, use_configured_root=False)
        if category == "concurrency" and kind in {"expire", "stale"}:
            connect = registry._connect
            def paced_connection():
                db = connect()
                def trace(statement):
                    # Widen the real SQLite read/update interleaving. This trace
                    # changes scheduling only; every query/effect stays real.
                    if ("UPDATE leases SET status = 'expired'" in statement
                            or "UPDATE hosts SET online = 0" in statement):
                        time.sleep(.05)
                db.set_trace_callback(trace)
                return db
            registry._connect = paced_connection
        host = {"hostId": "c7d-owned", "hostType": "workstation", "capabilities": ["owned." + literal], "maxConcurrentJobs": 2, "workspaceMappings": {"owned": str(root)}}
        count = 0 if category == "empty" else 32 if category == "huge" and kind in {"expire", "stale", "load"} else 2
        if count:
            registry.heartbeat_host(host)
        def enqueue(index):
            return registry.upsert_job(dedupe_key="owned-" + str(index), mission_id="owned", workspace_id="owned", runtime_id="", required_capabilities=["owned." + literal] if count else [], payload={"literal": literal} if category != "empty" else {})
        jobs = [enqueue(i) for i in range(count)]
        def claims():
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda _: registry.claim_next_job(host), range(8)))
            active = [row for row in values if row.get("job")]
            require(len(active) == min(2, count) and len({row["job"]["jobId"] for row in active}) == len(active), "parallel scheduler claims exceeded actual capacity or reused one job")
            return active
        def prepare_leases():
            leases = [registry._create_lease(job["jobId"], "c7d-owned", lease_ttl_seconds=120) for job in jobs]
            require(all(registry.get_job(job["jobId"])["leaseId"] == lease["leaseId"] and registry.get_lease(lease["leaseId"])["jobId"] == job["jobId"] for job, lease in zip(jobs, leases)), "actual lease creation lost durable exact job/host affinity")
            return leases
        def age_leases():
            leases = prepare_leases()
            with registry._connect() as db:
                db.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00Z'")
            return leases
        def age_hosts():
            for index in range(count):
                registry.heartbeat_host({**host, "hostId": "stale-" + str(index)})
            with registry._connect() as db:
                db.execute("UPDATE hosts SET last_heartbeat_at='2000-01-01T00:00:00Z' WHERE online=1")
        if category == "interrupted":
            argument = {"kind": kind, "host": host, "jobs": jobs, "literal": literal}
            if kind == "expire": age_leases()
            elif kind == "stale": age_hosts()
            elif kind == "load": prepare_leases()
            command_path = root / "command.json"; command_path.write_text(json.dumps(argument), encoding="utf8")
            program = """import os,sys,json
from pathlib import Path
from grant_agent.cluster import ClusterRegistry
r=ClusterRegistry(sys.argv[1],use_configured_root=False);a=json.load(open(sys.argv[2],encoding='utf8'));k=a['kind']
if k=='job': r.upsert_job(dedupe_key='after-exit',mission_id='owned',workspace_id='owned',runtime_id='',payload={'literal':a['literal']})
elif k=='claim': r.claim_next_job(a['host'])
elif k=='lease': r._create_lease(a['jobs'][0]['jobId'],'c7d-owned',lease_ttl_seconds=120)
elif k=='expire': r.expire_stale_leases()
elif k=='stale': r.mark_stale_hosts(stale_seconds=1)
elif k=='load':
 with r._connect() as db:r._refresh_host_load_db(db,'c7d-owned')
os._exit(23)
"""
            child = _run_child([sys.executable, "-c", program, str(root), str(command_path)], capture_output=True, timeout=30)
            require(child.returncode == 23, "owned scheduler caller did not reach intended committed boundary before exit23")
            if kind == "job": require(any(row["payload"] == {"literal": literal} and row["dedupeKey"] == "after-exit" for row in registry.list_jobs(limit=100)), "upsert committed before exit lost its exact reopened payload")
            elif kind in {"lease", "claim"}: require(registry.get_job(jobs[0]["jobId"])["leaseId"] and registry.get_host("c7d-owned")["currentLoad"] == 1, "lease/claim committed before exit lost reopened owner affinity/load")
            elif kind == "expire": require(all(registry.get_job(row["jobId"])["status"] == "queued" for row in jobs) and registry.get_host("c7d-owned")["currentLoad"] == 0, "expired lease committed before exit retained active ownership/load")
            elif kind == "stale": require(not any(row["online"] for row in registry.list_hosts()), "stale host update committed before exit lost offline observation")
            else: require(registry.get_host("c7d-owned")["currentLoad"] == count, "load committed before exit lost actual active lease count")
            return {"exitCode": 23, "reopenedBoundary": kind, "runtimeChildrenStarted": 0}
        if kind == "job":
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: rows = list(pool.map(lambda _: enqueue(0), range(8)))
                require(len({row["jobId"] for row in rows}) == 1, "concurrent identical job upsert created multiple canonical owners")
            else: rows = [enqueue(0)]
            require(registry.get_job(rows[0]["jobId"])["payload"] == ({"literal": literal} if category != "empty" else {}), "reopened queued job lost exact original payload")
            if category == "stale":
                updated = registry.upsert_job(dedupe_key="owned-0", mission_id="owned", workspace_id="owned", runtime_id="", payload={"literal": "new-current"})
                newer = registry.upsert_job(dedupe_key="fresh-key", mission_id="owned", workspace_id="owned", runtime_id="", payload={"literal": "new-current"})
                require(updated["jobId"] == rows[0]["jobId"] and registry.get_job(updated["jobId"])["payload"] == {"literal": literal}
                        and newer["jobId"] != updated["jobId"] and registry.get_job(newer["jobId"])["payload"] == {"literal": "new-current"}, "deduplicated upsert overwrote canonical payload or fresh request retained old data")
        elif kind == "choose":
            target = jobs[0] if jobs else {"requiredCapabilities": [], "runtimeId": ""}
            chosen = registry.choose_host(target, preferred_host="c7d-owned", allow_remote=False, allow_nas_fallback=False)
            require((chosen.get("hostId") == "c7d-owned") is bool(count), "host choice ignored actual declared capability or online state")
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: selected = list(pool.map(lambda _: registry.choose_host(target, preferred_host="c7d-owned", allow_nas_fallback=False), range(8)))
                require(all(row.get("hostId") == "c7d-owned" for row in selected), "parallel host selectors lost exact eligible local owner")
            if category in {"stale", "offline"}:
                with registry._connect() as db: db.execute("UPDATE hosts SET online=0 WHERE host_id='c7d-owned'")
                require(registry.choose_host(target, preferred_host="c7d-owned", allow_nas_fallback=False) == {}, "offline/revoked host remained eligible for local dispatch")
        elif kind == "claim":
            active = claims()
            require(registry.get_host("c7d-owned")["currentLoad"] == len(active), "reopened claim load differs from distinct active owner leases")
            if active:
                first = active[0]
                wrong = registry.heartbeat_lease(lease_id=first["lease"]["leaseId"], host_id="foreign")
                require(not wrong["ok"], "foreign host extended selected claim lease")
        elif kind == "lease":
            if jobs:
                if category == "concurrency":
                    with ThreadPoolExecutor(max_workers=4) as pool: leases = list(pool.map(lambda _: registry._create_lease(jobs[0]["jobId"], "c7d-owned", lease_ttl_seconds=120), range(8)))
                    require(len({row["leaseId"] for row in leases}) == 1 and registry.get_host("c7d-owned")["currentLoad"] == 1, "competing exact lease creation duplicated execution owner or load")
                else: prepare_leases()
            else: require(registry._create_lease("absent", "c7d-owned", lease_ttl_seconds=120) == {}, "missing job acquired execution lease")
        elif kind == "load":
            if not count: registry.heartbeat_host(host)
            prepare_leases()
            with registry._connect() as db:
                actual = registry._refresh_host_load_db(db, "c7d-owned")
            require(actual == count and registry.get_host("c7d-owned")["currentLoad"] == count, "refreshed load differs from actual durable active lease count")
            if category == "concurrency":
                def observe(_):
                    with registry._connect() as db: return registry._refresh_host_load_db(db, "c7d-owned")
                with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(observe, range(8)))
                require(values == [count] * 8, "parallel refreshed host loads diverged from same active leases")
        elif kind == "expire":
            leases = age_leases()
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: expired = list(pool.map(lambda _: registry.expire_stale_leases(), range(8)))
                require(sum(expired) == count, f"concurrent lease expiry counted one owner more than once: {expired} versus {count} actual expired leases")
            else: require(registry.expire_stale_leases() == count, "expired durable lease count differs")
            require(all(registry.get_lease(row["leaseId"])["status"] == "expired" and registry.get_job(row["jobId"])["status"] == "queued" for row in leases), "expired lease retained execution ownership or failed to requeue selected job")
        else:
            age_hosts()
            expected = count + (1 if count else 0)
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool: values = list(pool.map(lambda _: registry.mark_stale_hosts(stale_seconds=1), range(8)))
                require(sum(values) == expected, f"concurrent stale host transitions counted same host repeatedly: {values} versus {expected} actual online hosts")
            else: require(registry.mark_stale_hosts(stale_seconds=1) == expected, "actual stale heartbeat count differs")
            require(not any(row["online"] for row in registry.list_hosts()), "stale heartbeat still admitted online host")
        return {"actualSeededJobs": count, "ownerBoundary": kind, "runtimeChildrenStarted": 0, "networkCalls": 0,
                "realSqlTraceScheduling": category == "concurrency" and kind in {"expire", "stale"}}


def _archive(root, category, identity):
    import sqlite3
    from email.message import EmailMessage
    from .communication_archive import inspect_communication_archive, MAX_BODY_PREVIEW
    from .ecosystem_fabric import NeyviaEcosystemFabric
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned archive message é›ª")
    source = root / "owned-é›ª.eml"
    def save(body):
        message = EmailMessage(); message["From"] = "owned@example.invalid"; message["Subject"] = "Owned selected mail"
        message.set_content(body); message.add_attachment((body or "owned").encode(), maintype="application", subtype="octet-stream", filename="owned.bin")
        source.write_bytes(message.as_bytes())
    save(literal); before = source.read_bytes()
    service = NeyviaEcosystemFabric(root)
    account = service.register_communication_account({"label": "Owned local archive", "route": "file-import", "state": "connected", "permissions": ["read"]})
    request = {"accountId": account["accountId"], "sourcePath": str(source), "userInitiated": True}
    def observe():
        value = inspect_communication_archive(source) if identity.endswith("inspect") else service.import_communication_archive(request)
        summary = value if identity.endswith("inspect") else value["summary"]
        digest = hashlib.sha256(source.name.encode() + hashlib.sha256(source.read_bytes()).digest()).hexdigest()
        require(value["sourceDigest"] == digest and summary["messageCount"] == summary["attachmentCount"] == 1
                and summary["messages"][0]["bodyPreview"] == " ".join(literal.split())[:MAX_BODY_PREVIEW], "real selected archive parser/import lost original content digest, exact summary or bounded body")
        if identity.endswith("import"):
            with NeyviaEcosystemFabric(root)._connection() as db:
                row = db.execute("SELECT source_digest, summary_json FROM communication_imports WHERE import_id=?", (value["importId"],)).fetchone()
            require(row["source_digest"] == digest and json.loads(row["summary_json"]) == summary and value["state"] == "imported-local", "reopened actual archive import differs from selected parser summary")
        return value
    if category == "permissions":
        with service._connection() as db:
            count = db.execute("SELECT COUNT(*) FROM communication_imports").fetchone()[0]
        with _sharing_denied(source):
            error = refusal(observe, (OSError, sqlite3.Error, ValueError, RuntimeError))
        with service._connection() as db:
            require(db.execute("SELECT COUNT(*) FROM communication_imports").fetchone()[0] == count, "OS-denied source inserted fabricated archive import")
        require(source.read_bytes() == before, "denied parser/import changed selected source")
        return {"refusal": error, "fabricatedImports": 0}
    if category == "interrupted":
        request_path = root / "request.json"; request_path.write_text(json.dumps(request), encoding="utf8")
        program = "import os,sys,json;from grant_agent.ecosystem_fabric import NeyviaEcosystemFabric;s=NeyviaEcosystemFabric(sys.argv[1]);s.import_communication_archive(json.load(open(sys.argv[2],encoding='utf8')));os._exit(23)"
        child = _run_child([sys.executable, "-c", program, str(root), str(request_path)], capture_output=True, timeout=30)
        with service._connection() as db:
            rows = db.execute("SELECT source_digest,summary_json FROM communication_imports").fetchall()
        require(child.returncode == 23 and len(rows) == 1 and rows[0]["source_digest"] == hashlib.sha256(source.name.encode() + hashlib.sha256(before).digest()).hexdigest()
                and json.loads(rows[0]["summary_json"])["messages"][0]["bodyPreview"] == " ".join(literal.split())[:MAX_BODY_PREVIEW], "archive import committed before abrupt caller exit lost reopened selected source identity or summary")
        return {"exitCode": 23, "reopenedImports": 1}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: observe(), range(8)))
        if identity.endswith("inspect"):
            require(values == [values[0]] * 8, "concurrent selected archive inspections diverged")
        else:
            require(len({r["importId"] for r in values}) == 8, "independent initiated imports collided in identity")
    elif category == "stale":
        old = observe(); literal = "Current selected source revision é›ª"; save(literal); fresh = observe()
        require(fresh["sourceDigest"] != old["sourceDigest"], "fresh selected archive retained previous source digest")
    else:
        observe()
    if identity.endswith("import"):
        with service._connection() as db:
            count = db.execute("SELECT COUNT(*) FROM communication_imports").fetchone()[0]
        refusal(lambda: service.import_communication_archive({**request, "userInitiated": False}))
        unsupported = root / "unsupported.msg"; unsupported.write_bytes(b"owned unsupported format")
        refusal(lambda: service.import_communication_archive({**request, "sourcePath": str(unsupported)}))
        with service._connection() as db:
            require(db.execute("SELECT COUNT(*) FROM communication_imports").fetchone()[0] == count, "uninitiated/unsupported archive request inserted import")
    require(category == "stale" or source.read_bytes() == before, "selected archive inspection/import changed source bytes")
    return {"selectedMessageCount": 1, "exactDigestAndSummary": True, "networkCalls": 0}


def _durable_cli_denial(root, category, identity):
    import sqlite3
    from .edge_fixture_native import _sharing_denied
    suffix = identity.rsplit(".", 1)[-1]
    if identity.startswith("a-cli.crash."):
        from .crashproof import CrashProofStore
        store = CrashProofStore(root)
        now = "2026-10-04T12:00:00Z"
        task = store.submit_task(mission_id="owned", kind="local", idempotency_key="owned", payload={"literal": "selected"}, now=now)
        result_set = store.create_result_set(mission_id="owned", kind="local")
        store.add_result_item(result_set["resultSetId"], payload={"literal": "selected"}, dedupe_key="owned")
        if suffix == "recover":
            store.claim_next(worker_id="owned", lease_seconds=1, now=now)
        actions = {"submit": lambda: store.submit_task(mission_id="owned", kind="local", idempotency_key="new", payload={}),
                   "claim": lambda: store.claim_next(worker_id="refused"),
                   "transition": lambda: store.transition_task(task["taskId"], "cancelled"),
                   "recover": lambda: store.recover_interrupted(now="2026-10-04T12:02:00Z"),
                   "result": lambda: store.add_result_item(result_set["resultSetId"], payload={}, dedupe_key="new"),
                   "summary": lambda: store.summarize_result_set(result_set["resultSetId"])}
        action = actions[suffix]; path = store.database_path
    elif identity.startswith("a-cli.continuity."):
        from .continuity_policy import MissionContinuityStore
        store = MissionContinuityStore(root); store.create_or_update("owned", patch={"objective": "selected"})
        path = store._record_path("owned"); previous = store._previous_path("owned")
        old = path.read_bytes(); prior = previous.read_bytes()
        action = (lambda: store.record_tool_attempt("owned", tool="read", idempotency_key="new", action={}, outcome="completed")) if suffix == "attempt" else lambda: store.recover("owned")
        with _sharing_denied(path), _sharing_denied(previous):
            if suffix == "recovery":
                result = action()
                require(result["status"] == "missing" and result["missionId"] == "owned" and "record" not in result and "duplicateProtection" not in result,
                        "unreadable continuity generations fabricated a recoverable record/action lineage")
                error = {"unavailableSelectedRecord": True, "returnedStatus": "missing"}
            else:
                error = refusal(action)
        require(path.read_bytes() == old and previous.read_bytes() == prior, "OS-denied continuity operation changed either saved generation")
        return {"refusal": error, "preservedGenerations": 2}
    else:
        from .cluster import ClusterRegistry
        store = ClusterRegistry(root, use_configured_root=False)
        host = {"hostId": "owned", "hostType": "workstation", "capabilities": ["command.run"], "maxConcurrentJobs": 1}
        store.heartbeat_host(host)
        job = store.upsert_job(mission_id="owned", workspace_id="owned", runtime_id="", payload={"literal": "selected"})
        def load():
            with store._connect() as db:
                return store._refresh_host_load_db(db, "owned")
        actions = {"choose": lambda: store.choose_host(job, preferred_host="owned", allow_remote=True, allow_nas_fallback=False),
                   "job": lambda: store.upsert_job(mission_id="new", workspace_id="owned", runtime_id="", payload={}),
                   "claim": lambda: store.claim_next_job(host), "stale": lambda: store.mark_stale_hosts(stale_seconds=1), "load": load}
        action = actions[suffix]; path = store.db_path
    def snapshot():
        db = sqlite3.connect(path)
        try:
            return {table: sorted(db.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr)
                    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
    before = snapshot()
    with _sharing_denied(path):
        error = refusal(action, (sqlite3.Error, OSError, ValueError, RuntimeError))
    require(snapshot() == before, "OS-denied durable CLI owner changed selected or sibling table rows")
    return {"refusal": error, "preservedDurableTables": len(before), "networkCalls": 0}


def _codex_assets(root, category, identity):
    from .codex_import import CodexAssetImporter, load_latest_codex_import_rows
    from .edge_fixture_native import _sharing_denied
    home = root / "owned-home"; home.mkdir()
    instructions = home / "AGENTS.md"; instructions.write_text("Owned local instructions", encoding="utf8")
    skill = home / "skills" / "owned" / "SKILL.md"; skill.parent.mkdir(parents=True)
    literal = TEXT.get(category, "owned asset instruction é›ª")
    skill.write_text(literal, encoding="utf8")
    source_bytes = skill.read_bytes()
    ignored = skill.parent / "unsupported.bin"; ignored.write_bytes(b"unimported-owned-data")
    importer = CodexAssetImporter(root, home)
    def audit():
        value = importer.audit()
        rows = value["personalSkills"]
        require(len(rows) == 1 and rows[0]["sha256"] == hashlib.sha256(skill.read_bytes()).hexdigest()
                and rows[0]["sizeBytes"] == skill.stat().st_size and value["globalInstructions"]["sha256"] == hashlib.sha256(instructions.read_bytes()).hexdigest()
                and value["privateStateInventory"]["contentImported"] is False and value["counts"]["personalSkills"] == 1,
                "actual owned Codex audit lost selected bytes, global instruction identity or honest read-only inventory")
        return value
    def imported():
        receipt = importer.import_assets()
        catalog_path = Path(receipt["catalogPath"])
        catalog = json.loads(catalog_path.read_text(encoding="utf8"))
        require(receipt["catalogSha256"] == hashlib.sha256(catalog_path.read_bytes()).hexdigest()
                and receipt["importedSkillCount"] == len(catalog["importedSkills"]) == 1
                and not receipt["secretsImported"] and not receipt["rawSessionsImported"], "actual import receipt differs from its saved catalog or claims private-state import")
        row = catalog["importedSkills"][0]
        require(Path(row["source"]["path"]).read_bytes() == skill.read_bytes() and not row["enabled"] and row["testStatus"] == "untested"
                and row["promotionState"] == "imported" and row["harnessCompatibility"]["adapterRequired"]
                and not Path(row["source"]["path"]).with_name("unsupported.bin").exists()
                and Path(catalog["globalInstructionCopy"]).read_bytes() == instructions.read_bytes(), "import changed copied bytes, activated unreviewed skill, or copied excluded unsupported file")
        return receipt
    observe = audit if identity.endswith("audit") else imported
    if category == "permissions":
        protected = instructions if identity.endswith("audit") else skill
        before = protected.read_bytes()
        with _sharing_denied(protected):
            if identity.endswith("audit"):
                error = refusal(observe)
            else:
                receipt = importer.import_assets()
                catalog = json.loads(Path(receipt["catalogPath"]).read_text(encoding="utf8"))
                require(receipt["importedSkillCount"] == 0 and catalog["importedSkills"] == []
                        and catalog["personalSkills"][0]["readError"] and not catalog["personalSkills"][0]["importEligible"]
                        and any(row["path"] == "SKILL.md" and row["reason"] == "not_utf8" for row in catalog["skippedFiles"])
                        and load_latest_codex_import_rows(root / ".agent_control") == [], "OS-denied source advertised a copied/usable skill")
                error = {"skippedSelectedSource": True, "copiedSkills": 0}
        require(protected.read_bytes() == before and (not identity.endswith("audit") or not (importer.import_root / "latest.json").exists()), "denied import/audit rewrote source or published false completed pointer")
        return {"refusalOrSafeSkip": error, "privateStateRead": False}
    if category == "stale":
        previous = observe(); skill.write_text("New actual revision é›ª", encoding="utf8")
        fresh = observe()
        if identity.endswith("audit"):
            require(previous["personalSkills"][0]["sha256"] != fresh["personalSkills"][0]["sha256"], "fresh audit retained old source digest")
        else:
            rows = load_latest_codex_import_rows(root / ".agent_control")
            require(len(rows) == 1 and Path(rows[0]["source"]["path"]).read_bytes() == skill.read_bytes()
                    and previous["catalogPath"] != fresh["catalogPath"], "new import pointer retained old skill snapshot")
        return {"freshSelectedBytesObserved": True, "activatedSkills": 0}
    if category == "interrupted":
        program = "import os,sys;from grant_agent.codex_import import CodexAssetImporter;CodexAssetImporter(sys.argv[1],sys.argv[2]).import_assets();os._exit(23)"
        child = _run_child([sys.executable, "-c", program, str(root), str(home)], capture_output=True, timeout=30)
        rows = load_latest_codex_import_rows(root / ".agent_control")
        require(child.returncode == 23 and len(rows) == 1 and Path(rows[0]["source"]["path"]).read_bytes() == source_bytes,
                "completed import before owned caller exit23 lost reopened copied bytes")
        return {"exitCode": 23, "reopenedImportedSkills": 1, "activatedSkills": 0}
    if category == "concurrency":
        count = 32 if identity.endswith("import") else 8
        if identity.endswith("import"):
            import threading
            done = threading.Event()
            def reader():
                observations = 0
                while not done.is_set():
                    rows = load_latest_codex_import_rows(root / ".agent_control")
                    if rows:
                        require(len(rows) == 1 and not rows[0]["enabled"] and Path(rows[0]["source"]["path"]).read_bytes() == source_bytes,
                                "concurrent pointer reader observed incomplete copied skill or enabled unreviewed asset")
                        observations += 1
                    time.sleep(.002)
                return observations
            with ThreadPoolExecutor(max_workers=9) as pool:
                future = pool.submit(reader)
                try:
                    results = list(pool.map(lambda _: observe(), range(count)))
                finally:
                    done.set()
                require(future.result(10) > 0, "concurrent reader never observed a published snapshot")
        else:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: observe(), range(count)))
        if identity.endswith("audit"):
            require(all(r["personalSkills"] == results[0]["personalSkills"] for r in results), "concurrent read-only asset audits diverged")
        else:
            require(len({r["snapshotRoot"] for r in results}) == count, "parallel imports shared or overwrote a snapshot root")
            pointer = json.loads((importer.import_root / "latest.json").read_text(encoding="utf8"))
            require(pointer["catalogPath"] in {r["catalogPath"] for r in results} and len(load_latest_codex_import_rows(root / ".agent_control")) == 1,
                    "concurrent latest pointer selected an incomplete/unknown import")
    else:
        observe()
    require(skill.read_bytes() == source_bytes, "read/import changed original selected asset")
    return {"ownedSkillBytes": len(source_bytes), "selectedSourcePreserved": True, "activatedSkills": 0, "networkCalls": 0}


def _mods(root, category, identity):
    import sqlite3
    from . import claude_code_mods as mods
    from .ui_command_bus import UICommandBus
    from .proofs_a_cli_scheduler import environment
    from .edge_fixture_native import _sharing_denied
    literal = TEXT.get(category, "owned mod report é›ª")
    with environment(NEYVIA_UI_STATE_ROOT=str(root)):
        bus = UICommandBus(root)
        if identity.endswith("launch"):
            declared = {"NEYVIA_UI_STATE_ROOT": str(root), "NEYVIA_UI_BACKEND_URL": "http://127.0.0.1:" + os.environ["NEYVIA_C7_PORT"],
                        "CLAUDE_CODE_PLUGIN_DIRS": os.pathsep.join([str(mods.PLUGIN_DIR), "owned-" + literal.replace("\x00", "")])}
            bus.put(mods.SETTING, {"enabled": True})
            def observe():
                result = mods.launch_env(declared)
                parts = result["CLAUDE_CODE_PLUGIN_DIRS"].split(os.pathsep)
                require(parts == [str(mods.PLUGIN_DIR), "owned-" + literal.replace("\x00", "")] and result["NEYVIA_PYTHON"], "launch environment lost own plugin uniqueness or literal companion directory")
                require(mods.launch_env({"NEYVIA_UI_STATE_ROOT": str(root)}) == {}, "missing backend fabricated active plugin environment")
                return result
            if category == "permissions":
                with _sharing_denied(bus.path):
                    require(mods.launch_env(declared) == {}, "unreadable plugin setting bypassed disabled launch environment")
            elif category == "stale":
                observe(); bus.put(mods.SETTING, {"enabled": False})
                require(mods.launch_env(declared) == {}, "fresh launch retained revoked plugin setting")
            elif category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool:
                    values = list(pool.map(lambda _: observe(), range(8)))
                require(values == [values[0]] * 8, "concurrent launch metadata lost same saved setting")
            else:
                observe()
            return {"pluginDirectories": 2, "claudeChildrenStarted": 0, "networkCalls": 0}
        def report(index=0):
            data = {"session": "owned", "kind": "session", "cwd": literal, "version": literal, "runId": "owned"}
            mods.record_report(bus, data)
            mods.record_report(bus, {"session": "owned", "kind": "checklist", "items": [{"text": literal or "owned", "status": "completed"}, {"text": "ignored", "status": "unknown"}]})
            return mods.record_report(bus, {"session": "owned", "kind": "edit", "path": "file-" + str(index) + ".py"})
        if category == "permissions":
            before = bus.get(mods.RUNS)
            with _sharing_denied(bus.path):
                error = refusal(report, (sqlite3.Error, OSError, RuntimeError, ValueError))
            require(bus.get(mods.RUNS) == before, "OS-denied report changed durable mod state")
            return {"refusal": error, "claudeChildrenStarted": 0}
        if category == "interrupted":
            program = "import os,sys;from pathlib import Path;from grant_agent.ui_command_bus import UICommandBus;from grant_agent.claude_code_mods import record_report;os.environ['NEYVIA_UI_STATE_ROOT']=sys.argv[1];record_report(UICommandBus(Path(sys.argv[1])),{'session':'owned','kind':'edit','path':'file-0.py'});os._exit(23)"
            child = _run_child([sys.executable, "-c", program, str(root)], capture_output=True, timeout=30)
            require(child.returncode == 23 and UICommandBus(root).get(mods.RUNS)["owned"]["files"] == ["file-0.py"], "report saved before abrupt caller exit lost reopened exact edit")
            return {"exitCode": 23, "reopenedEdits": 1}
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(report, range(8)))
            expected = {"file-" + str(i) + ".py" for i in range(8)}
        else:
            report(); expected = {"file-0.py"}
        row = UICommandBus(root).get(mods.RUNS)["owned"]
        require(set(row["files"]) == expected and row["checklist"] == [{"text": " ".join((literal or "owned").split())[:300], "status": "completed"}], "saved mod report lost concurrent file edits or filtered checklist bytes")
        if category == "stale":
            mods.record_report(bus, {"session": "owned", "kind": "turn", "state": "error"})
            require(UICommandBus(root).get(mods.RUNS)["owned"]["state"] == "error", "fresh report observer retained old turn state")
        before = bus.get(mods.RUNS)
        for invalid in ({"session": "invalid session", "kind": "edit", "path": "owned"}, {"session": "owned", "kind": "turn", "state": "invented"}, {"session": "owned", "kind": "edit", "path": ""}):
            refusal(lambda invalid=invalid: mods.record_report(bus, invalid))
        require(bus.get(mods.RUNS) == before, "invalid report changed durable sibling reports")
        return {"durableEdits": len(expected), "invalidReportsRefused": 3, "claudeChildrenStarted": 0, "networkCalls": 0}


def _gpu_decisions(root, category, identity):
    from .continuity_policy import MissionContinuityStore
    from .edge_fixture_native import _sharing_denied
    store = MissionContinuityStore(root)
    policy = {"maxConcurrentInstances": 1, "maxEstimatedHourlyCost": 2, "maxEstimatedSessionCost": 4,
              "maxConsecutiveUnchangedObservations": 3, "minObservationIntervalSeconds": 15}
    store.create_or_update("owned", patch={"gpuPolicy": policy})
    path = store._record_path("owned")
    before = path.read_bytes()
    def observe():
        literal = TEXT.get(category, "owned policy observation")
        observed = {"runningInstances": 1, "validCheckpoint": True, "literal": literal}
        proposal = {"action": "start_instance", "paid": True, "estimatedHourlyCost": 1e100 if category == "huge" else 3, "estimatedDurationMinutes": 120}
        result = store.evaluate_gpu_action("owned", proposal, observed)
        require(not result["allowed"] and result["approvalRequired"] and result["preferResume"] and len(result["blockers"]) == 3
                and result["estimatedSessionCost"] == proposal["estimatedHourlyCost"] * 2 and result["observed"] == observed, "GPU paid/capacity/hourly/session-cost/checkpoint decision lost supplied observations")
        require(observed == {"runningInstances": 1, "validCheckpoint": True, "literal": literal}, "GPU decision mutated caller observation")
        destructive = store.evaluate_gpu_action("owned", {"action": "delete_instance"}, {})
        require(destructive["approvalRequired"], "destructive GPU decision lost operator approval requirement")
        bounded = store.evaluate_gpu_action("owned", {"action": "inspect_gpu"}, {"consecutiveUnchangedObservations": 3, "secondsSinceLastObservation": 1})
        override = store.evaluate_gpu_action("owned", {"action": "inspect_gpu", "stateChangeExpected": True}, {"consecutiveUnchangedObservations": 3, "secondsSinceLastObservation": 1})
        require(not bounded["allowed"] and bounded["pollBackoffRequired"] and override["allowed"] and not override["pollBackoffRequired"], "GPU unchanged observation bound ignored state-change override")
        if category == "empty":
            empty = store.evaluate_gpu_action("owned", {}, {})
            require(empty["allowed"] and not empty["approvalRequired"] and empty["estimatedSessionCost"] is None, "empty GPU observation invented paid work/cost or capacity blockage")
        return result
    if category == "permissions":
        previous = store._previous_path("owned"); prior = previous.read_bytes()
        with _sharing_denied(path), _sharing_denied(previous):
            error = refusal(observe)
        require(path.read_bytes() == before and previous.read_bytes() == prior, "OS-denied GPU policy decision rewrote current or previous continuity snapshot")
        return {"refusal": error, "gpuActionsExecuted": 0}
    if category == "stale":
        store.create_or_update("owned", patch={"gpuPolicy": {**policy, "maxConsecutiveUnchangedObservations": 1}})
        result = store.evaluate_gpu_action("owned", {"action": "inspect_gpu"}, {"consecutiveUnchangedObservations": 1, "secondsSinceLastObservation": 60})
        require(not result["allowed"] and result["pollBackoffRequired"] and result["policy"]["maxConsecutiveUnchangedObservations"] == 1, "GPU decision retained previously observed policy after durable change")
        return {"freshPolicyObserved": True, "gpuActionsExecuted": 0}
    if category == "interrupted":
        target = root / "new-owner"
        program = "import os,sys,json;from grant_agent.continuity_policy import MissionContinuityStore;s=MissionContinuityStore(sys.argv[1]);r=s.evaluate_gpu_action('owned',{'action':'start_instance','paid':True},{});assert r['approvalRequired'];os._exit(23)"
        result = _run_child([sys.executable, "-c", program, str(target)], capture_output=True, timeout=30)
        require(result.returncode == 23 and MissionContinuityStore(target).load("owned")["revision"] == 1, "GPU initialization policy did not survive interrupted caller after real saved decision")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: observe(), range(8)))
        require(results == [results[0]] * 8, "parallel GPU policy decisions diverged from same explicit current state")
    else:
        observe()
    require(path.read_bytes() == before, "observing an existing GPU policy wrote progress or issued action")
    return {"paidAndDestructiveApprovalRequired": True, "capacityAndCostBounded": True, "pollOverrideObserved": True, "gpuActionsExecuted": 0, "networkCalls": 0}


def _control_stores(root, category, identity):
    from .mission_control import ControlRoomStore
    from .models import MissionEvent
    from .edge_fixture_native import _sharing_denied
    from dataclasses import asdict
    store = ControlRoomStore(root)
    kind = identity.rsplit(".", 1)[-1]
    if kind == "workspaces":
        profile = store._default_workspace_profile()
        profile.name = "Owned workspace é›ª"
        store.save_workspaces([profile])
        path = store.workspaces_path
        expected = [asdict(profile)]
        def observe():
            result = [asdict(row) for row in store.load_workspaces()]
            require(result == expected == json.loads(path.read_text(encoding="utf8")), "actual workspace projection differs from independently seeded durable rows")
            return result
    elif kind == "events":
        for index in range(5):
            store.append_event(MissionEvent(mission_id="owned", kind=f"event-{index}", message="owned é›ª"))
        path = store.events_path
        with path.open("ab") as stream:
            stream.write(b"malformed-row\n")
        expected = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines()[-3:-1]][::-1]
        def observe():
            result = store.recent_events(3)
            require(result == expected and store.recent_events(0) == [] and store.recent_events(-1) == [], "durable event tail ordering/malformed skip/zero bound changed")
            return result
    else:
        path = store.control_dir / "owned-cache.json"
        expected = {"version": 1, "literal": "owned é›ª"}
        store._write_json_if_changed(path, expected)
        parsed = store._load_json(path, {})
        def observe():
            result = store._load_json(path, {})
            require(result == expected and result is parsed, "unchanged metadata did not reuse the exact cached parse object")
            return result
    before = path.read_bytes()
    if category == "permissions":
        store._invalidate_json_cache(path)
        with _sharing_denied(path):
            if kind == "events":
                require(store.recent_events(3) == [], "OS-denied event reader fabricated durable rows")
                error = {"result": []}
            elif kind == "workspaces":
                error = refusal(store.load_workspaces)
            else:
                fallback = {"readDenied": True}
                require(store._load_json(path, fallback) is fallback, "OS-denied uncached parse fabricated data")
                error = refusal(lambda: store._write_json_if_changed(path, {"version": 2}))
        require(path.read_bytes() == before, "OS-denied control store changed selected durable bytes")
        return {"refusal": error, "durableBytesPreserved": len(before)}
    if category == "stale":
        if kind == "workspaces":
            profile.name = "new generation"; expected = [asdict(profile)]
            store.save_workspaces([profile]); observe()
        elif kind == "events":
            keeper = MissionEvent(mission_id="new", kind="new-generation", message="new")
            path.write_text(json.dumps(asdict(keeper)) + "\n", encoding="utf8")
            expected = [asdict(keeper)]; observe()
        else:
            previous = parsed
            expected = {"version": 2, "literal": "new generation"}
            store._write_json_if_changed(path, expected)
            parsed = store._load_json(path, {})
            require(parsed is not previous and previous == {"version": 1, "literal": "owned é›ª"}, "durable cache write mutated old observations or reused stale parse")
            observe()
        return {"newGenerationObserved": True}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            observed = list(pool.map(lambda _: observe(), range(8)))
        require(observed == [expected] * 8 and path.read_bytes() == before, "parallel control readers changed durable bytes or observed different generations")
        return {"concurrentReaders": 8, "durableBytesPreserved": len(before)}
    observe()
    require(path.read_bytes() == before, "offline control read modified selected durable state")
    return {"networkCalls": 0, "durableBytesPreserved": len(before)}


CLAUDE_LOCAL_PEER = r'''
import json,os,sys,uuid
from pathlib import Path
root=Path(os.environ['C7D_PEER_ROOT']); mode=os.environ.get('C7D_PEER_MODE','turn')
def send(value):
    print(json.dumps(value,ensure_ascii=True),flush=True)
if 'agents' in sys.argv:
    print('[]');sys.exit(0)
sid='owned-'+uuid.uuid4().hex
if '--resume' in sys.argv:
    sid='unexpected-copy' if mode=='fork' else sys.argv[sys.argv.index('--resume')+1]
records=[]
for line in sys.stdin:
    value=json.loads(line);records.append(value)
    if value.get('type')=='user':
        content=value['message']['content'][0]['text'];break
send({'type':'system','subtype':'init','session_id':sid,'model':'owned-protocol'})
if mode in ('reply','interrupt'):
    send({'type':'control_request','request_id':'owned-approval','request':{'subtype':'can_use_tool','tool_name':'Bash','input':{'command':'owned literal'},'tool_use_id':'owned-tool'}})
    for line in sys.stdin:
        value=json.loads(line);records.append(value)
        if value.get('type')=='control_response':
            if value['response']['response'].get('interrupt'):
                (root/('wire-'+sid+'.json')).write_text(json.dumps(records),encoding='utf8');os._exit(23)
            break
    send({'type':'control_request','request_id':'owned-question','request':{'subtype':'can_use_tool','tool_name':'AskUserQuestion','input':{'questions':[{'question':'Owned question','header':'Owned','options':[{'label':'A','description':'Owned'}],'multiSelect':False}]},'tool_use_id':'owned-question-tool'}})
    for line in sys.stdin:
        value=json.loads(line);records.append(value)
        if value.get('type')=='control_response':break
(root/('wire-'+sid+'.json')).write_text(json.dumps(records),encoding='utf8')
send({'type':'assistant','session_id':sid,'message':{'id':'owned-assistant','model':'owned-protocol','content':[{'type':'text','text':content}]}})
send({'type':'result','subtype':'success','is_error':False,'session_id':sid,'result':content,'usage':{'input_tokens':1,'output_tokens':1}})
'''


def _provider_turn(root, category, identity):
    if identity == "providers.claude.events" and category in {"empty", "huge"}:
        from .edge_fixture_mcp_adverse import claude_events
        return claude_events(root, category)
    import threading
    from .connected_sessions.claude import ClaudeAdapter, ClaudeSessionError
    from .connected_sessions.model import TurnOptions
    from .edge_fixture_native import _sharing_denied
    from .proofs_a_providers import _Events
    peer = root / "owned-stdio-peer.py"; peer.write_text(CLAUDE_LOCAL_PEER, encoding="utf8")
    config = root / "owned-config"; config.mkdir()
    mode = "interrupt" if category == "interrupted" else "fork" if category == "stale" and not identity.endswith("reply") else "reply" if identity.endswith("reply") else "turn"
    adapter = ClaudeAdapter(state_root=root, config_dir=config, cli_path=[sys.executable, str(peer)],
                            context_probe=False, interrupt_grace=.1, idle_timeout=8, pending_timeout=8,
                            extra_env={"C7D_PEER_MODE": mode, "C7D_PEER_ROOT": str(root), "NEYVIA_UI_BACKEND_URL": "http://127.0.0.1:48742"}, host={"deviceId": "owned-host", "deviceName": "Owned fixture"})
    literal = TEXT.get(category, "owned prompt")
    if category in {"empty", "huge"} and not identity.endswith("reply"):
        events = []
        error = refusal(lambda: adapter.start_turn(None, literal, TurnOptions(), cwd=str(root), run_id="owned-refused", emit=events.append), (ClaudeSessionError,))
        require(error["detail"] and events == [] and not adapter._runs and not list(root.glob("wire-*.json")), "invalid provider message started a child or emitted a run")
        return {"refusal": error, "providerExecution": False, "startedChildren": 0}
    selected = None
    if mode == "fork":
        selected = "owned-selected"
        folder = config / "projects/owned"; folder.mkdir(parents=True)
        (folder / (selected + ".jsonl")).write_text(json.dumps({"type": "user", "uuid": "owned-prior", "sessionId": selected, "cwd": str(root), "message": {"role": "user", "content": "prior"}}) + "\n", encoding="utf8")
    def execute(index=0):
        run_id = f"owned-{index}"
        events = _Events(); outcome = {}
        def worker():
            try:
                outcome["session"] = adapter.start_turn(selected, "owned request" if identity.endswith("reply") else literal,
                                                        TurnOptions(), cwd=str(root), run_id=run_id, emit=events)
            except BaseException as error:
                outcome["error"] = error
        thread = threading.Thread(target=worker, daemon=True); thread.start()
        try:
            thread.join(.02)
            if "error" in outcome and not events.rows:
                raise outcome["error"]
            if category == "permissions" and not identity.endswith("reply"):
                thread.join(12)
            elif mode in {"reply", "interrupt"}:
                events.wait(lambda e: e.get("type") == "run.state" and e.get("state") == "waiting_approval")
                before = len(events.rows)
                current = adapter._runs[run_id]
                refusal(lambda: current._emit({"type": "notice", "runId": "foreign-run", "sessionId": current.session_id}), (ValueError,))
                require(len(events.rows) == before, "cross-run provider event reached observer before refusal")
                if category == "interrupted":
                    adapter.interrupt(run_id)
                    error = refusal(lambda: adapter.answer(run_id, "owned-approval", {"decision": "approve"}), (ClaudeSessionError,))
                    require("no longer waiting" in error["detail"], "interrupted pending approval remained callable")
                else:
                    response = {"decision": "deny", "message": "owned denial"} if category == "permissions" else {"decision": "approve", "updatedInput": {"literal": literal}}
                    if category == "concurrency":
                        def answer(_):
                            try:
                                adapter.answer(run_id, "owned-approval", response); return "answered"
                            except ClaudeSessionError as exc:
                                require(exc.code == "request_not_pending", "duplicate approval refused with wrong machine code"); return "refused"
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            require(sorted(pool.map(answer, range(2))) == ["answered", "refused"], "competing person replies did not resolve exactly once")
                    else:
                        adapter.answer(run_id, "owned-approval", response)
                    duplicate = refusal(lambda: adapter.answer(run_id, "owned-approval", response), (ClaudeSessionError,))
                    require("no longer waiting" in duplicate["detail"], "stale/duplicate approval was accepted")
                    events.wait(lambda e: e.get("type") == "run.state" and e.get("state") == "waiting_input")
                    answer = literal if literal.strip() else "owned answer"
                    adapter.answer(run_id, "owned-question", {"decision": "approve", "answers": {"q0": answer}})
            thread.join(15)
            require(not thread.is_alive(), "owned finite stdio provider turn did not return")
            finals = [e for e in events.rows if e.get("type") == "run.state" and e.get("state") in {"completed", "failed", "interrupted"}]
            expected = "failed" if mode == "fork" or category == "permissions" and not identity.endswith("reply") else "interrupted" if category == "interrupted" else "completed"
            require(len(finals) == 1 and finals[0]["state"] == expected and finals[0]["runId"] == run_id and (category == "concurrency" or not adapter._runs), "returned provider turn lost exactly-one terminal run receipt: " + repr(outcome.get("error"))[:240] + "; states=" + repr([(r.get("state"), r.get("error")) for r in events.rows if r.get("type") == "run.state"])[:240])
            if "error" in outcome:
                require(expected == "failed" and getattr(outcome["error"], "code", None) in {"cli_exited", "cli_failed"}, "unexpected owned stdio provider refusal")
                return {"terminal": expected, "runId": run_id}
            sid = outcome["session"]
            require(finals[0]["sessionId"] == sid and (sid == selected if selected else sid.startswith("owned-")), "provider silently changed selected run/session identity")
            typed = [e for e in events.rows if e.get("type") in {"item.added", "item.updated"}]
            require(all(e["runId"] == run_id and e["sessionId"] == sid and e["item"]["id"] and isinstance(e["item"]["seq"], int) for e in typed), "actual stdio item events lost typed/run/session identity")
            if identity.endswith("reply") and category != "interrupted":
                wire = json.loads((root / ("wire-" + sid + ".json")).read_text(encoding="utf8"))
                replies = [r["response"]["response"] for r in wire if r.get("type") == "control_response"]
                require(len(replies) == 2 and replies[0]["behavior"] == ("deny" if category == "permissions" else "allow")
                        and (category == "permissions" or replies[0]["updatedInput"] == {"literal": literal})
                        and replies[1]["updatedInput"]["answers"] == {"Owned question": answer.strip()[:20000]}, "actual stdio approval/question reply altered exact updatedInput/answer wire shape")
            return {"terminal": expected, "runId": run_id, "sessionId": sid, "typedEvents": len(typed)}
        finally:
            if thread.is_alive():
                adapter.interrupt(run_id); thread.join(5)
    if category == "permissions" and not identity.endswith("reply"):
        with _sharing_denied(peer):
            result = execute()
        require(not list(root.glob("wire-*.json")), "OS-denied CLI entry emitted protocol wire")
    elif category == "concurrency" and not identity.endswith("reply"):
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(execute, range(4)))
        require(len({r["sessionId"] for r in result}) == 4 and len({r["runId"] for r in result}) == 4, "simultaneous real stdio turns reused identity")
    else:
        result = execute()
    return {"observations": result, "transport": "owned real Python stdio child; production Claude adapter", "providerExecution": False, "networkCalls": 0}


def _provider_reads(root, category, identity):
    from .edge_fixture_providers import _transcript, _adapter_read
    from .connected_sessions import claude_transcript as ct
    from .connected_sessions.claude import ClaudeAdapter
    from .connected_sessions.claude_items import image_token
    from .edge_fixture_native import _sharing_denied
    adapter_id = identity in {"providers.claude.page", "providers.claude.summary", "providers.claude.context", "providers.claude.media"}
    if category == "offline":
        result = _adapter_read(root, category) if adapter_id else _transcript(root, category)
        return {**result, "networkCalls": 0, "providerExecution": False}
    if category == "concurrency":
        _transcript(root, "unicode")
        path = root / "owned-session.jsonl"
        def title(_):
            index = ct.SummaryIndex(path, "owned-session"); index.refresh()
            return index.title
        with ThreadPoolExecutor(max_workers=4) as pool:
            observed = list(pool.map(title, range(8)))
        require(observed == ["Custom e\u0301"] * 8, "parallel actual summary readers lost latest custom title priority")
        return {"summaryReaders": 8, "exactCustomTitle": True}
    if adapter_id:
        _adapter_read(root, "unicode")
        config = root / "owned-config"
        path = config / "projects/owned-project/owned-session.jsonl"
        reader = ClaudeAdapter(config_dir=config, cli_path=[sys.executable, str(root / "inventory-peer.py")], host={"deviceId": "owned-device", "deviceName": "Owned fixture"}, context_probe=False)
        first = json.loads(path.read_text(encoding="utf8").splitlines()[0])
        source = first["message"]["content"][1]["source"]
        token = image_token("image/png", source["data"])
        before = path.read_bytes()
        with _sharing_denied(path):
            if identity.endswith("media"):
                error = refusal(lambda: reader.read_media("owned-session", token))
            else:
                error = refusal(lambda: reader.read("owned-session"))
    else:
        _transcript(root, "unicode")
        path = root / "owned-session.jsonl"; before = path.read_bytes()
        if identity.endswith("read_bytes"):
            observe = lambda: ct.read_bytes(path, 0, len(before))
        elif identity.endswith("title_priority"):
            fresh = ct.SummaryIndex(path, "owned-session")
            observe = fresh.refresh
        else:
            fresh = ct.ItemStore(path, "owned-session")
            observe = lambda: fresh.page(cursor=None, before_seq=None, limit=200)
        with _sharing_denied(path):
            error = refusal(observe)
    require(path.read_bytes() == before, "OS-denied provider read changed selected transcript")
    return {"refusal": error, "sourceBytesPreserved": len(before), "networkCalls": 0, "providerExecution": False}


def _core_rpc(root, category, identity):
    from .neyvia_native_rpc import NativeRpcServer, RpcError, serve
    import io
    from .edge_fixture_native import _sharing_denied
    text = TEXT.get(category, "owned request")
    server = NativeRpcServer(root)
    request = {"jsonrpc": "2.0", "id": text, "method": "native.alive", "params": {}}
    if identity.endswith("rpc-protocol"):
        source = ["not-json", json.dumps({**request, "method": "native.plan.compile"}),
                  json.dumps({**request, "params": [text]}),
                  json.dumps({"jsonrpc": "2.0", "method": "native.alive"}), json.dumps(request)]
        output = io.StringIO()
        require(serve(root, io.StringIO("\n".join(source) + "\n"), output) == 0, "owned JSONL RPC stopped after invalid input")
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        require(len(replies) == 4 and [r["error"]["code"] for r in replies[:3]] == [-32700, -32602, -32602]
                and replies[-1] == {"jsonrpc": "2.0", "id": text, "result": {"alive": True, "version": replies[-1]["result"]["version"], "root": str(root.resolve())}},
                "JSONL error recovery, notification silence, identity or actual root changed")
        observe = lambda: server.dispatch(request)
    elif identity.endswith("rpc-authority"):
        def observe():
            value = server.dispatch({**request, "method": "native.capabilities"})
            authority = value["result"]["authority"]
            require(value["id"] == text and authority["default"] == "read-only"
                    and not authority["deviceCommandOperatorVerifierReady"]
                    and authority["deviceCommandOperatorKeyId"] is None
                    and authority["deviceCommandSignedOperatorAuthorizationRequired"]
                    and not authority["deviceCommandAutomaticRetry"]
                    and not authority["deviceCommandHumanIdentityCryptographicallyVerified"], "RPC advertised unavailable operator authority")
            for name in ("native.device.approvals.approve", "native.device.approvals.deny", "native.device.commands.cancel"):
                error = refusal(lambda: server.dispatch({**request, "method": name, "params": {"humanConfirmed": True, "note": text}}), (RpcError,))
                require("method not found" in error["detail"], "operator-only RPC refusal changed")
            return value
        observe()
    else:
        task = text if category in TEXT else "Diagnose owned reconnect failure"
        if not task.strip():
            error = refusal(lambda: server.dispatch({**request, "method": "native.plan.compile", "params": {"task": task}}), (RpcError,))
            require(error["detail"] == "task is required", "empty task compiled a plan")
            return {"emptyTaskRefused": True, "networkCalls": 0}
        params = {"task": task, "behaviorCapsule": "diagnosis-repair", "resourceMode": "eco", "useLearning": False}
        def observe():
            value = server.dispatch({**request, "method": "native.plan.compile", "params": params})
            plan = value["result"]
            require(value["id"] == text and plan["capsule"]["id"] == "diagnosis-repair"
                    and plan["resourceProfile"]["mode"] == "eco" and bool(plan["compiledSkillPlan"]), "RPC compiled a different behavior/resource/skill binding")
            return value
        observe()
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(lambda _: observe(), range(8)))
        require(values == [values[0]] * 8, "concurrent local RPC observation changed exact reply")
    return {"literalRequestCharacters": len(text), "rpcRepliesObserved": 8 if category == "concurrency" else 1,
            "networkCalls": 0, "deviceExecution": False}


def _core_mcp(root, category, identity):
    from .neyvia_mcp import NeyviaMCPServer, MCP_PROTOCOL_VERSION
    from .proof_credential_guard import prepare_broker_fixture
    from .crashproof import CrashProofStore
    from .edge_fixture_native import _sharing_denied
    import sqlite3
    prepare_broker_fixture(root)
    server = NeyviaMCPServer(root)
    text = TEXT.get(category, "owned payload")
    counter = 0
    def request(method, params):
        nonlocal counter
        counter += 1
        response = server.handle({"jsonrpc": "2.0", "id": counter, "method": method, "params": params})
        require(response["id"] == counter, "MCP reply identity changed")
        return response
    def call(name, arguments, task=None):
        params = {"name": name, "arguments": arguments}
        if task is not None:
            params["task"] = task
        response = request("tools/call", params)
        require("error" not in response, "MCP local production call failed: " + str(response.get("error")))
        return response["result"]
    try:
        if identity.endswith("mcp-protocol"):
            from .edge_fixture_mcp_adverse import core_protocol
            observe, detail = core_protocol(server, category, text, request, call)
            if detail is not None:
                return detail
        elif identity.endswith("mcp-task-durable"):
            args = {"missionId": "owned-mission", "idempotencyKey": "owned-query", "query": text}
            denied = request("tools/call", {"name": "neyvia.research.start", "arguments": args})
            require(denied.get("error", {}).get("code") == -32002 and server.store.list_tasks() == [], "task augmentation refusal persisted work")
            def observe():
                return server._call_tool({"name": "neyvia.research.start", "arguments": args, "task": {"ttl": 60000}})
            if category == "permissions":
                with _sharing_denied(server.store.database_path):
                    error = refusal(observe, (sqlite3.Error, OSError, RuntimeError, ValueError))
                require(server.store.list_tasks() == [], "OS-denied task submission persisted work")
                return {"refusal": error, "durableTasks": 0}
            result = observe(); task_id = result["task"]["taskId"]
            require(CrashProofStore(root).get_task(task_id)["payload"] == args
                    and request("tasks/get", {"taskId": task_id})["result"]["task"]["taskId"] == task_id, "MCP task not saved/openable or changed payload")
            if category in {"stale", "concurrency"}:
                if category == "concurrency":
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        repeats = list(pool.map(lambda _: observe(), range(8)))
                else:
                    repeats = [observe()]
                require(all(r["task"]["taskId"] == task_id for r in repeats) and len(server.store.list_tasks()) == 1, "idempotent task replay duplicated durable work")
            batch_args = {"missionId": "owned-batch", "idempotencyKey": "batch", "modelCount": 129 if category == "huge" else 0 if category == "empty" else 3, "training": {"literal": text}}
            batch = call("neyvia.training.batch.start", batch_args, {"ttl": 60000})["task"]
            children = [r for r in server.store.list_tasks(mission_id="owned-batch") if r["taskId"] != batch["taskId"]]
            expected = 128 if category == "huge" else 1 if category == "empty" else 3
            require(len(children) == expected and all(r["parentTaskId"] == batch["taskId"] and r["payload"]["wakePolicy"] == "terminal_or_input_only" and r["payload"]["training"] == {"literal": text} for r in children), "bounded training children changed parent/payload/wake policy")
            server.store.transition_task(task_id, "working")
            payload = {"literal": text, "owned": True}
            server.store.transition_task(task_id, "completed", result=payload)
            terminal = request("tasks/result", {"taskId": task_id})["result"]
            require(terminal["structuredContent"] == payload and not terminal["isError"]
                    and terminal["_meta"]["io.modelcontextprotocol/related-task"] == {"taskId": task_id}, "MCP terminal result changed saved result/provenance")
            return {"durableTasks": expected + 2, "boundedChildren": expected, "savedTask": task_id, "terminalExact": True}
        elif identity.endswith("mcp-sync-budget"):
            from .edge_fixture_mcp_adverse import core_budget
            observe, detail = core_budget(server, category, text, request, call)
            if detail is not None:
                return detail
        elif identity.endswith("mcp-autonomy"):
            if category == "empty":
                error = request("tools/call", {"name": "neyvia.autonomy.grant", "arguments": {"allowedActions": []}})
                require(error.get("error", {}).get("code") == -32602, "unbounded empty autonomy policy accepted")
            actions = ["file_write"] * (10000 if category == "huge" else 1)
            lease = call("neyvia.autonomy.grant", {"missionId": text, "allowedActions": actions, "allowedRoots": [str(root)], "durationSeconds": 900})["structuredContent"]
            require(lease["policy"]["allowedActions"] == actions and lease["missionId"] == text.strip(), "saved autonomy policy lost large or Unicode declared values")
            args = {"leaseId": lease["leaseId"], "action": "file_write", "context": {"path": str(root / "owned.txt")}}
            def observe():
                result = server._call_tool({"name": "neyvia.autonomy.check", "arguments": args})
                require(result["structuredContent"]["allowed"] and not result["isError"], "saved bounded grant refused owned path")
                return result
            if category == "permissions":
                with _sharing_denied(server.store.database_path):
                    error = refusal(observe, (sqlite3.Error, OSError, RuntimeError, ValueError))
                require(server.store.autonomy_allows(lease["leaseId"], action="file_write", context=args["context"])["allowed"], "read-denied authority check revoked grant")
                return {"refusal": error, "grantUnchanged": True}
            observe()
            denied = call("neyvia.autonomy.check", {**args, "action": "shell_command"})
            require(not denied["structuredContent"]["allowed"] and denied["structuredContent"]["reason"] == "action_out_of_scope", "out-of-scope autonomy allowed")
            if category == "concurrency":
                with ThreadPoolExecutor(max_workers=4) as pool:
                    values = list(pool.map(lambda _: observe(), range(8)))
                require(all(v["structuredContent"]["allowed"] for v in values), "parallel authority observations diverged")
            revoked = call("neyvia.autonomy.revoke", {"leaseId": lease["leaseId"]})
            after = call("neyvia.autonomy.check", args)
            require(revoked["structuredContent"]["active"] is False and not after["structuredContent"]["allowed"], "revoked saved grant remained usable")
            return {"scopeDenied": True, "revocationObserved": True, "networkCalls": 0}
        else:
            parent = server.conversations.create_conversation(kind="chat", title="Owned parent")
            turn = server.conversations.append_turn(parent["conversationId"], role="user", content="owned evidence " + text)
            server.conversations.put_context_atom(parent["conversationId"], kind="decision", content="owned evidence " + text, evidence_turn_id=turn["turnId"])
            def observe():
                result = server._call_tool({"name": "neyvia.context.retrieve", "arguments": {"query": "owned evidence", "limit": 1}})
                items = result["structuredContent"]["items"]
                require(len(items) == 1 and items[0]["evidenceTurnId"] == turn["turnId"], "MCP retrieval lost actual saved turn provenance")
                return result
            if category == "stale":
                observe()
                fresh_turn = server.conversations.append_turn(parent["conversationId"], role="user", content="fresh owned evidence revision")
                server.conversations.put_context_atom(parent["conversationId"], kind="decision", content="fresh owned evidence revision", evidence_turn_id=fresh_turn["turnId"])
                refreshed = server._call_tool({"name": "neyvia.context.retrieve", "arguments": {"query": "fresh owned evidence revision", "limit": 1}})["structuredContent"]["items"]
                require(len(refreshed) == 1 and refreshed[0]["evidenceTurnId"] == fresh_turn["turnId"], "stale MCP context returned old saved evidence")
                return {"freshEvidenceTurn": fresh_turn["turnId"], "staleEvidenceRejected": True}
            if category == "permissions":
                with _sharing_denied(server.store.database_path):
                    error = refusal(observe, (sqlite3.Error, OSError, RuntimeError, ValueError))
                require(server.conversations.get_conversation(parent["conversationId"])["revision"] == parent["revision"] + 1, "OS-denied context read changed source conversation")
                return {"refusal": error, "sourceRevisionPreserved": True}
            observe()
            found = call("neyvia.conversation.search", {"query": "owned evidence", "limit": 1})["structuredContent"]
            require(found["results"][0]["conversationId"] == parent["conversationId"], "MCP search lost saved conversation provenance")
            branch = call("neyvia.question.branch", {"parentConversationId": parent["conversationId"], "question": text or "owned question"})["structuredContent"]
            allowed = call("neyvia.question.action.check", {"conversationId": branch["conversationId"], "action": "file.read"})
            denied = call("neyvia.question.action.check", {"conversationId": branch["conversationId"], "action": "file.write"})
            require(allowed["structuredContent"]["allowed"] and not denied["structuredContent"]["allowed"]
                    and server.conversations.get_conversation(branch["conversationId"])["parentConversationId"] == parent["conversationId"], "MCP question branch lost durable read-only parent policy")
            from .neyvia_conversations import FROZEN_SOL_PLANNER_ROUTE, typed_plan_hash
            orchestrated = server.conversations.create_conversation(kind="orchestration", title="Owned typed plan")
            children = [{"id": f"child-{index}", "name": f"Child {index}", "objective": "owned " + text,
                         "route": {"runtimeId": "codex", "provider": "openai-codex", "model": "gpt-5.6-luna", "effort": "high"},
                         "budget": {"maxSeconds": 90}, "authority": {"allowed": ["read_assigned_scope"]},
                         "tools": ["reasoning"], "handback": {"schema": "neyvia.agent_delta.v1"}} for index in range(6)]
            plan = {"schema": "neyvia.orchestration.typed-lead-plan.v1", "planId": "owned-plan", "approved": True, "governor": {"maxParallel": 2}, "preset": {"id": "owned"}, "children": children}
            digest = typed_plan_hash(plan)
            plan["approvedPlanHash"] = digest
            planned = server.conversations.create_dynamic_plan_run(orchestrated["conversationId"], planner_route=FROZEN_SOL_PLANNER_ROUTE)
            server.conversations.update_dynamic_plan_run(planned["runId"], status="awaiting_approval", typed_plan=plan, plan_hash=digest)
            approval = server.conversations.approve_dynamic_plan_run(planned["runId"], approval_receipt={"schema": "neyvia.approval.receipt.v1", "issuer": "neyvia", "approved": True, "runId": planned["runId"], "planHash": digest})
            graph = call("neyvia.orchestration.plan", {"conversationId": orchestrated["conversationId"], "typedPlan": plan, "approvedPlanHash": digest, "runId": planned["runId"], "approvalReceipt": approval["approvalReceipt"], "parentTaskId": "owned-parent-task"})["structuredContent"]
            require(graph["approvedPlanHash"] == digest and graph["parentTaskId"] == "owned-parent-task" and graph["governor"]["maxParallel"] == 2
                    and {r["nodeId"] for r in graph["nodes"]} == {r["id"] for r in children}
                    and all(r["approvedPlanHash"] == digest and r["parentTaskId"] == "owned-parent-task" and r["teamContract"] for r in graph["nodes"]), "MCP saved approved typed children lost named contract/hash/parent/governor binding")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: observe(), range(8)))
            require(len(results) == 8, "concurrent actual MCP observations missing")
        return {"literalCharacters": len(text), "actualHandlerObservations": 8 if category == "concurrency" else 1, "networkCalls": 0, "renderedProof": False}
    finally:
        server.mcp_broker.close()
        if getattr(server.capability_os, "_model_tool_broker", None) is not None:
            server.capability_os._model_tool_broker.close()


FAMILIES = {
    "pure": (_pure, set(PURE), set(TEXT)),
    "image-signatures": (_pure, {"control.image-magic"}, set(TEXT)),
    "attachments": (_attachments, {"control.attachments-content"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline"}),
    "registry-denial": (_runtime_read, {"runtime.install.catalog", "runtime.install.plan", "runtime.install.cycles"}, {"permissions"}),
    "toolchain-cache": (_toolchain_cache, {"runtime.toolchain.cache"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline"}),
    "toolchain-metadata": (_toolchain_cache, {"runtime.toolchain.discovery"}, set(TEXT)),
    "memory-adverse": (_memory, {"runtime.memory.durable", "runtime.memory.ingest"}, {"permissions", "concurrency", "stale", "offline", "interrupted"}),
    "memory-text": (_memory_existing, {"runtime.memory.durable", "runtime.memory.ingest", "runtime.memory.search"}, set(TEXT)),
    "mcp": (_mcp, {"runtime.mcp.authorization", "runtime.mcp.discovery", "runtime.mcp.receipt", "runtime.mcp.progressive", "runtime.mcp.host"}, set(TEXT) | {"permissions", "concurrency", "stale", "offline", "interrupted"}),
    "native-audit": (_audit, {"native.audit.delta", "native.audit.failure-gate", "native.audit.proof-discovery"}, set(TEXT) | {"permissions", "concurrency", "stale", "offline", "interrupted"}),
    "context-import": (_imports, {"control.import-upload", "control.import-preview", "control.import-selection", "control.import-read", "control.import-packet"}, set(TEXT) | {"permissions", "concurrency", "stale", "offline"}),
    "native-store-denial": (_native_store_denial, {"native.goals.durable", "native.goals.complete", "native.goals.due", "native.pairing.digest", "native.pairing.single-use", "native.pairing.authority", "native.learning.sample-floor"}, {"permissions"}),
    "core-rpc": (_core_rpc, {"neyvia-core.rpc-authority", "neyvia-core.rpc-plan", "neyvia-core.rpc-protocol"}, set(TEXT) | {"concurrency", "offline"}),
    "core-mcp": (_core_mcp, {"neyvia-core.mcp-protocol", "neyvia-core.mcp-task-durable", "neyvia-core.mcp-sync-budget", "neyvia-core.mcp-autonomy", "neyvia-core.mcp-conversation"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale"}),
    "provider-reads": (_provider_reads, {"providers.claude.read_bytes", "providers.claude.store_page", "providers.claude.sequence", "providers.claude.title_priority", "providers.claude.page", "providers.claude.summary", "providers.claude.context", "providers.claude.media"}, {"permissions", "offline", "concurrency"}),
    "control-stores": (_control_stores, {"proofs-c.control.workspaces", "proofs-c.control.cache", "proofs-c.control.events"}, {"permissions", "offline", "concurrency", "stale"}),
    "provider-turn": (_provider_turn, {"providers.claude.lifecycle", "providers.claude.events", "providers.claude.reply"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale", "interrupted"}),
    "gpu-decisions": (_gpu_decisions, {"a-cli.continuity.gpu"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale", "interrupted"}),
    "codex-assets-audit": (_codex_assets, {"a-cli.assets.audit"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale"}),
    "codex-assets-import": (_codex_assets, {"a-cli.assets.import"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale", "interrupted"}),
    "mods-launch": (_mods, {"a-cli.mods.launch"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale"}),
    "mods-report": (_mods, {"a-cli.mods.report"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale", "interrupted"}),
    "archive-inspect": (_archive, {"a-cli.archive.inspect"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale"}),
    "archive-import": (_archive, {"a-cli.archive.import"}, set(TEXT) | {"concurrency", "offline", "permissions", "stale", "interrupted"}),
    "durable-cli-denial": (_durable_cli_denial, {"a-cli.crash." + k for k in ("submit", "claim", "transition", "recover", "result", "summary")} | {"a-cli.continuity.attempt", "a-cli.continuity.recovery"} | {"a-cli.scheduler." + k for k in ("choose", "job", "claim", "stale", "load")}, {"permissions"}),
    "cluster-owners": (_cluster_rows, {"a-cli.scheduler." + k for k in ("job", "claim", "lease", "load", "stale", "expire")}, set(TEXT) | {"concurrency", "stale", "interrupted"}),
    "cluster-choice": (_cluster_rows, {"a-cli.scheduler.choose"}, set(TEXT) | {"concurrency", "stale", "offline"}),
    "broker-source-reads": (_broker_reads, {"sessions.broker.catalogue", "sessions.broker.read", "sessions.broker.media"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline"}),
    "broker-catalogue-exit": (_broker_reads, {"sessions.broker.catalogue"}, {"interrupted"}),
    "plugin-skill-invariants": (_plugin_skills, {"a-cli.mods.skills"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline"}),
    "first-run-state": (_first_run_state, {"a-cli.setup.state"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "crash-autonomy-completion": (_crash_completion, {"a-cli.crash.autonomy"}, {"huge", "concurrency"}),
    "crash-competition-completion": (_crash_completion, {"a-cli.crash.recover", "a-cli.crash.transition"}, {"concurrency"}),
    "crash-exit-completion": (_crash_completion, {"a-cli.crash.submit", "a-cli.crash.result"}, {"interrupted"}),
    "mission-resume-queue": (_mission_queue, {"a-cli.preferences.queue", "a-cli.preferences.dispatch"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "owned-worker-commands": (_owned_worker, {"a-cli.scheduler.execute", "a-cli.scheduler.environment", "a-cli.scheduler.worker", "a-cli.scheduler.threads"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "owned-worker-lifecycle": (_worker_lifecycle, {"a-cli.scheduler.lifecycle"}, {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "owned-installer": (_owned_installer, {"a-cli.installer.action", "a-cli.installer.integrity"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "mission-docs-state": (_mission_docs, {"a-cli.preferences.docs"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "setup-catalog-projection": (_setup_catalog, {"a-cli.setup.view", "a-cli.catalog.selection"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline"}),
    "workspace-cli-adverse": (_workspace_command, {"a-cli.preferences.workspace"}, {"concurrency", "permissions", "interrupted"}),
    "mission-terminal-stop": (_mission_stop, {"a-cli.preferences.stop"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "legacy-engine-preferences": (_legacy_preferences, {"a-cli.preferences.engine"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "delegated-queue-lineage": (_delegated_queue, {"a-cli.scheduler.queued", "a-cli.scheduler.rehome"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "owned-unlimited-loop": (_unlimited_loop, {"a-cli.scheduler.unlimited-loop"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "saved-mission-cycles": (_mission_cycles, {"a-cli.preferences.cycle"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "durable-mission-start": (_mission_started, {"a-cli.preferences.started"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "actual-mission-spawn": (_mission_spawn, {"a-cli.preferences.spawn"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
    "owned-watchdog-cadence": (_owned_watchdog, {"a-cli.preferences.watchdog"}, set(TEXT) | {"concurrency", "permissions", "stale", "offline", "interrupted"}),
}


def run(root, contracts, categories, families=None):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    from .proof_contracts import source_digest
    builder_sha = source_digest(Path(__file__))
    rows = []
    for family, (builder, identities, supported) in FAMILIES.items():
        if families and family not in families:
            continue
        for identity in sorted(identities & contracts.keys()):
            for category in sorted(supported & set(categories)):
                # Do not duplicate earlier real passing categories.
                if family == "pure" and identity in {"runtime.service.spec", "runtime.memory.search"}:
                    continue
                if identity == "runtime.mcp.host" and category not in set(TEXT) | {"permissions", "concurrency", "interrupted", "offline", "stale"}:
                    continue
                if identity == "control.import-upload" and category == "stale":
                    continue
                if family == "provider-reads" and category == "concurrency" and identity != "providers.claude.title_priority":
                    continue
                area = root / (identity.replace(".", "-") + "-" + category)
                area.mkdir(parents=True, exist_ok=True)
                row = {"id": f"c7d-control.{identity}.{category}", "contracts": [identity], "category": category,
                       "boundary": "production calls with independently supplied value/byte/refusal oracles; no provider, device or rendered claim"}
                started = time.perf_counter()
                try:
                    row.update(status="passed", detail=builder(area, category, identity))
                except Exception as error:
                    row.update(status="failed", detail={"type": type(error).__name__, "error": str(error)})
                row["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
                # This stream diagnoses long-running partial families. Only
                # the catalog's completed, source-bound receipt admits cases.
                with (root / "case-progress.jsonl").open("a", encoding="utf8") as progress:
                    progress.write(json.dumps({"diagnostic": True, "completionReceipt": False,
                                               "builderSourceSha256": builder_sha, "case": row},
                                              ensure_ascii=True) + "\n")
                rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract["id"]
    if category == "interrupted" and identity in {"a-cli.setup.view", "a-cli.catalog.selection"}:
        return {"kind": "not_applicable", "reason": f"Exact setup/catalog projection audit {identity}: with explicit already-observed runtime/cache and browser state, these calls derive optional catalog/readiness values without publishing saved choices, installing a CLI or starting a provider/browser worker. Interrupted saved choices and managed installation are separate writers with actual exit/failure receipts. No rendered or runtime-doctor claim follows this projection."}
    if category == "interrupted" and identity in {"a-cli.crash.autonomy", "a-cli.crash.summary"}:
        return {"kind": "not_applicable", "reason": f"Exact crash-store observation audit {identity}: autonomy_allows recursively reads inherited current lease/policy rows, while summarize_result_set reads selected result/count/sample rows. Neither call writes a result, changes a lease or executes an admitted action. Interrupted task/result writers have actual caller exit23 receipts; the observed policy/result reader owns no persisted incomplete operation to recover."}
    if category == "interrupted" and identity in {"sessions.broker.read", "sessions.broker.media"}:
        return {"kind": "not_applicable", "reason": f"Exact broker source observation audit {identity}: the explicitly selected adapter returns transcript/media bytes through a bounded read thread; the broker only derives a page or media tuple and updates volatile sequence/summary indexes. This call owns no persisted source mutation or provider turn requiring interrupted recovery. Catalogue's persisted seen baseline is separately exercised with actual caller exit23 and reopened SeenStore."}
    if category == "interrupted" and identity == "a-cli.mods.skills":
        return {"kind": "not_applicable", "reason": "Exact manual skill invariant audit: check_plugin_skills only compares selected current SKILL.md bytes against the actual current renderer. It owns no skill-generation writer, activation or provider child; interruption cannot mutate those bytes. Selected original read denial and stale bytes are separately exercised."}
    if category == "offline" and identity in LOCAL_COORDINATION:
        return {"kind": "not_applicable", "reason": f"Exact offline transport audit {identity}: {LOCAL_COORDINATION[identity]}. Actual offline host exclusion remains applicable and exercised at a-cli.scheduler.choose; worker network/child execution are separate owners."}
    if category == "interrupted" and identity == "a-cli.scheduler.choose":
        return {"kind": "not_applicable", "reason": "Exact choose_host audit: this method reads existing local host/job observations and returns a selection; it owns no dispatch worker or durable selected effect. Interrupted claim/lease/load/job/expiry/stale writers are separately exercised with actual caller exit23."}
    if identity in STATIC:
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return {"kind": "not_applicable", "reason": f"Exact static declaration audit {identity} ({digest}): {STATIC[identity]} Category {category} has no operation at this invariant.", "invariantSha256": digest}
    if category == "interrupted" and identity in {"a-cli.assets.audit", "a-cli.mods.launch", "a-cli.archive.inspect"}:
        return {"kind": "not_applicable", "reason": f"Exact owner audit {identity}: this call reads local metadata/settings and returns a value; it owns no provider/CLI child or persisted effect whose incomplete recovery can be observed. Asset import/report writers are independently exercised, including caller exit23 after committed bytes."}
    if identity in PURE and category not in TEXT:
        return {"kind": "not_applicable", "reason": f"Invariant audit {identity}: {PURE[identity]}. This invariant owns no {category} worker, endpoint, durable writer, grant or revision operation; source sites {contract.get('checkedAt', [])}."}
    if identity in {"runtime.install.catalog", "runtime.install.plan", "runtime.install.cycles"} and category in {"offline", "interrupted", "concurrency", "stale"}:
        return {"kind": "not_applicable", "reason": f"Invariant audit {identity}: constructor loads one explicit registry and validates its dependency graph before immutable catalog/resolve observations. No writer, worker, endpoint or optimistic revision is owned; a newer registry requires a fresh constructor. Read-denial has its own real permissions case."}
    if identity == "runtime.toolchain.integrity" and category in {"offline", "interrupted"}:
        return {"kind": "not_applicable", "reason": f"Invariant audit {identity}: local_integrity reads bounded pinned executable bytes and calculates digests without activation, network or durable writes; killed observation cannot mutate an installation. Read denial and changing-byte observations are separate cases."}
    if identity == "control.import-upload" and category == "stale":
        return {"kind": "not_applicable", "reason": "Invariant audit control.import-upload: stage_upload takes streamed bytes and mints a fresh unguessable upload identity; it accepts no prior upload ID, observation digest or revision. Hash-conflicting references are refused by the separately exercised preview/import readers."}
    if identity in {"control.import-preview", "control.import-read", "control.import-packet"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": f"Invariant audit {identity}: this synchronous explicit-source reader performs no durable mutation or external dispatch; abrupt termination cannot issue an import/upload. Interrupted durable writers remain separate fixture obligations."}
    return None


def main():
    import argparse
    import uuid
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", action="append", choices=tuple(FAMILIES))
    parser.add_argument("--contract", action="append")
    parser.add_argument("--category", action="append", choices=tuple(TEXT) + ("permissions", "concurrency", "stale", "offline", "interrupted"))
    args = parser.parse_args()
    from .proof_ports import C7_PORTS
    if args.port not in C7_PORTS:
        parser.error("Assigned C7 ports only")
    repo = Path(__file__).resolve().parents[2]
    root = repo / ".agent_control/proofs/c7d-control" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        directory = root / "home" / key.lower(); directory.mkdir(parents=True)
        os.environ[key] = str(directory)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), NEYVIA_TOOL_AUTO_UPDATE="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_NAS_ROOT=str(root), PYTHONPATH=str(repo / "src"), PYTHONIOENCODING="utf-8")
    from .proof_credential_guard import install
    install(root)
    def audit(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            raise PermissionError("This C7d control fixture campaign permits no network")
    sys.addaudithook(audit)
    contracts = {c["id"]: c for p in (repo / "config/proofs").glob("*.json")
                 if p.name != "test-inventory.json" for c in json.loads(p.read_text(encoding="utf8")).get("contracts", [])}
    if args.contract:
        require(set(args.contract) <= contracts.keys(), "unknown selected contract")
        contracts = {key: value for key, value in contracts.items() if key in args.contract}
    declarations = []
    if "sessions.api.allowlist" in contracts:
        from .proofs_a_sessions import check_connected_allowlist
        from .connected_sessions.api import CONNECTED_COMMANDS
        from .desktop_bridge import ALLOWED_DESKTOP_COMMANDS
        check_connected_allowlist()
        require(CONNECTED_COMMANDS <= ALLOWED_DESKTOP_COMMANDS, "connected static command declaration lacks desktop inclusion")
        declarations.append({"contract": "sessions.api.allowlist", "status": "passed", "declaredCommands": len(CONNECTED_COMMANDS), "boundary": "zero-input declaration diagnostic; no adverse category or runtime dispatch proof"})
    names = ["context_microkernel", "agent_vision", "marketplace_toolchain", "memory", "context_import",
             "neyvia_runtime_invocation", "native_proof_audit", "mcp_broker", "neyvia_mcp", "progressive_tools",
             "context_manager", "chat_run_control", "action_executor", "openai_adapter", "models", "install_profiles",
             "durability", "managed_local_service", "harness_jobs", "proof_credential_guard", "proofs_a_control",
             "native_goals", "native_pairing", "native_learning", "native_tools", "native_arguments",
             "neyvia_native_rpc", "neyvia_conversations", "crashproof", "behavior_capsules", "skill_capsules",
             "native_device_commands", "native_device_operator_authority", "edge_fixture_native", "edge_fixture_host_runtime", "edge_fixture_control_remaining",
             "mission_control", "edge_fixture_providers", "edge_fixture_mcp_adverse", "connected_sessions/claude", "connected_sessions/claude_transcript", "neyvia_time_tools",
             "connected_sessions/claude_stream", "proofs_a_providers", "cua_launch",
             "continuity_policy", "harness_comparison", "proofs_b_adapters", "cli", "proofs_a_cli_scheduler",
             "codex_import", "communication_archive", "runtime_supervisor", "claude_code_mods", "ui_command_bus",
             "ecosystem_fabric", "cluster", "subprocess_utils", "worker", "proofs_d_runtime_auth", "cli_installer", "cli_catalog", "proofs_c_control",
             "connected_sessions/registry", "connected_sessions/broker", "connected_sessions/api", "desktop_bridge", "proofs_a_cli", "proofs_a_sessions",
             "proofs_c_runtime", "proofs_d_native", "proofs_a_native_sessions", "connected_sessions/attachments",
             "connected_sessions/dashboard", "connected_sessions/neyvia", "connected_sessions/claude_items", "connected_sessions/model", "connected_sessions/seen", "external_chat_inventory", "progressive_setup", "neyvia_manuals", "cl/integration", "neyvia_browser", "laya_service", "snapshot_cache", "runtimes/__init__",
             "runtimes/base", "runtimes/managed_cli", "constitution", "profiles", "modes", "engine", "session_store", "checkpoints", "mission_watchdog", "browser_preflight"]
    sources = [Path(__file__)] + [repo / ("src/grant_agent/" + name + ".py") for name in names]
    sources.append(repo / "scripts/build_claude_plugin_skills.py")
    bindings = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    rows = run(root, contracts, args.category or set(TEXT) | {"permissions", "concurrency", "stale", "offline", "interrupted"}, families=args.family)
    stable = bindings == {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {"schema": "neyvia.c7d-control.raw.v1", "sourceBindings": bindings, "sourceStable": stable,
              "explicitPort": args.port, "scratchRoot": str(root), "rows": rows, "declarationDiagnostics": declarations,
              "counts": {s: sum(r["status"] == s for r in rows) for s in ("passed", "failed")}}
    args.output.resolve().relative_to(repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"counts": report["counts"], "sourceStable": stable,
                      "failed": [r for r in rows if r["status"] != "passed"]}, ensure_ascii=True))
    return int(not stable or report["counts"]["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
