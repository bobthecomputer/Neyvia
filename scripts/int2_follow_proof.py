"""Real FOLLOW HTTP/tool journeys on the explicitly selected integration server.

Disposable action executions and state reports are real; they confer no proof
of installed editor behavior or public promotion. No credentials are read.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    assert args.port == 48601 and root.is_relative_to(REPO / ".agent_control/int2")
    from int2_pytest_guard import install
    install()
    scratch = REPO / ".agent_control/int2/follow-proof-actions"
    scratch.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    checks = []
    evidence = {"base": base, "root": str(root), "checks": checks, "passed": False,
                "boundary": "Production HTTP dispatch and model tool surfaces; real disposable action processes and persistence. No installed editor or public service behavior claimed."}

    def request(route, payload=None):
        started = time.perf_counter()
        req = urllib.request.Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with client.open(req, timeout=60) as response:
                result = json.load(response)
                return response.status, result
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def good(route, payload=None):
        status, value = request(route, payload)
        assert status == 200 and value.get("ok", True), (route, status, value)
        return value.get("data", value)

    def command(name, payload=None):
        return good("/api/backend", {"command": name, "payload": payload or {}})

    def tool(name, payload=None):
        receipt = good("/api/ui/tools/call", {"tool": name, "arguments": payload or {}})
        assert receipt["status"] == "completed" and receipt["ok"] is True
        return receipt["result"]

    def check(name, details):
        checks.append({"name": name, "passed": True, **details})
        print(name, flush=True)

    try:
        good("/api/auth/local-session", {})
        reported = good("/api/ui/app-state", {"app": "game-dev", "clientId": "INT2", "state": {"tab": "godot", "picked": {"godot": "int2-reported-only"}}})
        selected = command("gamedev_state_command")
        model = tool("neyvia.gamedev.state")
        assert selected["ui"] == reported["state"] == model["ui"]
        assert selected["ui"]["source"] == "ui" and not selected["sessions"]
        check("Reported Game Dev selection round-trips through app-state, backend and model tool", {"state": selected})
        status, rejected = request("/api/ui/app-state", {"app": "game-dev", "state": {"tab": "unknown"}})
        assert status >= 400 and rejected.get("ok") is False
        recent = command("gamedev_receipts_command", {"limit": 20})
        model_recent = tool("neyvia.gamedev.receipts", {"limit": 20})
        assert recent == model_recent and "receipts" in recent
        status, bad = request("/api/backend", {"command": "gamedev_receipts_command", "payload": {"limit": True}})
        assert status >= 400 and bad.get("ok") is False
        status, unavailable = request("/api/backend", {"command": "gamedev_action_command", "payload": {"sessionId": "int2-reported-only", "action": "inspect", "requestId": "int2-missing-native-editor"}})
        assert status == 400 and "connected editor session" in unavailable["error"]
        check("Game Dev receipts share backend/model result and refuse an action on reported-only selection", {"receiptCount": len(recent["receipts"]), "missingEditorStatus": status,
              "limitation": "No native editor is connected on the disposable backend; no editor action receipt was manufactured."})

        from grant_agent.mission_control import ControlRoomStore
        from grant_agent.workspace_actions import _run_action, _workspace_action_receipt_path
        store = ControlRoomStore(root)
        process = scratch / "action_fixture.py"
        process.write_text("import sys\nprint('INT2 actual action '+sys.argv[1])\nraise SystemExit(0 if sys.argv[1]=='success' else 7)\n", encoding="utf-8")
        actions = []
        for mode in ("success", "failure"):
            spec = {"actionId": "int2-" + mode, "label": "INT2 disposable " + mode, "commandSurface": "validate.workspace",
                    "command": f'"{sys.executable}" "{process}" {mode}', "platform": "local", "requiresApproval": False}
            record = asdict(_run_action(root=scratch, surface="workspace", spec=spec, workspace=None, approved=False))
            assert record["result"]["ok"] is (mode == "success") and record["result"]["exit_code"] == (0 if mode == "success" else 7)
            assert "INT2 actual action " + mode in record["result"]["stdout"]
            store.append_workspace_action("__int2__", record)
            observed = command("get_control_room_workspace_action_receipt_command", {"actionId": record["action_id"]})
            assert observed == record
            # Also verify the hashed compact-history form expected by the new reader.
            detail = _workspace_action_receipt_path(root, record["action_id"])
            detail.parent.mkdir(parents=True, exist_ok=True)
            data = (json.dumps(record, indent=2) + "\n").encode()
            detail.write_bytes(data)
            histories = store.load_workspace_actions()
            compact = dict(record, detailPath=detail.relative_to(root).as_posix(), detailSha256=hashlib.sha256(data).hexdigest())
            compact["result"] = {key: value for key, value in record["result"].items() if key not in ("stdout", "stderr", "payload")}
            histories["__int2__"] = [compact if row["action_id"] == record["action_id"] else row for row in histories["__int2__"]]
            store.workspace_actions_path.write_text(json.dumps(histories), encoding="utf-8")
            assert command("get_control_room_workspace_action_receipt_command", {"actionId": record["action_id"]}) == record
            detail.write_bytes(data + b" ")
            status, bad = request("/api/backend", {"command": "get_control_room_workspace_action_receipt_command", "payload": {"actionId": record["action_id"]}})
            assert status == 400 and "hash mismatch" in bad["error"]
            detail.write_bytes(data)
            actions.append({"id": record["action_id"], "exitCode": record["result"]["exit_code"], "ok": record["result"]["ok"], "detailSha256": hashlib.sha256(data).hexdigest(), "tamperStatus": status})
        status, bad = request("/api/backend", {"command": "get_control_room_workspace_action_receipt_command", "payload": {"actionId": "int2-nonexistent"}})
        assert status == 400 and "Unknown workspace action" in bad["error"]
        check("Durable real success/error action receipts, compact hash read, tamper and nonexistent refusal", {"actions": actions, "nonexistentStatus": status,
              "fixtureBoundary": "Real production _run_action processes and append_workspace_action; compact detail fixture exercises the actual HTTP reader, not the setup compactor's writer."})

        settings = command("settings_get_command")
        original = settings["settings"]["localOnly"]
        from grant_agent import local_network_policy as policy
        policy.install(root)
        try:
            command("settings_update_command", {"expectedRevision": settings["revision"], "patch": {"localOnly": True}})
            assert policy.enabled()
            with socket.socket() as stream:
                try:
                    stream.connect(("192.0.2.1", 80))
                except policy.LocalOnlyError as exc:
                    assert exc.code == "local_only"
                else:
                    raise AssertionError("Local-only failed to block prohibited network")
            assert good("/api/health")["ok"] is True
            check("Saved HTTP local-only mode actually rejects egress before a network connection", {"code": "local_only", "target": "documentation-only192.0.2.1", "loopbackHealthWorks": True})
        finally:
            latest = command("settings_get_command")
            command("settings_update_command", {"expectedRevision": latest["revision"], "patch": {"localOnly": original}})
            assert command("settings_get_command")["settings"]["localOnly"] is original
            evidence["localOnlyRestored"] = True
        evidence["passed"] = True
    finally:
        evidence["checkedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        evidence["sourceSha256"] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in
                                    ["scripts/int2_follow_proof.py", "src/grant_agent/workspace_actions.py", "src/grant_agent/neyvia_gamedev.py", "src/grant_agent/local_network_policy.py"]}
        output = REPO / "scripts/evidence/int2/follow-routes.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
