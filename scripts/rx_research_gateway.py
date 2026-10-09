"""Prove the research manual through a fresh Neyvia gateway (stdio MCP).

Starts this checkout's MCP bootstrap in a task-local root, loads the
research-assistant manual, runs its journey procedure on public questions and
every tool-gate contract against the byte-identical C10-tools.json. The journey
procedure stops at its support judgement by design; the receipt records the
observer check outcome and the judgement it stopped at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs  # noqa: E402

QUESTIONS = ["Which RFC defines HTTP Semantics?", "In what year did the Berlin Wall fall?", "Who developed the theory of general relativity?"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Fresh task root on a fast local disk")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ports", required=True, help="Caller-assigned ports, e.g. 49041-49045")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
           "NEYVIA_BROWSER_PROOF_PORTS": args.ports}
    started = time.perf_counter()
    process = subprocess.Popen([sys.executable, str(REPO / "src/grant_agent/neyvia_mcp_bootstrap.py"), "--root", str(args.root),
                                "--permission-mode", "workspace"],
                               cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8", **hidden_windows_subprocess_kwargs())
    responses = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                responses.put(json.loads(line))
            except ValueError:
                continue
    threading.Thread(target=read, daemon=True).start()
    sequence = [0]

    def rpc(method, params, timeout=300):
        sequence[0] += 1
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": sequence[0], "method": method, "params": params}) + "\n")
        process.stdin.flush()
        while True:
            message = responses.get(timeout=timeout)
            if message.get("id") == sequence[0]:
                if message.get("error"):
                    raise ValueError(message["error"])
                return message["result"]

    def cl(lines):
        began = time.perf_counter()
        result = rpc("tools/call", {"name": "neyvia.cl", "arguments": {"lines": lines}})
        return result, round((time.perf_counter() - began) * 1000, 1)

    try:
        initialization = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "rx-research-gateway", "version": "1"}})
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        ready_ms = round((time.perf_counter() - started) * 1000, 1)
        manual, manual_ms = cl('help("research-assistant")')
        journeys = []
        stamp = time.strftime("%H%M%S")
        for index, question in enumerate(QUESTIONS):
            request = f"gw-{stamp}-{index}"
            receipt_path = f"research/{request}/receipt.json"
            # An observer goal on the caller-named receipt precedes the effect.
            lines = (f'G: research.receipt(path="{receipt_path}").claimGrounding.accepted == true\n'
                     f"run research-assistant.journey(question={json.dumps(question)}, requestId=\"{request}\")")
            result, ms = cl(lines)
            text = json.dumps(result)
            saved = args.root / receipt_path
            journey = json.loads(saved.read_text(encoding="utf-8")) if saved.is_file() else {}
            journeys.append({"question": question, "requestId": request, "ms": ms, "isError": bool(result.get("isError")),
                             "status": journey.get("status"), "grounded": (journey.get("claimGrounding") or {}).get("accepted"),
                             "citations": len(journey.get("citations", [])), "journeyElapsedMs": journey.get("elapsedMs"),
                             "answer": (journey.get("answer") or {}).get("answer"),
                             "stoppedAtSupportJudgement": "J support" in text or '"support"' in text, "result": result})
        report_path = args.root / "tool-gate" / "receipt.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes((REPO / "scripts/evidence/C10-tools.json").read_bytes())
        authored = json.loads((REPO / "manuals/research-assistant.manual.json").read_text(encoding="utf-8"))
        contracts = []
        for name in authored["chapters"]["tool-gate"]["procedures"]:
            result, ms = cl(f'run research-assistant.{name}(path="tool-gate/receipt.json")')
            contracts.append({"procedure": name, "ok": result.get("structuredContent", {}).get("ok", False), "ms": ms, "result": result})
        receipt = {"schema": "neyvia.rx-research.gateway.v1", "protocolVersion": initialization.get("protocolVersion"),
                   "serverInfo": initialization.get("serverInfo"), "gatewayReadyMs": ready_ms,
                   "manualLoaded": not manual.get("isError"), "manualLoadMs": manual_ms,
                   "journeys": journeys, "reportSha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                   "contracts": len(contracts), "contractsPassed": sum(row["ok"] for row in contracts),
                   "failedContracts": [row["procedure"] for row in contracts if not row["ok"]], "contractRows": contracts,
                   "boundary": "Fresh task-local stdio MCP from this checkout in Workspace permission mode; public web only; extractive answers, no model call"}
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "gateway.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in receipt.items() if k not in {"journeys", "contractRows"}}))
        print(json.dumps([{k: v for k, v in row.items() if k != "result"} for row in journeys]))
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
