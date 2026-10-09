"""Summary and bootstrap projections for the control room.

The public control-room facade owns collaborators. Resolve it at call time so
existing monkeypatch and late-binding seams survive the responsibility split.
"""
from __future__ import annotations

from pathlib import Path
from .models import (
    Mission,
    ExecutionScope,
    DelegatedRuntimeSession,
    WorkspaceProfile,
)


def _control_room_facade():
    from . import mission_control
    return mission_control


class ControlRoomProjectionMixin:
    @staticmethod
    def _summary_watchdog_issue_payload(issue: dict) -> dict:
        if not isinstance(issue, dict):
            return {}
        compact = {
            key: issue.get(key)
            for key in (
                "schema",
                "issueId",
                "problemId",
                "sourceIssueId",
                "missionId",
                "missionTitle",
                "workspaceId",
                "severity",
                "kind",
                "title",
                "status",
                "detectedAt",
                "firstDetectedAt",
                "lastSeenAt",
                "occurrenceCount",
                "scopeSafety",
            )
            if key in issue
        }
        for key, limit in (
            ("detail", 260),
            ("firstStep", 260),
            ("firstRepairStep", 260),
        ):
            value = str(issue.get(key) or "").strip()
            if value:
                compact[key] = value[:limit]
        compact["evidence"] = [
            str(item)[:180]
            for item in list(issue.get("evidence") or [])[:5]
            if str(item or "").strip()
        ]
        scope_evidence = issue.get("scopeEvidence")
        if isinstance(scope_evidence, dict):
            compact["scopeEvidence"] = {
                "activeFileCount": scope_evidence.get("activeFileCount", 0),
                "queuedFileCount": scope_evidence.get("queuedFileCount", 0),
                "overlapFiles": [
                    str(item)
                    for item in list(scope_evidence.get("overlapFiles") or [])[:3]
                    if str(item or "").strip()
                ],
            }
        compact["summaryCompaction"] = {
            "schema": "fluxio.watchdog_summary_compaction.v1",
            "liveData": True,
            "detailCommand": "get_control_room_snapshot_command",
        }
        return compact


    @staticmethod
    def _summary_browser_dependency_preflight_payload(preflight: dict) -> dict:
        if not isinstance(preflight, dict) or not preflight:
            return {}
        repair_plan = preflight.get("repairPlan")
        compact_repair_plan: dict[str, Any] = {}
        if isinstance(repair_plan, dict):
            package_manager = repair_plan.get("packageManager")
            compact_repair_plan = {
                "schema": repair_plan.get("schema", "fluxio.browser_dependency_repair_plan.v1"),
                "status": repair_plan.get("status", ""),
                "packages": [
                    str(item)
                    for item in list(repair_plan.get("packages") or [])[:14]
                    if str(item or "").strip()
                ],
                "commands": [
                    {
                        "id": item.get("id", ""),
                        "label": item.get("label", ""),
                        "command": str(item.get("command") or "")[:360],
                        "requiresRoot": bool(item.get("requiresRoot")),
                    }
                    for item in list(repair_plan.get("commands") or [])[:3]
                    if isinstance(item, dict)
                ],
                "nextAction": str(repair_plan.get("nextAction") or "")[:360],
            }
            if isinstance(package_manager, dict):
                compact_repair_plan["packageManager"] = {
                    "id": package_manager.get("id", ""),
                    "supportsInstall": bool(package_manager.get("supportsInstall")),
                    "rootAvailable": bool(package_manager.get("rootAvailable")),
                    "reason": str(package_manager.get("reason") or "")[:240],
                }
        return {
            "schema": preflight.get("schema", "fluxio.browser_dependency_preflight.v1"),
            "checkedAt": preflight.get("checkedAt", ""),
            "status": preflight.get("status", ""),
            "browserProofAvailable": bool(preflight.get("browserProofAvailable")),
            "chromeExecutable": str(preflight.get("chromeExecutable") or "")[:320],
            "missingLibraries": [
                str(item)
                for item in list(preflight.get("missingLibraries") or [])[:12]
                if str(item or "").strip()
            ],
            "error": str(preflight.get("error") or "")[:420],
            "installHint": str(preflight.get("installHint") or "")[:420],
            "repairPlan": compact_repair_plan,
            "receiptPath": str(preflight.get("receiptPath") or "")[:320],
        }


    @staticmethod
    def _summary_planned_scope_artifacts_payload(artifacts: dict) -> dict:
        if not isinstance(artifacts, dict) or not artifacts:
            return {}
        compact = {
            key: artifacts.get(key)
            for key in (
                "schema",
                "status",
                "scopeCount",
                "readyCount",
                "missingCount",
                "readmeCount",
                "previewableCount",
                "nextAction",
            )
            if key in artifacts
        }
        compact["entries"] = [
            {
                key: item.get(key)
                for key in (
                    "path",
                    "relativePath",
                    "status",
                    "exists",
                    "fileCount",
                    "readmePresent",
                    "previewable",
                )
                if key in item
            }
            for item in list(artifacts.get("entries") or [])[:4]
            if isinstance(item, dict)
        ]
        compact["summaryCompaction"] = {
            "schema": "fluxio.planned_scope_artifacts_summary_compaction.v1",
            "liveData": True,
            "entryLimit": 4,
            "detailCommand": "get_control_room_mission_detail_command",
        }
        return compact


    @staticmethod
    def _summary_context_roots_payload(context_roots: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(context_roots, dict):
            return {}
        compact = dict(context_roots)
        compact["roots"] = [
            _facade.ControlRoomStore._summary_context_root_row_payload(item)
            for item in list(compact.get("roots") or [])[:2]
            if isinstance(item, dict)
        ]
        compact["related"] = [
            _facade.ControlRoomStore._summary_context_root_row_payload(item)
            for item in list(compact.get("related") or [])[:2]
            if isinstance(item, dict)
        ]
        compact["dependencyEdges"] = [
            _facade.ControlRoomStore._summary_context_edge_payload(item)
            for item in list(compact.get("dependencyEdges") or [])[:2]
            if isinstance(item, dict)
        ]
        if isinstance(compact.get("primary"), dict):
            compact["primary"] = _facade.ControlRoomStore._summary_context_root_row_payload(compact["primary"])
        if isinstance(compact.get("execution"), dict):
            compact["execution"] = {
                key: compact["execution"].get(key)
                for key in (
                    "rootId",
                    "workspaceId",
                    "workspaceName",
                    "rootPath",
                    "branchName",
                    "role",
                    "writableByMission",
                )
                if key in compact["execution"]
            }
        if isinstance(compact.get("writeScopePreflight"), dict):
            preflight = compact["writeScopePreflight"]
            compact["writeScopePreflight"] = {
                key: preflight.get(key)
                for key in (
                    "schema",
                    "status",
                    "writePolicy",
                    "dependencyEdgeCount",
                    "nextAction",
                )
                if key in preflight
            }
        compact["summaryCompaction"] = {
            "schema": "fluxio.context_roots_summary_compaction.v1",
            "liveData": True,
            "rootLimit": 2,
            "relatedLimit": 2,
            "dependencyEdgeLimit": 2,
            "detailCommand": "get_control_room_mission_detail_command",
        }
        return compact


    @staticmethod
    def _summary_context_root_row_payload(row: dict) -> dict:
        if not isinstance(row, dict):
            return {}
        return {
            key: row.get(key)
            for key in (
                "rootId",
                "workspaceId",
                "workspaceName",
                "rootPath",
                "role",
                "relationship",
                "runtime",
                "harness",
                "profile",
                "folderLabel",
                "currentMission",
                "writableByMission",
                "missionCount",
                "activeMissionCount",
                "blockedMissionCount",
                "completedMissionCount",
            )
            if key in row
        }


    @staticmethod
    def _summary_context_edge_payload(edge: dict) -> dict:
        if not isinstance(edge, dict):
            return {}
        return {
            key: edge.get(key)
            for key in (
                "edgeId",
                "fromRootId",
                "toRootId",
                "type",
                "direction",
                "writePolicy",
                "summary",
            )
            if key in edge
        }


    @staticmethod
    def _summary_quota_payload(quota: dict) -> dict:
        if not isinstance(quota, dict):
            return {}
        return {
            key: quota.get(key)
            for key in (
                "schema",
                "status",
                "source",
                "remaining",
                "limit",
                "resetsAt",
                "checkedAt",
            )
            if key in quota
        }


    @staticmethod
    def _summary_runtime_lane_payload(lane: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(lane, dict):
            return {}
        compact = {
            key: lane.get(key)
            for key in (
                "role",
                "provider",
                "model",
                "effort",
                "phase",
                "active",
                "authPresent",
                "authPath",
                "authMode",
                "health",
                "failureClass",
                "blocker",
                "controlState",
                "lastControlEvent",
            )
            if key in lane
        }
        compact["actions"] = [
            str(item)
            for item in list(lane.get("actions") or [])[:4]
            if str(item or "").strip()
        ]
        compact["toolFamilies"] = [
            str(item)
            for item in list(lane.get("toolFamilies") or [])[:8]
            if str(item or "").strip()
        ]
        compact["quota"] = _facade.ControlRoomStore._summary_quota_payload(lane.get("quota", {}))
        lane_control_receipt = lane.get("laneControlReceipt")
        if isinstance(lane_control_receipt, dict) and lane_control_receipt:
            compact["laneControlReceipt"] = dict(lane_control_receipt)
        return compact


    @staticmethod
    def _summary_execution_scope_payload(scope: ExecutionScope | dict | None) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(scope) if _facade.is_dataclass(scope) else dict(scope or {})
        if not payload:
            return {}
        return {
            "schema": "fluxio.execution_scope_summary.v1",
            "requested": str(payload.get("requested") or "")[:80],
            "strategy": str(payload.get("strategy") or "")[:80],
            "executionRoot": str(payload.get("execution_root") or "")[:320],
            "workspaceRoot": str(payload.get("workspace_root") or "")[:320],
            "worktreePath": str(payload.get("worktree_path") or "")[:320],
            "branchName": str(payload.get("branch_name") or "")[:180],
            "executionTarget": str(payload.get("execution_target") or "")[:120],
            "storageMode": str(payload.get("storage_mode") or "")[:120],
            "hostLocality": str(payload.get("host_locality") or "")[:120],
            "isolated": bool(payload.get("isolated")),
            "status": str(payload.get("status") or "")[:120],
            "detail": str(payload.get("detail") or payload.get("execution_target_detail") or "")[:320],
        }


    @staticmethod
    def _summary_delegated_runtime_payload(session: DelegatedRuntimeSession | dict | None) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(session) if _facade.is_dataclass(session) else dict(session or {})
        if not payload:
            return {}
        latest_events = []
        for event in list(payload.get("latest_events") or [])[-3:]:
            if not isinstance(event, dict):
                continue
            latest_events.append(
                {
                    "kind": str(event.get("kind") or "")[:120],
                    "status": str(event.get("status") or "")[:80],
                    "message": str(event.get("message") or event.get("detail") or "")[:260],
                    "createdAt": str(event.get("created_at") or event.get("createdAt") or "")[:80],
                }
            )
        return {
            "schema": "fluxio.delegated_runtime_summary.v1",
            "delegatedId": str(payload.get("delegated_id") or "")[:120],
            "runtimeId": str(payload.get("runtime_id") or "")[:80],
            "status": str(payload.get("status") or "")[:80],
            "detail": str(payload.get("detail") or "")[:420],
            "lastEvent": str(payload.get("last_event") or "")[:420],
            "lastEventKind": str(payload.get("last_event_kind") or "")[:120],
            "updatedAt": str(payload.get("updated_at") or "")[:80],
            "createdAt": str(payload.get("created_at") or "")[:80],
            "targetPhase": str(payload.get("target_phase") or "")[:80],
            "targetRole": str(payload.get("target_role") or "")[:80],
            "targetProvider": str(payload.get("target_provider") or "")[:120],
            "targetModel": str(payload.get("target_model") or "")[:120],
            "pid": int(payload.get("pid") or 0),
            "supervisorPid": int(payload.get("supervisor_pid") or 0),
            "heartbeatStatus": str(payload.get("heartbeat_status") or "")[:80],
            "heartbeatAgeSeconds": payload.get("heartbeat_age_seconds"),
            "workspaceRoot": str(payload.get("workspace_root") or "")[:320],
            "executionRoot": str(payload.get("execution_root") or "")[:320],
            "executionTarget": str(payload.get("execution_target") or "")[:120],
            "storageMode": str(payload.get("storage_mode") or "")[:120],
            "hostLocality": str(payload.get("host_locality") or "")[:120],
            "sessionPath": str(payload.get("session_path") or "")[:320],
            "logPath": str(payload.get("log_path") or "")[:320],
            "latestEvents": latest_events,
            "changedFiles": [
                str(item)[:240]
                for item in list(payload.get("changed_files") or [])[-6:]
                if str(item or "").strip()
            ],
        }


    @staticmethod
    def _summary_provider_capabilities_payload(capabilities: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(capabilities, dict):
            return {}
        compact = {
            key: capabilities.get(key)
            for key in (
                "schema",
                "source",
                "missionId",
                "runtimeId",
                "harnessId",
                "status",
                "currentPhase",
                "liveData",
                "interchangeable",
                "laneCount",
                "readyLaneCount",
                "blockedLaneCount",
                "activeRoute",
                "toolSummary",
                "quotaSummary",
                "failureSummary",
                "nextAction",
                "updatedAt",
            )
            if key in capabilities
        }
        compact["providers"] = [
            {
                **{
                    key: provider.get(key)
                    for key in (
                        "provider",
                        "authPresent",
                        "authPath",
                        "authMode",
                        "health",
                        "readyRoles",
                        "blockedRoles",
                    )
                    if key in provider
                },
                "roles": [
                    str(item)
                    for item in list(provider.get("roles") or [])[:5]
                    if str(item or "").strip()
                ],
                "models": [
                    str(item)
                    for item in list(provider.get("models") or [])[:5]
                    if str(item or "").strip()
                ],
                "blockers": [
                    str(item)
                    for item in list(provider.get("blockers") or [])[:4]
                    if str(item or "").strip()
                ],
                "failureClasses": [
                    str(item)
                    for item in list(provider.get("failureClasses") or [])[:4]
                    if str(item or "").strip()
                ],
                "toolFamilies": [
                    str(item)
                    for item in list(provider.get("toolFamilies") or [])[:8]
                    if str(item or "").strip()
                ],
                "quota": _facade.ControlRoomStore._summary_quota_payload(provider.get("quota", {})),
            }
            for provider in list(capabilities.get("providers") or [])[:4]
            if isinstance(provider, dict)
        ]
        compact["lanes"] = [
            _facade.ControlRoomStore._summary_runtime_lane_payload(item)
            for item in list(capabilities.get("lanes") or [])[:3]
            if isinstance(item, dict)
        ]
        compact["summaryCompaction"] = {
            "schema": "fluxio.provider_capability_summary_compaction.v1",
            "liveData": True,
            "providerLimit": 4,
            "laneLimit": 3,
            "detailCommand": "get_control_room_mission_detail_command",
        }
        return compact


    @staticmethod
    def _summary_skill_catalog_payload(skill_catalog: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(skill_catalog, dict):
            return {}
        priority_signals = (
            "design-taste-frontend",
            "premium-product-ui-visuals",
            "fluxio-supervision-shell",
            "fluxio-human-feel-audit",
            "user-path-validator",
        )

        def priority(item: object) -> tuple[int, str]:
            row = item if isinstance(item, dict) else {}
            identity = " ".join(
                str(value or "")
                for value in (
                    row.get("skillId"), row.get("packId"), row.get("id"), row.get("label"),
                    " ".join(str(skill) for skill in row.get("skills", []) if str(skill).strip()),
                )
            ).lower().replace("_", "-").replace(" ", "-")
            index = next((i for i, signal in enumerate(priority_signals) if signal in identity), len(priority_signals))
            return index, identity

        recommended = list(skill_catalog.get("recommendedPacks") or [])
        curated = sorted(list(skill_catalog.get("curatedPacks") or []), key=priority)
        installed = sorted(list(skill_catalog.get("userInstalledSkills") or []), key=priority)
        learned = list(skill_catalog.get("learnedSkills") or [])
        feedback_loop = dict(skill_catalog.get("feedbackLoop") or {})
        if isinstance(feedback_loop.get("latest"), list):
            feedback_loop["latest"] = feedback_loop["latest"][:6]
        if isinstance(feedback_loop.get("repairProposals"), list):
            feedback_loop["repairProposals"] = feedback_loop["repairProposals"][:4]
        routing = feedback_loop.get("systemLossRouting")
        if isinstance(routing, dict):
            feedback_loop["systemLossRouting"] = {
                **routing,
                "activeRepairSkillIds": list(routing.get("activeRepairSkillIds") or [])[:8],
                "preferredSkillIds": list(routing.get("preferredSkillIds") or [])[:8],
            }
        return {
            **skill_catalog,
            "curatedPacks": [
                _facade.ControlRoomStore._summary_skill_row_payload(item)
                for item in curated[:12]
            ],
            "recommendedPacks": [
                _facade.ControlRoomStore._summary_skill_row_payload(item)
                for item in recommended[:8]
            ],
            "userInstalledSkills": [
                _facade.ControlRoomStore._summary_skill_row_payload(item)
                for item in installed[:8]
            ],
            "learnedSkills": [
                _facade.ControlRoomStore._summary_skill_row_payload(item)
                for item in learned[:8]
            ],
            "feedbackLoop": feedback_loop,
            "summaryTruncation": {
                "schema": "fluxio.summary_truncation.v1",
                "liveData": True,
                "detailCommand": "get_control_room_snapshot_command",
                "curatedTotal": len(curated),
                "curatedShown": min(len(curated), 12),
                "recommendedTotal": len(recommended),
                "recommendedShown": min(len(recommended), 8),
                "installedTotal": len(installed),
                "installedShown": min(len(installed), 8),
                "learnedTotal": len(learned),
                "learnedShown": min(len(learned), 8),
            },
        }


    def _fast_summary_skill_catalog_payload(self, focus_skill_id: str = "") -> dict:
        """Build the first-screen skill summary without full repair enrichment."""
        _facade = _control_room_facade()
        registry = _facade.SkillRegistry(self.root / "config" / "skills.json")
        control_dir = self.root / ".agent_control"
        live_catalog = _facade.SkillLibrary(self.root, registry).build_catalog()
        learned_raw = live_catalog.get("learnedSkills")
        installed_raw = live_catalog.get("userInstalledSkills")
        feedback_raw = _facade._load_json_file(control_dir / "skill_feedback.json")
        repair_receipts_raw = _facade._load_json_file(control_dir / "skill_repair_receipts.json")
        learned_rows = learned_raw if isinstance(learned_raw, list) else []
        installed_rows = installed_raw if isinstance(installed_raw, list) else []
        existing_installed_ids = {
            str(item.get("skillId") or item.get("skill_id") or item.get("id") or item.get("label") or "").strip()
            for item in installed_rows
            if isinstance(item, dict)
        }
        for item in _facade.load_codex_home_skill_rows(control_dir):
            skill_id = str(item.get("skillId") or item.get("label") or "").strip()
            if skill_id and skill_id not in existing_installed_ids:
                installed_rows.append(item)
                existing_installed_ids.add(skill_id)
        for item in _facade.load_latest_codex_import_rows(control_dir):
            skill_id = str(item.get("skillId") or item.get("label") or "").strip()
            if skill_id and skill_id not in existing_installed_ids:
                installed_rows.append(item)
                existing_installed_ids.add(skill_id)
        feedback_rows = feedback_raw if isinstance(feedback_raw, list) else []
        repair_receipts = repair_receipts_raw if isinstance(repair_receipts_raw, list) else []
        feedback_by_skill: dict[str, dict] = {}
        for row in feedback_rows:
            if not isinstance(row, dict):
                continue
            skill_id = str(row.get("skillId") or row.get("skill_id") or row.get("packId") or "").strip()
            if not skill_id:
                continue
            summary = feedback_by_skill.setdefault(
                skill_id,
                {
                    "sliceCount": 0,
                    "trend": "",
                    "nextAction": "",
                    "operatorValue": {"sampleCount": 0, "state": ""},
                },
            )
            summary["sliceCount"] = int(summary.get("sliceCount") or 0) + 1
            trend = str(row.get("trend") or row.get("outcomeTrend") or "").strip()
            if trend:
                summary["trend"] = trend
            next_action = str(row.get("nextAction") or "").strip()
            if next_action:
                summary["nextAction"] = next_action
            operator_value = row.get("operatorValue") if isinstance(row.get("operatorValue"), dict) else {}
            if operator_value:
                summary["operatorValue"] = {
                    "sampleCount": int(summary.get("operatorValue", {}).get("sampleCount") or 0) + 1,
                    "state": str(operator_value.get("state") or summary.get("operatorValue", {}).get("state") or ""),
                }
        curated = [
            {
                "packId": f"curated:{skill.name}",
                "label": skill.name.replace("_", " ").title(),
                "description": skill.description,
                "originType": "curated",
                "editableStatus": "active",
                "testStatus": "reviewed",
                "promotionState": "reviewed",
                "skills": [skill.name],
                "permissions": skill.permissions,
                "actionKinds": skill.action_kinds,
                "profileSuitability": skill.profile_suitability,
                "guidanceOnly": skill.guidance_only,
                "executionCapable": skill.execution_capable,
                "feedbackSummary": feedback_by_skill.get(skill.name, {}),
            }
            for skill in registry.skills
        ]
        learned = []
        for row in learned_rows:
            if not isinstance(row, dict):
                continue
            skill_id = str(row.get("skill_id") or row.get("skillId") or row.get("id") or "").strip()
            learned.append(
                {
                    **row,
                    "originType": "learned",
                    "editableStatus": "disabled" if row.get("disabled") else "active",
                    "testStatus": row.get("testStatus") or "untested",
                    "promotionState": row.get("promotionState") or "learning",
                    "feedbackSummary": feedback_by_skill.get(skill_id, row.get("feedbackSummary") if isinstance(row.get("feedbackSummary"), dict) else {}),
                }
            )
        installed = [
            {
                **row,
                "originType": row.get("originType") or "imported",
                "editableStatus": row.get("editableStatus") or "active",
                "testStatus": row.get("testStatus") or "untested",
                "promotionState": row.get("promotionState") or "imported",
            }
            for row in installed_rows
            if isinstance(row, dict)
        ]
        sections = [curated, installed, learned]
        items = [item for section in sections for item in section]
        measured = [
            item
            for item in items
            if int((item.get("feedbackSummary") or {}).get("sliceCount") or 0) > 0
        ]
        repair = [
            item
            for item in measured
            if str((item.get("feedbackSummary") or {}).get("trend") or "") in {"repair", "operator_value_repair", "operator_value_deprioritize"}
            or str(((item.get("feedbackSummary") or {}).get("operatorValue") or {}).get("state") or "") == "deprioritize"
        ]
        reinforce = [
            item
            for item in measured
            if str((item.get("feedbackSummary") or {}).get("trend") or "") in {"reinforce", "operator_value_prefer"}
            or str(((item.get("feedbackSummary") or {}).get("operatorValue") or {}).get("state") or "") == "prefer"
        ]
        skill_catalog = {
            "curatedPacks": curated,
            "recommendedPacks": [],
            "userInstalledSkills": installed,
            "learnedSkills": learned,
            "managementSummary": {
                "totalSkills": len(items),
                "needsTestCount": sum(1 for item in items if item.get("testStatus") in {"untested", "pending", "sample_ready"}),
                "reviewedReusableCount": sum(1 for item in items if item.get("promotionState") == "reviewed"),
                "learnedCount": len(learned),
                "disabledCount": sum(1 for item in items if item.get("editableStatus") in {"disabled", "archived"}),
                "feedbackSliceCount": len(feedback_rows),
                "repairCount": len(repair),
            },
            "feedbackLoop": {
                "enabled": True,
                "cadence": "mission_slice_end",
                "scoreInputs": ["execution_result", "verification_result", "changed_files", "operator_value_closeout"],
                "systemLossRouting": {
                    "enabled": True,
                    "deprioritizeThreshold": 0.55,
                    "preferThreshold": 0.15,
                    "minimumPromotionSlices": 3,
                    "minimumOperatorValueSamples": 2,
                    "humanReviewRequired": True,
                    "activeRepairSkillIds": [
                        str(item.get("skill_id") or item.get("skillId") or item.get("packId") or "")
                        for item in repair[:8]
                    ],
                    "preferredSkillIds": [
                        str(item.get("skill_id") or item.get("skillId") or item.get("packId") or "")
                        for item in reinforce[:8]
                    ],
                    "repairProposalPolicy": "automatic_before_after_validation",
                    "operatorValuePolicy": "prefer_useful_closeouts_deprioritize_low_value_closeouts",
                },
                "totalFeedbackSlices": len(feedback_rows),
                "operatorValueSkillCount": sum(
                    1
                    for item in measured
                    if int(((item.get("feedbackSummary") or {}).get("operatorValue") or {}).get("sampleCount") or 0) > 0
                ),
                "measuredSkillCount": len(measured),
                "reinforceCount": len(reinforce),
                "repairCount": len(repair),
                "repairProposals": [],
                "appliedRepairReceipts": repair_receipts[-8:],
                "appliedRepairCount": len(repair_receipts),
                "latest": sorted(
                    [row for row in feedback_rows if isinstance(row, dict)],
                    key=lambda item: str(item.get("createdAt") or item.get("created_at") or ""),
                    reverse=True,
                )[:8],
                "nextActions": [
                    str((item.get("feedbackSummary") or {}).get("nextAction") or "")
                    for item in repair[:3] + measured[:3]
                    if (item.get("feedbackSummary") or {}).get("nextAction")
                ][:4],
            },
        }
        compact = self._summary_skill_catalog_payload(skill_catalog)
        codex_import_rows = [
            item
            for item in installed
            if str(item.get("originType") or "") in {"codex_import", "codex_plugin_link"}
        ]
        compact["codexImportSummary"] = {
            "personalSkillCount": sum(
                1 for item in codex_import_rows if item.get("originType") == "codex_import"
            ),
            "linkedPluginSkillCount": sum(
                1 for item in codex_import_rows if item.get("originType") == "codex_plugin_link"
            ),
            "progressiveDisclosure": True,
        }
        normalized_focus_skill_id = str(focus_skill_id or "").strip()
        if normalized_focus_skill_id:
            focused_row = next(
                (
                    row
                    for row in installed
                    if str(
                        row.get("skillId")
                        or row.get("skill_id")
                        or row.get("id")
                        or row.get("label")
                        or ""
                    ).strip()
                    == normalized_focus_skill_id
                ),
                None,
            )
            visible_ids = {
                str(
                    row.get("skillId")
                    or row.get("skill_id")
                    or row.get("id")
                    or row.get("label")
                    or ""
                ).strip()
                for row in compact.get("userInstalledSkills", [])
                if isinstance(row, dict)
            }
            if focused_row is not None and normalized_focus_skill_id not in visible_ids:
                visible_rows = list(compact.get("userInstalledSkills") or [])
                focused_payload = self._summary_skill_row_payload(focused_row)
                compact["userInstalledSkills"] = (
                    [*visible_rows[:7], focused_payload]
                    if len(visible_rows) >= 8
                    else [*visible_rows, focused_payload]
                )
            compact["summaryTruncation"]["focusedSkillId"] = normalized_focus_skill_id
            compact["summaryTruncation"]["focusedSkillIncluded"] = focused_row is not None
            compact["summaryTruncation"]["installedShown"] = len(
                compact.get("userInstalledSkills") or []
            )
        compact["summaryTruncation"]["detailCommand"] = "get_skill_library_command"
        compact["summaryTruncation"]["source"] = "fast_live_skill_summary"
        compact["liveRefresh"] = {
            "schema": "neyvia.skill_library_refresh.v1",
            "generatedAt": _facade.utc_now_iso(),
            "focusedSkillId": normalized_focus_skill_id,
            "source": "dedicated_skill_library",
        }
        return compact


    @staticmethod
    def _summary_skill_row_payload(row: dict) -> dict:
        if not isinstance(row, dict):
            return {}
        skill_id = str(
            row.get("skillId")
            or row.get("skill_id")
            or row.get("id")
            or row.get("packId")
            or row.get("pack_id")
            or ""
        ).strip()
        feedback = row.get("feedbackSummary") if isinstance(row.get("feedbackSummary"), dict) else {}
        evolution = (
            row.get("evolutionSummary")
            if isinstance(row.get("evolutionSummary"), dict)
            else {}
        )
        compact_evolution = {
            **evolution,
            "history": list(evolution.get("history") or [])[:8],
        } if evolution else None
        operator_value = (
            feedback.get("operatorValue")
            if isinstance(feedback.get("operatorValue"), dict)
            else {}
        )
        repair_proposal = (
            feedback.get("repairProposal")
            if isinstance(feedback.get("repairProposal"), dict)
            else {}
        )
        compact_feedback = {
            "sliceCount": feedback.get("sliceCount", 0),
            "trend": feedback.get("trend", ""),
            "latestSystemLoss": feedback.get("latestSystemLoss"),
            "averageSystemLoss": feedback.get("averageSystemLoss"),
            "operatorValue": {
                "sampleCount": operator_value.get("sampleCount", 0),
                "state": operator_value.get("state", ""),
                "averageScore": operator_value.get("averageScore"),
            },
            "repairProposal": {
                "status": repair_proposal.get("status", ""),
                "title": repair_proposal.get("title", ""),
                "nextAction": repair_proposal.get("nextAction", ""),
            },
        }
        compact = {
            "skillId": skill_id,
            "packId": row.get("packId") or row.get("pack_id") or skill_id,
            "pack_id": row.get("pack_id") or row.get("packId") or "",
            "skill_id": row.get("skill_id") or skill_id,
            "id": row.get("id") or skill_id,
            "name": row.get("name") or row.get("label") or skill_id,
            "label": row.get("label") or row.get("name") or "",
            "description": str(row.get("description") or "")[:220],
            "promptHint": str(row.get("promptHint") or row.get("prompt_hint") or "")[:220],
            "instructions": row.get("instructions") or row.get("body") or row.get("content") or "",
            "source": row.get("source") if isinstance(row.get("source"), dict) else None,
            "sourcePath": (
                (row.get("source") or {}).get("path")
                if isinstance(row.get("source"), dict)
                else row.get("sourcePath") or row.get("source_path") or ""
            ),
            "originType": row.get("originType") or (row.get("source") or {}).get("kind", "")
            if isinstance(row.get("source"), dict)
            else row.get("originType", ""),
            "editableStatus": row.get("editableStatus") or row.get("editable_status") or "",
            "testStatus": row.get("testStatus") or row.get("test_status") or "",
            "promotionState": row.get("promotionState") or row.get("promotion_state") or "",
            "status": row.get("status", ""),
            "category": row.get("category") or row.get("originType") or "",
            "installed": bool(row.get("installed", False)),
            "execution_capable": bool(row.get("execution_capable", False)),
            "guidance_only": bool(row.get("guidance_only", False)),
            "usageCount": row.get("usageCount", row.get("usage_count", 0)),
            "helpedCount": row.get("helpedCount", row.get("helped_count", 0)),
            "permissions": list(row.get("permissions") or [])[:6],
            "profile_suitability": list(row.get("profile_suitability") or [])[:6],
            "tags": list(row.get("tags") or [])[:6],
            "feedbackSummary": compact_feedback,
            "evolutionSummary": compact_evolution,
            "summaryCompaction": {
                "schema": "fluxio.skill_summary_compaction.v1",
                "mode": "operator_skill_index_row",
                "liveData": True,
                "detailCommand": "get_control_room_snapshot_command",
            },
        }
        return compact


    @staticmethod
    def _summary_red_team_escalation_payload(red_team_escalation: dict) -> dict:
        if not isinstance(red_team_escalation, dict):
            return {}
        history = list(red_team_escalation.get("history") or [])
        audit = red_team_escalation.get("escalationAudit")
        compact_audit = audit
        if isinstance(audit, dict):
            compact_audit = {
                "schema": audit.get("schema", "fluxio.red_team_escalation_audit.v1"),
                "status": audit.get("status", ""),
                "targetCount": audit.get("targetCount", 0),
                "satisfiedTargets": audit.get("satisfiedTargets", 0),
                "pendingTargets": audit.get("pendingTargets", 0),
                "latestTargetPending": audit.get("latestTargetPending", False),
                "nextAction": audit.get("nextAction", ""),
            }
        return {
            **red_team_escalation,
            "history": history[-6:],
            "escalationAudit": compact_audit,
            "summaryTruncation": {
                "schema": "fluxio.summary_truncation.v1",
                "liveData": True,
                "historyTotal": len(history),
                "historyShown": min(len(history), 6),
                "detailCommand": "get_control_room_snapshot_command",
            },
        }


    @staticmethod
    def _summary_system_audit_digest_payload(system_audit_digest: dict) -> dict:
        if not isinstance(system_audit_digest, dict):
            return {}
        digest = dict(system_audit_digest)
        if isinstance(digest.get("systemLossBreakdown"), dict):
            breakdown = dict(digest["systemLossBreakdown"])
            breakdown["drivers"] = list(breakdown.get("drivers") or [])[:4]
            digest["systemLossBreakdown"] = breakdown
        if isinstance(digest.get("watchdogSelfImprovement"), dict):
            watchdog = dict(digest["watchdogSelfImprovement"])
            watchdog["recentReceipts"] = list(watchdog.get("recentReceipts") or [])[-3:]
            digest["watchdogSelfImprovement"] = watchdog
        if isinstance(digest.get("speedSupervisorSummary"), dict):
            speed_supervisor = dict(digest["speedSupervisorSummary"])
            speed_supervisor["rows"] = list(speed_supervisor.get("rows") or [])[:5]
            digest["speedSupervisorSummary"] = speed_supervisor
        if isinstance(digest.get("designDebtSummary"), dict):
            design_debt = dict(digest["designDebtSummary"])
            design_debt["rows"] = list(design_debt.get("rows") or [])[:5]
            digest["designDebtSummary"] = design_debt
        if isinstance(digest.get("missionAdvancementSummary"), dict):
            advancement = dict(digest["missionAdvancementSummary"])
            advancement["rows"] = list(advancement.get("rows") or [])[:6]
            digest["missionAdvancementSummary"] = advancement
        if isinstance(digest.get("storageTriageSummary"), dict):
            storage_triage = dict(digest["storageTriageSummary"])
            storage_triage["rows"] = list(storage_triage.get("rows") or [])[:6]
            digest["storageTriageSummary"] = storage_triage
        if isinstance(digest.get("operatorNextPath"), dict):
            operator_path = dict(digest["operatorNextPath"])
            operator_path["steps"] = list(operator_path.get("steps") or [])[:5]
            digest["operatorNextPath"] = operator_path
        for key, limit in (
            ("deficits", 6),
            ("badFirst", 4),
            ("improvementQueue", 6),
            ("activeGapMissions", 4),
        ):
            if isinstance(digest.get(key), list):
                digest[key] = digest[key][:limit]
        if isinstance(digest.get("t3Reference"), dict):
            t3_reference = dict(digest["t3Reference"])
            if isinstance(t3_reference.get("strengthsToBeat"), list):
                t3_reference["strengthsToBeat"] = t3_reference["strengthsToBeat"][:6]
            digest["t3Reference"] = t3_reference
        if isinstance(digest.get("publicLaunchReadiness"), dict):
            source_public_launch = dict(digest["publicLaunchReadiness"])
            public_launch = {
                key: source_public_launch.get(key)
                for key in (
                    "schema",
                    "checkedAt",
                    "ok",
                    "status",
                    "internalPacketReady",
                    "nextAction",
                )
                if key in source_public_launch
            }
            repair_packet = (
                dict(source_public_launch.get("repairPacket"))
                if isinstance(source_public_launch.get("repairPacket"), dict)
                else {}
            )
            if repair_packet:
                repair_packet = {
                    key: repair_packet.get(key)
                    for key in (
                        "schema",
                        "status",
                        "canClaimPublicLaunch",
                        "internalPacketReady",
                        "primaryBlocker",
                        "sourceCoverage",
                        "sourceDirtyPathCount",
                        "releaseBlockingPathCount",
                        "releaseBlockingSampleCount",
                        "privateOrGeneratedPathCount",
                        "publicWebUrl",
                        "workflowRun",
                        "gitHead",
                        "deployedSha",
                        "nextAction",
                        "stagingPlan",
                        "orderedLanes",
                        "commands",
                        "receiptTargets",
                    )
                    if key in repair_packet
                }
                staging_plan = (
                    dict(repair_packet.get("stagingPlan"))
                    if isinstance(repair_packet.get("stagingPlan"), dict)
                    else {}
                )
                if staging_plan:
                    staging_plan = {
                        key: staging_plan.get(key)
                        for key in (
                            "schema",
                            "status",
                            "releaseImpactPathCount",
                            "privateOrGeneratedPathCount",
                            "nextAction",
                            "verifyCommand",
                            "commitCommand",
                        )
                        if key in staging_plan
                    }
                    repair_packet["stagingPlan"] = staging_plan
                public_launch["repairPacket"] = repair_packet
            public_web = (
                dict(source_public_launch.get("publicWeb"))
                if isinstance(source_public_launch.get("publicWeb"), dict)
                else {}
            )
            if public_web:
                dirty_triage = (
                    dict(public_web.get("dirtySourceTriage"))
                    if isinstance(public_web.get("dirtySourceTriage"), dict)
                    else {}
                )
                if dirty_triage:
                    dirty_triage = {
                        key: dirty_triage.get(key)
                        for key in (
                            "schema",
                            "dirtyPathCount",
                            "sampleCount",
                            "releaseBlockingSampleCount",
                            "releaseBlockingPathCount",
                            "privateOrGeneratedPathCount",
                            "laneCounts",
                            "nextAction",
                        )
                        if key in dirty_triage
                    }
                public_web = {
                    key: public_web.get(key)
                    for key in (
                        "url",
                        "workflowRun",
                        "publicationCurrent",
                        "sourceDirtyPathCount",
                        "currentGitDirtyPathCount",
                        "sourceDirtyPathSample",
                    )
                    if key in public_web
                }
                public_web["sourceDirtyPathSample"] = [
                    str(item)
                    for item in list(public_web.get("sourceDirtyPathSample") or [])[:8]
                    if str(item or "").strip()
                ]
                if dirty_triage:
                    public_web["dirtySourceTriage"] = dirty_triage
                public_launch["publicWeb"] = public_web
            publication_proof = source_public_launch.get("publicationProof")
            if isinstance(publication_proof, dict):
                public_launch["publicationProof"] = {
                    key: publication_proof.get(key)
                    for key in (
                        "nextAction",
                        "npmReceiptPresent",
                        "signedInstallerReceiptPresent",
                        "githubReleaseReceiptPresent",
                        "githubReleasePlanReady",
                        "githubReleasePlanTag",
                        "githubReleasePlanAssetCount",
                        "githubReleaseHasExpectedAttachment",
                        "expectedGitHubReleaseAttachment",
                    )
                    if key in publication_proof
                }
            release_candidate = source_public_launch.get("releaseCandidate")
            if isinstance(release_candidate, dict):
                public_launch["releaseCandidate"] = {
                    key: release_candidate.get(key)
                    for key in ("candidateId", "status")
                    if key in release_candidate
                }
            if isinstance(source_public_launch.get("stagingProof"), dict):
                staging_proof = source_public_launch["stagingProof"]
                public_launch["stagingProof"] = {
                    key: staging_proof.get(key)
                    for key in (
                        "schema",
                        "status",
                        "releaseImpactPathCount",
                        "releaseBlockingPathCount",
                        "evidencePath",
                        "nextAction",
                        "checkedAt",
                    )
                    if key in staging_proof
                }
            public_launch["checks"] = [
                item
                for item in list(source_public_launch.get("checks") or [])[:6]
                if isinstance(item, dict)
            ]
            public_launch["blockers"] = [
                item
                for item in list(source_public_launch.get("blockers") or [])[:3]
                if isinstance(item, dict)
            ]
            public_launch["missing"] = [
                str(item)
                for item in list(source_public_launch.get("missing") or [])[:4]
                if str(item or "").strip()
            ]
            digest["publicLaunchReadiness"] = public_launch
        digest["summaryTruncation"] = {
            "schema": "fluxio.summary_truncation.v1",
            "liveData": True,
            "mode": "operator_system_audit_digest",
            "detailCommand": "get_control_room_snapshot_command",
        }
        return digest


    @staticmethod
    def _summary_project_progress_payload(project_progress_history: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(project_progress_history, dict):
            return {}
        projects = []
        for project in list(project_progress_history.get("projects") or []):
            if not isinstance(project, dict):
                continue
            projects.append(_facade.ControlRoomStore._summary_project_progress_row_payload(project))
            if len(projects) >= _facade.CONTROL_ROOM_VISIBLE_PROJECT_PROGRESS_LIMIT:
                break
        scheduling_queue = [
            _facade.ControlRoomStore._summary_project_schedule_payload(item)
            for item in list(project_progress_history.get("schedulingQueue") or [])[:8]
            if isinstance(item, dict)
        ]
        return {
            **project_progress_history,
            "projects": projects,
            "schedulingQueue": scheduling_queue,
            "summaryTruncation": {
                "schema": "fluxio.summary_truncation.v1",
                "liveData": True,
                "projectTotal": len(list(project_progress_history.get("projects") or [])),
                "projectShown": len(projects),
                "milestoneLimitPerProject": 5,
                "bucketLimitPerProject": 5,
                "projectLimit": _facade.CONTROL_ROOM_VISIBLE_PROJECT_PROGRESS_LIMIT,
                "schedulingQueueLimit": 8,
                "detailCommand": "get_control_room_snapshot_command",
            },
        }


    @staticmethod
    def _summary_runtime_recommendation_payload(recommendation: dict) -> dict:
        if not isinstance(recommendation, dict):
            return {}
        compact = {
            key: recommendation.get(key)
            for key in (
                "schema",
                "runtime",
                "confidence",
                "profile",
                "taskType",
                "taskLabel",
                "modelProvider",
                "model",
                "modelEffort",
                "reason",
                "modelReason",
                "beginnerSummary",
            )
            if key in recommendation
        }
        compact["guidance"] = [
            str(item)[:140]
            for item in list(recommendation.get("guidance") or [])[:3]
            if str(item or "").strip()
        ]
        return compact


    @staticmethod
    def _summary_project_schedule_payload(schedule: dict) -> dict:
        if not isinstance(schedule, dict):
            return {}
        compact = {
            key: schedule.get(key)
            for key in (
                "schema",
                "workspaceId",
                "workspaceName",
                "targetMissionId",
                "targetMissionTitle",
                "state",
                "safeToLaunch",
                "runtime",
                "launchMode",
                "priorityScore",
                "reason",
                "recommendedAction",
            )
            if key in schedule
        }
        compact["dependencyWarnings"] = [
            str(item)[:140]
            for item in list(schedule.get("dependencyWarnings") or [])[:3]
            if str(item or "").strip()
        ]
        for key in (
            "sameRootActiveWorkspaces",
            "sameRootBlockedWorkspaces",
            "dependencyActiveWorkspaces",
            "dependencyBlockedWorkspaces",
            "downstreamActiveWorkspaces",
            "declaredDependencyIds",
        ):
            compact[f"{key}Count"] = len(list(schedule.get(key) or []))
        for key in (
            "sameRootActiveWorkspaces",
            "sameRootBlockedWorkspaces",
            "dependencyActiveWorkspaces",
            "dependencyBlockedWorkspaces",
            "downstreamActiveWorkspaces",
        ):
            compact[key] = [
                {
                    nested_key: item.get(nested_key)
                    for nested_key in (
                        "workspaceId",
                        "workspaceName",
                        "activeMissionCount",
                        "blockedMissionCount",
                        "missionIds",
                        "relation",
                    )
                    if nested_key in item
                }
                for item in list(schedule.get(key) or [])[:3]
                if isinstance(item, dict)
            ]
        compact["declaredDependencyIds"] = [
            str(item)
            for item in list(schedule.get("declaredDependencyIds") or [])[:6]
            if str(item or "").strip()
        ]
        return compact


    @staticmethod
    def _summary_launch_rehearsal_payload(launch_rehearsal: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(launch_rehearsal, dict):
            return {}
        compact = {
            key: launch_rehearsal.get(key)
            for key in (
                "schema",
                "workspaceId",
                "status",
                "safeToLaunch",
                "recommendedRuntime",
                "urlPath",
                "cliCommand",
                "nextAction",
                "receiptCount",
                "receiptTrendStatus",
                "receiptBacked",
            )
            if key in launch_rehearsal
        }
        latest_receipt = launch_rehearsal.get("latestReceipt")
        if isinstance(latest_receipt, dict):
            compact["latestReceipt"] = {
                key: latest_receipt.get(key)
                for key in (
                    "id",
                    "receiptId",
                    "missionId",
                    "workspaceId",
                    "status",
                    "checkedAt",
                    "createdAt",
                )
                if key in latest_receipt
            }
        compact["blockedCheckIds"] = [
            str(item)
            for item in list(launch_rehearsal.get("blockedCheckIds") or [])[:5]
            if str(item or "").strip()
        ]
        compact["checklist"] = [
            {
                key: item.get(key)
                for key in ("id", "label", "status")
                if key in item
            }
            for item in list(launch_rehearsal.get("checklist") or [])[:5]
            if isinstance(item, dict)
        ]
        compact["receiptHistory"] = [
            {
                key: item.get(key)
                for key in ("id", "receiptId", "status", "checkedAt", "createdAt")
                if key in item
            }
            for item in list(launch_rehearsal.get("receiptHistory") or [])[:2]
            if isinstance(item, dict)
        ]
        compact["runtimeRecommendation"] = _facade.ControlRoomStore._summary_runtime_recommendation_payload(
            launch_rehearsal.get("runtimeRecommendation", {})
        )
        return compact


    @staticmethod
    def _summary_sync_authority_payload(sync_authority: dict) -> dict:
        if not isinstance(sync_authority, dict):
            return {}
        return {
            key: sync_authority.get(key)
            for key in (
                "schema",
                "workspaceId",
                "state",
                "authority",
                "syncMode",
                "requestedDirection",
                "effectiveDirection",
                "receiptId",
                "safeForWritableDependency",
                "manualReviewRequired",
                "conflictCount",
                "launchSafety",
                "summary",
                "nextAction",
            )
            if key in sync_authority
        }


    @staticmethod
    def _summary_project_progress_row_payload(project: dict) -> dict:
        _facade = _control_room_facade()
        compact = {
            key: project.get(key)
            for key in (
                "schema",
                "workspaceId",
                "workspaceName",
                "rootPath",
                "runtime",
                "harness",
                "profile",
                "latestMissionId",
                "latestMissionTitle",
                "latestUpdatedAt",
                "nextAction",
                "counts",
                "liveData",
            )
            if key in project
        }
        compact["milestones"] = [
            {
                key: (str(item.get(key) or "")[:140] if key == "message" else item.get(key))
                for key in (
                    "id",
                    "kind",
                    "message",
                    "missionId",
                    "missionTitle",
                    "timestamp",
                    "tone",
                    "source",
                )
                if key in item
            }
            for item in list(project.get("milestones") or [])[:5]
            if isinstance(item, dict)
        ]
        compact["buckets"] = [
            {
                key: item.get(key)
                for key in ("date", "missionsTouched", "active", "blocked", "completed")
                if key in item
            }
            for item in list(project.get("buckets") or [])[:5]
            if isinstance(item, dict)
        ]
        compact["launchRehearsal"] = _facade.ControlRoomStore._summary_launch_rehearsal_payload(
            project.get("launchRehearsal", {})
        )
        compact["scheduleRecommendation"] = _facade.ControlRoomStore._summary_project_schedule_payload(
            project.get("scheduleRecommendation", {})
        )
        compact["syncAuthority"] = _facade.ControlRoomStore._summary_sync_authority_payload(
            project.get("syncAuthority", {})
        )
        compact["summaryCompaction"] = {
            "schema": "fluxio.project_progress_summary_compaction.v1",
            "liveData": True,
            "milestoneLimit": 5,
            "bucketLimit": 5,
            "detailCommand": "get_control_room_snapshot_command",
        }
        return compact


    @staticmethod
    def _summary_terminal_mission_payload(row: dict) -> dict:
        _facade = _control_room_facade()
        if not isinstance(row, dict):
            return {}
        return {
            "mission_id": row.get("mission_id", ""),
            "workspace_id": row.get("workspace_id", ""),
            "title": row.get("title", ""),
            "objective": str(row.get("objective") or "")[:160],
            "runtime_id": row.get("runtime_id", ""),
            "harness_id": row.get("harness_id", ""),
            "status": row.get("status", ""),
            "planner_loop_status": row.get("planner_loop_status", ""),
            "phase": row.get("phase", ""),
            "queue_position": row.get("queue_position", 0),
            "continuity_state": row.get("continuity_state", ""),
            "current_runtime_lane": row.get("current_runtime_lane", ""),
            "last_runtime_event": str(row.get("last_runtime_event") or "")[:160],
            "last_error": str(row.get("last_error") or "")[:160],
            "elapsedRuntimeSeconds": row.get("elapsedRuntimeSeconds", 0),
            "remainingRuntimeSeconds": row.get("remainingRuntimeSeconds", 0),
            "maxRuntimeSeconds": row.get("maxRuntimeSeconds", 0),
            "timeBudgetStatus": row.get("timeBudgetStatus", ""),
            "liveProgress": row.get("liveProgress", {}),
            "updated_at": row.get("updated_at", ""),
            "created_at": row.get("created_at", ""),
            "proofSummary": str(row.get("proofSummary") or "")[:180],
            "passedChecks": row.get("passedChecks", 0),
            "failedChecks": row.get("failedChecks", 0),
            "pendingApprovals": row.get("pendingApprovals", 0),
            "blockedBy": list(row.get("blockedBy") or [])[:2],
            "plannedScopeArtifacts": _facade.ControlRoomStore._summary_planned_scope_artifacts_payload(
                row.get("plannedScopeArtifacts", {})
            ),
            "runtimeLanes": (
                list(row.get("runtimeLanes") or [])[:6]
                if row.get("hasExplicitRouteContract")
                else []
            ),
            "providerCapabilities": (
                row.get("providerCapabilities", {})
                if row.get("hasExplicitRouteContract")
                else {}
            ),
            "delegatedLaneCount": int(row.get("delegatedLaneCount") or 0),
            "activeDelegatedLaneCount": 0,
            "delegatedRuntime": {
                "status": (row.get("delegatedRuntime") or {}).get("status", "")
                if isinstance(row.get("delegatedRuntime"), dict)
                else "",
                "targetProvider": (row.get("delegatedRuntime") or {}).get("targetProvider", "")
                if isinstance(row.get("delegatedRuntime"), dict)
                else "",
                "targetModel": (row.get("delegatedRuntime") or {}).get("targetModel", "")
                if isinstance(row.get("delegatedRuntime"), dict)
                else "",
            },
            "summaryCompaction": {
                "schema": "fluxio.mission_summary_compaction.v1",
                "mode": "terminal_index_row",
                "liveData": True,
                "detailCommand": "get_control_room_mission_detail_command",
            },
        }


    @staticmethod
    def _bootstrap_route_payload(route: object) -> dict:
        if not isinstance(route, dict):
            return {}
        return {
            key: route.get(key)
            for key in (
                "phase",
                "role",
                "provider",
                "model",
                "effort",
                "status",
                "health",
                "authPresent",
                "authMode",
                "failureClass",
                "blocker",
            )
            if key in route
        }


    @staticmethod
    def _bootstrap_mission_payload(row: dict) -> dict:
        """Keep first-paint mission data while leaving rich routing to detail."""
        _facade = _control_room_facade()
        if not isinstance(row, dict):
            return {}
        compact = {
            key: row.get(key)
            for key in (
                "mission_id",
                "workspace_id",
                "title",
                "objective",
                "runtime_id",
                "harness_id",
                "status",
                "planner_loop_status",
                "phase",
                "queue_position",
                "continuity_state",
                "current_runtime_lane",
                "last_runtime_event",
                "last_error",
                "elapsedRuntimeSeconds",
                "remainingRuntimeSeconds",
                "maxRuntimeSeconds",
                "timeBudgetStatus",
                "runtimeBudgetEnforced",
                "liveProgress",
                "executionScope",
                "updated_at",
                "created_at",
                "proofSummary",
                "passedChecks",
                "failedChecks",
                "pendingApprovals",
                "blockedBy",
                "plannedScopeArtifacts",
                "contextRoots",
                "hasExplicitRouteContract",
                "delegatedLaneCount",
                "activeDelegatedLaneCount",
            )
            if key in row
        }
        compact["runtimeLanes"] = [
            _facade.ControlRoomStore._bootstrap_route_payload(item)
            for item in list(row.get("runtimeLanes") or [])[:2]
            if isinstance(item, dict)
        ]
        provider_capabilities = (
            row.get("providerCapabilities")
            if isinstance(row.get("providerCapabilities"), dict)
            else {}
        )
        compact["providerCapabilities"] = {
            key: provider_capabilities.get(key)
            for key in (
                "schema",
                "status",
                "activeRoute",
                "laneCount",
                "readyLaneCount",
                "blockedLaneCount",
                "failureSummary",
                "nextAction",
            )
            if key in provider_capabilities
        }
        provider_truth = (
            row.get("providerTruth")
            if isinstance(row.get("providerTruth"), dict)
            else {}
        )
        compact["providerTruth"] = {
            key: provider_truth.get(key)
            for key in (
                "authPresent",
                "authKnown",
                "authDeferred",
                "authMode",
                "authPath",
                "activeRoute",
                "lastSuccessfulCall",
                "lastFailure",
                "updatedAt",
            )
            if key in provider_truth
        }
        delegated_runtime = (
            row.get("delegatedRuntime")
            if isinstance(row.get("delegatedRuntime"), dict)
            else {}
        )
        compact["delegatedRuntime"] = {
            key: delegated_runtime.get(key)
            for key in (
                "schema",
                "delegatedId",
                "runtimeId",
                "status",
                "detail",
                "hostLocality",
                "executionTarget",
                "executionRoot",
                "workspaceRoot",
                "targetPhase",
                "targetRole",
                "targetProvider",
                "targetModel",
                "targetEffort",
                "lastEvent",
                "lastEventKind",
                "heartbeatStatus",
                "heartbeatAgeSeconds",
                "updatedAt",
            )
            if key in delegated_runtime
        }
        compact["summaryCompaction"] = {
            "schema": "fluxio.mission_summary_compaction.v1",
            "mode": "bootstrap_index_row",
            "liveData": True,
            "runtimeLaneLimit": 2,
            "detailCommand": "get_control_room_mission_detail_command",
        }
        return compact


    @staticmethod
    def _bootstrap_runtime_compartments_payload(snapshot: dict) -> dict:
        """Keep live-session identity and dialogue without every proof lane."""
        _facade = _control_room_facade()
        if not isinstance(snapshot, dict):
            return {
                "items": [],
                "compartments": [],
                "summary": {
                    "total": 0,
                    "live": 0,
                    "recorded": 0,
                    "controlCompartments": 0,
                },
                "emptyState": "Runtime compartment summary is unavailable.",
                "source": "agent_control_runtime_state",
            }

        def compact_rows(rows: object, *, limit: int) -> list[dict]:
            if not isinstance(rows, list):
                return []
            output: list[dict] = []
            for item in rows[-limit:]:
                if not isinstance(item, dict):
                    continue
                output.append(
                    {
                        key: item.get(key)
                        for key in (
                            "id",
                            "kind",
                            "role",
                            "title",
                            "summary",
                            "message",
                            "text",
                            "content",
                            "source",
                            "status",
                            "createdAt",
                            "created_at",
                            "timestamp",
                        )
                        if key in item
                    }
                )
            return output

        compact_items: list[dict] = []
        for item in list(snapshot.get("items") or [])[
            :_facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_COMPARTMENT_LIMIT
        ]:
            if not isinstance(item, dict):
                continue
            compact_item = {
                key: item.get(key)
                for key in (
                    "id",
                    "sessionId",
                    "missionId",
                    "missionTitle",
                    "runtime",
                    "status",
                    "state",
                    "lifecycle",
                    "streaming",
                    "host",
                    "route",
                    "updatedAt",
                    "source",
                    "turnReceipt",
                    "restartControls",
                    "heartbeat",
                    "actions",
                )
                if key in item
            }
            compact_item["recentActivity"] = compact_rows(
                item.get("recentActivity") or item.get("toolTimeline"),
                limit=_facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_ACTIVITY_LIMIT,
            )
            compact_item["messages"] = compact_rows(
                item.get("messages"),
                limit=_facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_MESSAGE_LIMIT,
            )
            compact_item["turnReceipts"] = compact_rows(
                item.get("turnReceipts"),
                limit=1,
            )
            compact_item["lanes"] = [
                _facade.ControlRoomStore._bootstrap_route_payload(lane)
                for lane in list(item.get("lanes") or [])[:2]
                if isinstance(lane, dict)
            ]
            compact_item["blockers"] = [
                str(value)[:240] for value in list(item.get("blockers") or [])[:2]
            ]
            compact_item["filesChanged"] = [
                str(value)[:320] for value in list(item.get("filesChanged") or [])[:4]
            ]
            compact_items.append(compact_item)

        return {
            "items": compact_items,
            "compartments": list(snapshot.get("compartments") or []),
            "summary": dict(snapshot.get("summary") or {}),
            "emptyState": str(snapshot.get("emptyState") or ""),
            "source": str(snapshot.get("source") or "agent_control_runtime_state"),
            "summaryCompaction": {
                "schema": "fluxio.runtime_compartments_compaction.v1",
                "mode": "bootstrap_index",
                "itemLimit": _facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_COMPARTMENT_LIMIT,
                "activityLimit": _facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_ACTIVITY_LIMIT,
                "messageLimit": _facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_MESSAGE_LIMIT,
                "detailSource": ".agent_control/runtime_compartments",
            },
        }


    def build_bootstrap_summary_snapshot(self) -> dict:
        _facade = _control_room_facade()
        started = _facade.time.perf_counter()
        workspaces = self.load_workspaces()
        missions = self.load_missions()
        activity = self.recent_events(limit=24)
        provider_auth_presence, provider_auth_presence_source = _facade._provider_auth_presence_for_bootstrap()
        status_counts: dict[str, int] = {}
        runtime_counts: dict[str, int] = {}
        workspace_missions: dict[str, list[Mission]] = {}
        for mission in missions:
            status_counts[mission.state.status] = status_counts.get(mission.state.status, 0) + 1
            runtime_counts[mission.runtime_id] = runtime_counts.get(mission.runtime_id, 0) + 1
            workspace_missions.setdefault(mission.workspace_id, []).append(mission)
        workspace_by_id = {workspace.workspace_id: workspace for workspace in workspaces}
        workspace_payload = []
        mission_launch_shortcuts = []
        for workspace in workspaces:
            related = workspace_missions.get(workspace.workspace_id, [])
            ownership = _facade._control_workspace_queue_projection(workspace.workspace_id, related)
            workspace_payload.append({'workspace_id': workspace.workspace_id, 'name': workspace.name, 'root_path': workspace.root_path, 'workspace_type': workspace.workspace_type, 'default_runtime': workspace.default_runtime, 'preferred_harness': workspace.preferred_harness, 'user_profile': workspace.user_profile, 'enabled': workspace.enabled, 'updated_at': workspace.updated_at, **{key: ownership[key] for key in ('activeMissionId', 'activeMissionTitle', 'activeMissionStatus', 'queuedMissionCount', 'missionCount')}})
            mission_launch_shortcuts.append(self._mission_launch_shortcut_payload(workspace))
        sorted_missions = sorted(missions, key=lambda item: item.updated_at or item.created_at or '', reverse=True)
        active_bootstrap_missions = [mission for mission in sorted_missions if mission.state.status not in _facade.TERMINAL_MISSION_STATUSES and mission.state.status != 'draft']
        recent_missions = []
        seen_bootstrap_mission_ids: set[str] = set()
        for mission in [*active_bootstrap_missions, *sorted_missions]:
            if mission.mission_id in seen_bootstrap_mission_ids:
                continue
            seen_bootstrap_mission_ids.add(mission.mission_id)
            recent_missions.append(mission)
            if len(recent_missions) >= _facade.CONTROL_ROOM_BOOTSTRAP_MISSION_LIMIT:
                break
        mission_payload = []
        for mission in recent_missions:
            mission_active = _facade._mission_counts_as_active_live(mission, require_queue_front=False)
            mission.state.provider_runtime_truth = _facade._deferred_bootstrap_provider_truth(_facade._provider_truth_for_mission(mission, auth_presence=provider_auth_presence, workspace=workspace_by_id.get(mission.workspace_id)), source=provider_auth_presence_source)
            row = self._mission_summary_payload(mission, root=self.root if mission_active else None, workspace=workspace_by_id.get(mission.workspace_id))
            if mission_active:
                row['contextRoots'] = self._summary_context_roots_payload(self._mission_context_roots_payload(mission, workspace=workspace_by_id.get(mission.workspace_id), workspaces=workspaces, workspace_missions=workspace_missions))
            else:
                row['contextRoots'] = self._bootstrap_context_roots_placeholder(mission)
            mission_payload.append(self._bootstrap_mission_payload(row))
        notifications = self._build_notification_feed(missions=missions, activity=activity, root=self.root, workspace_by_id=workspace_by_id)
        project_progress_history = self._bootstrap_project_progress_history_payload(workspaces=workspaces, workspace_missions=workspace_missions)
        mission_counts = _facade._control_mission_counts_projection(missions)
        active_mission_count = mission_counts['active']
        queued_mission_count = mission_counts['queued']
        blocked_mission_count = mission_counts['blocked']
        runtime_budget_attention_mission_count = mission_counts['runtimeBudgetAttention']
        attention_mission_count = mission_counts['attention']
        scheduling_queue_count = len(project_progress_history.get('schedulingQueue', []))
        zero_active_queue_healthy = active_mission_count == 0 and queued_mission_count == 0 and (attention_mission_count == 0) and (project_progress_history.get('schema') == 'fluxio.project_progress_history.v1') and (scheduling_queue_count > 0)
        live_control_state = {'schema': 'fluxio.live_control_state.v1', 'status': 'ready_no_active' if zero_active_queue_healthy else 'active_or_attention', 'healthy': bool(active_mission_count > 0 or queued_mission_count > 0 or attention_mission_count > 0 or zero_active_queue_healthy), 'zeroActiveQueueHealthy': zero_active_queue_healthy, 'activeMissionCount': active_mission_count, 'queuedMissionCount': queued_mission_count, 'blockedMissionCount': blocked_mission_count, 'blockingMetricsSince': self.blocking_metrics_since(), 'attentionMissionCount': attention_mission_count, 'runtimeBudgetAttentionMissionCount': runtime_budget_attention_mission_count, 'schedulingQueueCount': scheduling_queue_count, 'detail': 'No mission is running; the NAS scheduler queue is live and ready for the next launch.' if zero_active_queue_healthy else 'Mission state includes active, queued, or attention rows.'}
        overnight_digest = self._overnight_progress_digest_payload(root=self.root, missions=missions, recent_missions=recent_missions, workspaces=workspaces, activity=activity, notifications=notifications, telegram_destination=_facade.load_telegram_destination(self.root), delivery_receipts=[_facade.asdict(item) for item in _facade.load_delivery_receipts(self.root, limit=24)])
        connected_apps_snapshot = _facade._build_bootstrap_connected_apps_snapshot(self.root)
        bootstrap_setup_health = {'source': 'bootstrap_deferred', 'serviceManagementSummary': {'totalItems': 0, 'healthyCount': 0}, 'actionHistory': []}
        bootstrap_nas_deploy_readiness = _facade.build_nas_deploy_readiness_snapshot(self.root, onboarding={'setupHealth': bootstrap_setup_health}, setup_health=bootstrap_setup_health)
        bootstrap_runtime_compartments = _facade._build_runtime_compartments_snapshot(self.root, missions, runtime_statuses=[], setup_health=bootstrap_setup_health, storage_bridge={}, provider_auth_presence=provider_auth_presence, item_limit=_facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_COMPARTMENT_LIMIT)
        bootstrap_runtime_compartments_payload = self._bootstrap_runtime_compartments_payload(bootstrap_runtime_compartments)
        integration_readiness = _facade.build_integration_readiness_snapshot(self.root, missions=missions, connected_apps_snapshot=connected_apps_snapshot, runtime_compartments=bootstrap_runtime_compartments, provider_auth_presence=provider_auth_presence, nas_deploy_readiness=bootstrap_nas_deploy_readiness, hermes_mission_evidence={'items': [], 'summary': {'total': 0}, 'source': 'bootstrap_deferred'}, proof_scan_deferred=True)
        payload = {'schema': 'fluxio.control_room.summary.v1', 'summaryMode': 'bootstrap', 'workspaceRoot': str(self.root), 'generatedAt': _facade.utc_now_iso(), 'counts': {'workspaces': len(workspaces), 'missions': len(missions), 'activeMissions': active_mission_count, 'queuedMissions': queued_mission_count, 'blockedMissions': blocked_mission_count, 'attentionMissions': attention_mission_count, 'runtimeBudgetAttentionMissions': runtime_budget_attention_mission_count, 'completedMissions': status_counts.get('completed', 0)}, 'statusCounts': status_counts, 'runtimeCounts': runtime_counts, 'workspaces': workspace_payload, 'missions': mission_payload, 'notifications': notifications, 'overnightDigest': overnight_digest, 'projectProgressHistory': project_progress_history, 'liveControlState': live_control_state, 'bridgeLab': connected_apps_snapshot, 'runtimeCompartments': bootstrap_runtime_compartments_payload, 'integrationReadiness': integration_readiness, 'missionLaunchShortcuts': mission_launch_shortcuts[:_facade.CONTROL_ROOM_VISIBLE_LAUNCH_SHORTCUT_LIMIT], 'providers': {'authPresence': provider_auth_presence, 'authPresenceSource': provider_auth_presence_source, 'authPresenceDeferred': provider_auth_presence_source == 'bootstrap_env_file_only', 'checkedAt': _facade.utc_now_iso(), 'consistentHermesCredentialPool': True, 'fullAuthCheck': 'deferred_to_full_summary' if provider_auth_presence_source == 'bootstrap_env_file_only' else 'cached'}, 'mobileWeb': {'summaryFirst': True, 'notificationFeed': True, 'overnightDigest': True, 'appLikeProgress': True, 'phoneNotificationChannels': overnight_digest['delivery']['channels'], 'targetSurfaces': ['phone', 'tablet', 'desktop-web', 'tauri'], 'recommendedRefreshSeconds': 20, 'detailPayload': 'get_control_room_snapshot_command'}}
        payload['systemAuditDigest'] = self._summary_system_audit_digest_payload(_facade._build_bootstrap_system_audit_digest(root=self.root, missions=missions, workspaces=workspaces))
        payload['performance'] = {'source': 'control_room_summary_bootstrap', 'durationMs': round((_facade.time.perf_counter() - started) * 1000, 2), 'missionLimit': len(mission_payload), 'activityLimit': len(activity), 'payloadBytes': len(_facade.json.dumps(payload, separators=(',', ':')).encode('utf-8')), 'budget': self._performance_budget_payload(source='control_room_summary_bootstrap', duration_ms=round((_facade.time.perf_counter() - started) * 1000, 2), payload_bytes=len(_facade.json.dumps(payload, separators=(',', ':')).encode('utf-8')), duration_budget_ms=_facade.CONTROL_ROOM_SUMMARY_DURATION_BUDGET_MS, payload_budget_bytes=_facade.CONTROL_ROOM_SUMMARY_PAYLOAD_BUDGET_BYTES, item_limits={'missions': len(recent_missions), 'activity': 24, 'notifications': 24, 'overnightDigest': 1, 'runtimeCompartments': _facade.CONTROL_ROOM_BOOTSTRAP_RUNTIME_COMPARTMENT_LIMIT, 'projectProgressHistory': len(project_progress_history.get('projects') or []), 'workspaces': len(workspace_payload), 'bootstrapMissionLimit': _facade.CONTROL_ROOM_BOOTSTRAP_MISSION_LIMIT})}
        payload['performance']['payloadBytes'] = len(_facade.json.dumps(payload, separators=(',', ':')).encode('utf-8'))
        return payload


    @staticmethod
    def _bootstrap_context_roots_placeholder(mission: Mission) -> dict:
        return {
            "schema": "fluxio.mission.context_roots.v1",
            "missionId": mission.mission_id,
            "source": "summary_deferred_terminal_context",
            "status": "detail_required",
            "liveData": True,
            "deferredToDetail": True,
            "writeScopePreflight": {
                "schema": "fluxio.write_scope_preflight.v1",
                "status": "deferred_terminal_mission",
                "nextAction": "Open mission detail to inspect archived terminal context roots.",
            },
            "counts": {
                "totalRoots": 0,
                "relatedWorkspaces": 0,
                "dependencyEdges": 0,
            },
            "policy": {
                "relatedWorkspaceWritePolicy": "deferred_to_mission_detail",
                "terminalMission": True,
            },
            "nextAction": "Open mission detail to inspect archived terminal context roots.",
        }


    @staticmethod
    def _summary_project_progress_history_payload(
        *,
        root: Path,
        workspaces: list[WorkspaceProfile],
        missions: list[Mission],
        events: list[dict],
        workspace_missions: dict[str, list[Mission]],
    ) -> dict:
        _facade = _control_room_facade()
        mission_by_id = {mission.mission_id: mission for mission in missions}
        events_by_workspace: dict[str, list[dict]] = {workspace.workspace_id: [] for workspace in workspaces}
        workspace_by_id = {workspace.workspace_id: workspace for workspace in workspaces}
        for event in events:
            mission_id = str(event.get("mission_id") or event.get("missionId") or "").strip()
            mission = mission_by_id.get(mission_id)
            workspace_id = str(
                event.get("workspace_id")
                or event.get("workspaceId")
                or (event.get("metadata") or {}).get("workspaceId")
                or (mission.workspace_id if mission else "")
            ).strip()
            if workspace_id:
                events_by_workspace.setdefault(workspace_id, []).append(event)

        def blocked_rows(rows: list[Mission]) -> list[Mission]:
            return [
                mission
                for mission in rows
                if mission.state.status not in _facade.TERMINAL_MISSION_STATUSES
                and not _facade._mission_releases_workspace_slot(mission)
                and (
                    mission.state.status in {"blocked", "needs_approval"}
                    or _facade._mission_runtime_budget_exhausted(mission)
                    or mission.proof.pending_approvals
                )
            ]

        def schedule_payload(
            workspace: WorkspaceProfile,
            *,
            rows: list[Mission],
            active: list[Mission],
            queued: list[Mission],
            blocked: list[Mission],
            completed: list[Mission],
        ) -> dict:
            return _facade.ControlRoomStore._project_schedule_recommendation(
                workspace=workspace,
                rows=rows,
                active=active,
                queued=queued,
                blocked=blocked,
                completed=completed,
                workspaces=workspaces,
                workspace_missions=workspace_missions,
                workspace_by_id=workspace_by_id,
            )

        candidates: list[dict] = []
        for workspace in workspaces:
            rows = sorted(
                workspace_missions.get(workspace.workspace_id, []),
                key=lambda mission: mission.updated_at or mission.created_at or "",
                reverse=True,
            )
            active = [
                mission
                for mission in rows
                if _facade._mission_counts_as_active_live(mission)
            ]
            queued = sorted(
                [
                    mission
                    for mission in rows
                    if mission.state.status == "queued"
                ],
                key=lambda mission: (
                    int(mission.state.queue_position or 0),
                    mission.created_at,
                    mission.mission_id,
                ),
            )
            blocked = blocked_rows(rows)
            completed = [mission for mission in rows if mission.state.status == "completed"]
            workspace_events = sorted(
                events_by_workspace.get(workspace.workspace_id, []),
                key=lambda event: _facade._event_timestamp(event),
                reverse=True,
            )
            latest = rows[0] if rows else None
            schedule = schedule_payload(
                workspace,
                rows=rows,
                active=active,
                queued=queued,
                blocked=blocked,
                completed=completed,
            )
            latest_event_at = _facade._event_timestamp(workspace_events[0]) if workspace_events else ""
            latest_updated_at = max(
                latest.updated_at or latest.created_at if latest else workspace.updated_at,
                latest_event_at,
            )
            candidates.append(
                {
                    "workspace": workspace,
                    "rows": rows,
                    "workspaceEvents": workspace_events,
                    "active": active,
                    "queued": queued,
                    "blocked": blocked,
                    "completed": completed,
                    "latest": latest,
                    "latestUpdatedAt": latest_updated_at,
                    "scheduleRecommendation": schedule,
                }
            )
        candidates.sort(key=lambda item: str(item.get("latestUpdatedAt") or ""), reverse=True)
        candidates.sort(
            key=lambda item: int(item["scheduleRecommendation"].get("priorityScore", 0) or 0),
            reverse=True,
        )

        projects: list[dict] = []
        for item in candidates[:_facade.CONTROL_ROOM_VISIBLE_PROJECT_PROGRESS_LIMIT]:
            workspace = item["workspace"]
            rows = item["rows"]
            workspace_events = item["workspaceEvents"]
            active = item["active"]
            queued = item["queued"]
            blocked = item["blocked"]
            completed = item["completed"]
            latest = item["latest"]
            milestones: list[dict] = []
            for event in workspace_events[:5]:
                mission_id = str(event.get("mission_id") or event.get("missionId") or "").strip()
                mission = mission_by_id.get(mission_id)
                milestones.append(
                    {
                        "id": f"{workspace.workspace_id}:{mission_id or 'workspace'}:{_facade._event_timestamp(event)}:{event.get('kind', 'event')}",
                        "source": "mission_events",
                        "missionId": mission_id,
                        "missionTitle": mission.title if mission else "",
                        "kind": str(event.get("kind") or "event"),
                        "message": str(event.get("message") or ""),
                        "timestamp": _facade._event_timestamp(event),
                        "tone": _facade._project_event_tone(event),
                    }
                )
            for mission in rows[:4]:
                if any(entry["missionId"] == mission.mission_id and entry["kind"] == "mission_state" for entry in milestones):
                    continue
                milestones.append(
                    {
                        "id": f"{workspace.workspace_id}:{mission.mission_id}:mission_state",
                        "source": "mission_store",
                        "missionId": mission.mission_id,
                        "missionTitle": mission.title or mission.objective,
                        "kind": "mission_state",
                        "message": f"{mission.state.status}: {mission.proof.summary or mission.state.last_runtime_event or 'Mission state recorded.'}",
                        "timestamp": mission.updated_at or mission.created_at,
                        "tone": (
                            "bad"
                            if mission.state.status in {"failed", "verification_failed"}
                            else "warn"
                            if mission in blocked or mission.state.status in {"blocked", "needs_approval", "queued"}
                            else "good"
                            if mission.state.status == "completed"
                            else "neutral"
                        ),
                    }
                )
            milestones = sorted(milestones, key=lambda row: row.get("timestamp") or "", reverse=True)[:5]
            bucket_map: dict[str, dict] = {}
            for mission in rows[:20]:
                timestamp = mission.updated_at or mission.created_at or ""
                day = timestamp[:10] if len(timestamp) >= 10 else "unknown"
                bucket = bucket_map.setdefault(
                    day,
                    {"date": day, "missionsTouched": 0, "completed": 0, "active": 0, "blocked": 0},
                )
                bucket["missionsTouched"] += 1
                if mission.state.status == "completed":
                    bucket["completed"] += 1
                if mission in active:
                    bucket["active"] += 1
                if mission in blocked:
                    bucket["blocked"] += 1
            buckets = sorted(bucket_map.values(), key=lambda row: row["date"], reverse=True)[:5]
            if blocked:
                next_action = "Review the first blocked mission or failed check before dispatching more project work."
            elif active:
                next_action = "Let the active mission continue and watch for the next slice-complete notification."
            elif queued:
                next_action = "Resume the front queued mission now; the workspace slot is available."
            elif completed:
                next_action = "Open the latest proof digest and decide the next project mission."
            else:
                next_action = "Launch the first mission for this project."
            sync_authority = _facade.ControlRoomStore._summary_sync_authority_payload(
                _facade.ControlRoomStore._workspace_sync_authority(workspace)
            )
            launch_rehearsal = _facade.ControlRoomStore._cross_device_launch_rehearsal(
                workspace=workspace,
                schedule=item["scheduleRecommendation"],
                sync_authority=sync_authority,
            )
            launch_receipt_history = _facade._cross_device_launch_receipt_history(
                root,
                workspace_id=workspace.workspace_id,
                limit=2,
            )
            if launch_receipt_history:
                launch_rehearsal = {
                    **launch_rehearsal,
                    "latestReceipt": launch_receipt_history[0],
                    "receiptHistory": launch_receipt_history,
                    "receiptCount": len(launch_receipt_history),
                    "receiptTrendStatus": "repeated" if len(launch_receipt_history) >= 2 else "single",
                    "receiptBacked": True,
                }
            projects.append(
                _facade.ControlRoomStore._summary_project_progress_row_payload(
                    {
                        "schema": "fluxio.project_progress.v1",
                        "workspaceId": workspace.workspace_id,
                        "workspaceName": workspace.name,
                        "rootPath": workspace.root_path,
                        "runtime": workspace.default_runtime,
                        "harness": workspace.preferred_harness,
                        "counts": {
                            "missions": len(rows),
                            "active": len(active),
                            "queued": len(queued),
                            "blocked": len(blocked),
                            "completed": len(completed),
                            "events": len(workspace_events),
                        },
                        "latestMissionId": latest.mission_id if latest else "",
                        "latestMissionTitle": latest.title or latest.objective if latest else "",
                        "latestUpdatedAt": item["latestUpdatedAt"],
                        "milestones": milestones,
                        "buckets": buckets,
                        "nextAction": next_action,
                        "scheduleRecommendation": item["scheduleRecommendation"],
                        "syncAuthority": sync_authority,
                        "launchRehearsal": launch_rehearsal,
                        "liveData": True,
                        "empty": len(rows) == 0 and len(workspace_events) == 0,
                    }
                )
            )

        scheduling_queue = [
            _facade.ControlRoomStore._summary_project_schedule_payload(item["scheduleRecommendation"])
            for item in candidates[:8]
        ]
        return {
            "schema": "fluxio.project_progress_history.v1",
            "generatedAt": _facade.utc_now_iso(),
            "source": "mission_store_and_mission_events",
            "eventLimit": len(events),
            "projects": projects,
            "schedulingQueue": scheduling_queue,
            "launchReceiptSummary": _facade._cross_device_launch_receipt_summary(root),
            "scheduler": {
                "schema": "fluxio.dependency_aware_project_scheduler.v1",
                "source": "summary_bounded_workspace_mission_counts",
                "queueSize": len(candidates),
                "topWorkspaceId": scheduling_queue[0].get("workspaceId") if scheduling_queue else "",
                "nextAction": (
                    scheduling_queue[0].get("recommendedAction")
                    if scheduling_queue
                    else "Register a workspace and launch the first mission."
                ),
            },
            "empty": not candidates,
            "summaryTruncation": {
                "schema": "fluxio.summary_truncation.v1",
                "liveData": True,
                "projectTotal": len(candidates),
                "projectShown": len(projects),
                "milestoneLimitPerProject": 5,
                "bucketLimitPerProject": 5,
                "projectLimit": _facade.CONTROL_ROOM_VISIBLE_PROJECT_PROGRESS_LIMIT,
                "schedulingQueueLimit": 8,
                "detailCommand": "get_control_room_snapshot_command",
            },
        }
