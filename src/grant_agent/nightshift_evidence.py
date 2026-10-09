"""Task-bound completion checks. Transport completion is never work evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from .neyvia_workspace_tools import workspace_for
from .subprocess_utils import hidden_windows_subprocess_kwargs


def evidence_path(service, task, evidence):
    path = Path(evidence.get("path") or "")
    path = path if path.is_absolute() else Path(task["folder"]) / path
    path = workspace_for(service.root).safe_path(path)
    path.relative_to(Path(task["folder"]).resolve())
    return path


def git(task, *args):
    try:
        result = subprocess.run(["git", *args], cwd=task["folder"], capture_output=True, text=True,
                                timeout=15, **hidden_windows_subprocess_kwargs())
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Git completion observer timed out") from exc
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Git evidence is unavailable")
    return result.stdout.strip()


def baseline(service, task):
    expected = task.get("completionEvidence") or {}
    if expected.get("type") in {"file", "receipt"}:
        path = evidence_path(service, task, expected)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    if expected.get("type") == "commit":
        try:
            return {"head": git(task, "rev-parse", "HEAD")}
        except ValueError:
            return {"head": None}
    return {}


def verify_condition(service, condition):
    from .cl.goals import evaluate_goal
    from .native_tools import NativeToolRegistry
    registry = NativeToolRegistry(service.root)

    def exact(name):
        return name if name.startswith("neyvia.") else "neyvia." + name

    def readonly(name):
        try:
            return registry.describe(exact(name)).get("mutability_class") == "read"
        except KeyError:
            return False

    def observe(name, positional, args):
        if positional:
            raise ValueError("Completion observers require named arguments")
        receipt = registry.call(exact(name), args)
        if not receipt.get("ok"):
            raise ValueError(receipt.get("error") or "Completion observer failed")
        return receipt.get("result")

    checked = evaluate_goal(condition, observe, readonly)
    if not checked["observed"] or not checked["passed"]:
        errors = "; ".join(row["error"] for row in checked["observerErrors"])
        raise ValueError("The task's read-only completion verifier did not accept the result" + (": " + errors if errors else ""))
    return {"condition": condition, "observations": checked["observations"]}


def attempt_items(service, task):
    run = service.broker.get_run(task["runId"])
    page = service.broker.read(run["sessionId"], limit=200)
    return run, [item for item in page.get("items", [])
                 if (item.get("at") or "") >= (run.get("startedAt") or "")]


def receipt_call(data, receipt):
    if data.get("status") != "ok":
        return False
    name = data.get("tool") if data.get("server") == "neyvia" else str(data.get("name") or "").removeprefix("mcp__neyvia__")
    args = data.get("args") or data.get("input") or {}
    try:
        args = json.loads(args) if isinstance(args, str) else args
    except ValueError:
        return False
    if not isinstance(args, dict):
        return False
    if name == "tools_call":
        name, args = str(args.get("tool") or "").removeprefix("neyvia.").replace(".", "_"), args.get("arguments") or {}
    alias = receipt["tool"].removeprefix("neyvia.").replace(".", "_")
    return name == alias and isinstance(args, dict) and all(
        (receipt.get("arguments") or {}).get(key) == value for key, value in args.items())


def tool_receipt(service, task, expected, content):
    """Check the saved native receipt and its real call, not agent-authored JSON."""
    from .native_tools import TOOL_RECEIPT_SCHEMA
    receipt = json.loads(content)
    if not isinstance(receipt, dict) or receipt.get("schema") != TOOL_RECEIPT_SCHEMA or receipt.get("ok") is not True:
        raise ValueError("Supply a successful saved native tool receipt")
    declared = expected.get("expect") or {}
    if not declared.get("tool") or any(receipt.get(key) != value for key, value in declared.items()):
        raise ValueError("Tool receipt does not match the task's declared tool and result fields")
    saved = Path(receipt.get("receipt_path") or "").resolve()
    saved.relative_to((service.root / ".agent_control" / "tool_receipts").resolve())
    if not saved.is_file() or json.loads(saved.read_text(encoding="utf-8")) != receipt:
        raise ValueError("Tool receipt is not the workspace's saved tool result")
    payload = {key: value for key, value in receipt.items() if key != "receiptHash"}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if receipt.get("receiptHash") != digest:
        raise ValueError("Tool receipt hash is invalid")
    if task.get("runId"):
        run, items = attempt_items(service, task)
        if receipt.get("runId") and receipt["runId"] != run["runId"]:
            raise ValueError("Tool receipt belongs to another run")
        timestamp = lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if not timestamp(run["startedAt"]) <= timestamp(receipt.get("created_at")) <= timestamp(run["updatedAt"]):
            raise ValueError("Tool receipt was not produced during this attempt")
        if not any(item.get("kind") == "tool" and receipt_call(item.get("data") or {}, receipt) for item in items):
            raise ValueError("This attempt has no successful call for the receipt's tool")


def check(service, task, evidence):
    if not isinstance(evidence, dict):
        raise ValueError("Supply task-matching file change, commit, tool receipt or verified result evidence")
    kind = evidence.get("type")
    expected = task.get("completionEvidence") or {}
    before = task.get("evidenceBefore") or {}
    if kind == "run":
        # Preserve the public run evidence envelope, but require its actual output witness.
        run = service.broker.get_run(str(evidence.get("runId") or ""))
        if run.get("state") != "completed" or task.get("runId") != run["runId"]:
            raise ValueError("The task's harness run has not completed")
        witness = evidence.get("evidence")
        if not witness or witness.get("type") == "run":
            raise ValueError("Run completed without task-matching completion evidence; inspect the agent's result")
        return {"type": "run", "runId": run["runId"], "sessionId": run.get("sessionId"),
                "state": "completed", "evidence": check(service, task, witness), "verified": True}
    if expected and expected.get("type") != kind:
        raise ValueError("Evidence type differs from the task's declared completion contract")
    if kind in {"file", "receipt"}:
        path = evidence_path(service, task, evidence)
        if expected and path != evidence_path(service, task, expected):
            raise ValueError("Evidence path differs from the task's declared output")
        if not path.is_file():
            raise ValueError("Evidence file does not exist")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if task.get("runId") and (before.get("path") != str(path) or before.get("sha256") == digest):
            raise ValueError("The declared output was not changed by this task's attempt")
        if expected.get("sha256") and expected["sha256"] != digest:
            raise ValueError("Output hash does not match the task contract")
        if expected.get("contains") and expected["contains"] not in content.decode("utf-8", "replace"):
            raise ValueError("Output content does not match the task contract")
        if kind == "receipt":
            tool_receipt(service, task, expected, content)
        result = {"type": kind, "path": str(path), "sha256": digest, "verified": True}
    elif kind == "commit":
        commit = str(evidence.get("hash") or git(task, "rev-parse", "HEAD"))
        import re
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            raise ValueError("Use a Git commit hash")
        commit = git(task, "rev-parse", "--verify", commit + "^{commit}")
        head = before.get("head")
        if task.get("runId"):
            if not head or head == commit:
                raise ValueError("This attempt did not produce a new commit")
            git(task, "merge-base", "--is-ancestor", head, commit)
        changed = git(task, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        if not changed or not expected.get("paths") or not set(expected["paths"]) <= set(changed):
            raise ValueError("Commit does not change the task's declared paths")
        result = {"type": kind, "hash": commit, "files": changed, "verified": True}
    elif kind in {"result", "command"}:
        condition = expected.get("condition")
        if not condition or evidence.get("condition", condition) != condition:
            raise ValueError("A stated result requires the task's declared read-only completion verifier")
        text = str(evidence.get("text") or evidence.get("output") or "").strip()
        if task.get("runId"):
            _, items = attempt_items(service, task)
            text = "\n".join(str((item.get("data") or {}).get("text") or "") for item in items if item.get("kind") == "assistant")
        if not text.strip():
            raise ValueError("The agent did not state a result for the verifier to accept")
        if kind == "command" and (evidence.get("exitCode") != 0 or not evidence.get("command")):
            raise ValueError("Command evidence needs command, exitCode=0 and output")
        if expected.get("contains") and expected["contains"] not in text:
            raise ValueError("Stated result does not match the task contract")
        result = {"type": kind, "text": text[:12000], "verified": True, **verify_condition(service, condition)}
        if kind == "command":
            result.update(command=evidence["command"], exitCode=0, output=evidence.get("output", text))
    else:
        raise ValueError("Supply task-matching file change, commit, tool receipt or verified result evidence")
    if kind not in {"result", "command"} and expected.get("condition"):
        result.update(verify_condition(service, expected["condition"]))
    return result
