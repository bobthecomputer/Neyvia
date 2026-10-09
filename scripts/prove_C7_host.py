"""Exercise the registered C7 bot tools and executable manual, plus stale receipts."""
import json
import hashlib
import os
import sys
import uuid
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.port not in range(48741, 48750):
        parser.error("C7b permits ports 48741-48749 only")
    output = args.output.resolve()
    output.relative_to(REPO / "scripts/evidence")
    root = REPO / ".agent_control/proofs/c7-host" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "APPDATA", "LOCALAPPDATA"):
        folder = root / "home" / key.lower()
        folder.mkdir(parents=True)
        os.environ[key] = str(folder)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT"):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_NAS_ROOT=str(root), NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", PYTHONPATH=str(REPO / "src"))
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(root)
    prepare_broker_fixture(root)
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    from grant_agent.neyvia_manuals import unwrap
    server = CompactNeyviaMCPServer(root, read_only=True, session_id="c7-host")
    calls = []

    def rpc(tool, arguments):
        answer = server.handle({"jsonrpc": "2.0", "id": len(calls) + 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
        if answer.get("error"):
            raise ValueError(answer["error"]["message"])
        result = unwrap(answer["result"]["structuredContent"])
        calls.append({"tool": tool, "arguments": arguments, "result": result})
        if result.get("ok") is False:
            raise ValueError("Host tool refused: " + tool + " " + str(result.get("error", result.get("status"))))
        return result

    empty = rpc("neyvia.verify.edges.status", {})
    if empty.get("available"):
        raise ValueError("Fresh host reported a previous campaign")
    validated = rpc("neyvia.manual.validate", {"id": "edge-contracts"})
    procedure = rpc("neyvia.manual.run", {"id": "edge-contracts", "chapter": "campaign", "procedure": "verify-local-edges", "inputs": {"port": args.port}})
    if procedure.get("status") != "completed" or len(procedure["checks"]) != 2 or not all(row["passed"] for row in procedure["checks"]):
        raise ValueError("Manual did not complete both fresh observers")
    status = rpc("neyvia.verify.edges.status", {})
    if not status["sourceCurrent"] or not status["receiptIntact"] or status["complete"]:
        raise ValueError("Expected passing, source-current, partial semantic campaign")
    latest_path = root / ".agent_control/c7/latest.json"
    original = latest_path.read_bytes()
    value = json.loads(original)
    value["sourceBindings"]["src/grant_agent/edge_contracts.py"] = "0" * 64
    latest_path.write_text(json.dumps(value), encoding="utf-8")
    stale = server._gateway().call_native("neyvia.verify.edges.status", {})
    stale = stale.get("result", stale)
    if stale.get("ok") is not False or stale.get("sourceCurrent") is not False:
        raise ValueError("Changed source binding failed to invalidate the receipt")
    latest_path.write_bytes(original)
    value = json.loads(original)
    value["receiptSha256"] = "0" * 64
    latest_path.write_text(json.dumps(value), encoding="utf-8")
    corrupt = server._gateway().call_native("neyvia.verify.edges.status", {})
    corrupt = corrupt.get("result", corrupt)
    if corrupt.get("ok") is not False or corrupt.get("receiptIntact") is not False:
        raise ValueError("Corrupt receipt hash was accepted")
    latest_path.write_bytes(original)
    report = {"schema": "neyvia.c7-host.v1", "ok": True, "transport": "actual CompactNeyviaMCPServer JSON-RPC tools/call in owned read-only session",
              "root": str(root), "calls": calls, "manualChecks": procedure["checks"], "staleBindingRefused": stale,
              "corruptReceiptRefused": corrupt, "registeredCommands": ["neyvia.verify.edges", "neyvia.verify.edges.status"],
              "registration": ["neyvia_manuals.DEFINITIONS", "neyvia_workspace_tools.tool_specs and dispatch", "NativeToolRegistry", "MCP progressive native gateway", "manuals/cl/edge-contracts.cl"],
              "desktop": "No new desktop IPC command; CLI and existing bot/manual interfaces own this verification capability"}
    host_path = output.with_name(output.stem + "-host.json")
    host_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    campaign = json.loads(Path(status["receipt"]).read_text(encoding="utf-8"))
    campaign["hostProof"] = {"path": host_path.relative_to(REPO).as_posix(), "sha256": hashlib.sha256(host_path.read_bytes()).hexdigest(),
                             "manualCompleted": True, "freshChecks": 2, "staleBindingRefused": True, "corruptReceiptRefused": True}
    campaign["baselines"] = {name: hashlib.sha256((REPO / "scripts/evidence" / name).read_bytes()).hexdigest()
                             for name in ("C7-schema-before.json", "C7-notes-before.json", "C7-workspace-before.json")}
    output.write_text(json.dumps(campaign, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "manualCompleted": True, "checks": 2, "staleBindingRefused": True, "corruptReceiptRefused": True}))


if __name__ == "__main__":
    main()
