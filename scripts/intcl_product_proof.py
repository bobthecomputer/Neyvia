"""Real Luna calls through the product CLI transport and its completion receipts."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import socket
from pathlib import Path
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


async def prove(port: int, model: str, backend_root: Path) -> int:
    from grant_agent.neyvia_agent import NeyviaAgentConfig, run_neyvia_agent
    from grant_agent.neyvia_intent_plan import publish_plan
    from grant_agent.ui_command_bus import bus_for

    root = REPO / ".agent_control/INTCL/product-live" / uuid.uuid4().hex
    # Native notes intentionally forward to the connected UI. Bind the same
    # canonical control root and configure its folder through the real owner API.
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(backend_root)
    notes = root / "notes"
    notes.mkdir(parents=True)
    note = notes / "proof.md"
    note.write_bytes(b"Original\n")
    spec = importlib.util.spec_from_file_location("intcl_product_plugin", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend = module.Backend(f"http://127.0.0.1:{port}")
    selected = backend.request("/api/ui/tools/call", {"tool": "neyvia.notes.folder", "arguments": {"folder": str(notes)}})
    if selected.get("data", {}).get("result", {}).get("folder") != str(notes):
        raise RuntimeError("Canonical backend did not select the disposable proof notes folder")
    instructions = root / "instructions.txt"
    instructions.write_text(
        "You are testing Neyvia's CL 1.1 product completion boundary. Discover the actual Neyvia CL tool "
        "in functions.exec via ALL_TOOLS.filter(x => /neyvia.*cl/.test(x.name)); call the matching tools[name] "
        "with {lines: 'notes.read(path=\"proof.md\")'} as a single JSON argument. CL statements are strings "
        "submitted to that tool, never JavaScript functions. Use the Neyvia MCP CL tool only, "
        "with notes.read, notes.write, notes.pin, run notes.write-and-pin, and done(). "
        "All state and task files are inside your assigned working directory. Never read credentials, "
        "the NAS runbook, or files outside this directory; never use shell tools or contact other local ports. "
        "Host-authorized observer goals decide task completion. Preserve the exact requested note bytes. "
        "A refusal is evidence, not permission to bypass the host.\n", encoding="utf-8")
    receipts = {}
    for name, goal, prompt, writable in (
        ("refused", 'notes.read(path="proof.md").body == "Never written\\n"',
         'This is the deliberate refusal case. Read proof.md using the CL tool, then try done("test"). '
         'You have read-only access and must leave the note unchanged. Return a short final reply even if '
         'done refuses. The outer product receipt must remain unfinished.', False),
        ("completed", 'notes.read(path="proof.md").body == "Accepted\\n" and notes.read(path="proof.md").pinned == True',
         'Save exactly "Accepted\\n" into proof.md and pin it using CL run notes.write-and-pin '
         '(replace_note="replace"). Read the procedure signature if necessary. Finish only after '
         'explicit done("saved and pinned") passes the authored observer goal. Use only the Neyvia CL MCP tool.', True),
    ):
        prompt += (' Discover the exposed CL gateway with functions.exec: '
                   'const matches = ALL_TOOLS.filter(x => /neyvia.*cl/.test(x.name)); '
                   'text(matches); then call the matching tools entry with {lines: "<CL statements>"}. '
                   'Use the actual tool metadata if its normalized name differs. Do not invoke done as JavaScript, '
                   'or use shell tools. You must actually submit done through the CL gateway even in the refusal case.')
        session = "intcl-product-" + name + "-" + uuid.uuid4().hex[:12]
        publish_plan(root, {"sessionId": session, "plan": [{"step": name, "status": "pending", "doneWhen": goal}]})
        config = NeyviaAgentConfig(root=root, control_root=backend_root, session_id=session, model=model,
            transport="codex-cli", reasoning_effort="low", enable_specialists=False,
            instructions_file=instructions, timeout_seconds=600, max_turns=12,
            allow_mutations=writable,
            native_mutation_tools=("neyvia.notes.write", "neyvia.notes.pin") if writable else ())
        print("Starting product " + name + " with " + model, flush=True)
        try:
            receipt = await run_neyvia_agent(config, prompt)
        except Exception as exc:
            receipt = {"status": "failed", "error": str(exc)}
        receipts[name] = receipt
        if name == "refused":
            receipts["refusedBytesPreserved"] = note.read_bytes() == b"Original\n"
        print(json.dumps({"case": name, "status": receipt["status"]}), flush=True)
    pin_file = notes / ".neyvia-notes.json"
    pins = json.loads(pin_file.read_text(encoding="utf-8")) if pin_file.is_file() else {}
    checks = {
        "refused_product_not_completed": receipts["refused"]["status"] == "incomplete",
        "refused_host_goal_recorded": receipts["refused"].get("clCompletion", {}).get("doneStatus") == "refused",
        "refused_note_bytes_preserved": receipts["refusedBytesPreserved"],
        "accepted_product_completed": receipts["completed"]["status"] == "completed",
        "accepted_explicit_host_done": receipts["completed"].get("clCompletion", {}).get("doneStatus") == "ok",
        "accepted_note_exact_bytes": note.read_bytes() == b"Accepted\n",
        "accepted_note_pinned": "proof.md" in pins.get("pinned", []),
    }
    result = {"schema": "neyvia.intcl.product-live.v1", "model": model,
              "port": port, "root": str(root), "allPassed": all(checks.values()),
              "checks": checks, "receipts": receipts}
    destination = REPO / "scripts/evidence/intcl/product-live.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"allPassed": result["allPassed"], "checks": checks}), flush=True)
    return int(not result["allPassed"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--backend-root", type=Path, default=REPO / ".agent_control/INTCL/runtime")
    args = parser.parse_args()
    if args.port not in range(48521, 48530):
        parser.error("only assigned INTCL ports")
    os.environ.update(NEYVIA_UI_BACKEND_URL=f"http://127.0.0.1:{args.port}",
                      FLUXIO_WEB_BACKEND_URL=f"http://127.0.0.1:{args.port}",
                      NEYVIA_TOOL_AUTO_UPDATE="0", NEYVIA_COORDINATOR_AUTOSTART="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", PYTHONNOUSERSITE="1")
    backend_root = args.backend_root.resolve()
    if not backend_root.is_relative_to(REPO):
        parser.error("canonical backend root must stay within this worktree")
    if os.name == "nt":
        # Windows asyncio's wakeup pair uses a listener. Keep even that
        # disposable fixture inside the task's explicitly assigned ports.
        from intcl_socketpair import explicit_socketpair
        socket.socketpair = explicit_socketpair
    return asyncio.run(prove(args.port, args.model, backend_root))


if __name__ == "__main__":
    raise SystemExit(main())
