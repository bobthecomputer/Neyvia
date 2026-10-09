"""Outcome contract for scoped working-memory continuity and retrieval."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

CONTRACT = "p22.working-memory-continuity"
CONTRACTS = (CONTRACT,)


def scoped_projection_retrieval(root: str | Path) -> dict:
    """Prove projection, reopen/retrieval, and isolation through the real store."""
    from .working_memory import WorkingMemoryStore

    root = Path(root).resolve()
    owner_id = "p22-memory-owner-journey"
    other_id = "p22-memory-other-work-journey"
    owner = WorkingMemoryStore(root, owner_id)
    other = WorkingMemoryStore(root, other_id)

    expected_objective = "Keep the migration note attached to the correct work identity."
    expected_decision = "Keep the owner decision available in the compact projection."
    expected_key = "journey.retrieval-target"
    expected_value = {
        "title": "Exact retrieval after projection",
        "detail": "A saved observation is omitted from the bounded view and remains retrievable.",
        "body": "retain this user-visible source text " + ("evidence " * 1800),
    }

    before = owner.snapshot()
    if before["revision"] != 0 or before["memoryId"] != owner_id:
        raise AssertionError(f"New work identity did not start at revision zero: {before!r}")

    objective_state = owner.set_objective(expected_objective, source="user")
    decision_state = owner.record_decision(expected_decision, source="user", scope="p22")
    observation_state = owner.record_observation(
        expected_key,
        expected_value,
        source="journey-source",
        freshness="current",
        observed_at="2026-10-07T20:00:00Z",
        source_ref="journey:source-note-1",
    )
    decision_id = decision_state["decisions"][-1]["recordId"]
    observation_id = observation_state["observations"][-1]["recordId"]
    if (objective_state["revision"], decision_state["revision"], observation_state["revision"]) != (1, 2, 3):
        raise AssertionError("Each successful memory mutation must advance this work identity exactly once")

    projection = owner.project(token_budget=600)
    visible_decisions = projection.get("records", {}).get("decisions", [])
    visible_observations = projection.get("records", {}).get("observations", [])
    omitted_ids = {item.get("recordId") for item in projection.get("omitted", [])}
    if projection.get("memoryId") != owner_id or projection.get("revision") != 3:
        raise AssertionError(f"Projection lost its exact work identity/revision: {projection!r}")
    if projection.get("objective", {}).get("text") != expected_objective:
        raise AssertionError("Projection did not preserve the independently expected objective text")
    if not any(row.get("recordId") == decision_id and row.get("text") == expected_decision for row in visible_decisions):
        raise AssertionError("Projection did not retain the exact user decision")
    if any(row.get("recordId") == observation_id for row in visible_observations):
        raise AssertionError("The large retrieval target should be omitted from the compact projection")
    if observation_id not in omitted_ids or projection.get("omittedCount", 0) < 1:
        raise AssertionError("The compact projection omitted content without its exact retrieval identity")

    reopened = WorkingMemoryStore(root, owner_id)
    persisted_projection = reopened.project(token_budget=600)
    recovered_decision = reopened.retrieve(decision_id)
    recovered_observation = reopened.retrieve(observation_id)
    if persisted_projection.get("revision") != 3 or persisted_projection.get("objective", {}).get("text") != expected_objective:
        raise AssertionError("Reopened projection did not preserve the expected work state")
    if not recovered_decision or recovered_decision.get("text") != expected_decision:
        raise AssertionError("Reopened store did not retrieve the exact decision by its record identity")
    if not recovered_observation or recovered_observation.get("recordId") != observation_id:
        raise AssertionError("Reopened store did not retrieve the exact omitted record identity")
    if recovered_observation.get("key") != expected_key or recovered_observation.get("value") != expected_value:
        raise AssertionError("Retrieved record did not preserve independently expected user content")
    if recovered_observation.get("source") != "journey-source" or recovered_observation.get("sourceRef") != "journey:source-note-1":
        raise AssertionError("Retrieved record lost its source provenance")

    other.set_objective("This is a separate work identity.", source="user")
    other.record_decision("Do not expose the first work's decision.", source="user", scope="other")
    other_revision = other.snapshot()["revision"]
    refused_decision = other.retrieve(decision_id)
    refused_observation = other.retrieve(observation_id)
    other_projection = other.project(token_budget=600)
    if refused_decision is not None or refused_observation is not None:
        raise AssertionError("Another work identity retrieved a record owned by the first identity")
    if other.snapshot()["revision"] != other_revision:
        raise AssertionError("A cross-work retrieval refusal mutated the unrelated work state")
    if (other_projection.get("memoryId") != other_id
            or other_projection.get("objective", {}).get("text") != "This is a separate work identity."):
        raise AssertionError("The second work projection was not independently scoped")
    if any(row.get("text") == expected_decision for rows in other_projection.get("records", {}).values() for row in rows):
        raise AssertionError("The second work projection exposed the first work's decision")

    events_path = root / ".agent_control" / "working_memory" / f"{owner_id}.events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    expected_events = ["objective_set", "decision_recorded", "observation_recorded"]
    if [event.get("event") for event in events] != expected_events:
        raise AssertionError(f"Owner event sequence does not match the three user changes: {events!r}")
    if ([event.get("revision") for event in events] != [1, 2, 3]
            or any(event.get("memoryId") != owner_id for event in events)
            or len({event.get("eventId") for event in events}) != 3):
        raise AssertionError("Owner event identities or revisions are not exact and unique")
    if (events[1].get("payload", {}).get("recordId") != decision_id
            or events[2].get("payload", {}).get("recordId") != observation_id):
        raise AssertionError("Durable events do not point to the exact returned record identities")

    return {
        "ownerMemoryId": owner_id,
        "ownerRevision": persisted_projection["revision"],
        "objective": persisted_projection["objective"]["text"],
        "decisionRecordId": decision_id,
        "decisionText": recovered_decision["text"],
        "omittedRecordId": observation_id,
        "retrievedKey": recovered_observation["key"],
        "retrievedBodyPrefix": recovered_observation["value"]["body"][:38],
        "eventIds": [event["eventId"] for event in events],
        "eventRevisions": [event["revision"] for event in events],
        "otherWorkId": other_id,
        "otherRevision": other_revision,
        "crossWorkDecisionRefused": refused_decision is None,
        "crossWorkObservationRefused": refused_observation is None,
        "crossWorkStateUnchanged": other.snapshot()["revision"] == other_revision,
    }


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            with tempfile.TemporaryDirectory(prefix="working-memory-", dir=scratch) as folder:
                observed = scoped_projection_retrieval(Path(folder))
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
