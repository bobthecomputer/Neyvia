"""LAYA on by default: start the Neyvia backend normally (no LAYA environment variable) and prove it owns the service.

Ports: 48841 LAYA (started by the backend itself), 48842 backend, 48845 Obscura. Then, against that backend:
  - a short real browser task in Neyvia's own Obscura browser (open a page, decide page_done before and after a click),
  - a Connected Language routing call (the real HostContext.cold_start on a real benchmark task),
  - the status-strip panel rendered in Obscura from the resulting receipts.
Writes docs/evidence/laya-default/receipt.json and screenshots.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".agent_control/laya-visible"
OUT = ROOT / "docs/evidence/laya-default"
PYTHON = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe")
LAYA, BACKEND, OBSCURA = 48841, 48842, 48845
EXE = SCRATCH / "obscura.exe"
BUILD = SCRATCH / "build2"
ORIGIN = f"http://127.0.0.1:{BACKEND}"
sys.path.insert(0, str(ROOT / "src"))

FIXTURE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme pricing</title></head><body>
<h1>Acme pricing</h1><p>Pro plan: $29 per month. Team plan: $79 per month. Enterprise: contact sales.</p>
<button id="choose" onclick="document.getElementById('out').textContent='Pro plan selected: $29 per month. Confirmation sent.'">Choose Pro</button>
<p id="out" aria-live="polite"></p></body></html>"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def free(port):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def main():
    for port in (LAYA, BACKEND, OBSCURA):
        free(port)
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = SCRATCH / f"default-runtime-{time.time_ns()}"
    runtime.mkdir(parents=True)
    fixture = BUILD / "fixture"
    fixture.mkdir(exist_ok=True)
    (fixture / "pricing.html").write_text(FIXTURE, encoding="utf-8")
    home = SCRATCH / "home"
    home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH_FILE", "LAYA"))}
    password = secrets.token_urlsafe(32)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
        "CODEX_HOME": str(home / "codex"), "HERMES_HOME": str(home / "hermes"), "CLAUDE_CONFIG_DIR": str(home / "claude"),
        "PYTHONDONTWRITEBYTECODE": "1", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0", "NEYVIA_TOOL_AUTO_UPDATE": "0",
        "FLUXIO_RUNTIME_AUTO_UPDATE": "0", "FLUXIO_LOCAL_SESSION_BOOTSTRAP": "1", "SYNTELOS_ACCOUNT_USER": "laya-default-proof",
        "SYNTELOS_ACCOUNT_PASSWORD": password, "NEYVIA_OBSCURA_EXE": str(EXE),
        "NEYVIA_BROWSER_PROOF_PORTS": f"{BACKEND},{OBSCURA}", "NEYVIA_PROOF_ALLOWED_PORTS": json.dumps([BACKEND, OBSCURA]),
    })
    # The LAYA model lives in the user's profile; the sandboxed HOME above must not hide it.
    real_home = Path(os.environ["USERPROFILE"])
    config_dir = runtime / ".neyvia" / "laya"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({
        "python": str(real_home / "miniforge3/envs/whisper/python.exe"),
        "model": str(real_home / "Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work/models/laya-english")}), encoding="utf-8")
    receipt = {"schema": "neyvia.laya-default.proof.v1", "ports": {"laya": LAYA, "backend": BACKEND, "obscura": OBSCURA},
               "layaEnvVarSetForBackend": "NEYVIA_LAYA_URL" in env, "checks": [], "screenshots": [], "errors": []}
    backend = None
    browser = None
    try:
        with (OUT / "backend.log").open("wb") as log:
            backend = subprocess.Popen([str(PYTHON), str(ROOT / "scripts/run_web_backend.py"), "--host", "127.0.0.1", "--port", str(BACKEND),
                                        "--root", str(runtime), "--static-root", str(BUILD), "--skip-runtime-auto-update"],
                                       cwd=ROOT, env={**env, "PYTHONPATH": str(ROOT / "src")}, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(200):
            if backend.poll() is not None:
                raise RuntimeError(f"backend exited {backend.returncode}")
            try:
                urllib.request.urlopen(f"{ORIGIN}/api/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        cookies = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

        def call(path, body=None, timeout=60):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(ORIGIN + path, data=data, headers={"Content-Type": "application/json", "Origin": ORIGIN})
            with client.open(req, timeout=timeout) as response:
                value = json.load(response)
            return value.get("data", value) if isinstance(value, dict) else value

        def check(label, condition, **extra):
            receipt["checks"].append({"label": label, "ok": bool(condition), **extra})
            if not condition:
                raise AssertionError(label)

        call("/api/auth/local-session", {})
        # 1. The backend starts and owns LAYA by itself.
        started = time.time()
        status = None
        while time.time() - started < 300:
            status = call("/api/ui/laya")["service"]
            if status.get("ready"):
                break
            time.sleep(3)
        receipt["layaStatus"] = status
        receipt["secondsToReady"] = round(time.time() - started)
        check("Backend started LAYA by itself (owned child, no environment variable)", status.get("ready") and status.get("owned") and not receipt["layaEnvVarSetForBackend"], host=status.get("host"))
        pid = status["host"]["pid"]
        parent = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ParentProcessId"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        receipt["serviceParentPid"], receipt["backendPid"] = parent, backend.pid
        check("The LAYA process is a child of the backend", parent == str(backend.pid), parent=parent, backend=backend.pid)

        # 2. A short real browser task.
        call("/api/ui/browser", {"op": "headless.start", "args": {"port": OBSCURA, "allowLocalFixtures": True}})
        tab = call("/api/ui/browser", {"op": "tab.open", "args": {"url": f"{ORIGIN}/fixture/pricing.html", "engine": "obscura"}})["tabId"]
        call("/api/ui/browser", {"op": "tab.grant", "args": {"tabId": tab, "enabled": True}})
        time.sleep(2)
        evidence = "Pro plan selected: $29 per month"
        goal = "Choose the Pro plan and confirm the page shows the selection"

        def decide(context):
            return call("/api/ui/browser", {"op": "decide", "args": {"tabId": tab, "question": "page_done", "context": context}}, timeout=90)
        before = decide({"goal": goal, "evidence": evidence, "action_receipts": []})
        receipt["pageDoneBefore"] = before
        observation = call("/api/ui/browser", {"op": "observe", "args": {"tabId": tab, "cached": False}})
        if observation.get("actionId"):
            time.sleep(2)
            observation = call("/api/ui/browser", {"op": "observe", "args": {"tabId": tab, "cached": True}})
        element = next((e["id"] for e in observation.get("elements", []) if "Choose Pro" in str(e.get("name"))), None)
        check("Obscura saw the Choose Pro button", element, elements=len(observation.get("elements", [])))
        acted = call("/api/ui/browser", {"op": "action", "args": {"tabId": tab, "revision": observation["revision"], "element": element, "action": "click"}})
        receipt["click"] = {k: acted.get(k) for k in ("ok", "status", "actionId")}
        time.sleep(2)
        after = decide({"goal": goal, "evidence": evidence, "action_receipts": [{"action": "click", "status": "ok", "summary": "clicked Choose Pro"}]})
        receipt["pageDoneAfter"] = after

        # 3. A Connected Language routing call against the same backend-owned service.
        os.environ["NEYVIA_LAYA_URL"] = f"http://127.0.0.1:{LAYA}"  # this proof client only; the backend never had it
        from grant_agent.cl.host import HostContext
        tasks = json.loads((ROOT / "config/cl_benchmark_1.1_tasks.json").read_text(encoding="utf-8"))
        routing = []
        for task in tasks["tasks"] + tasks.get("dev", []):
            host = HostContext([{"name": f"{task['layer']}.read", "effect": "", "annotations": {"readOnlyHint": True}, "inputSchema": {"properties": {}}}],
                               lambda *a, **k: {}, root=runtime, task_text=task["text"])
            verdict = host.route()
            routing.append({"task": task["text"][:80], "layer": task["layer"], "routed": verdict and verdict.get("layer")})
            if len(routing) >= 4:
                break
        receipt["routing"] = routing

        # 4. What the panel says.
        report = call("/api/ui/laya")
        receipt["report"] = {k: report[k] for k in ("service", "totals", "tasks")}
        receipt["recent"] = report["recent"][:10]
        check("The ledger holds real LAYA answers and handed-up decisions from the browser task", report["totals"]["answered"] + report["totals"]["escalated"] >= 2, totals=report["totals"])
        receipt["ok"] = True
    except Exception as exc:
        receipt["ok"] = False
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback"] = traceback.format_exc()
    finally:
        # Capture the panel before shutting down (only if the backend is still up).
        try:
            if backend and backend.poll() is None and receipt.get("report"):
                import grant_agent.browser_obscura as obscura
                obscura.proof_ports = lambda: {BACKEND, OBSCURA + 1}
                os.environ["NEYVIA_OBSCURA_EXE"] = str(EXE)
                from grant_agent.neyvia_browser import BrowserService
                browser = BrowserService(SCRATCH / f"default-browser-{time.time_ns()}")
                browser.request("headless.start", {"port": OBSCURA + 1, "allowLocalFixtures": True}, owner=True)
                tab2 = browser.request("tab.open", {"url": ORIGIN + "/", "engine": "obscura"}, owner=True)["tabId"]
                worker = browser.headless.profiles["default"]
                page_do = lambda fn: worker.executor.submit(lambda: fn(worker.pages[tab2]["page"])).result(timeout=60)
                page_do(lambda p: p.context.add_cookies([{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "httpOnly": True, "sameSite": "Lax"} for c in cookies]))
                page_do(lambda p: p.evaluate("localStorage.setItem('nx.os.theme',JSON.stringify('dark'))"))
                browser.request("tab.navigate", {"tabId": tab2, "url": ORIGIN + "/control"}, owner=True)
                for _ in range(40):
                    time.sleep(0.5)
                    if page_do(lambda p: p.evaluate("()=>[...document.querySelectorAll('.nx-laya span')].some(e=>/LAYA \\d+\\/\\d+/.test(e.innerText))")):
                        break
                for _ in range(4):
                    if page_do(lambda p: p.evaluate("()=>!!document.querySelector('.nx-laya-detail .nx-laya-stat')")):
                        break
                    page_do(lambda p: p.evaluate("()=>document.querySelector('.nx-laya')&&document.querySelector('.nx-laya').click()"))
                    time.sleep(2)
                receipt["panelText"] = page_do(lambda p: p.evaluate("()=>document.querySelector('.nx-laya-detail')?.innerText||null"))
                time.sleep(1.5)
                path = OUT / "laya-panel.png"
                page_do(lambda p: p.screenshot(path=str(path)))
                receipt["screenshots"].append(str(path.relative_to(ROOT)))
        except Exception as exc:
            receipt["errors"].append("panel: " + str(exc)[:200])
        if browser:
            try:
                browser.request("headless.stop", {}, owner=True)
            except Exception:
                pass
        if backend and backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                backend.kill()
        time.sleep(3)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{LAYA}/v1/health", timeout=1)
            receipt["layaStoppedWithBackend"] = False
        except OSError:
            receipt["layaStoppedWithBackend"] = True
        (OUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "failure": receipt.get("failure"), "checks": len(receipt["checks"]),
                          "layaStoppedWithBackend": receipt["layaStoppedWithBackend"]}))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
