from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROOF_IMPORT_SCHEMA = "fluxio.real_agent_proof_bundle_import.v1"
REPORT_FILENAMES = {"real-agent-conversation-check.json", "mixed-real-agent-runtime-proof.json"}


@dataclass(frozen=True)
class ProofImportPlan:
    source_root: Path
    source_report_path: Path
    target_root: Path
    target_path_root: str
    target_dir: Path
    target_path_dir: str
    target_report_path: Path
    path_map: dict[str, str]
    payload: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read proof report JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Proof report is not a JSON object: {path}")
    return payload


def _posix_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _safe_segment(value: str, fallback: str = "proof") -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or fallback


def _iter_strings(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for item in payload.values():
            values.extend(_iter_strings(item))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_strings(item))
    elif isinstance(payload, str):
        values.append(payload)
    return values


def _collect_referenced_files(report: dict[str, Any], report_path: Path, source_root: Path) -> list[Path]:
    source_report_dir = report_path.parent.resolve()
    candidates = {report_path.resolve()}
    for text in _iter_strings(report):
        stripped = text.strip()
        if not stripped:
            continue
        path = Path(stripped)
        if not path.is_absolute():
            relative_candidates = [source_report_dir / path, source_root / path]
            for candidate in relative_candidates:
                if candidate.exists() and candidate.is_file():
                    candidates.add(candidate.resolve())
            continue
        if path.exists() and path.is_file():
            try:
                path.resolve().relative_to(source_root.resolve())
            except ValueError:
                try:
                    path.resolve().relative_to(source_report_dir)
                except ValueError:
                    continue
            candidates.add(path.resolve())
    return sorted(candidates)


def _rewrite_string(value: str, replacements: list[tuple[str, str]]) -> str:
    result = value
    for source, target in replacements:
        if source:
            result = result.replace(source, target)
    return result


def _rewrite_payload(payload: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(payload, dict):
        return {key: _rewrite_payload(value, replacements) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_rewrite_payload(value, replacements) for value in payload]
    if isinstance(payload, str):
        return _rewrite_string(payload, replacements)
    return payload


def build_import_plan(
    *,
    source_root: Path,
    report_path: Path,
    target_root: Path,
    target_path_root: str | None = None,
    target_subdir: str | None = None,
) -> ProofImportPlan:
    source_root = source_root.resolve()
    report_path = report_path.resolve()
    target_root = target_root.resolve()
    report = _read_json(report_path)
    if report.get("schema") not in {
        "fluxio.real_agent_conversation_proof.v1",
        "fluxio.real_agent_mixed_runtime_proof.v1",
    }:
        raise RuntimeError(f"Unsupported proof report schema: {report.get('schema')!r}")

    mission = report.get("mission") if isinstance(report.get("mission"), dict) else {}
    mission_id = str(mission.get("missionId") or report.get("missionId") or "").strip()
    run_segment = _safe_segment(f"{report_path.parent.name}-{mission_id}" if mission_id else report_path.parent.name)
    relative_subdir = Path(target_subdir or f"tmp-ui-checks/real-agent-conversation-proof/imported-{run_segment}")
    target_dir = (target_root / relative_subdir).resolve()
    target_path_root_text = _posix_path(target_path_root or target_root)
    target_path_dir = _posix_path(Path(target_path_root_text) / relative_subdir)
    target_report_path = target_dir / report_path.name
    target_report_path_text = _posix_path(Path(target_path_dir) / report_path.name)

    referenced_files = _collect_referenced_files(report, report_path, source_root)
    path_map: dict[str, str] = {}
    for source_path in referenced_files:
        if source_path == report_path:
            target_path = target_report_path
        else:
            target_path = target_dir / source_path.name
        path_map[str(source_path)] = _posix_path(Path(target_path_dir) / target_path.name)

    replacements: list[tuple[str, str]] = []
    for source_path, target_path_text in sorted(path_map.items(), key=lambda item: len(item[0]), reverse=True):
        replacements.append((source_path, target_path_text))
        replacements.append((_posix_path(source_path), target_path_text))
    replacements.append((str(report_path.parent), target_path_dir))
    replacements.append((_posix_path(report_path.parent), target_path_dir))
    replacements.append((str(source_root), target_path_root_text))
    replacements.append((_posix_path(source_root), target_path_root_text))

    rewritten = _rewrite_payload(report, replacements)
    rewritten["root"] = target_path_root_text
    rewritten["reportPath"] = target_report_path_text
    rewritten["importedProofBundle"] = {
        "schema": PROOF_IMPORT_SCHEMA,
        "importedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRoot": str(source_root),
        "sourceReportPath": str(report_path),
        "targetRoot": target_path_root_text,
        "targetReportPath": target_report_path_text,
    }

    return ProofImportPlan(
        source_root=source_root,
        source_report_path=report_path,
        target_root=target_root,
        target_path_root=target_path_root_text,
        target_dir=target_dir,
        target_path_dir=target_path_dir,
        target_report_path=target_report_path,
        path_map=path_map,
        payload=rewritten,
    )


def write_import_plan(plan: ProofImportPlan) -> dict[str, Any]:
    plan.target_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[dict[str, str]] = []
    for source_text, target_text in plan.path_map.items():
        source_path = Path(source_text)
        target_name = Path(target_text).name
        target_path = plan.target_dir / target_name
        if source_path.name in REPORT_FILENAMES:
            continue
        shutil.copy2(source_path, target_path)
        copied_files.append({"source": str(source_path), "target": _posix_path(Path(plan.target_path_dir) / target_name)})
    plan.target_report_path.write_text(json.dumps(plan.payload, indent=2), encoding="utf-8")
    copied_files.append(
        {
            "source": str(plan.source_report_path),
            "target": _posix_path(Path(plan.target_path_dir) / plan.target_report_path.name),
        }
    )
    manifest = {
        "schema": PROOF_IMPORT_SCHEMA,
        "importedAt": datetime.now(timezone.utc).isoformat(),
        "sourceRoot": str(plan.source_root),
        "sourceReportPath": str(plan.source_report_path),
        "targetRoot": plan.target_path_root,
        "targetDir": plan.target_path_dir,
        "targetReportPath": _posix_path(Path(plan.target_path_dir) / plan.target_report_path.name),
        "copiedFiles": copied_files,
    }
    manifest_dir = plan.target_root / ".agent_control" / "real_agent_proof_imports"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{_safe_segment(plan.target_dir.name)}.json"
    manifest["manifestPath"] = _posix_path(Path(plan.target_path_root) / ".agent_control" / "real_agent_proof_imports" / manifest_path.name)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _default_complete_report(source_root: Path) -> Path:
    from grant_agent.real_agent_proof import build_real_agent_proof_status

    status = build_real_agent_proof_status(source_root)
    latest = status.get("latestCompleteProof") if isinstance(status.get("latestCompleteProof"), dict) else {}
    report_path = Path(str(latest.get("reportPath") or ""))
    if not report_path.exists():
        raise RuntimeError("No complete real-agent proof report is available under the source root.")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a real local Agent proof bundle into another proof root.")
    parser.add_argument("--source-root", default=".", help="Local project root that owns the source proof report.")
    parser.add_argument("--report-path", default="", help="Specific source report JSON. Defaults to latest complete proof.")
    parser.add_argument("--target-root", required=True, help="Filesystem root to write imported proof files into.")
    parser.add_argument(
        "--target-path-root",
        default="",
        help="Path prefix to write inside JSON. Use this when staging files locally for a remote root.",
    )
    parser.add_argument("--target-subdir", default="", help="Relative proof directory under the target root.")
    parser.add_argument("--write", action="store_true", help="Write files. Without this flag, only print the plan.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_root).resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else _default_complete_report(source_root)
    plan = build_import_plan(
        source_root=source_root,
        report_path=report_path,
        target_root=Path(args.target_root),
        target_path_root=args.target_path_root or None,
        target_subdir=args.target_subdir or None,
    )
    if args.write:
        payload = write_import_plan(plan)
    else:
        payload = {
            "schema": PROOF_IMPORT_SCHEMA,
            "dryRun": True,
            "sourceReportPath": str(plan.source_report_path),
            "targetRoot": plan.target_path_root,
            "targetDir": plan.target_path_dir,
            "targetReportPath": _posix_path(Path(plan.target_path_dir) / plan.target_report_path.name),
            "fileCount": len(plan.path_map),
            "pathMap": plan.path_map,
        }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
