"""Real rubric/LOO calibration with hidden Neyvia Search/WebView2 captures.

Never launches Chrome/Edge, touches a user profile, or attributes proxy identity
guesses to true preference. All owned servers use explicitly supplied C9c ports.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.durability import atomic_write_json
from grant_agent.lesson_replay import digest
from grant_agent.lesson_evolver import LearnedJudge
from grant_agent.lesson_preference import FEATURES, margin
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

ROOT = REPO / "scripts/evidence/C9c-runs/judge"
OUTPUT = REPO / "scripts/evidence/C9c-judge.json"
INSTRUMENT = r'''<script>(()=>{
const errors=[];addEventListener('error',e=>errors.push(String(e.message)));addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
const send=()=>{const controls=[...document.querySelectorAll('button,input,select,textarea,a[href],[role=button]')].map(e=>({name:e.getAttribute('aria-label')||e.textContent.trim().slice(0,100),tag:e.tagName,type:e.type,href:e.getAttribute('href'),width:e.getBoundingClientRect().width}));
fetch('/diag'+location.search,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({errors,viewport:{width:innerWidth,height:innerHeight},overflow:document.documentElement.scrollWidth>innerWidth+1,controls,sections:[...document.querySelectorAll('section')].map(e=>e.innerText.trim().length)})}).catch(()=>{});};
addEventListener('load',()=>{send();setTimeout(send,500)});addEventListener('click',()=>setTimeout(send,100));})();</script>'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend-port", type=int, required=True)
    p.add_argument("--fixture-port", type=int, required=True)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--score-only", action="store_true", help="Reuse already retained actual browser observations")
    args = p.parse_args()
    if len({args.backend_port, args.fixture_port}) != 2 or not {args.backend_port, args.fixture_port} <= set(range(48761, 48770)):
        raise ValueError("Two distinct explicit C9c ports required")
    native_path = args.native.resolve()
    if not native_path.is_relative_to(REPO / ".agent_control/C9c-build") or not native_path.is_file():
        raise ValueError("Only this task's hidden Neyvia browser probe is allowed")
    ROOT.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.backend_port}"
    fixture_base = f"http://127.0.0.1:{args.fixture_port}"
    cookie = ""
    def request(path, value=None):
        req = Request(base + path, None if value is None else json.dumps(value).encode(),
                      {"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
        with urlopen(req, timeout=40) as r:
            return json.load(r), r.headers
    data, headers = request("/api/auth/local-session", {})
    if not data.get("ok"):
        raise ValueError("Owned local authentication failed")
    cookie = headers["Set-Cookie"].split(";")[0]
    def browser(op, args=None):
        value, _ = request("/api/ui/browser", {"op": op, "args": args or {}})
        if value.get("ok") is False:
            raise ValueError("Browser operation failed: " + op)
        return value
    def completed(value):
        if "actionId" not in value:
            return value
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            row = browser("action.get", {"actionId": value["actionId"]})
            if row.get("status") == "failed":
                raise ValueError("Native browser operation failed: " + str(row.get("error")))
            if row.get("status") == "done":
                return row
            time.sleep(.1)
        raise TimeoutError("Native browser operation did not return")
    def observe(tab):
        row = completed(browser("observe", {"tabId": tab}))
        return row["result"]["observation"]

    original = json.loads((REPO / "proof/preference-pairs.json").read_text(encoding="utf-8"))
    outputs = []
    for pair in original["pairs"]:
        for arm in ("C", "L"):
            files = {n: f["text"] for n, f in pair["arms"][arm]["files"].items()}
            outputs.append({"task": pair["taskText"], "files": files})
    task_source = (REPO / "proof/r6-blind/tasks.md").read_text(encoding="utf-8")
    parts = re.split(r"^## (T\d) · [^\n]*\n", task_source, flags=re.M)
    tasks = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    keys = json.loads((REPO / "proof/r6-blind/answer-key.SPOILER.json").read_text(encoding="utf-8"))
    r6 = []
    for tid, key in keys["pairs"].items():
        pair = {"id": key["pairId"], "task": tasks[tid]}
        for side, folder in ((key["claudeSide"], "arm-c"), (key["lunaSide"], "arm-l")):
            files = {key["file"]: (REPO / "proof/r6-blind" / folder / key["file"]).read_text(encoding="utf-8")}
            pair[side] = files
            outputs.append({"task": tasks[tid], "files": files})
        r6.append(pair)
    if args.score_only:
        return score_existing(r6, keys)
    pages, diagnostics = {}, {}
    for item in outputs:
        identity = digest(item)
        for filename, text in item["files"].items():
            if filename.lower().endswith((".html", ".htm")):
                pages[identity + "/" + filename] = text
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0].lstrip("/")
            if path not in pages:
                self.send_error(404); return
            raw = pages[path]
            raw = re.sub(r"(<head[^>]*>)", lambda m: m[0] + INSTRUMENT, raw, count=1, flags=re.I) if re.search(r"<head\b", raw, re.I) else INSTRUMENT + raw
            body = raw.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            identity = self.path.split("?", 1)[-1]
            length = int(self.headers.get("Content-Length", 0))
            if not self.path.startswith("/diag?") or length > 100000:
                self.send_error(400); return
            diagnostics[identity] = json.loads(self.rfile.read(length))
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *_): pass
    fixture = ThreadingHTTPServer(("127.0.0.1", args.fixture_port), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True); thread.start()
    grant = browser("runtime.connect")
    from c9c_native import NativeProcess
    user = ctypes.windll.user32
    native = NativeProcess(native_path, REPO,
        {**os.environ, "NEYVIA_BROWSER_BASE": base, "NEYVIA_BROWSER_TOKEN": grant["token"],
         "NEYVIA_BROWSER_PROOF_SCOPE": "C9c"})
    desktop_name = native.verified_name
    user.GetForegroundWindow.restype = wintypes.HWND
    foreground = int(user.GetForegroundWindow() or 0)
    point = wintypes.POINT(); user.GetCursorPos(ctypes.byref(point)); cursor = [point.x, point.y]
    visible_owned = set()
    stop = threading.Event()
    def monitor():
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @callback_type
        def inspect(hwnd, _):
            pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == native.pid and user.IsWindowVisible(hwnd):
                visible_owned.add(int(hwnd))
            return True
        while not stop.wait(.025): user.EnumWindows(inspect, 0)
    monitor_thread = threading.Thread(target=monitor, daemon=True); monitor_thread.start()
    receipt = {"schema": "neyvia.C9c-rubric-proof.v1", "ports": [args.backend_port, args.fixture_port],
        "captures": [], "boundary": "Fresh hidden Neyvia Search-inspired Tauri/WebView2; no Chrome/Edge automation, unchanged artifact plus nonvisual error/DOM instrumentation"}
    observations = {}
    try:
        for index, item in enumerate(outputs):
            identity = digest(item)
            images, runtime = [], {"errors": [], "failures": [], "allControlsExercised": False,
                                  "boundary": "Rendered and semantic actions sampled; arbitrary pointer/keyboard/touch behavior remains unproven"}
            for filename, text in item["files"].items():
                if not filename.lower().endswith((".html", ".htm")): continue
                url = fixture_base + "/" + identity + "/" + filename + "?" + identity
                tab = browser("tab.open", {"url": url, "engine": "webview2"})["tabId"]
                for label, width, height in (("desktop", 1280, 1500), ("phone", 390, 1200)):
                    completed(browser("layout", {"tabs": [{"tabId": tab, "x": 0, "y": 0, "width": width, "height": height, "visible": True}]}))
                    time.sleep(.65)
                    obs = observe(tab)
                    captured = completed(browser("capture", {"tabId": tab}))
                    path = Path(captured["result"]["path"])
                    destination = ROOT / "images" / (identity + "-" + Path(filename).stem + "-" + label + ".png")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(path.read_bytes())
                    images.append(str(destination))
                    row = {"artifactSha256": hashlib.sha256(text.encode()).hexdigest(), "image": str(destination.relative_to(REPO)),
                           "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "viewport": label,
                           "projection": obs, "diagnostics": diagnostics.get(identity, {})}
                    receipt["captures"].append(row)
                    runtime["errors"] += row["diagnostics"].get("errors", [])
                    # Overflow is a direct observed failure; missing/pointer-only
                    # control behavior stays unknown rather than receiving a pass.
                    if row["diagnostics"].get("overflow"):
                        runtime["failures"].append("Horizontal overflow in " + label)
                browser("tab.grant", {"tabId": tab, "enabled": True})
                obs = observe(tab)
                action = next((e for e in obs["elements"] if e["role"] == "button" and "click" in e["actions"]), None)
                if action:
                    try:
                        completed(browser("action", {"tabId": tab, "revision": obs["revision"], "element": action["id"], "action": "click"}))
                        after = observe(tab)
                        runtime.setdefault("sampledActions", []).append({"name": action["name"], "textChanged": after["text"] != obs["text"]})
                    except Exception as exc:
                        # A harness grant/staleness refusal is not an observed
                        # artifact defect: the action never reached the page.
                        runtime.setdefault("actionRefusals", []).append(str(exc))
                browser("tab.close", {"tabId": tab})
            if images:
                # CLI image budget: at most four artifacts per judgement.
                observations[identity] = {"images": images[:4], "runtime": runtime}
            atomic_write_json(OUTPUT, receipt)
            print(json.dumps({"output": index + 1, "images": len(images)}), flush=True)
        atomic_write_json(ROOT / ".neyvia/lessons/rubric-observations.json", observations)
    finally:
        native.terminate()
        try: native.wait(timeout=15)
        except subprocess.TimeoutExpired: native.kill(); native.wait(timeout=5)
        stop.set(); monitor_thread.join(timeout=2)
        fixture.shutdown(); fixture.server_close(); thread.join(timeout=2)
        desktop_closed = native.close()
        user.GetCursorPos(ctypes.byref(point))
        receipt["desktopGuard"] = {"ownedVisibleWindows": sorted(visible_owned), "foregroundBefore": foreground,
            "foregroundAfter": int(user.GetForegroundWindow() or 0), "cursorBefore": cursor, "cursorAfter": [point.x, point.y],
            "nativeExit": native.returncode, "fixtureStopped": not thread.is_alive(),
            "agentDesktop": desktop_name, "agentDesktopHandleClosed": desktop_closed}
        atomic_write_json(OUTPUT, receipt)
    if visible_owned:
        raise ValueError("Hidden Neyvia browser violated the owned-window guard")
    score_existing(r6, keys)


def score_existing(r6, keys):
    receipt = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if receipt["desktopGuard"]["ownedVisibleWindows"]:
        raise ValueError("Cannot use a desktop-guard failure for successful rubric proof")
    judge = LearnedJudge(ROOT)
    frozen = judge.calibrate()
    receipt["calibration"] = frozen
    scored, calls = judge._features(r6)
    votes = json.loads((REPO / "proof/preference-pairs-r6-votes.json").read_text(encoding="utf-8"))
    comparisons = []
    for pair in scored:
        score = margin([1.] * len(FEATURES), pair["vector"])
        weighted = margin(frozen["weights"], pair["vector"])
        expected = next(k["claudeSide"] for k in keys["pairs"].values() if k["pairId"] == pair["id"])
        pick = "A" if score > .05 else "B" if score < -.05 else "tie"
        comparisons.append({**pair, "rubricPick": pick, "rubricMargin": score, "weightedMargin": weighted,
                            "spokenPreference": expected, "agreesWithSpokenVerdict": pick == expected})
    receipt["round3"] = {"suppliedVotes": votes, "spokenVerdict": "Claude better on both; Luna generic and partly broken",
                          "provenance": "User instruction and plan20 round3 result; separate from identity guesses",
                          "comparisons": comparisons, "modelRuns": calls, "notUsedForWeightFitting": True}
    receipt["passed"] = len(frozen["leaveOneOut"]) == 18 and len(comparisons) == 2
    atomic_write_json(OUTPUT, receipt)
    print(json.dumps({"loo": frozen["agreement"], "rubricAgreement": frozen["rubricAgreement"],
                      "round3Agreement": sum(c["agreesWithSpokenVerdict"] for c in comparisons),
                      "learnedGateAdmitted": frozen["passed"]}), flush=True)

if __name__ == "__main__": main()
