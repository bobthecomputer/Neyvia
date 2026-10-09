"""Outcome contract for the connected-session event cursor stream."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

CONTRACT = "p22.session-event-cursor"
CONTRACTS = (CONTRACT,)


def cursor_overflow_wait_close() -> dict:
    """Exercise the production in-memory EventBuffer without starting a broker."""
    from .connected_sessions.events import EventBuffer

    stream = EventBuffer("host-alpha", max_events=3, max_bytes=4096, max_event_bytes=1024, start_cursor=100)
    initial = stream.since(None)
    if initial != ([], 100, False):
        raise AssertionError(f"A new subscriber must start at the current head: {initial!r}")

    authored = [
        {"type": "run.state", "sessionId": "session-A", "runId": "run-A", "requestId": "req-A1", "state": "running"},
        {"type": "run.state", "sessionId": "session-B", "runId": "run-B", "requestId": "req-B1", "state": "waiting"},
        {"type": "run.output", "sessionId": "session-A", "runId": "run-A", "requestId": "req-A2", "text": "A output"},
        {"type": "run.output", "sessionId": "session-B", "runId": "run-B", "requestId": "req-B2", "text": "B output"},
        {"type": "run.state", "sessionId": "session-A", "runId": "run-A", "requestId": "req-A3", "state": "completed"},
    ]
    published = [stream.publish(event) for event in authored]
    if [event.get("cursor") for event in published] != [101, 102, 103, 104, 105]:
        raise AssertionError("Published session events lost monotonic cursor identity")
    if any(event.get("hostDeviceId") != "host-alpha" for event in published):
        raise AssertionError("A published event lost its owning host identity")
    for actual, expected in zip(published, authored):
        for key in ("type", "sessionId", "runId", "requestId"):
            if actual.get(key) != expected.get(key):
                raise AssertionError(f"Published event changed {key}: {actual!r}")

    retained, head, resync = stream.since(102)
    if (head, resync) != (105, False) or retained != published[2:]:
        raise AssertionError(f"Reconnect at oldest retained cursor did not drain exact ordered events: {(retained, head, resync)!r}")
    expected_sessions = ["session-A", "session-B", "session-A"]
    expected_requests = ["req-A2", "req-B2", "req-A3"]
    if ([event["sessionId"] for event in retained] != expected_sessions
            or [event["requestId"] for event in retained] != expected_requests):
        raise AssertionError("Interleaved sessions were conflated or lost their event identity")
    retained_bytes = sum(len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                         for event in retained)
    if len(retained) != 3 or retained_bytes > 4096:
        raise AssertionError("Reconnect exceeded the configured event-count or byte bound")
    gap_events, gap_head, gap_resync = stream.since(101)
    if (gap_events, gap_head, gap_resync) != ([], 105, True):
        raise AssertionError("A cursor older than the bounded ring did not request a clean resync")
    future_events, future_head, future_resync = stream.since(106)
    if (future_events, future_head, future_resync) != ([], 105, True):
        raise AssertionError("An ahead-of-head cursor did not request a clean resync")
    resume, resume_head, resume_resync = stream.since(104)
    if (resume, resume_head, resume_resync) != ([published[-1]], 105, False):
        raise AssertionError("Resume from the latest prior cursor did not return exactly the next session event")

    # A separately owned host stream must not inherit another host's cursor or events.
    other_host = EventBuffer("host-beta", max_events=3, max_bytes=2048, max_event_bytes=1024, start_cursor=900)
    other_event = other_host.publish({
        "type": "run.output", "sessionId": "session-B", "runId": "run-B", "requestId": "req-B-private", "text": "other host",
    })
    if other_event.get("cursor") != 901 or other_event.get("hostDeviceId") != "host-beta":
        raise AssertionError("Second host event did not retain its own cursor and host identity")
    other_host_isolated = stream.since(105) == ([], 105, False)
    if not other_host_isolated:
        raise AssertionError("A separately owned host event leaked into this host stream")
    if other_host.since(900) != ([other_event], 901, False):
        raise AssertionError("Second host could not resume its own exact event")

    bounded = EventBuffer("host-bounded", max_events=2, max_bytes=1024, max_event_bytes=512, start_cursor=50)
    long_payload = bounded.publish({
        "type": "run.output", "sessionId": "session-large", "runId": "run-large",
        "requestId": "req-large", "text": "retain-prefix-" + ("payload " * 800),
    })
    encoded_size = len(json.dumps(long_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if (encoded_size > 512 or long_payload.get("truncated") is not True
            or long_payload.get("text", "").startswith("retain-prefix-") is not True
            or long_payload.get("sessionId") != "session-large"
            or bounded.since(50) != ([long_payload], 51, False)):
        raise AssertionError("Oversized event did not preserve bounded payload and identifying fields")

    ready = threading.Event()
    wake_result_box: list[tuple[list[dict], int, bool]] = []

    def receive_after(cursor: int):
        ready.set()
        wake_result_box.append(stream.wait(cursor, 0.25))

    cursor_before_wakeup = stream.head()
    waiter = threading.Thread(target=receive_after, args=(cursor_before_wakeup,), name="p22-session-event-wait", daemon=True)
    waiter.start()
    try:
        if not ready.wait(0.1):
            raise AssertionError("Event reader failed to enter its bounded wait")
        time.sleep(0.003)
        if not waiter.is_alive():
            raise AssertionError("Event reader returned before an event or close")
        wake_event = stream.publish({
            "type": "run.output", "sessionId": "session-A", "runId": "run-A",
            "requestId": "req-A-wake", "text": "control drain",
        })
        waiter.join(0.15)
        if waiter.is_alive() or not wake_result_box:
            raise AssertionError("Published event did not release the waiting reader")
        wake_result = wake_result_box[0]
        if wake_result != ([wake_event], cursor_before_wakeup + 1, False):
            raise AssertionError(f"Waiting reader did not drain the exact published event: {wake_result!r}")
        if wake_event.get("sessionId") != "session-A" or wake_event.get("requestId") != "req-A-wake":
            raise AssertionError("Wake event identity changed in the reader result")
    finally:
        if waiter.is_alive():
            stream.close()
            waiter.join(0.15)

    close_cursor = stream.head()
    close_ready = threading.Event()
    close_result_box: list[tuple[list[dict], int, bool]] = []

    def receive_until_close():
        close_ready.set()
        close_result_box.append(stream.wait(close_cursor, 0.25))

    closer = threading.Thread(target=receive_until_close, name="p22-session-event-close", daemon=True)
    closer.start()
    try:
        if not close_ready.wait(0.1):
            raise AssertionError("Close observer failed to enter its bounded wait")
        time.sleep(0.003)
        stream.close()
        closer.join(0.15)
        if closer.is_alive() or not close_result_box:
            raise AssertionError("Close failed to release the waiting reader")
        close_result = close_result_box[0]
        if close_result != ([], close_cursor, False) or not stream.closed:
            raise AssertionError(f"Closing the stream did not release the reader cleanly: {close_result!r}")
    finally:
        if closer.is_alive():
            stream.close()
            closer.join(0.15)

    return {
        "hostId": "host-alpha",
        "firstAndLastCursor": [published[0]["cursor"], published[-1]["cursor"]],
        "retainedSessionRequestIds": [event["requestId"] for event in retained],
        "retainedSessionIds": [event["sessionId"] for event in retained],
        "sessionIdentityNotConflated": [event["sessionId"] for event in retained] == expected_sessions,
        "retainedEventBytes": retained_bytes,
        "gapResync": gap_resync,
        "aheadResync": future_resync,
        "exactResumeRequestId": resume[0]["requestId"],
        "otherHostIsolation": other_host_isolated,
        "boundedEventBytes": encoded_size,
        "boundedEventTruncated": long_payload["truncated"],
        "wakeRequestId": wake_event["requestId"],
        "wakeReturnedExactEvent": wake_result[0] == [wake_event],
        "closeReleasedReader": close_result == ([], close_cursor, False),
        "readerThreadJoined": not waiter.is_alive() and not closer.is_alive(),
    }


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            observed = cursor_overflow_wait_close()
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
