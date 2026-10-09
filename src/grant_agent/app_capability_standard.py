from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import (
    AppActionHook,
    AppBridgeHandshake,
    AppCapabilityManifest,
    AppContextSurface,
    AppTaskDescriptor,
    CapabilityGrant,
    ConnectedAppSession,
    utc_now_iso,
)
from .application_surface import validate_application_surface_manifest
from .proofs_a_capabilities import checked_action
from .proofs_a_app_standard import (
    checked_state_save, check_snapshot, check_storage_plan,
    check_storage_session, check_cloud_plan,
)

SCHEMA_VERSION = "neyvia.app-capability/v1"
BRIDGE_VERSION = "neyvia.bridge/v1"
LEGACY_SCHEMA_VERSIONS = {"fluxio.app-capability/v0-draft"}
FOLLOW_ON_APP_IDS: set[str] = set()
BRIDGE_HTTP_TIMEOUT_SECONDS = 0.35
SOLANTIR_PREVIEW_PROOF_MAX_AGE_HOURS = 36
SOLENTIR_APP_ID = "neyvia.app.solentir"
LEGACY_SOLENTIR_APP_IDS = {"solantir-terminal"}
SIGNAL_BRIEFS_APP_ID = "neyvia.app.signal-briefs"


def _is_solentir_app_id(app_id: str) -> bool:
    return app_id == SOLENTIR_APP_ID or app_id in LEGACY_SOLENTIR_APP_IDS


def _is_native_solentir_app_id(app_id: str) -> bool:
    return app_id == SOLENTIR_APP_ID


def _is_legacy_solentir_app_id(app_id: str) -> bool:
    return app_id in LEGACY_SOLENTIR_APP_IDS


def _is_signal_briefs_app_id(app_id: str) -> bool:
    return app_id == SIGNAL_BRIEFS_APP_ID


def manifest_schema() -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "optional": ["application_surface"],
        "required": [
            "manifest_id",
            "schema_version",
            "app_id",
            "name",
            "description",
            "bridge",
            "auth",
            "permissions",
            "tasks",
            "context_surfaces",
            "action_hooks",
        ],
        "bridgeFields": ["transport", "endpoint", "healthcheck", "event_stream"],
        "authFields": ["mode", "scopes"],
        "taskFields": ["task_id", "label", "description"],
        "contextSurfaceFields": ["surface_id", "label", "description", "access"],
        "actionHookFields": ["hook_id", "label", "description", "mutability"],
    }


def validate_manifest_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    schema = manifest_schema()
    for key in schema["required"]:
        if key not in payload:
            errors.append(f"Missing manifest field: {key}")
    schema_version = str(payload.get("schema_version") or "")
    if schema_version not in {SCHEMA_VERSION, *LEGACY_SCHEMA_VERSIONS}:
        errors.append(f"Unsupported manifest schema: {schema_version or 'missing'}")

    bridge = payload.get("bridge", {})
    for key in schema["bridgeFields"]:
        if key not in bridge:
            errors.append(f"Missing bridge field: {key}")

    auth = payload.get("auth", {})
    for key in schema["authFields"]:
        if key not in auth:
            errors.append(f"Missing auth field: {key}")

    for collection_name, required_fields in (
        ("tasks", schema["taskFields"]),
        ("context_surfaces", schema["contextSurfaceFields"]),
        ("action_hooks", schema["actionHookFields"]),
    ):
        collection = payload.get(collection_name, [])
        if not isinstance(collection, list) or not collection:
            errors.append(f"{collection_name} must contain at least one entry")
            continue
        for index, item in enumerate(collection):
            for field_name in required_fields:
                if field_name not in item:
                    errors.append(f"{collection_name}[{index}] is missing {field_name}")
    if "application_surface" in payload:
        validation = validate_application_surface_manifest(payload)
        errors.extend(
            f"application_surface: {item}" for item in validation["errors"]
        )
    return errors


def validate_handshake_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    for key in ("app_id", "bridge_version", "session_id", "transport"):
        if key not in payload:
            errors.append(f"Missing handshake field: {key}")
    return errors


def load_mock_manifests(root: Path) -> list[AppCapabilityManifest]:
    config_path = root / "config" / "connected_apps.json"
    payload = _load_manifest_payloads(config_path)
    return [_to_manifest(item) for item in payload]


@checked_action(check_snapshot)
def build_connected_apps_snapshot(root: Path) -> dict:
    manifests = load_mock_manifests(root)
    state = _load_session_state(root)
    connected_sessions: list[ConnectedAppSession] = []
    handshakes: list[dict] = []

    for manifest in manifests:
        if manifest.app_id in FOLLOW_ON_APP_IDS:
            session = _build_follow_on_session(root, manifest)
            connected_sessions.append(session)
            handshakes.append(
                asdict(
                    AppBridgeHandshake(
                        app_id=manifest.app_id,
                        bridge_version=BRIDGE_VERSION,
                        session_id=session.session_id,
                        transport=manifest.bridge.get("transport", "ipc"),
                        capabilities=manifest.permissions,
                        auth_mode=manifest.auth.get("mode", "local_session"),
                        requires_user_present=bool(
                            manifest.ui_hints.get("requiresUserPresent", True)
                        ),
                    )
                )
            )
            continue

        live_session, handshake = _build_live_session(
            root=root,
            manifest=manifest,
            previous_state=state.get(manifest.app_id, {}),
        )
        connected_sessions.append(live_session)
        handshakes.append(handshake)
        state[manifest.app_id] = _persistable_session_state(live_session)

    if state:
        _save_session_state(root, state)

    connected_names = [
        session.app_name for session in connected_sessions if session.status == "connected"
    ]
    workspace_ready_names = [
        session.app_name
        for session in connected_sessions
        if session.status == "available" and session.bridge_health == "workspace_ready"
    ]
    recommendation_parts = []
    if connected_names:
        recommendation_parts.append(f"{', '.join(connected_names)} bridge session(s) are live.")
    if workspace_ready_names:
        recommendation_parts.append(
            f"{', '.join(workspace_ready_names)} workspace bridge is ready for RSS, camera, feed, and DR verification."
        )
    recommendation = (
        " ".join(recommendation_parts)
        if recommendation_parts
        else "Connected apps are loaded, but live bridge sessions are not healthy yet."
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "bridgeVersion": BRIDGE_VERSION,
        "manifestSchema": manifest_schema(),
        "bridgeHandshake": handshakes[0]
        if handshakes
        else asdict(
            AppBridgeHandshake(
                app_id="mock.app",
                bridge_version=BRIDGE_VERSION,
                session_id=f"handshake_{uuid.uuid4().hex[:8]}",
                transport="http",
            )
        ),
        "bridgeHandshakes": handshakes,
        "phases": [
            "Phase A: manifest and policy contract",
            "Phase B: live reference integrations for OratioViva plus storage and cloud bridges",
            "Phase C: Solentir intelligence bridge with durable runs, traces, artifacts, and approval",
        ],
        "discoveredApps": [asdict(item) for item in manifests],
        "connectedSessions": [asdict(item) for item in connected_sessions],
        "recommendation": recommendation,
    }


def _build_live_session(
    *,
    root: Path,
    manifest: AppCapabilityManifest,
    previous_state: dict,
) -> tuple[ConnectedAppSession, dict]:
    app_root = _resolve_app_root(root, manifest)
    grants = _build_grants(manifest)
    session_id = previous_state.get("session_id") or f"bridge_{manifest.app_id}"
    handshake = AppBridgeHandshake(
        app_id=manifest.app_id,
        bridge_version=BRIDGE_VERSION,
        session_id=session_id,
        transport=manifest.bridge.get("transport", "http"),
        capabilities=manifest.permissions,
        auth_mode=manifest.auth.get("mode", "local_token"),
        requires_user_present=bool(manifest.ui_hints.get("requiresUserPresent", False)),
    )

    if manifest.app_id == "cloud-drive-sync":
        return (
            _build_cloud_drive_session(
                root=root,
                manifest=manifest,
                previous_state=previous_state,
                grants=grants,
            ),
            asdict(handshake),
        )

    if manifest.app_id == "synology-fast-sync":
        return (
            _build_synology_fast_sync_session(
                manifest=manifest,
                app_root=app_root or root,
                previous_state=previous_state,
                grants=grants,
            ),
            asdict(handshake),
        )

    if app_root is None or not app_root.exists():
        session = ConnectedAppSession(
            session_id=session_id,
            app_id=manifest.app_id,
            app_name=manifest.name,
            status="missing",
            bridge_health="missing",
            manifest_id=manifest.manifest_id,
            granted_capabilities=grants,
            handshake_status="bridge_missing",
            bridge_transport=manifest.bridge.get("transport", ""),
            bridge_endpoint=manifest.bridge.get("endpoint", ""),
            notes=[
                "The manifest loaded, but the local sibling app repository was not found.",
                "Keep this integration in review until the app root is available on disk.",
            ],
        )
        return session, asdict(handshake)

    context_preview = _context_preview_for_app(root, manifest.app_id, app_root, manifest)
    task_history = _task_history_for_app(
        root=root,
        manifest=manifest,
        app_root=app_root,
        previous_task_history=previous_state.get("task_history", []),
    )
    latest_task_result = task_history[-1] if task_history else {}
    approval_callback = _approval_callback_for_app(manifest.app_id, app_root)
    status = "connected"
    bridge_health = "healthy"
    handshake_status = "connected"
    active_tasks = [
        item.get("label", item.get("taskId", "task"))
        for item in task_history
        if item.get("status") in {"queued", "running"}
    ]
    notes = [
        f"Handshake resolved against {app_root}.",
        "Capability grants stay scoped to the app manifest and bridge contract.",
    ]
    if _is_native_solentir_app_id(manifest.app_id):
        health, workspace = _solentir_native_state(manifest)
        latest = _latest_solentir_native_run(workspace)
        runtime_live = bool(health.get("ok"))
        engine_connected = bool(health.get("evidenceEngineConnected"))
        status = "connected" if runtime_live else "available"
        bridge_health = "healthy" if runtime_live else "workspace_ready"
        handshake_status = "connected" if runtime_live else "workspace_registered"
        notes = [
            f"Solentir native workspace resolved at {app_root}.",
            (
                f"Intelligence program run {latest.get('id')} is {latest.get('status')}."
                if latest.get("id")
                else "The Solentir runtime is ready for a new intelligence program."
                if runtime_live
                else "The workspace is present; start the native Solentir runtime to expose programs."
            ),
            (
                "Signal Briefs is connected as the evidence engine."
                if engine_connected
                else "Solentir is online, but its Signal Briefs evidence engine is offline."
                if runtime_live
                else "The evidence engine state will be checked after Solentir starts."
            ),
            "Approval remains internal to Neyvia and never posts, sends, uploads, or changes a release pointer.",
        ]
    elif _is_legacy_solentir_app_id(manifest.app_id):
        runtime_state = _read_bridge_json(
            str(manifest.bridge.get("endpoint") or "http://127.0.0.1:8015"),
            "/api/terminal/briefing-studio",
        )
        runtime = runtime_state.get("runtime") if isinstance(runtime_state, dict) else None
        runtime_live = isinstance(runtime, dict) and bool(runtime.get("id"))
        status = "connected" if runtime_live else "available"
        bridge_health = "healthy" if runtime_live else "workspace_ready"
        handshake_status = "connected" if runtime_live else "workspace_registered"
        notes = [
            f"Solentir workspace resolved at {app_root}.",
            (
                f"Durable briefing run {runtime.get('id')} is {runtime.get('status')}."
                if runtime_live
                else "The workspace is present; start the durable briefing runtime to expose a live run."
            ),
            "Neyvia supervises source collection, model routes, build trace, artifacts, and approval without claiming external publication.",
        ]
    if _is_signal_briefs_app_id(manifest.app_id):
        endpoint = str(manifest.bridge.get("endpoint") or "http://127.0.0.1:8025")
        health = _read_bridge_json(endpoint, str(manifest.bridge.get("healthcheck") or "/health"))
        runs_payload = _read_bridge_json(endpoint, "/api/runs") if health.get("ok") else {}
        runs = runs_payload.get("runs") if isinstance(runs_payload.get("runs"), list) else []
        latest = runs[0] if runs and isinstance(runs[0], dict) else {}
        runtime_live = bool(health.get("ok"))
        status = "connected" if runtime_live else "available"
        bridge_health = "healthy" if runtime_live else "workspace_ready"
        handshake_status = "connected" if runtime_live else "workspace_registered"
        notes = [
            f"Signal Briefs workspace resolved at {app_root}.",
            (
                f"Durable evidence run {latest.get('id')} is {latest.get('status')}."
                if latest.get("id")
                else "The runtime is healthy and ready for a new evidence run."
                if runtime_live
                else "The workspace is present; start Signal Briefs to expose live runs."
            ),
            "Neyvia supervises source collection, bounded model analysis, independent review, artifacts, and internal approval without claiming external publication.",
        ]
    if approval_callback.get("available"):
        notes.append(approval_callback.get("detail", "Approval callback is available."))

    session = ConnectedAppSession(
        session_id=session_id,
        app_id=manifest.app_id,
        app_name=manifest.name,
        status=status,
        bridge_health=bridge_health,
        manifest_id=manifest.manifest_id,
        granted_capabilities=grants,
        active_tasks=active_tasks,
        last_seen_at=utc_now_iso(),
        notes=notes,
        handshake_status=handshake_status,
        bridge_transport=manifest.bridge.get("transport", ""),
        bridge_endpoint=manifest.bridge.get("endpoint", ""),
        app_root=str(app_root),
        context_preview=context_preview,
        action_hooks=[asdict(item) for item in manifest.action_hooks],
        task_history=task_history[-4:],
        latest_task_result=latest_task_result,
        approval_callback=approval_callback,
        ui_hints=manifest.ui_hints,
    )
    return session, asdict(handshake)


@checked_action(check_storage_session)
def _build_synology_fast_sync_session(
    *,
    manifest: AppCapabilityManifest,
    app_root: Path,
    previous_state: dict,
    grants: list[CapabilityGrant],
) -> ConnectedAppSession:
    bridge_endpoint = manifest.bridge.get("endpoint", "http://127.0.0.1:8765")
    public_endpoint = str(manifest.bridge.get("public_endpoint") or bridge_endpoint).rstrip("/")
    status_payload = _read_bridge_json(bridge_endpoint, "/api/status")
    job_payload = _read_bridge_json(bridge_endpoint, "/api/job") if status_payload else {}
    bridge_online = bool(status_payload)
    bridge_plan = _synology_bridge_plan(manifest, status_payload, job_payload)

    context_preview = _synology_context_preview(
        manifest=manifest,
        app_root=app_root,
        status_payload=status_payload,
        job_payload=job_payload,
        bridge_plan=bridge_plan,
    )
    task_history = _synology_task_history(
        manifest=manifest,
        status_payload=status_payload,
        job_payload=job_payload,
        bridge_plan=bridge_plan,
        previous_task_history=previous_state.get("task_history", []),
    )
    latest_task_result = task_history[-1] if task_history else {}
    app_root_exists = bool(app_root.exists())
    notes = [
        (
            "Cowork Synology Fast Sync files are present and registered as a local app bridge."
            if app_root_exists
            else "Synology bridge metadata is loaded even though the mapped app root is not available on this host."
        ),
        "Use the Fast Sync web surface for large project upload/download output.",
    ]
    if bridge_online:
        notes.insert(0, str(status_payload.get("message") or "Synology Fast Sync bridge is online."))
    else:
        notes.insert(
            0,
            "Synology Fast Sync UI is not responding on the configured local endpoint.",
        )

    return ConnectedAppSession(
        session_id=previous_state.get("session_id") or f"bridge_{manifest.app_id}",
        app_id=manifest.app_id,
        app_name=manifest.name,
        status="connected" if bridge_online else "available",
        bridge_health="healthy" if bridge_online else "offline",
        manifest_id=manifest.manifest_id,
        granted_capabilities=grants,
        active_tasks=[
            "Fast Sync copy"
            for state in [job_payload.get("state")]
            if state in {"preparing", "running"}
        ],
        last_seen_at=utc_now_iso(),
        notes=notes,
        handshake_status="connected" if bridge_online else "endpoint_offline",
        bridge_transport=manifest.bridge.get("transport", "http"),
        bridge_endpoint=bridge_endpoint,
        app_root=str(app_root),
        context_preview=context_preview,
        task_history=task_history[-4:],
        latest_task_result=latest_task_result,
        approval_callback={
            "available": True,
            "channel": "mobile_web",
            "detail": (
                "Fast Sync output is browser-readable; bind the service to a LAN or Tailscale "
                "address when you want the phone to operate the same bridge."
            ),
        },
        ui_hints={
            **manifest.ui_hints,
            "bridgeRole": "nas_storage",
            "sourceRoot": bridge_plan.get("sourceRoot", ""),
            "targetRoot": bridge_plan.get("targetRoot", ""),
            "selectedMode": bridge_plan.get("selectedMode", ""),
            "selectedHost": bridge_plan.get("selectedHost", ""),
            "controlProtocol": bridge_plan.get("controlProtocol", ""),
            "controlPort": bridge_plan.get("controlPort", 0),
            "requestedSshPort": bridge_plan.get("requestedSshPort", 0),
            "observedSshPort": bridge_plan.get("observedSshPort", 0),
            "sshPortStatus": bridge_plan.get("sshPortStatus", ""),
            "sshUser": bridge_plan.get("sshUser", ""),
            "remoteProjectRoot": bridge_plan.get("remoteProjectRoot", ""),
            "safeDirections": bridge_plan.get("safeDirections", []),
            "activeDirection": bridge_plan.get("activeDirection", ""),
            "targetReady": bridge_plan.get("targetReady", False),
            "activationRequired": bridge_plan.get("activationRequired", False),
            "activationProject": bridge_plan.get("activationProject", ""),
            "activationHint": bridge_plan.get("activationHint", ""),
            "publicEndpoint": public_endpoint,
            "preferredTransport": manifest.bridge.get("preferred_transport", ""),
            "httpsReady": public_endpoint.startswith("https://"),
            "requiresApprovalForWrite": bool(
                bridge_plan.get("requiresApprovalForWrite", True)
            ),
        },
    )


def _build_cloud_drive_session(
    *,
    root: Path,
    manifest: AppCapabilityManifest,
    previous_state: dict,
    grants: list[CapabilityGrant],
) -> ConnectedAppSession:
    bridge_plan = _cloud_drive_bridge_plan(root, manifest)
    context_preview = _cloud_drive_context_preview(manifest, bridge_plan)
    task_history = _cloud_drive_task_history(
        manifest=manifest,
        bridge_plan=bridge_plan,
        previous_task_history=previous_state.get("task_history", []),
    )
    latest_task_result = task_history[-1] if task_history else {}
    connected = bool(bridge_plan.get("mountedRoots") or bridge_plan.get("googleLoginReady"))
    notes = [
        "Cloud Drive Bridge is registered as a storage bridge for Google Drive and mounted folders.",
        "Writes stay approval-gated so cloud and NAS copies cannot be changed silently.",
    ]
    if bridge_plan.get("googleLoginReady"):
        notes.insert(0, "Google Drive login state is present on this machine.")
    elif bridge_plan.get("mountedRoots"):
        notes.insert(0, "Mounted cloud-drive folders were detected on this machine.")
    else:
        notes.insert(0, "Cloud storage is ready to configure, but no Google login or mounted folder is detected yet.")

    return ConnectedAppSession(
        session_id=previous_state.get("session_id") or f"bridge_{manifest.app_id}",
        app_id=manifest.app_id,
        app_name=manifest.name,
        status="connected" if connected else "available",
        bridge_health="healthy" if connected else "configure",
        manifest_id=manifest.manifest_id,
        granted_capabilities=grants,
        active_tasks=[],
        last_seen_at=utc_now_iso(),
        notes=notes,
        handshake_status="connected" if connected else "configuration_pending",
        bridge_transport=manifest.bridge.get("transport", "local_mount_oauth"),
        bridge_endpoint=manifest.bridge.get("endpoint", "local://cloud-drive"),
        app_root=str(root),
        context_preview=context_preview,
        task_history=task_history[-4:],
        latest_task_result=latest_task_result,
        approval_callback={
            "available": True,
            "channel": "desktop_oauth",
            "detail": (
                "Google login should be launched by the desktop credential service; mounted "
                "folders can be used without sending raw cloud tokens to the browser."
            ),
        },
        ui_hints={
            **manifest.ui_hints,
            "bridgeRole": "cloud_storage",
            "sourceRoot": bridge_plan.get("sourceRoot", ""),
            "targetRoot": bridge_plan.get("primaryRoot", ""),
            "selectedMode": bridge_plan.get("selectedMode", ""),
            "selectedHost": bridge_plan.get("selectedProvider", ""),
            "safeDirections": bridge_plan.get("safeDirections", []),
            "activeDirection": bridge_plan.get("activeDirection", ""),
            "targetReady": bool(bridge_plan.get("targetReady")),
            "requiresApprovalForWrite": True,
            "mountedRoots": bridge_plan.get("mountedRoots", []),
            "googleLoginReady": bool(bridge_plan.get("googleLoginReady")),
        },
    )


def _build_follow_on_session(root: Path, manifest: AppCapabilityManifest) -> ConnectedAppSession:
    app_root = _resolve_app_root(root, manifest)
    return ConnectedAppSession(
        session_id=f"bridge_{manifest.app_id}",
        app_id=manifest.app_id,
        app_name=manifest.name,
        status="follow_on_manifest",
        bridge_health="manifest_only",
        manifest_id=manifest.manifest_id,
        granted_capabilities=_build_grants(manifest),
        last_seen_at=utc_now_iso(),
        notes=[
            "Kept in the Bridge Lab design set for 1.0 review.",
            "Full handshake and task execution are intentionally deferred until after the reference bridge path is proven.",
        ],
        handshake_status="manifest_loaded",
        bridge_transport=manifest.bridge.get("transport", ""),
        bridge_endpoint=manifest.bridge.get("endpoint", ""),
        app_root=str(app_root) if app_root else "",
        context_preview=[],
        task_history=[],
        latest_task_result={
            "taskId": manifest.tasks[0].task_id if manifest.tasks else "",
            "label": manifest.tasks[0].label if manifest.tasks else "Follow-on task",
            "status": "deferred",
            "sourceKind": "connected_app",
            "resultSummary": "Solentir stays in review until its durable runtime and operator approval gate are healthy.",
            "createdAt": utc_now_iso(),
            "completedAt": utc_now_iso(),
            "approvalStatus": "deferred",
            "payload": {
                "followOnSlice": "watchlist read plus approval-aware terminal action",
            },
        },
        approval_callback={
            "available": True,
            "channel": "terminal",
            "detail": "Approval-aware terminal callback is part of the follow-on slice definition.",
        },
    )


def _context_preview_for_app(
    root: Path,
    app_id: str,
    app_root: Path,
    manifest: AppCapabilityManifest,
) -> list[dict]:
    if app_id == "oratio-viva":
        worker_files = sorted(
            path.stem.replace("_worker", "")
            for path in (app_root / "backend").glob("*worker.py")
        )
        package_name, package_version = _read_package_name_version(
            app_root / "frontend" / "package.json"
        )
        return [
            {
                "surfaceId": "voice-catalog",
                "label": "Voice Catalog",
                "summary": (
                    f"{len(worker_files)} voice engines detected"
                    + (f" in {package_name} {package_version}" if package_name else "")
                ),
                "items": worker_files[:6],
                "access": manifest.context_surfaces[0].access if manifest.context_surfaces else "read",
            }
        ]
    if _is_native_solentir_app_id(app_id):
        return _solentir_native_context_preview(app_root, manifest)
    if _is_legacy_solentir_app_id(app_id):
        return _solantir_context_preview(root, app_root, manifest)
    if _is_signal_briefs_app_id(app_id):
        return _signal_briefs_context_preview(app_root, manifest)
    return []


def _task_history_for_app(
    *,
    root: Path,
    manifest: AppCapabilityManifest,
    app_root: Path,
    previous_task_history: list[dict],
) -> list[dict]:
    if (
        previous_task_history
        and not _is_solentir_app_id(manifest.app_id)
        and not _is_signal_briefs_app_id(manifest.app_id)
    ):
        return list(previous_task_history)

    if manifest.app_id == "oratio-viva":
        workers = sorted(
            path.stem.replace("_worker", "")
            for path in (app_root / "backend").glob("*worker.py")
        )
        selected = workers[0] if workers else "default"
        return [
            {
                "taskId": manifest.tasks[0].task_id,
                "label": manifest.tasks[0].label,
                "status": "completed",
                "sourceKind": "connected_app",
                "resultSummary": f"Queued and completed a local preview bridge task for the {selected} voice engine.",
                "createdAt": utc_now_iso(),
                "completedAt": utc_now_iso(),
                "approvalStatus": "not_required",
                "payload": {
                    "selectedEngine": selected,
                    "workspaceRoot": str(app_root),
                    "surfaceRead": "voice-catalog",
                    "previewPrompt": "Neyvia bridge preview",
                },
            }
        ]

    if _is_native_solentir_app_id(manifest.app_id):
        return [_solentir_native_task_result(manifest, app_root)]
    if _is_legacy_solentir_app_id(manifest.app_id):
        return [_solantir_task_result(manifest, app_root, control_root=root)]
    if _is_signal_briefs_app_id(manifest.app_id):
        return [_signal_briefs_task_result(manifest, app_root)]

    return []


def _signal_briefs_state(manifest: AppCapabilityManifest) -> tuple[dict, dict]:
    endpoint = str(manifest.bridge.get("endpoint") or "http://127.0.0.1:8025")
    health = _read_bridge_json(endpoint, str(manifest.bridge.get("healthcheck") or "/health"))
    runs_payload = _read_bridge_json(endpoint, "/api/runs") if health.get("ok") else {}
    runs = runs_payload.get("runs") if isinstance(runs_payload.get("runs"), list) else []
    latest = runs[0] if runs and isinstance(runs[0], dict) else {}
    return health, latest


def _solentir_native_state(manifest: AppCapabilityManifest) -> tuple[dict, dict]:
    endpoint = str(manifest.bridge.get("endpoint") or "http://127.0.0.1:8035")
    health = _read_bridge_json(
        endpoint,
        str(manifest.bridge.get("healthcheck") or "/health"),
    )
    workspace = _read_bridge_json(endpoint, "/api/workspace") if health.get("ok") else {}
    return health, workspace


def _latest_solentir_native_run(workspace: dict) -> dict:
    programs = workspace.get("programs") if isinstance(workspace.get("programs"), list) else []
    runs = [
        program.get("run")
        for program in programs
        if isinstance(program, dict) and isinstance(program.get("run"), dict)
    ]
    runs = [run for run in runs if run.get("id")]
    return max(
        runs,
        key=lambda run: str(run.get("updatedAt") or run.get("createdAt") or ""),
        default={},
    )


def _solentir_native_context_preview(
    app_root: Path,
    manifest: AppCapabilityManifest,
) -> list[dict]:
    health, workspace = _solentir_native_state(manifest)
    engine = workspace.get("engine") if isinstance(workspace.get("engine"), dict) else {}
    programs = workspace.get("programs") if isinstance(workspace.get("programs"), list) else []
    latest = _latest_solentir_native_run(workspace)
    metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
    routes = latest.get("routes") if isinstance(latest.get("routes"), dict) else {}
    primary = routes.get("primary") if isinstance(routes.get("primary"), dict) else {}
    reviewer = routes.get("reviewer") if isinstance(routes.get("reviewer"), dict) else {}
    snapshots = latest.get("snapshots") if isinstance(latest.get("snapshots"), list) else []
    artifacts = latest.get("artifacts") if isinstance(latest.get("artifacts"), list) else []
    approval = latest.get("approval") if isinstance(latest.get("approval"), dict) else {}
    return [
        {
            "surfaceId": "intelligence-programs",
            "label": "Intelligence Programs",
            "summary": (
                f"{len(programs)} durable intelligence program(s) are registered."
                if health.get("ok")
                else "The native Solentir runtime is offline; no program state is claimed."
            ),
            "items": [
                f"{program.get('name') or program.get('id')}: @{program.get('handle') or 'unconfigured'}"
                for program in programs[:8]
                if isinstance(program, dict)
            ] or [f"Workspace: {app_root}"],
            "access": "read",
        },
        {
            "surfaceId": "evidence-supervision",
            "label": "Evidence Supervision",
            "summary": (
                f"Run {latest.get('id')} is {latest.get('status')} with "
                f"{metrics.get('followingAccounts', 0)} accounts and "
                f"{metrics.get('postsCollected', 0)} captured posts."
                if latest.get("id")
                else "No program has launched a durable evidence run yet."
            ),
            "items": [
                f"Evidence engine: {'connected' if engine.get('healthy') else 'offline'}",
                f"Primary: {primary.get('model') or 'not run'} · {primary.get('state') or 'idle'}",
                f"Reviewer: {reviewer.get('model') or 'not run'} · {reviewer.get('state') or 'idle'}",
                f"External publication: {engine.get('approvalPublishesExternally', False)}",
            ],
            "access": "read",
        },
        {
            "surfaceId": "progressive-proof",
            "label": "Progressive Proof",
            "summary": (
                f"{len(snapshots)} snapshots and {len(artifacts)} artifacts are attached; "
                f"approval is {approval.get('state') or 'not requested'}."
                if latest.get("id")
                else "Snapshots, traces, and artifacts appear after a real program run starts."
            ),
            "items": [
                str(item.get("label") or item.get("stage") or "Snapshot")
                for item in snapshots[-8:]
                if isinstance(item, dict)
            ],
            "access": "read",
        },
    ]


def _solentir_native_task_result(
    manifest: AppCapabilityManifest,
    app_root: Path,
) -> dict:
    health, workspace = _solentir_native_state(manifest)
    latest = _latest_solentir_native_run(workspace)
    run_status = str(latest.get("status") or "")
    status = (
        "completed"
        if run_status in {"approved_internal", "awaiting_approval"}
        else "running"
        if run_status == "running"
        else "needs_attention"
        if run_status == "failed"
        else "ready"
        if health.get("ok")
        else "available"
    )
    programs = workspace.get("programs") if isinstance(workspace.get("programs"), list) else []
    artifacts = latest.get("artifacts") if isinstance(latest.get("artifacts"), list) else []
    approval = latest.get("approval") if isinstance(latest.get("approval"), dict) else {}
    return {
        "taskId": (
            manifest.tasks[0].task_id
            if manifest.tasks
            else "supervise-intelligence-program"
        ),
        "label": (
            manifest.tasks[0].label
            if manifest.tasks
            else "Supervise intelligence program"
        ),
        "status": status,
        "sourceKind": "connected_app",
        "resultSummary": (
            f"Solentir program run {latest.get('id')} is {run_status} with {len(artifacts)} durable artifacts."
            if latest.get("id")
            else f"Solentir is ready with {len(programs)} durable intelligence program(s)."
            if health.get("ok")
            else "Solentir is registered, but its native local runtime is offline."
        ),
        "createdAt": str(latest.get("createdAt") or utc_now_iso()),
        "completedAt": str(latest.get("updatedAt") or ""),
        "approvalStatus": str(approval.get("state") or "not_requested"),
        "payload": {
            "workspaceRoot": str(app_root),
            "programCount": len(programs),
            "evidenceEngineConnected": bool(health.get("evidenceEngineConnected")),
            "approvalPublishesExternally": bool(
                health.get("approvalPublishesExternally", False)
            ),
            "run": latest,
        },
    }


def _signal_briefs_context_preview(
    app_root: Path,
    manifest: AppCapabilityManifest,
) -> list[dict]:
    health, latest = _signal_briefs_state(manifest)
    metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
    routes = latest.get("routes") if isinstance(latest.get("routes"), dict) else {}
    primary = routes.get("primary") if isinstance(routes.get("primary"), dict) else {}
    reviewer = routes.get("reviewer") if isinstance(routes.get("reviewer"), dict) else {}
    approval = latest.get("approval") if isinstance(latest.get("approval"), dict) else {}
    snapshots = latest.get("snapshots") if isinstance(latest.get("snapshots"), list) else []
    artifacts = latest.get("artifacts") if isinstance(latest.get("artifacts"), list) else []
    run_id = str(latest.get("id") or "")
    return [
        {
            "surfaceId": "source-graph",
            "label": "Source Graph",
            "summary": (
                f"{metrics.get('followingAccounts', 0)} followed accounts produced "
                f"{metrics.get('postsCollected', 0)} captured posts with "
                f"{metrics.get('timelinesFailed', 0)} timeline failures."
                if run_id
                else "No durable source-graph run is available yet."
            ),
            "items": [
                f"Run: {run_id or 'not started'}",
                f"Stage: {latest.get('stageLabel') or 'idle'}",
                f"FxTwitter/Folo routes: {'live' if health.get('ok') else 'runtime offline'}",
                f"External publication: {approval.get('externalPublication', False)}",
            ],
            "access": "read",
        },
        {
            "surfaceId": "progressive-preview",
            "label": "Progressive Preview",
            "summary": (
                f"{len(snapshots)} durable snapshots expose the run evolution."
                if run_id
                else "Snapshots appear only after a real run starts."
            ),
            "items": [
                str(item.get("label") or item.get("stage") or "Snapshot")
                for item in snapshots[-8:]
                if isinstance(item, dict)
            ],
            "access": "read",
        },
        {
            "surfaceId": "proof-and-control",
            "label": "Proof and Control",
            "summary": (
                f"{len(artifacts)} artifacts; approval is {approval.get('state') or 'not requested'}."
                if run_id
                else "Model receipts, hashes, artifacts, and approval appear after evidence gates pass."
            ),
            "items": [
                f"Primary: {primary.get('model') or 'not run'} · {primary.get('state') or 'idle'}",
                f"Reviewer: {reviewer.get('model') or 'not run'} · {reviewer.get('state') or 'idle'}",
                f"Status: {latest.get('status') or 'idle'}",
                f"Workspace: {app_root}",
            ],
            "access": "read",
        },
    ]


def _signal_briefs_task_result(
    manifest: AppCapabilityManifest,
    app_root: Path,
) -> dict:
    health, latest = _signal_briefs_state(manifest)
    run_status = str(latest.get("status") or "")
    status = (
        "completed"
        if run_status in {"approved_internal", "awaiting_approval"}
        else "running"
        if run_status == "running"
        else "needs_attention"
        if run_status == "failed"
        else "ready"
        if health.get("ok")
        else "available"
    )
    artifacts = latest.get("artifacts") if isinstance(latest.get("artifacts"), list) else []
    metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
    routes = latest.get("routes") if isinstance(latest.get("routes"), dict) else {}
    approval = latest.get("approval") if isinstance(latest.get("approval"), dict) else {}
    return {
        "taskId": (
            manifest.tasks[0].task_id
            if manifest.tasks
            else "build-evidence-brief"
        ),
        "label": (
            manifest.tasks[0].label
            if manifest.tasks
            else "Build evidence brief"
        ),
        "status": status,
        "sourceKind": "connected_app",
        "resultSummary": (
            f"Signal Briefs run {latest.get('id')} is {run_status} with {len(artifacts)} durable artifacts."
            if latest.get("id")
            else "Signal Briefs is ready for a real source-graph evidence run."
            if health.get("ok")
            else "Signal Briefs workspace is registered, but its local runtime is offline."
        ),
        "createdAt": str(latest.get("createdAt") or utc_now_iso()),
        "completedAt": str(latest.get("updatedAt") or ""),
        "approvalStatus": str(
            (latest.get("approval") or {}).get("state")
            if isinstance(latest.get("approval"), dict)
            else "not_requested"
        ),
        "payload": {
            "workspaceRoot": str(app_root),
            "run": {
                "id": str(latest.get("id") or ""),
                "status": run_status,
                "stage": str(latest.get("stage") or ""),
                "progress": _safe_int(latest.get("progress")),
                "metrics": metrics,
                "snapshotCount": len(latest.get("snapshots") or []),
                "artifactCount": len(artifacts),
                "primary": dict(routes.get("primary") or {}),
                "reviewer": dict(routes.get("reviewer") or {}),
                "approval": approval,
            },
            "health": {
                "ok": bool(health.get("ok")),
                "sourceRoutes": list(health.get("sourceRoutes") or []),
                "approvalPublishesExternally": bool(
                    health.get("approvalPublishesExternally")
                ),
            },
        },
    }


def _solantir_terminal_root(app_root: Path, manifest: AppCapabilityManifest) -> Path:
    app_subdir = str(manifest.bridge.get("app_subdir") or "apps/terminal").strip()
    return app_root / app_subdir.replace("\\", "/")


def _read_text_if_exists(path: Path, limit: int = 250_000) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _read_package_scripts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    scripts = payload.get("scripts")
    return {str(key): str(value) for key, value in scripts.items()} if isinstance(scripts, dict) else {}


def _count_regex_matches(path: Path, pattern: str) -> int:
    text = _read_text_if_exists(path)
    return len(re.findall(pattern, text, flags=re.MULTILINE)) if text else 0


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _same_path(left: object, right: Path) -> bool:
    try:
        left_path = Path(str(left)).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    try:
        right_path = right.resolve()
    except (OSError, RuntimeError, ValueError):
        right_path = right
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))


def _latest_solantir_preview_proof(control_root: Path, app_root: Path, terminal_root: Path) -> dict:
    proof_paths = []
    for owner in (control_root, app_root):
        proof_path = owner / ".agent_control" / "solantir_preview_proofs" / "latest.json"
        if proof_path not in proof_paths:
            proof_paths.append(proof_path)
    existing_proof_path = next((path for path in proof_paths if path.exists()), None)
    default_proof_path = proof_paths[0]
    if existing_proof_path is None:
        return {
            "schema": "neyvia.solentir.preview-proof-status/v1",
            "status": "missing",
            "ready": False,
            "fresh": False,
            "checkedAt": "",
            "proofPath": str(default_proof_path),
            "summary": "Run typecheck, data tests, production build, and the Chrome proof flow to refresh Solentir verification.",
            "checks": [],
        }
    proof_path = existing_proof_path
    try:
        report = json.loads(proof_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "schema": "neyvia.solentir.preview-proof-status/v1",
            "status": "unreadable",
            "ready": False,
            "fresh": False,
            "checkedAt": "",
            "proofPath": str(proof_path),
            "summary": f"Solentir preview proof could not be read: {exc}",
            "checks": [],
        }

    checked_at = _parse_iso_datetime(report.get("checkedAt"))
    fresh = (
        checked_at is not None
        and datetime.now(timezone.utc) - checked_at <= timedelta(hours=SOLANTIR_PREVIEW_PROOF_MAX_AGE_HOURS)
    )
    terminal_matches = _same_path(report.get("terminalRoot"), terminal_root)
    status = str(report.get("status") or "unknown")
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    ready = status == "passed" and fresh and terminal_matches
    if ready:
        summary = str(report.get("summary") or "Solentir live preview proof passed.")
    elif status == "passed" and not terminal_matches:
        summary = "Latest Solentir preview proof points at a different terminal root."
    elif status == "passed" and not fresh:
        summary = "Latest Solentir preview proof is stale; repeat the Chrome proof flow."
    else:
        summary = str(report.get("summary") or "Solentir preview proof is not passing.")
    return {
        "schema": "neyvia.solentir.preview-proof-status/v1",
        "status": status,
        "ready": ready,
        "fresh": fresh,
        "terminalMatches": terminal_matches,
        "checkedAt": str(report.get("checkedAt") or ""),
        "proofPath": str(report.get("proofPath") or proof_path),
        "summary": summary,
        "checks": checks,
    }


def _solantir_capability_payload(app_root: Path, manifest: AppCapabilityManifest, *, control_root: Path | None = None) -> dict:
    terminal_root = _solantir_terminal_root(app_root, manifest)
    terminal_package = terminal_root / "package.json"
    package_name, package_version = _read_package_name_version(terminal_package)
    root_package_name, root_package_version = _read_package_name_version(app_root / "package.json")
    scripts = _read_package_scripts(terminal_package)
    contracts_path = app_root / "packages" / "contracts" / "src" / "solantir.ts"
    vite_config_path = terminal_root / "vite.config.ts"
    settings_html_path = terminal_root / "settings.html"
    feeds_path = terminal_root / "src" / "config" / "feeds.ts"
    rss_service_path = terminal_root / "src" / "services" / "rss.ts"
    live_news_path = terminal_root / "src" / "components" / "LiveNewsPanel.ts"
    live_webcams_path = terminal_root / "src" / "components" / "LiveWebcamsPanel.ts"
    briefing_path = terminal_root / "src" / "services" / "briefing-studio.ts"
    feed_camera_test_path = terminal_root / "tests" / "feed-camera-contract.test.mjs"
    desktop_contract_test_path = terminal_root / "tests" / "desktop-runtime-contract.test.mjs"
    dist_index_path = terminal_root / "dist" / "index.html"
    dist_settings_path = terminal_root / "dist" / "settings.html"
    dist_service_worker_path = terminal_root / "dist" / "sw.js"
    vite_config_text = _read_text_if_exists(vite_config_path)
    live_news_text = _read_text_if_exists(live_news_path)
    live_webcams_text = _read_text_if_exists(live_webcams_path)
    service_root = terminal_root / "src" / "generated" / "client" / "worldmonitor"
    service_domains = (
        sorted(path.name for path in service_root.iterdir() if path.is_dir())
        if service_root.exists()
        else []
    )
    verification_commands = [
        str(item)
        for item in manifest.bridge.get("verification_commands", [])
        if str(item).strip()
    ]
    if not verification_commands:
        verification_commands = [
            "npm run typecheck",
            "npm run test:data",
            "npm run test:sidecar",
            "npm run build",
        ]
    rss_proxy_ready = "/api/rss-proxy" in vite_config_text and "rss-proxy-local" in vite_config_text
    camera_contract_ready = (
        feed_camera_test_path.exists()
        and "youtube-nocookie.com/embed" in live_webcams_text
        and "/api/youtube/embed" in live_news_text
        and "fetchLiveVideoId(feed.channelHandle)" in live_webcams_text
        and "webcam-feed-status" in live_webcams_text
        and "Live lookup unavailable -" in live_webcams_text
        and "configurePreviewServer(server)" in vite_config_text
        and "handleYoutubeLive" in vite_config_text
    )
    desktop_contract_ready = desktop_contract_test_path.exists()
    build_artifacts_ready = (
        dist_index_path.exists()
        and dist_settings_path.exists()
        and dist_service_worker_path.exists()
    )
    settings_entry_ready = settings_html_path.exists()
    live_preview_proof = _latest_solantir_preview_proof(control_root or app_root, app_root, terminal_root)
    live_preview_ready = bool(live_preview_proof.get("ready"))
    proof_checks = [
        {"label": "RSS proxy", "ready": rss_proxy_ready, "detail": "/api/rss-proxy is available in Vite dev and preview."},
        {"label": "Feed/camera contracts", "ready": camera_contract_ready, "detail": "Contract tests cover RSS config plus live-news and webcam embeds."},
        {"label": "Live preview receipt", "ready": live_preview_ready, "detail": live_preview_proof["summary"]},
        {"label": "Desktop runtime contract", "ready": desktop_contract_ready, "detail": "Sidecar/package references are checked against files present in the fusion copy."},
        {"label": "Production build artifacts", "ready": build_artifacts_ready, "detail": "index.html, settings.html, and sw.js exist under dist."},
        {"label": "Settings entry", "ready": settings_entry_ready, "detail": "settings.html exists for the desktop settings window."},
    ]
    verification_status = "verified" if all(item["ready"] for item in proof_checks) else "needs_verification"
    preview_url = str(manifest.ui_hints.get("appUrl") or "http://127.0.0.1:4173/")
    settings_url = str(manifest.ui_hints.get("settingsUrl") or preview_url.rstrip("/") + "/settings.html")
    runtime_state = _read_bridge_json(
        str(manifest.bridge.get("endpoint") or "http://127.0.0.1:8015"),
        "/api/terminal/briefing-studio",
    )
    runtime = runtime_state.get("runtime") if isinstance(runtime_state, dict) else None
    briefing = runtime_state.get("briefing") if isinstance(runtime_state, dict) else None
    briefing_runtime = {
        "connected": isinstance(runtime, dict) and bool(runtime.get("id")),
        "runId": str(runtime.get("id") or "") if isinstance(runtime, dict) else "",
        "status": str(runtime.get("status") or "offline") if isinstance(runtime, dict) else "offline",
        "topic": str(runtime.get("topic") or "") if isinstance(runtime, dict) else "",
        "primary": dict(runtime.get("routes", {}).get("primary") or {}) if isinstance(runtime, dict) else {},
        "reviewer": dict(runtime.get("routes", {}).get("reviewer") or {}) if isinstance(runtime, dict) else {},
        "eventCount": len(runtime.get("events") or []) if isinstance(runtime, dict) else 0,
        "snapshotCount": len(runtime.get("snapshots") or []) if isinstance(runtime, dict) else 0,
        "approval": dict(runtime.get("approval") or {}) if isinstance(runtime, dict) else {},
        "artifactBaseUrl": str(runtime.get("artifactBaseUrl") or "") if isinstance(runtime, dict) else "",
        "citationCount": len(briefing.get("citationIds") or []) if isinstance(briefing, dict) else 0,
        "summary": str(briefing.get("generatedSummary") or "") if isinstance(briefing, dict) else "",
    }

    return {
        "schema": "neyvia.solentir.workspace-capabilities/v1",
        "workspaceRoot": str(app_root),
        "terminalRoot": str(terminal_root),
        "rootPackage": root_package_name,
        "rootVersion": root_package_version,
        "package": package_name,
        "version": package_version,
        "contractsReady": contracts_path.exists(),
        "rssServiceReady": rss_service_path.exists(),
        "liveNewsReady": live_news_path.exists(),
        "liveWebcamsReady": live_webcams_path.exists(),
        "briefingStudioReady": briefing_path.exists(),
        "rssProxyReady": rss_proxy_ready,
        "feedCameraContractReady": camera_contract_ready,
        "livePreviewVerified": live_preview_ready,
        "desktopRuntimeContractReady": desktop_contract_ready,
        "buildArtifactsReady": build_artifacts_ready,
        "settingsEntryReady": settings_entry_ready,
        "browserPreview": {
            "url": preview_url,
            "settingsUrl": settings_url,
            "startCommand": str(manifest.ui_hints.get("previewCommand") or "npm run preview"),
        },
        "briefingRuntime": briefing_runtime,
        "feedDeclarationCount": _count_regex_matches(feeds_path, r"\burl\s*:"),
        "sourceTierCount": _count_regex_matches(feeds_path, r"^\s*'[^']+'\s*:"),
        "serviceDomains": service_domains,
        "verificationCommands": verification_commands,
        "availableScripts": sorted(
            name
            for name in ("typecheck", "test:data", "test:sidecar", "build", "dev", "preview")
            if name in scripts
        ),
        "deliveryReceipt": {
            "enabled": "delivery.receipt" in manifest.permissions,
            "command": "record_delivery_receipt_command",
        },
        "livePreviewProof": live_preview_proof,
        "verificationProof": {
            "status": verification_status,
            "checks": proof_checks,
        },
        "routeDefaults": [
            {
                "role": "planner",
                "runtimeId": "codex",
                "provider": "openai-codex",
                "model": "provider-default",
                "effort": "xhigh",
            },
            {
                "role": "reviewer",
                "runtimeId": "ollama",
                "provider": "local-open-source",
                "model": briefing_runtime["reviewer"].get("model") or "operator-selected",
                "effort": "high",
            },
            {
                "role": "synthesizer",
                "runtimeId": "codex",
                "provider": "openai-codex",
                "model": "provider-default",
                "effort": "high",
            },
        ],
    }


def _solantir_context_preview(
    control_root: Path,
    app_root: Path,
    manifest: AppCapabilityManifest,
) -> list[dict]:
    payload = _solantir_capability_payload(app_root, manifest, control_root=control_root)
    source_total = payload["feedDeclarationCount"] or payload["sourceTierCount"]
    service_domains = payload["serviceDomains"]
    verification_commands = payload["verificationCommands"]
    return [
        {
            "surfaceId": "agent-advisor",
            "label": "Agent Advisor & Build Trace",
            "summary": (
                f"Run {payload['briefingRuntime']['runId']} is {payload['briefingRuntime']['status']} "
                f"with {payload['briefingRuntime']['snapshotCount']} snapshots and "
                f"{payload['briefingRuntime']['citationCount']} citations."
                if payload["briefingRuntime"]["connected"]
                else "The durable briefing runtime is offline; no run or artifact is claimed."
            ),
            "items": [
                f"Primary: {payload['briefingRuntime']['primary'].get('id') or 'not connected'}",
                f"Reviewer: {payload['briefingRuntime']['reviewer'].get('id') or 'not connected'}",
                f"Events: {payload['briefingRuntime']['eventCount']}",
                f"Approval: {payload['briefingRuntime']['approval'].get('status') or 'unavailable'}",
                payload["briefingRuntime"]["summary"] or "No verified synthesis is available.",
            ],
            "access": "read",
        },
        {
            "surfaceId": "runtime-readiness",
            "label": "Runtime Readiness",
            "summary": (
                f"{payload['package'] or 'Solentir Intelligence Studio'}"
                + (f" {payload['version']}" if payload["version"] else "")
                + " is available from the NAS fusion workspace."
            ),
            "items": [
                f"Workspace: {payload['workspaceRoot']}",
                f"Terminal: {payload['terminalRoot']}",
                f"Contracts: {'ready' if payload['contractsReady'] else 'missing'}",
                f"Scripts: {', '.join(payload['availableScripts']) or 'none detected'}",
            ],
            "access": "read",
        },
        {
            "surfaceId": "intelligence-feeds",
            "label": "Intelligence Feeds",
            "summary": (
                f"{source_total} feed/source declarations, "
                f"{len(service_domains)} generated service domains, "
                f"RSS={'ready' if payload['rssServiceReady'] else 'missing'}, "
                f"camera={'ready' if payload['liveWebcamsReady'] else 'missing'}."
            ),
            "items": [
                "RSS service with cache and per-feed cooldown",
                f"RSS proxy: {'ready' if payload['rssProxyReady'] else 'needs verification'}",
                "Live news and webcam panels",
                f"Feed/camera contract: {'ready' if payload['feedCameraContractReady'] else 'needs verification'}",
                "Briefing studio schedules and source readiness",
                *service_domains[:8],
            ],
            "access": "read",
        },
        {
            "surfaceId": "verification-loop",
            "label": "Verification Loop",
            "summary": "Neyvia can run Solentir's non-mutating checks before opening mutating watchlist actions.",
            "items": [
                *verification_commands[:6],
                f"Preview: {payload['browserPreview']['url']}",
                f"Build artifacts: {'ready' if payload['buildArtifactsReady'] else 'not built'}",
            ],
            "access": "read",
        },
    ]


def _solantir_task_result(manifest: AppCapabilityManifest, app_root: Path, *, control_root: Path | None = None) -> dict:
    payload = _solantir_capability_payload(app_root, manifest, control_root=control_root)
    missing = [
        label
        for label, ready in (
            ("contracts", payload["contractsReady"]),
            ("rss service", payload["rssServiceReady"]),
            ("live news panel", payload["liveNewsReady"]),
            ("live webcams panel", payload["liveWebcamsReady"]),
            ("briefing studio", payload["briefingStudioReady"]),
        )
        if not ready
    ]
    status = "ready" if not missing else "needs_attention"
    return {
        "taskId": manifest.tasks[0].task_id if manifest.tasks else "verify-intelligence-feeds",
        "label": manifest.tasks[0].label if manifest.tasks else "Verify intelligence feeds",
        "status": status,
        "sourceKind": "connected_app",
        "resultSummary": (
            (
                "Solentir workspace is verified for RSS, camera/live-news contracts, preview build, route, and disaster-recovery readiness."
                if payload["verificationProof"]["status"] == "verified"
                else "Solentir workspace is ready for RSS, camera, briefing, route, and disaster-recovery verification."
            )
            if status == "ready"
            else f"Solentir workspace is present, but these expected files are missing: {', '.join(missing)}."
        ),
        "createdAt": utc_now_iso(),
        "completedAt": "",
        "approvalStatus": "not_required",
        "payload": payload,
    }


def _synology_context_preview(
    *,
    manifest: AppCapabilityManifest,
    app_root: Path,
    status_payload: dict,
    job_payload: dict,
    bridge_plan: dict,
) -> list[dict]:
    surface = manifest.context_surfaces[0] if manifest.context_surfaces else None
    selected_mode = str(bridge_plan.get("selectedMode") or "offline")
    selected_host = str(bridge_plan.get("selectedHost") or "")
    status_items = [
        f"Mode: {selected_mode}",
        f"Host: {selected_host or 'not selected'}",
        f"Control: {bridge_plan.get('controlProtocol') or 'not configured'}:{bridge_plan.get('controlPort') or '-'}",
        f"Port note: {bridge_plan.get('sshPortStatus') or 'operator configured'}",
        f"Remote user: {bridge_plan.get('sshUser') or 'not configured'}",
        f"Computer: {bridge_plan.get('sourceRoot') or 'not mapped'}",
        f"NAS: {bridge_plan.get('targetRoot') or 'not mapped'}",
        f"Remote root: {bridge_plan.get('remoteProjectRoot') or 'not configured'}",
        f"Active transfer: {bridge_plan.get('activeDirection') or 'none'}",
        f"Queued writes need approval: {'yes' if bridge_plan.get('requiresApprovalForWrite') else 'no'}",
    ]
    if job_payload.get("currentPath"):
        status_items.append(f"Current file: {job_payload.get('currentPath')}")
    if bridge_plan.get("activationRequired"):
        status_items.append(str(bridge_plan.get("activationHint") or "Activate the storage project before mapping."))

    return [
        {
            "surfaceId": surface.surface_id if surface else "sync-status",
            "label": surface.label if surface else "Sync Status",
            "summary": (
                str(status_payload.get("message"))
                if status_payload
                else "Cowork Fast Sync backend is installed but the local web bridge is offline."
            ),
            "items": status_items
            or [
                str(app_root / "synology-fast-ui.py"),
                str(app_root / "synology_fast_ui"),
            ],
            "access": surface.access if surface else "read",
        }
    ]


def _synology_task_history(
    *,
    manifest: AppCapabilityManifest,
    status_payload: dict,
    job_payload: dict,
    bridge_plan: dict,
    previous_task_history: list[dict],
) -> list[dict]:
    task = manifest.tasks[0] if manifest.tasks else None
    previous_created_at = ""
    if previous_task_history:
        previous_created_at = str(previous_task_history[-1].get("createdAt", ""))
    job_state = str(job_payload.get("state") or "offline")
    direction = str(job_payload.get("direction") or "")
    completed_files = _safe_int(job_payload.get("completedFiles"))
    remaining_files = _safe_int(job_payload.get("remainingFiles"))
    result_summary = (
        f"Fast Sync job is {job_state}."
        if not status_payload
        else (
            f"{bridge_plan.get('selectedMode') or 'offline'} path selected; "
            f"{completed_files} file(s) completed and {remaining_files} remaining."
        )
    )
    if direction:
        result_summary = f"{direction.title()} output: {result_summary}"

    return [
        {
            "taskId": task.task_id if task else "monitor-fast-sync",
            "label": task.label if task else "Monitor Fast Sync output",
            "status": "running" if job_state in {"preparing", "running"} else "completed",
            "sourceKind": "connected_app",
            "resultSummary": result_summary,
            "createdAt": previous_created_at or utc_now_iso(),
            "completedAt": "" if job_state in {"preparing", "running"} else utc_now_iso(),
            "approvalStatus": "not_required",
            "payload": {
                "targetReady": bool(bridge_plan.get("targetReady")),
                "targetRoot": str(bridge_plan.get("targetRoot") or ""),
                "sourceRoot": str(bridge_plan.get("sourceRoot") or ""),
                "selectedMode": str(bridge_plan.get("selectedMode") or ""),
                "selectedHost": str(bridge_plan.get("selectedHost") or ""),
                "controlProtocol": str(bridge_plan.get("controlProtocol") or ""),
                "controlPort": _safe_int(bridge_plan.get("controlPort")),
                "requestedSshPort": _safe_int(bridge_plan.get("requestedSshPort")),
                "observedSshPort": _safe_int(bridge_plan.get("observedSshPort")),
                "sshPortStatus": str(bridge_plan.get("sshPortStatus") or ""),
                "sshUser": str(bridge_plan.get("sshUser") or ""),
                "remoteProjectRoot": str(bridge_plan.get("remoteProjectRoot") or ""),
                "safeDirections": list(bridge_plan.get("safeDirections", [])),
                "activeDirection": str(bridge_plan.get("activeDirection") or ""),
                "requiresApprovalForWrite": bool(bridge_plan.get("requiresApprovalForWrite")),
                "activationRequired": bool(bridge_plan.get("activationRequired")),
                "activationProject": str(bridge_plan.get("activationProject") or ""),
                "activationHint": str(bridge_plan.get("activationHint") or ""),
                "activationCommand": str(bridge_plan.get("activationCommand") or ""),
                "bridgePlan": bridge_plan,
                "currentPath": str(job_payload.get("currentPath") or ""),
            },
        }
    ]


def _cloud_drive_context_preview(manifest: AppCapabilityManifest, bridge_plan: dict) -> list[dict]:
    surface = manifest.context_surfaces[0] if manifest.context_surfaces else None
    mounted_roots = list(bridge_plan.get("mountedRoots", []))
    items = [
        f"Provider: {bridge_plan.get('selectedProvider') or 'not selected'}",
        f"Computer: {bridge_plan.get('sourceRoot') or 'not mapped'}",
        f"Primary cloud folder: {bridge_plan.get('primaryRoot') or 'not mounted'}",
        f"Google login: {'ready' if bridge_plan.get('googleLoginReady') else 'not configured'}",
        f"Queued writes need approval: {'yes' if bridge_plan.get('requiresApprovalForWrite') else 'no'}",
    ]
    items.extend(str(item.get("root", "")) for item in mounted_roots[:4] if item.get("root"))
    return [
        {
            "surfaceId": surface.surface_id if surface else "cloud-drive-status",
            "label": surface.label if surface else "Cloud Drive Status",
            "summary": bridge_plan.get("summary", ""),
            "items": items,
            "access": surface.access if surface else "read",
        }
    ]


def _cloud_drive_task_history(
    *,
    manifest: AppCapabilityManifest,
    bridge_plan: dict,
    previous_task_history: list[dict],
) -> list[dict]:
    task = manifest.tasks[0] if manifest.tasks else None
    previous_created_at = ""
    if previous_task_history:
        previous_created_at = str(previous_task_history[-1].get("createdAt", ""))
    return [
        {
            "taskId": task.task_id if task else "monitor-cloud-drive",
            "label": task.label if task else "Monitor Cloud Drive bridge",
            "status": "completed",
            "sourceKind": "connected_app",
            "resultSummary": bridge_plan.get("summary", "Cloud-drive bridge state was refreshed."),
            "createdAt": previous_created_at or utc_now_iso(),
            "completedAt": utc_now_iso(),
            "approvalStatus": "not_required",
            "payload": {
                "targetReady": bool(bridge_plan.get("targetReady")),
                "targetRoot": str(bridge_plan.get("primaryRoot") or ""),
                "sourceRoot": str(bridge_plan.get("sourceRoot") or ""),
                "selectedMode": str(bridge_plan.get("selectedMode") or ""),
                "selectedHost": str(bridge_plan.get("selectedProvider") or ""),
                "safeDirections": list(bridge_plan.get("safeDirections", [])),
                "activeDirection": str(bridge_plan.get("activeDirection") or ""),
                "requiresApprovalForWrite": bool(bridge_plan.get("requiresApprovalForWrite")),
                "bridgePlan": bridge_plan,
                "cloudProviders": list(bridge_plan.get("providers", [])),
                "mountedRoots": list(bridge_plan.get("mountedRoots", [])),
                "googleLoginReady": bool(bridge_plan.get("googleLoginReady")),
            },
        }
    ]


@checked_action(check_cloud_plan)
def _cloud_drive_bridge_plan(root: Path, manifest: AppCapabilityManifest) -> dict:
    source_root = str(
        manifest.bridge.get("source_root")
        or manifest.bridge.get("workspace_root")
        or root.resolve()
    )
    mounted_roots = _discover_cloud_drive_roots(manifest.bridge.get("discovery_roots"))
    google_login_ready = _google_drive_oauth_present(root)
    primary = mounted_roots[0] if mounted_roots else {}
    selected_provider = str(primary.get("provider") or manifest.ui_hints.get("primaryProvider") or "google-drive")
    primary_root = str(primary.get("root") or "")
    target_ready = bool(primary_root or google_login_ready)
    safe_directions = ["upload", "download"] if target_ready else []
    summary = (
        f"{selected_provider} bridge ready at {primary_root}."
        if primary_root
        else (
            "Google Drive OAuth is ready; select a cloud folder before queuing transfers."
            if google_login_ready
            else "Cloud Drive bridge is waiting for Google login or a mounted cloud folder."
        )
    )
    return {
        "mode": "cloud_drive_bridge",
        "selectedMode": "google_oauth" if google_login_ready else ("mounted_folder" if primary_root else "configure"),
        "selectedProvider": selected_provider,
        "sourceRoot": source_root,
        "primaryRoot": primary_root,
        "targetRoot": primary_root,
        "mountedRoots": mounted_roots,
        "providers": list(manifest.ui_hints.get("providers", [])),
        "googleLoginReady": google_login_ready,
        "activeDirection": "",
        "safeDirections": safe_directions,
        "targetReady": target_ready,
        "requiresApprovalForWrite": True,
        "writePolicy": "preview_then_approve",
        "conflictPolicy": "keep_newer_and_log",
        "loginUrl": "https://drive.google.com/drive/my-drive",
        "desktopClientUrl": "https://www.google.com/drive/download/",
        "summary": summary,
    }


def _discover_cloud_drive_roots(discovery_roots: object = None) -> list[dict]:
    """Observe only explicitly selected mounts when the bridge supplies roots.

    An empty list deliberately disables ambient mount discovery. This is
    directory metadata only; it never reads authentication or file contents.
    Omission preserves the existing environment/default discovery behavior.
    """
    if discovery_roots is not None:
        if not isinstance(discovery_roots, list) or len(discovery_roots) > 32:
            raise ValueError("discovery_roots must be a list of at most 32 absolute paths")
        candidates: list[Path] = []
        for value in discovery_roots:
            if not isinstance(value, str) or not value.strip() or len(value) > 4096 or "\x00" in value:
                raise ValueError("discovery_roots entries must be bounded nonempty path strings")
            path = Path(value)
            if not path.is_absolute():
                raise ValueError("discovery_roots entries must be absolute paths")
            candidates.append(path)
        selected: list[dict] = []
        seen: set[str] = set()
        for path in candidates:
            resolved = path.resolve()
            key = str(resolved).casefold()
            if key in seen or not resolved.exists() or not resolved.is_dir():
                continue
            seen.add(key)
            selected.append({"provider": "local-mounted-drive", "root": str(resolved)})
        return selected
    candidates: list[tuple[str, Path]] = []
    for env_name, provider in (
        ("FLUXIO_CLOUD_DRIVE_ROOT", "local-mounted-drive"),
        ("FLUXIO_GOOGLE_DRIVE_ROOT", "google-drive"),
        ("GOOGLE_DRIVE_ROOT", "google-drive"),
        ("OneDrive", "onedrive"),
        ("OneDriveConsumer", "onedrive"),
        ("OneDriveCommercial", "onedrive"),
        ("DROPBOX", "dropbox"),
    ):
        value = str(os.environ.get(env_name, "")).strip()
        if value:
            candidates.append((provider, Path(value)))

    home = Path.home()
    candidates.extend(
        [
            ("google-drive", Path("G:/My Drive")),
            ("google-drive", Path("G:/Shared drives")),
            ("google-drive", home / "Google Drive"),
            ("google-drive", home / "My Drive"),
            ("onedrive", home / "OneDrive"),
            ("dropbox", home / "Dropbox"),
        ]
    )

    seen: set[str] = set()
    roots: list[dict] = []
    for provider, path in candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        key = str(resolved).lower()
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        roots.append({"provider": provider, "root": str(resolved)})
    return roots


def _google_drive_oauth_present(root: Path) -> bool:
    if str(os.environ.get("FLUXIO_GOOGLE_DRIVE_OAUTH_PRESENT", "")).strip():
        return True
    for env_name in ("GOOGLE_DRIVE_OAUTH_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS"):
        if str(os.environ.get(env_name, "")).strip():
            return True
    for candidate in (
        root / ".agent_control" / "google_drive_token.json",
        Path.home() / ".config" / "syntelos" / "google_drive_token.json",
        Path.home() / ".config" / "fluxio" / "google_drive_token.json",
    ):
        if candidate.exists():
            return True
    return False


@checked_action(check_storage_plan)
def _synology_bridge_plan(
    manifest: AppCapabilityManifest,
    status_payload: dict,
    job_payload: dict,
) -> dict:
    selected_mode = str(
        status_payload.get("selectedMode")
        or manifest.bridge.get("connection_mode")
        or "offline"
    ) if status_payload or manifest.bridge else "offline"
    selected_host = str(
        status_payload.get("selectedHost")
        or manifest.bridge.get("nas_host")
        or ""
    ) if status_payload or manifest.bridge else ""
    source_root = str(
        status_payload.get("sourceRoot")
        or manifest.bridge.get("source_root")
        or manifest.bridge.get("workspace_root")
        or ""
    ) if status_payload or manifest.bridge else ""
    target_root = str(
        status_payload.get("targetRoot")
        or manifest.bridge.get("target_root")
        or ""
    ) if status_payload or manifest.bridge else ""
    remote_project_root = str(
        manifest.bridge.get("remote_project_root")
        or manifest.bridge.get("remote_root")
        or ""
    ).strip()
    if remote_project_root:
        if not target_root:
            target_root = remote_project_root
        elif _looks_unavailable_mapped_drive_path(target_root, source_root):
            if not Path(target_root).expanduser().exists():
                target_root = remote_project_root
    active_direction = str(job_payload.get("direction") or "").strip().lower()
    target_path_exists = bool(target_root and Path(target_root).expanduser().exists())
    target_ready = bool(status_payload.get("targetReady")) if status_payload else target_path_exists
    activation_project = str(manifest.bridge.get("activation_project") or "Core")
    activation_command = str(
        manifest.bridge.get("activation_command")
        or manifest.bridge.get("map_command")
        or ""
    )
    control_protocol = str(manifest.bridge.get("control_protocol") or "ssh").strip().lower()
    requested_ssh_port = _safe_int(manifest.bridge.get("requested_ssh_port"))
    observed_ssh_port = _safe_int(manifest.bridge.get("ssh_port"))
    control_port = _safe_int(
        manifest.bridge.get("control_port")
        or requested_ssh_port
        or observed_ssh_port
        or 22
    )
    ssh_port_status = str(manifest.bridge.get("ssh_port_status") or "").strip()
    ssh_user = str(manifest.bridge.get("ssh_user") or "").strip()
    activation_required = bool(
        source_root
        and target_root
        and not target_ready
        and (selected_mode in {"tailscale", "lan"} or selected_host)
    )
    activation_hint = (
        f"Activate the {activation_project} project or run the Synology mapper before using {target_root}."
        if activation_required
        else ""
    )
    requires_approval_for_write = _as_bool(
        manifest.bridge.get("requires_approval_for_write"),
        default=True,
    )
    auto_sync_enabled = _as_bool(manifest.bridge.get("auto_sync"), default=False)
    configured_write_policy = str(manifest.bridge.get("write_policy") or "").strip()
    write_policy = (
        configured_write_policy
        or (
            "preview_then_approve"
            if requires_approval_for_write
            else "automatic_bidirectional"
        )
    )
    safe_directions = []
    if source_root and target_ready:
        safe_directions = ["upload", "download"]
    return {
        "mode": "bidirectional_bridge",
        "selectedMode": selected_mode,
        "selectedHost": selected_host,
        "controlProtocol": control_protocol,
        "controlPort": control_port,
        "requestedSshPort": requested_ssh_port or control_port,
        "observedSshPort": observed_ssh_port,
        "sshPortStatus": ssh_port_status,
        "sshUser": ssh_user,
        "remoteProjectRoot": remote_project_root,
        "sourceRoot": source_root,
        "targetRoot": target_root,
        "activeDirection": active_direction,
        "safeDirections": safe_directions,
        "targetReady": target_ready,
        "activationRequired": activation_required,
        "activationProject": activation_project,
        "activationHint": activation_hint,
        "activationCommand": activation_command,
        "requiresApprovalForWrite": requires_approval_for_write,
        "autoSyncEnabled": auto_sync_enabled and not requires_approval_for_write,
        "writePolicy": write_policy,
        "conflictPolicy": str(status_payload.get("conflictPolicy") or "keep_newer_and_log"),
        "continuousRunRole": (
            "NAS keeps the service online while the desktop keeps local working files editable."
        ),
    }


def _read_bridge_json(endpoint: str, path: str) -> dict:
    base = str(endpoint or "").rstrip("/")
    if not base:
        return {}
    if base.endswith("/fluxio"):
        base = base[: -len("/fluxio")]
    normalized_path = f"/{str(path or '').lstrip('/')}"
    url = f"{base}{normalized_path}"
    try:
        with urllib.request.urlopen(url, timeout=BRIDGE_HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _looks_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in {"/", "\\"}


def _looks_unavailable_mapped_drive_path(value: str, source_root: str = "") -> bool:
    if not _looks_windows_drive_path(value):
        return False
    if not _looks_windows_drive_path(source_root):
        return True
    return value[0].lower() != source_root[0].lower()


def _as_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _approval_callback_for_app(app_id: str, app_root: Path) -> dict:
    if _is_native_solentir_app_id(app_id):
        return {
            "available": True,
            "channel": "intelligence_program",
            "detail": (
                "Solentir can approve a selected evidence bundle inside Neyvia only; "
                "it never invokes an external publication destination."
            ),
        }
    if _is_legacy_solentir_app_id(app_id):
        return {
            "available": True,
            "channel": "terminal_workbench",
            "detail": (
                "Solentir watchlist and alert actions remain approval-aware while feed, camera, "
                "briefing, and DR checks are read-only."
            ),
        }
    if _is_signal_briefs_app_id(app_id):
        return {
            "available": True,
            "channel": "evidence_briefing",
            "detail": (
                "Signal Briefs approval marks a durable artifact bundle publishable "
                "inside Neyvia and never invokes an external destination."
            ),
        }
    return {"available": False, "channel": "", "detail": ""}


def _persistable_session_state(session: ConnectedAppSession) -> dict:
    return {
        "session_id": session.session_id,
        "task_history": session.task_history,
        "latest_task_result": session.latest_task_result,
    }


def _load_session_state(root: Path) -> dict:
    state_path = root / ".agent_control" / "connected_apps_state.json"
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


@checked_state_save
def _save_session_state(root: Path, state: dict) -> None:
    state_path = root / ".agent_control" / "connected_apps_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(state, indent=2)
    if state_path.exists():
        try:
            if state_path.read_text(encoding="utf-8") == serialized:
                return
        except OSError:
            pass
    from .durability import atomic_write_text
    atomic_write_text(state_path, serialized, encoding="utf-8")


def _build_grants(manifest: AppCapabilityManifest) -> list[CapabilityGrant]:
    return [
        CapabilityGrant(
            grant_id=f"grant_{manifest.app_id}_{index}",
            capability_key=permission,
            status="granted" if index < 2 else "review",
            scope="app",
            reason="Loaded from the local bridge manifest and kept inside capability scope.",
        )
        for index, permission in enumerate(manifest.permissions)
    ]


def _resolve_app_root(root: Path, manifest: AppCapabilityManifest) -> Path | None:
    configured_root = manifest.bridge.get("workspace_root") or manifest.ui_hints.get(
        "workspaceRoot"
    )
    if configured_root:
        path = Path(str(configured_root)).expanduser().resolve()
        return path

    for candidate in _candidate_app_roots(root, manifest.app_id):
        if candidate.exists():
            return candidate.resolve()
    return _candidate_app_roots(root, manifest.app_id)[0]


def _candidate_app_roots(root: Path, app_id: str) -> list[Path]:
    base = root.resolve().parent
    if _is_signal_briefs_app_id(app_id):
        return [
            base / "neyvia-app-signal-briefs",
            Path("Y:/projects/neyvia/development/signal-briefs"),
        ]
    if _is_solentir_app_id(app_id):
        return [
            base / "neyvia-app-solentir",
            Path("Y:/projects/neyvia/development/solentir"),
            Path("Y:/projects/solantir-mindtower-fusion/Solantir"),
            base / "Solentir",
            base / "Solantir",
            base / "solantir",
        ]

    lookup = {
        "oratio-viva": [base / "OratioViva", base / "oratio-viva"],
        "synology-fast-sync": [base / "Cowork"],
    }
    return lookup.get(app_id, [base / app_id])


def _read_package_name_version(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "", ""
    return str(payload.get("name", "")), str(payload.get("version", ""))


def _count_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def _load_manifest_payloads(config_path: Path) -> list[dict]:
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, list) and payload:
            return payload
    return [
        {
            "manifest_id": "manifest_oratio_viva",
            "schema_version": SCHEMA_VERSION,
            "app_id": "oratio-viva",
            "name": "Oratio Viva",
            "description": "Speech and voice workflows exposed through a local bridge for guided agent execution.",
            "bridge": {
                "transport": "http",
                "endpoint": "http://127.0.0.1:47830/fluxio",
                "healthcheck": "/health",
                "event_stream": "/events",
            },
            "auth": {"mode": "local_token", "scopes": ["speech.manage", "voice.render"]},
            "permissions": ["task.run", "context.read", "action.invoke"],
            "tasks": [
                {
                    "task_id": "render-voice-preview",
                    "label": "Render voice preview",
                    "description": "Create a short preview from app-managed voices and prompts.",
                    "requires_approval": False,
                }
            ],
            "context_surfaces": [
                {
                    "surface_id": "voice-catalog",
                    "label": "Voice Catalog",
                    "description": "App-managed voice inventory and metadata.",
                    "access": "read",
                }
            ],
            "action_hooks": [
                {
                    "hook_id": "queue-render",
                    "label": "Queue Render",
                    "description": "Send a render request into the app job queue.",
                    "mutability": "write",
                    "risk_level": "medium",
                    "requires_approval": False,
                }
            ],
            "ui_hints": {"category": "speech", "requiresUserPresent": False},
        },
        {
            "manifest_id": "manifest_neyvia_app_solentir",
            "schema_version": SCHEMA_VERSION,
            "app_id": SOLENTIR_APP_ID,
            "name": "Solentir Intelligence Studio",
            "description": "Evidence-bound intelligence surfaces exposed to Neyvia through a capability-scoped bridge.",
            "bridge": {
                "transport": "ipc",
                "endpoint": "http://127.0.0.1:8015",
                "healthcheck": "ping",
                "event_stream": "events",
            },
            "auth": {"mode": "local_session", "scopes": ["dashboard.read", "watchlist.write"]},
            "permissions": ["task.run", "context.read", "approval.request"],
            "tasks": [
                {
                    "task_id": "refresh-watchlist",
                    "label": "Refresh watchlist",
                    "description": "Run the app-native watchlist refresh workflow.",
                    "requires_approval": True,
                }
            ],
            "context_surfaces": [
                {
                    "surface_id": "watchlist",
                    "label": "Watchlist",
                    "description": "Current analyst watchlist state.",
                    "access": "read",
                }
            ],
            "action_hooks": [
                {
                    "hook_id": "ack-alert",
                    "label": "Acknowledge alert",
                    "description": "Mark a surfaced alert as acknowledged inside the app.",
                    "mutability": "write",
                    "risk_level": "medium",
                    "requires_approval": True,
                }
            ],
            "ui_hints": {"category": "operations", "requiresUserPresent": True},
        },
    ]


def _to_manifest(payload: dict) -> AppCapabilityManifest:
    errors = validate_manifest_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return AppCapabilityManifest(
        manifest_id=str(payload["manifest_id"]),
        schema_version=str(payload["schema_version"]),
        app_id=str(payload["app_id"]),
        name=str(payload["name"]),
        description=str(payload["description"]),
        bridge=dict(payload.get("bridge", {})),
        auth=dict(payload.get("auth", {})),
        permissions=list(payload.get("permissions", [])),
        tasks=[AppTaskDescriptor(**item) for item in payload.get("tasks", [])],
        context_surfaces=[AppContextSurface(**item) for item in payload.get("context_surfaces", [])],
        action_hooks=[AppActionHook(**item) for item in payload.get("action_hooks", [])],
        ui_hints=dict(payload.get("ui_hints", {})),
        application_surface=dict(payload.get("application_surface", {})),
    )
