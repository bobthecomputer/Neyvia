"""Score saved OCR outputs against a small, explicit ground-truth manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grant_agent.ocr_benchmark import aggregate_scores, score_ocr_sample


def _read_payload(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    manifest = _read_payload(arguments.manifest)
    rows = manifest.get("samples")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Benchmark manifest must contain non-empty samples")
    scored = []
    for row in rows:
        reference = _read_payload(
            (arguments.manifest.parent / row["reference"]).resolve()
        )
        hypothesis = _read_payload(
            (arguments.manifest.parent / row["hypothesis"]).resolve()
        )
        score = score_ocr_sample(
            reference_text=reference.get("text"),
            hypothesis_text=hypothesis.get("text"),
            reference_order=reference.get("order") or [],
            hypothesis_order=hypothesis.get("order") or [],
            reference_blocks=reference.get("blockCount"),
            hypothesis_blocks=hypothesis.get("blockCount"),
            latency_ms=hypothesis.get("latencyMs"),
            peak_vram_mb=hypothesis.get("peakVramMb"),
        )
        score["sampleId"] = row.get("sampleId")
        score["category"] = row.get("category")
        scored.append(score)
    result = {
        "schema": "neyvia.ocr_benchmark_run.v1",
        "candidateId": manifest.get("candidateId"),
        "scores": scored,
        "aggregate": aggregate_scores(scored),
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
