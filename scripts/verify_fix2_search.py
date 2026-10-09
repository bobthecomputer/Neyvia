"""Real production local-only search journey; no network/child exemptions."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent import local_network_policy as policy
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_workspace_tools import WorkspaceTools
from grant_agent.neyvia_settings import get, update
from grant_agent.research import search_workspace_detailed


def main():
    root = REPO / ".agent_control" / "fix2-search" / uuid4().hex
    root.mkdir(parents=True)
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
    (root / "patch.txt").write_text("ALPHA\nBETA token-47291\nbeta token-47291\n", encoding="utf-8")
    (root / "binary.txt").write_bytes(b"BETA\x00")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "hidden.txt").write_text("BETA", encoding="utf-8")
    (root / "slow.txt").write_text("a" * 250000 + "!", encoding="utf-8")
    service = WorkspaceTools(root)
    registry = NativeToolRegistry(root)
    initial = get(service)
    changed = update(service, {"localOnly": True}, initial["revision"])
    assert policy.enabled()
    events = []
    watched = False

    def audit(event, args):
        if watched and (event.startswith("socket.") or event in {"subprocess.Popen", "_winapi.CreateProcess", "os.system"}):
            events.append(event)

    sys.addaudithook(audit)
    watched = True
    exact = registry.call("workspace.search", {"query": "token-47291", "includeGlob": "patch.txt", "maxResults": 10})
    regex = registry.call("workspace.search", {"query": r"BETA\s+token-\d+", "includeGlob": "**/*.txt", "maxResults": 10})
    truncated = registry.call("workspace.search", {"query": "BETA", "includeGlob": "patch.txt", "maxResults": 1})
    absent = registry.call("workspace.search", {"query": "absent-73915", "includeGlob": "patch.txt"})
    timeout = registry.call("workspace.search", {"query": "(a+)+$", "includeGlob": "slow.txt"})
    zero_budget = search_workspace_detailed(root, "BETA", time_budget=0)
    watched = False
    assert events == [], events
    assert all(row["ok"] for row in (exact, regex, truncated, absent, timeout))
    assert exact["result"]["engine"] == "python-inprocess"
    assert [(row["path"], row["line"]) for row in exact["result"]["matches"]] == [("patch.txt", 2), ("patch.txt", 3)]
    assert regex["result"]["count"] == 2 and regex["result"]["complete"]
    assert regex["result"]["skipped"]["binary"] == 1
    assert truncated["result"]["count"] == 1 and truncated["result"]["truncated"] and not truncated["result"]["complete"]
    assert absent["result"]["count"] == 0 and absent["result"]["complete"]
    assert timeout["result"]["timedOut"] and not timeout["result"]["complete"]
    assert zero_budget["timedOut"] and not zero_budget["complete"]
    refusals = []
    for label, action in (("external-dns", lambda: socket.getaddrinfo("example.invalid", None)),
                          ("child-process", lambda: subprocess.run([sys.executable, "-c", "raise SystemExit(99)"], check=True))):
        try:
            action()
        except policy.LocalOnlyError as exc:
            refusals.append({"operation": label, "errorType": type(exc).__name__, "message": str(exc)})
        else:
            raise AssertionError(label + " was not refused")
    # Exercise the existing optional-dependency boundary, never weakening policy.
    saved = sys.modules.get("regex")
    sys.modules["regex"] = None
    try:
        no_dependency = registry.call("workspace.search", {"query": "BETA", "includeGlob": "patch.txt"})
        regex_unavailable = registry.call("workspace.search", {"query": "BETA.*", "includeGlob": "patch.txt"})
    finally:
        if saved is None:
            sys.modules.pop("regex", None)
        else:
            sys.modules["regex"] = saved
    assert no_dependency["ok"] and no_dependency["result"]["count"] == 2
    assert not regex_unavailable["ok"] and "optional 'cl' dependency" in regex_unavailable["error"]
    final = get(service)
    assert final["settings"]["localOnly"] is True
    receipt = {"schema": "neyvia.fix2-local-search.v1", "createdAt": datetime.now(timezone.utc).isoformat(),
               "ok": True, "stateRoot": str(root), "settingsBefore": initial, "activation": changed,
               "calls": {"exact": exact, "regex": regex, "truncated": truncated, "absent": absent, "regexTimeout": timeout,
                         "literalWithoutOptionalDependency": no_dependency, "regexWithoutOptionalDependency": regex_unavailable},
               "zeroBudget": zero_budget, "searchNetworkOrChildEvents": events, "refusals": refusals,
               "settingsAfter": final, "limit": "Python backend local-only boundary; Rust/WebView2 enforcement is separately scoped"}
    path = REPO / "scripts/evidence/fix2-search.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    service.close()
    print(json.dumps({"ok": True, "receipt": str(path), "nativeCalls": 7, "searchNetworkOrChildEvents": len(events), "refusals": len(refusals)}))


if __name__ == "__main__":
    main()
