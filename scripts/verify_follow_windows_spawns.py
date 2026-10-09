"""Prove real scoped child operations and explicit hidden flags on Windows."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]
import verify_follow_failures as fixtures
fixtures.SCRATCH = REPO / ".agent_control/follow-windows-spawns"
fixtures.isolate()
from grant_agent import research
from grant_agent import neyvia_panes

spec = importlib.util.spec_from_file_location("follow_windows_case", REPO / "tests/test_windows_hidden_subprocesses.py")
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
cases.test_every_product_spawn_passes_a_hidden_window_argument()

recorded = []
with fixtures.real_http() as (backend, request):
    original_init = subprocess.Popen.__init__
    def popen_init(process, args, *positional, **kwargs):
        recorded.append({"program": Path(str(args[0])).name, "creationflags": kwargs.get("creationflags", 0)})
        return original_init(process, args, *positional, **kwargs)
    with mock.patch.object(subprocess.Popen, "__init__", popen_init):
        root = backend.root
        (root / "needle.txt").write_text("FOLLOW_SEARCH_NEEDLE\n", encoding="utf-8")
        assert request("/api/auth/local-session", {})["http"] == 200
        searched = request("/api/backend", {"command": "call_native_tool_command", "payload": {"tool": "workspace.search", "arguments": {"query": "FOLLOW_SEARCH_NEEDLE"}}})
        assert searched["http"] == 200 and "FOLLOW_SEARCH_NEEDLE" in json.dumps(searched["body"])
        # Exercise the file-path worker too, where package-relative imports differ.
        with mock.patch.object(research.shutil, "which", return_value=None):
            fallback = research.search_workspace_detailed(root, "FOLLOW_SEARCH_NEEDLE", time_budget=5)
        assert fallback["matches"] and not fallback["timedOut"]
        git = neyvia_panes._git(root, "rev-parse", "--is-inside-work-tree")
        assert git.returncode in {0, 128}
        asset = root / "empty.gltf"
        asset.write_text(json.dumps({"asset": {"version": "2.0"}, "scenes": [{"nodes": []}], "scene": 0}), encoding="utf-8")
        validated = request("/api/backend", {"command": "gamedev_asset_validate_command", "payload": {"path": str(asset)}})
        assert validated["http"] == 200
        assert "numErrors" in json.dumps(validated["body"])
assert recorded
if os.name == "nt":
    assert all(row["creationflags"] & 0x08000000 for row in recorded)
receipt = {"boundary": "Actual authenticatedHTTP48449 native search and GameDev asset-validator, real bounded file-path Python regex worker and Git pane helper on disposable root. Allactual childcalls recorded with WindowsCREATE_NO_WINDOW. No onboardingdownload/networkcheck invoked.",
           "id": "tests/test_windows_hidden_subprocesses.py::test_every_product_spawn_passes_a_hidden_window_argument",
           "passed": True, "httpPort": 48449, "httpChecks": 3, "childCalls": recorded,
           "sourceScannerFindings": [], "fallbackWorkerReturned": True, "ownedServerStopped": True}
(REPO / "scripts/evidence/FOLLOW-windows-spawns.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"passed": True, "httpChecks": 3, "actualHiddenChildren": len(recorded)}))
