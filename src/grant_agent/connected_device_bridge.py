from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import WorkspaceProfile, utc_now_iso
from .durability import file_transaction

BRIDGE_SCHEMA_VERSION = "connected-device-bridge/v1"
AUDIT_RELATIVE_PATH = ".agent_control/connected_device_bridge_audit.jsonl"
RECEIPTS_RELATIVE_PATH = ".agent_control/connected_device_bridge_receipts.jsonl"
PERMISSIONS_RELATIVE_PATH = ".agent_control/connected_device_bridge_permissions.json"
_GRANT_LOCKS = tuple(threading.RLock() for _ in range(64))


@dataclass
class PermissionGrant:
    capability: str
    state: str = "pending"
    scope: str = ""
    reason: str = ""
    granted_by: str = ""
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass
class FileRootScope:
    root_id: str
    path: str
    access: str = "read"
    permission_state: str = "pending"
    label: str = ""


@dataclass
class CommandCapability:
    command: str
    available: bool
    approval_required: bool = True
    permission_state: str = "pending"
    allowed_prefixes: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class ToolCapability:
    tool_id: str
    label: str
    available: bool
    permission_state: str = "pending"
    detail: str = ""


@dataclass
class AppSurfaceCapability:
    surface_id: str
    label: str
    surface_type: str
    available: bool
    permission_state: str = "pending"
    access: str = "inspect"


@dataclass
class GitHubAuthCapability:
    authenticated: bool = False
    source: str = ""
    username: str = ""
    permission_state: str = "pending"
    workflows: list[str] = field(default_factory=list)


@dataclass
class HostHealth:
    status: str = "unknown"
    checked_at: str = field(default_factory=utc_now_iso)
    detail: str = ""


@dataclass
class ConnectedHostManifest:
    host_id: str
    label: str
    host_type: str
    trust_level: str = "untrusted"
    permission_state: str = "pending"
    file_roots: list[FileRootScope] = field(default_factory=list)
    command_capabilities: list[CommandCapability] = field(default_factory=list)
    tool_capabilities: list[ToolCapability] = field(default_factory=list)
    app_surfaces: list[AppSurfaceCapability] = field(default_factory=list)
    github_auth: GitHubAuthCapability = field(default_factory=GitHubAuthCapability)
    permissions: list[PermissionGrant] = field(default_factory=list)
    last_health: HostHealth = field(default_factory=HostHealth)
    evidence: list[str] = field(default_factory=list)


@dataclass
class BridgeActionRequest:
    action_id: str
    action_type: str
    direction: str
    source_host: str
    target_host: str
    path: str = ""
    destination_path: str = ""
    command: str = ""
    surface_id: str = ""
    artifact_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BridgeActionDecision:
    action_id: str
    action_type: str
    direction: str
    source_host: str
    target_host: str
    performed_by_host: str
    status: str
    reason: str
    approval_required: bool = False
    sync_status: str = "not_applicable"
    result_status: str = "not_started"
    audit_event_id: str = ""
    timestamp: str = field(default_factory=utc_now_iso)
    evidence: list[str] = field(default_factory=list)


def _camelize_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def bridge_to_payload(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {_camelize_key(str(key)): bridge_to_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [bridge_to_payload(item) for item in value]
    return value


def _normal_state(value: object) -> str:
    state = str(value or "pending").strip().lower()
    return state if state in {"approved", "pending", "denied", "unavailable"} else "pending"


def _path_within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _host_lookup(hosts: list[ConnectedHostManifest]) -> dict[str, ConnectedHostManifest]:
    return {host.host_id: host for host in hosts}


def _capability_permission_state(host: ConnectedHostManifest, capability: str, scope: str = "") -> str:
    matches = [grant for grant in host.permissions if grant.capability == capability]
    if scope:
        scoped = [grant for grant in matches if not grant.scope or grant.scope == scope or _path_within(scope, grant.scope)]
        matches = scoped or matches
    if any(_normal_state(grant.state) == "approved" for grant in matches):
        return "approved"
    if any(_normal_state(grant.state) == "denied" for grant in matches):
        return "denied"
    return "pending"


def _required_file_capability(action_type: str) -> str:
    if action_type in {"write_file", "sync_file", "record_artifact", "record_receipt"}:
        return "file.write"
    return "file.read"


def _evaluate_file_action(host: ConnectedHostManifest, request: BridgeActionRequest) -> BridgeActionDecision:
    path = request.path or request.destination_path or request.artifact_path
    capability = _required_file_capability(request.action_type)
    roots = [root for root in host.file_roots if _path_within(path, root.path)]
    if not roots:
        return _decision(request, "denied", f"{path or 'target path'} is outside approved file roots", host.host_id)
    if request.action_type in {"write_file", "sync_file", "record_artifact", "record_receipt"}:
        roots = [root for root in roots if root.access in {"write", "read_write", "sync"}]
        if not roots:
            return _decision(request, "denied", "matching file root is read-only", host.host_id)
    state = "approved" if any(_normal_state(root.permission_state) == "approved" for root in roots) else "pending"
    grant_state = _capability_permission_state(host, capability, path)
    has_explicit_grants = any(grant.capability == capability for grant in host.permissions)
    if grant_state == "denied" or state == "denied":
        return _decision(request, "denied", f"{capability} was denied for {host.host_id}", host.host_id)
    # An approved FileRootScope is itself an explicit scoped grant. Additional
    # PermissionGrant rows can narrow/deny/prompt, but are not required when the
    # root scope already carries approval evidence.
    if state != "approved" or (has_explicit_grants and grant_state != "approved"):
        return _decision(request, "pending_approval", f"{capability} requires approval for {host.host_id}", host.host_id, approval=True)
    sync_status = "queued" if request.action_type == "sync_file" else "not_applicable"
    return _decision(request, "approved", f"{capability} allowed on {host.host_id}", host.host_id, sync_status=sync_status)


def _command_name(command: str) -> str:
    return str(command or "").strip().split()[0] if str(command or "").strip() else ""


def _unsafe_command_text(command: str) -> bool:
    value = str(command or "")
    if not value.strip():
        return False
    return any(token in value for token in (";", "&&", "||", "|", "`", "$(", ")", "\n", "\r", ">", "<"))


def _evaluate_command_action(host: ConnectedHostManifest, request: BridgeActionRequest) -> BridgeActionDecision:
    command_name = _command_name(request.command)
    if not command_name:
        return _decision(request, "denied", "command is required", host.host_id)
    capability = next((item for item in host.command_capabilities if item.command == command_name), None)
    if capability is None or not capability.available:
        return _decision(request, "denied", f"{command_name} is not available on {host.host_id}", host.host_id)
    if _unsafe_command_text(request.command):
        return _decision(request, "denied", "command contains unsafe shell operators and is outside bridge policy", host.host_id)
    if capability.allowed_prefixes and not any(request.command.startswith(prefix) for prefix in capability.allowed_prefixes):
        return _decision(request, "denied", f"{request.command} is outside allowed command prefixes", host.host_id)
    state = _normal_state(capability.permission_state)
    grant_state = _capability_permission_state(host, "command.run", command_name)
    if state == "denied" or grant_state == "denied":
        return _decision(request, "denied", f"command {command_name} was denied", host.host_id)
    if capability.approval_required and (state != "approved" or grant_state != "approved"):
        return _decision(request, "pending_approval", f"command {command_name} requires approval on {host.host_id}", host.host_id, approval=True)
    return _decision(request, "approved", f"command {command_name} allowed on {host.host_id}", host.host_id)


def _evaluate_github_action(host: ConnectedHostManifest, request: BridgeActionRequest) -> BridgeActionDecision:
    if not host.github_auth.authenticated:
        return _decision(request, "denied", f"GitHub auth is not available on {host.host_id}", host.host_id)
    if _normal_state(host.github_auth.permission_state) != "approved":
        return _decision(request, "pending_approval", f"GitHub auth use requires approval on {host.host_id}", host.host_id, approval=True)
    auth_grant = _capability_permission_state(host, "github.auth", "gh")
    if auth_grant == "denied":
        return _decision(request, "denied", "GitHub auth grant was denied", host.host_id)
    if auth_grant != "approved":
        return _decision(request, "pending_approval", "GitHub auth use requires approval", host.host_id, approval=True)
    if request.command:
        command_decision = _evaluate_command_action(host, request)
        if command_decision.status != "approved":
            return command_decision
    return _decision(request, "approved", f"GitHub authenticated workflow allowed on {host.host_id}", host.host_id)


def _evaluate_surface_action(host: ConnectedHostManifest, request: BridgeActionRequest) -> BridgeActionDecision:
    surface = next((item for item in host.app_surfaces if item.surface_id == request.surface_id), None)
    if surface is None or not surface.available:
        return _decision(request, "denied", f"surface {request.surface_id or '<missing>'} is unavailable", host.host_id)
    grant_state = _capability_permission_state(host, "surface.inspect", surface.surface_id)
    if grant_state == "denied" or _normal_state(surface.permission_state) == "denied":
        return _decision(request, "denied", f"surface {surface.surface_id} was denied", host.host_id)
    if _normal_state(surface.permission_state) != "approved" or grant_state != "approved":
        return _decision(request, "pending_approval", f"surface {surface.surface_id} requires approval", host.host_id, approval=True)
    return _decision(request, "approved", f"surface {surface.surface_id} can be inspected on {host.host_id}", host.host_id)


def _decision(
    request: BridgeActionRequest,
    status: str,
    reason: str,
    performed_by_host: str,
    *,
    approval: bool = False,
    sync_status: str = "not_applicable",
) -> BridgeActionDecision:
    return BridgeActionDecision(
        action_id=request.action_id,
        action_type=request.action_type,
        direction=request.direction,
        source_host=request.source_host,
        target_host=request.target_host,
        performed_by_host=performed_by_host,
        status=status,
        reason=reason,
        approval_required=approval,
        sync_status=sync_status,
        audit_event_id=f"bridge_{utc_now_iso().replace(':', '').replace('.', '')}_{request.action_id}",
        evidence=[f"host={performed_by_host}", f"direction={request.direction}", f"status={status}"],
    )


def evaluate_bridge_action(
    hosts: list[ConnectedHostManifest],
    request: BridgeActionRequest,
    *,
    audit_root: str | Path | None = None,
) -> BridgeActionDecision:
    lookup = _host_lookup(hosts)
    source = lookup.get(request.source_host)
    target = lookup.get(request.target_host)
    if source is None:
        decision = _decision(request, "denied", f"source host {request.source_host} is not connected", request.source_host)
    elif target is None:
        decision = _decision(request, "denied", f"target host {request.target_host} is not connected", request.target_host)
    elif request.direction == "nas_to_local" and (request.source_host != "nas" or request.target_host != "local"):
        decision = _decision(request, "denied", "direction nas_to_local requires source=nas and target=local", target.host_id)
    elif request.direction == "local_to_nas" and (request.source_host != "local" or request.target_host != "nas"):
        decision = _decision(request, "denied", "direction local_to_nas requires source=local and target=nas", target.host_id)
    elif request.action_type in {"read_file", "write_file", "sync_file", "record_artifact", "record_receipt"}:
        decision = _evaluate_file_action(target, request)
    elif request.action_type == "run_command":
        decision = _evaluate_command_action(target, request)
    elif request.action_type == "use_github_auth":
        decision = _evaluate_github_action(target, request)
    elif request.action_type in {"inspect_browser", "inspect_app_window", "inspect_window"}:
        decision = _evaluate_surface_action(target, request)
    else:
        decision = _decision(request, "denied", f"unsupported bridge action type: {request.action_type}", target.host_id)
    from .proofs_a_control import check_bridge_decision
    check_bridge_decision(hosts, request, decision)
    if audit_root is not None:
        record_bridge_audit_event(audit_root, decision)
    return decision


def record_bridge_audit_event(root: str | Path, decision: BridgeActionDecision) -> Path:
    return _append_jsonl(Path(root) / AUDIT_RELATIVE_PATH, bridge_to_payload(decision))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> Path:
    # Windows append handles can independently seek to the same EOF. Guard the
    # complete append and durable publication with the existing transaction.
    with file_transaction(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return path


def load_bridge_receipts(root: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    receipt_path = Path(root) / RECEIPTS_RELATIVE_PATH
    if not receipt_path.exists():
        return []
    rows = []
    with file_transaction(receipt_path):
        lines = receipt_path.read_text(encoding="utf-8").splitlines()[-limit:]
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _feedback_record(value: Any, *, fallback_key: str = "summary") -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    text = str(value or "").strip()
    return {fallback_key: text} if text else {}


def build_live_review_structured_feedback_receipt(
    *,
    event_id: str,
    route_context: Any = None,
    task_context: Any = None,
    verifier_feedback: Any = None,
    planner_executor_handoff_id: str = "",
    audit_root: str | Path | None = None,
    next_idea: str = "",
    source: str = "live-review",
) -> dict[str, Any]:
    """Persist the backend receipt for a Live Review structured-feedback handoff.

    The Live Review UI emits ``agent:structured-feedback`` when an operator turns
    visual review notes into agent-facing guidance. This receipt is the product
    path that proves the backend received that event and preserved the routing,
    task, verifier, timestamp, and planner/executor handoff context needed for a
    later agent turn.
    """
    clean_event_id = str(event_id or "").strip()
    if not clean_event_id:
        raise ValueError("event_id is required for Live Review structured feedback receipts")
    handoff_id = str(planner_executor_handoff_id or "").strip() or f"handoff:{clean_event_id}"
    receipt = {
        "schemaVersion": BRIDGE_SCHEMA_VERSION,
        "receiptKind": "live_review_structured_feedback",
        "eventName": "agent:structured-feedback",
        "eventId": clean_event_id,
        "source": str(source or "live-review"),
        "plannerExecutorHandoffId": handoff_id,
        "timestamp": utc_now_iso(),
        "routeContext": _feedback_record(route_context, fallback_key="route"),
        "taskContext": _feedback_record(task_context, fallback_key="task"),
        "verifierFeedback": _feedback_record(verifier_feedback, fallback_key="summary"),
        "nextIdea": str(next_idea or "").strip(),
        "status": "received",
        "evidence": [
            "backend received Live Review agent:structured-feedback",
            "receipt preserves event id, route context, task context, verifier feedback, timestamp, and planner/executor handoff id",
        ],
    }
    if audit_root is not None:
        _append_jsonl(Path(audit_root) / RECEIPTS_RELATIVE_PATH, receipt)
    from .proofs_a_control import check_bridge_feedback
    check_bridge_feedback(receipt, clean_event_id, handoff_id, route_context, task_context, verifier_feedback, next_idea)
    return receipt


def build_bridge_operation_receipt(
    hosts: list[ConnectedHostManifest],
    actions: list[BridgeActionRequest],
    *,
    operation_id: str,
    audit_root: str | Path | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Plan/evaluate a multi-step bridge operation and persist an auditable receipt.

    This intentionally does not run commands or copy files. It proves whether a
    proposed local<->NAS action sequence is inside the currently approved bridge
    surface. A later executor can consume only receipts whose status is approved.
    """
    decisions = [evaluate_bridge_action(hosts, action, audit_root=audit_root) for action in actions]
    steps = []
    pending = []
    denials = []
    host_status: dict[str, str] = {}
    for decision in decisions:
        step = bridge_to_payload(decision)
        step["resultStatus"] = "executed" if execute and decision.status == "approved" else "not_executed"
        steps.append(step)
        host_id = decision.performed_by_host
        previous = host_status.get(host_id, "approved")
        if decision.status == "denied" or previous == "denied":
            host_status[host_id] = "denied"
        elif decision.status == "pending_approval" or previous == "pending_approval":
            host_status[host_id] = "pending_approval"
        else:
            host_status[host_id] = "approved"
        if decision.status == "pending_approval":
            pending.append({"actionId": decision.action_id, "hostId": host_id, "reason": decision.reason})
        elif decision.status == "denied":
            denials.append({"actionId": decision.action_id, "hostId": host_id, "reason": decision.reason})
    if denials:
        status = "denied"
    elif pending:
        status = "pending_approval"
    elif decisions:
        status = "approved"
    else:
        status = "empty"
    receipt = {
        "schemaVersion": BRIDGE_SCHEMA_VERSION,
        "operationId": str(operation_id or "bridge_operation"),
        "status": status,
        "executeMode": "execute" if execute else "plan_only",
        "createdAt": utc_now_iso(),
        "steps": steps,
        "hostStatus": host_status,
        "pendingApprovals": pending,
        "denials": denials,
        "syncStatus": [step for step in steps if step.get("syncStatus") not in {"", "not_applicable", None}],
        "evidence": [
            "bridge receipt is auditable and plan-only unless an approved executor consumes it",
            "each step includes performedByHost, approvalRequired, syncStatus, and auditEventId",
        ],
    }
    if audit_root is not None:
        _append_jsonl(Path(audit_root) / RECEIPTS_RELATIVE_PATH, receipt)
    from .proofs_a_control import check_bridge_receipt
    check_bridge_receipt(decisions, receipt, execute)
    return receipt


def load_bridge_audit_events(root: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    audit_path = Path(root) / AUDIT_RELATIVE_PATH
    if not audit_path.exists():
        return []
    rows = []
    for line in audit_path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _permission_from_payload(payload: Any) -> PermissionGrant | None:
    if not isinstance(payload, dict):
        return None
    capability = str(payload.get("capability") or "").strip()
    if not capability:
        return None
    return PermissionGrant(
        capability=capability,
        state=_normal_state(payload.get("state")),
        scope=str(payload.get("scope") or "").strip(),
        reason=str(payload.get("reason") or "").strip(),
        granted_by=str(payload.get("grantedBy") or payload.get("granted_by") or "").strip(),
        updated_at=str(payload.get("updatedAt") or payload.get("updated_at") or utc_now_iso()),
    )


def load_bridge_permission_grants(root: str | Path) -> dict[str, list[PermissionGrant]]:
    permission_path = Path(root) / PERMISSIONS_RELATIVE_PATH
    if not permission_path.exists():
        return {}
    from .harness_jobs import _exclusive_job_lock

    guard = _GRANT_LOCKS[hash(str(permission_path.resolve()).casefold()) % len(_GRANT_LOCKS)]
    with guard, _exclusive_job_lock(permission_path, timeout_seconds=30):
        return _load_bridge_permission_grants_locked(permission_path)


def _load_bridge_permission_grants_locked(permission_path: Path) -> dict[str, list[PermissionGrant]]:
    try:
        payload = json.loads(permission_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Existing bridge grants are unreadable; Neyvia refused to infer approval.") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != BRIDGE_SCHEMA_VERSION:
        raise RuntimeError("Existing bridge grants have an unsupported schema; approval was refused.")
    hosts = payload.get("hosts") if isinstance(payload, dict) else None
    if not isinstance(hosts, dict):
        raise RuntimeError("Existing bridge grants lack authoritative host records; approval was refused.")
    grants: dict[str, list[PermissionGrant]] = {}
    for host_id, rows in hosts.items():
        if not isinstance(rows, list):
            raise RuntimeError("Existing bridge host grants are malformed; approval was refused.")
        parsed = [grant for grant in (_permission_from_payload(row) for row in rows) if grant is not None]
        if len(parsed) != len(rows):
            raise RuntimeError("Existing bridge grant records are malformed; approval was refused.")
        if parsed:
            grants[str(host_id)] = parsed
    return grants


def save_bridge_permission_grants(root: str | Path, grants_by_host: dict[str, list[PermissionGrant]]) -> Path:
    from .harness_jobs import _exclusive_job_lock

    permission_path = Path(root) / PERMISSIONS_RELATIVE_PATH
    permission_path.parent.mkdir(parents=True, exist_ok=True)
    guard = _GRANT_LOCKS[hash(str(permission_path.resolve()).casefold()) % len(_GRANT_LOCKS)]
    with guard, _exclusive_job_lock(permission_path, timeout_seconds=30):
        return _save_bridge_permission_grants_locked(root, grants_by_host)


def _save_bridge_permission_grants_locked(root: str | Path, grants_by_host: dict[str, list[PermissionGrant]]) -> Path:
    from .durability import atomic_write_text

    permission_path = Path(root) / PERMISSIONS_RELATIVE_PATH
    permission_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": BRIDGE_SCHEMA_VERSION,
        "updatedAt": utc_now_iso(),
        "hosts": {
            host_id: [bridge_to_payload(grant) for grant in grants]
            for host_id, grants in sorted(grants_by_host.items())
        },
    }
    atomic_write_text(permission_path, json.dumps(payload, indent=2, sort_keys=True))
    from .proofs_a_control import require
    require(json.loads(permission_path.read_text(encoding="utf-8")) == payload,
            "control.bridge-grants", "persisted host grants differ from approved transaction")
    return permission_path


def upsert_bridge_permission_grant(root: str | Path, host_id: str, grant: PermissionGrant) -> Path:
    host_key = str(host_id or "").strip()
    if not host_key:
        raise ValueError("host_id is required")
    grant.updated_at = utc_now_iso()
    grants_by_host = load_bridge_permission_grants(root)
    existing = grants_by_host.get(host_key, [])
    replaced = False
    next_rows: list[PermissionGrant] = []
    for row in existing:
        if row.capability == grant.capability and row.scope == grant.scope:
            next_rows.append(grant)
            replaced = True
        else:
            next_rows.append(row)
    if not replaced:
        next_rows.append(grant)
    grants_by_host[host_key] = next_rows
    path = save_bridge_permission_grants(root, grants_by_host)
    record_bridge_audit_event(
        root,
        BridgeActionDecision(
            action_id=f"permission_{grant.capability}_{grant.scope or 'all'}".replace("/", "_"),
            action_type="permission_grant",
            direction="operator_to_bridge",
            source_host="operator",
            target_host=host_key,
            performed_by_host=host_key,
            status=_normal_state(grant.state),
            reason=grant.reason or f"{grant.capability} {grant.state} for {host_key}",
            evidence=[f"host={host_key}", f"capability={grant.capability}", f"scope={grant.scope}", f"status={grant.state}"],
        ),
    )
    return path


def _merge_persisted_permission_grants(
    host: ConnectedHostManifest,
    persisted: dict[str, list[PermissionGrant]],
) -> None:
    rows = persisted.get(host.host_id, [])
    if not rows:
        return
    merged: dict[tuple[str, str], PermissionGrant] = {
        (grant.capability, grant.scope): grant for grant in host.permissions
    }
    for grant in rows:
        merged[(grant.capability, grant.scope)] = grant
    host.permissions = list(merged.values())
    for capability in host.command_capabilities:
        state = _capability_permission_state(host, "command.run", capability.command)
        if state in {"approved", "denied"}:
            capability.permission_state = state
    auth_state = _capability_permission_state(host, "github.auth", "gh")
    if auth_state in {"approved", "denied"}:
        host.github_auth.permission_state = auth_state
    for root in host.file_roots:
        read_state = _capability_permission_state(host, "file.read", root.path)
        write_state = _capability_permission_state(host, "file.write", root.path)
        if root.access in {"write", "read_write", "sync"} and write_state in {"approved", "denied"}:
            root.permission_state = write_state
        elif read_state in {"approved", "denied"}:
            root.permission_state = read_state


def _command_available(host_id: str, command: str, command_presence: dict[str, dict[str, bool]] | None) -> bool:
    if command_presence and host_id in command_presence and command in command_presence[host_id]:
        return bool(command_presence[host_id][command])
    if host_id == "local":
        return shutil.which(command) is not None
    return False


def _local_project_roots(workspaces: list[WorkspaceProfile]) -> list[str]:
    roots = []
    for workspace in workspaces:
        local_path = str(workspace.local_project_path or "").strip()
        if local_path and local_path not in roots:
            roots.append(local_path)
    return roots


def _nas_project_roots(root: Path, workspaces: list[WorkspaceProfile]) -> list[str]:
    roots = []
    for workspace in workspaces:
        for value in (workspace.nas_project_path, workspace.root_path):
            path = str(value or "").strip()
            if path and path not in roots:
                roots.append(path)
    if not roots:
        roots.append(str(root))
    return roots


def build_connected_host_manifests(
    root: str | Path,
    *,
    workspaces: list[WorkspaceProfile] | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
    command_presence: dict[str, dict[str, bool]] | None = None,
) -> list[ConnectedHostManifest]:
    root_path = Path(root)
    workspaces = workspaces or []
    provider_auth_presence = provider_auth_presence or {}
    local_roots = _local_project_roots(workspaces)
    nas_roots = _nas_project_roots(root_path, workspaces)
    local_gh = _command_available("local", "gh", command_presence)
    local_git = _command_available("local", "git", command_presence)
    nas_gh = _command_available("nas", "gh", command_presence)
    nas_git = _command_available("nas", "git", command_presence)
    github_authenticated = bool(
        provider_auth_presence.get("github")
        or provider_auth_presence.get("gh")
        or provider_auth_presence.get("openai-codex")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )

    local_permissions = []
    for path in local_roots:
        local_permissions.extend(
            [
                PermissionGrant("file.read", "approved", path, "workspace-linked local root"),
                PermissionGrant("file.write", "approved", path, "workspace-linked local root"),
            ]
        )
    if local_gh:
        local_permissions.append(PermissionGrant("command.run", "pending", "gh", "explicit approval required before local gh runs"))
    if local_git:
        local_permissions.append(PermissionGrant("command.run", "pending", "git", "explicit approval required before local git runs"))
    if github_authenticated:
        local_permissions.append(PermissionGrant("github.auth", "pending", "gh", "explicit approval required before using local GitHub identity"))
    local_permissions.append(PermissionGrant("surface.inspect", "pending", "browser", "explicit approval required before inspecting local browser/window surfaces"))

    local = ConnectedHostManifest(
        host_id="local",
        label="Local Codex computer",
        host_type="local_computer",
        trust_level="paired" if local_roots or local_gh or local_git else "discovered",
        permission_state="pending",
        file_roots=[FileRootScope(f"local-{idx}", path, "read_write", "approved", "Local project root") for idx, path in enumerate(local_roots, 1)],
        command_capabilities=[
            CommandCapability("git", local_git, True, "pending", ["git status", "git diff", "git add", "git commit", "git push", "git pull", "git checkout", "git merge"], "Local git CLI"),
            CommandCapability("gh", local_gh, True, "pending", ["gh auth status", "gh repo", "gh pr", "gh issue", "gh workflow", "gh run"], "Local GitHub CLI"),
        ],
        tool_capabilities=[ToolCapability("codex", "Local Codex runtime", True, "pending", "Can inspect/run local Codex sessions when paired")],
        app_surfaces=[AppSurfaceCapability("browser", "Local browser/computer-use surface", "browser", True, "pending")],
        github_auth=GitHubAuthCapability(github_authenticated, "gh-cli-or-token" if github_authenticated else "", permission_state="pending", workflows=["pr", "merge", "release", "workflow"]),
        permissions=local_permissions,
        last_health=HostHealth("ready" if local_roots or local_gh or local_git else "limited", detail="Local bridge endpoint discovered from workspace configuration"),
        evidence=["local host is explicit; file/command use still requires scoped grants"],
    )

    nas = ConnectedHostManifest(
        host_id="nas",
        label="NAS/Syntelos runtime",
        host_type="nas_runtime",
        trust_level="runtime_owner",
        permission_state="approved",
        file_roots=[FileRootScope(f"nas-{idx}", path, "read_write", "approved", "NAS workspace root") for idx, path in enumerate(nas_roots, 1)],
        command_capabilities=[
            CommandCapability("git", nas_git, True, "approved" if nas_git else "unavailable", detail="NAS git CLI"),
            CommandCapability("gh", nas_gh, True, "approved" if nas_gh else "unavailable", detail="NAS GitHub CLI"),
        ],
        tool_capabilities=[ToolCapability("syntelos-runtime", "Syntelos runtime sessions", True, "approved", "Runtime sessions/artifacts/receipts under .agent_control")],
        permissions=[PermissionGrant("file.read", "approved", path) for path in nas_roots]
        + [PermissionGrant("file.write", "approved", path) for path in nas_roots],
        last_health=HostHealth("ready", detail="Current backend root is the NAS/runtime side of the bridge"),
        evidence=["NAS runtime can expose workspace artifacts and receipts through audited bridge state"],
    )
    persisted_grants = load_bridge_permission_grants(root_path)
    for host in (local, nas):
        _merge_persisted_permission_grants(host, persisted_grants)
    return [local, nas]


def _sync_rows(workspaces: list[WorkspaceProfile]) -> list[dict[str, Any]]:
    rows = []
    for workspace in workspaces:
        if not (workspace.local_project_path or workspace.nas_project_path):
            continue
        rows.append(
            {
                "workspaceId": workspace.workspace_id,
                "localPath": workspace.local_project_path,
                "nasPath": workspace.nas_project_path or workspace.root_path,
                "mode": workspace.sync_mode,
                "direction": workspace.sync_direction,
                "conflictPolicy": workspace.sync_conflict_policy,
                "status": "ready" if workspace.local_project_path and (workspace.nas_project_path or workspace.root_path) else "needs_mapping",
                "lastCheckedAt": utc_now_iso(),
            }
        )
    return rows


def manual_github_bridge_actions(nas_root: str, local_root: str) -> list[BridgeActionRequest]:
    return [
        BridgeActionRequest("sync_nas_to_local", "sync_file", "nas_to_local", "nas", "local", path=str(local_root), destination_path=str(local_root)),
        BridgeActionRequest("local_gh_merge", "use_github_auth", "nas_to_local", "nas", "local", command="gh pr merge --merge"),
        BridgeActionRequest("sync_result_to_nas", "sync_file", "local_to_nas", "local", "nas", path=str(nas_root), destination_path=str(nas_root)),
    ]


def _manual_github_bridge_summary(hosts: list[ConnectedHostManifest], sync_rows: list[dict[str, Any]]) -> dict[str, Any]:
    lookup = _host_lookup(hosts)
    local = lookup.get("local")
    nas = lookup.get("nas")
    local_commands = {item.command: item.available for item in (local.command_capabilities if local else [])}
    nas_commands = {item.command: item.available for item in (nas.command_capabilities if nas else [])}
    viable = bool(sync_rows and local_commands.get("gh") and local_commands.get("git") and not (nas_commands.get("gh") and nas_commands.get("git")))
    return {
        "available": viable,
        "summary": "Local gh/git can perform authenticated GitHub work for NAS workspaces, then sync results back to NAS." if viable else "Manual GitHub bridge needs local gh/git, workspace mapping, and approval before use.",
        "requiredApprovals": ["local file read/write scope", "local git/gh command scope", "local GitHub auth use", "NAS result sync scope"],
        "referenceFlow": ["sync NAS workspace slice to local", "run approved local gh/git workflow", "record receipt", "sync result back to NAS"],
    }


def build_dual_path_bridge_snapshot(
    root: str | Path,
    *,
    workspaces: list[WorkspaceProfile] | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
    command_presence: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    workspaces = workspaces or []
    hosts = build_connected_host_manifests(
        root_path,
        workspaces=workspaces,
        provider_auth_presence=provider_auth_presence,
        command_presence=command_presence,
    )
    sync_rows = _sync_rows(workspaces)
    pending = []
    denials = []
    for host in hosts:
        for grant in host.permissions:
            state = _normal_state(grant.state)
            if state == "pending":
                pending.append({"hostId": host.host_id, "capability": grant.capability, "scope": grant.scope, "reason": grant.reason})
            elif state == "denied":
                denials.append({"hostId": host.host_id, "capability": grant.capability, "scope": grant.scope, "reason": grant.reason})
    status = "ready" if sync_rows else "needs_mapping"
    result = {
        "schemaVersion": BRIDGE_SCHEMA_VERSION,
        "status": status,
        "hosts": bridge_to_payload(hosts),
        "sync": sync_rows,
        "pendingApprovals": pending,
        "denials": denials,
        "auditTrail": load_bridge_audit_events(root_path),
        "receipts": load_bridge_receipts(root_path),
        "manualGitHubBridge": _manual_github_bridge_summary(hosts, sync_rows),
        "uiEvidence": {
            "hostBadgesRequired": True,
            "actionRowsIncludePerformedByHost": True,
            "pendingApprovalVisible": bool(pending),
            "denialsVisible": bool(denials),
        },
        "lastHealthAt": utc_now_iso(),
    }
    from .proofs_a_control import require
    require(result["hosts"] == bridge_to_payload(hosts) and result["sync"] == sync_rows
            and result["pendingApprovals"] == pending and result["denials"] == denials
            and result["uiEvidence"]["pendingApprovalVisible"] == bool(pending)
            and result["uiEvidence"]["denialsVisible"] == bool(denials),
            "control.bridge-snapshot", "snapshot omitted current host authority or mapping/pending visibility")
    return result
