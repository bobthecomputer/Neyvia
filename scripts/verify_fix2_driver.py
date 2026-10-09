"""Real pinned Windows driver discovery, native call and readiness failures."""
from __future__ import annotations
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    root = REPO / ".agent_control/FIX2/driver" / uuid.uuid4().hex
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONDONTWRITEBYTECODE="1")
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.cua_upstream import runtime_status, UpstreamDriver, UPSTREAM_TOOLS
    from grant_agent.neyvia_cua import service_for
    from grant_agent.native_tools import NativeToolRegistry
    registry = NativeToolRegistry(root)
    state = registry.call("neyvia.cua.state", {})
    assert state["ok"], state.get("error")
    assert state["result"]["driver"]["available"]
    service = service_for(root)
    try:
        names = sorted(row["name"] for row in service.upstream.list_tools())
        assert set(names) == UPSTREAM_TOOLS
        screen = service.driver({"tool": "get_screen_size", "arguments": {}})
        assert not screen.get("isError"), screen
        native = screen.get("structuredContent")
        if native is None:
            native = json.loads(next(row["text"] for row in screen["content"] if row["type"] == "text"))
        assert native, screen
        # Compile and query the same checkout-local UIA background worker.
        assembly = service.native.assembly()
        status = service.native.request("status")
        assert "foregroundWindowId" in status and "cursor" in status
        # Retain only presence, not the operator's HWND/cursor position.
        local_worker = {"assembly": str(assembly), "sha256": hashlib.sha256(assembly.read_bytes()).hexdigest(),
                        "statusReturned": True}
    finally:
        service.shutdown()
    missing = runtime_status(root / "missing-runtime")
    assert not missing["available"] and "install_cua_driver.py" in missing["detail"] and "install_cua_driver" not in missing["reason"]
    corrupt_directory = root / "corrupt-runtime"
    corrupt_directory.mkdir()
    (corrupt_directory / "cua-driver.exe").write_bytes(b"FIX2 deliberate invalid executable fixture")
    corrupt = runtime_status(corrupt_directory)
    assert not corrupt["available"] and "hash mismatch" in corrupt["detail"] and corrupt["code"] == "hash_mismatch"
    report = {"schema": "neyvia.FIX2.driver.v1", "ok": True, "stateCall": state,
              "discoveredTools": names, "nativeScreenCall": screen, "localWorker": local_worker,
              "missingRuntime": missing, "corruptRuntime": corrupt, "downloaded": False,
              "boundary": "Pinned stdio runtime and local native worker readiness; no takeover/remote task claimed"}
    (REPO / "scripts/evidence/fix2-driver.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "tools": len(names), "nativeCall": "get_screen_size", "workerReady": True}))


if __name__ == "__main__":
    main()
