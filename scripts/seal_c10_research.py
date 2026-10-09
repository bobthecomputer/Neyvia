"""Bind completed C10 pairs, preserve small public proof archives, append a result."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.transition_memory import atomic_json
from efficiency_log import validate, ledger_lock
from score_c10_research import summary, digest


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    if not args.run.replace("-", "").replace("_", "").isalnum():
        parser.error("Simple run name required")
    directory = REPO / "scripts/evidence/C10-runs" / args.run
    panel = read(REPO / "scripts/evidence/C10-tasks.json")
    report = summary(panel, directory)
    if not report["complete"]:
        raise ValueError("All 50 questions and five briefs need observed paired requests and valid frozen judgments")
    rows = []
    files = set()
    for task in [*panel["questions"], *panel["open_briefs"]]:
        score_path = directory / "scores" / (task["id"] + ".json")
        score = read(score_path)
        arms = {arm: read(directory / arm / (task["id"] + ".json")) for arm in ("neyvia", "openai")}
        binding = digest({"receipts": arms, "panel": panel["panel_sha256"], "rubric": panel["rubric_sha256"], "judge": "gpt-6.1-sol"})
        if score["inputBindingSha256"] != binding:
            raise ValueError("Score is stale relative to the actual paired receipts: " + task["id"])
        rows.append(score)
        files.add(score_path)
        for arm, receipt in arms.items():
            files.add(directory / arm / (task["id"] + ".json"))
            referenced = [m.get("receiptPath") for m in receipt.get("models", [])]
            referenced += [s.get("receiptPath") for s in receipt.get("sources", [])]
            referenced += [r.get("receipt_path") for r in receipt.get("searches", [])]
            for observed in receipt.get("sources", []):
                historical = observed.get("historical") or {}
                document = observed.get("documentExtraction") or {}
                referenced += [historical.get("receiptPath"), historical.get("titleLookupReceipt"), document.get("receiptPath")]
            reuse = receipt.get("sourceReuse") or {}
            referenced += [reuse.get("originalReceipt")]
            referenced += [row.get("path") for row in reuse.get("sources", [])]
            referenced += [receipt.get("receiptPath"), receipt.get("cascade", {}).get("receiptPath")]
            for value in referenced:
                if value:
                    path = Path(value).resolve()
                    if not path.is_relative_to(REPO / "scripts/evidence") or not path.is_file():
                        raise ValueError("A referenced public proof is missing or outside task evidence: " + str(path))
                    files.add(path)
        for document in score["citationDocuments"]:
            path = directory / "citation-docs" / (hashlib.sha256(document["url"].encode()).hexdigest() + ".json")
            if path.is_file():
                files.add(path)
                fetch_receipt = read(path).get("fetchReceiptPath")
                if fetch_receipt:
                    fetched_path = Path(fetch_receipt).resolve()
                    if not fetched_path.is_relative_to(REPO / "scripts/evidence") or not fetched_path.is_file():
                        raise ValueError("Citation fetch receipt missing/outside evidence")
                    files.add(fetched_path)
        judge = score.get("judgeReceipt") or {}
        if judge.get("receiptPath"):
            files.add(Path(judge["receiptPath"]))
    raw = REPO / "scripts/evidence" / ("C10-scored-" + args.run + ".json")
    atomic_json(raw, rows)
    archive = REPO / "scripts/evidence" / ("C10-proof-" + args.run + ".zip")
    manifest = {str(p.relative_to(REPO)).replace("\\", "/"): sha(p) for p in sorted(files)}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(files):
            bundle.write(path, str(path.relative_to(REPO)).replace("\\", "/"))
        bundle.writestr("C10-content-bindings.json", json.dumps(manifest, sort_keys=True))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Proof archive integrity failure")
        for name, expected in manifest.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError("Archive binding mismatch: " + name)
    limitations = ["Frozen FRAMES development panel: repeated repairs are not held-out evidence of general superiority.",
                  "A source-reuse run reports incremental request latency/tokens/cost; the summary separately reports matched original plus repair, with other development attempts separate.",
                  "One arm-blind Sol judge; fetched quote validation is deterministic, semantic judgments remain model judgments.",
                  "Historical baseline PDF-byte caches are preserved; repair2 PDF citations were independently fetched using corrected bounded pypdf text extraction. Frozen judge and rubric are unchanged.",
                  "USD is observed API list-price equivalent, not billed subscription cost; missing usage remains null.",
                  "LAYA runs on CPU with frozen existing weights; no training, stealth, native desktop or public release proof.",
                  "Claude comparison is the lead's separate arm; this result contains Neyvia and OpenAI only."]
    metrics = []
    for arm in ("neyvia", "openai"):
        for name, field, unit in [("accuracy", "correct", "fraction"), ("citation_support", "supportedClaimFraction", "fraction"),
                                  ("reachable_urls", "reachableURLFraction", "fraction"), ("latency", "elapsedMs", "ms")]:
            metrics.append({"name": arm + "_" + name, "unit": unit,
                            "calculation": {"op": "mean", "args": [{"receipt": "raw", "where": {"/kind": "factual"}, "field": "/scores/" + arm + "/" + field}]},
                            "ci_request": {"method": "not-estimable", "reason": "One deterministic fixed development-panel pass; repeated repairs are not independent samples"}})
        known = report["arms"][arm]["cost"].get("observedKnownUsd")
        if known is not None:
            metrics.append({"name": arm + "_observed_known_cost", "unit": "API-equivalent USD lower bound",
                            "calculation": {"receipt": "summary", "pointer": "/arms/" + arm + "/cost/observedKnownUsd"},
                            "ci_request": {"method": "not-estimable", "reason": "Observed usage accounting; unavailable usage and invoice costs unknown"}})
    spec = {"schema": "neyvia.efficiency-result.v1", "id": "C10-" + args.run,
            "study": "C10 public research: Neyvia versus OpenAI", "evidence_status": "aggregate-only",
            "method": "First 50 FRAMES rows at the pinned Apache-2.0 revision plus five frozen briefs; actual codex exec arms; arm-blind frozen-rubric Sol judgment and independent citation fetches. Failed requests stay in denominator50.",
            "models": ["gpt-6-luna via codex exec", "gpt-6.1-sol via codex exec", "laya/laya-english frozen CPU"],
            "tasks": {"description": "50 public factual questions and five open research briefs", "repetitions": 1, "independent_unit": "question or brief"},
            "limitations": limitations, "receipts": [{"id": "raw", "path": str(raw.relative_to(REPO)).replace("\\", "/"), "sha256": sha(raw), "kind": "raw"},
                {"id": "summary", "path": str((directory / "summary.json").relative_to(REPO)).replace("\\", "/"), "sha256": sha(directory / "summary.json"), "kind": "aggregate"}], "metrics": metrics}
    validate(spec, prepare=True)
    atomic_json(REPO / "scripts/evidence" / ("C10-result-" + args.run + ".json"), spec)
    if args.append:
        ledger = REPO / "docs/research/results.jsonl"
        with ledger_lock(ledger):
            existing = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
            previous = next((r for r in existing if r["id"] == spec["id"]), None)
            if previous is not None and previous != spec:
                raise ValueError("Existing append-only result differs; use a fresh run identifier")
            if previous is None:
                with ledger.open("ab") as stream:
                    stream.write((json.dumps(spec, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    atomic_json(REPO / "scripts/evidence" / ("C10-seal-" + args.run + ".json"),
                {"run": args.run, "summary": report, "archive": str(archive.relative_to(REPO)), "archiveSha256": sha(archive),
                 "archiveBytes": archive.stat().st_size, "boundPublicFiles": len(files), "limitations": limitations})
    print(json.dumps({"run": args.run, "complete": True, "archiveBytes": archive.stat().st_size, "resultId": spec["id"]}))


if __name__ == "__main__":
    main()
