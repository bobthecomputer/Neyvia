"""Audit reference matching against a real captured source, including adverse controls."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.research_grounding import match


def main():
    path = REPO / "scripts/evidence/C10d-runs/soft-failures/development/neyvia/frames-020.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    metadata = receipt["sources"][0]
    captured = json.loads(Path(metadata["receiptPath"]).read_text(encoding="utf-8"))["projection"]
    source = {**metadata, "fullText": captured["text"], "tables": captured.get("tables", [])}
    citation = next(c for c in receipt["answer"]["citations"] if c["url"] == source["url"])
    words = citation["quote"].split()
    nonliteral = " ".join(reversed(words))
    checks, observations = {}, {}
    for kind in ("paraphrase", "verbatim"):
        actual = {}
        result = match({"answer": receipt["answer"]["answer"], "citations": [{**citation, "kind": kind, "quote": nonliteral}]}, [source], actual)
        checks[kind] = bool(result["citations"][0]["quote"]) if kind == "paraphrase" else not result["citations"][0]["quote"]
        observations[kind] = actual["citationCapture"]
    actual = {}
    match({"answer": "adverse citation control", "citations": [{**citation,
        "claim": "A volcanic eruption killed 2300 villagers in 1995.", "quote": "", "kind": "paraphrase"}]}, [source], actual)
    checks["unrelatedReferenceFlagged"] = not actual["citationCapture"]["accepted"]
    observations["unrelated"] = actual["citationCapture"]
    unchanged = []
    for artifact in sorted(path.parent.glob("frames-*.json")):
        saved = json.loads(artifact.read_text(encoding="utf-8"))
        sources = []
        for meta in saved["sources"]:
            projection = json.loads(Path(meta["receiptPath"]).read_text(encoding="utf-8"))["projection"]
            sources.append({**meta, "fullText": projection["text"], "tables": projection.get("tables", [])})
        new = match(saved["answer"], sources, {})
        unchanged.append({"id": artifact.stem, "answerUnchanged": new["answer"] == saved["answer"]["answer"] and new["explanation"] == saved["answer"]["explanation"]})
    checks["factualAnswersUnchanged"] = len(unchanged) == 14 and all(r["answerUnchanged"] for r in unchanged)
    result = {"source": str(path.relative_to(REPO)), "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "capturedReceipt": metadata["receiptPath"], "checks": checks, "passed": all(checks.values()),
        "observations": observations, "developmentReplay": unchanged, "modelCalls": 0, "tokens": 0,
        "boundary": "Native-source reference mechanism audit, not semantic accuracy or whole-panel proof; reversed quotation is an explicit adverse control. Citation validity after the signal change awaits the frozen judge."}
    (REPO / "scripts/evidence/C10d-soft-reference-proof.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": checks}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
