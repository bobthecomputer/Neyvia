"""Real Codex new/resumed turn injection; board inputs seeded explicitly."""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.connected_sessions.broker import ConnectedBroker
from grant_agent.connected_sessions.codex import CodexAdapter
from grant_agent.neyvia_awareness import claim, release


def main():
    workspace = Path(__file__).resolve().parents[1]
    root = workspace / ".agent_control" / ("codex-board-proof-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    traces = []
    def trace(direction, data):
        if data.get("method") in {"thread/start", "thread/resume"}:
            traces.append({"direction": direction, "method": data["method"], "params": data.get("params")})
    adapter = CodexAdapter(state_root=root, trace=trace)
    broker = ConnectedBroker(root, adapters={"codex": adapter}, load_defaults=False)
    identities, results = [], []
    request = "Name the file another agent is currently editing from the live work board in your first sentence. No tools."
    options = {"permissionMode": "read-only", "effort": "low"}
    try:
        session = None
        for name in ("copper.py", "silver.py"):
            if identities:
                release(root, {"id": identities.pop()})
                # The existing writer guard refuses idle threads still locked by this app-server.
                # Restart our disposable broker to release that writer before proving resume.
                broker.close()
                adapter = CodexAdapter(state_root=root, trace=trace)
                broker = ConnectedBroker(root, adapters={"codex": adapter}, load_defaults=False)
            record = claim(root, {"agent": "Claude Code", "chat": "explicit-proof-fixture",
                "files": [str(root / name)], "intent": "board injection fixture"})
            identities.append(record["claim"]["id"])
            run = (broker.send(session, request, uuid.uuid4().hex, options) if session else
                   broker.new("codex", str(root), request, uuid.uuid4().hex, options))
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                run = broker.get_run(run["runId"])
                if run["state"] not in {"queued", "running", "waiting_input", "waiting_approval"}:
                    break
                time.sleep(.25)
            assert run["state"] == "completed", run
            session = run["sessionId"]
            page = broker.read(session)
            replies = [item["data"]["text"] for item in page["items"] if item["kind"] == "assistant"]
            (workspace / "scripts/evidence/work-board-codex-trace.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
            assert replies and name in replies[-1], page
            results.append({"file": name, "run": run, "reply": replies[-1]})
        output = workspace / "scripts/evidence/work-board-codex.json"
        output.write_text(json.dumps({"ok": True, "boundary": "Real Codex new and resumed turns after disposable broker restart, explicit seeded work-board fixture",
            "results": results, "instructionTrace": traces}, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "results": results}))
    finally:
        for identity in identities:
            release(root, {"id": identity})
        broker.close()


if __name__ == "__main__":
    main()
