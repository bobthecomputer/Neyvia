from __future__ import annotations

from .subprocess_utils import windows_pid_alive as _windows_pid_alive

import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import uuid
from collections import deque
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
import time

from .cluster import (
    ClusterRegistry,
    _same_host_id,
    build_local_worker_capabilities,
    current_host_id,
    current_host_type,
)
from .models import (
    DelegatedApprovalRequest,
    DelegatedRuntimeEvent,
    DelegatedRuntimeSession,
    DelegatedSessionSnapshot,
    Mission,
    WorkspaceProfile,
    utc_now_iso,
)
from .execution_truth import derive_execution_target
from .proofs_a_cli_scheduler import check_rehome
from .runtimes import runtime_adapter_map
from .runtimes.base import runtime_subprocess_env, runtime_which
from .platform_config import platform_config
from .subprocess_utils import background_creationflags, hidden_windows_subprocess_kwargs
from .durability import file_transaction

HEARTBEAT_STALE_FLOOR_SECONDS = max(
    int(os.environ.get("FLUXIO_HEARTBEAT_STALE_SECONDS", "35")),
    5,
)
SESSION_SETTLE_TIMEOUT_SECONDS = max(
    float(os.environ.get("FLUXIO_SESSION_SETTLE_SECONDS", "0.9")),
    0.0,
)
SESSION_QUICK_EXIT_GRACE_SECONDS = max(
    float(os.environ.get("FLUXIO_SESSION_QUICK_EXIT_GRACE_SECONDS", "0.45")),
    0.0,
)
RUNTIME_AUTH_PREFLIGHT_ENABLED = str(
    os.environ.get("FLUXIO_RUNTIME_AUTH_PREFLIGHT", "1")
).strip().lower() not in {"0", "false", "no", "off"}
RUNTIME_AUTH_PREFLIGHT_TIMEOUT_SECONDS = max(
    float(os.environ.get("FLUXIO_RUNTIME_AUTH_PREFLIGHT_TIMEOUT_SECONDS", "45")),
    10.0,
)

DELEGATED_RUNTIME_SESSION_FIELD_NAMES = {
    item.name for item in fields(DelegatedRuntimeSession)
}
SESSION_SETTLE_POLL_SECONDS = max(
    float(os.environ.get("FLUXIO_SESSION_SETTLE_POLL_SECONDS", "0.05")),
    0.01,
)
PID_ALIVE_CACHE_TTL_SECONDS = max(
    float(os.environ.get("FLUXIO_PID_CACHE_TTL_SECONDS", "0.35")),
    0.0,
)
PID_ALIVE_CACHE_MAX_SIZE = max(
    int(os.environ.get("FLUXIO_PID_CACHE_MAX_SIZE", "512")),
    64,
)
_PID_ALIVE_CACHE: dict[int, tuple[float, bool]] = {}


def _mission_coordination_payload(
    root: Path,
    mission: Mission,
    *,
    project_workspace_id: str,
) -> dict:
    awareness = str(
        getattr(getattr(mission, "state", None), "cross_mission_awareness", "observe")
        or "observe"
    ).strip().lower()
    if awareness not in {"off", "observe", "adapt"}:
        awareness = "observe"
    peers: list[dict] = []
    if awareness != "off":
        try:
            stored = json.loads((root / ".agent_control" / "missions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            stored = []
        if isinstance(stored, dict):
            stored = stored.get("missions") or stored.get("items") or []
        for item in stored if isinstance(stored, list) else []:
            if not isinstance(item, dict):
                continue
            mission_id = str(item.get("mission_id") or item.get("missionId") or "").strip()
            if not mission_id or mission_id == mission.mission_id:
                continue
            if str(item.get("workspace_id") or item.get("workspaceId") or "") != project_workspace_id:
                continue
            state = item.get("state") if isinstance(item.get("state"), dict) else {}
            status = str(state.get("status") or item.get("status") or "draft").strip().lower()
            if status in {"draft", "created", "stopped"}:
                continue
            scope = item.get("execution_scope") if isinstance(item.get("execution_scope"), dict) else {}
            proof = item.get("proof") if isinstance(item.get("proof"), dict) else {}
            peers.append(
                {
                    "missionId": mission_id,
                    "title": str(item.get("title") or item.get("objective") or "")[:240],
                    "objective": str(item.get("objective") or "")[:600],
                    "status": status,
                    "plannedFileScope": list(item.get("planned_file_scope") or ["."])[:80],
                    "changedFiles": list(proof.get("changed_files") or [])[:120],
                    "executionRoot": str(scope.get("execution_root") or scope.get("worktree_path") or ""),
                    "updatedAt": str(item.get("updated_at") or state.get("updated_at") or ""),
                }
            )
    return {
        "schema": "neyvia.mission_coordination.v1",
        "generatedAt": utc_now_iso(),
        "missionId": str(mission.mission_id or ""),
        "projectWorkspaceId": project_workspace_id,
        "awareness": awareness,
        "rules": [
            "Sibling worktrees are read-only context.",
            "Adapt only public interfaces, schemas, and declared intent relevant to this mission.",
            "Record compatibility decisions in this mission's proof; never merge a peer worktree directly.",
        ],
        "peers": peers,
    }


def _write_mission_coordination_manifest(execution_root: Path, payload: dict) -> Path:
    manifest_path = execution_root / ".agent_control" / "mission_coordination" / "current.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest_path


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off", ""}


def _hermetic_blocks_live_hermes_launch(launch_command: object) -> bool:
    """Block only real Hermes CLI launches during hermetic pytest runs."""
    if not _env_flag("NEYVIA_HERMETIC_TESTS", default=False):
        return False
    if _env_flag("NEYVIA_ALLOW_LIVE_HERMES", default=False):
        return False
    text = str(launch_command or "").strip().lower()
    if "hermes" not in text:
        return False
    # Unit tests often drive a python -c / temp worker while runtime_id remains hermes.
    if "python" in text and (" -c " in f" {text} " or text.rstrip().endswith("-c")):
        return False
    return any(
        token in text
        for token in (
            "hermes chat",
            "hermes --",
            "hermes.exe",
            "/hermes",
            "\\hermes",
            "wsl ",
        )
    )


from .proofs_a_cli import checked


@checked('a-cli.scheduler.roles')
def _cluster_required_capabilities(session: DelegatedRuntimeSession) -> list[str]:
    required = ["runtime.launch"]
    route_text = " ".join([session.target_role, session.target_phase]).lower()
    if any(token in route_text for token in ("browser", "playwright", "frontend", "ui")):
        required.append("browser.verify")
    return sorted(set(required))


def _cluster_job_dedupe_key(
    session: DelegatedRuntimeSession,
    *,
    mission_id: str = "",
    workspace_id: str = "",
) -> str:
    material = {
        "missionId": str(mission_id or session.mission_id or "").strip(),
        "workspaceId": str(workspace_id or "").strip(),
        "sourceStepId": str(session.source_step_id or "").strip(),
        "runtimeId": str(session.runtime_id or "").strip().lower(),
        "executionRoot": str(session.execution_root or session.workspace_root or "").strip(),
        "phase": str(session.target_phase or "").strip().lower(),
        "role": str(session.target_role or "").strip().lower(),
        "provider": str(session.target_provider or "").strip().lower(),
        "model": str(session.target_model or "").strip().lower(),
        "effort": str(session.target_effort or "").strip().lower(),
        "command": str(session.launch_command or "").strip(),
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"runtime_lane:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _apply_cluster_assignment_to_session(
    session: DelegatedRuntimeSession,
    assignment: dict,
) -> DelegatedRuntimeSession:
    job = assignment.get("job") if isinstance(assignment.get("job"), dict) else {}
    lease = assignment.get("lease") if isinstance(assignment.get("lease"), dict) else {}
    host = assignment.get("host") if isinstance(assignment.get("host"), dict) else {}
    session.cluster_job_id = str(job.get("jobId") or session.cluster_job_id or "")
    session.assigned_host = str(
        lease.get("hostId")
        or job.get("assignedHost")
        or host.get("hostId")
        or session.assigned_host
        or ""
    )
    session.host_lease_id = str(
        lease.get("leaseId") or job.get("leaseId") or session.host_lease_id or ""
    )
    session.lease_status = str(
        lease.get("status") or job.get("status") or session.lease_status or ""
    )
    session.worker_heartbeat_at = str(
        lease.get("heartbeatAt")
        or host.get("lastHeartbeatAt")
        or session.worker_heartbeat_at
        or ""
    )
    if host.get("hostType"):
        session.host_locality = str(host.get("hostType") or session.host_locality)
    elif session.assigned_host and _same_host_id(session.assigned_host, current_host_id()):
        session.host_locality = current_host_type(
            Path(session.execution_root or session.workspace_root or ".")
        )
    return session


def _wsl_has_command(command_name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        completed = subprocess.run(  # noqa: S603
            ["wsl", "bash", "-lc", f"command -v {shlex.quote(command_name)} >/dev/null 2>&1"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except Exception:
        return False
    return completed.returncode == 0


def _path_candidates(path: Path) -> list[Path]:
    return platform_config().path_candidates(path)


def _coerce_platform_path(value: str | Path, *, posix: bool | None = None) -> Path:
    return platform_config().coerce_path(value, posix=posix)


def _failed_unreadable_session(
    session: DelegatedRuntimeSession | dict,
    *,
    detail: str,
) -> DelegatedRuntimeSession:
    if isinstance(session, DelegatedRuntimeSession):
        payload = asdict(session)
    else:
        payload = dict(session)
    payload["status"] = "failed"
    payload["exit_code"] = -1
    payload["detail"] = detail
    payload["heartbeat_status"] = "inactive"
    payload["updated_at"] = utc_now_iso()
    return DelegatedRuntimeSession(**payload)


class DelegatedRuntimeSupervisor:
    def __init__(self, root: Path) -> None:
        self.root = _coerce_platform_path(root).resolve()
        self.platform_config = platform_config(self.root)
        self.control_dir = self.root / ".agent_control" / "runtime_sessions"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.worker_path = Path(__file__).with_name("runtime_worker.py")

    def start_session(
        self,
        runtime_id: str,
        mission: Mission,
        workspace: WorkspaceProfile,
        source_step_id: str,
        resume: bool = False,
        handoff_reason: str = "",
        source_delegated_id: str = "",
        handoff_count: int = 0,
    ) -> DelegatedRuntimeSession:
        adapter = runtime_adapter_map()[runtime_id]
        launch = (
            adapter.resume_mission(mission, workspace)
            if resume
            else adapter.start_mission(mission, workspace)
        )
        delegated_id = f"delegate_{uuid.uuid4().hex[:8]}"
        session_path = self.control_dir / f"{delegated_id}.json"
        log_path = self.control_dir / f"{delegated_id}.log"
        events_path = self.control_dir / f"{delegated_id}.events.jsonl"
        decision_path = self.control_dir / f"{delegated_id}.approval.json"
        mission_scope = getattr(mission, "execution_scope", None)
        workspace_root = str(
            _coerce_platform_path(
                str(getattr(mission_scope, "workspace_root", "") or "")
                or workspace.root_path
            ).resolve()
        )
        scoped_execution_root = ""
        if bool(getattr(mission_scope, "isolated", False)):
            scoped_execution_root = str(
                getattr(mission_scope, "execution_root", "")
                or getattr(mission_scope, "worktree_path", "")
                or ""
            ).strip()
        execution_root = str(
            _coerce_platform_path(
                scoped_execution_root
                or launch.get("workspace")
                or workspace.root_path
            ).resolve()
        )
        project_workspace_id = str(workspace.workspace_id or mission.workspace_id or "")
        isolated_execution = bool(getattr(mission_scope, "isolated", False)) and (
            os.path.normcase(os.path.normpath(execution_root))
            != os.path.normcase(os.path.normpath(workspace_root))
        )
        cluster_workspace_id = (
            f"{project_workspace_id}:mission:{mission.mission_id}"
            if isolated_execution
            else project_workspace_id
        )
        coordination = _mission_coordination_payload(
            self.root,
            mission,
            project_workspace_id=project_workspace_id,
        )
        coordination_manifest_path = _write_mission_coordination_manifest(
            Path(execution_root),
            coordination,
        )
        session = DelegatedRuntimeSession(
            delegated_id=delegated_id,
            runtime_id=runtime_id,
            launch_command=str(launch.get("launch_command", "")),
            mission_id=str(mission.mission_id or ""),
            status="queued",
            detail=str(
                launch.get("route_summary", "Delegated runtime worker queued.")
            ),
            session_path=str(session_path),
            workspace_root=workspace_root,
            execution_root=execution_root,
            log_path=str(log_path),
            events_path=str(events_path),
            decision_path=str(decision_path),
            source_step_id=source_step_id,
        )
        _apply_execution_truth(session)
        self._write_session(session)
        self._append_structured_event(
            session,
            kind="session.queued",
            message="Delegated runtime worker queued.",
            status="queued",
        )
        route_summary = str(launch.get("route_summary", "")).strip()
        route_contract = launch.get("route_contract", {})
        route_contract_payload = (
            dict(route_contract) if isinstance(route_contract, dict) else {}
        )
        if route_summary:
            self._append_structured_event(
                session,
                kind="runtime.route_contract",
                message=route_summary,
                status="queued",
                data=route_contract_payload,
            )
        session.target_phase = str(route_contract_payload.get("phase", "")).strip().lower()
        session.target_role = str(route_contract_payload.get("role", "")).strip().lower()
        session.target_provider = str(route_contract_payload.get("provider", "")).strip().lower()
        session.target_model = str(route_contract_payload.get("model", "")).strip()
        session.target_effort = str(route_contract_payload.get("effort", "")).strip().lower()
        session.target_budget_class = str(
            route_contract_payload.get("budget_class", route_contract_payload.get("budgetClass", ""))
        ).strip()
        session.handoff_count = max(0, int(handoff_count or 0))
        session.handoff_reason = str(handoff_reason or "").strip()
        session.source_delegated_id = str(source_delegated_id or "").strip()
        if session.target_phase:
            self._append_structured_event(
                session,
                kind="runtime.phase_entered",
                message=(
                    f"Entered {session.target_phase} phase via {session.target_role or 'route'} route."
                ),
                status="queued",
                data={
                    "reason": session.handoff_reason,
                    "phase": session.target_phase,
                    "role": session.target_role,
                    "provider": session.target_provider,
                    "model": session.target_model,
                },
            )
        if session.handoff_reason:
            self._append_structured_event(
                session,
                kind="runtime.route_switch_reason",
                message=session.handoff_reason,
                status="queued",
                data={
                    "phase": session.target_phase,
                    "role": session.target_role,
                    "provider": session.target_provider,
                    "model": session.target_model,
                    "source_delegated_id": session.source_delegated_id,
                    "handoff_count": session.handoff_count,
                },
            )
            self._append_structured_event(
                session,
                kind="runtime.handoff",
                message="Delegated runtime lane was relaunched after a route or phase change.",
                status="queued",
                data={
                    "reason": session.handoff_reason,
                    "source_delegated_id": session.source_delegated_id,
                    "handoff_count": session.handoff_count,
                },
            )

        auth_failure = self._runtime_auth_failure(session)
        if auth_failure:
            session.status = "failed"
            session.exit_code = -1
            session.detail = auth_failure
            session.updated_at = utc_now_iso()
            session.heartbeat_status = "inactive"
            self._write_session(session)
            self._append_structured_event(
                session,
                kind="session.failed",
                message=auth_failure,
                status="failed",
                data={
                    "reason": "provider_auth_unavailable",
                    "provider": session.target_provider,
                    "model": session.target_model,
                },
            )
            self._write_session(session)
            return self.refresh_session(session)

        registry = ClusterRegistry(self.root)
        registry.heartbeat_host(
            build_local_worker_capabilities(
                registry.root,
                host_id=current_host_id(),
            )
        )
        preferred_host = str(
            getattr(workspace, "preferred_host", "")
            or getattr(mission.state, "preferred_host", "")
            or ""
        ).strip()
        session.preferred_host = preferred_host
        allow_remote = _env_flag("FLUXIO_CLUSTER_REMOTE_EXECUTION", default=True)
        allow_nas_fallback = bool(getattr(workspace, "allow_nas_fallback", False)) or _env_flag(
            "FLUXIO_ALLOW_NAS_RUNTIME_FALLBACK",
            default=False,
        )
        cluster_job = registry.upsert_job(
            dedupe_key=_cluster_job_dedupe_key(
                session,
                mission_id=str(mission.mission_id or ""),
                workspace_id=cluster_workspace_id,
            ),
            mission_id=str(mission.mission_id or ""),
            workspace_id=cluster_workspace_id,
            lane_role=session.target_role or session.target_phase or "executor",
            runtime_id=runtime_id,
            target_provider=session.target_provider,
            target_model=session.target_model,
            preferred_host=preferred_host,
            required_capabilities=_cluster_required_capabilities(session),
            planned_file_scope=list(getattr(mission, "planned_file_scope", []) or ["."]),
            required_artifacts=["cluster_receipt"],
            payload={
                "command": session.launch_command,
                "launchCommand": session.launch_command,
                "workspaceId": cluster_workspace_id,
                "projectWorkspaceId": project_workspace_id,
                "workspaceRoot": workspace_root,
                "executionRoot": execution_root,
                "coordinationManifest": str(coordination_manifest_path),
                "coordination": coordination,
                "sessionPath": str(session_path),
                "eventsPath": str(events_path),
                "logPath": str(log_path),
                "decisionPath": str(decision_path),
                "delegatedId": delegated_id,
                "sourceStepId": source_step_id,
                "targetProvider": session.target_provider,
                "targetModel": session.target_model,
                "route": {
                    "provider": session.target_provider,
                    "model": session.target_model,
                },
                "allowNasFallback": allow_nas_fallback,
                "timeoutSeconds": int(
                    os.environ.get("FLUXIO_WORKER_JOB_TIMEOUT_SECONDS", "1800") or 1800
                ),
            },
            status_detail="Delegated runtime lane queued for host scheduling.",
        )
        session.cluster_job_id = str(cluster_job.get("jobId") or "")
        assigned = registry.assign_job(
            session.cluster_job_id,
            preferred_host=preferred_host,
            allow_remote=allow_remote,
            allow_nas_fallback=allow_nas_fallback,
        )
        if not assigned.get("ok"):
            queued_job = assigned.get("job") or registry.get_job(session.cluster_job_id)
            session.status = "queued"
            session.detail = str(
                queued_job.get("statusDetail")
                or assigned.get("error")
                or "Delegated runtime is queued for a healthy worker."
            )
            session.lease_status = str(queued_job.get("status") or "queued")
            session.updated_at = utc_now_iso()
            self._write_session(session)
            self._append_structured_event(
                session,
                kind="cluster.queued",
                message=session.detail,
                status="queued",
                data={"job": queued_job, "error": assigned.get("error", "")},
            )
            return self.refresh_session(session)

        session = _apply_cluster_assignment_to_session(session, assigned)
        self._write_session(session)
        assigned_host_id = str(session.assigned_host or "")
        if assigned_host_id and not _same_host_id(assigned_host_id, current_host_id()):
            session.status = "queued"
            session.detail = f"Delegated runtime assigned to worker host {assigned_host_id}."
            session.updated_at = utc_now_iso()
            self._write_session(session)
            self._append_structured_event(
                session,
                kind="cluster.remote_queued",
                message=session.detail,
                status="queued",
                data={
                    "jobId": session.cluster_job_id,
                    "leaseId": session.host_lease_id,
                    "assignedHost": assigned_host_id,
                },
            )
            return self.refresh_session(session)

        worker_env = runtime_subprocess_env(Path(execution_root))
        package_src_root = Path(__file__).resolve().parents[1]
        python_path_entries = [str(package_src_root)]
        workspace_src_root = self.root / "src"
        if workspace_src_root.exists():
            python_path_entries.append(str(workspace_src_root))
        existing_python_path = str(worker_env.get("PYTHONPATH", "")).strip()
        if existing_python_path:
            python_path_entries.append(existing_python_path)
        worker_env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in python_path_entries if entry
        )
        worker_env["FLUXIO_CLUSTER_JOB_ID"] = session.cluster_job_id
        worker_env["FLUXIO_CLUSTER_LEASE_ID"] = session.host_lease_id
        worker_env["FLUXIO_CLUSTER_HOST_ID"] = session.assigned_host or current_host_id()
        worker_env["FLUXIO_CLUSTER_ROOT"] = str(registry.root)
        if _hermetic_blocks_live_hermes_launch(session.launch_command):
            raise RuntimeError(
                "Hermetic mode blocked a live Hermes delegated session launch. "
                "Set NEYVIA_ALLOW_LIVE_HERMES=1 to opt in."
            )
        process = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "grant_agent.runtime_worker",
                "--session",
                str(session_path),
                "--cwd",
                execution_root,
                "--command",
                session.launch_command,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creationflags(),
            env=worker_env,
        )
        session.supervisor_pid = process.pid
        if session.host_lease_id and session.assigned_host:
            heartbeat = registry.heartbeat_lease(
                lease_id=session.host_lease_id,
                host_id=session.assigned_host,
                process_id=process.pid,
            )
            session = _apply_cluster_assignment_to_session(
                session,
                {
                    "job": heartbeat.get("job", {}),
                    "lease": heartbeat.get("lease", {}),
                    "host": registry.get_host(session.assigned_host),
                },
            )
        session.status = "launching"
        session.updated_at = utc_now_iso()
        session.detail = "Delegated runtime supervisor started."
        self._write_session(session)
        self._append_structured_event(
            session,
            kind="session.launching",
            message="Delegated runtime supervisor started.",
            status="launching",
        )
        return self._settle_session(session)

    def refresh_session(self, session: DelegatedRuntimeSession | dict | str) -> DelegatedRuntimeSession:
        payload = self._load_session(session)
        if payload is None:
            raise FileNotFoundError(f"Unknown delegated runtime session: {session}")
        payload = self._sync_cluster_state(payload)
        payload = self._sync_structured_state(payload)
        _apply_execution_truth(payload)
        _apply_heartbeat_truth(payload)
        if payload.status in {"completed", "failed", "stopped"}:
            terminal_detail = _terminal_session_detail(payload)
            if terminal_detail and (
                not payload.detail or _is_stale_runtime_detail(payload.detail)
            ):
                payload.detail = terminal_detail
                payload.updated_at = utc_now_iso()
            stored = self._load_session(payload.session_path)
            if (
                stored is not None
                and (
                    stored.heartbeat_status != payload.heartbeat_status
                    or stored.detail != payload.detail
                    or stored.exit_code != payload.exit_code
                )
            ):
                self._write_session(payload)
            return payload

        alive = _pid_alive(payload.supervisor_pid) or _pid_alive(payload.pid)
        if payload.pending_approval and payload.pending_approval.get("status") == "pending":
            payload.status = "waiting_for_approval"
            payload.detail = payload.pending_approval.get(
                "prompt",
                "Delegated runtime is waiting for operator approval.",
            )
        elif alive:
            payload.status = "running" if payload.pid else "launching"
            payload.detail = "Delegated runtime process is active."
        else:
            reloaded = self._load_session(payload.session_path)
            if reloaded is not None and reloaded.exit_code is not None:
                payload = self._sync_structured_state(reloaded)
            elif _log_suggests_clean_completion(payload):
                payload.exit_code = 0
                payload.status = "completed"
                payload.detail = "Delegated runtime completion recovered from terminal log output."
                payload.last_event = _tail_summary(Path(payload.log_path)) or payload.detail
                payload.updated_at = utc_now_iso()
                payload.heartbeat_status = "inactive"
                self._write_session(payload)
                self._append_structured_event(
                    payload,
                    kind="session.completed",
                    message=payload.last_event,
                    status="completed",
                    data={
                        "exit_code": 0,
                        "recovered": True,
                        "reason": "terminal_log_completion_without_session_event",
                    },
                )
                return self._sync_structured_state(payload)
            elif payload.exit_code is None:
                recorded_process_missing = payload.pid > 0 or payload.supervisor_pid > 0
                if payload.heartbeat_status == "stale" or recorded_process_missing:
                    payload.exit_code = -1
                    payload.status = "failed"
                    payload.detail = (
                        "Delegated runtime process disappeared before reporting an exit code."
                    )
                    payload.updated_at = utc_now_iso()
                    self._append_structured_event(
                        payload,
                        kind="session.failed",
                        message=payload.detail,
                        status="failed",
                        data={
                            "reason": (
                                "stale_heartbeat_without_live_process"
                                if payload.heartbeat_status == "stale"
                                else "recorded_process_missing_without_exit"
                            ),
                            "pid": payload.pid,
                            "supervisor_pid": payload.supervisor_pid,
                            "heartbeat_age_seconds": payload.heartbeat_age_seconds,
                        },
                    )
                    _apply_heartbeat_truth(payload)
                    self._write_session(payload)
                    return payload
                payload.detail = payload.last_event or payload.detail or "Delegated runtime state is settling."
                _apply_heartbeat_truth(payload)
                self._write_session(payload)
                return payload
            payload.status = "completed" if payload.exit_code == 0 else "failed"
            payload.detail = _terminal_session_detail(payload)
            payload.updated_at = utc_now_iso()
            _apply_heartbeat_truth(payload)
            self._write_session(payload)
            return payload
        _apply_heartbeat_truth(payload)
        return payload

    def stop_session(self, session: DelegatedRuntimeSession | dict | str) -> DelegatedRuntimeSession:
        payload = self._load_session(session)
        if payload is None:
            raise FileNotFoundError(f"Unknown delegated runtime session: {session}")
        was_terminal = payload.status in {"completed", "failed", "stopped"}
        if payload.pid:
            _terminate_pid(payload.pid)
        if payload.supervisor_pid and payload.supervisor_pid != payload.pid:
            _terminate_pid(payload.supervisor_pid)
        payload.status = "stopped"
        payload.detail = "Delegated runtime session was stopped by Neyvia."
        payload.updated_at = utc_now_iso()
        payload.heartbeat_status = "inactive"
        self._write_session(payload)
        self._append_structured_event(
            payload,
            kind="session.stopped",
            message="Delegated runtime session was stopped by Neyvia.",
            status="stopped",
        )
        if (
            not was_terminal
            and payload.cluster_job_id
            and payload.host_lease_id
            and payload.assigned_host
        ):
            try:
                ClusterRegistry(self.root).complete_job(
                    job_id=payload.cluster_job_id,
                    lease_id=payload.host_lease_id,
                    host_id=payload.assigned_host,
                    status="stopped",
                    detail=payload.detail,
                    changed_files=payload.changed_files,
                )
            except Exception:
                pass
        return self.refresh_session(payload)

    def _sync_cluster_state(self, session: DelegatedRuntimeSession) -> DelegatedRuntimeSession:
        if not session.cluster_job_id:
            return session
        try:
            registry = ClusterRegistry(self.root)
            job = registry.get_job(session.cluster_job_id)
        except Exception:
            return session
        if not job:
            try:
                legacy_registry = ClusterRegistry(self.root, use_configured_root=False)
                legacy_job = legacy_registry.get_job(session.cluster_job_id)
            except Exception:
                return session
            if not legacy_job:
                return session
            legacy_status = str(legacy_job.get("status") or "").strip().lower()
            if registry.root == legacy_registry.root or legacy_status not in {
                "queued",
                "leased",
                "running",
            }:
                registry = legacy_registry
                job = legacy_job
            else:
                legacy_payload = (
                    dict(legacy_job.get("payload"))
                    if isinstance(legacy_job.get("payload"), dict)
                    else {}
                )
                legacy_payload["legacyClusterJobId"] = str(legacy_job.get("jobId") or "")
                legacy_payload["legacyClusterRoot"] = str(legacy_registry.root)
                legacy_payload["sessionPath"] = session.session_path
                legacy_payload.setdefault(
                    "targetProvider",
                    str(legacy_job.get("targetProvider") or session.target_provider or "").strip().lower(),
                )
                legacy_payload.setdefault(
                    "targetModel",
                    str(legacy_job.get("targetModel") or session.target_model or "").strip(),
                )
                job = registry.upsert_job(
                    dedupe_key=_cluster_job_dedupe_key(
                        session,
                        mission_id=str(legacy_job.get("missionId") or session.mission_id or ""),
                        workspace_id=str(legacy_job.get("workspaceId") or ""),
                    ),
                    mission_id=str(legacy_job.get("missionId") or session.mission_id or ""),
                    workspace_id=str(legacy_job.get("workspaceId") or ""),
                    lane_role=str(legacy_job.get("laneRole") or session.target_role or "executor"),
                    runtime_id=str(legacy_job.get("runtimeId") or session.runtime_id or ""),
                    target_provider=str(
                        legacy_job.get("targetProvider")
                        or legacy_payload.get("targetProvider")
                        or session.target_provider
                        or ""
                    ),
                    target_model=str(
                        legacy_job.get("targetModel")
                        or legacy_payload.get("targetModel")
                        or session.target_model
                        or ""
                    ),
                    job_kind=str(legacy_job.get("jobKind") or "runtime_lane"),
                    preferred_host=str(legacy_job.get("preferredHost") or session.preferred_host or ""),
                    required_capabilities=list(legacy_job.get("requiredCapabilities") or []),
                    planned_file_scope=list(legacy_job.get("plannedFileScope") or []),
                    required_artifacts=list(legacy_job.get("requiredArtifacts") or []),
                    payload=legacy_payload,
                    status_detail=(
                        "Recovered automatically from a mission-local queue into the shared cluster queue."
                    ),
                )
                old_job_id = session.cluster_job_id
                session.cluster_job_id = str(job.get("jobId") or session.cluster_job_id)
                session.host_lease_id = ""
                session.assigned_host = ""
                session.lease_status = str(job.get("status") or "queued")
                session.status = "queued"
                session.detail = str(job.get("statusDetail") or "Recovered into the shared cluster queue.")
                session.updated_at = utc_now_iso()
                self._write_session(session)
                registry.record_event(
                    job_id=session.cluster_job_id,
                    kind="job.legacy_rehomed",
                    message="Mission-local cluster job was recovered into the shared queue.",
                    payload={
                        "legacyJobId": old_job_id,
                        "legacyRoot": str(legacy_registry.root),
                        "sessionPath": session.session_path,
                    },
                )
                check_rehome(legacy_registry, legacy_job, job, session)
        lease = registry.get_lease(str(job.get("leaseId") or session.host_lease_id or ""))
        host = registry.get_host(str(job.get("assignedHost") or session.assigned_host or ""))
        _apply_cluster_assignment_to_session(
            session,
            {"job": job, "lease": lease, "host": host},
        )
        if session.worker_heartbeat_at:
            session.heartbeat_at = session.worker_heartbeat_at
        job_status = str(job.get("status") or "").strip().lower()
        if job_status in {"completed", "failed", "blocked", "stopped"}:
            if session.status in {"completed", "failed", "stopped"} and session.detail:
                return session
            events = registry.list_events(job_id=session.cluster_job_id, limit=20)
            terminal_event = next(
                (
                    item
                    for item in reversed(events)
                    if str(item.get("kind") or "").startswith("job.")
                ),
                {},
            )
            event_payload = (
                terminal_event.get("payload")
                if isinstance(terminal_event.get("payload"), dict)
                else {}
            )
            result = event_payload.get("result") if isinstance(event_payload.get("result"), dict) else {}
            return_code = result.get("returnCode", result.get("return_code"))
            if isinstance(return_code, int):
                session.exit_code = return_code
            elif job_status == "completed":
                session.exit_code = 0
            elif session.exit_code is None:
                session.exit_code = -1
            changed_files = event_payload.get("changedFiles", [])
            if isinstance(changed_files, list):
                session.changed_files = [str(item) for item in changed_files]
            session.status = "completed" if job_status == "completed" else job_status
            session.detail = str(
                job.get("statusDetail")
                or terminal_event.get("message")
                or f"Cluster job {job_status}."
            )
            session.last_event = str(
                terminal_event.get("message")
                or session.last_event
                or session.detail
            )
            session.heartbeat_status = "inactive"
            session.updated_at = utc_now_iso()
            self._write_session(session)
            return session
        if job_status in {"leased", "running"} and session.status in {"queued", "launching", "running"}:
            session.status = "running" if job_status == "running" else "queued"
            session.detail = str(
                job.get("statusDetail")
                or (
                    f"Delegated runtime is leased to {session.assigned_host}."
                    if job_status == "leased"
                    else "Delegated runtime is running on a worker."
                )
            )
            session.updated_at = utc_now_iso()
            if session.assigned_host and not _same_host_id(session.assigned_host, current_host_id()):
                self._write_session(session)
        return session

    def _runtime_auth_failure(self, session: DelegatedRuntimeSession) -> str:
        if not RUNTIME_AUTH_PREFLIGHT_ENABLED:
            return ""
        runtime_id = str(session.runtime_id or "").strip().lower()
        provider = str(session.target_provider or "").strip().lower()
        if runtime_id != "hermes" or not provider:
            return ""
        execution_root = Path(session.execution_root or session.workspace_root or self.root)
        command = runtime_which("hermes", execution_root)
        use_wsl_hermes = not command and _wsl_has_command("hermes")
        if not command and not use_wsl_hermes:
            return "Hermes CLI is not available, so the delegated provider route cannot start."
        if use_wsl_hermes:
            command_args = [
                "wsl",
                "bash",
                "-lc",
                f"hermes auth status {shlex.quote(provider)}",
            ]
        else:
            command_args = [command, "auth", "status", provider]
        try:
            completed = subprocess.run(  # noqa: S603
                command_args,
                cwd=str(execution_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=RUNTIME_AUTH_PREFLIGHT_TIMEOUT_SECONDS,
                check=False,
                env=runtime_subprocess_env(execution_root),
                **hidden_windows_subprocess_kwargs(),
            )
        except Exception as exc:  # pragma: no cover - defensive subprocess failure
            return f"Hermes provider auth preflight failed for {provider}: {exc}"
        output = f"{completed.stdout}\n{completed.stderr}".strip()
        normalized = output.lower()
        if completed.returncode == 0 and f"{provider}: logged in" in normalized:
            return ""
        if completed.returncode == 0 and "logged in" in normalized and "logged out" not in normalized:
            return ""
        status_text = " ".join(output.split()) or f"exit code {completed.returncode}"
        return (
            f"Hermes provider '{provider}' is not authenticated for this runtime route "
            f"({status_text}). Configure that provider or switch the mission route to a logged-in provider."
        )

    def handoff_session(
        self,
        *,
        session: DelegatedRuntimeSession | dict | str,
        mission: Mission,
        workspace: WorkspaceProfile,
        source_step_id: str,
        reason: str,
    ) -> DelegatedRuntimeSession:
        current = self.refresh_session(session)
        clean_reason = str(reason or "Delegated route changed.").strip()
        self._append_structured_event(
            current,
            kind="runtime.handoff",
            message=f"Handoff requested: {clean_reason}",
            status=current.status,
            data={
                "phase": current.target_phase,
                "role": current.target_role,
                "provider": current.target_provider,
                "model": current.target_model,
                "handoff_count": current.handoff_count,
            },
        )
        self.stop_session(current)
        relaunched = self.start_session(
            runtime_id=current.runtime_id,
            mission=mission,
            workspace=workspace,
            source_step_id=source_step_id or current.source_step_id,
            resume=False,
            handoff_reason=clean_reason,
            source_delegated_id=current.delegated_id,
            handoff_count=int(current.handoff_count or 0) + 1,
        )
        return self.refresh_session(relaunched)

    def resolve_approval(
        self,
        session: DelegatedRuntimeSession | dict | str,
        status: str,
        actor: str = "operator",
    ) -> DelegatedRuntimeSession:
        payload = self._load_session(session)
        if payload is None:
            raise FileNotFoundError(f"Unknown delegated runtime session: {session}")
        if status not in {"approved", "rejected"}:
            raise ValueError(f"Unsupported approval status: {status}")
        if not payload.pending_approval:
            raise ValueError("Delegated runtime session is not waiting for approval.")

        request = dict(payload.pending_approval)
        request["status"] = status
        request["resolved_at"] = utc_now_iso()
        request["resolved_by"] = actor
        approval_history = list(payload.approval_history)
        approval_history.append(request)
        decision_path = Path(payload.decision_path)
        decision_path.write_text(
            json.dumps(
                {
                    "request_id": request.get("request_id"),
                    "status": status,
                    "actor": actor,
                    "resolved_at": request["resolved_at"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        payload.pending_approval = request
        payload.approval_history = approval_history
        payload.updated_at = utc_now_iso()
        payload.detail = f"Delegated approval {status} by {actor}."
        self._write_session(payload)
        self._append_structured_event(
            payload,
            kind="approval.decision",
            message=f"Delegated approval {status} by {actor}.",
            status="waiting_for_approval" if status == "approved" else "failed",
            data={"request_id": request.get("request_id"), "decision": status},
        )
        return self.refresh_session(payload)

    def read_events(self, session: DelegatedRuntimeSession | dict | str, max_lines: int = 5) -> list[dict]:
        payload = self.refresh_session(session)
        return payload.latest_events[-max_lines:]

    def append_operator_follow_up(
        self,
        session: DelegatedRuntimeSession | dict | str,
        message: str,
        *,
        actor: str = "operator",
        channel: str = "desktop",
    ) -> DelegatedRuntimeSession:
        payload = self._load_session(session)
        if payload is None:
            raise FileNotFoundError(f"Unknown delegated runtime session: {session}")
        clean_message = str(message).strip()
        if not clean_message:
            raise ValueError("Follow-up message cannot be empty.")
        self._append_structured_event(
            payload,
            kind="operator.followup",
            message=clean_message,
            status=payload.status,
            data={"actor": actor, "channel": channel},
        )
        return self.refresh_session(payload)

    def build_session_snapshot(
        self,
        session: DelegatedRuntimeSession | dict | str,
        max_events: int = 5,
    ) -> DelegatedSessionSnapshot:
        payload = self.refresh_session(session)
        latest_events = [
            DelegatedRuntimeEvent(**item)
            for item in payload.latest_events[-max_events:]
        ]
        pending_approval = (
            DelegatedApprovalRequest(**payload.pending_approval)
            if payload.pending_approval
            else None
        )
        return DelegatedSessionSnapshot(
            delegated_id=payload.delegated_id,
            runtime_id=payload.runtime_id,
            mission_id=payload.mission_id,
            status=payload.status,
            detail=payload.detail,
            last_event=payload.last_event,
            last_event_kind=payload.last_event_kind,
            latest_events=latest_events,
            pending_approval=pending_approval,
            event_cursor=payload.event_cursor,
            created_at=payload.created_at,
            updated_at=payload.updated_at,
            workspace_root=payload.workspace_root,
            execution_root=payload.execution_root,
            execution_target=payload.execution_target,
            storage_mode=payload.storage_mode,
            host_locality=payload.host_locality,
            execution_target_detail=payload.execution_target_detail,
            session_path=payload.session_path,
            log_path=payload.log_path,
            source_step_id=payload.source_step_id,
            pid=payload.pid,
            supervisor_pid=payload.supervisor_pid,
            exit_code=payload.exit_code,
            heartbeat_at=payload.heartbeat_at,
            heartbeat_status=payload.heartbeat_status,
            heartbeat_age_seconds=payload.heartbeat_age_seconds,
            heartbeat_interval_seconds=payload.heartbeat_interval_seconds,
            target_phase=payload.target_phase,
            target_role=payload.target_role,
            target_provider=payload.target_provider,
            target_model=payload.target_model,
            target_effort=payload.target_effort,
            target_budget_class=payload.target_budget_class,
            handoff_count=payload.handoff_count,
            handoff_reason=payload.handoff_reason,
            source_delegated_id=payload.source_delegated_id,
            changed_files=list(payload.changed_files or []),
        )

    def _load_session(self, session: DelegatedRuntimeSession | dict | str) -> DelegatedRuntimeSession | None:
        acknowledged = False
        if isinstance(session, DelegatedRuntimeSession):
            path = Path(session.session_path) if session.session_path else self.control_dir / f"{session.delegated_id}.json"
            acknowledged = bool(session.acknowledged)
        elif isinstance(session, dict):
            if session.get("session_path"):
                path = Path(str(session["session_path"]))
            else:
                path = self.control_dir / f"{session['delegated_id']}.json"
            acknowledged = bool(session.get("acknowledged"))
        else:
            path = Path(session)
            if not path.suffix:
                path = self.control_dir / f"{session}.json"
        delegated_id = ""
        if isinstance(session, DelegatedRuntimeSession):
            delegated_id = session.delegated_id
        elif isinstance(session, dict):
            delegated_id = str(session.get("delegated_id") or "")
        elif not path.suffix:
            delegated_id = str(session)
        candidates = list(self.platform_config.path_candidates(path))
        if delegated_id:
            candidates.append(self.control_dir / f"{delegated_id}.json")
        payload = None
        try:
            for candidate in candidates:
                # A stale saved path must not create a lock outside the current
                # control tree. Only lock candidates that actually contain a
                # session; recheck under the lock before reading.
                if not candidate.is_file():
                    continue
                with file_transaction(candidate):
                    if candidate.exists():
                        payload = _read_json_with_retries(candidate)
                        break
        except OSError:
            if isinstance(session, (DelegatedRuntimeSession, dict)):
                return _failed_unreadable_session(
                    session,
                    detail="Delegated runtime session file is missing or inaccessible.",
                )
            raise
        if payload is None:
            if isinstance(session, (DelegatedRuntimeSession, dict)):
                return _failed_unreadable_session(
                    session,
                    detail="Delegated runtime session file is missing or inaccessible.",
                )
            return None
        loaded = DelegatedRuntimeSession(
            **{
                key: value
                for key, value in payload.items()
                if key in DELEGATED_RUNTIME_SESSION_FIELD_NAMES
            }
        )
        if acknowledged and not loaded.acknowledged:
            loaded.acknowledged = True
        return loaded

    def _write_session(self, session: DelegatedRuntimeSession) -> None:
        path = Path(session.session_path) if session.session_path else self.control_dir / f"{session.delegated_id}.json"
        session.session_path = str(path)
        _atomic_write_json(path, asdict(session))

    def _append_structured_event(
        self,
        session: DelegatedRuntimeSession,
        *,
        kind: str,
        message: str,
        status: str = "",
        data: dict | None = None,
    ) -> DelegatedRuntimeEvent:
        events_path = Path(session.events_path) if session.events_path else self.control_dir / f"{session.delegated_id}.events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        event = DelegatedRuntimeEvent(
            event_id=f"evt_{uuid.uuid4().hex[:10]}",
            delegated_id=session.delegated_id,
            runtime_id=session.runtime_id,
            kind=kind,
            message=message,
            status=status or session.status,
            data=data or {},
        )
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")
        self._sync_structured_state(session)
        return event

    def _sync_structured_state(self, session: DelegatedRuntimeSession, max_events: int = 5) -> DelegatedRuntimeSession:
        if session.events_path:
            latest_events, event_count = _read_structured_events(
                Path(session.events_path),
                max_events=max_events,
            )
        else:
            latest_events, event_count = [], 0
        session.event_cursor = event_count
        session.latest_events = latest_events
        if session.latest_events:
            latest = session.latest_events[-1]
            session.last_event = latest.get("message", session.last_event)
            session.last_event_kind = latest.get("kind", session.last_event_kind)
        if session.log_path:
            log_path = Path(session.log_path)
            if log_path.exists() and not session.last_event:
                session.last_event = _tail_summary(log_path) or session.last_event
        if session.pending_approval and session.pending_approval.get("status") == "approved":
            session.pending_approval = {}
        return session

    def _settle_session(self, session: DelegatedRuntimeSession) -> DelegatedRuntimeSession:
        current = self.refresh_session(session)
        if SESSION_SETTLE_TIMEOUT_SECONDS <= 0:
            return current
        terminal_statuses = {"completed", "failed", "stopped", "waiting_for_approval"}
        if current.status in terminal_statuses:
            return current
        now = time.monotonic()
        settle_deadline = now + SESSION_SETTLE_TIMEOUT_SECONDS
        quick_exit_deadline = now + min(
            SESSION_SETTLE_TIMEOUT_SECONDS,
            SESSION_QUICK_EXIT_GRACE_SECONDS,
        )
        while time.monotonic() < settle_deadline:
            if current.status in terminal_statuses:
                return current
            if current.status not in {"launching", "running"}:
                return current
            if (
                current.status == "running"
                and time.monotonic() >= quick_exit_deadline
            ):
                return current
            time.sleep(SESSION_SETTLE_POLL_SECONDS)
            current = self.refresh_session(current)
        return current


def _read_structured_events(events_path: Path, max_events: int = 5) -> tuple[list[dict], int]:
    if not events_path.exists():
        return [], 0
    event_count = 0
    tail: deque[dict] = deque(maxlen=max(1, max_events))
    with events_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_count += 1
            tail.append(event)
    return list(tail), event_count


def _read_json_with_retries(path: Path, retries: int = 8, delay: float = 0.02) -> dict:
    with file_transaction(path):
        return _read_json_locked(path, retries, delay)


def _read_json_locked(path: Path, retries: int, delay: float) -> dict:
    last_error: json.JSONDecodeError | None = None
    for attempt in range(retries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            time.sleep(delay)
    raise RuntimeError(f"Unable to read delegated session state from {path}") from last_error


def _apply_execution_truth(session: DelegatedRuntimeSession) -> DelegatedRuntimeSession:
    truth = derive_execution_target(
        execution_root=session.execution_root,
        workspace_root=session.workspace_root,
        strategy="delegated_runtime",
    )
    session.execution_target = truth["execution_target"]
    session.storage_mode = truth["storage_mode"]
    session.host_locality = truth["host_locality"]
    session.execution_target_detail = truth["execution_target_detail"]
    return session


def _parse_utc_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: str) -> int | None:
    parsed = _parse_utc_timestamp(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed
    return max(int(delta.total_seconds()), 0)


def _apply_heartbeat_truth(session: DelegatedRuntimeSession) -> DelegatedRuntimeSession:
    active_statuses = {"launching", "running", "waiting_for_approval"}
    if session.status in {"completed", "failed", "stopped"}:
        session.heartbeat_status = "inactive"
        session.heartbeat_age_seconds = _age_seconds(
            session.heartbeat_at or session.updated_at
        )
        return session

    heartbeat_source = session.heartbeat_at or session.updated_at
    heartbeat_age = _age_seconds(heartbeat_source)
    session.heartbeat_age_seconds = heartbeat_age
    if session.status not in active_statuses:
        session.heartbeat_status = "unknown"
        return session
    stale_after = max(
        int(session.heartbeat_interval_seconds or 10) * 3,
        HEARTBEAT_STALE_FLOOR_SECONDS,
    )
    if heartbeat_age is None:
        session.heartbeat_status = "unknown"
    elif heartbeat_age > stale_after:
        session.heartbeat_status = "stale"
    else:
        session.heartbeat_status = "healthy"
    return session


def _is_stale_runtime_detail(detail: str) -> bool:
    text = str(detail or "").strip().lower()
    if not text:
        return True
    stale_fragments = (
        "process is running",
        "process is active",
        "heartbeat: session is healthy",
        "supervisor started",
        "state is settling",
        "no longer active",
    )
    return any(fragment in text for fragment in stale_fragments)


def _terminal_session_detail(session: DelegatedRuntimeSession) -> str:
    exit_code = session.exit_code
    log_tail = ""
    if session.log_path:
        log_path = Path(session.log_path)
        if log_path.exists() and log_path.is_file():
            log_tail = _tail_summary(log_path, max_lines=5)
    terminal_event = ""
    for event in reversed(session.latest_events or []):
        kind = str(event.get("kind") or "").lower()
        message = str(event.get("message") or "").strip()
        if not message:
            continue
        if kind in {"session.failed", "session.completed", "session.stopped"}:
            terminal_event = message
            break
        if not _is_stale_runtime_detail(message):
            terminal_event = message
            break
    current_detail = str(session.detail or "").strip()
    current_detail_lower = current_detail.lower()
    if (
        session.status == "failed"
        and current_detail
        and not _is_stale_runtime_detail(current_detail)
        and "delegated runtime failed" not in current_detail_lower
        and "runtime process failed" not in current_detail_lower
    ):
        if exit_code is not None and "exit" not in current_detail_lower:
            return f"{current_detail} Exit code {exit_code}."
        return current_detail
    if session.status == "completed" or exit_code == 0:
        return log_tail or terminal_event or "Delegated runtime completed."
    if log_tail:
        return f"Delegated runtime exited with code {exit_code if exit_code is not None else -1}: {log_tail}"
    if terminal_event and not _is_stale_runtime_detail(terminal_event):
        if exit_code is not None and "exit" not in terminal_event.lower():
            return f"{terminal_event} Exit code {exit_code}."
        return terminal_event
    if terminal_event:
        return f"{terminal_event} Exit code {exit_code if exit_code is not None else -1}."
    return f"Delegated runtime exited with code {exit_code if exit_code is not None else -1} without terminal output."


def _atomic_write_json(path: Path, payload: dict) -> None:
    with file_transaction(path):
        _atomic_write_json_locked(path, payload)


def _atomic_write_json_locked(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                break
            time.sleep(0.02)
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    raise PermissionError(f"Unable to atomically update delegated session state at {path}")


def _creationflags() -> int:
    return background_creationflags()


def _tail_summary(log_path: Path, max_lines: int = 3) -> str:
    lines = [
        line.strip()
        for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    ]
    return " | ".join(lines[-max_lines:])


def _log_suggests_clean_completion(session: DelegatedRuntimeSession) -> bool:
    if not session.log_path:
        return False
    log_path = Path(session.log_path)
    if not log_path.exists() or not log_path.is_file():
        return False
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 16384), os.SEEK_SET)
            tail = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return False
    lowered = tail.lower()
    return "completed." in lowered and "session_id:" in lowered


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    now = time.monotonic()
    if PID_ALIVE_CACHE_TTL_SECONDS > 0:
        cached = _PID_ALIVE_CACHE.get(pid)
        if cached and now - cached[0] <= PID_ALIVE_CACHE_TTL_SECONDS:
            return cached[1]
    if os.name == "nt":
        alive = _windows_pid_alive(pid)
        if alive is None:
            completed = subprocess.run(  # noqa: S603
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                **hidden_windows_subprocess_kwargs(),
            )
            alive = completed.returncode == 0 and str(pid) in completed.stdout
        _cache_pid_liveness(pid, alive, now)
        return alive
    try:
        os.kill(pid, 0)
    except OSError:
        _cache_pid_liveness(pid, False, now)
        return False
    _cache_pid_liveness(pid, True, now)
    return True



def _terminate_pid(pid: int) -> None:
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        _PID_ALIVE_CACHE.pop(pid, None)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    _PID_ALIVE_CACHE.pop(pid, None)


def _cache_pid_liveness(pid: int, alive: bool, now: float) -> None:
    if PID_ALIVE_CACHE_TTL_SECONDS <= 0:
        return
    if len(_PID_ALIVE_CACHE) >= PID_ALIVE_CACHE_MAX_SIZE:
        expiry_cutoff = now - PID_ALIVE_CACHE_TTL_SECONDS
        expired = [key for key, value in _PID_ALIVE_CACHE.items() if value[0] < expiry_cutoff]
        for key in expired:
            _PID_ALIVE_CACHE.pop(key, None)
    while len(_PID_ALIVE_CACHE) >= PID_ALIVE_CACHE_MAX_SIZE:
        oldest_pid = min(
            _PID_ALIVE_CACHE.items(),
            key=lambda item: item[1][0],
        )[0]
        _PID_ALIVE_CACHE.pop(oldest_pid, None)
    _PID_ALIVE_CACHE[pid] = (now, alive)
