from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_e_sv import enforced

VERIFICATION_LADDER_SCHEMA = "fluxio.verification_ladder.v1"
SYNTAX_IMPORT_RECEIPT_SCHEMA = "fluxio.syntax_import_receipt.v1"
CHANGED_FILE_TARGETED_RECEIPT_SCHEMA = "fluxio.changed_file_targeted_receipt.v1"
BACKEND_COMMAND_SMOKE_RECEIPT_SCHEMA = "fluxio.backend_command_smoke_receipt.v1"
UI_BUTTON_SMOKE_RECEIPT_SCHEMA = "fluxio.ui_button_smoke_receipt.v1"
VERIFICATION_CAPACITY_POLICY_SCHEMA = "fluxio.verification_capacity_policy.v1"


@enforced("sv.ladder.plan")
def build_verification_ladder(
    *,
    mission_id: str,
    changed_files: list[str],
    proof_artifacts: list[str] | None = None,
    capacity_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = _bounded_strings(changed_files, limit=120, text_limit=240)
    proof = _bounded_strings(proof_artifacts or [], limit=40, text_limit=240)
    policy = capacity_policy or {}
    has_python = any(Path(item).suffix == ".py" for item in files)
    has_backend = has_python or any(_contains_part(item, {"src", "scripts", "tests"}) for item in files)
    has_frontend = any(Path(item).suffix in {".js", ".jsx", ".ts", ".tsx", ".css"} for item in files)
    has_ui = has_frontend or any(_contains_part(item, {"web", "ui", "frontend"}) for item in files)
    allow_frontend_build = bool(policy.get("allowFrontendBuild", False))
    allow_browser = bool(policy.get("allowBrowserVerification", False))
    steps = [
        _step(
            "syntax_import",
            "Syntax/import receipt",
            required=has_python,
            reason="Python files changed." if has_python else "No Python files changed.",
        ),
        _step(
            "changed_file_targeted",
            "Changed-file targeted check receipt",
            required=bool(files),
            reason="Changed files are present." if files else "No changed files were provided.",
        ),
        _step(
            "backend_smoke",
            "Backend command smoke receipt",
            required=has_backend,
            reason="Backend or test files changed." if has_backend else "No backend/test files changed.",
        ),
        _step(
            "ui_button_smoke",
            "UI/button smoke receipt",
            required=has_ui,
            reason="UI-facing files changed." if has_ui else "No UI-facing files changed.",
        ),
        _step(
            "frontend_build",
            "Full frontend build receipt",
            required=has_frontend and allow_frontend_build,
            reason=(
                "Frontend files changed and capacity policy allows build."
                if has_frontend and allow_frontend_build
                else "Frontend build is gated by capacity policy."
                if has_frontend
                else "No frontend files changed."
            ),
            capacity_gated=has_frontend and not allow_frontend_build,
        ),
        _step(
            "browser_verification",
            "Browser verification receipt",
            required=has_ui and allow_browser,
            reason=(
                "UI files changed and capacity policy allows browser verification."
                if has_ui and allow_browser
                else "Browser verification is gated by capacity policy."
                if has_ui
                else "No UI files changed."
            ),
            capacity_gated=has_ui and not allow_browser,
        ),
    ]
    required = [item for item in steps if item["required"]]
    gated = [item for item in steps if item["capacityGated"]]
    return {
        "schema": VERIFICATION_LADDER_SCHEMA,
        "ladderId": f"verification_ladder_{uuid.uuid4().hex[:12]}",
        "missionId": _compact_text(mission_id, 120),
        "changedFiles": files,
        "proofArtifacts": proof,
        "steps": steps,
        "requiredStepCount": len(required),
        "capacityGatedStepCount": len(gated),
        "nextAction": (
            "Run required verification receipts in order; record gated checks as skipped with policy reason."
            if steps
            else "Provide changed files before planning verification."
        ),
    }


@enforced("sv.ladder.capacity")
def build_verification_capacity_policy(
    *,
    pc_gateway_online: bool,
    time_budget_seconds: int,
    frontend_build_min_seconds: int = 300,
    browser_verification_min_seconds: int = 420,
    operator_present: bool = False,
) -> dict[str, Any]:
    time_budget = max(0, int(time_budget_seconds or 0))
    allow_frontend = bool(pc_gateway_online) and time_budget >= max(1, int(frontend_build_min_seconds or 1))
    allow_browser = (
        bool(pc_gateway_online)
        and bool(operator_present)
        and time_budget >= max(1, int(browser_verification_min_seconds or 1))
    )
    reasons: list[str] = []
    if not pc_gateway_online:
        reasons.append("PC gateway is offline; heavy frontend/browser checks stay gated.")
    if time_budget < max(1, int(frontend_build_min_seconds or 1)):
        reasons.append("Insufficient time budget for full frontend build.")
    if not operator_present:
        reasons.append("Operator is not marked present; browser verification stays gated.")
    return {
        "schema": VERIFICATION_CAPACITY_POLICY_SCHEMA,
        "allowFrontendBuild": allow_frontend,
        "allowBrowserVerification": allow_browser,
        "pcGatewayOnline": bool(pc_gateway_online),
        "operatorPresent": bool(operator_present),
        "timeBudgetSeconds": time_budget,
        "frontendBuildMinSeconds": max(1, int(frontend_build_min_seconds or 1)),
        "browserVerificationMinSeconds": max(1, int(browser_verification_min_seconds or 1)),
        "reasons": reasons,
        "nextAction": (
            "Run capacity-gated frontend/browser verification only where allowed."
            if allow_frontend or allow_browser
            else "Record full frontend build/browser verification as capacity-gated skips."
        ),
    }


@enforced("sv.ladder.receipt")
def build_syntax_import_receipt(
    *,
    mission_id: str,
    workspace: str | Path,
    changed_files: list[str],
) -> dict[str, Any]:
    workspace_path = Path(workspace)
    files = _bounded_strings(changed_files, limit=120, text_limit=240)
    python_files = [item for item in files if Path(item).suffix == ".py"]
    skipped = [item for item in files if Path(item).suffix != ".py"]
    existing_python_files = [
        item for item in python_files if (workspace_path / item).exists()
    ]
    missing_python_files = [
        item for item in python_files if not (workspace_path / item).exists()
    ]
    command = [sys.executable, "-m", "py_compile", *existing_python_files]
    if existing_python_files:
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    else:
        exit_code = 0 if not missing_python_files else 2
        stdout = ""
        stderr = "Python files were listed but missing from workspace." if missing_python_files else ""
    status = "passed" if exit_code == 0 and not missing_python_files else "failed"
    return {
        "schema": SYNTAX_IMPORT_RECEIPT_SCHEMA,
        "receiptId": f"receipt_syntax_import_{uuid.uuid4().hex[:12]}",
        "missionId": _compact_text(mission_id, 120),
        "workspace": str(workspace_path),
        "status": status,
        "command": " ".join(command) if existing_python_files else "",
        "exitCode": exit_code,
        "checkedFiles": existing_python_files,
        "missingFiles": missing_python_files,
        "skippedFiles": skipped,
        "stdoutSummary": _compact_text(stdout, 1000),
        "stderrSummary": _compact_text(stderr, 1000),
        "nextAction": (
            "Continue to changed-file targeted verification."
            if status == "passed"
            else "Fix syntax/import failures before running later verification steps."
        ),
    }


@enforced("sv.ladder.receipt")
def build_changed_file_targeted_receipt(
    *,
    mission_id: str,
    workspace: str | Path,
    changed_files: list[str],
) -> dict[str, Any]:
    workspace_path = Path(workspace)
    files = _bounded_strings(changed_files, limit=120, text_limit=240)
    test_files = [
        item
        for item in files
        if Path(item).suffix == ".py"
        and (Path(item).name.startswith("test_") or _contains_part(item, {"tests"}))
    ]
    existing_tests = [item for item in test_files if (workspace_path / item).exists()]
    missing_tests = [item for item in test_files if not (workspace_path / item).exists()]
    command = [sys.executable, "-m", "pytest", "--rootdir", str(workspace_path), *existing_tests, "-q"]
    if existing_tests:
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
        status = "passed" if exit_code == 0 and not missing_tests else "failed"
    elif missing_tests:
        exit_code = 2
        stdout = ""
        stderr = "Changed test files were listed but missing from workspace."
        status = "failed"
    else:
        exit_code = 0
        stdout = ""
        stderr = ""
        status = "skipped"
    return {
        "schema": CHANGED_FILE_TARGETED_RECEIPT_SCHEMA,
        "receiptId": f"receipt_changed_file_targeted_{uuid.uuid4().hex[:12]}",
        "missionId": _compact_text(mission_id, 120),
        "workspace": str(workspace_path),
        "status": status,
        "command": " ".join(command) if existing_tests else "",
        "exitCode": exit_code,
        "changedFiles": files,
        "targetedTestFiles": existing_tests,
        "missingTestFiles": missing_tests,
        "stdoutSummary": _compact_text(stdout, 1200),
        "stderrSummary": _compact_text(stderr, 1200),
        "nextAction": (
            "Continue to backend or UI smoke checks."
            if status == "passed"
            else "No direct changed-file test target was present; use the next applicable smoke check."
            if status == "skipped"
            else "Fix targeted test failures before broadening verification."
        ),
    }


@enforced("sv.ladder.receipt")
def build_backend_command_smoke_receipt(
    *,
    mission_id: str,
    workspace: str | Path,
    commands: list[list[str]] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    workspace_path = Path(workspace)
    bounded_commands = [
        [str(part) for part in command if str(part or "").strip()]
        for command in (commands or [])
        if isinstance(command, list) and command
    ][:6]
    command_receipts: list[dict[str, Any]] = []
    overall_status = "skipped"
    for command in bounded_commands:
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout_seconds or 1), 600)),
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
        command_status = "passed" if completed.returncode == 0 else "failed"
        command_receipts.append(
            {
                "command": " ".join(command),
                "exitCode": int(completed.returncode),
                "status": command_status,
                "stdoutSummary": _compact_text(completed.stdout, 1000),
                "stderrSummary": _compact_text(completed.stderr, 1000),
            }
        )
        if command_status == "failed":
            overall_status = "failed"
            break
        overall_status = "passed"
    return {
        "schema": BACKEND_COMMAND_SMOKE_RECEIPT_SCHEMA,
        "receiptId": f"receipt_backend_smoke_{uuid.uuid4().hex[:12]}",
        "missionId": _compact_text(mission_id, 120),
        "workspace": str(workspace_path),
        "status": overall_status,
        "commands": command_receipts,
        "skippedReason": "" if bounded_commands else "No backend smoke command was provided.",
        "nextAction": (
            "Continue to applicable UI or heavier verification checks."
            if overall_status == "passed"
            else "Provide a focused backend smoke command before claiming backend verification."
            if overall_status == "skipped"
            else "Fix backend smoke failure before continuing."
        ),
    }


@enforced("sv.ladder.receipt")
def build_ui_button_smoke_receipt(
    *,
    mission_id: str,
    target: str,
    interactions: list[dict[str, Any]] | None = None,
    proof_paths: list[str] | None = None,
) -> dict[str, Any]:
    rows = [_compact_interaction(item) for item in (interactions or []) if isinstance(item, dict)][:20]
    failed = [item for item in rows if item["status"] == "failed"]
    status = "skipped" if not rows else "failed" if failed else "passed"
    return {
        "schema": UI_BUTTON_SMOKE_RECEIPT_SCHEMA,
        "receiptId": f"receipt_ui_button_smoke_{uuid.uuid4().hex[:12]}",
        "missionId": _compact_text(mission_id, 120),
        "target": _compact_text(target, 240),
        "status": status,
        "interactions": rows,
        "proofPaths": _bounded_strings(proof_paths or [], limit=20, text_limit=240),
        "skippedReason": "" if rows else "No UI interactions were observed.",
        "nextAction": (
            "Continue to gated build/browser verification if capacity allows."
            if status == "passed"
            else "Collect real UI interaction proof before claiming button smoke coverage."
            if status == "skipped"
            else "Fix failed UI interaction before broader browser verification."
        ),
    }


def _compact_interaction(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or item.get("result") or "").strip().lower()
    normalized_status = "passed" if status in {"passed", "ok", "success"} else "failed"
    return {
        "label": _compact_text(item.get("label") or item.get("name") or "", 120),
        "selector": _compact_text(item.get("selector") or "", 160),
        "action": _compact_text(item.get("action") or "click", 80),
        "status": normalized_status,
        "observed": _compact_text(item.get("observed") or item.get("detail") or "", 240),
    }


def _step(
    step_id: str,
    label: str,
    *,
    required: bool,
    reason: str,
    capacity_gated: bool = False,
) -> dict[str, Any]:
    return {
        "stepId": step_id,
        "label": label,
        "required": bool(required),
        "capacityGated": bool(capacity_gated),
        "reason": reason,
        "status": "pending" if required else "skipped",
    }


def _contains_part(path: str, parts: set[str]) -> bool:
    normalized = Path(path.replace("\\", "/")).parts
    return any(part.lower() in parts for part in normalized)


def _bounded_strings(values: list[Any], *, limit: int, text_limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_text(value, text_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
