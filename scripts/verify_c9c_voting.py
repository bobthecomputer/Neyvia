"""Exercise generated blind voting pages in Neyvia's actual Obscura workspace."""
from __future__ import annotations
import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--obscura", type=Path, required=True)
    parser.add_argument("--engine-port", type=int, required=True)
    parser.add_argument("--fixture-port", type=int, required=True)
    args = parser.parse_args()
    ports = {args.engine_port, args.fixture_port}
    if len(ports) != 2 or not ports <= set(range(48761, 48770)):
        raise ValueError("Distinct explicit C9c ports required")
    os.environ["NEYVIA_OBSCURA_EXE"] = str(args.obscura.resolve())
    os.environ["NEYVIA_BROWSER_PROOF_PORTS"] = ",".join(map(str, sorted(ports)))
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    from grant_agent.neyvia_browser import BrowserError, service_for

    output = REPO / "scripts/evidence/C9c-voting-builds"
    receipt_path = REPO / "scripts/evidence/C9c-voting.json"
    protected = [REPO / f"proof/{round_name}-blind/{name}" for round_name in ("r5", "r6")
                 for name in ("site/index.html", "answer-key.SPOILER.json")]
    before = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    for round_name in ("r5", "r6"):
        subprocess.run([sys.executable, str(REPO / f"proof/{round_name}-blind/build.py"), "--out-dir", str(output / round_name)], check=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", args.fixture_port), partial(Handler, directory=str(output)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = service_for(REPO / ".agent_control/C9c-voting" / str(time.time_ns()))
    receipt = {"schema": "neyvia.c9c-voting-proof.v1", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "ports": sorted(ports), "engine": "Neyvia browser service + explicit Obscura", "rounds": [],
               "limitations": ["Shared cloud vote storage was not contacted. Historical published pages are preserved; future generator output is changed."]}
    try:
        browser.request("headless.start", {"port": args.engine_port, "allowLocalFixtures": True}, owner=True)
        for round_name in ("r5", "r6"):
            tab = browser.request("tab.open", {"url": f"http://127.0.0.1:{args.fixture_port}/{round_name}/index.html", "engine": "obscura"}, owner=True)["tabId"]
            browser.request("tab.grant", {"tabId": tab, "enabled": True}, owner=True)
            worker = browser.headless.profiles["default"]
            def evaluate(expression):
                return worker.executor.submit(lambda: worker.pages[tab]["page"].evaluate(expression)).result(timeout=30)
            def action(role, name, operation, value=None, index=0):
                for attempt in range(3):
                    obs = browser.request("observe", {"tabId": tab}, owner=True)
                    target = [e for e in obs["elements"] if e["role"] == role and e["name"] == name][index]
                    payload = {"tabId": tab, "revision": obs["revision"], "element": target["id"], "action": operation}
                    if value is not None:
                        payload["value"] = value
                    try:
                        return browser.request("action", payload)
                    except BrowserError as exc:
                        if exc.code != "stale_projection" or attempt == 2:
                            raise
                        # The browser explicitly refused before acting. Refresh
                        # while the asynchronous local save status settles.
                        row.setdefault("staleRefusals", []).append(exc.code)
                        time.sleep(0.1)
            row = {"round": round_name, "pageSha256": hashlib.sha256((output / round_name / "index.html").read_bytes()).hexdigest(), "checks": []}
            receipt["rounds"].append(row)
            initial = browser.request("observe", {"tabId": tab}, owner=True)
            assert len([e for e in initial["elements"] if e["role"] == "combobox" and e["name"] == "Which is better?"]) >= 2
            assert not [e for e in initial["elements"] if e["name"] in ("A is Claude", "B is Claude") and e["enabled"]]
            assert evaluate("async () => {await castVote(DATA.pairs[0].id, 'A'); return Object.keys(votes).length}") == 0
            assert evaluate("() => document.querySelector('.reveal-slot').textContent") == ""
            row["checks"].append("Blank preference refuses identity submission and reveal")
            action("combobox", "Which is better?", "select", "B")
            action("button", "A is Claude", "click")
            actual = evaluate("() => votes[DATA.pairs[0].id]")
            assert actual["pick"] == "A" and actual["preference"] == "B" and actual["preferenceCollectedBlind"] is True
            assert actual["schema"] == "neyvia.preference-vote.v2"
            assert "You preferred B." in evaluate("() => document.querySelector('.reveal-slot').textContent")
            row["firstVote"] = actual
            row["checks"].append("Real select and click save identity A separately from preference B")
            action("combobox", "Which is better?", "select", "tie", index=1)
            action("button", "B is Claude", "click", index=1)
            assert evaluate("() => votes[DATA.pairs[1].id].preference") == "tie"
            unchanged = evaluate("async () => {const v=JSON.stringify(votes[DATA.pairs[0].id]);await castVote(DATA.pairs[0].id,'B');return v===JSON.stringify(votes[DATA.pairs[0].id])}")
            assert unchanged is True
            row["checks"].append("Tie persists; repeated identity submission cannot change the revealed vote")
            row["storageBeforeReload"] = evaluate(f"() => {{try {{return {{type:typeof localStorage,value:localStorage.getItem('{round_name}votes')}}}}catch(e){{return {{error:String(e)}}}}}}")
            browser.request("tab.reload", {"tabId": tab}, owner=True)
            restored = evaluate("() => [votes[DATA.pairs[0].id],votes[DATA.pairs[1].id]]")
            row["votesAfterActualEngineReload"] = restored
            row["engineReloadPreservedVotes"] = bool(restored[0] and restored[1])
            if not row["engineReloadPreservedVotes"]:
                receipt["limitations"].append(f"{round_name}: Obscura 0.2.3 loses actual origin localStorage on tab.reload. Save is real; boot parsing below uses the exact saved row reinserted as an explicit controlled fixture, not a claimed engine persistence fix.")
                saved = json.dumps(row["storageBeforeReload"]["value"])
                evaluate(f"async () => {{localStorage.setItem('{round_name}votes',{saved});await boot();}}")
                restored = evaluate("() => [votes[DATA.pairs[0].id],votes[DATA.pairs[1].id]]")
            assert restored[0]["pick"] == "A" and restored[0]["preference"] == "B" and restored[1]["preference"] == "tie"
            row["restoredVotes"] = restored
            row["checks"].append("Actual page boot parser restores separate identity/preference fields from the exact saved localStorage row")
            evaluate(f"async () => {{const p=DATA.pairs[0].id;localStorage.setItem('{round_name}votes',JSON.stringify({{[p]:{{pairId:p,pick:'B',correct:false,at:'2026-10-04T00:00:00Z'}}}}));Object.keys(votes).forEach(k=>delete votes[k]);await boot();}}")
            legacy = evaluate("() => ({vote:votes[DATA.pairs[0].id],text:document.querySelector('.reveal-slot').textContent,disabled:document.querySelector('select[data-preference]').disabled})")
            assert "preference" not in legacy["vote"] and legacy["disabled"] and "older vote did not ask" in legacy["text"]
            row["legacyVote"] = legacy["vote"]
            row["checks"].append("Historical identity-only vote remains unchanged, preference unknown and post-reveal collection disabled")
            browser.request("tab.close", {"tabId": tab}, owner=True)
            # Each round gets clean local storage despite reusing the origin.
        after = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        assert before == after
        receipt["historicalPagesAndKeysUnchanged"] = before
        table_html = '<!doctype html><title>C9c table collector</title><table>' + '<tr>' + '<td>' + 'x' * 4001 + '</td>' + '<td>cell</td>' * 100 + '</tr>' + '<tr><td>row</td></tr>' * 100 + '</table><table><tr><th>Outer</th><td>Cell<table><tr><td>Nested</td></tr></table></td></tr></table><input type="password" value="controlled-synthetic-secret">'
        (output / "tables.html").write_text(table_html, encoding="utf-8")
        table_tab = browser.request("tab.open", {"url": f"http://127.0.0.1:{args.fixture_port}/tables.html", "engine": "obscura"}, owner=True)["tabId"]
        obs = browser.request("observe", {"tabId": table_tab}, owner=True)
        assert obs["tablesTruncated"] and len(obs["tables"][0]) == 100 and len(obs["tables"][0][0]) == 100 and len(obs["tables"][0][0][0]) == 4000
        assert len(obs["tables"][1]) == 1 and len(obs["tables"][1][0]) == 2 and obs["tables"][2] == [["Nested"]]
        password = next(e for e in obs["elements"] if e["secret"])
        assert password["value"] == "[redacted]" and password["actions"] == []
        receipt["tableCompatibilitySentinels"] = {"rows": len(obs["tables"][0]), "cells": len(obs["tables"][0][0]), "cellCharacters": len(obs["tables"][0][0][0]), "truncated": obs["tablesTruncated"], "outerRows": len(obs["tables"][1]), "nestedTable": obs["tables"][2], "secretRedactedAndNotActionable": True}
        browser.request("tab.close", {"tabId": table_tab}, owner=True)
        receipt["sourceHashes"] = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in [
            REPO / "src/grant_agent/perception_browser.py", REPO / "src/grant_agent/browser_obscura.py", Path(__file__),
            *(REPO / f"proof/{name}-blind/{file}" for name, file in [("r5", "build.py"), ("r5", "template.html"), ("r6", "build.py"), ("r6", "page.template.html")])]}
        receipt["pageContractChecksPassed"] = True
        receipt["endToEndPersistenceProven"] = all(row["engineReloadPreservedVotes"] for row in receipt["rounds"])
        receipt["ok"] = receipt["endToEndPersistenceProven"]
    except Exception as exc:
        receipt["ok"] = False
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        browser.request("headless.stop", {}, owner=True)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": receipt["ok"], "rounds": len(receipt["rounds"]), "receipt": str(receipt_path)}))


if __name__ == "__main__":
    main()
