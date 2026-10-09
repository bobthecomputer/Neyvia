"""Integrated computer-use journey on Neyvia's private agent desktop.

One run of the real, authenticated backend on an assigned rx port:

1. Paul's grant: the owner allows Character Map for one chat (the preview
   allow-list call, /api/ui/cua op=open). Nothing else is pre-arranged.
2. The agent's task goes through Neyvia's own CL tool surface (neyvia.cl on
   /api/ui/tools/call) as that chat: declare G, run the manual procedure
   cua.open-on-agent-desktop, perceive with cua.windows()/cua.inspect(wN),
   run cua.type-and-verify, perceive again, run cua.click-and-verify (each action
   behind its check), done().
3. Independent verification: a separate process reads the private window with
   Win32 WM_GETTEXT (scripts/rx_cua_readback.py) and confirms the app has no
   window on Paul's input desktop.
4. The agent view's time-lapse for that chat must show the launch, the typing
   and the click, each with an "after" keyframe; the keyframes are saved.
5. Two zero-disturbance guards (the driver's own and an independent one in
   this process) must report no foreground change, no new visible window and
   no injected input on Paul's desktop.

Receipts go to --out (default D:\\NeyviaRuns\\rx-cua\\<UTC stamp>).
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
APP_PATH = "C:/Windows/System32/charmap.exe"
SOURCES = ("src/grant_agent/neyvia_cua.py", "src/grant_agent/cua_guard.py", "src/grant_agent/cua_desktop.py",
           "src/grant_agent/cua_native.py", "src/grant_agent/neyvia_agentview.py", "src/grant_agent/cl/host.py",
           "src/grant_agent/neyvia_cua_mcp.py", "src/grant_agent/cua_launch.py",
           "manuals/cl/computer-use.cl", "manuals/computer-use.manual.json",
           "scripts/rx_cua_readback.py", "scripts/prove_rx_cua_journey.py")
GUARD_KEYS = ("ok", "violations", "foreground_changes", "new_visible_windows", "injected_mouse_events",
              "injected_keyboard_events", "owned_escaped_windows_hidden", "unowned_activity", "slowest_barrier_ms", "elapsed_ms")


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def journey_cl(cl, text, composed, receipt):
    """The task through neyvia.cl, as the chat the owner allowed."""
    if not cl("G: cua.state()['agentDesktop']['guard']['ok'] == True", "goal-desktop-undisturbed")["ok"]:
        raise RuntimeError("Task goal was not admitted")
    launch = cl('run cua.open-on-agent-desktop(path="' + APP_PATH + '")', "open-on-agent-desktop")
    if not launch["ok"]:
        raise RuntimeError("Launch procedure failed")
    ref = None
    for _ in range(40):
        listed = cl("cua.windows()", "perceive-windows")
        match = re.search(r'^E "([^"]+)" "charmap\.exe" (w\d+)$', listed["cl"] or "", re.M)
        if match:
            ref = match.group(2)
            receipt["window"] = {"title": json.loads('"' + match.group(1) + '"'), "ref": ref}
            break
        time.sleep(0.5)
    if not ref:
        raise RuntimeError("No titled Character Map window appeared on the agent desktop")
    seen = cl("cua.inspect(" + ref + ")", "perceive-elements")
    edit = re.search(r'^E "Edit" "([^"]*)" e\d+ value=', seen["cl"] or "", re.M)
    button = re.search(r'^E "Button" "([^"]+)" e\d+ value=', seen["cl"] or "", re.M)
    if not (seen["ok"] and edit and button):
        raise RuntimeError("The window's field and first button were not perceived")
    label, select = json.loads('"' + edit.group(1) + '"'), json.loads('"' + button.group(1) + '"')
    receipt["perceived"] = {"fieldLabel": label, "button": select}
    expect = json.dumps([{"element": {"selector": {"label_contains": label, "role": "Edit"}, "value_equals": composed}}], ensure_ascii=False)
    if not cl("G: cua.verify(expect=" + expect + ", timeout_ms=3000)['status'] == 'satisfied'", "goal-composed-value")["ok"]:
        raise RuntimeError("Composed-value goal was not admitted")
    cl("cua.inspect(" + ref + ")", "reselect-window")
    typed = cl("run cua.type-and-verify(text=" + json.dumps(text) + ", label=" + json.dumps(label, ensure_ascii=False)
               + ", typed=" + json.dumps(text) + ")", "type-and-verify")
    cl("cua.inspect(" + ref + ")", "perceive-after-typing")
    clicked = cl("run cua.click-and-verify(button=" + json.dumps(select, ensure_ascii=False) + ", label="
                 + json.dumps(label, ensure_ascii=False) + ", composed=" + json.dumps(composed) + ")", "click-and-verify")
    finished = cl('done("Composed ' + composed + ' in Character Map on the private agent desktop")', "done")
    receipt["gates"]["launchProcedurePassed"] = launch["ok"] and " ok +G" in (launch["cl"] or "")
    receipt["gates"]["typeProcedurePassed"] = typed["ok"] and " ok +G" in (typed["cl"] or "")
    receipt["gates"]["clickProcedurePassed"] = clicked["ok"] and " ok +G" in (clicked["cl"] or "")
    receipt["gates"]["doneAllGoalsPassed"] = finished["ok"] and (finished["cl"] or "").startswith("R done ok")


def claude_arm(base, chat, text, model, out, receipt):
    """A Claude Code chat gets the task; its only tools are Neyvia's computer-use MCP server."""
    from grant_agent.cl.provider11 import _claude_command
    from grant_agent.cua_launch import server_spec
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    os.environ["NEYVIA_UI_BACKEND_URL"] = base
    spec = server_spec(chat, "claude", "RX computer-use journey")
    if not spec:
        raise RuntimeError("The computer-use MCP server refused this backend URL")
    prompt = ("You are an agent in Neyvia. Paul allowed you to use Character Map in this chat through the neyvia-cua tools. "
              "It runs on Neyvia's private agent desktop, so nothing appears on Paul's screen.\n"
              "Task: launch Character Map (launch_app with path C:\\Windows\\System32\\charmap.exe), put the text \"" + text + "\" "
              "into its 'Characters to copy' field (the interface may be French: 'Caract\u00e8res \u00e0 copier'), then press its Select button "
              "('S\u00e9lectionner') exactly once so the selected character is added. Read the window again to check the result. "
              "Use element tokens from get_window_state, not coordinates. End your reply with one line: FINAL: <the field's value>.")
    command = [*_claude_command(), "-p", "--model", model, "--effort", "low", "--output-format", "stream-json", "--verbose",
               "--no-session-persistence", "--setting-sources=", "--strict-mcp-config", "--no-chrome",
               "--settings", json.dumps({"disableAllHooks": True, "enabledPlugins": {}}),
               "--mcp-config", json.dumps({"mcpServers": {"neyvia-cua": spec}}, ensure_ascii=True),
               "--tools=", "--allowedTools", "mcp__neyvia-cua__*", "--disable-slash-commands",
               "--max-budget-usd", "2"]
    (out / "claude-prompt.txt").write_text(prompt, encoding="utf-8")
    # The proof authority refuses provider processes unless this exact argv is
    # admitted; the provider's saved-credential files stay refused to this process.
    from grant_agent.proof_credential_guard import authorize_provider_transport
    version_command = [*_claude_command(), "--version"]
    admitted = [authorize_provider_transport(ROOT / ".agent_control/proofs/rx-cua", c) for c in (command, version_command)]
    started = time.monotonic()
    with (out / "claude-events.jsonl").open("wb") as events, (out / "claude-stderr.txt").open("wb") as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors, cwd=str(out),
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, **hidden_windows_subprocess_kwargs())
        try:
            process.communicate(prompt.encode("utf-8"), timeout=900)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
    calls, final, cost = [], None, None
    for line in (out / "claude-events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        for block in ((event.get("message") or {}).get("content") or []) if isinstance(event.get("message"), dict) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"tool": block.get("name"), "input": block.get("input")})
        if event.get("type") == "result":
            final, cost = event.get("result"), event.get("total_cost_usd")
    answer = re.findall(r"FINAL:\s*(.+)", final or "")
    receipt["model"] = {"cli": subprocess.run(version_command, capture_output=True, text=True, **hidden_windows_subprocess_kwargs()).stdout.strip(),
                        "providerTransport": admitted,
                        "model": model, "exitCode": process.returncode, "seconds": round(time.monotonic() - started, 1),
                        "costUsd": cost, "toolCalls": calls, "final": (final or "")[-1200:], "reportedValue": answer[-1].strip() if answer else None,
                        "tools": "only mcp__neyvia-cua__* (built-in tools disabled)"}
    receipt["gates"]["modelFinishedTask"] = process.returncode == 0 and bool(answer)
    receipt["gates"]["modelUsedOnlyNeyviaComputerUse"] = bool(calls) and all(str(c["tool"]).startswith("mcp__neyvia-cua__") for c in calls)


def run(port, out, arm="cl", model="sonnet"):
    out.mkdir(parents=True, exist_ok=True)
    workspace = out / "workspace"
    workspace.mkdir()
    for name in ("NEYVIA_COORDINATOR_AUTOSTART", "NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "FLUXIO_RUNTIME_AUTO_UPDATE"):
        os.environ[name] = "0"
    os.environ.update(FLUXIO_WORKSPACE_ROOT=str(workspace), NEYVIA_UI_STATE_ROOT=str(workspace), NEYVIA_PROOF_CREDENTIAL_GUARD="1",
                      SYNTELOS_ACCOUNT_USER="rx-cua-owner", SYNTELOS_ACCOUNT_PASSWORD=secrets.token_urlsafe(40))
    from grant_agent.proof_credential_guard import install
    install(workspace)
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    watcher = ZeroDisturbanceGuard().start()
    from grant_agent.web_backend import FluxioWebBackend, SESSION_COOKIE_NAME, _HandshakeSafeThreadingHTTPServer, make_handler
    token = secrets.token_hex(4)
    text = "RX-CUA " + token
    receipt = {"schema": "neyvia.rx-cua.integrated-journey.v1", "startedAt": datetime.now(timezone.utc).isoformat(),
               "arm": arm, "port": port, "out": str(out), "app": APP_PATH,
               "task": "Open Character Map on the private agent desktop, type '" + text + "' into Characters to copy, "
                       "click Select so it adds the selected character, and verify the field reads '!" + text + "'.",
               "sourceSha256": {name: sha(name) for name in SOURCES}, "calls": [], "gates": {}}
    server = backend = None
    base = "http://127.0.0.1:" + str(port)
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))

    def http(path, data=None, timeout=900):
        request = Request(base + path, data=None if data is None else json.dumps(data).encode(),
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw[:1] in (b"{", b"[") else raw

    def cl(lines, step):
        started = time.perf_counter()
        answer = http("/api/ui/tools/call", {"tool": "neyvia.cl", "arguments": {"lines": lines}})
        data = answer.get("data") or {}
        row = {"step": step, "lines": lines, "ok": bool(data.get("ok")), "status": data.get("status"),
               "ms": round((time.perf_counter() - started) * 1000), "cl": data.get("text") or answer.get("error")}
        receipt["calls"].append(row)
        with (out / "cl-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**row, "response": answer}, ensure_ascii=False) + "\n")
        print(json.dumps({k: row[k] for k in ("step", "ok", "status", "ms")}), flush=True)
        return row

    try:
        backend = FluxioWebBackend(workspace, workspace)
        server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", port), make_handler(backend))
        threading.Thread(target=server.serve_forever, daemon=True, name="rx-cua-http").start()
        if not http("/api/auth/local-session", {}).get("ok"):
            raise RuntimeError("Local owner authentication failed")
        if arm == "cl":
            session = backend.web_auth_sessions.lookup(next(c.value for c in jar if c.name == SESSION_COOKIE_NAME))
            chat, app = "http-owner:" + str(session["sessionId"]), "neyvia"
            receipt["chat"] = {"identity": chat, "boundary": "owner HTTP CL calls act as this chat; cookie never stored"}
        else:
            chat, app = "rx-claude-" + token, "claude"
            receipt["chat"] = {"identity": chat, "boundary": "Claude Code chat with Neyvia's computer-use MCP server (cua_launch.server_spec)"}

        # 1. Paul's grant for this chat (the preview allow-list).
        opened = http("/api/ui/cua", {"op": "open", "args": {"apps": ["charmap"], "chatId": chat, "app": app,
                                                               "title": "RX computer-use journey"}})["data"]
        receipt["grant"] = {"session": opened["id"], "allow": opened["allow"], "status": opened["status"], "control": opened["control"]}
        composed = "!" + text
        if arm == "claude":
            # 2b. A real model receives the task in a Claude Code chat whose only
            # tools are Neyvia's computer-use MCP server (no shell, no files).
            claude_arm(base, chat, text, model, out, receipt)
        else:
            # 2. The agent's task through neyvia.cl.
            journey_cl(cl, text, composed, receipt)

        # 3. Independent readback in a separate process.
        state = http("/api/ui/cua/state")["data"]
        desktop = state["agentDesktop"]["name"]
        session_row = next(s for s in state["sessions"] if s["id"] == opened["id"])
        pids = sorted({w["pid"] for w in session_row.get("windows", []) if w.get("pid")})
        readbacks = []
        for pid in pids:
            done = subprocess.run([sys.executable, str(ROOT / "scripts/rx_cua_readback.py"), "--desktop", desktop, "--pid", str(pid)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=60, creationflags=0x08000000)
            readbacks.append(json.loads(done.stdout) if done.returncode == 0 else {"pid": pid, "error": done.stderr[-800:]})
        receipt["independentReadback"] = readbacks
        fields = [e["text"] for r in readbacks for w in r.get("privateWindows", []) for e in w.get("edits", []) if e["class"] == "RICHEDIT50W"]
        # Select inserts the grid's selected character at the caret: before the
        # text after WM_SETTEXT, after it when the text was typed key by key.
        accepted = [composed] if arm == "cl" else [composed, text + "!"]
        receipt["gates"]["independentReadbackMatches"] = len(fields) == 1 and fields[0] in accepted
        if arm == "claude":
            receipt["gates"]["modelReportMatchesReadback"] = bool(fields) and receipt["model"]["reportedValue"] == fields[0]
        receipt["gates"]["noWindowOnPaulsDesktop"] = bool(readbacks) and all(r.get("windowsOnInputDesktop") == [] for r in readbacks)
        receipt["gates"]["privateDesktop"] = desktop.split("\\")[-1].startswith("Neyvia-C11-")

        # 4. Agent view time-lapse for this chat.
        time.sleep(2.5)  # "after" keyframes are taken shortly after each action
        runs = http("/api/ui/agentview/runs")["data"]["runs"]
        run_row = next(r for r in runs if (r.get("agent") or {}).get("chatId") == chat)
        timeline = http("/api/ui/agentview/timeline?run=" + quote(run_row["key"], safe=""))["data"]
        actions = [e for e in timeline["entries"] if e.get("kind") == "action"]
        frames = out / "timelapse"
        frames.mkdir(exist_ok=True)
        saved = []
        for key in timeline["keyframes"]:
            raw = http("/api/ui/agentview/keyframe?run=" + quote(run_row["key"], safe="") + "&id=" + key["id"])
            path = frames / (key["id"] + "-" + str(key.get("reason")) + ".jpg")
            path.write_bytes(raw)
            saved.append({"id": key["id"], "reason": key.get("reason"), "action": key.get("action"), "file": str(path),
                          "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        receipt["agentView"] = {"run": run_row["key"], "actions": [{k: e.get(k) for k in ("n", "tool", "status", "effect", "say", "element", "kf")} for e in actions],
                                "keyframes": saved, "surfaces": timeline["surfaces"]}
        tools = [e.get("tool") for e in actions]
        with_frames = {e.get("tool") for e in actions if e.get("kf")}
        typing = "type_text" if "type_text" in tools else "set_value"
        receipt["gates"]["timelapseShowsJourney"] = all(t in tools for t in ("launch_app", typing, "click")) and {typing, "click"} <= with_frames
        digest = {k["id"]: k["sha256"] for k in saved}
        after = {e.get("tool"): digest.get(e.get("kf")) for e in actions if e.get("kf")}
        # The click changes the field, so its "after" keyframe must differ from the typing one.
        receipt["gates"]["clickKeyframeShowsNewState"] = bool(after.get("click")) and after.get("click") != after.get(typing)

        # 5. The driver's own guard as the service saw it.
        receipt["driverGuard"] = {k: state["agentDesktop"]["guard"].get(k) for k in GUARD_KEYS}
        http("/api/ui/cua", {"op": "end", "args": {"sessionId": opened["id"]}})
    except Exception as exc:
        receipt["error"] = type(exc).__name__ + ": " + str(exc)[:600]
        receipt["trace"] = traceback.format_exc()[-3000:]
    finally:
        from grant_agent.neyvia_cua import _SERVICES
        for service in list(_SERVICES.values()):
            service.shutdown()
        if server:
            server.shutdown()
            server.server_close()
        guard = watcher.close()
        receipt["independentGuard"] = {k: guard.get(k) for k in GUARD_KEYS}

        def quiet(g):
            return bool(g) and g.get("ok") is True and all(g.get(k, 0) == 0 for k in (
                "foreground_changes", "new_visible_windows", "injected_mouse_events", "injected_keyboard_events", "owned_escaped_windows_hidden"))
        receipt["gates"]["zeroDisturbanceIndependentGuard"] = quiet(receipt["independentGuard"])
        receipt["gates"]["zeroDisturbanceDriverGuard"] = quiet(receipt.get("driverGuard"))
        receipt["finishedAt"] = datetime.now(timezone.utc).isoformat()
        receipt["ok"] = "error" not in receipt and bool(receipt["gates"]) and all(receipt["gates"].values())
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": receipt["ok"], "gates": receipt["gates"], "error": receipt.get("error"), "receipt": str(out / "receipt.json")}))
    return receipt["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int, choices=range(48871, 48890))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--arm", choices=("cl", "claude"), default="cl",
                        help="cl: the task through neyvia.cl; claude: a Claude Code chat gets the task with only Neyvia's computer-use MCP")
    parser.add_argument("--model", default="sonnet")
    args = parser.parse_args()
    out = args.out or Path(r"D:\NeyviaRuns\rx-cua") / (args.arm + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    raise SystemExit(0 if run(args.port, out, args.arm, args.model) else 2)
