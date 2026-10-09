"""Seal bounded C9b evidence; include no runtime databases or account stores."""
from datetime import datetime, timezone
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "scripts/evidence"
RUNS = EVIDENCE / "C9b-runs"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-commit", help="Source commit whose files are sealed")
    args = parser.parse_args()
    previous = EVIDENCE / "C9b.json"
    implementation = args.implementation_commit or (read(previous)["implementationCommit"] if previous.is_file() else "HEAD")
    implementation = subprocess.check_output(["git", "rev-parse", implementation], cwd=REPO, text=True).strip()
    source_commits = read(previous).get("sourceCommits", [read(previous)["implementationCommit"]]) if previous.is_file() else []
    source_commits = list(dict.fromkeys([*source_commits, implementation]))
    receipts = {name: read(EVIDENCE / (name + ".json")) for name in
                ("C9b-deliverables", "C9b-http", "C9b-source", "C9b-r5", "C9b-r5-ungated", "C9b-dates", "C9b-r5-targeted")}
    raw = set()
    # Only named generated replay receipts and their explicitly named artifacts.
    for scope in (RUNS / "source", RUNS / "r5"):
        for path in scope.rglob("replay*.json"):
            raw.add(path)
            for name in read(path).get("files", {}):
                output = (path.parent / name).resolve()
                if not output.is_relative_to(path.parent.resolve()):
                    raise ValueError("Output escaped its owned replay")
                raw.add(output)
        raw.update(scope.glob("**/.neyvia/autopilot-model/*.json"))
    for scope in (RUNS / "calibration", RUNS / "runtime"):
        raw.update(scope.glob(".neyvia/autopilot-model/*.json"))
        for name in ("judge.json", "preference-judge.json", "suite.json"):
            path = scope / ".neyvia/lessons" / name
            if path.is_file():
                raw.add(path)
    for lesson in receipts["C9b-http"]["lessons"]:
        for suffix in (".cl", ".json"):
            raw.add(RUNS / "runtime/.neyvia/lessons" / (lesson["id"] + suffix))
    if sum(p.stat().st_size for p in raw) > 50_000_000:
        raise ValueError("Evidence exceeds its 50 MB ceiling")
    index = [{"path": p.relative_to(REPO).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(raw)]
    archive = EVIDENCE / "C9b-raw.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for p in sorted(raw):
            bundle.write(p, p.relative_to(REPO).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.infolist()) == len(index)
    committed = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", implementation], cwd=REPO, text=True).splitlines()
    prior_sources = [row["path"] for row in read(previous).get("sources", [])] if previous.is_file() else []
    source = [REPO / p for p in sorted(set(committed + prior_sources)) if p.startswith(("src/", "config/"))]
    for path in source:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fixed = read(RUNS / "calibration/.neyvia/lessons/judge.json")
    learned = read(RUNS / "calibration/.neyvia/lessons/preference-judge.json")
    r5 = receipts["C9b-r5"]["records"]
    http = receipts["C9b-http"]
    summary = {
        "schema": "neyvia.c9b-proof.v1", "at": datetime.now(timezone.utc).isoformat(),
        "status": "partial: calibration prevents promotion; learning improvement unproven",
        "branch": "track/c5-noslop", "implementationCommit": implementation,
        "sourceCommits": source_commits,
        "recovery": "No tracked uncommitted source diff was present after reboot; pre-existing proof/r6-blind was preserved.",
        "scope": {"port": 48761, "published": False, "NAS": False, "downloads": False, "runtimeBytes": sum(p.stat().st_size for p in RUNS.rglob("*") if p.is_file())},
        "gates": {"fileAndHostChecks": len(receipts["C9b-deliverables"]["checks"]), "passed": all(receipts["C9b-deliverables"]["checks"].values())},
        "feedback": {"checks": len(http["checks"]), "passed": http["passed"], "uniqueChecks": len({c["name"] for c in http["checks"]}),
                     "model": "gpt-6-luna", "drafted": len(http["lessons"]), "states": [r["state"] for r in http["lessons"]],
                     "inputBoundary": "Controlled verifier feedback on real Luna output, not a new Paul vote or microphone recording."},
        "judge": {"fixedAgreement": fixed["agreement"], "learnedLeaveOneOutAgreement": learned["agreement"], "required": learned["spec"]["minimumAgreement"],
                  "passed": learned["passed"], "preferencePairs": learned["count"], "weightsUpdated": "small local preference ranker only; provider weights unchanged"},
        "r5": {"tasks": len(r5), "validRuns": sum(r["valid"] for c in r5 for r in c["runs"].values()), "runs": len(r5) * 2,
               "failed": [{"task": c["task"], "arm": arm, "error": r.get("error")} for c in r5 for arm, r in c["runs"].items() if not r["valid"]],
               "boundary": "Full gated round predates twelve-turn/timeout repair; trial guidance was authored, not promoted. Preliminary ungated round preserved separately."},
        "targeted": [{"receipt": name + ".json", "task": receipts[name]["records"][0]["task"], "validRuns": sum(r["valid"] for c in receipts[name]["records"] for r in c["runs"].values())} for name in ("C9b-dates", "C9b-r5-targeted")],
        "unproven": ["successful measured lesson promotion and revert", "taste or model improvement", "new blind round with Paul", "browser UI journey owned by Claude", "general browser/native/network task replay"],
        "adverse": ["Initial owned backend launcher started its broad verification suite; it was stopped and replaced by isolated guarded HTTP handlers.",
                    "HTTP stale-process failures and draft-format/verifier-race failures are retained in C9b-http.json.",
                    "Automatic approval review rejected cleanup with blocked by policy; one tiny fixture and ten owned temporary dist folders remain untracked."],
        "sources": [{"path": p.relative_to(REPO).as_posix(), "sha256": sha(p)} for p in source],
        "receipts": [{"path": "scripts/evidence/" + n + ".json", "sha256": sha(EVIDENCE / (n + ".json"))} for n in receipts],
        "archive": {"path": "scripts/evidence/C9b-raw.zip", "bytes": archive.stat().st_size, "sha256": sha(archive), "entries": index},
    }
    (EVIDENCE / "C9b.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": "scripts/evidence/C9b.json", "archiveBytes": archive.stat().st_size, "rawFiles": len(index), "status": summary["status"]}))


if __name__ == "__main__":
    main()
