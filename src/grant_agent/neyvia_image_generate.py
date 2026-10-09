"""Image generation through the Codex CLI's own built-in image tool.

This is the official route available on a PC that is signed in to Codex with a
ChatGPT account: ``codex exec`` with the ``image_generation`` feature writes the
PNG under ``~/.codex/generated_images/<thread>/``. Nothing here reads or copies
credentials; the CLI uses its own login.

Every attempt leaves a small job record under ``.agent_control/image_jobs`` so
an abandoned "generating" job from a crashed or restarted backend is marked
failed instead of staying in that state forever.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs

GENERATION_TIMEOUT_SECONDS = 300
STALE_GRACE_SECONDS = 60
_IMAGE_SUFFIXES = {".png"}
_generation_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def codex_cli_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Fast check that the Codex CLI exists and is signed in."""
    path = shutil.which("codex", path=(env or os.environ).get("PATH"))
    if not path:
        return {
            "ready": False,
            "reason": "codex_cli_missing",
            "message": "The Codex CLI was not found. Install it (npm i -g @openai/codex), run `codex login`, then try again.",
        }
    try:
        done = subprocess.run(  # noqa: S603
            [path, "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **(env or {})},
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ready": False,
            "reason": "codex_status_failed",
            "message": f"Could not check the Codex sign-in ({exc}). Run `codex login status` in a terminal.",
            "path": path,
        }
    text = f"{done.stdout}\n{done.stderr}".strip()
    if done.returncode != 0 or "logged in" not in text.lower():
        return {
            "ready": False,
            "reason": "codex_auth_missing",
            "message": "Codex is not signed in on this PC. Run `codex login` in a terminal, then try again.",
            "path": path,
            "detail": text[-300:],
        }
    return {"ready": True, "path": path, "login": text.splitlines()[0] if text else ""}


def _jobs_dir(root: Path) -> Path:
    path = root / ".agent_control" / "image_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_job(root: Path, request_id: str, **fields: Any) -> dict[str, Any]:
    path = _jobs_dir(root) / f"{request_id}.json"
    record: dict[str, Any] = {}
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
    record.update(fields)
    record["requestId"] = request_id
    record["updatedAt"] = _utc_now()
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def sweep_stale_jobs(root: Path) -> list[str]:
    """Mark running jobs from earlier backend sessions (or past deadline) failed."""
    swept: list[str] = []
    for path in list(_jobs_dir(root).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("status") != "running":
            continue
        started = float(record.get("startedAtEpoch") or 0)
        expired = time.time() - started > GENERATION_TIMEOUT_SECONDS + STALE_GRACE_SECONDS
        if record.get("backendPid") == os.getpid() and _generation_lock.locked() and not expired:
            continue
        _write_job(
            root,
            path.stem,
            status="failed",
            error="This generation was interrupted (the backend restarted or it ran past its deadline).",
            finishedAt=_utc_now(),
        )
        swept.append(path.stem)
    return swept


def list_jobs(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    files = sorted(_jobs_dir(root).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:limit]:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows


def _explain_failure(stdout: str, stderr: str, returncode: int) -> str:
    messages: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") in {"error", "turn.failed"}:
            raw = event.get("message") or (event.get("error") or {}).get("message") or ""
            if raw:
                messages.append(str(raw))
    for line in stderr.splitlines():
        if " ERROR " in line and "websocket" not in line.lower():
            messages.append(line.split(" ERROR ", 1)[1].strip())
    text = " | ".join(dict.fromkeys(messages))[:400]
    return text or f"Codex exited with code {returncode} without producing an image."


def generate_image(
    *,
    root: Path,
    request_id: str,
    prompt_text: str,
    size: str,
    out_path: Path,
    env: dict[str, str] | None = None,
    timeout: int = GENERATION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Generate exactly one image. Never blocks past ``timeout``; always returns."""
    from .web_backend import _terminate_process_tree  # late import: avoid cycle

    sweep_stale_jobs(root)
    status = codex_cli_status(env)
    if not status.get("ready"):
        _write_job(root, request_id, status="failed", error=status["message"], finishedAt=_utc_now())
        return {"ok": False, "reason": status["reason"], "message": status["message"], "details": status}
    if not _generation_lock.acquire(blocking=False):
        running = next((j for j in list_jobs(root) if j.get("status") == "running"), {})
        since = str(running.get("startedAt") or "")[11:16]
        message = (
            "Another image is still generating"
            + (f" (started {since} UTC)" if since else "")
            + ". Wait for it to finish, then try again."
        )
        return {"ok": False, "reason": "generation_busy", "message": message, "details": {}}
    started = time.perf_counter()
    try:
        _write_job(
            root,
            request_id,
            status="running",
            startedAt=_utc_now(),
            startedAtEpoch=time.time(),
            backendPid=os.getpid(),
            route="codex exec (built-in image generation)",
            deadlineSeconds=timeout,
        )
        work_dir = root / ".agent_control" / "image_jobs" / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        instruction = (
            "Use your image generation tool to create exactly one image and nothing else. "
            "Do not write code, run commands or edit files. "
            f"Preferred size {size or '1024x1024'}. Image request: {prompt_text}\n"
            "When done, reply with only the saved file path."
        )
        args = [
            status["path"], "exec", "--ephemeral", "--skip-git-repo-check",
            "-s", "read-only", "-C", str(work_dir), "--json", "-",
        ]
        # The instruction goes in on stdin: codex is an npm .cmd shim on Windows and a
        # command-line argument containing newlines would be cut at the first one.
        process = subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **(env or {})},
            **hidden_windows_subprocess_kwargs(new_process_group=True),
        )
        try:
            stdout, stderr = process.communicate(input=instruction, timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            message = (
                f"Image generation took longer than {timeout} seconds and was stopped. "
                "Try again; if it keeps happening, run `codex exec hello` in a terminal to check Codex."
            )
            _write_job(root, request_id, status="failed", error=message, finishedAt=_utc_now())
            return {"ok": False, "reason": "generation_timeout", "message": message, "details": {}}
        thread_id = ""
        agent_text = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "thread.started":
                thread_id = str(event.get("thread_id") or "")
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                agent_text = str(item.get("text") or "")
        produced: Path | None = None
        if thread_id:
            folder = Path.home() / ".codex" / "generated_images" / thread_id
            if folder.is_dir():
                files = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                produced = files[0] if files else None
        if produced is None and agent_text.strip():
            candidate = Path(agent_text.strip().strip("`\"'"))
            if candidate.is_file() and candidate.suffix.lower() in _IMAGE_SUFFIXES:
                produced = candidate
        if produced is None:
            message = _explain_failure(stdout, stderr, process.returncode)
            if agent_text.strip() and process.returncode == 0:
                message = f"Codex did not create an image. It said: {agent_text.strip()[:300]}"
            _write_job(root, request_id, status="failed", error=message, finishedAt=_utc_now())
            return {"ok": False, "reason": "generation_failed", "message": message, "details": {"threadId": thread_id}}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, out_path)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _write_job(
            root, request_id, status="done", finishedAt=_utc_now(), elapsedMs=elapsed_ms,
            artifactPath=str(out_path), threadId=thread_id,
        )
        return {"ok": True, "elapsedMs": elapsed_ms, "threadId": thread_id, "source": str(produced)}
    except Exception as exc:  # noqa: BLE001 - the job must never stay "running"
        message = f"Image generation could not start: {exc}"
        _write_job(root, request_id, status="failed", error=message, finishedAt=_utc_now())
        return {"ok": False, "reason": "generation_error", "message": message, "details": {}}
    finally:
        _generation_lock.release()
