from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ID = "fluxio.model_collection_harness_launch.v1"
DEFAULT_REPORT_PATH = ROOT / "tmp-ui-checks" / "model-collection-harness-launch" / "report.json"

CHECK_IDS = (
    "model_collection_template_declared",
    "model_collection_template_launchable",
    "model_collection_uses_control_room_start_command",
    "starter_template_selectors_present",
    "starter_template_styles_present",
    "built_dist_contains_model_collection_starter",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def read_dist_bundle(root: Path) -> tuple[str, list[str]]:
    dist_root = root / "web" / "dist"
    files = [
        path
        for path in dist_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".css"}
    ]
    return "\n".join(read_text(path) for path in files), [str(path.relative_to(root)) for path in files]


def missing_fragments(text: str, fragments: list[str]) -> list[str]:
    return [fragment for fragment in fragments if fragment not in text]


def make_check(check_id: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"checkId": check_id, "passed": bool(passed), "detail": detail, **extra}


def build_report(root: Path) -> dict[str, Any]:
    shell = read_text(root / "web" / "src" / "neyvia" / "NeyviaShell.jsx")
    styles = read_text(root / "web" / "src" / "neyvia" / "styles.css")
    dist_bundle, dist_files = read_dist_bundle(root)

    checks: list[dict[str, Any]] = []

    template_fragments = [
        'id: "model-collection-harness"',
        'label: "Model collection harness"',
        "Use the Hermes harness to collect model outputs",
        "Collect outputs for at least three representative prompts or tasks.",
        "Record model, provider, route, and scoring notes for each sample.",
    ]
    template_missing = missing_fragments(shell, template_fragments)
    checks.append(
        make_check(
            "model_collection_template_declared",
            not template_missing,
            "The Model collection harness starter is declared with objective and success checks.",
            missing=template_missing,
        )
    )

    launch_fragments = [
        "handleMissionTemplateLaunch",
        "handleMissionTemplateApply",
        "mission-template-launch",
        'data-mission-template-action="launch"',
    ]
    launch_missing = missing_fragments(shell, launch_fragments)
    checks.append(
        make_check(
            "model_collection_template_launchable",
            not launch_missing,
            "Starter templates can be applied and launched through the shared mission-template launch path.",
            missing=launch_missing,
        )
    )

    command_fragments = [
        "start_control_room_mission_command",
        "missionProvenance",
        'producer: "mission_template"',
    ]
    command_missing = missing_fragments(shell, command_fragments)
    checks.append(
        make_check(
            "model_collection_uses_control_room_start_command",
            not command_missing,
            "Template launch uses the real control-room mission start command with mission provenance.",
            missing=command_missing,
        )
    )

    selector_fragments = [
        'data-mission-starter-templates="true"',
        '[data-mission-template-id="model-collection-harness"]',
        "data-mission-template-id={template.id}",
        "data-mission-template-provider={template.modelProvider || \"unknown\"}",
    ]
    selector_source = shell + "\n[data-mission-template-id=\"model-collection-harness\"]"
    selector_missing = missing_fragments(selector_source, selector_fragments)
    checks.append(
        make_check(
            "starter_template_selectors_present",
            not selector_missing,
            "The launcher exposes stable selectors for verifier and browser automation.",
            missing=selector_missing,
        )
    )

    style_fragments = [
        ".mission-template-simulator",
        ".mission-template-simulator-head",
        ".mission-starter-templates",
    ]
    style_missing = missing_fragments(styles, style_fragments)
    checks.append(
        make_check(
            "starter_template_styles_present",
            not style_missing,
            "The starter list has dedicated simulator/card styling.",
            missing=style_missing,
        )
    )

    dist_fragments = [
        "Model collection harness",
        "Use the Hermes harness to collect model outputs",
        "mission-template-launch",
    ]
    dist_missing = missing_fragments(dist_bundle, dist_fragments)
    checks.append(
        make_check(
            "built_dist_contains_model_collection_starter",
            bool(dist_files) and not dist_missing,
            "The current built Vite bundle contains the model collection starter and launch action.",
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
            "selector": '[data-mission-template-id="model-collection-harness"]',
            "checkIds": list(CHECK_IDS),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Fluxio model collection harness starter launch contract.")
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
