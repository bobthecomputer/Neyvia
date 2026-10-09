from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from .models import utc_now_iso

READER_ROLE = "context-reader"
EXECUTION_LANE_SEQUENCE = ("planner", "executor", "verifier")
LANE_SEQUENCE = (READER_ROLE, *EXECUTION_LANE_SEQUENCE)
LANE_PHASES = {
    "context-reader": "context",
    "planner": "plan",
    "executor": "execute",
    "verifier": "verify",
}
DEFAULT_LANE_MODEL = "gpt-5.6-sol"
DEFAULT_LANE_PROVIDER = "openai-codex"

LaneRunner = Callable[[dict[str, Any]], dict[str, Any]]


def runtime_lane_cycle_receipt_path(root: Path, cycle_id: str) -> Path:
    safe_id = _safe_identifier(cycle_id or "runtime_lane_cycle")
    return root / ".agent_control" / "runtime_lane_cycles" / f"{safe_id}.json"


def run_runtime_lane_cycle(
    *,
    root: Path,
    objective: str,
    runner: LaneRunner,
    route_overrides: list[dict[str, Any]] | None = None,
    default_runtime: str = "hermes",
    workspace_path: str | Path | None = None,
    mission_id: str = "",
    cycle_id: str = "",
    app_context: dict[str, Any] | None = None,
    instructions: str = "",
    reader_receipt: dict[str, Any] | None = None,
    continue_on_failure: bool = False,
    write_receipt: bool = True,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Runtime lane root is not a directory: {root}")
    clean_objective = str(objective or "").strip()
    if not clean_objective:
        raise ValueError("Runtime lane cycle objective is required.")
    resolved_cycle_id = _safe_identifier(cycle_id or f"lane_cycle_{uuid.uuid4().hex[:10]}")
    resolved_workspace = Path(workspace_path or root).expanduser()
    if not resolved_workspace.is_absolute():
        resolved_workspace = root / resolved_workspace
    resolved_workspace = resolved_workspace.resolve(strict=True)
    if not resolved_workspace.is_dir():
        raise ValueError(f"Runtime lane workspace is not a directory: {resolved_workspace}")
    try:
        resolved_workspace.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Runtime lane workspace is outside the selected root: {resolved_workspace}"
        ) from exc
    routes = normalize_lane_routes(route_overrides or [], default_runtime=default_runtime)
    started_at = utc_now_iso()
    reader_route = next(item for item in routes if item["role"] == READER_ROLE)
    normalized_reader_receipt = {
        "schema": "neyvia.context_reader_receipt.v1",
        "status": "completed",
        "workspacePath": str(resolved_workspace),
        **dict(reader_receipt or {}),
    }
    reader_summary = str(
        normalized_reader_receipt.get("summary")
        or (
            "Workspace context is bound to this cycle. "
            "No external cache result was claimed."
        )
    ).strip()
    prior_outputs: dict[str, str] = {
        READER_ROLE: json.dumps(normalized_reader_receipt, indent=2, sort_keys=True)[:6000]
    }
    lane_results: list[dict[str, Any]] = [
        {
            "role": READER_ROLE,
            "phase": reader_route["phase"],
            "runtimeId": reader_route["runtimeId"],
            "requestedRoute": reader_route,
            "actualRoute": {
                "provider": reader_route["provider"],
                "model": reader_route["model"],
                "effort": reader_route["effort"],
            },
            "status": str(normalized_reader_receipt.get("status") or "completed"),
            "error": str(normalized_reader_receipt.get("error") or ""),
            "assistantMessage": reader_summary,
            "turnReceipt": normalized_reader_receipt,
            "compartmentPath": "",
        }
    ]

    for role in EXECUTION_LANE_SEQUENCE:
        route = next(item for item in routes if item["role"] == role)
        prompt = build_lane_prompt(
            objective=clean_objective,
            role=role,
            prior_outputs=prior_outputs,
            app_context=app_context or {},
            instructions=instructions,
        )
        payload = {
            "message": prompt,
            "runtime": route["runtimeId"],
            "runtimeId": route["runtimeId"],
            "provider": route["provider"],
            "model": route["model"],
            "effort": route["effort"],
            "role": role,
            "route": {
                "role": role,
                "provider": route["provider"],
                "model": route["model"],
                "effort": route["effort"],
            },
            "sourceType": "runtime_lane_cycle",
            "sourceZone": role,
            "workspacePath": str(resolved_workspace),
            "missionId": mission_id,
            "sessionId": f"{resolved_cycle_id}_{role}",
            "systemContext": _lane_system_context(
                role=role,
                route=route,
                cycle_id=resolved_cycle_id,
            ),
        }
        try:
            result = runner(payload)
            if not isinstance(result, dict):
                result = {"status": "failed", "error": "Lane runner returned a non-object result."}
        except Exception as exc:  # pragma: no cover - defensive callback boundary
            result = {"status": "failed", "error": str(exc)}
        lane = _lane_result_from_runner(role=role, route=route, payload=payload, result=result)
        lane_results.append(lane)
        if lane["assistantMessage"]:
            prior_outputs[role] = lane["assistantMessage"]
        if lane["status"] == "failed" and not continue_on_failure:
            break

    failed_lanes = [item for item in lane_results if item["status"] == "failed"]
    completed_roles = {item["role"] for item in lane_results}
    missing_roles = [role for role in LANE_SEQUENCE if role not in completed_roles]
    receipt = {
        "schema": "fluxio.runtime_lane_cycle.v1",
        "cycleId": resolved_cycle_id,
        "missionId": mission_id,
        "root": str(root),
        "workspacePath": str(resolved_workspace),
        "objectiveSha256": hashlib.sha256(clean_objective.encode("utf-8")).hexdigest(),
        "objectivePreview": clean_objective[:500],
        "startedAt": started_at,
        "completedAt": utc_now_iso(),
        "status": "failed" if failed_lanes or missing_roles else "passed",
        "defaultRuntime": _normalize_runtime_id(default_runtime),
        "routeContract": {
            "schema": "fluxio.runtime_lane_route_contract.v1",
            "roles": routes,
            "separation": "context_reader_planner_executor_verifier",
        },
        "laneResults": lane_results,
        "failedLanes": failed_lanes,
        "missingRoles": missing_roles,
        "appContextAttached": bool(app_context),
        "instructionsAttached": bool(str(instructions or "").strip()),
    }
    if write_receipt:
        path = runtime_lane_cycle_receipt_path(root, resolved_cycle_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        receipt["receiptPath"] = str(path)
    return receipt


def normalize_lane_routes(
    route_overrides: list[dict[str, Any]],
    *,
    default_runtime: str = "hermes",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for role in LANE_SEQUENCE:
        route = _route_override_for_lane(route_overrides, role)
        is_reader = role == READER_ROLE
        provider = str(
            route.get("provider")
            or ("neyvia-context" if is_reader else DEFAULT_LANE_PROVIDER)
        ).strip().lower()
        model = str(
            route.get("model")
            or ("receipt-bound-cache" if is_reader else DEFAULT_LANE_MODEL)
        ).strip()
        effort = str(
            route.get("effort")
            or (
                "retrieval"
                if is_reader
                else "high"
                if role in {"planner", "verifier"}
                else "medium"
            )
        ).strip().lower()
        runtime_id = _normalize_runtime_id(
            route.get("runtimeId")
            or route.get("runtime_id")
            or route.get("runtime")
            or ("neyvia-context" if is_reader else default_runtime)
        )
        rows.append(
            {
                "role": role,
                "phase": LANE_PHASES[role],
                "runtimeId": runtime_id,
                "provider": provider,
                "model": model,
                "effort": effort,
                "budgetClass": str(
                    route.get("budgetClass")
                    or route.get("budget_class")
                    or ("efficient" if is_reader else "balanced")
                ).strip().lower(),
            }
        )
        seen.add(role)
    for route in route_overrides:
        if not isinstance(route, dict):
            continue
        role = str(route.get("role") or "").strip().lower()
        if not role or role in seen:
            continue
        provider = str(route.get("provider") or DEFAULT_LANE_PROVIDER).strip().lower()
        model = str(route.get("model") or DEFAULT_LANE_MODEL).strip()
        rows.append(
            {
                "role": role,
                "phase": str(route.get("phase") or role).strip().lower(),
                "runtimeId": _normalize_runtime_id(route.get("runtimeId") or route.get("runtime_id") or default_runtime),
                "provider": provider,
                "model": model,
                "effort": str(route.get("effort") or "medium").strip().lower(),
                "budgetClass": str(route.get("budgetClass") or route.get("budget_class") or "balanced").strip().lower(),
            }
        )
    return rows


def _route_override_for_lane(
    route_overrides: list[dict[str, Any]],
    role: str,
) -> dict[str, Any]:
    exact = next(
        (
            item
            for item in route_overrides
            if isinstance(item, dict)
            and str(item.get("role") or "").strip().lower() == role
        ),
        {},
    )
    if exact or role != "executor":
        return exact
    return next(
        (
            item
            for item in route_overrides
            if isinstance(item, dict)
            and str(item.get("role") or "").strip().lower()
            in {"frontend_executor", "backend_executor"}
        ),
        {},
    )


def build_lane_prompt(
    *,
    objective: str,
    role: str,
    prior_outputs: dict[str, str],
    app_context: dict[str, Any],
    instructions: str = "",
) -> str:
    normalized_role = str(role or "").strip().lower()
    lines = [
        "Neyvia runtime lane cycle.",
        f"Objective: {objective}",
        "",
        f"Current lane: {normalized_role}",
        "Return concrete, reviewable output. If you cannot perform the lane honestly, say exactly what blocks it.",
    ]
    if instructions.strip():
        lines.extend(["", "Operator instructions:", instructions.strip()])
    if app_context:
        lines.extend(
            [
                "",
                "Connected app/control context JSON:",
                json.dumps(app_context, indent=2, sort_keys=True)[:6000],
            ]
        )
    if prior_outputs:
        lines.extend(["", "Prior lane outputs:"])
        for prior_role in LANE_SEQUENCE:
            if prior_role in prior_outputs:
                lines.append(f"\n[{prior_role}]\n{prior_outputs[prior_role][:6000]}")
    if normalized_role == "planner":
        lines.extend(
            [
                "",
                "Planner task:",
                "- Produce a short execution plan.",
                "- Identify the exact executor handoff and verification checks.",
                "- Do not edit files in this lane.",
            ]
        )
    elif normalized_role == "executor":
        lines.extend(
            [
                "",
                "Executor task:",
                "- Use the planner output as the handoff.",
                "- Do the concrete implementation work available to your runtime.",
                "- Report changed files, commands, artifacts, and blockers.",
            ]
        )
    elif normalized_role == "verifier":
        lines.extend(
            [
                "",
                "Verifier task:",
                "- Review the planner and executor outputs.",
                "- Decide PASS or FAIL.",
                "- List the smallest correction needed if there is a failure.",
            ]
        )
    return "\n".join(lines).strip()


def _lane_result_from_runner(
    *,
    role: str,
    route: dict[str, str],
    payload: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    compartment = result.get("compartment") if isinstance(result.get("compartment"), dict) else {}
    receipt = (
        result.get("turnReceipt")
        if isinstance(result.get("turnReceipt"), dict)
        else compartment.get("turnReceipt")
        if isinstance(compartment.get("turnReceipt"), dict)
        else {}
    )
    assistant_message = str(
        receipt.get("assistantMessage")
        or receipt.get("finalMessage")
        or result.get("assistantMessage")
        or result.get("reply")
        or result.get("message")
        or ""
    ).strip()
    result_status = str(result.get("status") or receipt.get("status") or "completed").strip().lower()
    error = str(result.get("error") or result.get("errorMessage") or "").strip()
    failed = result_status in {"failed", "error", "timeout"} or bool(error) or not assistant_message
    actual_route = result.get("route") if isinstance(result.get("route"), dict) else {}
    return {
        "role": role,
        "phase": route["phase"],
        "runtimeId": str(result.get("runtime") or payload.get("runtime") or route["runtimeId"]),
        "requestedRoute": route,
        "actualRoute": actual_route,
        "status": "failed" if failed else "completed",
        "error": error or ("" if assistant_message else "Lane returned no readable model reply."),
        "assistantMessage": assistant_message,
        "turnReceipt": receipt,
        "compartmentPath": str(compartment.get("path") or compartment.get("compartmentPath") or ""),
    }


def _lane_system_context(*, role: str, route: dict[str, str], cycle_id: str) -> str:
    return (
        f"Runtime lane cycle {cycle_id}. Role={role}. "
        f"Runtime={route['runtimeId']}. Provider={route['provider']}. Model={route['model']}. "
        "Keep this lane separate from the other roles and report real blockers."
    )


def _safe_identifier(value: object) -> str:
    text = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value or "").strip()
    )
    return text[:100] or "runtime_lane_cycle"


def _normalize_runtime_id(value: object) -> str:
    normalized = str(value or "hermes").strip().lower().replace("_", "-")
    aliases = {
        "open-code": "opencode",
        "opencode-native": "opencode",
        "native-opencode": "opencode",
        "openclaw-local": "openclaw",
        "cursor-agent": "cursor",
        "cursor-native": "cursor",
    }
    return aliases.get(normalized, normalized) or "hermes"


from .proofs_d_runtime import checked as _checked
normalize_lane_routes = _checked("d.runtime.lane.aliases", normalize_lane_routes)

