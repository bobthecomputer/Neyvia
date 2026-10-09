"""Harness responsibilities for the control room.

Facade-owned collaborators are explicit keyword dependencies so callers retain
the established late-binding and monkeypatch seams.
"""

from __future__ import annotations

from pathlib import Path

from .models import Mission

def _harness_efficiency_recommendation(
    *,
    total_runs: int,
    completion_rate: int,
    delegated_run_rate: int,
    resume_run_rate: int,
    resume_completion_rate: int,
    approval_pause_rate: int,
    verification_pause_rate: int,
    stale_heartbeat_count: int,
) -> str:
    if total_runs == 0:
        return (
            "No local harness runs are recorded yet. Start one real mission to measure "
            "pause friction, delegated session health, and verification efficiency."
        )
    if stale_heartbeat_count > 0:
        return (
            "Delegated runtime heartbeat went stale recently. Verify runtime health "
            "before widening unattended autonomy."
        )
    if delegated_run_rate < 20 and total_runs >= 4:
        return (
            "Delegated runtime usage is still low in recent runs. Run more real delegated "
            "missions before claiming long-run readiness."
        )
    if resume_run_rate >= 20 and resume_completion_rate < 60:
        return (
            "Resume continuity is still weak after restart. Improve resume completion "
            "before expanding unattended missions."
        )
    if completion_rate < 50:
        return (
            "Completion rate is below 50% on recent runs. Stabilize runtime and verification "
            "before widening autonomy."
        )
    if approval_pause_rate >= 35:
        return (
            "Approval waits dominate recent runs. Keep the hybrid harness, but reduce "
            "unnecessary approval pressure before widening delegation."
        )
    if verification_pause_rate >= 25:
        return (
            "Verification failures are the main pause source. Improve verification "
            "defaults before increasing autonomy."
        )
    return (
        "Neyvia hybrid looks stable on recent local runs. Keep it as production and "
        "use the legacy harness only as a benchmark."
    )


def _route_trust_label(
    task_type: str,
    *,
    ROUTE_TRUST_TASK_LABELS,
) -> str:
    return ROUTE_TRUST_TASK_LABELS.get(task_type, task_type.replace("_", " ").title())


def _route_trust_task_type(
    payload: dict,
    *,
    ROUTE_TRUST_SAMPLE_TEMPLATES,
    ROUTE_TRUST_TASK_KEYWORDS,
) -> str:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    feedback = state.get("operator_value_feedback") if isinstance(state, dict) else {}
    if isinstance(feedback, dict):
        task_type = str(
            feedback.get("routeTrustTaskType")
            or feedback.get("route_trust_task_type")
            or ""
        ).strip()
        if task_type:
            return task_type
    objective = f" {payload.get('objective') or ''} ".lower()
    for task_type, template in ROUTE_TRUST_SAMPLE_TEMPLATES.items():
        sample_objective = f" {template.get('objective') or ''} ".lower()
        if sample_objective.strip() and sample_objective in objective:
            return task_type
    route_configs = payload.get("route_configs", [])
    if isinstance(route_configs, list):
        for route in route_configs:
            if not isinstance(route, dict):
                continue
            task_type = str(route.get("task_type") or route.get("taskType") or "").strip()
            if task_type:
                return task_type
    best_task = "general_coding"
    best_count = 0
    for task_type, keywords in ROUTE_TRUST_TASK_KEYWORDS.items():
        count = sum(1 for keyword in keywords if keyword in objective)
        if count > best_count:
            best_task = task_type
            best_count = count
    return best_task


def _operator_value_feedback_signal(feedback: object) -> dict:
    if not isinstance(feedback, dict):
        return {}
    try:
        score = int(feedback.get("score"))
    except (TypeError, ValueError):
        score = -1
    outcome = str(feedback.get("outcome") or "").strip().lower()
    trust_signal = str(
        feedback.get("trustSignal") or feedback.get("trust_signal") or ""
    ).strip().lower()
    if score < 0 and not outcome and not trust_signal:
        return {}
    return {
        "score": score,
        "promote": trust_signal == "promote" or outcome == "useful" or score >= 80,
        "deprioritize": trust_signal == "deprioritize" or outcome == "not_useful" or (0 <= score < 50),
    }


def _route_trust_closeout_low_value(item: dict) -> bool:
    try:
        score = int(item.get("score") or item.get("operatorValueScore") or -1)
    except (TypeError, ValueError):
        score = -1
    outcome = str(item.get("outcome") or item.get("operatorOutcome") or "").strip().lower()
    trust_signal = str(item.get("trustSignal") or item.get("trust_signal") or "").strip().lower()
    return (0 <= score < 50) or outcome == "not_useful" or trust_signal == "deprioritize"


def _route_trust_repair_steps(
    low_value_items: list[dict],
    coverage: dict[str, dict],
    *,
    _route_trust_label,
) -> list[dict]:
    plan: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in low_value_items:
        task_type = str(item.get("taskType") or "general_coding").strip() or "general_coding"
        mission_id = str(item.get("missionId") or item.get("mission_id") or "").strip()
        key = (task_type, mission_id)
        if key in seen:
            continue
        seen.add(key)
        label = str(coverage.get(task_type, {}).get("label") or _route_trust_label(task_type))
        if task_type == "frontend_design":
            executor_policy = (
                "OpenCodeGo GLM-5.2 when authenticated and available; otherwise Codex gpt-5.5 high "
                "with explicit provider-unavailable evidence; do not silently downgrade to GLM-5"
            )
        elif task_type in {"data_f1_analytics", "hardware_electrical", "research_analysis"}:
            executor_policy = "Codex gpt-5.5 high with dataset/artifact/browser-preview verification gates"
        else:
            executor_policy = "Codex gpt-5.5 high until the next value-scored sample proves a better route"
        repair_action = (
            f"Repair the {label} route before another promotion: require a served artifact, "
            "proof digest, browser preview/check result, and operator value closeout before trust can rise."
        )
        try:
            score = int(item.get("score") or item.get("operatorValueScore") or 0)
        except (TypeError, ValueError):
            score = 0
        plan.append(
            {
                "schema": "fluxio.route_trust_repair_step.v1",
                "taskType": task_type,
                "label": label,
                "missionId": mission_id,
                "score": score,
                "missionStatus": str(item.get("missionStatus") or item.get("status") or ""),
                "repairAction": repair_action,
                "modelPolicy": (
                    "Hermes harness; planner/verifier use openai-codex gpt-5.5 high; "
                    f"executor uses {executor_policy}; never claim a provider path when auth/runtime evidence is missing."
                ),
                "trustEffect": "Do not promote this task category until the next sample scores at least 80 with no failed verification.",
            }
        )
    return plan


def _route_trust_row(
    coverage: dict[str, dict],
    task_type: str,
    *,
    _route_trust_label,
) -> dict:
    return coverage.setdefault(
        task_type,
        {
            "taskType": task_type,
            "label": _route_trust_label(task_type),
            "routeSamples": 0,
            "operatorValueSamples": 0,
            "operatorPromoteCount": 0,
            "operatorDeprioritizeCount": 0,
            "latestMissionId": "",
        },
    )


def _shell_quote(value: object) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _route_trust_sampling_template(
    task_type: str,
    row: dict[str, object],
    *,
    repair: dict[str, object] | None = None,
    ROUTE_TRUST_SAMPLE_TEMPLATES,
    _route_trust_label,
    _shell_quote,
    urlencode,
) -> dict[str, object]:
    template = ROUTE_TRUST_SAMPLE_TEMPLATES.get(
        task_type,
        ROUTE_TRUST_SAMPLE_TEMPLATES["general_coding"],
    )
    label = str(row.get("label") or _route_trust_label(task_type))
    objective = str(template["objective"])
    success_checks = [str(item) for item in template.get("successChecks", []) if str(item).strip()]
    runtime = str(template.get("preferredRuntime") or "auto")
    budget_hours = int(template.get("budgetHours") or 4)
    sample_title = str(template.get("title") or f"{label} trust sample")
    route_intent = (
        "Gather live, value-scored evidence so route and skill trust can move "
        "from static defaults to operator-proven task routing."
    )
    operator_closeout_instruction = (
        "After the artifact is tested, complete the mission with an operator value "
        "score so this category contributes to route and skill trust."
    )
    if repair:
        failed_mission_id = str(repair.get("missionId") or "").strip()
        repair_action = str(repair.get("repairAction") or "").strip()
        model_policy = str(repair.get("modelPolicy") or "").strip()
        sample_title = f"Repair {label} route trust sample"
        objective = (
            f"Repair route trust for {label}"
            + (f" after low-value mission {failed_mission_id}" if failed_mission_id else "")
            + f". {repair_action} Base task: {objective} "
            "Hard requirements: create or serve a reviewable artifact, capture browser/preview proof, "
            "write a proof digest, and only allow route trust to rise after an operator-value closeout "
            "scores at least 80 with no failed verification."
        )
        success_checks = [
            *success_checks,
            "Create or serve a reviewable artifact for this repaired route sample.",
            "Capture browser or preview verification evidence and attach it to the proof digest.",
            "Record why the previous low-value sample failed and what changed in this repair attempt.",
            "Do not promote route trust unless the operator-value closeout is at least 80 with no failed verification.",
        ]
        if model_policy:
            success_checks.append(f"Follow repaired model policy: {model_policy}")
        route_intent = (
            "Repair a low-value route before more sampling: the mission must prove artifact quality, "
            "browser verification, and operator value before trust can recover."
        )
        operator_closeout_instruction = (
            "After testing the repaired artifact, complete this mission with an operator value score; "
            "scores below 80 keep the route in repair."
        )
    query = urlencode(
        {
            "launch": "mission",
            "runtime": runtime,
            "profile": "builder",
            "mode": "Autopilot",
            "objective": objective,
            "successCheck": success_checks,
        },
        doseq=True,
    )
    success_check_args = " ".join(
        f"--success-check {_shell_quote(item)}" for item in success_checks
    )
    cli_command = (
        "python -m grant_agent.cli mission-quickstart --root . "
        f"--runtime {runtime} --mode Autopilot --budget-hours {budget_hours} "
        f"--objective {_shell_quote(objective)}"
    )
    if success_check_args:
        cli_command = f"{cli_command} {success_check_args}"
    return {
        "schema": "fluxio.route_trust_sampling_template.v1",
        "taskType": task_type,
        "label": label,
        "sampleMissionTitle": sample_title,
        "sampleMissionObjective": objective,
        "sampleMissionMode": "Autopilot",
        "sampleMissionRuntime": runtime,
        "sampleMissionBudgetHours": budget_hours,
        "sampleMissionSuccessChecks": success_checks,
        "sampleMissionUrlPath": f"/control?{query}",
        "sampleMissionCliCommand": cli_command,
        "routeIntent": route_intent,
        "operatorCloseoutInstruction": operator_closeout_instruction,
    }


def _build_route_trust_coverage_snapshot(
    root: Path,
    *,
    sessions: list[Path],
    HARNESS_RECENT_RUN_LIMIT,
    ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
    ROUTE_TRUST_TASK_LABELS,
    _build_route_outcome_trends_for_trust,
    _load_json_file,
    _operator_value_feedback_signal,
    _quarantined_route_count,
    _route_outcome_quarantines,
    _route_trust_closeout_low_value,
    _route_trust_repair_steps,
    _route_trust_row,
    _route_trust_sampling_template,
    _route_trust_task_type,
) -> dict:
    coverage = {
        task_type: {
            "taskType": task_type,
            "label": label,
            "routeSamples": 0,
            "operatorValueSamples": 0,
            "operatorPromoteCount": 0,
            "operatorDeprioritizeCount": 0,
            "latestMissionId": "",
        }
        for task_type, label in ROUTE_TRUST_TASK_LABELS.items()
    }
    for session in sessions[:HARNESS_RECENT_RUN_LIMIT]:
        state_path = session / "state.json"
        if not state_path.exists():
            continue
        payload = _load_json_file(state_path)
        if not isinstance(payload, dict) or not isinstance(payload.get("route_configs"), list):
            continue
        status = str(payload.get("autopilot_status") or "").strip().lower()
        pause_reason = str(payload.get("autopilot_pause_reason") or "").strip().lower()
        if status not in {"completed", "failed", "blocked"} and pause_reason not in {
            "verification_failed",
            "runtime_budget",
            "delegated_runtime_failed",
        }:
            continue
        _route_trust_row(coverage, _route_trust_task_type(payload))["routeSamples"] += 1

    mission_status_by_id: dict[str, str] = {}
    missions_payload = _load_json_file(root / ".agent_control" / "missions.json")
    if isinstance(missions_payload, list):
        for mission in missions_payload:
            if not isinstance(mission, dict):
                continue
            mission_id = str(mission.get("mission_id") or mission.get("missionId") or "").strip()
            state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
            if mission_id:
                mission_status_by_id[mission_id] = str(
                    state.get("status") or mission.get("status") or ""
                ).strip().lower()
            state = mission.get("state") if isinstance(mission.get("state"), dict) else {}
            feedback = _operator_value_feedback_signal(state.get("operator_value_feedback"))
            if not feedback:
                continue
            row = _route_trust_row(coverage, _route_trust_task_type(mission))
            row["operatorValueSamples"] += 1
            row["operatorPromoteCount"] += 1 if feedback.get("promote") else 0
            row["operatorDeprioritizeCount"] += 1 if feedback.get("deprioritize") else 0
            row["latestMissionId"] = str(mission.get("mission_id") or mission.get("missionId") or "")

    sampling_report = _load_json_file(root / ".agent_control" / "route_trust_sampling" / "latest.json")
    closeout_report = _load_json_file(root / ".agent_control" / "route_trust_sampling" / "closeout_review_latest.json")
    launched = (
        sampling_report.get("launchedSamplingMissions", [])
        if isinstance(sampling_report, dict) and isinstance(sampling_report.get("launchedSamplingMissions"), list)
        else []
    )
    active_statuses = {"running", "queued", "launching", "needs_approval", "verification_pending"}
    active_sampling_ids = []
    for item in launched:
        if not isinstance(item, dict):
            continue
        mission_id = str(item.get("missionId") or item.get("mission_id") or "").strip()
        status = mission_status_by_id.get(mission_id) or str(item.get("missionStatus") or item.get("status") or "").strip().lower()
        if mission_id and status in active_statuses:
            active_sampling_ids.append(mission_id)

    closeout_proposals = (
        closeout_report.get("proposals", [])
        if isinstance(closeout_report, dict) and isinstance(closeout_report.get("proposals"), list)
        else []
    )
    low_value_items = [
        item for item in closeout_proposals if isinstance(item, dict) and _route_trust_closeout_low_value(item)
    ]
    repair_plan = _route_trust_repair_steps(low_value_items, coverage)
    repair_by_task = {item["taskType"]: item for item in repair_plan}
    route_outcome_trends = _build_route_outcome_trends_for_trust(root)
    quarantined_routes = _route_outcome_quarantines(route_outcome_trends)
    quarantined_route_count = _quarantined_route_count(quarantined_routes)

    rows = []
    for row in coverage.values():
        value_samples = int(row["operatorValueSamples"])
        useful_samples = int(row.get("operatorPromoteCount") or 0)
        low_value_samples = int(row.get("operatorDeprioritizeCount") or 0)
        missing = max(0, ROUTE_TRUST_REQUIRED_VALUE_SAMPLES - useful_samples)
        status = "proven" if missing == 0 else "sampling"
        repair = repair_by_task.get(str(row["taskType"]))
        repair_required = repair is not None
        rows.append(
            {
                **row,
                "requiredOperatorValueSamples": ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
                "usefulOperatorValueSamples": useful_samples,
                "lowValueOperatorSamples": low_value_samples,
                "missingOperatorValueSamples": missing,
                "status": "repair" if repair_required else status,
                "repairRequired": repair_required,
                "repairMissionId": repair.get("missionId", "") if repair else "",
                "repairAction": repair.get("repairAction", "") if repair else "",
                "modelPolicy": repair.get("modelPolicy", "") if repair else "",
                **_route_trust_sampling_template(str(row["taskType"]), row, repair=repair),
                "nextAction": (
                    repair["repairAction"]
                    if repair_required
                    else (
                    "Route and skill trust have enough useful value-scored samples for this task category."
                    if status == "proven"
                    else (
                        f"Run {missing} more useful value-scored {row['label']} mission(s); "
                        f"{value_samples} scored sample(s), {low_value_samples} low-value sample(s), "
                        f"and {useful_samples} useful sample(s) are recorded."
                    )
                    )
                ),
            }
        )
    rows.sort(
        key=lambda item: (
            not item["repairRequired"],
            item["status"] != "sampling",
            item["missingOperatorValueSamples"],
            item["taskType"],
        )
    )
    sampling = [item for item in rows if item["status"] in {"sampling", "repair"}]
    return {
        "schema": "fluxio.route_trust_coverage.v1",
        "requiredOperatorValueSamples": ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
        "taskCoverage": rows,
        "provenTaskCount": sum(1 for item in rows if item["status"] == "proven"),
        "samplingTaskCount": sum(1 for item in rows if item["status"] == "sampling"),
        "activeSamplingMissionCount": len(active_sampling_ids),
        "activeSamplingMissionIds": active_sampling_ids,
        "lowValueCloseoutCount": len(low_value_items),
        "quarantinedRouteCount": quarantined_route_count,
        "quarantinedRoutes": quarantined_routes,
        "routeOutcomeTrendSchema": str(route_outcome_trends.get("schema") or ""),
        "repairPlanStatus": "required" if repair_plan else ("sampling_active" if active_sampling_ids else "clear"),
        "repairPlan": repair_plan,
        "nextRepairStep": repair_plan[0]["repairAction"] if repair_plan else "",
        "operatorConfidenceScore": (
            68
            if repair_plan
            else 72
            if active_sampling_ids
            else 92
            if not sampling
            else 64
        ),
        "nextSamplingPlan": sampling[:5],
        "nextAction": (
            repair_plan[0]["repairAction"]
            if repair_plan
            else (
            sampling[0]["nextAction"]
            if sampling
            else "All tracked task categories have enough value-scored route and skill trust samples."
            )
        ),
    }


def _route_trust_payload_for_mission(
    mission: Mission,
    *,
    asdict,
    is_dataclass,
) -> dict:
    route_configs = []
    for route in mission.route_configs or []:
        if is_dataclass(route):
            route_configs.append(asdict(route))
        elif isinstance(route, dict):
            route_configs.append(dict(route))
    return {
        "mission_id": mission.mission_id,
        "objective": mission.objective,
        "title": mission.title,
        "route_configs": route_configs,
        "state": {
            "status": mission.state.status,
            "operator_value_feedback": mission.state.operator_value_feedback,
        },
    }


def _build_route_outcome_trends_for_trust(root: Path) -> dict:
    try:
        from .fluxio_harness import build_route_outcome_trends
    except Exception:
        return {}
    try:
        trends = build_route_outcome_trends(root)
    except Exception:
        return {}
    return trends if isinstance(trends, dict) else {}


def _route_outcome_quarantines(trends: dict) -> dict:
    quarantined = trends.get("quarantinedRoutes") if isinstance(trends, dict) else {}
    return quarantined if isinstance(quarantined, dict) else {}


def _quarantined_route_count(quarantined_routes: dict) -> int:
    count = 0
    for task_rows in quarantined_routes.values() if isinstance(quarantined_routes, dict) else []:
        if not isinstance(task_rows, dict):
            continue
        for role_rows in task_rows.values():
            if isinstance(role_rows, list):
                count += len(role_rows)
    return count


def _build_route_trust_coverage_summary(
    root: Path,
    *,
    missions: list[Mission],
    include_route_outcome_trends: bool = True,
    ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
    ROUTE_TRUST_TASK_LABELS,
    _build_route_outcome_trends_for_trust,
    _load_json_file,
    _operator_value_feedback_signal,
    _quarantined_route_count,
    _route_outcome_quarantines,
    _route_trust_closeout_low_value,
    _route_trust_payload_for_mission,
    _route_trust_repair_steps,
    _route_trust_row,
    _route_trust_sampling_template,
    _route_trust_task_type,
) -> dict:
    coverage = {
        task_type: {
            "taskType": task_type,
            "label": label,
            "routeSamples": 0,
            "operatorValueSamples": 0,
            "operatorPromoteCount": 0,
            "operatorDeprioritizeCount": 0,
            "latestMissionId": "",
        }
        for task_type, label in ROUTE_TRUST_TASK_LABELS.items()
    }
    mission_status_by_id: dict[str, str] = {}
    for mission in missions:
        payload = _route_trust_payload_for_mission(mission)
        mission_status_by_id[mission.mission_id] = str(mission.state.status or "").strip().lower()
        status = str(mission.state.status or "").strip().lower()
        if mission.route_configs and status in {"completed", "failed", "blocked", "verification_failed", "stopped"}:
            _route_trust_row(coverage, _route_trust_task_type(payload))["routeSamples"] += 1
        feedback = _operator_value_feedback_signal(mission.state.operator_value_feedback)
        if not feedback:
            continue
        row = _route_trust_row(coverage, _route_trust_task_type(payload))
        row["operatorValueSamples"] += 1
        row["operatorPromoteCount"] += 1 if feedback.get("promote") else 0
        row["operatorDeprioritizeCount"] += 1 if feedback.get("deprioritize") else 0
        row["latestMissionId"] = mission.mission_id

    sampling_report = _load_json_file(root / ".agent_control" / "route_trust_sampling" / "latest.json")
    closeout_report = _load_json_file(root / ".agent_control" / "route_trust_sampling" / "closeout_review_latest.json")
    launched = (
        sampling_report.get("launchedSamplingMissions", [])
        if isinstance(sampling_report, dict) and isinstance(sampling_report.get("launchedSamplingMissions"), list)
        else []
    )
    active_statuses = {"running", "queued", "launching", "needs_approval", "verification_pending"}
    active_sampling_ids = []
    for item in launched:
        if not isinstance(item, dict):
            continue
        mission_id = str(item.get("missionId") or item.get("mission_id") or "").strip()
        status = mission_status_by_id.get(mission_id) or str(item.get("missionStatus") or item.get("status") or "").strip().lower()
        if mission_id and status in active_statuses:
            active_sampling_ids.append(mission_id)

    closeout_proposals = (
        closeout_report.get("proposals", [])
        if isinstance(closeout_report, dict) and isinstance(closeout_report.get("proposals"), list)
        else []
    )
    low_value_items = [
        item for item in closeout_proposals if isinstance(item, dict) and _route_trust_closeout_low_value(item)
    ]
    repair_plan = _route_trust_repair_steps(low_value_items, coverage)
    repair_by_task = {item["taskType"]: item for item in repair_plan}
    route_outcome_trends = (
        _build_route_outcome_trends_for_trust(root)
        if include_route_outcome_trends
        else {
            "schema": "fluxio.route_outcome_trends.v1",
            "summaryDeferred": True,
        }
    )
    quarantined_routes = (
        _route_outcome_quarantines(route_outcome_trends)
        if include_route_outcome_trends
        else {}
    )
    quarantined_route_count = _quarantined_route_count(quarantined_routes)

    rows = []
    for row in coverage.values():
        value_samples = int(row["operatorValueSamples"])
        useful_samples = int(row.get("operatorPromoteCount") or 0)
        low_value_samples = int(row.get("operatorDeprioritizeCount") or 0)
        missing = max(0, ROUTE_TRUST_REQUIRED_VALUE_SAMPLES - useful_samples)
        status = "proven" if missing == 0 else "sampling"
        repair = repair_by_task.get(str(row["taskType"]))
        repair_required = repair is not None
        rows.append(
            {
                **row,
                "requiredOperatorValueSamples": ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
                "usefulOperatorValueSamples": useful_samples,
                "lowValueOperatorSamples": low_value_samples,
                "missingOperatorValueSamples": missing,
                "status": "repair" if repair_required else status,
                "repairRequired": repair_required,
                "repairMissionId": repair.get("missionId", "") if repair else "",
                "repairAction": repair.get("repairAction", "") if repair else "",
                "modelPolicy": repair.get("modelPolicy", "") if repair else "",
                **_route_trust_sampling_template(str(row["taskType"]), row, repair=repair),
                "nextAction": (
                    repair["repairAction"]
                    if repair_required
                    else (
                        "Route and skill trust have enough useful value-scored samples for this task category."
                        if status == "proven"
                        else (
                            f"Run {missing} more useful value-scored {row['label']} mission(s); "
                            f"{value_samples} scored sample(s), {low_value_samples} low-value sample(s), "
                            f"and {useful_samples} useful sample(s) are recorded."
                        )
                    )
                ),
            }
        )
    rows.sort(
        key=lambda item: (
            not item["repairRequired"],
            item["status"] != "sampling",
            item["missingOperatorValueSamples"],
            item["taskType"],
        )
    )
    sampling = [item for item in rows if item["status"] in {"sampling", "repair"}]
    return {
        "schema": "fluxio.route_trust_coverage.v1",
        "source": "mission_store_route_trust_summary",
        "requiredOperatorValueSamples": ROUTE_TRUST_REQUIRED_VALUE_SAMPLES,
        "taskCoverage": rows,
        "provenTaskCount": sum(1 for item in rows if item["status"] == "proven"),
        "samplingTaskCount": sum(1 for item in rows if item["status"] == "sampling"),
        "activeSamplingMissionCount": len(active_sampling_ids),
        "activeSamplingMissionIds": active_sampling_ids,
        "lowValueCloseoutCount": len(low_value_items),
        "quarantinedRouteCount": quarantined_route_count,
        "quarantinedRoutes": quarantined_routes if include_route_outcome_trends else {},
        "routeOutcomeTrendSchema": str(route_outcome_trends.get("schema") or ""),
        "routeOutcomeTrendsDeferred": not include_route_outcome_trends,
        "repairPlanStatus": "required" if repair_plan else ("sampling_active" if active_sampling_ids else "clear"),
        "repairPlan": repair_plan,
        "nextRepairStep": repair_plan[0]["repairAction"] if repair_plan else "",
        "operatorConfidenceScore": (
            68
            if repair_plan
            else 72
            if active_sampling_ids
            else 92
            if not sampling
            else 64
        ),
        "nextSamplingPlan": sampling[:5],
        "nextAction": (
            repair_plan[0]["repairAction"]
            if repair_plan
            else (
                sampling[0]["nextAction"]
                if sampling
                else "All tracked task categories have enough value-scored route and skill trust samples."
            )
        ),
    }


def _build_harness_parity_matrix() -> list[dict]:
    capabilities = [
        (
            "Mission planning and resume",
            "native",
            "native",
            "partial",
            "Syntelos wraps both Hermes and OpenClaw into durable mission state; legacy remains benchmark-only.",
        ),
        (
            "Planner/executor/verifier lanes",
            "bridged",
            "native",
            "missing",
            "Hermes supplies supervised delegation while OpenClaw exposes sub-agent commands and ACP controls.",
        ),
        (
            "Provider/model switching",
            "native",
            "native",
            "partial",
            "Shared provider auth detection now reads env, Hermes auth, OpenClaw auth, and Codex OAuth stores.",
        ),
        (
            "Approval gates",
            "native",
            "native",
            "partial",
            "Both modern runtimes are normalized into Syntelos approval history and proof state.",
        ),
        (
            "Tool/MCP/plugin access",
            "bridged",
            "native",
            "partial",
            "OpenClaw has the richer live command catalog; Hermes remains the steadier supervised mission lane.",
        ),
        (
            "Proof artifacts and digest",
            "native",
            "bridged",
            "partial",
            "Syntelos turns both runtime event streams into mission proof, checks, and digest artifacts.",
        ),
        (
            "Phone/tablet web supervision",
            "native",
            "native",
            "missing",
            "Both runtimes surface through the same web summary and notification feed.",
        ),
    ]
    return [
        {
            "capability": capability,
            "hermes": hermes,
            "openclaw": openclaw,
            "legacy": legacy,
            "summary": summary,
        }
        for capability, hermes, openclaw, legacy, summary in capabilities
    ]


def build_harness_lab_snapshot(
    root: Path,
    *,
    HARNESS_RECENT_RUN_LIMIT,
    TERMINAL_MISSION_STATUSES,
    _build_harness_parity_matrix,
    _build_route_trust_coverage_snapshot,
    _build_runtime_session_health,
    _harness_efficiency_recommendation,
    _load_json_file,
    _percent,
) -> dict:
    runs_root = root / ".agent_runs"
    sessions = sorted(
        [path for path in runs_root.glob("session_*") if path.is_dir()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    recent_runs: list[dict] = []
    harness_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    pause_reason_counts: dict[str, int] = {}
    delegated_run_count = 0
    delegated_failure_run_count = 0
    runtime_budget_pause_count = 0
    delegated_active_pause_count = 0
    active_continuity_run_count = 0
    resumed_run_count = 0
    resumed_completed_count = 0
    resumed_completed_or_continuing_count = 0
    approval_resolved_run_count = 0
    approval_rejected_run_count = 0
    verification_failure_total = 0
    action_count_total = 0
    for session in sessions[:HARNESS_RECENT_RUN_LIMIT]:
        state_path = session / "state.json"
        if not state_path.exists():
            continue
        payload = _load_json_file(state_path)
        if not isinstance(payload, dict):
            continue
        harness_id = payload.get("harness_id", "legacy_autonomous_engine")
        status = str(payload.get("autopilot_status", "unknown"))
        pause_reason = str(payload.get("autopilot_pause_reason", "none") or "none")
        delegated_sessions = payload.get("delegated_runtime_sessions", [])
        if not isinstance(delegated_sessions, list):
            delegated_sessions = []
        delegated_session_count = len(delegated_sessions)
        verification_failures = len(payload.get("verification_failures", []))
        action_count = len(payload.get("action_history", []))
        metadata = _load_json_file(session / "metadata.json")
        parent_session_id = (
            str(metadata.get("parent_session_id", "")).strip()
            if isinstance(metadata, dict)
            else ""
        )
        harness_counts[harness_id] = harness_counts.get(harness_id, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        pause_reason_counts[pause_reason] = pause_reason_counts.get(pause_reason, 0) + 1
        if delegated_session_count:
            delegated_run_count += 1
            if status == "failed" or any(
                str(item.get("status", "")) in {"failed", "stopped"}
                for item in delegated_sessions
                if isinstance(item, dict)
            ):
                delegated_failure_run_count += 1
            approval_decisions = {
                str(entry.get("status", ""))
                for item in delegated_sessions
                if isinstance(item, dict)
                for entry in item.get("approval_history", [])
                if isinstance(entry, dict)
            }
            if "approved" in approval_decisions:
                approval_resolved_run_count += 1
            if "rejected" in approval_decisions:
                approval_rejected_run_count += 1
        if pause_reason == "runtime_budget":
            runtime_budget_pause_count += 1
        if pause_reason == "delegated_runtime_running":
            delegated_active_pause_count += 1
        active_continuity = status not in TERMINAL_MISSION_STATUSES and (
            pause_reason == "delegated_runtime_running"
            or delegated_session_count > 0
            or action_count > 0
        )
        if active_continuity:
            active_continuity_run_count += 1
        if parent_session_id:
            resumed_run_count += 1
            if status == "completed":
                resumed_completed_count += 1
            if status == "completed" or active_continuity:
                resumed_completed_or_continuing_count += 1
        verification_failure_total += verification_failures
        action_count_total += action_count
        recent_runs.append(
            {
                "sessionId": session.name,
                "harnessId": harness_id,
                "runtimeId": payload.get("runtime_id", "openclaw"),
                "autopilotStatus": status,
                "pauseReason": pause_reason if pause_reason != "none" else "",
                "verificationFailures": verification_failures,
                "delegatedSessionCount": delegated_session_count,
                "resumedFromSessionId": parent_session_id,
                "actionCount": action_count,
            }
        )
    total_runs = len(recent_runs)
    completed_runs = status_counts.get("completed", 0)
    approval_pauses = pause_reason_counts.get("approval_required", 0)
    verification_pauses = pause_reason_counts.get("verification_failed", 0)
    completion_rate = _percent(completed_runs, total_runs)
    completed_or_continuing_rate = _percent(
        completed_runs + active_continuity_run_count,
        total_runs,
    )
    delegated_run_rate = _percent(delegated_run_count, total_runs)
    resume_run_rate = _percent(resumed_run_count, total_runs)
    resume_completion_rate = _percent(resumed_completed_count, resumed_run_count)
    resume_completed_or_continuing_rate = _percent(
        resumed_completed_or_continuing_count,
        resumed_run_count,
    )
    approval_decision_total = approval_resolved_run_count + approval_rejected_run_count
    session_health = _build_runtime_session_health(root)
    route_trust_coverage = _build_route_trust_coverage_snapshot(root, sessions=sessions)
    recommendation = _harness_efficiency_recommendation(
        total_runs=total_runs,
        completion_rate=completion_rate,
        delegated_run_rate=delegated_run_rate,
        resume_run_rate=resume_run_rate,
        resume_completion_rate=resume_completion_rate,
        approval_pause_rate=_percent(approval_pauses, total_runs),
        verification_pause_rate=_percent(verification_pauses, total_runs),
        stale_heartbeat_count=int(session_health["staleHeartbeatCount"]),
    )
    return {
        "productionHarness": "fluxio_hybrid",
        "shadowCandidates": ["legacy_autonomous_engine"],
        "parityMatrix": _build_harness_parity_matrix(),
        "beginnerGuidance": [
            {
                "runtime": "Hermes",
                "useWhen": "Use for long supervised missions, resume/continue loops, and proof-heavy work.",
            },
            {
                "runtime": "OpenClaw",
                "useWhen": "Use for live provider/tool exploration, sub-agent command work, and direct gateway sessions.",
            },
            {
                "runtime": "Syntelos Hybrid",
                "useWhen": "Default choice: it can route through Hermes or OpenClaw while preserving one mission/proof record.",
            },
        ],
        "recentRuns": recent_runs,
        "harnessCounts": harness_counts,
        "statusCounts": status_counts,
        "pauseReasonCounts": pause_reason_counts,
        "efficiency": {
            "totalRuns": total_runs,
            "completedRuns": completed_runs,
            "completionRate": completion_rate,
            "completedOrContinuingRate": completed_or_continuing_rate,
            "activeContinuityRunCount": active_continuity_run_count,
            "approvalPauseRate": _percent(approval_pauses, total_runs),
            "verificationPauseRate": _percent(verification_pauses, total_runs),
            "delegatedRunRate": delegated_run_rate,
            "delegatedFailureRate": _percent(
                delegated_failure_run_count,
                delegated_run_count,
            ),
            "runtimeBudgetPauseRate": _percent(runtime_budget_pause_count, total_runs),
            "delegatedActivePauseRate": _percent(
                delegated_active_pause_count,
                total_runs,
            ),
            "resumeRunRate": resume_run_rate,
            "resumeCompletionRate": resume_completion_rate,
            "resumeCompletedOrContinuingRate": resume_completed_or_continuing_rate,
            "approvalRecoveryRate": _percent(
                approval_resolved_run_count,
                approval_decision_total,
            ),
            "averageActionsPerRun": round(action_count_total / total_runs, 1)
            if total_runs
            else 0.0,
            "averageVerificationFailures": round(
                verification_failure_total / total_runs, 1
            )
            if total_runs
            else 0.0,
        },
        "sessionHealth": session_health,
        "routeTrustCoverage": route_trust_coverage,
        "recommendation": recommendation,
    }


def build_summary_harness_lab_snapshot(
    root: Path,
    *,
    missions: list[Mission],
    HARNESS_RECENT_RUN_LIMIT,
    TERMINAL_MISSION_STATUSES,
    _build_harness_parity_matrix,
    _build_route_trust_coverage_summary,
    _build_runtime_session_health_summary,
    _harness_efficiency_recommendation,
    _percent,
) -> dict:
    recent_missions = sorted(
        [mission for mission in missions if str(mission.state.status or "").strip()],
        key=lambda item: item.updated_at or item.created_at,
        reverse=True,
    )[:HARNESS_RECENT_RUN_LIMIT]
    harness_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    pause_reason_counts: dict[str, int] = {}
    delegated_run_count = 0
    delegated_failure_run_count = 0
    runtime_budget_pause_count = 0
    delegated_active_pause_count = 0
    active_continuity_run_count = 0
    resumed_run_count = 0
    resumed_completed_count = 0
    resumed_completed_or_continuing_count = 0
    approval_resolved_run_count = 0
    approval_rejected_run_count = 0
    verification_failure_total = 0
    action_count_total = 0
    recent_runs: list[dict[str, object]] = []
    for mission in recent_missions:
        harness_id = mission.harness_id or "fluxio_hybrid"
        status = str(mission.state.status or "unknown").strip().lower()
        pause_reason = str(
            mission.state.stop_reason
            or mission.state.last_budget_pause_reason
            or "none"
        ).strip().lower() or "none"
        delegated_sessions = list(mission.delegated_runtime_sessions or [])
        delegated_session_count = len(delegated_sessions)
        verification_failures = len(mission.proof.failed_checks or mission.state.verification_failures or [])
        action_count = len(mission.action_history or [])
        harness_counts[harness_id] = harness_counts.get(harness_id, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        pause_reason_counts[pause_reason] = pause_reason_counts.get(pause_reason, 0) + 1
        if delegated_session_count:
            delegated_run_count += 1
            if status == "failed" or any(
                str(getattr(item, "status", "") or "").lower() in {"failed", "stopped"}
                for item in delegated_sessions
            ):
                delegated_failure_run_count += 1
            approval_decisions = {
                str(entry.get("status", ""))
                for item in delegated_sessions
                for entry in getattr(item, "approval_history", []) or []
                if isinstance(entry, dict)
            }
            if "approved" in approval_decisions:
                approval_resolved_run_count += 1
            if "rejected" in approval_decisions:
                approval_rejected_run_count += 1
        if pause_reason == "runtime_budget":
            runtime_budget_pause_count += 1
        if pause_reason == "delegated_runtime_running":
            delegated_active_pause_count += 1
        active_continuity = status not in TERMINAL_MISSION_STATUSES and (
            pause_reason == "delegated_runtime_running"
            or delegated_session_count > 0
            or action_count > 0
            or str(mission.state.planner_loop_status or "").strip().lower()
            in {"running", "launching", "resume_dispatched"}
        )
        if active_continuity:
            active_continuity_run_count += 1
        if mission.current_plan_revision_id:
            resumed_run_count += 1
            if status == "completed":
                resumed_completed_count += 1
            if status == "completed" or active_continuity:
                resumed_completed_or_continuing_count += 1
        verification_failure_total += verification_failures
        action_count_total += action_count
        recent_runs.append(
            {
                "sessionId": mission.state.latest_session_id or mission.mission_id,
                "missionId": mission.mission_id,
                "harnessId": harness_id,
                "runtimeId": mission.runtime_id,
                "autopilotStatus": status,
                "pauseReason": pause_reason if pause_reason != "none" else "",
                "verificationFailures": verification_failures,
                "delegatedSessionCount": delegated_session_count,
                "resumedFromSessionId": "",
                "actionCount": action_count,
            }
        )

    total_runs = len(recent_runs)
    completed_runs = status_counts.get("completed", 0)
    approval_pauses = pause_reason_counts.get("approval_required", 0)
    verification_pauses = pause_reason_counts.get("verification_failed", 0)
    completion_rate = _percent(completed_runs, total_runs)
    completed_or_continuing_rate = _percent(
        completed_runs + active_continuity_run_count,
        total_runs,
    )
    delegated_run_rate = _percent(delegated_run_count, total_runs)
    resume_run_rate = _percent(resumed_run_count, total_runs)
    resume_completion_rate = _percent(resumed_completed_count, resumed_run_count)
    resume_completed_or_continuing_rate = _percent(
        resumed_completed_or_continuing_count,
        resumed_run_count,
    )
    approval_decision_total = approval_resolved_run_count + approval_rejected_run_count
    session_health = _build_runtime_session_health_summary(missions=missions)
    route_trust_coverage = _build_route_trust_coverage_summary(
        root,
        missions=missions,
        include_route_outcome_trends=False,
    )
    recommendation = _harness_efficiency_recommendation(
        total_runs=total_runs,
        completion_rate=completion_rate,
        delegated_run_rate=delegated_run_rate,
        resume_run_rate=resume_run_rate,
        resume_completion_rate=resume_completion_rate,
        approval_pause_rate=_percent(approval_pauses, total_runs),
        verification_pause_rate=_percent(verification_pauses, total_runs),
        stale_heartbeat_count=int(session_health["staleHeartbeatCount"]),
    )
    return {
        "schema": "fluxio.harness_lab.summary.v1",
        "source": "mission_store_delegated_sessions_summary",
        "fullSessionScanDeferred": True,
        "productionHarness": "fluxio_hybrid",
        "shadowCandidates": ["legacy_autonomous_engine"],
        "parityMatrix": _build_harness_parity_matrix(),
        "beginnerGuidance": [
            {
                "runtime": "Hermes",
                "useWhen": "Use for long supervised missions, resume/continue loops, and proof-heavy work.",
            },
            {
                "runtime": "OpenClaw",
                "useWhen": "Use for live provider/tool exploration, sub-agent command work, and direct gateway sessions.",
            },
            {
                "runtime": "Syntelos Hybrid",
                "useWhen": "Default choice: it can route through Hermes or OpenClaw while preserving one mission/proof record.",
            },
        ],
        "recentRuns": recent_runs,
        "harnessCounts": harness_counts,
        "statusCounts": status_counts,
        "pauseReasonCounts": pause_reason_counts,
        "efficiency": {
            "totalRuns": total_runs,
            "completedRuns": completed_runs,
            "completionRate": completion_rate,
            "completedOrContinuingRate": completed_or_continuing_rate,
            "activeContinuityRunCount": active_continuity_run_count,
            "approvalPauseRate": _percent(approval_pauses, total_runs),
            "verificationPauseRate": _percent(verification_pauses, total_runs),
            "delegatedRunRate": delegated_run_rate,
            "delegatedFailureRate": _percent(
                delegated_failure_run_count,
                delegated_run_count,
            ),
            "runtimeBudgetPauseRate": _percent(runtime_budget_pause_count, total_runs),
            "delegatedActivePauseRate": _percent(
                delegated_active_pause_count,
                total_runs,
            ),
            "resumeRunRate": resume_run_rate,
            "resumeCompletionRate": resume_completion_rate,
            "resumeCompletedOrContinuingRate": resume_completed_or_continuing_rate,
            "approvalRecoveryRate": _percent(
                approval_resolved_run_count,
                approval_decision_total,
            ),
            "averageActionsPerRun": round(action_count_total / total_runs, 1)
            if total_runs
            else 0.0,
            "averageVerificationFailures": round(
                verification_failure_total / total_runs, 1
            )
            if total_runs
            else 0.0,
        },
        "sessionHealth": session_health,
        "routeTrustCoverage": route_trust_coverage,
        "recommendation": recommendation,
    }



__all__ = [
    "_harness_efficiency_recommendation",
    "_route_trust_label",
    "_route_trust_task_type",
    "_operator_value_feedback_signal",
    "_route_trust_closeout_low_value",
    "_route_trust_repair_steps",
    "_route_trust_row",
    "_shell_quote",
    "_route_trust_sampling_template",
    "_build_route_trust_coverage_snapshot",
    "_route_trust_payload_for_mission",
    "_build_route_outcome_trends_for_trust",
    "_route_outcome_quarantines",
    "_quarantined_route_count",
    "_build_route_trust_coverage_summary",
    "_build_harness_parity_matrix",
    "build_harness_lab_snapshot",
    "build_summary_harness_lab_snapshot",
]
