"""Conservative, reproducible evidence index for CL11 native transcripts.

This does not regrade outcomes or claim semantic understanding. Predicate checks
are commands containing an explicit assertion/comparison guard; a zero exit code
proves execution, not that the predicate is a sufficient task goal. Readbacks are
listed separately and never counted as passed checks. No model calls are made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICATE = re.compile(r"\bassert\b|Assert-|\bif\s*\([^\n]*(?:-eq|-ne|-notmatch|-match|==|!=|Test-Path)[^\n]*\)\s*\{?\s*(?:throw|exit)|\bif\b[^\n]*(?:==|!=)[^\n]*:\s*(?:raise|assert)", re.I)
READ = re.compile(r"Get-Content|Get-ChildItem|Test-Path|read_text|read_bytes|readFile|\bRead\b|browser_(?:snapshot|screenshot)|textContent|innerText|querySelector", re.I)
EFFECT = re.compile(r"Set-Content|Add-Content|Move-Item|Rename-Item|Remove-Item|write_text|write_bytes|writeFile|\b(?:Write|Edit)\b|browser_(?:click|fill)|\.click\(|\.fill\(", re.I)
IMPACT = re.compile(r"\b(?:impact|affected|affects|side effect|other files|other notes|only (?:the |this )?(?:fixture|target|note|file)|preserv(?:e|ing|ed) (?:all |the )?(?:other|existing))\b", re.I)
UNDO = re.compile(r"\b(?:undo|revers(?:e|ible)|recover(?:able|ability)|recycle bin|backup|restore)\b", re.I)
NO_KNOWLEDGE = re.compile(r"\b(?:no|not|cannot|can't|unavailable|unknown|couldn't)\b", re.I)


def compact(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Screenshots and opaque signatures are not searchable behavioral proof.
        return " ".join(compact(v) for k, v in value.items()
                        if k not in {"data", "signature", "thinking", "base64"})
    if isinstance(value, list):
        return " ".join(compact(v) for v in value)
    return str(value) if value is not None else ""


def review_events(path: Path):
    raw = path.read_bytes()
    actions, statements, results, malformed = [], [], {}, []
    for line_no, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            malformed.append(line_no)
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed":
            kind = item.get("type")
            if kind in {"command_execution", "mcp_tool_call", "file_change"}:
                actions.append({"line": line_no, "id": item.get("id"), "tool": item.get("tool", kind),
                                "input": compact(item.get("command") or item.get("arguments") or item.get("changes")),
                                "output": compact(item.get("aggregated_output") or item.get("result")),
                                "executionOk": item.get("exit_code") == 0 if kind == "command_execution"
                                else item.get("status") == "completed" and not item.get("error")})
            elif kind == "agent_message":
                statements.append((line_no, item.get("text", "")))
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                actions.append({"line": line_no, "id": block.get("id"), "tool": block.get("name"),
                                "input": compact(block.get("input", {})), "output": "", "executionOk": None})
            elif block.get("type") == "tool_result":
                results[block.get("tool_use_id")] = (line_no, not block.get("is_error", False), compact(block.get("content")))
            elif block.get("type") == "text" and event.get("type") == "assistant":
                statements.append((line_no, block.get("text", "")))
    effects_seen = False
    checks, readbacks, initial_reads = [], [], []
    for action in actions:
        if action["id"] in results:
            result_line, ok, output = results[action["id"]]
            action.update(resultLine=result_line, executionOk=False if not ok else None,
                          toolResultReportedError=not ok, output=output)
        text = str(action["tool"]) + " " + action["input"]
        entry = {k: v for k, v in action.items() if k not in {"output", "input"}}
        entry["inputExcerpt"] = action["input"][:900]
        entry["outputExcerpt"] = action["output"][:500]
        if PREDICATE.search(text):
            checks.append(entry)
        if READ.search(text):
            (readbacks if effects_seen or EFFECT.search(text) else initial_reads).append(entry)
        if EFFECT.search(text):
            effects_seen = True
    def knowledge(pattern):
        evidence = [{"line": n, "statement": t[:1000],
                     "classification": "explicit_negative_or_uncertain" if NO_KNOWLEDGE.search(t) else "explicit_mention"}
                    for n, t in statements if pattern.search(t)]
        return {"status": "explicit_mention_needs_semantic_review" if evidence else "evidence_missing",
                "evidence": evidence}
    return {"eventsPath": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
            "eventsSha256": hashlib.sha256(raw).hexdigest(), "malformedLines": malformed,
            "observedActions": len(actions), "explicitPredicateCommands": checks,
            "explicitPredicateCommandsExecutedWithZeroExit": sum(c["executionOk"] is True for c in checks),
            "postEffectReadbackCandidates": readbacks, "preEffectReadCandidates": initial_reads,
            "impactKnown": knowledge(IMPACT), "undoKnown": knowledge(UNDO)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=ROOT / ".agent_control/cl11/scored-1")
    parser.add_argument("--output", type=Path, default=ROOT / "scripts/evidence/CL11-native-review.json")
    parser.add_argument("--events", type=Path, action="append", default=[], help="Additional smoke transcripts; excluded from scored counts")
    args = parser.parse_args()
    args.cohort = args.cohort.resolve()
    runs = []
    for result_path in sorted(args.cohort.glob("task-*/*/*-alone/rep-*/result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        events_path = result_path.parent / "native/events.jsonl"
        review = review_events(events_path) if events_path.exists() else {"eventsMissing": True}
        review.update(task=int(result_path.parts[-5].split("-")[-1]), harness=result_path.parts[-3],
                      repetition=int(result_path.parts[-2].split("-")[-1]),
                      resultPath=result_path.relative_to(ROOT).as_posix(),
                      resultSha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                      independentSuccess=result.get("success"), valid=result.get("valid"))
        runs.append(review)
    aggregates = []
    for key in sorted({(r["task"], r["harness"]) for r in runs}):
        subset = [r for r in runs if (r["task"], r["harness"]) == key]
        aggregates.append({"task": key[0], "harness": key[1], "runsAvailable": len(subset),
                           "explicitPredicateAttempts": sum(len(r.get("explicitPredicateCommands", [])) for r in subset),
                           "predicateCommandsWithZeroExit": sum(r.get("explicitPredicateCommandsExecutedWithZeroExit", 0) for r in subset),
                           "postEffectReadbackCandidates": sum(len(r.get("postEffectReadbackCandidates", [])) for r in subset),
                           "impactMentionsRequiringReview": sum(bool(r.get("impactKnown", {}).get("evidence")) for r in subset),
                           "undoMentionsRequiringReview": sum(bool(r.get("undoKnown", {}).get("evidence")) for r in subset)})
    report = {"metricBoundary": "Deterministic transcript evidence index, not semantic grading. Zero-exit explicit predicate commands are executed checks, never certified goal checks. Claude tool-result completion without a reported error has no separately attested exit code and is not a zero-exit predicate. Post-effect readbacks are candidates, not assertions. Explicit impact/undo mentions require semantic review; absence means evidence missing, not unavailable. Native provider receipts and independent outcome success do not establish agent knowledge.",
              "expectedNativeRuns": 60, "completedNativeResultFiles": len(runs), "missingNativeResultFiles": max(0, 60-len(runs)),
              "byHarness": dict(Counter(r["harness"] for r in runs)), "perTaskHarness": aggregates, "runs": runs,
              "smokeTranscripts": [review_events(p.resolve()) for p in args.events]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "completed": len(runs), "missing": report["missingNativeResultFiles"], "smokeTranscripts": len(args.events)}))


if __name__ == "__main__":
    main()
