"""Fast production-parser journey for incremental Claude transcript pages."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

CONTRACT = "p22.sessions.claude-incremental-transcript"
CONTRACTS = (CONTRACT,)


def _line(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _view(item) -> dict:
    return {"id": item.id, "seq": item.seq, "kind": item.kind,
            "text": item.data.get("text"), "status": item.data.get("status")}


def incremental_journal(root: str | Path) -> dict:
    """Write protocol-valid disposable records, then read them via ItemStore."""
    from .connected_sessions.claude_transcript import ItemStore

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    journal = root / "captured-protocol-input.jsonl"
    session_id = "0123456789abcdef0123456789abcdef"
    user = {"type": "user", "uuid": "journey-user-001", "timestamp": "2026-10-07T20:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Summarize the launch report."}]}}
    assistant = {"type": "assistant", "timestamp": "2026-10-07T20:00:01Z",
                 "message": {"id": "journey-msg-001", "role": "assistant", "model": "fixture-model",
                             "content": [{"type": "thinking", "thinking": "Read the report and summarize its result."},
                                         {"type": "text", "text": "The launch report says all three checks passed."}],
                             "stop_reason": "end_turn"}}
    first = _line(user)
    malformed = b"{this is not a transcript record}\n"
    second = _line(assistant)
    journal.write_bytes(first + malformed + second)

    store = ItemStore(journal, session_id, cwd="C:/journey/workspace")
    page, has_older, cursor = store.page(cursor=None, before_seq=None, limit=20)
    expected_initial = [
        {"id": "journey-user-001", "seq": 0, "kind": "user", "text": "Summarize the launch report.", "status": None},
        {"id": "journey-msg-001:0", "seq": (len(first) + len(malformed)) << 6, "kind": "reasoning",
         "text": None, "status": None},
        {"id": "journey-msg-001:1", "seq": ((len(first) + len(malformed)) << 6) | 1, "kind": "assistant",
         "text": "The launch report says all three checks passed.", "status": None},
    ]
    observed_initial = [_view(item) for item in page]
    if observed_initial != expected_initial:
        raise AssertionError(f"production parser initial events differ: {observed_initial!r}")
    if has_older or not cursor or not cursor.partition(":")[2].isdigit():
        raise AssertionError("initial page/sequence cursor state is incorrect")
    if any("this is not a transcript" in (item.data.get("text") or "") for item in page):
        raise AssertionError("malformed JSON leaked into normalized visible events")

    # Exclusive sequence reads use the exact preceding event sequence and do not duplicate it.
    first_page, _, _ = store.page(cursor=None, before_seq=expected_initial[-1]["seq"], limit=20)
    expected_older = expected_initial[:2]
    if [_view(item) for item in first_page] != expected_older:
        raise AssertionError("before_seq did not return exactly the older exclusive prefix")

    # An unfinished append is retained as a tail; it must not produce a partial event.
    pending = b'{"type":"user","uuid":"journey-user-002","timestamp":"2026-10-07T20:00:02Z","message":{"role":"user","content":[{"type":"text","text":"The revised report is ready'
    with journal.open("ab") as handle:
        handle.write(pending)
    no_change, _, unchanged_cursor = store.page(cursor=cursor, before_seq=None, limit=20)
    if no_change or unchanged_cursor != cursor:
        raise AssertionError("partial JSONL tail changed event state or cursor")

    completed = b'."}]}}\n'
    with journal.open("ab") as handle:
        handle.write(completed)
    delta, _, advanced_cursor = store.page(cursor=cursor, before_seq=None, limit=20)
    expected_delta = [{"id": "journey-user-002", "seq": (len(first) + len(malformed) + len(second)) << 6,
                       "kind": "user", "text": "The revised report is ready.", "status": None}]
    observed_delta = [_view(item) for item in delta]
    if observed_delta != expected_delta:
        raise AssertionError(f"completed append did not become the exact normalized event: {observed_delta!r}")
    if advanced_cursor == cursor or advanced_cursor.partition(":")[0] != cursor.partition(":")[0]:
        raise AssertionError("append should advance cursor version while retaining transcript generation")

    # Replacing/truncating the transcript resets its generation, so an old cursor cannot mask new events.
    replacement = _line({"type": "user", "uuid": "journey-user-003", "timestamp": "2026-10-07T20:00:03Z",
                         "message": {"role": "user", "content": [{"type": "text", "text": "Start a fresh report review."}]}})
    journal.write_bytes(replacement)
    after_replace, _, replacement_cursor = store.page(cursor=advanced_cursor, before_seq=None, limit=20)
    expected_replacement = [{"id": "journey-user-003", "seq": 0, "kind": "user",
                             "text": "Start a fresh report review.", "status": None}]
    if [_view(item) for item in after_replace] != expected_replacement:
        raise AssertionError("replacement failed to invalidate stale cursor and expose new transcript")
    if replacement_cursor.partition(":")[0] == advanced_cursor.partition(":")[0]:
        raise AssertionError("replacement retained the stale transcript generation")

    return {"initialEvents": observed_initial, "exclusiveOlderEvents": expected_older,
            "malformedRecordSkipped": True, "partialTailWithheld": True, "appendEvent": observed_delta[0],
            "cursorVersionAdvanced": True, "replacementGenerationChanged": True,
            "replacementEvent": expected_replacement[0]}


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            with tempfile.TemporaryDirectory(prefix="transcript-journey-", dir=scratch) as folder:
                observed = incremental_journal(folder)
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
