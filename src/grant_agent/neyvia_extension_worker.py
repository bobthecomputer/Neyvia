from __future__ import annotations
from contextlib import ExitStack

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .crashproof import CrashProofStore
from .durability import atomic_write_json
from .research import search_workspace
from .subprocess_utils import hidden_windows_subprocess_kwargs, install_hidden_subprocess_default


def run_extension_task(root: str | Path, task_id: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    store = CrashProofStore(root_path)
    task = store.get_task(task_id)
    if task["status"] == "completed":
        return task["result"] or {"status": "completed", "deduplicated": True}
    if task["status"] in {"failed", "cancelled"}:
        raise RuntimeError(f"task is already {task['status']}")
    if task["status"] != "working":
        task = store.transition_task(task_id, "working", event_payload={"worker": "neyvia-extension"})
    try:
        if task["kind"] == "extension.research":
            result = _run_research(root_path, store, task)
        elif task["kind"] == "extension.browser":
            result = _run_browser(root_path, store, task)
        elif task["kind"] == "extension.computer-use":
            result = _run_computer_use(root_path, store, task)
        elif task["kind"] == "model.train":
            result = _run_model_training(root_path, store, task)
        else:
            raise ValueError(f"unsupported extension task kind: {task['kind']}")
        if result.get("status") == "input_required":
            store.transition_task(task_id, "input_required", checkpoint=result)
            return result
        store.transition_task(task_id, "completed", result=result)
        return result
    except Exception as exc:
        store.transition_task(
            task_id,
            "failed",
            error={"type": type(exc).__name__, "message": str(exc)[:1000]},
        )
        raise


def _task_artifact_dir(root: Path, task_id: str) -> Path:
    path = root / ".agent_control" / "neyvia_tasks" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_research(root: Path, store: CrashProofStore, task: dict[str, Any]) -> dict[str, Any]:
    payload = task["payload"]
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("research query is required")
    result_set = store.create_result_set(
        mission_id=task["missionId"],
        kind="research.evidence",
        metadata={"taskId": task["taskId"], "query": query},
    )
    result_set_id = result_set["resultSetId"]
    workspace_root = Path(payload.get("workspaceRoot") or root).resolve()
    workspace_matches = search_workspace(
        workspace_root,
        query if payload.get("regex") else re.escape(query),
        include_glob=str(payload.get("includeGlob") or "**/*"),
        max_results=max(1, min(int(payload.get("maxResults", 50)), 500)),
    )
    if not payload.get("includeAgentControl", False):
        workspace_matches = [
            match
            for match in workspace_matches
            if not str(match.get("path") or "").replace("\\", "/").startswith(".agent_control/")
        ]
    for match in workspace_matches:
        store.add_result_item(
            result_set_id,
            source=f"workspace:{match['path']}:{match['line']}",
            payload=match,
        )
    sources = [str(item) for item in payload.get("sources", []) if str(item).startswith(("http://", "https://"))]
    completed_sources: list[str] = []
    for index, source in enumerate(sources):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "N-E-Y-V-I-A-research/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                body = response.read(2_000_000)
                content_type = str(response.headers.get("Content-Type") or "")
            text = body.decode("utf-8", errors="replace")
            store.add_result_item(
                result_set_id,
                source=source,
                payload={
                    "url": source,
                    "contentType": content_type,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "excerpt": " ".join(text.split())[:4000],
                },
            )
            completed_sources.append(source)
        except Exception as exc:
            store.add_result_item(
                result_set_id,
                source=source,
                status="failed",
                payload={"url": source, "error": str(exc)[:500]},
            )
        store.transition_task(
            task["taskId"],
            "working",
            checkpoint={"resultSetId": result_set_id, "sourceIndex": index + 1, "completedSources": completed_sources},
            event_payload={"sourceIndex": index + 1},
        )
    return {
        "resultSetId": result_set_id,
        "summary": store.summarize_result_set(result_set_id, sample_limit=5),
        "workspaceRoot": str(workspace_root),
    }


def _run_browser(root: Path, store: CrashProofStore, task: dict[str, Any]) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for N-E-Y-V-I-A browser tasks") from exc

    payload = task["payload"]
    artifacts = _task_artifact_dir(root, task["taskId"])
    state_path = artifacts / "browser-state.json"
    checkpoint = task.get("checkpoint") or {}
    start_index = int(checkpoint.get("actionIndex", 0))
    actions = list(payload.get("actions") or [])
    start_url = str(payload.get("startUrl") or "").strip()
    if not actions and start_url:
        actions = [
            {"id": "navigate", "type": "navigate", "url": start_url},
            {"id": "inspect", "type": "read", "selector": "body", "maxCharacters": 4000},
            {"id": "proof", "type": "screenshot", "name": "proof.png"},
        ]
    if not actions:
        raise ValueError("browser task requires startUrl or deterministic actions")
    from .local_browser_authority import approved_browser_url
    def ensure_local_control(url: str) -> None:
        approved_browser_url(root, url, legacy_ports={4173,47908})
    if not start_url:
        start_url = next((str(action.get("url") or "") for action in actions if isinstance(action,dict) and action.get("type") == "navigate"), "")
    ensure_local_control(start_url)
    resume_url = str(checkpoint.get("url") or "").strip()
    if start_index > 0 and resume_url and resume_url != "about:blank":
        ensure_local_control(resume_url)
    if any(
        str(action.get("type") or "").lower() in {"click", "fill", "press"}
        for action in actions
        if isinstance(action, dict)
    ):
        lease_id = str(task.get("permissionLeaseId") or "").strip()
        if not lease_id:
            return {
                "status": "input_required",
                "reason": "autonomy_lease_required",
                "message": "Interactive browser work needs one scoped autonomy lease; N-E-Y-V-I-A will not ask again while that lease remains valid.",
            }
        permission_url = start_url or next(
            (str(action.get("url") or "") for action in actions if isinstance(action, dict) and action.get("type") == "navigate"),
            "",
        )
        domain = urllib.parse.urlparse(permission_url).hostname or ""
        decision = store.autonomy_allows(
            lease_id,
            action="extension.browser.interact",
            context={"path": str(root), "domain": domain, "destructive": False},
        )
        if not decision["allowed"]:
            return {
                "status": "input_required",
                "reason": decision["reason"],
                "message": "The current autonomy lease does not cover this browser interaction.",
            }
    outputs = list(checkpoint.get("outputs") or [])
    screenshots: list[str] = list(checkpoint.get("screenshots") or [])
    with sync_playwright() as playwright, ExitStack() as resources:
        from .browser_obscura import connect_owned_playwright
        browser, owned_browser = connect_owned_playwright(playwright, artifacts / 'obscura', port=payload.get('obscuraPort'), local_control=True)
        resources.callback(owned_browser.close)
        context_args: dict[str, Any] = {}
        if state_path.exists():
            context_args["storage_state"] = str(state_path)
        context = browser.new_context(**context_args)
        page = context.new_page()
        from .local_browser_authority import guard_browser_page
        guard_browser_page(root,page,start_url,legacy_ports={4173,47908})
        if start_index > 0 and resume_url and resume_url != "about:blank":
            page.goto(resume_url, wait_until="domcontentloaded", timeout=30000)
            ensure_local_control(page.url)
        for index in range(start_index, len(actions)):
            action = actions[index] if isinstance(actions[index], dict) else {}
            action_type = str(action.get("type") or "").lower()
            if action_type == "navigate":
                target_url = str(action.get("url") or start_url)
                ensure_local_control(target_url)
                page.goto(target_url, wait_until="domcontentloaded", timeout=int(action.get("timeoutMs", 30000)))
                ensure_local_control(page.url)
            elif action_type == "click":
                page.locator(str(action.get("selector") or "")).click(timeout=int(action.get("timeoutMs", 30000)))
            elif action_type == "fill":
                page.locator(str(action.get("selector") or "")).fill(str(action.get("value") or ""), timeout=int(action.get("timeoutMs", 30000)))
            elif action_type == "press":
                page.locator(str(action.get("selector") or "body")).press(str(action.get("key") or "Enter"))
            elif action_type == "wait":
                if action.get("selector"):
                    page.locator(str(action["selector"])).wait_for(timeout=int(action.get("timeoutMs", 30000)))
                else:
                    page.wait_for_timeout(int(action.get("milliseconds", 1000)))
            elif action_type == "read":
                text = page.locator(str(action.get("selector") or "body")).inner_text(timeout=int(action.get("timeoutMs", 30000)))
                outputs.append({"actionId": action.get("id") or str(index), "text": text[: int(action.get("maxCharacters", 4000))]})
            elif action_type == "screenshot":
                name = Path(str(action.get("name") or f"step-{index:03d}.png")).name
                screenshot_path = artifacts / name
                page.screenshot(path=str(screenshot_path), full_page=bool(action.get("fullPage", True)))
                screenshots.append(str(screenshot_path))
            else:
                raise ValueError(f"unsupported browser action: {action_type}")
            ensure_local_control(page.url)
            context.storage_state(path=str(state_path))
            store.transition_task(
                task["taskId"],
                "working",
                checkpoint={
                    "actionIndex": index + 1,
                    "lastActionId": action.get("id") or str(index),
                    "url": page.url,
                    "title": page.title(),
                    "outputs": outputs[-20:],
                    "screenshots": screenshots[-20:],
                    "statePath": str(state_path),
                },
                event_payload={"actionIndex": index + 1, "actionType": action_type},
            )
        result = {
            "url": page.url,
            "title": page.title(),
            "outputs": outputs,
            "screenshots": screenshots,
            "statePath": str(state_path),
            "actionCount": len(actions),
        }
        context.close()
        owned_browser.close()
    return result


def _run_computer_use(root: Path, store: CrashProofStore, task: dict[str, Any]) -> dict[str, Any]:
    if os.name != "nt" or str(os.environ.get("NEYVIA_ISOLATED_DESKTOP") or "").lower() not in {"1", "true", "yes"}:
        return {
            "status": "input_required",
            "reason": "isolated_desktop_required",
            "message": "Computer-use is queued until an isolated Windows desktop worker is available; the active user desktop will not be interrupted.",
        }
    lease_id = str(task.get("permissionLeaseId") or "").strip()
    if not lease_id:
        return {
            "status": "input_required",
            "reason": "autonomy_lease_required",
            "message": "Isolated computer use needs one scoped autonomy lease; N-E-Y-V-I-A will not ask again while it remains valid.",
        }
    decision = store.autonomy_allows(
        lease_id,
        action="extension.computer.interact",
        context={"path": str(root), "destructive": False},
    )
    if not decision["allowed"]:
        return {
            "status": "input_required",
            "reason": decision["reason"],
            "message": "The current autonomy lease does not cover this isolated computer-use task.",
        }
    import ctypes
    from PIL import ImageGrab

    payload = task["payload"]
    actions = list(payload.get("actions") or [])
    checkpoint = task.get("checkpoint") or {}
    start_index = int(checkpoint.get("actionIndex", 0))
    artifacts = _task_artifact_dir(root, task["taskId"])
    screenshots: list[str] = list(checkpoint.get("screenshots") or [])
    user32 = ctypes.windll.user32
    for index in range(start_index, len(actions)):
        action = actions[index] if isinstance(actions[index], dict) else {}
        action_type = str(action.get("type") or "").lower()
        if action_type == "click":
            user32.SetCursorPos(int(action.get("x", 0)), int(action.get("y", 0)))
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        elif action_type == "key":
            virtual_key = int(action.get("virtualKey", 13))
            user32.keybd_event(virtual_key, 0, 0, 0)
            user32.keybd_event(virtual_key, 0, 0x0002, 0)
        elif action_type == "wait":
            time.sleep(max(0, min(float(action.get("seconds", 1)), 60)))
        elif action_type == "screenshot":
            screenshot = artifacts / Path(str(action.get("name") or f"desktop-{index:03d}.png")).name
            ImageGrab.grab(all_screens=True).save(screenshot)
            screenshots.append(str(screenshot))
        else:
            raise ValueError(f"unsupported isolated computer-use action: {action_type}")
        store.transition_task(
            task["taskId"],
            "working",
            checkpoint={"actionIndex": index + 1, "screenshots": screenshots[-20:]},
            event_payload={"actionIndex": index + 1, "actionType": action_type},
        )
    return {"status": "completed", "actionCount": len(actions), "screenshots": screenshots}


def _run_model_training(root: Path, store: CrashProofStore, task: dict[str, Any]) -> dict[str, Any]:
    payload = task["payload"]
    training = payload.get("training") if isinstance(payload.get("training"), dict) else {}
    command = training.get("command")
    artifacts = _task_artifact_dir(root, task["taskId"])
    if command:
        args = [str(item) for item in command] if isinstance(command, list) else [str(command)]
        completed = subprocess.run(
            args,
            cwd=str(Path(training.get("cwd") or root).resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(training.get("timeoutSeconds", 3600))),
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        if completed.returncode != 0:
            raise RuntimeError(f"training command failed ({completed.returncode}): {completed.stderr[-1000:]}")
        return {"returnCode": 0, "stdout": completed.stdout[-4000:], "artifactDirectory": str(artifacts)}

    if str(training.get("kind") or "torch.linear.proof") != "torch.linear.proof":
        raise ValueError("training.kind requires a command adapter or torch.linear.proof")
    import torch

    seed = 1000 + int(payload.get("modelIndex", 0))
    torch.manual_seed(seed)
    device = torch.device("cuda" if torch.cuda.is_available() and training.get("device", "auto") != "cpu" else "cpu")
    x = torch.linspace(-1, 1, int(training.get("samples", 128)), device=device).unsqueeze(1)
    y = 2.5 * x - 0.75
    model = torch.nn.Linear(1, 1).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=float(training.get("learningRate", 0.1)))
    epochs = max(1, min(int(training.get("epochs", 80)), 2000))
    losses: list[float] = []
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.mse_loss(model(x), y)
        loss.backward()
        optimizer.step()
        if epoch in {0, epochs - 1}:
            losses.append(float(loss.detach().cpu()))
    model_path = artifacts / "model.pt"
    temporary = artifacts / ".model.pt.tmp"
    torch.save(model.state_dict(), temporary)
    os.replace(temporary, model_path)
    metrics = {
        "schema": "neyvia.model-training-proof.v1",
        "taskId": task["taskId"],
        "modelIndex": int(payload.get("modelIndex", 0)),
        "seed": seed,
        "device": str(device),
        "epochs": epochs,
        "initialLoss": losses[0],
        "finalLoss": losses[-1],
        "improved": losses[-1] < losses[0],
        "modelPath": str(model_path),
    }
    atomic_write_json(artifacts / "metrics.json", metrics)
    if not metrics["improved"]:
        raise RuntimeError("model proof did not improve its training loss")
    return metrics


def main(argv: list[str] | None = None) -> int:
    install_hidden_subprocess_default()
    parser = argparse.ArgumentParser(description="Run one durable N-E-Y-V-I-A extension task.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    result = run_extension_task(args.root, args.task_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
