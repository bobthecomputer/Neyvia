"""Exact C7d capability and support fixtures, below rendering authority.

Generated data reaches real production owners. Pure input projections, local
files and denied grants are distinct from rendered/device/provider execution.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .edge_fixture_local import require, refused

CATEGORIES = ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
MODULE = "grant_agent.edge_fixture_c7d_capability"
TEXTS = {"empty": "", "huge": "bounded " * 16385, "unicode": "雪🙂e\u0301\u202e العربية\x00"}
PURE_OWNERS = {
    "a.cu-metrics": "summarize_cu_receipts: direct receipt-array statistics and declared URL counts; no capture, grant, worker, revision or transport",
    "a.evolution-stagnation": "_recommendation: supplied loss/usage thresholds produce review-required suggested actions; no write or execution",
    "a.evolution-forge": "_trial_from_row: decodes supplied JSON forge cases and checks acceptance/authority sums; it reads no DB or file and never promotes",
    "a.evolution-receipts": "_trial_from_row: decodes supplied JSON receipt identities/package digests; actual durable evidence writes are separate owners",
    "a.evolution-sealed": "_trial_from_row: checks supplied sealed bytes/digests/inactive flags without writing or reading a package",
    "sv.snapshot.private-filter": "_is_excluded: path-component metadata only; no snapshot, file read or NAS transfer",
    "sv.suggestions.priority": "build_vibe_next_steps: supplied objective/state/signals only, without shared mutation or external execution",
    "sv.update.package-parse": "npm_package_of: regex on supplied update-command text; no installation/process/network",
    "sv.verification.normalize": "_normalize_verification_command: supplied strings only; no command runs, imports or interpreter discovery",
    "sv.sdk.portable-schema": "validate_portable_schema: supplied schema syntax/literals only; no I/O or generated-file mutation",
    "sv.sdk.manifest": "build_app_manifest/build_solantir_manifest: supplied declaration dictionaries only; no active bridge, revision token or execution",
    "a.permission-modes": "CapabilityPermissionEngine.decide: evaluates current supplied approval/mode/scope; accepts no previous revision or cached authorization token",
    "a.surface-manifest": "validate_application_surface_manifest: validates supplied optional manifest declarations without reading files or granting runtime readiness",
    "sv.skills.retrieval": "SkillRegistry.retrieve ranks the already loaded caller-owned Skill list; no file read/write, grant, transport or previous token occurs in this owner",
    "sv.skills.feedback-summary": "_feedback_summary reduces already loaded feedback/operator-value lists; it performs no persistence, authorization, transport or previous-token admission",
    "a.challenge-catalog": "ChallengePresetRegistry.list_names sorts already loaded preset keys; no file read/write, grant, endpoint or prior-token admission",
    "a.challenge-selection": "ChallengePreset.pick_selectors ranks caller-owned objective/preset strings; no file read/write, grant, transport or prior-token admission",
    "sv.skills.brief": "SkillLibrary.build_skill_brief reduces already loaded registry/user/learned/feedback/evolution lists into compact selections; it does not reread files, authorize a grant, start a worker/transport, write, or admit a prior token",
    "sv.skills.catalog": "SkillLibrary.build_catalog projects already loaded curated/user/learned/feedback/evolution lists; it does not reread files, persist, authorize a grant, start a transport or admit a prior token",
}


def text(category):
    return TEXTS.get(category, "local reviewed owner proof")


def blocker(contract, category):
    identity = contract["id"]
    if identity in PURE_OWNERS and category in {"concurrency", "interrupted", "offline", "stale", "permissions"}:
        # Permission decisions themselves have a real permission input; only
        # the missing stale CAS operation is excluded for that exact owner.
        if identity == "a.permission-modes" and category != "stale":
            return None
        return {"kind": "not_applicable", "reason": f"Audited {identity} at {contract.get('checkedAt', [])}: {PURE_OWNERS[identity]}. No {category} operation exists at this exact invariant; unrelated service effects remain separate obligations."}
    if identity == "a.capability-ui-schema":
        return {"kind": "not_applicable", "reason": f"Audited {identity} owner CapabilityService.ui_contract accepts zero arguments and constructs a fixed command/lifecycle/visual-owner dictionary. It owns no mutable field, input text/collection, grant, worker, transport or revision for {category}. Actual rendered UI is a separate contract."}
    if identity == "a.app-state" and category in {"offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"Audited _save_session_state writes the current caller-supplied local observation; it performs no network request and accepts no prior revision/token for {category}. Exact bytes, idempotent mtime, sharing denial, synchronized writers and interrupted persistence have distinct applicable fixtures."}
    if identity == "sv.ui.graph-state" and category in {"interrupted", "permissions", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": f"Audited UiGraph.replace_nodes synchronously replaces caller-owned in-memory nodes and stamps their revision; it has no durable write, external grant, network, worker or prior-token admission for {category}. Rendered observation/action effects are separate owners."}
    if identity == "sv.ui.action-gates" and category in {"interrupted", "permissions", "offline"}:
        return {"kind": "not_applicable", "reason": "Audited exact contract refuses a supplied stale graph token and truthfully refuses when no browser page is attached. No OS grant, durable partial write or network request occurs in that refusal path; real attached-page actions remain separate rendered obligations."}
    if identity in {"a.adapter-execution", "a.adapter-file-inspection", "a.tool-workspace"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": f"Audited {identity} dispatch/file inspection/path admission owner reads or returns an invocation result without persisting a partial effect or resumable journal. Handler-owned mutations have separate writer invariants; an interrupted result is never completed by this exact owner."}
    if identity in {"a.adapter-file-inspection", "a.tool-workspace", "a.adapter-session"} and category == "offline":
        return {"kind": "not_applicable", "reason": f"Audited {identity} operates on selected local file bytes/path metadata/session JSON only; it performs no endpoint request. Session presence does not execute a remote adapter. Offline transport execution remains a separate owner."}
    if identity == "a.android-approval" and category in {"concurrency", "interrupted", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited exact _execute_android mutation refusal checks the caller's approval before parsing or launching any device command; it starts no process, shared mutation, network or cached revision. Approved Android/device execution is outside this refusal invariant."}
    if identity in {"a.surface-authority", "a.surface-receipt", "a.surface-lifecycle", "a.surface-log", "a.surface-plan"} and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": f"Audited {identity} verifies selected local ledger/log bytes or constructs a nonexecuting launch plan. It owns no durable mutation journal or endpoint request for {category}; actual lifecycle process/listener/device execution remains a separate observation."}
    if identity == "sv.suggestions.signals" and category in {"interrupted", "offline", "permissions"}:
        return {"kind": "not_applicable", "reason": f"Audited collect_repo_signals uses path existence and glob metadata only, never reads contents, owns no mutation or external endpoint. File-sharing content grants, interrupted writes and offline transports do not occur at this {category} projection boundary."}
    if identity in {"sv.sdk.bindings", "sv.sdk.plan-only"} and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": f"Audited {identity} generates returned binding strings or nonexecuting local plans from input declarations. It starts no transport/activation or durable write. Publication writers and runtime readiness are separate obligations."}
    if identity == "sv.sdk.transport" and category == "stale":
        return {"kind": "not_applicable", "reason": "Audited FluxioClient._post serializes the current request with current include_cookie policy; it owns no cached response, revision or prior receipt admission. Actual bytes, closed endpoint, sharing-independent requests and aborted responses have fixtures."}
    if identity == "sv.support.bundle" and category in {"offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited support bundle exports the currently selected local bounded metadata; it never requests a network endpoint or admits a caller's prior revision/receipt as authority. Current source rereads and archive replacement/interruption remain applicable."}
    if identity == "a.capability-admission" and category in {"concurrency", "interrupted", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited execute_capability's delegated and compute-spend refusal paths check current declarations/permissions and return before executing a provider, mutating shared state, starting a transport or accepting a prior revision. Approved actual execution is a separate invariant and remains unproved."}
    if identity == "a.capability-benchmark" and category in {"interrupted", "offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited benchmark measures current in-memory registry searches and current process-memory observations; no endpoint, durable mutation or caller prior revision is admitted. A ten-times claim still requires retained baseline evidence."}
    if identity == "a.capability-pack" and category == "offline":
        return {"kind": "not_applicable", "reason": "Audited save_pack validates and atomically saves/reloads scoped local JSON declarations without any endpoint request, provider invocation or activation."}
    if identity == "a.authored-tool" and category == "offline":
        return {"kind": "not_applicable", "reason": "Audited AuthoredToolStore.save validates a current manifest/approval then writes scoped local JSON. It invokes no endpoint/adapter; actual authored execution has a distinct contract."}
    if identity == "a.authored-argv" and category in {"offline", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited _execute_command_tool invokes a selected local scalar-argv executable in current scoped cwd. It owns no endpoint or prior revision/token admission; timeout and child exit/parse evidence remain applicable."}
    if identity == "a.treasury-boundary" and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": "Audited CapabilityTreasury.snapshot reads explicitly supported selected local asset metadata into review-only returned capsules. It owns no mutation/publication journal, endpoint request or background worker for interruption/offline semantics; untrusted input never raises activation or publication authority."}
    if identity == "a.app-cloud" and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": "Audited _cloud_drive_bridge_plan observes declared login-presence metadata and selected local directory metadata then returns an approval-gated plan. It starts no sync, endpoint request or durable write; this discovery invariant cannot prove actual remote authentication or transfer."}
    if identity == "a.app-storage" and category == "interrupted":
        return {"kind": "not_applicable", "reason": "Audited _synology_bridge_plan and read-only _build_synology_fast_sync_session return selected local metadata/policy plus observed owned HTTP status; they never start a sync or write a resumable journal. Interrupted transfer semantics belong to the actual writer, outside this observation invariant."}
    if identity in {"a.evolution-outcome", "a.evolution-friction"} and category == "offline":
        return {"kind": "not_applicable", "reason": f"Audited {identity} accepts current typed local graph/run inputs after local binding checks and persists review-only SQLite observations. It performs no endpoint request or provider run; declaration availability inputs and externally executed/rendered proofs remain distinct."}
    if identity in {"a.evolution-inactive", "a.evolution-handoff", "a.factory-lineage"} and category == "offline":
        return {"kind": "not_applicable", "reason": f"Audited {identity} verifies selected inactive local package/SQLite/lease bindings and returns a reviewed capsule or writes an inactive local package/draft. It performs no network/provider execution or publication; actual provider and rendered work remain separate."}
    if identity in {"a.evolution-handoff", "a.evolution-lease"} and category == "interrupted":
        return {"kind": "not_applicable", "reason": f"Audited {identity} reads current selected local package/dependency/SQLite facts and returns an assessment/capsule. It performs no durable mutation, resumable write or external worker step; writer interruption belongs to lease establishment/renewal/materialization or factory copy, distinct owners."}
    if identity in {"a.tool-readiness", "a.tool-reference", "a.tool-private", "a.tool-typed"} and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": f"Audited {identity} parses current declarations, validates selected local reference bytes or projects typed compatibility metadata. These exact calls never execute an adapter/provider, publish a writer journal or request an endpoint. Execution, rendering and broker activation remain separate obligations."}
    if identity == "a.pdf-bounded" and category in {"interrupted", "offline"}:
        return {"kind": "not_applicable", "reason": "Audited _execute_pdftotext runs an installed local executable with a temporary output and returns bounded text. It starts no network, publishes no resumable document mutation or retained result journal; subprocess failure cannot return completed text. Input bounds, genuine extraction, access denial and fresh bytes remain exercised."}
    if identity in {"a.cu-replay", "a.cu-portable", "a.cu-verifier"} and category == "offline":
        return {"kind": "not_applicable", "reason": f"Audited {identity} replay receipt/inline worker replay path uses generated local records only and performs no endpoint request. Its model inputs cannot grant live proof. Actual live browser/remote worker execution remains a distinct authority obligation."}
    return None


def _trial(root, category):
    from .capability_evolution import NeyviaCapabilityEvolution
    from .proofs_a_capability_evolution import check_trial
    value = text(category)
    candidate = {"schema": "neyvia.sealed_skill_candidate.v1", "skillMarkdown": value,
                 "openaiYaml": value, "skillSha256": hashlib.sha256(value.encode()).hexdigest(),
                 "metadataSha256": hashlib.sha256(value.encode()).hexdigest(), "state": "sealed",
                 "activated": False, "packageDigest": "a" * 64}
    cases = [] if category == "empty" else [{"classification": "win", "authority": {"expandedPermissions": []}} for _ in range(128 if category == "huge" else 3)]
    counts = {"wins": len(cases), "ties": 0, "regressions": 0, "inconclusive": 0}
    forge = {"cases": cases, "scorecard": counts, "caseCount": len(cases), "requiredCaseCount": 3,
             "reviewGatePassed": len(cases) >= 3, "authorityComparison": {"expandedPermissions": []},
             "candidatePackageDigest": candidate["packageDigest"], "candidateActivated": False, "transcriptsIncluded": False}
    evidence = [{"runId": f"owned-{i}", "receiptPair": {"schema": "neyvia.receipt_comparison.v1",
                 "candidatePackageDigest": candidate["packageDigest"], "transcriptsIncluded": False},
                 "measurementRubric": {"derivedFromReceipts": True}, "candidatePackageDigest": candidate["packageDigest"]} for i in range(len(cases))]
    row = {key: value for key in ("trial_id", "lineage_id", "capability_id", "capability_kind", "label", "action", "title", "reason", "created_by", "created_at", "updated_at")}
    row.update(state="draft", context_json="{}", baseline_json="{}", candidate_json=json.dumps(candidate), success_contract_json="{}",
               evidence_json=json.dumps(evidence), verdict_json=json.dumps({"counterfactualForge": forge}))
    original = copy.deepcopy(row)
    result = NeyviaCapabilityEvolution._trial_from_row(row)
    require(row == original and result["candidate"] == candidate and result["evidence"] == evidence, "Trial projection mutated inputs or lost exact sealed values")
    require(result["verdict"]["counterfactualForge"]["scorecard"] == counts and not result["candidate"]["activated"], "Forge counters or inactive authority changed")
    malformed = copy.deepcopy(row)
    malformed["evidence_json"] = json.dumps([{"runId": "duplicate"}, {"runId": "duplicate"}])
    refused(lambda: NeyviaCapabilityEvolution._trial_from_row(malformed))
    expanded = copy.deepcopy(forge)
    expanded["cases"] = [{"classification": "win", "authority": {"expandedPermissions": ["dangerous"]}}] * 3
    expanded.update(scorecard={"wins": 3, "ties": 0, "regressions": 0, "inconclusive": 0}, caseCount=3,
                    authorityComparison={"expandedPermissions": ["dangerous"]}, reviewGatePassed=False)
    row["verdict_json"] = json.dumps({"counterfactualForge": expanded})
    result = NeyviaCapabilityEvolution._trial_from_row(row)
    require(not result["verdict"]["counterfactualForge"]["reviewGatePassed"], "Expanded authority was accepted")
    return {"sealedBytes": len(value.encode()), "distinctReceipts": len(evidence), "forgeCases": len(cases), "duplicateRefused": True, "expandedAuthorityBlocked": True}


def _pure(root, category, identity):
    value = text(category)
    if identity in {"sv.skills.retrieval", "sv.skills.feedback-summary", "sv.skills.brief", "sv.skills.catalog"}:
        from .edge_fixture_preferences_skills import _registry, _feedback
        result = (_feedback if identity == "sv.skills.feedback-summary" else _registry)(root, category)
        require(identity in result["contracts"], "Family builder did not exercise selected skill invariant")
        return result["detail"]
    if identity in {"a.challenge-catalog", "a.challenge-selection"}:
        from .edge_fixture_capabilities import _challenges
        return _challenges(root, category)
    if identity == "a.evolution-stagnation":
        from .capability_evolution import NeyviaCapabilityEvolution
        service = NeyviaCapabilityEvolution(root)
        for inputs, expected in (({"latestSystemLoss": .55}, "repair"), ({"usageCount": 3, "zeroImprovementStreak": 2}, "branch"), ({"usageCount": 100000}, "prove")):
            row = {"capabilityId": value, "label": value, **inputs}
            result = service._recommendation(row)
            require(result["action"] == expected and result["humanDecisionRequired"] and result["status"] == "suggested", "Loss/usage raised trust or changed expected repair decision")
        return {"thresholdDecisions": 3, "labelBytes": len(value.encode()), "humanReviewRequired": True}
    if identity == "a.cu-metrics":
        from .computer_use_twin import summarize_cu_receipts
        receipts = [] if category == "empty" else [{"baseUrl": f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}", "durationMs": i,
                    "treeOmitted": True, "results": [{"flow": "owned" + (value if category == "unicode" else ""), "pass": i % 2 == 0, "skipped": False}]} for i in range(1024 if category == "huge" else 4)]
        result = summarize_cu_receipts(receipts)
        require(result["repetitions"] == result["flowObservations"] == len(receipts), "Receipt count differs from actual array")
        require(result["compactReceiptBytes"] == sum(len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()) for row in receipts), "Receipt byte accounting differs")
        require(result["flowSuccessRate"] == (.5 if receipts else 0) and result["liveReceiptCount"] == len(receipts), "Flow outcomes or declared URL count differs")
        return {"receipts": len(receipts), "compactBytes": result["compactReceiptBytes"], "scope": "supplied receipt statistics; no live capture"}
    if identity == "sv.verification.normalize":
        from .verification import _normalize_verification_command
        executable = str(root / "explicit-unused-interpreter.exe")
        for original in ("pytest " + value, "python -m pytest " + value):
            require(_normalize_verification_command(original, executable) == (f'"{executable}" -m pytest ' + value.strip()).strip(), "Selected interpreter or literal suffix changed")
        require(_normalize_verification_command(value, executable) == value.strip(), "Unrelated command altered")
        return {"inputCharacters": len(value), "preparedOnly": True}
    if identity == "sv.update.package-parse":
        from .runtime_auto_update import npm_package_of
        require(npm_package_of("npm install -g @owned/tool@latest") == "@owned/tool", "Scoped package literal changed")
        for invalid in (value, "npm install @owned/tool@latest", "npm install -g tool@3"):
            require(npm_package_of(invalid) is None, "Non-global/latest input claimed an update package")
        return {"inputCharacters": len(value), "installExecuted": False}
    if identity == "sv.snapshot.private-filter":
        path = Path(__file__).resolve().parents[2] / "scripts/stage_neyvia_wip_snapshot.py"
        spec = importlib.util.spec_from_file_location("owned_snapshot_metadata", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for candidate in (Path(".env"), Path(".agent_control/private/memory.json"), Path("browser-profile/Cookies"), Path(".codex/memories/private.md")):
            require(module._is_excluded(candidate), "Private metadata path admitted")
        public = Path("scripts/evidence/" + ("proof雪🙂" if category == "unicode" else "x" * 5000 if category == "huge" else "proof") + ".json")
        require(not module._is_excluded(public), "Public redacted receipt path excluded")
        return {"privatePathsRefused": 4, "publicComponents": len(public.parts), "filesRead": 0, "transfers": 0}
    if identity == "sv.suggestions.priority":
        from .vibe_suggestions import build_vibe_next_steps
        state = {"next_actions": [] if category == "empty" else [value] * (1000 if category == "huge" else 2)}
        result = build_vibe_next_steps(value, state, [value] if value else [], {"tests_count": 0, "docs_count": 0}, limit=6)
        require(len(result) <= 6 and len(result) == len(set(result)), "Suggestion bound or duplicate changed")
        if value:
            require(result[0] == "Finish remaining plan step: " + value, "Pending plan lost first priority")
        return {"suggestions": len(result), "pendingFirst": bool(value)}
    if identity == "sv.sdk.portable-schema":
        from .sdk_codegen import validate_portable_schema, LossySchemaError
        schema = {"type": "object", "properties": {"owned": {"type": "string", "const": value}}, "additionalProperties": False}
        require(validate_portable_schema(schema) is None, "Portable literal schema rejected")
        try:
            validate_portable_schema({"type": "object", "additionalProperties": False, "properties": {"owned": {"patternProperties": {}}}})
        except LossySchemaError as error:
            require(error.pointer == "/properties/owned" and error.keyword == "patternProperties", "Lossy schema error lost exact pointer")
        else:
            raise AssertionError("Lossy keyword accepted")
        return {"literalCharacters": len(value), "lossyPointerRefused": True}
    raise NotImplementedError(identity)


def _ui(root, category, identity):
    from .ui_graph import UiGraph, UiNode, compute_semantic_hash
    from .ui_tools import UiToolSurface
    ui = UiToolSurface()
    try:
        ui.call("ui.observe", {"nodes": [{"id": "owned", "role": "button", "name": "review", "actions": ["click"]}]})
        if identity == "sv.ui.action-gates":
            before = copy.deepcopy(ui.graph)
            for gate in ({"ifRev": 0}, {"ifHash": "stale"}):
                result = ui.call("ui.do", {"id": "owned", "action": "click", **gate})
                require(result["status"] == "stale_state" and not result["ok"], "Stale action reached execution")
                require(ui.graph == before, "Rejected action changed resident graph")
            result = ui.call("ui.do", {"id": "owned", "action": "click", "ifRev": ui.graph.revision, "ifHash": ui.graph.semantic_hash})
            require(result["status"] == "no_page" and not result["ok"], "Missing page fabricated an effect")
            return {"staleRefusals": 2, "actualMissingPageStatus": result["status"], "rendered": False}
        if identity == "sv.ui.compact-result":
            result = ui.call("ui.ls", {"limit": 40})
            require(result["treeOmitted"] and result["revision"] == ui.graph.revision and result["semanticHash"] == ui.graph.semantic_hash, "Compact result lost current graph binding")
            return {"residentNodes": len(ui.graph.nodes), "revision": ui.graph.revision, "treeOmitted": True}
        graph = UiGraph()
        def replace(index):
            nodes = [UiNode(f"owned-{index}", "button", "review")]
            changes = graph.replace_nodes(nodes)
            return {"revision": graph.revision, "hash": graph.semantic_hash, "nodes": graph.snapshot_nodes(), "changes": changes}
        # Each concurrent caller owns its graph, because the owner advertises no
        # synchronization for a shared graph; shared replacement is explicitly
        # exercised below and every observed resulting graph must be coherent.
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(replace, range(16)))
        require(graph.revision == 16 and all(node.revision == graph.revision for node in graph.nodes.values()) and graph.semantic_hash == compute_semantic_hash(graph.nodes.values()), "Resident shared replacements lost revision/hash coherence")
        return {"calls": len(results), "finalRevision": graph.revision, "residentNodes": len(graph.nodes), "rendered": False}
    finally:
        ui.close()


def _appstate(root, category, identity):
    from .app_capability_standard import _save_session_state
    from .edge_fixture_preferences_skills import denied_file
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    value = text(category)
    state = {"owned": {"session_id": "owned", "status": value}}
    _save_session_state(root, state)
    path = root / ".agent_control/connected_apps_state.json"
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    _save_session_state(root, state)
    require(path.read_bytes() == before and path.stat().st_mtime_ns == stamp, "Idempotent app observation rewrote durable state")
    if category == "interrupted":
        child = subprocess.run([sys.executable, "-m", MODULE, "--port", os.environ["NEYVIA_C7_PORT"], "--crash-app-state", str(root)],
                               capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
        require(child.returncode == 23, "App state worker did not exit at the actual write boundary: " + child.stderr[-1000:])
        require(path.read_bytes() == before, "Interrupted app state overwrite destroyed prior complete observation")
    elif category == "permissions":
        with denied_file(path):
            refused(lambda: _save_session_state(root, {"after": {"status": "changed"}}), OSError)
        require(path.read_bytes() == before, "Denied app state overwrite changed prior bytes")
    elif category == "concurrency":
        def save(index):
            fresh = {"owned": {"session_id": str(index), "status": value}}
            _save_session_state(root, fresh)
            return fresh
        with ThreadPoolExecutor(max_workers=8) as pool:
            writes = list(pool.map(save, range(16)))
        require(json.loads(path.read_text(encoding="utf-8")) in writes, "Concurrent app state writes produced a torn observation")
    elif category == "stale":
        after = {"owned": {"session_id": "fresh", "status": "new observation"}}
        _save_session_state(root, after)
        require(json.loads(path.read_text(encoding="utf-8")) == after, "Fresh supplied app state did not replace prior observation")
    return {"stateBytes": path.stat().st_size, "unchangedWritePreservedMtime": True,
            "categoryBoundary": "real process write interruption" if category == "interrupted" else "real local persistence"}


def _crash_app_state(root):
    from .app_capability_standard import _save_session_state
    path = root / ".agent_control/connected_apps_state.json"
    original_open, original_replace = Path.open, os.replace
    class InterruptedWrite:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close()
        def write(self, value):
            self.handle.write(value[:max(1, len(value) // 2)]); self.handle.flush(); os.fsync(self.handle.fileno()); os._exit(23)
    def opened(target, mode="r", *args, **kwargs):
        handle = original_open(target, mode, *args, **kwargs)
        return InterruptedWrite(handle) if target.resolve() == path.resolve() and "w" in mode else handle
    def replaced(source, target):
        if Path(target).resolve() == path.resolve(): os._exit(23)
        return original_replace(source, target)
    Path.open, os.replace = opened, replaced
    _save_session_state(root, {"after": {"session_id": "fresh", "status": "new complete observation"}})
    raise AssertionError("No app state write boundary reached")


def _adapters(root, category, identity):
    from .capability_adapters import CapabilityAdapterRegistry
    from .capability_contracts import AdapterDescriptor
    from .proof_credential_guard import prepare_broker_fixture
    from .edge_fixture_preferences_skills import denied_file
    prepare_broker_fixture(root)
    registry = CapabilityAdapterRegistry(root)
    value = text(category)
    if identity == "a.android-approval":
        registry.register(AdapterDescriptor(adapter_id="device.android", label="Owned nonexecuting approval probe", kind="external_executable",
                          available=True, executable=sys.executable, supports_execution=True), registry._execute_android)
        for operation in ("tap", "swipe", "install", "launch", "text", "start_emulator"):
            result = registry.execute("device.android", {"operation": operation, "approved": False, "text": value, "x": value, "package": value})
            require(not result["ok"] and result["status"] == "approval_required" and result["result"]["requiredPermission"] == "external.side_effect", "Unapproved Android mutation reached an executable")
        return {"mutationRefusals": 6, "executableInvocations": 0, "deviceProof": False}
    if identity == "a.adapter-session":
        payload = {"adapterId": "device.apple-remote", "sessionId": "owned", "label": value, "transport": "remote_runner",
                   "endpoint": "runner://owned", "capabilities": ["owned.read"], "approved": True}
        unapproved = registry.register_session({**payload, "approved": False})
        require(unapproved["status"] == "approval_required", "Session registered without review")
        saved = registry.register_session(payload)
        session_id, heartbeat_key = saved["session"]["sessionId"], saved["heartbeatKey"]
        require("heartbeatKeyHash" not in json.dumps(saved), "Verifier hash leaked into session registration")
        refused(lambda: registry.heartbeat_session(session_id, "wrong"), PermissionError)
        current = registry.heartbeat_session(session_id, heartbeat_key)
        require("heartbeatKeyHash" not in json.dumps(current), "Verifier hash leaked into heartbeat projection")
        require(not registry.descriptor("device.apple-remote").supports_execution, "Session presence fabricated an in-process executor")
        if category == "permissions":
            before = registry.sessions.path.read_bytes()
            refused(lambda: registry.disconnect_session(session_id, approved=False))
            require(registry.sessions.path.read_bytes() == before, "Denied disconnect changed durable session bytes")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda _: registry.heartbeat_session(session_id, heartbeat_key), range(16)))
            require(all(row["sessionId"] == session_id and "heartbeatKeyHash" not in row for row in responses), "Concurrent heartbeats lost privacy or identity")
        elif category == "stale":
            saved = registry.register_session(payload)
            refused(lambda: registry.heartbeat_session(session_id, heartbeat_key), PermissionError)
            require(saved["heartbeatKey"] != heartbeat_key, "Re-registration retained stale heartbeat authority")
        elif category == "interrupted":
            from .edge_fixture_local import replacement_fault
            from . import capability_adapters as owner
            before = registry.sessions.path.read_bytes()
            with replacement_fault(owner, registry.sessions.path, KeyboardInterrupt) as calls:
                refused(lambda: registry.heartbeat_session(session_id, heartbeat_key), KeyboardInterrupt)
            require(calls and registry.sessions.path.read_bytes() == before, "Interrupted adapter session commit changed durable state")
        return {"sessionId": session_id, "privateVerifierOmitted": True, "supportsExecution": False, "persistedBytes": registry.sessions.path.stat().st_size}
    path = root / ("observed雪🙂.txt" if category == "unicode" else "observed.txt")
    path.write_bytes(value.encode())
    before = path.read_bytes()
    if identity == "a.tool-workspace":
        observed = registry._resolve_existing_workspace_path(path)
        require(observed == path.resolve(), "Scoped file path identity changed")
        outside = root.parent / (root.name + "-outside.txt"); outside.write_bytes(b"scoped keeper")
        refused(lambda: registry._resolve_existing_workspace_path(outside), PermissionError)
        require(outside.read_bytes() == b"scoped keeper", "Out-of-workspace refusal changed other file bytes")
        if category == "stale":
            path.rename(root / "moved.txt")
            refused(lambda: registry._resolve_existing_workspace_path(path), FileNotFoundError)
        return {"scopeEscapeRefused": True, "sourceBytes": len(before), "executableInvocations": 0}
    if category == "permissions":
        with denied_file(path):
            result = registry.execute("builtin.artifact.inspect", {"path": str(path)})
        require(not result["ok"] and result["status"] == "failed" and path.read_bytes() == before, "Denied inspector claimed success or changed bytes")
        return {"sharingDenied": True, "sourcePreserved": True}
    if category == "offline" and identity == "a.adapter-execution":
        import socket
        def closed_endpoint(arguments):
            with socket.create_connection(("127.0.0.1", int(os.environ["NEYVIA_C7_PORT"])), timeout=.2):
                raise AssertionError("Unowned endpoint unexpectedly accepted")
        registry.register(AdapterDescriptor(adapter_id="owned.closed-endpoint", label="Owned explicit unreachable invocation", kind="builtin", available=True, supports_execution=True), closed_endpoint)
        result = registry.execute("owned.closed-endpoint", {})
        require(not result["ok"] and result["status"] == "failed", "Closed endpoint invocation invented completion")
        return {"registeredHandlerCalled": True, "actualClosedPort": int(os.environ["NEYVIA_C7_PORT"]), "failureTruthful": True}
    def inspect(_): return registry.execute("builtin.artifact.inspect", {"path": str(path)})
    results = list(ThreadPoolExecutor(max_workers=8).map(inspect, range(16))) if category == "concurrency" else [inspect(0)]
    require(all(row["ok"] and row["result"]["sha256"] == hashlib.sha256(before).hexdigest() and row["result"]["sizeBytes"] == len(before) for row in results), "Production inspector hash/size does not bind actual bytes")
    require(path.read_bytes() == before, "Read-only adapter mutated source bytes")
    if category == "stale":
        path.write_bytes(b"new independent observation")
        fresh = inspect(0)
        require(fresh["result"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and fresh["result"]["sha256"] != results[0]["result"]["sha256"], "Inspector reused stale byte evidence")
    if identity == "a.adapter-execution":
        require(registry.execute("unregistered.owned", {})["status"] == "unavailable" and registry.execute("neyvia.agent", {})["status"] == "not_executable", "Availability or registered execution handler truth changed")
    return {"sourceBytes": len(before), "actualInvocations": len(results), "independentSha256": hashlib.sha256(before).hexdigest()}


def _surface(root, category, identity):
    from . import application_surface as owner
    from .sdk import build_application_surface
    from .edge_fixture_preferences_skills import denied_file
    work, ledger = root / "workspace", root / "authority"
    work.mkdir(); ledger.mkdir()
    key = os.urandom(32)
    authority = owner.ExternalReceiptAuthority(ledger, key)
    service = owner.ApplicationSurfaceService(work, receipt_authority=authority)
    now = datetime.now(timezone.utc)
    value = text(category)
    surface = build_application_surface(surface_id="owned.preview", title="Owned " + (value[:100] if value else "preview"), description="Selected local proof",
               permissions={"inspect": [], "launch": [], "control": []}, targets=[{"target_id": "web.owned", "kind": "web", "platform": "web", "build": {"status": "not_required"},
               "launch": {"kind": "url", "url": f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}"}, "required_permissions": [], "readiness": {"receipt_id": "missing-ready"}}])
    manifest = {"app_id": "owned-preview", "name": "Owned Preview", "application_surface": surface}
    if identity == "a.surface-manifest":
        require(owner.validate_application_surface_manifest({})["valid"], "Absent optional declaration became invalid")
        valid = owner.validate_application_surface_manifest(manifest)
        require(valid["valid"], "Valid supplied declaration rejected")
        malformed = copy.deepcopy(manifest)
        malformed["application_surface"]["unexpected"] = value
        require(not owner.validate_application_surface_manifest(malformed)["valid"], "Extra surface field escaped persisted schema")
        return {"optionalAbsentValid": True, "suppliedValid": True, "unknownFieldRejected": True, "rendered": False}
    if identity == "a.surface-authority":
        refused(lambda: owner.ApplicationSurfaceService(work, receipt_authority=owner.ExternalReceiptAuthority(work / "editable-ledger", key)))
        status = service.status(manifest)
        require(status["targets"][0]["available"] is False, "Missing host readiness invented available execution")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses = list(pool.map(lambda _: service.status(manifest), range(16)))
            require(all(not row["targets"][0]["available"] for row in statuses), "Concurrent missing-readiness projection became ready")
        return {"editableAuthorityRefused": True, "outsideAuthorityInjected": True, "readiness": "unavailable", "rendered": False}
    if identity == "a.surface-plan":
        plan = service.plan_launch(manifest, target_id="web.owned", permission_mode="review_only", approval_id=value)
        require(plan["status"] != "ready" and not any(plan["executionPolicy"][key] for key in ("executes", "builds", "installs", "publishes")), "Unproved plan acquired execution authority")
        return {"status": plan["status"], "executionPolicy": plan["executionPolicy"], "approvalValid": plan["approval"]["valid"]}
    if identity == "a.surface-log":
        path = work / "owned.log"
        path.write_text("public雪🙂\npassword=owned-generated-secret\nuncommitted-tail", encoding="utf-8")
        original = path.read_bytes()
        result = service._read_log("owned.log", max_lines=80, remaining_bytes=1024 * 1024)
        encoded = json.dumps(result, ensure_ascii=False)
        require("owned-generated-secret" not in encoded and "uncommitted-tail" not in encoded and "public雪🙂" in encoded, "Log leaked a secret or partial tail")
        if category == "empty":
            path.write_bytes(b""); require(service._read_log("owned.log", max_lines=80, remaining_bytes=1024)["lines"] == [], "Empty log fabricated rows")
        elif category == "huge":
            with path.open("wb") as handle: handle.truncate(owner.MAX_LOG_FILE_BYTES + 1)
            require(service._read_log("owned.log", max_lines=80, remaining_bytes=1024)["status"] == "too_large", "Oversized log was read")
        elif category == "permissions":
            with denied_file(path): denied = service._read_log("owned.log", max_lines=80, remaining_bytes=1024)
            require(denied["lines"] == [] and denied["status"] == "missing" and path.read_bytes() == original, "Denied log disclosed lines or changed bytes")
        elif category == "stale":
            path.write_text("new completed observation\n", encoding="utf-8")
            require(service._read_log("owned.log", max_lines=80, remaining_bytes=1024)["lines"] == ["new completed observation"], "Log returned stale tail")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: replies = list(pool.map(lambda _: service._read_log("owned.log", max_lines=80, remaining_bytes=1024), range(16)))
            require(all(row["lines"] == result["lines"] for row in replies), "Concurrent immutable tail reads lost rows")
        return {"observedStatus": result["status"], "secretsRedacted": True, "partialTailDropped": True}
    def signed(receipt_id, kind, payload, *, stream=None):
        envelope = {"schema": owner.EXTERNAL_RECEIPT_ENVELOPE_SCHEMA, "receiptId": receipt_id, "kind": kind, "singleUse": True,
                    "issuedAt": now.isoformat(), "expiresAt": (now + timedelta(minutes=10)).isoformat(), "nonce": "owned",
                    "payload": payload}
        envelope["signature"] = hmac.new(key, authority._signature_material(envelope), hashlib.sha256).hexdigest()
        path = ledger / "lifecycle" / stream / (receipt_id + ".json") if stream else ledger / "receipts" / (receipt_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    if identity == "a.surface-receipt":
        path, digest = signed("owned", "approval", {"value": value})
        verified = authority.verify_receipt("owned", expected_kind="approval")
        require(verified["verified"] and verified["receiptHash"] == digest and verified["payload"]["value"] == value, "Signed receipt identity/content/hash binding failed")
        require(not authority.verify_receipt("owned", expected_kind="readiness")["verified"], "Wrong receipt kind accepted")
        if category == "permissions":
            with denied_file(path): result = authority.verify_receipt("owned", expected_kind="approval")
            require(not result["verified"], "Denied authority bytes remained verified")
        elif category == "huge":
            path.write_bytes(b"x" * (owner.MAX_STRUCTURED_RECEIPT_BYTES + 1))
            require(not authority.verify_receipt("owned", expected_kind="approval")["verified"], "Oversized signed bytes accepted")
        elif category == "empty":
            path.write_bytes(b""); require(not authority.verify_receipt("owned", expected_kind="approval")["verified"], "Empty receipt verified")
        elif category == "stale":
            consumed = ledger / "consumed/owned.json"; consumed.parent.mkdir(); consumed.write_text("{}")
            require(not authority.verify_receipt("owned", expected_kind="approval")["verified"], "Consumed receipt reauthorized")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: rows = list(pool.map(lambda _: authority.verify_receipt("owned", expected_kind="approval"), range(16)))
            require(all(row["verified"] and row["receiptHash"] == digest for row in rows), "Concurrent signed verification lost stable bytes")
        else:
            payload = json.loads(path.read_text(encoding="utf-8")); payload["payload"]["value"] = "tampered"; path.write_text(json.dumps(payload), encoding="utf-8")
            require(not authority.verify_receipt("owned", expected_kind="approval")["verified"], "Tampered Unicode payload retained signature authority")
        return {"labSignatureVerified": True, "independentReceiptSha256": digest, "deviceOrProviderProof": False}
    previous = ""
    count = 128 if category == "huge" else 3
    paths = []
    previous_state = "declared"
    states = ["ready", "launching", "running"] + ["stopped", "launching", "running"] * 42
    for index in range(1, count + 1):
        path, previous = signed(f"owned-{index:03}", "lifecycle", {"streamId": "owned", "sequence": index,
                                "previousReceiptHash": previous, "previousState": previous_state, "state": states[index - 1], "value": value[:1024],
                                "schema": owner.APPLICATION_SURFACE_LIFECYCLE_SCHEMA, "updatedAt": now.isoformat(),
                                "runId": "owned-run", "manifestHash": "a" * 64, "planHash": "b" * 64, "artifactSha256": "", "targetId": "web.owned"}, stream="owned")
        paths.append(path)
        previous_state = states[index - 1]
    verified = authority.verify_lifecycle_stream("owned")
    require(verified["verified"] and verified["chainLength"] == count, "Monotonic signed hash chain rejected or miscounted")
    # A cryptographically valid running report cannot invent live process or
    # listener identity. Exercise the actual status owner as well as its chain.
    lifecycle = {"stream_id": "owned", "states": list(owner.LIFECYCLE_STATES)}
    status = service._lifecycle_status({"lifecycle": lifecycle}, manifest_hash="a" * 64,
        targets=[{"targetId": "web.owned", "kind": "web", "planHash": "b" * 64, "artifact": {"sha256": ""}}])
    require(not status["verified"] and not status["workspaceReportTrusted"], "Signed ledger report invented live running proof")
    if category == "permissions":
        with denied_file(paths[-1]): refused_chain = authority.verify_lifecycle_stream("owned")
        require(not refused_chain["verified"], "Unreadable chain link remained verified")
    elif category == "empty":
        require(not authority.verify_lifecycle_stream("missing")["verified"], "Missing stream became trusted")
    elif category == "stale":
        envelope = json.loads(paths[-1].read_text(encoding="utf-8")); envelope["payload"]["previousReceiptHash"] = "b" * 64
        envelope["signature"] = hmac.new(key, authority._signature_material(envelope), hashlib.sha256).hexdigest()
        paths[-1].write_text(json.dumps(envelope))
        require(not authority.verify_lifecycle_stream("owned")["verified"], "Validly signed but stale previous hash admitted")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: chains = list(pool.map(lambda _: authority.verify_lifecycle_stream("owned"), range(16)))
        require(all(row["verified"] and row["chainLength"] == count for row in chains), "Concurrent immutable chains diverged")
    return {"signedChainLength": count, "monotonicHashesChecked": True, "liveProcessProof": False}


def _signals(root, category, identity):
    from .vibe_suggestions import collect_repo_signals
    for directory in ("tests", "docs"):
        (root / directory).mkdir()
    count = 0 if category == "empty" else 512 if category == "huge" else 3
    for index in range(count):
        stem = ("雪🙂" if category == "unicode" else "owned") + str(index)
        (root / "tests" / (stem + ".py")).write_text("NOT_EXECUTED = True\n", encoding="utf-8")
        (root / "docs" / (stem + ".md")).write_text(text(category)[:1024], encoding="utf-8")
    if count:
        (root / "pyproject.toml").write_text("[project]\nname='owned'\nversion='0.0.0'\n")
        (root / "README.md").write_text("# Owned\n")
    expected = {"tests_count": count, "docs_count": count, "has_pyproject": bool(count), "has_readme": bool(count)}
    require(collect_repo_signals(root) == expected, "Repository metadata counts/fields changed")
    if category == "stale":
        (root / "tests/owned-fresh.py").write_text("NOT_EXECUTED = True\n")
        require(collect_repo_signals(root)["tests_count"] == count + 1, "Metadata reused stale count")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(lambda _: collect_repo_signals(root), range(16)))
        require(all(result == expected for result in results), "Concurrent metadata reads invented files")
    return {"actualFilesPerKind": count, "contentsExecuted": False, "observed": expected}


def _artifacts(root, category, identity):
    from . import artifact_graph as owner
    from .edge_fixture_capabilities import _artifacts as build
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    base = build(root, category)
    graph = owner.ArtifactGraph(root)
    original = graph.state_path.read_bytes()
    state = json.loads(original); ids = list(state["artifacts"])
    if category == "interrupted":
        with replacement_fault(owner, graph.state_path, OSError) as faults:
            refused(lambda: graph.relate(ids[0], ids[-1], "references"), (OSError,))
        require(faults and graph.state_path.read_bytes() == original, "Interrupted artifact relation changed durable graph")
    elif category == "permissions":
        with denied_file(graph.state_path):
            if identity == "a.artifact-durable":
                refused(lambda: graph.register(path=root / "source-0.txt"), (OSError, ValueError))
            elif identity == "a.artifact-relations":
                refused(lambda: graph.relate(ids[0], ids[-1], "references"), (KeyError, ValueError, OSError))
            else:
                refused(lambda: graph.lineage(ids[-1]), (KeyError, ValueError, OSError))
        require(graph.state_path.read_bytes() == original, "Denied lineage altered stored artifact bytes")
    return {**base, "rejectedDurableBytesPreserved": category in {"permissions", "interrupted"}}


def _factory(root, category, identity):
    from . import app_factory as owner
    from .edge_fixture_capabilities import _factory as build
    from .edge_fixture_local import replacement_fault
    base = build(root, category)
    factory = owner.AppFactory(root)
    job = factory.get_job(base["jobId"])
    if category == "concurrency":
        def create(index):
            return factory.create(name=f"Concurrent Owned Notes {index}", brief="Keep owned local notes and export portable JSON records", target="neyvia", template="notes", directory=f"apps/owned-{index}")
        with ThreadPoolExecutor(max_workers=4) as pool: jobs = list(pool.map(create, range(4)))
        registry = json.loads(factory.registry_path.read_text(encoding="utf-8"))
        require({row["spec"]["appId"] for row in jobs} <= {row["applicationId"] for row in registry["applications"]}, "Concurrent factory creation lost registered applications")
        require(all(Path(row["package"]["path"]).is_file() and hashlib.sha256(Path(row["package"]["path"]).read_bytes()).hexdigest() == row["package"]["sha256"] for row in jobs), "Concurrent packages lost bound bytes")
    elif category == "interrupted":
        path = factory._job_path(job["jobId"]); original = path.read_bytes()
        with replacement_fault(owner, path, OSError) as faults:
            refused(lambda: factory._save_job(copy.deepcopy(job)), (OSError,))
        require(faults and path.read_bytes() == original, "Interrupted factory job write destroyed resumable journal")
        require(owner.AppFactory(root).resume(job["jobId"])["package"]["sha256"] == job["package"]["sha256"], "Interrupted job lost recoverable sealed package")
    return {**base, "previewRoot": str(Path(job["projectRoot"]) / "dist"), "rendered": False}


def _durable(root, category, identity):
    from .edge_fixture_preferences_skills import denied_file
    from .edge_fixture_local import replacement_fault
    if identity == "a.checkpoint-durable":
        from .checkpoints import CheckpointStore
        from .models import RunState
        store = CheckpointStore(root); state = RunState(objective=text(category), plan_steps=["observe"], acceptance_checks=["readback"])
        path = store.save("owned", 1, state, {"revision": 1}, [])
        original = path.read_bytes()
        with denied_file(path): refused(lambda: store.save("owned", 1, state, {"revision": 2}, []), (OSError,))
        require(path.read_bytes() == original and CheckpointStore.load(path)["context"]["revision"] == 1, "Denied checkpoint replacement lost durable prior state")
        return {"deniedWritePreservedSha256": hashlib.sha256(original).hexdigest()}
    from . import capability_runtime as owner
    from .capability_contracts import PreviewEvent
    store = owner.CapabilityRunStore(root)
    run = store.create({"planId": "owned", "goal": "Owned ordered preview"}, permission_summary={})
    path = store._path(run["runId"]); original = path.read_bytes()
    event = PreviewEvent(run_id=run["runId"], phase="live", kind="owned", summary="New observed event", payload={}, artifact_ids=())
    with replacement_fault(owner, path, OSError) as faults:
        refused(lambda: store.append_preview(event), (OSError,))
    require(faults and path.read_bytes() == original and store.get(run["runId"]) == run, "Interrupted preview mutation returned a partial durable record")
    done = store.finish(run["runId"], status="cancelled", summary="Owned worker interrupted")
    require(store.get(run["runId"]) == done and done["previewEvents"][-1]["phase"] == "result", "Cancellation lost terminal result event")
    return {"beforeSha256": hashlib.sha256(original).hexdigest(), "persistedStatus": done["status"], "terminalEvent": "result"}


def _capabilities(root, category, identity):
    from . import capability_service as owner
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    service = owner.CapabilityService(root)
    value = text(category)
    if identity == "a.capability-admission":
        delegated = service.execute_capability({"capabilityId": "research.literature-review", "arguments": {"query": value}})
        expensive = service.execute_capability({"capabilityId": "ai.model-training", "arguments": {"query": value}})
        require(not delegated["ok"] and delegated["status"] == "delegation_required" and not expensive["ok"] and expensive["status"] == "approval_required", "Capability admission synthesized successful agent work")
        return {"delegatedStatus": delegated["status"], "computeStatus": expensive["status"], "providerRun": False}
    if identity == "a.capability-benchmark":
        result = service.benchmark({"iterations": 10000 if category == "huge" else 3, "warmups": 1, "queries": [value]})
        require(result["search"]["status"] == ("pass" if result["search"]["p95Ms"] <= result["search"]["budgetP95Ms"] else "fail") and result["tenXAcceptance"]["baselineRequired"], "Benchmark budget/baseline claim did not follow real observations")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: service.benchmark({"iterations": 3, "warmups": 1, "queries": [value]}), range(4)))
            require(all(row["search"]["status"] == ("pass" if row["search"]["p95Ms"] <= row["search"]["budgetP95Ms"] else "fail") for row in results), "Concurrent benchmark lost measured budget binding")
        return {"iterations": result["iterations"], "actualP95Ms": result["search"]["p95Ms"], "budgetStatus": result["search"]["status"], "tenXClaimed": False}
    pack = {"packId": "custom.archaeology", "name": "Owned archaeology", "description": value or "Owned local definitions", "domains": ["archaeology"], "roles": ["researcher"],
            "capabilities": [{"capabilityId": "archaeology.site-analysis", "name": "Analyze owned site", "description": value or "Local analysis definition", "adapterId": "neyvia.agent", "domains": ["archaeology"], "roles": ["researcher"], "requiredPermissions": ["artifact.read", "artifact.write"]}]}
    denied = service.save_pack({"pack": pack})
    require(denied["status"] == "approval_required", "Unapproved custom pack wrote configuration")
    result = service.save_pack({"pack": pack, "approved": True})
    require(result["ok"], "Valid reviewed pack rejected: " + str(result))
    path = Path(result["path"]); original = path.read_bytes()
    require(path.is_relative_to(root) and json.loads(original)["packId"] == pack["packId"] and pack["capabilities"][0]["capabilityId"] in owner.CapabilityService(root).registry.capabilities, "Custom pack lost durable scope/definition on restart")
    if category == "interrupted":
        with replacement_fault(owner, path, OSError) as faults:
            refused(lambda: service.save_pack({"pack": pack, "approved": True, "replaceExisting": True}), (OSError,))
        require(faults and path.read_bytes() == original, "Interrupted pack publication lost earlier definitions")
    elif category == "permissions":
        with denied_file(path): refused(lambda: service.save_pack({"pack": pack, "approved": True, "replaceExisting": True}), (OSError,))
        require(path.read_bytes() == original, "Denied pack write destroyed definitions")
    elif category == "concurrency":
        def save(index):
            changed = copy.deepcopy(pack); changed["packId"] = f"custom.owned{index}"; changed["capabilities"][0]["capabilityId"] = f"archaeology.owned{index}"
            return service.save_pack({"pack": changed, "approved": True})
        with ThreadPoolExecutor(max_workers=4) as pool: saved = list(pool.map(save, range(4)))
        require(all(row["ok"] for row in saved) and all(f"archaeology.owned{index}" in owner.CapabilityService(root).registry.capabilities for index in range(4)), "Concurrent distinct pack definitions disappeared on restart")
    elif category == "stale":
        path.write_text("{}", encoding="utf-8")
        require(pack["capabilities"][0]["capabilityId"] not in owner.CapabilityService(root).registry.capabilities, "Invalid durable definition reloaded stale valid pack")
    return {"packId": pack["packId"], "durableBytes": len(original), "approved": True, "providerExecuted": False}


def _authored(root, category, identity):
    from . import tool_factory as owner
    from .capability_service import CapabilityService
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    store = owner.AuthoredToolStore(root)
    command = "import json,sys,os;print(json.dumps({'value':sys.argv[1],'argc':len(sys.argv),'cwd':os.getcwd(),'secretInherited':'OWNED_SECRET_MARKER' in os.environ}))"
    manifest = {"schema": owner.AUTHORED_TOOL_SCHEMA, "toolId": "custom.owned-echo", "name": "Owned scalar echo", "description": text(category)[:8192] or "Owned local scalar argv",
                "kind": "command", "version": "1.0.0", "permissions": ["process.execute"], "inputSchema": {"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}},
                "outputSchema": {"type": "object"}, "command": {"adapterId": "runtime.python", "argvTemplate": ["-c", command, "{{input.value}}"], "workingDirectory": ".", "timeoutSeconds": 15, "outputParser": "json"}}
    require(store.save(manifest)["status"] == "approval_required", "Unapproved authored tool saved")
    saved = store.save(manifest, approved=True)
    require(saved["ok"], "Reviewed authored manifest rejected: " + str(saved))
    path = Path(saved["path"]); original = path.read_bytes()
    require(path.is_relative_to(root) and json.loads(original)["toolId"] == manifest["toolId"], "Authored manifest escaped scoped durable identity")
    if identity == "a.authored-tool":
        if category == "interrupted":
            with replacement_fault(owner, path, OSError) as faults:
                refused(lambda: store.save(manifest, approved=True), (OSError,))
            require(faults and path.read_bytes() == original, "Interrupted authored save lost prior manifest")
        elif category == "permissions":
            with denied_file(path): refused(lambda: store.save(manifest, approved=True), (OSError,))
            require(path.read_bytes() == original, "Denied authored save lost bytes")
        elif category == "concurrency":
            def save(index):
                changed = copy.deepcopy(manifest); changed["toolId"] = f"custom.owned-{index}"
                return store.save(changed, approved=True)
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(save, range(4)))
            require(all(row["ok"] for row in results) and len(owner.AuthoredToolStore(root).list_tools()["tools"]) == 5, "Concurrent manifest writes lost distinct durable tools")
        elif category == "stale":
            path.write_text("{}", encoding="utf-8")
            restarted = owner.AuthoredToolStore(root).list_tools()
            require(not restarted["tools"] and restarted["loadErrors"], "Invalid saved authored tool revived stale executable")
        return {"manifestBytes": len(original), "manifestSha256": hashlib.sha256(original).hexdigest(), "approvalRequired": True}
    service = CapabilityService(root)
    argument = text(category).replace("\x00", "")[:8192] + " ; & | $(owned-literal)"
    invoke = lambda: service.execute_authored_tool({"toolId": manifest["toolId"], "arguments": {"value": argument}, "permissionMode": "autonomous_scoped"})
    if category == "permissions": os.environ["OWNED_SECRET_MARKER"] = "owned-generated"
    try:
        result = invoke()
    finally:
        os.environ.pop("OWNED_SECRET_MARKER", None)
    require(result["ok"] and result["exitCode"] == 0 and result["argvCount"] == 4 and result["output"]["argc"] == 2 and result["output"]["value"] == argument and Path(result["output"]["cwd"]) == root and not result["output"]["secretInherited"], "Actual authored argv split/interpolated, escaped cwd or leaked excluded environment")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: replies = list(pool.map(lambda _: invoke(), range(4)))
        require(all(row["ok"] and row["output"]["value"] == argument for row in replies), "Concurrent scalar argv results were mixed")
    elif category == "interrupted":
        timed = copy.deepcopy(manifest); timed["toolId"] = "custom.owned-timeout"; timed["command"]["argvTemplate"] = ["-c", "import time;time.sleep(5)"]
        timed["command"]["timeoutSeconds"] = 1
        require(service.authored_tools.save(timed, approved=True)["ok"], "Timeout manifest rejected")
        refused(lambda: service.execute_authored_tool({"toolId": timed["toolId"], "arguments": {"value": "unused"}, "permissionMode": "autonomous_scoped"}), (subprocess.TimeoutExpired,))
    elif category == "unicode":
        refused(lambda: service.execute_authored_tool({"toolId": manifest["toolId"], "arguments": {"value": "owned\x00null"}, "permissionMode": "autonomous_scoped"}), (ValueError,))
    return {"scalarArgvCount": result["argvCount"], "literalCharacters": len(argument), "exitCode": result["exitCode"], "actualHiddenLocalChild": True, "providerInvocation": False}


def _skills(root, category, identity):
    from .edge_fixture_preferences_skills import _roots, _registry, denied_file
    from .edge_fixture_local import replacement_fault
    work, home = _roots(root)
    if identity == "sv.skills.discovery":
        from .skill_library import load_codex_home_skill_rows
        skill = work / ".codex/skills/owned-guide/SKILL.md"; skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: owned-guide\ndescription: Owned local guidance\n---\n# Owned\n", encoding="utf-8")
        control = work / ".agent_control"; control.mkdir()
        (control / "workspaces.json").write_text("{}")
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: load_codex_home_skill_rows(control, home_root=home), range(4)))
        require(all(len(row) == 1 and row[0]["source"]["kind"] == "workspace" and row[0]["executionCapable"] is False for row in rows), "Concurrent skill discovery lost exact guidance origin or raised execution authority")
        return {"concurrentDiscoveries": 4, "guidanceOnly": True}
    if identity == "sv.skills.feedback":
        from . import skill_library as owner
        from .skills import SkillRegistry
        from . import durability
        library = owner.SkillLibrary(work, SkillRegistry(work / "absent.json"), home_root=home)
        record = lambda: library.record_slice_feedback(mission_id="owned", step_id="owned", selected_skills=[], execution_ok=True, verification_failures=[], changed_files=["owned.py"])
        record(); path = library.feedback_path; original = path.read_bytes()
        with replacement_fault(durability, path, OSError) as faults:
            refused(record, (OSError,))
        require(faults and path.read_bytes() == original, "Interrupted feedback write lost accepted history")
        reloaded = owner.SkillLibrary(work, SkillRegistry(work / "absent.json"), home_root=home)
        require(reloaded.feedback_records == json.loads(original), "Restart accepted interrupted feedback as complete history")
        return {"acceptedRecords": len(reloaded.feedback_records), "beforeSha256": hashlib.sha256(original).hexdigest()}
    from . import web_backend as owner
    base = {"name": "owned-base", "description": "Preserve exact owned observations", "instructions": "1. Inspect owned state.\n2. Verify its observed result.\n", "scope": "project"}
    result = owner._create_codex_skill(base, root=work, home_root=home)
    path = Path(result["evolutionReceiptPath"]); original = path.read_bytes()
    action = lambda: owner._create_codex_skill({**base, "name": "owned-adverse"}, root=work, home_root=home)
    if category == "permissions":
        with denied_file(path): refused(action, (RuntimeError, OSError))
    else:
        with replacement_fault(owner, path, OSError) as faults: refused(action, (RuntimeError, OSError))
        require(faults, "Skill creation interruption never reached durable receipt publication")
    require(path.read_bytes() == original and not (work / ".codex/skills/owned-adverse").exists(), "Adverse creation left a partial skill or destroyed prior history")
    return {"priorReceiptSha256": hashlib.sha256(original).hexdigest(), "partialSkillRemoved": True, "createdInterfaceAndHistory": True}


def _treasury(root, category, identity):
    from .legacy_asset_treasury import CapabilityTreasury
    from .edge_fixture_preferences_skills import denied_file
    docs = root / "docs"; docs.mkdir()
    count = 0 if category == "empty" else 200 if category == "huge" else 3
    marker = "OWNED_RAW_BODY_NEVER_EXPORTED"
    paths = []
    for index in range(count):
        path = docs / (("plan雪🙂" if category == "unicode" else "plan-owned-") + str(index) + ".md")
        path.write_text("# Owned\n- [ ] Observe\n- [x] Verified\n" + marker + "\n" + text(category)[:1024], encoding="utf-8")
        paths.append(path)
    treasury = CapabilityTreasury(root)
    result = treasury.snapshot()
    require(result["summary"]["assetCount"] <= 180 and marker not in json.dumps(result, ensure_ascii=False) and not result["trustRaised"] and result["humanApprovalRequired"] and not result["published"] and not result["candidateActivated"], "Treasury exported file bodies or elevated review-only recovery")
    if category == "permissions":
        before = paths[0].read_bytes()
        with denied_file(paths[0]): denied = treasury.snapshot()
        require(marker not in json.dumps(denied) and not denied["trustRaised"] and paths[0].read_bytes() == before, "Denied source read leaked bodies or raised recovery trust")
    elif category == "stale":
        old = next(row for row in result["assets"] if row["path"] == paths[0].relative_to(root).as_posix())["digest"]
        paths[0].write_text("# New owned plan\n- [ ] Verify changed facts\n", encoding="utf-8")
        fresh = treasury.snapshot()
        require(next(row for row in fresh["assets"] if row["path"] == paths[0].relative_to(root).as_posix())["digest"] != old, "Treasury reused stale retained-source digest")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: treasury.snapshot(), range(4)))
        require(all(row["summary"] == result["summary"] and not row["trustRaised"] for row in results), "Concurrent recovery projection lost typed source accounting")
    return {"inputPlanFiles": count, "returnedAssets": result["summary"]["assetCount"], "recoveryMissions": len(result["recoveries"]), "privateBodyExported": False, "humanReviewRequired": True}


def _cloud(root, category, identity):
    from . import app_capability_standard as owner
    from .models import AppCapabilityManifest
    selected = root / ("mount雪🙂" if category == "unicode" else "selected-mount"); selected.mkdir()
    candidates = [] if category == "empty" else [str(selected)] * (32 if category == "huge" else 1)
    manifest = AppCapabilityManifest(manifest_id="owned", schema_version=owner.SCHEMA_VERSION, app_id="cloud-drive-sync", name="Owned cloud observation", description="Selected metadata only",
        bridge={"source_root": str(root), "discovery_roots": candidates}, auth={}, permissions=[], tasks=[], context_surfaces=[], action_hooks=[], ui_hints={})
    previous = os.environ.get("FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT")
    os.environ["FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT"] = "1"
    observations = []
    exists = Path.exists
    def selected_exists(path):
        observations.append(str(path))
        require(path.resolve() == selected.resolve(), "Cloud discovery probed an undeclared ambient root")
        return exists(path)
    try:
        Path.exists = selected_exists
        result = owner._cloud_drive_bridge_plan(root, manifest)
    finally:
        Path.exists = exists
        if previous is None: os.environ.pop("FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT", None)
        else: os.environ["FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT"] = previous
    require(len(result["mountedRoots"]) == (0 if not candidates else 1) and result["requiresApprovalForWrite"] and result["googleLoginReady"] and result["writePolicy"] == "preview_then_approve", "Selected mount/declared login observation lost approval policy")
    require((not observations) if not candidates else all(Path(path) == selected for path in observations), "Empty explicit roots fell back to ambient mounts")
    if category == "stale":
        renamed = root / "renamed-selected-mount"; selected.rename(renamed)
        result = owner._discover_cloud_drive_roots(candidates)
        require(not result, "Cloud mount presence reused stale indexed readiness")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: owner._discover_cloud_drive_roots(candidates), range(4)))
        require(all(len(row) == 1 and row[0]["root"] == str(selected) for row in results), "Concurrent selected discovery lost explicit mounted identity")
    elif category == "permissions":
        require(result["requiresApprovalForWrite"] and result["safeDirections"] == ["upload", "download"], "Mounted presence granted unapproved write execution")
    elif category == "huge":
        refused(lambda: owner._discover_cloud_drive_roots(candidates + [str(selected)]), (ValueError,))
    return {"explicitRoots": len(candidates), "metadataProbes": len(observations), "ambientRootsProbed": False, "rawCredentialsRead": False, "syncExecuted": False}


def _apps(root, category, identity):
    from . import app_capability_standard as owner
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    app = root / "owned-app"; app.mkdir()
    target = root / "owned-target"; target.mkdir()
    bridge = {"transport": "http", "endpoint": f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}", "healthcheck": "/api/status", "event_stream": "/api/job", "workspace_root": str(app), "source_root": str(root), "target_root": str(target),
              "remote_project_root": str(target), "connection_mode": "lan", "nas_host": "owned-loopback-metadata", "control_protocol": "ssh", "control_port": int(os.environ['NEYVIA_C7_PORT']), "requested_ssh_port": int(os.environ['NEYVIA_C7_PORT']), "ssh_user": "owned-no-login", "activation_project": "Owned reviewed project"}
    payload = {"manifest_id": "owned", "schema_version": owner.SCHEMA_VERSION, "app_id": "owned-observer", "name": "Owned observation " + ("雪🙂" if category == "unicode" else ""),
               "description": "Generated local observation only", "bridge": bridge, "auth": {"mode": "local_session", "scopes": []}, "permissions": [] if category == "empty" else ["task.run", "context.read"],
               "tasks": [{"task_id": "owned", "label": "Owned observation", "description": "Observe selected local metadata"}],
               "context_surfaces": [{"surface_id": "owned", "label": "Owned metadata", "description": "Read selected metadata", "access": "read"}],
               "action_hooks": [{"hook_id": "owned", "label": "Owned review", "description": "Review only", "mutability": "write"}], "ui_hints": {}}
    manifest = owner._to_manifest(payload)
    if identity == "a.app-storage":
        ready = owner._synology_bridge_plan(manifest, {}, {})
        require(ready["targetReady"] and ready["requiresApprovalForWrite"] and ready["safeDirections"] == ["upload", "download"], "Selected local storage metadata lost bounded ready directions or approval")
        automatic = copy.deepcopy(payload); automatic["bridge"].update(requires_approval_for_write=False, auto_sync=True, write_policy="automatic_bidirectional")
        auto = owner._synology_bridge_plan(owner._to_manifest(automatic), {}, {})
        require(auto["autoSyncEnabled"] and not auto["requiresApprovalForWrite"] and auto["writePolicy"] == "automatic_bidirectional", "Explicit automatic policy silently changed")
        if category == "stale":
            target.rename(root / "renamed-target")
            missing = owner._synology_bridge_plan(manifest, {}, {})
            require(not missing["targetReady"] and missing["safeDirections"] == [] and missing["activationRequired"] and missing["activationHint"], "Absent mapped root retained stale readiness or lost activation guidance")
        elif category == "offline":
            session = owner._build_synology_fast_sync_session(manifest=manifest, app_root=app, previous_state={}, grants=owner._build_grants(manifest))
            require(session.status == "available" and session.latest_task_result["payload"]["targetReady"] and session.latest_task_result["payload"]["requiresApprovalForWrite"], "Closed owned HTTP observer lost local selected-root metadata or granted writes")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: owner._synology_bridge_plan(manifest, {}, {}), range(4)))
            require(all(row == ready for row in results), "Concurrent read-only storage plans mixed scoped selections")
        elif category in {"empty", "huge", "unicode"}:
            mutated = copy.deepcopy(payload); mutated["bridge"]["activation_project"] = text(category)
            missing = root / "missing-target"
            mutated["bridge"].update(target_root=str(missing), remote_project_root=str(missing))
            plan = owner._synology_bridge_plan(owner._to_manifest(mutated), {}, {})
            require(plan["safeDirections"] == [] and not plan["targetReady"] and plan["activationHint"] and not plan["autoSyncEnabled"], "Absent storage selection lost approved activation metadata")
        return {"selectedTargetPresent": True, "requiresApprovalForWrite": True, "explicitAutomaticPolicyRetained": True, "syncExecuted": False, "networkTarget": "owned loopback only"}
    config = root / "config/connected_apps.json"; config.parent.mkdir()
    count = 16 if category == "huge" else 1
    manifests = [{**copy.deepcopy(payload), "app_id": f"owned-observer-{index}", "manifest_id": f"owned-{index}"} for index in range(count)]
    if category == "offline": manifests[0]["app_id"] = "synology-fast-sync"
    config.write_text(json.dumps(manifests, ensure_ascii=False), encoding="utf-8")
    result = owner.build_connected_apps_snapshot(root)
    require(len(result["connectedSessions"]) == len(result["bridgeHandshakes"]) == count, "Manifest observation lost one session/handshake per source")
    allowed = set(payload["permissions"])
    require(all({grant["capability_key"] for grant in row["granted_capabilities"]} <= allowed for row in result["connectedSessions"]), "Observation granted undeclared capabilities")
    state_path = root / ".agent_control/connected_apps_state.json"; original = state_path.read_bytes()
    if category == "permissions":
        with denied_file(state_path): refused(lambda: owner.build_connected_apps_snapshot(root), (OSError,))
        require(state_path.read_bytes() == original, "Denied observation changed accepted session state")
    elif category == "interrupted":
        manifests.append({**copy.deepcopy(payload), "app_id": "owned-fresh", "manifest_id": "owned-fresh"})
        config.write_text(json.dumps(manifests), encoding="utf-8")
        with replacement_fault(owner, state_path, OSError) as faults:
            refused(lambda: owner.build_connected_apps_snapshot(root), (OSError,))
        require(faults and state_path.read_bytes() == original, "Interrupted new-session observation destroyed existing session state")
    elif category == "stale":
        manifests[0]["permissions"] = ["context.read"]
        config.write_text(json.dumps(manifests), encoding="utf-8")
        fresh = owner.build_connected_apps_snapshot(root)
        require({row["capability_key"] for row in fresh["connectedSessions"][0]["granted_capabilities"]} == {"context.read"}, "Fresh declaration retained stale broader grants")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: owner.build_connected_apps_snapshot(root), range(4)))
        require(all(len(row["connectedSessions"]) == len(row["bridgeHandshakes"]) == count for row in results), "Concurrent observation duplicated/dropped manifest bindings")
    return {"actualManifestRecords": count, "matchingSessionsAndHandshakes": count, "undeclaredGrants": 0, "providerAuthenticationProven": False}


def _evolution_setup(root, category, *, create_app=True):
    """The existing reviewed family mechanism with explicit local policy inputs.

    Typed receipt data exercises reducer/admission policy; it does not prove a
    provider run, a rendered application, or the usefulness of its workflow.
    """
    from .capability_evolution import NeyviaCapabilityEvolution
    from .app_factory import AppFactory
    service = NeyviaCapabilityEvolution(root, database_path=root / "evolution.sqlite3", hermes_import_dir=root / "hermes")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda delta=timedelta(): (now + delta).isoformat()
    trial = service.create_trial({"capabilityId": "owned-reviewed-workflow", "capabilityKind": "skill", "label": "Owned reviewed workflow", "action": "branch", "context": {"conversationId": "owned-policy-fixture"}})
    name = trial["candidate"]["targetSkillId"]
    markdown = f"---\nname: {name}\ndescription: Retain exact locally reviewed observations.\n---\n# Owned workflow\n\n1. Inspect the current selected contract.\n2. Retain its observed result without expanding authority.\n3. Review the result before using the workflow.\n"
    markdown += "\n" + text(category)[:4096].replace("\x00", "")
    trial = service.seal_skill_candidate(trial["trialId"], skill_markdown=markdown, review_confirmed=True)
    def record(identity, duration, artifacts):
        return {"turnId": identity, "conversationId": "owned-policy-fixture", "createdAt": iso(), "receipt": {"schema": "fluxio.turn_receipt.v1", "sessionId": "owned-policy-fixture", "missionId": "owned-policy-fixture", "runtime": "codex", "provider": "owned-lab", "model": "supplied-policy-input", "effort": "high", "status": "completed", "exitCode": 0, "endedAt": iso(), "durationMs": duration,
                "toolTimeline": [{"kind": "verification.test", "summary": "Supplied local policy fixture", "status": "passed"}], "changedFiles": ["proof/local-result.txt"], "proofArtifacts": [{"kind": "test", "path": f"proof/{identity}-{index}.json"} for index in range(artifacts)],
                "assistantMessage": "OWNED_TRANSCRIPT_NOT_STORED", "permissionSummary": {"allowed": ["workspace.read", "process.execute"], "approvalRequired": ["workspace.write"], "denied": ["network.write"]}}}
    for index in range(2):
        trial = service.record_receipt_comparison(trial["trialId"], baseline_record=record(f"owned-base-{index}", 12000, 1), candidate_record=record(f"owned-candidate-{index}", 6000, 2), same_contract_confirmed=True, operator_value="candidate_better")
    trial = service.build_counterfactual_forge(trial["trialId"], case_run_ids=[row["runId"] for row in trial["evidence"]], review_confirmed=True)
    trial = service.decide_trial(trial["trialId"], decision="accept")
    digest = trial["candidate"]["packageDigest"]
    materialized = service.materialize_skill_candidate(trial["trialId"], candidate_digest=digest, review_confirmed=True)
    dependency = root / "proof/runtime.lock"; dependency.parent.mkdir(); dependency.write_text("owned-local-dependency-v1\n")
    providers = {"owned-lab": True}
    lease = service.establish_capability_proof_lease(materialized["materializationId"], goal_statement="Retain a locally reviewed exact workflow for operator use.", dependency_paths=["proof/runtime.lock"], review_after_days=30, review_confirmed=True, provider_availability=providers, now=iso())
    require(lease["state"] == "current" and not lease["candidateActivated"], "Local declaration lease lost dependency binding or activated candidate")
    handoff = service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=True, provider_availability=providers)
    factory = AppFactory(root)
    app = factory.create_from_capability_handoff(handoff, name="Owned Guided Workflow", brief="Guide a locally reviewed workflow and retain bound portable observations.", target="neyvia", theme="paper", directory="apps/owned-guided-workflow") if create_app else None
    if app: require(app["status"] == "ready" and not app["capabilityHandoff"]["candidateActivated"], "Guided local draft lost inactive lineage")
    return service, factory, trial, materialized, lease, handoff, app, providers, dependency, iso


def _evolution(root, category, identity):
    import sqlite3
    service, factory, trial, materialized, lease, handoff, app, providers, dependency, iso = _evolution_setup(root, category, create_app=identity != "a.factory-lineage")
    if identity in {"a.evolution-inactive", "a.evolution-handoff", "a.evolution-lease", "a.factory-lineage"}:
        return _evolution_bound(root, category, identity, service, factory, trial, materialized, lease, handoff, app, providers, dependency)
    if identity == "a.evolution-outcome":
        count = 128 if category == "huge" else 1
        nodes = [{"nodeId": f"owned-{index}", "runtime": "hermes", "title": text(category)[:4096], "lifecycleStage": "completed", "capabilities": [f"owned.capability{index}"],
                  "resultSummary": {"schema": "neyvia.agent_delta.v1", "delta": {"schema": "neyvia.agent_delta.v1", "claims": [{"text": "Supplied local policy observation"}], "evidence": [{"path": "proof/owned.json", "passed": True}], "artifacts": [], "conflicts": [], "blockers": [], "notes": []}}} for index in range(count)]
        graph = {"conversationId": "owned-policy-fixture", "synthesis": {"synthesisId": "owned", "status": "ready", "candidateNodeIds": [row["nodeId"] for row in nodes]}, "nodes": nodes}
        action = lambda: service.accept_constellation_outcome(constellation=graph, synthesis_id="owned", mission_id="owned-policy-fixture")
        result = action(); replay = action()
        require(result["status"] == "accepted_into_learning" and result["observationCount"] == count and {row["observationId"] for row in result["observations"]} == {row["observationId"] for row in replay["observations"]}, "Typed local outcome lost durable idempotent identity")
        if category == "empty": refused(lambda: service.accept_constellation_outcome(constellation={}, synthesis_id=""), (ValueError,))
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: action(), range(4)))
            require(all(row["observations"][0]["observationId"] == result["observations"][0]["observationId"] for row in results), "Concurrent typed outcome replay created duplicate learning rows")
        elif category in {"stale", "permissions"}:
            stale = copy.deepcopy(graph); stale["synthesis"]["status"] = "blocked_evidence"
            refused(lambda: service.accept_constellation_outcome(constellation=stale, synthesis_id="owned"), (ValueError,))
        elif category == "interrupted":
            fresh = copy.deepcopy(graph); fresh["synthesis"]["synthesisId"] = "owned-crash"; fresh["nodes"][0]["capabilities"] = ["owned.new-crash-only"]
            _evolution_interruption(root, service.database_path, {"kind": "outcome", "graph": fresh})
        return {"actualSqliteObservations": count, "idempotentReplay": True, "typedInputsOnly": True, "providerProof": False}
    binding = app["capabilityHandoff"]
    bundle = {"schema": "neyvia.capability-run-bundle/v2", "appFactoryJobId": app["jobId"], "appId": app["spec"]["appId"], **{key: binding[key] for key in ("handoffId", "handoffDigest", "candidateDigest", "skillId", "proofLease")}, "exportedAt": iso(), "candidateActivated": False, "transcriptsIncluded": False, "runs": []}
    def run(index):
        value = {"schema": "neyvia.capability-run/v2", "runId": f"owned-{index}", **{key: bundle[key] for key in ("appFactoryJobId", "appId", "handoffId", "handoffDigest", "candidateDigest", "skillId", "proofLease")},
                 "goal": "OWNED_PRIVATE_GOAL " + text(category)[:1024], "status": "sealed", "outcome": "completed", "operatorValue": "helpful", "friction": {"code": "verification_gap", "severity": "medium", "correctionCount": 1, "usualMinutes": 30}, "proofNote": "OWNED_PRIVATE_PROOF", "startedAt": iso(timedelta(minutes=-25)), "completedAt": iso(timedelta(minutes=-15)),
                 "steps": [{"text": "OWNED_PRIVATE_STEP", "complete": True, "note": "OWNED_PRIVATE_NOTE", "updatedAt": iso(timedelta(minutes=-15))}], "candidateActivated": False, "transcriptsIncluded": False}
        value["receiptDigest"] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return value
    runs = [run(index) for index in range(64 if category == "huge" else 2)]
    action = lambda: service.import_capability_run_bundle({**bundle, "runs": runs}, app_factory_jobs=[app], provider_availability=providers)
    result = action(); replay = action()
    require(result["importedRunCount"] == len(runs) and replay["importedRunCount"] == 0 and replay["duplicateRunCount"] == len(runs) and not result["trustRaised"], "Typed outcome import lost exact durable deduplication/privacy")
    with sqlite3.connect(service.database_path) as connection:
        stored = connection.execute("SELECT measurements_json,evidence_json FROM capability_observations WHERE source_kind='app_run'").fetchall()
    require(len(stored) == len(runs) and all(marker not in json.dumps(stored) for marker in ("OWNED_PRIVATE_GOAL", "OWNED_PRIVATE_PROOF", "OWNED_PRIVATE_STEP", "OWNED_PRIVATE_NOTE")), "Typed importer retained private run bodies")
    if category == "empty": refused(lambda: service.import_capability_run_bundle({}, app_factory_jobs=[app]), (ValueError,))
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: action(), range(4)))
        require(all(row["importedRunCount"] == 0 and row["duplicateRunCount"] == len(runs) for row in results), "Concurrent imported receipt replay double-counted outcomes")
    elif category in {"stale", "permissions"}:
        changed = copy.deepcopy(bundle); changed["candidateActivated"] = True
        refused(lambda: service.import_capability_run_bundle({**changed, "runs": runs}, app_factory_jobs=[app], provider_availability=providers), (ValueError,))
    elif category == "interrupted":
        _evolution_interruption(root, service.database_path, {"kind": "friction", "bundle": {**bundle, "runs": [run(900)]}, "app": app, "providers": providers})
    return {"actualSqliteImports": len(stored), "rawBodiesStored": False, "idempotentReplay": True, "renderedOrProviderProof": False}


def _evolution_interruption(root, database, payload):
    import sqlite3
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    def snapshot():
        connection = sqlite3.connect(database)
        try: return hashlib.sha256("\n".join(connection.iterdump()).encode()).hexdigest()
        finally: connection.close()
    before = snapshot()
    request = root / "owned-crash-request.json"; request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", MODULE, "--port", os.environ["NEYVIA_C7_PORT"], "--crash-evolution", str(root)],
                            capture_output=True, text=True, timeout=30, **hidden_windows_subprocess_kwargs())
    require(result.returncode == 23, "Owned SQLite child did not die before real commit: " + result.stderr[-800:])
    require(snapshot() == before, "Interrupted SQLite transaction leaked partial observations/lineage")
    return {"childExit": result.returncode, "durableRowsSha256": before}


def _evolution_bound(root, category, identity, service, factory, trial, materialized, lease, handoff, app, providers, dependency):
    from . import capability_evolution as owner
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    mid = materialized["materializationId"]; digest = materialized["candidateDigest"]
    if identity == "a.evolution-lease":
        action = lambda: service.assess_capability_proof_lease(mid, provider_availability=providers)
        require(action()["state"] == "current", "Exact local dependency/package lease was not current")
        if category == "offline":
            denied = service.assess_capability_proof_lease(mid, provider_availability={"owned-lab": False})
            require(denied["state"] == "held" and not denied["canPromoteToApp"], "Declared unavailable route retained promotability")
        elif category == "permissions":
            with denied_file(dependency): denied = action()
            require(denied["state"] != "current" and not denied["canPromoteToApp"], "Unreadable dependency retained current lease")
        elif category == "stale":
            dependency.write_text("owned-local-dependency-v2\n")
            require(action()["state"] == "reproof_required", "Changed local dependency retained stale lease")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: action(), range(4)))
            require(all(row["state"] == "current" and row["leaseDigest"] == lease["leaseDigest"] for row in results), "Concurrent assessment lost current digest binding")
        return {"leaseDigest": lease["leaseDigest"], "packageAndDependencyBytesVerified": True, "providerAvailability": "supplied policy input", "externalProviderProved": False}
    if identity == "a.evolution-handoff":
        action = lambda: service.prepare_app_factory_handoff(mid, candidate_digest=digest, review_confirmed=True, provider_availability=providers, reviewed_by=text(category) or "owned")
        result = action()
        require(result["candidateDigest"] == digest and result["proofLease"]["leaseDigest"] == lease["leaseDigest"] and not any(result[key] for key in ("candidateActivated", "appActivated", "transcriptsIncluded")), "Reviewed handoff lost exact inactive package/lease boundary")
        if category in {"empty", "huge", "permissions"}:
            refused(lambda: service.prepare_app_factory_handoff(mid, candidate_digest="" if category == "empty" else "x" * 100000 if category == "huge" else digest, review_confirmed=category != "permissions", provider_availability=providers), (ValueError,))
        elif category == "stale":
            dependency.write_text("owned changed dependency\n")
            refused(action, (ValueError,))
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: action(), range(4)))
            require(all(row["handoffDigest"] == result["handoffDigest"] for row in results), "Concurrent reviewed handoff lost stable contract digest")
        return {"handoffDigest": result["handoffDigest"], "candidateActivated": False, "localDraftOnly": True, "transcriptsIncluded": False}
    if identity == "a.evolution-inactive":
        package = Path(materialized["packagePath"]); original = (package / "SKILL.md").read_bytes()
        if category == "interrupted":
            rollback = package.parents[1] / "rollback.json"
            original_replace = Path.replace; faults = []
            def replace(source, destination):
                if Path(destination).resolve() == rollback.resolve():
                    faults.append({"temporaryBytes": source.stat().st_size})
                    raise OSError("Owned interruption before rollback publication")
                return original_replace(source, destination)
            Path.replace = replace
            try:
                refused(lambda: service.rollback_skill_materialization(mid, candidate_digest=digest, review_confirmed=True), (OSError,))
            finally:
                Path.replace = original_replace
            require(faults and not rollback.exists() and (package / "SKILL.md").read_bytes() == original, "Interrupted withdrawal published a partial receipt or changed retained package")
        elif category == "permissions":
            refused(lambda: service.rollback_skill_materialization(mid, candidate_digest=digest, review_confirmed=False), (ValueError,))
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: service.materialize_skill_candidate(trial["trialId"], candidate_digest=digest, review_confirmed=True), range(4)))
            require(all(row["materializationId"] == mid for row in results), "Concurrent materialization replay created duplicate inactive branches")
        elif category == "stale":
            refused(lambda: service.rollback_skill_materialization(mid, candidate_digest="b" * 64, review_confirmed=True), (ValueError,))
        elif category in {"empty", "huge"}:
            refused(lambda: service.materialize_skill_candidate(trial["trialId"], candidate_digest="" if category == "empty" else "x" * 100000, review_confirmed=True), (ValueError,))
        withdrawn = service.rollback_skill_materialization(mid, candidate_digest=digest, review_confirmed=True, reason=text(category) or "Owned rollback")
        require(withdrawn["state"] == "withdrawn" and package.is_dir() and (package / "SKILL.md").read_bytes() == original and not withdrawn["candidateActivated"], "Inactive withdrawal lost retained immutable package or activated capability")
        return {"materializationId": mid, "withdrawn": True, "retainedPackageSha256": hashlib.sha256(original).hexdigest(), "candidateActivated": False}
    from . import app_factory as factory_owner
    args = {"name": "Owned Guided Workflow " + ("雪🙂" if category == "unicode" else ""), "brief": "Guide a locally reviewed workflow and retain bound portable observations.", "target": "neyvia", "theme": "paper", "directory": "apps/owned-guided-workflow"}
    action = lambda: factory.create_from_capability_handoff(handoff, **args)
    if category == "interrupted":
        destination = factory.handoffs_root / handoff["handoffId"]
        with replacement_fault(factory_owner, destination, OSError) as faults:
            refused(action, (OSError, RuntimeError))
        require(faults and not destination.exists(), "Interrupted lineage copy published partial source authority")
    elif category == "permissions":
        forbidden = copy.deepcopy(handoff); forbidden["state"] = "unreviewed"
        refused(lambda: factory.create_from_capability_handoff(forbidden, **args), (ValueError, RuntimeError))
    elif category == "stale":
        source = Path(handoff["sourcePackage"]["skillPath"]); original = source.read_bytes()
        source.write_bytes(original + b"\nchanged unreviewed source\n")
        refused(action, (ValueError, RuntimeError))
        source.write_bytes(original)
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: jobs = list(pool.map(lambda _: action(), range(4)))
        require(len({job["jobId"] for job in jobs}) == 1, "Concurrent exact capsule created multiple guided drafts")
        app = jobs[0]
    else: app = action()
    require(app["status"] == "ready" and app["capabilityHandoff"]["handoffDigest"] == handoff["handoffDigest"] and not app["capabilityHandoff"]["candidateActivated"], "Ready guided draft lost copied reviewed inactive lineage")
    if category in {"empty", "huge"}:
        refused(lambda: factory.create_from_capability_handoff(handoff, **{**args, "name": "" if category == "empty" else "N" * 100000}), (ValueError, RuntimeError))
        require(factory.get_job(app["jobId"])["status"] == "ready", "Rejected name rebind corrupted retained ready draft")
    return {"jobId": app["jobId"], "handoffDigest": handoff["handoffDigest"], "previewRoot": str(Path(app["projectRoot"]) / "dist"), "rendered": False, "candidateActivated": False}


def _crash_evolution(root):
    import sqlite3
    from .capability_evolution import NeyviaCapabilityEvolution
    service = NeyviaCapabilityEvolution(root, database_path=root / "evolution.sqlite3", hermes_import_dir=root / "hermes")
    payload = json.loads((root / "owned-crash-request.json").read_text(encoding="utf-8"))
    connect = sqlite3.connect
    class CrashBeforeCommit(sqlite3.Connection):
        def commit(self):
            if self.in_transaction: os._exit(23)
            return super().commit()
    def guarded_connect(database, *args, **kwargs):
        if Path(database).resolve() == service.database_path.resolve(): kwargs["factory"] = CrashBeforeCommit
        return connect(database, *args, **kwargs)
    sqlite3.connect = guarded_connect
    try:
        if payload["kind"] == "outcome":
            service.accept_constellation_outcome(constellation=payload["graph"], synthesis_id="owned-crash", mission_id="owned-policy-fixture")
        else:
            service.import_capability_run_bundle(payload["bundle"], app_factory_jobs=[payload["app"]], provider_availability=payload["providers"])
    finally:
        sqlite3.connect = connect
    raise AssertionError("Owned mutation never reached commit boundary")


def _sdk(root, category, identity):
    from . import sdk
    from .edge_fixture_preferences_skills import denied_file
    value = text(category)
    if identity == "sv.sdk.manifest":
        manifest = sdk.build_solantir_manifest(workspace_root=str(root), endpoint=f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}")
        require(manifest["app_id"] and manifest["tasks"] and manifest["context_surfaces"], "Manifest lost declared tasks/context")
        return {"appId": manifest["app_id"], "declarationsOnly": True}
    if identity == "sv.sdk.bindings":
        from . import sdk_codegen as owner
        repo = Path(__file__).resolve().parents[2]
        (root / "config").mkdir()
        for name in ("neyvia_module_manifest_schema.json", "neyvia_application_surface_schema.json"):
            (root / "config" / name).write_bytes((repo / "config" / name).read_bytes())
        first = owner.generated_bindings(root)
        require(first == owner.generated_bindings(root), "Actual binding generator changed identical input")
        if category == "permissions":
            source = root / "config/neyvia_module_manifest_schema.json"
            before = source.read_bytes()
            with denied_file(source): error = refused(lambda: owner.generated_bindings(root), (owner.LossySchemaError,))
            require(source.read_bytes() == before, "Denied schema generation modified source")
        elif category == "stale":
            source = root / "config/neyvia_module_manifest_schema.json"
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["title"] = "Fresh owned schema"
            source.write_text(json.dumps(payload), encoding="utf-8")
            require(owner.load_schema_sources(root)[0].schema["title"] == payload["title"], "Generator reused stale source")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(lambda _: owner.generated_bindings(root), range(16)))
            require(all(result == first for result in results), "Concurrent binding projection changed bytes")
        elif category in {"empty", "huge", "unicode"}:
            source = root / "config/neyvia_module_manifest_schema.json"
            payload = json.loads(source.read_text(encoding="utf-8")); payload["description"] = value
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            require(owner.load_schema_sources(root)[0].schema["description"] == value, "Generator lost exact source literal")
            require(owner.generated_bindings(root) == owner.generated_bindings(root), "Text-source generation was not deterministic")
        return {"returnedFiles": len(first), "sourceLocal": True, "generatedBytes": sum(len(content) for content in first.values()), "published": False}
    if identity == "sv.sdk.plan-only":
        surface = sdk.build_application_surface(surface_id="owned.preview", title="Owned preview", description=value[:300] or "Owned plan", permissions={"inspect": [], "launch": [], "control": []},
                  targets=[{"target_id": "web.owned", "kind": "web", "platform": "web", "build": {"status": "not_required"}, "launch": {"kind": "url", "url": f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}"}, "required_permissions": []}])
        manifest = {"app_id": "owned.preview", "name": "Owned preview", "application_surface": surface}
        def plan():
            return sdk.plan_application_surface_launch(manifest, target_id="web.owned", workspace_root=root, approval_id=value)
        result = plan()
        require(not any(result["executionPolicy"][key] for key in ("executes", "builds", "installs", "publishes")) and result["status"] != "ready", "SDK plan acquired active authority")
        profile = sdk.plan_install_profile("recommended", workspace_root=root)
        require(not profile.get("installationExecuted", False), "Profile planning executed installation")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: plans = list(pool.map(lambda _: plan(), range(16)))
            require(all(not row["executionPolicy"]["executes"] for row in plans), "Concurrent SDK plans executed")
        elif category == "permissions":
            require(result["approval"]["valid"] is False, "Arbitrary caller approval text gained authority")
        elif category == "stale":
            changed = copy.deepcopy(manifest); changed["application_surface"]["title"] = "Updated owned declaration"
            fresh = sdk.plan_application_surface_launch(changed, target_id="web.owned", workspace_root=root)
            require(fresh["manifestHash"] != result["manifestHash"], "Plan reused stale manifest binding")
        return {"status": result["status"], "executes": False, "installs": False, "liveReadiness": False}
    # An actual owned HTTP receiver records the exact wire request. It exercises
    # client transport only, never represents a Neyvia app or external provider.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import urllib.error
    observed = []
    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            observed.append({"path": self.path, "body": body, "cookie": self.headers.get("Cookie", "")})
            if self.path == "/abort":
                self.connection.shutdown(2); self.connection.close(); return
            reply = json.dumps({"ok": True, "data": json.loads(body)}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(reply)
    port = int(os.environ["NEYVIA_C7_PORT"])
    server = ThreadingHTTPServer(("127.0.0.1", port), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    client = sdk.FluxioClient(f"http://127.0.0.1:{port}", timeout_seconds=2)
    payload = {"value": value}
    try:
        reply = client._post("/owned", payload, include_cookie=False)
        require(reply["data"] == payload and json.loads(observed[-1]["body"]) == payload and observed[-1]["path"] == "/owned", "Wire path/body changed")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool: replies = list(pool.map(lambda _: client._post("/owned", payload, include_cookie=False), range(16)))
            require(all(row["data"] == payload for row in replies), "Concurrent wire response mismatch")
        elif category == "permissions":
            client._cookie = "owned=generated"
            client._post("/owned", payload, include_cookie=False)
            require(not observed[-1]["cookie"], "Excluded session cookie reached wire")
            client._post("/owned", payload, include_cookie=True)
            require(observed[-1]["cookie"] == client._cookie, "Explicit session cookie omitted")
        elif category == "interrupted":
            refused(lambda: client._post("/abort", payload, include_cookie=False), (OSError,))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    if category == "offline":
        refused(lambda: client._post("/owned", payload, include_cookie=False), (urllib.error.URLError, OSError))
    return {"actualHttpRequests": len(observed), "wireBytes": len(observed[0]["body"]), "ownedPort": port, "providerProof": False}


def _support(root, category, identity):
    from . import support_bundle as owner
    from .edge_fixture_local import replacement_fault
    from .edge_fixture_preferences_skills import denied_file
    from zipfile import ZipFile
    jobs = root / "workspace/.agent_control/harness_jobs"; jobs.mkdir(parents=True)
    work = root / "workspace"
    count = 0 if category == "empty" else 64 if category == "huge" else 3
    for index in range(count):
        row = {"id": f"harness-job-{index}", "status": "blocked", "prompt": text(category), "error": "AuthError: password=owned-private-secret", "result": {"providerId": "owned-local", "blockedReason": "offline"}}
        (jobs / f"harness-job-{index}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        (jobs / f"harness-job-{index}.log").write_text("password=owned-private-secret\n" + text(category), encoding="utf-8")
    output = root / "support.zip"
    result = owner.build_redacted_support_bundle(work, output, max_jobs=2)
    original = output.read_bytes()
    with ZipFile(output) as archive:
        names = set(archive.namelist()); data = b"\n".join(archive.read(name) for name in names)
        jobs_payload = json.loads(archive.read("harness-jobs.json"))
    require(names == {"manifest.json", "runtime.json", "harness-jobs.json", "logs/index.json", "redaction-policy.json"}, "Support archive added unallowlisted bytes")
    require(b"owned-private-secret" not in data and str(work).encode() not in data and result["selectedHarnessJobs"] == min(count, 2), "Support archive leaked secrets/path or exceeded selection")
    if category == "interrupted":
        with replacement_fault(owner, output, OSError) as observed:
            error = refused(lambda: owner.build_redacted_support_bundle(work, output, overwrite=True), (OSError,))
        require(observed and output.read_bytes() == original, "Interrupted support publication lost previous archive")
    elif category == "permissions":
        with denied_file(output): refused(lambda: owner.build_redacted_support_bundle(work, output, overwrite=True), (OSError,))
        require(output.read_bytes() == original, "Denied support replacement destroyed archive")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda index: owner.build_redacted_support_bundle(work, root / f"concurrent-{index}.zip", max_jobs=2), range(4)))
        require(all(row["selectedHarnessJobs"] == 2 for row in replies), "Concurrent bounded support exports lost source observations")
    return {"selectedJobs": result["selectedHarnessJobs"], "archiveBytes": len(original), "archiveSha256": result["sha256"], "rawContentIncluded": False}


def _cu(root, category, identity):
    from . import computer_use_twin as owner
    from .computer_use_verifier import ComputerUseVerifierService
    from .edge_fixture_preferences_skills import denied_file
    receipt = {"status": "passed", "pass": True, "baseUrl": f"http://127.0.0.1:{os.environ['NEYVIA_C7_PORT']}", "durationMs": 120,
               "treeOmitted": True, "results": [{"flow": "control_room", "pass": True, "skipped": False, "reason": text(category)} for _ in range(3 if category == "huge" else 1)]}
    replay = root / "owned-replay.json"; replay.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    twin = owner.ComputerUseTwinService(root)
    saved = twin.save_spec({"name": "Owned local replay", "mode": "replay", "flows": ["control_room"], "replayReceiptPath": str(replay)}, approved=True)
    require(saved["ok"], "Local replay specification was not saved")
    if identity == "a.cu-portable":
        payload = {"runner": "computer_use_twin", "twinSpec": {**saved["spec"], "replayReceiptPath": "unreachable-controller.json", "thresholds": {**saved["spec"]["thresholds"], "requireLiveProof": False}}, "replayReceipt": receipt}
        index = [0]
        def action():
            index[0] += 1
            return owner.execute_cluster_twin_job(payload, root=root / f"worker-{uuid.uuid4().hex}")
        result = action(); run = result["computerUseTwin"]
        require(result["returnCode"] == (0 if run["status"] == "passed" else 1) and Path(result["artifacts"][0]["path"]).is_relative_to(root) and not run["liveProof"], "Inline worker replay depended on controller state or granted live proof")
        if category == "huge": require(run["status"] == "failed", "Oversized replay lost compact-context failure gate")
    elif identity == "a.cu-verifier":
        verifier = ComputerUseVerifierService(root)
        request = {"mode": "replay", "flows": ["control_room"], "replayReceiptPath": str(replay), "approved": True, "changeId": text(category)}
        require(verifier.verify({**request, "approved": False})["status"] == "approval_required", "Replay verifier bypassed approval")
        action = lambda: verifier.verify(request)
        result = action(); run = result
        require(not any(result["claims"].values()), "Supplied replay models granted functional/comparative authority")
    else:
        action = lambda: twin.run(saved["spec"]["specId"])
        result = action(); run = result
    require(run["evidenceMode"] == "replay" and not run["liveProof"] and not run["comparison"]["comparativeClaimAllowed"], "Replay became rendered/live proof")
    if category == "empty":
        replay.write_text("{}", encoding="utf-8")
        if identity != "a.cu-portable":
            empty = action(); require(not empty["liveProof"], "Empty receipt became live proof")
    elif category == "permissions":
        if identity != "a.cu-portable":
            with denied_file(replay): refused(action, (OSError, ValueError))
        else:
            # Inline replay is portable even when its controller path is denied.
            with denied_file(replay): require(action()["returnCode"] == 0, "Portable inline replay read denied controller bytes")
    elif category == "stale":
        receipt["pass"] = False
        for row in receipt["results"]: row["pass"] = False
        replay.write_text(json.dumps(receipt), encoding="utf-8")
        changed = action()
        observed = changed["computerUseTwin"] if identity == "a.cu-portable" else changed
        require(observed["metrics"]["flowSuccessRate"] == 0 and not observed["liveProof"], "Current failed replay retained a stale passing projection")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: action(), range(4)))
        runs = [item["computerUseTwin"] if identity == "a.cu-portable" else item for item in results]
        require(len({item["runId"] if "runId" in item else item["verificationId"] for item in runs}) == 4 and all(not item["liveProof"] for item in runs), "Concurrent replay overwrote another run or granted live proof")
    elif category == "interrupted":
        from .edge_fixture_local import replacement_fault
        original_replace = owner.os.replace; faults = []
        def replace(source, destination):
            path = Path(destination)
            if path.name.startswith("cutwinrun_"):
                faults.append(path); raise OSError("Owned interruption before replay receipt publication")
            return original_replace(source, destination)
        owner.os.replace = replace
        try: refused(action, (OSError,))
        finally: owner.os.replace = original_replace
        require(faults and all(not path.exists() for path in faults), "Interrupted replay published a completed receipt")
    return {"localReplayOnly": True, "rendered": False, "externalWorkerExecuted": False, "liveProof": False, "recordedResults": len(receipt["results"])}


def _tools(root, category, identity):
    from .tool_manifest_registry import ToolManifest, ToolManifestRegistry
    from .edge_fixture_preferences_skills import denied_file
    repo = Path(__file__).resolve().parents[2]
    lock = json.loads((repo / "config/tool_suite_lock.json").read_text(encoding="utf-8"))
    if identity == "a.tool-reference":
        payload = copy.deepcopy(next(row for row in lock["tools"] if row["toolId"] == "tool.pandoc"))
        source = repo / payload["metadata"]["defaultReferenceDoc"]
        owned = root / "reference-雪.docx"; owned.write_bytes(source.read_bytes())
        payload["metadata"]["defaultReferenceDoc"] = owned.relative_to(repo).as_posix()
        payload["metadata"]["defaultReferenceDocSha256"] = hashlib.sha256(owned.read_bytes()).hexdigest()
        action = lambda: ToolManifest.from_payload(payload)
        action()
        if category == "permissions":
            with denied_file(owned): refused(action, (OSError,))
        elif category == "stale":
            owned.write_bytes(owned.read_bytes() + b"changed")
            refused(action)
        elif category in {"empty", "huge"}:
            payload["metadata"]["defaultReferenceDocSha256"] = "" if category == "empty" else "a" * 100000
            refused(action)
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: require(all(pool.map(lambda _: action().tool_id == "tool.pandoc", range(4))), "Concurrent pinned reference validation lost selected bytes")
        return {"selectedReferenceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "pinnedGeometryValidated": True, "executionClaimed": False}
    if identity == "a.tool-readiness":
        payload = copy.deepcopy(lock["tools"][0]); payload["name"] = text(category) or payload["name"]
        parsed = ToolManifest.from_payload(payload)
        path = root / "selected-lock.json"; path.write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
        registry = ToolManifestRegistry(path)
        current = registry.snapshot(); require(all(not row["executionReady"] for row in current["tools"]), "Pin metadata without attached runtime proved execution")
        if category == "permissions":
            for field in ("accessToken", "access_token", "refresh-token", "apiKey", "sessionKey", "privateKey", "credentials"):
                forbidden = copy.deepcopy(payload); forbidden.setdefault("metadata", {})[field] = "owned-not-a-secret"
                refused(lambda: ToolManifest.from_payload(forbidden), (ValueError,))
            safe = copy.deepcopy(payload); safe.setdefault("metadata", {}).update(credentialsExposed=False, credentialPathsExposed=False)
            require(ToolManifest.from_payload(safe).metadata["credentialsExposed"] is False, "Public privacy-status booleans were mistaken for credentials")
            with denied_file(path): refused(registry.reload, (OSError,))
        elif category == "stale":
            lock["tools"][0]["state"] = "planned"; path.write_text(json.dumps(lock), encoding="utf-8"); registry.reload()
            require(registry.tools[lock["tools"][0]["toolId"]].state == "planned", "Reload retained a prior declared state")
        elif category == "concurrency":
            with ThreadPoolExecutor(max_workers=4) as pool: require(all(pool.map(lambda _: registry.snapshot()["summary"]["tools"] == len(lock["tools"]), range(4))), "Concurrent inventory lost metadata count")
        elif category == "empty": refused(lambda: ToolManifest.from_payload({}), (ValueError,))
        elif category == "huge":
            payload["packageSha256"] = "a" * 100000; refused(lambda: ToolManifest.from_payload(payload), (ValueError,))
        registry.search(text(category))
        return {"tools": len(registry.tools), "operationsDeferred": current["operationsDeferred"], "executionClaimed": False}
    from .proof_credential_guard import prepare_broker_fixture
    from .capability_service import CapabilityService
    prepare_broker_fixture(root); service = CapabilityService(root)
    requests = [("tool.neyvia-encrypted-chat", "chat.compatibility"), ("tool.neyvia-secret-broker", "secret.compatibility"), ("tool.neyvia-p2p-cache", "cache.provider-status")]
    if identity == "a.tool-typed": requests.append(("tool.neyvia-p2p-cache", "cache.compatibility"))
    def action():
        rows = [service.execute_tool_operation({"toolId": tool, "operationId": operation, "arguments": {}}) for tool, operation in requests]
        require(all(row["ok"] and row["inputValidation"]["valid"] and row["outputValidation"]["valid"] for row in rows), "Typed compatibility failed current schema boundaries")
        serialized = json.dumps([row["result"] for row in rows])
        require(not any(f'"{field}"' in serialized for field in ("credentialsPath", "accessToken", "sessionEnvRef", "appDataDir", "heartbeatKeyHash", "endpointId", "ticket")), "Private identity escaped compatibility projection")
        return rows
    action()
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: require(all(pool.map(lambda _: bool(action()), range(4))), "Concurrent compatibility projection failed")
    elif category in {"empty", "huge", "unicode", "permissions", "stale"}:
        refused(lambda: service.execute_tool_operation({"toolId": requests[0][0], "operationId": "missing-" + text(category)[:256], "arguments": {"accessToken": "owned-marker"}}), (KeyError,))
        malformed = service.execute_tool_operation({"toolId": requests[0][0], "operationId": requests[0][1], "arguments": {"accessToken": text(category)}})
        require(not malformed["ok"] and malformed["status"] == "invalid_arguments", "Secret-shaped undeclared input escaped typed schema admission")
        if category == "stale":
            selected = copy.deepcopy(next(row for row in lock["tools"] if row["toolId"] == requests[0][0]))
            selected["state"] = "planned"
            service.tool_manifests.tools[requests[0][0]] = ToolManifest.from_payload(selected)
            require(service.execute_tool_operation({"toolId": requests[0][0], "operationId": requests[0][1], "arguments": {}})["status"] == "tool_not_ready", "Current narrowed declaration retained stale operation readiness")
            selected["state"] = "verified"; service.tool_manifests.tools[requests[0][0]] = ToolManifest.from_payload(selected)
        action()
    return {"typedOperations": len(requests), "privateValuesExposed": False, "adapterExecutionClaimed": False}


def _pdf(root, category, identity):
    import shutil
    from .capability_adapters import CapabilityAdapterRegistry
    from .capability_contracts import AdapterDescriptor
    from .edge_fixture_preferences_skills import denied_file
    executable = shutil.which("pdftotext")
    require(executable and "neyvia-next" not in executable.casefold() and "projects\\neyvia\\" not in executable.casefold(), "Selected installed Poppler must be outside protected projects")
    registry = CapabilityAdapterRegistry(root)
    registry.register(AdapterDescriptor(adapter_id="pdf.pdftotext", label="Actual installed Poppler", kind="external_executable", available=True, executable=executable, supports_execution=True), registry._execute_pdftotext)
    source = root / ("owned-雪🙂.pdf" if category == "unicode" else "owned.pdf")
    def document(word):
        stream = b"BT /F1 12 Tf 50 750 Td (" + word + b") Tj ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        raw = bytearray(b"%PDF-1.4\n"); offsets = [0]
        for index, value in enumerate(objects, 1): offsets.append(len(raw)); raw.extend(str(index).encode() + b" 0 obj\n" + value + b"\nendobj\n")
        xref = len(raw); raw.extend(b"xref\n0 6\n0000000000 65535 f \n")
        for offset in offsets[1:]: raw.extend(f"{offset:010} 00000 n \n".encode())
        raw.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()); return bytes(raw)
    source.write_bytes(document(b"Owned local PDF " + b"A" * (4096 if category == "huge" else 1)))
    arguments = {"path": str(source), "firstPage": 1, "lastPage": 1, "maxChars": 1000, "layout": False}
    action = lambda: registry.execute("pdf.pdftotext", arguments)
    result = action(); require(result["ok"] and result["result"]["engine"] == "poppler-pdftotext" and len(result["result"]["text"]) <= 1000, "Installed Poppler did not return genuine bounded text")
    if category == "permissions":
        with denied_file(source): require(not action()["ok"], "Denied PDF contents returned completed text")
    elif category == "stale":
        source.write_bytes(document(b"Fresh selected PDF")); require("Fresh selected PDF" in action()["result"]["text"], "Extraction reused stale PDF text")
    elif category == "empty": source.write_bytes(b""); require(not action()["ok"], "Empty invalid PDF returned completed text")
    elif category == "concurrency":
        with ThreadPoolExecutor(max_workers=4) as pool: require(all(pool.map(lambda _: action()["ok"], range(4))), "Concurrent Poppler outputs collided")
    elif category == "huge":
        require(not registry.execute("pdf.pdftotext", {**arguments, "maxChars": 5000001})["ok"], "Oversized extraction bound was admitted")
    return {"installedExecutable": executable, "inputSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "returnedChars": len(result["result"]["text"]), "rendered": False}


GROUPS = {
    "trial": ({"a.evolution-forge", "a.evolution-receipts", "a.evolution-sealed"}, _trial),
    "pure": (set(PURE_OWNERS) - {"a.evolution-forge", "a.evolution-receipts", "a.evolution-sealed", "sv.sdk.manifest", "a.permission-modes", "a.surface-manifest"}, _pure),
    "ui": ({"sv.ui.graph-state", "sv.ui.action-gates", "sv.ui.compact-result"}, _ui),
    "app-state": ({"a.app-state"}, _appstate),
    "adapters": ({"a.adapter-execution", "a.adapter-file-inspection", "a.tool-workspace", "a.android-approval", "a.adapter-session"}, _adapters),
    "surface": ({"a.surface-manifest", "a.surface-authority", "a.surface-receipt", "a.surface-lifecycle", "a.surface-log", "a.surface-plan"}, _surface),
    "signals": ({"sv.suggestions.signals"}, _signals),
    "sdk": ({"sv.sdk.manifest", "sv.sdk.bindings", "sv.sdk.plan-only", "sv.sdk.transport"}, _sdk),
    "support": ({"sv.support.bundle"}, _support),
    "artifacts": ({"a.artifact-durable", "a.artifact-relations", "a.artifact-lineage"}, _artifacts),
    "factory": ({"a.factory-draft", "a.factory-package", "a.factory-paths"}, _factory),
    "durable": ({"a.checkpoint-durable", "a.capability-preview"}, _durable),
    "capabilities": ({"a.capability-admission", "a.capability-benchmark", "a.capability-pack"}, _capabilities),
    "authored": ({"a.authored-tool", "a.authored-argv"}, _authored),
    "skills": ({"sv.skills.discovery", "sv.skills.feedback", "sv.skills.create"}, _skills),
    "treasury": ({"a.treasury-boundary"}, _treasury),
    "cloud": ({"a.app-cloud"}, _cloud),
    "apps": ({"a.app-observation", "a.app-storage"}, _apps),
    "evolution": ({"a.evolution-outcome", "a.evolution-friction", "a.evolution-inactive", "a.evolution-handoff", "a.evolution-lease", "a.factory-lineage"}, _evolution),
    "cu": ({"a.cu-replay", "a.cu-portable", "a.cu-verifier"}, _cu),
    "tools": ({"a.tool-readiness", "a.tool-reference", "a.tool-private", "a.tool-typed"}, _tools),
    "pdf": ({"a.pdf-bounded"}, _pdf),
}


def run(root, contracts, categories):
    root = Path(root).resolve()
    repo = Path(__file__).resolve().parents[2]
    require(any(root.is_relative_to(repo / name) for name in (".agent_control/proofs", ".agent_control/proofs-a")), "Owned generated proof root required")
    from .proof_ports import c7_port_block
    c7_port_block(int(os.environ.get("NEYVIA_C7_PORT", "0")))
    from .proof_credential_guard import install
    install(root)
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (identities, action) in GROUPS.items():
        for identity in sorted(identities & contracts.keys()):
            for category in categories:
                if blocker(contracts[identity], category):
                    continue
                # This completion family adds only missing categories for
                # resident UI helpers; earlier generated text cases remain.
                if name == "ui" and category != "concurrency":
                    continue
                if name == "durable" and category != ("permissions" if identity == "a.checkpoint-durable" else "interrupted"):
                    continue
                if name == "skills" and category not in ({"concurrency"} if identity == "sv.skills.discovery" else {"interrupted"} if identity == "sv.skills.feedback" else {"permissions", "interrupted"}):
                    continue
                path = root / identity / category; path.mkdir(parents=True, exist_ok=True)
                row = {"id": f"c7d-capability:{identity}:{category}", "contracts": [identity], "category": category,
                       "proofScope": "local_semantic", "rendered": False,
                       "boundary": "Exact production owner with generated arguments/local readback; no rendered/device/provider proof"}
                try:
                    row["detail"] = action(path, category) if name == "trial" else action(path, category, identity)
                    row["status"] = "passed"
                except Exception as error:
                    row.update(status="failed", detail=f"{type(error).__name__}: {error}")
                rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crash-app-state", type=Path)
    parser.add_argument("--families", nargs="*")
    parser.add_argument("--contracts", nargs="*")
    parser.add_argument("--categories", nargs="*", choices=CATEGORIES)
    parser.add_argument("--prepare-rendered", action="store_true")
    parser.add_argument("--crash-evolution", type=Path)
    args = parser.parse_args()
    from .proof_ports import C7_PORTS
    if args.port not in C7_PORTS:
        parser.error("Assigned C7 ports only")
    repo = Path(__file__).resolve().parents[2]
    if args.crash_app_state:
        root = args.crash_app_state.resolve(); root.relative_to(repo / ".agent_control/proofs")
        from .proof_credential_guard import install
        install(root)
        _crash_app_state(root)
        return
    if args.crash_evolution:
        root = args.crash_evolution.resolve(); root.relative_to(repo / ".agent_control/proofs")
        from .proof_credential_guard import install
        install(root)
        _crash_evolution(root); return
    if not args.output:
        parser.error("--output required")
    root = repo / ".agent_control/proofs/c7d-capability" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        path = root / "home" / key.lower(); path.mkdir(parents=True); os.environ[key] = str(path)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_C7_PORT=str(args.port))
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WEB_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(key, None)
    def network_guard(event, values):
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            address = values[1] if event != "socket.getaddrinfo" else (values[0], values[1])
            if tuple(address[:2]) != ("127.0.0.1", args.port):
                raise PermissionError("C7d capability proofs permit only the explicit owned loopback port")
    sys.addaudithook(network_guard)
    from .proof_credential_guard import install
    install(root)
    if args.prepare_rendered:
        from .app_factory import AppFactory
        from .proofs_a_capability_evolution import self_check
        (root / "notes").mkdir()
        notes = AppFactory(root / "notes").create(name="Owned Notes", brief="Keep local notes and export portable JSON records", target="neyvia", template="notes", theme="paper")
        self_check(root)
        details = {"notes": str(Path(notes["projectRoot"]) / "dist"), "guided": str(root / "evolution/apps/proof-renewed-workbench/dist"), "rendered": False}
        args.output.resolve().write_text(json.dumps(details, indent=2), encoding="utf-8")
        print(json.dumps(details)); return
    from .edge_contracts import inventory
    from .proof_contracts import source_digest
    _, contracts = inventory()
    if args.families:
        unknown = set(args.families) - GROUPS.keys()
        if unknown: parser.error("Unknown fixture family: " + str(unknown))
        for name in list(GROUPS):
            if name not in args.families: del GROUPS[name]
    selected = {identity: contracts[identity] for identity in set.union(*(value[0] for value in GROUPS.values()))}
    if args.contracts:
        if set(args.contracts) - selected.keys(): parser.error("Unknown selected contracts")
        selected = {identity: selected[identity] for identity in args.contracts}
    categories = args.categories or CATEGORIES
    import re
    module_names = {"edge_fixture_c7d_capability", "proofs_a_capabilities", "proofs_a_capability_tools", "proofs_a_capability_evolution", "proofs_a_app_standard", "durability", "edge_fixture_capabilities", "edge_fixture_preferences_skills", "edge_fixture_local", "harness_jobs", "capability_adapters", "capability_contracts", "capability_service", "tool_factory", "proof_credential_guard"}
    for contract in selected.values():
        module_names.update(re.findall(r"grant_agent\.([a-z_]+)\.", " ".join(contract.get("checkedAt", []))))
    source_paths = [repo / "src/grant_agent" / (name + ".py") for name in sorted(module_names)]
    bindings = {path.relative_to(repo).as_posix(): source_digest(path) for path in source_paths if path.is_file()}
    rows = run(root, selected, categories)
    audits = [{"contract": identity, "category": category, **reason} for identity, contract in selected.items() for category in categories if (reason := blocker(contract, category))]
    target = args.output.resolve(); target.relative_to(repo)
    stable = all(source_digest(repo / path) == digest for path, digest in bindings.items())
    target.write_text(json.dumps({"ok": stable and all(row["status"] == "passed" for row in rows), "explicitPort": args.port, "root": str(root), "rows": rows,
                                 "audits": audits, "sourceBindings": bindings, "sourceStableDuringRun": stable}, indent=2) + "\n", encoding="utf-8")
    from collections import Counter
    print(json.dumps({"rows": dict(Counter(row["status"] for row in rows)), "audits": len(audits), "root": str(root)}))


if __name__ == "__main__":
    main()
