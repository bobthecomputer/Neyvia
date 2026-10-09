"""Native Obscura journey for learned browser site manuals.

The page is served only from an owned loopback fixture. Observations and
actions go through the production BrowserService and the admitted Obscura
engine; the checks below assert the returned native receipts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import uuid

CONTRACTS = ("browser.site-manual-journey",)


def site_manual_journey(root: Path, receipt_root: Path) -> dict:
    from .neyvia_browser import BrowserService
    from .proof_ports import proof_port
    BACKEND_PORT, ENGINE_PORT = proof_port(48461), proof_port(48462)

    root = Path(root).resolve()
    receipt_root = Path(receipt_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)

    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            variant = query.get("variant", ["first"])[0]
            if variant == "changed":
                form = '<label for="q">Find invoice</label><input id="q" name="invoice" type="text">'
                results = "Invoice 42"
            elif variant == "ambiguous":
                form = ('<label for="q1">Search catalog</label><input id="q1" name="first" type="search">'
                        '<label for="q2">Search catalog</label><input id="q2" name="second" type="search">')
                results = "Two matching controls"
            else:
                form = '<label for="q">Search catalog</label><input id="q" name="q" type="search">'
                results = "Catalog ready"
            body = ("<!doctype html><meta charset=utf-8><title>Local catalog</title>"
                    "<main><h1>Local catalog</h1>" + form + "<p id=results>" + results + "</p></main>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    # Refuse an occupied port rather than attaching to an unrelated listener.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", BACKEND_PORT))
    server = ThreadingHTTPServer(("127.0.0.1", BACKEND_PORT), Fixture)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="p22-browser-fixture", daemon=True)
    thread.start()

    prior_ports = os.environ.get("NEYVIA_BROWSER_PROOF_PORTS")
    os.environ["NEYVIA_BROWSER_PROOF_PORTS"] = f"{BACKEND_PORT}-{ENGINE_PORT}"
    service = BrowserService(root)
    tab_id = None
    try:
        status = service.request("headless.start", {
            "port": ENGINE_PORT, "assignedPorts": [BACKEND_PORT, ENGINE_PORT],
            "allowLocalFixtures": True, "colorScheme": "light", "reducedMotion": "reduce",
        }, owner=True)
        if status.get("engine") != "obscura" or status.get("stealth") is not False or not status.get("connected"):
            raise ValueError("The admitted non-stealth Obscura engine did not start on its assigned port")

        base = f"http://127.0.0.1:{BACKEND_PORT}/fixture"
        opened = service.request("tab.open", {"url": base + "?variant=first", "engine": "obscura"}, owner=True)
        tab_id = opened["tabId"]
        service.request("tab.grant", {"tabId": tab_id, "enabled": True}, owner=True)

        learned = service.request("site.manual", {"tabId": tab_id}, owner=True)
        reopened = service.request("site.manual", {"tabId": tab_id}, owner=True)
        if learned.get("status") != "learned" or reopened.get("status") != "reused":
            raise ValueError("A fresh site manual was not reused after a fresh native observation: "
                             + json.dumps({"learned": learned.get("status"), "reopened": reopened.get("status"),
                                           "validation": reopened.get("validation"), "fingerprints": [learned.get("fingerprint"), reopened.get("fingerprint")]},
                                          ensure_ascii=False))
        if not reopened.get("validation", {}).get("structureMatches") or not reopened.get("controls"):
            raise ValueError("Reopened manual lacked its fresh matching observed controls")
        first_fingerprint = reopened["fingerprint"]

        service.request("tab.navigate", {"tabId": tab_id, "url": base + "?variant=changed"}, owner=True)
        changed = service.request("site.manual", {"tabId": tab_id}, owner=True)
        if (changed.get("status") != "relearned" or changed.get("fingerprint") == first_fingerprint
                or not changed.get("validation", {}).get("priorFactsDemoted")
                or not changed.get("quarantined")):
            raise ValueError("Changed native controls did not quarantine the stale learned facts")
        if any("variant=" in json.dumps(fact, ensure_ascii=False) for fact in changed["controls"]):
            raise ValueError("A site manual retained fixture query values in its learned controls")

        service.request("tab.navigate", {"tabId": tab_id, "url": base + "?variant=ambiguous"}, owner=True)
        observed = service.request("observe", {"tabId": tab_id}, owner=True)
        from .browser_site_manuals import action_batch
        refused = action_batch(service, {
            "tabId": tab_id, "revision": observed["revision"],
            "steps": [{"target": {"role": "textbox", "name": "Search catalog"},
                       "action": "fill", "value": "must not dispatch"}],
        }, owner=True, initial_observation=observed)
        if (refused.get("ok") is not False or refused.get("completed") != 0
                or refused.get("error", {}).get("code") != "ambiguous_target"
                or refused.get("receipts")):
            raise ValueError("Ambiguous semantic target was not refused before native action dispatch: "
                             + json.dumps({key: refused.get(key) for key in ("ok", "status", "completed", "error", "receipts")},
                                          ensure_ascii=False)
                             + "; observed controls=" + json.dumps([
                                 {key: row.get(key) for key in ("role", "name", "inputName", "actions", "enabled")}
                                 for row in observed.get("elements", []) if row.get("actions")], ensure_ascii=False))

        return {
            "engine": "obscura", "stealth": False, "assignedPorts": [BACKEND_PORT, ENGINE_PORT],
            "learnedThenReused": True, "changedStructureQuarantined": True,
            "ambiguousTargetRefusedBeforeDispatch": True,
            "manualTrust": reopened.get("trust"), "dispatchReceiptsOnRefusal": len(refused.get("receipts", [])),
        }
    finally:
        try:
            if tab_id:
                service.request("tab.close", {"tabId": tab_id}, owner=True)
        except Exception:
            pass
        try:
            if service.headless:
                service.request("headless.stop", {}, owner=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            if prior_ports is None:
                os.environ.pop("NEYVIA_BROWSER_PROOF_PORTS", None)
            else:
                os.environ["NEYVIA_BROWSER_PROOF_PORTS"] = prior_ports


def self_check(scratch: Path, receipt_root: Path | None = None) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    receipt_root = Path(receipt_root or (Path("D:/NeyviaRuns/P22/browser-journey") / uuid.uuid4().hex))
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            observed = site_manual_journey(scratch / uuid.uuid4().hex, receipt_root)
            cases.append({"id": CONTRACTS[0], "contracts": list(CONTRACTS), "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACTS[0], "contracts": list(CONTRACTS), "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACTS[0]] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    scratch.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    (scratch / "outcomes.json").write_text(payload, encoding="utf-8")
    (receipt_root / "outcomes.json").write_text(payload, encoding="utf-8")
    return report
