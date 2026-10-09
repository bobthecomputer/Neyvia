"""One bounded real Luna manual/MCP native task, independently checked afterward."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cua_launch import codex_config
from grant_agent.cua_native import NativeWorker
from grant_agent.neyvia_cua_mcp import CuaMCPServer

os.environ["NEYVIA_UI_BACKEND_URL"] = "http://127.0.0.1:48171"
evidence = REPO / "scripts/evidence"
core = json.loads((evidence / "T16.json").read_text())
launch = json.loads((evidence / "T16-build-launch.json").read_text())
root = evidence / ".t16-runtime/luna"
root.mkdir(parents=True, exist_ok=True)
bridge = CuaMCPServer()
bridge._authenticate()
bridge._http("/api/ui/cua", {"op": "control", "args": {"sessionId": core["receipts"]["buildSessionId"], "mode": "agent", "note": "Authorized bounded Luna proof on the disposable native app."}})
manual_path = REPO / "manuals/computer-use.manual.json"
manual = manual_path.read_text(encoding="utf-8")
prior = (evidence / ".t16-runtime/probe/state.result").read_text(encoding="utf-8-sig")
marker = " Luna verified " + format(time.time_ns(), "x")
config = codex_config("t16-proof")
config["mcp_servers.neyvia-cua"]["enabled_tools"] = ["get_window_state", "list_windows", "type_text", "click", "verify_state", "get_session", "preview_log", "preview_show", "preview_note"]
args = [shutil.which("codex"), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--json",
        "-m", "gpt-6-luna", "-s", "danger-full-access", "-C", str(root),
        "-c", 'model_reasoning_effort="low"', "-c", "features.shell_tool=false", "-c", "project_doc_max_bytes=0"]
for key, spec in config.items():
    for field, value in spec.items():
        if field == "env":
            for name, text in value.items():
                args += ["-c", f"{key}.env.{name}=" + json.dumps(text)]
        else:
            args += ["-c", f"{key}.{field}=" + ("true" if value is True else json.dumps(value))]
args.append("-")
prompt = f"""Complete exactly this authorized native UI task using only the neyvia-cua MCP tools. Do not use shell, files, other apps, foreground delivery, or another model.
The PC owner already granted your chat t16-proof/codex session {core['receipts']['buildSessionId']} and real native PID {launch['pid']}, window {launch['window_id']}. Bind by passing session to the first get_window_state. Always pass this exact PID and window_id, never PID 0. Read its accessibility tree with include_screenshot=false, read preview_log to see Paul input, and call preview_show.
Append exactly '{marker}' once to Task input, preserving its existing text, then click Apply. Reobserve and verify the resulting input value with verify_state. Check the output element shows Applied: followed by the exact input value. Do not assume an unverifiable click succeeded. Fresh tokens are required; if stale_element_token is refused, reobserve and retry with the new token. End with a short concrete account of what you observed and verified. Do not end the session.
Here is the actual grounded computer-use manual. The manual's native tools map directly to this MCP: cua.inspect=get_window_state, cua.action=its named tool, cua.verify=verify_state, cua.log=preview_log, pane.show preview=preview_show. The same shared session and safety apply.
{manual}
"""
worker = NativeWorker()
before = worker.request("status")
started = time.monotonic()
try:
    # Bypass npm's cmd shim so TOML quotes reach the installed CLI unchanged.
    if args[0].lower().endswith((".cmd", ".bat")):
        binary = Path(args[0]).parent / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
        if not binary.is_file():
            raise RuntimeError("Installed Windows Codex CLI binary not found")
        args[0] = str(binary)
    result = subprocess.run(args, input=prompt.encode(), capture_output=True, timeout=300,
                            creationflags=subprocess.CREATE_NO_WINDOW, cwd=REPO)
    after = worker.request("status")
finally:
    worker.close()
(root / "stdout.jsonl").write_bytes(result.stdout)
(root / "stderr.txt").write_bytes(result.stderr)
events = []
for line in result.stdout.decode("utf-8", errors="replace").splitlines():
    try:
        events.append(json.loads(line))
    except ValueError:
        pass
tool_events = [event for event in events if (event.get("item") or {}).get("type") == "mcp_tool_call"]
usage = [event.get("usage") for event in events if event.get("type") == "turn.completed"]
final = [event["item"].get("text") for event in events if (event.get("item") or {}).get("type") == "agent_message"]
output = (evidence / ".t16-runtime/probe/state.result").read_text(encoding="utf-8-sig")
passed = result.returncode == 0 and bool(usage) and bool(tool_events) and output == prior + marker
passed = passed and before["foregroundGeneration"] == after["foregroundGeneration"] and before["foregroundWindowId"] == after["foregroundWindowId"] and before["cursor"] == after["cursor"]
receipt = {"passed": passed, "model": "gpt-6-luna", "effort": "low", "exitCode": result.returncode,
           "seconds": round(time.monotonic() - started, 3), "usage": usage, "final": final,
           "manualSha256": hashlib.sha256(manual.encode()).hexdigest(), "actualMcpCalls": tool_events,
           "priorNativeResult": prior, "requestedMarker": marker,
           "independentNativeResult": output, "focusBefore": before, "focusAfter": after,
           "failure": None if passed else result.stderr.decode(errors="replace")[-2000:]}
(evidence / "T16-luna.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps({"passed": passed, "model": receipt["model"], "calls": len(tool_events), "usage": usage, "seconds": receipt["seconds"], "exitCode": result.returncode}))
raise SystemExit(0 if passed else 1)
