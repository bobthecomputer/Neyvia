from __future__ import annotations

import json
import platform
import socket
from pathlib import Path
from typing import Any

from .cluster import ClusterRegistry, current_host_id
from .models import utc_now_iso
from .proofs_b_desktop import checked

DESKTOP_GATEWAY_HEARTBEAT_SCHEMA = "fluxio.desktop_gateway_heartbeat.v1"
DESKTOP_GATEWAY_ROUTE_SCHEMA = "fluxio.desktop_gateway_route.v1"
DESKTOP_GATEWAY_RECONCILE_SCHEMA = "fluxio.desktop_gateway_reconcile.v1"
DESKTOP_GATEWAY_EVENT_SCHEMA = "fluxio.desktop_gateway_event.v1"
DESKTOP_GATEWAY_HEARTBEATS_PATH = ".agent_control/desktop_gateway/heartbeats.jsonl"
DESKTOP_GATEWAY_EVENTS_PATH = ".agent_control/desktop_gateway/events.jsonl"
GATEWAY_JOB_CAPABILITIES = {"browser.verify", "frontend.build", "heavy.verifier"}


@checked("desktop.gateway.heartbeat")
def record_desktop_gateway_heartbeat(
    root: str | Path,
    *,
    host_id: str = "",
    label: str = "",
    tailscale_ip: str = "",
    local_workspace: str = "",
    nas_workspace: str = "",
    current_load: int = 0,
) -> dict[str, Any]:
    resolved_host_id = str(host_id or current_host_id()).strip()
    capabilities = [
        "pc.gateway",
        "browser.verify",
        "frontend.build",
        "heavy.verifier",
        "artifact.write",
    ]
    workspace_mappings = {}
    if local_workspace and nas_workspace:
        workspace_mappings[str(nas_workspace)] = str(local_workspace)
    registry = ClusterRegistry(root)
    heartbeat = registry.heartbeat_host(
        {
            "hostId": resolved_host_id,
            "label": label or resolved_host_id,
            "hostType": "pc_gateway",
            "role": "accelerator",
            "tailscaleIp": tailscale_ip,
            "osName": platform.system().lower(),
            "capabilities": capabilities,
            "runtimes": ["codex"],
            "workspaceMappings": workspace_mappings,
            "maxConcurrentJobs": 0,
            "currentLoad": current_load,
        }
    )
    receipt = {
        "schema": DESKTOP_GATEWAY_HEARTBEAT_SCHEMA,
        "hostId": resolved_host_id,
        "status": "online",
        "heartbeatAt": utc_now_iso(),
        "clusterHost": heartbeat.get("host", {}),
        "capabilities": capabilities,
        "workspaceMappings": workspace_mappings,
        "nextAction": "NAS can route browser/build/heavy verifier jobs here while this heartbeat is fresh.",
    }
    _append_gateway_heartbeat(root, receipt)
    return receipt


def load_desktop_gateway_heartbeats(root: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    path = Path(root) / DESKTOP_GATEWAY_HEARTBEATS_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit or 1)) :]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def route_gateway_job(
    root: str | Path,
    *,
    job_kind: str,
    required_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    from .proofs_b_desktop import check
    def outcome(result, selected_host=None):
        # Validate the same host snapshot used by the routing decision, so a
        # subsequent concurrent heartbeat cannot invalidate an earlier decision.
        check("desktop.gateway.route", {"root": root, "required_capabilities": required_capabilities, "selected_host": selected_host}, result)
        return result
    required = {str(item).strip() for item in (required_capabilities or []) if str(item or "").strip()}
    if not required & GATEWAY_JOB_CAPABILITIES:
        return outcome({
            "schema": DESKTOP_GATEWAY_ROUTE_SCHEMA,
            "jobKind": job_kind,
            "decision": "controller",
            "assignedHost": "",
            "requiredCapabilities": sorted(required),
            "reason": "Job does not require PC gateway acceleration.",
        })
    registry = ClusterRegistry(root)
    for host in registry.list_hosts():
        capabilities = {str(item) for item in host.get("capabilities", [])}
        if (
            host.get("online")
            and host.get("hostType") == "pc_gateway"
            and required.issubset(capabilities)
        ):
            return outcome({
                "schema": DESKTOP_GATEWAY_ROUTE_SCHEMA,
                "jobKind": job_kind,
                "decision": "pc_gateway",
                "assignedHost": host.get("hostId", ""),
                "requiredCapabilities": sorted(required),
                "reason": "Online PC gateway has the required browser/build/heavy verifier capabilities.",
            }, host)
    return outcome({
        "schema": DESKTOP_GATEWAY_ROUTE_SCHEMA,
        "jobKind": job_kind,
        "decision": "queued_proof_gap",
        "assignedHost": "",
        "requiredCapabilities": sorted(required),
        "reason": "No online PC gateway currently has the required capabilities.",
    })


@checked("desktop.gateway.reconcile")
def reconcile_disappeared_gateway_jobs(root: str | Path, *, limit: int = 100) -> dict[str, Any]:
    registry = ClusterRegistry(root)
    converted: list[dict[str, Any]] = []
    for job in registry.list_jobs(limit=limit):
        status = str(job.get("status") or "").lower()
        assigned_host = str(job.get("assignedHost") or "")
        required = {str(item) for item in job.get("requiredCapabilities", [])}
        if status not in {"leased", "running"} or not assigned_host or not (required & GATEWAY_JOB_CAPABILITIES):
            continue
        host = registry.get_host(assigned_host)
        if host.get("online") and host.get("hostType") == "pc_gateway":
            continue
        detail = "Queued proof gap: PC gateway disappeared before gateway proof completed."
        updated = registry.update_job_status(str(job.get("jobId") or ""), "queued", status_detail=detail)
        registry.record_event(
            job_id=str(job.get("jobId") or ""),
            host_id=assigned_host,
            kind="gateway.proof_gap_queued",
            message=detail,
            payload={"previousStatus": status, "requiredCapabilities": sorted(required)},
        )
        converted.append(
            {
                "jobId": job.get("jobId", ""),
                "assignedHost": assigned_host,
                "previousStatus": status,
                "status": updated.get("status", ""),
                "statusDetail": updated.get("statusDetail", ""),
            }
        )
    return {
        "schema": DESKTOP_GATEWAY_RECONCILE_SCHEMA,
        "convertedCount": len(converted),
        "converted": converted,
        "nextAction": (
            "Leave converted jobs queued until a PC gateway returns or a headless proof path is sufficient."
            if converted
            else "No active gateway jobs needed proof-gap conversion."
        ),
    }


@checked("desktop.gateway.event")
def record_gateway_event(
    root: str | Path,
    *,
    host_id: str,
    job_id: str = "",
    event_kind: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "schema": DESKTOP_GATEWAY_EVENT_SCHEMA,
        "hostId": str(host_id or ""),
        "jobId": str(job_id or ""),
        "eventKind": str(event_kind or ""),
        "message": str(message or ""),
        "payload": dict(payload or {}),
        "createdAt": utc_now_iso(),
    }
    path = Path(root) / DESKTOP_GATEWAY_EVENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
    if job_id:
        ClusterRegistry(root).record_event(
            job_id=job_id,
            host_id=host_id,
            kind=f"gateway.{event_kind}",
            message=message,
            payload=payload or {},
        )
    return event


def load_gateway_events(root: str | Path, *, limit: int = 50, job_id: str = "") -> list[dict[str, Any]]:
    path = Path(root) / DESKTOP_GATEWAY_EVENTS_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    target = str(job_id or "")
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit or 1)) :]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if target and str(value.get("jobId") or "") != target:
            continue
        rows.append(value)
    return rows


def _append_gateway_heartbeat(root: str | Path, payload: dict[str, Any]) -> None:
    path = Path(root) / DESKTOP_GATEWAY_HEARTBEATS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
