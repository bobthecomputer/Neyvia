"""Classify historical failure evidence and record bounded repair receipts.

The historical XML is read-only. Diagnostic text is summarized rather than
copied, so neither source dumps nor credential material enters the receipt.
"""
from __future__ import annotations

import argparse
import ast
import collections
from contextlib import contextmanager
import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
RAW = Path(r"C:\Users\user\Projects\nx-final\.agent_control\final-split\evidence")
OUTPUT = REPO / "scripts/evidence/FOLLOW-failures.json"
SCRATCH = REPO / ".agent_control/follow-failures"

GROUPS = {
    "device-sqlite-fixture-lifecycle": ("fixture repair", "Close each fixture's direct SQLite transaction after commit/rollback; retain every security assertion.", "tests/test_native_device_*.py; src/grant_agent/native_device_commands.py"),
    "web-auth-sqlite-lifecycle": ("product repair", "Close session database connections after every success, early return and exception while preserving transactions.", "src/grant_agent/web_auth_sessions.py"),
    "continuity-failed-status": ("product repair", "Persist truthful failed continuity status; inspect any underlying scheduler failure separately, never turn failure into success.", "src/grant_agent/continuity_policy.py; src/grant_agent/mission_acceptance_harness.py"),
    "publisher-ownership-admission": ("fixture/admission review", "Supply a correctly owned module identifier and publisher fixture; preserve publisher-ownership and provenance guards.", "tests/test_marketplace_oci.py; src/grant_agent/module_marketplace.py"),
    "cargo-license-evidence": ("fixture/evidence review", "Rebuild correctly scoped evidence from the exact Cargo lock identity; preserve freshness and license admission.", "tests/test_dependency_inventory.py; src/grant_agent/dependency_inventory.py; config"),
    "secret-broker-device-session-admission": ("fixture repair", "Create real device/session admissions for the same asserted destination-bound invariants; preserve all guards.", "tests/test_secret_broker.py; src/grant_agent/secret_broker.py"),
    "source-contract-ownership-or-ui-frontier": ("source contract review", "Follow current responsibility owners and maintained paths without duplicating dead text. UI behavior changes outside the explicitly authorized surfaces remain an explicit gate.", "tests/source_contract_families.json; tests/frontend source contracts"),
    "removed-fixture-artifact-path": ("fixture path review", "Locate the maintained artifact or executable seam and preserve its invariant; do not restore obsolete product wrappers merely to satisfy a path assertion.", "tests/frontend and release fixtures"),
    "runtime-host-or-seam-drift": ("fixture/runtime review", "Isolate host discovery and patch the current resolver seam; preserve runtime, timeout, provider-profile and write-authority behavior.", "src/grant_agent/runtimes.py; src/grant_agent/web_backend_chat.py; tests"),
    "expanded-public-contract": ("contract review", "Compare the actual current API/catalog against the intended public contract; update valid fixtures only after semantic review.", "src/grant_agent/neyvia_mcp.py; native tools/catalogs; tests"),
    "syncthing-error-contract": ("product/contract review", "Preserve fail-closed health and honest unavailable/error state; inspect error projection and scoped request fixtures on assigned ports.", "src/grant_agent/folder_sync.py; tests/test_folder_sync.py"),
    "approval-recovery-or-replay": ("behavior review", "Reproduce the scoped recovery/replay invariant through production calls; preserve idempotency and approval admission.", "continuity, connected sessions and release acceptance owners"),
    "capability-proof-admission": ("fixture/behavior review", "Bind fresh proof receipts and current policy before evolution; preserve provenance, expiry and inactive promotion rules.", "src/grant_agent/capability_evolution.py; tests/test_capability_evolution.py"),
    "local-browser-authority": ("fixture/authority review", "Use an approved local origin and granted state while preserving navigation, resident-page and take-over guards.", "src/grant_agent/neyvia_extension_worker.py; ui_graph owners; tests"),
    "verified-provider-or-package-readiness": ("environment/admission review", "Inspect the current verified provider/tool/package seam; do not substitute missing models or relax trust/readiness.", "MCP broker, capability service, package exports and cache owners"),
    "remaining-behavior-review": ("behavior review", "Inspect the recorded failing call and maintained owner before a bounded fixture or product repair.", "exact case/source locations below"),
}

# These are documentary review boundaries, never inferred passing results.
RUNTIME_FRONTIERS = {
    "test_agent_chat_runtime_timeout_expands_for_xhigh_without_becoming_unbounded": ("src/grant_agent/web_backend.py", "_agent_chat_runtime_timeout_seconds", "The current declared policy returns no default wall deadline and preserves an explicit positive caller budget; the old 600-second cap assertion describes another policy."),
    "test_agent_chat_command_uses_codex_cli_when_runtime_is_codex": ("src/grant_agent/web_backend.py", "_agent_chat_runtime_timeout_seconds", "The old fixture expects an automatic 180-second total deadline; the current declared chat policy is unlimited unless the caller supplies a positive wall budget."),
    "test_managed_cli_uses_explicit_clamped_runtime_timeout": ("src/grant_agent/web_backend.py", "_agent_chat_runtime_timeout_seconds", "The old fixture expects 9000 seconds clamped to 1800; current declared policy preserves an explicit positive caller budget. Changing that business assertion requires contract review."),
    "test_neyvia_agent_chat_resolves_cli_from_source_workspace": ("src/grant_agent/web_backend_chat.py", "_run_neyvia_chat", "Native uses the active backend interpreter and package for its launcher, with source workspace supplying control state and subprocess environment. The old PATH launcher lookup assertion is obsolete; its replacement contract is not replayed here."),
    "test_agent_exposes_progressive_gateways_and_real_specialists": ("src/grant_agent/neyvia_agent.py", "build_neyvia_agent", "The declared current tool setup has manual-first active gateways and deferred specialist/tool schemas. The old exact active-tool list is not the present public contract; deferred reachability still needs its own direct journey."),
    "test_openai_codex_route_continues_through_codex_when_delegated_runtime_fails": ("src/grant_agent/web_backend_chat.py", "_run_agent_chat", "Current read-only routing may execute through the Codex app-server before the old mocked Hermes/fallback branch. This fixture requires reviewed permission and transport isolation; no live model call is authorized by the old fixture."),
    "test_hermes_auth_store_does_not_own_codex_oauth": ("src/grant_agent/web_backend.py", "_codex_cli_login_status", "The fixture mocks every subprocess login probe with generic logged-in text, including the current independent Codex login probe. HOME-only isolation is insufficient for current resolver inputs; the consumer ownership invariant needs a correctly isolated resolver fixture."),
    "test_conversation_bootstrap_is_index_first_and_session_detail_is_lazy": ("src/grant_agent/web_backend.py", "_conversation_state_bootstrap", "The legacy NAS-labeled fixture has not been replayed under the no-NAS boundary. Current bootstrap/detail and merge contracts must be assessed with a local-only fixture, preserving index counts, selected tail and merge assertions."),
}


def case_id(case):
    parts = case.get("classname", "").split(".")
    path = "tests/" + parts[1] + ".py" if len(parts) > 1 else case.get("file", "unknown")
    return path + "::" + "::".join(parts[2:] + [case.get("name", "unknown")])


def category(identifier, trace):
    file = identifier.split("::")[0]
    if "WinError 32" in trace and "devices.sqlite3" in trace:
        return "device-sqlite-fixture-lifecycle"
    if "WinError 32" in trace and "web-auth-sessions.sqlite3" in trace:
        return "web-auth-sqlite-lifecycle"
    if "Unsupported mission continuity status: failed" in trace:
        return "continuity-failed-status"
    if "module identifier must be owned by publisher.id" in trace:
        return "publisher-ownership-admission"
    if "Cargo license evidence is stale, duplicated, or mis-scoped" in trace:
        return "cargo-license-evidence"
    if file == "tests/test_secret_broker.py" and "plan_use() missing" in trace:
        return "secret-broker-device-session-admission"
    if "FileNotFoundError" in trace and any(value in trace for value in ("desktop-ui", "BuilderProgressSurface", "stage_production_candidate")):
        return "removed-fixture-artifact-path"
    if file == "tests/test_folder_sync.py":
        return "syncthing-error-contract"
    if file == "tests/test_capability_evolution.py":
        return "capability-proof-admission"
    if file in {"tests/test_neyvia_extensions.py", "tests/test_ui_graph.py"}:
        return "local-browser-authority"
    if file in {"tests/test_runtimes.py", "tests/test_web_backend.py", "tests/test_neyvia_agent.py", "tests/test_neyvia_harnesses.py"}:
        return "runtime-host-or-seam-drift"
    if file in {"tests/test_neyvia_mcp.py", "tests/test_product_catalog.py", "tests/test_capability_os.py", "tests/test_harness_registry.py", "tests/test_connected_sessions_api.py", "tests/test_connected_plan.py", "tests/test_claude_code_mods.py"}:
        return "expanded-public-contract"
    if file in {"tests/test_connected_sessions_broker.py", "tests/test_efficient_workflow.py", "tests/test_release_acceptance.py", "tests/test_connected_sessions_claude_terminal.py"}:
        return "approval-recovery-or-replay"
    if file in {"tests/test_model_tool_intelligence.py", "tests/test_p2p_cache.py", "tests/test_package_init.py", "tests/test_git_reference_adapter.py", "tests/test_agent_vision.py"}:
        return "verified-provider-or-package-readiness"
    if any(value in file for value in ("desktop_ui_contract", "image_playground_frontend", "live_review_panel_frontend", "neyvia_navigation_contract", "neyvia_production_ui_gate", "neyvia_ui_polish_contract", "neyvia_conversation_finish", "preview_research_tools", "unified_agent_preview_contract", "workspace_selection_behavior", "neyvia_integration")):
        return "source-contract-ownership-or-ui-frontier"
    return "remaining-behavior-review"


def classify():
    rows = []
    sources = {}
    for path in sorted(RAW.glob("pytest-after-*.xml")):
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for case in ET.parse(path).iter("testcase"):
            failure = case.find("failure")
            failure = failure if failure is not None else case.find("error")
            if failure is None:
                continue
            trace = failure.text or ""
            identifier = case_id(case)
            kind = category(identifier, trace)
            exceptions = re.findall(r"(?:^|\n)(?:E\s+)?(?:[\w.]+\.)?([A-Za-z_]\w*(?:Error|Exception)):\s*", trace)
            exception = exceptions[-1] if exceptions else "AssertionError"
            locations = re.findall(r"(?m)^((?:src|tests)[\\/][^:\n]+\.py):(\d+):", trace)
            rows.append({"id": identifier, "historicalOutcome": "failed" if failure.tag == "failure" else "error",
                         "exceptionType": exception, "rootCauseGroup": kind,
                         "sourceLocations": [{"path": name.replace("\\", "/"), "line": int(line)} for name, line in dict.fromkeys(locations)],
                         "diagnosis": GROUPS[kind][1], "currentOutcome": "not replayed",
                         "rawSource": path.name})
    assert len(rows) == 134, f"Expected all 134 historical failures/errors, saw {len(rows)}"
    assert len({row["id"] for row in rows}) == len(rows)
    groups = []
    counts = collections.Counter(row["rootCauseGroup"] for row in rows)
    for name, count in counts.most_common():
        nature, action, owners = GROUPS[name]
        groups.append({"id": name, "count": count, "classification": nature, "action": action, "owners": owners})
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    old_cases = {row["id"]: row for row in previous.get("cases", [])}
    for row in rows:
        old = old_cases.get(row["id"], {})
        for key in ("currentOutcome", "repairCommit", "currentProof", "currentDiagnosis", "policyEvidence"):
            if key in old:
                row[key] = old[key]
        name = row["id"].rsplit("::", 1)[1]
        if row["rootCauseGroup"] == "runtime-host-or-seam-drift" and name in RUNTIME_FRONTIERS and row["currentOutcome"] != "original case passed":
            relative, symbol, diagnosis = RUNTIME_FRONTIERS[name]
            tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
            node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == symbol)
            row["currentOutcome"] = "not replayed; documentary contract or fixture frontier"
            row["currentDiagnosis"] = diagnosis
            row["policyEvidence"] = {"path": relative, "symbol": symbol, "line": node.lineno,
                                     "sourceSha256": hashlib.sha256((REPO / relative).read_bytes()).hexdigest()}
    return {"schema": "neyvia.FOLLOW.failures.v1", "rawEvidence": sources,
            "historicalFailed": sum(row["historicalOutcome"] == "failed" for row in rows),
            "historicalErrors": sum(row["historicalOutcome"] == "error" for row in rows),
            "classificationBoundary": "complete recorded failure inventory and root-cause grouping; current outcomes require bounded replay, not inference",
            "releaseGate": "in progress; no whole-suite green claim", "groups": groups, "cases": rows,
            "repairs": previous.get("repairs", {})}


def isolate():
    import verify_follow_depth as depth
    depth.SCRATCH = SCRATCH
    depth.STATE = SCRATCH / "runtime"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    depth.install_isolation()
    os.environ.update({"NEYVIA_TOOL_AUTO_UPDATE": "0", "NEYVIA_COORDINATOR_AUTOSTART": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
                       "FLUXIO_DISABLE_WSL_AUTH_DISCOVERY": "1", "FLUXIO_RUNTIME_HOME": str(SCRATCH / "home"),
                       "FLUXIO_NAS_VOLUME_ROOT": str(SCRATCH / "unavailable-volume"), "FLUXIO_CONTROL_PROJECT_ROOT": str(depth.STATE),
                       "FLUXIO_WORKSPACE_ROOT": str(depth.STATE), "FLUXIO_WEB_BACKEND_PYTHON": str(depth.PYTHON)})
    (SCRATCH / "temporary").mkdir(exist_ok=True)
    tempfile.tempdir = str(SCRATCH / "temporary")
    sys.path.insert(0, str(REPO / "src"))


@contextmanager
def real_http():
    from grant_agent import web_backend
    root = SCRATCH / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    backend = web_backend.FluxioWebBackend(root, root / "static")
    server = web_backend._HandshakeSafeThreadingHTTPServer(("127.0.0.1", 48449), web_backend.make_handler(backend))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request("http://127.0.0.1:48449" + path, data=data, headers={"Content-Type": "application/json"})
        try:
            response = opener.open(req, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return {"http": response.status, "body": json.load(response)}

    thread.start()
    try:
        yield backend, request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "Owned HTTP server did not stop"


def session_lifecycle():
    from grant_agent.web_auth_sessions import WebAuthSessions
    root = SCRATCH / "session-lifecycle"
    sessions = WebAuthSessions(root, auth_identity="FOLLOW disposable account fingerprint")
    token = sessions.issue({"username": "fixture-owner", "role": "admin"})
    assert sessions.lookup(token)["username"] == "fixture-owner"
    assert len(sessions.sessions("fixture-owner")) == 1
    # Keep the store and connection references alive: no garbage collection can
    # disguise whether the production context closed on success or rollback.
    with sessions._connection() as committed:
        committed.execute("BEGIN IMMEDIATE")
        committed.execute("UPDATE web_auth_sessions SET display_name = ?", ("committed name",))
    assert sessions.lookup(token)["displayName"] == "committed name"
    try:
        with sessions._connection() as rolled_back:
            rolled_back.execute("BEGIN IMMEDIATE")
            rolled_back.execute("UPDATE web_auth_sessions SET display_name = ?", ("must roll back",))
            raise RuntimeError("controlled transaction failure")
    except RuntimeError:
        pass
    assert sessions.lookup(token)["displayName"] == "committed name"
    for connection in (committed, rolled_back):
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("Session transaction kept its SQLite handle open")
    destination = sessions.path.with_suffix(".move-proof")
    sessions.path.rename(destination)
    destination.rename(sessions.path)
    assert sessions.lookup(token)["username"] == "fixture-owner"
    assert sessions.revoke_where(username="fixture-owner") == 1
    assert sessions.lookup(token) is None
    with real_http() as (backend, request):
        login = request("/api/auth/local-session", {})
        assert login["http"] == 200
        observations = [request("/api/auth/status") for _ in range(4)]
        assert all(row["http"] == 200 and row["body"]["data"]["authenticated"] for row in observations)
        path = backend.web_auth_sessions.path
        moved = path.with_suffix(".move-proof")
        path.rename(moved)
        moved.rename(path)
        after_move = request("/api/auth/status")
        assert after_move["http"] == 200 and after_move["body"]["data"]["authenticated"]
    return {"passed": True, "actualHttpPort": 48449, "productionIssueLookupListRevoke": True,
            "commitPreserved": True, "rollbackPreserved": True, "bothTransactionHandlesClosed": True,
            "windowsRenameWithStoreAndConnectionReferencesAlive": True,
            "http": {"ownerLogin": login, "sessionPolls": observations, "authenticatedAfterDatabaseMove": after_move},
            "ownedServerStopped": True, "sourceSha256": hashlib.sha256((REPO / "src/grant_agent/web_auth_sessions.py").read_bytes()).hexdigest()}


class OriginalTransaction(ast.NodeTransformer):
    def visit_With(self, node):
        if len(node.items) == 2:
            call = node.items[0].context_expr
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "closing":
                node.items = [ast.withitem(context_expr=call.args[0], optional_vars=node.items[0].optional_vars)]
        return self.generic_visit(node)


def device_fixtures(rows):
    selected = [row for row in rows if row["rootCauseGroup"] == "device-sqlite-fixture-lifecycle"]
    paths = sorted({row["id"].split("::")[0] for row in selected})
    modules = {}
    preserved = 0
    for relative in paths:
        path = REPO / relative
        original = subprocess.check_output(["git", "show", "f83d003d:" + relative], cwd=REPO, text=True, encoding="utf-8")
        before = {node.name: node for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)}
        after = {node.name: node for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)}
        for name, function in before.items():
            restored = OriginalTransaction().visit(after[name])
            assert ast.dump(function, include_attributes=False) == ast.dump(restored, include_attributes=False), "Changed fixture business/assertion code: " + relative + "::" + name
            preserved += 1
        spec = importlib.util.spec_from_file_location("follow_device_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        modules[relative] = module
    results = []
    for row in selected:
        path, name = row["id"].rsplit("::", 1)
        try:
            getattr(modules[path], name)()
        except Exception as exc:
            # A failure remains a failure. Never emit device secrets or signed
            # fixture payloads from exception representations.
            results.append({"id": row["id"], "passed": False, "exceptionType": type(exc).__name__})
        else:
            results.append({"id": row["id"], "passed": True})
    return {"passed": all(row["passed"] for row in results), "originalCasesReplayed": len(results),
            "unchangedOriginalFunctionASTs": preserved, "cases": results,
            "boundary": "only the 13 reviewed local SQLite/device authority cases, actual production stores and exact assertions; no pytest runner/network/provider actions"}


def web_auth_cases(rows):
    selected = [row for row in rows if row["rootCauseGroup"] == "web-auth-sqlite-lifecycle"]
    path = REPO / "tests/test_web_backend.py"
    spec = importlib.util.spec_from_file_location("follow_auth_original", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    results = []
    for row in selected:
        name = row["id"].rsplit("::", 1)[1]
        case = module.FluxioWebBackendTests(name)
        try:
            getattr(case, name)()
        except Exception as exc:
            results.append({"id": row["id"], "passed": False, "exceptionType": type(exc).__name__})
        else:
            results.append({"id": row["id"], "passed": True})
    return {"passed": all(row["passed"] for row in results), "originalCasesReplayed": len(results), "cases": results,
            "boundary": "six inspected original local-auth and FakeHandler cases; durable-session assertion seam and declared 8-256 password fixture updated; all authority/identity/order/refusal invariants retained; no pytest runner"}


def continuity_failure():
    from grant_agent.continuity_policy import MissionContinuityStore
    root = SCRATCH / "continuity-failure"
    store = MissionContinuityStore(root)
    mission_id = "follow-truthful-failure"
    patch = {"status": "failed", "knownFailure": "FOLLOW deliberate verification refusal", "currentStep": "verification refused", "nextAction": "Inspect the refusal before retrying."}
    saved = store.create_or_update(mission_id, patch=patch)
    assert saved["status"] == "failed"
    assert MissionContinuityStore(root).load(mission_id)["knownFailure"] == patch["knownFailure"]
    assert store.operator_update(mission_id)["status"] == "failed"
    assert store.recover(mission_id)["knownFailure"] == patch["knownFailure"]
    with real_http() as (_, request):
        assert request("/api/auth/local-session", {})["http"] == 200
        def command(name, **payload):
            result = request("/api/backend", {"command": name, "payload": {"missionId": mission_id, **payload}})
            assert result["http"] == 200, name
            return result
        checkpoint = command("checkpoint_mission_continuity_command", patch=patch)
        loaded = command("get_mission_continuity_command")
        operator = command("get_mission_operator_update_command")
        recovery = command("recover_mission_continuity_command")
        for result in (checkpoint, loaded, operator):
            assert result["body"]["data"]["status"] == "failed"
        assert recovery["body"]["data"]["knownFailure"] == patch["knownFailure"]
    return {"passed": True, "actualHttpPort": 48449, "failedStatusDurable": True, "operatorRetainsFailure": True,
            "recoveryRetainsKnownFailure": True, "http": [checkpoint, loaded, operator, recovery], "ownedServerStopped": True}


def continuity_cases(rows):
    selected = [row for row in rows if row["rootCauseGroup"] == "continuity-failed-status"]
    path = REPO / "tests/test_mission_acceptance_harness.py"
    spec = importlib.util.spec_from_file_location("follow_continuity_original", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    results = []
    for row in selected:
        name = row["id"].rsplit("::", 1)[1]
        with tempfile.TemporaryDirectory() as fixture:
            try:
                getattr(module, name)(Path(fixture))
            except Exception as exc:
                results.append({"id": row["id"], "passed": False, "exceptionType": type(exc).__name__})
            else:
                results.append({"id": row["id"], "passed": True})
    return {"passed": all(row["passed"] for row in results), "originalCasesReplayed": len(results), "cases": results,
            "boundary": "two inspected original local acceptance cases; unchanged assertions; harness explicitly simulated with no network, external accounts or paid compute"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-lifecycle", action="store_true")
    parser.add_argument("--device-fixtures", action="store_true")
    parser.add_argument("--web-auth-cases", action="store_true")
    parser.add_argument("--continuity-failure", action="store_true")
    parser.add_argument("--continuity-cases", action="store_true")
    args = parser.parse_args()
    result = classify()
    if args.session_lifecycle or args.device_fixtures or args.web_auth_cases or args.continuity_failure or args.continuity_cases:
        isolate()
    if args.session_lifecycle:
        result["repairs"]["web-auth-sqlite-lifecycle"] = session_lifecycle()
        for row in result["cases"]:
            if row["rootCauseGroup"] == "web-auth-sqlite-lifecycle":
                row["currentOutcome"] = "underlying product lifecycle verified with real HTTP; original case not run"
                row["currentProof"] = "repairs.web-auth-sqlite-lifecycle"
    if args.device_fixtures:
        proof = result["repairs"]["device-sqlite-fixture-lifecycle"] = device_fixtures(result["cases"])
        outcomes = {row["id"]: row["passed"] for row in proof["cases"]}
        for row in result["cases"]:
            if row["id"] in outcomes:
                row["currentOutcome"] = "original case passed" if outcomes[row["id"]] else "original case failed"
                row["currentProof"] = "repairs.device-sqlite-fixture-lifecycle"
    if args.web_auth_cases:
        proof = result["repairs"]["web-auth-original-cases"] = web_auth_cases(result["cases"])
        outcomes = {row["id"]: row["passed"] for row in proof["cases"]}
        for row in result["cases"]:
            if row["id"] in outcomes:
                row["currentOutcome"] = "original case passed" if outcomes[row["id"]] else "original case failed"
                row["currentProof"] = "repairs.web-auth-original-cases"
                row["repairCommit"] = "4e47a00b"
    if args.continuity_failure:
        result["repairs"]["continuity-failed-status"] = continuity_failure()
    if args.continuity_cases:
        proof = result["repairs"]["continuity-original-cases"] = continuity_cases(result["cases"])
        outcomes = {row["id"]: row["passed"] for row in proof["cases"]}
        for row in result["cases"]:
            if row["id"] in outcomes:
                row["currentOutcome"] = "original case passed" if outcomes[row["id"]] else "original case failed"
                row["currentProof"] = "repairs.continuity-original-cases"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"historicalFailed": result["historicalFailed"], "historicalErrors": result["historicalErrors"],
                      "groups": {row["id"]: row["count"] for row in result["groups"]}, "receipt": str(OUTPUT.relative_to(REPO))}))
    selected = [(args.session_lifecycle, "web-auth-sqlite-lifecycle"), (args.device_fixtures, "device-sqlite-fixture-lifecycle"),
                (args.web_auth_cases, "web-auth-original-cases"), (args.continuity_failure, "continuity-failed-status"),
                (args.continuity_cases, "continuity-original-cases")]
    if any(enabled and result["repairs"][key].get("passed") is False for enabled, key in selected):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
