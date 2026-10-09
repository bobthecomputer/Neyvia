"""Check terminal cleanup and edit filtering against the real board store."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.connected_sessions.broker import ConnectedBroker, _LiveRun
from grant_agent.neyvia_awareness import board_list


def main():
    checks = []
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        broker = ConnectedBroker(root, adapters={}, load_defaults=False)
        # No harness is mocked: feed its public item schema into the broker's event handler.
        broker._persist = lambda run: None  # isolated lifecycle, no fabricated durable run row
        try:
            for state in ("completed", "failed", "cancelled", "interrupted"):
                run = _LiveRun({"runId": state, "app": "codex", "state": "running"}, None, "turn")
                run.cwd = str(root)
                edit = {"kind": "tool", "data": {"category": "edit", "files": ["a.py"], "status": "running"}}
                broker._on_event(run, {"type": "item.added", "item": edit})
                assert board_list(root)["count"] == 1
                broker._on_event(run, {"type": "item.updated", "item": edit})
                assert board_list(root)["count"] == 1
                broker._set_state(run, state)
                assert board_list(root)["count"] == 0
                broker._on_event(run, {"type": "item.updated", "item": edit})
                assert board_list(root)["count"] == 0
                checks.append(state + ": refresh, release, late-event exclusion")
            run = _LiveRun({"runId": "reads", "app": "claude-code", "state": "running"}, None, "turn")
            run.cwd = str(root)
            for data in ({"category": "read", "files": ["a.py"]},
                         {"category": "edit", "files": ["b.py"], "declined": True}):
                broker._on_event(run, {"type": "item.added", "item": {"kind": "tool", "data": data}})
            assert board_list(root)["count"] == 0
            checks.append("reads and declined edits excluded")
        finally:
            broker.close()
    output = Path(__file__).resolve().parent / "evidence/work-board-lifecycle.json"
    output.write_text(json.dumps({"ok": True, "checks": checks}, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "checks": checks}))


if __name__ == "__main__":
    main()
