from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.cli import bootstrap_project
from grant_agent.cluster import ClusterRegistry, current_host_id
from grant_agent.mission_control import ControlRoomStore
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from grant_agent.web_backend import FluxioWebBackend


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _mission_event_kinds(root: Path, mission_id: str) -> list[str]:
    path = root / ".agent_control" / "mission_events.jsonl"
    if not path.exists():
        return []
    kinds: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(event.get("mission_id") or event.get("missionId") or "") == mission_id:
            kinds.append(str(event.get("kind") or ""))
    return kinds


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove composer-arrow mission creation and bundled-worker execution."
    )
    parser.add_argument(
        "--proof-root",
        default=str(Path("C:/tmp") / f"fluxio-composer-worker-{_stamp()}"),
    )
    parser.add_argument("--runtime", default="openclaw", choices=["openclaw", "hermes"])
    parser.add_argument(
        "--model",
        default="gpt-5.6-sol",
        help="Exact model used for planner, executor, and verifier route overrides.",
    )
    parser.add_argument(
        "--node-bin-dir",
        default=(
            "C:/tmp/fluxio-node-v22.22.3/node-v22.22.3-win-x64"
            if Path("C:/tmp/fluxio-node-v22.22.3/node-v22.22.3-win-x64").exists()
            else ""
        ),
        help="Optional Node.js bin directory to prepend for runtime compatibility.",
    )
    parser.add_argument("--host-id", default=current_host_id())
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)

    proof_root = Path(args.proof_root).expanduser().resolve()
    workspace_root = proof_root / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "README.md").write_text(
        "# Composer worker proof\n\nThis isolated workspace verifies a real bundled worker dispatch.\n",
        encoding="utf-8",
    )
    bootstrap_project(proof_root)
    store = ControlRoomStore(proof_root)
    workspace = store.upsert_workspace(
        name="Composer worker proof",
        root_path=str(workspace_root),
        default_runtime=args.runtime,
        user_profile="builder",
        preferred_harness="fluxio_hybrid",
    )

    python_path = os.pathsep.join(
        item
        for item in (str(SRC), str(os.environ.get("PYTHONPATH") or ""))
        if item
    )
    previous_python_path = os.environ.get("PYTHONPATH")
    previous_path = os.environ.get("PATH")
    previous_worker_host = os.environ.get("FLUXIO_MISSION_WORKER_HOST_ID")
    os.environ["PYTHONPATH"] = python_path
    node_bin_dir = str(Path(args.node_bin_dir).expanduser().resolve()) if args.node_bin_dir else ""
    if node_bin_dir:
        os.environ["PATH"] = os.pathsep.join(
            item for item in (node_bin_dir, str(previous_path or "")) if item
        )
    os.environ["FLUXIO_MISSION_WORKER_HOST_ID"] = str(args.host_id)
    try:
        backend = FluxioWebBackend(proof_root, proof_root)
        launch = backend.dispatch(
            "quickstart_control_room_mission_command",
            {
                "objective": (
                    "Create WORKER_PROOF.txt in the isolated workspace with exactly "
                    "this public text: GPT-5.6 Sol worker proof OK. Verify the file and finish."
                ),
                "workspaceId": workspace.workspace_id,
                "runtime": args.runtime,
                "mode": "Autopilot",
                "successChecks": [
                    "WORKER_PROOF.txt exists and contains exactly GPT-5.6 Sol worker proof OK."
                ],
                "routeOverrides": [
                    {
                        "role": role,
                        "provider": "openai-codex",
                        "model": args.model,
                        "effort": "high",
                    }
                    for role in ("planner", "executor", "verifier")
                ],
                "clientLaunchToken": f"composer-worker-proof-{_stamp()}",
            },
        )
    finally:
        if previous_python_path is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous_python_path
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path
        if previous_worker_host is None:
            os.environ.pop("FLUXIO_MISSION_WORKER_HOST_ID", None)
        else:
            os.environ["FLUXIO_MISSION_WORKER_HOST_ID"] = previous_worker_host

    mission_id = str(
        launch.get("mission_id")
        or launch.get("missionId")
        or (launch.get("mission") or {}).get("mission_id")
        or ""
    )
    dispatch = launch.get("dispatch") if isinstance(launch.get("dispatch"), dict) else {}
    job_id = str(dispatch.get("jobId") or "")
    mission_before = store.get_mission(mission_id)
    registry = ClusterRegistry(proof_root)
    job_before = registry.get_job(job_id)

    worker_env = os.environ.copy()
    worker_env["PYTHONPATH"] = python_path
    if node_bin_dir:
        worker_env["PATH"] = os.pathsep.join(
            item for item in (node_bin_dir, str(worker_env.get("PATH") or "")) if item
        )
    worker_env["FLUXIO_MISSION_DISPATCH_MODE"] = "cluster_worker"
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "grant_agent.worker",
            "--root",
            str(proof_root),
            "--host-id",
            str(args.host_id),
            "--once",
        ],
        cwd=str(ROOT),
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    deadline = time.monotonic() + max(10, int(args.timeout_seconds))
    observed_statuses: list[str] = []
    observed_heartbeat = ""
    observed_worker_started = False
    job_reached_terminal_state = False
    while time.monotonic() < deadline:
        job = registry.get_job(job_id)
        status = str(job.get("status") or "")
        if status and (not observed_statuses or observed_statuses[-1] != status):
            observed_statuses.append(status)
        lease_id = str(job.get("leaseId") or "")
        if lease_id:
            lease = registry.get_lease(lease_id)
            observed_heartbeat = str(lease.get("heartbeatAt") or observed_heartbeat)
        events = registry.list_events(limit=100)
        observed_worker_started = observed_worker_started or any(
            str(item.get("jobId") or "") == job_id
            and str(item.get("kind") or "") == "worker.started"
            for item in events
        )
        job_reached_terminal_state = status in {"completed", "failed", "blocked", "stopped"}
        if job_reached_terminal_state or worker.poll() is not None:
            break
        time.sleep(0.5)

    if job_reached_terminal_state and worker.poll() is None:
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    worker_wrapper_exited = worker.poll() is not None
    if not worker_wrapper_exited:
        _terminate_process(worker)
    stdout, stderr = worker.communicate(timeout=15)

    mission_after = store.get_mission(mission_id)
    job_after = registry.get_job(job_id)
    host = next(
        (
            item
            for item in registry.list_hosts()
            if str(item.get("hostId") or "") == str(args.host_id)
        ),
        {},
    )
    event_kinds = _mission_event_kinds(proof_root, mission_id)
    mission_status = str(
        getattr(getattr(mission_after, "state", None), "status", "")
    ).strip().lower()
    job_status = str(job_after.get("status") or "").strip().lower()
    checks = {
        "canonicalMissionRow": bool(mission_before and mission_after),
        "workerJobBoundToMission": str(job_before.get("missionId") or "") == mission_id,
        "workerHeartbeatObserved": bool(observed_heartbeat or host.get("lastHeartbeatAt")),
        "workerStartedObserved": observed_worker_started,
        "workerProgressObserved": any(
            status in {"leased", "running", "completed", "failed", "blocked"}
            for status in observed_statuses
        ),
        "missionRuntimeProgressObserved": any(
            kind
            in {
                "runtime.status",
                "mission.cycle_started",
                "mission.runtime_started",
                "mission.runtime_cycle",
                "mission.completed",
                "mission.blocked",
            }
            for kind in event_kinds
        ),
        "workerJobReachedTerminalState": job_reached_terminal_state,
        "workerJobCompleted": job_status == "completed",
        "missionReachedSuccessfulTerminalState": mission_status
        in {"completed", "complete", "succeeded", "success"},
        "workerWrapperExited": worker_wrapper_exited,
    }
    receipt = {
        "schema": "fluxio.composer_worker_e2e_proof.v1",
        "ok": all(checks.values()),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "proofRoot": str(proof_root),
        "missionId": mission_id,
        "jobId": job_id,
        "dispatch": dispatch,
        "checks": checks,
        "observedJobStatuses": observed_statuses,
        "job": job_after,
        "host": host,
        "leaseHeartbeatAt": observed_heartbeat,
        "missionStatus": mission_status,
        "missionEventKinds": event_kinds,
        "workerReturnCode": worker.returncode,
        "workerWrapperExited": worker_wrapper_exited,
        "workerStdoutTail": stdout[-4000:],
        "workerStderrTail": stderr[-4000:],
    }
    receipt_path = proof_root / ".agent_control" / "proofs" / "composer_worker_e2e.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    receipt["receiptPath"] = str(receipt_path)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
