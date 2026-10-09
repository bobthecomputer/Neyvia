from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from grant_agent.context_engine import DurableContextEngine


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(root: Path, *, rounds: int = 12) -> dict:
    run_id = f"context-stress-{_stamp()}"
    engine = DurableContextEngine(
        root,
        run_id,
        max_context_tokens=40_000,
        reserve_tokens=5_000,
        protect_recent_tokens=3_000,
        max_inline_tool_tokens=200,
    )
    sentinels: list[str] = []
    receipts: list[dict] = []
    started = time.perf_counter()
    for round_index in range(rounds):
        sentinel = f"decision-sentinel-{round_index:02d}-transport-generation-{round_index:04d}"
        sentinels.append(sentinel)
        engine.append(
            "system",
            f"{sentinel}: preserve this verified architectural decision.",
            kind="decision",
            importance=1.0,
            pinned=True,
            source="long-context-stress",
        )
        for output_index in range(20):
            engine.append(
                "tool",
                (
                    f"round={round_index} tool={output_index} "
                    + (f"trace-{round_index}-{output_index} " * 260)
                ),
                kind="tool_output",
                source="stress-tool",
            )
        for event_index in range(80):
            engine.append(
                "assistant",
                (
                    f"round={round_index} progress={event_index} "
                    + (f"implementation-evidence-{round_index}-{event_index} " * 28)
                ),
                kind="message",
                source="stress-run",
            )
        receipts.append(
            engine.compact(
                focus=f"preserve architecture and proof through round {round_index}",
                target_ratio=0.15,
            )
        )

    retrieval = {
        sentinel: engine.search(sentinel, limit=3)
        for sentinel in sentinels
    }
    bundle = engine.build_bundle(
        "transport generation architectural decisions and latest proof",
        token_budget=30_000,
    )
    status = engine.status()
    visible_limit = int(status["modelVisibleLimit"])
    retrieved_sentinels = [
        sentinel
        for sentinel, matches in retrieval.items()
        if any(sentinel in str(item.get("content") or "") for item in matches)
    ]
    report = {
        "schema": "neyvia.long_context_stress.v1",
        "runId": run_id,
        "rounds": rounds,
        "durationMs": int((time.perf_counter() - started) * 1000),
        "status": status,
        "retainedToVisibleRatio": round(
            int(status["totalTokensRetained"]) / max(1, visible_limit),
            2,
        ),
        "bundle": {
            "estimatedTokens": bundle["estimated_tokens"],
            "tokenBudget": bundle["token_budget"],
            "itemCount": len(bundle["items"]),
            "cacheKey": bundle["cache_key"],
            "stablePrefixCacheKey": bundle["stable_prefix_cache_key"],
            "segments": bundle["segments"],
        },
        "sentinels": {
            "expected": sentinels,
            "retrieved": retrieved_sentinels,
        },
        "compactions": [
            {
                "compactionId": item.get("compactionId"),
                "archivedCount": item.get("archivedCount", 0),
                "protectedCount": item.get("protectedCount", 0),
                "checkpointEventId": item.get("checkpointEventId", ""),
                "receiptPath": item.get("receiptPath", ""),
            }
            for item in receipts
        ],
        "passed": (
            len(retrieval) == len(sentinels)
            and len(retrieved_sentinels) == len(sentinels)
            and bundle["estimated_tokens"] <= bundle["token_budget"]
            and float(status["totalTokensRetained"]) >= visible_limit * 10
            and len(retrieved_sentinels) == rounds
        ),
    }
    output_root = root / ".agent_control" / "mission_artifacts" / "context_stress" / run_id
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "long-context-stress.json"
    report["reportPath"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Neyvia durable context beyond one model window.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--rounds", type=int, default=12)
    args = parser.parse_args()
    report = run(Path(args.root).resolve(), rounds=max(2, min(args.rounds, 50)))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
