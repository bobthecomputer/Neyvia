"""Run T4 feedback migration, durability and concurrent-writer acceptance journeys.

Uses only the standard library and real workspace stores; no external services.
Run with system Python and --output scripts/evidence/T4-feedback.json.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.model_tool_intelligence import ToolFeedbackStore


def expected(events, limit=5000):
    grouped = {}
    for event in events[-max(1, min(int(limit), 10000)):]:
        if event.get("callTarget"):
            grouped.setdefault(event["callTarget"], []).append(event)
    result = {}
    for target, rows in grouped.items():
        successes = sum(bool(row.get("ok")) for row in rows)
        errors = sum(not row.get("argumentValid", True) for row in rows)
        corrections = sum(bool(row.get("userCorrected")) for row in rows)
        durations = sorted(float(row.get("durationMs") or 0) for row in rows)
        reliability = (successes + 1) / (len(rows) + 2)
        reliability *= max(.25, 1 - (errors + corrections) / len(rows))
        result[target] = {
            "calls": len(rows), "successes": successes,
            "argumentErrors": errors, "userCorrections": corrections,
            "reliability": round(reliability, 4),
            "p50LatencyMs": durations[len(rows) // 2],
        }
    return result


def worker(root, label, count):
    store = ToolFeedbackStore(root)
    for index in range(count):
        store.record({"eventId": f"{label}-{index}", "callTarget": "concurrent.call",
                      "ok": index % 3 != 0, "durationMs": index + .5})


def verify(root):
    store = ToolFeedbackStore(root)
    store.directory.mkdir(parents=True, exist_ok=True)
    legacy = [{"eventId": f"legacy-{i}", "callTarget": f"tool.{i % 3}",
               "ok": i % 4 != 0, "durationMs": i % 71 + .25,
               "argumentValid": i % 13 != 0, "userCorrected": i % 19 == 0}
              for i in range(5106)]
    store.path.write_text("{malformed}\n" + "".join(json.dumps(row) + "\n" for row in legacy),
                          encoding="utf-8")
    began = time.perf_counter()
    assert store.aggregate() == expected(legacy), "Legacy migration metrics differ"
    migration_ms = (time.perf_counter() - began) * 1000
    assert store.recent(limit=3) == legacy[-3:]
    for limit in (0, 1, 3, 4999, 5000, 10000, 12000):
        assert store.aggregate(limit=limit) == expected(legacy, limit), limit
    # A new store opens the same on-disk index, rather than migrating again.
    reopened = ToolFeedbackStore(root)
    assert reopened.aggregate() == expected(legacy)
    appended = {"eventId": "external-append", "callTarget": "tool.external",
                "ok": True, "durationMs": 42}
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(appended) + "\n")
    legacy.append(appended)
    assert reopened.aggregate() == expected(legacy), "External JSONL append was lost"
    # SQLite rollback after a durable log append is recovered exactly once.
    class InterruptedStore(ToolFeedbackStore):
        def _insert(self, connection, event, offset):
            if event.get("eventId") == "interrupt-after-append":
                raise RuntimeError("injected interruption after durable append")
            return super()._insert(connection, event, offset)
    try:
        InterruptedStore(root).record({"eventId": "interrupt-after-append",
                                      "callTarget": "recovered.call", "ok": True})
    except RuntimeError as error:
        assert "injected interruption" in str(error)
    else:
        raise AssertionError("Interruption was not exercised")
    restored = ToolFeedbackStore(root)
    assert restored.aggregate()["recovered.call"]["calls"] == 1
    assert restored.aggregate()["recovered.call"]["calls"] == 1
    # Four independent Python processes exercise actual SQLite writer arbitration.
    writers, writes_each = 4, 40
    processes = [subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(root),
         f"writer-{i}", str(writes_each)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
         text=True) for i in range(writers)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, stdout + stderr
    recent = restored.recent(limit=10000)
    assert len(recent) == 5106 + 1 + 1 + writers * writes_each
    ids = [row["eventId"] for row in recent if row["eventId"].startswith("writer-")]
    assert len(ids) == len(set(ids)) == writers * writes_each
    assert restored.aggregate() == expected(recent), "Concurrent/rolling counters differ"
    with sqlite3.connect(restored.index_path) as connection:
        plans = {
            "recent": [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT payload FROM feedback_events ORDER BY sequence DESC LIMIT 100")],
            "aggregate": [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM feedback_aggregates")],
            "latency": [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT duration FROM feedback_window WHERE target=? "
                "ORDER BY duration,sequence LIMIT 1 OFFSET 5", ("tool.0",))],
        }
        counts = dict(connection.execute("SELECT key,value FROM feedback_metadata"))
        window_rows = connection.execute("SELECT count(*) FROM feedback_window").fetchone()[0]
        assert window_rows == 5000
        assert int(counts["offset"]) == restored.path.stat().st_size
    assert any("COVERING INDEX feedback_window_latency" in row for row in plans["latency"])
    assert not any("TEMP B-TREE" in row for row in plans["latency"])
    baseline = expected(recent)
    start = time.perf_counter()
    for _ in range(50):
        assert restored.aggregate() == baseline
    warm_ms = (time.perf_counter() - start) * 1000 / 50
    # Exercise the production capability facade, including its write authorization.
    from grant_agent.capability_service import CapabilityService
    service = CapabilityService(root)
    facade_target = "model.tools.feedback.record"
    denied = service.record_model_tool_feedback({"callTarget": facade_target, "ok": True})
    assert denied["status"] == "approval_required"
    written = service.record_model_tool_feedback({"approved": True, "callTarget": facade_target,
                                                 "ok": True, "durationMs": 12})
    snapshot = service.model_tool_feedback({"limit": 2})
    assert snapshot["events"][-1]["eventId"] == written["eventId"]
    assert snapshot["aggregates"][facade_target]["calls"] == 1
    belt = service.compile_model_tool_belt({"task": "record tool feedback", "limit": 8})
    card = next(tool for tool in belt["tools"] if tool["callTarget"] == facade_target)
    assert card["observedCalls"] == 1 and card["p50LatencyMs"] == 12
    assert card["reliability"] == snapshot["aggregates"][facade_target]["reliability"]
    # An interrupted external append remains pending until its row is complete.
    edge = ToolFeedbackStore(root / "edge-cases")
    edge.directory.mkdir(parents=True, exist_ok=True)
    pending = {"eventId": "pending", "callTarget": "pending.call", "ok": True}
    edge.path.write_text(json.dumps(pending), encoding="utf-8")
    assert edge.recent() == []
    added = edge.record({"callTarget": "after-pending.call", "ok": True})
    assert [row["eventId"] for row in edge.recent()] == ["pending", added["eventId"]]
    assert edge.aggregate()["pending.call"]["calls"] == 1
    before = edge.path.stat().st_size
    try:
        edge.record({"callTarget": "invalid.call", "durationMs": float("nan")})
    except ValueError:
        pass
    else:
        raise AssertionError("Nonfinite latency was accepted")
    assert edge.path.stat().st_size == before
    # Explicit replacement of the legacy log invalidates all old indexed rows.
    edge.path.write_text(json.dumps({"callTarget": "replacement.call", "ok": True}) + "\n",
                         encoding="utf-8")
    assert set(edge.aggregate()) == {"replacement.call"}
    return {
        "ok": True, "root": str(root), "legacyEventsMigrated": 5106,
        "externalAppendImported": True, "reopenPreserved": True,
        "interruptedAppendRecoveredExactlyOnce": True,
        "concurrentProcesses": writers, "concurrentWrites": writers * writes_each,
        "rollingWindowEvents": window_rows, "customWindowsMatch": True,
        "facadeApprovalEnforced": True, "facadeSnapshot": snapshot,
        "modelBeltConsumesIndexedFeedback": True,
        "beltCard": {key: card[key] for key in
                     ("name", "callTarget", "observedCalls", "p50LatencyMs", "reliability")},
        "incompleteTailRecovered": True, "nonfiniteLatencyRejected": True,
        "replacedLogReindexed": True,
        "queryPlans": plans, "migrationMs": round(migration_ms, 3),
        "warmAggregateMeanMs": round(warm_ms, 3),
        "indexedOffsetBytes": int(counts["offset"]),
        "indexPath": str(restored.index_path), "logPath": str(restored.path),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--worker", nargs=3)
    args = parser.parse_args()
    if args.worker:
        worker(Path(args.worker[0]), args.worker[1], int(args.worker[2]))
        return
    root = args.root or Path(tempfile.mkdtemp(prefix="neyvia-t4-feedback-"))
    result = verify(root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
