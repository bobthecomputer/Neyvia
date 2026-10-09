from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_agent.capability_evolution import NeyviaCapabilityEvolution
from grant_agent.app_factory import AppFactory
from grant_agent.neyvia_conversations import NeyviaConversationStore


def _receipt(
    turn_id: str,
    *,
    duration_ms: int,
    artifact_count: int,
    created_at: str = "2026-07-29T12:00:00Z",
    ended_at: str = "2026-07-29T12:00:10Z",
) -> dict[str, Any]:
    return {
        "turnId": turn_id,
        "conversationId": "conversation_capability_app_fixture",
        "createdAt": created_at,
        "receipt": {
            "schema": "fluxio.turn_receipt.v1",
            "sessionId": "conversation_capability_app_fixture",
            "missionId": "mission_capability_app_fixture",
            "runtime": "codex",
            "provider": "openai-codex",
            "model": "fixture-proof",
            "effort": "high",
            "status": "completed",
            "exitCode": 0,
            "endedAt": ended_at,
            "durationMs": duration_ms,
            "toolTimeline": [
                {
                    "kind": "verification.test",
                    "summary": "Bounded workflow verification passed.",
                    "status": "passed",
                }
            ],
            "changedFiles": ["proof/fixture-result.json"],
            "proofArtifacts": [
                {
                    "kind": "test",
                    "path": f"proof/{turn_id}-{index}.json",
                }
                for index in range(artifact_count)
            ],
            "permissionSummary": {
                "allowed": ["workspace.read", "process.execute"],
                "approvalRequired": ["workspace.write"],
                "denied": ["network.write"],
            },
        },
    }


def prepare_fixture(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise RuntimeError(
            f"Fixture root must be absent or empty: {resolved}"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    service = NeyviaCapabilityEvolution(
        resolved,
        hermes_import_dir=resolved / "missing-hermes-import",
    )
    active_skill_path = (
        resolved
        / ".codex"
        / "skills"
        / "guided-proof-loop"
        / "SKILL.md"
    )
    active_skill_path.parent.mkdir(parents=True, exist_ok=True)
    active_skill_path.write_text(
        """---
name: guided-proof-loop
description: Preserve a small proof-first workflow.
---

# Guided proof loop

Keep the active workflow unchanged.
""",
        encoding="utf-8",
    )
    snapshot = service.snapshot(
        skill_catalog={
            "userInstalledSkills": [
                {
                    "skillId": "guided-proof-loop",
                    "label": "Guided Proof Loop",
                    "sourcePath": str(active_skill_path),
                    "evolutionSummary": {
                        "state": "learning",
                        "usageCount": 6,
                    },
                    "feedbackSummary": {
                        "sliceCount": 4,
                        "zeroImprovementStreak": 2,
                    },
                }
            ]
        }
    )
    proposal = next(
        item
        for item in snapshot["recommendations"]
        if item["capabilityId"] == "guided-proof-loop"
    )
    trial = service.create_trial(
        {
            "lineageId": proposal["lineageId"],
            "capabilityId": proposal["capabilityId"],
            "capabilityKind": proposal["capabilityKind"],
            "label": proposal["label"],
            "origin": proposal["origin"],
            "action": "branch",
            "context": {
                "conversationId": "conversation_capability_app_fixture",
                "missionId": "mission_capability_app_fixture",
            },
        }
    )
    skill_id = trial["candidate"]["targetSkillId"]
    trial = service.seal_skill_candidate(
        trial["trialId"],
        skill_markdown=f"""---
name: {skill_id}
description: Turn a bounded workflow into exact local proof.
---

# Guided proof loop candidate

1. State the concrete outcome and confirm the exact source identity.
2. Complete the bounded workflow without expanding its authority.
3. Attach evidence to every step and verify the final outcome.
4. Seal a recoverable receipt and record the next decision.
""",
        display_name="Guided Proof Loop Candidate",
        default_prompt=(
            f"Use ${skill_id} to guide one bounded outcome and return a "
            "recoverable proof receipt."
        ),
        review_confirmed=True,
    )
    for index in (1, 2):
        trial = service.record_receipt_comparison(
            trial["trialId"],
            baseline_record=_receipt(
                f"fixture_baseline_{index}",
                duration_ms=14_000,
                artifact_count=1,
            ),
            candidate_record=_receipt(
                f"fixture_candidate_{index}",
                duration_ms=7_000,
                artifact_count=2,
            ),
            same_contract_confirmed=True,
            operator_value="candidate_better",
            operator_note=(
                "The candidate completed the same bounded work with stronger "
                "proof and no authority expansion."
            ),
        )
    trial = service.build_counterfactual_forge(
        trial["trialId"],
        case_run_ids=[item["runId"] for item in trial["evidence"]],
        review_confirmed=True,
        reviewed_by="fixture-operator",
    )
    accepted = service.decide_trial(
        trial["trialId"],
        decision="accept",
        decided_by="fixture-operator",
        note="Accepted for a disposable Chrome proof fixture.",
    )
    materialized = service.materialize_skill_candidate(
        accepted["trialId"],
        candidate_digest=accepted["candidate"]["packageDigest"],
        review_confirmed=True,
        materialized_by="fixture-operator",
    )
    dependency_path = resolved / "proof" / "fixture-runtime.lock"
    dependency_path.parent.mkdir(parents=True, exist_ok=True)
    dependency_path.write_text("fixture-runtime-v1\n", encoding="utf-8")
    proof_lease = service.establish_capability_proof_lease(
        materialized["materializationId"],
        goal_statement=(
            "Keep this guided local proof workflow useful as its runtime "
            "conditions evolve."
        ),
        dependency_paths=["proof/fixture-runtime.lock"],
        review_after_days=30,
        review_confirmed=True,
        issued_by="fixture-operator",
        provider_availability={"openai-codex": True},
        now="2026-07-29T12:00:00Z",
    )
    handoff = service.prepare_app_factory_handoff(
        materialized["materializationId"],
        candidate_digest=materialized["candidateDigest"],
        review_confirmed=True,
        reviewed_by="fixture-operator",
        provider_availability={"openai-codex": True},
    )
    app_job = AppFactory(resolved).create_from_capability_handoff(
        handoff,
        name="Guided Proof Workbench",
        brief=(
            "Guide one bounded proof workflow, seal typed local outcomes, "
            "and return repeated friction for operator review."
        ),
        target="neyvia",
        theme="midnight",
        directory="apps/guided-proof-workbench",
    )
    conversations = NeyviaConversationStore(resolved)
    conversation = conversations.create_conversation(
        workspace_id=str(resolved),
        kind="orchestration",
        title="Capability proof lease fixture",
        title_mode="off",
        conversation_id="conversation_capability_app_fixture",
        now="2026-07-29T12:30:00Z",
    )
    renewal_record = _receipt(
        "fixture_reproof_current_conditions",
        duration_ms=6_500,
        artifact_count=2,
        created_at="2026-07-29T13:00:00Z",
        ended_at="2026-07-29T13:00:10Z",
    )
    conversations.append_turn(
        conversation["conversationId"],
        role="assistant",
        content="Fresh bounded re-proof completed for the disposable fixture.",
        source="fixture",
        turn_kind="result",
        metadata={"turnReceipt": renewal_record["receipt"]},
        turn_id=renewal_record["turnId"],
        now=renewal_record["createdAt"],
    )
    summary = {
        "schema": "neyvia.capability-app-fixture/v1",
        "root": str(resolved),
        "trialId": accepted["trialId"],
        "materializationId": materialized["materializationId"],
        "skillId": materialized["skillId"],
        "candidateDigest": materialized["candidateDigest"],
        "handoffId": handoff["handoffId"],
        "handoffDigest": handoff["handoffDigest"],
        "appFactoryJobId": app_job["jobId"],
        "appId": app_job["spec"]["appId"],
        "appProjectRoot": app_job["projectRoot"],
        "appPreviewUrl": app_job["previewUrl"],
        "appVerificationReceiptPath": app_job["verification"]["receiptPath"],
        "proofLeaseId": proof_lease["leaseId"],
        "proofLeaseDigest": proof_lease["leaseDigest"],
        "proofLeaseRevision": proof_lease["revision"],
        "proofLeaseState": proof_lease["state"],
        "dependencyPath": str(dependency_path),
        "renewalTurnId": renewal_record["turnId"],
        "conversationId": conversation["conversationId"],
        "qualifyingRunCount": handoff["evidenceSummary"][
            "qualifyingRunCount"
        ],
        "authorityStatus": handoff["authorityComparison"]["status"],
        "candidateActivated": False,
        "appActivated": False,
        "transcriptsIncluded": False,
    }
    summary_path = (
        resolved
        / ".agent_control"
        / "capability-app-fixture.json"
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {**summary, "summaryPath": str(summary_path)}


def mutate_fixture_dependency(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    summary_path = (
        resolved
        / ".agent_control"
        / "capability-app-fixture.json"
    )
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Disposable fixture summary is missing or invalid: {summary_path}"
        ) from exc
    if (
        not isinstance(summary, dict)
        or summary.get("schema") != "neyvia.capability-app-fixture/v1"
        or Path(str(summary.get("root") or "")).resolve() != resolved
    ):
        raise RuntimeError(
            "Refusing to mutate a root that is not this disposable fixture."
        )
    dependency = (resolved / "proof" / "fixture-runtime.lock").resolve()
    dependency.relative_to(resolved)
    if dependency.read_text(encoding="utf-8") != "fixture-runtime-v1\n":
        raise RuntimeError(
            "Fixture dependency is not at its known initial value."
        )
    dependency.write_text("fixture-runtime-v2\n", encoding="utf-8")
    return {
        "schema": "neyvia.capability-app-fixture-drift/v1",
        "root": str(resolved),
        "dependencyPath": str(dependency),
        "previous": "fixture-runtime-v1",
        "current": "fixture-runtime-v2",
        "candidateActivated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a disposable accepted and inactive capability lineage "
            "for App Factory user-journey verification."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--mutate-dependency",
        action="store_true",
        help="Change only the verified disposable fixture dependency.",
    )
    args = parser.parse_args()
    result = (
        mutate_fixture_dependency(Path(args.root))
        if args.mutate_dependency
        else prepare_fixture(Path(args.root))
    )
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
