"""Mission detail, transcript and notification read models.

The public control-room facade owns collaborators. Resolve it at call time so
existing monkeypatch and late-binding seams survive the responsibility split.
"""
from __future__ import annotations
from .proofs_c_control import checked as _control_checked
from .proofs_c_missions import checked_local_mission as _mission_local_checked

from pathlib import Path
from .models import (
    Mission,
    MissionProof,
    MissionStateSnapshot,
    DelegatedRuntimeSession,
    WorkspaceProfile,
)


def _control_room_facade():
    from . import mission_control
    return mission_control


class ControlRoomDetailMixin:
    def build_mission_detail_snapshot(self, mission_id: str, *, event_limit: int = 80) -> dict:
        _facade = _control_room_facade()
        started = _facade.time.perf_counter()
        section_started = started
        section_durations: list[dict[str, float | str]] = []

        def mark_section(name: str) -> None:
            nonlocal section_started
            now = _facade.time.perf_counter()
            section_durations.append(
                {"name": name, "durationMs": round((now - section_started) * 1000, 2)}
            )
            section_started = now

        all_missions = self.load_missions()
        mission = next((item for item in all_missions if item.mission_id == mission_id), None)
        if mission is None:
            mission = self._mission_from_autonomous_workflow_record(mission_id)
            if mission is not None:
                all_missions.append(mission)
        if mission is None:
            raise ValueError(f"Unknown mission id: {mission_id}")
        self.attach_lane_control_receipts(mission)
        workspaces = self.load_workspaces()
        workspace_by_id = {item.workspace_id: item for item in workspaces}
        workspace = workspace_by_id.get(mission.workspace_id)
        workspace_missions: dict[str, list[Mission]] = {}
        for item in all_missions:
            workspace_missions.setdefault(item.workspace_id, []).append(item)
        mark_section("base_store_load")
        raw_mission_events = [
            event
            for event in self.recent_events(limit=max(event_limit * 8, 600))
            if str(event.get("mission_id") or event.get("missionId") or "") == mission.mission_id
        ]
        latest_runtime_cycle = next(
            (
                event
                for event in raw_mission_events
                if str(event.get("kind") or event.get("event") or "") == "mission.runtime_cycle"
            ),
            None,
        )
        if _facade._reconcile_mission_from_runtime_cycle(
            mission,
            latest_runtime_cycle,
            root=self.root,
            workspace=workspace,
        ):
            _facade.sync_mission_state_snapshot(mission)
            self.update_mission(mission)
        events = raw_mission_events[:event_limit]
        agent_message_events = list(events)

        def meaningful_operator_event(event: dict) -> bool:
            kind = str(event.get("kind") or event.get("event") or "").strip().lower()
            if kind not in {"mission.follow_up", "operator.followup", "operator.message"} and not any(
                token in kind for token in ("follow_up", "followup", "operator", "user")
            ):
                return False
            message = " ".join(str(event.get(key) or "") for key in ("message", "detail")).strip()
            normalized = " ".join(message.lower().split())
            if not normalized:
                return False
            generated_context_markers = (
                "active rule set:",
                "rule-set route for",
                "approval-sensitive actions:",
                "active skills:",
                "route preference for",
                "runtime preference:",
            )
            return not any(marker in normalized for marker in generated_context_markers)

        seen_agent_event_keys = {
            (
                str(event.get("timestamp") or event.get("created_at") or ""),
                str(event.get("kind") or event.get("event") or ""),
                str(event.get("message") or event.get("detail") or "")[:160],
            )
            for event in agent_message_events
        }
        for event in raw_mission_events[event_limit:]:
            if not meaningful_operator_event(event):
                continue
            key = (
                str(event.get("timestamp") or event.get("created_at") or ""),
                str(event.get("kind") or event.get("event") or ""),
                str(event.get("message") or event.get("detail") or "")[:160],
            )
            if key in seen_agent_event_keys:
                continue
            seen_agent_event_keys.add(key)
            agent_message_events.append(event)
            if len(agent_message_events) >= event_limit + 8:
                break
        mark_section("events")
        runtime_transcript = self._mission_runtime_transcript_payload(
            mission,
            events=events,
            root=self.root,
            workspace=workspace,
        )
        mark_section("runtime_transcript")
        planned_scope_artifacts = _facade.build_planned_scope_artifacts(
            root=self.root,
            mission=mission,
            workspace=workspace,
        )
        mark_section("planned_scope_artifacts")
        if mission.delegated_runtime_sessions:
            runtime_supervisor = _facade.DelegatedRuntimeSupervisor(self.root)
            refreshed_sessions: list[DelegatedRuntimeSession] = []
            for session in mission.delegated_runtime_sessions:
                try:
                    refreshed_sessions.append(runtime_supervisor.refresh_session(session))
                except Exception:
                    refreshed_sessions.append(session)
            mission.delegated_runtime_sessions = sorted(
                refreshed_sessions,
                key=_facade._delegated_runtime_session_order_key,
            )
            mission.state.delegated_runtime_sessions = [
                _facade.asdict(item) for item in mission.delegated_runtime_sessions
            ]
            _facade.refresh_mission_runtime_state(mission, mission.delegated_runtime_sessions)
            self.update_mission(mission)
            mark_section("delegated_runtime_refresh")
        if _facade._apply_planned_scope_artifact_gate_if_completed(mission, planned_scope_artifacts):
            self.update_mission(mission)
        mission_summary = self._mission_summary_payload(
            mission,
            root=self.root,
            workspace=workspace,
            planned_scope_artifacts=planned_scope_artifacts,
        )
        mark_section("mission_summary")
        bounded_mission = self._bounded_mission_detail_payload(
            mission,
            root=self.root,
            workspace=workspace,
            planned_scope_artifacts=planned_scope_artifacts,
        )
        mark_section("bounded_mission")
        agent_messages = self._mission_agent_messages_payload(
            mission,
            events=agent_message_events,
            runtime_transcript=runtime_transcript,
            root=self.root,
        )
        mark_section("agent_messages")
        artifact_gate = _facade.mission_hard_artifact_gate(
            mission,
            root=self.root,
            runtime_transcript=runtime_transcript,
            agent_messages=agent_messages,
            mission_events=events,
        )
        mark_section("artifact_gate")
        if _facade._complete_repaired_planned_scope_artifact_gate_from_detail(
            mission,
            artifact_gate,
            planned_scope_artifacts=planned_scope_artifacts,
        ) or _facade._complete_repaired_hard_artifact_gate_from_detail(
            mission,
            artifact_gate,
            planned_scope_artifacts=planned_scope_artifacts,
        ):
            self.update_mission(mission)
            mission_summary = self._mission_summary_payload(
                mission,
                root=self.root,
                workspace=workspace,
                planned_scope_artifacts=planned_scope_artifacts,
            )
            bounded_mission = self._bounded_mission_detail_payload(
                mission,
                root=self.root,
                workspace=workspace,
                planned_scope_artifacts=planned_scope_artifacts,
            )
        proof_digest = self._mission_proof_digest_payload(
            mission,
            workspace=workspace,
            artifact_gate=artifact_gate,
            root=self.root,
        )
        mark_section("proof_digest")
        mission_run_read_model = self._mission_run_read_model_payload(
            mission,
            root=self.root,
        )
        mark_section("mission_run_read_model")
        context_roots = self._mission_context_roots_payload(
            mission,
            workspace=workspace,
            workspaces=workspaces,
            workspace_missions=workspace_missions,
        )
        mark_section("context_roots")
        payload = {
            "schema": "fluxio.control_room.mission_detail.v1",
            "workspaceRoot": str(self.root),
            "generatedAt": _facade.utc_now_iso(),
            "missionId": mission.mission_id,
            "workspace": _facade.asdict(workspace) if workspace else {},
            "summary": mission_summary,
            "mission": bounded_mission,
            "events": events,
            "proof": self._compact_mission_proof_payload(mission.proof),
            "state": self._compact_mission_state_payload(mission.state),
            "delegatedRuntimeSessions": [
                self._compact_delegated_runtime_session_payload(item)
                for item in mission.delegated_runtime_sessions[-8:]
            ],
            "runtimeTranscript": runtime_transcript,
            "routeConfigs": [
                _facade.asdict(item) if _facade.is_dataclass(item) else dict(item)
                for item in mission.route_configs
                if _facade.is_dataclass(item) or isinstance(item, dict)
            ],
            "executionScope": _facade.asdict(mission.execution_scope),
            "verificationCommands": list(mission.verification_policy.commands),
            "successChecks": list(mission.success_checks),
            "agentMessages": agent_messages,
            "proofDigest": proof_digest,
            "artifactGate": artifact_gate,
            "missionRun": mission_run_read_model,
            "contextRoots": context_roots,
            "nextAction": self._next_mission_detail_action(
                mission,
                artifact_gate=artifact_gate,
            ),
            "performance": {
                "source": "control_room_mission_detail",
                "durationMs": round((_facade.time.perf_counter() - started) * 1000, 2),
                "sectionDurations": section_durations,
                "slowestSections": sorted(
                    section_durations,
                    key=lambda item: float(item.get("durationMs") or 0),
                    reverse=True,
                )[:5],
                "eventLimit": event_limit,
                "virtualization": {
                    "lazyMissionDetail": True,
                    "boundedEvents": event_limit,
                    "boundedActionHistory": 60,
                    "boundedPlanRevisions": 12,
                    "boundedDerivedTasks": 80,
                    "boundedDelegatedSessionEvents": 20,
                    "proofDigestInsteadOfFullScan": True,
                },
            },
        }
        payload["performance"]["payloadBytes"] = len(
            _facade.json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        payload["performance"]["budget"] = self._performance_budget_payload(
            source="control_room_mission_detail",
            duration_ms=payload["performance"]["durationMs"],
            payload_bytes=payload["performance"]["payloadBytes"],
            duration_budget_ms=_facade.CONTROL_ROOM_DETAIL_DURATION_BUDGET_MS,
            payload_budget_bytes=_facade.CONTROL_ROOM_DETAIL_PAYLOAD_BUDGET_BYTES,
            item_limits={
                "events": event_limit,
                "action_history": 60,
                "plan_revisions": 12,
                "derived_tasks": 80,
                "improvement_queue": 80,
                "routing_decisions": 40,
                "skill_usage": 80,
                "learned_skill_events": 80,
                "delegated_session_events": 20,
            },
        )
        return payload


    @staticmethod
    def _bootstrap_project_progress_history_payload(
        *,
        workspaces: list[WorkspaceProfile],
        workspace_missions: dict[str, list[Mission]],
    ) -> dict:
        _facade = _control_room_facade()
        projects: list[dict] = []
        scheduling_queue: list[dict] = []
        for workspace in workspaces:
            rows = sorted(
                workspace_missions.get(workspace.workspace_id, []),
                key=lambda item: item.updated_at or item.created_at or "",
                reverse=True,
            )
            if not rows:
                continue
            active = [
                item for item in rows
                if _facade._mission_counts_as_active_live(item)
            ]
            queued = sorted(
                [
                    item for item in rows
                    if item.state.status == "queued"
                ],
                key=lambda item: (
                    int(item.state.queue_position or 0),
                    item.created_at,
                    item.mission_id,
                ),
            )
            blocked = [
                item for item in rows
                if not _facade._mission_releases_workspace_slot(item)
                and item.state.status in {"blocked", "needs_approval", "failed"}
            ]
            completed = [item for item in rows if item.state.status == "completed"]
            target = active[0] if active else queued[0] if queued else blocked[0] if blocked else rows[0]
            state = "blocked" if blocked else "active" if active else "queued" if queued else "watch"
            priority_score = (
                100
                + len(active) * 25
                + len(queued) * 8
                + len(blocked) * 15
                + max(0, 6 - min(len(completed), 6))
            )
            recommended_action = (
                "Fix the first blocked or failed mission before dispatching more project work."
                if blocked
                else "Let the active mission continue and watch the next runtime transcript update."
                if active
                else "Resume the first queued mission when its workspace slot opens."
                if queued
                else "Review the latest completed proof and choose the next live mission."
            )
            schedule = {
                "schema": "fluxio.project_schedule_recommendation.v1",
                "workspaceId": workspace.workspace_id,
                "workspaceName": workspace.name,
                "state": state,
                "priorityScore": priority_score,
                "safeToLaunch": not active and bool(queued) and not blocked,
                "recommendedAction": recommended_action,
                "reason": "Bootstrap queue derived from current live workspace mission rows.",
                "runtime": workspace.default_runtime or target.runtime_id or "hermes",
                "targetMissionId": target.mission_id,
                "targetMissionTitle": target.title or target.objective,
                "sameRootActiveWorkspaces": [],
                "dependencyActiveWorkspaces": [],
                "sameRootBlockedWorkspaces": [],
                "dependencyBlockedWorkspaces": [],
            }
            project = {
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
                    "events": 0,
                },
                "latestMissionId": target.mission_id,
                "latestMissionTitle": target.title or target.objective,
                "latestUpdatedAt": target.updated_at or target.created_at,
                "milestones": [],
                "buckets": [],
                "nextAction": recommended_action,
                "scheduleRecommendation": schedule,
                "liveData": True,
                "empty": False,
            }
            projects.append(project)
            scheduling_queue.append(schedule)
        scheduling_queue.sort(
            key=lambda item: (
                -int(item.get("priorityScore", 0) or 0),
                str(item.get("workspaceName") or ""),
            )
        )
        return {
            "schema": "fluxio.project_progress_history.v1",
            "generatedAt": _facade.utc_now_iso(),
            "source": "bootstrap_live_workspace_mission_rows",
            "projects": projects[:12],
            "schedulingQueue": scheduling_queue[:8],
            "scheduler": {
                "schema": "fluxio.dependency_aware_project_scheduler.v1",
                "source": "bootstrap_live_workspace_mission_rows",
                "queueSize": len(scheduling_queue),
                "topWorkspaceId": scheduling_queue[0]["workspaceId"] if scheduling_queue else "",
                "nextAction": (
                    scheduling_queue[0]["recommendedAction"]
                    if scheduling_queue
                    else "Register a workspace and launch the first mission."
                ),
            },
            "summaryTruncation": {
                "schema": "fluxio.summary_truncation.v1",
                "liveData": True,
                "projectTotal": len(projects),
                "projectShown": min(len(projects), 12),
                "schedulingQueueLimit": 8,
                "detailCommand": "get_control_room_snapshot_command",
            },
            "empty": not projects,
        }


    @staticmethod
    def _path_identity(value: str) -> str:
        normalized = str(value or "").strip().replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return normalized.rstrip("/").lower()


    @staticmethod
    def _folder_label(value: str) -> str:
        normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
        if not normalized:
            return "root"
        return normalized.split("/")[-1] or normalized


    @staticmethod
    def _mission_context_roots_payload(
        mission: Mission,
        *,
        workspace: WorkspaceProfile | None,
        workspaces: list[WorkspaceProfile],
        workspace_missions: dict[str, list[Mission]],
    ) -> dict:
        _facade = _control_room_facade()
        roots: list[dict] = []
        seen: set[str] = set()

        def workspace_counts(workspace_id: str) -> dict[str, int]:
            rows = workspace_missions.get(workspace_id, [])
            active = [
                item
                for item in rows
                if _facade._mission_counts_as_active_live(item, require_queue_front=False)
            ]
            blocked = [
                item
                for item in active
                if item.state.status in {"blocked", "needs_approval", "verification_failed"}
                or _facade._mission_runtime_budget_exhausted(item)
                or item.proof.pending_approvals
                or item.proof.failed_checks
            ]
            return {
                "missions": len(rows),
                "active": len(active),
                "blocked": len(blocked),
                "completed": sum(1 for item in rows if item.state.status == "completed"),
            }

        def add_root(
            *,
            role: str,
            relationship: str,
            root_path: str,
            source_workspace: WorkspaceProfile | None,
            current: bool = False,
            writable: bool = True,
            detail: str = "",
        ) -> None:
            clean_path = str(root_path or "").strip()
            if not clean_path:
                return
            source_id = source_workspace.workspace_id if source_workspace else mission.workspace_id
            identity = f"{source_id}|{role}|{_facade.ControlRoomStore._path_identity(clean_path)}"
            if identity in seen:
                return
            seen.add(identity)
            counts = workspace_counts(source_id)
            roots.append(
                {
                    "rootId": f"{source_id}:{role}:{len(roots) + 1}",
                    "workspaceId": source_id,
                    "workspaceName": source_workspace.name if source_workspace else "",
                    "role": role,
                    "relationship": relationship,
                    "rootPath": clean_path,
                    "folderLabel": _facade.ControlRoomStore._folder_label(clean_path),
                    "runtime": source_workspace.default_runtime if source_workspace else mission.runtime_id,
                    "profile": source_workspace.user_profile if source_workspace else mission.selected_profile,
                    "harness": source_workspace.preferred_harness if source_workspace else mission.harness_id,
                    "syncMode": source_workspace.sync_mode if source_workspace else "mission",
                    "syncDirection": source_workspace.sync_direction if source_workspace else "bidirectional",
                    "autoSyncToNas": bool(source_workspace.auto_sync_to_nas) if source_workspace else False,
                    "localProjectPath": source_workspace.local_project_path if source_workspace else "",
                    "nasProjectPath": source_workspace.nas_project_path if source_workspace else "",
                    "missionCount": counts["missions"],
                    "activeMissionCount": counts["active"],
                    "blockedMissionCount": counts["blocked"],
                    "completedMissionCount": counts["completed"],
                    "currentMission": current,
                    "writableByMission": writable,
                    "detail": detail,
                }
            )

        add_root(
            role="primary",
            relationship="mission_workspace",
            root_path=workspace.root_path if workspace else mission.execution_scope.workspace_root,
            source_workspace=workspace,
            current=True,
            detail="Primary mission workspace.",
        )

        for role, root_path, detail in (
            ("execution", mission.execution_scope.execution_root, "Resolved execution root for the current run."),
            ("workspace_scope", mission.execution_scope.workspace_root, "Execution scope workspace root."),
            (
                "state_scope",
                str(mission.state.execution_scope.get("execution_root") or ""),
                "Runtime-reported execution root.",
            ),
            (
                "worktree",
                mission.execution_scope.worktree_path,
                "Isolated worktree root for this mission.",
            ),
        ):
            add_root(
                role=role,
                relationship="mission_execution_scope",
                root_path=root_path,
                source_workspace=workspace,
                current=role in {"execution", "worktree"},
                detail=detail,
            )

        if workspace:
            add_root(
                role="local_mirror",
                relationship="workspace_sync_pair",
                root_path=workspace.local_project_path,
                source_workspace=workspace,
                writable=workspace.sync_direction in {"bidirectional", "local_to_nas"},
                detail="Local project mirror configured for this workspace.",
            )
            add_root(
                role="nas_mirror",
                relationship="workspace_sync_pair",
                root_path=workspace.nas_project_path,
                source_workspace=workspace,
                writable=workspace.sync_direction in {"bidirectional", "nas_to_local"},
                detail="NAS project mirror configured for this workspace.",
            )

        related_workspaces = [
            item
            for item in workspaces
            if item.workspace_id != mission.workspace_id and item.enabled
        ]
        related_workspaces.sort(
            key=lambda item: (
                -len(workspace_missions.get(item.workspace_id, [])),
                item.name.lower(),
            )
        )
        for related in related_workspaces[:6]:
            add_root(
                role="related_workspace",
                relationship="same_control_room",
                root_path=related.root_path,
                source_workspace=related,
                writable=False,
                detail="Visible sibling project for cross-project planning and dependency review.",
            )

        roots = roots[:10]
        related_roots = [item for item in roots if item["role"] == "related_workspace"]
        writable_roots = [item for item in roots if item["writableByMission"]]
        sync_pairs = [item for item in roots if item["relationship"] == "workspace_sync_pair"]
        dependency_edges = _facade.ControlRoomStore._mission_context_dependency_edges(
            roots=roots,
            primary_root=roots[0] if roots else {},
        )
        write_preflight = _facade.ControlRoomStore._mission_context_write_preflight(
            roots=roots,
            dependency_edges=dependency_edges,
            mission=mission,
        )
        return {
            "schema": "fluxio.mission.context_roots.v1",
            "missionId": mission.mission_id,
            "workspaceId": mission.workspace_id,
            "mode": "multi_root" if len(roots) > 1 else "single_root",
            "primary": roots[0] if roots else {},
            "roots": roots,
            "related": related_roots,
            "dependencyEdges": dependency_edges,
            "writeScopePreflight": write_preflight,
            "counts": {
                "totalRoots": len(roots),
                "relatedWorkspaces": len(related_roots),
                "writableRoots": len(writable_roots),
                "syncPairs": len(sync_pairs),
                "dependencyEdges": len(dependency_edges),
                "preflightWarnings": len(write_preflight.get("warnings", [])),
            },
            "execution": {
                "target": mission.execution_scope.execution_target,
                "storageMode": mission.execution_scope.storage_mode,
                "hostLocality": mission.execution_scope.host_locality,
                "branchName": mission.execution_scope.branch_name,
                "detail": mission.execution_scope.detail,
            },
            "policy": {
                "writeScope": "primary_and_declared_mirrors",
                "relatedWorkspaceWritePolicy": "read_only_until_selected",
                "beginnerSafety": "Show every root before cross-project edits.",
            },
            "recommendedAction": (
                "Resolve write-scope warnings before cross-project edits."
                if write_preflight.get("warnings")
                else
                "Review related roots before planning cross-project edits."
                if related_roots
                else "Add related workspaces when this mission depends on another project."
            ),
        }


    @staticmethod
    def _mission_context_dependency_edges(
        *,
        roots: list[dict],
        primary_root: dict,
    ) -> list[dict]:
        _facade = _control_room_facade()
        primary_id = str(primary_root.get("rootId") or "")
        if not primary_id:
            return []
        edges: list[dict] = []
        for root in roots:
            root_id = str(root.get("rootId") or "")
            if not root_id or root_id == primary_id:
                continue
            relationship = str(root.get("relationship") or "")
            role = str(root.get("role") or "")
            if relationship == "workspace_sync_pair":
                edge_type = "sync_mirror"
                direction = str(root.get("syncDirection") or "bidirectional")
                write_policy = (
                    "writable_when_direction_allows"
                    if root.get("writableByMission")
                    else "read_only_for_this_direction"
                )
            elif role == "related_workspace":
                edge_type = "related_project"
                direction = "read_only"
                write_policy = "read_only_until_selected"
            else:
                edge_type = "execution_scope"
                direction = "mission_internal"
                write_policy = "writable" if root.get("writableByMission") else "read_only"
            edges.append(
                {
                    "edgeId": f"{primary_id}->{root_id}",
                    "fromRootId": primary_id,
                    "toRootId": root_id,
                    "type": edge_type,
                    "direction": direction,
                    "writePolicy": write_policy,
                    "summary": (
                        f"{_facade.ControlRoomStore._folder_label(str(primary_root.get('rootPath') or ''))}"
                        f" -> {_facade.ControlRoomStore._folder_label(str(root.get('rootPath') or ''))}"
                    ),
                }
            )
        return edges[:12]


    @staticmethod
    def _mission_context_write_preflight(
        *,
        roots: list[dict],
        dependency_edges: list[dict],
        mission: Mission,
    ) -> dict:
        writable_roots = [item for item in roots if item.get("writableByMission")]
        read_only_related = [
            item
            for item in roots
            if item.get("role") == "related_workspace" and not item.get("writableByMission")
        ]
        warnings: list[str] = []
        write_policy = str(
            getattr(mission.execution_policy, "write_policy", "")
            or getattr(mission.execution_policy, "approval_mode", "")
            or "tiered"
        )
        if read_only_related and write_policy != "read_only":
            warnings.append("Related projects are visible for planning but stay read-only until selected.")
        if len(writable_roots) > 1 and not dependency_edges:
            warnings.append("Multiple writable roots exist without explicit dependency edges.")
        return {
            "schema": "fluxio.write_scope_preflight.v1",
            "status": "warn" if warnings else "pass",
            "writePolicy": write_policy,
            "allowedRootIds": [str(item.get("rootId") or "") for item in writable_roots],
            "readOnlyRootIds": [
                str(item.get("rootId") or "")
                for item in roots
                if not item.get("writableByMission")
            ],
            "dependencyEdgeCount": len(dependency_edges),
            "warnings": warnings,
            "nextAction": (
                "Keep related roots read-only or explicitly select them before cross-project edits."
                if warnings
                else "Write scope is bounded to the primary root and declared sync mirrors."
            ),
        }


    @staticmethod
    def _performance_budget_payload(
        *,
        source: str,
        duration_ms: float,
        payload_bytes: int,
        duration_budget_ms: int,
        payload_budget_bytes: int,
        item_limits: dict[str, int],
    ) -> dict:
        _facade = _control_room_facade()
        duration_within_budget = duration_ms <= duration_budget_ms
        payload_within_budget = payload_bytes <= payload_budget_bytes
        if duration_within_budget and payload_within_budget:
            status = "pass"
            recommended_action = "Keep this endpoint in the warm-tab refresh path."
        elif not payload_within_budget:
            status = "warn"
            recommended_action = "Page or virtualize the largest lists before increasing refresh frequency."
        else:
            status = "warn"
            recommended_action = "Profile the endpoint before using it for instant mission switching."
        return {
            "schema": "fluxio.performance_budget.v1",
            "source": source,
            "status": status,
            "durationBudgetMs": duration_budget_ms,
            "payloadBudgetBytes": payload_budget_bytes,
            "measuredDurationMs": duration_ms,
            "measuredPayloadBytes": payload_bytes,
            "durationWithinBudget": duration_within_budget,
            "payloadWithinBudget": payload_within_budget,
            "durationOverBudgetMs": round(max(0.0, duration_ms - duration_budget_ms), 2),
            "payloadOverBudgetBytes": max(0, int(payload_bytes) - int(payload_budget_bytes)),
            "itemLimits": dict(item_limits),
            "recommendedAction": recommended_action,
        }


    @staticmethod
    @_control_checked('proof-digest')
    def _mission_proof_digest_payload(mission: Mission, *, workspace: WorkspaceProfile | None=None, artifact_gate: dict | None=None, root: Path | None=None) -> dict:
        _facade = _control_room_facade()
        latest_session = mission.delegated_runtime_sessions[-1] if mission.delegated_runtime_sessions else None
        latest_session_payload = _facade.asdict(latest_session) if latest_session else {}
        passed_checks = list(mission.proof.passed_checks)
        failed_checks = list(mission.proof.failed_checks)
        pending_approvals = list(mission.proof.pending_approvals)
        changed_files = list(mission.proof.changed_files)
        artifacts = list(getattr(mission.proof, 'artifacts', []) or [])
        artifact_gate = artifact_gate if isinstance(artifact_gate, dict) else _facade.mission_hard_artifact_gate(mission)
        skill_feedback = [item for item in mission.learned_skill_events[-80:] if isinstance(item, dict) and str(item.get('kind') or item.get('event') or '') == 'skill.slice_feedback'][-8:]
        checks_total = max(1, len(passed_checks) + len(failed_checks) + len(pending_approvals))
        proof_score = round(max(0, min(100, len(passed_checks) / checks_total * 72 + (18 if changed_files or artifacts or artifact_gate.get('passed') else 0) + (10 if latest_session_payload.get('status') in {'completed', 'running'} else 0) - (24 if mission.state.status == 'completed' and (not artifact_gate.get('passed')) else 0) - len(failed_checks) * 18 - len(pending_approvals) * 10)))
        preview_url = getattr(mission.state, 'last_preview_url', '') or getattr(mission.state, 'preview_url', '') or ''
        preview_source = 'served_live_preview' if preview_url else 'fixture_or_evidence_timeline'
        if not preview_url:
            manifest_preview_url = _facade.mission_artifact_manifest_preview_url(mission, root=root)
            if manifest_preview_url:
                preview_url = manifest_preview_url
                preview_source = 'mission_artifact_manifest'
        verification_state = 'blocked' if failed_checks else 'waiting_for_approval' if pending_approvals else 'passed' if passed_checks else 'not_recorded'
        return {'schema': 'fluxio.mission.proof_digest.v1', 'missionId': mission.mission_id, 'workspaceId': mission.workspace_id, 'workspaceName': workspace.name if workspace else '', 'status': mission.state.status, 'plannerLoopStatus': mission.state.planner_loop_status, 'proofScore': proof_score, 'verificationState': verification_state, 'previewSource': preview_source, 'previewUrl': preview_url, 'summary': mission.proof.summary or 'No proof summary captured yet.', 'counts': {'passedChecks': len(passed_checks), 'failedChecks': len(failed_checks), 'pendingApprovals': len(pending_approvals), 'changedFiles': len(changed_files), 'artifacts': len(artifacts), 'delegatedSessions': len(mission.delegated_runtime_sessions), 'skillFeedbackSlices': len(skill_feedback)}, 'latest': {'passedChecks': passed_checks[-5:], 'failedChecks': failed_checks[-5:], 'pendingApprovals': pending_approvals[-5:], 'changedFiles': changed_files[-8:], 'artifacts': artifacts[-5:], 'skillFeedback': skill_feedback}, 'delegatedRuntime': {'status': latest_session_payload.get('status', ''), 'detail': latest_session_payload.get('detail', ''), 'targetProvider': latest_session_payload.get('target_provider', ''), 'targetModel': latest_session_payload.get('target_model', ''), 'updatedAt': latest_session_payload.get('updated_at', ''), 'lastEvent': latest_session_payload.get('last_event', '')}, 'artifactGate': artifact_gate, 'export': {'schema': 'fluxio.mission.proof_digest_export.v1', 'backendCommand': 'export_mission_proof_digest_command', 'formats': ['markdown', 'json'], 'defaultDirectory': '.agent_control/proof_digests', 'shareActions': ['copy_path', 'archive_artifact']}, 'nextAction': _facade.ControlRoomStore._next_mission_detail_action(mission)}


    @staticmethod
    def _mission_activity_progress_payload(
        mission: Mission,
        *,
        active_runtime_lane_count: int,
    ) -> dict:
        _facade = _control_room_facade()
        status = str(mission.state.status or "").lower()
        action_count = len(list(mission.action_history or []))
        remaining_count = len(list(mission.state.remaining_steps or []))
        failure_count = len(list(mission.state.verification_failures or []))
        approval_count = len(list(mission.proof.pending_approvals or []))
        delegated_count = len(list(mission.delegated_runtime_sessions or []))
        skill_event_count = len(list(mission.learned_skill_events or []))
        completed_delegated_count = sum(
            1
            for session in mission.delegated_runtime_sessions or []
            if str(getattr(session, "status", "") or "").lower()
            in {"completed", "done", "succeeded"}
        )
        total_signals = (
            action_count
            + remaining_count
            + failure_count
            + approval_count
            + delegated_count
            + active_runtime_lane_count
            + skill_event_count
        )
        completed_signals = action_count + completed_delegated_count + skill_event_count
        value: int | None = None
        label = "Activity progress unavailable"
        if status in _facade.TERMINAL_MISSION_STATUSES:
            value = 100 if status == "completed" else None
            label = "Mission completed" if status == "completed" else "Terminal mission state"
        elif status == "queued":
            value = 4
            label = "Queued live state"
        elif failure_count > 0 or status in {"blocked", "verification_failed"}:
            value = max(6, min(64, round((completed_signals / max(1, total_signals)) * 100)))
            label = "Proof repair readiness"
        elif total_signals > 0:
            floor = 18 if active_runtime_lane_count > 0 or status == "running" else 8
            value = max(
                floor,
                min(
                    94,
                    round((completed_signals + active_runtime_lane_count) / max(1, total_signals) * 100),
                ),
            )
            label = "Live activity progress"
        elif status == "running":
            value = 12
            label = "Running live state"
        return {
            "schema": "fluxio.mission_live_progress.v1",
            "source": "mission_activity_signals",
            "label": label,
            "value": value,
            "signalCounts": {
                "actions": action_count,
                "remainingSteps": remaining_count,
                "verificationFailures": failure_count,
                "pendingApprovals": approval_count,
                "delegatedSessions": delegated_count,
                "activeRuntimeLanes": active_runtime_lane_count,
                "skillEvents": skill_event_count,
            },
            "nextAction": _facade.ControlRoomStore._next_mission_detail_action(mission),
        }


    @staticmethod
    @_control_checked('progress')
    def _mission_summary_payload(mission: Mission, *, root: Path | None=None, workspace: WorkspaceProfile | None=None, planned_scope_artifacts: dict | None=None) -> dict:
        _facade = _control_room_facade()
        sessions = mission.delegated_runtime_sessions or []
        latest_session = sessions[-1] if sessions else None
        latest_session_payload = _facade.asdict(latest_session) if latest_session else {}
        planned_scope_artifacts = planned_scope_artifacts if isinstance(planned_scope_artifacts, dict) else _facade.build_planned_scope_artifacts(root=root, mission=mission, workspace=workspace) if root is not None else {}
        elapsed_runtime_seconds = max(0, int(mission.state.elapsed_runtime_seconds or 0))
        remaining_runtime_seconds = max(0, int(mission.state.remaining_runtime_seconds or 0))
        budget_enforced = _facade.mission_runtime_budget_enforced(mission)
        max_runtime_seconds = max(0, int(mission.run_budget.max_runtime_seconds or 0)) if budget_enforced else 0
        stored_max_runtime_seconds = max_runtime_seconds
        runtime_lanes = _facade._runtime_lane_rows_for_mission(mission, latest_session)
        has_explicit_route_contract = bool(mission.route_configs or (isinstance(mission.effective_route_contract, dict) and mission.effective_route_contract.get('roles')))
        provider_capabilities = _facade._provider_capability_contract_for_mission(mission, runtime_lanes=runtime_lanes)
        active_runtime_lane_count = len(runtime_lanes) if mission.state.status not in _facade.TERMINAL_MISSION_STATUSES and mission.state.status != 'draft' else 0
        live_budget_window_active = mission.state.status == 'running' and remaining_runtime_seconds > 0 and (str(mission.state.time_budget_status or '').lower() in _facade.ACTIVE_TIME_BUDGET_STATUSES)
        stale_over_budget_without_active_window = mission.state.status == 'running' and stored_max_runtime_seconds > 0 and (elapsed_runtime_seconds >= stored_max_runtime_seconds) and (not live_budget_window_active)
        stale_cumulative_runtime_window = live_budget_window_active and stored_max_runtime_seconds > 0 and (elapsed_runtime_seconds >= stored_max_runtime_seconds)
        # Only a recorded remaining window yields a denominator. An unlimited
        # mission's wall-clock elapsed time alone would read as a 99% budget
        # bar after one second; it keeps live activity progress instead.
        if (max_runtime_seconds <= 0 or stale_cumulative_runtime_window) and remaining_runtime_seconds > 0:
            max_runtime_seconds = elapsed_runtime_seconds + remaining_runtime_seconds
        runtime_progress_value = None
        runtime_progress_label = 'Runtime progress unavailable'
        runtime_budget_progress_used = False
        runtime_budget_exhausted = _facade._mission_runtime_budget_exhausted(mission)
        if mission.state.status == 'completed':
            runtime_progress_value = 100
            runtime_progress_label = 'Mission completed'
            runtime_budget_progress_used = True
        elif mission.state.status == 'running' and max_runtime_seconds > 0:
            runtime_progress_value = max(0, min(99 if mission.state.status != 'completed' else 100, round(elapsed_runtime_seconds / max(1, max_runtime_seconds) * 100)))
            runtime_progress_label = 'Runtime budget exhausted' if runtime_budget_exhausted else 'Budget window progress'
            runtime_budget_progress_used = True
        activity_progress_payload = _facade.ControlRoomStore._mission_activity_progress_payload(mission, active_runtime_lane_count=active_runtime_lane_count)
        if mission.state.status == 'running' and runtime_budget_progress_used and (not runtime_budget_exhausted) and (int(runtime_progress_value or 0) <= 0) and (active_runtime_lane_count > 0) and (activity_progress_payload.get('value') is not None):
            runtime_progress_value = activity_progress_payload.get('value')
            runtime_progress_label = activity_progress_payload.get('label') or 'Live activity progress'
            runtime_budget_progress_used = False
        if stale_cumulative_runtime_window and activity_progress_payload.get('value') is not None:
            runtime_progress_value = activity_progress_payload.get('value')
            runtime_progress_label = activity_progress_payload.get('label') or 'Live activity progress'
            runtime_budget_progress_used = False
        if runtime_progress_value is None and activity_progress_payload.get('value') is not None:
            runtime_progress_value = activity_progress_payload.get('value')
            runtime_progress_label = activity_progress_payload.get('label') or runtime_progress_label
        proof_blocked = mission.state.status in {'blocked', 'verification_failed', 'failed'} or bool(activity_progress_payload.get('signalCounts', {}).get('verificationFailures', 0))
        non_completion_progress = proof_blocked or runtime_budget_exhausted
        progress_kind = 'runtime_budget_exhausted' if runtime_budget_exhausted else 'proof_repair' if proof_blocked else 'runtime_progress'
        progress_payload = {'schema': 'fluxio.mission_live_progress.v1', 'source': 'mission_runtime_budget_exhausted' if runtime_budget_exhausted else 'mission_proof_repair_readiness' if proof_blocked else 'mission_state_runtime_budget' if runtime_budget_progress_used else activity_progress_payload.get('source', 'mission_activity_signals'), 'label': runtime_progress_label, 'value': runtime_progress_value, 'displayAsCompletion': not non_completion_progress, 'progressKind': progress_kind, 'elapsedSeconds': elapsed_runtime_seconds, 'remainingSeconds': remaining_runtime_seconds, 'maxRuntimeSeconds': max_runtime_seconds, 'timeBudgetStatus': mission.state.time_budget_status, 'runtimeBudgetEnforced': budget_enforced, 'signalCounts': activity_progress_payload.get('signalCounts', {}), 'nextAction': 'Extend the runtime budget or resume with a fresh budget before treating this mission as unattended.' if runtime_budget_exhausted else _facade.ControlRoomStore._next_mission_detail_action(mission)}
        return {'mission_id': mission.mission_id, 'workspace_id': mission.workspace_id, 'title': mission.title, 'objective': mission.objective[:260], 'runtime_id': mission.runtime_id, 'harness_id': mission.harness_id, 'status': mission.state.status, 'planner_loop_status': mission.state.planner_loop_status, 'phase': mission.state.current_cycle_phase, 'queue_position': mission.state.queue_position, 'continuity_state': mission.state.continuity_state, 'current_runtime_lane': mission.state.current_runtime_lane, 'last_runtime_event': mission.state.last_runtime_event, 'last_error': mission.state.last_error, 'elapsedRuntimeSeconds': elapsed_runtime_seconds, 'remainingRuntimeSeconds': remaining_runtime_seconds, 'maxRuntimeSeconds': max_runtime_seconds, 'timeBudgetStatus': mission.state.time_budget_status, 'runtimeBudgetEnforced': budget_enforced, 'liveProgress': progress_payload, 'executionScope': _facade.ControlRoomStore._summary_execution_scope_payload(mission.execution_scope), 'updated_at': mission.updated_at, 'created_at': mission.created_at, 'proofSummary': mission.proof.summary, 'passedChecks': len(mission.proof.passed_checks), 'failedChecks': len(mission.proof.failed_checks), 'pendingApprovals': len(mission.proof.pending_approvals), 'blockedBy': list(mission.proof.blocked_by), 'plannedScopeArtifacts': planned_scope_artifacts, 'runtimeLanes': [_facade.ControlRoomStore._summary_runtime_lane_payload(item) for item in runtime_lanes if isinstance(item, dict)], 'providerTruth': dict(mission.state.provider_runtime_truth or {}), 'providerCapabilities': _facade.ControlRoomStore._summary_provider_capabilities_payload(provider_capabilities), 'hasExplicitRouteContract': has_explicit_route_contract, 'delegatedLaneCount': len(runtime_lanes), 'activeDelegatedLaneCount': active_runtime_lane_count, 'delegatedRuntime': _facade.ControlRoomStore._summary_delegated_runtime_payload(latest_session_payload)}


    @staticmethod
    def _bounded_mission_detail_payload(
        mission: Mission,
        *,
        root: Path | None = None,
        workspace: WorkspaceProfile | None = None,
        planned_scope_artifacts: dict | None = None,
    ) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(mission)
        if root is not None:
            payload["plannedScopeArtifacts"] = (
                planned_scope_artifacts
                if isinstance(planned_scope_artifacts, dict)
                else _facade.build_planned_scope_artifacts(
                    root=root,
                    mission=mission,
                    workspace=workspace,
                )
            )
        payload["providerCapabilities"] = _facade._provider_capability_contract_for_mission(mission)
        for key, limit in (
            ("action_history", 60),
            ("plan_revisions", 12),
            ("derived_tasks", 80),
            ("improvement_queue", 80),
            ("routing_decisions", 40),
            ("skill_usage", 80),
            ("learned_skill_events", 80),
        ):
            if isinstance(payload.get(key), list):
                payload[key] = payload[key][-limit:]
        for session in payload.get("delegated_runtime_sessions", []):
            if not isinstance(session, dict):
                continue
            if isinstance(session.get("latest_events"), list):
                session["latest_events"] = session["latest_events"][-20:]
            if isinstance(session.get("approval_history"), list):
                session["approval_history"] = session["approval_history"][-20:]
        payload["proof"] = _facade.ControlRoomStore._compact_mission_proof_payload(mission.proof)
        payload["state"] = _facade.ControlRoomStore._compact_mission_state_payload(mission.state)
        payload["delegated_runtime_sessions"] = [
            _facade.ControlRoomStore._compact_delegated_runtime_session_payload(item)
            for item in mission.delegated_runtime_sessions[-8:]
        ]
        return payload


    @staticmethod
    @_mission_local_checked('read-model')
    def _mission_run_read_model_payload(
        mission: Mission,
        *,
        root: Path,
        receipt_limit: int = 20,
    ) -> dict:
        _facade = _control_room_facade()
        layout = _facade.build_mission_run_artifact_layout(root, mission.mission_id, create=False)
        layout_payload = _facade.asdict(layout)
        snapshot_path = _facade.Path(layout.snapshots_dir) / "mission_run.json"
        snapshot = _facade._load_json_file(snapshot_path)
        snapshot_valid = (
            isinstance(snapshot, dict)
            and str(snapshot.get("schema_version") or snapshot.get("schema") or "").startswith("fluxio.mission_run.")
            and str(snapshot.get("mission_id") or "") == mission.mission_id
        )
        snapshot_payload = snapshot if snapshot_valid else {}
        receipts = _facade.load_mission_receipts(
            _facade.Path(layout.receipts_jsonl),
            limit=receipt_limit,
            mission_id=mission.mission_id,
        )
        latest_receipt = receipts[-1] if receipts else {}
        flight_recorder_snapshot_path = (
            root
            / ".agent_control"
            / "mission_runs"
            / mission.mission_id
            / "flight_recorder"
            / "snapshot.json"
        )
        flight_recorder = _facade.ControlRoomStore._compact_flight_recorder_payload(
            _facade._load_json_file(flight_recorder_snapshot_path),
            snapshot_path=flight_recorder_snapshot_path,
        )
        legacy_phase = str(mission.state.current_cycle_phase or "").strip() or "preflight"
        legacy_status = str(mission.state.status or "").strip() or "draft"
        mission_run_id = (
            str(snapshot_payload.get("mission_run_id") or "").strip()
            if snapshot_valid
            else f"legacy_{mission.mission_id}"
        )
        current_phase = (
            str(snapshot_payload.get("current_phase") or "").strip()
            if snapshot_valid
            else legacy_phase
        ) or legacy_phase
        status = (
            str(snapshot_payload.get("status") or "").strip()
            if snapshot_valid
            else legacy_status
        ) or legacy_status
        receipt_refs = snapshot_payload.get("receipts") if snapshot_valid else []
        if not isinstance(receipt_refs, list):
            receipt_refs = []
        return {
            "schema": "fluxio.mission_run_read_model.v1",
            "source": "mission_run_snapshot" if snapshot_valid else "legacy_missions_json",
            "migrationRequired": False,
            "missionRunId": mission_run_id,
            "missionId": mission.mission_id,
            "workspaceId": mission.workspace_id,
            "objective": mission.objective,
            "status": status,
            "currentPhase": current_phase,
            "runtimeId": str(snapshot_payload.get("runtime_id") or mission.runtime_id) if snapshot_valid else mission.runtime_id,
            "runProfile": str(snapshot_payload.get("run_profile") or mission.run_budget.mode or "") if snapshot_valid else mission.run_budget.mode,
            "host": {
                "preferred": str(snapshot_payload.get("preferred_host") or mission.state.preferred_host or ""),
                "assigned": str(snapshot_payload.get("assigned_host") or mission.state.assigned_host or ""),
                "locality": str(snapshot_payload.get("host_locality") or mission.state.host_locality or ""),
                "leaseId": str(snapshot_payload.get("lease_id") or mission.state.host_lease_id or ""),
                "leaseStatus": str(snapshot_payload.get("lease_status") or mission.state.lease_status or ""),
            },
            "artifactLayout": layout_payload,
            "receiptCount": len(receipts),
            "receipts": receipts[-receipt_limit:],
            "receiptRefs": receipt_refs[-receipt_limit:],
            "latestReceipt": latest_receipt,
            "flightRecorder": flight_recorder,
            "proofGaps": list(snapshot_payload.get("proof_gaps") or mission.proof.blocked_by or []) if snapshot_valid else list(mission.proof.blocked_by),
            "changedFiles": list(snapshot_payload.get("changed_files") or mission.proof.changed_files or [])[-40:] if snapshot_valid else list(mission.proof.changed_files)[-40:],
            "snapshotPath": str(snapshot_path),
            "snapshotPresent": snapshot_valid,
            "nextAction": (
                "Read the latest mission-run receipts for phase truth."
                if receipts
                else "No mission-run receipts have been recorded yet; showing legacy mission state."
            ),
        }


    @staticmethod
    @_mission_local_checked('flight')
    def _compact_flight_recorder_payload(snapshot: dict, *, snapshot_path: Path) -> dict:
        _facade = _control_room_facade()
        if not isinstance(snapshot, dict) or snapshot.get('schema') != 'fluxio.mission_flight_recorder_snapshot.v1':
            return {'schema': 'fluxio.mission_flight_recorder_read_model.v1', 'present': False, 'snapshotPath': str(snapshot_path), 'events': [], 'eventCount': 0}
        events = snapshot.get('events') if isinstance(snapshot.get('events'), list) else []
        return {'schema': 'fluxio.mission_flight_recorder_read_model.v1', 'present': True, 'snapshotPath': str(snapshot_path), 'generatedAt': str(snapshot.get('generatedAt') or ''), 'currentPhase': str(snapshot.get('currentPhase') or ''), 'runtimeCommand': str(snapshot.get('runtimeCommand') or '')[:500], 'cwd': str(snapshot.get('cwd') or '')[:240], 'envStatus': snapshot.get('envStatus') if isinstance(snapshot.get('envStatus'), dict) else {}, 'processIds': list(snapshot.get('processIds') or [])[:20], 'leaseId': str(snapshot.get('leaseId') or '')[:120], 'heartbeatAgeSeconds': snapshot.get('heartbeatAgeSeconds'), 'queueReason': str(snapshot.get('queueReason') or '')[:240], 'stdoutTail': str(snapshot.get('stdoutTail') or '')[-1000:], 'stderrTail': str(snapshot.get('stderrTail') or '')[-1000:], 'changedFiles': list(snapshot.get('changedFiles') or [])[-80:], 'verifierResult': snapshot.get('verifierResult') if isinstance(snapshot.get('verifierResult'), dict) else {}, 'nextRecoveryAction': str(snapshot.get('nextRecoveryAction') or '')[:300], 'eventCount': int(snapshot.get('eventCount') or len(events)), 'events': events[-20:]}


    @staticmethod
    def _compact_mission_proof_payload(proof: MissionProof | dict | None) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(proof) if _facade.is_dataclass(proof) else dict(proof or {})
        for key, limit in (
            ("changed_files", 40),
            ("artifacts", 16),
            ("passed_checks", 24),
            ("failed_checks", 24),
            ("pending_approvals", 16),
            ("blocked_by", 16),
        ):
            if isinstance(payload.get(key), list):
                payload[key] = payload[key][-limit:]
        payload["summary"] = str(payload.get("summary") or "")[:800]
        return payload


    @staticmethod
    def _compact_mission_state_payload(state: MissionStateSnapshot | dict | None) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(state) if _facade.is_dataclass(state) else dict(state or {})
        for key, limit in (
            ("remaining_steps", 16),
            ("verification_failures", 16),
            ("approval_history", 20),
            ("blocker_history", 20),
            ("lane_control_receipts", 20),
        ):
            if isinstance(payload.get(key), list):
                payload[key] = payload[key][-limit:]
        if isinstance(payload.get("delegated_runtime_sessions"), list):
            payload["delegated_runtime_sessions"] = [
                _facade.ControlRoomStore._compact_delegated_runtime_session_payload(item)
                for item in payload["delegated_runtime_sessions"][-8:]
            ]
        if isinstance(payload.get("code_execution"), dict):
            code_execution = dict(payload["code_execution"])
            if isinstance(code_execution.get("artifacts"), list):
                code_execution["artifacts"] = code_execution["artifacts"][-16:]
            payload["code_execution"] = code_execution
        for key in (
            "last_runtime_event",
            "last_error",
            "last_plan_summary",
            "continuity_detail",
            "last_verification_summary",
            "last_budget_pause_reason",
            "current_runtime_lane",
        ):
            if key in payload:
                payload[key] = str(payload.get(key) or "")[:800]
        return payload


    @staticmethod
    def _compact_delegated_runtime_session_payload(session: DelegatedRuntimeSession | dict) -> dict:
        _facade = _control_room_facade()
        payload = _facade.asdict(session) if _facade.is_dataclass(session) else dict(session or {})
        for key in ("launch_command", "detail", "last_event", "execution_target_detail"):
            if key in payload:
                payload[key] = str(payload.get(key) or "")[:800]
        if isinstance(payload.get("latest_events"), list):
            compact_events = []
            for event in payload["latest_events"][-8:]:
                if not isinstance(event, dict):
                    continue
                row = dict(event)
                for text_key in ("message", "detail", "trace", "stdout", "stderr"):
                    if text_key in row:
                        row[text_key] = str(row.get(text_key) or "")[:800]
                compact_events.append(row)
            payload["latest_events"] = compact_events
        if isinstance(payload.get("approval_history"), list):
            payload["approval_history"] = payload["approval_history"][-8:]
        if isinstance(payload.get("changed_files"), list):
            payload["changed_files"] = payload["changed_files"][-40:]
        return payload


    @staticmethod
    @_mission_local_checked('transcript')
    def _mission_runtime_transcript_payload(
        mission: Mission,
        *,
        events: list[dict],
        root: Path,
        workspace: WorkspaceProfile | None = None,
        limit: int = 10,
    ) -> dict:
        _facade = _control_room_facade()
        session_ids: list[str] = []

        def add_session_id(value: object) -> None:
            session_id = str(value or "").strip()
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)

        add_session_id(mission.state.latest_session_id)
        for event in events:
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
            add_session_id(metadata.get("sessionId") or metadata.get("session_id"))
            add_session_id(event.get("sessionId") or event.get("session_id"))
        latest_session_id = str(mission.state.latest_session_id or "").strip()
        if latest_session_id:
            session_ids = [item for item in session_ids if item != latest_session_id]
            session_ids.append(latest_session_id)
        session_ids = session_ids[-8:]

        transcript_roots: list[_facade.Path] = []
        for candidate in (
            _facade.Path(str(workspace.root_path)) if workspace and workspace.root_path else None,
            _facade.Path(str(mission.execution_scope.execution_root)) if mission.execution_scope.execution_root else None,
            _facade.Path(str(mission.execution_scope.workspace_root)) if mission.execution_scope.workspace_root else None,
            root,
        ):
            if candidate is None:
                continue
            transcript_root = candidate / ".agent_runs"
            if str(transcript_root) not in {str(item) for item in transcript_roots}:
                transcript_roots.append(transcript_root)
        attached_messages: list[dict] = []
        attached_session_id = ""
        attached_source = ""
        missing_session_ids: list[str] = []
        non_concrete_session_ids: list[str] = []
        non_concrete_sources: list[str] = []
        for session_id in reversed(session_ids):
            session_dir = next(
                (
                    transcript_root / session_id
                    for transcript_root in transcript_roots
                    if (transcript_root / session_id).exists()
                ),
                None,
            )
            if session_dir is None:
                missing_session_ids.append(session_id)
                continue
            state_path = session_dir / "state.json"
            timeline_path = session_dir / "timeline.jsonl"
            attached_session_id = session_id
            attached_source = str(session_dir.parent)
            timeline_messages: list[dict] = []
            state_messages: list[dict] = []
            timeline_rows = _facade._read_jsonl_tail(timeline_path, limit=limit)
            for index, row in enumerate(timeline_rows[-limit:]):
                if not isinstance(row, dict):
                    continue
                kind = str(row.get("kind") or "runtime.event").strip()
                message = str(row.get("message") or "").strip()
                if not message:
                    continue
                detail = _facade._runtime_transcript_detail(row)
                timeline_messages.append(
                    {
                        "id": f"session-timeline:{session_id}:{row.get('timestamp') or index}:{kind}",
                        "sessionId": session_id,
                        "kind": kind,
                        "label": "Hermes session transcript",
                        "title": message[:320],
                        "detail": detail,
                        "technicalDetail": _facade.json.dumps(row.get("metadata", {}), ensure_ascii=False, indent=2)[:3000]
                        if isinstance(row.get("metadata"), dict) and row.get("metadata")
                        else "",
                        "createdAt": str(row.get("timestamp") or row.get("created_at") or ""),
                        "runtimeId": mission.runtime_id,
                        "tone": "bad" if any(token in kind.lower() for token in ("fail", "error", "block")) else "neutral",
                        "runtimeOutput": _facade._runtime_transcript_has_concrete_output(row, detail),
                        "traceOnly": False,
                        "messageKind": "activity",
                        "conversationTurn": False,
                    }
                )
            state = {} if timeline_messages else _facade._load_json_file(state_path)
            if isinstance(state, dict) and state:
                for key, label in (
                    ("decisions", "Hermes session decision"),
                    ("next_actions", "Hermes session next action"),
                    ("risks", "Hermes session risk"),
                    ("notes", "Hermes session note"),
                ):
                    for index, value in enumerate([item for item in state.get(key, []) if str(item or "").strip()][-3:]):
                        state_value = str(value)
                        if timeline_messages and key != "risks":
                            continue
                        if timeline_messages and _facade._is_low_signal_session_state_value(state_value):
                            continue
                        state_messages.append(
                            {
                                "id": f"session-state:{session_id}:{key}:{index}",
                                "sessionId": session_id,
                                "kind": key,
                                "label": label,
                                "title": state_value[:320],
                                "detail": "",
                                "createdAt": str(state.get("updated_at") or state.get("generated_at") or ""),
                                "runtimeId": mission.runtime_id,
                                "tone": "warn" if key == "risks" else "neutral",
                                "runtimeOutput": False,
                                "traceOnly": bool(timeline_messages),
                                "messageKind": "activity",
                                "conversationTurn": False,
                            }
                        )
            if timeline_messages:
                concrete = [item for item in timeline_messages if item.get("runtimeOutput")]
                non_concrete = [item for item in timeline_messages if not item.get("runtimeOutput")]
                attached_messages = (concrete + non_concrete + state_messages)[-limit:]
            else:
                attached_messages = state_messages[-limit:]
            if attached_messages:
                has_artifact_evidence = bool(
                    _facade._runtime_transcript_artifact_evidence_items(
                        runtime_transcript={"messages": attached_messages}
                    )
                )
                has_runtime_output = any(item.get("runtimeOutput") for item in attached_messages)
                if has_runtime_output or has_artifact_evidence:
                    break
                non_concrete_session_ids.append(attached_session_id)
                non_concrete_sources.append(attached_source)
                attached_messages = []
                attached_session_id = ""
                attached_source = ""

        if attached_messages:
            return {
                "schema": "fluxio.runtime_transcript.v1",
                "status": "attached",
                "source": attached_source or ".agent_runs",
                "sessionId": attached_session_id,
                "candidateSessionIds": session_ids,
                "missingSessionIds": missing_session_ids,
                "nonConcreteSessionIds": non_concrete_session_ids,
                "messageCount": len(attached_messages),
                "messages": attached_messages[-limit:],
                "detail": f"Attached {len(attached_messages[-limit:])} live session transcript row(s) from {attached_session_id}.",
            }

        delegated_messages, delegated_session_ids, delegated_sources = _facade._delegated_runtime_event_transcript_messages(
            mission,
            limit=limit,
        )
        if delegated_messages:
            for delegated_session_id in delegated_session_ids:
                if delegated_session_id and delegated_session_id not in session_ids:
                    session_ids.append(delegated_session_id)
            return {
                "schema": "fluxio.runtime_transcript.v1",
                "status": "attached",
                "source": " | ".join(delegated_sources) or "delegated_runtime_session.events",
                "sessionId": delegated_messages[-1].get("sessionId", ""),
                "candidateSessionIds": session_ids[-12:],
                "missingSessionIds": missing_session_ids,
                "nonConcreteSessionIds": non_concrete_session_ids,
                "messageCount": len(delegated_messages),
                "messages": delegated_messages[-limit:],
                "detail": (
                    f"Attached {len(delegated_messages[-limit:])} live delegated runtime event row(s) "
                    "because the runtime event stream contains real output even when .agent_runs is unavailable."
                ),
            }

        for candidate in _facade._mission_artifact_root_candidates(mission, root=root):
            artifact_dir = (
                candidate
                / ".agent_control"
                / "mission_artifacts"
                / str(mission.mission_id)
            )
            runtime_output_path = artifact_dir / "proof" / "runtime_output.txt"
            if not runtime_output_path.exists():
                continue
            runtime_output = _facade._read_gate_text(runtime_output_path).strip()
            if not _facade._gate_has_meaningful_text(runtime_output):
                continue
            lines = runtime_output.splitlines()
            headline = next((line.strip() for line in lines if line.strip()), "Runtime output proof artifact")
            sections: list[tuple[str, str]] = []
            current_title = headline
            current_lines: list[str] = []
            section_heading_pattern = _facade.re.compile(r"^(What changed|Concrete verification|Live-only inputs|Status)\s*:\s*$", _facade.re.IGNORECASE)
            for line in lines[1:]:
                heading = section_heading_pattern.match(line.strip())
                if heading:
                    if current_lines:
                        sections.append((current_title, "\n".join(current_lines).strip()))
                    current_title = heading.group(1)
                    current_lines = []
                    continue
                current_lines.append(line)
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            if len(sections) < 2:
                sections = [(headline, runtime_output)]
            created_at = _facade.datetime.fromtimestamp(
                runtime_output_path.stat().st_mtime,
                tz=_facade.timezone.utc,
            ).isoformat()
            attached_messages = []
            for index, (section_title, section_body) in enumerate(sections[:limit]):
                body = section_body.strip() or runtime_output
                attached_messages.append(
                    {
                        "id": f"runtime-artifact:{mission.mission_id}:runtime_output:{index}",
                        "sessionId": "runtime_artifact",
                        "kind": "runtime.artifact_output",
                        "label": "Runtime output artifact",
                        "title": section_title[:320],
                        "detail": f"Runtime output:\n{body[:4800]}",
                        "technicalDetail": _facade.json.dumps(
                            {
                                "artifactPath": str(runtime_output_path),
                                "source": "mission_artifact_runtime_output",
                                "section": section_title,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        "createdAt": created_at,
                        "runtimeId": mission.runtime_id,
                        "tone": "good",
                        "runtimeOutput": True,
                        "traceOnly": False,
                        "messageKind": "proof",
                        "conversationTurn": False,
                        "artifactPath": str(runtime_output_path),
                    }
                )
            return {
                "schema": "fluxio.runtime_transcript.v1",
                "status": "attached",
                "source": str(runtime_output_path),
                "sessionId": "runtime_artifact",
                "candidateSessionIds": session_ids,
                "missingSessionIds": missing_session_ids,
                "nonConcreteSessionIds": non_concrete_session_ids,
                "messageCount": len(attached_messages),
                "messages": attached_messages,
                "detail": (
                    "Attached mission proof/runtime_output.txt as the live runtime transcript "
                    "because readable .agent_runs rows were bookkeeping-only."
                ),
            }

        if non_concrete_session_ids:
            detail = (
                "Readable .agent_runs transcript session(s) "
                + ", ".join(non_concrete_session_ids[:4])
                + " exist, but they only contain read-only/bookkeeping rows and no runtime output body or artifact evidence. "
                "Neyvia does not attach them as mission messages; resume with a hard artifact/runtime-output gate."
            )
            status = "missing_runtime_output"
        else:
            detail = (
                "No runtime session id has been recorded for this mission yet."
                if not session_ids
                else (
                    "Mission references runtime session(s) "
                    + ", ".join(session_ids[:4])
                    + ", but no readable .agent_runs transcript directory exists for them. "
                    "Only control-room bookkeeping is available until the runtime writes or restores that transcript."
                )
            )
            status = "missing_session_reference" if not session_ids else "missing_transcript"
        return {
            "schema": "fluxio.runtime_transcript.v1",
            "status": status,
            "source": " | ".join(non_concrete_sources or [str(path) for path in transcript_roots]),
            "sessionId": "",
            "candidateSessionIds": session_ids,
            "missingSessionIds": missing_session_ids,
            "nonConcreteSessionIds": non_concrete_session_ids,
            "messageCount": 0,
            "messages": [],
            "detail": detail,
        }


    @staticmethod
    @_mission_local_checked('messages')
    def _mission_agent_messages_payload(mission: Mission, *, events: list[dict], runtime_transcript: dict | None=None, limit: int=80, root: Path | None=None) -> list[dict]:
        _facade = _control_room_facade()
        messages: list[dict] = []

        def value(row: object, key: str, default: object='') -> object:
            if isinstance(row, dict):
                return row.get(key, default)
            return getattr(row, key, default)

        def append(*, message_id: str, title: str, detail: str='', technical_detail: str='', created_at: str='', role: str='runtime', label: str='Mission detail', runtime_id: str='', tone: str='neutral', process_message: bool=False, trace_only: bool=False, chips: list[str] | None=None, message_kind: str='', conversation_turn: bool=False, source: str='', turn_receipt: dict | None=None) -> None:
            if not title and (not detail):
                return
            messages.append({'id': message_id, 'role': role, 'label': label, 'runtimeId': runtime_id or mission.runtime_id, 'runtimeLabel': _facade.runtime_label(runtime_id or mission.runtime_id), 'title': str(title or detail)[:320], 'detail': str(detail or '')[:1200], 'technicalDetail': str(technical_detail or '')[:3000], 'createdAt': created_at, 'tone': tone, 'processMessage': process_message, 'traceOnly': trace_only, 'chatPreferred': not trace_only, 'messageKind': str(message_kind or ''), "conversationTurn": bool(conversation_turn), 'source': str(source or ''), 'turnReceipt': turn_receipt if isinstance(turn_receipt, dict) else None, 'chips': [str(item) for item in list(chips or []) if str(item or '').strip()][:4]})
        for turn_index, dialogue_turn in enumerate(_facade.mission_runtime_dialogue_turns(mission, root=root)):
            turn_text = str(dialogue_turn.get('text') or '')
            dialogue_runtime_id = str(dialogue_turn.get("runtimeId") or mission.runtime_id or '')
            dialogue_runtime_label = _facade.runtime_label(dialogue_runtime_id)
            capture_mode = str(dialogue_turn.get('captureMode') or '').strip()
            capture_label = _facade.runtime_capture_label(capture_mode)
            turn_receipt = {'schema': 'fluxio.agent_dialogue_runtime_provenance.v1', 'sourceKind': str(dialogue_turn.get('sourceKind') or 'real-runtime-output'), 'captureMode': capture_mode, 'captureLabel': capture_label, 'sessionId': str(dialogue_turn.get('sessionId') or ''), 'externalRuntimeSessionId': str(dialogue_turn.get('externalRuntimeSessionId') or ''), 'sourcePath': str(dialogue_turn.get('sourcePath') or ''), 'reportPath': str(dialogue_turn.get('reportPath') or '')}
            append(message_id=f"runtime-dialogue:{mission.mission_id}:{turn_index}:{_facade.hashlib.sha1(turn_text[:400].encode('utf-8')).hexdigest()[:10]}", title=turn_text[:160], detail=turn_text, created_at=str(dialogue_turn.get('createdAt') or ''), role='assistant', label=f'{dialogue_runtime_label} reply', runtime_id=dialogue_runtime_id, tone='neutral', process_message=False, trace_only=False, message_kind='dialogue', conversation_turn=True, source="backend-runtime-reply", turn_receipt=turn_receipt, chips=[str(dialogue_turn.get('model') or ''), str(dialogue_turn.get('provider') or ''), 'real runtime output', capture_label])
        runtime_transcript = runtime_transcript if isinstance(runtime_transcript, dict) else {}
        for item in runtime_transcript.get('messages', []) if isinstance(runtime_transcript.get('messages'), list) else []:
            if not isinstance(item, dict):
                continue
            append(message_id=str(item.get('id') or f'runtime-transcript:{mission.mission_id}:{len(messages)}'), title=str(item.get('title') or item.get('message') or 'Runtime transcript event'), detail=str(item.get('detail') or ''), technical_detail=str(item.get('technicalDetail') or ''), created_at=str(item.get('createdAt') or item.get('created_at') or ''), role=str(item.get('role') or 'runtime'), label=str(item.get('label') or 'Hermes session transcript'), runtime_id=str(item.get('runtimeId') or mission.runtime_id), tone=str(item.get('tone') or 'neutral'), process_message=True, trace_only=bool(item.get('traceOnly')), message_kind=str(item.get('messageKind') or item.get('kind') or 'activity'), conversation_turn=bool(item.get('conversationTurn')), source=str(item.get('source') or 'runtime-transcript'), turn_receipt=item.get('turnReceipt') if isinstance(item.get('turnReceipt'), dict) else None, chips=[str(item.get('sessionId') or ''), str(item.get('kind') or ''), 'real transcript'])
        if runtime_transcript and runtime_transcript.get('status') != 'attached':
            candidate_ids = [str(item) for item in runtime_transcript.get('candidateSessionIds', []) if str(item or '').strip()]
            append(message_id=f'runtime-transcript-integrity:{mission.mission_id}:{mission.updated_at}', title='Hermes session transcript is not attached', detail=str(runtime_transcript.get('detail') or 'The mission points at a runtime session, but no readable session transcript was found under .agent_runs.'), created_at=mission.updated_at or mission.created_at, role='runtime', label='Runtime transcript integrity', runtime_id=mission.runtime_id, tone='bad', process_message=True, trace_only=True, message_kind='integrity', chips=['live data gap', *candidate_ids[:2]])
            runtime_evidence = _facade._mission_runtime_output_evidence_items(mission, runtime_transcript=runtime_transcript)
            artifact_evidence = _facade._mission_artifact_evidence_items(mission, runtime_transcript=runtime_transcript)
            for evidence_index, evidence in enumerate((runtime_evidence + artifact_evidence)[:4]):
                if not isinstance(evidence, dict):
                    continue
                evidence_detail = _facade._gate_text(evidence.get('detail') or '')
                if not _facade._gate_has_meaningful_text(evidence_detail):
                    continue
                evidence_source = str(evidence.get('source') or 'mission evidence')
                append(message_id=f"runtime-evidence:{mission.mission_id}:{evidence_index}:{_facade.hashlib.sha1(evidence_detail.encode('utf-8')).hexdigest()[:10]}", title='Recorded Hermes runtime evidence', detail=evidence_detail, technical_detail=f'Source: {evidence_source}', created_at=mission.updated_at or mission.created_at, role='runtime', label='Hermes runtime evidence', runtime_id=mission.runtime_id, tone='neutral', process_message=True, trace_only=False, message_kind='proof', chips=['real runtime proof', evidence_source[:40]])
        provider_truth = mission.state.provider_runtime_truth if isinstance(mission.state.provider_runtime_truth, dict) else {}
        active_route = provider_truth.get('activeRoute') if isinstance(provider_truth.get('activeRoute'), dict) else {}
        route_provider = str(active_route.get('provider') or '').strip()
        route_model = str(active_route.get('model') or '').strip()
        route_effort = str(active_route.get('effort') or '').strip()
        auth_known = bool(provider_truth.get('authKnown'))
        auth_present = bool(provider_truth.get('authPresent'))
        auth_mode = str(provider_truth.get('authMode') or '').strip()
        last_failure = provider_truth.get('lastFailure') if isinstance(provider_truth.get('lastFailure'), dict) else {}
        last_success = provider_truth.get('lastSuccessfulCall') if isinstance(provider_truth.get('lastSuccessfulCall'), dict) else {}
        delegated_auth_failure_detail = ''
        for session in reversed(list(mission.delegated_runtime_sessions or [])):
            session_provider = str(value(session, 'target_provider') or '').strip()
            session_status = str(value(session, 'status') or '').strip().lower()
            session_detail = str(value(session, 'detail') or '').strip()
            session_detail_normalized = session_detail.lower()
            session_provider_matches = not route_provider or not session_provider or session_provider == route_provider or (route_provider.lower() in session_detail_normalized)
            if session_provider_matches and session_status == 'failed' and any((token in session_detail_normalized for token in ('not authenticated', 'logged out', 'provider_auth_unavailable'))):
                delegated_auth_failure_detail = session_detail
                break
        if provider_truth or active_route:
            effective_auth_present = auth_present and (not delegated_auth_failure_detail)
            auth_detail = delegated_auth_failure_detail if delegated_auth_failure_detail else 'auth present' if effective_auth_present else 'auth not configured' if auth_known else 'auth state unknown'
            route_title = 'Provider route is not authenticated' if delegated_auth_failure_detail or (auth_known and (not effective_auth_present)) else 'Provider route truth'
            route_detail_parts = [f"Route: {route_provider or 'unknown'} / {route_model or 'unknown'}" + (f' / {route_effort}' if route_effort else ''), f'Auth: {auth_detail}' + (f' ({auth_mode})' if auth_mode else '')]
            if last_failure:
                route_detail_parts.append('Last failure: ' + str(last_failure.get('summary') or last_failure.get('error') or last_failure.get('message') or 'recorded'))
            elif last_success:
                route_detail_parts.append('Last recorded action: ' + str(last_success.get('summary') or last_success.get('source') or 'recorded'))
            append(message_id=f"provider-truth:{mission.mission_id}:{provider_truth.get('updatedAt') or mission.updated_at}", title=route_title, detail=' · '.join((part for part in route_detail_parts if part)), created_at=str(provider_truth.get('updatedAt') or mission.updated_at or mission.created_at), role='runtime', label='Provider route truth', runtime_id=mission.runtime_id, tone='warn' if delegated_auth_failure_detail or (auth_known and (not effective_auth_present)) else 'neutral', process_message=True, trace_only=True, message_kind='activity', chips=[route_provider, route_model, 'auth missing' if delegated_auth_failure_detail or (auth_known and (not effective_auth_present)) else ''])
        latest_runtime_cycle = next((item for item in reversed(list(events)) if str(item.get('kind') or item.get('event') or '') == 'mission.runtime_cycle'), None)
        if latest_runtime_cycle:
            metadata = latest_runtime_cycle.get('metadata') if isinstance(latest_runtime_cycle.get('metadata'), dict) else {}
            runtime_status = str(metadata.get('autopilotStatus') or mission.state.status or '').strip()
            cycle_provider = str(metadata.get('provider') or route_provider or '').strip()
            cycle_model = str(metadata.get('model') or route_model or '').strip()
            append(message_id=f"runtime-cycle:{mission.mission_id}:{latest_runtime_cycle.get('timestamp') or latest_runtime_cycle.get('created_at') or ''}", title=f'{_facade.runtime_label(mission.runtime_id)} is still cycling' if runtime_status else f'{_facade.runtime_label(mission.runtime_id)} heartbeat', detail=' · '.join((part for part in (f'Status: {runtime_status}' if runtime_status else '', f'Route: {cycle_provider} / {cycle_model}' if cycle_provider or cycle_model else '', f"Session: {metadata.get('sessionId')}" if metadata.get('sessionId') else '') if part)), created_at=str(latest_runtime_cycle.get('timestamp') or latest_runtime_cycle.get('created_at') or mission.updated_at), role='runtime', label='Runtime heartbeat', runtime_id=mission.runtime_id, tone='neutral', process_message=False, trace_only=True, message_kind='activity', chips=[runtime_status, cycle_provider, cycle_model])
        status_detail = ' · '.join((part for part in (f'Status: {mission.state.status}', 'Current: ' + (mission.state.last_runtime_event or mission.state.last_plan_summary or (mission.state.remaining_steps[0] if mission.state.remaining_steps else '') or mission.objective), f'Next: {_facade.ControlRoomStore._next_mission_detail_action(mission)}') if part))
        append(message_id=f'mission-review:{mission.mission_id}', title=mission.title or mission.objective or 'Mission review', detail=status_detail, created_at=mission.updated_at or mission.created_at, role='runtime', label='Control-room mission state', runtime_id=mission.runtime_id, tone='warn' if mission.state.status in {'blocked', 'needs_approval', 'verification_failed', 'failed'} else 'neutral', process_message=False, trace_only=True, message_kind='activity', chips=[mission.state.status, _facade.runtime_label(mission.runtime_id)])
        for index, revision in enumerate(list(mission.plan_revisions)[-6:]):
            steps = [str(value(step, 'title')) for step in list(value(revision, 'steps', []) or []) if value(step, 'status') != 'completed'][:3]
            append(message_id=f"plan:{value(revision, 'revision_id') or index}", title=str(value(revision, 'summary') or 'Planner revision recorded'), detail=' · '.join(steps), created_at=str(value(revision, 'created_at')), label='Control-room planner', tone='neutral', process_message=True, trace_only=True, message_kind='activity', chips=['planner', str(value(revision, 'trigger'))])
        for action in list(mission.action_history)[-10:]:
            result = value(action, 'result', {}) or {}
            proposal = value(action, 'proposal', {}) or {}
            stdout = str(value(result, 'stdout'))
            error = str(value(result, 'error'))
            result_summary = str(value(result, 'result_summary'))
            detail = error or result_summary or stdout
            if not detail:
                continue
            action_kind = str(value(proposal, 'kind'))
            title = str(value(proposal, 'title'))
            append(message_id=f"action:{value(action, 'action_id') or len(messages)}", title=title or str(value(action, 'action_id')) or 'Mission action', detail=detail, created_at=str(value(action, 'executed_at')), label='Control-room action result', tone='bad' if error else 'neutral', process_message=True, trace_only=True, message_kind='activity', chips=[action_kind, str(value(value(action, 'gate', {}) or {}, 'status'))])
        for session in list(mission.delegated_runtime_sessions)[-6:]:
            session_id = str(value(session, 'delegated_id') or value(session, 'runtime_id'))
            session_runtime = str(value(session, 'runtime_id'))
            session_status = str(value(session, 'status'))
            session_status_normalized = session_status.lower()
            session_detail = str(value(session, 'detail') or '')
            session_failure_visible = session_status_normalized in {'failed', 'blocked'} or any((token in session_detail.lower() for token in ('not authenticated', 'logged out', 'provider_auth_unavailable', 'failed', 'blocked', 'error')))
            append(message_id=f'session:{session_id}', title=str(value(session, 'last_event') or session_detail or f'{_facade.runtime_label(session_runtime)} lane {session_status}'), detail=str(value(session, 'execution_target_detail') or value(session, 'execution_root') or ''), created_at=str(value(session, 'updated_at')), label=f'{_facade.runtime_label(session_runtime)} lane failed' if session_failure_visible else f'{_facade.runtime_label(session_runtime)} lane', runtime_id=session_runtime, tone='bad' if session_status == 'failed' else 'warn' if session_status == 'waiting_for_approval' else 'neutral', process_message=True, trace_only=not session_failure_visible, message_kind='activity', chips=[session_status, str(value(session, 'execution_target'))])
            for event_index, event in enumerate(list(value(session, 'latest_events', []) or [])[-8:]):
                kind = str(event.get('kind') or 'runtime.event')
                event_message = str(event.get('message') or event.get('detail') or '').strip()
                is_runtime_output_event = _facade.is_process_runtime_kind(kind)
                event_status = str(event.get('status') or '').lower()
                event_detail = str(event.get('detail') or event.get('trace') or '')
                event_text = f'{kind} {event_status} {event_message} {event_detail}'.lower()
                visible_runtime_status = kind.lower() in {'session.failed', 'session.completed', 'session.stopped', 'runtime.failed', 'runtime.error'} or event_status in {'failed', 'blocked'} or any((token in event_text for token in ('not authenticated', 'logged out', 'provider_auth_unavailable', 'failed', 'blocked', 'error')))
                append(message_id=f"session-event:{session_id}:{event.get('event_id') or event_index}", title=event_message or kind, detail=event_detail[:1200], created_at=str(event.get('created_at') or value(session, 'updated_at')), label='Hermes runtime output' if is_runtime_output_event and session_runtime == 'hermes' else 'Runtime failure' if visible_runtime_status and (event_status == 'failed' or 'failed' in kind.lower()) else kind, runtime_id=session_runtime, tone='bad' if event_status == 'failed' or 'failed' in kind.lower() else 'neutral', process_message=True, trace_only=not (is_runtime_output_event or visible_runtime_status), message_kind='activity', chips=[kind, str(event.get('status') or '')])
        for index, event in enumerate(list(events)[-limit:]):
            kind = str(event.get('kind') or event.get('event') or 'mission.event')
            if kind == 'mission.runtime_cycle':
                continue
            message = str(event.get('message') or event.get('detail') or '').strip()
            if not message:
                continue
            event_is_operator_dialogue = kind.lower() in {'mission.follow_up', 'operator.followup', 'operator.message'} or any((token in kind.lower() for token in ('follow_up', 'followup', 'operator', 'user')))
            append(message_id=f"event:{event.get('timestamp', '')}:{kind}:{index}", title=message, detail=str(event.get('detail') or '')[:1200], created_at=str(event.get('timestamp') or event.get('created_at') or ''), role='operator' if event_is_operator_dialogue else 'queue' if 'approval' in kind or 'question' in kind else 'runtime', label=kind, runtime_id=str(event.get('runtime_id') or mission.runtime_id), tone='bad' if any((token in kind.lower() for token in ('failed', 'error', 'blocked'))) else 'warn' if 'approval' in kind.lower() else 'neutral', process_message=True, trace_only=False if event_is_operator_dialogue else not ('approval' in kind.lower() or 'question' in kind.lower()), message_kind='dialogue' if event_is_operator_dialogue else 'activity', conversation_turn=event_is_operator_dialogue, chips=[kind])
        messages.sort(key=lambda item: item.get('createdAt', ''))
        return messages[-limit:]


    @staticmethod
    def _next_mission_detail_action(
        mission: Mission,
        *,
        artifact_gate: dict | None = None,
    ) -> str:
        _facade = _control_room_facade()
        artifact_gate = artifact_gate if isinstance(artifact_gate, dict) else _facade.mission_hard_artifact_gate(mission)
        if mission.state.status == "completed" and not bool(artifact_gate.get("passed")):
            return "Resume with a hard artifact gate; this completion is missing a runtime-output body or served artifact."
        latest_session = (
            mission.delegated_runtime_sessions[-1]
            if mission.delegated_runtime_sessions
            else None
        )
        if mission.proof.pending_approvals:
            return "Review pending approvals before resuming mission work."
        if mission.proof.failed_checks:
            return "Fix failed checks, then resume the mission detail loop."
        if latest_session and latest_session.status in {"running", "waiting_for_approval"}:
            return "Watch delegated runtime events until a completion or blocker lands."
        if mission.state.status == "completed":
            return "Review proof and close or archive the mission."
        if mission.state.status in {"blocked", "failed"}:
            return "Resolve the blocker and resume after evidence changes."
        return "Resume the mission if the objective still has remaining work."


    @staticmethod
    def _latest_notification_agent_message(
        mission: Mission,
        *,
        root: Path | None = None,
        workspace: WorkspaceProfile | None = None,
    ) -> tuple[str, str]:
        """Return the freshest concrete runtime/report text for notification cards."""
        _facade = _control_room_facade()

        def value(row: object, key: str, default: object = "") -> object:
            if isinstance(row, dict):
                return row.get(key, default)
            return getattr(row, key, default)

        def concrete_text(item: dict) -> str:
            title = str(item.get("title") or item.get("message") or "").strip()
            detail = str(item.get("detail") or "").strip()
            if title and detail and detail != title:
                return f"{title}\n{detail}"
            return title or detail

        def low_signal(message: str) -> bool:
            text = message.strip().lower()
            return (
                not text
                or text == "running"
                or "delegated runtime heartbeat" in text
                or "git_diff completed with filesystem snapshot" in text
                or "git is unavailable" in text
                or text == "file mutation completed."
                or text == "file read completed."
            )

        should_hydrate_live_transcript = str(mission.state.status or "").strip().lower() in {
            "running",
            "queued",
            "launching",
            "waiting_for_approval",
        }
        if root and should_hydrate_live_transcript:
            try:
                transcript = _facade.ControlRoomStore._mission_runtime_transcript_payload(
                    mission,
                    events=[],
                    root=root,
                    workspace=workspace,
                    limit=6,
                )
            except Exception:
                transcript = {}
            transcript_messages = (
                transcript.get("messages", [])
                if isinstance(transcript, dict) and isinstance(transcript.get("messages"), list)
                else []
            )
            for item in reversed(transcript_messages):
                if not isinstance(item, dict) or not item.get("runtimeOutput"):
                    continue
                message = concrete_text(item)
                if not low_signal(message):
                    if str(item.get("source") or "") == "delegated-runtime-event":
                        runtime_id = str(item.get("runtimeId") or mission.runtime_id or "")
                        session_id = str(item.get("sessionId") or transcript.get("sessionId") or "")
                        return message, f"runtime_output:{runtime_id}:{session_id}"
                    return message, f"runtime_transcript:{item.get('sessionId') or transcript.get('sessionId') or ''}"
            for item in reversed(transcript_messages):
                if not isinstance(item, dict):
                    continue
                message = concrete_text(item)
                if not low_signal(message):
                    return message, f"runtime_transcript:{item.get('sessionId') or transcript.get('sessionId') or ''}"

        latest_event_message = ""
        latest_event_source = ""
        for session in reversed(list(mission.delegated_runtime_sessions or [])[-8:]):
            session_runtime = str(value(session, "runtime_id") or mission.runtime_id)
            session_id = str(value(session, "delegated_id") or value(session, "runtime_id") or "")
            for event in reversed(list(value(session, "latest_events", []) or [])[-16:]):
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("kind") or "").strip()
                message = str(event.get("message") or event.get("detail") or event.get("trace") or "").strip()
                if low_signal(message):
                    continue
                source = "runtime_output" if _facade.is_process_runtime_kind(kind) else "runtime_event"
                if _facade.is_process_runtime_kind(kind):
                    return message, f"{source}:{session_runtime}:{session_id}"
                if not latest_event_message:
                    latest_event_message = message
                    latest_event_source = f"{source}:{session_runtime}:{session_id}"
            last_event = str(value(session, "last_event") or value(session, "detail") or "").strip()
            if not low_signal(last_event) and not latest_event_message:
                latest_event_message = last_event
                latest_event_source = f"session_last_event:{session_runtime}:{session_id}"
        if latest_event_message:
            return latest_event_message, latest_event_source

        if root and should_hydrate_live_transcript:
            for item in reversed(_facade._mission_runtime_output_evidence_items(mission)):
                message = str(item.get("detail") or "").strip()
                if not low_signal(message):
                    return message, f"runtime_output:{mission.runtime_id}:hard_artifact_gate"

        for action in reversed(list(mission.action_history or [])[-8:]):
            result = value(action, "result", {}) or {}
            if not isinstance(result, dict):
                continue
            message = str(
                result.get("result_summary")
                or result.get("stdout")
                or result.get("error")
                or ""
            ).strip()
            if not low_signal(message):
                return message, "action_history"

        fallback = (
            mission.state.last_error
            or mission.proof.summary
            or mission.state.last_plan_summary
            or (mission.state.remaining_steps[0] if mission.state.remaining_steps else "")
            or (mission.state.last_runtime_event if mission.state.last_runtime_event != "running" else "")
            or mission.objective
            or "Mission status changed."
        )
        return str(fallback or "").strip(), "mission_state"


    @staticmethod
    @_control_checked('notifications')
    def _build_notification_feed(*, missions: list[Mission], activity: list[dict], watchdog_report: dict | None=None, root: Path | None=None, workspace_by_id: dict[str, WorkspaceProfile] | None=None, limit: int=24) -> list[dict]:
        _facade = _control_room_facade()
        notifications: list[dict] = []
        hydration_store = _facade.ControlRoomStore(root) if root is not None else None
        live_mission_ids = {mission.mission_id for mission in missions}
        runtime_hydration_mission_ids = {mission.mission_id for mission in missions if not mission.delegated_runtime_sessions and str(mission.state.status or '').strip().lower() in {'running', 'queued', 'launching', 'waiting_for_approval'}}
        recovered_sessions_by_mission = hydration_store._delegated_sessions_by_workflow_mission(runtime_hydration_mission_ids) if hydration_store is not None and runtime_hydration_mission_ids else {}
        blocking_cutoff = _facade._parse_iso_datetime(hydration_store.blocking_metrics_since() or '') if hydration_store is not None else None

        def belongs_to_current_window(item: dict) -> bool:
            mission_id = str(item.get('missionId') or item.get('mission_id') or '').strip()
            if mission_id and mission_id != 'control_room' and (mission_id not in live_mission_ids):
                return False
            if blocking_cutoff is None:
                return True
            timestamp = _facade._parse_iso_datetime(str(item.get('detectedAt') or item.get('timestamp') or item.get('createdAt') or ''))
            return timestamp is None or timestamp >= blocking_cutoff
        for mission in missions:
            notification_mission = mission
            if hydration_store is not None and (not mission.delegated_runtime_sessions):
                recovered_sessions = recovered_sessions_by_mission.get(mission.mission_id, [])
                if recovered_sessions:
                    notification_mission = _facade.replace(mission, delegated_runtime_sessions=recovered_sessions)
            status = mission.state.status
            severity = 'info'
            if status in {'blocked', 'needs_approval', 'verification_failed', 'failed'}:
                severity = 'action'
            elif status == 'completed':
                severity = 'success'
            elif mission.state.queue_position > 0:
                severity = 'queued'
            agent_message, agent_message_source = _facade.ControlRoomStore._latest_notification_agent_message(notification_mission, root=root, workspace=(workspace_by_id or {}).get(mission.workspace_id))
            if status not in _facade.TERMINAL_MISSION_STATUSES and status not in {'blocked', 'needs_approval', 'verification_failed', 'failed'} and (not agent_message_source.startswith(('runtime_transcript:', 'runtime_output:'))):
                continue
            detail = agent_message
            notifications.append({'id': f'mission:{mission.mission_id}:{status}', 'kind': 'mission_status', 'severity': severity, 'title': mission.title or mission.mission_id, 'detail': str(detail or '')[:320], 'agentMessage': agent_message[:320], 'agentMessageSource': agent_message_source, 'missionId': mission.mission_id, 'workspaceId': mission.workspace_id, 'status': status, 'createdAt': mission.updated_at or mission.created_at, 'action': 'open_mission'})
            if status == 'completed' and agent_message_source.startswith(('runtime_transcript:', 'runtime_output:')):
                slice_message = f'Slice completed for {mission.title or mission.mission_id}. {agent_message}'.strip()
                notifications.append({'id': f'slice:{mission.mission_id}:mission_completed', 'kind': 'mission_slice_completed', 'severity': 'success', 'title': f'Slice completed: {mission.title or mission.mission_id}', 'detail': slice_message[:320], 'agentMessage': slice_message[:320], 'agentMessageSource': agent_message_source, 'missionId': mission.mission_id, 'workspaceId': mission.workspace_id, 'status': 'completed', 'createdAt': mission.updated_at or mission.created_at, 'action': 'open_mission_slice'})
            for index, feedback in enumerate(list(mission.learned_skill_events or [])[-6:]):
                if not isinstance(feedback, dict):
                    continue
                kind = str(feedback.get('kind') or '')
                if 'slice' not in kind and 'feedback' not in kind:
                    continue
                skill_id = str(feedback.get('skillId') or feedback.get('skill_id') or 'mission skill')
                system_loss = feedback.get('systemLoss', feedback.get('system_loss', ''))
                loss_label = ''
                try:
                    loss_label = f'system gap {float(system_loss):.2f}'
                except (TypeError, ValueError):
                    if system_loss != '':
                        loss_label = f'system gap {system_loss}'
                next_action = str(feedback.get('nextAction') or feedback.get('next_action') or 'recorded')
                detail_parts = [f'Slice completed for {skill_id}.', loss_label, f'Next action: {next_action}.']
                agent_message = ' '.join((part for part in detail_parts if part))
                notifications.append({'id': f'slice:{mission.mission_id}:{index}:{skill_id}:{next_action}', 'kind': 'mission_slice_completed', 'severity': 'success', 'title': f'Slice completed: {mission.title or mission.mission_id}', 'detail': agent_message[:320], 'agentMessage': agent_message[:320], 'missionId': mission.mission_id, 'workspaceId': mission.workspace_id, 'status': 'completed', 'createdAt': str(feedback.get('timestamp') or mission.updated_at or mission.created_at), 'action': 'open_mission_slice'})
        for problem in ((watchdog_report or {}).get('problemReport', {}).get('openProblems', []) if isinstance(watchdog_report, dict) else [])[:6]:
            if not belongs_to_current_window(problem):
                continue
            severity = str(problem.get('severity') or 'info')
            agent_message = str(problem.get('firstStep') or problem.get('detail') or '').strip()
            notifications.append({'id': f"watchdog:{problem.get('problemId', '')}", 'kind': 'watchdog_problem', 'severity': 'action' if severity in {'bad', 'warn'} else 'info', 'title': str(problem.get('title') or 'Watchdog problem'), 'detail': agent_message[:320], 'agentMessage': agent_message[:320], 'missionId': str(problem.get('missionId') or ''), 'workspaceId': str(problem.get('workspaceId') or ''), 'status': str(problem.get('status') or 'open'), 'createdAt': str(problem.get('detectedAt') or _facade.utc_now_iso()), 'action': 'open_watchdog_problem'})
        for event in activity[:limit]:
            if not belongs_to_current_window(event):
                continue
            event_kind = str(event.get('kind') or 'activity')
            if event_kind == 'mission.runtime_cycle':
                continue
            event_message = str(event.get('message') or '')
            agent_message = event_message.strip()
            is_slice_event = 'slice' in event_kind.lower() and ('complete' in event_kind.lower() or 'completed' in event_message.lower() or 'feedback' in event_kind.lower())
            notifications.append({'id': f"event:{event.get('timestamp', '')}:{event.get('kind', '')}", 'kind': 'mission_slice_completed' if is_slice_event else event_kind, 'severity': 'success' if is_slice_event else 'info', 'title': 'Slice completed' if is_slice_event else event_kind, 'detail': event_message[:320], 'agentMessage': agent_message[:320], 'missionId': str(event.get('mission_id') or event.get('missionId') or ''), 'workspaceId': str(event.get('workspace_id') or event.get('workspaceId') or ''), 'createdAt': str(event.get('timestamp') or ''), 'action': 'open_mission_slice' if is_slice_event else 'open_activity'})
        notifications.sort(key=lambda item: item.get('createdAt', ''), reverse=True)
        limited = notifications[:limit]
        if limit > 0 and (not any((item.get('kind') == 'mission_slice_completed' for item in limited))):
            first_slice = next((item for item in notifications if item.get('kind') == 'mission_slice_completed'), None)
            if first_slice:
                replace_index = next((index for index in range(len(limited) - 1, -1, -1) if limited[index].get('severity') not in {'action', 'queued'}), len(limited) - 1)
                if limited:
                    limited[replace_index] = first_slice
                else:
                    limited.append(first_slice)
                limited.sort(key=lambda item: item.get('createdAt', ''), reverse=True)
        return limited
