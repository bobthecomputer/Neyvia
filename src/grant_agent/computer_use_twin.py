"""Isolated structured Computer Use comparison and worker-dispatch backend.

A Computer Use Twin is a verifier lane, not a screenshot clone. It runs the
existing structured CU acceptance flows one or more times, records compact
receipts, and compares candidate correctness, determinism, latency, and compact
context size with a retained baseline. Remote runs are ordinary cluster jobs
requiring a browser-capable worker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capability_contracts import canonical_hash, normalized_strings, utc_now
from .cu_acceptance import CANONICAL_FLOWS, FLOW_ALIASES, run_suite
from .proofs_a_capabilities import checked_action
from .proofs_a_capability_tools import check_metrics, check_twin_run, check_dispatch, check_worker


CU_TWIN_SPEC_SCHEMA = "neyvia.computer_use_twin_spec.v1"
CU_TWIN_RUN_SCHEMA = "neyvia.computer_use_twin_run.v1"
CU_TWIN_DISPATCH_SCHEMA = "neyvia.computer_use_twin_dispatch.v1"
CU_TWIN_MODES = frozenset({"live", "replay"})


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(float(ordered[index]), 3)


def _duration_from_receipt(receipt: dict[str, Any]) -> float | None:
    direct = receipt.get("durationMs")
    if isinstance(direct, (int, float)) and direct >= 0:
        return float(direct)
    try:
        started = datetime.fromisoformat(
            str(receipt.get("startedAt") or "").replace("Z", "+00:00")
        )
        finished = datetime.fromisoformat(
            str(receipt.get("finishedAt") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds() * 1000.0)


@checked_action(check_metrics)
def summarize_cu_receipts(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    flows: dict[str, list[bool]] = {}
    durations: list[float] = []
    compact_bytes = 0
    all_tree_omitted = True
    live_receipts = 0
    for receipt in receipts:
        duration = _duration_from_receipt(receipt)
        if duration is not None:
            durations.append(duration)
        compact_bytes += len(
            json.dumps(receipt, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        all_tree_omitted = all_tree_omitted and bool(receipt.get("treeOmitted"))
        if str(receipt.get("baseUrl") or "").startswith(("http://", "https://")):
            live_receipts += 1
        for result in receipt.get("results") or []:
            if not isinstance(result, dict):
                continue
            flow = str(result.get("flow") or "")
            if flow:
                flows.setdefault(flow, []).append(
                    bool(result.get("pass")) and not bool(result.get("skipped"))
                )
    outcomes = [value for values in flows.values() for value in values]
    correctness = (
        sum(1 for value in outcomes if value) / len(outcomes)
        if outcomes
        else 0.0
    )
    deterministic = (
        sum(1 for values in flows.values() if len(set(values)) <= 1) / len(flows)
        if flows
        else 0.0
    )
    return {
        "repetitions": len(receipts),
        "flowObservations": len(outcomes),
        "flowSuccessRate": round(correctness, 6),
        "deterministicAgreement": round(deterministic, 6),
        "latency": {
            "p50Ms": _percentile(durations, 0.50),
            "p95Ms": _percentile(durations, 0.95),
            "maximumMs": round(max(durations), 3) if durations else None,
        },
        "compactReceiptBytes": compact_bytes,
        "structuredTreeOmitted": all_tree_omitted,
        "liveReceiptCount": live_receipts,
        "flowOutcomes": {
            flow: {
                "passes": sum(1 for value in values if value),
                "total": len(values),
                "agreement": len(set(values)) <= 1,
            }
            for flow, values in sorted(flows.items())
        },
    }


class ComputerUseTwinService:
    """Create, execute, compare, replay, and remotely dispatch CU twin specs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.base_dir = (
            self.root
            / ".agent_control"
            / "mission_artifacts"
            / "computer_use_twin"
        )
        self.spec_dir = self.base_dir / "specs"
        self.run_dir = self.base_dir / "runs"

    def validate_spec(self, payload: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        mode = str(payload.get("mode") or "live").strip().lower()
        if mode not in CU_TWIN_MODES:
            errors.append(f"mode must be one of {sorted(CU_TWIN_MODES)}")
        flows: list[str] = []
        for name in normalized_strings(payload.get("flows")) or list(
            CANONICAL_FLOWS
        ):
            canonical = FLOW_ALIASES.get(name)
            if canonical is None:
                errors.append(f"unknown Computer Use flow: {name}")
            elif canonical not in flows:
                flows.append(canonical)
        try:
            repetitions = int(payload.get("repetitions") or 1)
        except (TypeError, ValueError):
            repetitions = 0
        if repetitions < 1 or repetitions > 10:
            errors.append("repetitions must be between 1 and 10")
        baseline_path = str(payload.get("baselineReceiptPath") or "").strip()
        replay_path = str(payload.get("replayReceiptPath") or "").strip()
        if mode == "replay" and not replay_path:
            errors.append("replay mode requires replayReceiptPath")
        thresholds = dict(payload.get("thresholds") or {})
        normalized = {
            "schema": CU_TWIN_SPEC_SCHEMA,
            "specId": str(
                payload.get("specId") or f"cutwin_{uuid.uuid4().hex[:16]}"
            ),
            "name": str(payload.get("name") or "N-E-Y-V-I-A CU comparison"),
            "mode": mode,
            "baseUrl": str(payload.get("baseUrl") or "").rstrip("/"),
            "flows": flows,
            "repetitions": repetitions,
            "baselineReceiptPath": baseline_path,
            "replayReceiptPath": replay_path,
            "thresholds": {
                "minimumFlowSuccessRate": float(
                    thresholds.get("minimumFlowSuccessRate", 1.0)
                ),
                "minimumDeterministicAgreement": float(
                    thresholds.get("minimumDeterministicAgreement", 1.0)
                ),
                "maximumLatencyRatio": float(
                    thresholds.get("maximumLatencyRatio", 1.0)
                ),
                "maximumCompactReceiptBytes": int(
                    thresholds.get("maximumCompactReceiptBytes", 256_000)
                ),
                "requireLiveProof": bool(
                    thresholds.get("requireLiveProof", mode == "live")
                ),
            },
            "metadata": dict(payload.get("metadata") or {}),
            "createdAt": str(payload.get("createdAt") or utc_now()),
        }
        for key, value in normalized["thresholds"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value < 0:
                    errors.append(f"thresholds.{key} cannot be negative")
        return {
            "schema": "neyvia.computer_use_twin_validation.v1",
            "valid": not errors,
            "errors": errors,
            "spec": normalized,
            "specHash": canonical_hash(normalized),
        }

    def save_spec(
        self,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        validation = self.validate_spec(payload)
        if not validation["valid"]:
            return {"ok": False, "status": "invalid", "validation": validation}
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "artifact.write",
                "validation": validation,
            }
        spec = validation["spec"]
        path = self.spec_dir / f"{spec['specId']}.json"
        _atomic_json(path, spec)
        return {
            "ok": True,
            "status": "saved",
            "spec": spec,
            "specHash": validation["specHash"],
            "path": str(path),
        }

    def get_spec(self, spec_id: str) -> dict[str, Any]:
        path = self.spec_dir / f"{str(spec_id or '').strip()}.json"
        if not path.exists():
            raise KeyError(f"Unknown Computer Use Twin spec: {spec_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        validation = self.validate_spec(payload)
        if not validation["valid"]:
            raise RuntimeError(
                "Invalid stored Computer Use Twin spec: "
                + "; ".join(validation["errors"])
            )
        return validation["spec"]

    def list_specs(self) -> dict[str, Any]:
        specs: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if self.spec_dir.exists():
            for path in sorted(self.spec_dir.glob("*.json")):
                try:
                    specs.append(self.get_spec(path.stem))
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    errors.append({"path": str(path), "error": str(exc)})
        return {
            "schema": "neyvia.computer_use_twin_catalog.v1",
            "generatedAt": utc_now(),
            "specs": specs,
            "loadErrors": errors,
        }

    def _read_receipt(self, raw_path: str) -> dict[str, Any]:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"Computer Use receipt not found: {resolved}")
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Computer Use receipt must be a JSON object")
        return payload

    def _comparison(
        self,
        metrics: dict[str, Any],
        *,
        baseline: dict[str, Any] | None,
        thresholds: dict[str, Any],
        live_proof: bool,
    ) -> dict[str, Any]:
        gates: list[dict[str, Any]] = []

        def gate(name: str, passed: bool, actual: Any, expected: Any) -> None:
            gates.append(
                {
                    "name": name,
                    "pass": bool(passed),
                    "actual": actual,
                    "expected": expected,
                }
            )

        gate(
            "flow_success_rate",
            metrics["flowSuccessRate"]
            >= float(thresholds["minimumFlowSuccessRate"]),
            metrics["flowSuccessRate"],
            f">={thresholds['minimumFlowSuccessRate']}",
        )
        gate(
            "deterministic_agreement",
            metrics["deterministicAgreement"]
            >= float(thresholds["minimumDeterministicAgreement"]),
            metrics["deterministicAgreement"],
            f">={thresholds['minimumDeterministicAgreement']}",
        )
        gate(
            "compact_context",
            metrics["compactReceiptBytes"]
            <= int(thresholds["maximumCompactReceiptBytes"]),
            metrics["compactReceiptBytes"],
            f"<={thresholds['maximumCompactReceiptBytes']}",
        )
        gate(
            "structured_state",
            bool(metrics["structuredTreeOmitted"]),
            bool(metrics["structuredTreeOmitted"]),
            True,
        )
        if thresholds["requireLiveProof"]:
            gate("live_proof", live_proof, live_proof, True)

        baseline_metrics = (
            summarize_cu_receipts([baseline]) if baseline is not None else None
        )
        speedup = None
        accuracy_delta = None
        if baseline_metrics:
            baseline_p95 = float(
                baseline_metrics.get("latency", {}).get("p95Ms") or 0.0
            )
            candidate_p95 = float(metrics["latency"].get("p95Ms") or 0.0)
            if baseline_p95 > 0 and candidate_p95 > 0:
                speedup = round(baseline_p95 / candidate_p95, 4)
                gate(
                    "latency_vs_baseline",
                    candidate_p95
                    <= baseline_p95
                    * float(thresholds["maximumLatencyRatio"]),
                    candidate_p95,
                    (
                        f"<={round(baseline_p95 * float(thresholds['maximumLatencyRatio']), 3)}"
                    ),
                )
            accuracy_delta = round(
                metrics["flowSuccessRate"]
                - baseline_metrics["flowSuccessRate"],
                6,
            )
            gate(
                "accuracy_vs_baseline",
                accuracy_delta >= 0,
                metrics["flowSuccessRate"],
                f">={baseline_metrics['flowSuccessRate']}",
            )
        return {
            "baselineAvailable": baseline_metrics is not None,
            "baselineMetrics": baseline_metrics,
            "latencySpeedup": speedup,
            "accuracyDelta": accuracy_delta,
            "gates": gates,
            "pass": bool(gates) and all(item["pass"] for item in gates),
            "claimPolicy": (
                "Faster and more accurate may be claimed only when a live candidate "
                "passes and a retained live baseline is available."
            ),
            "comparativeClaimAllowed": bool(
                baseline_metrics is not None
                and live_proof
                and all(item["pass"] for item in gates)
            ),
        }

    @checked_action(check_twin_run)
    def run(self, spec_id: str) -> dict[str, Any]:
        spec = self.get_spec(spec_id)
        started_at = utc_now()
        started = time.perf_counter()
        receipts: list[dict[str, Any]] = []
        evidence_mode = "live"
        if spec["mode"] == "replay":
            receipts = [self._read_receipt(spec["replayReceiptPath"])]
            evidence_mode = "replay"
        else:
            for _ in range(spec["repetitions"]):
                receipts.append(
                    run_suite(
                        base_url=spec["baseUrl"] or None,
                        flows=spec["flows"],
                        root=self.root,
                    )
                )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metrics = summarize_cu_receipts(receipts)
        metrics["twinWallClockMs"] = round(elapsed_ms, 3)
        baseline = (
            self._read_receipt(spec["baselineReceiptPath"])
            if spec["baselineReceiptPath"]
            else None
        )
        live_proof = (
            evidence_mode == "live"
            and metrics["liveReceiptCount"] == len(receipts)
            and bool(receipts)
        )
        comparison = self._comparison(
            metrics,
            baseline=baseline,
            thresholds=spec["thresholds"],
            live_proof=live_proof,
        )
        run_id = f"cutwinrun_{uuid.uuid4().hex[:16]}"
        payload = {
            "schema": CU_TWIN_RUN_SCHEMA,
            "runId": run_id,
            "specId": spec["specId"],
            "specHash": canonical_hash(spec),
            "status": "passed" if comparison["pass"] else "failed",
            "evidenceMode": evidence_mode,
            "liveProof": live_proof,
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "metrics": metrics,
            "comparison": comparison,
            "receipts": [
                {
                    "status": item.get("status"),
                    "pass": bool(item.get("pass")),
                    "baseUrl": item.get("baseUrl"),
                    "receiptPath": item.get("receiptPath"),
                    "durationMs": item.get("durationMs"),
                    "summary": item.get("summary"),
                    "results": [
                        {
                            "flow": result.get("flow"),
                            "status": result.get("status"),
                            "pass": bool(result.get("pass")),
                            "skipped": bool(result.get("skipped")),
                            "reason": str(result.get("reason") or ""),
                        }
                        for result in item.get("results", [])
                        if isinstance(result, dict)
                    ],
                }
                for item in receipts
            ],
            "treeOmitted": True,
        }
        path = self.run_dir / f"{run_id}.json"
        _atomic_json(path, payload)
        payload["receiptPath"] = str(path)
        return payload

    @checked_action(check_dispatch)
    def dispatch(
        self,
        spec_id: str,
        *,
        preferred_host: str = "",
        assign_now: bool = False,
    ) -> dict[str, Any]:
        spec = self.get_spec(spec_id)
        from .cluster import ClusterRegistry

        registry = ClusterRegistry(self.root)
        job_id = f"cutwin_{spec['specId']}_{uuid.uuid4().hex[:8]}"
        baseline_receipt = (
            self._read_receipt(spec["baselineReceiptPath"])
            if spec["baselineReceiptPath"]
            else None
        )
        replay_receipt = (
            self._read_receipt(spec["replayReceiptPath"])
            if spec["replayReceiptPath"]
            else None
        )
        portable_bytes = len(
            json.dumps(
                {
                    "spec": spec,
                    "baselineReceipt": baseline_receipt,
                    "replayReceipt": replay_receipt,
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
        if portable_bytes > 2_000_000:
            raise ValueError(
                "Portable Computer Use Twin payload exceeds the 2 MB worker limit"
            )
        job = registry.upsert_job(
            job_id=job_id,
            mission_id=spec["specId"],
            workspace_id="neyvia",
            lane_role="computer-use-verifier",
            runtime_id="python",
            job_kind="browser_verify",
            preferred_host=preferred_host,
            required_capabilities=["browser.verify", "computer.use.isolated"],
            required_artifacts=["computer_use_twin_receipt"],
            payload={
                "runner": "computer_use_twin",
                "twinSpec": spec,
                "baselineReceipt": baseline_receipt,
                "replayReceipt": replay_receipt,
                "executionRoot": ".",
                "timeoutSeconds": 3600,
                "allowNasFallback": False,
                "evidenceMode": spec["mode"],
            },
            status="queued",
            status_detail=(
                "Computer Use Twin is queued for an isolated browser-capable worker."
            ),
        )
        assignment = None
        if assign_now:
            assignment = registry.assign_job(
                job_id,
                preferred_host=preferred_host,
                allow_remote=True,
                allow_nas_fallback=False,
            )
        return {
            "schema": CU_TWIN_DISPATCH_SCHEMA,
            "status": "assigned" if assignment and assignment.get("ok") else "queued",
            "job": job,
            "assignment": assignment,
            "requiredCapabilities": ["browser.verify", "computer.use.isolated"],
            "nasExecutionAllowed": False,
            "portablePayloadBytes": portable_bytes,
        }


@checked_action(check_worker)
def execute_cluster_twin_job(
    payload: dict[str, Any],
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Execute the portable cluster payload without controller-local paths."""

    service = ComputerUseTwinService(root)
    spec = payload.get("twinSpec")
    if not isinstance(spec, dict):
        return {
            "status": "blocked",
            "detail": "Computer Use Twin worker payload has no twinSpec.",
            "returnCode": -1,
            "stdout": "",
            "stderr": "",
            "changedFiles": [],
            "artifacts": [],
        }
    portable_dir = (
        service.base_dir
        / "portable"
        / f"{spec.get('specId') or uuid.uuid4().hex[:12]}"
    )
    portable_dir.mkdir(parents=True, exist_ok=True)
    portable_spec = dict(spec)
    for payload_key, spec_key, filename in (
        ("baselineReceipt", "baselineReceiptPath", "baseline.json"),
        ("replayReceipt", "replayReceiptPath", "replay.json"),
    ):
        receipt = payload.get(payload_key)
        if isinstance(receipt, dict):
            receipt_path = portable_dir / filename
            _atomic_json(receipt_path, receipt)
            portable_spec[spec_key] = str(receipt_path)
        elif portable_spec.get(spec_key):
            return {
                "status": "blocked",
                "detail": (
                    f"Portable Twin omitted {payload_key}; controller-local paths "
                    "cannot be used on another worker."
                ),
                "returnCode": -1,
                "stdout": "",
                "stderr": "",
                "changedFiles": [],
                "artifacts": [],
            }
    saved = service.save_spec(portable_spec, approved=True)
    if not saved.get("ok"):
        return {
            "status": "blocked",
            "detail": "Portable Computer Use Twin spec was invalid.",
            "returnCode": -1,
            "stdout": json.dumps(saved, ensure_ascii=True)[-4000:],
            "stderr": "",
            "changedFiles": [],
            "artifacts": [],
        }
    result = service.run(saved["spec"]["specId"])
    passed = result.get("status") == "passed"
    return {
        "status": "completed" if passed else "failed",
        "detail": (
            "Computer Use Twin passed on the isolated worker."
            if passed
            else "Computer Use Twin failed one or more comparison gates."
        ),
        "returnCode": 0 if passed else 1,
        "stdout": json.dumps(
            {
                "runId": result.get("runId"),
                "status": result.get("status"),
                "metrics": result.get("metrics"),
                "comparison": result.get("comparison"),
            },
            ensure_ascii=True,
        )[-4000:],
        "stderr": "",
        "changedFiles": [],
        "phaseEvents": [
            {
                "kind": "computer_use_twin.completed",
                "message": (
                    "Structured Computer Use comparison completed on a worker."
                ),
                "payload": {
                    "runId": result.get("runId"),
                    "status": result.get("status"),
                    "liveProof": result.get("liveProof"),
                },
            }
        ],
        "artifacts": [
            {
                "kind": "computer_use_twin_receipt",
                "path": result.get("receiptPath"),
                "metadata": {
                    "runId": result.get("runId"),
                    "liveProof": result.get("liveProof"),
                },
            }
        ],
        "computerUseTwin": result,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a saved N-E-Y-V-I-A Computer Use Twin spec."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--root", default=".")
    run.add_argument("--spec-id", required=True)
    run.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = ComputerUseTwinService(Path(args.root))
    result = service.run(args.spec_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        print(
            f"Computer Use Twin {result['status']}: "
            f"{result['metrics']['flowSuccessRate']:.0%} flow success; "
            f"receipt={result['receiptPath']}"
        )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
