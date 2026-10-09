from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.crashproof import CrashProofStore  # noqa: E402
from grant_agent.durability import atomic_write_json  # noqa: E402
from grant_agent.neyvia_coordinator import NeyviaCoordinator  # noqa: E402
from grant_agent.neyvia_extension_worker import run_extension_task  # noqa: E402
from grant_agent.neyvia_mcp import NeyviaMCPServer  # noqa: E402
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mcp_call(server: NeyviaMCPServer, name: str, arguments: dict) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments, "task": {"ttl": 86_400_000}},
        }
    )
    if not response or "error" in response:
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return response["result"]


def _prove_process_loss_recovery(root: Path, campaign_id: str) -> dict:
    store = CrashProofStore(root)
    task = store.submit_task(
        mission_id=campaign_id,
        kind="campaign.process-loss",
        idempotency_key=f"{campaign_id}:process-loss",
        payload={"proof": "worker exits without releasing its lease"},
    )
    if task["status"] == "completed":
        return task["result"]
    if task["status"] == "working":
        store.transition_task(task["taskId"], "queued")
    code = (
        "import os,sys;"
        f"sys.path.insert(0,{str(SRC)!r});"
        "from grant_agent.crashproof import CrashProofStore;"
        f"s=CrashProofStore({str(root)!r});"
        "t=s.claim_next(worker_id='campaign-crashed-worker',kinds=['campaign.process-loss'],lease_seconds=1);"
        "os._exit(23 if t else 24)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root),
        capture_output=True,
        timeout=20,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    if completed.returncode != 23:
        raise RuntimeError(f"crash worker did not claim and exit as expected: {completed.returncode}")
    recovery_time = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")
    reopened = CrashProofStore(root)
    recovered = reopened.recover_interrupted(now=recovery_time)
    if task["taskId"] not in recovered:
        raise RuntimeError("expired task lease was not recovered after process loss")
    reopened.transition_task(task["taskId"], "working", event_payload={"worker": "campaign-recovery"})
    result = {
        "status": "completed",
        "crashedExitCode": completed.returncode,
        "recoveredTaskId": task["taskId"],
        "reopenedDatabase": True,
    }
    reopened.transition_task(task["taskId"], "completed", result=result)
    return result


def _prove_browser_resume(root: Path, campaign_id: str) -> dict:
    store = CrashProofStore(root)
    task = store.submit_task(
        mission_id=campaign_id,
        kind="extension.browser",
        idempotency_key=f"{campaign_id}:browser-resume",
        payload={
            "objective": "Resume deterministic browser work after a worker process loss.",
            "actions": [
                {"id": "navigate", "type": "navigate", "url": "data:text/html,<main id='proof'>N-E-Y-V-I-A resumed</main>"},
                {"id": "read", "type": "read", "selector": "#proof"},
                {"id": "screenshot", "type": "screenshot", "name": "browser-resumed.png"},
            ],
        },
    )
    if task["status"] == "completed":
        return task["result"]
    if task["status"] != "working":
        store.transition_task(task["taskId"], "working")
    store.transition_task(
        task["taskId"],
        "working",
        checkpoint={
            "actionIndex": 1,
            "url": "data:text/html,<main id='proof'>N-E-Y-V-I-A resumed</main>",
            "outputs": [],
            "screenshots": [],
        },
        event_payload={"simulatedCrashAfterActionIndex": 1},
    )
    result = run_extension_task(root, task["taskId"])
    if not result.get("outputs") or result["outputs"][0].get("text") != "N-E-Y-V-I-A resumed":
        raise RuntimeError("browser checkpoint did not resume at the persisted URL")
    return result


def run_campaign(root: Path, campaign_id: str, output: Path) -> dict:
    started = time.perf_counter()
    server = NeyviaMCPServer(root)
    accepted = _mcp_call(
        server,
        "neyvia.training.batch.start",
        {
            "missionId": campaign_id,
            "idempotencyKey": f"{campaign_id}:28-model-batch",
            "modelCount": 28,
            "training": {
                "kind": "torch.linear.proof",
                "device": "cpu",
                "samples": 96,
                "epochs": 60,
                "learningRate": 0.1,
            },
        },
    )
    parent_id = accepted["task"]["taskId"]
    process_loss = _prove_process_loss_recovery(root, campaign_id)
    browser_resume = _prove_browser_resume(root, campaign_id)

    store = CrashProofStore(root)
    children = sorted(
        (task for task in store.list_tasks(mission_id=campaign_id, limit=1000) if task["parentTaskId"] == parent_id),
        key=lambda task: int(task["payload"].get("modelIndex", 0)),
    )
    if len(children) != 28:
        raise RuntimeError(f"expected 28 durable model tasks, found {len(children)}")

    completed_models: list[dict] = []
    for index, child in enumerate(children):
        current = CrashProofStore(root).get_task(child["taskId"])
        if current["status"] == "completed":
            metrics = current["result"]
        else:
            metrics = run_extension_task(root, current["taskId"])
        model_path = Path(metrics["modelPath"])
        if not metrics.get("improved") or not model_path.is_file():
            raise RuntimeError(f"model {index} lacks real improving training proof")
        completed_models.append(
            {
                "modelIndex": metrics["modelIndex"],
                "taskId": current["taskId"],
                "seed": metrics["seed"],
                "device": metrics["device"],
                "initialLoss": metrics["initialLoss"],
                "finalLoss": metrics["finalLoss"],
                "modelPath": str(model_path),
                "modelSha256": _sha256(model_path),
            }
        )
        atomic_write_json(
            output,
            {
                "schema": "neyvia.crash-campaign.progress.v1",
                "campaignId": campaign_id,
                "status": "running",
                "completedModelCount": len(completed_models),
                "expectedModelCount": 28,
                "updatedAt": _utc_now(),
            },
        )

    NeyviaCoordinator(root).reconcile_once()
    final_store = CrashProofStore(root)
    parent = final_store.get_task(parent_id)
    campaign_tasks = final_store.list_tasks(mission_id=campaign_id, limit=1000)
    started_at = min(_parse_time(task["createdAt"]) for task in campaign_tasks)
    terminal_times = [
        _parse_time(task["completedAt"])
        for task in campaign_tasks
        if task.get("completedAt")
    ]
    completed_at = max(terminal_times) if terminal_times else datetime.now(timezone.utc)
    event_counts = {
        "processLoss": len(final_store.task_events(process_loss["recoveredTaskId"])),
        "browserResume": len(
            final_store.task_events(
                next(task["taskId"] for task in final_store.list_tasks(mission_id=campaign_id, limit=1000) if task["idempotencyKey"] == f"{campaign_id}:browser-resume")
            )
        ),
    }
    receipt = {
        "schema": "neyvia.crash-campaign.receipt.v1",
        "campaignId": campaign_id,
        "product": "N-E-Y-V-I-A",
        "scope": {"auvHapsIncluded": False},
        "status": "passed",
        "startedAt": started_at.isoformat().replace("+00:00", "Z"),
        "completedAt": completed_at.isoformat().replace("+00:00", "Z"),
        "durationSeconds": round((completed_at - started_at).total_seconds(), 3),
        "verificationRunSeconds": round(time.perf_counter() - started, 3),
        "sparseRuntime": {
            "modelWakePolling": False,
            "wakePolicy": "terminal_or_input_only",
            "durableTaskCount": 28,
        },
        "processLossRecovery": process_loss,
        "browserCheckpointRecovery": {
            "resumedText": browser_resume["outputs"][0]["text"],
            "screenshotPaths": browser_resume["screenshots"],
        },
        "trainingBatch": {
            "parentTaskId": parent_id,
            "parentStatus": parent["status"],
            "completedModelCount": len(completed_models),
            "allImproved": all(item["finalLoss"] < item["initialLoss"] for item in completed_models),
            "distinctSeeds": len({item["seed"] for item in completed_models}),
            "models": completed_models,
        },
        "eventCounts": event_counts,
        "durability": {"journalMode": "WAL", "synchronous": "FULL", "databaseReopenedBetweenModels": True},
    }
    if parent["status"] != "completed" or len(completed_models) != 28 or receipt["trainingBatch"]["distinctSeeds"] != 28:
        raise RuntimeError("campaign acceptance gate failed")
    atomic_write_json(output, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the N-E-Y-V-I-A 28-model crash-proof campaign.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--campaign-id", default="neyvia-crash-campaign-20260721-v1")
    parser.add_argument("--output", default=".agent_control/runtime_proof/neyvia-crash-campaign-20260721.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    receipt = run_campaign(root, args.campaign_id, output)
    print(json.dumps({
        "ok": True,
        "campaignId": receipt["campaignId"],
        "durationSeconds": receipt["durationSeconds"],
        "completedModelCount": receipt["trainingBatch"]["completedModelCount"],
        "allImproved": receipt["trainingBatch"]["allImproved"],
        "receipt": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
