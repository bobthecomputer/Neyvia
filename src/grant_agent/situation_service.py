"""Keep the browser on one owner thread across HTTP requests and SDK tool calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from pathlib import Path
import hashlib
import uuid


class SituationService:
    def __init__(self, root):
        self.root = root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="neyvia-situation")
        self.server = None
        self.gate = Lock()

    def _call(self, verb, work_id, arguments, may_change):
        if self.server is None:
            from .neyvia_mcp import NeyviaMCPServer
            from .ui_tools import UiToolSurface
            self.server = NeyviaMCPServer(self.root)
            # This adapter owns its attachment; HTTP worker threads never touch it.
            self.server.ui_tools = UiToolSurface(workspace_root=self.root)
        return self.server.situations.call(verb, work_id, arguments, may_change=may_change)

    def call(self, verb, work_id, arguments, *, may_change=False):
        if not self.gate.acquire(blocking=False):
            raise RuntimeError("Browser observation is busy; wait for the active request")
        try:
            # Do not timeout an effect then report that it never ran. The existing
            # browser calls bound navigation and actions; their receipt survives.
            return self.executor.submit(self._call,verb,work_id,arguments,may_change).result()
        finally:
            self.gate.release()

    def run_app_factory_journey(self, *, job_id, url, session_cookie_name,
                                session_token, source_digest, template):
        """Run the local starter's saved journey in an isolated authenticated page."""
        if not self.gate.acquire(blocking=False):
            raise RuntimeError("Browser observation is busy; wait for the active request")
        try:
            return self.executor.submit(
                self._run_app_factory_journey, job_id, url, session_cookie_name,
                session_token, source_digest, template,
            ).result()
        finally:
            self.gate.release()

    def _run_app_factory_journey(self, job_id, url, session_cookie_name,
                                 session_token, source_digest, template):
        from .situation_interface import SituationStore
        if self.server is None:
            from .neyvia_mcp import NeyviaMCPServer
            from .ui_tools import UiToolSurface
            self.server = NeyviaMCPServer(self.root)
            self.server.ui_tools = UiToolSurface(workspace_root=self.root)
        self.server._approved_browser_url(url)
        if template not in {"checklist", "notes"}:
            raise ValueError("The built-in browser journey supports checklist and notes starters only")
        work_id = "app-factory:" + job_id
        store = SituationStore(self.root, work_id)
        run_id = uuid.uuid4().hex
        test_value = "Neyvia journey " + run_id[:12]
        noun = "Note" if template == "notes" else "Item"
        verb = "Save note" if template == "notes" else "Add item"
        steps = [
            {"target": {"role": "textbox", "name": noun}, "action": "fill",
             "args": {"value": test_value},
             "assertions": [{"kind": "text_contains", "text": test_value, "contains": True}]},
            {"target": {"role": "button", "name": verb}, "action": "click",
             "args": {}, "assertions": [{"kind": "added", "role": "checkbox",
                                         "name": "Mark " + test_value + " complete", "equals": 1}]},
        ]
        acceptance = [{"kind": "text_contains", "text": test_value, "contains": True}]
        browser = self.server.ui_tools.observer.browser_runtime
        with browser.page(width=1280, height=900) as page:
            page.context.add_cookies([{"name": session_cookie_name,
                                       "value": session_token, "url": url,
                                       "httpOnly": True, "sameSite": "Lax"}])
            self.server.ui_tools.attached_page = page
            self.server.situations.page_identity = None
            try:
                state = store._read()
                store.define(
                    "Add an item, verify persistence, remove it, and verify removal after reload.",
                    ["Only the selected local App Factory preview may be changed."],
                    ["A new list item appears.", "Its text remains after reload.",
                     "Removal persists after a second reload."],
                    expected_revision=state["revision"], source="operator:app-factory-test",
                )
                self.server.situations.call("observe", work_id, {"url": url}, may_change=True)
                self.server.situations.call("journey", work_id, {
                    "operation": "save", "journeyId": "starter-add-and-reload-v1",
                    "steps": steps, "acceptance": acceptance,
                    "sourceDigest": source_digest,
                }, may_change=True)
                run = self.server.situations.call("journey", work_id, {
                    "operation": "replay", "journeyId": "starter-add-and-reload-v1",
                    "runId": run_id, "sourceDigest": source_digest,
                    "reload": True, "reloadAssertions": acceptance,
                }, may_change=True)
                proof_dir = Path(self.root) / ".agent_control" / "app_factory_tests" / job_id
                proof_dir.mkdir(parents=True, exist_ok=True)
                screenshot = proof_dir / (run_id + ".png")
                pixels = page.screenshot(path=str(screenshot), full_page=True)
                cleanup = {}
                cleanup_screenshot = None
                cleanup_hash = ""
                if run.get("accepted") is True:
                    absent = [
                        {"kind": "count", "role": "checkbox",
                         "name": "Mark " + test_value + " complete", "equals": 0},
                        {"kind": "text_contains", "text": test_value, "contains": False},
                    ]
                    self.server.situations.call("journey", work_id, {
                        "operation": "save", "journeyId": "starter-remove-and-reload-v1",
                        "steps": [{"target": {"role": "button", "name": "Remove"},
                                   "action": "click", "args": {},
                                   "assertions": [{"kind": "removed", "role": "checkbox",
                                                   "name": "Mark " + test_value + " complete", "equals": 1}]}],
                        "acceptance": absent, "sourceDigest": source_digest,
                    }, may_change=True)
                    cleanup = self.server.situations.call("journey", work_id, {
                        "operation": "replay", "journeyId": "starter-remove-and-reload-v1",
                        "runId": run_id + "-remove", "sourceDigest": source_digest,
                        "reload": True, "reloadAssertions": absent,
                    }, may_change=True)
                    cleanup_screenshot = proof_dir / (run_id + "-removed.png")
                    cleanup_pixels = page.screenshot(path=str(cleanup_screenshot), full_page=True)
                    cleanup_hash = hashlib.sha256(cleanup_pixels).hexdigest()
                return {"run": run, "cleanupRun": cleanup, "sourceSha256": source_digest,
                        "screenshotPath": str(screenshot),
                        "screenshotSha256": hashlib.sha256(pixels).hexdigest(),
                        "cleanupScreenshotPath": str(cleanup_screenshot) if cleanup_screenshot else "",
                        "cleanupScreenshotSha256": cleanup_hash}
            finally:
                self.server.ui_tools.attached_page = None
                self.server.situations.page_identity = None

    def close(self):
        with self.gate:
            if self.server is not None:
                self.executor.submit(self.server.ui_tools.close).result()
            self.executor.shutdown(wait=True)
