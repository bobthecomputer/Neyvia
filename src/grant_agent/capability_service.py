"""Facade joining N-E-Y-V-I-A capability catalog, artifacts, runs, and adapters."""

from __future__ import annotations

from .proofs_c_models import checked

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .artifact_graph import ArtifactGraph
from .proofs_b_adapters import checked as _proofs_b_checked
from .application_surface import ApplicationSurfaceService, ExternalReceiptAuthority
from .capability_adapters import CapabilityAdapterRegistry
from .capability_catalog import CapabilityPlanner, CapabilityRegistry
from .capability_contracts import (
    CAPABILITY_PLAN_SCHEMA,
    ArtifactSelector,
    CapabilityPack,
    PreviewEvent,
    canonical_hash,
    normalized_strings,
    utc_now,
)
from .capability_runtime import (
    CapabilityPermissionEngine,
    CapabilityRunStore,
    CapabilityTelemetryStore,
    process_memory_bytes,
)
from .computer_use_twin import ComputerUseTwinService
from .computer_use_verifier import ComputerUseVerifierService
from .encrypted_chat import EncryptedChatService
from .folder_sync import FolderSyncService
from .model_tool_intelligence import (
    ModelToolIntelligence,
    validate_json_schema_value,
)
from .mesh_service import MeshService
from .module_marketplace import ModuleMarketplace
from .nearby_send import NearbySendService
from .p2p_cache import P2PCacheService
from .p2p_provider import P2PProviderService
from .secret_broker import SecretBrokerService
from .security_runtime_policy import (
    audit_installed_security_runtime,
    build_purple_team_plan,
    evaluate_security_action,
    validate_security_scope,
)
from .tool_factory import AuthoredToolStore, render_templates
from .tool_manifest_registry import ToolManifestRegistry
from .proofs_a_capabilities import checked_action, check_pack_save, check_capability_execution, check_ui_contract
from .proofs_a_capability_tools import check_authored_command, check_operation, check_benchmark


CAPABILITY_OS_SNAPSHOT_SCHEMA = "neyvia.capability_os_snapshot.v1"
CAPABILITY_UI_CONTRACT_SCHEMA = "neyvia.capability_ui_contract.v1"
CAPABILITY_BENCHMARK_SCHEMA = "neyvia.capability_benchmark.v1"

CAPABILITY_PERFORMANCE_BUDGETS = {
    "searchWarmP95Ms": 50.0,
    "localRoutingP95Ms": 250.0,
    "uiAcknowledgementMs": 100.0,
    "idleCpuPercent": 1.0,
    "idleWorkingSetBytes": 450 * 1024 * 1024,
    "previewPhases": ["plan", "live", "result"],
}

SECURITY_SCOPE_TOOL_SCHEMA = {
    "type": "object",
    "required": ["target"],
    "properties": {
        "target": {"type": "string"},
        "authorizedBy": {"type": "string"},
        "authorizationConfirmed": {"type": "boolean"},
        "environment": {
            "type": "string",
            "enum": ["lab", "staging", "production"],
        },
        "mode": {"type": "string", "enum": ["passive", "active"]},
        "allowedTargets": {"type": "array", "items": {"type": "string"}},
        "excludedTargets": {"type": "array", "items": {"type": "string"}},
        "allowedActionClasses": {
            "type": "array",
            "items": {"type": "string"},
        },
        "allowCredentialAccess": {"type": "boolean"},
        "allowDestructiveActions": {"type": "boolean"},
        "allowPersistence": {"type": "boolean"},
        "allowExternalDelivery": {"type": "boolean"},
        "maxProbeAttempts": {"type": "integer", "minimum": 1, "maximum": 50},
        "dataHandling": {"type": "string"},
        "approvalId": {"type": "string"},
    },
}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


class CapabilityService:
    """Stable backend boundary intended for CLI, workers, HTTP, and future UI."""

    def __init__(
        self,
        root: str | Path,
        *,
        catalog_path: str | Path | None = None,
        application_surface_receipt_authority: ExternalReceiptAuthority | None = None,
        include_default_mcp_demo: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.include_default_mcp_demo = bool(include_default_mcp_demo)
        selected_catalog = Path(
            catalog_path or self.root / "config" / "capability_packs.json"
        )
        if not selected_catalog.exists():
            selected_catalog = (
                Path(__file__).resolve().parents[2]
                / "config"
                / "capability_packs.json"
            )
        self.catalog_path = selected_catalog.resolve()
        selected_tool_lock = self.root / "config" / "tool_suite_lock.json"
        if not selected_tool_lock.exists():
            selected_tool_lock = (
                Path(__file__).resolve().parents[2]
                / "config"
                / "tool_suite_lock.json"
            )
        self.tool_lock_path = selected_tool_lock.resolve()
        self.tool_manifests = ToolManifestRegistry(self.tool_lock_path)
        self.adapters = CapabilityAdapterRegistry(
            self.root,
            tool_manifests=self.tool_manifests,
        )
        self.tool_manifests.bind_adapters(self.adapters)
        self.permissions = CapabilityPermissionEngine()
        self.registry = CapabilityRegistry(
            self.catalog_path,
            adapters=self.adapters,
            extra_catalog_dir=(
                self.root / ".agent_control" / "capability_packs"
            ),
        )
        self.planner = CapabilityPlanner(self.registry, self.permissions)
        self.artifacts = ArtifactGraph(self.root)
        self.runs = CapabilityRunStore(self.root)
        self.telemetry = CapabilityTelemetryStore(self.root)
        self.authored_tools = AuthoredToolStore(self.root)
        self.module_marketplace = ModuleMarketplace(self.root)
        self.mesh = MeshService(self.root)
        self.nearby_send = NearbySendService(self.root)
        self.folder_sync = FolderSyncService(self.root)
        self.encrypted_chat = EncryptedChatService(self.root)
        self.secret_broker = SecretBrokerService(self.root)
        self.p2p_cache = P2PCacheService(self.root)
        self.p2p_provider = P2PProviderService(self.root)
        self.computer_use_twin = ComputerUseTwinService(self.root)
        self.computer_use_verifier = ComputerUseVerifierService(self.root)
        self.application_surfaces = ApplicationSurfaceService(
            self.root,
            receipt_authority=application_surface_receipt_authority,
        )
        self._model_tool_surface: Any | None = None
        self._model_tool_broker: Any | None = None
        self._model_tool_intelligence: ModelToolIntelligence | None = None
        self.plan_dir = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "capability_os"
            / "plans"
        )

    @staticmethod
    def _artifact_selectors(values: object) -> list[ArtifactSelector]:
        return [
            ArtifactSelector.from_payload(item)
            for item in (values if isinstance(values, list) else [])
        ]

    def snapshot(
        self,
        *,
        include_capabilities: bool = False,
        telemetry_limit: int = 20,
        run_limit: int = 20,
    ) -> dict[str, Any]:
        catalog = self.registry.snapshot(
            include_capabilities=include_capabilities
        )
        graph = self.artifacts.snapshot()
        runs = self.runs.list_runs(limit=run_limit)
        authored_tools = self.authored_tools.list_tools()
        tool_suite = self.tool_manifests.snapshot(
            include_operations=include_capabilities
        )
        active_modules = self.module_marketplace.active_context_snapshot(
            max_modules=50 if include_capabilities else 20,
            max_context_bytes=256 * 1024 if include_capabilities else 64 * 1024,
        )
        mesh = self.mesh.bootstrap()
        nearby_send = self.nearby_send.bootstrap()
        folder_sync = self.folder_sync.bootstrap()
        encrypted_chat = self.encrypted_chat.bootstrap()
        secret_broker = self.secret_broker.bootstrap()
        p2p_cache = self.p2p_cache.bootstrap()
        p2p_provider = self.p2p_provider.status()
        twin_specs = self.computer_use_twin.list_specs()
        application_surfaces = self.application_surfaces.catalog()
        return {
            "schema": CAPABILITY_OS_SNAPSHOT_SCHEMA,
            "generatedAt": utc_now(),
            "catalog": catalog,
            "artifactGraph": graph,
            "runs": runs,
            "authoredTools": authored_tools,
            "toolSuite": tool_suite,
            "activeModules": active_modules,
            "mesh": mesh,
            "nearbySend": nearby_send,
            "folderSync": folder_sync,
            "encryptedChat": encrypted_chat,
            "secretBroker": secret_broker,
            "p2pCache": p2p_cache,
            "p2pProvider": p2p_provider,
            "computerUseTwins": twin_specs,
            "applicationSurfaces": application_surfaces,
            "telemetry": self.telemetry.recent(limit=telemetry_limit),
            "contracts": {
                "schemasDeferred": not include_capabilities,
                "previewPhases": ["plan", "live", "result"],
                "experienceLevels": ["guided", "standard", "advanced", "expert"],
                "permissionModes": [
                    "always_ask",
                    "workspace_safe",
                    "review_only",
                    "autonomous_scoped",
                ],
                "uiImplementationOwnedBy": "cursor",
                "performanceBudgets": dict(CAPABILITY_PERFORMANCE_BUDGETS),
            },
            "summary": {
                "packs": catalog["summary"]["packs"],
                "capabilities": catalog["summary"]["capabilities"],
                "availableCapabilities": catalog["summary"]["availableCapabilities"],
                "artifacts": graph["summary"]["artifacts"],
                "runs": len(runs),
                "authoredTools": len(authored_tools["tools"]),
                "selectedTools": tool_suite["summary"]["tools"],
                "agentReadyTools": tool_suite["summary"]["agentReady"],
                "executionReadyTools": tool_suite["summary"]["executionReady"],
                "productionReadyTools": tool_suite["summary"]["productionReady"],
                "activeModules": active_modules["moduleCount"],
                "meshServices": mesh["registeredServices"],
                "computerUseTwins": len(twin_specs["specs"]),
                "applicationSurfaces": application_surfaces["summary"]["declared"],
                "launchReadyApplicationTargets": application_surfaces["summary"][
                    "launchReadyTargets"
                ],
            },
        }

    @checked_action(check_ui_contract)
    def ui_contract(self) -> dict[str, Any]:
        """Return behavior and state contracts without prescribing visual styling."""

        return {
            "schema": CAPABILITY_UI_CONTRACT_SCHEMA,
            "generatedAt": utc_now(),
            "ownerBoundary": {
                "backend": "N-E-Y-V-I-A capability service",
                "visualImplementation": "Cursor",
                "rule": "UI must render backend truth and must not invent capability availability.",
            },
            "primaryObjects": [
                "capability",
                "capabilityPack",
                "artifact",
                "artifactRelation",
                "capabilityPlan",
                "capabilityRun",
                "previewEvent",
                "adapter",
                "telemetryReceipt",
                "authoredTool",
                "toolAdaptationDraft",
                "computerUseTwinSpec",
                "computerUseTwinRun",
                "computerUseVerification",
                "modelToolDescriptor",
                "modelToolBelt",
                "modelToolLoop",
                "modelToolFeedback",
                "applicationSurface",
                "applicationSurfaceLaunchPlan",
                "applicationSurfaceProof",
                "applicationSurfaceApprovalReceipt",
            ],
            "commands": [
                {"name": "get_capability_os_snapshot_command", "mutability": "read"},
                {"name": "search_capabilities_command", "mutability": "read"},
                {"name": "describe_capability_command", "mutability": "read"},
                {"name": "validate_capability_pack_command", "mutability": "read"},
                {
                    "name": "save_capability_pack_command",
                    "mutability": "workspace_write",
                    "approvalRequired": True,
                },
                {"name": "plan_capability_run_command", "mutability": "read"},
                {"name": "create_capability_run_command", "mutability": "artifact_write"},
                {"name": "get_capability_run_command", "mutability": "read"},
                {"name": "record_capability_preview_command", "mutability": "artifact_write"},
                {"name": "finish_capability_run_command", "mutability": "artifact_write"},
                {"name": "register_capability_artifact_command", "mutability": "artifact_write"},
                {"name": "relate_capability_artifacts_command", "mutability": "artifact_write"},
                {"name": "get_capability_artifact_lineage_command", "mutability": "read"},
                {
                    "name": "execute_capability_command",
                    "mutability": "permission_dependent",
                },
                {"name": "benchmark_capability_os_command", "mutability": "read"},
                {
                    "name": "register_capability_adapter_session_command",
                    "mutability": "external_side_effect",
                    "approvalRequired": True,
                },
                {
                    "name": "heartbeat_capability_adapter_session_command",
                    "mutability": "session_heartbeat",
                },
                {
                    "name": "disconnect_capability_adapter_session_command",
                    "mutability": "external_side_effect",
                    "approvalRequired": True,
                },
                {"name": "list_authored_tools_command", "mutability": "read"},
                {"name": "search_authored_tools_command", "mutability": "read"},
                {"name": "describe_authored_tool_command", "mutability": "read"},
                {"name": "adapt_authored_tool_command", "mutability": "read"},
                {"name": "validate_authored_tool_command", "mutability": "read"},
                {
                    "name": "save_authored_tool_command",
                    "mutability": "workspace_write",
                    "approvalRequired": True,
                },
                {
                    "name": "execute_authored_tool_command",
                    "mutability": "permission_dependent",
                },
                {"name": "get_mcp_broker_snapshot_command", "mutability": "read"},
                {"name": "search_mcp_tools_command", "mutability": "read"},
                {"name": "describe_mcp_tool_command", "mutability": "read"},
                {
                    "name": "call_mcp_tool_command",
                    "mutability": "permission_dependent",
                    "approvalRequired": True,
                },
                {"name": "list_computer_use_twins_command", "mutability": "read"},
                {"name": "validate_computer_use_twin_command", "mutability": "read"},
                {
                    "name": "save_computer_use_twin_command",
                    "mutability": "artifact_write",
                    "approvalRequired": True,
                },
                {
                    "name": "run_computer_use_twin_command",
                    "mutability": "isolated_browser_execution",
                    "approvalRequired": True,
                },
                {
                    "name": "dispatch_computer_use_twin_command",
                    "mutability": "cluster_job",
                    "approvalRequired": True,
                },
                {
                    "name": "verify_computer_use_change_command",
                    "mutability": "isolated_browser_execution",
                    "approvalRequired": True,
                },
                {
                    "name": "dispatch_computer_use_verification_command",
                    "mutability": "cluster_job",
                    "approvalRequired": True,
                },
                {"name": "get_security_runtime_audit_command", "mutability": "read"},
                {"name": "validate_security_scope_command", "mutability": "read"},
                {"name": "build_purple_team_plan_command", "mutability": "read"},
                {"name": "evaluate_security_action_command", "mutability": "read"},
                {"name": "compile_model_tool_belt_command", "mutability": "read"},
                {"name": "compile_openai_tool_belt_command", "mutability": "read"},
                {"name": "benchmark_model_tool_routing_command", "mutability": "read"},
                {"name": "get_model_tool_feedback_command", "mutability": "read"},
                {"name": "record_model_tool_feedback_command", "mutability": "artifact_write"},
                {
                    "name": "run_model_tool_plan_command",
                    "mutability": "permission_dependent",
                },
                {"name": "get_application_surface_catalog_command", "mutability": "read"},
                {"name": "validate_application_surface_command", "mutability": "read"},
                {"name": "get_application_surface_status_command", "mutability": "read"},
                {
                    "name": "plan_application_surface_launch_command",
                    "mutability": "read",
                    "note": "Returns a permission-bound plan and never launches.",
                },
                {"name": "observe_application_surface_command", "mutability": "read"},
            ],
            "lifecycle": {
                "runStatuses": [
                    "ready",
                    "awaiting_approval",
                    "running",
                    "completed",
                    "failed",
                    "cancelled",
                ],
                "planReadiness": [
                    "ready",
                    "approval_required",
                    "adapter_required",
                    "blocked",
                ],
                "previewPhases": ["plan", "live", "result"],
                "adapterStates": [
                    "available",
                    "unavailable",
                    "not_executable",
                    "delegation_required",
                ],
                "applicationSurfaceStates": [
                    "undeclared",
                    "invalid",
                    "unavailable",
                    "declared",
                    "present",
                    "ready",
                    "launching",
                    "running",
                    "stopped",
                    "failed",
                ],
                "applicationSurfaceLaunchPlanStates": [
                    "ready",
                    "approval_required",
                    "unavailable",
                    "blocked",
                ],
            },
            "requiredEmptyStates": {
                "noSearchResults": "No capability matched. Offer custom-pack authoring.",
                "adapterUnavailable": "Name the missing real adapter and keep execution disabled.",
                "approvalRequired": "Show exact permissions and wait for explicit approval.",
                "noArtifacts": "Allow prompt-only planning; do not invent a selected file.",
                "runFailed": "Keep partial previews, proof, and retry boundary available.",
                "noAuthoredTools": "Offer adaptation or authoring; never invent a runnable tool.",
                "noTwinBaseline": "Allow functional proof, but forbid faster or more accurate comparative claims.",
                "computerUseReplayOnly": "Label replay as non-live and keep product-verification claims disabled.",
                "applicationSurfaceUnavailable": "Name the missing build artifact or declared unavailable target; never fabricate an installer or mobile proof.",
            },
            "performanceBudgets": dict(CAPABILITY_PERFORMANCE_BUDGETS),
            "catalogSummary": {
                "packs": len(self.registry.packs),
                "capabilities": len(self.registry.capabilities),
                "catalogHash": self.registry.catalog_hash,
            },
        }

    def application_surface_catalog(self) -> dict[str, Any]:
        return self.application_surfaces.catalog()

    def validate_application_surface(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = payload.get("manifest", payload)
        return self.application_surfaces.validate(manifest)

    def application_surface_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = payload.get("manifest", payload)
        return self.application_surfaces.status(
            manifest,
            target_id=str(payload.get("targetId") or payload.get("target_id") or ""),
        )

    def plan_application_surface_launch(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = payload.get("manifest", payload)
        return self.application_surfaces.plan_launch(
            manifest,
            target_id=str(payload.get("targetId") or payload.get("target_id") or ""),
            permission_mode=str(
                payload.get("permissionMode")
                or payload.get("permission_mode")
                or "workspace_safe"
            ),
            approval_id=str(
                payload.get("approvalId") or payload.get("approval_id") or ""
            ),
        )

    def observe_application_surface(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = payload.get("manifest", payload)
        return self.application_surfaces.observe(
            manifest,
            max_log_lines=int(
                payload.get("maxLogLines") or payload.get("max_log_lines") or 80
            ),
            max_proof_files=int(
                payload.get("maxProofFiles") or payload.get("max_proof_files") or 20
            ),
        )

    def _ensure_model_tool_intelligence(self) -> ModelToolIntelligence:
        if self._model_tool_intelligence is not None:
            return self._model_tool_intelligence
        from .mcp_broker import McpOutboundBroker, register_with_progressive_surface as register_mcp
        from .progressive_tools import ProgressiveToolSurface
        from .ui_tools import (
            default_ui_surface,
            register_with_progressive_surface as register_ui,
        )
        from .native_tools import (
            NativeToolRegistry,
            register_with_progressive_surface as register_native,
        )

        surface = ProgressiveToolSurface()
        register_with_progressive_surface(surface, self)
        ui_surface = default_ui_surface(self.root)
        register_ui(surface, ui_surface)
        register_native(
            surface,
            NativeToolRegistry(
                self.root,
                browser_runtime=ui_surface.observer.browser_runtime,
            ),
        )
        broker = McpOutboundBroker(
            self.root,
            include_default_demo=self.include_default_mcp_demo,
        )
        register_mcp(surface, broker)
        self._model_tool_surface = surface
        self._model_tool_broker = broker
        self._model_tool_intelligence = ModelToolIntelligence(
            self.root,
            progressive=surface,
            authored_store=self.authored_tools,
            adapter_registry=self.adapters,
            capability_registry=self.registry,
            mcp_broker=broker,
        )
        return self._model_tool_intelligence

    def compile_model_tool_belt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._ensure_model_tool_intelligence().compile_belt(payload)

    def mcp_broker_snapshot(self) -> dict[str, Any]:
        self._ensure_model_tool_intelligence()
        return self._model_tool_broker.snapshot()

    def search_mcp_tools(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_model_tool_intelligence()
        query = str(payload.get("query") or "")
        server = str(payload.get("server") or "").strip() or None
        return {
            "schema": "neyvia.mcp_broker.search.v1",
            "query": query,
            "server": server,
            "tools": self._model_tool_broker.search(
                query,
                limit=int(payload.get("limit") or 20),
                server=server,
            ),
        }

    def describe_mcp_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_model_tool_intelligence()
        return self._model_tool_broker.describe(
            str(payload.get("server") or payload.get("name") or ""),
            tool=str(payload.get("tool") or "").strip() or None,
            name=str(payload.get("name") or "").strip() or None,
        )

    def call_mcp_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_model_tool_intelligence()
        return self._model_tool_broker.call(
            str(payload.get("server") or payload.get("name") or ""),
            tool=str(payload.get("tool") or "").strip() or None,
            name=str(payload.get("name") or "").strip() or None,
            arguments=(
                dict(payload.get("arguments"))
                if isinstance(payload.get("arguments"), dict)
                else {}
            ),
            approved=bool(payload.get("approved")),
            approval_id=str(payload.get("approvalId") or payload.get("approval_id") or ""),
            mission_id=str(payload.get("missionId") or payload.get("mission_id") or ""),
        )

    def compile_openai_tool_belt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._ensure_model_tool_intelligence().compile_openai(payload)

    @checked("benchmark")
    def benchmark_model_tool_routing(
        self, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = payload or {}
        cases = data.get("cases")
        if not isinstance(cases, list) or not cases:
            cases = [
                {"task": "OCR a scanned PDF quickly and retain page citations", "expected": "document.fast-ocr"},
                {"task": "Review research papers and synthesize a cited literature review", "expected": "research.literature-review"},
                {"task": "Analyze this Excel workbook and explain its charts", "expected": "office.spreadsheet-analysis"},
                {"task": "Create a PowerPoint presentation from the research", "expected": "office.presentation-authoring"},
                {"task": "Build and playtest a Unity 3D scene", "expected": "game.unity-project"},
                {"task": "Run an authorized AI model red-team assessment", "expected": "security.ai-red-team"},
                {"task": "Benchmark an AI model for quality latency and robustness", "expected": "ai.model-benchmarking"},
                {"task": "Test the native Android app in an emulator", "expected": "device.android-test"},
                {"task": "Make source-grounded flashcards for a student", "expected": "learning.flashcards"},
                {"task": "Design a clothing label system and production-ready specifications", "expected": "fashion.label-system"},
            ]
        intelligence = self._ensure_model_tool_intelligence()
        rows: list[dict[str, Any]] = []
        durations: list[float] = []
        for case in cases[:100]:
            if not isinstance(case, dict):
                continue
            task = str(case.get("task") or "").strip()
            expected = str(case.get("expected") or "").strip()
            if not task or not expected:
                continue
            started = time.perf_counter()
            belt = intelligence.compile_belt(
                {
                    "task": task,
                    "roles": case.get("roles") or [],
                    "artifactTypes": case.get("artifactTypes") or [],
                    "limit": int(case.get("limit") or 8),
                }
            )
            duration_ms = (time.perf_counter() - started) * 1000.0
            durations.append(duration_ms)
            selected = [str(item.get("name") or "") for item in belt["tools"]]
            rows.append(
                {
                    "task": task,
                    "expected": expected,
                    "selected": selected,
                    "top1": bool(selected and selected[0] == expected),
                    "top3": expected in selected[:3],
                    "topK": expected in selected,
                    "durationMs": round(duration_ms, 3),
                    "modelContextBytes": belt["summary"]["modelContextBytes"],
                    "fullSchemaContextBytes": belt["summary"]["fullSchemaContextBytes"],
                    "contextReductionRatio": belt["summary"]["contextReductionRatio"],
                }
            )
        count = len(rows)
        sorted_durations = sorted(durations)
        p95_index = max(
            0,
            min(
                len(sorted_durations) - 1,
                int(len(sorted_durations) * 0.95) - 1,
            ),
        )
        result = {
            "schema": "neyvia.model_tool_routing_benchmark.v1",
            "generatedAt": utc_now(),
            "cases": rows,
            "summary": {
                "cases": count,
                "top1Accuracy": round(
                    sum(1 for row in rows if row["top1"]) / max(count, 1), 4
                ),
                "top3Accuracy": round(
                    sum(1 for row in rows if row["top3"]) / max(count, 1), 4
                ),
                "topKAccuracy": round(
                    sum(1 for row in rows if row["topK"]) / max(count, 1), 4
                ),
                "p95RoutingMs": (
                    round(sorted_durations[p95_index], 3)
                    if sorted_durations
                    else 0.0
                ),
                "averageContextReductionRatio": round(
                    sum(row["contextReductionRatio"] for row in rows)
                    / max(count, 1),
                    4,
                ),
            },
            "acceptance": {
                "top3AccuracyMinimum": 0.9,
                "p95RoutingMsMaximum": 250.0,
                "contextReductionRatioMinimum": 2.0,
            },
        }
        result["status"] = (
            "pass"
            if result["summary"]["top3Accuracy"]
            >= result["acceptance"]["top3AccuracyMinimum"]
            and result["summary"]["p95RoutingMs"]
            <= result["acceptance"]["p95RoutingMsMaximum"]
            and result["summary"]["averageContextReductionRatio"]
            >= result["acceptance"]["contextReductionRatioMinimum"]
            else "fail"
        )
        receipt_dir = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "model_tool_intelligence"
            / "benchmarks"
        )
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        receipt = receipt_dir / f"{stamp}_{uuid.uuid4().hex}_routing.json"
        _atomic_json(receipt, result)
        result["receiptPath"] = str(receipt)
        return result

    def model_tool_feedback(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload or {}
        intelligence = self._ensure_model_tool_intelligence()
        return {
            "schema": "neyvia.model_tool_feedback_snapshot.v1",
            "events": intelligence.feedback.recent(
                limit=int(data.get("limit") or 100)
            ),
            "aggregates": intelligence.feedback.aggregate(
                limit=int(data.get("aggregateLimit") or 5000)
            ),
        }

    def record_model_tool_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "schema": "neyvia.model_tool_feedback_write.v1",
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "artifact.write",
            }
        return self._ensure_model_tool_intelligence().feedback.record(payload)

    def run_model_tool_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        intelligence = self._ensure_model_tool_intelligence()

        def execute(
            target: str,
            arguments: dict[str, Any],
            context: dict[str, Any],
        ) -> Any:
            call_args = dict(arguments)
            approved = bool(context.get("approved"))
            approval_id = str(context.get("approvalId") or "")
            mission_id = str(context.get("missionId") or "")
            if target == "laya.native.neyvia_navigation" and not bool(payload.get("approved")):
                return {
                    "ok": False,
                    "status": "approval_required",
                    "requiredPermission": "external.side_effect",
                }
            if target.startswith("mcp.") and target not in {
                "mcp.servers",
                "mcp.search",
                "mcp.describe",
                "mcp.call",
            }:
                return self._model_tool_broker.call(
                    target,
                    arguments=call_args,
                    name=target,
                    approved=approved,
                    approval_id=approval_id,
                    mission_id=mission_id,
                )
            if target == "mcp.call":
                call_args.setdefault("approved", approved)
                call_args.setdefault("approvalId", approval_id)
                call_args.setdefault("missionId", mission_id)
            return self._model_tool_surface.call(target, call_args)

        return intelligence.run_bounded(payload, executor=execute)

    @checked_action(check_benchmark)
    def benchmark(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload or {}
        queries = normalized_strings(data.get("queries")) or [
            "OCR a scanned PDF and cite the sources",
            "build and playtest a Unity game mod",
            "analyze an Excel workbook and create a PowerPoint",
            "run an authorized AI red-team benchmark",
            "teach literature with flashcards and a graded quiz",
            "design a clothing label and production pack",
        ]
        iterations = max(1, min(int(data.get("iterations") or 20), 100))
        warmups = max(1, min(int(data.get("warmups") or 3), 20))
        for index in range(warmups):
            self.registry.search(queries[index % len(queries)], limit=12)
        started_memory = process_memory_bytes()
        durations: list[float] = []
        started = time.perf_counter()
        for index in range(iterations):
            query = queries[index % len(queries)]
            item_started = time.perf_counter()
            self.registry.search(query, limit=12)
            durations.append((time.perf_counter() - item_started) * 1000.0)
        total_ms = (time.perf_counter() - started) * 1000.0
        finished_memory = process_memory_bytes()
        durations.sort()

        def percentile(fraction: float) -> float:
            position = max(0, min(len(durations) - 1, int(len(durations) * fraction) - 1))
            return round(durations[position], 3)

        p50 = percentile(0.50)
        p95 = percentile(0.95)
        budget = float(CAPABILITY_PERFORMANCE_BUDGETS["searchWarmP95Ms"])
        result = {
            "schema": CAPABILITY_BENCHMARK_SCHEMA,
            "generatedAt": utc_now(),
            "catalogHash": self.registry.catalog_hash,
            "catalogCapabilities": len(self.registry.capabilities),
            "queries": queries,
            "iterations": iterations,
            "warmups": warmups,
            "search": {
                "p50Ms": p50,
                "p95Ms": p95,
                "maximumMs": round(max(durations), 3),
                "totalMs": round(total_ms, 3),
                "operationsPerSecond": round(
                    iterations / max(total_ms / 1000.0, 0.000001),
                    2,
                ),
                "budgetP95Ms": budget,
                "status": "pass" if p95 <= budget else "fail",
            },
            "memory": {
                "startedWorkingSetBytes": started_memory,
                "finishedWorkingSetBytes": finished_memory,
                "deltaBytes": (
                    None
                    if started_memory is None or finished_memory is None
                    else finished_memory - started_memory
                ),
            },
            "tenXAcceptance": {
                "baselineRequired": True,
                "qualifyingMetrics": [
                    "time_to_first_useful_result",
                    "manual_interaction_count",
                    "repeat_task_throughput",
                    "model_context_bytes",
                    "operator_wait_time",
                ],
                "claimPolicy": "No 10x claim is valid without a retained baseline and candidate receipt.",
            },
        }
        result["telemetry"] = self.telemetry.record(
            "capability.benchmark",
            duration_ms=total_ms,
            ok=result["search"]["status"] == "pass",
            started_memory_bytes=started_memory,
            finished_memory_bytes=finished_memory,
            metadata={
                "iterations": iterations,
                "p95Ms": p95,
                "catalogCapabilities": len(self.registry.capabilities),
            },
        )
        return result

    def register_adapter_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.adapters.register_session(payload)

    def heartbeat_adapter_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.adapters.heartbeat_session(
            str(payload.get("sessionId") or payload.get("session_id") or ""),
            str(payload.get("heartbeatKey") or payload.get("heartbeat_key") or ""),
        )

    def disconnect_adapter_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.adapters.disconnect_session(
            str(payload.get("sessionId") or payload.get("session_id") or ""),
            approved=bool(payload.get("approved")),
        )

    def list_authored_tools(self) -> dict[str, Any]:
        return self.authored_tools.list_tools()

    def search_authored_tools(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "")
        return {
            "schema": "neyvia.authored_tool_search.v1",
            "query": query,
            "tools": self.authored_tools.search(
                query,
                limit=int(payload.get("limit") or 10),
            ),
        }

    def describe_authored_tool(self, tool_id: str) -> dict[str, Any]:
        tool = self.authored_tools.describe(tool_id)
        adapter_id = ""
        if tool["kind"] == "command":
            adapter_id = str(tool["command"].get("adapterId") or "")
        elif tool["kind"] == "delegated":
            adapter_id = str(tool["delegated"].get("adapterId") or "")
        descriptor = self.adapters.descriptor(adapter_id) if adapter_id else None
        result = dict(tool)
        result["adapterDescriptor"] = (
            descriptor.as_dict() if descriptor is not None else None
        )
        result["available"] = (
            tool["kind"] == "composite"
            or bool(descriptor and descriptor.available)
        )
        return result

    def adapt_authored_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.authored_tools.adapt(payload)

    def validate_authored_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = payload.get("tool") or payload.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("tool manifest is required")
        return self.authored_tools.validate(manifest)

    def save_authored_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        manifest = payload.get("tool") or payload.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("tool manifest is required")
        return self.authored_tools.save(
            manifest,
            approved=bool(payload.get("approved")),
        )

    @staticmethod
    def _validate_tool_inputs(
        tool: dict[str, Any],
        arguments: dict[str, Any],
    ) -> None:
        schema = tool.get("inputSchema") or {}
        required = normalized_strings(schema.get("required"))
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ValueError(
                "Missing required authored-tool inputs: " + ", ".join(missing)
            )

    @checked_action(check_authored_command)
    def _execute_command_tool(
        self,
        tool: dict[str, Any],
        arguments: dict[str, Any],
        *,
        allow_secrets: bool,
    ) -> dict[str, Any]:
        command = dict(tool["command"])
        adapter = self.adapters.descriptor(str(command.get("adapterId") or ""))
        if not adapter.available or not adapter.executable:
            return {
                "ok": False,
                "status": "adapter_required",
                "toolId": tool["toolId"],
                "adapter": adapter.as_dict(),
            }
        rendered = render_templates(command["argvTemplate"], arguments)
        if not isinstance(rendered, list) or not all(
            isinstance(item, (str, int, float, bool)) for item in rendered
        ):
            raise ValueError("Rendered argv must contain only scalar values")
        argv = [adapter.executable, *[str(item) for item in rendered]]
        cwd = self.authored_tools.resolve_working_directory(
            command.get("workingDirectory")
        )
        environment = dict(os.environ)
        if not allow_secrets:
            secret_markers = ("TOKEN", "PASSWORD", "SECRET", "API_KEY", "APIKEY")
            environment = {
                key: value
                for key, value in environment.items()
                if not any(marker in key.upper() for marker in secret_markers)
            }
        creation_flags = (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.name == "nt"
            else 0
        )
        started = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(command.get("timeoutSeconds") or 30),
            shell=False,
            check=False,
            creationflags=creation_flags,
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        stdout = completed.stdout[:1_000_000]
        stderr = completed.stderr[:250_000]
        parser = str(command.get("outputParser") or "text").lower()
        parsed: Any = stdout
        parse_error = ""
        if parser == "json" and stdout.strip():
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
        ok = completed.returncode == 0 and not parse_error
        return {
            "ok": ok,
            "status": "completed" if ok else "failed",
            "toolId": tool["toolId"],
            "adapterId": adapter.adapter_id,
            "argvCount": len(argv),
            "exitCode": completed.returncode,
            "durationMs": round(duration_ms, 3),
            "output": parsed,
            "stderr": stderr,
            "outputTruncated": len(completed.stdout) > len(stdout),
            "stderrTruncated": len(completed.stderr) > len(stderr),
            "parseError": parse_error,
        }

    def _execute_composite_tool(
        self,
        tool: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        operations = {
            "capability.search": self.search,
            "capability.describe": lambda data: self.describe(
                str(data.get("capabilityId") or "")
            ),
            "capability.execute": self.execute_capability,
            "artifact.register": self.register_artifact,
            "artifact.lineage": self.artifact_lineage,
        }
        results: dict[str, Any] = {}
        for step in tool.get("steps") or []:
            operation = str(step.get("operation") or "")
            handler = operations.get(operation)
            if handler is None:
                return {
                    "ok": False,
                    "status": "unsupported_operation",
                    "toolId": tool["toolId"],
                    "operation": operation,
                    "completedSteps": results,
                }
            context = dict(arguments)
            context["steps"] = results
            rendered_arguments = render_templates(
                dict(step.get("arguments") or {}),
                context,
            )
            result = handler(rendered_arguments)
            step_id = str(step.get("stepId") or operation)
            results[step_id] = result
            if isinstance(result, dict) and result.get("ok") is False:
                return {
                    "ok": False,
                    "status": "step_failed",
                    "toolId": tool["toolId"],
                    "failedStepId": step_id,
                    "steps": results,
                }
        return {
            "ok": True,
            "status": "completed",
            "toolId": tool["toolId"],
            "steps": results,
        }

    @checked("authored-execute")
    def execute_authored_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_id = str(
            payload.get("toolId") or payload.get("tool_id") or ""
        ).strip().lower()
        tool = self.authored_tools.describe(tool_id)
        arguments = dict(payload.get("arguments") or {})
        self._validate_tool_inputs(tool, arguments)
        decisions = self.permissions.decide(
            normalized_strings(tool.get("permissions")),
            mode=str(payload.get("permissionMode") or "workspace_safe"),
            approved_permissions=normalized_strings(
                payload.get("approvedPermissions")
            ),
        )
        permission_summary = self.permissions.summarize(decisions)
        if permission_summary["denied"]:
            return {
                "ok": False,
                "status": "permission_denied",
                "toolId": tool_id,
                "permissionSummary": permission_summary,
            }
        if permission_summary["approvalRequired"]:
            return {
                "ok": False,
                "status": "approval_required",
                "toolId": tool_id,
                "permissionSummary": permission_summary,
            }
        if tool["kind"] == "delegated":
            delegated = dict(tool.get("delegated") or {})
            provenance = dict(tool.get("provenance") or {})
            source_type = str(delegated.get("sourceType") or "").lower()
            if source_type == "mcp" and str(provenance.get("server") or "").strip():
                self._ensure_model_tool_intelligence()
                receipt = self._model_tool_broker.call(
                    str(provenance.get("server") or ""),
                    tool=str(delegated.get("remoteToolName") or ""),
                    arguments=arguments,
                    approved=bool(payload.get("approved")),
                    approval_id=str(
                        payload.get("approvalId")
                        or payload.get("approval_id")
                        or ""
                    ),
                    mission_id=str(
                        payload.get("missionId")
                        or payload.get("mission_id")
                        or ""
                    ),
                )
                receipt["toolId"] = tool_id
                receipt["permissionSummary"] = permission_summary
                receipt["provenance"] = provenance
                authored_output = (
                    (receipt.get("result") or {}).get("structuredContent")
                    if isinstance(receipt.get("result"), dict)
                    else None
                )
                output_validation = validate_json_schema_value(
                    authored_output,
                    tool.get("outputSchema") or {},
                )
                receipt["authoredOutputValidation"] = output_validation
                if output_validation["valid"] is False:
                    receipt["ok"] = False
                    receipt["status"] = "failed"
                    receipt["error"] = (
                        "authored_invalid_output:"
                        + str(output_validation.get("error") or "")
                    )
                return receipt
            adapter = self.adapters.descriptor(
                str(delegated.get("adapterId") or "")
            )
            return {
                "ok": False,
                "status": (
                    "delegation_required" if adapter.available else "adapter_required"
                ),
                "toolId": tool_id,
                "adapter": adapter.as_dict(),
                "remoteToolName": delegated.get("remoteToolName"),
                "permissionSummary": permission_summary,
            }

        def execute() -> dict[str, Any]:
            if tool["kind"] == "command":
                approved = {
                    item.casefold()
                    for item in normalized_strings(payload.get("approvedPermissions"))
                }
                return self._execute_command_tool(
                    tool,
                    arguments,
                    allow_secrets="secret.use" in approved,
                )
            return self._execute_composite_tool(tool, arguments)

        result, receipt = self.telemetry.measure(
            f"authored_tool.execute.{tool_id}",
            execute,
            metadata={"toolId": tool_id, "kind": tool["kind"]},
        )
        output_value = (
            result.get("output")
            if tool["kind"] == "command" and isinstance(result, dict)
            else result
        )
        output_validation = validate_json_schema_value(
            output_value,
            tool.get("outputSchema") or {},
        )
        result["outputValidation"] = output_validation
        if output_validation["valid"] is False:
            result["ok"] = False
            result["status"] = "failed"
            result["error"] = (
                "authored_invalid_output:"
                + str(output_validation.get("error") or "")
            )
        result["permissionSummary"] = permission_summary
        result["telemetry"] = receipt
        return result

    def list_computer_use_twins(self) -> dict[str, Any]:
        return self.computer_use_twin.list_specs()

    def validate_computer_use_twin(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
        return self.computer_use_twin.validate_spec(dict(spec))

    def save_computer_use_twin(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else payload
        return self.computer_use_twin.save_spec(
            dict(spec),
            approved=bool(payload.get("approved")),
        )

    def run_computer_use_twin(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermissions": [
                    "process.execute",
                    "external.side_effect",
                ],
            }
        return self.computer_use_twin.run(
            str(payload.get("specId") or payload.get("spec_id") or "")
        )

    def dispatch_computer_use_twin(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "external.side_effect",
            }
        return self.computer_use_twin.dispatch(
            str(payload.get("specId") or payload.get("spec_id") or ""),
            preferred_host=str(
                payload.get("preferredHost") or payload.get("preferred_host") or ""
            ),
            assign_now=bool(payload.get("assignNow") or payload.get("assign_now")),
        )

    def verify_computer_use_change(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.computer_use_verifier.verify(payload)

    def dispatch_computer_use_verification(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.computer_use_verifier.dispatch(payload)

    def audit_security_runtime(
        self,
        *,
        delegation_ready: bool = False,
        delegation_detail: str = "",
    ) -> dict[str, Any]:
        return audit_installed_security_runtime(
            self.root,
            service=self,
            delegation_ready=delegation_ready,
            delegation_detail=delegation_detail,
        )

    @staticmethod
    def validate_security_scope(payload: dict[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else payload
        return validate_security_scope(scope)

    @staticmethod
    def build_purple_team_plan(payload: dict[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else payload
        return build_purple_team_plan(scope)

    @staticmethod
    def evaluate_security_action(payload: dict[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        return evaluate_security_action(scope, action)

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        selectors = self._artifact_selectors(payload.get("artifacts"))
        query = str(payload.get("query") or payload.get("goal") or "")

        def _search() -> dict[str, Any]:
            result = self.registry.search(
                query,
                artifacts=selectors,
                roles=normalized_strings(payload.get("roles")),
                domains=normalized_strings(payload.get("domains")),
                limit=int(payload.get("limit") or 12),
                include_unavailable=bool(payload.get("includeUnavailable", True)),
            )
            result["authoredTools"] = self.authored_tools.search(
                query,
                limit=int(payload.get("authoredToolLimit") or 8),
            )
            result["summary"]["authoredToolMatches"] = len(
                result["authoredTools"]
            )
            return result

        result, receipt = self.telemetry.measure(
            "capability.search",
            _search,
            metadata={
                "artifactCount": len(selectors),
                "catalogCapabilities": len(self.registry.capabilities),
            },
        )
        result["telemetry"] = receipt
        return result

    def describe(self, capability_id: str) -> dict[str, Any]:
        return self.registry.describe(capability_id)

    def validate_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        pack_payload = payload.get("pack") if isinstance(payload.get("pack"), dict) else payload
        pack = CapabilityPack.from_payload(pack_payload)
        duplicate = pack.pack_id in self.registry.packs
        source = str(self.registry.pack_sources.get(pack.pack_id) or "")
        custom_dir = (
            self.root / ".agent_control" / "capability_packs"
        ).resolve()
        source_is_custom = False
        if source:
            try:
                source_is_custom = Path(source).resolve().parent == custom_dir
            except OSError:
                source_is_custom = False
        replace_existing = bool(payload.get("replaceExisting"))
        existing_ids = set(self.registry.capabilities)
        if duplicate and source_is_custom:
            existing_ids.difference_update(
                item.capability_id
                for item in self.registry.packs[pack.pack_id].capabilities
            )
        capability_collisions = sorted(
            existing_ids.intersection(
                item.capability_id for item in pack.capabilities
            )
        )
        can_replace = duplicate and source_is_custom and replace_existing
        errors: list[str] = []
        if duplicate and not can_replace:
            errors.append(
                (
                    f"Capability pack {pack.pack_id} is built in and cannot be replaced."
                    if not source_is_custom
                    else (
                        f"Capability pack {pack.pack_id} already exists. "
                        "Set replaceExisting=true to update the custom pack."
                    )
                )
            )
        if capability_collisions:
            errors.append(
                "Capability identifiers already exist: "
                + ", ".join(capability_collisions)
            )
        return {
            "schema": "neyvia.capability_pack_validation.v1",
            "valid": not errors,
            "pack": pack.as_dict(),
            "duplicatePackId": duplicate,
            "replaceExisting": replace_existing,
            "sourceIsCustom": source_is_custom,
            "capabilityCollisions": capability_collisions,
            "errors": errors,
        }

    @checked_action(check_pack_save)
    def save_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("approved")):
            return {
                "ok": False,
                "status": "approval_required",
                "reason": "Saving a capability pack changes workspace configuration.",
                "requiredPermission": "workspace.write",
            }
        validation = self.validate_pack(payload)
        if not validation["valid"]:
            return {
                "ok": False,
                "status": "invalid",
                **validation,
            }
        pack = CapabilityPack.from_payload(
            payload.get("pack") if isinstance(payload.get("pack"), dict) else payload
        )
        target_dir = self.root / ".agent_control" / "capability_packs"
        file_name = pack.pack_id.replace(".", "_").replace("-", "_") + ".json"
        target = target_dir / file_name
        _atomic_json(target, pack.as_dict())
        self.registry.reload()
        return {
            "ok": True,
            "status": "saved",
            "packId": pack.pack_id,
            "path": str(target),
            "catalogHash": self.registry.catalog_hash,
            "savedAt": utc_now(),
        }

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        selectors = self._artifact_selectors(payload.get("artifacts"))

        def _plan() -> dict[str, Any]:
            return self.planner.plan(
                str(payload.get("goal") or payload.get("query") or ""),
                artifacts=selectors,
                roles=normalized_strings(payload.get("roles")),
                domains=normalized_strings(payload.get("domains")),
                experience=str(payload.get("experience") or "standard"),
                permission_mode=str(
                    payload.get("permissionMode")
                    or payload.get("permission_mode")
                    or "workspace_safe"
                ),
                approved_permissions=normalized_strings(
                    payload.get("approvedPermissions")
                    or payload.get("approved_permissions")
                ),
                max_capabilities=int(payload.get("maxCapabilities") or 4),
            )

        result, receipt = self.telemetry.measure(
            "capability.plan",
            _plan,
            metadata={"artifactCount": len(selectors)},
        )
        result["telemetry"] = receipt
        self._write_plan(result)
        return result

    def _plan_path(self, plan_id: str) -> Path:
        normalized = str(plan_id or "").strip()
        if not normalized.startswith("capplan_") or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in normalized
        ):
            raise ValueError("Invalid planId")
        return self.plan_dir / f"{normalized}.json"

    def _write_plan(self, plan: dict[str, Any]) -> None:
        if plan.get("schema") != CAPABILITY_PLAN_SCHEMA:
            raise ValueError("Invalid capability plan schema")
        _atomic_json(self._plan_path(str(plan.get("planId") or "")), plan)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        path = self._plan_path(plan_id)
        if not path.exists():
            raise KeyError(f"Unknown capability plan: {plan_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Capability plan could not be read: {plan_id}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != CAPABILITY_PLAN_SCHEMA:
            raise RuntimeError(f"Invalid capability plan payload: {plan_id}")
        return payload

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_data = payload.get("plan")
        if isinstance(plan_data, dict):
            plan = dict(plan_data)
            self._write_plan(plan)
        else:
            plan = self.get_plan(
                str(payload.get("planId") or payload.get("plan_id") or "")
            )
        approved_permissions = normalized_strings(
            payload.get("approvedPermissions")
            or payload.get("approved_permissions")
        )
        permissions = sorted(
            {
                permission
                for item in (plan.get("capabilities") or [])
                for permission in (item.get("requiredPermissions") or [])
            }
        )
        decisions = self.permissions.decide(
            permissions,
            mode=str(plan.get("permissionMode") or "workspace_safe"),
            approved_permissions=approved_permissions,
        )
        summary = self.permissions.summarize(decisions)
        return self.runs.create(plan, permission_summary=summary)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.runs.get(run_id)

    def record_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = PreviewEvent(
            run_id=str(payload.get("runId") or payload.get("run_id") or "").strip(),
            phase=str(payload.get("phase") or "live").strip().lower(),
            kind=str(payload.get("kind") or "progress").strip().lower(),
            summary=str(payload.get("summary") or ""),
            payload=dict(payload.get("payload") or {}),
            artifact_ids=tuple(
                normalized_strings(
                    payload.get("artifactIds") or payload.get("artifact_ids")
                )
            ),
        )
        return self.runs.append_preview(event)

    def finish_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runs.finish(
            str(payload.get("runId") or payload.get("run_id") or ""),
            status=str(payload.get("status") or "completed"),
            summary=str(payload.get("summary") or ""),
            payload=dict(payload.get("payload") or {}),
            artifact_ids=normalized_strings(
                payload.get("artifactIds") or payload.get("artifact_ids")
            ),
        )

    def register_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.artifacts.register(
            path=payload.get("path"),
            artifact_id=str(
                payload.get("artifactId") or payload.get("artifact_id") or ""
            ),
            name=str(payload.get("name") or ""),
            media_type=str(
                payload.get("mediaType")
                or payload.get("media_type")
                or payload.get("mimeType")
                or ""
            ),
            kind=str(payload.get("kind") or "file"),
            metadata=dict(payload.get("metadata") or {}),
            source=str(payload.get("source") or "workspace"),
        )

    def relate_artifacts(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.artifacts.relate(
            str(
                payload.get("parentArtifactId")
                or payload.get("parent_artifact_id")
                or ""
            ),
            str(
                payload.get("childArtifactId")
                or payload.get("child_artifact_id")
                or ""
            ),
            str(payload.get("relation") or "derived_from"),
            capability_id=str(
                payload.get("capabilityId") or payload.get("capability_id") or ""
            ),
            run_id=str(payload.get("runId") or payload.get("run_id") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    def artifact_lineage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.artifacts.lineage(
            str(payload.get("artifactId") or payload.get("artifact_id") or ""),
            direction=str(payload.get("direction") or "both"),
            max_depth=int(payload.get("maxDepth") or payload.get("max_depth") or 8),
        )

    def search_tool_suite(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tool_manifests.search(
            str(payload.get("query") or ""),
            limit=int(payload.get("limit") or 12),
            agent_ready_only=bool(payload.get("agentReadyOnly", False)),
            execution_ready_only=bool(
                payload.get("executionReadyOnly", False)
            ),
        )

    def describe_tool_suite(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.tool_manifests.describe(
            str(payload.get("toolId") or payload.get("tool_id") or "")
        )

    @_proofs_b_checked("registration")
    def _register_adapter_artifacts(
        self,
        result: dict[str, Any],
        *,
        capability_id: str,
        run_id: str,
        adapter_id: str,
    ) -> dict[str, Any]:
        adapter_result = result.get("result")
        declarations = (
            adapter_result.get("artifacts")
            if isinstance(adapter_result, dict)
            else None
        )
        if not isinstance(declarations, list):
            return {"artifacts": [], "relations": []}
        registered: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for declaration in declarations[:100]:
            if not isinstance(declaration, dict):
                continue
            path_text = str(declaration.get("path") or "").strip()
            if not path_text:
                continue
            path = Path(path_text)
            if not path.is_absolute():
                path = self.root / path
            resolved = path.resolve()
            if not resolved.is_file():
                continue
            role = str(declaration.get("role") or "artifact").strip().lower()
            declared_sha256 = str(
                declaration.get("sha256") or ""
            ).strip().lower()
            if declared_sha256:
                if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256):
                    raise ValueError(
                        f"Adapter artifact {path_text} has an invalid SHA-256"
                    )
                actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
                if actual_sha256 != declared_sha256:
                    raise ValueError(
                        f"Adapter artifact hash mismatch for {path_text}"
                    )
            derived_from = str(
                declaration.get("derivedFrom") or ""
            ).strip().lower()
            if derived_from and not re.fullmatch(r"[0-9a-f]{64}", derived_from):
                raise ValueError(
                    f"Adapter artifact {path_text} has invalid derivedFrom lineage"
                )
            if role == "git-reference-receipt":
                try:
                    receipt_payload = json.loads(
                        resolved.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "Git reference receipt must be valid UTF-8 JSON"
                    ) from exc
                receipt_lineage = receipt_payload.get("lineage") or {}
                receipt_output = receipt_lineage.get("output") or {}
                if (
                    not derived_from
                    or str(receipt_output.get("sha256") or "").strip().lower()
                    != derived_from
                ):
                    raise ValueError(
                        "Git reference receipt derivedFrom does not match its lineage"
                    )
            item = self.artifacts.register(
                path=resolved,
                kind=str(declaration.get("kind") or "file"),
                source=f"capability:{capability_id}",
                metadata={
                    "role": role,
                    "adapterId": adapter_id,
                    "capabilityId": capability_id,
                    "runId": run_id,
                    "verifiedBy": str(declaration.get("verifiedBy") or ""),
                    "declaredSha256": declared_sha256,
                    "derivedFrom": derived_from,
                },
            )
            registered.append((item, declaration))
        sources = [
            item
            for item, declaration in registered
            if str(declaration.get("role") or "").strip().lower() == "source"
        ]
        relations: list[dict[str, Any]] = []
        if sources:
            parent = sources[0]
            for child, declaration in registered:
                if child["artifactId"] == parent["artifactId"]:
                    continue
                relation = str(
                    declaration.get("relation") or "derived_from"
                ).strip().lower()
                relations.append(
                    self.artifacts.relate(
                        parent["artifactId"],
                        child["artifactId"],
                        relation,
                        capability_id=capability_id,
                        run_id=run_id,
                        metadata={"adapterId": adapter_id},
                    )
                )
        return {
            "artifacts": [item for item, _declaration in registered],
            "relations": relations,
        }

    @checked_action(check_operation)
    @_proofs_b_checked("sync-discovery")
    def execute_tool_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_id = str(
            payload.get("toolId") or payload.get("tool_id") or ""
        ).strip().lower()
        operation_id = str(
            payload.get("operationId") or payload.get("operation_id") or ""
        ).strip().lower()
        tool = self.tool_manifests.tools.get(tool_id)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_id}")
        operation = next(
            (
                item
                for item in tool.operations
                if item.operation_id == operation_id
            ),
            None,
        )
        if operation is None:
            raise KeyError(
                f"Tool {tool_id} does not expose operation {operation_id}"
            )
        if not tool.agent_ready:
            return {
                "ok": False,
                "status": "tool_not_ready",
                "toolId": tool_id,
                "operationId": operation_id,
                "tool": tool.as_dict(include_operations=False),
            }
        arguments = dict(payload.get("arguments") or {})
        input_validation = validate_json_schema_value(
            arguments,
            operation.input_schema,
        )
        if input_validation.get("valid") is not True:
            return {
                "ok": False,
                "status": "invalid_arguments",
                "toolId": tool_id,
                "operationId": operation_id,
                "inputValidation": input_validation,
            }
        decisions = self.permissions.decide(
            list(operation.permissions),
            mode=str(payload.get("permissionMode") or "workspace_safe"),
            approved_permissions=normalized_strings(
                payload.get("approvedPermissions")
            ),
        )
        permission_summary = self.permissions.summarize(decisions)
        if permission_summary["denied"]:
            return {
                "ok": False,
                "status": "permission_denied",
                "toolId": tool_id,
                "operationId": operation_id,
                "permissionSummary": permission_summary,
            }
        durable_approval = (
            operation.metadata.get("externalApprovalReceipt") is True
            and isinstance(arguments.get("approvalReceipt"), dict)
        )
        if permission_summary["approvalRequired"] and not durable_approval:
            return {
                "ok": False,
                "status": "approval_required",
                "toolId": tool_id,
                "operationId": operation_id,
                "permissionSummary": permission_summary,
            }
        if durable_approval:
            permission_summary["durableApprovalPendingValidation"] = True
        adapter = next(
            (
                self.adapters.descriptor(adapter_id)
                for adapter_id in tool.adapters
                if self.adapters.descriptor(adapter_id).supports_execution
            ),
            None,
        )
        if adapter is None:
            return {
                "ok": False,
                "status": "adapter_required",
                "toolId": tool_id,
                "operationId": operation_id,
                "adapters": [
                    self.adapters.descriptor(adapter_id).as_dict()
                    for adapter_id in tool.adapters
                ],
            }
        adapter_operation = str(
            operation.metadata.get("adapterOperation")
            or operation.operation_id.rsplit(".", 1)[-1].replace("-", "_")
        )
        adapter_arguments = {**arguments, "operation": adapter_operation}

        def _execute() -> dict[str, Any]:
            return self.adapters.execute(
                adapter.adapter_id,
                adapter_arguments,
            )

        execution, telemetry = self.telemetry.measure(
            f"tool.execute.{tool_id}.{operation_id}",
            _execute,
            metadata={
                "toolId": tool_id,
                "operationId": operation_id,
                "adapterId": adapter.adapter_id,
            },
        )
        adapter_output = execution.get("result")
        output_validation = validate_json_schema_value(
            adapter_output,
            operation.output_schema,
        )
        if execution.get("ok") and output_validation.get("valid") is not True:
            execution["ok"] = False
            execution["status"] = "output_schema_invalid"
            execution["summary"] = (
                "The adapter completed, but its output did not satisfy the "
                "declared operation contract."
            )
        capability_id = str(
            payload.get("capabilityId")
            or operation.metadata.get("capabilityId")
            or ""
        ).strip().lower()
        if capability_id and capability_id not in tool.capabilities:
            raise ValueError(
                f"Tool {tool_id} is not mapped to capability {capability_id}"
            )
        if not capability_id:
            capability_id = (
                tool.capabilities[0]
                if tool.capabilities
                else f"tool.{operation_id}"
            )
        run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
        artifact_receipt = self._register_adapter_artifacts(
            execution,
            capability_id=capability_id,
            run_id=run_id,
            adapter_id=adapter.adapter_id,
        )
        execution.update(
            {
                "toolId": tool_id,
                "operationId": operation_id,
                "capabilityId": capability_id,
                "adapterId": adapter.adapter_id,
                "permissionSummary": permission_summary,
                "inputValidation": input_validation,
                "outputValidation": output_validation,
                "telemetry": telemetry,
                "toolReceipt": {
                    "toolManifestHash": canonical_hash(
                        tool.as_dict(include_operations=True)
                    ),
                    "packageSha256": tool.package_sha256,
                    "selectedVersion": tool.selected_version,
                    "verifier": operation.verifier,
                },
            }
        )
        if artifact_receipt["artifacts"]:
            execution["artifactReceipt"] = artifact_receipt
        return execution

    @checked_action(check_capability_execution)
    def execute_capability(self, payload: dict[str, Any]) -> dict[str, Any]:
        capability_id = str(
            payload.get("capabilityId") or payload.get("capability_id") or ""
        ).strip().lower()
        capability = self.registry.describe(capability_id)
        decisions = self.permissions.decide(
            list(capability.get("requiredPermissions") or []),
            mode=str(payload.get("permissionMode") or "workspace_safe"),
            approved_permissions=normalized_strings(
                payload.get("approvedPermissions")
            ),
        )
        permission_summary = self.permissions.summarize(decisions)
        if permission_summary["denied"]:
            return {
                "ok": False,
                "status": "permission_denied",
                "capabilityId": capability_id,
                "permissionSummary": permission_summary,
            }
        if permission_summary["approvalRequired"]:
            return {
                "ok": False,
                "status": "approval_required",
                "capabilityId": capability_id,
                "permissionSummary": permission_summary,
            }
        if not capability["available"]:
            return {
                "ok": False,
                "status": "adapter_required",
                "capabilityId": capability_id,
                "adapter": capability["adapterDescriptor"],
                "permissionSummary": permission_summary,
            }
        adapter = capability["adapterDescriptor"]
        if not adapter["supportsExecution"]:
            return {
                "ok": False,
                "status": "delegation_required",
                "capabilityId": capability_id,
                "adapter": adapter,
                "permissionSummary": permission_summary,
                "handoff": {
                    "runtime": "neyvia.stage_scheduler",
                    "goal": str(payload.get("goal") or capability["description"]),
                    "capabilityId": capability_id,
                    "arguments": dict(payload.get("arguments") or {}),
                },
            }

        def _execute() -> dict[str, Any]:
            return self.adapters.execute(
                str(adapter["adapterId"]),
                dict(payload.get("arguments") or {}),
            )

        result, receipt = self.telemetry.measure(
            f"capability.execute.{capability_id}",
            _execute,
            metadata={"adapterId": adapter["adapterId"]},
        )
        result["capabilityId"] = capability_id
        result["permissionSummary"] = permission_summary
        result["telemetry"] = receipt
        run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
        artifact_receipt = self._register_adapter_artifacts(
            result,
            capability_id=capability_id,
            run_id=run_id,
            adapter_id=str(adapter["adapterId"]),
        )
        if artifact_receipt["artifacts"]:
            result["artifactReceipt"] = artifact_receipt
        if run_id:
            self.record_preview(
                {
                    "runId": run_id,
                    "phase": "live",
                    "kind": "capability_execution",
                    "summary": result.get("summary") or capability["name"],
                    "payload": {
                        "capabilityId": capability_id,
                        "adapterId": adapter["adapterId"],
                        "status": result.get("status"),
                        "durationMs": result.get("durationMs"),
                    },
                }
            )
        return result


def register_with_progressive_surface(surface: Any, service: CapabilityService) -> None:
    """Expose capability OS operations without dumping catalog schemas."""

    from .progressive_tools import ProgressiveToolSpec

    tools: list[tuple[ProgressiveToolSpec, Any]] = [
        (
            ProgressiveToolSpec(
                name="app.surface.catalog",
                title="List Workspace Application Surfaces",
                description="List validated optional desktop and web surfaces declared by workspace-built apps, including truthful target availability.",
                category="application-surface",
                aliases=("workspace app", "desktop app", "web app", "app surface"),
                tags=("application", "surface", "desktop", "web", "workspace"),
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                permissions=("workspace.read",),
            ),
            lambda _payload: service.application_surface_catalog(),
        ),
        (
            ProgressiveToolSpec(
                name="app.surface.status",
                title="Inspect Application Surface Status",
                description="Validate one app surface and report declared, lifecycle, build-artifact, and launch-readiness state without starting it.",
                category="application-surface",
                aliases=("app status", "surface readiness", "build target"),
                tags=("application", "lifecycle", "status", "proof"),
                input_schema={
                    "type": "object",
                    "required": ["manifest"],
                    "properties": {
                        "manifest": {"type": "object"},
                        "targetId": {"type": "string"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                permissions=("workspace.read",),
            ),
            service.application_surface_status,
        ),
        (
            ProgressiveToolSpec(
                name="app.surface.launch.plan",
                title="Plan Application Surface Launch",
                description="Create a permission-bound launch plan for a declared desktop or web target. This tool never builds, installs, or launches.",
                category="application-surface",
                aliases=("launch app", "open workspace app", "start desktop surface"),
                tags=("application", "launch", "permissions", "plan"),
                input_schema={
                    "type": "object",
                    "required": ["manifest", "targetId"],
                    "properties": {
                        "manifest": {"type": "object"},
                        "targetId": {"type": "string"},
                        "permissionMode": {"type": "string"},
                        "approvalId": {"type": "string"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                permissions=("workspace.read",),
            ),
            service.plan_application_surface_launch,
        ),
        (
            ProgressiveToolSpec(
                name="app.surface.observe",
                title="Read Application Surface Logs and Proof",
                description="Read bounded workspace-scoped log tails and proof hashes declared by an application surface.",
                category="application-surface",
                aliases=("app logs", "app proof", "surface evidence"),
                tags=("application", "logs", "proof", "observability"),
                input_schema={
                    "type": "object",
                    "required": ["manifest"],
                    "properties": {
                        "manifest": {"type": "object"},
                        "maxLogLines": {"type": "integer"},
                        "maxProofFiles": {"type": "integer"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                permissions=("workspace.read", "artifact.read"),
            ),
            service.observe_application_surface,
        ),
        (
            ProgressiveToolSpec(
                name="tool.suite.search",
                title="Search Managed Tool Suite",
                description="Search pinned external tools with truthful contract, execution, and production readiness without loading operation schemas.",
                category="capability-os",
                aliases=("external tools", "installed tools", "tool capabilities"),
                tags=("tools", "versions", "features", "discovery"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                        "agentReadyOnly": {"type": "boolean"},
                        "executionReadyOnly": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
            ),
            service.search_tool_suite,
        ),
        (
            ProgressiveToolSpec(
                name="tool.suite.describe",
                title="Describe Managed Tool",
                description="Load one pinned tool's source, version, license, health, features, typed operations, permissions, limits, and verifier contracts.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["toolId"],
                    "properties": {"toolId": {"type": "string"}},
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
            ),
            service.describe_tool_suite,
        ),
        (
            ProgressiveToolSpec(
                name="tool.suite.execute",
                title="Execute Managed Tool Operation",
                description="Validate and run one typed operation from a verified managed tool, enforcing operation permissions, output schema, artifact lineage, telemetry, and a versioned receipt.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["toolId", "operationId", "arguments"],
                    "properties": {
                        "toolId": {"type": "string"},
                        "operationId": {"type": "string"},
                        "arguments": {"type": "object"},
                        "capabilityId": {"type": "string"},
                        "runId": {"type": "string"},
                        "permissionMode": {"type": "string"},
                        "approvedPermissions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": False},
            ),
            service.execute_tool_operation,
        ),
        (
            ProgressiveToolSpec(
                name="capability.search",
                description="Search installed and declared capability packs without loading full schemas.",
                category="capability-os",
                aliases=("tools.search", "domain.search"),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "domains": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.search,
        ),
        (
            ProgressiveToolSpec(
                name="capability.describe",
                description="Describe one capability, adapter, permissions, previews, and verifier.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["capabilityId"],
                    "properties": {"capabilityId": {"type": "string"}},
                },
                annotations={"readOnlyHint": True},
            ),
            lambda payload: service.describe(str(payload.get("capabilityId") or "")),
        ),
        (
            ProgressiveToolSpec(
                name="capability.plan",
                description="Compile a goal and artifacts into a permissioned capability stage graph.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["goal"],
                    "properties": {
                        "goal": {"type": "string"},
                        "artifacts": {"type": "array"},
                        "experience": {"type": "string"},
                        "permissionMode": {"type": "string"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.plan,
        ),
        (
            ProgressiveToolSpec(
                name="capability.ui.contract",
                description="Read the stable backend states and commands available to the visual UI.",
                category="capability-os",
                input_schema={"type": "object", "properties": {}},
                annotations={"readOnlyHint": True},
            ),
            lambda _payload: service.ui_contract(),
        ),
        (
            ProgressiveToolSpec(
                name="capability.benchmark",
                description="Measure warm capability routing latency and emit a retained performance receipt.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}},
                        "iterations": {"type": "integer"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.benchmark,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.compile",
                title="Compile Model Tool Belt",
                description="Select a small task-specific belt of native, authored, and brokered tools with schemas, provenance, routing, and context-efficiency metrics.",
                category="model-tool-intelligence",
                aliases=("tool belt", "model fingers", "tool routing"),
                tags=("model", "tools", "routing", "discovery"),
                input_schema={
                    "type": "object",
                    "required": ["task"],
                    "properties": {
                        "task": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "artifactTypes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "limit": {"type": "integer"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.compile",
                    "trustLevel": "builtin",
                },
            ),
            service.compile_model_tool_belt,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.openai.compile",
                title="Compile OpenAI Tool Search Payload",
                description="Compile the selected tool belt into OpenAI Responses namespaces, deferred functions, strict schemas, and an immutable provider-call map.",
                category="model-tool-intelligence",
                aliases=("openai tool search", "responses tools"),
                tags=("openai", "tools", "deferred", "strict"),
                input_schema={
                    "type": "object",
                    "required": ["task"],
                    "properties": {
                        "task": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "artifactTypes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "limit": {"type": "integer"},
                        "deferLoading": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True, "idempotentHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.openai.compile",
                    "trustLevel": "builtin",
                },
            ),
            service.compile_openai_tool_belt,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.benchmark",
                title="Benchmark Model Tool Routing",
                description="Measure top-1, top-3, and top-k selection accuracy, routing latency, and model-context reduction on representative N-E-Y-V-I-A workflows.",
                category="model-tool-intelligence",
                aliases=("tool routing eval", "tool efficiency benchmark"),
                tags=("model", "tools", "benchmark", "latency", "accuracy"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "cases": {"type": "array", "items": {"type": "object"}},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.benchmark",
                    "trustLevel": "builtin",
                },
            ),
            service.benchmark_model_tool_routing,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.feedback",
                title="Read Model Tool Feedback",
                description="Read transparent tool success, schema-error, correction, latency, and reliability aggregates.",
                category="model-tool-intelligence",
                aliases=("tool reliability", "tool outcomes"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "aggregateLimit": {"type": "integer"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.feedback",
                    "trustLevel": "builtin",
                },
            ),
            service.model_tool_feedback,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.feedback.record",
                title="Record Model Tool Outcome",
                description="Append a model-tool outcome receipt without changing permissions or silently self-training routing policy.",
                category="model-tool-intelligence",
                input_schema={
                    "type": "object",
                    "required": ["callTarget", "ok", "approved"],
                    "properties": {
                        "callTarget": {"type": "string"},
                        "ok": {"type": "boolean"},
                        "approved": {"type": "boolean"},
                        "status": {"type": "string"},
                        "durationMs": {"type": "number"},
                        "argumentValid": {"type": "boolean"},
                        "fallbackUsed": {"type": "boolean"},
                        "userCorrected": {"type": "boolean"},
                        "evidenceCount": {"type": "integer"},
                        "route": {"type": "string"},
                        "errorClass": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": False, "idempotentHint": False},
                permissions=("artifact.write",),
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.feedback.record",
                    "trustLevel": "builtin",
                },
            ),
            service.record_model_tool_feedback,
        ),
        (
            ProgressiveToolSpec(
                name="model.tools.run",
                title="Run Bounded Model Tool Plan",
                description="Run an explicit model-produced tool plan with hard call, retry, time, context, approval, stagnation, and evidence boundaries.",
                category="model-tool-intelligence",
                aliases=("plan act verify", "bounded tool loop"),
                tags=("model", "execution", "verify", "receipts"),
                input_schema={
                    "type": "object",
                    "required": ["goal", "calls"],
                    "properties": {
                        "goal": {"type": "string"},
                        "acceptance": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "calls": {"type": "array", "items": {"type": "object"}},
                        "maxCalls": {"type": "integer"},
                        "maxRetries": {"type": "integer"},
                        "maxWallTimeMs": {"type": "integer"},
                        "maxContextBytes": {"type": "integer"},
                        "minimumEvidence": {"type": "integer"},
                        "approved": {"type": "boolean"},
                        "approvalId": {"type": "string"},
                        "missionId": {"type": "string"},
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": False, "requiresApproval": True},
                permissions=("artifact.write",),
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "model.tools.run",
                    "trustLevel": "builtin",
                },
            ),
            service.run_model_tool_plan,
        ),
        (
            ProgressiveToolSpec(
                name="capability.execute",
                description="Execute a capability only when its real adapter and permissions are available.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["capabilityId"],
                    "properties": {
                        "capabilityId": {"type": "string"},
                        "arguments": {"type": "object"},
                        "approvedPermissions": {"type": "array"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.execute_capability,
        ),
        (
            ProgressiveToolSpec(
                name="capability.pack.validate",
                description="Validate a user-authored domain capability pack without saving it.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["pack"],
                    "properties": {"pack": {"type": "object"}},
                },
                annotations={"readOnlyHint": True},
            ),
            service.validate_pack,
        ),
        (
            ProgressiveToolSpec(
                name="capability.pack.save",
                description="Save a validated custom capability pack after explicit approval.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["pack", "approved"],
                    "properties": {
                        "pack": {"type": "object"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.save_pack,
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.search",
                description="Search workspace-authored N-E-Y-V-I-A tools without loading their schemas.",
                category="tool-authoring",
                aliases=("custom.tool.search", "tool.factory.search"),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.search_authored_tools,
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.describe",
                description="Describe one authored tool, its schema, permissions, and real adapter state.",
                category="tool-authoring",
                input_schema={
                    "type": "object",
                    "required": ["toolId"],
                    "properties": {"toolId": {"type": "string"}},
                },
                annotations={"readOnlyHint": True},
            ),
            lambda payload: service.describe_authored_tool(
                str(payload.get("toolId") or "")
            ),
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.adapt",
                description="Adapt an MCP, OpenAI-function, or argv command definition into a reviewable native draft.",
                category="tool-authoring",
                input_schema={
                    "type": "object",
                    "required": ["sourceType", "source"],
                    "properties": {
                        "sourceType": {"type": "string"},
                        "source": {"type": "object"},
                        "adapterId": {"type": "string"},
                        "toolId": {"type": "string"},
                        "server": {"type": "string"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "sourceMetadata": {"type": "object"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.adapt_authored_tool,
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.validate",
                description="Validate a native authored-tool manifest without saving or executing it.",
                category="tool-authoring",
                input_schema={
                    "type": "object",
                    "required": ["tool"],
                    "properties": {"tool": {"type": "object"}},
                },
                annotations={"readOnlyHint": True},
            ),
            service.validate_authored_tool,
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.save",
                description="Persist a validated workspace tool after explicit approval.",
                category="tool-authoring",
                input_schema={
                    "type": "object",
                    "required": ["tool", "approved"],
                    "properties": {
                        "tool": {"type": "object"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.save_authored_tool,
        ),
        (
            ProgressiveToolSpec(
                name="tool.author.execute",
                description="Execute an authored tool with declared permissions, no shell interpolation, and retained telemetry.",
                category="tool-authoring",
                input_schema={
                    "type": "object",
                    "required": ["toolId"],
                    "properties": {
                        "toolId": {"type": "string"},
                        "arguments": {"type": "object"},
                        "approvedPermissions": {"type": "array"},
                        "approved": {"type": "boolean"},
                        "approvalId": {"type": "string"},
                        "missionId": {"type": "string"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.execute_authored_tool,
        ),
        (
            ProgressiveToolSpec(
                name="security.runtime.audit",
                title="Audit Security Runtime Coverage",
                description="Read real installed red/blue-team coverage for scope, bounded probe, detection, remediation, and independent retest without executing a probe.",
                category="security-runtime",
                aliases=("purple.team.audit", "security.tools.audit"),
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "security.runtime.audit",
                    "trustLevel": "builtin",
                },
            ),
            lambda _payload: service.audit_security_runtime(),
        ),
        (
            ProgressiveToolSpec(
                name="security.scope.validate",
                title="Validate Authorized Security Scope",
                description="Validate target boundaries, authorization owner, action classes, attempt budget, and high-risk allowances before security work.",
                category="security-runtime",
                aliases=("purple.team.scope", "red.blue.scope"),
                input_schema={
                    "type": "object",
                    "required": ["scope"],
                    "properties": {"scope": SECURITY_SCOPE_TOOL_SCHEMA},
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "security.scope.validate",
                    "trustLevel": "builtin",
                },
            ),
            service.validate_security_scope,
        ),
        (
            ProgressiveToolSpec(
                name="security.purple.plan",
                title="Build Purple-Team Plan",
                description="Build a five-phase red/blue plan with explicit proof requirements and stop conditions from a validated scope.",
                category="security-runtime",
                aliases=("purple.team.plan", "red.blue.plan"),
                input_schema={
                    "type": "object",
                    "required": ["scope"],
                    "properties": {"scope": SECURITY_SCOPE_TOOL_SCHEMA},
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "security.purple.plan",
                    "trustLevel": "builtin",
                },
            ),
            service.build_purple_team_plan,
        ),
        (
            ProgressiveToolSpec(
                name="security.action.evaluate",
                title="Evaluate Security Action",
                description="Fail closed when a proposed action exceeds authorized targets, action classes, high-risk allowances, or action-time approval.",
                category="security-runtime",
                aliases=("purple.team.action.check", "security.guard"),
                input_schema={
                    "type": "object",
                    "required": ["scope", "action"],
                    "properties": {
                        "scope": SECURITY_SCOPE_TOOL_SCHEMA,
                        "action": {
                            "type": "object",
                            "required": ["actionClass"],
                            "properties": {
                                "target": {"type": "string"},
                                "actionClass": {"type": "string"},
                                "active": {"type": "boolean"},
                                "externalSideEffect": {"type": "boolean"},
                                "approvalId": {"type": "string"},
                            },
                        },
                    },
                },
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
                provenance={
                    "sourceKind": "native",
                    "provider": "neyvia",
                    "originalName": "security.action.evaluate",
                    "trustLevel": "builtin",
                },
            ),
            service.evaluate_security_action,
        ),
        (
            ProgressiveToolSpec(
                name="computer_use.verify",
                description="Verify an app change with structured UI observations and retained speed, accuracy, determinism, and compact-context evidence.",
                category="computer-use",
                aliases=("cu.verify", "app.change.verify"),
                input_schema={
                    "type": "object",
                    "required": ["approved"],
                    "properties": {
                        "changeId": {"type": "string"},
                        "changeLabel": {"type": "string"},
                        "baseUrl": {"type": "string"},
                        "flows": {"type": "array"},
                        "repetitions": {"type": "integer"},
                        "baselineReceiptPath": {"type": "string"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.verify_computer_use_change,
        ),
        (
            ProgressiveToolSpec(
                name="computer_use.dispatch_verification",
                description="Dispatch the same structured Computer Use change verification to another isolated browser-capable worker.",
                category="computer-use",
                aliases=("cu.dispatch",),
                input_schema={
                    "type": "object",
                    "required": ["approved"],
                    "properties": {
                        "changeId": {"type": "string"},
                        "baseUrl": {"type": "string"},
                        "flows": {"type": "array"},
                        "preferredHost": {"type": "string"},
                        "assignNow": {"type": "boolean"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.dispatch_computer_use_verification,
        ),
        (
            ProgressiveToolSpec(
                name="cu.twin.validate",
                description="Validate an isolated structured Computer Use comparison spec.",
                category="computer-use-twin",
                input_schema={
                    "type": "object",
                    "properties": {"spec": {"type": "object"}},
                },
                annotations={"readOnlyHint": True},
            ),
            service.validate_computer_use_twin,
        ),
        (
            ProgressiveToolSpec(
                name="cu.twin.save",
                description="Save a Computer Use Twin spec after explicit approval.",
                category="computer-use-twin",
                input_schema={
                    "type": "object",
                    "required": ["spec", "approved"],
                    "properties": {
                        "spec": {"type": "object"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.save_computer_use_twin,
        ),
        (
            ProgressiveToolSpec(
                name="cu.twin.run",
                description="Run live structured CU flows and compare accuracy, determinism, latency, and compact context with a baseline.",
                category="computer-use-twin",
                input_schema={
                    "type": "object",
                    "required": ["specId", "approved"],
                    "properties": {
                        "specId": {"type": "string"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.run_computer_use_twin,
        ),
        (
            ProgressiveToolSpec(
                name="cu.twin.dispatch",
                description="Queue a Computer Use Twin on another isolated browser-capable worker or CPU.",
                category="computer-use-twin",
                input_schema={
                    "type": "object",
                    "required": ["specId", "approved"],
                    "properties": {
                        "specId": {"type": "string"},
                        "preferredHost": {"type": "string"},
                        "assignNow": {"type": "boolean"},
                        "approved": {"type": "boolean"},
                    },
                },
                annotations={"requiresApproval": True, "readOnlyHint": False},
            ),
            service.dispatch_computer_use_twin,
        ),
        (
            ProgressiveToolSpec(
                name="artifact.register",
                description="Register a real artifact path and content hash in the lineage graph.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
                annotations={"readOnlyHint": False},
            ),
            service.register_artifact,
        ),
        (
            ProgressiveToolSpec(
                name="artifact.lineage",
                description="Read source-to-result lineage for one artifact.",
                category="capability-os",
                input_schema={
                    "type": "object",
                    "required": ["artifactId"],
                    "properties": {
                        "artifactId": {"type": "string"},
                        "direction": {"type": "string"},
                    },
                },
                annotations={"readOnlyHint": True},
            ),
            service.artifact_lineage,
        ),
    ]
    for spec, handler in tools:
        surface.register(spec, handler)
