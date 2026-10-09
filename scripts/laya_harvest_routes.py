"""Harvest bounded manual-first and C4 route evidence into the Laya review set.

The heldout manual-real-cases file is deliberately not opened by this script.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path


REPO = Path(r"C:\Users\user\Projects\nx-int-final")
DOCS_EVIDENCE = REPO / "docs" / "evidence"
SCRIPTS_EVIDENCE = REPO / "scripts" / "evidence"
TASKS_PATH = Path(r"C:\Users\user\Projects\nx-r4-blind\proof\r4-blind-20261004\tasks.json")
OUTPUT = Path(r"D:\NeyviaRuns\laya-train\review\wave2\routing-logs.json")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rel(path: Path) -> str:
    return str(path)


def read_jsonl_calls(path: Path) -> list[dict]:
    calls: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = row.get("item", {})
        if item.get("type") == "mcp_tool_call":
            tool = item.get("tool")
            args = item.get("arguments", {})
            if tool not in {"neyvia.manual.run", "neyvia.native.call"}:
                continue
            result = item.get("result") or {}
            text = " ".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
            call = {"tool": tool, "arguments": args, "resultExcerpt": text[:420]}
        else:
            msg = row.get("message", {})
            if row.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            for content in msg.get("content", []):
                if content.get("type") != "tool_use":
                    continue
                name = content.get("name", "")
                if not re.search(r"manual_run|native_call$", name):
                    continue
                call = {"tool": name.split("__")[-1], "arguments": content.get("input", {})}
                # Claude's paired tool-result event is separately retained by the source log.
                call["resultExcerpt"] = "result recorded in paired user tool-result event"
                calls.append(call)
                continue
            else:
                continue
        key = (call["tool"], json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            calls.append(call)
    return calls


def manual_first_records() -> list[dict]:
    # These are exact task clauses from the recorded manual-first prompt.
    specs = [
        {
            "key": "read-confirm",
            "input": "1 Load workspace/files and run manual.run(id='workspace',chapter='files',procedure='read-and-confirm',inputs={'path':'receipt-input.txt','phrase':'cobalt orchard'}), report phrase/hash and verifier result.",
            "manual": "workspace",
            "actions": ["workspace.read"],
            "procedure": "read-and-confirm",
            "match": lambda c: c["tool"] in {"neyvia.manual.run", "manual_run"}
            and c["arguments"].get("id") == "workspace"
            and c["arguments"].get("procedure") == "read-and-confirm"
            or c["tool"] in {"neyvia.native.call", "native_call"}
            and c["arguments"].get("toolId") == "workspace.read",
        },
        {
            "key": "workspace-search",
            "input": "2 Search the workspace for 'cobalt orchard' via workspace.search and report matched path.",
            "manual": "workspace",
            "actions": ["workspace.search"],
            "procedure": "find-source",
            "match": lambda c: c["tool"] in {"neyvia.native.call", "native_call"}
            and c["arguments"].get("toolId") == "workspace.search",
        },
        {
            "key": "clock",
            "input": "3 Load neyvia-reference/time and run its clock procedure; report actual UTC/local time and verifier.",
            "manual": "neyvia-reference",
            "actions": ["time.now"],
            "procedure": "clock",
            "match": lambda c: c["tool"] in {"neyvia.manual.run", "manual_run"}
            and c["arguments"].get("id") == "neyvia-reference"
            and c["arguments"].get("procedure") == "clock"
            or c["tool"] in {"neyvia.native.call", "native_call"}
            and c["arguments"].get("toolId") == "neyvia.time.now",
        },
    ]
    log_paths = [
        DOCS_EVIDENCE / "manual_first_codex_agent.jsonl",
        DOCS_EVIDENCE / "manual_first_codex_initial_blocked.jsonl",
        DOCS_EVIDENCE / "manual_first_codex_metadata_confusion.jsonl",
        DOCS_EVIDENCE / "manual_first_claude_agent.jsonl",
        DOCS_EVIDENCE / "manual_first_claude_initial_blocked.jsonl",
        DOCS_EVIDENCE / "manual_first_claude_verifier_failure.jsonl",
    ]
    logs = []
    for path in log_paths:
        if path.is_file():
            logs.append((path, read_jsonl_calls(path)))
    records = []
    prompt_source = REPO / "scripts" / "run_manual_first_agents.py"
    for spec in specs:
        observations = []
        sources = []
        for path, calls in logs:
            matched = [c for c in calls if spec["match"](c)]
            if not matched:
                continue
            sources.append({"path": rel(path), "sha256": sha256(path.read_bytes()), "matchedCalls": len(matched)})
            for call in matched:
                observations.append({"source": rel(path), **call})
        records.append({
            "input": spec["input"],
            "label": spec["manual"],
            "expectedActions": spec["actions"],
            "family": f"manual-first/{spec['key']}",
            "source": {
                "kind": "manual-first task clause; Codex and Claude transcripts plus blocked/retry variants",
                "promptDefinition": rel(prompt_source),
                "logs": sources,
                "replicaPolicy": "All harness/retry logs for the same subtask share this family.",
            },
            "evidence": [
                {"kind": "manual", "path": rel(REPO / "manuals" / f"{spec['manual']}.manual.json"),
                 "chapter": "files" if spec["manual"] == "workspace" else "time",
                 "procedure": spec["procedure"], "actions": spec["actions"]},
                {"kind": "observed-model-calls", "calls": observations},
            ],
            "prediction": {
                "manual": None,
                "status": "manual-level prediction not emitted; actual tool calls are recorded separately",
            },
        })
    return records


def c4_variants(task_id: str) -> list[dict]:
    archives = [
        SCRIPTS_EVIDENCE / "C4c" / "runs.zip",
        SCRIPTS_EVIDENCE / "C4b" / "c4b-typed-panel.zip",
    ]
    variants = []
    for archive in archives:
        if not archive.is_file():
            continue
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not name.endswith("/history/task.json") or f"/{task_id}/" not in name:
                    continue
                raw = bundle.read(name)
                try:
                    task_doc = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                task_text = task_doc.get("task", "") if isinstance(task_doc, dict) else ""
                variants.append({
                    "archive": rel(archive),
                    "path": name,
                    "taskSha256": sha256(raw),
                    "promptSha256": sha256(task_text.encode("utf-8")),
                    "variant": name.split("/")[1:-2],
                })
    return variants


def c4_observations(task_id: str) -> list[dict]:
    archive = SCRIPTS_EVIDENCE / "C4b" / "c4b-typed-panel.zip"
    observations = []
    if not archive.is_file():
        return observations
    action_re = re.compile(r"(?m)^(?:run\s+)?([a-z][a-z0-9_.-]+)\(")
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not name.endswith("/result.json") or f"/{task_id}/" not in name:
                continue
            parts = name.split("/")
            if len(parts) < 4 or parts[0] != "c4b-typed-panel" or parts[1] not in {"control", "efficient"}:
                continue
            try:
                result = json.loads(bundle.read(name))
            except json.JSONDecodeError:
                continue
            run = result.get("run", {})
            seen = []
            for action in run.get("actions", []):
                seen.extend(action_re.findall(action.get("proposal", "")))
            observations.append({
                "path": f"{rel(archive)}::{name}",
                "arm": parts[1],
                "runPassed": run.get("passed"),
                "qualityPassed": result.get("quality", {}).get("passed"),
                "proposedActionSequence": list(dict.fromkeys(seen)),
                "actionCount": len(run.get("actions", [])),
            })
    return observations


def c4_records() -> tuple[list[dict], list[dict]]:
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    by_id = {row["id"]: row["task"] for row in tasks}
    accepted = []
    for task_id, manual, actions, procedure, basis in [
        ("t3-notes", "notes", ["notes.write", "notes.pin", "notes.read", "notes.list"], "write-and-pin",
         "Task explicitly names the Notes app, asks for note create/pin/append/readback, and the fixture run is the Notes owner."),
        ("t5-cua", "computer-use", ["cua.inspect", "cua.action"], "set-field-and-verify",
         "Task explicitly names the open Character Map window and the exact input field/action; the fixture is a native UI task."),
    ]:
        observations = c4_observations(task_id)
        variants = c4_variants(task_id)
        accepted.append({
            "input": by_id[task_id],
            "label": manual,
            "expectedActions": actions,
            "family": f"C4/{task_id}",
            "source": {
                "kind": "C4 task prompt and retained task/run replicas",
                "taskDefinition": rel(TASKS_PATH),
                "taskId": task_id,
                "variants": variants,
                "runReplicas": [{"path": row["path"], "arm": row["arm"]} for row in observations],
                "replicaPolicy": "All arms, prompt amendments and repeated runs with this task ID share one family.",
            },
            "evidence": [
                {"kind": "manual", "path": rel(REPO / "manuals" / f"{manual}.manual.json"),
                 "chapter": "notes" if manual == "notes" else "cua", "procedure": procedure,
                 "actions": actions, "basis": basis},
                {"kind": "C4-run-observations", "runs": observations},
            ],
            "prediction": {
                "manual": None,
                "status": "C4 records tool proposals, not a manual-ID prediction; see observedActions.",
            },
            "observedActions": [
                {"family": f"C4/{task_id}", "run": run}
                for run in observations
            ],
        })
    rejected_specs = [
        ("t1-ui", "design", "UI output is requested, but the C4 fixture only verifies a standalone HTML artifact; it does not bind the task to Neyvia's rendered design workflow."),
        ("t2-bugfix", "workspace/terminal/efficiency", "The task combines source editing, tests and command execution; available traces do not establish one documented workflow-manual owner."),
        ("t4-browse", "research", "A page extraction is explicit, but the current research manual is an experimental workflow and no fixture-owner binding selects it for this generic browse task."),
        ("t6-study", "creativity/workspace", "The educational transformation and file output do not identify one documented workflow manual owner."),
        ("t7-explain", "workspace/creativity", "Generic explanatory writing has no independently bound manual owner."),
        ("t8-plan", "mission-plan/workspace", "The plan-writing request has no explicit plan-builder fixture or verified workflow-manual binding."),
    ]
    rejected = [{"taskId": tid, "candidateManuals": guesses, "reason": reason,
                 "source": rel(TASKS_PATH)} for tid, guesses, reason in rejected_specs]
    return accepted, rejected


def main() -> None:
    records = manual_first_records()
    c4, rejected = c4_records()
    records.extend(c4)
    output = {
        "schema": "laya.routing-manual-evidence.v1",
        "labelSemantics": "label is the verified expected manual; prediction is kept separate and is null when runs do not emit a manual-level prediction.",
        "heldoutPolicy": "manual-real-cases.json was not opened or used.",
        "records": records,
        "inventory": {
            "acceptedRecords": len(records),
            "manualFirstRecords": 3,
            "c4Records": len(c4),
            "families": len({row["family"] for row in records}),
            "rejectedAmbiguousRows": rejected,
            "notes": [
                "Manual-first retries and Codex/Claude variants are grouped by task family.",
                "C4 arm, amendment and replica paths are listed under one task family.",
                "A successful tool trace is execution evidence, not by itself a manual label.",
            ],
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "records": len(records), "families": output["inventory"]["families"],
                      "rejected": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
