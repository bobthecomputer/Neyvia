"""Bounded production-parser journey for Codex thread items and rollout state."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

CONTRACT = "p22.sessions.codex-transcript-journal"
CONTRACTS = (CONTRACT,)


def _line(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _view(item) -> dict:
    return {"id": item.id, "seq": item.seq, "kind": item.kind,
            "text": item.data.get("text"), "status": item.data.get("status")}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _turns() -> tuple[list[dict], dict[str, int]]:
    return ([
        {"id": "turn-failed", "status": "failed", "startedAt": 1791400000, "completedAt": 1791400001,
         "error": {"message": "Earlier attempt stopped."},
         "items": [{"id": "old-answer", "type": "agentMessage", "text": "Earlier partial answer"}]},
        {"id": "turn-current", "status": "completed", "startedAt": 1791400010, "completedAt": 1791400011,
         "items": [
             {"id": "user-1", "type": "userMessage", "content": [{"type": "text", "text": "Summarize the workspace changes."}]},
             {"id": "command-1", "type": "commandExecution", "status": "completed", "exitCode": 0,
              "command": "rg changed files", "aggregatedOutput": "2 files changed", "cwd": "C:/work/demo",
              "commandActions": [{"type": "read", "path": "C:/work/demo/src/app.py"}]},
             {"id": "tool-1", "type": "mcpToolCall", "server": "workspace", "tool": "read",
              "status": "completed", "arguments": {"path": "src/app.py"},
              "result": {"content": [{"type": "text", "text": "The parser preserves the exact tool result."}]}},
             {"id": "edit-1", "type": "fileChange", "status": "completed", "changes": [
                 {"path": "C:/work/demo/src/app.py", "kind": {"type": "update"},
                  "diff": "@@ -1 +1 @@\n-old\n+new"}]},
             {"id": "agent-1", "type": "collabAgentToolCall", "status": "completed", "tool": "builder",
              "prompt": "Inspect the changed parser.", "receiverThreadIds": ["agent-thread-17"]},
             {"id": "answer-1", "type": "agentMessage", "text": "Two files changed; the parser result is preserved."},
             None,
             {"id": "future-1", "type": "futureProtocolItem"},
         ]},
        {"id": "turn-interrupted", "status": "interrupted", "startedAt": 1791400020,
         "items": [{"id": "answer-2", "type": "agentMessage", "text": "This reply was interrupted."}]},
        None,
    ], {"turn-failed": 0, "turn-current": 1, "turn-interrupted": 2})


def _replacement_read() -> dict:
    """Run the actual page/reindex code against fixed app-server protocol replies."""
    from .connected_sessions.codex import CodexAdapter

    adapter = object.__new__(CodexAdapter)
    adapter._lock = threading.RLock()
    adapter._turn_indexes = OrderedDict()
    adapter._turn_cursors = OrderedDict()
    adapter._output_turns = OrderedDict()
    index_calls = 0
    read_calls = 0
    replacement = {"id": "turn-new", "status": "completed", "startedAt": 1791400100,
                   "completedAt": 1791400101,
                   "items": [{"id": "replacement-answer", "type": "agentMessage",
                              "text": "The replacement turn is visible."}]}

    def rpc(method, params, **_kwargs):
        nonlocal index_calls, read_calls
        if method != "thread/turns/list":
            raise AssertionError(f"unexpected production page request: {method}")
        if params.get("itemsView") == "notLoaded":
            index_calls += 1
            turn_id = "turn-old" if index_calls == 1 else "turn-new"
            return {"data": [{"id": turn_id}], "nextCursor": None}
        read_calls += 1
        # The first indexed turn was replaced before its full item page arrived.
        return {"data": [replacement], "nextCursor": None}

    adapter._rpc = rpc
    page, has_earlier, newest = adapter._load_turns("thread-replaced", "C:/work/demo", 20, None, None)
    _require(index_calls == 2 and read_calls == 2, "changed turn list did not trigger one bounded reindex")
    _require(not has_earlier and newest == 0, "replacement page cursor/ordinal is incorrect")
    _require([item.id for item in page] == ["replacement-answer", "reasoning-unreported:turn-new"],
             "replacement exposed stale or incorrect page entries")
    _require(page[0].data.get("text") == replacement["items"][0]["text"], "replacement assistant text changed")
    return {"indexRequests": index_calls, "turnReadRequests": read_calls,
            "replacementIds": [item.id for item in page], "staleTurnVisible": False}


def transcript_journey(root: str | Path) -> dict:
    from .connected_sessions.codex_items import make_seq, map_turns, read_tail_rows, rollout_activity
    from .connected_sessions.codex_stream import ThreadStream

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    turns, ordinals = _turns()
    mapped = map_turns(turns, ordinals, cwd="C:/work/demo")
    by_id = {item.id: item for item in mapped}

    _require(by_id["user-1"].seq == make_seq(1, 0), "user transcript slot is not stable")
    _require(by_id["command-1"].seq == make_seq(1, 1), "command transcript slot is not stable")
    _require(by_id["tool-1"].seq == make_seq(1, 2), "MCP transcript slot is not stable")
    _require(by_id["edit-1"].seq == make_seq(1, 3), "file-change transcript slot is not stable")
    _require(by_id["edit-1:diff"].seq == make_seq(1, 3, 1), "file diff did not retain its subslot")
    _require(by_id["agent-1"].seq == make_seq(1, 4), "agent transcript slot is not stable")
    _require(by_id["answer-1"].seq == make_seq(1, 5), "assistant transcript slot is not stable")
    _require(by_id["user-1"].data["text"] == "Summarize the workspace changes.", "user text changed")
    _require(by_id["command-1"].data["output"] == "2 files changed" and by_id["command-1"].data["status"] == "ok",
             "terminal command result or status was lost")
    _require(by_id["command-1"].data["files"] == ["src/app.py"], "command path was not made workspace-relative")
    _require("The parser preserves the exact tool result." in by_id["tool-1"].data["output"],
             "MCP tool result text was not retained")
    _require(by_id["edit-1"].data["files"] == ["src/app.py"], "file-change path was not made workspace-relative")
    _require(by_id["agent-1"].data["agentThreadIds"] == ["agent-thread-17"], "sub-agent thread identity was lost")
    _require(by_id["answer-1"].data["text"] == "Two files changed; the parser result is preserved.",
             "assistant transcript text changed")
    _require("future-1" in by_id and "futureprotocolitem" in by_id["future-1"].data["text"].lower(),
             "unknown item was not represented as a calm transcript notice")
    _require("turn-error:turn-failed" in by_id and "turn-interrupted:turn-interrupted" in by_id,
             "failed/interrupted turn terminal markers were lost")
    _require(len(mapped) == 13 and "None" not in by_id,
             "malformed non-object turn/item was not skipped cleanly")

    # The same live production parser carries a partial command through start,
    # output deltas, completion, and terminal turn failure without a provider.
    events = []
    stream = ThreadStream("external:codex:device:thread-live", "thread-live", events.append,
                          cwd="C:/work/demo", ordinal_of_turn=lambda _turn: 0)
    stream.begin_turn(turn_id="turn-live")
    started = {"type": "commandExecution", "id": "live-command", "status": "inProgress",
               "command": "rg result", "aggregatedOutput": ""}
    stream.handle("item/started", {"turnId": "turn-live", "item": started})
    _require(stream.items["live-command"].data["status"] == "running", "started command did not remain pending")
    stream.handle("item/commandExecution/outputDelta", {"itemId": "live-command", "delta": "first "})
    stream.handle("item/commandExecution/outputDelta", {"itemId": "live-command", "delta": "result"})
    completed = {**started, "status": "completed", "exitCode": 0, "aggregatedOutput": "first result"}
    stream.handle("item/completed", {"turnId": "turn-live", "item": completed})
    stream.end_turn({"id": "turn-live", "status": "failed", "error": {"message": "Stream failed after output."}})
    live = {item.id: item for item in stream.live_items()}
    _require(live["live-command"].seq == make_seq(0, 0), "live/read transcript slot diverged")
    _require(live["live-command"].data["status"] == "ok" and live["live-command"].data["output"] == "first result",
             "partial live output did not settle to the exact terminal command result")
    _require("turn-error:turn-live" in live, "live failed turn did not produce its terminal marker")
    _require(any(event.get("type") == "item.delta" and event.get("textDelta") == "first " for event in events),
             "first live output delta was not emitted")

    # Codex's persisted JSONL rollout is the production active-turn journal.
    # It is separate from app-server transcript items; malformed/partial rows
    # are skipped, terminal markers close activity, and replacement is fresh.
    journal = root / "codex-rollout.jsonl"
    start = _line({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "rollout-1",
                                                       "started_at": 1791400200}})
    journal.write_bytes(start + b'{"type":"event_msg","payload":{"type":"task_complete"')
    rows = read_tail_rows(journal, 1024)
    active = rollout_activity(journal, now=time.time())
    _require(len(rows) == 1 and active["inProgress"] and active["turnId"] == "rollout-1",
             "malformed/partial rollout tail changed active-turn state")
    terminal = _line({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "rollout-1"}})
    with journal.open("ab") as handle:
        handle.write(b"}}\n" + terminal)
    closed = rollout_activity(journal, now=time.time())
    _require(not closed["inProgress"], "terminal rollout marker left turn active")
    replacement = _line({"type": "event_msg", "payload": {"type": "turn_started", "turn_id": "rollout-2",
                                                              "started_at": 1791400210}})
    journal.write_bytes(replacement)
    replaced = rollout_activity(journal, now=time.time())
    _require(replaced["inProgress"] and replaced["turnId"] == "rollout-2",
             "replacement rollout journal retained the prior turn identity")

    return {"mappedSlots": {key: by_id[key].seq for key in
                             ("user-1", "command-1", "tool-1", "edit-1", "edit-1:diff", "agent-1", "answer-1")},
            "toolOutput": by_id["tool-1"].data["output"], "assistantText": by_id["answer-1"].data["text"],
            "workspacePaths": by_id["command-1"].data["files"],
            "agentThreadIds": by_id["agent-1"].data["agentThreadIds"], "unknownNotice": by_id["future-1"].data["text"],
            "failedAndInterruptedMarkers": ["turn-error:turn-failed", "turn-interrupted:turn-interrupted"],
            "liveResult": live["live-command"].public(), "liveDeltaEvents": sum(event.get("type") == "item.delta" for event in events),
            "malformedAndPartialRolloutRowsSkipped": True, "terminalRolloutClosesTurn": True,
            "replacementRolloutTurnId": replaced["turnId"], "turnListReplacement": _replacement_read()}


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            with tempfile.TemporaryDirectory(prefix="codex-transcript-", dir=scratch) as folder:
                observed = transcript_journey(folder)
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
