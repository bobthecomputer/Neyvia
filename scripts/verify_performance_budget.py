#!/usr/bin/env python3
"""Fail-closed Neyvia performance-budget gate.

The gate measures produced Vite assets and consumes a separately recorded
runtime-evidence JSON file. Local measurements can pass their budgets, but
promotion remains ``unproven`` until a separately provisioned verifier
attestation validates. Missing or malformed evidence fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.proofs_e_sv import enforced


SCHEMA = "neyvia.performance-budget-report.v1"
RUNTIME_SCHEMA = "neyvia.runtime-performance-evidence.v1"
RECORDER_SCHEMA = "neyvia.runtime-performance-recorder.v1"
EVIDENCE_BINDING_SCHEMA = "neyvia.runtime-performance-evidence-binding.v1"
REQUIRED_RUNTIME_METRICS = (
    "bootstrapPayloadBytes",
    "startupP95Ms",
    "memoryP95MiB",
    "cpuP95Percent",
    "networkInitialBytes",
    "batteryDrainPercentPerHour",
)
REQUIRED_BUILD_METRICS = (
    "initialJavascriptBytes",
    "initialCssBytes",
    "lazyChunkMaxBytes",
)
DEFAULT_EVIDENCE_LIMITS = {
    "minStartupSamples": 3,
    "maxSamplesPerMetric": 20,
    "maxCaptureDurationSeconds": 1800,
}
MAX_FUTURE_SKEW = timedelta(minutes=5)
P95_METRICS = {"startupP95Ms", "memoryP95MiB", "cpuP95Percent"}
MAX_METRICS = {"bootstrapPayloadBytes", "networkInitialBytes", "batteryDrainPercentPerHour"}
EXPECTED_AGGREGATION = {
    **{name: "p95" for name in P95_METRICS},
    **{name: "maximum" for name in MAX_METRICS},
}
ALLOWED_METRIC_SOURCES = {
    "startupP95Ms": {"spawn-to-http-readiness-v1"},
    "bootstrapPayloadBytes": {"http-response-body-bytes-v1"},
    "memoryP95MiB": {"windows-root-process", "procfs-root-process"},
    "cpuP95Percent": {"windows-root-process", "procfs-root-process"},
    "networkInitialBytes": {"same-origin-initial-http-response-body-bytes-v1"},
    "batteryDrainPercentPerHour": {
        "external-power-meter",
        "os-battery-telemetry",
        "windows-energy-report",
    },
}
ALLOWED_REASON_CODES = {
    "BATTERY_NOT_MEASURED",
    "CAPTURE_DEADLINE_EXCEEDED",
    "HTTP_BOUND_EXCEEDED",
    "HTTP_REQUEST_FAILED",
    "MEASUREMENT_UNAVAILABLE",
    "STARTUP_ENDPOINT_STATE_INVALID",
    "STARTUP_PROCESS_EXITED",
    "STARTUP_TIMEOUT",
}


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def config_fingerprint(config: dict[str, Any]) -> str:
    return canonical_sha256(config)


def _evidence_digest(evidence: dict[str, Any]) -> str:
    payload = dict(evidence)
    payload.pop("evidenceBinding", None)
    return canonical_sha256(payload)


def _redact_diagnostic(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(
        r'''(?i)(["']?(?:token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*)(["'])(.*?)\2''',
        r"\1\2[redacted]\2",
        text,
    )
    text = re.sub(
        r'''(?i)(["']?(?:token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*)([^"',;&\s}]+)''',
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\s]*)?", "[local-path]", text)
    text = re.sub(r"(?<!:)//[^/\s]+/[^/\s]+(?:/[^\s,;]*)?", "[local-path]", text)
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\r\n,;]+", "[local-path]", text)
    text = re.sub(
        r"(?<!\w)/(?:home|users|tmp|var|volume1|mnt|workspace|opt|srv)/[^\s,;]+",
        "[local-path]",
        text,
    )
    return text[:240] or "unavailable"


def _asset_path(build_dir: Path, asset: object) -> Path | None:
    if not isinstance(asset, str) or not asset.strip():
        return None
    normalized = asset.strip().replace("\\", "/")
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    candidate = (build_dir / parsed.path.lstrip("/")).resolve()
    try:
        candidate.relative_to(build_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _required_asset_path(build_dir: Path, asset: object, *, reference: str) -> Path:
    path = _asset_path(build_dir, asset)
    if path is None:
        raise ValueError(f"Vite manifest references missing or unsafe {reference}")
    return path


def _vite_manifest_measurements(build_dir: Path, manifest: dict[str, Any]) -> tuple[dict[str, int], str]:
    entries = [item for item in manifest.values() if isinstance(item, dict) and item.get("isEntry")]
    if not entries:
        raise ValueError("Vite manifest has no isEntry record")
    initial_js: set[Path] = set()
    initial_css: set[Path] = set()
    visited: set[str] = set()

    def visit(record: dict[str, Any]) -> None:
        file_name = record.get("file")
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError("Vite manifest visited record has no valid file")
        declared_file = _required_asset_path(build_dir, file_name, reference="declared entry/import asset")
        if urllib.parse.urlsplit(file_name).path.endswith(".js"):
            initial_js.add(declared_file)
        css_values = record.get("css", [])
        if not isinstance(css_values, list):
            raise ValueError("Vite manifest css must be an array")
        for css in css_values:
            if not isinstance(css, str) or not css.strip():
                raise ValueError("Vite manifest css entries must be non-empty strings")
            initial_css.add(_required_asset_path(build_dir, css, reference="CSS asset"))
        import_values = record.get("imports", [])
        if not isinstance(import_values, list):
            raise ValueError("Vite manifest imports must be an array")
        for imported_key in import_values:
            if not isinstance(imported_key, str) or not imported_key.strip():
                raise ValueError("Vite manifest import keys must be non-empty strings")
            if imported_key in visited:
                continue
            imported = manifest.get(imported_key)
            if not isinstance(imported, dict):
                raise ValueError("Vite manifest references a missing import record")
            visited.add(imported_key)
            visit(imported)

    for entry in entries:
        visit(entry)
    all_js = set(build_dir.glob("assets/**/*.js"))
    lazy_js = all_js - initial_js
    return {
        "initialJavascriptBytes": sum(path.stat().st_size for path in initial_js),
        "initialCssBytes": sum(path.stat().st_size for path in initial_css),
        "lazyChunkMaxBytes": max((path.stat().st_size for path in lazy_js), default=0),
    }, "vite-manifest"


class _BuildHtmlReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []
        self.invalid_reason: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if "src" in values:
            source = values.get("src")
            if not isinstance(source, str) or not source.strip():
                self.invalid_reason = "HTML asset src must be a non-empty string"
            else:
                self.references.append(source)
        if tag != "link":
            return
        rel = set(str(values.get("rel") or "").casefold().split())
        preload_kind = str(values.get("as") or "").casefold()
        is_initial = bool(rel.intersection({"stylesheet", "modulepreload"})) or (
            "preload" in rel and preload_kind in {"script", "style"}
        )
        if "href" not in values and not is_initial:
            return
        href = values.get("href")
        if not isinstance(href, str) or not href.strip():
            self.invalid_reason = "HTML initial link href must be a non-empty string"
        else:
            self.references.append(href)


def _html_measurements(build_dir: Path) -> tuple[dict[str, int], str]:
    index = build_dir / "index.html"
    if not index.is_file():
        raise ValueError("Neither Vite manifest nor index.html exists in the configured build directory")
    html = index.read_text(encoding="utf-8")
    parser = _BuildHtmlReferenceParser()
    parser.feed(html)
    parser.close()
    if parser.invalid_reason:
        raise ValueError(parser.invalid_reason)
    resolved = [
        _required_asset_path(build_dir, reference, reference="HTML asset")
        for reference in parser.references
    ]
    initial_js = [path for path in resolved if path.suffix == ".js"]
    initial_css = [path for path in resolved if path.suffix == ".css"]
    all_js = set(build_dir.glob("assets/**/*.js"))
    lazy_js = all_js - set(initial_js)
    return {
        "initialJavascriptBytes": sum(path.stat().st_size for path in initial_js),
        "initialCssBytes": sum(path.stat().st_size for path in initial_css),
        "lazyChunkMaxBytes": max((path.stat().st_size for path in lazy_js), default=0),
    }, "vite-output-index"


def measure_build(build_dir: Path) -> tuple[dict[str, int], str, str]:
    manifest_path = build_dir / ".vite" / "manifest.json"
    if manifest_path.is_file():
        metrics, source = _vite_manifest_measurements(build_dir, _read_json(manifest_path))
    else:
        metrics, source = _html_measurements(build_dir)
    fingerprint = hashlib.sha256()
    for path in sorted(build_dir.rglob("*")):
        if path.is_file():
            fingerprint.update(path.relative_to(build_dir).as_posix().encode("utf-8"))
            fingerprint.update(_sha256(path).encode("ascii"))
    return metrics, source, fingerprint.hexdigest()


def _metric_result(name: str, budget: int | float, actual: object, *, evidence: str) -> dict[str, Any]:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return {"name": name, "budget": budget, "status": "unproven", "reason": evidence}
    value = float(actual)
    return {
        "name": name,
        "budget": budget,
        "actual": value,
        "status": "pass" if value <= budget else "fail",
        "overBudget": max(0.0, value - float(budget)),
        "evidence": evidence,
    }


def _evidence_limits(config: dict[str, Any]) -> dict[str, int | float]:
    configured = config.get("evidenceLimits")
    merged = dict(DEFAULT_EVIDENCE_LIMITS)
    if isinstance(configured, dict):
        merged.update({key: configured[key] for key in DEFAULT_EVIDENCE_LIMITS if key in configured})
    for name, value in merged.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"evidenceLimits.{name} must be a positive number")
    if int(merged["minStartupSamples"]) > int(merged["maxSamplesPerMetric"]):
        raise ValueError("minStartupSamples cannot exceed maxSamplesPerMetric")
    return merged


def _validate_config(config: dict[str, Any]) -> None:
    max_age = config.get("maxEvidenceAgeHours")
    if (
        not isinstance(max_age, (int, float))
        or isinstance(max_age, bool)
        or not math.isfinite(float(max_age))
        or float(max_age) <= 0
    ):
        raise ValueError("maxEvidenceAgeHours must be finite and positive")
    build = config.get("build")
    if not isinstance(build, dict):
        raise ValueError("build performance budgets must be an object")
    missing_build = [name for name in REQUIRED_BUILD_METRICS if name not in build]
    if missing_build:
        raise ValueError(f"build performance budgets are missing required metrics: {', '.join(missing_build)}")
    unexpected_build = sorted(set(build) - set(REQUIRED_BUILD_METRICS))
    if unexpected_build:
        raise ValueError(f"build performance budgets contain unsupported metrics: {', '.join(unexpected_build)}")
    for name in REQUIRED_BUILD_METRICS:
        value = build[name]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"build performance budget {name} must be finite and non-negative")
    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("runtime performance budgets must be an object")
    missing = [name for name in REQUIRED_RUNTIME_METRICS if name not in runtime]
    if missing:
        raise ValueError(f"runtime performance budgets are missing required metrics: {', '.join(missing)}")
    unexpected = sorted(set(runtime) - set(REQUIRED_RUNTIME_METRICS))
    if unexpected:
        raise ValueError(f"runtime performance budgets contain unsupported metrics: {', '.join(unexpected)}")
    for name in REQUIRED_RUNTIME_METRICS:
        value = runtime[name]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(f"runtime performance budget {name} must be finite and non-negative")


def _aggregate_runtime_samples(name: str, values: list[float]) -> float:
    if name in P95_METRICS:
        ordered = sorted(values)
        actual = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    elif name in MAX_METRICS:
        actual = max(values)
    else:
        raise ValueError(f"unsupported runtime metric {name}")
    return round(actual, 3)


def _validated_runtime_metric(
    runtime: dict[str, Any],
    name: str,
    *,
    limits: dict[str, int | float],
) -> tuple[object, str]:
    metrics = runtime.get("metrics")
    evidence = runtime.get("metricEvidence")
    raw_samples = runtime.get("rawSamples")
    if not isinstance(metrics, dict) or not isinstance(evidence, dict) or not isinstance(raw_samples, dict):
        return None, "RUNTIME_METRIC_PROVENANCE_MISSING"
    detail = evidence.get(name)
    if not isinstance(detail, dict):
        return None, "RUNTIME_METRIC_EVIDENCE_MISSING"
    if detail.get("status") != "measured":
        reason_code = detail.get("reasonCode")
        if reason_code not in ALLOWED_REASON_CODES:
            return None, "RUNTIME_METRIC_REASON_UNSUPPORTED"
        return None, str(reason_code)
    if detail.get("aggregation") != EXPECTED_AGGREGATION[name]:
        return None, "RUNTIME_METRIC_AGGREGATION_UNSUPPORTED"
    if detail.get("source") not in ALLOWED_METRIC_SOURCES[name]:
        return None, "RUNTIME_METRIC_SOURCE_UNSUPPORTED"
    sample_count = detail.get("sampleCount")
    maximum = int(limits["maxSamplesPerMetric"])
    minimum = int(limits["minStartupSamples"]) if name == "startupP95Ms" else 1
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or not minimum <= sample_count <= maximum:
        return None, "RUNTIME_METRIC_SAMPLE_COUNT_OUT_OF_BOUNDS"
    samples = raw_samples.get(name)
    if not isinstance(samples, list) or len(samples) != sample_count:
        return None, "RUNTIME_METRIC_RAW_SAMPLES_MISMATCH"
    normalized: list[float] = []
    for sample in samples:
        if (
            not isinstance(sample, (int, float))
            or isinstance(sample, bool)
            or not math.isfinite(float(sample))
            or float(sample) < 0
        ):
            return None, "RUNTIME_METRIC_RAW_SAMPLE_INVALID"
        normalized.append(float(sample))
    actual = metrics.get(name)
    if (
        not isinstance(actual, (int, float))
        or isinstance(actual, bool)
        or not math.isfinite(float(actual))
        or float(actual) < 0
    ):
        return None, "RUNTIME_METRIC_VALUE_INVALID"
    recomputed = _aggregate_runtime_samples(name, normalized)
    if float(actual) != recomputed:
        return None, "RUNTIME_METRIC_AGGREGATE_MISMATCH"
    return recomputed, "RUNTIME_METRIC_EVIDENCE_VALIDATED"


@enforced("sv.performance.fail-closed")
def evaluate(
    *,
    config: dict[str, Any],
    build_dir: Path,
    runtime_evidence_path: Path,
    now: datetime,
) -> dict[str, Any]:
    if config.get("schema") != "neyvia.performance-budgets.v1":
        raise ValueError("unsupported performance budget schema")
    _validate_config(config)
    evidence_limits = _evidence_limits(config)
    build_reason = "BUILD_OUTPUT_VALIDATED"
    try:
        build_metrics, build_source, build_fingerprint = measure_build(build_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        build_metrics, build_source, build_fingerprint = {}, "unavailable", ""
        build_reason = "BUILD_OUTPUT_INVALID_OR_UNAVAILABLE"
    results = [
        _metric_result(
            name,
            budget,
            build_metrics.get(name) if build_reason == "BUILD_OUTPUT_VALIDATED" else None,
            evidence=build_source if build_reason == "BUILD_OUTPUT_VALIDATED" else build_reason,
        )
        for name, budget in dict(config["build"]).items()
    ]
    runtime: dict[str, Any] = {}
    captured_at: datetime | None = None
    runtime_reason = "RUNTIME_EVIDENCE_MISSING"
    if runtime_evidence_path.is_file():
        try:
            runtime = _read_json(runtime_evidence_path)
            if runtime.get("schema") != RUNTIME_SCHEMA:
                runtime_reason = "RUNTIME_EVIDENCE_SCHEMA_UNSUPPORTED"
            elif runtime.get("recorderSchema") != RECORDER_SCHEMA:
                runtime_reason = "RUNTIME_RECORDER_SCHEMA_UNSUPPORTED"
            elif runtime.get("budgetConfigFingerprint") != config_fingerprint(config):
                runtime_reason = "RUNTIME_CONFIG_FINGERPRINT_MISMATCH"
            elif not isinstance(runtime.get("evidenceBinding"), dict):
                runtime_reason = "RUNTIME_BINDING_MISSING"
            elif runtime["evidenceBinding"].get("schema") != EVIDENCE_BINDING_SCHEMA:
                runtime_reason = "RUNTIME_BINDING_SCHEMA_UNSUPPORTED"
            elif runtime["evidenceBinding"].get("algorithm") != "sha256":
                runtime_reason = "RUNTIME_BINDING_ALGORITHM_UNSUPPORTED"
            elif runtime["evidenceBinding"].get("canonicalization") != "json-sort-keys-compact-v1":
                runtime_reason = "RUNTIME_CANONICALIZATION_UNSUPPORTED"
            elif runtime["evidenceBinding"].get("digest") != _evidence_digest(runtime):
                runtime_reason = "RUNTIME_EVIDENCE_DIGEST_MISMATCH"
            else:
                capture_started_at = _parse_timestamp(runtime.get("captureStartedAt"))
                captured_at = _parse_timestamp(runtime.get("capturedAt"))
                if captured_at is None:
                    runtime_reason = "RUNTIME_CAPTURED_AT_INVALID"
                elif capture_started_at is None:
                    runtime_reason = "RUNTIME_CAPTURE_STARTED_AT_INVALID"
                elif capture_started_at > captured_at:
                    runtime_reason = "RUNTIME_CAPTURE_WINDOW_INVALID"
                elif captured_at > now + MAX_FUTURE_SKEW:
                    runtime_reason = "RUNTIME_CAPTURE_IN_FUTURE"
                elif (captured_at - capture_started_at).total_seconds() > float(
                    evidence_limits["maxCaptureDurationSeconds"]
                ):
                    runtime_reason = "RUNTIME_CAPTURE_DURATION_EXCEEDED"
                elif captured_at < now - timedelta(hours=float(config["maxEvidenceAgeHours"])):
                    runtime_reason = "RUNTIME_EVIDENCE_STALE"
                elif not build_fingerprint:
                    runtime_reason = "RUNTIME_BUILD_MATCH_UNAVAILABLE"
                elif runtime.get("buildFingerprint") != build_fingerprint:
                    runtime_reason = "RUNTIME_BUILD_FINGERPRINT_MISMATCH"
                else:
                    runtime_reason = "RUNTIME_EVIDENCE_VALIDATED"
        except (OSError, ValueError, json.JSONDecodeError):
            runtime_reason = "RUNTIME_EVIDENCE_UNREADABLE"
    for name, budget in dict(config["runtime"]).items():
        actual: object = None
        metric_reason = runtime_reason
        if runtime_reason == "RUNTIME_EVIDENCE_VALIDATED":
            actual, metric_reason = _validated_runtime_metric(runtime, name, limits=evidence_limits)
        results.append(_metric_result(name, budget, actual, evidence=metric_reason))
    statuses = {result["status"] for result in results}
    local_budget_status = "fail" if "fail" in statuses else "unproven" if "unproven" in statuses else "pass"
    status = "fail" if local_budget_status == "fail" else "unproven"
    return {
        "schema": SCHEMA,
        "status": status,
        "localBudgetStatus": local_budget_status,
        "promotionEligible": False,
        "trust": {
            "status": "unproven",
            "reasonCode": "VERIFIER_ATTESTATION_NOT_PROVISIONED",
            "localTamperEvidenceOnly": True,
        },
        "build": {"pathRef": "build-dir", "fingerprint": build_fingerprint, "measurementSource": build_source},
        "runtimeEvidence": {
            "pathRef": "runtime-evidence",
            "capturedAt": (
                captured_at.isoformat().replace("+00:00", "Z")
                if captured_at is not None
                else None
            ),
            "status": runtime_reason,
        },
        "results": results,
        "summary": {
            "passed": sum(result["status"] == "pass" for result in results),
            "failed": sum(result["status"] == "fail" for result in results),
            "unproven": sum(result["status"] == "unproven" for result in results),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Neyvia build and runtime performance-budget gate")
    parser.add_argument("--config", type=Path, default=Path("config/neyvia_performance_budgets.json"))
    parser.add_argument("--build-dir", type=Path, default=Path("web/dist"))
    parser.add_argument("--runtime-evidence", type=Path, default=Path(".agent_control/performance/runtime-latest.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(
            config=_read_json(args.config),
            build_dir=args.build_dir,
            runtime_evidence_path=args.runtime_evidence,
            now=datetime.now(timezone.utc),
        )
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        report = {
            "schema": SCHEMA,
            "status": "unproven",
            "localBudgetStatus": "unproven",
            "promotionEligible": False,
            "errorCode": "PERFORMANCE_VERIFICATION_FAILED",
        }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 2 if "errorCode" in report else 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
