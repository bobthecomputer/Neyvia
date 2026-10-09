"""Deterministic OCR evaluation and routing primitives.

The OCR stack is selected from measured document behavior, not from a single
upstream leaderboard.  This module intentionally has no ML dependencies so it
can score candidate outputs on any Neyvia worker.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


OCR_BENCHMARK_SCHEMA = "neyvia.ocr_benchmark.v1"
OCR_CANDIDATE_REGISTRY_SCHEMA = "neyvia.ocr_model_candidates.v1"
OCR_ROUTE_SCHEMA = "neyvia.ocr_route.v1"
OCR_BENCHMARK_MANIFEST_SCHEMA = "neyvia.ocr_benchmark_manifest.v2"
OCR_BENCHMARK_RUN_SCHEMA = "neyvia.ocr_benchmark_run.v2"
OCR_OBSERVATION_STATES = frozenset({"measured", "unproven", "missing-model"})
OCR_CONTENT_TAGS = frozenset({"printed-text", "table", "math", "handwriting"})
OCR_LAYOUT_TAGS = frozenset(
    {"single-column", "multi-column", "structured", "photographed", "distorted"}
)
MAX_OCR_BOUND_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_OCR_RUN_BOUND_BYTES = 512 * 1024 * 1024
MAX_OCR_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_OCR_MODELS = 32
MAX_OCR_CASES = 1000
MAX_OCR_OBSERVATIONS = 5000
MAX_OCR_STRING_CHARACTERS = 4096
OCR_COLLECTOR_EVIDENCE_SCHEMA = "neyvia.ocr_benchmark_collector_evidence.v1"


def normalize_ocr_text(value: object) -> str:
    """Normalize Unicode and whitespace without destroying punctuation."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, ref_value in enumerate(reference, start=1):
        current = [row]
        for column, hyp_value in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_value != hyp_value),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: object, hypothesis: object) -> float:
    expected = normalize_ocr_text(reference)
    actual = normalize_ocr_text(hypothesis)
    value = _edit_distance(expected, actual) / max(1, len(expected))
    from .proofs_d_ui_planning import check_ocr_metric
    check_ocr_metric(expected, actual, value)
    return value


def word_error_rate(reference: object, hypothesis: object) -> float:
    expected = normalize_ocr_text(reference).split()
    actual = normalize_ocr_text(hypothesis).split()
    value = _edit_distance(expected, actual) / max(1, len(expected))
    from .proofs_d_ui_planning import check_ocr_metric
    check_ocr_metric(expected, actual, value)
    return value


def _token_coverage_rates(reference: object, hypothesis: object) -> tuple[float, float]:
    expected = Counter(normalize_ocr_text(reference).split())
    actual = Counter(normalize_ocr_text(hypothesis).split())
    matched = sum((expected & actual).values())
    omitted = max(0, sum(expected.values()) - matched)
    hallucinated = max(0, sum(actual.values()) - matched)
    return (
        omitted / max(1, sum(expected.values())),
        hallucinated / max(1, sum(actual.values())),
    )


def _normalized_formula(value: object) -> str:
    return re.sub(r"\s+", "", normalize_ocr_text(value))


def _inversion_rate(reference: Sequence[str], hypothesis: Sequence[str]) -> float:
    expected = {value: index for index, value in enumerate(reference)}
    observed = [expected[value] for value in hypothesis if value in expected]
    if len(observed) < 2:
        return 0.0 if list(reference) == list(hypothesis) else 1.0
    inversions = sum(
        1
        for left in range(len(observed))
        for right in range(left + 1, len(observed))
        if observed[left] > observed[right]
    )
    return inversions / (len(observed) * (len(observed) - 1) / 2)


def score_ocr_sample(
    *,
    reference_text: object,
    hypothesis_text: object,
    reference_order: Iterable[object] = (),
    hypothesis_order: Iterable[object] = (),
    reference_blocks: int | None = None,
    hypothesis_blocks: int | None = None,
    latency_ms: float | None = None,
    peak_vram_mb: float | None = None,
    reference_table_cells: int | None = None,
    hypothesis_table_cells: int | None = None,
    reference_formula: object | None = None,
    hypothesis_formula: object | None = None,
) -> dict[str, Any]:
    expected = normalize_ocr_text(reference_text)
    actual = normalize_ocr_text(hypothesis_text)
    ref_order = [str(item) for item in reference_order]
    hyp_order = [str(item) for item in hypothesis_order]
    block_error = None
    if reference_blocks is not None and hypothesis_blocks is not None:
        block_error = abs(reference_blocks - hypothesis_blocks) / max(
            1, reference_blocks
        )
    table_cell_error = None
    if reference_table_cells is not None and hypothesis_table_cells is not None:
        table_cell_error = abs(reference_table_cells - hypothesis_table_cells) / max(
            1, reference_table_cells
        )
    formula_exact = None
    if reference_formula is not None and hypothesis_formula is not None:
        formula_exact = _normalized_formula(reference_formula) == _normalized_formula(
            hypothesis_formula
        )
    omission_rate, hallucination_rate = _token_coverage_rates(expected, actual)
    return {
        "schema": OCR_BENCHMARK_SCHEMA,
        "exact": expected == actual,
        "characterErrorRate": round(character_error_rate(expected, actual), 8),
        "wordErrorRate": round(word_error_rate(expected, actual), 8),
        "readingOrderErrorRate": round(
            _inversion_rate(ref_order, hyp_order), 8
        )
        if ref_order or hyp_order
        else None,
        "blockCountErrorRate": round(block_error, 8)
        if block_error is not None
        else None,
        "tableCellCountErrorRate": round(table_cell_error, 8)
        if table_cell_error is not None
        else None,
        "formulaNormalizedExact": formula_exact,
        "omissionRate": round(omission_rate, 8),
        "hallucinationRate": round(hallucination_rate, 8),
        "referenceCharacters": len(expected),
        "hypothesisCharacters": len(actual),
        "latencyMs": round(float(latency_ms), 3)
        if latency_ms is not None
        else None,
        "peakVramMb": round(float(peak_vram_mb), 3)
        if peak_vram_mb is not None
        else None,
    }


def aggregate_scores(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(samples)
    if not rows:
        raise ValueError("At least one OCR benchmark sample is required")

    def average(key: str) -> float | None:
        values = [
            float(row[key])
            for row in rows
            if row.get(key) is not None
        ]
        return round(sum(values) / len(values), 8) if values else None

    result = {
        "schema": OCR_BENCHMARK_SCHEMA,
        "samples": len(rows),
        "exactRate": round(
            sum(bool(row.get("exact")) for row in rows) / len(rows), 8
        ),
        "meanCharacterErrorRate": average("characterErrorRate"),
        "meanWordErrorRate": average("wordErrorRate"),
        "meanReadingOrderErrorRate": average("readingOrderErrorRate"),
        "meanBlockCountErrorRate": average("blockCountErrorRate"),
        "meanTableCellCountErrorRate": average("tableCellCountErrorRate"),
        "formulaNormalizedExactRate": average("formulaNormalizedExact"),
        "meanOmissionRate": average("omissionRate"),
        "meanHallucinationRate": average("hallucinationRate"),
        "meanLatencyMs": average("latencyMs"),
        "peakVramMb": max(
            (
                float(row["peakVramMb"])
                for row in rows
                if row.get("peakVramMb") is not None
            ),
            default=None,
        ),
    }
    from .proofs_d_ui_planning import check_ocr_aggregate
    check_ocr_aggregate(rows, result)
    return result


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must be a non-empty string")
    if len(normalized) > MAX_OCR_STRING_CHARACTERS:
        raise ValueError(
            f"{label} exceeds {MAX_OCR_STRING_CHARACTERS} characters"
        )
    return normalized


def _validate_sha256(value: object, label: str) -> None:
    if value is not None and (
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value)
    ):
        raise ValueError(f"{label} must be a 64-character SHA-256")


def _reject_unknown_fields(
    payload: dict[str, Any], allowed: set[str], label: str
) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _canonical_object_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_benchmark_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the v2 evidence contract without claiming a benchmark ran."""

    try:
        manifest_size = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("OCR benchmark manifest must be finite JSON data") from exc
    if manifest_size > MAX_OCR_MANIFEST_BYTES:
        raise ValueError(f"OCR benchmark manifest exceeds {MAX_OCR_MANIFEST_BYTES} bytes")
    if payload.get("schema") != OCR_BENCHMARK_MANIFEST_SCHEMA:
        raise ValueError("Unsupported OCR benchmark manifest schema")
    _reject_unknown_fields(
        payload,
        {"schema", "benchmarkId", "description", "evidence", "models", "cases", "observations"},
        "manifest",
    )
    _require_non_empty_string(payload.get("benchmarkId"), "benchmarkId")
    models = payload.get("models")
    cases = payload.get("cases")
    observations = payload.get("observations")
    if not isinstance(models, list) or not models:
        raise ValueError("models must be a non-empty array")
    if len(models) > MAX_OCR_MODELS:
        raise ValueError(f"models exceeds {MAX_OCR_MODELS} entries")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty array")
    if len(cases) > MAX_OCR_CASES:
        raise ValueError(f"cases exceeds {MAX_OCR_CASES} entries")
    if not isinstance(observations, list) or not observations:
        raise ValueError("observations must be a non-empty array")
    if len(observations) > MAX_OCR_OBSERVATIONS:
        raise ValueError(f"observations exceeds {MAX_OCR_OBSERVATIONS} entries")

    model_ids: set[str] = set()
    model_availability: dict[str, str] = {}
    model_engines: dict[str, set[str]] = {}
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError(f"models[{index}] must be an object")
        _reject_unknown_fields(
            model,
            {
                "candidateId",
                "availability",
                "identity",
                "engineIds",
                "quantization",
                "cache",
            },
            f"models[{index}]",
        )
        model_id = _require_non_empty_string(
            model.get("candidateId"), f"models[{index}].candidateId"
        )
        if model_id in model_ids:
            raise ValueError(f"Duplicate candidateId: {model_id}")
        model_ids.add(model_id)
        availability = model.get("availability")
        if availability not in {"installed", "missing-model", "unproven"}:
            raise ValueError(
                f"models[{index}].availability must be installed, missing-model, or unproven"
            )
        model_availability[model_id] = availability
        identity = model.get("identity")
        if not isinstance(identity, dict):
            raise ValueError(f"models[{index}].identity must be an object")
        _reject_unknown_fields(
            identity,
            {
                "source",
                "revision",
                "digest",
                "weightsSha256",
                "registry",
                "toolLock",
            },
            f"models[{index}].identity",
        )
        identity_source = _require_non_empty_string(
            identity.get("source"), f"models[{index}].identity.source"
        )
        for key in ("revision", "digest", "weightsSha256"):
            if key.endswith("Sha256"):
                _validate_sha256(identity.get(key), f"models[{index}].identity.{key}")
            elif identity.get(key) is not None:
                _require_non_empty_string(
                    identity.get(key), f"models[{index}].identity.{key}"
                )
        engine_ids = model.get("engineIds")
        if availability == "installed":
            revision = _require_non_empty_string(
                identity.get("revision"), f"models[{index}].identity.revision"
            )
            pinned_revision = bool(
                re.fullmatch(r"[0-9a-fA-F]{7,64}", revision)
                or re.fullmatch(r"v?\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?", revision)
            )
            if not pinned_revision:
                raise ValueError(
                    f"models[{index}] installed model revision is a placeholder"
                )
            if not identity_source.startswith(("https://", "http://")) or any(
                marker in identity_source.lower()
                for marker in ("example.", "placeholder", "localhost")
            ):
                raise ValueError(
                    f"models[{index}] installed model source is a placeholder"
                )
            if identity.get("weightsSha256") is None:
                raise ValueError(
                    f"models[{index}] installed model requires weightsSha256"
                )
            _validate_sha256(
                identity["weightsSha256"],
                f"models[{index}].identity.weightsSha256",
            )
            for anchor_name in ("registry", "toolLock"):
                anchor = identity.get(anchor_name)
                if not isinstance(anchor, dict):
                    raise ValueError(
                        f"models[{index}].identity.{anchor_name} is required"
                    )
                allowed_anchor = {"path", "canonicalSha256", "entrySha256"}
                if anchor_name == "toolLock":
                    allowed_anchor.add("toolId")
                _reject_unknown_fields(
                    anchor,
                    allowed_anchor,
                    f"models[{index}].identity.{anchor_name}",
                )
                _require_non_empty_string(
                    anchor.get("path"),
                    f"models[{index}].identity.{anchor_name}.path",
                )
                expected_anchor_path = (
                    "config/ocr_model_candidates.json"
                    if anchor_name == "registry"
                    else "config/tool_suite_lock.json"
                )
                if anchor["path"].replace("\\", "/") != expected_anchor_path:
                    raise ValueError(
                        f"models[{index}].identity.{anchor_name}.path must bind "
                        f"{expected_anchor_path}"
                    )
                for digest_key in ("canonicalSha256", "entrySha256"):
                    if anchor.get(digest_key) is None:
                        raise ValueError(
                            f"models[{index}].identity.{anchor_name}.{digest_key} "
                            "is required"
                        )
                    _validate_sha256(
                        anchor[digest_key],
                        f"models[{index}].identity.{anchor_name}.{digest_key}",
                    )
                if anchor_name == "toolLock":
                    _require_non_empty_string(
                        anchor.get("toolId"),
                        f"models[{index}].identity.toolLock.toolId",
                    )
            if not isinstance(engine_ids, list) or not engine_ids or not all(
                isinstance(item, str) and item.strip() for item in engine_ids
            ):
                raise ValueError(
                    f"models[{index}].engineIds must bind installed model engines"
                )
        elif engine_ids is not None and (
            not isinstance(engine_ids, list)
            or not all(isinstance(item, str) and item.strip() for item in engine_ids)
        ):
            raise ValueError(f"models[{index}].engineIds must be a string array")
        model_engines[model_id] = set(engine_ids or [])
        for metadata_key in ("quantization", "cache"):
            if not isinstance(model.get(metadata_key), dict):
                raise ValueError(f"models[{index}].{metadata_key} must be an object")
            _require_non_empty_string(
                model[metadata_key].get("provenance"),
                f"models[{index}].{metadata_key}.provenance",
            )
        _reject_unknown_fields(
            model["quantization"],
            {"format", "precision", "provenance"},
            f"models[{index}].quantization",
        )
        _reject_unknown_fields(
            model["cache"],
            {"state", "treeSha256", "provenance"},
            f"models[{index}].cache",
        )
        if model["cache"].get("state") not in {"present", "missing", "unproven"}:
            raise ValueError(f"models[{index}].cache.state is unsupported")
        _validate_sha256(
            model["cache"].get("treeSha256"),
            f"models[{index}].cache.treeSha256",
        )

    case_ids: set[str] = set()
    cases_by_id: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be an object")
        _reject_unknown_fields(case, {"caseId", "source", "tags"}, f"cases[{index}]")
        case_id = _require_non_empty_string(case.get("caseId"), f"cases[{index}].caseId")
        if case_id in case_ids:
            raise ValueError(f"Duplicate caseId: {case_id}")
        case_ids.add(case_id)
        cases_by_id[case_id] = case
        tags = case.get("tags")
        if not isinstance(tags, dict):
            raise ValueError(f"cases[{index}].tags must be an object")
        _reject_unknown_fields(
            tags,
            {"languages", "layout", "content", "handwriting"},
            f"cases[{index}].tags",
        )
        languages = tags.get("languages")
        layout = tags.get("layout")
        content = tags.get("content")
        if not isinstance(languages, list) or not languages or not all(
            isinstance(item, str) and item.strip() for item in languages
        ):
            raise ValueError(f"cases[{index}].tags.languages must be non-empty")
        if not isinstance(layout, list) or not set(layout).issubset(OCR_LAYOUT_TAGS):
            raise ValueError(f"cases[{index}].tags.layout contains unsupported tags")
        if not isinstance(content, list) or not set(content).issubset(OCR_CONTENT_TAGS):
            raise ValueError(f"cases[{index}].tags.content contains unsupported tags")
        if not isinstance(tags.get("handwriting"), bool):
            raise ValueError(f"cases[{index}].tags.handwriting must be boolean")
        source = case.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"cases[{index}].source must be an object")
        _reject_unknown_fields(
            source, {"path", "sha256"}, f"cases[{index}].source"
        )
        _require_non_empty_string(source.get("path"), f"cases[{index}].source.path")
        _validate_sha256(source.get("sha256"), f"cases[{index}].source.sha256")

    observation_keys: set[tuple[str, str]] = set()
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"observations[{index}] must be an object")
        _reject_unknown_fields(
            observation,
            {
                "candidateId",
                "caseId",
                "state",
                "reason",
                "artifacts",
                "route",
                "performance",
            },
            f"observations[{index}]",
        )
        model_id = _require_non_empty_string(
            observation.get("candidateId"), f"observations[{index}].candidateId"
        )
        case_id = _require_non_empty_string(
            observation.get("caseId"), f"observations[{index}].caseId"
        )
        if model_id not in model_ids or case_id not in case_ids:
            raise ValueError(f"observations[{index}] references an unknown model or case")
        key = (model_id, case_id)
        if key in observation_keys:
            raise ValueError(f"Duplicate observation: {model_id}/{case_id}")
        observation_keys.add(key)
        state = observation.get("state")
        if state not in OCR_OBSERVATION_STATES:
            raise ValueError(f"observations[{index}].state is unsupported")
        if state == "measured" and model_availability[model_id] != "installed":
            raise ValueError(
                f"observations[{index}] cannot measure a model that is not installed"
            )
        if state == "missing-model" and model_availability[model_id] != "missing-model":
            raise ValueError(
                f"observations[{index}] missing-model state conflicts with model availability"
            )
        if state == "measured":
            if not cases_by_id[case_id]["source"].get("sha256"):
                raise ValueError(
                    f"observations[{index}] measured case source requires sha256"
                )
            artifacts = observation.get("artifacts")
            if not isinstance(artifacts, dict):
                raise ValueError(f"observations[{index}].artifacts is required")
            _reject_unknown_fields(
                artifacts,
                {"reference", "hypothesis"},
                f"observations[{index}].artifacts",
            )
            for artifact_name in ("reference", "hypothesis"):
                artifact = artifacts.get(artifact_name)
                if not isinstance(artifact, dict):
                    raise ValueError(
                        f"observations[{index}].artifacts.{artifact_name} must be an object"
                    )
                _reject_unknown_fields(
                    artifact,
                    {"path", "sha256"},
                    f"observations[{index}].artifacts.{artifact_name}",
                )
                _require_non_empty_string(
                    artifact.get("path"),
                    f"observations[{index}].artifacts.{artifact_name}.path",
                )
                if artifact.get("sha256") is None:
                    raise ValueError(
                        f"observations[{index}].artifacts.{artifact_name}.sha256 is required"
                    )
                _validate_sha256(
                    artifact.get("sha256"),
                    f"observations[{index}].artifacts.{artifact_name}.sha256",
                )
            route = observation.get("route")
            if not isinstance(route, dict):
                raise ValueError(f"observations[{index}].route is required")
            _reject_unknown_fields(
                route,
                {"selectedEngine", "automatic", "reason", "signals"},
                f"observations[{index}].route",
            )
            _require_non_empty_string(
                route.get("selectedEngine"),
                f"observations[{index}].route.selectedEngine",
            )
            if route["selectedEngine"] not in model_engines[model_id]:
                raise ValueError(
                    f"observations[{index}].route.selectedEngine is not bound "
                    f"to candidateId {model_id}"
                )
            _require_non_empty_string(
                route.get("reason"), f"observations[{index}].route.reason"
            )
            if not isinstance(route.get("automatic"), bool) or not isinstance(
                route.get("signals"), dict
            ):
                raise ValueError(
                    f"observations[{index}].route requires automatic and signals"
                )
            allowed_signals = {
                "nativeTextCharacters",
                "requiresLayout",
                "containsTable",
                "containsFormula",
                "containsChart",
                "containsHandwriting",
                "distortedOrPhotographed",
                "preferFastFullPage",
                "requestedEngine",
                "gpuAvailable",
            }
            _reject_unknown_fields(
                route["signals"],
                allowed_signals,
                f"observations[{index}].route.signals",
            )
            for signal_name, signal_value in route["signals"].items():
                if signal_name == "nativeTextCharacters":
                    if (
                        not isinstance(signal_value, int)
                        or isinstance(signal_value, bool)
                        or signal_value < 0
                    ):
                        raise ValueError(
                            f"observations[{index}].route.signals."
                            "nativeTextCharacters must be non-negative integer"
                        )
                elif signal_name == "requestedEngine":
                    _require_non_empty_string(
                        signal_value,
                        f"observations[{index}].route.signals.requestedEngine",
                    )
                elif not isinstance(signal_value, bool):
                    raise ValueError(
                        f"observations[{index}].route.signals.{signal_name} "
                        "must be boolean"
                    )
            performance = observation.get("performance")
            if not isinstance(performance, dict):
                raise ValueError(f"observations[{index}].performance is required")
            _reject_unknown_fields(
                performance,
                {
                    "startupMs",
                    "latencyMs",
                    "peakMemoryMb",
                    "pagesPerSecond",
                    "temperature",
                    "cacheMode",
                    "measurementProvenance",
                },
                f"observations[{index}].performance",
            )
            for metric in ("startupMs", "latencyMs", "peakMemoryMb", "pagesPerSecond"):
                value = performance.get(metric)
                if value is not None and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(
                        f"observations[{index}].performance.{metric} must be non-negative"
                    )
            if performance.get("temperature") != 0:
                raise ValueError(
                    f"observations[{index}].performance.temperature must be zero"
                )
            if performance.get("cacheMode") not in {"cold", "warm", "unknown"}:
                raise ValueError(
                    f"observations[{index}].performance.cacheMode is unsupported"
                )
            provenance = performance.get("measurementProvenance")
            if not isinstance(provenance, dict):
                raise ValueError(
                    f"observations[{index}].performance.measurementProvenance is required"
                )
            _reject_unknown_fields(
                provenance,
                {"classification", "source", "method", "collector", "evidence"},
                f"observations[{index}].performance.measurementProvenance",
            )
            if provenance.get("classification") != "self-declared":
                raise ValueError(
                    f"observations[{index}].performance.measurementProvenance."
                    "classification must be self-declared"
                )
            _require_non_empty_string(
                provenance.get("source"),
                f"observations[{index}].performance.measurementProvenance.source",
            )
            _require_non_empty_string(
                provenance.get("method"),
                f"observations[{index}].performance.measurementProvenance.method",
            )
            collector = provenance.get("collector")
            if not isinstance(collector, dict):
                raise ValueError(
                    f"observations[{index}].performance.measurementProvenance."
                    "collector is required"
                )
            _reject_unknown_fields(
                collector,
                {"name", "version"},
                f"observations[{index}].performance.measurementProvenance.collector",
            )
            _require_non_empty_string(
                collector.get("name"),
                f"observations[{index}].performance.measurementProvenance.collector.name",
            )
            _require_non_empty_string(
                collector.get("version"),
                f"observations[{index}].performance.measurementProvenance.collector.version",
            )
            collector_evidence = provenance.get("evidence")
            if not isinstance(collector_evidence, dict):
                raise ValueError(
                    f"observations[{index}].performance.measurementProvenance."
                    "evidence is required"
                )
            _reject_unknown_fields(
                collector_evidence,
                {"path", "sha256"},
                f"observations[{index}].performance.measurementProvenance.evidence",
            )
            _require_non_empty_string(
                collector_evidence.get("path"),
                f"observations[{index}].performance.measurementProvenance.evidence.path",
            )
            if collector_evidence.get("sha256") is None:
                raise ValueError(
                    f"observations[{index}].performance.measurementProvenance."
                    "evidence.sha256 is required"
                )
            _validate_sha256(
                collector_evidence.get("sha256"),
                f"observations[{index}].performance.measurementProvenance.evidence.sha256",
            )
        else:
            _require_non_empty_string(
                observation.get("reason"), f"observations[{index}].reason"
            )
    return payload


def evaluate_benchmark_manifest(
    payload: dict[str, Any], *, base_path: str | Path
) -> dict[str, Any]:
    """Evaluate measured rows and preserve non-results as explicit states."""

    validate_benchmark_manifest(payload)
    root = Path(base_path).resolve()
    cases_by_id = {case["caseId"]: case for case in payload["cases"]}
    models_by_id = {model["candidateId"]: model for model in payload["models"]}
    rows: list[dict[str, Any]] = []
    measured_scores: list[dict[str, Any]] = []
    measured_performance: list[dict[str, Any]] = []
    path_digests: dict[Path, tuple[str, str]] = {}
    verified_model_ids: set[str] = set()
    total_bound_bytes = 0

    def artifact_path(relative_path: str) -> Path:
        resolved = (root / relative_path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("OCR artifacts must remain inside the manifest directory") from exc
        return resolved

    def read_file_bytes(path: Path, label: str) -> bytes:
        nonlocal total_bound_bytes
        if not path.is_file():
            raise FileNotFoundError(f"Missing bound OCR {label}: {path}")
        with path.open("rb") as handle:
            data = handle.read(MAX_OCR_BOUND_ARTIFACT_BYTES + 1)
        if len(data) > MAX_OCR_BOUND_ARTIFACT_BYTES:
            raise ValueError(f"OCR {label} exceeds {MAX_OCR_BOUND_ARTIFACT_BYTES} bytes")
        if total_bound_bytes + len(data) > MAX_OCR_RUN_BOUND_BYTES:
            raise ValueError(
                f"OCR run bound artifacts exceed {MAX_OCR_RUN_BOUND_BYTES} bytes"
            )
        total_bound_bytes += len(data)
        return data

    def read_bound_bytes(path: Path, expected_sha256: str, label: str) -> bytes:
        data = read_file_bytes(path, label)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            raise ValueError(
                f"OCR {label} SHA-256 mismatch: expected "
                f"{expected_sha256.lower()}, got {actual_sha256}"
            )
        previous = path_digests.get(path)
        binding = ("raw", actual_sha256)
        if previous is not None and previous != binding:
            raise ValueError(f"OCR {label} conflicts with an existing path binding")
        path_digests[path] = binding
        return data

    def parse_json_bytes(data: bytes, label: str) -> Any:
        try:
            return json.loads(
                data.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant {value}")
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"OCR {label} must be strict UTF-8 JSON") from exc

    def verify_model_identity(model: dict[str, Any]) -> None:
        candidate_id = model["candidateId"]
        if candidate_id in verified_model_ids:
            return
        identity = model["identity"]
        registry_binding = identity["registry"]
        tool_lock_binding = identity["toolLock"]
        registry_path = artifact_path(registry_binding["path"])
        tool_lock_path = artifact_path(tool_lock_binding["path"])
        registry = parse_json_bytes(
            read_file_bytes(registry_path, "candidate registry"),
            "candidate registry",
        )
        if not isinstance(registry, dict):
            raise ValueError("OCR candidate registry must be a JSON object")
        registry_canonical = _canonical_object_sha256(registry)
        if registry_canonical != registry_binding["canonicalSha256"]:
            raise ValueError("OCR candidate registry canonical SHA-256 mismatch")
        path_digests[registry_path] = ("canonical-json", registry_canonical)
        if not isinstance(registry.get("candidates"), list):
            raise ValueError("OCR candidate registry has an invalid structure")
        candidate = next(
            (
                item
                for item in registry["candidates"]
                if isinstance(item, dict) and item.get("candidateId") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError(f"OCR candidate registry lacks {candidate_id}")
        if _canonical_object_sha256(candidate) != registry_binding["entrySha256"]:
            raise ValueError("OCR candidate registry entry SHA-256 mismatch")
        if (
            candidate.get("source") != identity["source"]
            or candidate.get("revision") != identity["revision"]
            or candidate.get("localModelWeightsSha256") != identity["weightsSha256"]
        ):
            raise ValueError("OCR candidate registry identity relation mismatch")
        del candidate
        del registry
        tool_lock = parse_json_bytes(
            read_file_bytes(tool_lock_path, "tool lock"),
            "tool lock",
        )
        if not isinstance(tool_lock, dict):
            raise ValueError("OCR tool lock must be a JSON object")
        tool_lock_canonical = _canonical_object_sha256(tool_lock)
        if tool_lock_canonical != tool_lock_binding["canonicalSha256"]:
            raise ValueError("OCR tool lock canonical SHA-256 mismatch")
        path_digests[tool_lock_path] = ("canonical-json", tool_lock_canonical)
        if not isinstance(tool_lock, dict) or not isinstance(tool_lock.get("tools"), list):
            raise ValueError("OCR tool lock has an invalid structure")
        tool_entry = next(
            (
                item
                for item in tool_lock["tools"]
                if isinstance(item, dict)
                and item.get("toolId") == tool_lock_binding["toolId"]
            ),
            None,
        )
        if tool_entry is None:
            raise ValueError("OCR tool lock lacks the bound tool entry")
        if _canonical_object_sha256(tool_entry) != tool_lock_binding["entrySha256"]:
            raise ValueError("OCR tool lock entry SHA-256 mismatch")
        metadata = tool_entry.get("metadata")
        if not isinstance(metadata, dict) or (
            metadata.get("modelRevision") != identity["revision"]
            or metadata.get("modelWeightsSha256") != identity["weightsSha256"]
        ):
            raise ValueError("OCR tool lock identity relation mismatch")
        del metadata
        del tool_entry
        del tool_lock
        verified_model_ids.add(candidate_id)

    def strict_performance(performance: dict[str, Any]) -> dict[str, Any]:
        return {
            key: performance.get(key)
            for key in (
                "startupMs",
                "latencyMs",
                "peakMemoryMb",
                "pagesPerSecond",
                "temperature",
                "cacheMode",
            )
        }

    def validate_collector_evidence(
        evidence: Any,
        *,
        observation: dict[str, Any],
        model: dict[str, Any],
        case_source: dict[str, Any],
    ) -> None:
        if not isinstance(evidence, dict):
            raise ValueError("OCR collector evidence must be an object")
        _reject_unknown_fields(
            evidence,
            {
                "schema",
                "benchmarkId",
                "caseId",
                "sourceSha256",
                "candidateId",
                "modelIdentity",
                "referenceSha256",
                "hypothesisSha256",
                "route",
                "performance",
            },
            "collector evidence",
        )
        expected = {
            "schema": OCR_COLLECTOR_EVIDENCE_SCHEMA,
            "benchmarkId": payload["benchmarkId"],
            "caseId": observation["caseId"],
            "sourceSha256": case_source["sha256"],
            "candidateId": observation["candidateId"],
            "modelIdentity": {
                "revision": model["identity"]["revision"],
                "weightsSha256": model["identity"]["weightsSha256"],
            },
            "referenceSha256": observation["artifacts"]["reference"]["sha256"],
            "hypothesisSha256": observation["artifacts"]["hypothesis"]["sha256"],
            "route": observation["route"],
            "performance": strict_performance(observation["performance"]),
        }
        if evidence != expected:
            raise ValueError("OCR collector evidence relation mismatch")

    def validate_content_artifact(value: dict[str, Any], label: str) -> None:
        _reject_unknown_fields(
            value,
            {"text", "order", "blockCount", "tableCellCount", "formula"},
            label,
        )
        if not isinstance(value.get("text"), str) or not normalize_ocr_text(
            value["text"]
        ):
            raise ValueError(f"Measured OCR {label} text must be non-empty")
        order = value.get("order")
        if order is not None and (
            not isinstance(order, list)
            or not all(isinstance(item, str) for item in order)
        ):
            raise ValueError(f"Measured OCR {label} order must be a string array")
        for count_key in ("blockCount", "tableCellCount"):
            count = value.get(count_key)
            if count is not None and (
                not isinstance(count, int) or isinstance(count, bool) or count < 0
            ):
                raise ValueError(
                    f"Measured OCR {label} {count_key} must be a non-negative integer"
                )
        if value.get("formula") is not None and not isinstance(value["formula"], str):
            raise ValueError(f"Measured OCR {label} formula must be a string")

    for observation in payload["observations"]:
        performance = observation.get("performance")
        row = {
            "candidateId": observation["candidateId"],
            "caseId": observation["caseId"],
            "state": observation["state"],
            "reason": observation.get("reason"),
            "route": observation.get("route"),
            "performance": (
                {
                    key: performance.get(key)
                    for key in (
                        "startupMs",
                        "latencyMs",
                        "peakMemoryMb",
                        "pagesPerSecond",
                        "temperature",
                        "cacheMode",
                    )
                }
                if isinstance(performance, dict)
                else None
            ),
            "performanceEvidence": None,
            "quality": None,
        }
        if observation["state"] == "measured":
            artifacts = observation["artifacts"]
            case_source = cases_by_id[observation["caseId"]]["source"]
            model = models_by_id[observation["candidateId"]]
            source_path = artifact_path(case_source["path"])
            reference_path = artifact_path(artifacts["reference"]["path"])
            hypothesis_path = artifact_path(artifacts["hypothesis"]["path"])
            provenance = observation["performance"]["measurementProvenance"]
            collector_evidence_path = artifact_path(provenance["evidence"]["path"])
            primary_paths = {
                source_path,
                reference_path,
                hypothesis_path,
                collector_evidence_path,
            }
            if len(primary_paths) != 4:
                raise ValueError(
                    "OCR case source, reference, hypothesis, and collector paths "
                    "must be distinct"
                )
            verify_model_identity(model)
            read_bound_bytes(source_path, case_source["sha256"], "case source")
            reference_bytes = read_bound_bytes(
                reference_path,
                artifacts["reference"]["sha256"],
                "reference artifact",
            )
            reference = parse_json_bytes(reference_bytes, "reference artifact")
            del reference_bytes
            hypothesis_bytes = read_bound_bytes(
                hypothesis_path,
                artifacts["hypothesis"]["sha256"],
                "hypothesis artifact",
            )
            hypothesis = parse_json_bytes(hypothesis_bytes, "hypothesis artifact")
            del hypothesis_bytes
            collector_bytes = read_bound_bytes(
                collector_evidence_path,
                provenance["evidence"]["sha256"],
                "collector evidence",
            )
            collector_evidence = parse_json_bytes(collector_bytes, "collector evidence")
            del collector_bytes
            validate_collector_evidence(
                collector_evidence,
                observation=observation,
                model=model,
                case_source=case_source,
            )
            if not isinstance(reference, dict) or not isinstance(hypothesis, dict):
                raise ValueError("OCR reference and hypothesis artifacts must be objects")
            validate_content_artifact(reference, "reference artifact")
            validate_content_artifact(hypothesis, "hypothesis artifact")
            performance = observation["performance"]
            quality = score_ocr_sample(
                reference_text=reference.get("text"),
                hypothesis_text=hypothesis.get("text"),
                reference_order=reference.get("order") or (),
                hypothesis_order=hypothesis.get("order") or (),
                reference_blocks=reference.get("blockCount"),
                hypothesis_blocks=hypothesis.get("blockCount"),
                latency_ms=performance.get("latencyMs"),
                peak_vram_mb=performance.get("peakMemoryMb"),
                reference_table_cells=reference.get("tableCellCount"),
                hypothesis_table_cells=hypothesis.get("tableCellCount"),
                reference_formula=reference.get("formula"),
                hypothesis_formula=hypothesis.get("formula"),
            )
            row["quality"] = quality
            row["performanceEvidence"] = {
                "classification": "self-declared",
                "cryptographicallyTrusted": False,
                "integrityBindingsVerified": True,
                "relationBindingsVerified": True,
                "provenance": provenance,
            }
            measured_scores.append(quality)
            measured_performance.append(performance)
        rows.append(row)
    state_counts = Counter(row["state"] for row in rows)

    def performance_summary() -> dict[str, Any] | None:
        if not measured_performance:
            return None

        def mean(key: str) -> float | None:
            values = [
                float(item[key])
                for item in measured_performance
                if item.get(key) is not None
            ]
            return round(sum(values) / len(values), 8) if values else None

        peak_values = [
            float(item["peakMemoryMb"])
            for item in measured_performance
            if item.get("peakMemoryMb") is not None
        ]
        return {
            "meanStartupMs": mean("startupMs"),
            "meanLatencyMs": mean("latencyMs"),
            "peakMemoryMb": max(peak_values) if peak_values else None,
            "meanPagesPerSecond": mean("pagesPerSecond"),
            "cacheModes": sorted(
                {
                    str(item["cacheMode"])
                    for item in measured_performance
                    if item.get("cacheMode")
                }
            ),
            "evidenceClassification": "self-declared",
            "cryptographicallyTrusted": False,
        }

    return {
        "schema": OCR_BENCHMARK_RUN_SCHEMA,
        "benchmarkId": payload["benchmarkId"],
        "models": payload["models"],
        "cases": payload["cases"],
        "observations": rows,
        "stateCounts": {
            state: state_counts.get(state, 0)
            for state in ("measured", "unproven", "missing-model")
        },
        "aggregate": aggregate_scores(measured_scores) if measured_scores else None,
        "performanceAggregate": performance_summary(),
        "claimStatus": (
            "integrity-bound-local-self-declared"
            if measured_scores
            else "unproven"
        ),
        "qualityClaimStatus": (
            "measured-integrity-only" if measured_scores else "unproven"
        ),
        "performanceClaimStatus": (
            "self-declared" if measured_scores else "unproven"
        ),
        "promotionEligible": False,
    }


@dataclass(frozen=True)
class OcrPageSignals:
    native_text_characters: int = 0
    requires_layout: bool = False
    contains_table: bool = False
    contains_formula: bool = False
    contains_chart: bool = False
    contains_handwriting: bool = False
    distorted_or_photographed: bool = False
    prefer_fast_full_page: bool = False
    requested_engine: str = ""
    gpu_available: bool = True


def _select_ocr_route(signals: OcrPageSignals) -> dict[str, Any]:
    requested = signals.requested_engine.strip().lower()
    if requested:
        allowed = {
            "native-pdf",
            "pp-ocrv6-medium",
            "glm-ocr-bf16",
            "paddleocr-vl-1.6",
            "tesseract-fallback",
        }
        if requested not in allowed:
            raise ValueError(f"Unsupported OCR engine override: {requested}")
        return {
            "schema": OCR_ROUTE_SCHEMA,
            "engine": requested,
            "reason": "The caller explicitly selected a bounded OCR engine.",
            "automatic": False,
        }
    if signals.native_text_characters >= 32:
        return {
            "schema": OCR_ROUTE_SCHEMA,
            "engine": "native-pdf",
            "reason": "The page already contains enough native text for extraction.",
            "automatic": True,
        }
    if signals.prefer_fast_full_page and signals.gpu_available:
        return {
            "schema": OCR_ROUTE_SCHEMA,
            "engine": "glm-ocr-bf16",
            "reason": (
                "Fast full-page visual recognition was requested without "
                "coordinate-level structure."
            ),
            "automatic": True,
        }
    complex_page = any(
        (
            signals.requires_layout,
            signals.contains_table,
            signals.contains_formula,
            signals.contains_chart,
            signals.contains_handwriting,
            signals.distorted_or_photographed,
        )
    )
    if complex_page and signals.gpu_available:
        return {
            "schema": OCR_ROUTE_SCHEMA,
            "engine": "paddleocr-vl-1.6",
            "reason": "Complex document structure requires the layout-aware VLM.",
            "automatic": True,
        }
    if signals.gpu_available:
        return {
            "schema": OCR_ROUTE_SCHEMA,
            "engine": "pp-ocrv6-medium",
            "reason": "A scanned text page can use the low-hallucination OCR path.",
            "automatic": True,
        }
    return {
        "schema": OCR_ROUTE_SCHEMA,
        "engine": "tesseract-fallback",
        "reason": "No healthy GPU worker is available; use the explicit CPU fallback.",
        "automatic": True,
    }


def select_ocr_route(signals: OcrPageSignals) -> dict[str, Any]:
    result = _select_ocr_route(signals)
    from .proofs_d_ui_planning import check_ocr_route
    check_ocr_route(signals, result)
    return result


def load_candidate_registry(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != OCR_CANDIDATE_REGISTRY_SCHEMA:
        raise ValueError("Unsupported OCR candidate registry schema")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("OCR candidate registry must contain candidates")
    identifiers: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("OCR candidates must be objects")
        identifier = str(candidate.get("candidateId") or "").strip().lower()
        if not identifier or identifier in identifiers:
            raise ValueError("OCR candidate identifiers must be unique and non-empty")
        identifiers.add(identifier)
        if not candidate.get("license") or not candidate.get("source"):
            raise ValueError(f"OCR candidate {identifier} lacks license/source")
    from .proofs_d_ui_planning import check_ocr_candidates
    check_ocr_candidates(payload)
    return payload
