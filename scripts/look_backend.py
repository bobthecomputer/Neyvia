"""Look track: the real web backend with a few disposable sample chats.

Runs scripts/run_web_backend.py's own `main` (production handlers, the given
--root and --static-root) after registering a fixture Codex adapter, so the
chat view can be rendered and inspected without any model run or real chat
history. Nothing here is product code.

  python scripts/look_backend.py --host 127.0.0.1 --port 48851 --root <worktree> \
      --static-root <worktree>/web/dist --skip-runtime-auto-update --skip-proof-self-check
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ANSWER = """Here is what changed in the sidebar:

1. **Rows breathe more.** Each chat row now has 8 px of vertical padding and the title uses the body size, so long titles stay on one line.
2. **The active chat is easier to spot.** It gets the raised surface and a leaf-green marker on the left.
3. **Folders keep their order** when a chat moves between them.

```js
export function rowPadding(density) {
  return { calm: 9, workshop: 7, grove: 5 }[density] ?? 7;
}
```

I ran the sidebar tests and they pass. Want me to apply the same spacing to the Night Shift board?"""

CHATS = [
    ("Tidy the sidebar spacing", "C:/Users/user/Projects/Neyvia-next", [
        {"kind": "user", "data": {"text": "The sidebar rows feel cramped. Can you give them more room and make the active chat easier to see?"}},
        {"kind": "tool", "data": {"category": "read", "name": "read_file", "title": "Read web/src/neyvia/next/nxSidebar.css", "status": "completed", "files": ["web/src/neyvia/next/nxSidebar.css"]}},
        {"kind": "tool", "data": {"category": "edit", "name": "apply_patch", "title": "Edited nxSidebar.css", "status": "completed", "files": ["web/src/neyvia/next/nxSidebar.css"]}},
        {"kind": "tool", "data": {"category": "command", "name": "shell", "title": "npm test -- sidebar", "status": "completed", "exitCode": 0, "command": "npm test -- sidebar", "output": "12 passed"}},
        {"kind": "assistant", "data": {"text": ANSWER}},
    ]),
    ("Plan the release checklist", "C:/Users/user/Projects/plans", [
        {"kind": "user", "data": {"text": "What is left before Monday's release?"}},
        {"kind": "assistant", "data": {"text": "Three things are open: the settings page polish, the dictation retry, and the release notes."}},
    ]),
    ("Night Shift budget", None, [
        {"kind": "user", "data": {"text": "Keep Night Shift under two hours of GPU time."}},
        {"kind": "assistant", "data": {"text": "Done. Night Shift now stops at two hours and tells you in the morning what it skipped."}},
    ]),
    ("Fix the PDF zoom", "C:/Users/user/Projects/Neyvia-next", [
        {"kind": "user", "data": {"text": "Zooming a PDF jumps back to page one."}},
        {"kind": "assistant", "data": {"text": "Fixed: the viewer keeps the page you were on when the zoom changes."}},
    ]),
]


def install_fixture(root: Path) -> None:
    from grant_agent.connected_sessions import broker as broker_module
    from grant_agent.connected_sessions.model import Capabilities, SessionSummary
    from grant_agent.connected_sessions.registry import make_session_id

    original = broker_module.ConnectedBroker.__init__

    class Adapter:
        def __init__(self, device):
            now = datetime.now(timezone.utc)
            self.rows = []
            self.items = {}
            for index, (title, cwd, items) in enumerate(CHATS):
                sid = make_session_id("codex", device, f"look-{index}")
                stamp = (now - timedelta(minutes=7 + index * 95)).isoformat()
                self.rows.append(SessionSummary(id=sid, app="codex", title=title, cwd=cwd, updated_at=stamp, created_at=stamp,
                                                status="idle", capabilities=Capabilities(continue_session=True)))
                self.items[sid] = [{"id": f"{sid}-{n}", "seq": n + 1, **item} for n, item in enumerate(items)]

        def available(self): return True, None
        def live_status(self): return {}
        def list_sessions(self, **kwargs): return list(self.rows)
        def read(self, session_id, **kwargs):
            row = next(row for row in self.rows if row.id == session_id)
            return {"session": row.public(), "items": self.items[session_id]}
        def options(self, session_id=None): return {}
        def start_turn(self, *args, **kwargs): raise RuntimeError("Sample chats are read-only")

    def patched(self, state_root, *args, **kwargs):
        if Path(state_root).resolve() == root.resolve() and kwargs.get("adapters") is None:
            from grant_agent.external_chat_inventory import _host
            kwargs.update(adapters={"codex": Adapter(_host()["deviceId"])}, load_defaults=False, autostart=False)
        original(self, state_root, *args, **kwargs)

    broker_module.ConnectedBroker.__init__ = patched


if __name__ == "__main__":
    root = Path(sys.argv[sys.argv.index("--root") + 1])
    from grant_agent.local_network_policy import install
    install(root)
    install_fixture(root)
    from grant_agent.web_backend import main
    raise SystemExit(main(sys.argv[1:]))
