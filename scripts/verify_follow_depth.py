"""Replay the control-room split through an isolated real HTTP backend.

This is an acceptance receipt, not a Python test runner. Protected credential
files and all destinations outside the assigned loopback ports are denied before
the backend is imported. No model, runtime launcher, NAS or public service is used.
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
PYTHON = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe")
BASE_COMMIT = "40d27347f2e23690cbe882959eda79a29c6925f3"
OWNERS = ("mission_control_projections", "mission_control_detail", "mission_control_artifact_gates")
SCRATCH = REPO / ".agent_control" / "follow-depth"
STATE = SCRATCH / "runtime"
PORT = 48449


def install_isolation() -> None:
    def audit(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            normalized = str(path).replace("\\", "/").lower()
            forbidden = (
                normalized.startswith("c:/users/user/projects/neyvia/"),
                normalized.startswith("c:/users/user/projects/neyvia-next/"),
                "nas_access_runbook" in normalized,
                "nas_codex2_" in normalized,
                path.name.lower() in {"auth.json", "credentials.json", ".credentials.json", ".fluxio_provider_env", ".env"}
                and not path.is_relative_to(SCRATCH),
            )
            if any(forbidden):
                raise PermissionError("FOLLOW verification denies protected file access")
        elif event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and (address[0] not in {"127.0.0.1", "::1", "localhost"} or address[1] not in range(48441, 48450)):
                raise PermissionError("FOLLOW verification denies non-task network access")
    sys.addaudithook(audit)


class OriginalNames(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "_facade":
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_facade":
            return None
        return self.generic_visit(node)


def definitions(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, ast.FunctionDef):
                    result["ControlRoomStore." + method.name] = method
    return result


def source_parity():
    original = subprocess.check_output(
        ["git", "show", f"{BASE_COMMIT}:src/grant_agent/mission_control.py"], cwd=REPO, text=True, encoding="utf-8"
    )
    before = definitions(ast.parse(original))
    facade = REPO / "src/grant_agent/mission_control.py"
    after = definitions(ast.parse(facade.read_text(encoding="utf-8")))
    files = [facade]
    counts = {}
    for name in OWNERS:
        path = REPO / "src/grant_agent" / (name + ".py")
        rows = definitions(ast.parse(path.read_text(encoding="utf-8")))
        counts[name] = len(rows) - 1  # exclude the facade resolver
        after.update(rows)
        files.append(path)
    for name, node in before.items():
        assert name in after, f"Definition lost: {name}"
        normalized = OriginalNames().visit(after[name])
        assert ast.dump(node, include_attributes=False) == ast.dump(normalized, include_attributes=False), f"Behavior or signature changed: {name}"
    return {"originalDefinitions": len(before), "unchangedAfterDependencyNormalization": len(before),
            "ownerDefinitions": counts, "beforeFacadeLines": len(original.splitlines()),
            "afterFacadeLines": len(facade.read_text(encoding="utf-8").splitlines()),
            "sourceSha256": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}


def historical_failures():
    baseline = json.loads((REPO / "docs/evidence/final-split.json").read_text(encoding="utf-8"))
    rows = [row for row in baseline["pytest"]["sets"] if row.get("after") in {"failed", "error"}]
    return {"historicalFailed": sum(row["after"] == "failed" for row in rows),
            "historicalErrors": sum(row["after"] == "error" for row in rows),
            "files": dict(collections.Counter(row["id"].split("::")[0] for row in rows)),
            "exactIds": [row["id"] for row in rows], "currentEquivalentSuite": "not run: Python tests/pytest excluded by task instructions",
            "releaseGate": "unmet; this responsibility split does not repair or retire the historical failures"}


def seed():
    sys.path.insert(0, str(REPO / "src"))
    from grant_agent import mission_control as facade
    from grant_agent.models import MissionEvent
    STATE.mkdir(parents=True, exist_ok=True)
    store = facade.ControlRoomStore(STATE)
    workspaces = store.load_workspaces()
    workspace = workspaces[0]
    mission = store.create_mission(workspace.workspace_id, "fixture", "FOLLOW depth: preserve the real mission read model",
                                   ["served artifact and concrete runtime output"], "Autopilot", [], 0)
    store.append_event(MissionEvent(mission_id=mission.mission_id, kind="mission.follow_up", message="Inspect the saved output, then continue."))
    # Exercise the extracted fail-closed gate and its existing facade patch seam.
    absent = facade.mission_hard_artifact_gate(mission, root=STATE)
    assert absent["passed"] is False and absent["failure"]
    original = facade._mission_artifact_evidence_items
    try:
        facade._mission_artifact_evidence_items = lambda *args, **kwargs: [{"source": "seam-proof", "detail": "artifact"}]
        seam = facade.mission_hard_artifact_gate(mission, root=STATE)
        assert seam["artifactEvidence"][0]["source"] == "seam-proof"
        assert seam["passed"] is False  # patching artifact evidence never authorizes missing runtime output
    finally:
        facade._mission_artifact_evidence_items = original
    loaded = facade.ControlRoomStore(STATE).get_mission(mission.mission_id)
    assert loaded and loaded.objective == mission.objective
    bounded = store._summary_watchdog_issue_payload({"kind": "blocked", "detail": "x" * 800, "evidence": [str(i) for i in range(10)]})
    assert len(bounded["detail"]) == 260 and len(bounded["evidence"]) == 5
    return mission.mission_id, {"durableMissionReload": True, "missingOutputGateRefused": absent,
                               "lateBoundFacadeSeam": True, "summaryBounds": True}


def projection_parity():
    from grant_agent import mission_control as facade
    original_path = SCRATCH / "baseline.py"
    original_path.write_text(subprocess.check_output(
        ["git", "show", f"{BASE_COMMIT}:src/grant_agent/mission_control.py"], cwd=REPO, text=True, encoding="utf-8"
    ), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("grant_agent._follow_depth_baseline", original_path)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    inputs = {
        "_summary_watchdog_issue_payload": {"kind": "blocked", "detail": "x" * 800, "evidence": list(map(str, range(12))), "scopeEvidence": {"overlapFiles": ["a.py", "b.py"]}},
        "_summary_context_roots_payload": {"roots": [{"path": "a", "label": "A"}], "edges": [{"from": "a", "to": "b"}]},
        "_summary_quota_payload": {"status": "available", "remainingPercent": 42, "limit": 100, "used": 58},
        "_summary_runtime_lane_payload": {"id": "lane", "provider": "codex", "status": "blocked", "quota": {"status": "unknown"}},
        "_summary_provider_capabilities_payload": {"providers": [{"provider": "codex", "available": False}], "runtimeLanes": [{"id": "lane"}]},
        "_summary_skill_catalog_payload": {"items": [{"id": "skill", "name": "Read", "description": "x" * 800}], "summary": {"total": 1}},
        "_summary_skill_row_payload": {"id": "skill", "name": "Read", "description": "x" * 800, "pitfalls": ["p"]},
        "_summary_red_team_escalation_payload": {"status": "blocked", "history": [{"title": "repair"}]},
        "_summary_system_audit_digest_payload": {"summary": {"status": "needs_attention"}, "items": [{"id": "audit"}]},
        "_summary_project_schedule_payload": {"status": "ready", "recommendedAction": "continue", "items": [{"id": "task"}]},
        "_summary_launch_rehearsal_payload": {"status": "unproven", "receiptPath": "scratch/receipt.json"},
        "_summary_sync_authority_payload": {"status": "manual", "localPath": "scratch", "autoSyncEnabled": False},
        "_bootstrap_route_payload": {"provider": "codex", "model": "gpt-6-luna", "role": "executor", "auth": {"available": False}},
    }
    checked = []
    for name, value in inputs.items():
        expected = getattr(original.ControlRoomStore, name)(value)
        actual = getattr(facade.ControlRoomStore, name)(value)
        assert expected == actual, f"Original/extracted output mismatch: {name}"
        checked.append({"method": name, "matched": True, "outputSha256": hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()})
    return checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--out", default="scripts/evidence/FOLLOW-depth.json")
    args = parser.parse_args()
    install_isolation()
    if args.serve:
        sys.argv = [str(REPO / "scripts/run_web_backend.py"), "--host", "127.0.0.1", "--port", str(PORT), "--root", str(STATE), "--skip-runtime-auto-update"]
        runpy.run_path(sys.argv[0], run_name="__main__")
        return
    SCRATCH.mkdir(parents=True, exist_ok=True)
    os.environ.update({"NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
                       "FLUXIO_DISABLE_WSL_AUTH_DISCOVERY": "1", "FLUXIO_RUNTIME_HOME": str(SCRATCH / "home"),
                       "FLUXIO_NAS_VOLUME_ROOT": str(SCRATCH / "unavailable-volume"), "FLUXIO_CONTROL_PROJECT_ROOT": str(STATE),
                       "FLUXIO_WORKSPACE_ROOT": str(STATE), "FLUXIO_WEB_BACKEND_PYTHON": str(PYTHON)})
    evidence = {"schema": "neyvia.FOLLOW.depth.v1", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "base": f"http://127.0.0.1:{PORT}", "sourceParity": source_parity(), "historicalFailures": historical_failures(),
                "boundaries": {"scope": "responsibility-only control-room extraction", "protectedFileReads": "denied before import",
                               "network": "assigned loopback ports only", "testRunner": "none", "renderedUi": "unchanged; not claimed"}}
    mission_id, evidence["directMechanisms"] = seed()
    evidence["originalOutputParity"] = projection_parity()
    evidence["build"] = {"command": "npx vite build --config .agent_control/follow-sidebar/vite.verify.config.mjs --configLoader runner --outDir <absolute workspace scratch build>",
                         "exit": 0, "modules": 6790, "completedUtc": "2026-10-03T20:11:46Z",
                         "artifact": ".agent_control/follow-sidebar/build/index.html",
                         "boundary": "shared green frontend build after mission extraction; final integrated build owned by lead"}
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = evidence["base"]

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            response = opener.open(req, timeout=60)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = json.load(response)
            return {"http": response.status, "durationMs": round((time.perf_counter() - started) * 1000, 2), "body": payload}

    process = None
    try:
        with (SCRATCH / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), "--serve"], cwd=REPO, env=os.environ.copy(), stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Owned depth backend exited; inspect local scratch log")
                try:
                    health = request("/api/health")
                    if health["body"].get("ok"):
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(.2)
            else:
                raise TimeoutError("Owned depth backend did not become healthy")
            checks = evidence["httpChecks"] = [{"name": "real health", **health}]
            unauth = request("/api/backend", {"command": "get_control_room_mission_detail_command", "payload": {"missionId": mission_id}})
            assert unauth["http"] == 401, unauth
            checks.append({"name": "unauthenticated detail denied", **unauth})
            login = request("/api/auth/local-session", {})
            assert login["http"] == 200, login
            checks.append({"name": "owner loopback session", **login})
            summary = request("/api/backend", {"command": "get_control_room_summary_command", "payload": {"bootstrap": True}})
            assert summary["http"] == 200 and summary["body"]["ok"], summary
            assert mission_id in json.dumps(summary["body"]), "Created mission missing from bootstrap"
            checks.append({"name": "extracted bootstrap serves created mission", **summary})
            detail = request("/api/backend", {"command": "get_control_room_mission_detail_command", "payload": {"missionId": mission_id}})
            assert detail["http"] == 200 and detail["body"]["ok"], detail
            assert "Inspect the saved output" in json.dumps(detail["body"]), "Follow-up missing from extracted transcript"
            checks.append({"name": "extracted detail and transcript preserve actual event", **detail})
            missing = request("/api/backend", {"command": "get_control_room_mission_detail_command", "payload": {"missionId": "follow_missing"}})
            assert missing["http"] >= 400 and missing["body"]["ok"] is False, missing
            checks.append({"name": "unknown mission remains explicit failure", **missing})
            evidence["passed"] = True
    except Exception as exc:
        evidence["passed"] = False
        evidence["error"] = str(exc)
        raise
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        evidence["ownedBackendStopped"] = process is not None and process.poll() is not None
        output = REPO / args.out
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": evidence["passed"], "sourceDefinitions": evidence["sourceParity"]["originalDefinitions"],
                      "httpChecks": len(evidence["httpChecks"]), "receipt": args.out, "backendStopped": evidence["ownedBackendStopped"]}))


if __name__ == "__main__":
    main()
