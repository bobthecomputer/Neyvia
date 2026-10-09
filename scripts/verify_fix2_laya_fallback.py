"""Actual service-down decisions before a native page has been captured."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import fix2_scope


def main():
    fix2_scope.install()
    from grant_agent.neyvia_browser import service_for, handle_command
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.proof_credential_guard import install
    results = []
    for endpoint in ("http://127.0.0.1:48684", None):
        if endpoint is None:
            os.environ.pop("NEYVIA_LAYA_URL", None)
        else:
            os.environ["NEYVIA_LAYA_URL"] = endpoint
        root = REPO / ".agent_control/FIX2/laya-fallback" / uuid.uuid4().hex
        root.mkdir(parents=True)
        install(root)
        browser = service_for(root)
        tab = browser.request("tab.open", {"url": "http://127.0.0.1:48685/"}, owner=True)["tabId"]
        assert not browser.projections
        registry = NativeToolRegistry(root)
        count = len(browser.actions)
        native = registry.call("neyvia.browser.decide", {"tabId": tab, "question": "page_done"})
        assert native["ok"] and not native["result"]["available"] and native["result"]["decision"] is None
        backend = handle_command(root, "browser_decide_command", {"tabId": tab, "question": "page_done"}, owner=True)
        assert backend["available"] is False
        assert len(browser.actions) == count and not browser.projections
        unknown = registry.call("neyvia.browser.decide", {"tabId": "not-a-tab", "question": "page_done"})
        assert not unknown["ok"] and "does not exist" in unknown["error"]
        results.append({"endpoint": endpoint, "nativeCall": native, "backendCall": backend,
                        "unknownTabRefused": unknown, "newObservationActions": len(browser.actions) - count})
    report = {"schema": "neyvia.FIX2.laya-fallback.v1", "ok": True, "results": results,
              "boundary": "Real production calls; no captured page, substitute decision, or native observation queued"}
    (REPO / "scripts/evidence/fix2-laya-fallback.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "nativeCalls": 4, "backendCalls": 2, "queuedObservations": 0}))


if __name__ == "__main__":
    main()
