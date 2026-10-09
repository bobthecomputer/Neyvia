"""Fast, deterministic acceptance journeys for Neyvia's mission runtime.

This harness intentionally uses the in-process MCP stub. It exercises the same
broker receipts, approval gates, continuity store, retry policy, GPU policy, and
security scope contracts as a live journey without touching accounts, browsers,
files outside its root, paid compute, or the network.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .continuity_policy import MissionContinuityStore
from .durability import atomic_write_json
from .mcp_broker import McpOutboundBroker
from .neyvia_stage_scheduler import (
    build_progressive_step_handler,
    execute_neyvia_stages,
)
from .security_runtime_policy import (
    audit_security_tool_coverage,
    build_purple_team_plan,
    evaluate_security_action,
)


ACCEPTANCE_SCHEMA = "neyvia.mission_acceptance_harness.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tool(
    name: str,
    description: str,
    *,
    mutating: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "additionalProperties": True},
        "annotations": {
            "readOnlyHint": not mutating,
            "requiresApproval": mutating,
        },
    }


def acceptance_mcp_config() -> dict[str, Any]:
    """Return a complete, network-free MCP landscape for the five journeys."""

    return {
        "servers": {
            "research-primary": {
                "transport": "stub",
                "authState": "unauthenticated",
                "tools": [_tool("search_tasks", "Search the primary task source.")],
            },
            "research-backup": {
                "transport": "stub",
                "authState": "authenticated",
                "tools": [_tool("search_tasks", "Search a justified alternative source.")],
            },
            "filesystem": {
                "transport": "stub",
                "authState": "authenticated",
                "tools": [_tool("transfer_file", "Transfer one selected file.", mutating=True)],
            },
            "thunder": {
                "transport": "stub",
                "authState": "authenticated",
                "tools": [
                    _tool("inspect_instance", "Observe GPU, job, checkpoint, and cost state."),
                    _tool("resume_training", "Resume an existing checkpoint.", mutating=True),
                    _tool("stop_instance", "Release the selected paid GPU.", mutating=True),
                ],
            },
            "security": {
                "transport": "stub",
                "authState": "authenticated",
                "tools": [
                    _tool("threat_model", "Bind target, trust boundary, and authorization."),
                    _tool("run_bounded_probe", "Run a bounded authorized lab probe."),
                    _tool(
                        "collect_detection_evidence",
                        "Collect defender detection evidence.",
                    ),
                    _tool("apply_remediation", "Apply a scoped remediation.", mutating=True),
                    _tool("independent_retest", "Retest independently after remediation."),
                ],
            },
        }
    }


class MissionAcceptanceHarness:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.store = MissionContinuityStore(self.root)
        self.broker = McpOutboundBroker(
            self.root,
            config=acceptance_mcp_config(),
            include_default_demo=False,
        )
        self.receipt_dir = self.root / ".agent_control" / "neyvia" / "acceptance"
        self.receipt_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict[str, Any]:
        started = time.perf_counter()
        started_cpu = time.process_time()
        journeys = [
            self._research_fallback_journey(),
            self._proportional_transfer_journey(),
            self._gpu_continuity_journey(),
            self._compiled_scheduler_journey(),
            self._purple_team_journey(),
        ]
        payload = {
            "schema": ACCEPTANCE_SCHEMA,
            "runId": self.run_id,
            "generatedAt": _now(),
            "simulated": True,
            "networkUsed": False,
            "paidComputeUsed": False,
            "externalAccountsUsed": False,
            "ok": all(item["ok"] for item in journeys),
            "durationMs": max(1, int((time.perf_counter() - started) * 1000)),
            # Wall time is dominated by durable fsync latency of the storage
            # device; the harness's own work budget is its process CPU time.
            "cpuMs": max(1, int((time.process_time() - started_cpu) * 1000)),
            "journeys": journeys,
            "summary": {
                "passed": sum(1 for item in journeys if item["ok"]),
                "total": len(journeys),
                "failed": [item["id"] for item in journeys if not item["ok"]],
            },
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.receipt_dir / (
            f"{stamp}_{self.run_id[:12]}_mission_acceptance.json"
        )
        payload["receiptPath"] = str(path)
        atomic_write_json(path, payload)
        from .proofs_c_missions import check_acceptance
        check_acceptance(payload, path)
        return payload

    def _research_fallback_journey(self) -> dict[str, Any]:
        mission_id = f"acceptance-research-fallback-{self.run_id}"
        action = {"kind": "research_task_search"}
        self.store.create_or_update(
            mission_id,
            goal="Find legitimate paying tasks and return evidence, not only a plan.",
            patch={
                "status": "running",
                "currentStep": "Search the primary source.",
                "nextAction": "Use a justified alternative if the primary source is unavailable.",
            },
            event_kind="journey_started",
        )
        primary = self.broker.call(
            "research-primary",
            "search_tasks",
            {"constraints": ["legitimate", "paid", "small-scope"]},
            mission_id=mission_id,
        )
        self.store.record_tool_attempt(
            mission_id,
            tool=primary["tool"],
            idempotency_key="research-primary-v1",
            action=action,
            outcome="failed",
            evidence={"receipt": primary["receipt_path"]},
            error=primary["error"],
            alternative="mcp.research-backup.search_tasks",
        )
        decision = self.store.retry_decision(
            mission_id,
            tool=primary["tool"],
            action=action,
            transient=False,
            alternative_available=True,
        )
        backup = self.broker.call(
            "research-backup",
            "search_tasks",
            {"constraints": ["legitimate", "paid", "small-scope"]},
            mission_id=mission_id,
        )
        recorded = self.store.record_tool_attempt(
            mission_id,
            tool=backup["tool"],
            idempotency_key="research-backup-v1",
            action=action,
            outcome="verified",
            evidence={
                "receipt": backup["receipt_path"],
                "resultCount": 3,
                "filtered": True,
                "nextAction": "Review the three evidence-linked candidates.",
            },
        )
        duplicate = self.store.record_tool_attempt(
            mission_id,
            tool=backup["tool"],
            idempotency_key="research-backup-v1",
            action=action,
            outcome="verified",
        )
        self.store.create_or_update(
            mission_id,
            patch={
                "status": "completed",
                "lastCompletedStep": "Returned filtered evidence-linked candidates.",
                "currentStep": "",
                "nextAction": "Operator reviews the candidates.",
            },
            event_kind="journey_completed",
        )
        checks = {
            "primaryFailedHonestly": primary["status"] == "auth_required",
            "usedJustifiedAlternative": decision["decision"] == "use_alternative",
            "alternativeVerified": backup["ok"] and recorded["attempt"]["outcome"] == "verified",
            "duplicateSuppressed": duplicate["duplicateSuppressed"] is True,
        }
        return {
            "id": "research-fallback",
            "ok": all(checks.values()),
            "checks": checks,
            "evidence": [primary["receipt_path"], backup["receipt_path"]],
        }

    def _proportional_transfer_journey(self) -> dict[str, Any]:
        mission_id = f"acceptance-proportional-transfer-{self.run_id}"
        action = {"kind": "file_transfer"}
        self.store.create_or_update(
            mission_id,
            goal="Transfer one selected file with one proportionate verification receipt.",
            patch={"status": "running", "currentStep": "Transfer the selected file."},
            event_kind="journey_started",
        )
        transfer = self.broker.call(
            "filesystem",
            "transfer_file",
            {
                "source": "fixture/source.bin",
                "target": "fixture/desktop/source.bin",
            },
            approved=True,
            approval_id="acceptance-local-transfer",
            mission_id=mission_id,
        )
        recorded = self.store.record_tool_attempt(
            mission_id,
            tool=transfer["tool"],
            idempotency_key="transfer-source-bin-v1",
            action=action,
            outcome="verified",
            evidence={
                "targetExists": True,
                "sizeMatches": True,
                "sha256Matches": True,
                "unrelatedChecksRun": 0,
            },
        )
        verification = recorded["attempt"]["verification"]
        checks = {
            "singleToolCallCompleted": transfer["ok"],
            "exactVerificationDepth": verification["checks"]
            == ["target_exists", "size_or_hash_matches"],
            "noUnrelatedChecks": recorded["attempt"]["evidence"]["unrelatedChecksRun"] == 0,
        }
        self.store.create_or_update(
            mission_id,
            patch={
                "status": "completed",
                "lastCompletedStep": "Transferred and verified the selected file.",
            },
            event_kind="journey_completed",
        )
        return {
            "id": "proportional-transfer",
            "ok": all(checks.values()),
            "checks": checks,
            "evidence": [transfer["receipt_path"]],
        }

    def _gpu_continuity_journey(self) -> dict[str, Any]:
        mission_id = f"acceptance-gpu-continuity-{self.run_id}"
        self.store.create_or_update(
            mission_id,
            goal="Resume an ASR checkpoint, preserve evidence, then release paid compute.",
            patch={
                "status": "running",
                "gpuPolicy": {
                    "maxConcurrentInstances": 1,
                    "maxEstimatedHourlyCost": 2.0,
                    "maxEstimatedSessionCost": 4.0,
                    "maxDurationMinutes": 120,
                    "idleReleaseMinutes": 10,
                    "minObservationIntervalSeconds": 15,
                    "maxConsecutiveUnchangedObservations": 3,
                    "requireApprovalForPaidStart": True,
                    "requireApprovalForDestructiveAction": True,
                    "preferExistingCheckpoint": True,
                },
            },
            event_kind="journey_started",
        )
        inspect = self.broker.call(
            "thunder",
            "inspect_instance",
            {"instance": "gpu-fixture-1"},
            mission_id=mission_id,
        )
        observed = {
            "runningInstances": 0,
            "validCheckpoint": True,
            "checkpoint": "asr-step-420",
            "runningDurationMinutes": 0,
            "idleMinutes": 0,
        }
        start_decision = self.store.evaluate_gpu_action(
            mission_id,
            {
                "action": "start_instance",
                "paid": True,
                "estimatedHourlyCost": 1.5,
                "estimatedDurationMinutes": 90,
            },
            observed,
        )
        capacity_decision = self.store.evaluate_gpu_action(
            mission_id,
            {
                "action": "start_instance",
                "paid": True,
                "estimatedHourlyCost": 1.0,
                "estimatedDurationMinutes": 30,
            },
            {
                **observed,
                "runningInstances": 1,
                "validCheckpoint": False,
            },
        )
        rapid_poll_decision = self.store.evaluate_gpu_action(
            mission_id,
            {"action": "inspect_gpu"},
            {
                **observed,
                "secondsSinceLastObservation": 2,
                "consecutiveUnchangedObservations": 1,
            },
        )
        unchanged_poll_decision = self.store.evaluate_gpu_action(
            mission_id,
            {"action": "inspect_gpu"},
            {
                **observed,
                "secondsSinceLastObservation": 30,
                "consecutiveUnchangedObservations": 3,
            },
        )
        urgent_poll_decision = self.store.evaluate_gpu_action(
            mission_id,
            {"action": "inspect_gpu", "stateChangeExpected": True},
            {
                **observed,
                "secondsSinceLastObservation": 2,
                "consecutiveUnchangedObservations": 3,
            },
        )
        resume = self.broker.call(
            "thunder",
            "resume_training",
            {"checkpoint": "asr-step-420"},
            approved=True,
            approval_id="acceptance-resume-checkpoint",
            mission_id=mission_id,
        )
        self.store.record_tool_attempt(
            mission_id,
            tool=resume["tool"],
            idempotency_key="resume-asr-step-420",
            action={"kind": "gpu_resume_training"},
            outcome="verified",
            evidence={"checkpoint": "asr-step-420", "state": "running"},
        )
        self.store.record_tool_attempt(
            mission_id,
            tool="mcp.thunder.inspect_instance",
            idempotency_key="gpu-observation-interrupted",
            action={"kind": "gpu_state_poll"},
            outcome="failed",
            error="simulated_context_restart",
        )
        after_restart = MissionContinuityStore(self.root)
        recovery = after_restart.recover(mission_id)
        reobserve = self.broker.call(
            "thunder",
            "inspect_instance",
            {"instance": "gpu-fixture-1", "reason": "reconcile-after-restart"},
            mission_id=mission_id,
        )
        after_restart.record_tool_attempt(
            mission_id,
            tool=reobserve["tool"],
            idempotency_key="gpu-reobserve-after-restart",
            action={"kind": "gpu_state_inspection"},
            outcome="verified",
            evidence={"state": "running", "checkpoint": "asr-step-420"},
        )
        release_decision = after_restart.evaluate_gpu_action(
            mission_id,
            {"action": "continue_training"},
            {
                "runningInstances": 1,
                "validCheckpoint": True,
                "runningDurationMinutes": 45,
                "idleMinutes": 12,
            },
        )
        stop = self.broker.call(
            "thunder",
            "stop_instance",
            {"instance": "gpu-fixture-1", "checkpoint": "asr-step-420"},
            approved=True,
            approval_id="acceptance-release-idle-gpu",
            mission_id=mission_id,
        )
        after_restart.record_tool_attempt(
            mission_id,
            tool=stop["tool"],
            idempotency_key="stop-gpu-fixture-1",
            action={"kind": "gpu_stop_instance"},
            outcome="verified",
            evidence={
                "instance": "gpu-fixture-1",
                "state": "stopped",
                "checkpoint": "asr-step-420",
                "estimatedCost": 1.13,
            },
        )
        after_restart.create_or_update(
            mission_id,
            patch={
                "status": "completed",
                "lastCompletedStep": "Checkpoint preserved and paid GPU released.",
                "nextAction": "Review ASR evidence before another paid run.",
            },
            event_kind="journey_completed",
        )
        final_recovery = after_restart.recover(mission_id)
        checks = {
            "inspectedBeforeAction": inspect["ok"],
            "preferredCheckpointOverNewStart": start_decision["preferResume"] is True,
            "paidStartWouldRequireApproval": start_decision["approvalRequired"] is True,
            "capacityPreventsDuplicateGpuStart": capacity_decision["allowed"] is False,
            "rapidPollingUsesBackoff": (
                rapid_poll_decision["allowed"] is False
                and rapid_poll_decision["pollBackoffRequired"] is True
            ),
            "unchangedPollingUsesBackoff": (
                unchanged_poll_decision["allowed"] is False
                and unchanged_poll_decision["pollBackoffRequired"] is True
            ),
            "expectedStateChangeCanBeObservedImmediately": urgent_poll_decision["allowed"] is True,
            "resumedExistingCheckpoint": resume["ok"],
            "restartRequiredReconciliation": recovery["status"] == "reconcile_required",
            "reobservedBeforeContinuing": reobserve["ok"],
            "idlePolicyRequiredRelease": release_decision["releaseRequired"] is True,
            "releasedGpu": stop["ok"],
            "durableFinalResume": final_recovery["status"] == "resume",
        }
        return {
            "id": "gpu-continuity",
            "ok": all(checks.values()),
            "checks": checks,
            "evidence": [
                inspect["receipt_path"],
                resume["receipt_path"],
                reobserve["receipt_path"],
                stop["receipt_path"],
            ],
        }

    def _compiled_scheduler_journey(self) -> dict[str, Any]:
        """Prove a compiled mission reaches the broker and keeps approval receipts."""

        mission_id = f"acceptance-compiled-scheduler-{self.run_id}"
        source = r'''
NEYVIA/1
GOAL text="Inspect paid compute, then resume only with operator approval and proof"
BUDGET context=4000 reserve=500 wall=30 repairs=0
LANE operator runtime=neyvia-native model=none effort=none permissions=read,write
STEP inspect lane=operator action=tool tool=mcp.thunder.inspect_instance risk=read args='{"instance":"gpu-fixture-1"}'
STEP resume lane=operator action=tool tool=mcp.thunder.resume_training after=inspect risk=external_write args='{"checkpoint":"asr-step-420"}'
VERIFY prove lane=operator after=resume args='{"verificationScore":1.0}' accept="approved resume produced a durable MCP receipt"
STOP when="approved checkpoint resume is verified"
'''
        blocked = execute_neyvia_stages(
            self.root,
            source,
            mission_id=mission_id,
            initial_context={"executionId": f"{self.run_id}-blocked"},
            step_handler=build_progressive_step_handler(
                self.root,
                broker=self.broker,
            ),
        )
        approved = execute_neyvia_stages(
            self.root,
            source,
            mission_id=mission_id,
            initial_context={"executionId": f"{self.run_id}-approved"},
            step_handler=build_progressive_step_handler(
                self.root,
                broker=self.broker,
                approved_mutations=True,
                approval_id="acceptance-compiled-resume",
            ),
        )
        checks = {
            "compiledPlanRan": blocked["language"] == "NEYVIA/1",
            "mutationBlockedWithoutApproval": (
                blocked["interrupted"] is True
                and blocked["interruptReason"] == "step_failed:resume"
                and blocked["completedStepIds"] == ["inspect"]
            ),
            "approvedPlanCompleted": (
                approved["ok"] is True
                and approved["completedStepIds"] == ["inspect", "resume", "prove"]
            ),
            "verificationReached": approved["bestVerificationScore"] == 1.0,
            "attemptReceiptsPreserved": (
                blocked["receiptPath"] != approved["receiptPath"]
                and Path(blocked["receiptPath"]).exists()
                and Path(approved["receiptPath"]).exists()
            ),
        }
        self.store.create_or_update(
            mission_id,
            goal="Run the compiled scheduler through the fake MCP with approval proof.",
            patch={
                "status": "completed" if all(checks.values()) else "blocked",
                "lastCompletedStep": "Approved compiled mission completed with proof.",
                "nextAction": "Use the same scheduler contract with connected providers.",
                "metadata": {
                    "planHash": approved["planHash"],
                    "blockedReceipt": blocked["receiptPath"],
                    "approvedReceipt": approved["receiptPath"],
                },
            },
            event_kind="journey_completed",
        )
        return {
            "id": "compiled-scheduler",
            "ok": all(checks.values()),
            "checks": checks,
            "evidence": [blocked["receiptPath"], approved["receiptPath"]],
        }

    def _purple_team_journey(self) -> dict[str, Any]:
        mission_id = f"acceptance-purple-team-{self.run_id}"
        scope = {
            "target": "neyvia-fixture.local",
            "authorizedBy": "acceptance-harness",
            "authorizationConfirmed": True,
            "environment": "lab",
            "mode": "active",
            "allowedTargets": ["neyvia-fixture.local"],
            "excludedTargets": ["third-party.invalid"],
            "allowedActionClasses": ["probe", "detection", "remediation", "retest"],
            "maxProbeAttempts": 3,
        }
        plan = build_purple_team_plan(scope)
        unscoped = evaluate_security_action(
            {"target": "neyvia-fixture.local", "mode": "active"},
            {"actionClass": "probe", "active": True},
        )
        authorized_probe = evaluate_security_action(
            scope,
            {
                "target": "neyvia-fixture.local",
                "actionClass": "probe",
                "active": True,
            },
        )
        high_risk = evaluate_security_action(
            scope,
            {
                "target": "neyvia-fixture.local",
                "actionClass": "credential_access",
                "active": True,
            },
        )
        tool_rows = self.broker.search("", server="security", limit=20)
        coverage = audit_security_tool_coverage(
            [row["qualifiedName"] for row in tool_rows]
        )
        calls = [
            self.broker.call(
                "security",
                "threat_model",
                {"target": scope["target"]},
                mission_id=mission_id,
            ),
            self.broker.call(
                "security",
                "run_bounded_probe",
                {"target": scope["target"], "maxAttempts": 3},
                mission_id=mission_id,
            ),
            self.broker.call(
                "security",
                "collect_detection_evidence",
                {"target": scope["target"]},
                mission_id=mission_id,
            ),
            self.broker.call(
                "security",
                "apply_remediation",
                {"target": scope["target"], "finding": "fixture-finding"},
                approved=True,
                approval_id="acceptance-remediation",
                mission_id=mission_id,
            ),
            self.broker.call(
                "security",
                "independent_retest",
                {"target": scope["target"], "finding": "fixture-finding"},
                mission_id=mission_id,
            ),
        ]
        checks = {
            "unscopedActiveProbeBlocked": unscoped["allowed"] is False,
            "authorizedLabProbeAllowed": authorized_probe["allowed"] is True,
            "unapprovedHighRiskClassBlocked": high_risk["allowed"] is False,
            "redAndBluePhasesPresent": {
                item["owner"] for item in plan["phases"]
            }.issuperset({"red", "blue", "auditor"}),
            "everyPhaseHasTools": coverage["ready"] is True,
            "allPhaseReceiptsSucceeded": all(item["ok"] for item in calls),
        }
        return {
            "id": "purple-team",
            "ok": all(checks.values()),
            "checks": checks,
            "toolCoverage": coverage,
            "evidence": [item["receipt_path"] for item in calls],
        }


def run_acceptance_harness(root: str | Path) -> dict[str, Any]:
    return MissionAcceptanceHarness(root).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Neyvia's network-free mission acceptance harness."
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Workspace or temporary root where durable acceptance receipts are written.",
    )
    args = parser.parse_args(argv)
    result = run_acceptance_harness(args.root)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
