"""Time and check full research journeys through neyvia.research.journey.

Each frozen public question runs through Neyvia's own tools in a fresh task
root (search -> open -> dedupe -> extract -> cite -> answer -> re-verify).
The lexical answer check below is a development signal only: semantic support
stays the manual's separate judgement. Receipts are copied to --output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

QUESTIONS = [
    ("apollo", "In what year did Apollo 11 land on the Moon?", [r"\b1969\b"]),
    ("python", "Who created the Python programming language?", [r"Guido van Rossum"]),
    ("candela", "What is the SI base unit of luminous intensity?", [r"\bcandela\b"]),
    ("http", "Which RFC defines HTTP Semantics?", [r"\b9110\b"]),
    ("canberra", "What is the capital city of Australia?", [r"\bCanberra\b"]),
    ("alice", "Who wrote Alice's Adventures in Wonderland?", [r"Lewis Carroll"]),
    ("gold", "What is the chemical symbol for gold?", [r"\bAu\b"]),
    ("congress", "In which city did the United States Congress meet from 1790 to 1800?", [r"\bPhiladelphia\b"]),
    ("w3c", "In what year was the World Wide Web Consortium founded?", [r"\b1994\b"]),
    ("kilimanjaro", "What is the tallest mountain in Africa?", [r"\bKilimanjaro\b"]),
    ("mars", "Which planet is known as the Red Planet?", [r"\bMars\b"]),
    ("curie", "Who was the first woman to win a Nobel Prize?", [r"\bCurie\b"]),
    ("light", "What is the speed of light in vacuum in metres per second?", [r"299[,\s]?792[,\s]?458"]),
    ("mona-lisa", "Who painted the Mona Lisa?", [r"Leonardo"]),
    ("ocean", "What is the largest ocean on Earth?", [r"\bPacific\b"]),
    ("berlin", "In what year did the Berlin Wall fall?", [r"\b1989\b"]),
    ("hydrogen", "Which chemical element has atomic number 1?", [r"(?i)\bhydrogen\b"]),
    ("relativity", "Who developed the theory of general relativity?", [r"\bEinstein\b"]),
    ("nile", "What is the longest river in Africa?", [r"\bNile\b"]),
    ("wcag", "Which organization publishes the Web Content Accessibility Guidelines?", [r"W3C|World Wide Web Consortium"]),
]
CASES_SHA = hashlib.sha256(json.dumps(QUESTIONS).encode()).hexdigest()


def percentile(values, p):
    return sorted(values)[max(0, int(len(values) * p + 0.999999) - 1)] if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Task root for runtimes (fast local disk)")
    parser.add_argument("--output", type=Path, required=True, help="Receipt directory (copied after the run)")
    parser.add_argument("--ports", required=True, help="Assigned local ports, e.g. 49041-49045; the first is Obscura's")
    parser.add_argument("--obscura", type=Path, help="Admitted Obscura executable; omit to run plain HTTP only")
    parser.add_argument("--answer-model", default="extractive", choices=["extractive", "gpt-6.1-sol"])
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    from grant_agent.browser_ports import parse_ports
    ports = sorted(parse_ports(args.ports))
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      NEYVIA_BROWSER_PROOF_PORTS=args.ports)
    if args.obscura:
        os.environ["NEYVIA_OBSCURA_EXE"] = str(args.obscura.resolve())
    from grant_agent.native_tools import NativeToolRegistry
    args.root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    registry = NativeToolRegistry(args.root)
    initialization_ms = (time.perf_counter() - started) * 1000
    rows = []
    for identity, question, expected in QUESTIONS:
        if args.only and identity not in args.only:
            continue
        call = {"question": question, "answerModel": args.answer_model}
        if args.obscura:
            call["obscuraPort"] = ports[0]
        began = time.perf_counter()
        result = registry.call("neyvia.research.journey", call)
        wall = (time.perf_counter() - began) * 1000
        value = result.get("result") or {}
        answer = (value.get("answer") or {}).get("answer", "")
        quotes = " ".join(c.get("quote", "") for c in value.get("citations", []))
        found = all(re.search(pattern, answer) for pattern in expected)
        row = {"id": identity, "question": question, "status": value.get("status"), "ok": result.get("ok"),
               "error": value.get("error") or result.get("error"), "wallMs": round(wall, 1), "elapsedMs": value.get("elapsedMs"),
               "stages": {s["stage"]: s["elapsedMs"] for s in value.get("stages", [])}, "toolCalls": value.get("toolCalls"),
               "provider": (value.get("search") or {}).get("provider"), "sources": [s.get("url") for s in value.get("sources", [])],
               "retrievals": [s.get("retrieval") for s in value.get("sources", [])],
               "citations": len(value.get("citations", [])), "citationsReverified": all(c.get("reverified") for c in value.get("citations", [])),
               "grounded": (value.get("claimGrounding") or {}).get("accepted"), "answer": answer,
               "expectedInAnswer": found, "expectedInCitedQuotes": all(re.search(p, quotes) for p in expected),
               "receiptPath": value.get("receiptPath"), "toolReceipt": result.get("receipt_path"), "tokens": value.get("tokens")}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("id", "status", "wallMs", "provider", "citations", "grounded", "expectedInAnswer")}), flush=True)
    walls = [row["wallMs"] for row in rows]
    completed = [row for row in rows if row["status"] == "completed" and row["grounded"] and row["citationsReverified"]]
    report = {"schema": "neyvia.rx-research.journeys.v1", "casesSha256": CASES_SHA, "answerModel": args.answer_model,
              "ports": ports, "obscura": str(args.obscura) if args.obscura else None, "initializationMs": round(initialization_ms, 1),
              "journeys": len(rows), "completedVerified": len(completed),
              "expectedAnswerFound": sum(row["expectedInAnswer"] for row in rows),
              "wallMs": {"p50": statistics.median(walls) if walls else None, "p95": percentile(walls, .95),
                         "mean": round(statistics.mean(walls), 1) if walls else None, "max": max(walls) if walls else None},
              "boundary": "Lexical expected-answer presence is a development signal; semantic support is the manual's separate judgement. "
                          "Times include every native tool receipt; search is paced for the no-key provider.",
              "rows": rows}
    args.output.mkdir(parents=True, exist_ok=True)
    for row in rows:
        if row["receiptPath"] and Path(row["receiptPath"]).is_file():
            target = args.output / "receipts" / row["id"]
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row["receiptPath"], target / "receipt.json")
    (args.output / "journeys.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
