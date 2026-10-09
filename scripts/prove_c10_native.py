"""Real native research, receipt replay, and confined refusal on owned ports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.transition_memory import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obscura-port", required=True, type=int)
    parser.add_argument("--laya-port", required=True, type=int)
    parser.add_argument("--proof-name", default="C10-native-final")
    parser.add_argument("--task-id", help="Optional frozen factual task; pass only its public model prompt, never its reference answer")
    args = parser.parse_args()
    if any(port not in range(48771, 48780) for port in (args.obscura_port, args.laya_port)):
        parser.error("Explicit C10 ports48771-48779 required")
    if not args.proof_name.startswith("C10-native-") or not args.proof_name.replace("-", "").isalnum():
        parser.error("Simple C10-native- proof name required")
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_OBSCURA_EXE=str(REPO / ".agent_control/T20/obscura-v0.2.3/bin/obscura.exe"),
                      NEYVIA_BROWSER_PROOF_PORTS=",".join(str(p) for p in range(48771, 48780)),
                      NEYVIA_LAYA_URL=f"http://127.0.0.1:{args.laya_port}")
    root = REPO / "scripts/evidence" / args.proof_name
    registry = NativeToolRegistry(root)
    question = "Who was Harriet Lane's mother? Give her complete name with a direct source quotation."
    panel = None
    if args.task_id:
        panel = json.loads((REPO / "scripts/evidence/C10-tasks.json").read_text(encoding="utf-8"))
        task = next((task for task in panel["questions"] if task["id"] == args.task_id), None)
        if task is None:
            parser.error("Unknown frozen factual task")
        question = task["model_prompt"]
    try:
        native = registry.call("neyvia.research.answer", {"question": question,
                               "obscuraPort": args.obscura_port, "rounds": 2, "timeoutSeconds": 600})
        research = native.get("result", {})
        path = research.get("receiptPath", "")
        replay = registry.call("neyvia.research.receipt", {"path": path}) if path else {"ok": False}
        refused = registry.call("neyvia.research.receipt", {"path": str(REPO / "scripts/evidence/C10b.json")})
        sources = research.get("sources", [])
        laya = [s["laya"] for s in sources if s.get("laya", {}).get("available")]
        ranking_batches = [b for b in research.get("snippetRankingBatches", [])
                           if b.get("available") and b.get("response")]
        legacy_rankings = [r["judgment"] for r in research.get("snippetRanking", [])
                           if r.get("judgment", {}).get("available") and r["judgment"].get("response")]
        actual_rankings = ranking_batches or legacy_rankings
        checks = {"nativeCompleted": native.get("ok") and research.get("status") == "completed",
                  "directCitations": bool(research.get("answer", {}).get("citations")),
                  "actualLaya": bool(laya or actual_rankings),
                  "capturedSourceEvidence": bool(sources), "providerCalls": bool(research.get("models")),
                  "answerChallenge": any(c["accepted"] for c in research.get("answerChecks", [])),
                  "boundSource": bool(research.get("sourceBinding")),
                  "receiptReplay": replay.get("ok") and replay.get("result") == research,
                  "escapeRefused": not refused.get("ok")}
        checks["nonemptyAnswer" if args.task_id else "completeName"] = (
            bool(research.get("answer", {}).get("answer", "").strip()) if args.task_id
            else "jane ann" in research.get("answer", {}).get("answer", "").casefold())
        proof = {"schema": "neyvia.C10.native-final.v1", "passed": all(checks.values()), "checks": checks,
                 "question": research.get("question"), "answer": research.get("answer"), "route": research.get("cascade", {}).get("route"),
                 "elapsedMs": research.get("elapsedMs"), "layaCalls": len(laya) + len(actual_rankings),
                 "snippetRankingCalls": len(actual_rankings), "tokens": research.get("tokens"),
                 "sourceBinding": research.get("sourceBinding"), "receiptPath": path,
                 "receiptSha256": hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None,
                 "nativeReceiptPath": native.get("receipt_path"), "replayReceiptPath": replay.get("receipt_path"),
                 "refusalReceiptPath": refused.get("receipt_path"), "ports": [args.obscura_port, args.laya_port]}
        if panel:
            proof.update(taskId=args.task_id, panelSha256=panel["panel_sha256"],
                         accuracyBoundary="Native execution gates only; factual accuracy requires the frozen independent scorer")
        atomic_json(REPO / "scripts/evidence" / (args.proof_name + ".json"), proof)
        print(json.dumps(proof, ensure_ascii=False))
        if not proof["passed"]:
            raise SystemExit(1)
    finally:
        workspace_for(root).close()


if __name__ == "__main__":
    main()
