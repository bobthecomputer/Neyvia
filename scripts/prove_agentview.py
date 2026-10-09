"""Agent view, real journey: agents work on their own surfaces, Paul watches and steers.

Against the isolated backend (scripts/run_web_backend.py on --base, ports 48901-48909):

1. Codex tests an app it built (Invoice Builder, compiled here) on the private agent
   desktop through the C11 driver, via the same MCP bridge real agents use.
2. Claude Code uses a normal Windows app (Character Map) on the agent desktop.
3. Claude Code checks a web checkout page in Obscura (local staging fixture).
4. Neyvia's own UI renders in Neyvia's Obscura engine (no Chrome/Edge, no window):
   Agents at work, the live view with the action overlay, a comment clicked onto the
   live frame, the agent reading it on its next step and changing course, the
   time-lapse with "while you were away" and what progressed, the browser run, and the
   narrow side-panel layout. Screenshots land in docs/evidence/agentview/.

The window guard log (plans/logs/window-guard.jsonl) must be unchanged at the end.

Setup (once per run): stop any previous proof backend, remove .neyvia/agentview, write
.neyvia/dictation.json {"enabled": false} (the shell would otherwise start the dictation engine,
whose spawn trips the zero-disturbance guard), then start the backend with
scripts/agentview/start_backend.ps1 (hidden console, so console children never show a window).
The PC must be unlocked: the driver's guard refuses to act when it can't observe the input desktop.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import http.server
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
EVIDENCE = ROOT / "docs/evidence/agentview"
ATTEMPT = EVIDENCE / "attempt"  # a run writes here; only a passing run replaces the published evidence
GUARD_LOG = Path("C:/Users/user/Projects/plans/logs/window-guard.jsonl")
OBSCURA = os.environ.get("NEYVIA_OBSCURA_EXE", "C:/Users/user/Projects/nx-c13-taste/scripts/evidence/c13-runtime/obscura-v0.2.4/obscura.exe")
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


def now():
    return datetime.now(timezone.utc).isoformat()


def guard_state():
    raw = GUARD_LOG.read_bytes() if GUARD_LOG.exists() else b""
    return {"sha256": hashlib.sha256(raw).hexdigest(), "lines": raw.count(b"\n"), "bytes": len(raw)}


class Backend:
    """The owner's HTTP session on the isolated backend."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.jar))
        self.post("/api/auth/local-session", {})

    def request(self, path, body=None, timeout=140):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, headers={"Content-Type": "application/json", "Origin": self.base})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:  # urllib HTTPError carries the backend's JSON
            body = getattr(exc, "read", lambda: b"")()
            raise RuntimeError(f"{path}: {exc} {body[:400]!r}") from exc

    def post(self, path, body):
        return self.request(path, body)

    def get(self, path):
        return self.request(path)

    def cua(self, op, args):
        answer = self.post("/api/ui/cua", {"op": op, "args": args})
        if not answer.get("ok"):
            raise RuntimeError(f"cua {op}: {answer.get('error')}")
        return answer["data"]

    def browser(self, op, args, agent=None):
        body = {"op": op, "args": args}
        if agent:
            body["_agent"] = agent
        answer = self.post("/api/ui/browser", body)
        if answer.get("ok") is False:
            raise RuntimeError(f"browser {op}: {answer.get('error')}")
        return answer

    def agentview(self, path):
        answer = self.get("/api/ui/agentview/" + path)
        return answer["data"]

    def cookies(self):
        return [{"name": c.name, "value": c.value, "domain": "127.0.0.1", "path": "/", "httpOnly": True, "sameSite": "Lax"} for c in self.jar]


class Agent:
    """A scripted agent speaking the real MCP bridge (cua-driver tool shape) to the PC service."""

    def __init__(self, base, chat, app, title, session):
        from grant_agent.neyvia_cua_mcp import CuaMCPServer
        # The bridge only admits the production ports; the proof backend runs on 489xx.
        self.bridge = CuaMCPServer("http://127.0.0.1:48171")
        self.bridge.url = base.rstrip("/")
        self.bridge.client = {"chatId": chat, "app": app, "title": title}
        self.bridge.session_id = session
        self.n = 0
        self.heard = []
        self.calls = []
        self.call_raw("initialize", None)

    def call_raw(self, method, params):
        self.n += 1
        answer = self.bridge.handle({"jsonrpc": "2.0", "id": f"{self.bridge.client['chatId']}-{self.n}", "method": method, "params": params or {}})
        if "error" in answer:
            raise RuntimeError(f"{method}: {answer['error']}")
        return answer["result"]

    def tool(self, name, arguments, *, allow_error=False):
        result = self.call_raw("tools/call", {"name": name, "arguments": arguments})
        texts = [b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"]
        heard = [t for t in texts if t.startswith("Paul did since your last call")]
        self.heard += heard
        self.calls.append({"tool": name, "at": now(), "isError": result.get("isError"), "heardPaul": bool(heard),
                           "effect": (result.get("structuredContent") or {}).get("effect")})
        if result.get("isError") and not allow_error:
            raise RuntimeError(f"{name} refused: {texts[:1]}")
        return result

    def state(self, window_id):
        # Observation is read-only: like any MCP client, retry a busy provider lane a few times.
        for attempt in range(5):
            try:
                value = self.tool("get_window_state", {"window_id": window_id, "include_screenshot": True})
                return value.get("structuredContent") or {}
            except RuntimeError as exc:
                if "503" not in str(exc) or attempt == 4:
                    raise
                self.retries = getattr(self, "retries", 0) + 1
                time.sleep(0.4)

    def element(self, window_id, label=None, role=None, pick=None):
        # A busy provider can answer with a visual-only projection; look again until the native controls show.
        deadline = time.monotonic() + 25
        while True:
            elements = self.state(window_id).get("elements", [])
            found = [e for e in elements if (label is None or e.get("label") == label) and (role is None or e.get("role") == role)]
            if pick:
                found = [e for e in found if pick(e)]
            if found:
                return found[0]
            if time.monotonic() > deadline:
                raise RuntimeError(f"No element {label!r}/{role!r}: {[ (e.get('role'), e.get('label')) for e in elements][:40]}")
            self.relooks = getattr(self, "relooks", 0) + 1
            time.sleep(0.6)

    def set_field(self, window_id, label, value):
        element = self.element(window_id, label, "Edit")
        return self.tool("set_value", {"window_id": window_id, "element_token": element["element_token"], "value": value})

    def click(self, window_id, label, role="Button"):
        element = self.element(window_id, label, role)
        return self.tool("click", {"window_id": window_id, "element_token": element["element_token"]})


def compile_invoice(folder):
    exe = folder / "InvoiceProbe.exe"
    framework = CSC.parent
    subprocess.run([str(CSC), "/nologo", "/target:winexe", "/out:" + str(exe), str(ROOT / "scripts/agentview/InvoiceProbe.cs"),
                    "/reference:" + str(framework / "System.Windows.Forms.dll"), "/reference:" + str(framework / "System.Drawing.dll")],
                   check=True, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    return exe


def wait_file(path, seconds=15):
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for " + str(path))
        time.sleep(0.05)
    return path.read_text(encoding="utf-8")


def serve_shop(port):
    page = (ROOT / "scripts/agentview/shop.html").read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---- the UI, rendered by Neyvia's Obscura engine ------------------------------------------

class Ui:
    def __init__(self, backend, port, width=1480, height=920):
        token = secrets.token_urlsafe(27)
        self.log = (ATTEMPT / "obscura-ui.log").open("ab")
        self.child = subprocess.Popen([OBSCURA, "serve", "--host", "127.0.0.1", "--port", str(port), "--user-agent", "NeyviaAgent/1.0 (agent view proof; Obscura)",
                                       "--max-connections", "8", "--allow-private-network"], stdout=self.log, stderr=self.log,
                                      creationflags=subprocess.CREATE_NO_WINDOW,
                                      env={**os.environ, "OBSCURA_CDP_TOKEN": token, "OBSCURA_ROTATE_PROFILE": "0", "OBSCURA_NAV_TIMEOUT_MS": "20000", "OBSCURA_SCRIPT_DEADLINE_MS": "15000"})
        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with build_opener(ProxyHandler({})).open(Request(endpoint + "/json/version", headers={"Authorization": "Bearer " + token}), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(endpoint, headers={"Authorization": "Bearer " + token})
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        self.context.add_cookies(backend.cookies())
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)[:300]))
        self.base = backend.base
        self.size(width, height)

    def size(self, width, height):
        try:
            self.page.set_viewport_size({"width": width, "height": height})
        except Exception:
            pass

    def goto(self, query=""):
        self.page.goto(self.base + "/control" + query, wait_until="load", timeout=40000)
        self.page.wait_for_timeout(2500)
        hide = self.page.locator("button[aria-label='Hide sidebar']")
        if hide.count():
            hide.first.click()  # more room for the agent's screen, as Paul would
            self.page.wait_for_timeout(600)

    def emit(self, action, payload):
        from grant_agent.ui_command_bus import bus_for
        bus_for(ROOT).emit(action, payload)

    def wait(self, selector, timeout=20000):
        self.page.wait_for_selector(selector, timeout=timeout)

    def shot(self, name):
        path = ATTEMPT / name
        self.page.screenshot(path=str(path))
        return "docs/evidence/agentview/" + name

    def close(self):
        for step in (self.browser.close, self.pw.stop):
            try:
                step()
            except Exception:
                pass
        self.child.terminate()
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.child.kill()
        self.log.close()


def open_agents(ui):
    """Ctrl+Space, "Agents at work", Enter: the way Paul opens it."""
    for attempt in range(4):
        ui.page.mouse.click(700, 60)
        ui.page.keyboard.press("Control+Space")
        try:
            ui.page.wait_for_selector(".nx-launcher input", timeout=3000)
        except Exception:
            ui.page.wait_for_timeout(1500)
            continue
        box = ui.page.locator(".nx-launcher input").first
        box.fill("Agents at work")
        ui.page.wait_for_timeout(700)
        ui.page.keyboard.press("Enter")
        try:
            ui.page.wait_for_selector(".nx-av-all", timeout=8000)
            ui.page.wait_for_timeout(2500)
            return
        except Exception:
            ui.page.keyboard.press("Escape")
    raise RuntimeError("Agents at work did not open from the launcher")


def open_run(ui, title):
    """From Agents at work, open one run by clicking its card."""
    if not ui.page.locator(".nx-av-all").count():
        open_agents(ui)
    card = ui.page.locator(".nx-av-card-open", has_text=title).first
    card.wait_for(timeout=20000)
    card.click()
    ui.wait(".nx-av-live .nx-av-frame, .nx-av-lapse .nx-av-frame", 30000)
    ui.page.wait_for_timeout(1500)


def click_frame(ui, fx, fy):
    """Click the live frame at fractional coordinates, as Paul would."""
    box = ui.page.locator(".nx-av-live .nx-av-frame").first.bounding_box()
    x, y = box["x"] + box["width"] * fx, box["y"] + box["height"] * fy
    ui.page.mouse.click(x, y)
    ui.page.wait_for_timeout(400)
    if not ui.page.locator(".nx-av-composer").count():
        # Fall back to the exact pointer event the frame listens for.
        ui.page.evaluate("""([x, y]) => { const el = document.querySelector('.nx-av-live .nx-av-frame');
            el.dispatchEvent(new PointerEvent('pointerdown', {clientX: x, clientY: y, button: 0, bubbles: true})); }""", [x, y])
        ui.page.wait_for_timeout(400)
    ui.wait(".nx-av-composer textarea", 5000)


def write_comment(ui, text):
    area = ui.page.locator(".nx-av-composer textarea").first
    area.click()
    area.fill(text)
    ui.page.wait_for_timeout(300)


def send_comment(ui):
    ui.page.locator(".nx-av-composer button[type=submit]").first.click()
    ui.wait(".nx-av-sent", 10000)


def run(args):
    import shutil
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(ATTEMPT, ignore_errors=True)
    ATTEMPT.mkdir()
    receipt = {"schema": "neyvia.agentview.proof.v1", "at": now(), "base": args.base, "ok": False, "guardBefore": guard_state(), "steps": [], "shots": {}}
    note = lambda message, **data: receipt["steps"].append({"at": now(), "text": message, **data}) or print(message, flush=True)
    backend = Backend(args.base)
    ui = shop = None
    cua_sessions = []
    launched_pids = []
    tab_id = None
    try:
        # ---- 1. Codex builds and tests Invoice Builder on the agent desktop -------------------
        token = uuid.uuid4().hex
        folder = ROOT / ".agent_control/agentview" / token
        folder.mkdir(parents=True)
        exe = compile_invoice(folder)
        state = folder / "window.txt"
        invoice_chat = "agentview-invoice-" + token[:6]
        session = backend.cua("open", {"apps": [str(exe)], "chatId": invoice_chat, "app": "codex", "title": "Test the invoice app"})
        cua_sessions.append(session["id"])
        codex = Agent(args.base, invoice_chat, "codex", "Test the invoice app", session["id"])
        launch = codex.tool("launch_app", {"path": str(exe), "args": [str(state)], "disposable_target": {"path": str(folder), "token": token}})
        note("Codex launched Invoice Builder on the agent desktop", launch=launch.get("structuredContent"))
        launched_pids.append((launch.get("structuredContent") or {}).get("pid"))
        wid = int(wait_file(state))
        receipt["invoice"] = {"windowId": wid, "exe": str(exe.relative_to(ROOT)), "desktop": (launch.get("structuredContent") or {}).get("desktop")}
        codex.set_field(wid, "Quantity", "3")
        codex.set_field(wid, "Unit price", "12.50")
        time.sleep(1.2)
        codex.set_field(wid, "VAT rate", "20")
        codex.click(wid, "Compute total")
        first_total = wait_file(Path(str(state) + ".result"))
        note("Codex computed a first total", total=first_total)
        receipt["invoice"]["firstTotal"] = first_total

        # ---- 2. Claude Code uses Character Map on the agent desktop ---------------------------
        if not args.skip_charmap:
            try:
                charmap_chat = "agentview-charmap-" + token[:6]
                exe_map = "C:/Windows/System32/charmap.exe"
                cm = backend.cua("open", {"apps": [exe_map], "chatId": charmap_chat, "app": "claude", "title": "Collect symbols for the release notes"})
                cua_sessions.append(cm["id"])
                claude = Agent(args.base, charmap_chat, "claude", "Collect symbols for the release notes", cm["id"])
                launched = claude.tool("launch_app", {"path": exe_map}, allow_error=True)
                content = launched.get("structuredContent") or {}
                note("Character Map launch", launch=content)
                launched_pids.append(content.get("pid"))
                if content.get("launched") or content.get("effect") == "launched":
                    deadline = time.monotonic() + 12
                    window = None
                    while not window and time.monotonic() < deadline:
                        rows = (claude.tool("list_windows", {}).get("structuredContent") or {}).get("windows", [])
                        main = [w for w in rows if "charmap" in str(w.get("process", "")).lower() and w.get("title")
                                and (w.get("bounds") or {}).get("width", 0) > 200]
                        window = max(main, key=lambda w: w["bounds"]["width"] * w["bounds"]["height"]) if main else None
                        time.sleep(0.4)
                    if window:
                        cw = int(window["window_id"])
                        edit = claude.element(cw, role="Edit")
                        claude.tool("type_text", {"window_id": cw, "element_token": edit["element_token"], "text": "Neyvia 1.0 "})
                        time.sleep(0.8)
                        edit = claude.element(cw, role="Edit")
                        claude.tool("type_text", {"window_id": cw, "element_token": edit["element_token"], "text": "-> ok"})
                        receipt["charmap"] = {"windowId": cw, "typed": True}
                        note("Claude Code typed into Character Map's Characters to copy")
                        claude.tool("preview_note", {"text": "Symbols collected; done with Character Map."})
                    else:
                        receipt["charmap"] = {"windowId": None, "reason": "no window listed"}
                    # Done: the agent ends its session; its run stays as a time-lapse.
                    claude.tool("end_session", {}, allow_error=True)
                else:
                    receipt["charmap"] = {"refused": content}
            except Exception as exc:  # recorded, not hidden: the invoice run is the required desktop proof
                receipt["charmap"] = {"error": str(exc)[:400]}
                note("Character Map step failed: " + str(exc)[:200])

        # ---- 3. Claude Code checks a checkout page in Obscura ----------------------------------
        shop = serve_shop(args.shop_port)
        shop_agent = {"app": "claude", "chatId": "agentview-shop-" + token[:6], "title": "Check the checkout page"}
        backend.browser("headless.start", {"port": args.engine_port, "allowLocalFixtures": True})
        opened = backend.browser("tab.open", {"url": f"http://127.0.0.1:{args.shop_port}/", "engine": "obscura"}, shop_agent)
        tab_id = opened["tab"]["id"]
        time.sleep(1.0)

        def browse(op, extra=None):
            return backend.browser(op, {"tabId": tab_id, **(extra or {})}, shop_agent)

        def act(label, action, value=None):
            seen = browse("observe")
            element = next(e for e in seen["elements"] if label.lower() in str(e.get("name", "")).lower() and action in e.get("actions", []))
            answer = browse("action", {"revision": seen["revision"], "element": element["id"], "action": action, **({"value": value} if value is not None else {})})
            time.sleep(0.9)
            return answer

        act("Full name", "fill", "Ada Lovelace")
        act("Quantity", "fill", "2")
        act("Update total", "click")
        page_text = browse("observe")["text"]
        receipt["shop"] = {"tabId": tab_id, "firstText": re.findall(r"Total\s*[\d.]+|Updated[^\n]*", page_text)}
        note("Claude Code filled the checkout and updated the total", text=receipt["shop"]["firstText"])

        # ---- 4. Paul watches in Neyvia (rendered in Obscura) -----------------------------------
        try:  # the first-run setup sheet would cover the shell in this fresh browser profile
            backend.post("/api/backend", {"command": "onboarding_save_command", "payload": {"dismissed": True}})
        except RuntimeError as exc:
            note("Onboarding dismissal failed: " + str(exc)[:200])
        ui = Ui(backend, args.ui_port)
        ui.goto()
        ui.page.wait_for_timeout(3000)
        open_agents(ui)
        ui.wait(".nx-av-card", 30000)
        ui.page.wait_for_timeout(4500)
        receipt["shots"]["overview"] = ui.shot("01-agents-at-work.png")

        invoice_key = "codex:" + invoice_chat
        open_run(ui, "Test the invoice app")
        # Codex keeps working while Paul watches: the focus outline and the words follow it.
        codex.set_field(wid, "Quantity", "3")
        ui.page.wait_for_timeout(700)
        receipt["shots"]["live"] = ui.shot("02-live-view-action-overlay.png")

        # Paul spots a wrong VAT rate and clicks the total on the live frame.
        # Paul clicks the VAT rate field on the picture (located from the app's own controls).
        vat = codex.element(wid, "VAT rate", "Edit")
        win = next((w for w in codex.tool("list_windows", {}).get("structuredContent", {}).get("windows", []) if int(w["window_id"]) == wid), None)
        box, origin = vat.get("frame") or {}, (win or {}).get("bounds") or {"x": 80, "y": 80, "width": 560, "height": 420}
        fx = (box.get("x", 270) + box.get("width", 260) * 0.35 - origin["x"]) / origin["width"]
        fy = (box.get("y", 291) + box.get("height", 28) / 2 - origin["y"]) / origin["height"]
        click_frame(ui, fx, fy)
        write_comment(ui, "VAT for this customer is 5.5%, not 20%. Fix the rate and recompute.")
        receipt["shots"]["composer"] = ui.shot("03-comment-on-the-live-frame.png")
        send_comment(ui)
        ui.page.wait_for_timeout(800)
        receipt["shots"]["sent"] = ui.shot("04-comment-sent-waiting-for-agent.png")
        runs = backend.agentview("runs")["runs"]
        fb = next(r for r in runs if r["key"] == invoice_key)["feedback"][-1]
        receipt["feedback"] = {k: fb.get(k) for k in ("id", "text", "surface", "v", "keyframe", "action", "point", "anchor", "delivery", "message")}
        note("Paul's comment was bound and queued", feedback=receipt["feedback"])

        # Codex's next step reads it (the computer-use shared log) and changes course.
        before = len(codex.heard)
        state_now = codex.state(wid)
        heard = codex.heard[before:]
        if not heard:
            raise RuntimeError("Codex's next driver call did not carry Paul's comment")
        rate = re.search(r"(\d+(?:[.,]\d+)?)\s*%", heard[0])
        receipt["agentHeard"] = {"text": heard[0][:600], "rateParsed": rate.group(1) if rate else None}
        note("Codex read Paul's comment on its next step", heard=heard[0][:300])
        codex.tool("preview_note", {"text": "Paul says VAT is 5.5% here; fixing the rate and recomputing."})
        codex.set_field(wid, "VAT rate", (rate.group(1) if rate else "5.5").replace(",", "."))
        time.sleep(0.6)
        Path(str(state) + ".result").unlink(missing_ok=True)
        codex.click(wid, "Compute total")
        second_total = wait_file(Path(str(state) + ".result"))
        receipt["invoice"]["secondTotal"] = second_total
        note("Codex recomputed after Paul's comment", total=second_total)
        ui.page.wait_for_timeout(2500)
        receipt["shots"]["after"] = ui.shot("05-agent-changed-course-comment-read.png")
        runs = backend.agentview("runs")["runs"]
        receipt["feedbackAfter"] = next(r for r in runs if r["key"] == invoice_key)["feedback"][-1]["delivery"]
        # Codex is done testing: it ends its computer-use session; the run stays as a time-lapse.
        codex.tool("preview_note", {"text": "Invoice total verified at 39.56 EUR with 5.5% VAT. Done."})
        codex.tool("end_session", {}, allow_error=True)
        receipt["agentDesktopGuardAfterDesktopWork"] = backend.agentview("runs").get("agentDesktop")

        # ---- 5. Time-lapse: Paul comes back later -----------------------------------------------
        timeline = backend.agentview("timeline?run=" + invoice_key)
        start_t = timeline["entries"][0]["t"]
        # Paul last looked at this run when it started (his browser remembers that per run), then left.
        ui.goto()
        ui.page.evaluate("""([key, t]) => localStorage.setItem('nx.agentview.seen.' + key, JSON.stringify(t))""", [invoice_key, start_t + 0.5])
        open_run(ui, "Test the invoice app")
        ui.wait(".nx-av-away", 15000)
        receipt["shots"]["away"] = ui.shot("06-while-you-were-away.png")
        ui.page.locator(".nx-av-away button.nx-btn-primary").click()
        ui.wait(".nx-av-lapse .nx-av-frame img", 20000)
        ui.page.wait_for_timeout(450)
        pause = ui.page.locator(".nx-av-transport button[aria-label='Pause']")
        if pause.count():
            pause.first.click()  # hold the replay mid-way, where Paul came back
        ui.page.wait_for_timeout(500)
        receipt["shots"]["lapsePlaying"] = ui.shot("07-time-lapse-catching-up.png")
        ui.page.wait_for_timeout(6000)
        segments = ui.page.locator(".nx-av-progress li button")
        if segments.count() > 1:
            segments.nth(1).click()
            ui.page.wait_for_timeout(1200)
        receipt["shots"]["lapseSegments"] = ui.shot("08-time-lapse-what-progressed.png")
        receipt["timeline"] = {"keyframes": len(timeline["keyframes"]), "keyframeBytes": sum(k["bytes"] for k in timeline["keyframes"]),
                               "entries": len(timeline["entries"]), "bounds": timeline["bounds"],
                               "pinned": [k["id"] for k in timeline["keyframes"] if k.get("pinned")]}

        # ---- 6. The browser run: comment on the page, the agent reads it with its next result ----
        open_agents(ui)
        open_run(ui, "Check the checkout page")
        ui.page.wait_for_timeout(1500)
        receipt["shots"]["browserLive"] = ui.shot("09-browser-run-live.png")
        # Paul clicks the gift wrap option on the page picture (located from the page's own layout).
        seen = browse("observe")
        gift = next(e for e in seen["elements"] if "gift wrap" in str(e.get("name", "")).lower())
        click_frame(ui, (gift["bounds"]["x"] + gift["bounds"]["w"] / 2) / 1280, (gift["bounds"]["y"] + gift["bounds"]["h"] / 2) / 720)
        write_comment(ui, "It's a gift: tick gift wrap and update the total again.")
        send_comment(ui)
        answer = browse("observe")
        notes = answer.get("ownerFeedback") or []
        receipt["shopHeard"] = notes[:1]
        if not notes:
            raise RuntimeError("The browser agent's next result did not carry Paul's comment")
        note("Claude Code read Paul's comment in its next browser result", heard=notes[0][:300])
        act("Gift wrap", "click")
        act("Update total", "click")
        receipt["shop"]["secondText"] = re.findall(r"Total\s*[\d.]+|Updated[^\n]*", browse("observe")["text"])
        ui.page.wait_for_timeout(2500)
        receipt["shots"]["browserAfter"] = ui.shot("10-browser-run-after-comment.png")

        # ---- 7. On the side: the same run in a narrow panel ------------------------------------
        ui.size(460, 920)
        ui.goto()
        open_run(ui, "Test the invoice app")
        ui.page.wait_for_timeout(2500)
        receipt["shots"]["side"] = ui.shot("11-side-panel-width.png")
        ui.size(1480, 920)
        ui.goto()
        open_agents(ui)
        receipt["shots"]["overviewEnd"] = ui.shot("12-agents-at-work-after.png")

        receipt["uiErrors"] = ui.errors[-10:]
        receipt["agentDesktopGuard"] = backend.agentview("runs").get("agentDesktop")
        stream = backend.agentview(f"frame?run={invoice_key}&surface=w{wid}&since=0&fps=4")
        again = backend.agentview(f"frame?run={invoice_key}&surface=w{wid}&since={stream['v']}&fps=4")
        receipt["stream"] = {"full": {"kind": stream["kind"], "bytes": stream["bytes"], "w": stream["w"], "h": stream["h"]},
                             "next": {"kind": again["kind"], "bytes": again.get("bytes")}}
        receipt["ok"] = bool("39.56" in second_total and receipt["feedbackAfter"]["state"] == "delivered" and notes
                             and (receipt["agentDesktopGuardAfterDesktopWork"] or {}).get("ok")
                             and not (receipt["agentDesktopGuard"] or {}).get("newVisibleWindows")
                             and not (receipt["agentDesktopGuard"] or {}).get("foregroundChanges"))
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {str(exc)[:600]}"
        print("FAILED", receipt["error"], flush=True)
        try:
            receipt["agentDesktopAtFailure"] = backend.agentview("runs").get("agentDesktop")
            print("agent desktop guard:", receipt["agentDesktopAtFailure"], flush=True)
        except Exception:
            pass
        if ui is not None:
            try:
                receipt["shots"]["failure"] = ui.shot("zz-failure.png")
            except Exception:
                pass
    finally:
        if ui is not None:
            ui.close()
        for sid in cua_sessions:
            try:
                backend.cua("end", {"sessionId": sid})
            except Exception:
                pass
        if tab_id:
            try:
                backend.browser("tab.close", {"tabId": tab_id})
            except Exception:
                pass
        try:
            backend.browser("headless.stop", {})
        except Exception:
            pass
        if shop is not None:
            shop.shutdown()
        # Close the apps this run launched on the agent desktop (only those pids).
        for pid in filter(None, launched_pids):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, **hidden_windows_subprocess_kwargs())
        receipt["closedPids"] = [p for p in launched_pids if p]
        time.sleep(1.0)
        receipt["guardAfter"] = guard_state()
        receipt["noWindowOnPaulsDesktop"] = receipt["guardAfter"]["sha256"] == receipt["guardBefore"]["sha256"]
        receipt["ok"] = bool(receipt["ok"] and receipt["noWindowOnPaulsDesktop"])
        (ATTEMPT / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if receipt["ok"]:
            for old in EVIDENCE.glob("*.png"):
                old.unlink()
            for new in ATTEMPT.iterdir():
                if new.suffix in {".png", ".json"}:
                    new.replace(EVIDENCE / new.name)
        print(json.dumps({k: receipt.get(k) for k in ("ok", "error", "noWindowOnPaulsDesktop")}), flush=True)
    return receipt["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:48901")
    parser.add_argument("--shop-port", type=int, default=48903)
    parser.add_argument("--engine-port", type=int, default=48904)
    parser.add_argument("--ui-port", type=int, default=48905)
    parser.add_argument("--skip-charmap", action="store_true")
    args = parser.parse_args()
    for port in (args.shop_port, args.engine_port, args.ui_port, int(args.base.rsplit(":", 1)[1])):
        if port not in range(48901, 48910):
            parser.error("Agent view proof ports must be 48901-48909")
    raise SystemExit(0 if run(args) else 2)
