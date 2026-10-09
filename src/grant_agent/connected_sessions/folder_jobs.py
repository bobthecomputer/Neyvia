"""Durable, hidden worktree checkout jobs independent of the request/service lifetime."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from grant_agent.durability import atomic_write_json
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

_WORKERS: dict[str, subprocess.Popen] = {}


def _path(root: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("That worktree job was not found.")
    return Path(root) / ".agent_control/folder-jobs" / (job_id + ".json")


def start(root: Path, repo: Path, target: Path, branch: str) -> dict:
    job_id = uuid.uuid4().hex
    path = _path(root, job_id)
    data = {"jobId": job_id, "status": "queued", "path": str(target), "branch": branch,
            "repo": str(repo), "createdAt": time.time(), "pid": None, "error": None}
    atomic_write_json(path, data)
    try:
        _WORKERS[job_id] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **hidden_windows_subprocess_kwargs())
    except OSError:
        data.update(status="failed", error="The worktree checkout could not start. Check that Git is available and try again.")
        atomic_write_json(path, data)
    return _public(data)


def _public(data: dict) -> dict:
    return {key: data.get(key) for key in ("jobId", "status", "path", "branch", "error", "progress", "message")}


def checkout_progress(text: str, state: str) -> tuple[int | None, str]:
    if state == "completed":
        return 100, "Worktree ready"
    if state == "failed":
        return None, "Worktree couldn't be created"
    percentages = re.findall(r"Updating files:\s*(\d{1,3})%", text)
    percent = min(100, int(percentages[-1])) if percentages else None
    return percent, "Finishing checkout" if percent == 100 else "Checking out files" if state == "running" else "Preparing worktree"


def status(root: Path, job_id: str) -> dict:
    path = _path(root, job_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("That worktree job was not found.") from None
    if data["status"] in {"queued", "running"}:
        from grant_agent.chat_run_control import process_started_at
        worker = _WORKERS.get(job_id)
        exited = worker is not None and worker.poll() is not None
        orphaned = worker is None and time.time() - data["createdAt"] > 10 and (
            not data.get("pid") or process_started_at(data["pid"]) != data.get("processStartedAt"))
        if exited or orphaned:
            # The worker may have atomically completed between our read and poll.
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["status"] in {"queued", "running"}:
                data.update(status="failed", error="The worktree checkout stopped unexpectedly. Check the destination folder before trying again.")
                atomic_write_json(path, data)
    worker = _WORKERS.get(job_id)
    if worker and worker.poll() is not None:
        _WORKERS.pop(job_id, None)
    log = path.with_suffix(".log")
    text = ""
    if log.exists():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 16384))
            text = stream.read(16384).decode("utf-8", errors="replace")
    data["progress"], data["message"] = checkout_progress(text, data["status"])
    return _public(data)


def run_job(path: Path) -> None:
    from grant_agent.chat_run_control import process_started_at
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(status="running", pid=os.getpid(), processStartedAt=process_started_at(os.getpid()))
    atomic_write_json(path, data)
    log = path.with_suffix(".log")
    try:
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen([shutil.which("git") or "git", "worktree", "add", "--no-quiet", "-b", data["branch"], data["path"]],
                cwd=data["repo"], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PROGRESS_DELAY": "0"}, **hidden_windows_subprocess_kwargs())
            # Large checkouts have no fixed deadline. The hidden worker keeps
            # owning/reaping Git even when a client reloads or the service stops.
            code = process.wait()
        if code == 0:
            data.update(status="completed", error=None)
        else:
            raw = log.read_text(encoding="utf-8", errors="replace")[-800:]
            reason = next((line[6:].strip() for line in raw.splitlines() if line.startswith("fatal:")), "Git could not finish checking out the files.")
            data.update(status="failed", error="The worktree could not be created. " + reason + " Check the destination folder before retrying.")
    except OSError:
        data.update(status="failed", error="The worktree checkout could not start. Check that Git and the destination folder are available.")
    atomic_write_json(path, data)


if __name__ == "__main__":
    run_job(Path(sys.argv[1]))
