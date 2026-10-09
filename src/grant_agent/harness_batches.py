"""Bounded prompt batches over the existing durable, isolated Harness jobs.

The batch owns scheduling only. Jobs own execution, capacity, deadlines,
receipts and process-tree cancellation. A lost or failed result never retries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any

from .harness_jobs import (
    HarnessJobStore, TERMINAL_JOB_STATUSES, _atomic_write_json,
    _exclusive_job_lock, _process_alive, _process_command_line, _utc_now,
)
from .harness_registry import HARNESS_SPECS
from .subprocess_utils import hidden_windows_subprocess_kwargs, install_hidden_subprocess_default

SCHEMA = "neyvia.harness-batch.v1"
STOPPED = TERMINAL_JOB_STATUSES | {"blocked", "uncertain"}


def _bounded_int(value: Any, default: int, low: int, high: int, name: str) -> int:
    value = default if value is None else value
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}.")
    return value


class HarnessBatchStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve(strict=True)
        self.directory = self.root / ".agent_control" / "harness_batches"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs = HarnessJobStore(self.root)

    def path(self, batch_id: str) -> Path:
        if not re.fullmatch(r"harness-batch-[a-f0-9]{32}", str(batch_id)):
            raise ValueError("Invalid batch identity.")
        return self.directory / f"{batch_id}.json"

    def load(self, batch_id: str) -> dict[str, Any]:
        record = json.loads(self.path(batch_id).read_text(encoding="utf-8"))
        if record.get("schema") != SCHEMA or record.get("id") != batch_id:
            raise ValueError("Unsupported batch record.")
        return record

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.directory.glob("harness-batch-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            record = self.load(path.stem)
            # Avoid shipping every prompt and result during history polling.
            rows.append({k: record[k] for k in ("id", "title", "status", "runtime", "model", "counts", "updatedAt", "maxParallel")})
        return rows

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("requestId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ValueError("A stable batch requestId is required.")
        prompts = payload.get("prompts")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 100:
            raise ValueError("Provide 1 to 100 prompts.")
        if any(not isinstance(p, str) or not p.strip() or len(p) > 16000 for p in prompts):
            raise ValueError("Every prompt must contain 1 to 16000 characters.")
        if sum(len(p.encode("utf-8")) for p in prompts) > 256000:
            raise ValueError("The combined prompts exceed 256 KB.")
        runtime = str(payload.get("runtime") or "")
        spec = next((s for s in HARNESS_SPECS if s.harness_id == runtime), None)
        if not spec or spec.security_only or runtime == "fluxio-hybrid":
            raise ValueError("Choose a general-purpose direct harness for prompt batches.")
        workspace = str(Path(payload.get("workspacePath") or self.root).resolve(strict=True))
        model = str(payload.get("model") or "").strip()
        if not model or len(model) > 180:
            raise ValueError("Choose an exact model before preparing a batch.")
        provider = str(payload.get("provider") or runtime).strip()
        if len(provider) > 100 or len(str(payload.get("harnessProfileId") or "")) > 150:
            raise ValueError("Invalid provider or profile identity.")
        parallel = _bounded_int(payload.get("maxParallel"), 2, 1, 4, "Concurrency")
        turns = _bounded_int(payload.get("maxTurns"), 4, 1, 20, "Turn limit")
        seconds = _bounded_int(payload.get("runtimeBudgetSeconds"), 120, 30, 300, "Per-prompt time limit")
        output = _bounded_int(payload.get("maxOutputTokens"), 1024, 128, 4096, "Output limit")
        effort = str(payload.get("effort") or "medium")
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("Unsupported effort.")
        request = {
            "runtime": runtime, "runtimeId": runtime, "harnessId": runtime,
            "harnessLabel": spec.label, "mode": "direct", "workspacePath": workspace,
            "model": model, "route": {"provider": provider, "model": model, "effort": effort},
            "harnessProfileId": str(payload.get("harnessProfileId") or ""),
            "exactRoute": True, "allowRuntimeFallback": False, "allowMutations": False,
            "readOnly": True, "maxTurns": turns, "maxOutputTokens": output,
            "maxRuntimeSeconds": seconds,
        }
        if runtime != "neyvia-agent":
            # External CLIs do not share Native's per-turn/output controls.
            # Their own profiles apply; the Harness worker's wall-clock limit
            # remains enforced for every adapter.
            request.pop("maxTurns")
            request.pop("maxOutputTokens")
        title = str(payload.get("title") or f"{spec.label} prompt batch").strip()[:160]
        identity = {"request": request, "prompts": prompts, "maxParallel": parallel, "title": title}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        batch_id = "harness-batch-" + hashlib.sha256(request_id.encode()).hexdigest()[:32]
        path = self.path(batch_id)
        with _exclusive_job_lock(path):
            if path.exists():
                saved = self.load(batch_id)
                if saved["requestHash"] != digest:
                    raise ValueError("This batch requestId already belongs to different work.")
                return saved
            now = _utc_now()
            record = {
                "schema": SCHEMA, "id": batch_id, "title": title, "requestHash": digest,
                "status": "prepared", "runtime": runtime, "model": model,
                "request": request, "maxParallel": parallel, "pid": None,
                "createdAt": now, "updatedAt": now, "error": "",
                "counts": {"pending": len(prompts)},
                "items": [{"index": i, "prompt": p, "status": "pending",
                           "jobId": "harness-job-" + hashlib.sha256(f"{batch_id}:{i}".encode()).hexdigest()[:32]}
                          for i, p in enumerate(prompts)],
            }
            _atomic_write_json(path, record)
            return record

    def start(self, batch_id: str) -> dict[str, Any]:
        path = self.path(batch_id)
        with _exclusive_job_lock(path):
            record = self.load(batch_id)
            if record["status"] in STOPPED:
                return record
            pid = int(record.get("pid") or 0)
            if pid and _process_alive(pid):
                command = _process_command_line(pid)
                if "grant_agent.harness_batches" not in command or batch_id not in command:
                    raise RuntimeError("Batch worker ownership is uncertain; inspect it before resuming.")
                return record
            command = [sys.executable, "-m", "grant_agent.harness_batches", "--root", str(self.root), "--batch-id", batch_id]
            env = dict(os.environ)
            if sys.dont_write_bytecode:
                # Interpreter flags are not inherited through Popen. Preserve
                # a sealed release's no-write policy in workers and children.
                env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH", "")]))
            kwargs = hidden_windows_subprocess_kwargs(new_process_group=True)
            if os.name != "nt":
                kwargs["start_new_session"] = True
            with path.with_suffix(".log").open("a", encoding="utf-8") as log:
                child = subprocess.Popen(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **kwargs)
            record.update(pid=child.pid, status="cancelling" if record["status"] == "cancelling" else "running", updatedAt=_utc_now(), error="")
            _atomic_write_json(path, record)
            threading.Thread(target=child.wait, daemon=True).start()
            return record

    def cancel(self, batch_id: str) -> dict[str, Any]:
        path = self.path(batch_id)
        with _exclusive_job_lock(path):
            record = self.load(batch_id)
            if record["status"] in STOPPED:
                return record
            record.update(status="cancelling", updatedAt=_utc_now())
            _atomic_write_json(path, record)
        # The normal supervisor performs child process-tree cleanup. It can
        # reconnect to those jobs even if the original supervisor has died.
        return self.start(batch_id)

    def advance(self, batch_id: str) -> dict[str, Any]:
        """One durable scheduling pass; all execution stays in HarnessJobStore."""
        path = self.path(batch_id)
        with _exclusive_job_lock(path):
            record = self.load(batch_id)
            if record["status"] not in {"running", "cancelling"}:
                return record
            cancelling = record["status"] == "cancelling"
            active = 0
            for item in record["items"]:
                if item["status"] in STOPPED:
                    continue
                try:
                    job = self.jobs.load(item["jobId"])
                except KeyError:
                    if item["status"] != "pending":
                        item.update(status="uncertain", error="Reserved job receipt is missing. It was not repeated.")
                    elif cancelling:
                        item["status"] = "cancelled"
                    continue
                if cancelling and job["status"] not in TERMINAL_JOB_STATUSES:
                    job = self.jobs.cancel(item["jobId"])
                item.update(status=job["status"], error=job.get("error", ""))
                if item["status"] in STOPPED:
                    item.update(result=job.get("result"), receiptPath=str(self.jobs.job_path(item["jobId"])))
                else:
                    active += 1
            if not cancelling:
                for item in record["items"]:
                    if item["status"] not in {"pending", "queued"}:
                        continue
                    if item["status"] == "pending" and active >= record["maxParallel"]:
                        break
                    request = {**record["request"], "message": item["prompt"], "objective": item["prompt"],
                               "batchId": batch_id, "sessionId": item["jobId"]}
                    # Reserve the deterministic identity BEFORE create/start.
                    # If the response is lost, resume reconciles this identity.
                    if item["status"] == "pending":
                        item["status"] = "reserved"
                        _atomic_write_json(path, record)
                    try:
                        job = self.jobs.create(request, job_id=item["jobId"])
                    except RuntimeError as exc:
                        if "admission capacity is exhausted" not in str(exc):
                            raise
                        item["status"] = "pending"  # Explicit refusal guarantees no job was created.
                        record["error"] = "Waiting for workspace job capacity."
                        break
                    if job["status"] == "queued":
                        job = self.jobs.start(job["id"])
                    item.update(status=job["status"], error=job.get("error", ""))
                    active += 1
            counts: dict[str, int] = {}
            for item in record["items"]:
                counts[item["status"]] = counts.get(item["status"], 0) + 1
            record["counts"] = counts
            if all(item["status"] in STOPPED for item in record["items"]):
                record["status"] = "blocked" if any(k in counts for k in {"blocked", "uncertain"}) else "cancelled" if cancelling else "failed" if any(k in counts for k in {"failed", "interrupted", "cancelled"}) else "completed"
                record["finishedAt"] = _utc_now()
            record["updatedAt"] = _utc_now()
            _atomic_write_json(path, record)
            return record


def main() -> None:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    store = HarnessBatchStore(Path(args.root))
    try:
        while store.advance(args.batch_id)["status"] in {"running", "cancelling"}:
            time.sleep(1)
    except Exception as exc:
        path = store.path(args.batch_id)
        with _exclusive_job_lock(path):
            record = store.load(args.batch_id)
            # Keep the task resumable. Child identities remain authoritative.
            record.update(error=f"Supervisor stopped: {type(exc).__name__}: {exc}", updatedAt=_utc_now())
            _atomic_write_json(path, record)
        raise


if __name__ == "__main__":
    main()
