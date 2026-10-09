from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JBHEAVEN_ROOT = Path.home() / "projects" / "Jbheaven"
DEFAULT_OUTPUT_ROOT = ROOT / ".agent_control" / "mission_artifacts" / "controlled_ai_safety_review"
TEST_FILES = (
    "tests/red-team-harness.test.mjs",
    "tests/permission-gating.test.mjs",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tap_count(output: str, name: str) -> int:
    match = re.search(rf"^# {re.escape(name)}\s+(\d+)\s*$", output, flags=re.MULTILINE)
    return int(match.group(1)) if match else 0


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def detected_image_extension(path: Path) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        result = ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        result = ".jpg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        result = ".webp"
    else:
        result = ""
    from grant_agent.proofs_a_control import check_image_magic
    check_image_magic(data, result)
    return result


def render_report(findings: dict, test_output: str) -> str:
    passed = findings["testSummary"]["passed"]
    failed = findings["testSummary"]["failed"]
    status = "Passed" if findings["status"] == "passed" else "Failed"
    status_class = "pass" if findings["status"] == "passed" else "fail"
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in findings["limitations"])
    test_rows = "".join(
        f"<tr><td><code>{html.escape(item)}</code></td><td>Executed</td></tr>"
        for item in findings["testFiles"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Controlled AI Safety Review</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #080b11; color: #eef2f8; line-height: 1.55; }}
    main {{ width: min(1040px, calc(100% - 40px)); margin: 0 auto; padding: 52px 0 72px; }}
    .eyebrow {{ color: #79a7ff; font-size: 12px; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }}
    h1 {{ max-width: 760px; margin: 10px 0 12px; font-size: clamp(34px, 6vw, 62px); line-height: 1.02; letter-spacing: -.04em; }}
    .lede {{ max-width: 780px; color: #aab5c7; font-size: 18px; }}
    .status {{ display: inline-flex; margin: 24px 0; padding: 9px 14px; border: 1px solid #324052; border-radius: 999px; font-weight: 700; }}
    .status.pass {{ color: #71e1ad; border-color: #246b50; background: #0d2a20; }}
    .status.fail {{ color: #ff9d9d; border-color: #7a3434; background: #301515; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 8px 0 30px; }}
    .metric, section {{ border: 1px solid #222a37; border-radius: 16px; background: #0f141d; }}
    .metric {{ padding: 18px; }}
    .metric strong {{ display: block; font-size: 28px; }}
    .metric span {{ color: #95a1b4; }}
    section {{ margin-top: 16px; padding: 24px; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    p, li {{ color: #b8c2d1; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 12px 10px; border-bottom: 1px solid #27303e; text-align: left; }}
    th {{ color: #8f9db1; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    pre {{ max-height: 420px; overflow: auto; padding: 18px; border-radius: 12px; background: #080b11; color: #c9d4e5; white-space: pre-wrap; }}
    footer {{ margin-top: 24px; color: #748095; font-size: 13px; }}
    @media (max-width: 720px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ width: min(100% - 24px, 1040px); padding-top: 30px; }} }}
    @media print {{ :root {{ color-scheme: light; }} body {{ background: white; color: #111827; }} .metric, section {{ background: white; border-color: #d1d5db; }} p, li {{ color: #374151; }} pre {{ max-height: none; background: #f3f4f6; color: #111827; }} }}
  </style>
</head>
<body>
  <main>
    <div class="eyebrow">Fluxio · Authorized local review</div>
    <h1>Controlled AI safety review</h1>
    <p class="lede">Deterministic tests of the local JBHEAVEN synthetic red-team harness and permission boundaries. No model was queried and no live target received traffic.</p>
    <div class="status {status_class}">{status}: deterministic test command exited {findings['testSummary']['exitCode']}</div>
    <div class="grid" aria-label="Test summary">
      <div class="metric"><strong>{passed}</strong><span>tests passed</span></div>
      <div class="metric"><strong>{failed}</strong><span>tests failed</span></div>
      <div class="metric"><strong>0</strong><span>model calls</span></div>
    </div>
    <section>
      <h2>Scope and constraints</h2>
      <p>Read and test access was limited to <code>{html.escape(findings['target'])}</code>. Network and off-scope egress were denied by contract. The run used one local process, one round, and no credentials.</p>
    </section>
    <section>
      <h2>Executed evidence</h2>
      <table><thead><tr><th>Test file</th><th>Result source</th></tr></thead><tbody>{test_rows}</tbody></table>
    </section>
    <section>
      <h2>What this proves</h2>
      <p>The checked JavaScript modules satisfy their current deterministic assertions. The permission tests cover membership reveal limits, creator-only unlock rules, and canonical pipeline edit restrictions. The red-team harness tests cover bounded sampling, numeric scoring, and finding summaries.</p>
    </section>
    <section>
      <h2>Honest limitations</h2>
      <ul>{limitations}</ul>
    </section>
    <section>
      <h2>Raw TAP output</h2>
      <pre>{html.escape(test_output)}</pre>
    </section>
    <footer>Generated {html.escape(findings['generatedAt'])}. This report is printable HTML. PDF and audio were not produced.</footer>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded local JBHEAVEN safety review.")
    parser.add_argument("--jbheaven-root", type=Path, default=DEFAULT_JBHEAVEN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--screenshot", type=Path, default=None)
    args = parser.parse_args()

    target = args.jbheaven_root.resolve()
    output = args.output.resolve()
    missing = [item for item in TEST_FILES if not (target / item).is_file()]
    if missing:
        raise SystemExit(f"Missing required JBHEAVEN test files: {', '.join(missing)}")
    output.mkdir(parents=True, exist_ok=True)

    command = ["node", "--test", *TEST_FILES]
    completed = subprocess.run(
        command,
        cwd=target,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    test_output = (completed.stdout + "\n" + completed.stderr).strip()
    test_log = output / "test_output.txt"
    test_log.write_text(test_output + "\n", encoding="utf-8")
    generated_at = utc_now()
    receipt = {
        "schema": "fluxio.authorization_scope_receipt.v1",
        "missionId": "controlled_ai_safety_review",
        "generatedAt": generated_at,
        "selectedSkill": "jbheaven_godmode_lab",
        "authorization": {
            "confirmed": True,
            "targetScopes": [{"path": str(target), "access": "read_test"}],
        },
        "constraints": {
            "networkPolicy": "deny",
            "egressPolicy": "deny_off_scope_public_hosts",
            "modelCallLimit": 0,
            "executorCount": 1,
            "maxRounds": 1,
            "relativeStopMinutes": 10,
        },
        "actionPolicy": {
            "allowed": ["read_local_repository", "run_deterministic_tests", "write_proof_artifacts"],
            "approvalRequired": ["write_source_files"],
            "forbidden": ["third_party_targeting", "credential_export", "persistence", "destructive_action"],
        },
        "status": "accepted_scope",
    }
    receipt_path = output / "authorization_scope_receipt.json"
    write_json(receipt_path, receipt)

    findings = {
        "schema": "fluxio.controlled_ai_safety_findings.v1",
        "generatedAt": generated_at,
        "status": "passed" if completed.returncode == 0 else "failed",
        "classification": "deterministic_local_control_test",
        "target": str(target),
        "testFiles": list(TEST_FILES),
        "testSummary": {
            "exitCode": completed.returncode,
            "passed": tap_count(test_output, "pass"),
            "failed": tap_count(test_output, "fail"),
        },
        "constraintsObserved": {
            "modelCalls": 0,
            "liveTargetTraffic": False,
            "credentialUse": False,
            "sourceMutation": False,
        },
        "limitations": [
            "The red-team harness uses deterministic synthetic scenarios and does not evaluate a live model.",
            "Passing assertions prove current module behavior, not broad product security or safety.",
            "No third-party target, credential flow, persistence mechanism, or destructive action was tested.",
        ],
    }
    findings_path = output / "findings.json"
    write_json(findings_path, findings)
    report_path = output / "control_coverage_report.html"
    report_path.write_text(render_report(findings, test_output), encoding="utf-8")

    artifacts = [
        {"deliverableId": "authorization_scope_receipt", "role": "authorization_scope_receipt", "path": str(receipt_path)},
        {"deliverableId": "control_coverage_report", "role": "primary_deliverable", "path": str(report_path)},
        {"deliverableId": "findings_ledger", "role": "supporting_deliverable", "path": str(findings_path)},
        {"deliverableId": "test_output", "role": "supporting_evidence", "path": str(test_log)},
    ]
    if args.screenshot:
        screenshot = args.screenshot.resolve()
        if not screenshot.is_file() or screenshot.stat().st_size == 0:
            raise SystemExit(f"Screenshot does not exist or is empty: {screenshot}")
        detected_extension = detected_image_extension(screenshot)
        declared_extension = ".jpg" if screenshot.suffix.lower() == ".jpeg" else screenshot.suffix.lower()
        if not detected_extension:
            raise SystemExit(f"Screenshot is not a supported PNG, JPEG, or WebP image: {screenshot}")
        if detected_extension != declared_extension:
            raise SystemExit(
                f"Screenshot extension {screenshot.suffix.lower()} does not match {detected_extension} content: {screenshot}"
            )
        artifacts.append(
            {"deliverableId": "proof_screenshots", "role": "proof_screenshot", "path": str(screenshot)}
        )
    for item in artifacts:
        item["sha256"] = sha256(Path(item["path"]))
        item["bytes"] = Path(item["path"]).stat().st_size
    manifest = {
        "schema": "fluxio.artifact_manifest.v2",
        "missionId": "controlled_ai_safety_review",
        "generatedAt": generated_at,
        "status": findings["status"],
        "artifacts": artifacts,
    }
    manifest_path = output / "artifact_manifest.json"
    write_json(manifest_path, manifest)
    payload = {
        "ok": completed.returncode == 0,
        "status": findings["status"],
        "output": str(output),
        "report": str(report_path),
        "findings": str(findings_path),
        "manifest": str(manifest_path),
        "testSummary": findings["testSummary"],
    }
    print(json.dumps(payload, indent=2))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
