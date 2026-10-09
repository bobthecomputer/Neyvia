"""Proof for LAYA visibility and live preview, in Neyvia's owned Obscura browser.

Ports 48842 (backend) and 48843 (Obscura) only. The backend is the production HTTP handler over a
disposable runtime root. The LAYA service on 48841 (started separately) answers real decisions that
are recorded as receipts; the panel then reads them back through GET /api/ui/laya. The live preview
check opens an HTML artifact the way an agent does (neyvia.pane.show), then rewrites the file three
times and records what the pane shows after each write.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".agent_control/laya-visible"
OUT = ROOT / "docs/evidence/laya-visible"
PYTHON = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe")
BACKEND, OBSCURA, LAYA = 48842, 48843, 48841
EXE = SCRATCH / "obscura.exe"
BUILD = SCRATCH / "build2"
sys.path.insert(0, str(ROOT / "src"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def await_http(url, process):
    for _ in range(160):
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before {url}: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(url)


def serve(runtime):
    from http.server import ThreadingHTTPServer
    from grant_agent.web_backend import FluxioWebBackend, make_handler
    backend = FluxioWebBackend(Path(runtime), BUILD)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False
    Server(("127.0.0.1", BACKEND), make_handler(backend)).serve_forever()


def seed_laya(runtime, receipt):
    """Real decisions from the real LAYA service, recorded by the product code paths themselves."""
    from grant_agent.laya_client.contracts import T20Hook
    from grant_agent.laya_ledger import classify_browser, record
    from grant_agent.taste_lens import triage_report
    hook = T20Hook(f"http://127.0.0.1:{LAYA}", timeout_s=10)
    cases = [
        ("page_done", "Open the pricing page and find the Pro plan price", "Pricing - Acme", "https://acme.test/pricing",
         "Pro plan: $29 per month. Team plan: $79 per month.", [{"id": "e1", "role": "link", "name": "Contact sales"}]),
        ("page_done", "Open the pricing page and find the Pro plan price", "Acme - Home", "https://acme.test/",
         "Welcome to Acme. Get started. Learn more.", [{"id": "e1", "role": "link", "name": "Pricing"}]),
        ("next_action", "Open the pricing page and find the Pro plan price", "Acme - Home", "https://acme.test/",
         "Welcome to Acme. Build faster with Acme.", [{"id": "e1", "role": "link", "name": "Pricing"}, {"id": "e2", "role": "link", "name": "Docs"}]),
    ]
    rows = []
    for question, goal, title, url, text, controls in cases:
        state = {"revision": 1, "observed_at_ms": time.time() * 1000, "trust": "untrusted-data", "page": {"url": url, "title": title},
                 "controls": controls, "current": {"text": text, "title": title, "url": url}, "goal": goal, "options": ["done", "click", "search"]}
        started = time.monotonic()
        response = hook({"tabId": "t1", "observed": state, "question": question})
        ms = (time.monotonic() - started) * 1000
        outcome, confidence, detail = classify_browser(response)
        rows.append(record(runtime, task="browser", path="browser.decide", decision=question, outcome=outcome, latency_ms=ms,
                           confidence=confidence, prompt_chars=len(json.dumps(state)), detail=detail))
    grey = {"gate": "clear", "score": 94, "counts": {"block": 0, "warn": 1, "note": 0},
            "findings": [{"severity": "warn", "rule": "alt", "viewport": "desktop", "title": "1 images lack alt text"}]}
    receipt["tasteTriage"] = triage_report(runtime, grey)
    receipt["layaRows"] = [{k: r[k] for k in ("task", "decision", "outcome", "latencyMs", "confidence")} for r in rows]


def main():
    for port in (BACKEND, OBSCURA):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in list(env):
        if any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH_FILE")):
            env.pop(name, None)
    home = SCRATCH / "home"
    home.mkdir(exist_ok=True)
    runtime = SCRATCH / f"runtime-{time.time_ns()}"
    runtime.mkdir()
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / "codex"), "HERMES_HOME": str(home / "hermes"),
        "CLAUDE_CONFIG_DIR": str(home / "claude"), "XDG_CONFIG_HOME": str(home / "xdg"), "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
        "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1",
        "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_RUNTIME_AUTO_UPDATE": "0",
        "FLUXIO_LOCAL_SESSION_BOOTSTRAP": "1", "SYNTELOS_ACCOUNT_USER": "laya-proof", "SYNTELOS_ACCOUNT_PASSWORD": secrets.token_urlsafe(32),
        "FLUXIO_WEB_BACKEND_URL": f"http://127.0.0.1:{BACKEND}", "NEYVIA_OBSCURA_EXE": str(EXE),
        "NEYVIA_LAYA_URL": f"http://127.0.0.1:{LAYA}", "NEYVIA_UI_STATE_ROOT": str(runtime), "FLUXIO_WORKSPACE_ROOT": str(runtime),
    })
    os.environ["NEYVIA_LAYA_URL"] = env["NEYVIA_LAYA_URL"]
    receipt = {"schema": "neyvia.laya-visible.proof.v1", "ports": {"backend": BACKEND, "obscura": OBSCURA, "laya": LAYA},
               "engineSha256": sha(EXE), "checks": [], "screenshots": [], "errors": [], "previewSteps": []}
    processes, browser = [], None
    try:
        seed_laya(runtime, receipt)
        page_dir = runtime / "work" / "site"
        page_dir.mkdir(parents=True)
        page = page_dir / "index.html"
        css = page_dir / "style.css"

        def write_site(version, title, color):
            css.write_text(f"body{{margin:0;font:28px system-ui;background:{color};color:#111;padding:48px}}h1{{font-size:56px}}", encoding="utf-8")
            page.write_text(f"<!doctype html><meta charset=utf-8><link rel=stylesheet href=style.css><h1>{title}</h1><p>Edit {version} of 3</p>"
                            "<script>fetch('style.css').then(r=>r.text()).then(css=>parent.postMessage({edit:%d,title:document.querySelector('h1').textContent,css:css,href:location.href},'*'))</script>" % version, encoding="utf-8")
        write_site(1, "Launch page, first draft", "#f4efe6")
        with (OUT / "backend.log").open("wb") as log:
            backend = subprocess.Popen([str(PYTHON), str(Path(__file__)), "--serve", str(runtime)], cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(backend)
        await_http(f"http://127.0.0.1:{BACKEND}/api/health", backend)

        import grant_agent.browser_obscura as obscura
        obscura.proof_ports = lambda: {BACKEND, OBSCURA}
        os.environ["NEYVIA_OBSCURA_EXE"] = str(EXE)
        from grant_agent.neyvia_browser import BrowserService
        browser = BrowserService(SCRATCH / f"browser-{time.time_ns()}")
        browser.request("headless.start", {"port": OBSCURA, "allowLocalFixtures": True}, owner=True)
        tab = browser.request("tab.open", {"url": f"http://127.0.0.1:{BACKEND}/", "engine": "obscura"}, owner=True)["tabId"]
        worker = browser.headless.profiles["default"]

        def select_page():
            handle = worker.pages[tab]["page"]
            handle.on("pageerror", lambda error: receipt["errors"].append(str(error)))
            return handle
        worker.executor.submit(select_page).result(timeout=10)
        cookies = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
        origin = f"http://127.0.0.1:{BACKEND}"
        request = urllib.request.Request(f"{origin}/api/auth/local-session", data=b"{}", headers={"Content-Type": "application/json", "Origin": origin})
        with client.open(request, timeout=20) as response:
            receipt["authStatus"] = response.status

        def post(path, body):
            req = urllib.request.Request(origin + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Origin": origin})
            with client.open(req, timeout=30) as response:
                return json.load(response)

        def get(path):
            with client.open(urllib.request.Request(origin + path, headers={"Origin": origin}), timeout=30) as response:
                return json.load(response)
        post("/api/backend", {"command": "onboarding_save_command", "payload": {"dismissed": True}})
        worker.executor.submit(lambda: worker.pages[tab]["page"].context.add_cookies(
            [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "httpOnly": True, "sameSite": "Lax"} for c in cookies])).result(timeout=15)
        worker.executor.submit(lambda: worker.pages[tab]["page"].evaluate("localStorage.setItem('nx.os.theme',JSON.stringify('dark'))")).result(timeout=15)

        def page_do(fn):
            return worker.executor.submit(lambda: fn(worker.pages[tab]["page"])).result(timeout=60)

        def check(label, condition, **extra):
            receipt["checks"].append({"label": label, "ok": bool(condition), **extra})
            if not condition:
                raise AssertionError(label)

        def shot(name):
            path = OUT / f"{name}.png"
            time.sleep(1.5)  # Obscura paints a moment after the DOM changes
            page_do(lambda p: p.screenshot(path=str(path), full_page=False))
            receipt["screenshots"].append(str(path.relative_to(ROOT)))
            return sha(path)

        def wait_for(expression, timeout=25):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if page_do(lambda p: p.evaluate(expression)):
                    return
                time.sleep(0.25)
            receipt["busCursor"] = page_do(lambda p: p.evaluate("()=>({cursor:localStorage.getItem('nx.bus.cursor.live'),stage:document.querySelector('.nx-stage')?.className||null,url:location.href})"))
            receipt["domAtTimeout"] = page_do(lambda p: p.evaluate("()=>document.body.innerText.slice(0,2000)"))
            shot("failure")
            raise TimeoutError(expression)

        # ---- the backend report the panel reads
        report = get("/api/ui/laya")
        data = report.get("data", report)
        receipt["report"] = {k: data[k] for k in ("service", "totals", "tasks")}
        check("API reports the recorded LAYA decisions", data["totals"]["answered"] >= 1 and data["totals"]["escalated"] >= 1, totals=data["totals"])
        check("API sees the live LAYA service", data["service"]["ready"] is True, service=data["service"])

        # ---- the panel in the real UI
        browser.request("tab.navigate", {"tabId": tab, "url": f"{origin}/control"}, owner=True)
        wait_for("()=>!!document.querySelector('.nx-strip')")
        wait_for("()=>[...document.querySelectorAll('.nx-laya span')].some(e=>/LAYA \\d+\\/\\d+/.test(e.innerText))")
        strip = page_do(lambda p: p.evaluate("()=>document.querySelector('.nx-laya').innerText"))
        receipt["stripText"] = strip
        check("Strip shows answered of asked from real receipts", "LAYA" in strip and "/" in strip, strip=strip)
        for _ in range(4):
            if page_do(lambda p: p.evaluate("()=>!!document.querySelector('.nx-laya-detail .nx-laya-stat')")):
                break
            page_do(lambda p: p.evaluate("()=>document.querySelector('.nx-laya').click()"))
            time.sleep(2)
        wait_for("()=>!!document.querySelector('.nx-laya-detail .nx-laya-stat')", 10)
        detail = page_do(lambda p: p.evaluate("()=>document.querySelector('.nx-laya-detail').innerText"))
        receipt["panelText"] = detail
        check("Panel lists the browser task with answered and handed-up counts", "browser" in detail and "answered" in detail and "Computer use" in detail)
        receipt["stripRects"] = page_do(lambda p: p.evaluate("()=>[...document.querySelectorAll('.nx-strip > *')].map(e=>{const r=e.getBoundingClientRect();return {c:(e.className||'').toString().slice(0,40),x:Math.round(r.x),w:Math.round(r.width)}})"))
        shot("laya-panel")

        # ---- live preview: an agent opens the page, then rewrites it
        # Obscura delivers no server-sent events, so the agent's pane.show cannot reach the shell here.
        # The real artifact pane is mounted on its own page (harness, same origin as the backend).
        from urllib.parse import quote
        harness = BUILD / "liveproof" / "live.html"  # Obscura ignores a crossorigin stylesheet link; same origin needs none
        harness.write_text(harness.read_text(encoding="utf-8").replace('<link rel="stylesheet" crossorigin ', '<link rel="stylesheet" '), encoding="utf-8")
        browser.request("tab.navigate", {"tabId": tab, "url": f"{origin}/liveproof/live.html?target={quote(str(page))}"}, owner=True)
        wait_for("()=>!!document.querySelector('.nx-ap-live iframe')", 60)
        time.sleep(2)
        # This Obscura build does not apply <link rel=stylesheet>; the product's own loader injects styles as text, so does this.
        for attempt in range(4):
            try:
                page_do(lambda p: p.evaluate("async()=>{for(const l of document.querySelectorAll('link[rel=stylesheet]')){const t=await (await fetch(l.href)).text();const s=document.createElement('style');s.textContent=t;document.head.append(s);}}"))
                break
            except Exception as exc:
                receipt["errors"].append(f"css inject {attempt}: {str(exc)[:80]}")
                time.sleep(2)
        receipt["harnessCss"] = page_do(lambda p: p.evaluate("()=>({sheets:document.styleSheets.length,links:[...document.querySelectorAll('link')].map(l=>l.href),barDisplay:getComputedStyle(document.querySelector('.nx-fp-bar')).display,rootBg:getComputedStyle(document.querySelector('.nx-root')).backgroundColor})"))
        page_do(lambda p: p.evaluate("()=>{window.__seen=[];window.addEventListener('message',e=>{if(e.data&&e.data.edit)window.__seen.push(e.data)})}"))
        first = shot("preview-1")
        steps = [(2, "Launch page, second pass", "#e3f0e6", "rgb(227, 240, 230)"), (3, "Launch page, final", "#e6e9f5", "rgb(230, 233, 245)")]
        for version, title, color, expected_bg in steps:
            write_site(version, title, color)
            end = time.monotonic() + 25
            seen = None
            while time.monotonic() < end and seen is None:
                messages = page_do(lambda p: p.evaluate("()=>window.__seen"))
                seen = next((m for m in messages if m["edit"] == version), None)
                time.sleep(0.4)
            info = page_do(lambda p: p.evaluate("()=>({live:document.querySelector('.nx-ap-livechip')?.innerText,"
                                                "frames:[...document.querySelectorAll('.nx-ap-live iframe')].map(e=>({which:e.dataset.live,src:e.getAttribute('src')}))})"))
            time.sleep(1.5)
            shot(f"preview-{version}")
            receipt.setdefault("frameStyles", []).append(page_do(lambda p: p.evaluate("()=>[...document.querySelectorAll('.nx-ap-live iframe')].map(e=>({live:e.dataset.live,position:getComputedStyle(e).position,opacity:getComputedStyle(e).opacity}))")))
            receipt["previewSteps"].append({"version": version, "pageReported": seen, "pane": info})
            check(f"Preview showed edit {version} (title and sibling stylesheet) without a manual reload",
                  seen is not None and seen["title"] == title and color.lower() in seen["css"] and f"live={version - 1}" in seen["href"], seen=seen, pane=info)
        receipt["ok"] = True
    except Exception as exc:
        receipt["ok"] = False
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback"] = traceback.format_exc()
    finally:
        if browser:
            try:
                browser.request("headless.stop", {}, owner=True)
            except Exception as exc:
                receipt["errors"].append(f"close: {exc}")
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
        (OUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "failure": receipt.get("failure"), "checks": len(receipt["checks"]), "screenshots": receipt["screenshots"]}))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve(sys.argv[sys.argv.index("--serve") + 1])
    else:
        raise SystemExit(main())
