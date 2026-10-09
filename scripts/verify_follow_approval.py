"""Bounded original approval/replay cases plus isolated production journeys.

This calls reviewed functions directly; no pytest runner, host provider, public
service, credential or NAS access is admitted. CLI fixtures remain protocol
fixtures, not evidence of an actual signed-in model completing a task.
"""
from __future__ import annotations

import argparse
import faulthandler
import hashlib
import importlib.util
import inspect
import http.cookiejar
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import threading
import urllib.error
import urllib.request
import uuid

REPO = Path(__file__).resolve().parents[1]
SCRATCH = REPO / ".agent_control/follow-approval"
RECEIPT = REPO / "scripts/evidence/FOLLOW-approval.json"
PORT = 48444


def isolate():
    import verify_follow_depth as depth
    depth.SCRATCH = SCRATCH
    depth.STATE = SCRATCH / "runtime"
    depth.install_isolation()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "temporary").mkdir(exist_ok=True)
    tempfile.tempdir = str(SCRATCH / "temporary")
    home = SCRATCH / "home"
    home.mkdir(exist_ok=True)
    os.environ.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "roaming"),
                       "LOCALAPPDATA": str(home / "local"), "CODEX_HOME": str(home / ".codex"),
                       "CLAUDE_CONFIG_DIR": str(home / ".claude"), "OPENCODE_DATA_DIR": str(home / "opencode"),
                       "FLUXIO_DISABLE_WSL_AUTH_DISCOVERY": "1", "FLUXIO_RUNTIME_HOME": str(home),
                       "FLUXIO_RUNTIME_ROOT": str(SCRATCH / "managed"), "SYNTELOS_RUNTIME_ROOT": str(SCRATCH / "managed"),
                       "NEYVIA_MANAGED_RUNTIME_ROOT": str(SCRATCH / "managed"),
                       "FLUXIO_NAS_VOLUME_ROOT": str(SCRATCH / "unavailable-volume"),
                       "FLUXIO_CONTROL_ROOT": str(SCRATCH / "control"), "NEYVIA_TOOL_AUTO_UPDATE": "0",
                       "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
                       "FLUXIO_RUNTIME_AUTO_UPDATE": "0", "NEYVIA_UI_BACKEND_URL": f"http://127.0.0.1:{PORT}",
                       "NEYVIA_CONNECTED_SERVICE_PORT": str(PORT)})
    # Refuse real provider launch before a child exists. Only the reviewed
    # Python fixture and dead-owner no-op are allowed; git inspection is local.
    def subprocess_audit(event, args):
        if event != "subprocess.Popen":
            return
        argv = args[1]
        if isinstance(argv, str):
            # Windows has already quoted an argv list by the time its audit
            # event fires. Parse only for admission; never execute this text.
            argv = [part.strip('"') for part in shlex.split(argv, posix=False)]
        executable = Path(str(argv[0])).name.lower()
        if executable in {"python", "python.exe"} and len(argv) >= 3 and argv[1:3] == ["-c", "pass"]:
            return
        if executable in {"python", "python.exe"} and len(argv) > 1 and Path(str(argv[1])).name == "fake_claude_terminal.py":
            return
        if executable in {"git", "git.exe"}:
            return
        raise PermissionError("Approval proof refuses non-fixture process execution")
    sys.addaudithook(subprocess_audit)
    sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    name = "follow_approval_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def replay(selected_id=None):
    import pytest
    cases = json.loads((REPO / "scripts/evidence/FOLLOW-failures.json").read_text(encoding="utf-8"))["cases"]
    selected = [row for row in cases if row["rootCauseGroup"] in {"approval-recovery-or-replay", "capability-proof-admission"}]
    if selected_id:
        selected = [row for row in selected if selected_id in row["id"]]
        assert selected
    modules, outcomes = {}, []
    for row in selected:
        parts = row["id"].split("::")
        source = REPO / parts[0]
        module = modules.setdefault(parts[0], load(source))
        root = SCRATCH / "cases" / (parts[-1] + "-" + uuid.uuid4().hex[:8])
        root.mkdir(parents=True)
        with pytest.MonkeyPatch.context() as monkeypatch:
            cleanup = None
            arguments = {}
            if len(parts) == 3:
                case = getattr(module, parts[1])(methodName=parts[2])
                function = getattr(case, parts[2])
            else:
                function = getattr(module, parts[1])
                for name in inspect.signature(function).parameters:
                    if name == "tmp_path":
                        arguments[name] = root
                    elif name == "monkeypatch":
                        arguments[name] = monkeypatch
                    elif name == "make_broker":
                        cleanup = module.make_broker.__wrapped__(root)
                        arguments[name] = next(cleanup)
                    elif name == "term":
                        arguments[name] = module.term.__wrapped__(root, monkeypatch)
                    else:
                        raise AssertionError("Unreviewed fixture: " + name)
            try:
                print("START " + row["id"], flush=True)
                faulthandler.dump_traceback_later(45)
                function(**arguments)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                frames = traceback.extract_tb(exc.__traceback__)
                outcomes.append({"id": row["id"], "passed": False, "exceptionType": type(exc).__name__,
                                 "message": str(exc)[:1200], "sourceLocations": [{"path": str(Path(f.filename).relative_to(REPO)) if Path(f.filename).is_relative_to(REPO) else Path(f.filename).name, "line": f.lineno} for f in frames[-6:]]})
            else:
                outcomes.append({"id": row["id"], "passed": True})
            finally:
                faulthandler.cancel_dump_traceback_later()
                if cleanup is not None:
                    try:
                        next(cleanup)
                    except StopIteration:
                        pass
        print(json.dumps(outcomes[-1]), flush=True)
    return {"passed": all(row["passed"] for row in outcomes), "runner": "direct original functions; fixture utility only, no pytest runner",
            "sourceHashes": {name: digest(REPO / name) for name in modules}, "cases": outcomes}


def journeys():
    from unittest import mock
    from grant_agent.connected_sessions.claude import ClaudeAdapter, ClaudeSessionError
    from grant_agent.connected_sessions.model import TurnOptions
    from grant_agent import cli
    from grant_agent.workspace_actions import load_workspace_action_receipt
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
    release = load(REPO / "tests/test_release_acceptance.py")
    case = release.ReleaseAcceptanceTests()
    run_root = SCRATCH / ("journeys-" + uuid.uuid4().hex[:8])
    run_root.mkdir()
    trust_root = run_root / "trust"
    trust_root.mkdir()
    work = trust_root / "work"
    work.mkdir()
    cfg = trust_root / "config"
    cfg.mkdir()
    trust_rows = []
    class AdmittedToPreflight(Exception):
        pass
    adapter = ClaudeAdapter(config_dir=cfg, cli_path=["never-executed"], context_probe=False)
    with mock.patch.object(adapter, "preflight", side_effect=AdmittedToPreflight) as preflight:
        examples = [
            ("explicit_false", {str(work): {"hasTrustDialogAccepted": False}}, False),
            ("explicit_true", {str(work): {"hasTrustDialogAccepted": True}}, True),
            ("parent_true", {str(work.parent): {"hasTrustDialogAccepted": True}}, True),
            ("child_false_parent_true", {str(work): {"hasTrustDialogAccepted": False}, str(work.parent): {"hasTrustDialogAccepted": True}}, False),
            ("unrelated", {str(trust_root / "unrelated"): {"hasTrustDialogAccepted": True}}, None),
            ("empty", {}, None),
        ]
        for name, projects, expected in examples:
            (cfg / ".claude.json").write_text(json.dumps({"projects": projects}), encoding="utf-8")
            assert adapter._folder_trusted(str(work)) is expected
            before = preflight.call_count
            try:
                adapter.start_turn(None, "hello", TurnOptions(transport="terminal"), cwd=str(work), run_id=name, emit=lambda event: None)
            except ClaudeSessionError as exc:
                assert expected is False and exc.code == "folder_not_trusted"
                assert preflight.call_count == before
                code = exc.code
            except AdmittedToPreflight:
                assert expected is not False and preflight.call_count == before + 1
                code = "existing_preflight_path"
            else:
                raise AssertionError("A trust proof must stop before execution")
            trust_rows.append({"case": name, "trust": expected, "result": code, "preflightCalls": preflight.call_count - before, "launchedChildren": 0})
    root = run_root / "product"
    root.mkdir()
    cli.bootstrap_project(root)
    (root / "pyproject.toml").write_text("[project]\nname='approval-proof'\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"approval-proof"}\n', encoding="utf-8")
    for dependency in ("uv", "openclaw", "hermes"):
        case._set_marker(root, dependency)
    with case._patch_acceptance_environment(root):
        code, workspace = case._run_json_command(cli.cmd_workspace_save, root=str(root), name="Owned proof", path=str(root), default_runtime="openclaw", user_profile="experimental", workspace_id=None)
        assert code == 0
        workspace_id = workspace["workspace"]["workspace_id"]
        backend = FluxioWebBackend(root, run_root)
        def in_process_cli(selected_root, command, arguments, **kwargs):
            assert command == "workspace-action" and Path(selected_root) == root
            args = dict(zip(arguments[::2], arguments[1::2]))
            code, payload = case._run_json_command(cli.cmd_workspace_action, root=str(root), surface=args["--surface"], action_id=args["--action-id"], workspace_id=args.get("--workspace-id"), approved=False)
            return payload
        backend._run_cli = in_process_cli
        server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", PORT), make_handler(backend))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f"http://127.0.0.1:{PORT}"
        def request(path, payload=None):
            req = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            try:
                response = opener.open(req, timeout=60)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                body = response.read()
                return response.status, len(body), json.loads(body)
        measurements = []
        try:
            assert request("/api/health")[2]["ok"] is True
            assert request("/api/auth/local-session", {})[2]["ok"] is True
            for cycle in range(30):
                status, size, body = request("/api/backend", {"command": "apply_control_room_workspace_action_command", "payload": {"surface": "setup", "actionId": "verify_setup_health", "workspaceId": workspace_id}})
                assert status == 200 and body["ok"]
                health = body["data"]["record"]["result"]["payload"]["setupHealth"]
                assert health["environmentReady"] and not health["installerReady"]
                assert "First guided mission" in health["missingDependencies"]
                for dependency in health["dependencies"]:
                    latest = dependency.get("latestAction", {})
                    assert "payload" not in latest.get("result", {}) and "stdout" not in latest.get("result", {})
                for rows in health["actionHistoryByDependency"].values():
                    assert len(rows) <= 6 and all("payload" not in row["result"] for row in rows)
                history_size = (root / ".agent_control/workspace_actions.json").stat().st_size
                measurements.append({"cycle": cycle + 1, "http": status, "responseBytes": size, "durableHistoryBytes": history_size})
                print("SETUP " + json.dumps(measurements[-1]), flush=True)
            assert max(row["responseBytes"] for row in measurements) < 2_000_000
            assert measurements[-1]["durableHistoryBytes"] < 10_000_000
            assert measurements[-1]["responseBytes"] < measurements[0]["responseBytes"] * 1.25
            receipt_id = body["data"]["record"]["action_id"]
            original_record = body["data"]["record"]
            assert load_workspace_action_receipt(root, receipt_id) == original_record
            detail_command = {"command": "get_control_room_workspace_action_receipt_command", "payload": {"actionId": receipt_id}}
            status, _, detail_response = request("/api/backend", detail_command)
            assert status == 200 and detail_response["data"] == original_record
            index_path = root / ".agent_control/workspace_actions.json"
            index_bytes = index_path.read_bytes()
            index = json.loads(index_bytes)
            summary = next(row for row in index["__setup__"] if row["action_id"] == receipt_id)
            detail_path = root / summary["detailPath"]
            detail_bytes = detail_path.read_bytes()
            assert digest(detail_path) == summary["detailSha256"]
            detail_path.write_bytes(detail_bytes + b" ")
            status, _, refused = request("/api/backend", detail_command)
            assert status == 400 and "hash mismatch" in refused["error"]
            try:
                load_workspace_action_receipt(root, receipt_id)
            except ValueError as exc:
                assert "hash mismatch" in str(exc)
            else:
                raise AssertionError("Tampered receipt was accepted")
            detail_path.write_bytes(detail_bytes)
            summary["detailPath"] = "../escape.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            status, _, refused = request("/api/backend", detail_command)
            assert status == 400 and "path does not match" in refused["error"]
            try:
                load_workspace_action_receipt(root, receipt_id)
            except ValueError as exc:
                assert "path does not match" in str(exc)
            else:
                raise AssertionError("Untrusted detail path was accepted")
            index_path.write_bytes(index_bytes)
            status, _, refused = request("/api/backend", {"command": detail_command["command"], "payload": {"actionId": "../../outside"}})
            assert status == 400 and "Invalid workspace action ID" in refused["error"]
            try:
                load_workspace_action_receipt(root, "../../outside")
            except ValueError as exc:
                assert "Invalid workspace action ID" in str(exc)
            else:
                raise AssertionError("Escaping action ID was accepted")
            assert load_workspace_action_receipt(root, receipt_id) == original_record
            legacy = {"action_id": "workspace_action_legacy", "gate": {"status": "rejected", "required": True},
                      "result": {"ok": False, "payload": {"legacyProof": "retained-inline"}}}
            original_index = json.loads(index_bytes)
            original_index["legacy-fixture"] = [legacy]
            index_path.write_text(json.dumps(original_index), encoding="utf-8")
            assert load_workspace_action_receipt(root, legacy["action_id"]) == legacy
            index_path.write_bytes(index_bytes)
            details = list((root / ".agent_control/workspace_action_receipts").glob("*.json"))
            assert len(details) == 30
            assert not list((root / ".agent_control/workspace_action_receipts").glob("*.tmp"))
            detail_proof = {"retainedFullReceipts": len(details), "totalBytes": sum(path.stat().st_size for path in details), "reloadExactlyMatched": True,
                            "hashTamperRefused": True, "serializedPathEscapeRefused": True, "invalidIdRefused": True,
                            "httpReload": 200, "httpTamper": 400, "httpPathEscape": 400, "httpInvalidId": 400,
                            "legacyInlineReceiptUnchanged": True, "atomicTemporaryFilesRemaining": 0}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
        # A normal verification failure still creates the authorized repair.
        original_engine = case._engine_result_factory(root)
        def failure_engine(**kwargs):
            result = original_engine(**kwargs)
            result.update(autopilot_status="failed", changed_files=[], verification_failures=["Disposable verification failure"],
                          plan_revisions=[{"revision_id": "verification-failure", "trigger": "verification_failed", "summary": "Disposable verification failed"}])
            return result
        with mock.patch.object(cli, "_invoke_engine", side_effect=failure_engine), mock.patch.object(cli, "_launch_async_mission_resume", return_value={"started": True, "pid": 0, "fixture": True}) as launch:
            code, payload = case._run_json_command(cli.cmd_mission_start, root=str(root), workspace_id=workspace_id, runtime="openclaw", objective="Exercise ordinary verification repair.", success_check=["Verification passes"], mode="autopilot", budget_hours=1, profile="experimental", escalation_destination="", run_until="pause_on_failure")
            assert payload["mission"]["state"]["status"] == "verification_failed"
            assert launch.call_count == 1
            assert payload["autoRepair"]["repairMission"]["mission_id"] != payload["mission"]["mission_id"]
            recovery = {"ordinaryFailureRepairDispatchCalls": launch.call_count, "launchedChildren": 0, "repairMissionCreated": payload["autoRepair"]["repairMissionCreated"]}
    rejected_rows = []
    original_command = case._run_json_command
    def capture_rejection(command, **kwargs):
        code, payload = original_command(command, **kwargs)
        mission = payload.get("mission")
        if mission:
            rejected_rows.append({"action": kwargs.get("action", "start"), "missionId": mission["mission_id"],
                                  "status": mission["state"]["status"], "replanTrigger": mission["state"]["last_replan_trigger"],
                                  "approvalHistory": mission["state"]["approval_history"],
                                  "missionSha256": hashlib.sha256(json.dumps(mission, sort_keys=True).encode()).hexdigest(),
                                  "autoRepair": payload.get("autoRepair")})
        return code, payload
    case._run_json_command = capture_rejection
    with mock.patch.object(cli, "_launch_async_mission_resume", side_effect=AssertionError("Rejected approval cannot launch a repair")) as rejected_launch:
        case.test_cli_acceptance_records_replan_after_rejected_delegated_approval()
        assert rejected_launch.call_count == 0
    assert len({row["missionId"] for row in rejected_rows}) == 1
    assert rejected_rows[-1]["replanTrigger"] == "approval_rejected" and rejected_rows[-1]["autoRepair"] is None
    capability = load(REPO / "tests/test_capability_evolution.py")
    negative_root = run_root / "lease-negative"
    negative_root.mkdir()
    capability.test_proof_lease_detects_drift_and_renews_only_from_fresh_receipt(negative_root)
    return {"trustDispatch": trust_rows, "setupHttpCycles": measurements, "fullReceiptRetrieval": detail_proof,
            "ordinaryVerificationRecovery": recovery, "rejectedApproval": {"repairDispatchCalls": 0, "launchedChildren": 0, "originalMissionRetained": True, "commandReceipts": rejected_rows},
            "negativeProofLease": {"expiredAdmissionRefused": True, "unavailableProviderHeld": True, "dependencyDriftRefused": True, "secretDependencyRefused": True},
            "boundary": "Actual HTTP backend dispatch into production CLI in the same process; provider/setup installation protocols are isolated fixtures. Trust and recovery call production adapter/CLI with execution stopped or audited. No actual signed-in provider, install or model task claimed.",
            "ownedServiceClosed": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"])
    parser.add_argument("--id")
    parser.add_argument("--journeys", action="store_true")
    args = parser.parse_args()
    isolate()
    assert args.phase or args.journeys
    result = journeys() if args.journeys else replay(args.id)
    previous = json.loads(RECEIPT.read_text(encoding="utf-8")) if RECEIPT.exists() else {"schema": "neyvia.FOLLOW.approval.v1"}
    if args.id and args.phase in previous:
        updated = {row["id"] for row in result["cases"]}
        result["cases"] = [row for row in previous[args.phase]["cases"] if row["id"] not in updated] + result["cases"]
        result["passed"] = all(row["passed"] for row in result["cases"])
        result["sourceHashes"] = {**previous[args.phase]["sourceHashes"], **result["sourceHashes"]}
    previous["journeys" if args.journeys else args.phase] = result
    previous["boundary"] = "Exact original scoped approval/recovery/capability assertions; controlled protocol fixtures, no actual providers, public runtimes, protected credentials or NAS. All network denied outside loopback ports48441-48449; proof service48444 only."
    RECEIPT.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
