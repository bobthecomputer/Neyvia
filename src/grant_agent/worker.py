from __future__ import annotations

from .subprocess_utils import process_is_alive

import argparse
import concurrent.futures
from contextlib import ExitStack
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .cluster import (
    ClusterRegistry,
    build_local_worker_capabilities,
    classify_provider_result,
    current_host_id,
    normalize_concurrency_limit,
)
from .runtimes.base import runtime_subprocess_env
from .self_repair import execute_self_repair_job, is_self_repair_job
from .subprocess_utils import hidden_windows_subprocess_kwargs, split_process_command, install_hidden_subprocess_default
from .proofs_a_cli import checked
from .proofs_a_cli_scheduler import check_worker_environment


WORKER_STATE_SCHEMA = "fluxio.worker_state.v1"
_WORKER_STATE_LOCKS: dict[str, threading.RLock] = {}
_WORKER_STATE_LOCKS_GUARD = threading.Lock()
_WORKER_PROCESS_GUARDS: dict[str, tuple[int, Any]] = {}


def _serialize_worker_state(action):
    """Own the lifecycle merge, publication and persisted receipt check."""
    @wraps(action)
    def write(root, *args, **kwargs):
        from .harness_jobs import _exclusive_job_lock
        path = _worker_state_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WORKER_STATE_LOCKS_GUARD:
            lock = _WORKER_STATE_LOCKS.setdefault(str(path.resolve()), threading.RLock())
        with lock:
            owned = _WORKER_PROCESS_GUARDS.get(str(path.resolve()))
            if owned is not None and owned[0] == os.getpid():
                return action(root, *args, **kwargs)
            with _exclusive_job_lock(path):
                return action(root, *args, **kwargs)
    return write


def _parse_max_jobs_arg(value: object) -> int:
    normalized = str(value if value is not None else "").strip().lower()
    if normalized in {"", "0", "none", "unbounded", "unlimited", "infinite"}:
        return 0
    try:
        parsed = int(normalized)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "max jobs must be a positive integer or 'unlimited'"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            "max jobs must be a positive integer or 'unlimited'"
        )
    return parsed


def _notify_claim_observer(observer: Callable[[bool], None] | None, claimed: bool) -> None:
    if observer is None:
        return
    try:
        observer(bool(claimed))
    except Exception:
        # A diagnostic observer must never strand an already-created lease.
        return


@checked('a-cli.scheduler.threads')
def _start_unlimited_worker_attempt(
    runner: Callable[[Callable[[bool], None]], dict[str, Any]],
) -> tuple[concurrent.futures.Future, concurrent.futures.Future, threading.Thread]:
    """Start one claim/execution attempt without imposing a fixed pool ceiling."""
    completion: concurrent.futures.Future = concurrent.futures.Future()
    admission: concurrent.futures.Future = concurrent.futures.Future()

    def observe(claimed: bool) -> None:
        if not admission.done():
            admission.set_result(bool(claimed))

    def invoke() -> None:
        if not completion.set_running_or_notify_cancel():
            return
        try:
            result = runner(observe)
        except BaseException as exc:
            if not admission.done():
                admission.set_result(False)
            completion.set_exception(exc)
            return
        if not admission.done():
            admission.set_result(bool(result.get("claimed")))
        completion.set_result(result)

    thread = threading.Thread(
        target=invoke,
        daemon=False,
        name="fluxio-worker-unlimited",
    )
    thread.start()
    return completion, admission, thread


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_state_path(root: Path) -> Path:
    return root / ".agent_control" / "worker_state.json"


def _worker_pid_path(root: Path) -> Path:
    return root / ".agent_control" / "worker.pid"


def _read_worker_state(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_worker_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _pid_is_alive(process_id: int) -> bool:
    return process_is_alive(process_id)


def _claim_worker_process(root: Path) -> None:
    from .harness_jobs import _exclusive_job_lock
    pid_path = _worker_pid_path(root)
    def live_owner():
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0
    existing_pid = live_owner()
    if existing_pid and existing_pid != os.getpid() and _pid_is_alive(existing_pid):
        raise RuntimeError(f"Neyvia worker is already running with PID {existing_pid}.")
    path = _worker_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    guard = _exclusive_job_lock(path)
    guard.__enter__()
    try:
        # Recheck after taking the crash-safe lifetime lease: two launches may
        # both have observed the absent PID before either wrote it.
        existing_pid = live_owner()
        if existing_pid and existing_pid != os.getpid() and _pid_is_alive(existing_pid):
            raise RuntimeError(f"Neyvia worker is already running with PID {existing_pid}.")
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        _WORKER_PROCESS_GUARDS[str(path.resolve())] = (os.getpid(), guard)
    except BaseException:
        guard.__exit__(*__import__('sys').exc_info())
        raise


def _release_worker_process(root: Path) -> None:
    pid_path = _worker_pid_path(root)
    try:
        try:
            owned_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            owned_pid = 0
        if owned_pid == os.getpid():
            pid_path.unlink(missing_ok=True)
    finally:
        owned = _WORKER_PROCESS_GUARDS.pop(str(_worker_state_path(root).resolve()), None)
        if owned is not None and owned[0] == os.getpid():
            owned[1].__exit__(None, None, None)


@_serialize_worker_state
@checked('a-cli.scheduler.lifecycle')
def _write_worker_state(
    root: Path,
    *,
    status: str,
    host_id: str,
    controller: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    previous = _read_worker_state(root)
    now = _utc_now()
    claimed = bool((result or {}).get("claimed"))
    payload = {
        "schema": WORKER_STATE_SCHEMA,
        "status": status,
        "pid": os.getpid(),
        "parentPid": os.getppid() if hasattr(os, "getppid") else 0,
        "hostId": host_id,
        "mode": "controller" if controller else "local",
        "controller": controller,
        "startedAt": previous.get("startedAt") or now,
        "updatedAt": now,
        "lastClaimedJob": claimed,
        "lastJobId": str((result or {}).get("job", {}).get("jobId") or ""),
        "lastError": error,
    }
    from .durability import atomic_write_json
    atomic_write_json(_worker_state_path(root), payload)
    return payload


def _json_request(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    token: str = "",
    method: str = "POST",
    timeout: float = 30.0,
) -> dict[str, Any]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    body = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "fluxio-worker/1"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        decoded = response.read().decode("utf-8", errors="replace")
    result = json.loads(decoded) if decoded.strip() else {}
    return result.get("data", result) if isinstance(result, dict) else {}


def _load_token(root: Path, token_file: str = "") -> str:
    if os.environ.get("FLUXIO_WORKER_TOKEN"):
        return str(os.environ["FLUXIO_WORKER_TOKEN"]).strip()
    if os.environ.get("FLUXIO_CLUSTER_WORKER_TOKEN"):
        return str(os.environ["FLUXIO_CLUSTER_WORKER_TOKEN"]).strip()
    candidates = []
    if token_file:
        candidates.append(Path(token_file).expanduser())
    candidates.append(root / ".agent_control" / "cluster_worker_token.txt")
    for candidate in candidates:
        try:
            token = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            return token
    return ""


def _command_args(command: object) -> list[str]:
    if isinstance(command, list):
        return [str(item) for item in command]
    try:
        return split_process_command(str(command or ""))
    except ValueError:
        return []


def _snapshot_files(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    skip = {".git", ".agent_control", ".agent_runs", "node_modules", ".venv", "venv", "__pycache__"}
    if not root.exists():
        return snapshot
    scanned = 0
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [item for item in dirnames if item not in skip]
        current = Path(current_root)
        for filename in filenames:
            scanned += 1
            if scanned > 8000:
                return snapshot
            path = current / filename
            try:
                stat = path.stat()
                snapshot[str(path.relative_to(root)).replace("\\", "/")] = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue
    return snapshot


def _changed_files(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    changed = [
        path
        for path, value in after.items()
        if before.get(path) != value
    ]
    return sorted(changed)[:240]


def _workspace_mappings_from_env() -> dict[str, str]:
    raw = str(os.environ.get("FLUXIO_WORKSPACE_MAPPINGS") or "").strip()
    mappings: dict[str, str] = {}
    for pair in raw.split(";"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        if key.strip() and value.strip():
            mappings[key.strip()] = value.strip()
    return mappings


def _workspace_for_job(job: dict[str, Any], payload: dict[str, Any], root: Path) -> Path:
    workspace_id = str(job.get("workspaceId") or payload.get("workspaceId") or "").strip()
    mappings = _workspace_mappings_from_env()
    mapped = mappings.get(workspace_id) if workspace_id else ""
    workspace = Path(
        mapped
        or str(
            payload.get("execution_root")
            or payload.get("executionRoot")
            or payload.get("workspace_root")
            or payload.get("workspaceRoot")
            or root
        )
    ).expanduser()
    if not workspace.is_absolute():
        workspace = root / workspace
    return workspace.resolve()


def _materialize_coordination_manifest(workspace: Path, payload: dict[str, Any]) -> Path | None:
    coordination = payload.get("coordination")
    if not isinstance(coordination, dict) or not coordination:
        return None
    path = workspace / ".agent_control" / "mission_coordination" / "current.json"
    _atomic_write_json(path, coordination)
    return path


@checked('a-cli.scheduler.execute')
def execute_job(job: dict[str, Any], lease: dict[str, Any], *, root: Path, process_environment: dict[str, str] | None = None) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    command = payload.get("command") or payload.get("launch_command") or payload.get("launchCommand")
    args = _command_args(command)
    workspace = _workspace_for_job(job, payload, root)
    timeout = max(1, int(payload.get("timeoutSeconds") or payload.get("timeout_seconds") or 1800))
    if process_environment is None:
        coordination_path = _materialize_coordination_manifest(workspace, payload)
        worker_env = runtime_subprocess_env(workspace)
    else:
        from .proofs_d_runtime import require
        require(workspace.is_relative_to(root.resolve()) and isinstance(process_environment, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in process_environment.items()),
                "d.runtime.circuit.worker", "explicit process environment must stay within the local worker root")
        worker_env = dict(process_environment)
        # An explicit child environment still uses the host's selected
        # coordination database; it cannot redirect or drop that authority.
        cluster_root = os.environ.get("FLUXIO_CLUSTER_ROOT")
        if cluster_root:
            if worker_env.get("FLUXIO_CLUSTER_ROOT", cluster_root) != cluster_root:
                raise ValueError("Explicit process environment cannot change FLUXIO_CLUSTER_ROOT")
            worker_env["FLUXIO_CLUSTER_ROOT"] = cluster_root
        coordination_path = _materialize_coordination_manifest(workspace, payload)
    control_project_root = str(
        payload.get("controlProjectRoot") or payload.get("control_project_root") or ""
    ).strip()
    if control_project_root:
        worker_env["FLUXIO_CONTROL_PROJECT_ROOT"] = str(
            Path(control_project_root).expanduser().resolve()
        )
    worker_env["FLUXIO_MISSION_ID"] = str(job.get("missionId") or payload.get("missionId") or "")
    worker_env["FLUXIO_PROJECT_WORKSPACE_ID"] = str(
        payload.get("projectWorkspaceId") or payload.get("workspaceId") or job.get("workspaceId") or ""
    )
    if coordination_path is not None:
        worker_env["FLUXIO_COORDINATION_MANIFEST"] = str(coordination_path)
    check_worker_environment(job, worker_env)
    before = _snapshot_files(workspace)
    if is_self_repair_job(job):
        result = execute_self_repair_job(
            job,
            workspace=workspace,
            env=worker_env,
            timeout_seconds=timeout,
        )
        after = _snapshot_files(workspace)
        changed_files = _changed_files(before, after)
        result["changedFiles"] = sorted(
            set(changed_files) | set(result.get("changedFiles", []))
        )[:240]
        return result
    if str(payload.get("runner") or "").strip().lower() == "computer_use_twin":
        from .computer_use_twin import execute_cluster_twin_job

        return execute_cluster_twin_job(payload, root=workspace)
    if not args:
        return {
            "status": "blocked",
            "detail": "Worker claimed the job, but no executable command was provided.",
            "returnCode": -1,
            "stdout": "",
            "stderr": "",
            "changedFiles": [],
        }
    try:
        completed = subprocess.run(  # noqa: S603
            args,
            cwd=str(workspace),
            env=worker_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        after = _snapshot_files(workspace)
        return {
            "status": "completed" if completed.returncode == 0 else "failed",
            "detail": "Worker job completed." if completed.returncode == 0 else "Worker job failed.",
            "returnCode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "changedFiles": _changed_files(before, after),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "detail": f"Worker job exceeded timeout of {timeout} seconds.",
            "returnCode": -1,
            "stdout": str(exc.stdout or "")[-4000:],
            "stderr": str(exc.stderr or "")[-4000:],
            "changedFiles": [],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "detail": f"Worker could not execute job: {exc}",
            "returnCode": -1,
            "stdout": "",
            "stderr": "",
            "changedFiles": [],
        }


def _start_local_lease_heartbeat(
    registry: ClusterRegistry,
    *,
    lease_id: str,
    host_id: str,
    process_id: int,
    interval_seconds: float = 15.0,
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(max(1.0, interval_seconds)):
            try:
                registry.heartbeat_lease(
                    lease_id=lease_id,
                    host_id=host_id,
                    process_id=process_id,
                )
            except Exception:
                return

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return stop, thread


def _start_controller_lease_heartbeat(
    *,
    root: Path,
    controller: str,
    token: str,
    host_id: str,
    lease_id: str,
    process_id: int,
    max_concurrent_jobs: int | None = None,
    interval_seconds: float = 15.0,
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(max(1.0, interval_seconds)):
            payload = build_local_worker_capabilities(
                root,
                host_id=host_id,
                max_concurrent_jobs=max_concurrent_jobs,
            )
            payload["leaseId"] = lease_id
            payload["processId"] = process_id
            try:
                _json_request(
                    controller,
                    "/api/cluster/worker/heartbeat",
                    payload,
                    token=token,
                )
            except Exception:
                return

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return stop, thread


@checked('a-cli.scheduler.worker')
def run_local_worker_once(
    root: Path,
    *,
    host_id: str = "",
    max_concurrent_jobs: int | None = None,
    claim_observer: Callable[[bool], None] | None = None,
    observed_capabilities: dict[str, Any] | None = None,
    process_environment: dict[str, str] | None = None,
    registry: ClusterRegistry | None = None,
) -> dict[str, Any]:
    registry = registry if registry is not None else ClusterRegistry(root)
    resolved_host_id = host_id or current_host_id()
    capabilities = build_local_worker_capabilities(
        root,
        host_id=resolved_host_id,
        current_load=registry.active_host_load(resolved_host_id),
        max_concurrent_jobs=max_concurrent_jobs,
    ) if observed_capabilities is None else _observed_local_capabilities(root, resolved_host_id, observed_capabilities)
    claimed = registry.claim_next_job(capabilities)
    job = claimed.get("job")
    lease = claimed.get("lease")
    _notify_claim_observer(claim_observer, bool(job and lease))
    if not job or not lease:
        return {"ok": True, "claimed": False, "host": claimed.get("host")}
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    workspace = _workspace_for_job(job, payload, root)
    with registry._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        registry.heartbeat_lease(
            lease_id=lease["leaseId"],
            host_id=capabilities["hostId"],
            process_id=os.getpid(), db=db,
        )
        registry.record_event(
            job_id=job["jobId"],
            lease_id=lease["leaseId"],
            host_id=capabilities["hostId"],
            kind="worker.started",
            message="Worker started local job execution.", db=db,
        )
        process = registry.register_process(
            process_id=os.getpid(),
            parent_process_id=os.getppid() if hasattr(os, "getppid") else 0,
            host_id=capabilities["hostId"],
            job_id=job["jobId"],
            lease_id=lease["leaseId"],
            mission_id=str(job.get("missionId") or ""),
            kind="cluster_worker_job",
            command=str(payload.get("command") or payload.get("launchCommand") or ""),
            cwd=str(workspace),
            ttl_seconds=max(1, int(payload.get("timeoutSeconds") or payload.get("timeout_seconds") or 1800)) + 120,
            db=db,
        )
    stop, thread = _start_local_lease_heartbeat(
        registry,
        lease_id=lease["leaseId"],
        host_id=capabilities["hostId"],
        process_id=os.getpid(),
    )
    try:
        result = execute_job(job, lease, root=root, process_environment=process_environment) if process_environment is not None else execute_job(job, lease, root=root)
    finally:
        stop.set()
        thread.join(timeout=1)
    circuit_result = registry.record_provider_result(
        job=job,
        lease_id=lease["leaseId"],
        host_id=capabilities["hostId"],
        result=result,
    )
    result["providerCircuit"] = circuit_result.get("circuit", {})
    result["providerClassification"] = circuit_result.get("classification", classify_provider_result(job, result))
    for event in result.get("phaseEvents", []):
        if not isinstance(event, dict):
            continue
        registry.record_event(
            job_id=job["jobId"],
            lease_id=lease["leaseId"],
            host_id=capabilities["hostId"],
            kind=str(event.get("kind") or "worker.phase"),
            message=str(event.get("message") or "Worker phase completed."),
            payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
        )
    from .proofs_d_runtime_auth import check_worker_circuit_before_completion
    check_worker_circuit_before_completion(registry, job, circuit_result)
    completed = registry.complete_job(
        job_id=job["jobId"],
        lease_id=lease["leaseId"],
        host_id=capabilities["hostId"],
        status=result["status"],
        detail=result["detail"],
        artifacts=result.get("artifacts", []),
        changed_files=result.get("changedFiles", []),
        result=result,
    )
    registry.complete_process(
        process_key=str(process.get("processKey") or ""),
        process_id=os.getpid(),
        host_id=capabilities["hostId"],
        status=result["status"],
        reason=result["detail"],
    )
    if is_self_repair_job(job):
        from .proofs_e_wz import check_worker_repair
        check_worker_repair(registry, job, result)
    return {"ok": True, "claimed": True, "job": completed.get("job"), "result": result}


def run_controller_worker_once(
    *,
    root: Path,
    controller: str,
    token: str,
    host_id: str = "",
    max_concurrent_jobs: int | None = None,
    claim_observer: Callable[[bool], None] | None = None,
) -> dict[str, Any]:
    capabilities = build_local_worker_capabilities(
        root,
        host_id=host_id or current_host_id(),
        max_concurrent_jobs=max_concurrent_jobs,
    )
    claimed = _json_request(
        controller,
        "/api/cluster/worker/claim",
        capabilities,
        token=token,
    )
    job = claimed.get("job")
    lease = claimed.get("lease")
    _notify_claim_observer(claim_observer, bool(job and lease))
    if not job or not lease:
        return {"ok": True, "claimed": False, "host": claimed.get("host")}
    heartbeat_payload = dict(capabilities)
    heartbeat_payload["leaseId"] = lease["leaseId"]
    heartbeat_payload["processId"] = os.getpid()
    _json_request(
        controller,
        "/api/cluster/worker/heartbeat",
        heartbeat_payload,
        token=token,
    )
    _json_request(
        controller,
        "/api/cluster/worker/events",
        {
            "jobId": job["jobId"],
            "leaseId": lease["leaseId"],
            "hostId": capabilities["hostId"],
            "kind": "worker.started",
            "message": "Worker started remote job execution.",
        },
        token=token,
    )
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    workspace = _workspace_for_job(job, payload, root)
    _json_request(
        controller,
        "/api/cluster/worker/events",
        {
            "jobId": job["jobId"],
            "leaseId": lease["leaseId"],
            "hostId": capabilities["hostId"],
            "kind": "worker.process_registered",
            "message": "Worker registered remote job process.",
            "payload": {
                "processId": os.getpid(),
                "parentProcessId": os.getppid() if hasattr(os, "getppid") else 0,
                "missionId": str(job.get("missionId") or ""),
                "processKind": "cluster_worker_job",
                "command": str(payload.get("command") or payload.get("launchCommand") or ""),
                "cwd": str(workspace),
                "ttlSeconds": max(1, int(payload.get("timeoutSeconds") or payload.get("timeout_seconds") or 1800)) + 120,
            },
        },
        token=token,
    )
    stop, thread = _start_controller_lease_heartbeat(
        root=root,
        controller=controller,
        token=token,
        host_id=capabilities["hostId"],
        lease_id=lease["leaseId"],
        process_id=os.getpid(),
        max_concurrent_jobs=max_concurrent_jobs,
    )
    try:
        result = execute_job(job, lease, root=root)
    finally:
        stop.set()
        thread.join(timeout=1)
    circuit_result = _json_request(
        controller,
        "/api/cluster/worker/provider-result",
        {
            "jobId": job["jobId"],
            "leaseId": lease["leaseId"],
            "hostId": capabilities["hostId"],
            "result": result,
        },
        token=token,
    )
    result["providerCircuit"] = circuit_result.get("circuit", {})
    result["providerClassification"] = circuit_result.get("classification", classify_provider_result(job, result))
    for event in result.get("phaseEvents", []):
        if not isinstance(event, dict):
            continue
        _json_request(
            controller,
            "/api/cluster/worker/events",
            {
                "jobId": job["jobId"],
                "leaseId": lease["leaseId"],
                "hostId": capabilities["hostId"],
                "kind": str(event.get("kind") or "worker.phase"),
                "message": str(event.get("message") or "Worker phase completed."),
                "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
            },
            token=token,
        )
    completed = _json_request(
        controller,
        "/api/cluster/worker/complete",
        {
            "jobId": job["jobId"],
            "leaseId": lease["leaseId"],
            "hostId": capabilities["hostId"],
            "status": result["status"],
            "detail": result["detail"],
            "artifacts": result.get("artifacts", []),
            "changedFiles": result.get("changedFiles", []),
            "result": result,
        },
        token=token,
    )
    _json_request(
        controller,
        "/api/cluster/worker/events",
        {
            "jobId": job["jobId"],
            "leaseId": lease["leaseId"],
            "hostId": capabilities["hostId"],
            "kind": "worker.process_completed",
            "message": "Worker job process finished.",
            "payload": {
                "processId": os.getpid(),
                "status": result["status"],
                "reason": result["detail"],
            },
        },
        token=token,
    )
    return {"ok": True, "claimed": True, "job": completed.get("job"), "result": result}


def _observed_local_capabilities(root: Path, host_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    from .proofs_d_runtime_auth import observed_worker_capabilities
    return observed_worker_capabilities(root, host_id, observation)


def build_worker_doctor(root: Path, *, host_id: str = "", observed_capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_host = host_id or current_host_id()
    capabilities = build_local_worker_capabilities(root, host_id=resolved_host) if observed_capabilities is None else _observed_local_capabilities(root, resolved_host, observed_capabilities)
    registry = ClusterRegistry(root)
    circuits = registry.list_provider_circuits(limit=100)
    circuit_issues = [
        {
            "severity": "warn",
            "kind": "provider_circuit_" + str(item.get("state") or "unknown"),
            "detail": (
                f"{item.get('provider')} on {item.get('hostId')} is {item.get('state')} "
                f"({item.get('reason') or 'no reason'}); retry after {item.get('retryAfter') or 'n/a'}."
            ),
            "circuit": item,
        }
        for item in circuits
        if str(item.get("state") or "closed") in {"open", "half_open"}
    ]
    result = {
        "schema": "fluxio.worker_doctor.v1",
        "status": (
            "limited"
            if not capabilities["runtimes"]
            else ("warn" if circuit_issues else "ready")
        ),
        "root": str(root),
        "capabilities": capabilities,
        "providerCircuits": circuits,
        "circuitIssues": circuit_issues,
        "issues": (
            []
            if capabilities["runtimes"]
            else ["No Neyvia runtimes were detected for this worker root."]
        ),
    }
    from .proofs_d_runtime_auth import check_worker_doctor
    check_worker_doctor(result)
    return result


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Run a Neyvia cluster worker.")
    parser.add_argument("--root", default=".", help="Local worker root path")
    parser.add_argument("--controller", default="", help="NAS controller base URL")
    parser.add_argument("--host-id", default="", help="Stable worker host id")
    parser.add_argument("--token-file", default="", help="Worker token file")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument(
        "--max-jobs",
        type=_parse_max_jobs_arg,
        default=_parse_max_jobs_arg(
            os.environ.get("FLUXIO_WORKER_MAX_JOBS", "unlimited")
        ),
        help="Maximum concurrent jobs, or 0/unlimited for provider-governed concurrency",
    )
    parser.add_argument(
        "--startup-gate-file",
        default="",
        help="Advertise readiness but do not claim jobs while this transaction gate exists.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if args.doctor:
        print(json.dumps(build_worker_doctor(root, host_id=args.host_id), indent=2))
        return 0

    token = _load_token(root, args.token_file)
    if args.controller and not token:
        print(json.dumps({"ok": False, "error": "Worker token is required for remote controller polling."}, indent=2))
        return 2

    host_id = args.host_id or current_host_id()
    try:
        _claim_worker_process(root)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 3

    exit_code = 0
    executor: concurrent.futures.ThreadPoolExecutor | None = None
    unlimited_attempts: dict[concurrent.futures.Future, threading.Thread] = {}
    published_poll_state = None
    published_poll_at = 0.0
    connections = ExitStack()
    local_registry = None
    try:
        _write_worker_state(
            root,
            status="starting",
            host_id=host_id,
            controller=args.controller,
        )
        if not args.controller:
            local_registry = connections.enter_context(ClusterRegistry(root).connection_scope())
        max_jobs = normalize_concurrency_limit(args.max_jobs)
        unlimited = max_jobs == 0
        if not args.once and not unlimited:
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max_jobs,
                thread_name_prefix="fluxio-worker",
            )
            futures: set[concurrent.futures.Future] = set()
        elif not args.once:
            futures = set()
            admission: concurrent.futures.Future | None = None
            next_admission_at = 0.0
        while True:
            startup_gated = bool(
                args.startup_gate_file
                and Path(args.startup_gate_file).expanduser().is_file()
            )
            if startup_gated:
                capabilities = build_local_worker_capabilities(
                    root,
                    host_id=host_id,
                    max_concurrent_jobs=max_jobs,
                )
                if args.controller:
                    _json_request(
                        args.controller,
                        "/api/cluster/worker/heartbeat",
                        capabilities,
                        token=token,
                    )
                else:
                    ClusterRegistry(root).heartbeat_host(capabilities)
                _write_worker_state(
                    root,
                    status="idle",
                    host_id=host_id,
                    controller=args.controller,
                    result={"claimed": False, "job": {}, "startupGated": True},
                )
                if args.once:
                    return 0
                time.sleep(max(0.25, min(1.0, float(args.poll_seconds))))
                continue
            if not args.once:
                completed = {future for future in futures if future.done()}
                for future in completed:
                    futures.remove(future)
                    finished_thread = unlimited_attempts.pop(future, None)
                    if finished_thread is not None:
                        finished_thread.join(timeout=0)
                    try:
                        result = future.result()
                        print(json.dumps(result, indent=2))
                    except Exception as exc:
                        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                        print(json.dumps(result, indent=2))

                if unlimited:
                    now = time.monotonic()
                    if admission is not None and admission.done():
                        try:
                            admitted = bool(admission.result())
                        except Exception:
                            admitted = False
                        admission = None
                        next_admission_at = now if admitted else now + max(0.25, float(args.poll_seconds))

                    if admission is None and now >= next_admission_at:
                        def unlimited_runner(
                            observer: Callable[[bool], None],
                        ) -> dict[str, Any]:
                            if args.controller:
                                return run_controller_worker_once(
                                    root=root,
                                    controller=args.controller,
                                    token=token,
                                    host_id=host_id,
                                    max_concurrent_jobs=0,
                                    claim_observer=observer,
                                )
                            return run_local_worker_once(
                                root,
                                host_id=host_id,
                                max_concurrent_jobs=0,
                                claim_observer=observer,
                                registry=local_registry,
                            )

                        future, admission, thread = _start_unlimited_worker_attempt(
                            unlimited_runner
                        )
                        from .proofs_a_cli_scheduler import check_unlimited_admission
                        check_unlimited_admission(max_jobs, executor, future, admission, thread)
                        futures.add(future)
                        unlimited_attempts[future] = thread
                while not unlimited and len(futures) < max_jobs:
                    runner = run_controller_worker_once if args.controller else run_local_worker_once
                    if args.controller:
                        future = executor.submit(
                            runner,
                            root=root,
                            controller=args.controller,
                            token=token,
                            host_id=host_id,
                            max_concurrent_jobs=max_jobs,
                        )
                    else:
                        future = executor.submit(
                            runner,
                            root,
                            host_id=host_id,
                            max_concurrent_jobs=max_jobs,
                            registry=local_registry,
                        )
                    futures.add(future)
                    if len(futures) >= max_jobs:
                        break
                poll_state = ("working" if futures else "idle", bool(futures))
                # Publish transitions immediately; an unchanged receipt needs
                # only a periodic heartbeat, not an fsync for every 50 ms poll.
                # Five seconds stays below the 15-second lease heartbeat.
                if poll_state != published_poll_state or time.monotonic() - published_poll_at >= 5:
                    _write_worker_state(
                        root, status=poll_state[0], host_id=host_id,
                        controller=args.controller,
                        result={"claimed": poll_state[1], "job": {}},
                    )
                    published_poll_state = poll_state
                    published_poll_at = time.monotonic()
                wait_targets = futures | (
                    {admission} if unlimited and admission is not None else set()
                )
                wait_timeout = (
                    max(0.05, min(1.0, float(args.poll_seconds)))
                    if unlimited
                    else max(1.0, float(args.poll_seconds))
                )
                if wait_targets:
                    concurrent.futures.wait(
                        wait_targets,
                        timeout=wait_timeout,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                else:
                    time.sleep(wait_timeout)
                continue
            try:
                if args.controller:
                    result = run_controller_worker_once(
                        root=root,
                        controller=args.controller,
                        token=token,
                        host_id=host_id,
                        max_concurrent_jobs=max_jobs,
                    )
                else:
                    result = run_local_worker_once(
                        root,
                        host_id=host_id,
                        max_concurrent_jobs=max_jobs,
                        registry=local_registry,
                    )
                _write_worker_state(
                    root,
                    status="working" if result.get("claimed") else "idle",
                    host_id=host_id,
                    controller=args.controller,
                    result=result,
                )
                print(json.dumps(result, indent=2))
                exit_code = 0
            except Exception as exc:
                exit_code = 1
                failure = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                _write_worker_state(
                    root,
                    status="degraded",
                    host_id=host_id,
                    controller=args.controller,
                    error=failure["error"],
                )
                print(json.dumps(failure, indent=2))
            if args.once:
                return exit_code
            time.sleep(max(1.0, float(args.poll_seconds)))
    except KeyboardInterrupt:
        return 130
    finally:
        connections.close()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        try:
            previous = _read_worker_state(root)
            _write_worker_state(
                root,
                status="stopped",
                host_id=host_id,
                controller=args.controller,
                error=str(previous.get("lastError") or ""),
            )
        finally:
            _release_worker_process(root)



if __name__ == "__main__":
    raise SystemExit(main())
