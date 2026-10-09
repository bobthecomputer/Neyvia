"""Replay recorded folder health cases against disposable explicit-port REST."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
spec = importlib.util.spec_from_file_location("follow_folder_cases", REPO / "tests/test_folder_sync.py")
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
scratch = REPO / ".agent_control/follow-folder-health"
scratch.mkdir(exist_ok=True)
checks = []
for name in (
    "test_health_cache_expensive_status_and_event_sanitization",
    "test_health_surfaces_real_folder_errors_and_route_split",
    "test_folder_status_soft_degrades_without_faking_health",
    "test_health_returns_structured_unavailable_when_endpoint_down",
):
    server = None
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(dir=scratch, prefix="case-") as directory:
        try:
            if name.endswith("endpoint_down"):
                getattr(cases, name)(Path(directory))
            else:
                server = cases.SyncthingServer(port=48448)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                getattr(cases, name)(Path(directory), server)
                assert all(method == "GET" for method, _ in server.state.requests)
            checks.append({"id": "tests/test_folder_sync.py::" + name, "passed": True,
                           "httpCalls": len(server.state.requests) if server else 1,
                           "ms": round((time.perf_counter() - started) * 1000, 2)})
        finally:
            if server:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
receipt = {
    "boundary": "Production FolderSyncService against disposable HTTP REST on48448, then real refusal after server closes. No sync/activation/write requests, credentials or physical-peer claim.",
    "checks": checks, "port": 48448, "mutatingRequests": 0,
    "unavailableIsStructured": True, "partialFolderFailurePreservesHealthyPeers": True,
    "errorsAndRoutesProjected": True, "physicalPeerProof": False,
}
(REPO / "scripts/evidence/FOLLOW-folder-health.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"passed": len(checks), "httpCalls": sum(row["httpCalls"] for row in checks), "mutatingRequests": 0}))
