from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .app_capability_standard import SCHEMA_VERSION
from .proofs_e_sv import enforced
from .application_surface import (
    APPLICATION_SURFACE_SCHEMA_VERSION,
    ApplicationSurfaceService,
    validate_application_surface_manifest,
)
from .install_profiles import InstallProfileRegistry
from .encrypted_chat import EncryptedChatService
from .folder_sync import FolderSyncService
from .generated.neyvia_contracts import NeyviaModuleManifest
from .mesh_service import MeshService
from .module_marketplace import ModuleMarketplace
from .nearby_send import NearbySendService
from .p2p_cache import P2PCacheService
from .p2p_provider import P2PProviderService
from .secret_broker import SecretBrokerService
from .models import (
    AppActionHook,
    AppCapabilityManifest,
    AppContextSurface,
    AppTaskDescriptor,
)


SOLANTIR_ROUTE_OVERRIDES: list[dict[str, Any]] = [
    {
        "role": "planner",
        "runtimeId": "hermes",
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "effort": "xhigh",
        "budgetClass": "deep",
        "routeIntent": "plan Solantir feed, DR, and UI work before execution",
    },
    {
        "role": "executor",
        "runtimeId": "opencode",
        "provider": "openrouter",
        "model": "glm-5.2",
        "effort": "high",
        "budgetClass": "frontend",
        "routeIntent": "execute bounded UI and integration changes",
    },
    {
        "role": "verifier",
        "runtimeId": "hermes",
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "effort": "high",
        "budgetClass": "verification",
        "routeIntent": "verify browser preview, computerless behavior, and receipts",
    },
]


class FluxioClient:
    """Small HTTP client for projects that want to use the Fluxio runtime loop."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:47880",
        *,
        username: str = "",
        password: str = "",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds
        self._cookie = ""

    def login(self) -> dict[str, Any]:
        if not self.username or not self.password:
            raise ValueError("username and password are required for login().")
        response, headers = self._post(
            "/api/auth/login",
            {"username": self.username, "password": self.password},
            include_cookie=False,
            return_headers=True,
        )
        cookie = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
        if cookie:
            self._cookie = cookie.split(";", 1)[0]
        return response.get("data", response)

    def dispatch(self, command: str, payload: dict[str, Any] | None = None) -> Any:
        if not self._cookie and self.username and self.password:
            self.login()
        response = self._post(
            "/api/backend",
            {"command": command, "payload": payload or {}},
            include_cookie=True,
        )
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "Neyvia backend command failed."))
        return response.get("data")

    def agent_chat(
        self,
        message: str,
        *,
        runtime: str = "hermes",
        provider: str = "openai-codex",
        model: str = "gpt-5.5",
        effort: str = "high",
        workspace_path: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        return self.dispatch(
            "send_agent_chat_command",
            {
                "message": message,
                "runtime": runtime,
                "provider": provider,
                "model": model,
                "effort": effort,
                "workspacePath": workspace_path,
                "sessionId": session_id,
            },
        )

    def runtime_lane_cycle(
        self,
        objective: str,
        *,
        route_overrides: list[dict[str, Any]] | None = None,
        default_runtime: str = "hermes",
        workspace_path: str = "",
        mission_id: str = "",
        app_context: dict[str, Any] | None = None,
        instructions: str = "",
    ) -> dict[str, Any]:
        return self.dispatch(
            "run_runtime_lane_cycle_command",
            {
                "objective": objective,
                "routeOverrides": route_overrides or [],
                "defaultRuntime": default_runtime,
                "workspacePath": workspace_path,
                "missionId": mission_id,
                "appContext": app_context or {},
                "instructions": instructions,
            },
        )

    def runtime_auto_update(self, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
        return self.dispatch(
            "run_runtime_auto_update_command",
            {"force": force, "dryRun": dry_run},
        )

    def connected_apps(self) -> dict[str, Any]:
        return self.dispatch("get_connected_apps_snapshot_command", {})

    def module_catalog(self) -> dict[str, Any]:
        """Read the runtime's verified immutable module catalog."""

        return self.dispatch("get_installed_module_catalog_command", {})

    def application_registry(self) -> dict[str, Any]:
        """Read external SDK consumers and installed ecosystem applications."""

        return self.dispatch("get_neyvia_application_registry_command", {})

    def register_sdk_application(
        self,
        *,
        application_id: str,
        name: str,
        services: list[str],
        summary: str = "",
        version: str = "",
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register an independent product as an SDK consumer, not a shell app."""

        return self.dispatch(
            "register_sdk_application_command",
            {
                "applicationId": application_id,
                "name": name,
                "summary": summary,
                "version": version,
                "services": services,
                "permissions": permissions or [],
            },
        )

    def unregister_sdk_application(self, application_id: str) -> dict[str, Any]:
        return self.dispatch(
            "unregister_sdk_application_command",
            {"applicationId": application_id},
        )

    def validate_neyvia_application(
        self,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate either application proposition without registering it."""

        return self.dispatch(
            "validate_neyvia_application_manifest_command",
            {"manifest": manifest},
        )

    def validate_module_manifest(
        self,
        manifest: NeyviaModuleManifest,
    ) -> dict[str, Any]:
        """Ask the authoritative backend to apply structural and semantic validation."""

        return self.dispatch(
            "validate_module_manifest_command",
            {"manifest": manifest},
        )

    def inspect_module_package(
        self,
        manifest: NeyviaModuleManifest,
        archive_path: str,
    ) -> dict[str, Any]:
        """Inspect a package through the backend without extracting or executing it."""

        return self.dispatch(
            "inspect_module_package_command",
            {"manifest": manifest, "archivePath": archive_path},
        )

    def plan_module_install(
        self,
        manifest: NeyviaModuleManifest,
        archive_path: str,
        *,
        current_version: str = "",
    ) -> dict[str, Any]:
        """Create a verification/activation plan; this call does not install."""

        return self.dispatch(
            "plan_module_install_command",
            {
                "manifest": manifest,
                "archivePath": archive_path,
                "currentVersion": current_version,
            },
        )

    def application_surfaces(self) -> dict[str, Any]:
        """List optional workspace-built app surfaces known to the runtime."""

        return self.dispatch("get_application_surface_catalog_command", {})

    def validate_application_surface(
        self,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        return self.dispatch(
            "validate_application_surface_command",
            {"manifest": manifest},
        )

    def application_surface_status(
        self,
        manifest: dict[str, Any],
        *,
        target_id: str = "",
    ) -> dict[str, Any]:
        return self.dispatch(
            "get_application_surface_status_command",
            {"manifest": manifest, "targetId": target_id},
        )

    def plan_application_surface_launch(
        self,
        manifest: dict[str, Any],
        *,
        target_id: str,
        permission_mode: str = "workspace_safe",
        approval_id: str = "",
    ) -> dict[str, Any]:
        """Create a permission-bound launch plan without launching or building."""

        return self.dispatch(
            "plan_application_surface_launch_command",
            {
                "manifest": manifest,
                "targetId": target_id,
                "permissionMode": permission_mode,
                "approvalId": approval_id,
            },
        )

    def observe_application_surface(
        self,
        manifest: dict[str, Any],
        *,
        max_log_lines: int = 80,
        max_proof_files: int = 20,
    ) -> dict[str, Any]:
        return self.dispatch(
            "observe_application_surface_command",
            {
                "manifest": manifest,
                "maxLogLines": max_log_lines,
                "maxProofFiles": max_proof_files,
            },
        )

    def solantir_intelligence_cycle(
        self,
        objective: str,
        *,
        workspace_path: str = "Y:/projects/solantir-mindtower-fusion/Solantir",
        mission_id: str = "",
        route_overrides: list[dict[str, Any]] | None = None,
        include_delivery_receipts: bool = True,
        instructions: str = "",
    ) -> dict[str, Any]:
        merged_instructions = "\n".join(
            item
            for item in (
                "Use Solantir as a connected intelligence terminal. Verify RSS, camera/live-news, briefing, browser preview, and DR surfaces before marking work complete.",
                "Do not store raw social credentials in code, manifests, proof files, or browser-visible UI.",
                instructions.strip(),
            )
            if item
        )
        return self.runtime_lane_cycle(
            objective,
            route_overrides=route_overrides or SOLANTIR_ROUTE_OVERRIDES,
            default_runtime="hermes",
            workspace_path=workspace_path,
            mission_id=mission_id,
            app_context={
                "apps": [
                    {
                        "appId": "solantir-terminal",
                        "workspaceRoot": workspace_path,
                        "surfaces": [
                            "intelligence-feeds",
                            "runtime-readiness",
                            "watchlist",
                            "delivery-receipts",
                        ],
                    }
                ],
                "deliveryReceipts": {"requested": include_delivery_receipts},
            },
            instructions=merged_instructions,
        )

    def record_delivery_receipt(
        self,
        *,
        mission_id: str,
        event_kind: str,
        event_message: str,
        channel: str = "browser_notification",
        destination: str = "current_browser",
        status: str = "delivered",
        delivery_url: str = "",
        origin_runtime: str = "",
        origin_provider: str = "",
        origin_model: str = "",
    ) -> dict[str, Any]:
        return self.dispatch(
            "record_delivery_receipt_command",
            {
                "missionId": mission_id,
                "eventKind": event_kind,
                "eventMessage": event_message,
                "channel": channel,
                "destination": destination,
                "status": status,
                "deliveryUrl": delivery_url,
                "originRuntime": origin_runtime,
                "originProvider": origin_provider,
                "originModel": origin_model,
            },
        )

    @property
    def scenes(self):
        """Shared Scene core through the existing authenticated native-tool path."""
        from .scene_core import SceneClient
        return SceneClient(self.call_native_tool)

    def native_tools(self, query: str = "", *, describe: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if query:
            payload["query"] = query
        if describe:
            payload["describe"] = describe
        return self.dispatch("get_native_tool_catalog_command", payload)

    def call_native_tool(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.dispatch(
            "call_native_tool_command",
            {"tool": tool, "arguments": arguments or {}},
        )

    def nas_message_send(
        self,
        *,
        recipient: str,
        message: str,
        attachments: list[str] | None = None,
        nas_root: str = "",
    ) -> dict[str, Any]:
        return self.dispatch(
            "call_native_tool_command",
            {
                "tool": "nas.message.send",
                "arguments": {
                    "recipient": recipient,
                    "message": message,
                    "attachments": list(attachments or []),
                },
                "nasRoot": nas_root,
            },
        )

    @enforced("sv.sdk.transport")
    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        include_cookie: bool,
        return_headers: bool = False,
    ) -> Any:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if include_cookie and self._cookie:
            headers["Cookie"] = self._cookie
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        from .proofs_e_sv import check_sdk_request
        check_sdk_request(self, request, path, payload, include_cookie)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                text = response.read().decode("utf-8")
                parsed = json.loads(text) if text else {}
                if return_headers:
                    return parsed, response.headers
                return parsed
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(detail or f"Neyvia HTTP error {exc.code}") from exc


@enforced("sv.sdk.manifest")
def build_app_manifest(
    *,
    app_id: str,
    name: str,
    description: str,
    endpoint: str,
    tasks: list[dict[str, Any]],
    context_surfaces: list[dict[str, Any]],
    action_hooks: list[dict[str, Any]],
    permissions: list[str] | None = None,
    application_surface: dict[str, Any] | None = None,
    transport: str = "http",
    auth_mode: str = "local_token",
) -> dict[str, Any]:
    manifest = AppCapabilityManifest(
        manifest_id=f"manifest_{app_id.replace('-', '_')}",
        schema_version=SCHEMA_VERSION,
        app_id=app_id,
        name=name,
        description=description,
        bridge={
            "transport": transport,
            "endpoint": endpoint.rstrip("/"),
            "healthcheck": "/health",
            "event_stream": "/events",
        },
        auth={"mode": auth_mode, "scopes": permissions or ["task.run", "context.read"]},
        permissions=permissions or ["task.run", "context.read", "action.invoke"],
        tasks=[AppTaskDescriptor(**item) for item in tasks],
        context_surfaces=[AppContextSurface(**item) for item in context_surfaces],
        action_hooks=[AppActionHook(**item) for item in action_hooks],
        ui_hints={"category": "project", "requiresUserPresent": False},
        application_surface=dict(application_surface or {}),
    )
    payload = asdict(manifest)
    if application_surface is None:
        payload.pop("application_surface", None)
    else:
        validation = validate_application_surface_manifest(payload)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
    return payload


def build_application_surface(
    *,
    surface_id: str,
    title: str,
    description: str,
    targets: list[dict[str, Any]],
    control_modes: list[str] | None = None,
    permissions: dict[str, list[str]] | None = None,
    lifecycle: dict[str, Any] | None = None,
    observability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate an optional app-manifest application surface block."""

    surface = {
        "schema_version": APPLICATION_SURFACE_SCHEMA_VERSION,
        "surface_id": surface_id,
        "title": title,
        "description": description,
        "control_modes": (
            list(control_modes) if control_modes is not None else ["agent", "user"]
        ),
        "permissions": (
            permissions
            if permissions is not None
            else {
                "inspect": ["workspace.read"],
                "launch": ["process.execute"],
                "control": ["device.control"],
            }
        ),
        "targets": targets,
    }
    if lifecycle:
        surface["lifecycle"] = dict(lifecycle)
    if observability:
        surface["observability"] = dict(observability)
    validation = validate_application_surface_manifest(surface)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    return surface


def get_application_surface_status(
    manifest: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    target_id: str = "",
) -> dict[str, Any]:
    """Inspect declared and observed availability without starting the app."""

    return ApplicationSurfaceService(workspace_root).status(
        manifest,
        target_id=target_id,
    )


@enforced("sv.sdk.plan-only")
def plan_application_surface_launch(
    manifest: dict[str, Any],
    *,
    target_id: str,
    workspace_root: str | Path = ".",
    permission_mode: str = "workspace_safe",
    approval_id: str = "",
) -> dict[str, Any]:
    """Return a bounded, permission-aware plan; never launch or build."""

    return ApplicationSurfaceService(workspace_root).plan_launch(
        manifest,
        target_id=target_id,
        permission_mode=permission_mode,
        approval_id=approval_id,
    )


def observe_application_surface(
    manifest: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    max_log_lines: int = 80,
    max_proof_files: int = 20,
) -> dict[str, Any]:
    """Read bounded log tails and proof hashes from workspace-scoped hooks."""

    return ApplicationSurfaceService(workspace_root).observe(
        manifest,
        max_log_lines=max_log_lines,
        max_proof_files=max_proof_files,
    )


def build_solantir_manifest(
    *,
    workspace_root: str = "Y:/projects/solantir-mindtower-fusion/Solantir",
    endpoint: str = "local://solantir-terminal",
) -> dict[str, Any]:
    return build_app_manifest(
        app_id="solantir-terminal",
        name="Solantir Terminal",
        description="Solantir intelligence, audience, RSS, camera, briefing, and watchlist surfaces exposed to Neyvia.",
        endpoint=endpoint,
        tasks=[
            {
                "task_id": "verify-intelligence-feeds",
                "label": "Verify intelligence feeds",
                "description": "Run non-mutating Solantir checks for RSS, live news, camera, briefing, and data readiness.",
                "requires_approval": False,
            },
            {
                "task_id": "refresh-watchlist",
                "label": "Refresh watchlist",
                "description": "Run Solantir's watchlist refresh workflow after read-only feed health is visible.",
                "requires_approval": True,
            },
        ],
        context_surfaces=[
            {
                "surface_id": "intelligence-feeds",
                "label": "Intelligence Feeds",
                "description": "RSS, news, market, social, camera, and briefing pipeline readiness.",
                "access": "read",
            },
            {
                "surface_id": "runtime-readiness",
                "label": "Runtime Readiness",
                "description": "Solantir scripts, contracts, terminal package, and verification commands.",
                "access": "read",
            },
            {
                "surface_id": "watchlist",
                "label": "Watchlist",
                "description": "Current analyst watchlist state.",
                "access": "read",
            },
        ],
        action_hooks=[
            {
                "hook_id": "verify-feeds",
                "label": "Verify feeds",
                "description": "Run Solantir's non-mutating feed and readiness checks from the NAS workspace.",
                "mutability": "read",
                "risk_level": "low",
                "requires_approval": False,
                "execution_kind": "command",
                "execution_command": "npm run typecheck && npm run test:data",
            },
            {
                "hook_id": "ack-alert",
                "label": "Acknowledge alert",
                "description": "Mark a surfaced alert as acknowledged inside Solantir.",
                "mutability": "write",
                "risk_level": "medium",
                "requires_approval": True,
            },
        ],
        permissions=[
            "task.run",
            "context.read",
            "approval.request",
            "feed.read",
            "delivery.receipt",
        ],
        transport="workspace_bridge",
        auth_mode="local_session",
    ) | {
        "bridge": {
            "transport": "workspace_bridge",
            "endpoint": endpoint.rstrip("/"),
            "healthcheck": "npm run typecheck",
            "event_stream": "local-events",
            "workspace_root": workspace_root,
            "app_subdir": "apps/terminal",
            "verification_commands": [
                "npm run typecheck",
                "npm run test:data",
                "npm run test:sidecar",
                "npm run build",
            ],
        },
        "ui_hints": {
            "category": "operations",
            "bridgeRole": "intelligence_terminal",
            "workspaceRoot": workspace_root,
            "runtimeManager": "solantir-feed-and-briefing-manager",
            "requiresUserPresent": True,
            "verificationLoop": True,
            "primarySurfaces": ["RSS", "Live news", "Camera feeds", "Briefing studio", "Watchlists"],
        },
    }


def write_app_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


def validate_module_manifest(
    manifest: NeyviaModuleManifest,
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Validate a v1 module manifest without installing or activating it."""

    return ModuleMarketplace(workspace_root).validate_manifest(manifest)


def inspect_module_package(
    manifest: NeyviaModuleManifest,
    archive_path: str | Path,
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Inspect an immutable module archive without extracting or executing it."""

    return ModuleMarketplace(workspace_root).inspect_package(manifest, archive_path)


@enforced("sv.sdk.plan-only")
def plan_module_install(
    manifest: NeyviaModuleManifest,
    archive_path: str | Path,
    *,
    workspace_root: str | Path = ".",
    current_version: str = "",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a verification and activation plan without mutating module state."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).build_install_plan(
        manifest,
        archive_path,
        current_version=current_version,
    )


def get_module_marketplace_toolchain(
    *,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return exact pinned marketplace tools and their live hash status."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).toolchain_snapshot()


def check_module_marketplace_toolchain_updates(
    *,
    workspace_root: str | Path = ".",
    force: bool = False,
) -> dict[str, Any]:
    """Check local tool hashes and official stable release candidates."""

    return ModuleMarketplace(
        workspace_root,
    ).check_toolchain_updates(force=force)


def get_module_marketplace_browse(
    *,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the local operator marketplace catalog and explicit availability gaps."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).operator_browse_snapshot()


def get_mesh_snapshot(
    *,
    workspace_root: str | Path = ".",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return sanitized peer, route, and provider health."""

    return MeshService(workspace_root).snapshot(refresh=refresh)


def get_mesh_enrollment_trust(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return enrollment, device trust, route, service, and migration truth."""

    return MeshService(workspace_root).enrollment_and_trust_status()


def probe_mesh_peer(
    target: str,
    *,
    workspace_root: str | Path = ".",
    count: int = 3,
    timeout_seconds: int = 5,
) -> dict[str, Any]:
    """Measure a private peer route without exposing transport credentials."""

    return MeshService(workspace_root).probe_peer(
        target,
        count=count,
        timeout_seconds=timeout_seconds,
    )


def get_mesh_service_catalog(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return services explicitly advertised on the private mesh."""

    return MeshService(workspace_root).service_catalog()


def advertise_mesh_service(
    service: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advertise a credential-free private endpoint after explicit approval."""

    return MeshService(workspace_root).advertise_service(
        service,
        approval_receipt=approval_receipt,
    )


def revoke_mesh_service(
    service_id: str,
    *,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
    revoked_by: str,
    reason: str,
) -> dict[str, Any]:
    """Revoke a private service advertisement after explicit approval."""

    return MeshService(workspace_root).revoke_service(
        service_id,
        approval_receipt=approval_receipt,
        revoked_by=revoked_by,
        reason=reason,
    )


def get_mesh_migration_plan(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return the fail-closed Tailscale-to-NetBird migration gates."""

    return MeshService(workspace_root).migration_plan()


def get_mesh_identity_snapshot(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return durable opaque mesh identity, trust, and ACL state."""

    return MeshService(workspace_root).identity_snapshot()


def plan_mesh_identity_mutation(
    operation: str,
    *,
    device_ref: str,
    payload: dict[str, Any],
    workspace_root: str | Path = ".",
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Create a hash-, policy-, device-, and revision-bound mutation plan."""

    return MeshService(workspace_root).plan_identity_mutation(
        operation,
        device_ref=device_ref,
        payload=payload,
        ttl_seconds=ttl_seconds,
    )


def prepare_mesh_device_enrollment(
    *,
    device_label: str,
    platform: str,
    requested_by: str,
    workspace_root: str | Path = ".",
    ttl_seconds: int = 900,
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a short-lived local intent without claiming provider enrollment."""

    return MeshService(workspace_root).prepare_device_enrollment(
        device_label=device_label,
        platform=platform,
        requested_by=requested_by,
        ttl_seconds=ttl_seconds,
        approval_receipt=approval_receipt,
    )


def stage_mesh_device_identity(
    enrollment_ref: str,
    *,
    public_key_fingerprint: str,
    provider_enrollment_receipt: dict[str, Any] | None = None,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a public-key fingerprint to an opaque local device reference."""

    return MeshService(workspace_root).stage_device_identity(
        enrollment_ref,
        public_key_fingerprint=public_key_fingerprint,
        provider_enrollment_receipt=provider_enrollment_receipt,
        approval_receipt=approval_receipt,
    )


def request_mesh_key_rotation(
    device_ref: str,
    *,
    requested_by: str,
    reason: str,
    workspace_root: str | Path = ".",
    ttl_seconds: int = 3600,
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an approval-gated local mesh key-rotation request."""

    return MeshService(workspace_root).request_key_rotation(
        device_ref,
        requested_by=requested_by,
        reason=reason,
        ttl_seconds=ttl_seconds,
        approval_receipt=approval_receipt,
    )


def transition_mesh_key_rotation(
    rotation_ref: str,
    *,
    transition: str,
    public_key_fingerprint: str = "",
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance a local rotation while refusing unproven provider activation."""

    return MeshService(workspace_root).transition_key_rotation(
        rotation_ref,
        transition=transition,
        public_key_fingerprint=public_key_fingerprint,
        approval_receipt=approval_receipt,
    )


def revoke_mesh_device(
    device_ref: str,
    *,
    revoked_by: str,
    reason: str,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Disable a mesh identity locally and leave provider revocation pending."""

    return MeshService(workspace_root).revoke_device(
        device_ref,
        revoked_by=revoked_by,
        reason=reason,
        approval_receipt=approval_receipt,
    )


def set_mesh_device_trust(
    device_ref: str,
    *,
    trust_state: str,
    changed_by: str,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Set local mesh device trust without claiming transport enforcement."""

    return MeshService(workspace_root).set_device_trust(
        device_ref,
        trust_state=trust_state,
        changed_by=changed_by,
        approval_receipt=approval_receipt,
    )


def upsert_mesh_acl_rule(
    rule: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create or update one bounded local mesh ACL rule."""

    return MeshService(workspace_root).upsert_acl_rule(
        rule,
        approval_receipt=approval_receipt,
    )


def evaluate_mesh_acl(
    device_ref: str,
    *,
    action: str,
    resource: str,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Evaluate deny-by-default local mesh policy for one request."""

    return MeshService(workspace_root).evaluate_acl(
        device_ref,
        action=action,
        resource=resource,
    )


def request_mesh_device_recovery(
    device_ref: str,
    *,
    requested_by: str,
    reason: str,
    workspace_root: str | Path = ".",
    ttl_seconds: int = 3600,
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Quarantine a mesh device and record an opaque recovery request."""

    return MeshService(workspace_root).request_device_recovery(
        device_ref,
        requested_by=requested_by,
        reason=reason,
        ttl_seconds=ttl_seconds,
        approval_receipt=approval_receipt,
    )


def transition_mesh_device_recovery(
    recovery_ref: str,
    *,
    transition: str,
    workspace_root: str | Path = ".",
    approval_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance local recovery without claiming remote completion."""

    return MeshService(workspace_root).transition_device_recovery(
        recovery_ref,
        transition=transition,
        approval_receipt=approval_receipt,
    )


def get_mesh_identity_deployment_readiness(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return truthful blockers for provider-backed identity enforcement."""

    return MeshService(workspace_root).identity_deployment_readiness()


def get_nearby_send_compatibility(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return the installed LocalSend compatibility-client integrity."""

    return NearbySendService(workspace_root).compatibility_snapshot()


def discover_nearby_devices(
    *,
    workspace_root: str | Path = ".",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Discover LocalSend-compatible devices on the current LAN."""

    return NearbySendService(workspace_root).discover(
        timeout_seconds=timeout_seconds,
    )


def plan_nearby_send(
    paths: list[str | Path],
    *,
    recipient_endpoint: str,
    recipient_fingerprint: str = "",
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Build a hash-bound nearby-transfer preview without sending."""

    return NearbySendService(workspace_root).build_plan(
        paths,
        recipient_endpoint=recipient_endpoint,
        recipient_fingerprint=recipient_fingerprint,
    )


def send_nearby_files(
    plan: dict[str, Any],
    *,
    approved: bool = False,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Execute an approved hash-bound LocalSend transfer."""

    return NearbySendService(workspace_root).send(
        plan,
        approved=approved,
    )


def get_nearby_transfer_history(
    *,
    workspace_root: str | Path = ".",
    limit: int = 50,
) -> dict[str, Any]:
    """Return bounded, redacted Nearby Send receipt history."""

    return NearbySendService(workspace_root).list_transfer_history(limit=limit)


def get_nearby_active_transfer(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return bounded, redacted durable Nearby Send progress."""

    return NearbySendService(workspace_root).get_active_transfer()


def cancel_nearby_active_transfer(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Request cooperative cancellation through shared durable state."""

    return NearbySendService(
        workspace_root
    ).request_cancel_active_transfer()


def get_folder_sync_compatibility(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Verify the staged Syncthing transport without starting it."""

    return FolderSyncService(workspace_root).compatibility_snapshot()


def get_folder_sync_health(
    *,
    workspace_root: str | Path = ".",
    include_folder_status: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Read sanitized continuous-sync health through a short-lived cache."""

    return FolderSyncService(workspace_root).health(
        include_folder_status=include_folder_status,
        refresh=refresh,
    )


def plan_folder_sync(
    *,
    folder_id: str,
    path: str | Path,
    device_ids: list[str],
    workspace_root: str | Path = ".",
    label: str = "",
    folder_type: str = "sendonly",
    ignore_patterns: list[str] | None = None,
    versioning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a hash-bound paused Syncthing folder plan."""

    return FolderSyncService(workspace_root).build_folder_plan(
        folder_id=folder_id,
        path=path,
        device_ids=device_ids,
        label=label,
        folder_type=folder_type,
        ignore_patterns=ignore_patterns,
        versioning=versioning,
    )


def apply_folder_sync_plan(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Apply an approved folder relationship in the paused state."""

    return FolderSyncService(workspace_root).apply_folder_plan(
        plan,
        approved=approved,
    )


def pause_folder_sync(
    folder_id: str,
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Pause data movement for a configured synchronized folder."""

    return FolderSyncService(workspace_root).pause_folder(
        folder_id,
        approved=approved,
    )


def resume_folder_sync(
    folder_id: str,
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
    approved_deletion_propagation: bool = False,
) -> dict[str, Any]:
    """Activate a folder only after deletion propagation is approved."""

    return FolderSyncService(workspace_root).resume_folder(
        folder_id,
        approved=approved,
        approved_deletion_propagation=approved_deletion_propagation,
    )


def rescan_folder_sync(
    folder_id: str,
    *,
    workspace_root: str | Path = ".",
    sub_path: str = "",
    approved: bool = False,
) -> dict[str, Any]:
    """Request a bounded folder or subdirectory rescan."""

    return FolderSyncService(workspace_root).rescan_folder(
        folder_id,
        sub_path=sub_path,
        approved=approved,
    )


def get_folder_sync_events(
    *,
    workspace_root: str | Path = ".",
    since: int = 0,
    limit: int = 25,
    timeout_seconds: int = 1,
    disk_only: bool = False,
) -> dict[str, Any]:
    """Read a bounded, credential-sanitized Syncthing event window."""

    return FolderSyncService(workspace_root).events(
        since=since,
        limit=limit,
        timeout_seconds=timeout_seconds,
        disk_only=disk_only,
    )


def override_folder_sync(
    folder_id: str,
    *,
    confirmation: str,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Enforce a send-only source after exact-folder confirmation."""

    return FolderSyncService(workspace_root).override_folder(
        folder_id,
        confirmation=confirmation,
        approved=approved,
    )


def revert_folder_sync(
    folder_id: str,
    *,
    confirmation: str,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Discard receive-only local changes after exact-folder confirmation."""

    return FolderSyncService(workspace_root).revert_folder(
        folder_id,
        confirmation=confirmation,
        approved=approved,
    )


def get_encrypted_chat_compatibility(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return the verified Matrix stack without exposing credentials."""

    return EncryptedChatService(workspace_root).compatibility_snapshot()


def get_encrypted_chat_accounts(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """List only agent-allowed accounts and opaque room references."""

    return EncryptedChatService(workspace_root).account_catalog()


def get_encrypted_chat_lifecycle(
    *,
    workspace_root: str | Path = ".",
    account_id: str = "",
) -> dict[str, Any]:
    """Return opaque durable Matrix enrollment, device, and session state."""

    return EncryptedChatService(workspace_root).lifecycle_snapshot(
        account_id=account_id,
    )


def prepare_encrypted_chat_enrollment(
    *,
    account_id: str,
    homeserver: str,
    user_id: str,
    device_id: str,
    device_label: str,
    platform: str,
    workspace_root: str | Path = ".",
    session_ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Persist an enrollment intent without claiming a Matrix login."""

    return EncryptedChatService(workspace_root).prepare_device_enrollment(
        account_id=account_id,
        homeserver=homeserver,
        user_id=user_id,
        device_id=device_id,
        device_label=device_label,
        platform=platform,
        session_ttl_seconds=session_ttl_seconds,
    )


def remove_encrypted_chat_device(
    device_ref: str,
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Disable a Matrix device locally and request remote removal."""

    return EncryptedChatService(workspace_root).request_device_removal(
        device_ref,
        approved=approved,
    )


def expire_encrypted_chat_sessions(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Expire due local Matrix sessions without claiming remote revocation."""

    return EncryptedChatService(workspace_root).expire_sessions()


def recover_encrypted_chat_account(
    *,
    account_id: str,
    reason: str,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Create an approved, secret-free Matrix recovery request."""

    return EncryptedChatService(workspace_root).request_account_recovery(
        account_id=account_id,
        reason=reason,
        approved=approved,
    )


def plan_encrypted_chat_message(
    *,
    account_id: str,
    room_ref: str,
    actor: str,
    workspace_root: str | Path = ".",
    message: str = "",
    attachments: list[str | Path] | None = None,
    format: str = "text",
) -> dict[str, Any]:
    """Build an attributed, hash-bound E2EE message preview."""

    return EncryptedChatService(workspace_root).build_message_plan(
        account_id=account_id,
        room_ref=room_ref,
        actor=actor,
        message=message,
        attachments=attachments,
        format=format,
    )


def plan_encrypted_self_chat(
    *,
    account_id: str,
    actor: str,
    payloads: list[dict[str, Any]],
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Build a typed link/file/clipboard/note plan for the encrypted self room."""

    return EncryptedChatService(workspace_root).build_self_chat_plan(
        account_id=account_id,
        actor=actor,
        payloads=payloads,
    )


def send_encrypted_chat_message(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Send an approved E2EE message and retain no plaintext receipt."""

    return EncryptedChatService(workspace_root).send(
        plan,
        approved=approved,
    )


def get_encrypted_chat_history(
    *,
    account_id: str,
    room_ref: str,
    workspace_root: str | Path = ".",
    limit: int = 25,
) -> dict[str, Any]:
    """Read bounded history from one explicitly allowed encrypted room."""

    return EncryptedChatService(workspace_root).history(
        account_id=account_id,
        room_ref=room_ref,
        limit=limit,
    )


def get_secret_broker_compatibility(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return the verified vault stack without returning private state."""

    return SecretBrokerService(workspace_root).compatibility_snapshot()


def get_secret_handle_catalog(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """List only opaque agent-allowed handles and destinations."""

    return SecretBrokerService(workspace_root).catalog()


def plan_secret_use(
    *,
    handle_ref: str,
    destination_id: str,
    operation: str,
    worker: str,
    actor: str,
    purpose: str,
    device_id: str,
    session_id: str,
    workspace_root: str | Path = ".",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Create a one-time destination-bound secret-use lease."""

    return SecretBrokerService(workspace_root).plan_use(
        handle_ref=handle_ref,
        destination_id=destination_id,
        operation=operation,
        worker=worker,
        actor=actor,
        purpose=purpose,
        device_id=device_id,
        session_id=session_id,
        ttl_seconds=ttl_seconds,
    )


def use_secret(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an approved lease without returning the secret value."""

    return SecretBrokerService(workspace_root).use(
        plan,
        approved=approved,
        approval=approval,
    )


def revoke_secret_lease(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consume a lease without releasing its bound secret."""

    return SecretBrokerService(workspace_root).revoke(
        plan,
        approved=approved,
        approval=approval,
    )


def revoke_secret_subject(
    *,
    subject_type: str,
    subject_id: str,
    actor: str,
    reason_code: str,
    workspace_root: str | Path = ".",
    approved: bool = False,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Durably block future secret deliveries for a device or session."""

    return SecretBrokerService(workspace_root).revoke_subject(
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor,
        reason_code=reason_code,
        approved=approved,
        approval=approval,
    )


def get_secret_revocation_status(
    *,
    device_id: str,
    session_id: str,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return content-free device and session revocation status."""

    return SecretBrokerService(workspace_root).revocation_status(
        device_id=device_id,
        session_id=session_id,
    )


def get_secret_broker_audit(
    *,
    workspace_root: str | Path = ".",
    limit: int = 50,
) -> dict[str, Any]:
    """Read content-free secret-use receipts."""

    return SecretBrokerService(workspace_root).audit(limit=limit)


def get_p2p_cache_compatibility(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return local CAS and selected Iroh transport compatibility."""

    return P2PCacheService(workspace_root).compatibility_snapshot()


def plan_p2p_cache_import(
    path: str | Path,
    *,
    workspace_root: str | Path = ".",
    kind: str = "artifact",
    pin: bool = True,
) -> dict[str, Any]:
    """Hash and preview a workspace object without network activity."""

    return P2PCacheService(workspace_root).plan_import(
        path,
        kind=kind,
        pin=pin,
    )


def import_p2p_cache_object(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Import an approved immutable object into the local CAS."""

    return P2PCacheService(workspace_root).import_object(
        plan,
        approved=approved,
    )


def plan_p2p_cache_fetch(
    object_hash: str,
    *,
    peer_ref: str,
    workspace_root: str | Path = ".",
    kind: str = "artifact",
    pin: bool = True,
) -> dict[str, Any]:
    """Preview an allowlisted peer fetch without exposing its endpoint ticket."""

    return P2PCacheService(workspace_root).plan_fetch(
        object_hash,
        peer_ref=peer_ref,
        kind=kind,
        pin=pin,
    )


def fetch_p2p_cache_object(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Fetch and atomically admit an approved Iroh object into the local CAS."""

    return P2PCacheService(workspace_root).fetch_object(
        plan,
        approved=approved,
    )


def read_p2p_cache_text(
    object_hash: str,
    *,
    workspace_root: str | Path = ".",
    offset: int = 0,
    length: int | None = None,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Read one bounded local text range without a peer round trip."""

    return P2PCacheService(workspace_root).read_text(
        object_hash,
        offset=offset,
        length=length,
        encoding=encoding,
    )


def get_p2p_cache_stats(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return bounded local object and byte totals."""

    return P2PCacheService(workspace_root).stats()


def get_p2p_provider_status(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return sanitized supervised-provider lifecycle status."""

    return P2PProviderService(workspace_root).status()


def plan_p2p_publication(
    object_hashes: list[str],
    *,
    peer_refs: list[str],
    workspace_root: str | Path = ".",
    actor: str = "agent",
) -> dict[str, Any]:
    """Preview a private provider activation without exposing transport data."""

    return P2PProviderService(workspace_root).plan_publication(
        object_hashes,
        peer_refs=peer_refs,
        actor=actor,
    )


def apply_p2p_publication(
    plan: dict[str, Any],
    *,
    workspace_root: str | Path = ".",
    approved: bool = False,
) -> dict[str, Any]:
    """Apply an approved, hash-bound provider activation or stop plan."""

    return P2PProviderService(workspace_root).apply_publication(
        plan,
        approved=approved,
    )


def get_p2p_provider_receipts(
    *,
    workspace_root: str | Path = ".",
    limit: int = 50,
) -> dict[str, Any]:
    """Read bounded provider receipts without endpoint IDs or tickets."""

    return P2PProviderService(workspace_root).receipts(limit=limit)


def build_module_package(
    source_root: str | Path,
    manifest: dict[str, Any],
    archive_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic module archive and finalized manifest."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).build_package(
        source_root,
        manifest,
        archive_path,
        manifest_path=manifest_path,
    )


def sign_module_package(
    manifest: dict[str, Any],
    archive_path: str | Path,
    *,
    key_reference: str = "keyless",
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Sign the finalized canonical manifest with keyless or external-key Cosign."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).sign_package(
        manifest,
        archive_path,
        key_reference=key_reference,
    )


def publish_module_package(
    manifest: dict[str, Any],
    archive_path: str | Path,
    *,
    install_receipt: dict[str, Any],
    published_by: str,
    registry_root: str | Path | None = None,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Publish a verified module to the content-addressed local/NAS seed."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).publish_to_local_registry(
        manifest,
        archive_path,
        install_receipt=install_receipt,
        published_by=published_by,
        registry_root=registry_root,
    )


def trust_module_publisher(
    manifest: dict[str, Any],
    *,
    approved_by: str,
    public_key_path: str | Path | None = None,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Create an explicit module-ID-to-publisher trust binding."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).trust_publisher(
        manifest,
        approved_by=approved_by,
        public_key_path=public_key_path,
    )


def review_module_permissions(
    manifest: dict[str, Any],
    *,
    approved_by: str,
    accepted_permissions: list[str],
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Bind an operator's permission decision to one exact package digest."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).build_permission_review(
        manifest,
        approved_by=approved_by,
        accepted_permissions=accepted_permissions,
    )


def install_module_package(
    manifest: dict[str, Any],
    archive_path: str | Path,
    *,
    permission_review: dict[str, Any],
    activate: bool = False,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify, quarantine, and atomically install a marketplace module."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).install_package(
        manifest,
        archive_path,
        permission_review=permission_review,
        activate=activate,
    )


def activate_installed_module(
    module_id: str,
    *,
    requested_by: str,
    version: str = "",
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Stage and activate a previously installed immutable module version."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).activate_installed_module(
        module_id,
        requested_by=requested_by,
        version=version,
    )


def list_installed_modules(
    *,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """List immutable installed versions and their active pointer state."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).installed_catalog()


def get_active_module_context(
    *,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
    max_modules: int = 50,
    max_context_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    """Return bounded, model-readable context for active modules."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).active_context_snapshot(
        max_modules=max_modules,
        max_context_bytes=max_context_bytes,
    )


def disable_module(
    module_id: str,
    *,
    requested_by: str,
    reason: str,
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Disable a module by pointer change without deleting its version."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).disable_module(
        module_id,
        requested_by=requested_by,
        reason=reason,
    )


def rollback_module(
    module_id: str,
    *,
    requested_by: str,
    reason: str,
    target_version: str = "",
    workspace_root: str | Path = ".",
    module_root: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically reactivate a previously verified module version."""

    return ModuleMarketplace(
        workspace_root,
        module_root=module_root,
    ).rollback_module(
        module_id,
        requested_by=requested_by,
        reason=reason,
        target_version=target_version,
    )


def get_install_profile_catalog(
    *,
    workspace_root: str | Path = ".",
) -> dict[str, Any]:
    """Return the truthful core/optional package catalog and delivery states."""

    return InstallProfileRegistry(workspace_root).catalog_snapshot()


@enforced("sv.sdk.plan-only")
def plan_install_profile(
    profile_id: str,
    *,
    workspace_root: str | Path = ".",
    selected_optional: list[str] | None = None,
    excluded_optional: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a profile without executing installs or hiding unfinished packs."""

    return InstallProfileRegistry(workspace_root).resolve(
        profile_id,
        selected_optional=selected_optional,
        excluded_optional=excluded_optional,
    )


# Compatibility alias for Neyvia-branded SDK callers.
NeyviaClient = FluxioClient
