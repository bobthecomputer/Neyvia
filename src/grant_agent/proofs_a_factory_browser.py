"""User journeys through actual generated local apps with owned Obscura."""
from __future__ import annotations
from .proof_ports import proof_port, proof_text

import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .proofs_a_capabilities import require
from .browser_obscura import connect_owned_playwright


def self_check(scratch):
    from playwright.sync_api import sync_playwright
    notes = scratch / "factory/apps/proof-notes/dist"
    guided = scratch / "evolution/apps/proof-renewed-workbench/dist"
    require(notes.is_dir() and guided.is_dir(), "a.factory-notes-ui", "production draft directories missing")
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", proof_port(48462)), partial(Handler, directory=str(scratch)))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    receipt = {"authority": "Owned admitted Obscura actual generated drafts; local storage/download journeys only. No native build, model execution, activation, publication or NAS calls.", "notes": {}, "guided": {}}
    try:
        with sync_playwright() as playwright:
            native_browser, owned = connect_owned_playwright(playwright, scratch / "factory-browser",
                port=proof_port(48461), local_control=True)
            browser = native_browser.new_context(accept_downloads=True)
            try:
                page = browser.new_page()
                errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(proof_text("http://127.0.0.1:48462/")) else route.abort())
                page.goto(proof_text("http://127.0.0.1:48462/factory/apps/proof-notes/dist/"), wait_until="networkidle")
                require(page.title() == "Proof Notes" and page.locator("#empty-state").is_visible(), "a.factory-notes-ui", "generated notes first-use state missing")
                for entry in ["Field observation alpha", "Portable observation beta"]:
                    page.locator("#item-input").fill(entry); page.locator("#item-form button").click()
                require(page.locator("#item-list li").count() == 2, "a.factory-notes-ui", "notes entry flow did not render two records")
                page.locator("#item-search").fill("alpha")
                require(page.locator("#item-list li").count() == 1 and "alpha" in page.locator("#item-list").inner_text(), "a.factory-notes-ui", "search did not filter persisted records")
                page.locator("#item-list input[type=checkbox]").check(); page.reload(wait_until="networkidle")
                require(page.locator("#item-list li").count() == 2 and page.locator("#item-list input:checked").count() == 1, "a.factory-notes-ui", "entry completion or reload persistence failed")
                with page.expect_download() as download:
                    page.locator("#export-button").click()
                path = scratch / "notes-export.json"; download.value.save_as(str(path)); exported = json.loads(path.read_text())
                require(exported["schema"] == "neyvia.local-app-export/v1" and exported["appId"] == "local.proof.notes" and len(exported["items"]) == 2 and sum(item["complete"] for item in exported["items"]) == 1, "a.factory-notes-ui", "portable notes download lost identity or typed saved state")
                page.screenshot(path=str(scratch / "factory-notes.png"), full_page=True)
                receipt["notes"] = {"persistedEntries": 2, "completedEntries": 1, "searchMatchCount": 1, "downloadSha256": hashlib.sha256(path.read_bytes()).hexdigest(), "screenshot": str(scratch / "factory-notes.png")}
                page.goto(proof_text("http://127.0.0.1:48462/evolution/apps/proof-renewed-workbench/dist/"), wait_until="networkidle")
                page.locator("#run-goal").fill("PRIVATE BROWSER GOAL: verify local workflow")
                page.locator("#run-form button").click()
                page.locator("#complete-run").click()
                require("steps remain" in page.locator("#run-status").inner_text(), "a.factory-guided-ui", "incomplete workflow was sealed")
                require(page.locator("#step-list input[type=checkbox]").count() == 3, "a.factory-guided-ui", "exact reviewed workflow steps missing")
                for checkbox in page.locator("#step-list input[type=checkbox]").all():
                    checkbox.check()
                page.locator("#complete-run").click()
                require("Add a proof note" in page.locator("#run-status").inner_text(), "a.factory-guided-ui", "run without proof was sealed")
                page.locator("#run-proof").fill("PRIVATE BROWSER PROOF: local controls pass")
                page.locator("#complete-run").click(); page.wait_for_function("document.querySelector('#run-history').children.length === 1")
                page.reload(wait_until="networkidle")
                require(page.locator("#run-history li").count() == 1, "a.factory-guided-ui", "sealed run failed reload persistence")
                with page.expect_download() as download:
                    page.locator("#export-button").click()
                path = scratch / "guided-outcomes.json"; download.value.save_as(str(path)); bundle = json.loads(path.read_text()); run = bundle["runs"][0]
                canonical = json.dumps({key: value for key, value in run.items() if key != "receiptDigest"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                require(bundle["schema"] == "neyvia.capability-run-bundle/v2" and run["schema"] == "neyvia.capability-run/v2" and run["receiptDigest"] == hashlib.sha256(canonical).hexdigest() and len(run["steps"]) == 3 and all(step["complete"] for step in run["steps"]) and run["candidateDigest"] == bundle["candidateDigest"] and run["proofLease"] == bundle["proofLease"] and bundle["candidateActivated"] is False and bundle["transcriptsIncluded"] is False and len(bundle["handoffDigest"]) == 64, "a.factory-guided-ui", "browser-produced sealed receipt lost hash, package/lease binding or inactive boundary")
                with page.expect_download() as download:
                    page.locator("#return-button").click()
                returned = scratch / "guided-return.json"; download.value.save_as(str(returned)); returned_bundle = json.loads(returned.read_text())
                require(returned_bundle["runs"][0]["receiptDigest"] == run["receiptDigest"], "a.factory-guided-ui", "top-level explicit return differs from sealed exported evidence")
                page.screenshot(path=str(scratch / "factory-guided.png"), full_page=True)
                host = scratch / "guided-host.html"
                host.write_text('<!doctype html><title>Explicit outcome return host</title><iframe src="/evolution/apps/proof-renewed-workbench/dist/" style="width:100%;height:900px"></iframe><script>window.addEventListener("message",event=>{if(event.origin===location.origin) window.returnedOutcome=event.data;});</script>')
                page.goto(proof_text("http://127.0.0.1:48462/guided-host.html"), wait_until="networkidle")
                page.frame_locator("iframe").locator("#return-button").click()
                page.wait_for_function("window.returnedOutcome?.type === 'neyvia:capability-run-bundle:v2'")
                message = page.evaluate("window.returnedOutcome")
                require(message["bundle"]["runs"][0]["receiptDigest"] == run["receiptDigest"] and message["bundle"]["proofLease"]["revision"] == 2, "a.factory-guided-ui", "embedded explicit return lost sealed message or renewed lease")
                require(not errors, "a.factory-guided-ui", "generated app reported browser errors: " + "; ".join(errors))
                receipt["guided"] = {"sealedRuns": 1, "completedSteps": 3, "receiptDigest": run["receiptDigest"], "handoffDigest": bundle["handoffDigest"], "screenshot": str(scratch / "factory-guided.png"), "incompleteAndMissingProofRejected": True, "embeddedExplicitReturnObserved": True, "proofLeaseRevision": 2}
            finally:
                try:
                    browser.close()
                finally:
                    owned.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    (scratch / "factory-browser-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
