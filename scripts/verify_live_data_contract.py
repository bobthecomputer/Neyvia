from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ID = "fluxio.live_data_contract.v1"
DEFAULT_REPORT_PATH = ROOT / "tmp-ui-checks" / "live-data-contract" / "report.json"

CHECK_IDS = (
    "live_mode_does_not_boot_from_cached_snapshot",
    "fixtures_are_dev_preview_only",
    "fast_bootstrap_summary_is_backend_supported",
    "reference_shell_hides_fixture_rows_in_live_mode",
    "built_dist_contains_live_only_copy",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def make_check(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "passed": bool(passed),
        "detail": detail,
        **extra,
    }


def missing_fragments(text: str, fragments: list[str]) -> list[str]:
    return [fragment for fragment in fragments if fragment not in text]


def read_dist_bundle(root: Path) -> tuple[str, list[str]]:
    dist_root = root / "web" / "dist"
    paths = [
        path
        for path in dist_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".css"}
    ]
    return "\n".join(read_text(path) for path in paths), [str(path.relative_to(root)) for path in paths]


def build_report(root: Path) -> dict[str, Any]:
    shell = read_text(root / "web" / "src" / "neyvia" / "NeyviaShell.jsx")
    reference_shell = read_text(root / "web" / "src" / "neyvia" / "NeyviaWorkspace.jsx")
    styles = read_text(root / "web" / "src" / "neyvia" / "styles.css")
    model = read_text(root / "web" / "src" / "neyvia" / "missionControlModel.js")
    dist_bundle, dist_files = read_dist_bundle(root)

    checks: list[dict[str, Any]] = []

    live_boot_fragments = [
        'previewMode === "live"\n      ? summaryMissions',
        'previewMode === "live"\n        ? data.summary?.missions || []',
        "liveDataStatus",
        "summaryMode",
        "bootstrap",
    ]
    live_boot_missing = missing_fragments(shell, live_boot_fragments)
    checks.append(
        make_check(
            "live_mode_does_not_boot_from_cached_snapshot",
            not live_boot_missing and 'previewMode === "live" && summaryMissions.length > 0' not in shell,
            "Live mode reads the authenticated backend summary path and does not rehydrate cached mission fixtures.",
            missing=live_boot_missing,
        )
    )

    fixture_fragments = [
        "isLiveBackend ? [] : BUILDER_FLOWS",
        "isLiveBackend ? [] : CHANGED_FILES",
        "isLiveBackend ? [] : TOOL_EVENTS",
        "fixture flow cards are hidden in live mode",
    ]
    fixture_missing = missing_fragments(reference_shell, fixture_fragments)
    checks.append(
        make_check(
            "fixtures_are_dev_preview_only",
            not fixture_missing,
            "Fixture rows are only available outside live backend mode.",
            missing=fixture_missing,
        )
    )

    bootstrap_fragments = [
        "summaryMode",
        "bootstrap",
        "mergeAuthenticatedLiveSummaries",
        "control-room summary",
    ]
    bootstrap_missing = missing_fragments(shell, bootstrap_fragments)
    checks.append(
        make_check(
            "fast_bootstrap_summary_is_backend_supported",
            not bootstrap_missing,
            "The frontend supports a fast bootstrap summary before the enriched live snapshot arrives.",
            missing=bootstrap_missing,
        )
    )

    reference_fragments = [
        'data-live-builder-progress-board="true"',
        "liveMissionProgressBoardRows",
        "The home surface is waiting for NAS control-room data; no cached or sample sessions are shown.",
        "No live mission rows loaded yet",
        "No live review targets are available yet; the panel waits for current NAS mission evidence.",
        ".fluxos-live-data-banner",
        ".fluxos-flow-empty",
    ]
    reference_missing = missing_fragments(reference_shell + "\n" + styles + "\n" + model, reference_fragments)
    checks.append(
        make_check(
            "reference_shell_hides_fixture_rows_in_live_mode",
            not reference_missing,
            "Builder shows an explicit live-data waiting state instead of fixture rows when NAS evidence is missing.",
            missing=reference_missing,
        )
    )

    dist_fragments = [
        "data-live-builder-progress-board",
        "The home surface is waiting for NAS control-room data",
        "fixture flow cards are hidden in live mode",
    ]
    dist_missing = missing_fragments(dist_bundle, dist_fragments)
    checks.append(
        make_check(
            "built_dist_contains_live_only_copy",
            bool(dist_files) and not dist_missing,
            "The built Vite assets contain the same live-only copy used by the source UI.",
            missing=dist_missing,
            distFileCount=len(dist_files),
            sampleDistFiles=dist_files[:8],
        )
    )

    passed = all(check["passed"] for check in checks)
    return {
        "contract": CONTRACT_ID,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "passed": passed,
        "checks": checks,
        "summary": {
            "summaryMode": "bootstrap",
            "bootstrap": True,
            "liveOnlyCheckIds": list(CHECK_IDS),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Fluxio live data UI contract.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = build_report(root)
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"contract": CONTRACT_ID, "passed": report["passed"], "reportPath": str(report_path)}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
