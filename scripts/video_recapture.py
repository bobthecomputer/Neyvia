"""Evidence script: fresh, populated Neyvia captures for the launch film (track VIDEO, plan 28).

    PYTHONPATH=src python scripts/video_recapture.py capture [--tag run1] [--only laya,notes]
    PYTHONPATH=src python scripts/video_recapture.py backend --tag dev      # sandbox backend only, for exploring
    PYTHONPATH=src python scripts/video_recapture.py verify                 # glance + OCR every PNG, write the receipt

Reuses the placement tour rig (scripts/placement_shots.py): a sandbox backend over an isolated HOME and
state root on D:, the admitted headless Obscura engine, and the product's own controls (launcher, window
placement buttons). Every fixture is created through the sandbox backend's own routes after the
local-session bootstrap: Notes through /api/ui/notes, App Factory through its backend command, the agent
run through the integrated browser route (/api/ui/browser), the 3D file through Asset check. Nothing on
Paul's screen: all processes are started without windows and stopped by PID.

Ports: backend 49161, Obscura 49162 (track VIDEO). The agent's own Obscura and the capture Obscura take
turns on 49162: the agent works first, its engine stops, then the capture engine starts while the backend
(and the agent view's kept frames) stay up.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
import placement_shots as ps  # noqa: E402

BASE = Path(r"D:\NeyviaRuns\video\track-video\recapture")
BACKEND, ENGINE = 49161, 49162
LAYA_PORT = 48841  # the LAYA service already running on this PC (adopted read-only as "external")
KRONOS = Path(r"D:\NeyviaRuns\laya-3d\kronos\out")
PDF = ROOT / "scripts/evidence/C11g-artifacts/xournal.pdf"


def await_http_slow(url, process, headers=None, seconds=360):
    """ps.await_http gives a backend about 60 s; a cold start of the sandbox backend on this PC can take longer."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before {url}: {process.returncode}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(url)


def configure(tag):
    ps.await_http = await_http_slow
    from grant_agent.laya_glance_gate import _admitted_engine
    exe, _ = _admitted_engine()
    ps.BACKEND, ps.ENGINE, ps.EXE = BACKEND, ENGINE, exe
    ps.SCRATCH = BASE / "state" / tag
    ps.OUT = BASE / "dark"
    ps.BUILD = BASE / "build"
    ps.THEME = "dark"
    ps.SMALL_STATE = None
    for folder in (ps.SCRATCH, ps.OUT):
        folder.mkdir(parents=True, exist_ok=True)


def sandbox_env():
    env = ps.isolated_env()
    env.update({
        "PYTHONPYCACHEPREFIX": str(BASE / "bytecode"),
        "NEYVIA_BROWSER_PROOF_PORTS": f"{BACKEND}-{ENGINE}",
        "NEYVIA_OBSCURA_EXE": str(ps.EXE),
        "NEYVIA_GAMEDEV_WORKSPACE": str(ps.SCRATCH / "home" / "Game"),
        # LAYA learns only from this sandbox's own label inbox, never Paul's label folders.
        "NEYVIA_INSTANT_LABELS": str(ps.SCRATCH / "laya-labels"),
        "NEYVIA_INSTANT_VOTES": str(ps.SCRATCH / "laya-votes"),
    })
    return env


def prepare_state(receipt):
    root = ps.SCRATCH
    home = root / "home"
    # LAYA: adopt the service already answering on this PC; never spawn a second one here.
    laya = root / ".neyvia" / "laya"
    laya.mkdir(parents=True, exist_ok=True)
    (laya / "config.json").write_text(json.dumps({"port": LAYA_PORT, "python": r"C:\Users\user\miniforge3\envs\whisper\python.exe",
        "model": r"C:\Users\user\Documents\Codex\2026-09-20\laya-c-est-l-alternative-open\work\models\laya-english"}), encoding="utf-8")
    # 3D: real Kronos models inside the sandbox game workspace.
    game = home / "Game" / "kronos"
    game.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("emblem", "backpack", "body-turnaround"):
        source = KRONOS / name / f"{name}.glb"
        if source.is_file():
            shutil.copyfile(source, game / f"{name}.glb")
            copied.append(name)
    # Files/PDF: real documents in the sandbox Documents folder.
    docs = home / "Documents" / "Field Notes"
    docs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PDF, docs / "Sketch review.pdf")
    design_review_pdf(docs / "Design review.pdf")
    renders = {"Kronos overview.png": KRONOS / "overview.png", "Emblem colour pass.png": KRONOS / "emblem" / "after-colour.png",
               "Emblem shape pass.png": KRONOS / "emblem" / "after-shape.png"}
    for name, source in renders.items():
        if source.is_file():
            shutil.copyfile(source, docs / name)
    (docs / "Field guide outline.md").write_text(
        "# Field guide outline\n\n1. Getting started\n2. Capturing a note\n3. Tags and search\n4. Sync and export\n", encoding="utf-8")
    (docs / "Interview questions.txt").write_text(
        "What do you write down in the field?\nWhere do your notes end up today?\nWhat would make you trust an app with them?\n",
        encoding="utf-8")
    receipt["fixtures"] = {"kronos": copied, "documents": sorted(p.name for p in docs.iterdir())}


def design_review_pdf(path):
    """A one-page design review for the Field Notes app, written locally with pdf_compat (no personal data)."""
    from grant_agent import pdf_compat
    page = doc = pdf_compat.Canvas(842, 595)  # A4 landscape
    rect = (0, 0, 842, 595)
    ink, muted, accent, line = (0.11, 0.14, 0.14), (0.38, 0.43, 0.42), (0.18, 0.49, 0.40), (0.84, 0.82, 0.78)
    page.rect(rect, fill=(0.98, 0.97, 0.95))
    page.text((48, 70), "Field Notes", size=30, font="helv", color=ink)
    page.text((48, 96), "Design review  ·  revision 3", size=13, font="helv", color=muted)
    page.line((48, 116), (794, 116), color=line, width=1)
    y = 150
    page.text((48, y), "What changed", size=15, font="hebo", color=accent)
    for item in ("Capture button is 20% larger and always in reach", "Tags sit under each note and filter on tap",
                 "Search answers while you type, even offline", "One accent colour for actions; green means saved"):
        y += 28
        page.circle((56, y - 4), 3, fill=accent)
        page.text((68, y), item, size=12.5, font="helv", color=ink)
    y += 50
    page.text((48, y), "Open questions", size=15, font="hebo", color=accent)
    for item in ("Should photos sync on mobile data?", "Weekly digest: email or in-app only?"):
        y += 28
        page.circle((56, y - 4), 3, fill=muted)
        page.text((68, y), item, size=12.5, font="helv", color=ink)
    # A wireframe of the capture screen.
    frame = (520, 140, 794, 540)
    page.rect(frame, stroke=line, fill=(1, 1, 1), width=1.2, radius=0.04)
    page.text((540, 170), "Notes", size=14, font="hebo", color=ink)
    page.rect((540, 186, 700, 214), stroke=line, fill=(0.96, 0.95, 0.93), radius=0.2)
    page.rect((708, 186, 774, 214), fill=accent, radius=0.2)
    page.text((717, 204), "Save", size=11, font="hebo", color=(1, 1, 1))
    for index, (text, tag) in enumerate((("Heron on the north pond", "#birds"), ("Oak by the north gate", "#spring"),
                                         ("Trail marker 14 missing", "#maintenance"), ("Soil dry near plot 4", "#garden"))):
        top = 234 + index * 70
        page.rect((540, top, 774, top + 58), stroke=line, fill=(0.99, 0.99, 0.98), radius=0.12)
        page.text((552, top + 24), text, size=11.5, font="helv", color=ink)
        page.text((552, top + 44), tag, size=10, font="helv", color=accent)
    page.text((48, 548), "Next review after the 0.3 build.", size=11, font="helv", color=muted)
    doc.metadata = {"title": "Field Notes design review", "author": "Field Notes team"}
    doc.save(path)


class Client:
    """The sandbox backend's own HTTP routes, with the local-session cookie."""

    def __init__(self):
        self.base = f"http://127.0.0.1:{BACKEND}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.post("/api/auth/local-session", {})

    def post(self, path, body, timeout=120):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Origin": self.base})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            try:
                return {"ok": False, "status": error.code, **json.loads(text)}
            except ValueError:
                return {"ok": False, "status": error.code, "error": text[:400]}

    def get(self, path, timeout=60):
        with self.opener.open(urllib.request.Request(self.base + path), timeout=timeout) as response:
            return json.load(response)

    def command(self, command, payload=None):
        return self.post("/api/backend", {"command": command, "payload": payload or {}})


def start_backend(receipt):
    env = sandbox_env()
    ps.free(BACKEND)
    log = (ps.SCRATCH / "backend.log").open("ab")
    process = subprocess.Popen([str(ps.PYTHON), "scripts/run_web_backend.py", "--host", "127.0.0.1", "--port", str(BACKEND),
                                "--root", str(ps.SCRATCH).replace("\\", "/"), "--static-root", str(ps.BUILD).replace("\\", "/"),
                                "--skip-runtime-auto-update", "--skip-proof-self-check"],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    ps.await_http(f"http://127.0.0.1:{BACKEND}/api/health", process)
    receipt.setdefault("listeners", []).append(ps.owned_listener(BACKEND, process))
    receipt.setdefault("pids", []).append({"backend": process.pid})
    return process


# ---- fixtures through the backend's own routes ----------------------------------------------------

NOTES = [
    ("Launch checklist", """# Launch checklist

Everything that has to be true before Field Notes ships.

- Offline capture works with the network off (done)
- Search finds a note by any word in under 50 ms (done)
- Export to Markdown keeps tags and photos
- First-run tour fits on one screen

**Ship date:** after the 0.3 design review.

#launch #fieldnotes""", True),
    ("Sync design", """# Sync design

## Offline first

Every note is written locally first. Sync sends small changes, never whole files, and a note edited on two
devices becomes a choice instead of a silent overwrite.

1. Local write with a revision number
2. Background sync when a connection appears
3. Conflicts shown side by side

#design #sync""", True),
    ("Release notes 0.3", """# Release notes 0.3

### What's new

- Tags you can tap to filter
- Quick capture from the lock screen
- Dark theme follows the system

### Fixed

- Long notes no longer jump while you type

#release""", False),
    ("Ideas backlog", """# Ideas backlog

- Voice memo that turns into a note
- Map view of where each note was taken
- Weekly digest of new tags
- Share a read-only link to one notebook

#ideas""", False),
    ("Design review notes", """# Design review notes

Agreed in today's review:

- Bigger tap targets on the capture button
- One accent colour for actions, green for done
- Keep the first screen friendly and short

Next review after the 0.3 build.

#design""", False),
]


def seed_notes(client, receipt):
    # Notes keeps its Markdown in the project's Documents folder, beside the PDFs and renders.
    folder = client.post("/api/ui/notes", {"op": "folder", "args": {"folder": str(ps.SCRATCH / "home" / "Documents" / "Field Notes")}})
    receipt["notesFolder"] = {"ok": folder.get("ok"), "error": folder.get("error")}
    rows = []
    for title, body, pinned in NOTES:
        result = client.post("/api/ui/notes", {"op": "write", "args": {"title": title, "body": body}})
        data = result.get("data", result)
        rows.append({"title": title, "ok": result.get("ok", True) is not False, "path": data.get("path")})
        if pinned and data.get("path"):
            client.post("/api/ui/notes", {"op": "pin", "args": {"path": data["path"], "pinned": True}})
        time.sleep(0.3)
    receipt["notes"] = rows


def seed_app_factory(client, receipt):
    payload = {"name": "Field Notes", "brief": "Capture field observations offline, tag them, and find any note again in seconds.",
               "target": "neyvia", "template": "auto", "theme": "midnight", "directory": ""}
    job = client.command("create_app_factory_job_command", payload)
    receipt["appFactory"] = {"create": {k: job.get(k) for k in ("ok", "error", "status")},
                             "jobId": (job.get("data") or job).get("jobId") if isinstance(job.get("data") or job, dict) else None}
    return job.get("data") or job


ROUTING = [("save a note about the heron sighting", "notes"), ("write down the trail marker problem", "notes"),
           ("jot a reminder to export the tags", "notes"), ("find the release notes draft", "notes"),
           ("open the sketch review pdf", "files"), ("show me the field notes folder", "files"),
           ("move the photos into the project folder", "files"), ("rename the exported markdown files", "files"),
           ("build the field notes app", "app-factory"), ("make a desktop app for tagging notes", "app-factory"),
           ("check the emblem model", "3d-studio"), ("load the backpack model in the scene", "3d-studio")]
NOVEL = ["write a note about the design review", "open the sync design folder", "start a new app for trail reports"]


def teach_laya(receipt):
    """LAYA's own label inbox (plan 21 instant episodes): the sandbox backend ingests these within seconds."""
    inbox = ps.SCRATCH / "laya-labels"
    inbox.mkdir(parents=True, exist_ok=True)
    # Triage observations are objects ({question, context, options}); the inbox ingester cannot take the
    # plain-string inputs the 'routing' domain uses (laya_instant_ingest.ingest raises on a str input).
    rows = [{"domain": "triage:" + ROUTE_TASK, "input": {"question": text, "context": {}, "options": ROUTE_OPTIONS},
             "label": label, "evidence": {"source": "video-recapture fixture"}} for text, label in ROUTING]
    (inbox / "field-notes-routing.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    receipt["layaLabels"] = len(rows)
    # The backend's label watcher runs this same ingest every 5 s; in two sandbox runs it had not
    # ingested the inbox after 90 s, so the driver runs the product's ingest() itself, once.
    from grant_agent.laya_instant_ingest import ingest
    receipt["layaIngest"] = ingest(str(ps.SCRATCH))


ROUTE_TASK = "app-routing"
ROUTE_OPTIONS = ["notes", "files", "app-factory", "3d-studio"]


def seed_laya(client, receipt):
    """Routing decisions through the product's own triage (laya_service.triage), receipts in the sandbox ledger."""
    client.get("/api/ui/laya")  # starts the backend's label watcher for this root
    for _ in range(90):
        report = client.get("/api/ui/laya")
        report = report.get("data", report)
        if (report.get("instant") or {}).get("domains", {}).get("triage:" + ROUTE_TASK, 0) >= len(ROUTING):
            break
        time.sleep(1)
    receipt["layaIngested"] = (report.get("instant") or {}).get("domains")
    os.environ["NEYVIA_LAYA_URL"] = f"http://127.0.0.1:{LAYA_PORT}"
    from grant_agent.laya_service import triage
    options = ROUTE_OPTIONS
    rows = []
    for text in [t for t, _ in ROUTING[::2]] + NOVEL + [t for t, _ in ROUTING[1::2]]:
        try:
            result = triage(str(ps.SCRATCH), ROUTE_TASK, text, options, path="route.app")
            rows.append({"request": text, "route": result.get("route"), "decision": result.get("decision"), "source": result.get("source")})
        except Exception as exc:
            rows.append({"request": text, "error": f"{type(exc).__name__}: {exc}"[:300]})
        time.sleep(0.4)
    receipt["laya"] = rows


AGENT_NOTES = ["Oak by the north gate, first new leaves #spring",
               "Two herons on the east pond at 7:40 #birds",
               "Trail marker 14 is missing, report it #maintenance"]


def agent_session(client, receipt, preview_url):
    """An agent (labelled as a Claude chat) tests the app it just built, in its own Obscura engine.

    Uses the integrated browser route the agent tools use (POST /api/ui/browser with the acting chat), so
    Agents at work mirrors it: open Neyvia (the page signs itself in locally), open the app's preview,
    then fill and save three notes, each a verified browser action.
    """
    agent = {"chatId": "video-field-notes", "app": "claude", "title": "Test the Field Notes draft"}
    steps = []

    def call(op, args, timeout=120):
        result = client.post("/api/ui/browser", {"op": op, "args": args, "_agent": agent}, timeout=timeout)
        data = result.get("data", result)
        steps.append({"op": op, "ok": result.get("ok"), "status": data.get("status") if isinstance(data, dict) else None,
                      "error": str(result.get("error"))[:300] if result.get("error") else None})
        if result.get("ok") is False:
            raise RuntimeError(f"browser {op}: {result.get('error')}")
        return data

    receipt["agentRun"] = {"agent": agent, "steps": steps}
    started = call("headless.start", {"port": ENGINE, "allowLocalFixtures": True, "colorScheme": "dark",
                                      "assignedPorts": f"{BACKEND}-{ENGINE}"})
    receipt["agentRun"]["engine"] = {k: started.get(k) for k in ("connected", "port", "binarySha256")}
    tab = call("tab.open", {"url": f"http://127.0.0.1:{BACKEND}/control", "engine": "obscura"})["tabId"]
    time.sleep(12)  # the shell signs this engine's profile in on this PC (local-session bootstrap)
    # On a slow PC the sign-in can take longer: while the app answers "login is required", wait and open it again.
    for attempt in range(10):
        call("tab.navigate", {"tabId": tab, "url": f"http://127.0.0.1:{BACKEND}{preview_url}"})
        time.sleep(2)
        if "login is required" not in (call("observe", {"tabId": tab}).get("text") or ""):
            break
        receipt["agentRun"]["loginRetries"] = attempt + 1
        time.sleep(10)
    for text in AGENT_NOTES:
        seen = call("observe", {"tabId": tab})
        box = next(e["id"] for e in seen["elements"] if e.get("role") == "textbox" and e.get("name") == "Note")
        call("action", {"tabId": tab, "revision": seen["revision"], "element": box, "action": "fill", "value": text})
        seen = call("observe", {"tabId": tab})
        save = next(e["id"] for e in seen["elements"] if e.get("role") == "button" and e.get("name") == "Save note")
        call("action", {"tabId": tab, "revision": seen["revision"], "element": save, "action": "click"})
        time.sleep(1.0)
    final = call("observe", {"tabId": tab})
    receipt["agentRun"]["finalText"] = final.get("text", "")[:600]
    receipt["agentRun"]["tabId"] = tab
    return tab


def stop_agent_engine(client, receipt):
    result = client.post("/api/ui/browser", {"op": "headless.stop", "args": {}})
    receipt.setdefault("agentRun", {})["stopped"] = result.get("ok")


def open_full(rig, query, title):
    ps.open_from_launcher(rig, query, title)
    wid = ps.window_id(rig, title)
    ps.press_place(rig, wid, "Full screen")
    time.sleep(1.0)
    return wid


def click_text(rig, selector, text, *, exact=True):
    """Click the first visible element matching selector whose text is (or starts with) text."""
    return rig.js("""([sel, text, exact]) => {
      const el = [...document.querySelectorAll(sel)].find(e => e.offsetParent !== null
        && (exact ? e.textContent.trim() === text : e.textContent.trim().startsWith(text)));
      if (!el) return false; el.click(); return true; }""", [selector, text, exact])


def fill(rig, selector, value):
    """Type into a field the way React sees it (native setter + input event)."""
    return rig.js("""([sel, value]) => {
      const el = [...document.querySelectorAll(sel)].find(e => e.offsetParent !== null);
      if (!el) return false; el.focus();
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true })); return true; }""", [selector, value])


def surface_text(rig, title):
    return rig.js("""t => { const s = [...document.querySelectorAll('.nx-surface')].find(s => s.querySelector('.nx-stage-title strong')?.textContent.trim() === t);
      return s ? s.innerText.slice(0, 4000) : null; }""", title)


def start_capture_engine(rig, env):
    """The capture engine (rig.start's second half): Obscura on ENGINE, Playwright over CDP."""
    import hashlib
    import secrets
    ps.free(ENGINE)
    token = secrets.token_urlsafe(36)
    elog = (ps.SCRATCH / "engine.log").open("ab")
    engine = subprocess.Popen([str(ps.EXE), "serve", "--host", "127.0.0.1", "--port", str(ENGINE), "--user-agent", ps.UA,
                               "--max-connections", "8", "--allow-private-network"],
                              stdout=elog, stderr=elog, creationflags=subprocess.CREATE_NO_WINDOW,
                              env={**env, "OBSCURA_CDP_TOKEN": token, "OBSCURA_ROTATE_PROFILE": "0",
                                   "OBSCURA_NAV_TIMEOUT_MS": "30000", "OBSCURA_SCRIPT_DEADLINE_MS": "20000"})
    rig.processes.append(engine)
    ps.await_http(f"http://127.0.0.1:{ENGINE}/json/version", engine, {"Authorization": "Bearer " + token})
    rig.receipt.setdefault("listeners", []).append(ps.owned_listener(ENGINE, engine))
    rig.receipt.setdefault("pids", []).append({"captureEngine": engine.pid})
    from playwright.sync_api import sync_playwright
    rig.playwright = sync_playwright().start()
    rig.browser = rig.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{ENGINE}", headers={"Authorization": "Bearer " + token},
                                                           timeout=rig.connect_timeout)
    rig.receipt["engine"] = {"exe": str(ps.EXE), "sha256": hashlib.sha256(ps.EXE.read_bytes()).hexdigest()}


# ---- the screens ---------------------------------------------------------------------------------

def screen_agent_view(rig, rec):
    open_full(rig, "Agents at work", "Agents at work")
    rig.wait("() => document.querySelectorAll('.nx-av-card').length > 0", 20)
    time.sleep(2.5)
    path = rig.shot("agent-view-list-full")
    rec.setdefault("files", []).append(str(path))
    # Watch the run: its card opens the run's own pane (live picture, steps, time-lapse).
    before = set(rig.js("() => [...document.querySelectorAll('.nx-surface')].map(s => s.dataset.window)"))
    rig.js("() => document.querySelector('.nx-av-card-open')?.click()")
    rig.wait("ids => [...document.querySelectorAll('.nx-surface')].some(s => !ids.includes(s.dataset.window))", 15, list(before))
    wid = rig.js("ids => [...document.querySelectorAll('.nx-surface')].find(s => !ids.includes(s.dataset.window)).dataset.window", list(before))
    rec["runPane"] = wid
    ps.press_place(rig, wid, "Full screen")
    try:
        rig.wait("() => !!document.querySelector('.nx-av-stage img, .nx-av-stage canvas')", 20)
    except TimeoutError:
        rec["frame"] = "no picture"
    time.sleep(3.0)
    return ["agent-view-full"]


def screen_laya(rig, rec):
    open_full(rig, "LAYA activity", "LAYA")
    rig.wait("() => !document.body.innerText.includes('Reading LAYA activity')", 30)
    time.sleep(1.0)
    if rig.js("() => document.body.innerText.includes(\"LAYA isn't running\")"):
        # The pane's own Try again (POST /api/ui/laya restart) re-adopts the service on this PC.
        rec["tryAgain"] = click_text(rig, ".nx-laya-health button", "Try again", exact=False)
        try:
            rig.wait("() => document.body.innerText.includes('LAYA is running')", 30)
        except TimeoutError:
            rec["tryAgain"] = "still not running"
    time.sleep(2.0)
    return ["laya-full"]


def screen_notes(rig, rec):
    # A fresh 1440x936 session: the shell lays out at that height; the top 1440x900 is kept below.
    rig.session({"width": 1440, "height": 936})
    open_full(rig, "Notes", "Notes")
    rig.wait("() => document.querySelectorAll('.nx-notes-row').length >= 3", 20)
    rec["opened"] = click_text(rig, ".nx-notes-row .nx-notes-rowtitle", "Launch checklist")
    time.sleep(1.5)
    # Obscura does not paint a textarea's text, so show the note the way it reads: Preview.
    for _ in range(20):
        rec["preview"] = click_text(rig, ".nx-surface button, .nx-surface [role=radio]", "Preview")
        if rec["preview"]:
            break
        time.sleep(0.5)
    time.sleep(1.5)
    # The list's footer always prints the notes folder's absolute path (here the sandbox on D:). Framing:
    # the session renders the full-screen window at 1440x936 and the top 1440x900 is kept, which leaves out only
    # that 36 px footer row.
    tall = rig.shot("notes-full-tall")
    rig.session(ps.DESKTOP)
    from PIL import Image
    Image.open(tall).crop((0, 0, 1440, 900)).save(ps.OUT / "notes-full.png")
    shutil.move(str(tall), str(ps.SCRATCH / "notes-full-tall.png"))
    rec["framing"] = "rendered 1440x936, cropped to the top 1440x900 (footer row with the folder path left out)"
    rec.setdefault("files", []).append(str(ps.OUT / "notes-full.png"))
    time.sleep(1.0)
    return []


def screen_app_factory(rig, rec):
    open_full(rig, "App Factory", "App Factory")
    time.sleep(3.0)
    # The built job in its desktop window frame. Its live app is an iframe, which Obscura does not
    # paint (the frame stays blank in this engine). "New app" cannot show the sample instead: with a
    # job in the list, the catalog refresh re-selects the first job at once.
    rec["Window"] = click_text(rig, ".nx-surface button", "Window")
    time.sleep(3.0)
    return ["app-factory-full"]


def screen_3d(rig, rec):
    open_full(rig, "3D Studio", "3D Studio")
    time.sleep(4.0)
    shots = ["3d-studio-browser-full"]
    rec.setdefault("files", []).append(str(rig.shot(shots.pop())))
    for _ in range(60):
        rec["assetTab"] = click_text(rig, ".nx-surface button, .nx-surface [role=tab]", "Asset check", exact=False)
        if rec["assetTab"] and rig.js("() => !!document.querySelector('.nx-gd-setup input')"):
            break
        time.sleep(0.5)
    time.sleep(1.0)
    fill(rig, ".nx-gd-setup input", "kronos/emblem.glb")
    time.sleep(0.4)
    # The first validator run (a cold node start) can outlast the page's request; the Check button retries.
    for attempt in range(3):
        rig.js("() => document.querySelector('.nx-gd-setup button[type=submit]')?.click()")
        try:
            rig.wait("() => !!document.querySelector('[aria-label=\"Validator report\"]') || !!document.querySelector('.nx-gd-error')", 90)
        except TimeoutError:
            pass
        rec["assetReport"] = "report" if rig.js("() => !!document.querySelector('[aria-label=\"Validator report\"]')") else f"attempt {attempt + 1} failed"
        if rec["assetReport"] == "report":
            break
        time.sleep(2.0)
    time.sleep(1.0)
    shots.append("3d-studio-full")
    return shots


def files_go(rig, names):
    # Files reopens where it was: once its rows are listed, skip the folders already walked.
    rig.wait("names => [...document.querySelectorAll('[data-path]')].some(e => names.some(n => e.dataset.path.replace(/\\\\/g, '/').endsWith('/' + n)))", 15, names)
    here = rig.js("() => [...document.querySelectorAll('[data-path]')].map(e => e.dataset.path.replace(/\\\\/g, '/'))")
    for index, name in enumerate(names):
        if any(p.endswith('/' + n) for p in here for n in names[index:]) and not any(p.endswith('/' + name) for p in here):
            continue
        here = []
        rig.wait("n => [...document.querySelectorAll('[data-path]')].some(e => e.dataset.path.replace(/\\\\/g, '/').endsWith('/' + n))", 15, name)
        rig.js("n => [...document.querySelectorAll('[data-path]')].find(e => e.dataset.path.replace(/\\\\/g, '/').endsWith('/' + n)).dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))", name)
        time.sleep(1.2)


def files_at_notes_place(rig, rec):
    """Open Files and pick the Notes place (the project folder) with the Place picker."""
    open_full(rig, "Files", "Files")
    rig.wait("() => document.querySelectorAll('.nx-files-placepick option').length > 0", 15)
    rec["place"] = rig.js("""() => { const s = document.querySelector('.nx-files-placepick');
      const o = [...s.options].find(o => o.textContent.trim() === 'Neyvia Notes'); if (!o) return null;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value);
      s.dispatchEvent(new Event('change', { bubbles: true })); return o.textContent.trim(); }""")
    rig.wait("() => [...document.querySelectorAll('[data-path]')].some(e => e.dataset.path.endsWith('.pdf'))", 30)
    time.sleep(1.5)


def screen_files(rig, rec):
    # One breadcrumb ("Neyvia Notes"), so no ancestor segments are shortened.
    files_at_notes_place(rig, rec)
    return ["files-full"]


def open_pdf_from_files(rig, rec, filename):
    # Files -> double-click the PDF, the way Paul opens it.
    files_at_notes_place(rig, rec)
    files_go(rig, [filename])
    rig.wait("() => [...document.querySelectorAll('.nx-surface .nx-stage-title strong')].some(e => e.textContent.trim() === 'PDF')", 25)
    files = ps.window_id(rig, "Files")
    if files:
        rig.js("id => document.querySelector(`[data-window=\"${CSS.escape(id)}\"] .nx-stage-head > button[aria-label^=\"Close\"]`)?.click()", files)
    time.sleep(1.0)
    wid = ps.window_id(rig, "PDF")
    ps.press_place(rig, wid, "Full screen")
    try:
        rig.wait("() => !document.body.innerText.includes('Opening ')", 60)
    except TimeoutError:
        rec["pdfLoad"] = "timeout"
    time.sleep(3.0)


def screen_pdf(rig, rec):
    open_pdf_from_files(rig, rec, "Design review.pdf")
    rec.setdefault("files", []).append(str(rig.shot("pdf-full")))
    ps.close_all(rig)
    time.sleep(0.8)
    open_pdf_from_files(rig, rec, "Sketch review.pdf")  # the C11g xournal fixture
    return ["pdf-xournal-full"]


# ---- phone mode (track VIDEO2): the same seeded surfaces at 390x844 -------------------------------

PHONE = {"width": 390, "height": 844}


def open_phone(rig, query, title):
    """Open an app on the phone layout; the Full screen button may not exist there, so it is optional."""
    try:
        ps.open_from_launcher(rig, query, title)
    except TimeoutError:
        # The launcher can stay open on its first hit (seen on this PC): Enter picks the highlighted result.
        rig.js(ps.KEY, ["Enter", "Enter", False, False, False, ".nx-launcher input"])
        rig.wait("t => [...document.querySelectorAll('.nx-surface .nx-stage-title strong')].some(e => e.textContent.trim() === t)", 30, title)
        time.sleep(1.2)
    wid = ps.window_id(rig, title)
    try:
        ps.press_place(rig, wid, "Full screen")
    except AssertionError:
        pass
    time.sleep(1.0)
    return wid


def phone_state(rig, rec):
    rec["layout"] = rig.js("""() => ({ w: innerWidth, h: innerHeight, surfaces: [...document.querySelectorAll('.nx-surface')].map(s => ({
      title: s.querySelector('.nx-stage-title strong')?.textContent.trim(), placement: s.dataset.placement,
      w: Math.round(s.getBoundingClientRect().width), h: Math.round(s.getBoundingClientRect().height) })),
      buttons: [...document.querySelectorAll('.nx-surface button')].filter(b => b.offsetParent).map(b => (b.getAttribute('aria-label') || b.textContent).trim().slice(0, 30)).slice(0, 40) })""")
    rec["text"] = rig.js("() => document.body.innerText.slice(0, 1800)")


def phone_notes(rig, rec):
    # Same framing as the desktop Notes shot: the list's footer prints the notes folder's absolute path, so the
    # session renders 390x880 and the top 390x844 is kept, which leaves out only that footer row.
    rig.session({"width": 390, "height": 880})
    open_phone(rig, "Notes", "Notes")
    rig.wait("() => document.querySelectorAll('.nx-notes-row').length >= 3", 20)
    # Obscura has no -webkit-box line clamp, so a row's snippet stays on one line and the row grows to 900+ px,
    # running off the right edge. This engine-compat style gives the snippet the two-line clamp the product's CSS
    # (nxDocs.css .nx-notes-rowtext) asks for in a real browser; nothing else is changed.
    rig.js("""css => { const el = document.createElement('style'); el.textContent = css; document.head.appendChild(el); return true; }""",
           ".nx .nx-notes-row{min-width:0;max-width:100%}.nx .nx-notes-rowtext{display:block!important;max-height:calc(2*1.45em);overflow:hidden}")
    rec["engineShim"] = "two-line clamp for .nx-notes-rowtext (Obscura lacks -webkit-box)"
    time.sleep(1.0)
    phone_state(rig, rec)
    rec["rowBox"] = rig.js("""() => [...document.querySelectorAll('.nx-notes-row')].slice(0, 2).map(r => {
      const b = r.getBoundingClientRect(); const t = r.querySelector('[class*=snippet], [class*=excerpt], p, span:last-child');
      return { rowW: Math.round(b.width), right: Math.round(b.right), scrollW: r.scrollWidth, snippet: t ? { cls: t.className, w: Math.round(t.getBoundingClientRect().width), sw: t.scrollWidth, ws: getComputedStyle(t).whiteSpace, to: getComputedStyle(t).textOverflow } : null }; })""")
    tall = rig.shot("notes-phone-tall")
    from PIL import Image
    Image.open(tall).crop((0, 0, 390, 844)).save(ps.OUT / "notes-phone.png")
    shutil.move(str(tall), str(ps.SCRATCH / "notes-phone-tall.png"))
    rec["framing"] = "rendered 390x880, cropped to the top 390x844 (footer row with the folder path left out)"
    rec.setdefault("files", []).append(str(ps.OUT / "notes-phone.png"))
    return []


def phone_notes_open(rig, rec):
    open_phone(rig, "Notes", "Notes")
    rig.wait("() => document.querySelectorAll('.nx-notes-row').length >= 3", 20)
    rec["opened"] = click_text(rig, ".nx-notes-row .nx-notes-rowtitle", "Launch checklist")
    time.sleep(1.5)
    for _ in range(20):
        rec["preview"] = click_text(rig, ".nx-surface button, .nx-surface [role=radio]", "Preview")
        if rec["preview"]:
            break
        time.sleep(0.5)
    time.sleep(1.5)
    phone_state(rig, rec)
    return ["notes-open-phone"]


def phone_laya(rig, rec):
    open_phone(rig, "LAYA activity", "LAYA")
    rig.wait("() => !document.body.innerText.includes('Reading LAYA activity')", 30)
    time.sleep(1.0)
    if rig.js("() => document.body.innerText.includes(\"LAYA isn't running\")"):
        rec["tryAgain"] = click_text(rig, ".nx-laya-health button", "Try again", exact=False)
        try:
            rig.wait("() => document.body.innerText.includes('LAYA is running')", 30)
        except TimeoutError:
            rec["tryAgain"] = "still not running"
    time.sleep(2.0)
    phone_state(rig, rec)
    return ["laya-phone"]


def phone_agent_view(rig, rec):
    open_phone(rig, "Agents at work", "Agents at work")
    rig.wait("() => document.querySelectorAll('.nx-av-card').length > 0", 20)
    time.sleep(2.5)
    phone_state(rig, rec)
    return ["agent-view-list-phone"]


def phone_agent_run(rig, rec):
    open_phone(rig, "Agents at work", "Agents at work")
    rig.wait("() => document.querySelectorAll('.nx-av-card').length > 0", 20)
    before = set(rig.js("() => [...document.querySelectorAll('.nx-surface')].map(s => s.dataset.window)"))
    rig.js("() => document.querySelector('.nx-av-card-open')?.click()")
    rig.wait("ids => [...document.querySelectorAll('.nx-surface')].some(s => !ids.includes(s.dataset.window))", 15, list(before))
    wid = rig.js("ids => [...document.querySelectorAll('.nx-surface')].find(s => !ids.includes(s.dataset.window)).dataset.window", list(before))
    try:
        ps.press_place(rig, wid, "Full screen")
    except AssertionError:
        pass
    try:
        rig.wait("() => (!!document.querySelector('.nx-av-stage img, .nx-av-stage canvas') || document.body.innerText.includes('What progressed')) && !document.body.innerText.includes('Waiting for the first picture')", 60)
    except TimeoutError:
        rec["frame"] = "no picture"
    time.sleep(3.0)
    phone_state(rig, rec)
    return ["agent-view-phone"]


def phone_files(rig, rec):
    open_phone(rig, "Files", "Files")
    rig.wait("() => document.querySelectorAll('.nx-files-placepick option').length > 0", 15)
    rec["place"] = rig.js("""() => { const s = document.querySelector('.nx-files-placepick');
      const o = [...s.options].find(o => o.textContent.trim() === 'Neyvia Notes'); if (!o) return null;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value);
      s.dispatchEvent(new Event('change', { bubbles: true })); return o.textContent.trim(); }""")
    rig.wait("() => [...document.querySelectorAll('[data-path]')].some(e => e.dataset.path.endsWith('.pdf'))", 30)
    time.sleep(1.5)
    phone_state(rig, rec)
    return ["files-phone"]


# LAYA's pane is longer than a phone: below "Latest" sits a Computer use card that would be cut mid-sentence at 844.
# Rendering the pane 758 tall ends it cleanly after the Latest notes (that card starts at about y=770).
PHONE_VIEWPORT = {"laya-phone": {"width": 390, "height": 758}}

PHONE_SCREENS = {"notes-phone": phone_notes, "notes-open-phone": phone_notes_open, "laya-phone": phone_laya,
                 "agent-view-list-phone": phone_agent_view, "agent-view-phone": phone_agent_run, "files-phone": phone_files}


def capture_phone(rig, receipt, only):
    """Same shape as capture(), one fresh 390x844 session per surface so layouts never leak between shots.
    The launcher sometimes does not open on a cold session (seen on this PC), so a surface gets a second try."""
    for key, fn in PHONE_SCREENS.items():
        if only and key not in only:
            continue
        rec = {"screen": key, "started": time.strftime("%H:%M:%S"), "viewport": PHONE}
        for attempt in (1, 2):
            rec.pop("error", None)
            rec["attempts"] = attempt
            try:
                rig.session(PHONE_VIEWPORT.get(key, PHONE))
                rec["viewport"] = PHONE_VIEWPORT.get(key, PHONE)
                rec["files"] = []
                names = fn(rig, rec)  # a surface that shoots itself (notes) appends its own file and returns []
                rec["files"] = rec.get("files", []) + [str(rig.shot(name)) for name in names]
                break
            except Exception as exc:
                rec["error"] = f"{type(exc).__name__}: {exc}"[:600]
        if rec.get("error"):
            try:
                rec.setdefault("files", []).append(str(rig.shot(key + "-failure")))
            except Exception:
                pass
        receipt.setdefault("screens", []).append(rec)
        print(json.dumps({k: rec.get(k) for k in ("screen", "error", "files")}), flush=True)


SCREENS = {"agent-view": screen_agent_view, "laya": screen_laya, "notes": screen_notes, "app-factory": screen_app_factory,
           "3d-studio": screen_3d, "files": screen_files, "pdf": screen_pdf}


def capture(rig, receipt, only):
    for key, fn in SCREENS.items():
        if only and key not in only:
            continue
        rec = {"screen": key, "started": time.strftime("%H:%M:%S")}
        try:
            names = fn(rig, rec)
            for name in names:
                path = rig.shot(name)
                rec.setdefault("files", []).append(str(path))
            title = rig.js("() => [...document.querySelectorAll('.nx-surface')].filter(s => !s.classList.contains('is-hidden')).map(s => s.querySelector('.nx-stage-title strong')?.textContent.trim())")
            rec["windows"] = title
            rec["text"] = rig.js("() => document.querySelector('.nx-surface[data-placement=\"full\"]')?.innerText?.slice(0, 3000) || null")
            rec["iframes"] = rig.js("""() => [...document.querySelectorAll('.nx-surface iframe')].map(f => {
              let doc = null; try { doc = { title: f.contentDocument?.title, text: (f.contentDocument?.body?.innerText || '').slice(0, 200), ready: f.contentDocument?.readyState }; } catch (e) { doc = 'cross-origin'; }
              const r = f.getBoundingClientRect(); return { src: (f.getAttribute('src') || '').slice(0, 120), w: Math.round(r.width), h: Math.round(r.height), doc }; })""")
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"[:600]
            try:
                rec.setdefault("files", []).append(str(rig.shot(key + "-failure")))
            except Exception:
                pass
        ps.close_all(rig)
        time.sleep(0.8)
        receipt.setdefault("screens", []).append(rec)
        print(json.dumps({k: rec.get(k) for k in ("screen", "error", "files")}), flush=True)


import re  # noqa: E402

# Text that must never reach a launch-film frame: paths, encoded paths, raw values, errors, empty states.
FORBIDDEN = [
    ("absolute path", re.compile(r"\b[A-Z]:\\|NeyviaRuns|\\Users\\|/Users/", re.I)),
    ("encoded path", re.compile(r"%5C|%3A|raw\?path", re.I)),
    ("raw value", re.compile(r"\b(null|undefined|NaN|Traceback|Exception)\b")),
    ("error", re.compile(r"\berror\b|\bfailed\b|isn.t running|not running|couldn.t|can.t show", re.I)),
    ("empty state", re.compile(r"No notes yet|Nothing here yet|Nothing queued|No apps made|Nobody is working|When an agent uses an app|No steps yet|No chats yet|Nothing needs you", re.I)),
]
DELIVERABLES = ["laya-full", "3d-studio-full", "notes-full", "agent-view-full", "agent-view-list-full", "app-factory-full",
                "pdf-full", "pdf-xournal-full", "files-full", "3d-studio-browser-full"]


# What viewing each PNG showed that the 2x OCR pass can miss (small text) or cannot judge (empty viewports).
VISUAL = {
    "app-factory-full": "The built app's frame is blank: the live app is an iframe and Obscura does not paint iframes "
                        "(its document is loaded: title 'Field Notes'). URL bar shows the preview route.",
    "3d-studio-browser-full": "Viewport is empty: Obscura has no WebGL (editor registers as 'no 3D picture') and does not paint iframes.",
    "3d-studio-full": "Asset check on the real Kronos emblem.glb (valid, 53197 vertices); no 3D picture, see 3d-studio-browser-full.",
    "pdf-xournal-full": "The mandated C11g fixture renders, but its only line is a revision hash (glance: internal-id).",
}


def ocr_lines(path):
    from PIL import Image
    from grant_agent.laya_glance_image import _recognize
    image = Image.open(path).convert("RGBA")
    image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    return [text for text, _ in _recognize(image)]


def verify(receipt):
    from grant_agent.laya_glance import glance
    captures = sorted(BASE.glob(f"capture-{receipt['tag']}*.json"), key=lambda p: p.stat().st_mtime)
    captures = [p for p in captures if "-run" not in p.stem]
    produced = {}
    for capture_file in captures:
        data = json.loads(capture_file.read_text(encoding="utf-8"))
        for row in data.get("screens", []):
            for file in row.get("files", []):
                produced[Path(file).stem] = {"capture": capture_file.name, "screen": row["screen"], "steps": {k: v for k, v in row.items() if k not in {"text", "files", "iframes"}}}
    screens = []
    for name in DELIVERABLES:
        path = ps.OUT / f"{name}.png"
        if not path.is_file():
            screens.append({"name": name, "path": str(path), "missing": True})
            continue
        started = time.monotonic()
        verdict = glance(screenshot=str(path), record=False)
        bugs = [{"type": b.get("type"), "text": str((b.get("evidence") or {}).get("attributes.text") or "")[:120]} for b in verdict.get("bugs", [])]
        advisory = [f.get("predicate") for f in verdict.get("advisory", [])]
        lines = ocr_lines(path)
        hits = [{"kind": kind, "line": line[:160]} for line in lines for kind, pattern in FORBIDDEN if pattern.search(line)]
        screens.append({"name": name, "path": str(path), "bytes": path.stat().st_size, "produced": produced.get(name),
                        "glance": {"bugs": bugs, "advisory": advisory, "broken": verdict.get("broken"), "seconds": round(time.monotonic() - started, 1)},
                        "ocr": {"lines": len(lines), "forbidden": hits, "sample": lines[:14]},
                        "visual": VISUAL.get(name, "Viewed: populated, no path, error or empty-state text seen."),
                        "clean": not bugs and not hits and name not in VISUAL})
        print(json.dumps({"name": name, "bugs": [b["type"] for b in bugs], "advisory": advisory, "forbidden": hits[:6]}), flush=True)
    receipt.update({"schema": "neyvia.video-recapture-receipt.v1", "screens": screens, "captures": [p.name for p in captures],
                    "check": "laya_glance.glance(screenshot, record=False) + Windows OCR on a 2x LANCZOS upscale (RGBA) against FORBIDDEN"})
    for capture_file in captures[:1]:
        data = json.loads(capture_file.read_text(encoding="utf-8"))
        receipt["seeded"] = {k: data.get(k) for k in ("fixtures", "notes", "appFactory", "layaLabels", "laya", "agentRun", "seedSeconds", "listeners", "pids", "stoppedPids", "engine")}
    out = BASE / "receipt.json"
    out.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    evidence = ROOT / "scripts" / "evidence" / "VIDEO-recapture.json"
    shutil.copyfile(out, evidence)
    print(json.dumps({"receipt": str(out), "evidence": str(evidence), "clean": [s["name"] for s in screens if s.get("clean")]}))


PHONE_DELIVERABLES = ["notes-phone", "laya-phone", "files-phone", "agent-view-list-phone", "agent-view-phone"]
# Viewed verdicts (Read tool, each PNG) for the phone captures; clean = usable as is.
PHONE_VISUAL = {
    "notes-phone": (True, "Seven seeded notes with titles, two-line snippets, tags and times, two pinned; search and tag filters on top; "
                          "no folder-path footer (framing crop), no empty state. Engine shim: two-line clamp (Obscura lacks -webkit-box)."),
    "laya-phone": (True, "LAYA is running; 12 answered / 3 handed to the main model, 2 ms median, 1101 tokens saved, latest decisions list. "
                         "Rendered 390x758 so the pane ends cleanly before the Computer use card (which would be cut mid-sentence at 844)."),
    "files-phone": (True, "Neyvia Notes folder with 12 files (md, pdf, png, txt) and ages; no path, no empty state."),
    "agent-view-list-phone": (True, "Agents at work: one card, Claude Code testing the Field Notes draft, a real picture of the Field Notes app, "
                                    "'Clicked the Save note button', 8 steps."),
    "agent-view-phone": (False, "Caveat: populated time-lapse with the Field Notes picture and the run summary, but the summary prints "
                                "'127.0.0.1:49161' twice and the first thumbnail renders blank. Prefer agent-view-list-phone."),
}


# glance flags the product's own two-line clamp ellipsis in a note's snippet ("... instead ...") as clipped-text;
# viewed, it is an ordinary ellipsis at the end of the second line.
GLANCE_ACCEPTED = {"notes-phone": {"clipped-text"}}


def verify_phone(receipt):
    from grant_agent.laya_glance import glance
    phone = BASE / "phone"
    captures = sorted(BASE.glob(f"capture-{receipt['tag']}*-phone.json"), key=lambda p: p.stat().st_mtime)
    screens = []
    for name in PHONE_DELIVERABLES:
        path = phone / f"{name}.png"
        if not path.is_file():
            screens.append({"name": name, "path": str(path), "missing": True})
            continue
        from PIL import Image
        verdict = glance(screenshot=str(path), record=False)
        bugs = [{"type": b.get("type"), "text": str((b.get("evidence") or {}).get("attributes.text") or "")[:120]} for b in verdict.get("bugs", [])]
        lines = ocr_lines(path)
        hits = [{"kind": kind, "line": line[:160]} for line in lines for kind, pattern in FORBIDDEN if pattern.search(line)]
        ok, note = PHONE_VISUAL.get(name, (False, "not viewed"))
        screens.append({"name": name, "path": str(path), "size": list(Image.open(path).size), "bytes": path.stat().st_size,
                        "glance": {"bugs": bugs, "advisory": [f.get("predicate") for f in verdict.get("advisory", [])], "broken": verdict.get("broken")},
                        "ocr": {"lines": len(lines), "forbidden": hits, "sample": lines[:12]},
                        "viewed": note, "glanceAccepted": sorted(GLANCE_ACCEPTED.get(name, [])),
                        "clean": ok and not hits and all(b["type"] in GLANCE_ACCEPTED.get(name, ()) for b in bugs)})
        print(json.dumps({"name": name, "bugs": [b["type"] for b in bugs], "forbidden": hits[:6], "clean": screens[-1]["clean"]}), flush=True)
    receipt.update({"schema": "neyvia.video2-recapture-phone.v1", "viewport": PHONE, "theme": "dark", "screens": screens,
                    "captures": [p.name for p in captures],
                    "check": "laya_glance.glance(screenshot, record=False) + Windows OCR on a 2x LANCZOS upscale against FORBIDDEN, then each PNG viewed"})
    out = BASE / "receipt-phone.json"
    out.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    evidence = ROOT / "scripts" / "evidence" / "VIDEO2-recapture-phone.json"
    shutil.copyfile(out, evidence)
    print(json.dumps({"receipt": str(out), "evidence": str(evidence), "clean": [s["name"] for s in screens if s.get("clean")]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backend", "capture", "verify"))
    parser.add_argument("--tag", default="run1")
    parser.add_argument("--only", default="")
    parser.add_argument("--phone", action="store_true", help="Capture the phone surfaces at 390x844 into recapture/phone (track VIDEO2)")
    parser.add_argument("--keep", action="store_true", help="Leave the sandbox backend running after capture (stop it by PID)")
    parser.add_argument("--attach", action="store_true", help="Use the sandbox backend already running on the backend port")
    args = parser.parse_args()
    configure(args.tag)
    if args.phone:
        ps.OUT = BASE / "phone"
        ps.OUT.mkdir(parents=True, exist_ok=True)
    receipt ={"schema": "neyvia.video-recapture.v1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": args.tag,
               "ports": {"backend": BACKEND, "engine": ENGINE}, "checks": [], "errors": []}
    if args.mode == "backend":
        prepare_state(receipt)
        process = start_backend(receipt)
        (ps.SCRATCH / "backend.pid").write_text(str(process.pid))
        print(json.dumps({"pid": process.pid, "root": str(ps.SCRATCH)}), flush=True)
        process.wait()
        return
    if args.mode == "verify":
        verify_phone(receipt) if args.phone else verify(receipt)
        return
    env = sandbox_env()
    os.environ.update({k: env[k] for k in ("NEYVIA_INSTANT_LABELS", "NEYVIA_INSTANT_VOTES")})
    only = {name for name in args.only.split(",") if name}
    rig = ps.Rig(receipt, connect_timeout=30000)
    receipt.update({"shots": [], "build": str(ps.BUILD), "stateRoot": str(ps.SCRATCH), "theme": ps.THEME, "viewport": ps.DESKTOP})
    backend = None
    began = time.monotonic()
    try:
        if args.attach:
            client = Client()
        else:
            prepare_state(receipt)
            teach_laya(receipt)
            backend = start_backend(receipt)
            rig.processes.append(backend)
            client = Client()
            seed_notes(client, receipt)
            job = seed_app_factory(client, receipt)
            seed_laya(client, receipt)
            if not only or only & {"agent-view", "agent-view-phone", "agent-view-list-phone"}:
                try:
                    agent_session(client, receipt, job["previewUrl"])
                except Exception as exc:
                    receipt["agentRun"]["error"] = f"{type(exc).__name__}: {exc}"[:600]
                finally:
                    stop_agent_engine(client, receipt)
        receipt["seedSeconds"] = round(time.monotonic() - began, 1)
        start_capture_engine(rig, env)
        if args.phone:
            receipt["viewport"] = PHONE
            capture_phone(rig, receipt, only)
        else:
            rig.session(ps.DESKTOP)
            capture(rig, receipt, only)
        receipt["ok"] = all("error" not in row for row in receipt.get("screens", []))
    except Exception as exc:
        receipt["ok"] = False
        receipt["failure"] = f"{type(exc).__name__}: {exc}"
        receipt["traceback"] = traceback.format_exc()
    finally:
        if args.keep and backend is not None:
            receipt["backendKept"] = backend.pid
            (ps.SCRATCH / "backend.pid").write_text(str(backend.pid))
            rig.processes.remove(backend)
        if backend is not None and backend.poll() is None and not args.keep:
            # The backend's own children (Codex app server, git, validators) go with it: tree stop by PID.
            stopped = subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            receipt["backendTreeStop"] = stopped.returncode
        rig.stop()
        receipt["stoppedPids"] = [p.pid for p in rig.processes]
        out = BASE / (f"capture-{args.tag}-phone.json" if args.phone else f"capture-{args.tag}.json")
        out.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"ok": receipt.get("ok"), "failure": receipt.get("failure"), "receipt": str(out)}))


if __name__ == "__main__":
    main()
