"""Actual T15-r2 service + Obscura + production cascade attachment receipt."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-port", type=int, required=True)
    parser.add_argument("--fixture-port", type=int, required=True)
    parser.add_argument("--engine-port", type=int, required=True)
    parser.add_argument("--obscura", type=Path, required=True)
    args = parser.parse_args()
    ports = {args.service_port, args.fixture_port, args.engine_port}
    if len(ports) != 3 or not ports <= set(range(48681, 48690)):
        raise ValueError("Distinct explicit FIX2 assigned ports required")
    os.environ["NEYVIA_LAYA_URL"] = f"http://127.0.0.1:{args.service_port}"
    os.environ["NEYVIA_OBSCURA_EXE"] = str(args.obscura.resolve())
    os.environ["NEYVIA_BROWSER_PROOF_PORTS"] = ",".join(map(str, sorted(ports)))
    from grant_agent.neyvia_browser import service_for, handle_command
    from grant_agent.efficiency_cascade import Cascade, CascadeError
    from grant_agent.laya_service import system1
    from grant_agent.laya_client.contracts import digest
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.neyvia_manuals import unwrap
    out = REPO / "scripts/evidence/fix2-laya.json"
    root = REPO / ".agent_control/FIX2/laya" / str(time.time_ns())
    page = b'''<!doctype html><title>FIX2 LAYA</title><h1>Save a note</h1><label>Name <input aria-label="Name" id="name"></label><button onclick="document.getElementById('result').textContent='Saved: '+document.getElementById('name').value">Save</button><p id="result">Not saved</p>'''
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(page)
        def log_message(self, *_):
            pass
    fixture = ThreadingHTTPServer(("127.0.0.1", args.fixture_port), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True); thread.start()
    browser = service_for(root)
    receipt = {"ports": vars(args) | {"obscura": str(args.obscura)}, "boundary": "Owned CPU shipped round2 inference; actual Obscura DOM; no public service changes", "checks": []}
    engine = None
    try:
        with urllib.request.urlopen(os.environ["NEYVIA_LAYA_URL"] + "/v1/health", timeout=5) as response:
            receipt["serviceHealth"] = json.load(response)
        browser.request("headless.start", {"port": args.engine_port, "allowLocalFixtures": True}, owner=True)
        engine = browser.headless
        tab = browser.request("tab.open", {"url": f"http://127.0.0.1:{args.fixture_port}/", "engine": "obscura"}, owner=True)["tabId"]
        context = {"goal": "Enter FIX2 in Name and click Save. Completion requires visible Saved: FIX2 confirmation.",
                   "progress": {"expected_confirmation": "Saved: FIX2"}}
        before = handle_command(root, "browser_decide_command", {"tabId": tab, "question": "page_done", "context": context}, owner=True)
        assert before["available"] and before["decision"]["decision_id"]
        obs = browser.projection(tab)
        assert before["decision"]["t20"]["projection_digest"] == digest(obs)
        browser.request("tab.grant", {"tabId": tab, "enabled": True}, owner=True)
        field = next(e for e in obs["elements"] if e["name"] == "Name")
        browser.request("action", {"tabId": tab, "revision": obs["revision"], "element": field["id"], "action": "fill", "value": "FIX2"})
        obs = browser.laya_client.observe(tab)
        button = next(e for e in obs["elements"] if e["name"] == "Save")
        browser.request("action", {"tabId": tab, "revision": obs["revision"], "element": button["id"], "action": "click"})
        after = handle_command(root, "browser_decide_command", {"tabId": tab, "question": "page_done", "context": context}, owner=True)
        obs = browser.projection(tab)
        assert "Saved: FIX2" in obs["text"]
        assert after["decision"]["t20"]["projection_digest"] == digest(obs)
        receipt["browser"] = {"before": before, "after": after, "observation": obs, "state": browser.view()}
        receipt["semanticQuality"] = {"beforeExpected": "false", "afterExpected": "true",
            "beforeActual": before["decision"]["answers"]["page_done"]["answer"],
            "afterActual": after["decision"]["answers"]["page_done"]["answer"],
            "boundary": "Two authored actual DOM judgements only; escalation remains service-owned"}
        registry = NativeToolRegistry(root)
        native = registry.call("neyvia.browser.decide", {"tabId": tab, "question": "page_done", "context": context})
        native_result = unwrap(native)
        assert native_result["available"] and native_result["decision"]["decision_id"]
        assert native_result["decision"]["t20"]["projection_digest"] == digest(browser.projection(tab))
        receipt["nativeBrowserDecision"] = native
        receipt["checks"].append("Ordinary backend browser route acquires fresh actual DOM, invokes shipped client and real HTTP inference before and after fill/click")
        browser.laya_client.captures[tab]["observed_at_ms"] -= 6000
        try:
            browser.request("decide", {"tabId": tab, "question": "page_done"})
            raise AssertionError("Stale observation accepted")
        except ValueError as exc:
            assert "stale" in str(exc)
            receipt["staleRefusal"] = str(exc)
        # No provider substitution: later model transport is deliberately unavailable.
        def unavailable_model(*_, **__):
            raise ConnectionError("Proof does not call a substitute model")
        cascade = Cascade(root)
        try:
            receipt["cascade"] = cascade.decide("Is the note saved?", {"type": "boolean"},
                scope={"application": "note-proof"}, preconditions={"note": {"saved": True, "pending_edits": False}},
                validate=lambda answer: answer is True, provider=unavailable_model, learn=False)
        except CascadeError as exc:
            receipt["cascade"] = json.loads(Path(exc.receipt_path).read_text())
        direct = system1("Is the note saved?", {"type": "boolean"}, scope={"application": "note-proof"}, preconditions={"note": {"saved": True, "pending_edits": False}})
        assert direct["available"] and direct["decisionId"]
        assert any(row["stage"] == "system1" and row["status"] in {"validated", "rejected"} for row in receipt["cascade"]["trace"])
        receipt["cascadeProvider"] = direct
        receipt["checks"].append("Default production cascade System1 makes real typed CPU LAYA decision and retains confidence policy")
        accepted = cascade.decide("Which language is the text written in?", {"type": "string", "enum": ["English", "French"]},
            scope={"application": "language-proof"}, preconditions={"text": "Bonjour, je suis Paul et je parle français."},
            validate=lambda answer: answer == "French", provider=unavailable_model, learn=False)
        assert accepted["route"] == "system1" and accepted["answer"] == "French" and accepted["modelCalls"] == []
        receipt["acceptedCascade"] = accepted
        receipt["checks"].append("Actual production System1 French-language answer passes unchanged confidence, schema and independent semantic gates")
        # A stopped owned listener proves connection-down, rather than HTTP errors.
        fixture.shutdown(); fixture.server_close(); thread.join()
        browser.laya_client.hook.endpoint = f"http://127.0.0.1:{args.fixture_port}"
        browser_down = handle_command(root, "browser_decide_command", {"tabId": tab, "question": "page_done"}, owner=True)
        assert browser_down["available"] is False and browser_down["status"] == "service_unavailable"
        receipt["browserDownService"] = browser_down
        assert browser.view()["laya"] == {"available": False, "status": "service_unavailable"}
        receipt["browserDownState"] = browser.view()["laya"]
        os.environ["NEYVIA_LAYA_URL"] = f"http://127.0.0.1:{args.fixture_port}"
        down = system1("Is the note saved?", {"type": "boolean"}, scope={}, preconditions={"saved": True})
        assert down["available"] is False and "unavailable" in down["reason"]
        receipt["downService"] = down
        try:
            cascade.decide("Is the note saved?", {"type": "boolean"}, scope={"application": "down-proof"},
                preconditions={"note": {"saved": True}}, validate=lambda answer: answer is True,
                provider=unavailable_model, learn=False)
        except CascadeError as exc:
            receipt["downCascade"] = json.loads(Path(exc.receipt_path).read_text())
        assert any(row["stage"] == "system1" and row["status"] == "unavailable" for row in receipt["downCascade"]["trace"])
        assert receipt["downCascade"]["modelCalls"][0]["model"] == "gpt-6-luna"
        receipt["checks"].append("Stopped owned port returns unavailable for System1; no child process or substitute model")
        receipt["passed"] = True
    finally:
        browser.request("headless.stop", {}, owner=True)
        receipt["ownedEngineExit"] = engine.process.poll() if engine else None
        if thread.is_alive():
            fixture.shutdown(); fixture.server_close(); thread.join()
        receipt["fixtureStopped"] = not thread.is_alive()
        receipt["sourceHashes"] = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in [REPO / "src/grant_agent/laya_service.py", REPO / "src/grant_agent/laya_client/browser_client.py", REPO / "src/grant_agent/laya_client/contracts.py", Path(__file__)]}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": receipt["passed"], "checks": receipt["checks"], "cascadeRoute": receipt["cascade"]["route"], "receipt": str(out)}))


if __name__ == "__main__":
    main()
