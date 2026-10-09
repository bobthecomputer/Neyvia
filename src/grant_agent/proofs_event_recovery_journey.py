"""Bounded durable Native event-log recovery and refusal outcome contract."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path


CONTRACT = "native.events.recovery-journey"


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(f"Contract {CONTRACT}: {detail}")


def _canonical(value: object) -> bytes:
    """Independent observer encoding for the public native event wire format."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _observe_journal(path: Path, run_id: str) -> tuple[list[dict], bytes]:
    raw = path.read_bytes()
    lines = raw.splitlines()
    events: list[dict] = []
    previous = "0" * 64
    for expected_sequence, line in enumerate(lines, start=1):
        event = json.loads(line)
        supplied_hash = event.get("eventHash")
        unsigned = {key: value for key, value in event.items() if key != "eventHash"}
        require(event.get("schema") == "neyvia.native-event/v1", "persisted event schema changed")
        require(event.get("runId") == run_id, "persisted event belongs to a different run")
        require(event.get("sequence") == expected_sequence, "persisted sequence is duplicated or out of order")
        require(event.get("eventId") == f"{run_id}:{expected_sequence}", "persisted event identity is not unique and sequential")
        require(event.get("previousHash") == previous, "persisted event chain has a broken predecessor")
        require(supplied_hash == hashlib.sha256(_canonical(unsigned)).hexdigest(), "persisted event digest does not cover its fields")
        previous = supplied_hash
        events.append(event)
    return events, raw


def _journey(root: Path) -> dict:
    from .native_event_stream import NativeEventStream

    run_id = "event-recovery-" + uuid.uuid4().hex
    stream = NativeEventStream(root, run_id)
    first_payload = {"phase": "plan", "message": "Reviewed local plan"}
    first = stream.emit("run.started", first_payload, phase="plan")
    first_bytes = stream.path.read_bytes()
    require(first_bytes.endswith(b"\n"), "the durable event line is not newline terminated")
    persisted_first = json.loads(first_bytes.splitlines()[0])
    require(persisted_first == first, "the persisted first event differs from the emitted event")
    observed_first, _ = _observe_journal(stream.path, run_id)
    require(len(observed_first) == 1 and observed_first[0]["payload"] == first_payload,
            "an independent journal read did not recover the exact first event")

    # Reopening is observational only: construction must recover the tail without appending.
    reopened = NativeEventStream(root, run_id)
    require(stream.path.read_bytes() == first_bytes, "reopening the journal duplicated or rewrote an event")
    second_payload = {"result": "local review complete", "items": 2}
    second = reopened.emit("run.completed", second_payload, parent_event_id=first["eventId"], phase="post")
    require(second["sequence"] == 2 and second["eventId"] != first["eventId"]
            and second["previousHash"] == first["eventHash"],
            "reopened writer did not continue exactly once from the durable tail")
    independent, valid_bytes = _observe_journal(stream.path, run_id)
    require([item["eventId"] for item in independent] == [first["eventId"], second["eventId"]]
            and [item["payload"] for item in independent] == [first_payload, second_payload],
            "fresh observer did not see the exact ordered event contents")
    verification = reopened.verify()
    require(verification["valid"] is True and verification["events"] == 2
            and verification["lastHash"] == second["eventHash"] and not verification["failures"],
            "production integrity verification rejected a valid reopened event chain")

    # A value that cannot be encoded must be rejected before any durable append.
    try:
        reopened.emit("invalid.payload", {"unencodable": object()})
    except (TypeError, ValueError):
        refused = True
    else:
        refused = False
    require(refused, "non-serializable event payload was accepted")
    require(stream.path.read_bytes() == valid_bytes,
            "refused event changed the actual durable journal bytes")
    still_valid = reopened.verify()
    require(still_valid["valid"] is True and still_valid["events"] == 2,
            "valid event history changed after refused append")

    # Corrupt one persisted payload byte and require both independent and production readers to detect it.
    lines = valid_bytes.splitlines(keepends=True)
    first_line = json.loads(lines[0])
    first_line["payload"]["message"] = "tampered local plan"
    lines[0] = (json.dumps(first_line, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    stream.path.write_bytes(b"".join(lines))
    damaged = reopened.verify()
    require(damaged["valid"] is False and any("hash mismatch" in failure for failure in damaged["failures"]),
            "production verifier accepted changed event content")
    try:
        _observe_journal(stream.path, run_id)
    except AssertionError as error:
        require("digest" in str(error), "independent observer refused corruption for an unexpected reason")
        integrity_refused = True
    else:
        integrity_refused = False
    require(integrity_refused, "independent observer accepted the modified event payload")

    # Restore this task-owned fixture, then prove fresh reopen and full content after recovery.
    stream.path.write_bytes(valid_bytes)
    final_reader = NativeEventStream(root, run_id)
    final_events, final_bytes = _observe_journal(final_reader.path, run_id)
    require(final_bytes == valid_bytes and final_reader.verify()["valid"]
            and [event["payload"] for event in final_events] == [first_payload, second_payload],
            "restored fixture did not reopen with its exact prior events")

    return {
        "id": CONTRACT,
        "status": "PASS",
        "executed": [
            "native_event_stream.NativeEventStream.__init__/_recover_tail",
            "native_event_stream.NativeEventStream.emit",
            "native_event_stream.NativeEventStream.verify",
            "proofs_event_recovery_journey._observe_journal",
        ],
        "eventIds": [event["eventId"] for event in final_events],
        "eventPayloads": [event["payload"] for event in final_events],
        "refusal": {"nonSerializableAppend": refused, "tamperedPayload": integrity_refused},
        "reopenDidNotDuplicate": True,
        "independentContentObserved": True,
        "boundary": "Uses only a disposable local event journal; no process, listener, provider, device, account, or network call.",
    }


def self_check(root: str | Path, selected: list[str] | None = None) -> dict:
    """Run the actual event-log journey beneath the supplied disposable root."""
    if selected is not None and CONTRACT not in selected:
        return {"ok": True, "outcomes": [], "unselected": [CONTRACT]}
    base = Path(root).resolve()
    state_root = base / ".agent_control" / "proofs" / "event-recovery" / uuid.uuid4().hex
    state_root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    outcome = _journey(state_root)
    outcome["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
    return {"ok": outcome["status"] == "PASS", "outcomes": [outcome]}
