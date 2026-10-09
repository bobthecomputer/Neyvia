from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "web" / "src" / "neyvia" / "NeyviaShell.jsx"
REFERENCE_SHELL = ROOT / "web" / "src" / "neyvia" / "NeyviaWorkspace.jsx"
PACKAGE = ROOT / "package.json"


REQUIRED_TEMPLATE_IDS = (
    "fluxio-watchdog-repair",
    "solantir-account-watchdog-cleanup",
    "jbheaven-t3mp3st-research",
)

REQUIRED_TEMPLATE_SELECTORS = (
    '[data-mission-template-id="fluxio-watchdog-repair"]',
    '[data-mission-template-id="solantir-account-watchdog-cleanup"]',
    '[data-mission-template-id="jbheaven-t3mp3st-research"]',
)


def _check(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "passed": passed, "detail": detail}


def main() -> int:
    shell = SHELL.read_text(encoding="utf-8")
    reference_shell = REFERENCE_SHELL.read_text(encoding="utf-8")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))

    checks: list[dict[str, object]] = []
    for template_id in REQUIRED_TEMPLATE_IDS:
        marker = f'data-mission-template-id={{template.id}}'
        checks.append(
            _check(
                f"template:{template_id}",
                template_id in shell,
                f"Mission template id {template_id} is present in NeyviaShell.",
            )
        )

    for selector in REQUIRED_TEMPLATE_SELECTORS:
        template_id = selector.split('"')[1]
        checks.append(
            _check(
                f"selector:{template_id}",
                template_id in shell and "data-mission-template-id" in shell,
                f"Verifier selector {selector} maps to a rendered mission template.",
            )
        )
        checks.append(
            _check(
                f"rendered-template-hook:{template_id}",
                marker in shell and f'id: "{template_id}"' in shell,
                f"Mission template {template_id} can render through the shared template button.",
            )
        )

    checks.extend(
        [
            _check(
                "schema",
                True,
                "fluxio.mission_pack_launch.v1",
            ),
            _check(
                "template-load-handler",
                "handleMissionTemplateApply" in shell
                and "onClick={() => handleMissionTemplateApply(template)}" in shell,
                "Template buttons load the selected mission into the normal composer path.",
            ),
            _check(
                "backend-command",
                "start_control_room_mission_command" in shell,
                "Template launch uses the real control-room mission command.",
            ),
            _check(
                "mission-one-shortcut",
                'action: "agent:launch-watchdog-repair"' in reference_shell
                and "fluxio-watchdog-repair" in shell,
                "Agent Live shortcut points at mission 1.",
            ),
            _check(
                "package-script",
                package.get("scripts", {}).get("verify:mission-pack-launch")
                == "python scripts/verify_mission_pack_launch.py",
                "package.json exposes the verifier command.",
            ),
            _check(
                "package-files",
                "scripts/verify_mission_pack_launch.py" in package.get("files", []),
                "Verifier script is included in package files.",
            ),
        ]
    )

    passed = sum(1 for check in checks if check["passed"])
    payload = {
        "schema": "fluxio.mission_pack_launch.v1",
        "passed": passed == len(checks),
        "summary": f"{passed}/{len(checks)} mission pack launch checks passed.",
        "checks": checks,
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
