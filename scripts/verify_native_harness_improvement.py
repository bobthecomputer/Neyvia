from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _image_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        return struct.unpack(">II", header[16:24])
    if header.startswith((b"GIF87a", b"GIF89a")) and len(header) >= 10:
        return struct.unpack("<HH", header[6:10])
    raise AssertionError(f"Proof artifact is not a supported PNG or GIF: {path.name}")


def verify(proof_dir: Path) -> dict[str, Any]:
    baseline = _read_json(proof_dir / "baseline.json")
    after = _read_json(proof_dir / "after.json")
    before_evidence = baseline.get("operatorEvidence") or {}
    after_evidence = after.get("operatorEvidence") or {}
    after_run = after.get("realRun") or {}

    _require(
        (baseline.get("nativeHarness") or {}).get("readiness") == "blocked",
        "The frozen baseline does not contain the observed blocked native readiness.",
    )
    _require(
        (after.get("nativeHarness") or {}).get("readiness") == "ready",
        "The improved proof does not show ready native readiness.",
    )
    _require(
        int(after_evidence.get("measuredSummaryFields") or 0)
        > int(before_evidence.get("measuredSummaryFields") or 0),
        "The improved surface does not expose more measured summary fields.",
    )
    _require(
        int(after_evidence.get("selectedRunTimelineMilestones") or 0)
        > int(before_evidence.get("selectedRunTimelineMilestones") or 0),
        "The selected-run time-lapse did not gain real milestones.",
    )
    _require(
        int(after_evidence.get("sampleSize") or 0) >= 1,
        "The improved metrics are not backed by a terminal run sample.",
    )
    _require(after_run.get("status") == "completed", "The real native run did not complete.")
    _require(
        str(after_run.get("model") or "").endswith("deepseek-v4-flash"),
        "The real run did not preserve the requested DeepSeek V4 Flash model.",
    )
    _require(after_run.get("providerSubstitution") is False, "The real run substituted providers.")
    for field in ("queueLatencyMs", "executionDurationMs", "totalDurationMs"):
        _require(
            isinstance(after_run.get(field), int) and int(after_run[field]) >= 0,
            f"The real run is missing measured {field}.",
        )

    artifacts = after.get("artifacts") or {}
    for key in ("beforeScreenshot", "afterScreenshot", "timelineScreenshot", "timeLapse"):
        artifact = proof_dir / str(artifacts.get(key) or "")
        _require(artifact.is_file(), f"Missing proof artifact: {key}")
        _require(artifact.stat().st_size >= 8_000, f"Proof artifact is unexpectedly small: {artifact.name}")
        width, height = _image_dimensions(artifact)
        _require(
            width >= 700 and height >= 400,
            f"Proof artifact resolution is too small: {artifact.name} ({width}x{height})",
        )

    return {
        "baselineReadiness": (baseline.get("nativeHarness") or {}).get("readiness"),
        "afterReadiness": (after.get("nativeHarness") or {}).get("readiness"),
        "summaryFieldsBefore": before_evidence.get("measuredSummaryFields"),
        "summaryFieldsAfter": after_evidence.get("measuredSummaryFields"),
        "timelineMilestonesBefore": before_evidence.get("selectedRunTimelineMilestones"),
        "timelineMilestonesAfter": after_evidence.get("selectedRunTimelineMilestones"),
        "sampleSize": after_evidence.get("sampleSize"),
        "model": after_run.get("model"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify measured Neyvia native harness improvement proof.")
    parser.add_argument("--proof-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = verify(args.proof_dir.resolve())
    print(json.dumps(summary, sort_keys=True))
    print("native harness improvement verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
