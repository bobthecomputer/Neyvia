from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .cluster import ClusterRegistry
from .crashproof import CrashProofStore


EXTENSION_KINDS = {
    "extension.research",
    "extension.browser",
    "extension.computer-use",
    "model.train",
}


class NeyviaCoordinator:
    """Bridges durable tasks to background cluster jobs without model polling."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.store = CrashProofStore(self.root)
        self.cluster = ClusterRegistry(self.root)

    def reconcile_once(self) -> dict[str, Any]:
        recovered = self.store.recover_interrupted()
        queued: list[str] = []
        reconciled: list[str] = []
        for task in reversed(self.store.list_tasks(limit=1000)):
            if task["kind"] == "extension.model-training-batch":
                if self._reconcile_batch(task):
                    reconciled.append(task["taskId"])
                continue
            if task["kind"] not in EXTENSION_KINDS:
                continue
            checkpoint = task.get("checkpoint") or {}
            cluster_job_id = str(checkpoint.get("clusterJobId") or f"neyvia_{task['taskId']}")
            if task["status"] == "queued":
                self._queue_cluster_job(task, cluster_job_id)
                self.store.transition_task(
                    task["taskId"],
                    "waiting",
                    checkpoint={**checkpoint, "clusterJobId": cluster_job_id, "wakePolicy": "terminal_or_input_only"},
                    event_payload={"clusterJobId": cluster_job_id},
                )
                queued.append(task["taskId"])
                continue
            if task["status"] in {"waiting", "working"}:
                job = self.cluster.get_job(cluster_job_id)
                if job and job.get("status") in {"failed", "blocked", "cancelled"} and task["status"] != "failed":
                    self.store.transition_task(
                        task["taskId"],
                        "failed",
                        error={"clusterJobId": cluster_job_id, "status": job.get("status"), "detail": job.get("statusDetail")},
                    )
                    reconciled.append(task["taskId"])
        return {
            "schema": "neyvia.coordinator-reconcile.v1",
            "recovered": recovered,
            "queued": queued,
            "reconciled": reconciled,
        }

    def _queue_cluster_job(self, task: dict[str, Any], cluster_job_id: str) -> None:
        required_capabilities: list[str] = ["command.run"]
        preferred_host = ""
        if task["kind"] == "extension.browser":
            required_capabilities.append("browser.verify")
        elif task["kind"] == "extension.computer-use":
            required_capabilities.append("computer.use.isolated")
        elif task["kind"] == "model.train":
            required_capabilities.append("runtime.launch")
        self.cluster.upsert_job(
            job_id=cluster_job_id,
            mission_id=task["missionId"],
            workspace_id="neyvia",
            lane_role="extension-worker",
            runtime_id="python",
            job_kind=task["kind"],
            preferred_host=preferred_host,
            required_capabilities=required_capabilities,
            required_artifacts=["task_result"],
            payload={
                "command": [
                    "python",
                    "-m",
                    "grant_agent.neyvia_extension_worker",
                    "--root",
                    str(self.root),
                    "--task-id",
                    task["taskId"],
                ],
                "executionRoot": str(self.root),
                "timeoutSeconds": 86400 if task["kind"] == "model.train" else 3600,
                "neyviaTaskId": task["taskId"],
            },
            status="queued",
            status_detail="N-E-Y-V-I-A durable extension task is ready for a background worker.",
        )

    def _reconcile_batch(self, task: dict[str, Any]) -> bool:
        if task["status"] in {"completed", "failed", "cancelled"}:
            return False
        children = [row for row in self.store.list_tasks(mission_id=task["missionId"], limit=1000) if row["parentTaskId"] == task["taskId"]]
        if not children:
            return False
        counts: dict[str, int] = {}
        for child in children:
            counts[child["status"]] = counts.get(child["status"], 0) + 1
        terminal = sum(counts.get(state, 0) for state in ("completed", "failed", "cancelled"))
        if terminal != len(children):
            if task["status"] == "queued":
                self.store.transition_task(task["taskId"], "waiting", checkpoint={"childCount": len(children), "counts": counts})
            elif task["status"] == "waiting":
                self.store.transition_task(task["taskId"], "waiting", checkpoint={"childCount": len(children), "counts": counts})
            return False
        if task["status"] == "queued":
            task = self.store.transition_task(
                task["taskId"],
                "waiting",
                checkpoint={"childCount": len(children), "counts": counts},
            )
        if counts.get("failed") or counts.get("cancelled"):
            self.store.transition_task(task["taskId"], "failed", error={"childCount": len(children), "counts": counts})
        else:
            self.store.transition_task(task["taskId"], "completed", result={"childCount": len(children), "counts": counts})
        return True


def start_coordinator_loop(root: str | Path, *, interval_seconds: float = 2.0) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()
    coordinator = NeyviaCoordinator(root)

    def _loop() -> None:
        while not stop.is_set():
            try:
                coordinator.reconcile_once()
            except Exception:
                pass
            stop.wait(max(0.5, interval_seconds))

    thread = threading.Thread(target=_loop, name="neyvia-coordinator", daemon=True)
    thread.start()
    return stop, thread
