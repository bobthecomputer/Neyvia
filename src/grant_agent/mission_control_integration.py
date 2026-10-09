"""Integration responsibilities for the control room.

Facade-owned collaborators are explicit keyword dependencies so callers retain
the established late-binding and monkeypatch seams.
"""

from __future__ import annotations

from pathlib import Path

from .models import Mission

def _integration_state(ready: bool, fallback: str = "needs_action") -> str:
    return "ready" if ready else fallback


def _integration_state_label(state: str) -> str:
    return {
        "ready": "Ready",
        "needs_action": "Needs action",
        "needs_login": "Needs login",
        "blocked": "Blocked",
        "not_reported": "Not reported",
    }.get(str(state or "").strip().lower(), "Not reported")


def _integration_category(
    *,
    category_id: str,
    label: str,
    points: int,
    ready: bool,
    state: str | None = None,
    detail: str = '',
    source: str = '',
    receipt_path: str = '',
    screenshot_path: str = '',
    command: str = '',
    evidence: dict | None = None,
    _integration_state,
    _integration_state_label,
) -> dict:
    normalized_state = str(state or _integration_state(ready)).strip().lower()
    if ready:
        normalized_state = "ready"
    earned = int(points) if ready else 0
    row = {
        "id": category_id,
        "label": label,
        "points": int(points),
        "earnedPoints": earned,
        "state": normalized_state,
        "statusLabel": _integration_state_label(normalized_state),
        "detail": detail or ("Live NAS evidence passed." if ready else "Live NAS evidence is still missing."),
        "source": source or "live_nas_evidence",
        "receiptPath": receipt_path,
        "screenshotPath": screenshot_path,
        "command": command,
        "evidence": evidence if isinstance(evidence, dict) else {},
    }
    return row


def _latest_json_report(
    root: Path,
    patterns: list[str],
    *,
    _load_json_file,
) -> tuple[dict, Path | None]:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in root.glob(pattern) if path.is_file())
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for path in candidates[:20]:
        payload = _load_json_file(path)
        if isinstance(payload, dict):
            return payload, path
    return {}, None


def _connected_app_category(
    connected_apps_snapshot: dict,
    *,
    app_id: str,
    label: str,
    points: int,
    _integration_category,
) -> dict:
    sessions = connected_apps_snapshot.get("connectedSessions", [])
    session = next(
        (
            item
            for item in sessions
            if isinstance(item, dict) and str(item.get("app_id") or item.get("appId") or "") == app_id
        ),
        {},
    )
    latest = session.get("latest_task_result", {}) if isinstance(session.get("latest_task_result"), dict) else {}
    payload = latest.get("payload", {}) if isinstance(latest.get("payload"), dict) else {}
    ui_hints = session.get("ui_hints", {}) if isinstance(session.get("ui_hints"), dict) else {}
    state_text = str(session.get("status") or "").lower()
    health_text = str(session.get("bridge_health") or "").lower()
    task_status = str(latest.get("status") or "").lower()
    ready = (
        state_text == "connected"
        and health_text == "healthy"
        and task_status == "completed"
        and bool(payload.get("bridgeOnline") or payload.get("healthOnline") or payload.get("apiOnline"))
    )
    start_command = str(ui_hints.get("startCommand") or payload.get("startCommand") or payload.get("command") or "")
    health_url = str(ui_hints.get("healthUrl") or payload.get("healthUrl") or "")
    missing = state_text in {"", "missing"} or health_text in {"", "missing"}
    blocked = health_text in {"offline", "missing"} or task_status == "blocked"
    state = "ready" if ready else ("blocked" if blocked or missing else "needs_action")
    detail = str(latest.get("resultSummary") or latest.get("result_summary") or "").strip()
    if not detail:
        detail = (
            f"{label} action receipt is complete and bridge health is live."
            if ready
            else f"{label} needs a completed app action receipt from the live NAS bridge."
        )
    if app_id == "mind-tower" and state != "ready" and "pnpm" in start_command.lower():
        detail = (
            "Mind Tower bridge is not proven; the NAS start route still needs pnpm or an equivalent runtime before this category can count."
        )
    return _integration_category(
        category_id=f"{app_id.replace('-', '_')}_action",
        label=label,
        points=points,
        ready=ready,
        state=state,
        detail=detail,
        source="bridgeLab.connectedSessions.latest_task_result",
        receipt_path=str(payload.get("receiptPath") or payload.get("logPath") or ""),
        command=start_command,
        evidence={
            "appId": app_id,
            "status": session.get("status", ""),
            "bridgeHealth": session.get("bridge_health", ""),
            "taskStatus": latest.get("status", ""),
            "healthUrl": health_url,
            "appRoot": session.get("app_root", ""),
            "apiOnline": bool(payload.get("apiOnline")),
            "bridgeOnline": bool(payload.get("bridgeOnline") or payload.get("healthOnline")),
        },
    )


def _runtime_turn_category(
    *,
    root: Path,
    runtime_compartments: dict,
    hermes_mission_evidence: dict,
    INTEGRATION_READINESS_POINTS,
    _integration_category,
    _latest_json_report,
) -> dict:
    items = runtime_compartments.get("items", []) if isinstance(runtime_compartments, dict) else []
    evidence_items = hermes_mission_evidence.get("items", []) if isinstance(hermes_mission_evidence, dict) else []
    candidate = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        receipt = item.get("turnReceipt") if isinstance(item.get("turnReceipt"), dict) else {}
        runtime = str(receipt.get("runtime") or item.get("runtime") or item.get("runtimeId") or "").lower()
        assistant_message = str(
            receipt.get("assistantMessage")
            or receipt.get("finalMessage")
            or item.get("openRuntimeMessage")
            or ""
        ).strip()
        provider = str(
            receipt.get("provider")
            or (receipt.get("route") or {}).get("provider")
            or (item.get("route") or {}).get("provider")
            or ""
        ).lower()
        if assistant_message and (
            runtime in {"hermes", "openruntime", ""}
            or "minimax" in provider
            or "openruntime" in assistant_message.lower()
        ):
            candidate = item
            break
    ready = bool(candidate)
    evidence_path = ""
    screenshot_path = ""
    if candidate:
        evidence_path = str(candidate.get("path") or candidate.get("compartmentPath") or "")
    screenshot_report, screenshot_report_path = _latest_json_report(
        root,
        [
            "tmp-ui-checks/openruntime-final-message/*check.json",
            "tmp-ui-checks/openruntime-final-message/*.json",
        ],
    )
    if isinstance(screenshot_report.get("artifacts"), dict):
        screenshot_path = str(screenshot_report["artifacts"].get("screenshotPath") or "")
    elif screenshot_report_path is not None:
        screenshot_path = str(screenshot_report.get("screenshotPath") or "")
    return _integration_category(
        category_id="hermes_openruntime_turn",
        label="Hermes/OpenRuntime turn receipt",
        points=INTEGRATION_READINESS_POINTS["hermes_openruntime_turn"],
        ready=ready,
        state="ready" if ready else ("needs_action" if evidence_items else "not_reported"),
        detail=(
            "A real Hermes/OpenRuntime turn receipt has a final model message and route evidence."
            if ready
            else "Run a live Hermes/OpenRuntime mission turn and save the final-message receipt."
        ),
        source="runtimeCompartments.turnReceipt",
        receipt_path=evidence_path,
        screenshot_path=screenshot_path,
        evidence={
            "runtimeCompartmentCount": len(items),
            "hermesEvidenceCount": len(evidence_items),
            "candidateSessionId": candidate.get("sessionId") or candidate.get("id") or "",
        },
    )


def _nas_live_data_category(
    root: Path,
    nas_deploy_readiness: dict,
    *,
    INTEGRATION_READINESS_POINTS,
    _integration_category,
    _load_json_file,
) -> dict:
    audit_path = root / ".agent_control" / "live_nas_system_audit_latest.json"
    audit = _load_json_file(audit_path)
    audit_ok = isinstance(audit, dict) and bool(audit.get("ok"))
    deploy_ready = bool(nas_deploy_readiness.get("ready")) if isinstance(nas_deploy_readiness, dict) else False
    ready = audit_ok or deploy_ready
    details = ""
    if isinstance(audit, dict):
        summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
        details = str(
            summary.get("readiness")
            or summary.get("status")
            or audit.get("status")
            or "Live NAS audit file was loaded."
        )
    if not details:
        details = (
            "Live NAS audit/deploy readiness is current."
            if ready
            else "Run NAS audit/sync so the score is based on current live NAS data."
        )
    return _integration_category(
        category_id="nas_live_data",
        label="NAS/live data freshness",
        points=INTEGRATION_READINESS_POINTS["nas_live_data"],
        ready=ready,
        state="ready" if ready else "needs_action",
        detail=details,
        source="live_nas_system_audit_latest.json",
        receipt_path=str(audit_path) if audit_path.exists() else "",
        evidence={
            "auditOk": audit_ok,
            "nasDeployReady": deploy_ready,
            "auditPathExists": audit_path.exists(),
        },
    )


def _provider_route_category(
    provider_auth_presence: dict[str, bool],
    *,
    INTEGRATION_READINESS_POINTS,
    _integration_category,
) -> dict:
    open_code_go = bool(provider_auth_presence.get("opencode-go"))
    minimax = bool(
        provider_auth_presence.get("minimax")
        or provider_auth_presence.get("minimax-oauth")
        or provider_auth_presence.get("minimax-portal")
    )
    codex_or_openai = bool(provider_auth_presence.get("openai-codex") or provider_auth_presence.get("openai"))
    ready = bool(open_code_go and minimax and codex_or_openai)
    missing = [
        label
        for label, passed in (
            ("OpenCodeGo OPENCODE_API_KEY", open_code_go),
            ("MiniMax route auth", minimax),
            ("OpenAI/Codex route auth", codex_or_openai),
        )
        if not passed
    ]
    return _integration_category(
        category_id="provider_routes",
        label="OpenClaw/OpenCodeGo/provider routing",
        points=INTEGRATION_READINESS_POINTS["provider_routes"],
        ready=ready,
        state="ready" if ready else "needs_login",
        detail=(
            "Provider route auth is present for OpenCodeGo, MiniMax, and OpenAI/Codex."
            if ready
            else f"Needs login: {', '.join(missing)}."
        ),
        source="provider_auth_presence",
        command="OPENCODE_API_KEY -> opencode-go/... model routes",
        evidence={
            "opencodeGo": open_code_go,
            "minimax": minimax,
            "openaiOrCodex": codex_or_openai,
            "quota": "Not reported by provider",
        },
    )


def _authenticated_phone_agent_category(
    root: Path,
    *,
    INTEGRATION_READINESS_POINTS,
    _integration_category,
    _latest_json_report,
) -> dict:
    agent_report, agent_path = _latest_json_report(
        root,
        [
            "tmp-ui-checks/authenticated-live-agent/*check.json",
            "tmp-ui-checks/authenticated-live-agent/*.json",
            ".agent_control/*live-agent*check.json",
        ],
    )
    phone_report, phone_path = _latest_json_report(
        root,
        [
            "tmp-ui-checks/authenticated-phone-progress/*check.json",
            "tmp-ui-checks/authenticated-phone-progress/*.json",
            ".agent_control/*phone*check.json",
        ],
    )
    agent_ok = bool(agent_report.get("ok"))
    phone_ok = bool(phone_report.get("ok"))
    ready = agent_ok and phone_ok
    screenshot_path = ""
    for report in (agent_report, phone_report):
        artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
        if artifacts.get("screenshotPath"):
            screenshot_path = str(artifacts.get("screenshotPath"))
            break
    return _integration_category(
        category_id="authenticated_phone_agent",
        label="Authenticated phone/live-Agent proof",
        points=INTEGRATION_READINESS_POINTS["authenticated_phone_agent"],
        ready=ready,
        state="ready" if ready else ("needs_action" if agent_report or phone_report else "not_reported"),
        detail=(
            "Authenticated desktop Agent and phone proof reports both passed."
            if ready
            else "Run authenticated live-Agent and phone proof checks; both must pass for 100%."
        ),
        source="authenticated_browser_proofs",
        receipt_path=str(agent_path or phone_path or ""),
        screenshot_path=screenshot_path,
        command="npm run verify:authenticated-live-agent && npm run verify:authenticated-phone",
        evidence={
            "agentOk": agent_ok,
            "phoneOk": phone_ok,
            "agentReportPath": str(agent_path or ""),
            "phoneReportPath": str(phone_path or ""),
        },
    )


def _bootstrap_authenticated_phone_agent_category(
    root: Path,
    *,
    INTEGRATION_READINESS_POINTS,
    _integration_category,
    _load_json_file,
) -> dict:
    latest_path = root / ".agent_control" / "authenticated_live_agent_latest.json"
    latest = _load_json_file(latest_path)
    latest_ok = isinstance(latest, dict) and bool(latest.get("ok"))
    screenshot_path = ""
    if isinstance(latest, dict):
        screenshot_path = str(latest.get("screenshotPath") or latest.get("screenshot_path") or "")
        artifacts = latest.get("artifacts") if isinstance(latest.get("artifacts"), dict) else {}
        screenshot_path = screenshot_path or str(artifacts.get("screenshotPath") or "")
    return _integration_category(
        category_id="authenticated_phone_agent",
        label="Authenticated phone/live-Agent proof",
        points=INTEGRATION_READINESS_POINTS["authenticated_phone_agent"],
        ready=False,
        state="needs_action" if latest_ok else "not_reported",
        detail=(
            "Latest live-Agent proof is pinned; full phone/live-Agent proof scan is deferred from bootstrap."
            if latest_ok
            else "Full phone/live-Agent proof scan is deferred from bootstrap."
        ),
        source="bootstrap_deferred_authenticated_browser_proofs",
        receipt_path=str(latest_path) if latest_path.exists() else "",
        screenshot_path=screenshot_path,
        command="Open full integration readiness to scan authenticated browser proofs.",
        evidence={
            "agentLatestOk": latest_ok,
            "proofScanDeferred": True,
        },
    )


def build_integration_readiness_snapshot(
    root: Path,
    *,
    missions: list[Mission] | None = None,
    connected_apps_snapshot: dict | None = None,
    runtime_compartments: dict | None = None,
    provider_auth_presence: dict[str, bool] | None = None,
    nas_deploy_readiness: dict | None = None,
    hermes_mission_evidence: dict | None = None,
    proof_scan_deferred: bool = False,
    INTEGRATION_READINESS_POINTS,
    _authenticated_phone_agent_category,
    _bootstrap_authenticated_phone_agent_category,
    _build_hermes_mission_evidence,
    _build_runtime_compartments_snapshot,
    _connected_app_category,
    _nas_live_data_category,
    _percent,
    _provider_auth_presence_from_env,
    _provider_route_category,
    _runtime_turn_category,
    build_nas_deploy_readiness_snapshot,
    utc_now_iso,
) -> dict:
    from .app_capability_standard import build_connected_apps_snapshot

    root = root.resolve()
    missions = missions or []
    connected_apps_snapshot = connected_apps_snapshot or build_connected_apps_snapshot(root)
    provider_auth_presence = provider_auth_presence or _provider_auth_presence_from_env()
    runtime_compartments = runtime_compartments or _build_runtime_compartments_snapshot(
        root,
        missions,
        runtime_statuses=[],
        setup_health={"actionHistory": []},
        storage_bridge={},
        provider_auth_presence=provider_auth_presence,
    )
    nas_deploy_readiness = nas_deploy_readiness or build_nas_deploy_readiness_snapshot(root)
    hermes_mission_evidence = hermes_mission_evidence or _build_hermes_mission_evidence(root, missions, [])

    categories = [
        _nas_live_data_category(root, nas_deploy_readiness),
        _runtime_turn_category(
            root=root,
            runtime_compartments=runtime_compartments,
            hermes_mission_evidence=hermes_mission_evidence,
        ),
        _connected_app_category(
            connected_apps_snapshot,
            app_id="oratio-viva",
            label="Oratio connected-app action",
            points=INTEGRATION_READINESS_POINTS["oratio_viva_action"],
        ),
        _connected_app_category(
            connected_apps_snapshot,
            app_id="jbheaven",
            label="JBHABCN connected-app action",
            points=INTEGRATION_READINESS_POINTS["jbhabcn_action"],
        ),
        _connected_app_category(
            connected_apps_snapshot,
            app_id="mind-tower",
            label="Mind Tower connected-app action",
            points=INTEGRATION_READINESS_POINTS["mind_tower_action"],
        ),
        _provider_route_category(provider_auth_presence),
        (
            _bootstrap_authenticated_phone_agent_category(root)
            if proof_scan_deferred
            else _authenticated_phone_agent_category(root)
        ),
    ]
    score = sum(int(item.get("earnedPoints") or 0) for item in categories)
    max_score = sum(int(item.get("points") or 0) for item in categories)
    blockers = [
        {
            "id": item.get("id", ""),
            "label": item.get("label", ""),
            "state": item.get("state", ""),
            "statusLabel": item.get("statusLabel", ""),
            "detail": item.get("detail", ""),
        }
        for item in categories
        if item.get("state") != "ready"
    ]
    status = "ready" if score == max_score and max_score > 0 else ("blocked" if blockers else "unknown")
    return {
        "schema": "fluxio.integration_readiness.v1",
        "source": "live_nas_evidence_only",
        "score": score,
        "maxScore": max_score,
        "percent": _percent(score, max_score),
        "status": status,
        "statusLabel": "100% usable" if status == "ready" else f"{_percent(score, max_score)}% usable",
        "lastVerifiedAt": utc_now_iso(),
        "categories": categories,
        "evidence": [
            {
                "id": item.get("id", ""),
                "label": item.get("label", ""),
                "source": item.get("source", ""),
                "receiptPath": item.get("receiptPath", ""),
                "screenshotPath": item.get("screenshotPath", ""),
                "command": item.get("command", ""),
                "state": item.get("state", ""),
            }
            for item in categories
        ],
        "blockers": blockers,
        "assumptions": [
            "Only live NAS data, app endpoints, runtime receipts, and authenticated screenshots count.",
            "Demo/sample data is allowed only when labeled and never earns readiness points.",
            "Provider quota is recorded as Not reported when the provider does not expose it.",
        ],
    }



__all__ = [
    "_integration_state",
    "_integration_state_label",
    "_integration_category",
    "_latest_json_report",
    "_connected_app_category",
    "_runtime_turn_category",
    "_nas_live_data_category",
    "_provider_route_category",
    "_authenticated_phone_agent_category",
    "_bootstrap_authenticated_phone_agent_category",
    "build_integration_readiness_snapshot",
]
