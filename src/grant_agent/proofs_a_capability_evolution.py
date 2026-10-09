"""Executable contracts for receipt-bound, inactive capability evolution."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .proofs_a_capabilities import require


def check_recommendation(result, service, row):
    repair = row.get("state") == "needs_repair" or row.get("selectionState") == "deprioritize" or float(row.get("latestSystemLoss") or 0) >= .55
    stagnant = int(row.get("zeroImprovementStreak") or 0) >= 2 and int(row.get("usageCount") or 0) >= 3
    if repair or stagnant:
        require(result["action"] == ("repair" if repair else "branch"), "a.evolution-stagnation", "repair/stagnation evidence was treated as reinforcement")
    require(result["humanDecisionRequired"] is True and result["status"] == "suggested", "a.evolution-stagnation", "recommendation changed authority without a human decision")


def check_trial(result, row):
    candidate = result["candidate"]
    verdict = result["verdict"]
    require(candidate.get("activated", False) is False and verdict.get("candidateActivated", False) is False, "a.evolution-sealed", "trial output activated a candidate")
    if candidate.get("schema") == "neyvia.sealed_skill_candidate.v1":
        require(hashlib.sha256(candidate["skillMarkdown"].encode()).hexdigest() == candidate["skillSha256"] and hashlib.sha256(candidate["openaiYaml"].encode()).hexdigest() == candidate["metadataSha256"] and candidate["state"] == "sealed", "a.evolution-sealed", "sealed candidate content differs from its hashes")
    ids = [entry["runId"] for entry in result["evidence"]]
    require(len(ids) == len(set(ids)), "a.evolution-receipts", "repeated evidence double-counted a run")
    for entry in result["evidence"]:
        if entry.get("receiptPair", {}).get("schema") == "neyvia.receipt_comparison.v1":
            pair = entry["receiptPair"]
            digest = str(candidate.get("packageDigest") or "")
            require(candidate.get("schema") != "neyvia.sealed_skill_candidate.v1" or bool(digest), "a.evolution-receipts", "sealed comparison lacks its package digest")
            pair_digest = pair["candidatePackageDigest"]
            bound = pair_digest == digest if digest else pair_digest in ("", None)
            require(pair["transcriptsIncluded"] is False and entry["measurementRubric"]["derivedFromReceipts"] is True and bound and digest == entry["candidatePackageDigest"], "a.evolution-receipts", "comparison lost receipt identity or exact candidate binding")
    forge = verdict.get("counterfactualForge")
    if forge:
        cases = forge["cases"]
        expected = {plural: sum(entry["classification"] == singular for entry in cases) for plural, singular in [("wins", "win"), ("ties", "tie"), ("regressions", "regression"), ("inconclusive", "inconclusive")]}
        expanded = sorted({permission for entry in cases for permission in entry["authority"]["expandedPermissions"]})
        passed = len(cases) >= forge["requiredCaseCount"] and expected["wins"] >= 1 and expected["regressions"] == expected["inconclusive"] == 0 and not expanded
        require(forge["scorecard"] == expected and forge["caseCount"] == len(cases) and forge["reviewGatePassed"] == passed and forge["authorityComparison"]["expandedPermissions"] == expanded and forge["candidatePackageDigest"] == candidate["packageDigest"] and forge["candidateActivated"] is False and forge["transcriptsIncluded"] is False, "a.evolution-forge", "forge gate differs from its bounded replay cases and authority")
    if result["state"] == "accepted" and candidate.get("schema") == "neyvia.sealed_skill_candidate.v1":
        require(bool(forge and forge["reviewGatePassed"]), "a.evolution-forge", "skill was accepted without a reviewed authority-bounded forge")


def check_materialization(result, row):
    require(result["candidateActivated"] is False and result["rollback"]["candidateActivationChanged"] is False, "a.evolution-inactive", "materialization changed activation")


def check_materialization_write(result, service, *args, **kwargs):
    package = Path(result["packagePath"])
    require(package.resolve().is_relative_to(service.root / ".agent_control/capability_materializations"), "a.evolution-inactive", "materialization entered active skill storage")
    require(hashlib.sha256((package / "SKILL.md").read_bytes()).hexdigest() == result["skillSha256"] and hashlib.sha256((package / "agents/openai.yaml").read_bytes()).hexdigest() == result["metadataSha256"], "a.evolution-inactive", "inactive materialization changed its sealed content")
    if result["state"] == "withdrawn":
        require(package.is_dir() and json.loads(Path(result["rollback"]["receiptPath"]).read_text(encoding="utf-8"))["candidateDigest"] == result["candidateDigest"], "a.evolution-inactive", "withdrawal lost package or bound rollback receipt")


def check_lease(result, service, *args, **kwargs):
    require(result["candidateActivated"] is False and result["transcriptsIncluded"] is False and result["canPromoteToApp"] == (result["state"] == "current"), "a.evolution-lease", "lease activated a candidate or allowed stale promotion")
    if result["state"] == "current":
        require(result["signals"]["dependencies"]["status"] == "passed" and bool(result["leaseDigest"]), "a.evolution-lease", "current lease lacks passed bound dependencies")


def check_handoff(result, service, materialization_id, **kwargs):
    require(result["candidateDigest"] == kwargs["candidate_digest"] and result["materializationId"] == materialization_id and result["state"] == "reviewed_for_local_draft" and not any(result[key] for key in ["candidateActivated", "appActivated", "transcriptsIncluded"]) and result["proofLease"]["state"] == "current" and result["proofLease"]["leaseDigest"], "a.evolution-handoff", "app handoff lost exact package, current proof or inactive draft boundary")
    source = Path(result["sourcePackage"]["skillPath"])
    require(source.is_relative_to(service.root / ".agent_control/capability_materializations") and source.is_file() and all(row["transcriptsIncluded"] is False for row in result["comparisonRuns"]), "a.evolution-handoff", "handoff exposed active source or transcript bodies")


def check_constellation(result, service, **kwargs):
    graph = kwargs["constellation"]
    require(graph["synthesis"]["status"] == "ready" and result["trustRaised"] is False and result["observationCount"] == len(result["observations"]) > 0, "a.evolution-outcome", "unready evidence raised trust or produced empty learning")


def check_app_import(result, service, bundle, **kwargs):
    require(result["receivedRunCount"] == result["importedRunCount"] + result["duplicateRunCount"] and len(result["observations"]) == result["importedRunCount"] and not any(result[key] for key in ["trustRaised", "candidateActivated", "transcriptsStored", "privateRunTextStored"]), "a.evolution-friction", "app import double-counted outcomes or changed private state/activation")
    allowed = {"schema", "outcome", "completed", "durationSeconds", "operatorValue", "frictionCode", "frictionSeverity", "correctionCount", "usualMinutes", "operatorEstimatedMinutesReturned", "estimateBasis"}
    source = {row["runId"]: row for row in bundle["runs"]}
    for row in result["observations"]:
        run = source[row["runId"]]
        digest = hashlib.sha256(json.dumps({key: value for key, value in run.items() if key != "receiptDigest"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(set(row) == {"observationId", "runId", "receiptDigest", "measurements"} and set(row["measurements"]) == allowed and row["receiptDigest"] == run["receiptDigest"] == digest, "a.evolution-friction", "import stored private run fields or unbound receipt identity")


def check_app_learning(result, service, rows, **kwargs):
    measurements = [json.loads(row["measurements_json"]) for row in rows]
    dividends = result["operatorDividends"]
    require(result["receiptCount"] == len(rows) and result["privateRunTextStored"] is False and result["trustRaised"] is False and dividends["measuredRunMinutes"] == round(sum(max(0, float(row.get("durationSeconds") or 0)) for row in measurements) / 60, 2) and dividends["operatorEstimatedMinutesReturned"] == round(sum(max(0, float(row.get("operatorEstimatedMinutesReturned") or 0)) for row in measurements), 2), "a.evolution-friction", "learning mixed measured duration with operator estimates or raised trust")
    require(all(row["humanDecisionRequired"] and row["evidenceSummary"]["frictionCount"] >= 2 for row in result["proposals"]), "a.evolution-friction", "one friction signal silently promoted a repair")


def self_check(scratch):
    """Exercise real SQLite, package files and reviewed receipt semantics in scratch.

    Typed receipt inputs model completed tool runs; this does not claim a live
    model invocation or a promoted capability.
    """
    from .capability_evolution import NeyviaCapabilityEvolution
    root = scratch / "evolution"
    root.mkdir()
    service = NeyviaCapabilityEvolution(root, database_path=root / "ecosystem.sqlite3", hermes_import_dir=root / "hermes")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    iso = lambda delta=timedelta(): (now + delta).isoformat().replace("+00:00", "Z")
    def blocked(action, text=""):
        try:
            action()
        except ValueError as error:
            require(not text or text in str(error), "a.evolution-receipts", f"wrong rejection: {error}")
        else:
            require(False, "a.evolution-receipts", "invalid review/evidence input was accepted")
    def record(identity, duration=12000, artifacts=1, authority=None, conversation="scratch_evolution", created=None):
        return {"turnId": identity, "conversationId": conversation, "createdAt": created or iso(), "receipt": {"schema": "fluxio.turn_receipt.v1", "sessionId": conversation, "missionId": "scratch_mission", "runtime": "codex", "provider": "openai-codex", "model": "proof-fixture", "effort": "high", "status": "completed", "exitCode": 0, "endedAt": iso(), "durationMs": duration, "toolTimeline": [{"kind": "verification.test", "summary": "Bounded fixture verification", "status": "passed"}], "changedFiles": ["proof/result.txt"], "proofArtifacts": [{"kind": "test", "path": f"proof/{identity}-{index}.json"} for index in range(artifacts)], "assistantMessage": "PRIVATE_EVOLUTION_TRANSCRIPT", "permissionSummary": authority or {"allowed": ["workspace.read", "process.execute"], "approvalRequired": ["workspace.write"], "denied": ["network.write"]}}}
    def create(identity):
        return service.create_trial({"capabilityId": identity, "capabilityKind": "skill", "label": identity, "action": "branch", "context": {"conversationId": "scratch_evolution"}})
    def seal(trial):
        name = trial["candidate"]["targetSkillId"]
        markdown = f"---\nname: {name}\ndescription: Preserve exact proof identity while improving a repeated workflow.\n---\n\n# Proof workflow\n\n1. Inspect the active contract and the sealed candidate digest.\n2. Run the bounded workflow without expanding authority.\n3. Verify the outcome and retain a recoverable receipt.\n"
        return service.seal_skill_candidate(trial["trialId"], skill_markdown=markdown, display_name="Proof workflow", review_confirmed=True)
    active = root / ".codex/skills/sealed-proof-loop/SKILL.md"
    active.parent.mkdir(parents=True)
    active_text = "---\nname: sealed-proof-loop\ndescription: Preserve the active proof workflow.\n---\n\n# Active proof\n\nKeep the existing active workflow unchanged.\n"
    active.write_text(active_text)
    skill_catalog = {"userInstalledSkills": [{"skillId": "sealed-proof-loop", "label": "Active Proof Loop", "sourcePath": str(active), "evolutionSummary": {"state": "learning", "usageCount": 5}, "feedbackSummary": {"sliceCount": 3, "zeroImprovementStreak": 2}}]}
    proposal = next(row for row in service.snapshot(skill_catalog=skill_catalog)["recommendations"] if row["capabilityId"] == "sealed-proof-loop")
    trial = service.create_trial({**{key: proposal[key] for key in ["lineageId", "capabilityId", "capabilityKind", "label", "origin"]}, "action": "branch", "context": {"conversationId": "scratch_evolution"}})
    blocked(lambda: service.record_receipt_comparison(trial["trialId"], baseline_record=record("unsealed_b"), candidate_record=record("unsealed_c"), same_contract_confirmed=True, operator_value="candidate_better"), "seal the exact candidate")
    blocked(lambda: service.seal_skill_candidate(trial["trialId"], skill_markdown="not reviewed", review_confirmed=False), "confirm")
    trial = seal(trial)
    require(seal(trial)["candidate"]["packageDigest"] == trial["candidate"]["packageDigest"], "a.evolution-sealed", "identical sealing was not idempotent")
    blocked(lambda: service.seal_skill_candidate(trial["trialId"], skill_markdown=trial["candidate"]["skillMarkdown"].replace("recoverable receipt", "different workflow"), display_name="Proof workflow", review_confirmed=True), "already sealed")
    baseline, candidate = record("baseline_1"), record("candidate_1", 6000, 2)
    compare = lambda b, c, confirmed=True: service.record_receipt_comparison(trial["trialId"], baseline_record=b, candidate_record=c, same_contract_confirmed=confirmed, operator_value="candidate_better")
    blocked(lambda: compare(baseline, candidate, False), "same task contract")
    forged = record("forged"); forged["receipt"]["schema"] = "user.claimed.receipt.v1"
    blocked(lambda: compare(forged, candidate), "real Neyvia")
    blocked(lambda: compare(baseline, baseline), "different turn receipts")
    blocked(lambda: compare(baseline, record("other", conversation="other_conversation")), "same Constellation conversation")
    first = compare(baseline, candidate)
    entry = first["evidence"][0]
    require(first["state"] == "collecting" and first["verdict"]["comparableRunCount"] == 1 and entry["candidate"]["outcomeScore"] > entry["baseline"]["outcomeScore"] and entry["candidate"]["proofQuality"] >= entry["baseline"]["proofQuality"] and "PRIVATE_EVOLUTION_TRANSCRIPT" not in json.dumps(first), "a.evolution-receipts", "receipt comparison lost derived metrics or excluded transcript boundary")
    require(compare(baseline, candidate)["verdict"]["comparableRunCount"] == 1, "a.evolution-receipts", "receipt replay double-counted")
    trial = compare(record("baseline_2", 11000), record("candidate_2", 6000, 2))
    require(trial["state"] == "evidence_ready" and trial["verdict"]["qualifyingRunCount"] == 2 and trial["verdict"]["recommendedDecision"] == "review_counterfactual", "a.evolution-receipts", "two verified comparisons did not reach reviewed evidence gate")
    snapshot = service.snapshot(receipt_records=[baseline, candidate], constellation={"conversationId": "scratch_evolution", "nodes": []})
    require(snapshot["receiptComparisons"]["eligibleCount"] == 2 and snapshot["receiptComparisons"]["transcriptsIncluded"] is False and "assistantMessage" not in json.dumps(snapshot["receiptComparisons"]), "a.evolution-receipts", "snapshot exposed receipt transcript")
    run_ids = [entry["runId"] for entry in trial["evidence"]]
    blocked(lambda: service.decide_trial(trial["trialId"], decision="accept"), "counterfactual")
    blocked(lambda: service.build_counterfactual_forge(trial["trialId"], case_run_ids=run_ids, review_confirmed=False), "confirm")
    forged = service.build_counterfactual_forge(trial["trialId"], case_run_ids=run_ids, review_confirmed=True)
    forge = forged["verdict"]["counterfactualForge"]
    require(forge["state"] == "review_ready" and forge["scorecard"] == {"wins": 2, "ties": 0, "regressions": 0, "inconclusive": 0} and forge["authorityComparison"]["status"] == "unchanged", "a.evolution-forge", "reviewed forge scorecard or authority differs")
    require(service.build_counterfactual_forge(trial["trialId"], case_run_ids=run_ids, review_confirmed=True)["verdict"]["counterfactualForge"]["forgeId"] == forge["forgeId"], "a.evolution-forge", "forge replay changed identity")
    accepted = service.decide_trial(trial["trialId"], decision="accept")
    require(accepted["state"] == "accepted" and accepted["verdict"]["materializationStatus"] == "review_required" and accepted["approvedLineage"]["parentLineageId"] == trial["lineageId"], "a.evolution-forge", "acceptance skipped materialization review or parent binding")
    digest = accepted["candidate"]["packageDigest"]
    blocked(lambda: service.materialize_skill_candidate(trial["trialId"], candidate_digest=digest, review_confirmed=False), "confirm")
    materialized = service.materialize_skill_candidate(trial["trialId"], candidate_digest=digest, review_confirmed=True)
    package = Path(materialized["packagePath"])
    require(materialized["state"] == "materialized_inactive" and package.is_relative_to(root / ".agent_control") and (package / "SKILL.md").read_text() == accepted["candidate"]["skillMarkdown"] and active.read_text() == active_text and materialized["rollback"]["activeSourceDigest"], "a.evolution-inactive", "materialization escaped inactive storage, changed active parent or changed sealed package")
    require(service.materialize_skill_candidate(trial["trialId"], candidate_digest=digest, review_confirmed=True)["materializationId"] == materialized["materializationId"], "a.evolution-inactive", "materialization replay changed identity")
    dependency = root / "proof/runtime.lock"; dependency.parent.mkdir(); dependency.write_text("runtime-v1\n")
    lease_args = {"goal_statement": "Keep the exact verified local workflow useful.", "dependency_paths": ["proof/runtime.lock"], "review_after_days": 30, "review_confirmed": True, "provider_availability": {"openai-codex": True}, "now": iso()}
    blocked(lambda: service.establish_capability_proof_lease(materialized["materializationId"], **{**lease_args, "review_confirmed": False}), "confirm")
    # Empty name sentinel is rejected before any file bytes can be read.
    (root / ".env").write_bytes(b"")
    blocked(lambda: service.establish_capability_proof_lease(materialized["materializationId"], **{**lease_args, "dependency_paths": [".env"]}), "secret-bearing")
    lease = service.establish_capability_proof_lease(materialized["materializationId"], **lease_args)
    require(lease["state"] == "current" and lease["revision"] == 1 and lease["signals"]["dependencies"]["status"] == "passed", "a.evolution-lease", "lease did not establish current dependency proof")
    reviewed = service.snapshot(skill_catalog=skill_catalog, provider_availability={"openai-codex": True})
    review = next(row for row in reviewed["skillMaterializationReviews"] if row["trialId"] == trial["trialId"])
    require(review["state"] == "materialized_inactive" and review["rollbackAvailable"] and review["proofLease"]["state"] == "current" and review["appFactoryHandoff"]["state"] == "review_required" and review["appFactoryHandoff"]["canCreateApp"], "a.evolution-inactive", "inactive materialization review lost rollback or app admission state")
    blocked(lambda: service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=False), "confirm")
    handoff = service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=True, provider_availability={"openai-codex": True})
    require(handoff["evidenceSummary"]["qualifyingRunCount"] == 2 and handoff["workflowSteps"] == ["Inspect the active contract and the sealed candidate digest.", "Run the bounded workflow without expanding authority.", "Verify the outcome and retain a recoverable receipt."], "a.evolution-handoff", "handoff lost proved workflow or comparable runs")
    from .app_factory import AppFactory
    app = AppFactory(root).create_from_capability_handoff(handoff, name="Proof Guided Workbench", brief="Guide the exact reviewed proof workflow and retain bound local receipts.", target="neyvia", theme="midnight", directory="apps/proof-guided-workbench")
    app_bound = service.snapshot(app_factory_jobs=[app], provider_availability={"openai-codex": True})
    app_review = next(row for row in app_bound["appFactoryHandoffs"] if row["materializationId"] == materialized["materializationId"])
    require(app["status"] == "ready" and app_review["state"] == "draft_ready" and app_review["appFactoryJob"]["jobId"] == app["jobId"] and app_bound["summary"]["appFactoryDraftCount"] == 1, "a.evolution-handoff", "actual reviewed app draft lost lineage projection")
    app_handoff = app["capabilityHandoff"]
    bundle = {"schema": "neyvia.capability-run-bundle/v2", "appFactoryJobId": app["jobId"], "appId": app["spec"]["appId"], **{key: app_handoff[key] for key in ["handoffId", "handoffDigest", "candidateDigest", "skillId", "proofLease"]}, "exportedAt": iso(), "candidateActivated": False, "transcriptsIncluded": False, "runs": []}
    def app_run(identity, minute):
        run = {"schema": "neyvia.capability-run/v2", "runId": identity, **{key: bundle[key] for key in ["appFactoryJobId", "appId", "handoffId", "handoffDigest", "candidateDigest", "skillId", "proofLease"]}, "goal": "PRIVATE GOAL", "status": "sealed", "outcome": "completed", "operatorValue": "helpful", "friction": {"code": "verification_gap", "severity": "medium", "correctionCount": 1, "usualMinutes": 30}, "proofNote": "PRIVATE PROOF", "startedAt": iso(timedelta(minutes=minute)), "completedAt": iso(timedelta(minutes=minute+10)), "steps": [{"text": "PRIVATE STEP", "complete": True, "note": "PRIVATE STEP NOTE", "updatedAt": iso(timedelta(minutes=minute+10))}], "candidateActivated": False, "transcriptsIncluded": False}
        run["receiptDigest"] = hashlib.sha256(json.dumps(run, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return run
    first_run, second_run = app_run("friction-1", -25), app_run("friction-2", -12)
    import_runs = lambda runs, job=app: service.import_capability_run_bundle({**bundle, "runs": runs}, app_factory_jobs=[job], provider_availability={"openai-codex": True})
    first_import = import_runs([first_run]); second_import = import_runs([first_run, second_run])
    require(first_import["status"] == "accepted_into_discovery" and first_import["importedRunCount"] == 1 and first_import["frictionPatternCount"] == first_import["proposalCount"] == 0 and second_import["importedRunCount"] == second_import["duplicateRunCount"] == second_import["frictionPatternCount"] == second_import["proposalCount"] == 1, "a.evolution-friction", "friction was promoted before recurrence or duplicated")
    learning_snapshot = service.snapshot(app_factory_jobs=[app], provider_availability={"openai-codex": True})
    learning = learning_snapshot["appOutcomeLearning"]; repair_proposal = learning["proposals"][0]
    require(learning_snapshot["summary"]["appOutcomeReceiptCount"] == 2 and learning_snapshot["summary"]["frictionPatternCount"] == 1 and repair_proposal["origin"] == "app_outcome" and repair_proposal["action"] == "repair" and repair_proposal["evidenceSummary"]["frictionCount"] == 2 and learning["operatorDividends"]["measuredRunMinutes"] == 20 and learning["operatorDividends"]["operatorEstimatedMinutesReturned"] == 40 and "operator counterfactual estimate" in learning["operatorDividends"]["estimateClaim"], "a.evolution-friction", "typed recurrence lost repair meaning or measured versus estimated time")
    import sqlite3
    with sqlite3.connect(service.database_path) as connection:
        stored = connection.execute("SELECT measurements_json,evidence_json FROM capability_observations WHERE source_kind='app_run'").fetchall()
    persisted = json.dumps(stored)
    require(len(stored) == 2 and all(text not in persisted for text in ["PRIVATE GOAL", "PRIVATE PROOF", "PRIVATE STEP"]) and first_run["receiptDigest"] in persisted, "a.evolution-friction", "durable observations copied private text or omitted digest")
    replay_import = import_runs([first_run, second_run])
    require(replay_import["importedRunCount"] == 0 and replay_import["duplicateRunCount"] == 2, "a.evolution-friction", "outcome replay was not idempotent")
    tampered = json.loads(json.dumps(second_run)); tampered["friction"]["severity"] = "high"
    blocked(lambda: import_runs([first_run, tampered]), "digest does not match")
    changed_app = json.loads(json.dumps(app)); changed_app["spec"]["brief"] = "Changed after verification"
    blocked(lambda: import_runs([first_run], changed_app), "app binding changed")
    verification_path = Path(app["verification"]["receiptPath"])
    original_receipt = verification_path.read_bytes(); changed_receipt = json.loads(original_receipt); changed_receipt["appId"] = "local.changed"
    verification_path.write_text(json.dumps(changed_receipt))
    blocked(lambda: import_runs([first_run]), "receipt does not match")
    verification_path.write_bytes(original_receipt)
    due = service.assess_capability_proof_lease(materialized["materializationId"], provider_availability={"openai-codex": True}, now=iso(timedelta(days=31)))
    unavailable = service.assess_capability_proof_lease(materialized["materializationId"], provider_availability={"openai-codex": False}, now=iso(timedelta(hours=1)))
    require(due["state"] == "review_due" and not due["canPromoteToApp"] and unavailable["state"] == "held" and unavailable["signals"]["provider"]["status"] == "unavailable", "a.evolution-lease", "expired or unavailable route retained promotion")
    dependency.write_text("runtime-v2\n")
    drifted = service.assess_capability_proof_lease(materialized["materializationId"], provider_availability={"openai-codex": True}, now=iso(timedelta(hours=1)))
    require(drifted["state"] == "reproof_required" and drifted["signals"]["dependencies"]["changedPaths"] == ["proof/runtime.lock"], "a.evolution-lease", "changed dependency did not require reproof")
    blocked(lambda: import_runs([app_run("friction-stale", -10)]), "no longer current")
    blocked(lambda: service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=True, provider_availability={"openai-codex": True}), "not current")
    renewal = service.renew_capability_proof_lease(materialized["materializationId"], candidate_digest=digest, receipt_record=record("fresh_renewal", artifacts=2, created=iso(timedelta(hours=2))), goal_still_matches=True, operator_value="still_useful", review_confirmed=True, provider_availability={"openai-codex": True}, now=iso(timedelta(hours=3)))
    require(renewal["state"] == "current" and renewal["revision"] == 2 and renewal["leaseDigest"] != lease["leaseDigest"] and renewal["signals"]["dependencies"]["status"] == "passed", "a.evolution-lease", "fresh renewal lost history or changed dependency binding")
    renewed_handoff = service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=True, provider_availability={"openai-codex": True})
    factory = AppFactory(root)
    app_args = {"name": "Proof Renewed Workbench", "brief": "Guide the exact reviewed proof workflow and retain bound local receipts.", "target": "neyvia", "theme": "midnight", "directory": "apps/proof-renewed-workbench"}
    renewed_app = factory.create_from_capability_handoff(renewed_handoff, **app_args)
    require(renewed_app["status"] == "ready" and renewed_app["spec"]["template"] == "capability" and renewed_app["capabilityHandoff"]["proofLease"]["revision"] == 2 and renewed_app["capabilityHandoff"]["proofLease"]["leaseDigest"] == renewed_handoff["proofLease"]["leaseDigest"] and "The current runner guides a human" in renewed_app["agentHandoff"]["prompt"], "a.factory-lineage", "renewed guided draft lost proof history or human-runner boundary")
    require(factory.create_from_capability_handoff(renewed_handoff, **app_args)["jobId"] == renewed_app["jobId"], "a.factory-lineage", "guided app replay created another draft")
    try:
        factory.create_from_capability_handoff(renewed_handoff, **{**app_args, "name": "Changed Proof Workbench", "brief": "Guide the same workflow under a different app binding", "directory": "apps/changed-proof-workbench"})
    except RuntimeError as error:
        require("different app specification" in str(error), "a.factory-lineage", "rebound capsule rejected for wrong reason")
    else:
        require(False, "a.factory-lineage", "reviewed capsule admitted a changed app binding")
    receipt_after = json.loads(Path(renewed_app["capabilityHandoff"]["sourcePackage"]["receiptPath"]).read_text())
    require(receipt_after["state"] == "draft_ready" and receipt_after["error"] == "" and "different app specification" in receipt_after["lastRejectedRequest"]["reason"], "a.factory-lineage", "rejected rebind corrupted ready draft receipt")
    registered = next(row for row in json.loads(factory.registry_path.read_text())["applications"] if row["applicationId"] == renewed_app["spec"]["appId"])
    require(registered["capabilityHandoff"]["handoffDigest"] == renewed_handoff["handoffDigest"] and registered["capabilityHandoff"]["proofLease"]["revision"] == 2, "a.factory-lineage", "registry lost reviewed renewed lineage")
    repair = service.record_capability_proof_lease_disposition(materialized["materializationId"], disposition="needs_repair", review_confirmed=True, now=iso(timedelta(hours=4)))
    require(repair["state"] == "held" and repair["signals"]["goal"]["status"] == "needs_repair", "a.evolution-lease", "repair disposition remained promotable")
    blocked(lambda: service.renew_capability_proof_lease(materialized["materializationId"], candidate_digest=digest, receipt_record=record("after_repair", artifacts=2, created=iso(timedelta(hours=5))), goal_still_matches=True, operator_value="still_useful", review_confirmed=True, provider_availability={"openai-codex": True}), "repair disposition")
    rollback = service.rollback_skill_materialization(materialized["materializationId"], candidate_digest=digest, review_confirmed=True)
    require(rollback["state"] == "withdrawn" and package.is_dir() and Path(rollback["rollback"]["receiptPath"]).is_file() and active.read_text() == active_text, "a.evolution-inactive", "rollback lost retained package or receipt or changed active parent")
    blocked(lambda: service.prepare_app_factory_handoff(materialized["materializationId"], candidate_digest=digest, review_confirmed=True), "inactive, non-withdrawn")
    broad = seal(create("authority-bound-loop"))
    for index in (1, 2):
        broad = service.record_receipt_comparison(broad["trialId"], baseline_record=record(f"bound_base_{index}", authority={"allowed": ["workspace.read"], "approvalRequired": ["workspace.write"], "denied": ["network.write"]}), candidate_record=record(f"bound_candidate_{index}", artifacts=2, authority={"allowed": ["workspace.read", "network.write"], "approvalRequired": ["workspace.write"], "denied": []}), same_contract_confirmed=True, operator_value="candidate_better")
    held = service.build_counterfactual_forge(broad["trialId"], case_run_ids=[entry["runId"] for entry in broad["evidence"]], review_confirmed=True)
    require(held["state"] == "held" and held["verdict"]["counterfactualForge"]["authorityComparison"]["expandedPermissions"] == ["network.write"] and held["verdict"]["counterfactualForge"]["state"] == "blocked", "a.evolution-forge", "expanded candidate authority passed acceptance")
    blocked(lambda: service.decide_trial(broad["trialId"], decision="accept"), "counterfactual")
    manual = create("operator-review-loop")
    require(manual["state"] == "planned" and manual["candidate"]["schema"] == "neyvia.skill_candidate_brief.v1", "a.evolution-sealed", "new trial skipped candidate planning")
    manual = seal(manual)
    blocked(lambda: service.decide_trial(manual["trialId"], decision="accept"), "cannot be accepted")
    for index, baseline_score in enumerate([.70, .68], 1):
        manual = service.record_trial_evidence(manual["trialId"], {"comparable": True, "baseline": {"outcomeScore": baseline_score, "proofQuality": .82}, "candidate": {"outcomeScore": baseline_score + .12, "proofQuality": .88}, "verificationPassed": True, "operatorValueRecorded": True, "artifacts": [f"proof/manual-{index}.json"]})
        require(manual["state"] == ("collecting" if index == 1 else "evidence_ready") and manual["verdict"]["candidateActivated"] is False, "a.evolution-forge", "reviewed metrics skipped comparable evidence stage")
    blocked(lambda: service.decide_trial(manual["trialId"], decision="accept"), "counterfactual")
    require(service.decide_trial(manual["trialId"], decision="hold")["state"] == "held", "a.evolution-forge", "operator could not hold un-forged evidence")
    existing = service.create_trial({"capabilityId": "existing-proof", "capabilityKind": "skill", "label": "Existing proof", "action": "prove"})
    for index in range(2):
        existing = service.record_trial_evidence(existing["trialId"], {"comparable": True, "baseline": {"outcomeScore": .70, "proofQuality": .82}, "candidate": {"outcomeScore": .82, "proofQuality": .88}, "verificationPassed": True, "operatorValueRecorded": True, "artifacts": [f"proof/existing-{index}.json"]})
    existing = service.decide_trial(existing["trialId"], decision="accept")
    require(existing["state"] == "accepted" and existing["candidate"].get("schema") != "neyvia.sealed_skill_candidate.v1" and existing["verdict"].get("counterfactualForge") is None, "a.evolution-forge", "reading an accepted existing-skill proof incorrectly required a new candidate forge")
    graph = {"conversationId": "scratch_evolution", "synthesis": {"synthesisId": "scratch_synthesis", "status": "ready", "candidateNodeIds": ["verifier"]}, "nodes": [{"nodeId": "verifier", "runtime": "hermes", "title": "Verifier", "lifecycleStage": "completed", "capabilities": ["proof-loop"], "resultSummary": {"schema": "neyvia.agent_delta.v1", "delta": {"schema": "neyvia.agent_delta.v1", "claims": [{"text": "Bounded evidence passes"}], "evidence": [{"path": "proof/result.json", "passed": True}], "artifacts": [], "conflicts": [], "blockers": [], "notes": []}}}]}
    outcome = service.accept_constellation_outcome(constellation=graph, synthesis_id="scratch_synthesis", mission_id="scratch_mission")
    replay = service.accept_constellation_outcome(constellation=graph, synthesis_id="scratch_synthesis", mission_id="scratch_mission")
    require(outcome["status"] == "accepted_into_learning" and outcome["observationCount"] == 1 and replay["observations"][0]["observationId"] == outcome["observations"][0]["observationId"] and any(row["capabilityId"] == "proof-loop" and row["origin"] == "constellation" for row in service.snapshot()["lineages"]), "a.evolution-outcome", "typed synthesis lost idempotent lineage evidence")
    graph["synthesis"]["status"] = "blocked_evidence"
    blocked(lambda: service.accept_constellation_outcome(constellation=graph, synthesis_id="scratch_synthesis"), "evidence contract is ready")
    hermes = root / "hermes"; hermes.mkdir()
    for name, rows in [("learned_skills", [{"skill_id": "stagnant-loop", "label": "Stagnant Loop", "status": "active", "usage_count": 4}]), ("skill_usage", [{"skill_id": "stagnant-loop", "helped": True, "created_at": iso(timedelta(minutes=index))} for index in range(4)]), ("skill_feedback", [{"skillId": "stagnant-loop", "systemLoss": .13, "improvementScore": score, "nextAction": "reinforce", "createdAt": iso(timedelta(minutes=index))} for index, score in enumerate([8.7, 0, 0, 0])])]:
        (hermes / f"jbheaven-{name}.json").write_text(json.dumps(rows))
    stagnant = service.snapshot(skill_catalog={"userInstalledSkills": [{"skillId": "local-proof", "label": "Local Proof", "evolutionSummary": {"state": "new", "revisionCount": 1, "usageCount": 0}, "feedbackSummary": {"sliceCount": 0}}]})
    proposal = next(row for row in stagnant["recommendations"] if row["capabilityId"] == "stagnant-loop")
    require(proposal["action"] == "branch" and proposal["evidenceSummary"]["zeroImprovementStreak"] == 3 and "stagnation" in proposal["reason"].lower() and stagnant["summary"]["stagnatingCount"] == 1 and stagnant["trustPolicy"]["usageRaisesTrust"] is False and stagnant["importedEvidence"]["rawConversationContentRead"] is False, "a.evolution-stagnation", "repetition raised trust or lost zero-lift branch recommendation")
