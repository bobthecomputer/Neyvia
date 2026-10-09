"""Exercise authoritative browser revision contracts through real native calls."""
from __future__ import annotations
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    root = REPO / ".agent_control/FIX2/browser" / uuid.uuid4().hex
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONDONTWRITEBYTECODE="1")
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.neyvia_browser import service_for, BrowserService
    from grant_agent.proof_contracts import before_action, after_action, ContractViolation
    registry = NativeToolRegistry(root)
    calls = []

    def call(name, args=None):
        receipt = registry.call(name, args or {})
        calls.append(receipt)
        assert receipt["ok"], receipt.get("error")
        return receipt["result"]

    first = call("neyvia.browser.state")
    assert type(first["revision"]) is int
    service = service_for(root)
    service.request("profile.create", {"name": "FIX2 local proof"}, owner=True)
    after = call("neyvia.browser.state")
    assert after["revision"] == first["revision"] + 1
    restored = BrowserService(root).request("state")
    assert restored["revision"] == after["revision"]
    after_action(before_action("neyvia.browser.state", {}), restored)
    refused = []
    for revision in (str(after["revision"]), -1, True):
        try:
            after_action(before_action("neyvia.browser.state", {}), {**after, "revision": revision})
        except ContractViolation as error:
            refused.append(str(error))
        else:
            raise AssertionError("Invalid workspace revision accepted")
    # Page revisions remain strings: do not weaken the action freshness token.
    after_action(before_action("neyvia.browser.observe", {"tabId": "projection-contract"}),
                 {"ok": True, "revision": "page-17"})
    try:
        after_action(before_action("neyvia.browser.observe", {"tabId": "projection-contract"}),
                     {"ok": True, "revision": 17})
    except ContractViolation as error:
        refused.append(str(error))
    else:
        raise AssertionError("Integer page revision accepted")
    report = {"schema": "neyvia.FIX2.browser.v1", "ok": True, "calls": calls,
              "persistedRevision": restored["revision"], "invalidContractsRefused": refused,
              "boundary": "Real native browser-state tools and persisted state; no native page action claimed"}
    destination = REPO / "scripts/evidence/fix2-browser.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "realCalls": len(calls), "refusals": len(refused)}))


if __name__ == "__main__":
    main()
