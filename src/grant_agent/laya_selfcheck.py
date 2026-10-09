"""Deterministic observations of LAYA's gate, receipts, hosting and UI models, for the efficiency manual's contracts.

`efficiency.laya_selfcheck` runs one named part against stand-ins (a local HTTP service that answers as scripted, a
child process that serves /v1/health, throwaway state folders) and returns flat facts. The Connected Language checks in
manuals/cl/efficiency.cl (chapter `laya`) assert those facts, so the verification lives in the manual, not in test files.
Nothing here touches the real LAYA service, the backend's ledger, or any port other than free ones it opens itself.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from .subprocess_utils import hidden_windows_subprocess_kwargs

REPO = Path(__file__).resolve().parents[2]
PARTS = ("gate", "ledger", "host", "ui", "preview", "route", "shutdown", "instant")


class _Scripted(BaseHTTPRequestHandler):
    reply: dict = {}
    seen: dict = {}

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen = request
        body = json.dumps({"answers": {request["questions"][0]: type(self).reply}, "decision_id": "d_selfcheck"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@contextmanager
def _scripted_service():
    """A stand-in LAYA service on a free loopback port, set as the explicit override only inside this block."""
    handler = type("Scripted", (_Scripted,), {"reply": {}, "seen": {}})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    previous = os.environ.get("NEYVIA_LAYA_URL")
    os.environ["NEYVIA_LAYA_URL"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield handler
    finally:
        server.shutdown()
        if previous is None:
            os.environ.pop("NEYVIA_LAYA_URL", None)
        else:
            os.environ["NEYVIA_LAYA_URL"] = previous


@contextmanager
def _folder():
    path = Path(tempfile.mkdtemp(prefix="laya-selfcheck-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(predicate, seconds=40):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _sure(answer, **extra):
    return {"answer": answer, "policy": "answer", "top_probability": 1.0, "source": "m1", "conflict": False, **extra}


CHECKS = {"checks": [{"check": name, "level": "block", "passed": name != "visible-dash", "hits": [] if name != "visible-dash" else [{"text": "01 -"}]}
                     for name in ("theme-dark", "side-void", "visible-dash", "stock-phrase", "abstract-art")], "blocks": 1, "renderValid": True}


def gate() -> dict:
    """The 0.95 gate: only a confident, unconflicted answer is taken; everything else is handed up; each call leaves a receipt."""
    from . import laya_hooks, laya_ledger
    with _folder() as root, _scripted_service() as service:
        service.reply = _sure("repair_first")
        verdict = laya_hooks.triage_taste(root, CHECKS, "page1")
        accepted = verdict["route"] == "laya" and verdict["decision"] == "repair_first" and verdict["source"] == "m1"
        sent = service.seen
        service.reply = {"answer": "ask_critic", "policy": "escalate", "top_probability": 0.7, "source": "laya", "conflict": False}
        below = laya_hooks.triage_taste(root, CHECKS)
        service.reply = {**_sure("repair_first"), "policy": "escalate", "source": "escalated", "conflict": True}
        conflict = laya_hooks.triage_taste(root, CHECKS)
        incomplete = laya_hooks.triage_taste(root, {"checks": [], "blocks": 0})
        totals = laya_ledger.report(root, probe_service=False)["totals"]
        page = {"goal": "g", "page": {"url": "u"}, "current": {"text": "Pro plan selected"}, "action_receipts": [{"summary": "clicked save"}], "evidence": "Pro plan"}
        service.reply = _sure("true")
        verify_yes = laya_hooks.verify("page_done", True, page, root=root)
        verify_disagree = laya_hooks.verify("page_done", False, page, root=root)
        service.reply = {"answer": "true", "policy": "escalate", "top_probability": 0.6, "source": "laya", "conflict": False}
        unsure = laya_hooks.verify("page_done", True, page, root=root)
        unknown = laya_hooks.verify("something-else", 1, {})
        state = laya_hooks.page_done_state("g", {}, {}, [{"summary": "clicked save"}, {}], "ev")
        none_state = laya_hooks.page_done_state("g", {}, {}, [], "ev")
    return {"acceptedConfidentAnswer": accepted, "sentSetAndScope": sent["set"] == laya_hooks.SET and sent["scope"] == {"domain": "taste-triage"},
            "sentCheckHitCount": sent["state"]["checks"]["visible-dash"] == {"passed": False, "hits": 1},
            "belowGateEscalates": below["route"] == "escalate", "conflictEscalates": conflict.get("reason") == "conflict",
            "incompleteChecksEscalate": incomplete.get("reason") == "incomplete-checks",
            "ledgerAnswered": totals["answered"], "ledgerEscalated": totals["escalated"],
            "verifyAgrees": verify_yes["agrees"] is True and verify_yes["escalate"] is False and verify_yes["answer"] is True,
            "verifyDisagrees": verify_disagree["agrees"] is False,
            "verifyEscalatesWhenUnsure": unsure["escalate"] is True and unsure["answer"] is None and unsure["agrees"] is None,
            "verifyUnknownQuestionEscalates": unknown["escalate"] is True,
            "receiptSummary": state["receipt_summary"], "noReceiptSummary": none_state["receipt_summary"]}


def route() -> dict:
    """Connected Language routing asks about one clear candidate layer and stays silent without LAYA."""
    from . import laya_hooks, laya_host
    from .cl.host import HostContext
    saved = laya_hooks._vocab_cache
    laya_hooks._vocab_cache = {"notes": ["orchard", "pinned"], "pdf": ["highlight", "pages"]}
    try:
        with _folder() as root, _scripted_service() as service:
            service.reply = _sure("true")
            verdict = laya_hooks.route_layer(root, "append to the orchard note and keep it pinned")
            asked = service.seen["state"]
            nothing = laya_hooks.route_layer(root, "do something unrelated")
            tie = laya_hooks.route_layer(root, "orchard highlight")
            service.reply = {**_sure("false")}
            rejected = laya_hooks.route_layer(root, "append to the orchard note and keep it pinned")
            verify_no = laya_hooks.verify("cl_route", "notes", {"task": "orchard note"}, root=root)
            service.reply = _sure("true")
            verify_yes = laya_hooks.verify("cl_route", "notes", {"task": "orchard note"}, root=root)
        tools = [{"name": "notes.read", "effect": "", "annotations": {"readOnlyHint": True}, "inputSchema": {"properties": {}}}]
        with _folder() as root:
            host = HostContext(tools, lambda *a, **k: {}, root=root, task_text="append to the orchard note")
            previous_url, previous_host = os.environ.pop("NEYVIA_LAYA_URL", None), laya_host._HOST
            laya_host._HOST = None
            try:
                silent = host.route() is None and not (root / ".neyvia" / "laya").exists()
                os.environ["NEYVIA_LAYA_URL"] = "http://127.0.0.1:9"
                real = laya_hooks.route_layer
                laya_hooks.route_layer = lambda r, t: {"route": "laya", "decision": "notes", "layer": "notes"}
                routed = host.route() == {"route": "laya", "decision": "notes", "layer": "notes"}
                laya_hooks.route_layer = lambda r, t: {"route": "laya", "decision": "x", "layer": "not-a-layer"}
                unknown_layer = host.route() is None
                laya_hooks.route_layer = real
                os.environ["NEYVIA_CL_LAYA_ROUTE"] = "0"
                switched_off = host.route() is None
            finally:
                os.environ.pop("NEYVIA_CL_LAYA_ROUTE", None)
                os.environ.pop("NEYVIA_LAYA_URL", None)
                if previous_url is not None:
                    os.environ["NEYVIA_LAYA_URL"] = previous_url
                laya_host._HOST = previous_host
    finally:
        laya_hooks._vocab_cache = saved
    return {"confirmedClearCandidate": verdict["route"] == "laya" and verdict["decision"] == "notes",
            "askedLayerAndVocabulary": asked["layer_hit"] == "orchard,pinned" and asked["rival_hit"] == "",
            "noCandidateEscalates": nothing.get("reason") == "no-single-candidate", "tieEscalates": tie.get("reason") == "no-single-candidate",
            "layaNoIsNotARoute": rejected["decision"] is None, "verifyRouteNo": verify_no["agrees"] is False, "verifyRouteYes": verify_yes["agrees"] is True,
            "hostSilentWithoutLaya": silent, "hostRoutesWhenConfirmed": routed, "hostIgnoresUnknownLayer": unknown_layer, "hostRoutingSwitchedOff": switched_off}


def ledger() -> dict:
    """Receipts: triage gate, cascade System 1 stage, taste review triage, computer-use aggregation, browser classification."""
    from . import laya_ledger
    from .efficiency_cascade import Cascade
    from .laya_service import triage
    from .taste_lens import triage_report
    out = {}
    options = ["repair_with_model", "ship_as_is"]

    def fake(answer, confidence, escalate=False, available=True):
        def system1(prompt, schema, *, scope, preconditions):
            return {"available": True, "answer": answer, "confidence": confidence, "escalate": escalate} if available else {"available": False, "reason": "service down"}
        return system1
    with _folder() as root:
        routes = [triage(root, "t", "q?", options, system1_fn=fake("ship_as_is", .99))["route"], triage(root, "t", "q?", options, system1_fn=fake("ship_as_is", .6))["route"],
                  triage(root, "t", "q?", options, system1_fn=fake("other", .99))["route"], triage(root, "t", "q?", options, system1_fn=fake(None, 0, available=False))["route"]]
        totals = laya_ledger.report(root, probe_service=False)["totals"]
        out.update(triageRoutes=routes, triageAnswered=totals["answered"], triageEscalated=totals["escalated"], triageUnavailable=totals["unavailable"],
                   triageTokensSaved=totals["tokensSavedEstimate"] > 0)
    with _folder() as root:
        schema = {"type": "object", "properties": {"choice": {"type": "string"}}, "required": ["choice"], "additionalProperties": False}
        system1 = lambda prompt, schema, *, scope, preconditions: {"available": True, "answer": {"choice": "a"}, "confidence": .99, "escalate": False}

        def no_big(*a, **k):
            raise AssertionError("the big model must not run")
        result = Cascade(root).decide("Pick between apple and apricot for the label", schema, scope={"application": "unit"}, preconditions={"n": 1},
                                      validate=lambda a: a == {"choice": "a"}, system1=system1, provider=no_big)
        rows = laya_ledger.rows(root)
        out.update(cascadeRoute=result["route"], cascadeReceipt=bool(rows) and rows[-1]["outcome"] == "answered" and rows[-1]["path"] == "cascade.system1")
        Cascade(root).decide("Read value 42 and id 7", schema, scope={"application": "unit"}, preconditions={"n": 2}, validate=lambda a: True, system1=system1,
                             provider=lambda *a, **k: {"answer": {"choice": "a"}})
        out["cascadeExactValuesBypass"] = laya_ledger.rows(root)[-1]["outcome"] == "bypassed"
    with _folder() as root:
        blocked = triage_report(root, {"gate": "blocked", "counts": {"block": 1}, "findings": [{"severity": "block"}]}, system1_fn=fake("ship_as_is", .99))
        grey = {"gate": "clear", "score": 94, "counts": {"block": 0, "warn": 1, "note": 0},
                "findings": [{"severity": "warn", "rule": "alt", "viewport": "desktop", "title": "1 images lack alt text"}]}
        asked = triage_report(root, grey, system1_fn=fake("repair_with_model", .97))
        unsure = triage_report(root, grey, system1_fn=fake("ship_as_is", .5))
        clear = triage_report(root, {"gate": "clear", "counts": {}, "findings": []})
        task = {t["task"]: t for t in laya_ledger.report(root, probe_service=False)["tasks"]}["taste-review"]
        out.update(tasteBlockingStaysDeterministic=blocked["route"] == "deterministic" and blocked["decision"] == "repair_with_model",
                   tasteGreyZoneAnswered=asked["route"] == "laya", tasteUnsureEscalates=unsure["route"] == "escalate" and unsure["decision"] == "repair_with_model",
                   tasteCleanShips=clear["decision"] == "ship_as_is", tasteLedger=[task["answered"], task["escalated"], task["deterministic"]])
    with _folder() as root:
        folder = root / ".neyvia" / "cua"
        folder.mkdir(parents=True)
        receipts = [
            {"by": "agent", "tool": "click", "status": "ok", "ms": 40, "app": "notepad.exe", "at": "t1", "preservation": {"foregroundPreserved": True, "cursorPreserved": True}},
            {"by": "agent", "tool": "type_text", "status": "ok", "ms": 60, "app": "notepad.exe", "at": "t2", "preservation": {"foregroundPreserved": False, "cursorPreserved": True}},
            {"by": "paul", "tool": "scroll", "status": "refused", "ms": 0, "app": "calc.exe", "at": "t3"}, {"by": "driver", "tool": "snapshot", "status": "ok", "at": "t4"}]
        (folder / "receipts.jsonl").write_text("\n".join(json.dumps(r) for r in receipts), encoding="utf-8")
        (folder / "sessions.json").write_text(json.dumps({"sessions": [{"status": "active", "foreground": False}]}), encoding="utf-8")
        cu = laya_ledger.computer_use(root)
        out["computerUse"] = [cu["actions"], cu["byAgent"], cu["byPaul"], cu["refused"], cu["disturbances"]]
        out["agentDesktopBackground"] = cu["agentDesktop"] == {"backgroundSessions": 1, "foregroundSessions": 0} and cu["avgMs"] == 50.0
    postcheck = laya_ledger.classify_browser({"answers": {"decision": {"policy": "answer+postcheck", "top_probability": .9}}})
    out["browserPostcheckIsAnswered"] = postcheck == ("answered", .9, "postcheck required")
    out["browserEscalateIsHandedUp"] = laya_ledger.classify_browser({"answers": {"decision": {"policy": "escalate", "top_probability": .6}}})[0] == "escalated"
    out["browserUnavailable"] = laya_ledger.classify_browser({"available": False, "reason": "x"})[0] == "unavailable"
    return out


def host() -> dict:
    """The backend-owned service: starts, restarts after a crash, stops with its child, says why it cannot start."""
    from . import laya_host, laya_ledger
    from .laya_service import endpoint
    stand_in = ("import sys\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
                "class H(BaseHTTPRequestHandler):\n    def do_GET(self):\n        body=b'{\"status\":\"ready\"}'\n"
                "        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)\n"
                "    def log_message(self, *a): pass\nHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n")
    out = {}
    with _folder() as root:
        script = root / "service.py"
        script.write_text(stand_in, encoding="utf-8")
        port = _free_port()
        config = {**laya_host.DEFAULTS, "port": port, "_command": [sys.executable, str(script), str(port)], "startTimeoutSeconds": 20}
        service = laya_host.LayaHost(root, config).start()
        try:
            out["startsAndIsReady"] = _wait(service.ready)
            first = service.pid
            status = service.status()
            out["ownedChild"] = bool(status["owned"]) and service.url.endswith(str(port))
            service.process.kill()
            out["restartsAfterCrash"] = _wait(lambda: service.pid not in (None, first) and service.ready(), 45) and service.status()["restarts"] >= 1
        finally:
            service.stop()
        out["childStopsWithHost"] = _wait(lambda: not laya_host._health(port, 0.3), 10) and service.status()["state"] == "stopped"
        port2 = _free_port()
        owned = laya_host.LayaHost(root, {**laya_host.DEFAULTS, "port": port2, "_command": [sys.executable, str(script), str(port2)]}).start()
        previous_url, previous_host = os.environ.pop("NEYVIA_LAYA_URL", None), laya_host._HOST
        try:
            laya_host._HOST = None
            try:
                endpoint()
                out["endpointRefusesWithoutService"] = False
            except ValueError as exc:
                out["endpointRefusesWithoutService"] = "not running" in str(exc)
            out["statusExplainsAbsence"] = laya_ledger.service_status()["ready"] is False and bool(laya_ledger.service_status()["reason"])
            laya_host._HOST = owned
            _wait(owned.ready)
            out["endpointFollowsOwnedService"] = endpoint() == f"http://127.0.0.1:{port2}"
            status = laya_ledger.service_status()
            out["statusReportsOwnedReady"] = status["owned"] is True and status["ready"] is True
        finally:
            owned.stop()
            laya_host._HOST = previous_host
            if previous_url is not None:
                os.environ["NEYVIA_LAYA_URL"] = previous_url
        missing = laya_host.LayaHost(root, {**laya_host.DEFAULTS, "port": _free_port(), "python": str(root / "nope.exe")}).start()
        off = laya_host.LayaHost(root, {**laya_host.DEFAULTS, "enabled": False}).start()
        reserved = laya_host.LayaHost(root, {**laya_host.DEFAULTS, "port": 47881}).start()
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            busy = laya_host.LayaHost(root, {**laya_host.DEFAULTS, "port": taken.getsockname()[1]}).start()
        out["degradesWithReason"] = {"missingRuntime": missing.state == "unavailable" and "runtime is missing" in missing.reason,
                                     "switchedOff": off.state == "disabled" and "switched off" in off.reason,
                                     "reservedPort": reserved.state == "unavailable" and "not allowed" in reserved.reason,
                                     "portTaken": busy.state == "unavailable" and "another program" in busy.reason}
    return out


def shutdown() -> dict:
    """Observe stop-during-health without binding a port or starting a child."""
    from . import laya_host
    observed = {}
    for health in (None, {"status": "ready"}):
        service = laya_host.LayaHost(REPO, {**laya_host.DEFAULTS, "port": 48999})
        class DetachedChild:
            returncode = 0
            def poll(self):
                return None
        service.process = DetachedChild()
        service.state = "starting"
        def stopped_during_probe(*args, **kwargs):
            with service.lock:
                service.stopping.set()
                service.process = None
                service.state = "stopped"
            return health
        service._probe = stopped_during_probe
        service._watch()
        observed['staysStoppedAfter' + ('Ready' if health else 'Timeout')] = service.state == 'stopped' and not service.restarts
    return observed


def ui() -> dict:
    """The status-strip and live-preview models in web/src/neyvia/next, evaluated by Node."""
    script = r"""
import { computerUseView, formatMs, formatTokens, layaHealth, serviceView, stripView, taskRows } from './nxLayaModel.js';
import { MAX_WAIT_TICKS, initialWatch, liveLabel, tick } from './nxLiveModel.js';
const out = {};
out.stripUnread = stripView(null).text;
out.stripOff = stripView({ totals: {}, service: { configured: false } }).text;
out.stripOffline = stripView({ totals: {}, service: { configured: true, ready: false } }).text;
const warming = { totals: {}, service: { configured: true, ready: true, host: { instantEncoders: { state: 'warming' } } } };
out.stripWarming = stripView(warming).text;
out.healthWarming = layaHealth(warming).title;
out.stripReady = stripView({ totals: {}, service: { ready: true, host: { instantEncoders: { state: 'ready' } } } }).text;
const live = stripView({ totals: { answered: 7, escalated: 3, tokensSavedEstimate: 12400 }, service: { configured: true, ready: true } });
out.stripLive = [live.text, live.tone];
out.serviceTones = [serviceView({ configured: false }).tone, serviceView({ configured: true, ready: false }).tone, serviceView({ ready: true, owned: true }).tone];
out.serviceReason = /main model answers instead/.test(serviceView({ configured: false, ready: false, reason: 'weights missing' }).label);
out.formats = [formatTokens(950), formatTokens(null), formatMs(42.4), formatMs(2300)];
out.row = taskRows({ tasks: [{ task: 'browser', path: 'browser.decide', answered: 2, escalated: 1, unavailable: 0, answerRate: 0.6667, p50Ms: 31, tokensSavedEstimate: 400 }] })[0];
const cu = computerUseView({ driver: { available: true }, actions: 5, byAgent: 4, byPaul: 1, refused: 0, disturbances: 0, avgMs: 55, activeSessions: 1, agentDesktop: { backgroundSessions: 2, foregroundSessions: 0 }, layaWorkflowRuns: 3, layaWorkflowVerified: 2 });
out.computerUse = { line: cu.line, disturbanceTone: cu.disturbanceTone, workflows: cu.workflows, actions: cu.actions, ready: cu.ready, used: cu.used };
let state = initialWatch('v1'); let reloadsWhenQuiet = 0;
for (let i = 0; i < 5; i += 1) { const next = tick(state, 'v1'); reloadsWhenQuiet += next.reload ? 1 : 0; state = next.watch; }
out.quietNeverReloads = reloadsWhenQuiet === 0 && tick(state, null).reload === false;
let step = tick(initialWatch('v1'), 'v2'); const first = step.reload; step = tick(step.watch, 'v2');
out.changeWaitsOneTick = first === false && step.reload === true && tick(step.watch, 'v2').reload === false;
let moving = initialWatch('v0'); let at = 0;
for (let i = 1; i <= MAX_WAIT_TICKS + 2; i += 1) { const r = tick(moving, 'v' + i); moving = r.watch; if (r.reload) { at = i; break; } }
out.keepsChangingStopsWaiting = at === MAX_WAIT_TICKS;
out.liveLabels = [liveLabel(null), liveLabel(1000, 1500), liveLabel(1000, 11000), liveLabel(0, 180000)];
console.log(JSON.stringify(out));
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO / "web/src/neyvia/next", capture_output=True, text=True, encoding="utf-8", timeout=60, **hidden_windows_subprocess_kwargs())
    if done.returncode:
        return {"error": (done.stderr or done.stdout)[-300:]}
    observed = json.loads(done.stdout.strip().splitlines()[-1])
    # Exercise the backend guard in a child: the observer must never replace
    # the real host or load encoders in the process running the manual.
    probe = r"""
import json, tempfile
from types import SimpleNamespace
from pathlib import Path
from grant_agent import laya_host, laya_instant, laya_ledger
def forbidden_store(*args, **kwargs):
    raise AssertionError('A warming request tried to load the instant store')
laya_instant.store = forbidden_store
laya_host._HOST = SimpleNamespace(config={'enabled': True}, encoders={'state': 'warming'})
out = {}
out['warmupStates'] = {}
for state in ('waiting', 'warming', 'loading', 'ready', 'partial', 'idle'):
    laya_host._HOST.encoders['state'] = state
    out['warmupStates'][state] = laya_host.instant_ready()
laya_host._HOST.encoders['state'] = 'warming'
with tempfile.TemporaryDirectory(prefix='laya-warmup-contract-') as folder:
    answer = laya_instant.query(folder, 'routing', 'open a note')
    report = laya_ledger.report(Path(folder), probe_service=False)
    out['warmupAbstains'] = answer.get('warming') is True and answer.get('available') is False and answer.get('escalate') is True and answer.get('answer') is None
    out['warmupReason'] = answer.get('reason')
    out['warmupReport'] = report['instant'] == {'warming': True, 'reason': laya_host.WARMING_UP}
print(json.dumps(out))
"""
    env = {**os.environ, 'PYTHONPATH': str(REPO / 'src') + os.pathsep + os.environ.get('PYTHONPATH', '')}
    backend = subprocess.run([sys.executable, '-c', probe], cwd=REPO, env=env, capture_output=True,
                             text=True, encoding='utf-8', timeout=30, **hidden_windows_subprocess_kwargs())
    if backend.returncode:
        return {'error': (backend.stderr or backend.stdout)[-500:]}
    return {**observed, **json.loads(backend.stdout.strip().splitlines()[-1])}


def preview() -> dict:
    """The live preview's change marker follows page and sibling edits without reading content."""
    from .neyvia_panes import call_panes
    with _folder() as root:
        page = root / "site" / "index.html"
        page.parent.mkdir()
        page.write_text("<h1>one</h1><link rel=stylesheet href=a.css>", encoding="utf-8")
        css = page.parent / "a.css"
        css.write_text("h1{color:red}", encoding="utf-8")
        first = call_panes(root, "artifact.stat", {"path": str(page)})
        opened = call_panes(root, "artifact.open", {"path": str(page)})
        again = call_panes(root, "artifact.stat", {"path": str(page)})
        css.write_text("h1{color:blue;font-size:3rem}", encoding="utf-8")
        second = call_panes(root, "artifact.stat", {"path": str(page)})
        page.write_text("<h1>two</h1>", encoding="utf-8")
        third = call_panes(root, "artifact.stat", {"path": str(page)})
        missing = call_panes(root, "artifact.stat", {"path": str(root / "nope.html")})
    return {"statReadsNoContent": first["ok"] and "text" not in first, "openCarriesSameMarker": opened["version"] == first["version"],
            "unchangedKeepsMarker": again["version"] == first["version"], "stylesheetEditChangesMarker": second["version"] != first["version"],
            "pageEditChangesMarker": third["version"] != second["version"], "missingIsExplicit": missing.get("status") == "missing"}


def run(part: str) -> dict:
    if part not in PARTS:
        raise ValueError("part must be one of " + ", ".join(PARTS))
    started = time.monotonic()
    result = globals()[part]()
    return {"ok": True, "part": part, **result, "seconds": round(time.monotonic() - started, 1)}


def instant():
    """Real frozen encoder and durable writes; CL asserts the observed outcomes."""
    from .laya_instant import Episodes, encode
    from .laya_instant_ingest import experience, rows as ingest_rows
    from .laya_service import triage, verify
    encode('warm the frozen encoder')
    with _folder() as root:
        s = Episodes(root)
        empty = s.query('routing', 'save a note')
        first = s.learn('routing', 'save a note', 'notes', 'explicit')
        one = s.query('routing', 'save a note')
        correction = s.learn('routing', 'save a note', 'workspace', 'explicit')
        changed = s.query('routing', 'save a note')
        reopened = Episodes(root).query('routing', 'save a note')
        s.learn('routing', 'save a note', 'notes', 'independent')
        conflict = s.query('routing', 'save a note')
        s.forget('independent')
        resolved = s.query('routing', 'save a note')
        query_times = sorted(s.query('routing', 'save a note')['ms'] for _ in range(20))
        s.learn('routing', 'save a note', 'personal', 'paul-vote', user='paul', layer='personal')
        personal = s.query('routing', 'save a note', user='paul')
        other = s.query('routing', 'save a note', user='someone-else')
        novel = s.query('routing', 'compose an unrelated orchestral piece')
        weak = experience(root, 'experience', 'edit', 'kept', 'actual-kept')
        weak_query = Episodes(root).query('experience', 'edit')
        s.learn('triage:contract', {'question': 'where?', 'context': {}, 'options': ['notes', 'files']}, 'notes', 'host')
        routed = triage(root, 'contract', 'where?', ['notes', 'files'], system1_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('prior called')))
        s.learn('verify:page_done', {'candidate': True, 'evidence': {'current': 'bound'}}, False, 'host')
        checked = verify('page_done', True, {'current': 'bound'}, root=root)
        s.learn('routing', 'read a document', 'files', 'service-routing')
        manual_route = triage(root, 'manual-routing', 'read a document', ['notes', 'files'],
            system1_fn=lambda *a, **kw: (_ for _ in ()).throw(AssertionError('prior called')))
        from .laya_curriculum import outcome_input
        outcome_receipt = {'toolId': 'files.read', 'result': {'status': 'complete', 'bytes': 123}}
        s.learn('outcomes', outcome_input(outcome_receipt), 'success', 'service-outcomes')
        outcome_verified = verify('tool_outcome', 'success', outcome_receipt, root=root)
        s.forget('service-outcomes')
        s.forget('explicit')
        forgotten = s.query('routing', 'save a note')
        # A mechanism contract, not the independent corpus accuracy estimate.
        fields = 'file page note image mesh scene layer folder document window project revision'.split()
        for field in fields:
            for label, status, flag in [('success', 'complete', 'True'), ('failure', 'error', 'False')]:
                s.learn('outcomes', f'result.status={status} result.{field}={flag}', label,
                        'loo-contract-' + field + label)
        samples_before = sum(len(c.samples) for key, c in s.calibration.items() if key[0] == 'outcomes')
        novel_input = 'result.status=complete result.file=True result.page=True'
        admitted = s.query('outcomes', novel_input)
        s.learn('outcomes', novel_input, 'failure', 'excluded-evaluation', split='holdout')
        after_holdout = s.query('outcomes', novel_input)
        s.forget('loo-contract-filesuccess')
        samples_after = sum(len(c.samples) for key, c in s.calibration.items() if key[0] == 'outcomes')
        try:
            with s.import_batch():
                s.learn('archive', 'rolled back', True, 'atomic-import')
                raise ValueError('Intentional interrupted archive import')
        except ValueError:
            pass
        rollback = Episodes(root).query('archive', 'rolled back')['escalate']
        with s.import_batch():
            pending = s.learn('archive', 'committed', True, 'atomic-import')
        committed = Episodes(root).query('archive', 'committed')['answer'] is True
        votes = [dict(vote='A', winner='luna', tie=False, abstain=False),
                 dict(vote='same', winner=None, tie=True, abstain=False),
                 dict(vote=None, winner=None, tie=False, abstain=True)]
        mapped = [list(ingest_rows({'domain': 'taste', 'input': {'A': 'luna', 'B': 'sol'},
                  'label': vote, 'layer': 'personal', 'user': 'paul', 'source': 'contract-round12'}))[0] for vote in votes]
        votes_separate = [(r['domain'], r['label'], r['layer']) for r in mapped] == [
            ('personal', 'A', 'personal'), ('personal', 'tie', 'personal'), ('personal-abstention', 'abstain', 'personal')]
        exported = list(ingest_rows({'domain': 'taste', 'input': {'pageId': 'r12/pair'},
            'label': {**votes[0], 'A': 'luna', 'B': 'sol'}, 'layer': 'personal', 'user': 'paul'}))[0]
        votes_separate = votes_separate and exported['label'] == 'A' and exported['domain'] == 'personal'
        guidance = list(ingest_rows({'domain': 'taste', 'input': {'pageId': 'r12/feedback', 'evidenceKind': 'reason-only'},
            'label': {'aspect': 'motion', 'reason': 'Show real animation'}, 'layer': 'personal', 'user': 'paul'}))[0]
        votes_separate = votes_separate and guidance['domain'] == 'personal-guidance' and guidance['evidence']['qualityBound'] is False
        s.learn('retired', 'same input', True, 'same source', split='train')
        s.learn('retired', 'same input', True, 'same source', split='holdout')
        superseded = s.query('retired', 'same input')['escalate'] and not any(k[0] == 'retired' for k in s.calibration)
        # Reopening must reproduce incrementally maintained calibration after
        # additions, corrections, forgetting and a holdout supersession.
        rebuilt = Episodes(root)
        rebuilt.refresh()
        import numpy as np
        equivalent = set(s.calibration) == set(rebuilt.calibration)
        for key, index in s.calibration.items():
            other_index = rebuilt.calibration.get(key)
            equivalent = equivalent and other_index is not None and index.ids == other_index.ids
            if other_index is not None:
                equivalent = equivalent and np.allclose(index.samples, other_index.samples, atol=1e-6)
                equivalent = equivalent and index.threshold == other_index.threshold
                equivalent = equivalent and (index.radius == other_index.radius or (
                    index.radius is not None and other_index.radius is not None and abs(index.radius-other_index.radius) < 1e-6))
    return {'emptyAbstains': empty['escalate'], 'writeChangesNextAnswer': one['answer'] == 'notes',
            'correctionChangesNextAnswer': changed['answer'] == 'workspace', 'survivesReopen': reopened['answer'] == 'workspace',
            'contradictionAbstains': conflict.get('conflict') is True, 'forgetResolvesConflict': resolved['answer'] == 'workspace',
            'personalWins': personal['answer'] == 'personal', 'userIsolated': other['answer'] == 'workspace',
            'novelAbstains': novel['escalate'], 'weakNeverExactAuthority': weak_query['escalate'],
            'triageUsesEpisodes': routed['decision'] == 'notes', 'verifyUsesEpisodes': checked['answer'] is False,
            'manualTriageUsesRoutingEpisodes': manual_route['decision'] == 'files',
            'toolVerifyUsesOutcomeEpisodes': outcome_verified['answer'] == 'success' and outcome_verified['agrees'],
            'forgetRemovesAnswer': forgotten['escalate'], 'coldStoreWriteMs': first['labelToEffectMs'], 'warmWriteMs': correction['labelToEffectMs'],
            'warmQueryMs': one['ms'], 'warmQueryP50Ms': query_times[9], 'warmQueryP95Ms': query_times[18],
            'warmQueryMaxMs': query_times[-1], 'replayConfidenceKind': one['confidenceKind'],
            'calibratesOnWrite': samples_before == 24,
            'novelCrossConformalAnswer': admitted['answer'] == 'success' and admitted.get('confidenceKind') == 'leave-one-out-cross-conformal-singleton',
            'evaluationHoldoutExcluded': after_holdout['answer'] == admitted['answer'] and not after_holdout.get('conflict'),
            'forgetRecalibrates': samples_after == 23,
            'atomicImportRollback': rollback, 'atomicImportCommits': committed and pending.get('pendingImport') is True,
            'personalVotesPreserveTieAndAbstention': votes_separate,
            'holdoutSupersedesTrainingRevision': superseded,
            'incrementalMatchesRebuild': bool(equivalent),
            'mechanismNovelAnswer': admitted}
