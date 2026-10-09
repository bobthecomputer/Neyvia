"""Production HTTP archive/undo/policy calls with real scratch worktrees and jobs."""

from __future__ import annotations

import http.cookiejar
import gc
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grant_agent.connected_sessions.broker import ConnectedBroker, _BROKERS, make_session_id
from grant_agent.connected_sessions.model import SessionSummary
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from grant_agent.web_backend import FluxioWebBackend, make_handler


class ScratchInventory:
    """Supply disposable session metadata only; every tested action uses real services."""
    def __init__(self, rows):
        self.rows = rows

    def available(self):
        return True, None

    def list_sessions(self, **_):
        return self.rows

    def live_status(self):
        return {}

    def refresh_summary(self, identity):
        return next(row for row in self.rows if row.id == identity)


def git(cwd, *args):
    result = subprocess.run(["git", "-c", "user.name=Fixwave verification", "-c", "user.email=fixwave@example.invalid", *args],
                            cwd=cwd, capture_output=True, text=True, check=True, **hidden_windows_subprocess_kwargs())
    return result.stdout


def main():
    with TemporaryDirectory(prefix="fixwave-item5-") as temp:
        root = Path(temp)
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
        os.environ["NEYVIA_UI_BACKEND_URL"] = ""
        os.environ["NEYVIA_SIDEBAR_ALLOWED_ROOTS"] = json.dumps([str(root)])
        os.environ["NEYVIA_SIDEBAR_EXCLUDED_ROOTS"] = json.dumps([
            r"C:\Users\user\Projects\Neyvia", r"C:\Users\user\Projects\Neyvia-next"])
        os.environ["SYNTELOS_ACCOUNT_USER"] = "fixwave"
        password = secrets.token_urlsafe(24)
        os.environ["SYNTELOS_ACCOUNT_PASSWORD"] = password
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init")
        (repo / "keeper.txt").write_text("KEEP THIS FILE\n", encoding="utf-8")
        git(repo, "add", "keeper.txt")
        git(repo, "commit", "-m", "Disposable fixture")
        dirty = root / "dirty-linked-worktree"
        git(repo, "worktree", "add", "--detach", str(dirty))
        (dirty / "keeper.txt").write_text("KEEP DIRTY CONTENT\n", encoding="utf-8")
        (dirty / "untracked.txt").write_text("KEEP UNTRACKED CONTENT\n", encoding="utf-8")
        unknown, jobs, unavailable = root / "unknown-folder", root / "jobs", root / "unavailable"
        unknown.mkdir()
        jobs.mkdir()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=jobs,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
        static = root / "static"
        static.mkdir()
        backend = FluxioWebBackend(root, static)
        rows = []
        directories = {"clean": repo, "dirty": dirty, "unknown": unknown, "jobs": jobs,
                       "missing": unavailable, "pinned": repo, "needs": repo, "fresh-failure": repo}
        ids = {}
        from grant_agent.external_chat_inventory import _host
        host_id = _host()["deviceId"]
        for label, folder in directories.items():
            identity = ids[label] = make_session_id("codex", host_id, "fixwave-" + label)
            rows.append(SessionSummary(id=identity, app="codex", title=label, cwd=str(folder),
                updated_at=datetime.now(timezone.utc).isoformat() if label == "fresh-failure" else "2020-01-01T00:00:00Z",
                project=label, status="waiting_input" if label == "needs" else "failed" if label == "fresh-failure" else "idle"))
        broker = ConnectedBroker(root, backend=backend, adapters={"codex": ScratchInventory(rows)}, load_defaults=False, autostart=False)
        _BROKERS[os.path.normcase(str(root.resolve()))] = broker
        service = workspace_for(root, backend)
        service.bus.update("sessions", {ids["pinned"]: {"pinned": True}})
        server = ThreadingHTTPServer(("127.0.0.1", 47964), make_handler(backend))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def request(path, body=None):
            data = None if body is None else json.dumps(body).encode()
            response = opener.open(urllib.request.Request("http://127.0.0.1:47964" + path, data=data,
                headers={"Content-Type": "application/json"}), timeout=30)
            return json.load(response)

        def tool(name, args):
            result = request("/api/ui/tools/call", {"tool": "neyvia." + name, "arguments": args})
            receipt = result.get("data", result)
            return receipt.get("result", receipt)

        try:
            assert request("/api/auth/login", {"username": "fixwave", "password": password})["ok"]
            observed = broker.list_sessions(force=True)["sessions"]
            by_title = {row["title"]: row for row in observed}
            assert by_title["dirty"]["has_uncommitted"] is True
            assert by_title["jobs"]["has_running_jobs"] is True
            assert by_title["unknown"]["project_known"] is False
            assert by_title["clean"]["project_known"] is True
            refusals = {}
            for label in ("dirty", "jobs", "pinned", "needs", "fresh-failure", "missing"):
                result = tool("session.archive", {"id": ids[label]})
                assert result["ok"] is False, (label, result)
                assert not service.bus.get("sessions", {}).get(ids[label], {}).get("archived")
                refusals[label] = result["reason"]
            clean_archived = tool("session.archive", {"id": ids["clean"]})
            assert clean_archived["ok"] and service.bus.get("sessions")[ids["clean"]]["archived"]
            assert tool("session.archive", {"id": ids["clean"], "archived": False})["ok"]
            assert service.bus.get("sessions")[ids["clean"]]["archived"] is False
            preview = tool("sidebar.tidy", {"dryRun": True})
            assert set(preview["candidates"]) == {ids["clean"], ids["unknown"]}, preview
            assert not service.bus.get("sessions", {}).get(ids["unknown"], {}).get("archived")
            summary = tool("sidebar.tidy", {})
            assert summary["status"] == "confirmation_required" and summary["archived"] == []
            confirmed = tool("sidebar.tidy", {"confirmed": True})
            assert set(confirmed["archived"]) == {ids["clean"], ids["unknown"]}
            for label in ("clean", "unknown"):
                assert tool("session.archive", {"id": ids[label], "archived": False})["ok"]
            default = tool("sidebar.policy", {})["policy"]
            assert default["autoArchive"] is False
            enabled = tool("sidebar.policy", {"policy": {**default, "autoArchive": True}})
            assert enabled["ok"]
            assert request("/api/ui/state")["data"]["cleanupPolicy"]["autoArchive"] is True
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not service.bus.get("cleanupAutomaticAt"):
                time.sleep(0.1)
            assert service.bus.get("sessions")[ids["unknown"]]["archived"] is True
            assert service.bus.get("sessions")[ids["clean"]]["archived"] is True
            automatic = service.bus.get("cleanupLastRun")
            assert automatic["archived"] and automatic["protected"]
            assert tool("sidebar.policy", {"policy": default})["ok"]
            assert request("/api/ui/state")["data"]["cleanupPolicy"]["autoArchive"] is False
            assert (dirty / "keeper.txt").read_text() == "KEEP DIRTY CONTENT\n"
            assert (dirty / "untracked.txt").read_text() == "KEEP UNTRACKED CONTENT\n"
            assert child.poll() is None
            receipt = {"item": 5, "status": "passed", "observedAt": datetime.now(timezone.utc).isoformat(),
                "boundary": "Production HTTP login/tools, real git linked worktree and OS subprocess; disposable inventory adapter supplies session metadata only",
                "port": 47964, "refusals": refusals, "observations": [{key: row.get(key) for key in (
                    "id", "title", "cwd", "project_known", "has_uncommitted", "has_running_jobs", "cleanup_safety")}
                    for row in observed], "dryRun": preview,
                "archiveAndRestore": True, "manualSummaryThenConfirmation": summary["status"],
                "confirmedTidy": confirmed, "automaticDefaultOff": True, "automaticTimerArchived": automatic,
                "policyPersistsInBackendSnapshot": True,
                "dirtyAndUntrackedKeepersPreserved": True, "runningJobStillAlive": True,
                "frontendLogicTests": "node --test tests/fixwave-sidebar-cleanup.test.mjs: 3 passed",
                "frontendBuild": "pending", "missing": ["Supported browser surface unavailable; no rendered frontend journey or screenshot."]}
            destination = Path(__file__).resolve().parent / "evidence" / "fixwave-item5.json"
            destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "passed", "receipt": str(destination), "refusals": refusals, "automaticArchived": len(automatic["archived"])}))
        finally:
            service.close()
            broker.close()
            server.shutdown()
            server.server_close()
            child.terminate()
            child.wait(timeout=10)
            gc.collect()  # Release unreferenced sqlite contexts before Windows removes this disposable fixture.


if __name__ == "__main__":
    main()
