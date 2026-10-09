"""Action contracts for capability planning and recoverable local workflows."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import hmac
import json
import tempfile
import time
from functools import wraps
from contextlib import nullcontext
from pathlib import Path


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def checked_action(observer):
    """Keep early return branches under the same observable postcondition."""
    def decorate(action):
        @wraps(action)
        def checked(*args, **kwargs):
            lock = getattr(args[0], "_lock", None) if args else None
            with lock if lock is not None else nullcontext():
                result = action(*args, **kwargs)
                observer(result, *args, **kwargs)
                return result
        return checked
    return decorate


def check_catalog(result, registry, *, include_capabilities=False):
    from .capability_contracts import CAPABILITY_CATALOG_SCHEMA
    require(result["schema"] == CAPABILITY_CATALOG_SCHEMA and result["summary"]["packs"] == len(registry.packs) and result["summary"]["capabilities"] == len(registry.capabilities), "a.catalog-observer", "catalog summary differs from loaded packs")
    require(result["summary"]["schemasDeferred"] == (not include_capabilities) and all(("capabilities" in row) == include_capabilities for row in result["packs"]), "a.catalog-observer", "catalog expanded schemas without request")


def check_search(result, registry, query, **kwargs):
    ids = [row["capabilityId"] for row in result["results"]]
    require(len(ids) == len(set(ids)) and set(ids) <= set(registry.capabilities) and result["summary"]["schemasDeferred"] and not any("inputSchema" in row for row in result["results"]), "a.catalog-routing", "search invented or expanded a capability")
    require(result["summary"]["returned"] == len(ids) and len(ids) <= max(1, min(int(kwargs.get("limit", 12)), 50)), "a.catalog-routing", "search exceeded its requested result bound")


def check_description(result, registry, capability_id):
    source = registry.capabilities[str(capability_id).strip().lower()]
    require(result["capabilityId"] == source.capability_id and result["adapter"] == source.adapter and result["available"] == result["adapterDescriptor"]["available"], "a.catalog-adapter", "described capability does not bind its real adapter availability")


def check_graph_registration(result, graph, **kwargs):
    stored = json.loads(graph.state_path.read_text(encoding="utf-8"))["artifacts"]
    require(stored[result["artifactId"]] == result, "a.artifact-durable", "returned artifact differs from durable graph")
    if kwargs.get("path") and result["exists"]:
        path = Path(result["path"])
        require(hashlib.sha256(path.read_bytes()).hexdigest() == result["sha256"] and path.stat().st_size == result["sizeBytes"], "a.artifact-durable", "artifact identity differs from actual file bytes")


def check_graph_relation(result, graph, parent_artifact_id, child_artifact_id, relation, **kwargs):
    payload = json.loads(graph.state_path.read_text(encoding="utf-8"))
    require(result in payload["relations"] and result["parentArtifactId"] == parent_artifact_id and result["childArtifactId"] == child_artifact_id and parent_artifact_id != child_artifact_id and {parent_artifact_id, child_artifact_id} <= set(payload["artifacts"]), "a.artifact-relations", "relation is not durable or references unknown/self artifact")


def check_graph_lineage(result, graph, artifact_id, **kwargs):
    ids = {row["artifactId"] for row in result["artifacts"]}
    require(artifact_id in ids and result["summary"] == {"artifactCount": len(ids), "relationCount": len(result["relations"])} and all({row["parentArtifactId"], row["childArtifactId"]} <= ids for row in result["relations"]), "a.artifact-lineage", "lineage counts or relation endpoints are inconsistent")


def check_treasury(result, treasury, **kwargs):
    from .legacy_asset_treasury import SECRET_NAME_PATTERN
    policy = result["scanPolicy"]
    require(policy["contentStored"] is False and policy["transcriptsIncluded"] is False and policy["secretNamedFilesExcluded"] is True, "a.treasury-boundary", "treasury must retain typed facts only")
    for item in [result, *result["recoveries"]]:
        require(item["humanApprovalRequired"] is True and item["trustRaised"] is False and item["candidateActivated"] is False and item["published"] is False, "a.treasury-boundary", "recovery raised trust, activation or publication")
    require(all(item["state"] == "review_required" for item in result["recoveries"]), "a.treasury-boundary", "recovery bypassed human review")
    allowed = {"assetId", "kind", "label", "path", "digest", "digestAlgorithm", "fileCount", "sizeBytes", "updatedAt", "verificationState", "topicTokens", "details", "contentStored", "transcriptsIncluded", "trustRaised", "activated"}
    details = {"plan": {"openChecklistCount", "completedChecklistCount", "checklistCountsAreSignalsOnly"}, "proof_bundle": {"schemaCount", "schemas", "explicitPassingReceiptCount", "statuses"}, "local_app": {"appFactoryBound", "jobId", "appId", "packageSha256", "verificationReceiptPath"}, "app_factory_package": {"jobId", "appId", "template", "receiptPath"}, "skill_package": {"revisionBackupCount", "metadataPresent", "backupsIndexed"}, "receipt_ledger": {"receiptBodiesStored"}, "artifact_lineage": {"source", "artifactCount", "verifiedArtifactCount", "relationCount"}}
    for item in result["assets"]:
        require(set(item) == allowed and set(item["details"]) <= details.get(item["kind"], set()), "a.treasury-boundary", "asset includes undeclared narrative fields")
        require(not SECRET_NAME_PATTERN.search(Path(item["path"]).name) and all(item[key] is False for key in ["contentStored", "transcriptsIncluded", "trustRaised", "activated"]), "a.treasury-boundary", "asset retained secret path, content or promoted trust")
        for field, identity in [("schemas", "schema"), ("statuses", "status")]:
            for row in item["details"].get(field, []):
                require(set(row) == {identity, "count"} and isinstance(row[identity], str) and type(row["count"]) is int, "a.treasury-boundary", "proof metadata includes raw receipt fields")


def check_factory_job(result, factory, *args, **kwargs):
    if result.get("status") != "ready":
        return
    from .app_factory import APP_FACTORY_JOB_SCHEMA, APP_FACTORY_REGISTRY_SCHEMA
    project = Path(result["projectRoot"]).resolve()
    require(project.is_relative_to(factory.root) and result["schema"] == APP_FACTORY_JOB_SCHEMA and result["currentStage"] == "ready" and len(result["stages"]) == 5 and all(row["state"] == "completed" for row in result["stages"]), "a.factory-draft", "ready factory job is incomplete or outside its workspace")
    require(result["verification"]["state"] == "passed" and result["registration"]["state"] == "draft-ready" and result["marketplace"]["state"] == "draft" and "operator-activation" in result["marketplace"]["blockedBy"], "a.factory-draft", "draft readiness changed activation/publication authority")
    package = Path(result["package"]["path"])
    require(package.is_file() and hashlib.sha256(package.read_bytes()).hexdigest() == result["package"]["sha256"], "a.factory-package", "generated package hash no longer binds its bytes")
    application = json.loads((project / "neyvia.application.json").read_text(encoding="utf-8"))
    from .harness_jobs import _exclusive_job_lock
    with _exclusive_job_lock(factory.registry_path, timeout_seconds=10):
        registry = json.loads(factory.registry_path.read_text(encoding="utf-8"))
    require(application["valid"] and application["applicationId"] == result["spec"]["appId"] and registry["schema"] == APP_FACTORY_REGISTRY_SCHEMA and any(row["applicationId"] == application["applicationId"] and row["state"] == "draft-ready" for row in registry["applications"]), "a.factory-draft", "ready draft lacks its validated registered application")
    if result["spec"]["target"] == "desktop":
        config = json.loads((project / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        require((project / "src-tauri/Cargo.toml").is_file() and (project / "src-tauri/src/main.rs").is_file() and (project / "src-tauri/icons/icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and (project / "src-tauri/icons/icon.ico").read_bytes().startswith(b"\0\0\x01\0") and config["build"]["frontendDist"] == "../dist" and config["bundle"]["active"] is False, "a.factory-package", "desktop scaffold or inactive bundle boundary was lost")


def check_factory_lineage(result, factory, *args, **kwargs):
    check_factory_job(result, factory)
    if result.get("status") != "ready":
        return
    handoff = result["capabilityHandoff"]
    project = Path(result["projectRoot"])
    application = json.loads((project / "neyvia.application.json").read_text())
    lineage = json.loads((project / "neyvia.capability-lineage.json").read_text())
    source = project / "source/skill"
    receipt = json.loads(Path(handoff["sourcePackage"]["receiptPath"]).read_text())
    require(lineage["handoffDigest"] == handoff["handoffDigest"] and lineage["appBindingDigest"] == handoff["appBindingDigest"] and len(handoff["appBindingDigest"]) == 64 and application["permissions"] == [] and hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest() == handoff["skillSha256"] and hashlib.sha256((source / "agents/openai.yaml").read_bytes()).hexdigest() == handoff["metadataSha256"] and receipt["state"] == "draft_ready" and receipt["jobId"] == result["jobId"] and receipt["candidateActivated"] is False and not handoff["candidateActivated"] and not handoff["appActivated"], "a.factory-lineage", "guided app lost copied skill, reviewed lineage, inactive boundary or draft receipt")


def check_preview_asset(result, factory, job_id, requested_path):
    path, media = result
    project = Path(factory.get_job(job_id)["projectRoot"]).resolve()
    require(path.resolve().is_relative_to(project / "dist") and path.is_file() and not path.name.startswith("."), "a.factory-paths", "preview escaped the generated public assets")


def check_surface_validation(result, payload):
    from .application_surface import _surface_block, MOBILE_PLATFORMS
    surface = _surface_block(payload)
    if surface is None:
        declared_invalid = isinstance(payload, dict) and "application_surface" in payload
        require(result["valid"] == (not declared_invalid) and not result["declared"], "a.surface-manifest", "optional undeclared surface was invented")
    elif result["valid"]:
        require(all(row.get("platform") not in MOBILE_PLATFORMS or row.get("build", {}).get("status") == "unavailable" for row in surface.get("targets", [])), "a.surface-manifest", "mobile build readiness was invented")


def check_surface_target(result, service, surface, target, **kwargs):
    ready = result["status"] == "ready"
    require(result["available"] == ready, "a.surface-authority", "target readiness differs from availability")
    if ready:
        require(service.receipt_authority is not None, "a.surface-authority", "workspace facts alone raised surface readiness")
        proof = result["readinessEvidence"] if result["kind"] == "web" else result["artifact"]
        require(proof.get("verified") is True and not proof.get("errors"), "a.surface-authority", "ready target lacks verified external evidence")
        if result["kind"] == "desktop":
            require(proof.get("signatureVerified") is True, "a.surface-authority", "ready desktop lacks actual platform signature")


def check_launch_plan(result, service, payload, **kwargs):
    require(not any(result["executionPolicy"][key] for key in ["executes", "builds", "installs", "publishes"]), "a.surface-plan", "surface planner crossed execution boundary")
    if result["status"] == "ready":
        require(result["target"]["available"] and result["approval"].get("valid") and result["approval"].get("singleUse") and result["approval"].get("consumptionRequired") and not result["permissionBinding"]["denied"], "a.surface-plan", "ready launch plan lacks bound single-use approval")


def check_authority_receipt(result, authority, path, **kwargs):
    if not result.get("verified"):
        return
    envelope = json.loads(path.read_text(encoding="utf-8"))
    expected = hmac.new(authority.verification_key, authority._signature_material(envelope), hashlib.sha256).hexdigest()
    require(hmac.compare_digest(expected, str(envelope.get("signature", ""))) and envelope["kind"] == kwargs["expected_kind"] and envelope["receiptId"] == path.stem and result["receiptHash"] == hashlib.sha256(path.read_bytes()).hexdigest(), "a.surface-receipt", "verified receipt lacks signature, kind, identity or byte binding")


def check_lifecycle_stream(result, authority, stream_id):
    if not result.get("verified"):
        return
    rows = []
    for path in (authority.ledger_root / "lifecycle" / stream_id).glob("*.json"):
        content = path.read_bytes()
        envelope = json.loads(content)
        rows.append((envelope["payload"], hashlib.sha256(content).hexdigest()))
    require(all(type(payload["sequence"]) is int for payload, _ in rows), "a.surface-lifecycle", "lifecycle sequence is not integer")
    rows.sort(key=lambda row: row[0]["sequence"])
    previous = ""
    for sequence, (payload, digest) in enumerate(rows, 1):
        require(payload["sequence"] == sequence and payload["previousReceiptHash"] == previous, "a.surface-lifecycle", "lifecycle receipt chain is not monotonic and hash-linked")
        previous = digest
    require(result["chainLength"] == len(rows), "a.surface-lifecycle", "lifecycle chain length differs from signed stream")


def check_log_observer(result, service, *args, **kwargs):
    lines = result.get("lines", [])
    require(all(service._redact_log_text(line)[0] == line for line in lines), "a.surface-log", "log observer returned unredacted secrets")
    require(result.get("status") not in {"missing", "blocked"} or not lines, "a.surface-log", "blocked or missing hooks emitted file contents")


def check_capability_plan(result, planner, goal, **kwargs):
    from .capability_contracts import CAPABILITY_PLAN_SCHEMA, canonical_hash
    require(result["schema"] == CAPABILITY_PLAN_SCHEMA and result["planHash"] == canonical_hash({key: value for key, value in result.items() if key not in {"planId", "planHash"}}), "a.capability-plan", "plan hash does not bind its compiled stages")
    require(result["capabilityIds"] == [row["capabilityId"] for row in result["capabilities"]] and result["stages"][-1]["steps"][0]["kind"] == "verification" and result["estimated"]["modelSchemasLoaded"] == 0, "a.capability-plan", "plan lost selected capabilities, final proof gate or deferred model schemas")
    permissions = result["permissionSummary"]
    missing = [row["capabilityId"] for row in result["capabilities"] if not row["available"]]
    expected = "blocked" if permissions["denied"] else "adapter_required" if missing else "approval_required" if permissions["approvalRequired"] else "ready"
    require(result["readiness"]["status"] == expected and result["readiness"]["unavailableCapabilities"] == missing, "a.capability-plan", "plan readiness ignored missing adapters or approval")


def check_run_record(result, store, *args, **kwargs):
    require(json.loads(store._path(result["runId"]).read_text(encoding="utf-8")) == result and result["previewEvents"][0]["phase"] == "plan", "a.capability-preview", "run receipt differs from durable ordered preview")
    if result["status"] in store.TERMINAL_STATUSES:
        require(result["previewEvents"][-1]["phase"] == "result" and result["completedAt"], "a.capability-preview", "terminal run lacks completed result event")


def check_pack_save(result, service, payload):
    if not payload.get("approved"):
        require(result.get("status") == "approval_required", "a.capability-pack", "custom pack changed configuration without approval")
    if result.get("status") == "saved":
        path = Path(result["path"])
        require(path.resolve().is_relative_to(service.root / ".agent_control/capability_packs") and result["packId"] in service.registry.packs and json.loads(path.read_text(encoding="utf-8"))["packId"] == result["packId"], "a.capability-pack", "saved pack did not reload its durable scoped definition")


def check_capability_execution(result, service, payload):
    capability = service.registry.capabilities[str(payload.get("capabilityId") or payload.get("capability_id")).strip().lower()]
    if result.get("status") == "delegation_required":
        require(result["handoff"]["runtime"] == "neyvia.stage_scheduler" and not result.get("ok"), "a.capability-admission", "agent work was reported executed without delegated runtime")
    if result.get("status") == "approval_required":
        require(bool(result["permissionSummary"]["approvalRequired"]) and not result.get("ok"), "a.capability-admission", "approval gate lacks modeled requested authority")


def check_ui_contract(result, service):
    names = {item["name"] for item in result["commands"]}
    require(result["schema"] == "neyvia.capability_ui_contract.v1" and result["ownerBoundary"]["visualImplementation"] == "Cursor" and "running" in result["lifecycle"]["runStatuses"] and {"search_capabilities_command", "record_capability_preview_command"} <= names, "a.capability-ui-schema", "capability UI behavior contract lost ownership, lifecycle or commands")


def _capability_workflow_self_check(scratch):
    from .capability_service import CapabilityService, register_with_progressive_surface
    from .capability_adapters import CapabilityAdapterRegistry
    from .progressive_tools import ProgressiveToolSurface
    from .neyvia_mcp import NeyviaMCPServer
    from .web_backend import FluxioWebBackend
    root = scratch / "capability-workflows"
    root.mkdir()
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    service = CapabilityService(_fixture_root(root))
    plan = service.plan({"goal": "OCR these PDFs and create a cited literature review", "artifacts": [{"path": "paper.pdf", "mediaType": "application/pdf", "name": "paper.pdf"}], "experience": "guided", "permissionMode": "workspace_safe"})
    require(plan["experience"] == "guided" and plan["stages"][0]["label"] == "Inspect selected artifacts" and {"document.fast-ocr", "research.literature-review"} <= set(plan["capabilityIds"]) and service.get_plan(plan["planId"])["planHash"] == plan["planHash"], "a.capability-plan", "OCR/literature plan lost guided stages, routing or persistence")
    run_plan = service.plan({"goal": "create a cited literature review"})
    created = service.create_run({"planId": run_plan["planId"]})
    live = service.record_preview({"runId": created["runId"], "phase": "live", "kind": "source_matrix", "summary": "Compared sources", "payload": {"sources": 4}})
    finished = service.finish_run({"runId": created["runId"], "status": "completed", "summary": "Review complete"})
    restarted = CapabilityService(_fixture_root(root))
    persisted = restarted.get_run(created["runId"])
    require(created["schema"] == "neyvia.capability_run.v1" and live["status"] == "running" and finished["status"] == "completed" and len(persisted["previewEvents"]) == 3, "a.capability-preview", "preview phases or restart persistence failed")
    try:
        restarted.record_preview({"runId": created["runId"], "phase": "live", "kind": "late"})
    except RuntimeError:
        pass
    else:
        raise ValueError("Terminal capability run accepted late preview")
    delegated = service.execute_capability({"capabilityId": "research.literature-review"})
    approved = service.execute_capability({"capabilityId": "ai.model-training"})
    require(delegated["status"] == "delegation_required" and delegated["handoff"]["runtime"] == "neyvia.stage_scheduler" and approved["status"] == "approval_required" and "compute.spend" in approved["permissionSummary"]["approvalRequired"], "a.capability-admission", "capability synthesized execution or skipped compute approval")
    adapters = CapabilityAdapterRegistry(root)
    python, builtin = adapters.descriptor("runtime.python"), adapters.descriptor("builtin.artifact.inspect")
    require(python.available and not python.supports_execution and builtin.available and builtin.supports_execution, "a.adapter-execution", "discovery was equated with execution")
    source = root / "inspection.txt"
    source.write_text("Capability action receipt")
    inspected = adapters.execute("builtin.artifact.inspect", {"path": str(source)})
    require(inspected["ok"] and inspected["status"] == "completed" and inspected["result"]["sizeBytes"] > 0 and len(inspected["result"]["sha256"]) == 64, "a.adapter-file-inspection", "built-in handler failed actual file inspection")
    pack = {"packId": "custom.archaeology", "name": "Archaeology", "description": "Evidence-led archaeology workflows", "domains": ["archaeology"], "roles": ["archaeologist"], "capabilities": [{"capabilityId": "archaeology.site-analysis", "name": "Site analysis", "description": "Organize layers, finds and competing interpretations", "verbs": ["analyze", "excavate", "date"], "roles": ["archaeologist"], "inputTypes": ["map", "image", "record"], "outputTypes": ["site-report"], "adapter": "neyvia.agent", "requiredPermissions": ["artifact.read", "artifact.write"]}]}
    require(service.validate_pack({"pack": pack})["valid"] and service.save_pack({"pack": pack})["status"] == "approval_required", "a.capability-pack", "pack validation or approval boundary failed")
    saved = service.save_pack({"pack": pack, "approved": True})
    require(saved["status"] == "saved" and service.search({"query": "archaeology excavation site"})["results"][0]["capabilityId"] == "archaeology.site-analysis" and "custom.archaeology" in CapabilityService(_fixture_root(root)).registry.packs, "a.capability-pack", "pack persistence or discovery reload failed")
    broken = root / ".agent_control/capability_packs/broken.json"
    broken.write_text("{not json")
    snapshot = CapabilityService(_fixture_root(root)).snapshot()
    require(snapshot["summary"]["packs"] >= 15 and snapshot["catalog"]["summary"]["loadErrors"] == 1 and "broken.json" in snapshot["catalog"]["loadErrors"][0]["path"], "a.catalog-observer", "invalid extension broke builtin catalog")
    service.ui_contract()
    surface = ProgressiveToolSurface()
    register_with_progressive_surface(surface, service)
    names = {row["name"] for row in surface.list_tools()}
    expected = {"capability.search", "capability.describe", "capability.plan", "capability.execute", "tool.suite.search", "tool.suite.describe", "tool.suite.execute", "artifact.register", "artifact.lineage", "tool.author.adapt", "tool.author.execute", "computer_use.verify", "computer_use.dispatch_verification"}
    require(expected <= names and not any("inputSchema" in row for row in surface.list_tools()) and surface.call("capability.search", {"query": "PowerPoint presentation", "limit": 5})["results"][0]["capabilityId"] == "office.presentation-authoring", "a.catalog-routing", "progressive capability wiring lost tool names, deferred schemas or live calls")
    server = NeyviaMCPServer(_fixture_root(root))
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"includeSchemas": False}})
    called = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "capability.search", "arguments": {"query": "literature review", "limit": 4}}})
    require("capability.search" in {row["name"] for row in listed["result"]["tools"]} and called["result"]["structuredContent"]["results"][0]["capabilityId"] == "research.literature-review", "a.catalog-routing", "MCP search discovery/call failed")
    backend = FluxioWebBackend(root, root)
    snapshot = backend.dispatch("get_capability_os_snapshot_command", {})
    contract = backend.dispatch("get_capability_ui_contract_command", {})
    search = backend.dispatch("search_capabilities_command", {"query": "network architecture", "limit": 5})
    plan = backend.dispatch("plan_capability_run_command", {"goal": "design a network architecture", "permissionMode": "review_only"})
    created = backend.dispatch("create_capability_run_command", {"planId": plan["planId"]})
    loaded = backend.dispatch("get_capability_run_command", {"runId": created["runId"]})
    require(snapshot["schema"] == "neyvia.capability_os_snapshot.v1" and contract["schema"] == "neyvia.capability_ui_contract.v1" and search["results"][0]["capabilityId"] == "software.network-architecture" and loaded["runId"] == created["runId"], "a.catalog-routing", "backend capability command wiring failed")
    for _ in range(5):
        service.registry.search("OCR scanned PDF and citations")
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        service.registry.search("Unity game mod playtest and Android export")
        samples.append((time.perf_counter() - started) * 1000)
    require(sorted(samples)[27] < 50, "a.catalog-routing", "warm catalog search exceeded50ms p95")


def check_adapter_descriptor(result, registry, adapter_id):
    if result.supports_execution:
        require(result.adapter_id in registry._handlers, "a.adapter-execution", "adapter execution advertised without a real approved handler")


def check_adapter_execution(result, registry, adapter_id, arguments=None):
    descriptor = registry.descriptor(adapter_id)
    if result["ok"]:
        require(descriptor.available and descriptor.supports_execution and descriptor.adapter_id in registry._handlers, "a.adapter-execution", "adapter synthesized successful execution from mere discovery")
    if str(adapter_id).strip().lower() == "builtin.artifact.inspect" and result["ok"]:
        source = Path(result["result"]["path"])
        require(result["result"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest() and result["result"]["sizeBytes"] == source.stat().st_size, "a.adapter-file-inspection", "inspection does not bind actual file bytes")


def check_lifecycle_status(result, service, *args, **kwargs):
    require(result["workspaceReportTrusted"] is False, "a.surface-lifecycle", "editable lifecycle report was trusted")
    if result["verified"]:
        require(service.receipt_authority is not None and not result["verificationErrors"] and result.get("chainLength", 0) >= 1, "a.surface-lifecycle", "verified lifecycle lacks trusted bound chain")


def _surface_self_check(scratch):
    """Mint lab-only authority documents, then run the real read-only verifier."""
    import os
    from datetime import datetime, timedelta, timezone
    from . import application_surface as module
    from .capability_service import CapabilityService
    from .sdk import build_application_surface
    from jsonschema import Draft202012Validator
    root = scratch / "surface-workspace"
    root.mkdir()
    from .proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    ledger = scratch / "surface-authority"
    ledger.mkdir()
    key = os.urandom(32)
    service = module.ApplicationSurfaceService(root, receipt_authority=module.ExternalReceiptAuthority(ledger, key))
    now = datetime.now(timezone.utc)
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    surface = build_application_surface(surface_id="scratch.preview", title="Scratch Preview", description="Isolated lab authority contract", permissions={"inspect": ["workspace.read"], "launch": [], "control": []}, targets=[{"target_id": "web.local", "kind": "web", "platform": "web", "build": {"status": "not_required"}, "launch": {"kind": "url", "url": proof_text("http://127.0.0.1:48461")}, "required_permissions": [], "readiness": {"receipt_id": "web-ready", "max_age_seconds": 300}}], lifecycle={"status_file": ".agent_control/app-surface/status.json", "stream_id": "web-run"}, observability={"log_paths": [".agent_control/app-surface/runtime.log"], "proof_paths": []})
    manifest = {"app_id": "scratch-preview", "name": "Scratch Preview", "application_surface": surface}

    def write(identity, kind, payload, nonce="scratch", stream=""):
        envelope = {"schema": module.EXTERNAL_RECEIPT_ENVELOPE_SCHEMA, "receiptId": identity, "kind": kind, "singleUse": True, "issuedAt": iso(now), "expiresAt": iso(now + timedelta(minutes=10)), "nonce": nonce, "payload": payload}
        content = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        envelope["signature"] = hmac.new(key, content, hashlib.sha256).hexdigest()
        content = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        path = ledger / "lifecycle" / stream / (identity + ".json") if stream else ledger / "receipts" / (identity + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    def web(kind="browser", nonce="scratch"):
        return write("web-ready", "web_readiness", {"schema": module.APPLICATION_SURFACE_WEB_PROOF_SCHEMA, "targetId": "web.local", "url": proof_text("http://127.0.0.1:48461"), "status": "verified", "verifiedAt": iso(now), "httpStatus": 200, "verifier": {"kind": kind, "id": "lab-only-fixture"}}, nonce=nonce)

    absent = module.validate_application_surface_manifest({"app_id": "headless"})
    require(absent["valid"] and not absent["declared"] and not absent["errors"] and not absent["warnings"], "a.surface-manifest", "undeclared optional surface failed")
    persisted = json.loads((Path(__file__).resolve().parents[2] / "config/neyvia_application_surface_schema.json").read_text())
    Draft202012Validator.check_schema(persisted)
    Draft202012Validator(persisted).validate(surface)
    Draft202012Validator(module.application_surface_schema()).validate(surface)
    mobile = json.loads(json.dumps(surface))
    mobile["targets"][0].update(target_id="mobile.ios", kind="desktop", platform="ios", build={"status": "available"}, launch={"kind": "artifact", "artifact": "dist/mobile"})
    invalid = module.validate_application_surface_manifest(mobile)
    require(not invalid["valid"] and any("must remain unavailable" in item for item in invalid["errors"]), "a.surface-manifest", "unproven mobile build was accepted")
    try:
        module.ApplicationSurfaceService(root, receipt_authority=module.ExternalReceiptAuthority(root / "authority", key))
    except ValueError as error:
        require("outside the editable workspace" in str(error), "a.surface-authority", "wrong ledger boundary rejection")
    else:
        raise ValueError("Editable workspace authority was accepted")
    forged = root / ".agent_control/app-surface/web-proof.json"
    forged.parent.mkdir(parents=True)
    forged.write_text(json.dumps({"schema": module.APPLICATION_SURFACE_WEB_PROOF_SCHEMA, "targetId": "web.local", "url": proof_text("http://127.0.0.1:48461"), "status": "verified", "verifiedAt": iso(now), "httpStatus": 200}))
    default = module.ApplicationSurfaceService(root).status(manifest)
    require(default["status"] == "declared" and not default["targets"][0]["available"] and "external receipt authority is unavailable" in default["targets"][0]["blockers"], "a.surface-authority", "editable forged proof became trusted")
    web("workspace_script")
    untrusted = service.status(manifest)["targets"][0]
    require(not untrusted["available"] and any("trusted verifier" in item for item in untrusted["blockers"]), "a.surface-authority", "workspace verifier became trusted")
    web()
    first = service.status(manifest)["targets"][0]
    web(nonce="new-source-identity")
    second = service.status(manifest)["targets"][0]
    require(first["readinessEvidence"]["receiptHash"] != second["readinessEvidence"]["receiptHash"] and first["planHash"] != second["planHash"], "a.surface-receipt", "launch hash does not bind receipt bytes")
    pending = service.plan_launch(manifest, target_id="web.local")
    require(pending["status"] == "approval_required" and pending["target"]["available"], "a.surface-plan", "launch started without approval")
    write("approval-web", "approval", {"schema": module.APPLICATION_SURFACE_APPROVAL_SCHEMA, "approvalId": "approval-web", "status": "approved", "planHash": pending["planHash"], "manifestHash": pending["manifestHash"], "targetId": "web.local", "approvedPermissions": pending["target"]["effectivePermissions"], "approvedBy": "operator:scratch", "approvedAt": iso(now), "expiresAt": iso(now + timedelta(minutes=5))})
    ready = service.plan_launch(manifest, target_id="web.local", approval_id="approval-web")
    require(ready["status"] == "ready" and ready["approval"]["valid"] and ready["approval"]["singleUse"] and ready["approval"]["consumptionRequired"] and not ready["executionPolicy"]["executes"], "a.surface-plan", "bound lab approval did not make a non-executing plan ready")
    consumed = ledger / "consumed/approval-web.json"
    consumed.parent.mkdir()
    consumed.write_text("{}")
    rejected = service.plan_launch(manifest, target_id="web.local", approval_id="approval-web")
    require(rejected["status"] == "approval_required" and "consumed" in rejected["approval"]["reason"], "a.surface-receipt", "consumed approval was reused")
    consumed.unlink()
    approval_path = ledger / "receipts/approval-web.json"
    approval_path.write_text(approval_path.read_text().replace("operator:scratch", "operator:forged"))
    rejected = service.plan_launch(manifest, target_id="web.local", approval_id="approval-web")
    require(rejected["status"] == "approval_required" and "signature" in rejected["approval"]["reason"], "a.surface-receipt", "tampered approval was accepted")
    config = root / "config/connected_apps.json"
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps([{"app_id": "headless"}]))
    empty = service.catalog()
    require(empty["summary"]["declared"] == 0 and not empty["surfaces"], "a.surface-manifest", "catalog invented undeclared surfaces")
    config.write_text(json.dumps([manifest]))
    default_catalog = CapabilityService(_fixture_root(root)).application_surface_catalog()
    trusted_catalog = CapabilityService(_fixture_root(root), application_surface_receipt_authority=module.ExternalReceiptAuthority(ledger, key)).application_surface_catalog()
    require(default_catalog["summary"]["launchReadyTargets"] == 0 and trusted_catalog["summary"]["launchReadyTargets"] == 1, "a.surface-authority", "host-injected authority boundary was lost")
    report_path = root / ".agent_control/app-surface/status.json"
    report_path.write_text(json.dumps({"schema": module.APPLICATION_SURFACE_LIFECYCLE_SCHEMA, "state": "running", "previousState": "launching", "updatedAt": iso(now), "pid": os.getpid(), "detail": "workspace reports running"}))
    untrusted = module.ApplicationSurfaceService(root).status(manifest)["lifecycle"]
    require(untrusted["state"] == "declared" and untrusted["reportedState"] == "running" and not untrusted["verified"] and not untrusted["workspaceReportTrusted"], "a.surface-lifecycle", "live PID and workspace report became trusted lifecycle")
    initial = service.status(manifest)
    target = initial["targets"][0]
    process = service._process_identity(os.getpid())
    require(process["verified"], "a.surface-lifecycle", "host process identity API unavailable")

    def chain(break_hash=False, malformed=False):
        previous_hash = ""
        for sequence, (previous_state, state) in enumerate([("declared", "ready"), ("ready", "launching"), ("launching", "running")], 1):
            payload = {"schema": module.APPLICATION_SURFACE_LIFECYCLE_SCHEMA, "streamId": "web-run", "sequence": "1" if malformed and sequence == 1 else sequence, "previousReceiptHash": "0" * 64 if break_hash and sequence == 2 else previous_hash, "previousState": previous_state, "state": state, "updatedAt": iso(now), "targetId": target["targetId"], "manifestHash": initial["manifestHash"], "planHash": target["planHash"], "artifactSha256": "", "runId": "scratch-run", "process": process, "listener": {"url": target["readinessEvidence"]["url"], "readinessReceiptId": target["readinessEvidence"]["receiptId"], "readinessReceiptHash": target["readinessEvidence"]["receiptHash"], "pid": process["pid"], "protocol": "tcp", "host": "127.0.0.1", "port": proof_port(48461), "observedAt": iso(now)}}
            previous_hash = write(str(sequence), "lifecycle", payload, stream="web-run")
    chain()
    running = service.status(manifest)
    require(running["status"] == "running" and running["lifecycle"]["verified"] and running["lifecycle"]["chainLength"] == 3, "a.surface-lifecycle", "trusted lab lifecycle chain failed its process/listener binding")
    chain(break_hash=True)
    rejected = service.status(manifest)["lifecycle"]
    require(not rejected["verified"] and any("previous-receipt" in item for item in rejected["verificationErrors"]), "a.surface-lifecycle", "broken receipt hash chain became trusted")
    chain(malformed=True)
    rejected = service.status(manifest)["lifecycle"]
    require(not rejected["verified"] and any("sequence must be an integer" in item for item in rejected["verificationErrors"]), "a.surface-lifecycle", "signed noninteger sequence became trusted")
    log = root / ".agent_control/app-surface/runtime.log"
    content = bytearray(b"B" * 80000)
    secret = b"token=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    start = len(content) - 65536 - 10
    content[11000] = 10
    content[start - 1] = 10
    content[start:start + len(secret)] = secret
    content[start + len(secret)] = 10
    content[-15:] = b"visible-after\n\n"
    log.write_bytes(content)
    observed = service.observe(manifest)["logs"][0]
    rendered = "\n".join(observed["lines"])
    require(observed["partialLineDropped"] and "[REDACTED]" in rendered and "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in rendered and not rendered.startswith("B"), "a.surface-log", "boundary secret escaped tail redaction")
    log.write_bytes(b"token=" + b"S" * 70000 + b"\nvisible-after\n")
    observed = service.observe(manifest)["logs"][0]
    require(observed["partialLineDropped"] and observed["lines"] == ["visible-after"], "a.surface-log", "cut secret line escaped bounded log observer")
    # A signed statement cannot replace actual native platform signature proof.
    content = bytearray(512)
    content[:2] = b"MZ"
    content[0x3C:0x40] = (128).to_bytes(4, "little")
    content[128:132] = b"PE\0\0"
    content[132:134] = (0x8664).to_bytes(2, "little")
    binary = root / "dist/app.exe"
    binary.parent.mkdir()
    binary.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    write("desktop-build", "desktop_build", {"schema": module.APPLICATION_SURFACE_DESKTOP_PROOF_SCHEMA, "targetId": "desktop.windows", "artifactSha256": digest, "sizeBytes": len(content), "mediaType": "application/vnd.microsoft.portable-executable", "architecture": "x86_64", "verifiedAt": iso(now), "signature": {"status": "verified", "artifactSha256": digest, "verifiedAt": iso(now), "verifier": {"kind": "authenticode", "id": "claimed-only"}}})
    desktop = build_application_surface(surface_id="scratch.desktop", title="Desktop projection", description="Unsigned local artifact boundary", permissions={"inspect": [], "launch": [], "control": []}, targets=[{"target_id": "desktop.windows", "kind": "desktop", "platform": "windows", "build": {"status": "available", "artifact": "dist/app.exe", "sha256": digest, "size_bytes": len(content), "media_type": "application/vnd.microsoft.portable-executable", "architecture": "x86_64", "evidence": {"receipt_id": "desktop-build"}}, "launch": {"kind": "artifact", "artifact": "dist/app.exe"}, "required_permissions": []}])
    desktop_service = module.ApplicationSurfaceService(root, receipt_authority=service.receipt_authority)
    desktop_service.host_platform = "windows"
    desktop_service.host_architecture = "x86_64"
    projected = desktop_service.status({"app_id": "scratch-desktop", "application_surface": desktop})["targets"][0]
    require(projected["status"] == "present" and not projected["artifact"]["signatureVerified"] and any("actual trusted platform" in item for item in projected["artifact"]["errors"]), "a.surface-authority", "claimed Authenticode signature raised desktop readiness")


def _factory_self_check(scratch):
    from .app_factory import AppFactory
    root = scratch / "factory"
    root.mkdir()
    factory = AppFactory(root)
    job = factory.create(name="Proof Notes", brief="Keep local notes and export portable JSON records", target="neyvia", template="notes", theme="paper")
    require("Planner:" in job["agentHandoff"]["prompt"] and job["projectRoot"] in job["agentHandoff"]["prompt"], "a.factory-draft", "agent handoff lost role or project binding")
    desktop = factory.create(name="Proof Queue", brief="Keep a durable checklist and export the completed queue", target="desktop", template="checklist")
    resumed = factory.resume(desktop["jobId"])
    require(resumed["package"]["sha256"] == desktop["package"]["sha256"] and resumed["nativeBuild"]["state"] == "not_started", "a.factory-package", "resume changed package or started a native build")
    for directory in ["../escape", "apps/occupied"]:
        if "occupied" in directory:
            (root / directory).mkdir()
            (root / directory / "keeper.txt").write_text("preserved user data")
        try:
            factory.create(name="Forbidden Draft", brief="Attempt bounded creation with a protected destination", directory=directory)
        except RuntimeError as error:
            require("inside the selected workspace" in str(error) or "not empty" in str(error), "a.factory-paths", "wrong rejection for protected destination")
        else:
            raise ValueError("Unsafe factory destination accepted")
    require((root / "apps/occupied/keeper.txt").read_text() == "preserved user data", "a.factory-paths", "draft overwrote a nonempty folder")
    preview, media = factory.resolve_preview_asset(job["jobId"], "")
    require(preview.name == "index.html" and media.startswith("text/html"), "a.factory-paths", "default preview did not serve index HTML")
    for path in ["../README.md", ".gitignore"]:
        try:
            factory.resolve_preview_asset(job["jobId"], path)
        except RuntimeError as error:
            require("invalid" in str(error) or "escapes" in str(error), "a.factory-paths", "wrong preview path rejection")
        else:
            raise ValueError("Unsafe preview path accepted")
    from .web_backend import FluxioWebBackend
    backend_root = scratch / "factory-backend"
    backend_root.mkdir()
    backend = FluxioWebBackend(backend_root, backend_root)
    created = backend.dispatch("create_app_factory_job_command", {"root": str(backend_root), "name": "Local Ledger", "brief": "Keep saved local entries and export a portable JSON ledger", "target": "neyvia"})
    loaded = backend.dispatch("get_app_factory_job_command", {"root": str(backend_root), "jobId": created["jobId"]})
    catalog = backend.dispatch("get_app_factory_catalog_command", {"root": str(backend_root)})
    require(loaded["verification"]["state"] == "passed" and catalog["summary"]["total"] == 1 and catalog["jobs"][0]["jobId"] == created["jobId"] and catalog["targets"][0]["id"] == "desktop", "a.factory-draft", "backend factory commands lost verified job/catalog identity")
    try:
        backend.dispatch("start_app_factory_native_build_command", {"root": str(backend_root), "jobId": created["jobId"]})
    except RuntimeError as error:
        require("Only desktop" in str(error), "a.factory-draft", "non-desktop native build rejected for wrong reason")
    else:
        require(False, "a.factory-draft", "non-desktop job entered native build")
    return job


def check_behavior(plan, capsule, registry):
    from .behavior_capsules import PLAN_SCHEMA, canonical_hash
    require(plan["schema"] == PLAN_SCHEMA and plan["capsule"] == capsule.public_dict(),
            "a.behavior-plan", "compiled plan does not retain its selected capsule")
    require(plan["planHash"] == canonical_hash({k: v for k, v in plan.items() if k not in {"compiledAt", "planHash"}}),
            "a.behavior-plan", "plan hash does not bind its executable content")
    require(plan["skillRuntime"]["mode"] == "instruction-plus-executable-contract" and
            plan["skillRuntime"]["executableGates"] == list(capsule.proof_gates),
            "a.behavior-gates", "learning must preserve executable proof gates")
    require(all(0 <= item <= 1 for item in plan["behaviorVector"].values()),
            "a.behavior-gates", "learned behavior escaped bounded unit range")
    require(registry.cache_hits >= 0 and registry.cache_misses >= len(registry._compile_cache),
            "a.behavior-cache", "compile cache accounting differs from stored entries")


def check_checkpoint(path, expected):
    saved = json.loads(path.read_text(encoding="utf-8"))
    require(saved == expected and not list(path.parent.glob(f".{path.name}.*.tmp")),
            "a.checkpoint-durable", "checkpoint must persist its complete record without temporary tails")


def check_selectors(preset, objective, top_k, selected):
    from .challenge_presets import _tokens
    ranked = sorted(preset.selector_keywords, key=lambda item: len(_tokens(objective) & _tokens(item)), reverse=True)
    matches = [item for item in ranked if _tokens(objective) & _tokens(item)]
    require(selected == (matches or ranked)[:top_k], "a.challenge-selection", "selectors do not follow objective relevance and fallback order")


def check_challenges(registry, names):
    require(names == sorted(registry.presets), "a.challenge-catalog", "preset names differ from loaded catalog")


def check_permissions(engine, permissions, mode, approved_permissions, workspace_scoped, decisions):
    from .capability_contracts import normalized_strings
    approved = {item.lower() for item in normalized_strings(approved_permissions)}
    normalized_mode = engine.normalize_mode(mode)
    expected = []
    for item in normalized_strings(permissions):
        permission = item.lower()
        if permission in approved or permission in engine.READ_PERMISSIONS:
            status = "allowed"
        elif normalized_mode == "review_only":
            status = "denied"
        elif permission in engine.LOCAL_MUTATIONS and normalized_mode != "always_ask" and workspace_scoped:
            status = "allowed"
        else:
            status = "approval_required"
        expected.append((permission, status))
    require([(item.permission, item.status) for item in decisions] == expected,
            "a.permission-modes", "permission decisions violate approval and workspace boundaries")


def self_check(root):
    from .behavior_capsules import BehaviorCapsuleRegistry
    from .challenge_presets import ChallengePresetRegistry
    from .checkpoints import CheckpointStore
    from .models import RunState
    from .capability_runtime import CapabilityPermissionEngine
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="a-capabilities-", dir=base))
    cases = []

    def run(identity, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            action()
            cases.append({"id": identity, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "error": str(error)})

    def behavior():
        registry = BehaviorCapsuleRegistry(scratch)
        design = registry.compile("Redesign responsive UI and verify screenshots", resource_profile={"mode": "maximal", "maximumTurns": 32, "toolCatalogLimit": 20, "specialistLimit": 4})
        require(design["capsule"]["id"] == "design-evolution" and "critic" in design["capsule"]["specialistRoles"] and "screenshot_set" in design["capsule"]["proofGates"], "a.behavior-plan", "design selection lost rendered critic workflow")
        registry = BehaviorCapsuleRegistry(scratch)
        first = registry.compile("Research and compare two architectures")
        second = registry.compile("Research and compare two architectures")
        require(first == second and registry.cache_snapshot() == {"hits": 1, "misses": 1, "hitRate": .5, "entries": 1}, "a.behavior-cache", "warm cache did not reuse the identical compiled plan")
        try:
            registry.compile("Invalid profile then recover", resource_profile={"maximumTurns": "invalid"})
        except ValueError:
            pass
        else:
            raise ValueError("Invalid resource turn profile was accepted")
        recovered = registry.compile("Valid profile after rejected compile")
        require(bool(recovered["planHash"]), "a.behavior-cache", "rejected compile poisoned subsequent valid compilation")
        learned = registry.compile("Implement and verify feature", learned_adjustment={"applied": True, "evidenceRuns": 12, "behaviorVectorDelta": {"initiative": 99, "verificationPressure": -99}})
        require(learned["behaviorVector"]["initiative"] == 1 and learned["behaviorVector"]["verificationPressure"] == 0 and "deterministic_check" in learned["capsule"]["proofGates"], "a.behavior-gates", "adversarial adjustment weakened proof gates")

    def challenges():
        registry = ChallengePresetRegistry(Path(__file__).resolve().parents[2] / "config/challenge_presets.json")
        require({"gandalf", "hackaprompt"} <= set(registry.list_names()), "a.challenge-catalog", "configured challenge presets are missing")
        require(bool(registry.get("gandalf").pick_selectors("Need stronger secret leak resistance and refusal policy")), "a.challenge-selection", "objective produced no selectors")

    def checkpoints():
        state = RunState(objective="recover proof workflow", plan_steps=["inspect", "verify"], acceptance_checks=["receipt"], completed_steps=["inspect"], next_actions=["verify"])
        path = CheckpointStore(scratch / "session").save("session", 1, state, {"status": "ok"}, ["README.md"])
        saved = CheckpointStore.load(path)
        require(saved["checkpoint_id"] == "ckpt_001" and saved["session_id"] == "session" and saved["state"]["objective"] == state.objective, "a.checkpoint-durable", "checkpoint identity or objective was lost")

    def permissions():
        engine = CapabilityPermissionEngine()
        requested = ["artifact.read", "artifact.write", "process.execute", "compute.spend", "destructive"]
        review = engine.summarize(engine.decide(requested, mode="review_only"))
        safe = engine.summarize(engine.decide(requested, mode="workspace_safe"))
        approved = engine.summarize(engine.decide(requested, approved_permissions=["compute.spend", "destructive"]))
        require("artifact.read" in review["allowed"] and "artifact.write" in review["denied"] and not review["canStart"], "a.permission-modes", "review mode allowed mutation")
        require({"artifact.write", "process.execute"} <= set(safe["allowed"]) and {"compute.spend", "destructive"} <= set(safe["approvalRequired"]) and approved["canRunWithoutApproval"], "a.permission-modes", "scoped policy or explicit approval was lost")

    def catalog():
        from .capability_service import CapabilityService
        from .proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(scratch / "catalog")
        service = CapabilityService(_fixture_root(scratch / "catalog"))
        snapshot = service.snapshot()
        require(snapshot["schema"] == "neyvia.capability_os_snapshot.v1" and snapshot["summary"]["packs"] >= 15 and snapshot["summary"]["capabilities"] >= 60 and snapshot["contracts"]["uiImplementationOwnedBy"] == "cursor", "a.catalog-observer", "catalog lost breadth or ownership")
        queries = [("professor literature student flashcards", "learning.flashcards"), ("numbers man working heavily with Excel formulas", "office.spreadsheet-analysis"), ("build and playtest my Unity game", "game.unity-project"), ("OCR a scanned PDF quickly", "document.fast-ocr"), ("authorized AI red team benchmark", "security.ai-red-team"), ("make a clothing care label", "fashion.label-system"), ("design an AI chatbot assistant", "ai.assistant-architecture")]
        for query, expected in queries:
            result = service.search({"query": query, "limit": 8})
            require(expected in [row["capabilityId"] for row in result["results"][:5]] and result["summary"]["durationMs"] < 50 and result["telemetry"]["schema"] == "neyvia.capability_telemetry.v1", "a.catalog-routing", f"route or budget failed for {expected}")
        row = service.describe("game.unity-project")
        require(row["adapter"] == "game.unity" and row["adapterDescriptor"]["kind"] == "external_executable" and isinstance(row["available"], bool) and (row["available"] or "found on PATH" in row["availabilityReason"]), "a.catalog-adapter", "Unity adapter readiness lost its executable evidence")

    def graph():
        from .artifact_graph import ArtifactGraph
        root = scratch / "graph"
        root.mkdir()
        source = root / "source.md"
        derived = root / "derived.pdf"
        source.write_text("# source", encoding="utf-8")
        derived.write_bytes(b"%PDF-1.7\nproof")
        graph = ArtifactGraph(root)
        parent = graph.register(path=source)
        child = graph.register(path=derived)
        edge = graph.relate(parent["artifactId"], child["artifactId"], "compiled_from", capability_id="document.latex-production", run_id="caprun_proof")
        lineage = ArtifactGraph(root).lineage(child["artifactId"], direction="ancestors")
        require(lineage["schema"] == "neyvia.artifact_graph.v1" and lineage["summary"] == {"artifactCount": 2, "relationCount": 1} and edge["relation"] == "compiled_from" and all(row["sha256"] for row in lineage["artifacts"]), "a.artifact-lineage", "restart lost verified lineage")
        for other in [parent["artifactId"], "missing"]:
            try:
                graph.relate(parent["artifactId"], other, "derived_from")
            except (ValueError, KeyError):
                pass
            else:
                raise ValueError("Invalid graph relation accepted")

    def treasury():
        from .legacy_asset_treasury import CapabilityTreasury
        from .model_portfolio import build_model_portfolio
        root = scratch / "treasury"
        material = {"docs/NOTES_ROADMAP.md": "# Roadmap\nconfidential plan narrative\n- [ ] review\n- [x] prototype\n", "proof/notes/receipt.json": json.dumps({"schema": "neyvia.proof.v1", "status": "passed", "privateNarrative": "confidential receipt narrative"}), "proof/notes/provider-password.json": json.dumps({"password": "excluded local fixture", "status": "passed"}), "apps/notes/index.html": "<main>Notes</main>", ".codex/skills/proof-loop/SKILL.md": "---\nname: proof-loop\n---\nCurrent instructions", ".codex/skills/proof-loop/SKILL.md.bak1": "prior revision", ".codex/skills/proof-loop/SKILL.md.bak2": "older revision", "receipts/release.json": json.dumps({"schema": "neyvia.release_receipt.v1", "status": "passed"})}
        for name, text in material.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        job = {"jobId": "app-notes", "updatedAt": "2026-07-30T10:00:00Z", "spec": {"name": "Notes", "slug": "notes", "appId": "local.notes", "template": "static-local-app"}, "package": {"path": "notes.zip", "sha256": "a" * 64, "fileCount": 3, "bytes": 900}, "verification": {"state": "passed", "verifiedAt": "2026-07-30T10:00:00Z", "receiptPath": "proof/notes/receipt.json"}}
        graph = {"artifacts": [{"artifactId": "source", "source": "notes", "exists": True, "sha256": "b" * 64, "sizeBytes": 100}, {"artifactId": "result", "source": "notes", "exists": True, "sha256": "c" * 64, "sizeBytes": 200}], "relations": [{"parentArtifactId": "source", "childArtifactId": "result", "relation": "derived_from"}]}
        portfolio = build_model_portfolio(provider_presence={"openai-codex": True}, runtime_presence={"codex": True, "kimi-code": True})
        result = CapabilityTreasury(root).snapshot(app_factory_jobs=[job], artifact_graph=graph, model_portfolio=portfolio)
        encoded = json.dumps(result)
        require(result["schema"] == "neyvia.capability_treasury.v1" and result["summary"]["verifiedAssetCount"] >= 3 and result["summary"]["recoveryMissionCount"] >= 1 and result["recoveries"][0]["recommendedRoute"]["provider"] == "openai-codex", "a.treasury-boundary", "typed recovery or provider routing failed")
        require(all(text not in encoded for text in ["confidential plan narrative", "confidential receipt narrative", "excluded local fixture", "provider-password.json"]), "a.treasury-boundary", "file bodies or excluded credentials entered recovery output")

    run("behavior.compilation", ["a.behavior-plan", "a.behavior-gates", "a.behavior-cache"], behavior)
    run("challenge.selection", ["a.challenge-catalog", "a.challenge-selection"], challenges)
    run("checkpoint.roundtrip", ["a.checkpoint-durable"], checkpoints)
    run("permissions.policy", ["a.permission-modes"], permissions)
    run("catalog.routing", ["a.catalog-observer", "a.catalog-routing", "a.catalog-adapter"], catalog)
    run("artifacts.lineage", ["a.artifact-durable", "a.artifact-relations", "a.artifact-lineage"], graph)
    run("treasury.recovery", ["a.treasury-boundary"], treasury)
    run("surface.authority", ["a.surface-manifest", "a.surface-authority", "a.surface-plan", "a.surface-receipt", "a.surface-lifecycle", "a.surface-log"], lambda: _surface_self_check(scratch))
    run("factory.scaffold", ["a.factory-draft", "a.factory-package", "a.factory-paths"], lambda: _factory_self_check(scratch))
    run("capability.lifecycle", ["a.capability-plan", "a.capability-preview", "a.capability-pack", "a.capability-admission", "a.adapter-execution", "a.adapter-file-inspection", "a.capability-ui-schema", "a.catalog-routing"], lambda: _capability_workflow_self_check(scratch))
    from .proofs_a_capability_evolution import self_check as evolution_self_check
    run("evolution.receipt-workflow", ["a.evolution-stagnation", "a.evolution-sealed", "a.evolution-receipts", "a.evolution-forge", "a.evolution-inactive", "a.evolution-lease", "a.evolution-handoff", "a.evolution-outcome", "a.evolution-friction", "a.factory-lineage"], lambda: evolution_self_check(scratch))
    from .proofs_a_app_standard import self_check as app_standard_self_check
    run("apps.bridge-observation", ["a.app-state", "a.app-observation", "a.app-storage", "a.app-cloud"], lambda: app_standard_self_check(scratch))
    from .proofs_a_factory_browser import self_check as factory_browser_self_check
    run("factory.rendered-workflows", ["a.factory-notes-ui", "a.factory-guided-ui"], lambda: factory_browser_self_check(scratch))
    from .proofs_a_capability_tools import self_check as capability_tools_self_check
    run("capability.authored-and-replay", ["a.authored-tool", "a.authored-argv", "a.cu-metrics", "a.cu-replay", "a.cu-portable", "a.cu-verifier", "a.tool-readiness", "a.tool-reference", "a.tool-typed", "a.tool-private", "a.pdf-bounded", "a.android-approval", "a.adapter-session", "a.tool-workspace", "a.capability-benchmark"], lambda: capability_tools_self_check(scratch))
    return {"ok": all(item["ok"] for item in cases), "contracts": sorted({identity for item in cases if item["ok"] for identity in item["contracts"]}), "scratchRoot": str(scratch), "cases": cases, "durationMs": round((time.perf_counter() - started) * 1000, 3)}


def _fixture_root(root):
    """Bind the real consumer to an empty broker config in disposable state."""
    from .proof_credential_guard import prepare_broker_fixture
    root = Path(root).resolve()
    if not (root / "config/neyvia_secret_broker.json").exists():
        prepare_broker_fixture(root)
    return root
