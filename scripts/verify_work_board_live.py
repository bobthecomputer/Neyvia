"""Two real Claude chats through Neyvia's connected-session broker (no fake adapter)."""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.connected_sessions.broker import ConnectedBroker
from grant_agent.connected_sessions.claude import ClaudeAdapter
from grant_agent.neyvia_awareness import board_list


def main():
    workspace = Path(__file__).resolve().parents[1]
    scratch = workspace / ".agent_control" / ("work-board-proof-" + uuid.uuid4().hex[:8])
    scratch.mkdir(parents=True)
    adapter = ClaudeAdapter(state_root=scratch)
    broker = ConnectedBroker(scratch, adapters={"claude-code": adapter}, load_defaults=False)
    options = {"model": "haiku", "permissionMode": "bypassPermissions"}
    runs = []
    events = []
    cursor = broker.events.head()
    try:
        first = broker.new("claude-code", str(scratch),
            "Use Write to create amber.txt containing amber and violet.txt containing violet in this folder. "
            "Immediately after writing both files, run Bash sleep 60, then reply done. Use no other tools.",
            uuid.uuid4().hex, options)
        runs.append(first["runId"])
        deadline = time.monotonic() + 90
        live = []
        while time.monotonic() < deadline:
            batch, cursor, _ = broker.wait_events(cursor, 1)
            events.extend(batch)
            live = board_list(scratch)["claims"]
            paths = {Path(path).name for row in live for path in row["files"]}
            if {"amber.txt", "violet.txt"} <= paths:
                break
            if broker.get_run(first["runId"])["state"] in {"failed", "completed"}:
                break
        assert {"amber.txt", "violet.txt"} <= paths, ("first turn did not auto-claim both files", broker.get_run(first["runId"]))
        second = broker.new("claude-code", str(scratch),
            "In your first reply, name the files another chat is currently editing according to your live work board. "
            "Do not use any tools or read any files. Reply in one sentence.", uuid.uuid4().hex, options)
        runs.append(second["runId"])
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            batch, cursor, _ = broker.wait_events(cursor, 1)
            events.extend(batch)
            if all(broker.get_run(run)["state"] not in {"queued", "running", "waiting_input", "waiting_approval"} for run in runs):
                break
        second_page = broker.read(broker.get_run(second["runId"])["sessionId"])
        replies = [item["data"]["text"] for item in second_page["items"] if item["kind"] == "assistant"]
        text = replies[0] if replies else ""
        assert "amber.txt" in text and "violet.txt" in text, second_page
        assert not any(item["kind"] == "tool" for item in second_page["items"]), second_page
        assert board_list(scratch)["count"] == 0, board_list(scratch)
        result = {"ok": True, "boundary": "real Neyvia connected broker + installed Claude CLI; no UI screenshot",
            "scratch": str(scratch), "claimsDuringFirstTurn": live,
            "runs": [broker.get_run(run) for run in runs], "secondChat": second_page,
            "releasedBoard": board_list(scratch)}
        output = workspace / "scripts" / "evidence" / "work-board-live.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"ok": True, "evidence": str(output), "runs": result["runs"]}))
    finally:
        for run in runs:
            if broker.get_run(run)["state"] in {"running", "queued", "waiting_input", "waiting_approval"}:
                broker.stop(run)
        broker.close()


if __name__ == "__main__":
    main()
