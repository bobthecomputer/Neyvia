"""Release browser gate on the admitted Obscura engine (track rx-browser).

Ports are explicitly assigned by RX_BROWSER_PORTS in the integrator's
48871-48889 range: backend, engine, fixture and hidden renderer in that order.
Never 47881, never Chrome/Edge/WebView2, no window.
Large outputs stay in D:/NeyviaRuns/rx-browser.

  python scripts/rx_browser_gate.py backend           start the hidden task-owned backend
  python scripts/rx_browser_gate.py frozen36 [ids]    36 frozen public tasks, Obscura only
  python scripts/rx_browser_gate.py handoff           CAPTCHA owner hand-off in the side pane
  python scripts/rx_browser_gate.py stop              stop the backend and its engine

The hand-off never solves anything: the agent pauses on the wall, the owner clears a
controlled loopback fixture and selects Resume task in Neyvia's right pane.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("RX_BROWSER_OUTPUT", r"D:\NeyviaRuns\rx-browser"))
PORTS = os.environ.get("RX_BROWSER_PORTS", "")
sys.path.insert(0, str(REPO / "src"))
from grant_agent.browser_ports import parse_ports
assigned_ports = sorted(parse_ports(PORTS)) if PORTS else []
if len(assigned_ports) < 4 or not set(assigned_ports) <= set(range(48871, 48890)):
    raise ValueError("RX_BROWSER_PORTS must explicitly assign at least four ports within 48871-48889")
BACKEND, ENGINE, FIXTURE, RENDERER = assigned_ports[:4]
BASE = f"http://127.0.0.1:{BACKEND}"
# The UI build (D:/NeyviaRuns/INTN/build-library-handoff, copied unchanged) is served from the NVMe:
# from the USB disk the owner shell often stayed blank while its assets crawled in at ~200 KB/s.
# Backend state is small but fsync-heavy; on the D: USB disk one sign-in took 26 s, so the
# runtime root sits on the local NVMe. Receipts, runs and screenshots stay under OUT on D:.
RUNTIME = Path(os.environ.get("RX_BROWSER_RUNTIME", str(Path.home() / ".rx-browser-runtime")))
STATIC = Path(os.environ.get("RX_BROWSER_UI", str(RUNTIME / "ui")))
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(REPO / "src"))


def admitted_engine():
    """The engine managed_executable() resolves from the C2h admission; RX_DRY_RUN_OBSCURA only
    rehearses the harness and its receipts then record a non-admitted binary hash."""
    from grant_agent.browser_obscura import managed_executable
    return Path(os.environ["RX_DRY_RUN_OBSCURA"]) if os.environ.get("RX_DRY_RUN_OBSCURA") else managed_executable()


def adapter():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rx_neyvia_mcp", REPO / "plugins/neyvia/mcp/neyvia_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Server(module.Backend(BASE))


def browser(server, op, **args):
    result = server.backend.request("/api/ui/browser", {"op": op, "args": args})
    if result.get("ok") is False:
        raise RuntimeError(f"{op}: {result.get('error')}")
    return result


def start_backend():
    OUT.mkdir(parents=True, exist_ok=True)
    engine = admitted_engine()
    env = {**os.environ, "NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0",
           "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_LAYA_AUTOSTART": "0",
           "NEYVIA_BROWSER_PROOF_PORTS": PORTS, "NEYVIA_BROWSER_UI_ORIGIN": BASE,
           "NEYVIA_OBSCURA_EXE": str(engine)}
    with (OUT / "backend.stdout.log").open("ab") as stdout, (OUT / "backend.stderr.log").open("ab") as stderr:
        child = subprocess.Popen([sys.executable, str(REPO / "scripts/run_web_backend.py"), "--host", "127.0.0.1",
                                  "--port", str(BACKEND), "--root", str(RUNTIME), "--static-root", str(STATIC),
                                  "--skip-runtime-auto-update", "--skip-proof-self-check"],
                                 cwd=REPO, env=env, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=HIDDEN)
    (OUT / "backend.pid").write_text(str(child.pid), encoding="ascii")
    for _ in range(60):
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=2):
                break
        except urllib.error.HTTPError:
            break
        except OSError:
            if child.poll() is not None:
                raise SystemExit("Backend exited; see " + str(OUT / "backend.stderr.log"))
            time.sleep(1)
    else:
        child.terminate()
        child.wait(timeout=10)
        raise RuntimeError("Owned backend did not become healthy within 60 seconds")
    print(json.dumps({"pid": child.pid, "port": BACKEND, "engine": str(engine), "static": str(STATIC)}))


def stop_backend():
    pid = (OUT / "backend.pid").read_text(encoding="ascii").strip()
    subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=HIDDEN)
    print(json.dumps({"stopped": int(pid)}))


def ensure_headless(server, public):
    state = browser(server, "state")
    runtime = state.get("headless") or state.get("runtime", {}).get("headless") or {}
    if runtime.get("connected"):
        browser(server, "headless.stop")
    return browser(server, "headless.start", port=ENGINE, assignedPorts=PORTS, requestTimeoutMs=60000,
                   allowLocalFixtures=True, allowPublicResources=public)


def verify_admission():
    """Run only the authored connected-engine identity and no-stealth contract."""
    server = adapter()
    manual = server.call("cl", {"lines": 'help("browser")'})
    started = ensure_headless(server, public=False)
    try:
        result = server.call("cl", {"lines": "run browser.verify-admitted-engine()"})
        receipt = {"manual": manual, "engine": started, "contract": result,
                   "ports": PORTS, "ok": not manual.get("isError") and not result.get("isError")}
        (OUT / "admission.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt["ok"], "receipt": str(OUT / "admission.json")}))
        if not receipt["ok"]:
            raise RuntimeError("Admitted browser CL contract failed")
    finally:
        browser(server, "headless.stop")


def frozen36(task_ids):
    server = adapter()
    status = ensure_headless(server, public=True)
    run_dir = OUT / "frozen36"
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / time.strftime("run-%H%M%S.json")
    args = ["node", "scripts/c2f_replay.cjs", str(BACKEND), str(out), "1", "--cascade", "--obscura-only",
            "--profile=RX frozen36 obscura-only"]
    if task_ids:
        args.append("--task-ids=" + task_ids)
    with (run_dir / "replay.log").open("ab") as log:
        code = subprocess.run(args, cwd=REPO, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=HIDDEN).returncode
    print(json.dumps({"exit": code, "run": str(out), "engineSha256": status.get("binarySha256")}))


class Wall(BaseHTTPRequestHandler):
    cleared = False

    def do_GET(self):
        title, body = (("RX task result", "Ready: RX task result") if Wall.cleared else
                       ("RX human-check fixture", "CAPTCHA fixture: verify you are human. Only the owner can clear this controlled page."))
        payload = ("<!doctype html><html><title>" + title + "</title><body style=\"font:24px system-ui;background:#f5f5ef;padding:40px\"><h1>"
                   + title + "</h1><p>" + body + "</p><button onclick=\"location.reload()\">Refresh owner page</button></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


def handoff():
    from grant_agent.browser_obscura import ObscuraEngine
    folder = OUT / "handoff"
    folder.mkdir(parents=True, exist_ok=True)
    receipt = {"schema": "neyvia.rx-browser.owner-handoff@1", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "ports": {"backend": BACKEND, "agentEngine": ENGINE, "fixture": FIXTURE, "renderer": RENDERER},
               "policy": {"captchaSolved": False, "stealth": False, "visibleWindows": 0, "chromeOrEdge": False},
               "steps": []}
    step = lambda name, **values: receipt["steps"].append({"step": name, "at": round(time.time(), 3), **values})

    def save():
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    wall = ThreadingHTTPServer(("127.0.0.1", FIXTURE), Wall)
    threading.Thread(target=wall.serve_forever, daemon=True).start()
    server = adapter()
    renderer = None
    try:
        status = ensure_headless(server, public=False)
        for old in browser(server, "state")["tabs"]:  # one controlled tab: earlier rehearsals must not linger
            browser(server, "tab.close", tabId=old["id"])
        receipt["agentEngine"] = {k: status.get(k) for k in ("engine", "binarySha256", "stealth", "port", "automationUserAgent")}
        tab = browser(server, "tab.open", url=f"http://127.0.0.1:{FIXTURE}/", engine="obscura")["tabId"]
        browser(server, "tab.grant", tabId=tab, enabled=True)
        observed = browser(server, "observe", tabId=tab)
        step("agent-observed-wall", tabId=tab, title=observed.get("title"))

        renderer = ObscuraEngine(RUNTIME / time.strftime("owner-renderer-%H%M%S"), str(admitted_engine()), port=RENDERER, fixtures=True,
                                 assigned_ports=PORTS, color_scheme="dark", reduced_motion="reduce", request_timeout_ms=60000)
        receipt["ownerRenderer"] = {"engine": "obscura", "sha256": renderer.engine_sha256, "hidden": True}
        renderer.run("owner", "open", "shell", BASE + "/control")

        def view():
            return renderer.run("owner", "observe", "shell")

        def wait_text(text, seconds=45):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                value = view()
                if text in value.get("text", ""):
                    return value
                time.sleep(0.5)
            (folder / "owner-view-missing.json").write_text(json.dumps({"wanted": text, "url": value.get("url"), "title": value.get("title"),
                "text": value.get("text", "")[:6000], "controls": [e.get("name") for e in value.get("elements", [])][:80]}, indent=2), encoding="utf-8")
            try:
                shot("owner-view-missing")
            except Exception:
                pass
            raise RuntimeError("Owner view never showed: " + text)

        def shot(name):
            frame = renderer.run("owner", "frame", "shell")
            path = folder / (name + ".png")
            path.write_bytes(base64.b64decode(frame["dataUrl"].split(",", 1)[1]))
            return str(path)

        def click(name):
            value = view()
            targets = [e for e in value["elements"] if e.get("name") == name and e.get("enabled") is not False]
            if len(targets) != 1:
                raise RuntimeError(f"Expected one owner control named {name!r}, saw {len(targets)}")
            result = renderer.run("owner", "action", "shell", {"revision": value["revision"], "element": targets[0]["id"], "action": "click"})
            if not result.get("ok"):
                raise RuntimeError("Owner click unconfirmed: " + name)
            return result

        def cl(lines):
            box = {}
            # Each contract gets its own authenticated conversation so an earlier G cannot constrain it.
            worker = threading.Thread(target=lambda: box.update(result=adapter().call("tools_call", {"tool": "neyvia.cl", "arguments": {"lines": lines}})))
            worker.start()
            while worker.is_alive():  # keep the owner's page processing pane events while CL waits
                view()
                worker.join(0.5)
            text = "\n".join(b["text"] for b in box["result"].get("content", []) if b.get("type") == "text")
            return box["result"], text

        admitted = json.loads((REPO / "scripts/evidence/C2h-engine-admission.json").read_text(encoding="utf-8"))["engineBinary"]["sha256"]
        result, text = cl(f'G: browser.state().headless.binarySha256 == "{admitted}" and browser.state().headless.stealth == False\n'
                          "run browser.verify-admitted-engine()\ndone()")
        (folder / "cl-admitted-engine.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        step("cl-verify-admitted-engine", isError=bool(result.get("isError")), tail=text[-400:])
        if result.get("isError"):
            raise RuntimeError("The connected agent engine is not the admitted C2h build")
        try:
            wait_text("Bus live", 60)
        except RuntimeError:
            # An app shell that stayed blank is reloaded once by the owner; the receipt keeps it.
            step("owner-reloaded-blank-shell")
            renderer.run("owner", "navigate", "shell", BASE + "/control")
        wait_text("Bus live", 90)  # pane requests travel over the UI bus (WebSocket in the admitted engine)
        if any(e.get("name") == "Skip setup" for e in view().get("elements", [])):
            click("Skip setup")  # a fresh owner profile opens first-run setup
            step("owner-skipped-first-run-setup")
        wait_text("What would you like", 90)
        settle = time.monotonic() + 8  # let the shell finish subscribing to pane events on the live bus
        while time.monotonic() < settle:
            view()
            time.sleep(0.5)
        step("owner-ui-ready", screenshot=shot("owner-ui-ready"))
        save()

        requirements = json.dumps(["Read the ready result"])
        checks = json.dumps([{"path": "/text", "contains": "Ready: RX task result"}])
        result, text = cl('G: pane.observe().visible == True\n'
                          f'run browser.request-checked-owner-handoff(tabId="{tab}",goal="Read RX task result",'
                          f'requirements={requirements},checks={checks})\ndone()')
        (folder / "cl-handoff.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        step("cl-request-checked-owner-handoff", isError=bool(result.get("isError")), tail=text[-600:])
        save()
        if result.get("isError"):
            raise RuntimeError("Hand-off contract failed; see cl-handoff.json")
        wait_text("This task needs your help")
        paused = next(t for t in browser(server, "state")["tabs"] if t["id"] == tab)
        step("owner-pane-paused", screenshot=shot("owner-pause"), ownerTask=paused.get("ownerTask"), agentGranted=paused.get("agentGranted"))

        click("Resume task")
        wait_text("The page still needs your help")
        still = next(t for t in browser(server, "state")["tabs"] if t["id"] == tab)
        step("uncleared-resume-refused", screenshot=shot("owner-uncleared-refused"), ownerTask=still.get("ownerTask"),
             agentGranted=still.get("agentGranted"))
        if (still.get("ownerTask") or {}).get("status") != "needs_owner" or still.get("agentGranted"):
            raise RuntimeError("An uncleared wall must stay needs_owner with agent control revoked")

        Wall.cleared = True  # the owner's own action on the controlled page, outside the agent
        step("owner-cleared-wall", by="owner (controlled loopback fixture)", solver=None)
        click("Refresh owner page")
        wait_text("Ready: RX task result")
        step("owner-refreshed-page", screenshot=shot("owner-cleared"))
        click("Resume task")
        wait_text("An agent is working in this tab")
        step("owner-resumed", screenshot=shot("owner-resumed"))

        resumed = json.dumps({"contains": {"type": "object", "required": ["id", "ownerTask", "agentGranted"], "properties": {
            "id": {"const": tab}, "agentGranted": {"const": True},
            "ownerTask": {"type": "object", "required": ["status"], "properties": {"status": {"const": "done"}}}}}}).replace("true", "True")
        result, text = cl(f"G: matches(browser.state()['tabs'], {resumed})\n"
                          f'run browser.verify-owner-resumed(tabId="{tab}")\ndone()')
        (folder / "cl-resumed.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        step("cl-verify-owner-resumed", isError=bool(result.get("isError")), tail=text[-600:])
        if result.get("isError"):
            raise RuntimeError("Resume contract failed; see cl-resumed.json")
        duplicate = server.backend.request("/api/ui/browser", {"op": "task.resume", "args": {"taskId": paused["ownerTask"]["taskId"]}})
        step("duplicate-resume", ok=duplicate.get("ok"), error=duplicate.get("error"))
        if duplicate.get("ok") is not False:
            raise RuntimeError("A second resume must refuse")
        receipt["passed"] = True
    except BaseException as error:
        receipt["passed"] = False
        receipt["error"] = repr(error)[:2000]
        raise
    finally:
        save()
        if renderer:
            renderer.close()
        wall.shutdown()
        print(json.dumps({"passed": receipt.get("passed"), "receipt": str(folder / "receipt.json")}))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "backend":
        start_backend()
    elif command == "stop":
        stop_backend()
    elif command == "frozen36":
        frozen36(sys.argv[2] if len(sys.argv) > 2 else "")
    elif command == "handoff":
        handoff()
    elif command == "admission":
        verify_admission()
    else:
        raise SystemExit(__doc__)
