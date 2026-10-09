"""Evidence-bound local learning for Neyvia Native.

The store learns from completed receipts and explicit operator feedback.  It never
creates synthetic successes and it does not silently change a route until enough
verified samples support a conservative recommendation.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


LEARNING_SCHEMA = "neyvia.native-learning/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested(value: object, *path: str) -> object:
    current = value
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def usage_payload(value: object) -> dict[str, Any]:
    """Normalize OpenAI Agents usage without assuming optional cache fields."""

    requests = int(_number(_nested(value, "requests")))
    input_tokens = int(_number(_nested(value, "input_tokens")))
    output_tokens = int(_number(_nested(value, "output_tokens")))
    total_tokens = int(_number(_nested(value, "total_tokens"), input_tokens + output_tokens))
    details = _nested(value, "input_tokens_details")
    cached_tokens = int(
        _number(_nested(details, "cached_tokens"))
        or _number(_nested(value, "cached_tokens"))
    )
    uncached_tokens = max(0, input_tokens - cached_tokens)
    payload = {
        "requests": requests,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached_tokens,
        "uncachedInputTokens": uncached_tokens,
        "promptCacheHitRate": (
            round(cached_tokens / input_tokens, 4) if input_tokens else 0.0
        ),
        "reportedByTransport": bool(requests or total_tokens),
    }
    from .proofs_d_native import check_usage
    check_usage(payload, input_tokens, cached_tokens)
    return payload


def wilson_lower_bound(successes: int, attempts: int, z: float = 1.96) -> float:
    if attempts <= 0:
        return 0.0
    p = successes / attempts
    denominator = 1 + z * z / attempts
    centre = p + z * z / (2 * attempts)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * attempts)) / attempts)
    return max(0.0, (centre - margin) / denominator)


class NativeLearningStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / ".agent_control" / "neyvia_agent" / "learning.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS native_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    capsule_id TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    resource_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proof_status TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    cached_input_tokens INTEGER NOT NULL,
                    prompt_cache_hit_rate REAL NOT NULL,
                    tool_cache_hit_rate REAL NOT NULL,
                    operator_value REAL,
                    receipt_path TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_native_runs_kind
                    ON native_runs(task_kind, created_at);
                CREATE TABLE IF NOT EXISTS native_feedback (
                    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    value REAL NOT NULL,
                    note TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES native_runs(run_id)
                );
                """
            )

    def record_run(self, receipt: dict[str, Any], receipt_path: str = "") -> dict[str, Any]:
        behavior = receipt.get("behaviorPlan") or {}
        capsule = behavior.get("capsule") or {}
        proof = receipt.get("proofAudit") or {}
        usage = receipt.get("usage") or {}
        compiler = receipt.get("toolCompiler") or {}
        task_kinds = capsule.get("taskKinds") or ["general"]
        task_kind = str(task_kinds[0] if task_kinds else "general")
        proof_status = str(proof.get("status") or "not_audited")
        verified = int(
            proof_status in {"verified", "completed_read_only"}
            and str(receipt.get("status") or "") == "completed"
        )
        row = (
            str(receipt.get("runId") or ""),
            str(receipt.get("finishedAt") or _utc_now()),
            task_kind,
            str(capsule.get("id") or "unknown"),
            str(behavior.get("planHash") or ""),
            str(receipt.get("model") or ""),
            str((receipt.get("provider") or {}).get("transport") or ""),
            str((receipt.get("resourceProfile") or {}).get("mode") or "unknown"),
            str(receipt.get("status") or "unknown"),
            proof_status,
            verified,
            int(_number(receipt.get("durationMs"))),
            int(_number(usage.get("totalTokens"))),
            int(_number(usage.get("cachedInputTokens"))),
            _number(usage.get("promptCacheHitRate")),
            _number(compiler.get("hitRate")),
            None,
            str(receipt_path or receipt.get("receiptPath") or ""),
        )
        if not row[0]:
            raise ValueError("A run id is required before learning can record an outcome.")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO native_runs (
                    run_id, created_at, task_kind, capsule_id, plan_hash,
                    model, transport, resource_mode, status, proof_status,
                    verified, duration_ms, total_tokens, cached_input_tokens,
                    prompt_cache_hit_rate, tool_cache_hit_rate, operator_value,
                    receipt_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    proof_status=excluded.proof_status,
                    verified=excluded.verified,
                    duration_ms=excluded.duration_ms,
                    total_tokens=excluded.total_tokens,
                    cached_input_tokens=excluded.cached_input_tokens,
                    prompt_cache_hit_rate=excluded.prompt_cache_hit_rate,
                    tool_cache_hit_rate=excluded.tool_cache_hit_rate,
                    receipt_path=excluded.receipt_path
                """,
                row,
            )
            from .proofs_d_native import check_learning
            check_learning(connection, receipt)
        return self.run_snapshot(row[0])

    def record_feedback(self, run_id: str, value: float, note: str = "") -> dict[str, Any]:
        bounded = max(0.0, min(100.0, float(value)))
        with self.connection() as connection:
            found = connection.execute(
                "SELECT run_id FROM native_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if found is None:
                raise KeyError(f"Unknown native run: {run_id}")
            connection.execute(
                "INSERT INTO native_feedback(run_id, created_at, value, note) VALUES (?, ?, ?, ?)",
                (run_id, _utc_now(), bounded, str(note or "")[:2000]),
            )
            connection.execute(
                "UPDATE native_runs SET operator_value = ? WHERE run_id = ?",
                (bounded, run_id),
            )
        return self.run_snapshot(run_id)

    def run_snapshot(self, run_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM native_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return {}
        payload = dict(row)
        payload["verified"] = bool(payload["verified"])
        return payload

    def recommend(self, task_kind: str, minimum_samples: int = 8) -> dict[str, Any]:
        kind = str(task_kind or "general")
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT capsule_id, resource_mode,
                       COUNT(*) AS attempts,
                       SUM(verified) AS successes,
                       AVG(duration_ms) AS mean_duration_ms,
                       AVG(total_tokens) AS mean_total_tokens,
                       AVG(prompt_cache_hit_rate) AS mean_prompt_cache_hit_rate,
                       AVG(tool_cache_hit_rate) AS mean_tool_cache_hit_rate,
                       AVG(operator_value) AS mean_operator_value
                FROM native_runs
                WHERE task_kind = ?
                GROUP BY capsule_id, resource_mode
                ORDER BY attempts DESC
                """,
                (kind,),
            ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            attempts = int(row["attempts"] or 0)
            successes = int(row["successes"] or 0)
            candidates.append(
                {
                    "capsuleId": row["capsule_id"],
                    "resourceMode": row["resource_mode"],
                    "attempts": attempts,
                    "verifiedRuns": successes,
                    "successRate": round(successes / attempts, 4) if attempts else 0.0,
                    "successLowerBound": round(wilson_lower_bound(successes, attempts), 4),
                    "meanDurationMs": round(float(row["mean_duration_ms"] or 0), 2),
                    "meanTotalTokens": round(float(row["mean_total_tokens"] or 0), 2),
                    "meanPromptCacheHitRate": round(float(row["mean_prompt_cache_hit_rate"] or 0), 4),
                    "meanToolCacheHitRate": round(float(row["mean_tool_cache_hit_rate"] or 0), 4),
                    "meanOperatorValue": (
                        round(float(row["mean_operator_value"]), 2)
                        if row["mean_operator_value"] is not None
                        else None
                    ),
                }
            )
        eligible = [row for row in candidates if row["attempts"] >= minimum_samples]
        eligible.sort(
            key=lambda row: (
                row["successLowerBound"],
                row["meanOperatorValue"] if row["meanOperatorValue"] is not None else -1,
                -row["meanDurationMs"],
            ),
            reverse=True,
        )
        best = eligible[0] if eligible else None
        result = {
            "schema": LEARNING_SCHEMA,
            "taskKind": kind,
            "minimumSamples": minimum_samples,
            "evidenceRuns": sum(row["attempts"] for row in candidates),
            "eligible": bool(best),
            "applied": False,
            "recommendation": best,
            "candidates": candidates,
            "reason": (
                "A conservative evidence-backed recommendation is available; the caller may opt in."
                if best
                else f"Learning remains observational until one route has at least {minimum_samples} real runs."
            ),
        }
        from .proofs_d_native import check_recommendation
        check_recommendation(result)
        return result

    def behavior_adjustment(self, task_kind: str) -> dict[str, Any]:
        recommendation = self.recommend(task_kind)
        best = recommendation.get("recommendation") or {}
        if not best or best.get("successLowerBound", 0) < 0.6:
            return {
                "applied": False,
                "evidenceRuns": recommendation["evidenceRuns"],
                "reason": recommendation["reason"],
                "behaviorVectorDelta": {},
            }
        # Learning is intentionally small and bounded.  It never weakens proof pressure.
        value = best.get("meanOperatorValue")
        return {
            "applied": True,
            "evidenceRuns": recommendation["evidenceRuns"],
            "recommendedCapsuleId": best.get("capsuleId"),
            "recommendedResourceMode": best.get("resourceMode"),
            "reason": "Applied a small adjustment from verified runs with a conservative success bound.",
            "behaviorVectorDelta": {
                "initiative": 0.04 if value is not None and value >= 75 else 0.0,
                "compression": 0.03 if best.get("meanTotalTokens", 0) > 0 else 0.0,
                "verificationPressure": 0.0,
            },
        }

    def summary(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS attempts,
                       SUM(verified) AS verified_runs,
                       AVG(duration_ms) AS mean_duration_ms,
                       AVG(prompt_cache_hit_rate) AS prompt_cache,
                       AVG(tool_cache_hit_rate) AS tool_cache,
                       SUM(cached_input_tokens) AS cached_tokens,
                       SUM(total_tokens) AS total_tokens
                FROM native_runs
                """
            ).fetchone()
        attempts = int(row["attempts"] or 0)
        verified = int(row["verified_runs"] or 0)
        return {
            "schema": LEARNING_SCHEMA,
            "attempts": attempts,
            "verifiedRuns": verified,
            "verifiedRate": round(verified / attempts, 4) if attempts else 0.0,
            "meanDurationMs": round(float(row["mean_duration_ms"] or 0), 2),
            "meanPromptCacheHitRate": round(float(row["prompt_cache"] or 0), 4),
            "meanToolCacheHitRate": round(float(row["tool_cache"] or 0), 4),
            "cachedInputTokens": int(row["cached_tokens"] or 0),
            "totalTokens": int(row["total_tokens"] or 0),
            "truthBoundary": "Only real receipts and explicit feedback contribute to this summary.",
        }
