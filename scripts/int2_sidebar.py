"""Real HTTP sidebar proof against 900 persisted chats on an isolated native backend.

Only the native adapter is enabled in this disposable server: no account CLI,
protected history, credential file, shared runtime or public service is opened.
The production backend, adapter, bus, database and HTTP handlers are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
PYTHON = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe")


def serve(root, port):
    from int2_pytest_guard import install
    install()
    from grant_agent import neyvia_ui_api
    from grant_agent.connected_sessions.broker import broker_for
    from grant_agent.connected_sessions.neyvia import NeyviaAdapter
    bind = neyvia_ui_api.bind_backend

    def isolated(backend):
        bind(backend)
        broker = broker_for(root, backend)
        broker.registry._load_defaults = False
        broker.registry._adapters["neyvia"] = NeyviaAdapter(backend)

    neyvia_ui_api.bind_backend = isolated
    sys.argv = ["run_web_backend.py", "--host", "127.0.0.1", "--port", str(port),
                "--root", str(root), "--skip-runtime-auto-update"]
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    backend = FluxioWebBackend(root, REPO / ".agent_control/int2/build-final")
    isolated(backend)
    server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", port), make_handler(backend))
    try:
        server.serve_forever()
    finally:
        server.server_close()


def fixture(root):
    from grant_agent.neyvia_conversations import NeyviaConversationStore
    store = NeyviaConversationStore(root)
    folders = []
    for index in range(50):
        path = root / "folders" / str(index)
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--quiet", str(path)], check=True, capture_output=True)
        folders.append(path)
    for index in range(900):
        cid = f"follow_sidebar_{index:04}"
        try:
            store.get_conversation(cid)
            continue
        except KeyError:
            pass
        stamp = f"2026-10-03T12:{index // 60:02}:{index % 60:02}+00:00"
        store.create_conversation(conversation_id=cid, title=f"FOLLOW fixture conversation {index}",
                                  metadata={"workspacePath": str(folders[index % 50])}, now=stamp)
        for role, text in [("user", "Review the current project and identify the next useful change."),
                           ("assistant", f"Saved conversation {index}: inspect the affected implementation and verify the result.")]:
            store.append_turn(cid, role=role, content=text, now=stamp)
    return store, folders


def verify(root, port, receipt):
    store, folders = fixture(root)
    env = {**os.environ, "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
           "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_RUNTIME_AUTO_UPDATE": "0",
           "NEYVIA_UI_STATE_ROOT": str(root), "NEYVIA_CONNECTED_SERVICE_PORT": str(port),
           "NEYVIA_SIDEBAR_ALLOWED_ROOTS": json.dumps([str(root)]),
           "SYNTELOS_ACCOUNT_USERNAME": "int2-proof", "SYNTELOS_ACCOUNT_PASSWORD": "disposable-int2-fixture"}
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        start = time.perf_counter()
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=120) as response:
            value = json.load(response)
        return value.get("data", value), round((time.perf_counter() - start) * 1000, 2)

    evidence = {"schema": "neyvia.INT2.sidebar.v1", "base": base, "root": str(root), "checks": [],
                "boundary": "900 real persisted native conversations, 1800 durable turns, 50 real local git folders; production backend HTTP and SSE. Paul's protected history and provider CLIs were not opened; their cold latency is not claimed."}
    with (root / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), "--serve", "--root", str(root), "--port", str(port)],
                                  cwd=REPO, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 90
            while True:
                try:
                    health, _ = request("/api/health")
                    assert health["ok"] is True
                    break
                except (OSError, AssertionError):
                    assert server.poll() is None, "Isolated backend exited before health"
                    assert time.monotonic() < deadline, "Backend did not become healthy"
                    time.sleep(.2)
            request("/api/auth/local-session", {})
            first, cold = request("/api/ui/sidebar?limit=50")
            initial_pages = [{"total": first["total"], "ms": cold}]
            deadline = time.monotonic() + 60
            while first["total"] != 900:
                assert time.monotonic() < deadline, {"total": first["total"], "sources": first["sources"]}
                time.sleep(.2)
                first, elapsed = request("/api/ui/sidebar?limit=50")
                initial_pages.append({"total": first["total"], "ms": elapsed})
            assert first["total"] == 900 and len(first["sessions"]) == 50, {"total": first["total"], "sources": first["sources"], "errors": first["errors"]}
            assert all(row["sidebar"]["complete"] and row["sidebar"]["turnCount"] == 1 for row in first["sessions"])
            warm = []
            for _ in range(12):
                page, elapsed = request("/api/ui/sidebar?limit=50")
                assert page["total"] == 900 and page["nextOffset"] == 50
                assert elapsed < 1000, elapsed
                warm.append(elapsed)
            evidence["checks"].append({"name": "900-chat first page and twelve warm calls", "passed": True, "coldMs": cold, "initialPages": initial_pages, "warmMs": warm})
            next_page, _ = request("/api/ui/sidebar?limit=50&offset=50")
            assert len(next_page["sessions"]) == 50
            assert not {row["id"] for row in page["sessions"]} & {row["id"] for row in next_page["sessions"]}
            assert next_page["total"] == 900
            sid = first["sessions"][0]["id"]
            request("/api/ui/tools/call", {"tool": "neyvia.session.pin", "arguments": {"id": sid, "pinned": True}})
            pinned, pin_ms = request("/api/ui/sidebar?limit=50")
            assert pinned["sessions"][0]["pinned"] is True and pin_ms < 1000
            cid = sid.rsplit(":", 1)[-1]
            from grant_agent.ui_command_bus import bus_for
            with bus_for(root).connect() as db:
                event_cursor = db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
            marker = "FOLLOW background freshness marker " + str(time.time_ns())
            store.append_turn(cid, role="assistant", content=marker, now=datetime.now(timezone.utc).isoformat())
            time.sleep(3.1)
            stale, stale_ms = request("/api/ui/sidebar?limit=50")
            assert stale_ms < 1000
            deadline = time.monotonic() + 30
            while True:
                fresh, elapsed = request("/api/ui/sidebar?limit=50")
                assert elapsed < 1000, elapsed
                changed = next(row for row in fresh["sessions"] if row["id"] == sid)
                if changed["sidebar"]["preview"]["text"] == marker:
                    break
                assert time.monotonic() < deadline, "Background transcript did not refresh"
                time.sleep(.15)
            with opener.open(base + f"/api/ui/events?cursor={event_cursor}", timeout=10) as stream:
                assert stream.headers["Content-Type"] == "text/event-stream"
                for _ in range(100):
                    line = stream.readline().decode()
                    if line.startswith("data:") and json.loads(line[5:]).get("action") == "sidebar.refreshed":
                        event = json.loads(line[5:])
                        break
                else:
                    raise AssertionError("Refresh not delivered on the real UI stream")
            evidence["checks"].append({"name": "Paging, immediate saved pin, expired warm page, asynchronous transcript update and real SSE refresh", "passed": True,
                                       "pinMs": pin_ms, "expiredWarmMs": stale_ms, "streamEvent": event})
            from grant_agent.connected_sessions.sidebar_cleanup import SidebarSafetyObserver, archive_blocker
            observer = SidebarSafetyObserver(allowed_roots=[root])
            pending = observer.observe_cached(str(folders[0]))
            assert archive_blocker(pending) == "safety_unknown"
            deadline = time.monotonic() + 15
            while observer.observe_cached(str(folders[0]))["cleanup_safety"].get("refreshing"):
                assert time.monotonic() < deadline
                time.sleep(.05)
            (folders[0] / "dirty.txt").write_text("Preserve this uncommitted work\n")
            fresh_safety = SidebarSafetyObserver(allowed_roots=[root]).observe(str(folders[0]))
            assert fresh_safety["has_uncommitted"] is True and archive_blocker(fresh_safety) == "dirty_worktree"
            listed, list_ms = request("/api/backend", {"command": "connected_sessions_list_command", "payload": {"app": "neyvia", "limit": 50}})
            assert len(listed["sessions"]) == 50 and list_ms < 1000, list_ms
            evidence["checks"].append({"name": "Folder display refresh is nonblocking; fresh archival safety refuses dirty work; real 50-folder list", "passed": True, "listMs": list_ms})
            evidence["passed"] = True
        finally:
            server.terminate()
            server.wait(timeout=30)
            evidence["serverStopped"] = server.poll() is not None
            files = ["src/grant_agent/neyvia_sidebar_projection.py", "src/grant_agent/connected_sessions/sidebar_cleanup.py", "src/grant_agent/connected_sessions/broker.py", "scripts/int2_sidebar.py"]
            evidence["sourceHashes"] = {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in files}
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--receipt", type=Path, default=REPO / "scripts/evidence/int2/sidebar.json")
    args = parser.parse_args()
    assert args.port == 48602, "Only the assigned sidebar port is permitted"
    root = args.root or REPO / ".agent_control/int2" / f"sidebar-{time.time_ns()}"
    root = root.resolve()
    assert root.is_relative_to(REPO / ".agent_control/int2") and root.name.startswith("sidebar"), "Proof root must be task-local"
    root.mkdir(parents=True, exist_ok=True)
    serve(root, args.port) if args.serve else verify(root, args.port, args.receipt)
