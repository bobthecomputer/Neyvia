"""Generated local planning, compiler and durable view fixtures.

Each case invokes its exact production owner. Compiler/policy projections prove
their supplied-input contract; durable cases independently reopen bytes or SQL.
No existing aggregate self-check, browser, provider or device is invoked.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = {"empty": "", "huge": "large local evidence " * 1024,
        "unicode": "雪🙂 café e\u0301 שלום العربية"}
CATEGORIES = ("empty", "huge", "unicode", "concurrency", "interrupted", "permissions", "offline", "stale")
IDS = {"d-ui." + name for name in (
    "plan-order", "plan-compact", "plan-skills", "compiler-dag", "compiler-authority", "compiler-hash",
    "night-policy", "night-notification", "night-digest", "usage-truth", "view-arrange", "view-schemas",
    "view-controls", "search-bounds", "product-boundary", "ocr-candidates", "design-capsules",
    "night-readiness", "workspace-integrity", "workspace-snapshots", "dependency-context", "route-context", "selected-profile",
    "mesh-receipt", "office-boundary")}
EXTRA = {
    "d-ui.compiler-authority": {"permissions"},
    "d-ui.night-policy": {"permissions"},
    "d-ui.night-digest": {"permissions", "stale", "interrupted", "concurrency"},
    "d-ui.usage-truth": {"stale", "permissions", "interrupted", "concurrency"},
    "d-ui.view-arrange": {"concurrency", "stale", "permissions", "interrupted"},
    "d-ui.view-controls": {"stale", "permissions", "interrupted", "concurrency"},
    "d-ui.view-schemas": {"stale", "permissions", "interrupted", "concurrency"},
    "d-ui.search-bounds": {"permissions", "stale", "concurrency"},
    "d-ui.ocr-candidates": {"permissions", "stale", "concurrency"},
    "d-ui.design-capsules": {"permissions", "stale", "concurrency"},
    "d-ui.workspace-snapshots": {"permissions", "stale", "concurrency"},
    "d-ui.route-context": {"stale", "concurrency", "permissions"},
    "d-ui.night-readiness": {"permissions", "stale", "concurrency"},
    "d-ui.mesh-receipt": {"permissions", "stale", "concurrency"},
    "d-ui.selected-profile": {"permissions"},
}
SOURCES = ["src/grant_agent/" + name for name in (
    "edge_fixture_ui_planning_local.py", "planner.py", "models.py", "orchestration_language.py",
    "night_mode.py", "neyvia_view_tools.py", "neyvia_workspace_tools.py", "ui_command_bus.py",
    "neyvia_settings.py", "proofs_settings.py", "neyvia_analytics.py", "model_usage.py", "research.py",
    "local_network_policy.py", "product_catalog.py", "ocr_benchmark.py", "skill_capsules.py",
    "proofs_d_ui_planning.py", "proofs_e_sv.py", "proof_contracts.py", "neyvia_manuals.py",
            "proof_credential_guard.py", "edge_fixture_models.py")]
SOURCES += ["src/grant_agent/web_backend.py", "src/grant_agent/neyvia_conversations.py"]
SOURCES += ["config/proofs/d-ui-planning.json", "manuals/ui-planning.manual.json",
            "manuals/cl/ui-planning.cl", "config/proofs/settings.json", "manuals/settings.manual.json"]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def reject(action, classes=(ValueError, RuntimeError, OSError)):
    try:
        action()
    except classes as error:
        return {"type": type(error).__name__, "error": str(error)[:300]}
    raise AssertionError("Adverse input was admitted")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sql_snapshot(bus):
    db = sqlite3.connect(bus.path)
    try:
        state = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM state")}
        events = [(identity, action, json.loads(payload)) for identity, action, payload in
                  db.execute("SELECT id,action,payload FROM events ORDER BY id")]
    finally:
        db.close()
    return state, events


@contextmanager
def workspace(root):
    from .proof_credential_guard import prepare_broker_fixture
    from .neyvia_workspace_tools import WorkspaceTools
    prepare_broker_fixture(root)
    service = WorkspaceTools(root)
    service.bus.put("settings", {"localOnly": True})
    try:
        yield service
    finally:
        service.close()
        require(service.closed.is_set() and service._timer is None, "Owned view service did not close")


def _plan(root, category, identity):
    from .planner import build_docs_first_plan, build_docs_first_plan_receipt
    text = TEXT[category]
    count = 128 if category == "huge" else 0 if category == "empty" else 3
    docs = [f"document-{i} " + text for i in range(count)]
    if identity == "d-ui.plan-order":
        baseline = build_docs_first_plan(text, docs)
        expected = "Review referenced docs and extract constraints" if docs else "Collect missing docs/spec links before implementation"
        require(baseline.plan_steps[0] == expected, "Default first task ignores actual document collection")
        execute = build_docs_first_plan("Execute first, repair preview UI " + text, docs)
        require(execute.plan_steps[0] == "Implement smallest vertical slice in product files" and
                "Preview reflects expected UI behavior on desktop and mobile" in execute.acceptance_checks,
                "Execute-first/UI request lost required task or proof gate")
        require(docs == [f"document-{i} " + text for i in range(count)], "Planner modified caller documents")
        return {"docs": count, "firstTasks": [baseline.plan_steps[0], execute.plan_steps[0]]}
    brief = {"brief_id": "brief-" + text[:20], "schema": "fixture.skill-brief.v1",
             "selected_skills": [{"skillId": f"skill-{i}", "description": text} for i in range(count)]}
    common = {"objective": text, "docs": docs, "mission_id": "owned", "host": "local",
              "runtime": "none", "workspace": str(root), "skill_brief": brief}
    if identity == "d-ui.plan-compact":
        lists = [f"path-{i}/" + text for i in range(count)]
        before = copy.deepcopy((docs, lists, brief))
        result = build_docs_first_plan_receipt(**common, file_scope=lists, forbidden_paths=lists,
                                               expected_changed_files=lists, expected_artifacts=lists)
        require((docs, lists, brief) == before, "Receipt compiler modified caller input")
        value = asdict(result)
        for key, maximum, size in (("file_scope", 80, 240), ("forbidden_paths", 40, 240),
                                   ("expected_changed_files", 80, 240), ("expected_artifacts", 40, 240)):
            require(len(value[key]) == min(count, maximum) and all(len(item) <= size for item in value[key]),
                    "Receipt loses list order/count or exceeds compact budget: " + key)
        expected_goal = " ".join(text.split())
        expected_goal = expected_goal if len(expected_goal) <= 500 else expected_goal[:497] + "..."
        require(result.goal_restatement == expected_goal and result.inputs["docCount"] == count and
                result.inputs["docsTruncated"] == any(len(row) > 500 for row in docs) and
                not set(result.inputs) & {"docs", "documents"}, "Compact receipt differs from actual document/goal inputs")
        require(result.tasks and all(set(row) == {"id", "title", "status"} and row["status"] == "pending"
                                    and len(row["title"]) <= 160 for row in result.tasks), "Task schema/size differs")
        return {"docCount": count, "fileScopeCount": len(result.file_scope), "receiptCharacters": len(canonical(value))}
    default = build_docs_first_plan_receipt(**common)
    require(default.selected_skills == [f"skill-{i}" for i in range(min(count, 24))], "Brief skill selection order/count differs")
    explicit = [] if category == "empty" else [f"explicit-{i}-" + text for i in range(count)]
    overridden = build_docs_first_plan_receipt(**common, selected_skills=explicit)
    expected = [" ".join(row.split()) for row in explicit][:24]
    expected = [row if len(row) <= 120 else row[:117].rstrip() + "..." for row in expected]
    require(overridden.selected_skills == expected and overridden.inputs["skillBriefId"] == brief["brief_id"]
            and overridden.inputs["skillBriefSchema"] == brief["schema"], "Explicit selection erased retained brief provenance")
    empty_override = build_docs_first_plan_receipt(**common, selected_skills=[])
    require(empty_override.selected_skills == [], "Explicit empty override silently reused brief skills")
    return {"briefSkills": len(default.selected_skills), "explicitSkills": len(overridden.selected_skills), "emptyOverride": True}


def _compiler(root, category, identity):
    from .orchestration_language import NeyviaProgram, OrchestrationLane, OrchestrationStep, NeyviaLanguageError, compile_neyvia_program
    text = TEXT.get(category, "permission envelope")
    if category == "empty":
        reject(lambda: compile_neyvia_program(""), (NeyviaLanguageError,))
    count = 256 if category == "huge" else 4
    lane = OrchestrationLane("worker", "none", "none", "none", ["read", "workspace.write"])
    steps = [OrchestrationStep(f"s{i:04d}", "worker", "verify" if i % 2 else "checkpoint",
                              after=[f"s{i-1:04d}"] if i else [], arguments={"message": text},
                              risk=("read", "workspace_write", "external_write", "destructive")[i % 4],
                              acceptance=text if i % 2 else "") for i in range(count)]
    program = NeyviaProgram(objective=text or "Owned empty metadata", lanes=[lane], steps=steps, metadata={"note": text})
    before = asdict(program)
    value = program.compile()
    require(asdict(program) == before, "Compiler changed caller typed plan")
    if identity == "d-ui.compiler-dag":
        completed = set()
        by_id = {row["step_id"]: row for row in value["steps"]}
        for stage in value["executionStages"]:
            require(all(set(by_id[name]["after"]) <= completed for name in stage["stepIds"]), "A prerequisite ran after its dependent")
            require(not completed.intersection(stage["stepIds"]), "Stage repeated a step")
            completed.update(stage["stepIds"])
        require(completed == set(by_id) and len(completed) == count, "Compiled DAG lost steps")
        cycle = copy.deepcopy(program)
        cycle.steps[0] = OrchestrationStep("s0000", "worker", "checkpoint", after=[steps[-1].step_id])
        reject(cycle.compile, (NeyviaLanguageError,))
        duplicate = copy.deepcopy(program); duplicate.steps.append(steps[0])
        reject(duplicate.compile, (NeyviaLanguageError,))
        return {"steps": count, "stages": len(value["executionStages"]), "cyclesAndDuplicateIdsRefused": True}
    if identity == "d-ui.compiler-authority":
        for declared, row in zip(steps, value["steps"], strict=True):
            require(row["permissionEnvelope"] == {"allowed": lane.permissions, "mutability": declared.risk,
                    "approvalRequired": declared.risk in {"external_write", "destructive"}} and
                    row["proofRequired"] == bool(declared.output or declared.acceptance or declared.action == "verify"),
                    "Compiled scope/risk/proof requirement widened declared authority")
        # The exact authority contract consumes scopes and risk, so it has a
        # real permissions input mutation even though it launches no action.
        if category == "permissions":
            narrowed = copy.deepcopy(program); narrowed.lanes[0].permissions.clear()
            rows = narrowed.compile()["steps"]
            require(all(not row["permissionEnvelope"]["allowed"] for row in rows) and
                    all(row["permissionEnvelope"]["approvalRequired"] for row in rows if row["risk"] in {"external_write", "destructive"}),
                    "Empty scope conferred external/destructive authority")
        return {"steps": count, "scopes": lane.permissions, "permissionDecisionInputMutated": category == "permissions", "executedActions": 0}
    unsigned = {key: item for key, item in value.items() if key not in {"planHash", "estimatedPlanTokens"}}
    encoded = canonical(unsigned)
    require(value["planHash"] == hashlib.sha256(encoded.encode()).hexdigest() and
            value["estimatedPlanTokens"] == max(1, (len(encoded) + 3) // 4), "Compiled canonical hash/size differs from independent encoding")
    newer = copy.deepcopy(program); newer.metadata["note"] = text + " changed"
    require(newer.compile()["planHash"] != value["planHash"], "Changed actual compiled metadata retained the old plan hash")
    return {"canonicalBytes": len(encoded.encode()), "hash": value["planHash"], "tokens": value["estimatedPlanTokens"]}


def _night(root, category, identity):
    from .night_mode import classify_night_work, rank_night_queue, production_night_profile_payload, build_readiness_failure_message, write_morning_digest
    text = TEXT.get(category, "owned changed observation")
    count = 128 if category == "huge" else 0 if category == "empty" else 3
    if identity == "d-ui.night-policy":
        kinds = ["headless_executor_work", "headless_verifier_work", "browser_verification", "full_frontend_build",
                 "package_upgrade", "destructive_git_action", "outside_leased_workspace", "unknown-" + text]
        for gateway, pressure in ((False, False), (True, False), (True, True)):
            rows = [{"id": f"item-{i:04d}-" + text[:20], "kind": kinds[i % len(kinds)], "note": text}
                    for i in range(count)]
            before = copy.deepcopy(rows)
            result = rank_night_queue(rows, pc_gateway_online=gateway, nas_pressure_high=pressure)
            combined = result["ranked"] + result["deferred"] + result["held"]
            require(rows == before and sorted(row["id"] for row in combined) == sorted(row["id"] for row in rows), "Night queue modified/lost an item")
            require(result["ranked"] == sorted(result["ranked"], key=lambda row: (row["priority"], row["id"])), "Night queue is not priority ordered")
            require(classify_night_work("browser_verification", pc_gateway_online=gateway)["decision"] == ("allow" if gateway else "defer"), "Recorded missing gateway was admitted")
            require(classify_night_work("full_frontend_build", nas_pressure_high=pressure)["decision"] == ("defer" if pressure else "allow"), "Recorded capacity pressure was admitted")
        for kind in ("package_upgrade", "destructive_git_action", "outside_leased_workspace"):
            require(classify_night_work(kind, pc_gateway_online=True)["decision"] == "defer", "Work needing separate authority was admitted")
        require(classify_night_work("unknown-" + text)["decision"] == "hold", "Unknown recorded work was admitted")
        profile = production_night_profile_payload()
        require(profile["autopilot"] and profile["mission_execution_allowed"] and
                {"readiness_receipt", "verification_receipt"} <= set(profile["proof_requirements"]), "Night profile dropped its receipt admission gates")
        return {"generatedRows": count, "observationGateCombinations": 3, "permissionsDeferred": 3, "actionsExecuted": 0}
    if identity == "d-ui.night-notification":
        failures = [f"check-{i}-" + text for i in range(count)]
        receipt = {"status": "blocked", "failures": failures, "mission_id": text}
        before = copy.deepcopy(receipt)
        path = str(root / "readiness.json")
        blocked = build_readiness_failure_message(receipt, receipt_path=path)
        require(receipt == before and blocked["status"] == "action" and blocked["failureCount"] == count and
                blocked["failures"] == failures and blocked["receiptPath"] == path and
                all(row in blocked["body"] for row in failures), "Notification lost exact failure/path linkage")
        passed = build_readiness_failure_message({"status": "passed", "failures": []}, receipt_path=path)
        require(passed["status"] == "skipped" and not list(root.iterdir()), "Passed notification created an effect or action")
        return {"failures": count, "blockedStatus": blocked["status"], "passedStatus": passed["status"], "notificationsSent": 0}
    values = [f"item-{i}-" + text[:512] for i in range(count)]
    def write(chosen):
        return write_morning_digest(root, completed_items=chosen, blocked_items=values, proof_commands=values,
                                    changed_files=values, nas_sync_status="not requested", first_unchecked_item=text,
                                    proof_gaps=values, risks=values)
    value = write(values)
    json_path, md_path = Path(value["jsonPath"]), Path(value["markdownPath"])
    require(json.loads(json_path.read_bytes()) == {key: row for key, row in value.items() if key not in {"jsonPath", "markdownPath"}},
            "Morning digest differs from reopened JSON bytes")
    markdown = md_path.read_text(encoding="utf-8")
    require(all(row in markdown for row in values) and "not requested" in markdown and
            all(value[name] == count for name in ("completedCount", "blockedCount", "proofGapCount")), "Markdown/counts lost durable digest items")
    if category == "stale":
        prior = json_path.read_bytes()
        updated = write(["fresh changed completion"])
        require(json_path.read_bytes() != prior and json.loads(json_path.read_bytes())["completedItems"] == ["fresh changed completion"]
                and updated["completedCount"] == 1 and value["completedItems"] == values, "Digest replacement reused stale JSON or mutated returned history")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = {path: path.read_bytes() for path in (json_path, md_path)}
        with _deny_read(json_path):
            denied = reject(lambda: write(["denied replacement"]), (OSError,))
        require(all(path.read_bytes() == raw for path, raw in before.items()), "Denied digest replacement changed keeper bytes")
        return {"jsonBytes": len(before[json_path]), "permissionRefusal": denied, "nasSyncPerformed": False}
    return {"jsonBytes": json_path.stat().st_size, "markdownBytes": md_path.stat().st_size, "jsonSha256": digest(json_path), "nasSyncPerformed": False}


def _usage(root, category, identity):
    from .neyvia_analytics import publish_indicator
    from .ui_command_bus import UICommandBus
    bus = UICommandBus(root)
    samples = ([{"totalTokens": None, "coverage": "partial"}] if category == "empty" else
               [{"totalTokens": 10**15, "cachedInputTokens": 10**15 - 12345}] if category == "huge" else
               [{"totalTokens": 100, "cachedInputTokens": 70, "coverage": "partial"}])
    if category == "stale":
        samples = [{"totalTokens": 1000, "cachedInputTokens": 900}, {"totalTokens": None, "coverage": "partial"}]
    for index, observed in enumerate(samples):
        event = {"type": "usage.updated", "runId": TEXT.get(category, "old") + str(index), "usage": observed}
        before = copy.deepcopy(event)
        publish_indicator(bus, event)
        state, events = sql_snapshot(bus)
        reading = state["indicators"]["usage"]
        require(event == before and events[-1][1:] == ("indicator.updated", reading), "Usage event differs from durable SQL or input was changed")
        total, cache = observed.get("totalTokens"), observed.get("cachedInputTokens")
        require(reading["total"] == total and reading["used"] == (total - cache if total is not None and cache is not None else total), "Cached tokens inflated new-token headline")
        if total is None:
            require(reading["used"] is None and "unknown" in reading["label"], "Unknown latest usage retained an old known total")
        if observed.get("coverage") == "partial":
            require(reading["label"].endswith("(partial)"), "Partial coverage label vanished")
    return {"samples": len(samples), "durableEvents": len(sql_snapshot(bus)[1]), "latest": reading}


def _views(root, category, identity):
    text = TEXT.get(category, "fresh observed layout")
    with workspace(root) as service:
        bus = service.bus
        if identity == "d-ui.view-arrange":
            first = {"order": ["main", "sidebar", "panel", "canopy"], "dock": "left", "sidebarHidden": True}
            service.call("view.arrange", first)
            before, event_before = sql_snapshot(bus)
            invalid = ([{}] if category == "empty" else [{"order": ["main"] * 1024}] if category == "huge" else
                       [{"order": [text]}, {"widgets": [{"id": text}]}])
            for payload in invalid:
                reject(lambda payload=payload: service.call("view.arrange", payload))
                require(sql_snapshot(bus) == (before, event_before), "Refused layout changed durable state/events")
            patch = {"widgets": [{"id": "needs", "size": "l"}] * (128 if category == "huge" else 1)}
            result = service.call("view.arrange", patch)
            state, events = sql_snapshot(bus)
            require(state["arrangement"] == {**first, **patch} and events[-1][1:] == ("view.arrange", patch)
                    and result["event"]["payload"] == patch, "Layout patch lost omitted fields or event identity")
            if category == "stale":
                from .ui_command_bus import UICommandBus
                UICommandBus(root).update("arrangement", {"dock": "right", "canopy": "off"})
                service.call("view.arrange", {"sidebarHidden": False})
                require(sql_snapshot(bus)[0]["arrangement"] == {**first, **patch, "dock": "right", "canopy": "off", "sidebarHidden": False},
                        "Already opened view service overwrote newly persisted omitted fields")
            if category == "concurrency":
                patches = [{"order": ["canopy", "main", "panel", "sidebar"]}, {"dock": "right"},
                           {"canopy": "off"}, {"sidebarHidden": False}]
                gate = threading.Barrier(len(patches))
                def update(row):
                    gate.wait(timeout=10)
                    return service.call("view.arrange", row)
                with ThreadPoolExecutor(max_workers=len(patches)) as pool:
                    outputs = list(pool.map(update, patches))
                expected = {**first, **patch}
                for row in patches:
                    expected.update(row)
                state, events = sql_snapshot(bus)
                require(state["arrangement"] == expected and all(row["event"]["payload"] in patches for row in outputs)
                        and [row[2] for row in events[-4:]] and len(events) == len(event_before) + 5,
                        "Concurrent disjoint layout patches lost a field or event")
            return {"durableEvents": len(sql_snapshot(bus)[1]), "widgets": len(patch["widgets"]), "closedOwner": True}
        if identity == "d-ui.view-schemas":
            from .neyvia_workspace_tools import DEFINITIONS
            definitions = {row[0]: row[2] for row in DEFINITIONS}
            require(definitions["view.arrange"]["order"]["items"]["enum"] == ["sidebar", "main", "panel", "canopy"] and
                    definitions["view.arrange"]["dock"]["enum"] == ["left", "right"], "Public layout schema omits host regions/docks")
            for pane in ("replay", "builder", "accounts"):
                require(pane in definitions["pane.show"]["kind"]["enum"], "Public pane schema omits " + pane)
                result = service.call("pane.show", {"kind": pane, "target": text})
                require(result["event"]["payload"]["kind"] == pane and sql_snapshot(bus)[1][-1][2]["kind"] == pane,
                        "Advertised pane could not dispatch its real durable command")
            before = sql_snapshot(bus)
            invalid = text or "not-a-pane"
            reject(lambda: service.call("pane.show", {"kind": invalid, "target": text}))
            require(sql_snapshot(bus) == before, "Unadvertised pane reached durable command dispatch")
            return {"dispatchedAdvertisedPanes": 3, "invalidCharacters": len(invalid)}
        scene = "Saved " + text if text else "Saved empty input"
        for payload in ({}, {"name": "focus", "save": scene}, {"save": "Cockpit"}):
            before = sql_snapshot(bus)
            reject(lambda payload=payload: service.call("view.scene", payload))
            require(sql_snapshot(bus) == before, "Invalid/exclusive scene action emitted an event")
        saved = service.call("view.scene", {"save": scene})
        require(saved["event"]["payload"] == {"save": scene.strip()} and sql_snapshot(bus)[1][-1][2] == saved["event"]["payload"], "Scene command lost entered name")
        before = sql_snapshot(bus)
        reject(lambda: service.call("view.theme", {"theme": text or "unknown"}))
        require(sql_snapshot(bus) == before, "Invalid theme changed state/events")
        service.call("view.theme", {"theme": "sunset"})
        require(sql_snapshot(bus)[0]["theme"] == "sunset", "Theme command failed to persist actual selected theme")
        session_id = "known-" + text[:64]
        bus.update("sessions", {session_id: {"title": text}})
        service.call("view.float", {"id": session_id, "floating": True})
        if category == "stale":
            from .ui_command_bus import UICommandBus
            UICommandBus(root).update("floating", {"newer-session": True})
        service.call("view.float", {"id": session_id, "floating": False})
        require(sql_snapshot(bus)[0]["floating"][session_id] is False and
                (category != "stale" or sql_snapshot(bus)[0]["floating"]["newer-session"]), "Float reversal lost current unrelated persisted state")
        return {"sceneCharacters": len(scene), "knownSessionFloatedAndRestored": True, "closedOwner": True}


def _search(root, category, identity):
    from .research import search_workspace_detailed
    from .ui_command_bus import UICommandBus
    from .local_network_policy import install, release
    # Real local-only application policy selects its existing in-process
    # search implementation, so this fixture does not start an rg/Python child.
    bus = UICommandBus(root); bus.put("settings", {"localOnly": True})
    install(root, owner=bus)
    try:
        folder = root / "src"; folder.mkdir()
        count = 256 if category == "huge" else 0 if category == "empty" else 3
        query = "needle" if category != "unicode" else "雪"
        source = folder / "café-東京.txt"
        lines = [f"line-{i} {query} actual recorded match" for i in range(count)]
        source.write_text("\n".join(lines), encoding="utf-8")
        (folder / "binary.txt").write_bytes(query.encode() + b"\x00")
        generated = root / "node_modules"; generated.mkdir(); (generated / "generated.txt").write_text(query, encoding="utf-8")
        excluded = root / ".agent_control"; (excluded / "generated.txt").write_text(query, encoding="utf-8")
        def search(limit=200, budget=5):
            return search_workspace_detailed(root, query, "src/*.txt", max_results=limit, time_budget=budget, engine="python")
        result = search(17 if category == "huge" else 200)
        expected = [{"path": str(source.relative_to(root)), "line": i + 1, "snippet": line} for i, line in enumerate(lines)]
        require(result["matches"] == expected[:17 if category == "huge" else 200] and result["count"] == len(result["matches"])
                and result["engine"] == "python-inprocess" and (not result["complete"] if category == "huge" else result["complete"]),
                "Search output differs from independent source lines or bounded completeness")
        timed = search(budget=0)
        require(timed["timedOut"] and not timed["complete"] and timed["matches"] == [], "Expired budget claimed a complete search")
        reject(lambda: search_workspace_detailed(root, query, "../*.txt", engine="python"))
        if category == "stale":
            source.write_text("replacement with no matching word", encoding="utf-8")
            newer = search()
            require(newer["matches"] == [] and result["matches"] == expected, "Search reused old disk result or changed earlier observation")
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            before = source.read_bytes()
            with _deny_read(source):
                denied = search()
            require(denied["matches"] == [] and denied["skipped"]["unreadable"] >= 1 and source.read_bytes() == before,
                    "OS denied search invented a match or modified unreadable source")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: search(), range(16)))
            require(all(row["matches"] == expected and row["complete"] for row in results), "Concurrent local searches lost exact source lines")
        return {"sourceLines": count, "matches": result["count"], "timedOutIncomplete": True, "childrenStarted": 0}
    finally:
        release(bus)


def _product(root, category, identity):
    from .product_catalog import ProductDescriptor
    text = TEXT[category]
    count = 256 if category == "huge" else 1
    valid = ProductDescriptor("owned", text or "Owned empty label", "app", "shared", text or "Owned local fixture",
                              tuple(f"operation-{i}" for i in range(count)), ("preview",), "https://github.com/fixture/owned",
                              agent_callable=True, user_interactive=True)
    value = valid.as_dict()
    require(value["productId"] == "owned" and value["kind"] == "app" and value["audience"] == "shared"
            and value["operations"] == valid.operations and value["sourceUrl"] == valid.source_url, "Validated app serialization loses required source/callability")
    mutations = [("kind", "tool"), ("audience", "user"), ("agent_callable", False), ("surfaces", ()),
                 ("user_interactive", False), ("source_url", "https://example.invalid/owned")]
    for field, changed in mutations:
        candidate = asdict(valid); candidate[field] = changed
        reject(lambda candidate=candidate: ProductDescriptor(**candidate).as_dict())
    if category == "empty":
        for field in ("product_id", "name", "summary", "operations"):
            candidate = asdict(valid); candidate[field] = () if field == "operations" else ""
            reject(lambda candidate=candidate: ProductDescriptor(**candidate).validate())
    require(not list(root.iterdir()), "Descriptor validation performed a filesystem effect")
    return {"operations": count, "invalidBoundaryMutationsRejected": len(mutations), "sourceConnected": False}


def _ocr_registry(root, category, identity):
    from .ocr_benchmark import load_candidate_registry, OCR_CANDIDATE_REGISTRY_SCHEMA
    text = TEXT.get(category, "updated registry")
    count = 256 if category == "huge" else 1
    rows = [{"candidateId": f"owned-{i}", "license": text[:512] or "MIT", "source": "https://example.invalid/owned", "description": text[:512]} for i in range(count)]
    rows.append({"candidateId": "tesseract-5.5.2", "license": "Apache-2.0", "source": "https://example.invalid/tesseract",
                 "role": "emergency-fallback", "eligible": False})
    path = root / "registry.json"
    def save(chosen):
        path.write_text(json.dumps({"schema": OCR_CANDIDATE_REGISTRY_SCHEMA, "candidates": chosen}, ensure_ascii=False), encoding="utf-8")
    save(rows)
    actual = load_candidate_registry(path)
    require(actual == json.loads(path.read_bytes()) and actual["candidates"] == rows, "Registry load differs from independently parsed bytes")
    for mutated in ([], rows + [rows[0]], [{"candidateId": "", "license": "MIT", "source": "declared"}],
                    [{"candidateId": "missing-license", "source": "declared"}],
                    [{"candidateId": "missing-source", "license": "MIT"}],
                    [{**rows[-1], "eligible": True}]):
        save(mutated); reject(lambda: load_candidate_registry(path))
    save(rows)
    if category == "stale":
        newer = [{**rows[0], "license": "New observed license"}, rows[-1]]
        save(newer)
        require(load_candidate_registry(path)["candidates"] == newer and actual["candidates"] == rows, "Registry loader retained old source metadata or mutated earlier result")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = path.read_bytes()
        with _deny_read(path):
            denied = reject(lambda: load_candidate_registry(path), (OSError,))
        require(path.read_bytes() == before, "Denied registry observation changed source")
        return {"candidates": len(rows), "permissionRefusal": denied, "providersStarted": 0}
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: load_candidate_registry(path), range(16)))
        require(all(row["candidates"] == rows for row in results), "Concurrent registry observations lost current candidate identity/role")
    return {"candidates": len(rows), "registryBytes": path.stat().st_size, "registrySha256": digest(path), "providersStarted": 0}


def _capsules(root, category, identity):
    from .skill_capsules import SkillCapsuleRegistry
    text = TEXT.get(category, "changed actual instruction")
    source = root / "instructions/SKILL.md"; source.parent.mkdir(); source.write_text(text, encoding="utf-8")
    folder = root / "config"; folder.mkdir()
    definition = {"id": "owned-design", "label": text or "Owned empty design",
                  "instructionPaths": ["instructions/SKILL.md"], "requiredToolScopes": ["workspace.read"],
                  "proofGates": ["observed-local-source"], "phaseBindings": {"verify": ["Observe exact source hash"]},
                  "minimumEvidence": 1, "executableChecks": []}
    (folder / "neyvia_skill_capsules.json").write_text(json.dumps({"capsules": [definition]}, ensure_ascii=False), encoding="utf-8")
    owner = SkillCapsuleRegistry(root)
    ids = [] if category == "empty" else ["owned-design", "missing-design"]
    plan = owner.compile(ids)
    require(plan["planHash"] == hashlib.sha256(canonical({key: value for key, value in plan.items() if key != "planHash"}).encode()).hexdigest(), "Capsule full plan hash does not bind current data")
    if not ids:
        require(not plan["skills"] and not plan["instructionReceipts"] and not plan["proofGates"], "Empty selection acquired instructions/gates")
    else:
        require(plan["instructionReceipts"] == [{"path": "instructions/SKILL.md", "available": True,
                "sha256": digest(source), "bytes": source.stat().st_size}] and plan["missingSkillIds"] == ["missing-design"]
                and plan["proofGates"] == definition["proofGates"], "Capsule lost current source identity or proof gate")
    if category == "stale":
        old_hash = digest(source); source.write_text(text + " replaced", encoding="utf-8")
        updated = owner.compile(ids)
        require(updated["instructionReceipts"][0]["sha256"] == digest(source) != old_hash and
                updated["planHash"] != plan["planHash"], "Previously loaded capsule owner reused stale instruction bytes")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        before = source.read_bytes()
        with _deny_read(source):
            denied = reject(lambda: owner.compile(ids), (OSError,))
        require(source.read_bytes() == before, "Denied capsule compile changed instruction bytes")
        return {"permissionRefusal": denied, "sourceBytes": len(before), "checksExecuted": 0}
    if category == "concurrency":
        gate = threading.Barrier(8)
        def compile_once(_):
            gate.wait(timeout=10)
            return SkillCapsuleRegistry(root).compile(ids)
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(compile_once, range(8)))
        require(all(value == plan for value in values), "Concurrent source compilation diverged on unchanged bytes")
    return {"instructionBytes": source.stat().st_size, "planHash": plan["planHash"], "checksExecuted": 0}


BUILDERS = {name: _plan for name in ("d-ui.plan-order", "d-ui.plan-compact", "d-ui.plan-skills")}
BUILDERS.update({name: _compiler for name in ("d-ui.compiler-dag", "d-ui.compiler-authority", "d-ui.compiler-hash")})
BUILDERS.update({name: _night for name in ("d-ui.night-policy", "d-ui.night-notification", "d-ui.night-digest")})
BUILDERS.update({name: _views for name in ("d-ui.view-arrange", "d-ui.view-schemas", "d-ui.view-controls")})
BUILDERS.update({"d-ui.usage-truth": _usage, "d-ui.search-bounds": _search, "d-ui.product-boundary": _product,
                 "d-ui.ocr-candidates": _ocr_registry, "d-ui.design-capsules": _capsules})


def _context(root, category, identity):
    from types import SimpleNamespace
    from .web_backend import FluxioWebBackend, _chat_prompt
    text = TEXT.get(category, "fresh actual observation").strip()
    backend = FluxioWebBackend.__new__(FluxioWebBackend)
    if identity == "d-ui.selected-profile":
        if category == "permissions":
            from .agent_prompt_library import save_prompt_library, _library_path
            from .edge_fixture_models import _deny_read
            save_prompt_library(root, {"roles": {"chat": {"instructions": "Owned authored instructions"}}}, expected_revision=0)
            path = _library_path(root); before = path.read_bytes()
            payload = {"message": text, "_profileWorkspacePath": str(root), "systemPromptProfile": "ui_ux"}
            with _deny_read(path):
                reject(lambda: _chat_prompt(payload), (ValueError, OSError))
                supplied = _chat_prompt({**payload, "_systemInstructions": "Owned supplied instructions"})
                require(supplied.startswith("Owned supplied instructions\n\n") and text in supplied,
                        "Explicit caller-authored instructions failed their no-file-read branch")
            require(path.read_bytes() == before, "Permission refusal changed selected authored prompt keeper")
            return {"actualPromptFileSharingDenied": True, "deniedLibraryReadRefused": True, "suppliedAuthoredBranchPreserved": True}
        if not text:
            reject(lambda: _chat_prompt({"message": "", "_profileWorkspacePath": str(root)}))
            text = "Valid request after empty refusal"
        payload = {"message": text, "_profileWorkspacePath": str(root)}
        profiles = [_chat_prompt({**payload, "systemPromptProfile": profile}) for profile in ("general", "ui_ux")]
        require(profiles[0] != profiles[1] and "Task profile: general (explicit)." in profiles[0] and
                "Task profile: ui_ux (explicit)." in profiles[1] and all(text in prompt for prompt in profiles),
                "Explicit adaptive profile lost selected identity or original request")
        authored = _chat_prompt({**payload, "systemPromptProfile": "ui_ux", "_systemInstructions": "Owned authored instructions"})
        require(authored.startswith("Owned authored instructions\n\n") and text in authored and "Task profile:" not in authored,
                "Explicit authored instructions lost precedence to adaptive profile")
        return {"inputCharacters": len(text), "distinctProfiles": 2, "authoredPrecedence": True}
    if identity == "d-ui.dependency-context":
        count = 128 if category == "huge" else 0 if category == "empty" else 3
        dependencies = {"execute": {f"p{i}" for i in range(count)}}
        completed = {f"p{i}": {"result": {"reply": text, "status": "completed", "raw": "RAW-MUST-NOT-LEAK",
                      "compartment": {"messages": "NOISE" * 1000}, "route": {"model": "owned-local", "runtimeId": "codex"}}}
                      for i in range(count)}
        completed["future"] = {"result": {"reply": "FUTURE-MUST-NOT-LEAK"}}
        original = copy.deepcopy(completed)
        rows = backend._dependency_context_rows(node_id="execute", dependencies=dependencies, completed_results=completed)
        require(len(rows) == count and all(row["kind"] == "dependency-result" for row in rows) and completed == original,
                "Dependency projection lost ancestors or mutated completed evidence")
        joined = json.dumps(rows)
        require("RAW-MUST-NOT-LEAK" not in joined and "NOISE" not in joined and "FUTURE-MUST-NOT-LEAK" not in joined,
                "Uncompleted/noisy runtime data entered dependency context")
        return {"completedAncestorResults": count, "outputCharacters": len(joined)}
    if identity == "d-ui.route-context":
        from .neyvia_conversations import NeyviaConversationStore
        store = NeyviaConversationStore(root)
        # The context owner needs only its real durable conversation store;
        # avoid constructing unrelated MCP adapters/runtimes for a projection.
        backend._neyvia_mcp = SimpleNamespace(conversations=store)
        routes = {"executor": {"role": "executor", "runtimeId": "codex", "provider": "owned-local", "model": "owned-model",
                                "effort": "high", "irrelevant": text}}
        created = store.create_conversation(kind="orchestration", title=text, metadata={"routeSnapshot": routes,
                "routeSnapshotVersion": 7, "immutableAtCreation": True})
        cid = created["conversationId"]
        count = 32 if category == "huge" else 0 if category == "empty" else 3
        for index in range(count):
            store.append_turn(cid, role="user", content=f"turn-{index}:" + text[:1000], turn_id=f"turn-{index}")
        conversation = store.get_conversation(cid, include_turns=True)
        def observe():
            return backend._build_neyvia_base_context(conversation_id=cid, conversation=conversation, explicit_selection=None)
        rows = observe()
        require(rows[0]["kind"] == "conversation-route-snapshot" and '"routeSnapshotVersion": 7' in rows[0]["content"] and
                '"model": "owned-model"' in rows[0]["content"] and "irrelevant" not in rows[0]["content"], "Route identity lost order/version or leaked arbitrary metadata")
        require(len([row for row in rows if row["kind"] == "conversation-turn"]) == min(6, count) and
                NeyviaConversationStore(root).get_conversation(cid)["metadata"]["routeSnapshot"] == routes,
                "Context bound history incorrectly or changed persisted immutable routes")
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            before = store.database_path.read_bytes()
            with _deny_read(store.database_path):
                reject(lambda: observe(), (OSError, sqlite3.DatabaseError))
            require(store.database_path.read_bytes() == before, "Denied context read changed conversation database")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                values = list(pool.map(lambda _: observe(), range(16)))
            require(all(value == rows for value in values), "Concurrent fixed context reads diverged")
        if category == "stale":
            store.append_turn(cid, role="user", content="Fresh later turn", turn_id="fresh-turn")
            conversation = store.get_conversation(cid, include_turns=True)
            fresh = observe()
            require(fresh[0] == rows[0] and any(row["content"] == "Fresh later turn" for row in fresh), "Context reused old bounded history or changed frozen routes")
        return {"persistedRouteVersion": 7, "boundedTurns": min(6, count), "sourceAtoms": len(rows)}
    if identity == "d-ui.workspace-integrity":
        def integrity(result):
            return backend._workspace_integrity_receipt(node_id="executor", invocation_id="owned-call", conversation_id="owned-conversation",
                    mission_id=None, workspace_path=root, result=result)
        missing = integrity({"status": "completed", "filesChanged": [text] if text else []})
        require(missing["status"] == "unavailable" and not missing["evidenceAvailable"] and missing["filesChanged"] == [],
                "Adapter text without change evidence became workspace proof")
        protected = integrity({"status": "completed", "readOnly": {"enforced": True, "sourceWorkspace": str(root), "executionWorkspace": str(root / "mirror")}})
        require(protected["status"] == "source-protected" and protected["sourceWorkspaceStatus"] == "protected" and
                protected["workspaceState"] == "unchanged", "Read-only source protection became observed content evidence")
        observed = integrity({"status": "completed", "filesChanged": [], "changeEvidenceAvailable": True})
        require(observed["status"] == "unchanged" and observed["changeEvidenceAvailable"], "Authoritative observed unchanged case was lost")
        return {"unprovenChangesRejected": True, "readOnlyProtectionSeparate": True, "unchangedEvidenceRetained": True}
    path = root / "café-東京.txt"
    path.write_text(text, encoding="utf-8")
    before = backend._orchestration_workspace_snapshot(root)
    require(before["complete"] and before["files"][path.name] == digest(path), "Snapshot digest differs from actual file")
    path.write_text(text + " replaced", encoding="utf-8")
    new = root / "new.txt"; new.write_text("created", encoding="utf-8")
    after = backend._orchestration_workspace_snapshot(root)
    result = backend._apply_orchestration_workspace_evidence({"status": "completed", "filesChanged": []}, before=before, after=after)
    require(result["filesChanged"] == sorted([path.name, new.name]) and result["changeEvidenceAvailable"] and
            result["workspaceSnapshotEvidence"]["changedFileCount"] == 2, "Actual file replacement/create was absent from content evidence")
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(path):
            unreadable = backend._orchestration_workspace_snapshot(root)
        denied = backend._apply_orchestration_workspace_evidence({}, before=before, after=unreadable)
        require(not unreadable["complete"] and not denied["workspaceSnapshotEvidence"]["available"] and
                not denied.get("changeEvidenceAvailable"), "Denied file read fabricated complete snapshot evidence")
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: backend._orchestration_workspace_snapshot(root), range(16)))
        require(all(value == after for value in values), "Concurrent stable file readers diverged from observed hashes")
    if category == "stale":
        path.write_text("latest actual file", encoding="utf-8")
        later = backend._orchestration_workspace_snapshot(root)
        require(later["files"][path.name] == digest(path) != after["files"][path.name] and before["files"][path.name] != later["files"][path.name], "Snapshot reused stale source digest")
    unchanged = backend._apply_orchestration_workspace_evidence({}, before=after, after=after)
    incomplete = backend._apply_orchestration_workspace_evidence({}, before={**before, "complete": False}, after=after)
    require(unchanged["filesChanged"] == [] and unchanged["changeEvidenceAvailable"] and not incomplete.get("changeEvidenceAvailable"), "Incomplete or unchanged snapshots reported false changes")
    return {"filesActuallyModified": 1, "filesActuallyCreated": 1, "sourceDigestReopened": True}


def _readiness(root, category, identity):
    from .night_mode import build_night_readiness_receipt
    keys = ["NEYVIA_C7D_SYNTHETIC_KEY", "NEYVIA_C7D_MISSING_KEY"]
    prior = os.environ.get(keys[0])
    text = TEXT.get(category, "owned readiness")
    try:
        for value, expected in (("", "missing"), ("short", "***"), ("synthetic-value-123456", "syn...3456")):
            os.environ[keys[0]] = value
            receipt = build_night_readiness_receipt(root=root, mission_id=text[:128], host="owned-local", runtime="owned-local",
                    runtime_auth_available=True, runtime_available=True, selected_skills_available=True, nas_worker_alive=True,
                    desktop_gateway_status="online", model_key_names=keys)
            require(receipt.masked_keys[keys[0]] == expected and receipt.masked_keys[keys[1]] == "missing" and
                    receipt.status == ("passed" if all(receipt.checks.values()) else "blocked"), "Readiness key status unmasked or failed check admitted")
            for changed in ("runtime_auth_available", "runtime_available", "selected_skills_available", "nas_worker_alive"):
                kwargs = {"runtime_auth_available": True, "runtime_available": True, "selected_skills_available": True, "nas_worker_alive": True}
                kwargs[changed] = False
                blocked = build_night_readiness_receipt(root=root, desktop_gateway_status="online", **kwargs)
                require(blocked.status == "blocked" and blocked.failures, "One failed readiness check masked by others")
        if category == "permissions":
            from .edge_fixture_models import _deny_read
            blocked_path = root / "blocked-file"; blocked_path.write_text("keeper", encoding="utf-8")
            blocked = build_night_readiness_receipt(root=blocked_path, desktop_gateway_status="online", runtime_auth_available=True,
                    runtime_available=True, selected_skills_available=True, nas_worker_alive=True)
            require(blocked.status == "blocked" and blocked.checks["mission_queue_can_run"] is False and blocked_path.read_text(encoding="utf-8") == "keeper", "Unwritable queue readiness escaped refusal or changed keeper")
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                values = list(pool.map(lambda _: build_night_readiness_receipt(root=root, desktop_gateway_status="online"), range(16)))
            require(all(value.status == "blocked" for value in values), "Parallel readiness lost required unavailable checks")
        return {"syntheticKeyMaskCases": 3, "isolatedReadinessFailureCases": 12, "workersContacted": 0, "sourceKeysRead": False}
    finally:
        if prior is None:
            os.environ.pop(keys[0], None)
        else:
            os.environ[keys[0]] = prior


BUILDERS.update({name: _context for name in ("d-ui.workspace-integrity", "d-ui.workspace-snapshots", "d-ui.dependency-context", "d-ui.route-context", "d-ui.selected-profile")})
BUILDERS["d-ui.night-readiness"] = _readiness


def _mesh_receipt(root, category, identity):
    from datetime import UTC, datetime, timedelta
    import importlib.util
    verifier_path=Path(__file__).resolve().parents[2]/"scripts/verify_personal_mesh_browser_proof.py"
    spec=importlib.util.spec_from_file_location("c7_mesh_receipt_verifier",verifier_path)
    verifier=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    validate_receipt,ProofError,SCHEMA=verifier.validate_receipt,verifier.ProofError,verifier.SCHEMA
    source = root / "panel.jsx"; source.write_text(TEXT.get(category, "owned changed source"), encoding="utf-8")
    now = datetime.now(UTC)
    count = 512 if category == "huge" else 0 if category == "empty" else 3
    receipt = {"schema": SCHEMA, "capturedAt": now.isoformat(), "maxAgeSeconds": 900,
            "sourceFiles": [{"path": source.name, "sha256": digest(source)}],
            "states": {"route": {"before": "/control", "after": "/control"}, "modal": {"before": "open", "after": "closed"},
                "entry": {"before": "Lab", "after": "Personal Mesh"}, "meshTabs": {name: {"visited": True, "capture": "generated-receipt-validator-only:" + name,
                "visibleValues": [TEXT.get(category, name) or name]} for name in ("trust", "nearby", "sync")}},
            "api": {"historyCount": count}, "ui": {"historyCount": count, "visibleValues": ["generated receipt; no actual capture"]},
            "computedStyles": [{"name": "generated colors", "foreground": "#fff", "background": "#000"}]}
    validate = lambda payload: validate_receipt(payload, root=root, now=now)
    result = validate(receipt)
    require(result["ok"] and result["historyCount"] == count and result["sourceFiles"][0]["sha256"] == digest(source), "Validator lost exact source/history linkage")
    mutations = [lambda r: r["ui"].update(historyCount=count + 1), lambda r: r["ui"].update(visibleValues=["undefined"]),
                 lambda r: r["states"]["modal"].update(after="open"), lambda r: r["states"]["meshTabs"]["nearby"].update(visited=False),
                 lambda r: r["computedStyles"][0].update(background="#fff"), lambda r: r["sourceFiles"][0].update(path="../outside.jsx"),
                 lambda r: r.update(metadata={"authorization": "synthetic prohibited field"}),
                 lambda r: r.update(capturedAt=(now - timedelta(hours=1)).isoformat())]
    for mutate in mutations:
        invalid = copy.deepcopy(receipt); mutate(invalid); reject(lambda: validate(invalid), (ProofError,))
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with _deny_read(source):
            reject(lambda: validate(receipt), (OSError,))
    if category == "stale":
        source.write_text("actually changed source", encoding="utf-8")
        reject(lambda: validate(receipt), (ProofError,))
    if category == "concurrency":
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: validate(receipt), range(16)))
        require(all(row == result for row in results), "Concurrent fixed source receipt validation diverged")
    return {"generatedValidatorInput": True, "sourceHashReopened": True, "invalidBoundaryMutationsRejected": len(mutations), "renderedProof": False, "browserCaptures": 0}


def _office_boundary(root, category, identity):
    from .proof_credential_guard import prepare_broker_fixture
    from .capability_service import CapabilityService
    prepare_broker_fixture(root)
    owner = CapabilityService(root, catalog_path=REPO / "config/capability_packs.json")
    text = TEXT.get(category, "owned operation boundary")
    reject(lambda: owner.execute_tool_operation({"toolId": "tool.libreoffice", "operationId": "office.invalid-" + text, "arguments": {}}), (KeyError,))
    source = root / "source.md"; source.write_text(text, encoding="utf-8")
    result = owner.execute_tool_operation({"toolId": "tool.pandoc", "operationId": "document.convert", "arguments": {"path": str(source)}})
    require(not result["ok"] and result["status"] in {"invalid_arguments", "tool_not_ready"}, "Incomplete convert acquired a successful effect")
    if result["status"] == "invalid_arguments":
        require(result["inputValidation"]["valid"] is not True, "Invalid argument report lost invalid schema")
    descriptor = owner.adapters.descriptor("document.libreoffice")
    if descriptor.supports_execution:
        raise ValueError("Installed executable LibreOffice needs separately approved actual operation; refusal fixture cannot claim execution")
    unavailable = owner.execute_tool_operation({"toolId": "tool.libreoffice", "operationId": "office.version", "arguments": {}})
    require(not unavailable["ok"] and unavailable["status"] in {"adapter_required", "tool_not_ready"}, "Non-executable Office adapter claimed real effect")
    require(source.read_text(encoding="utf-8") == text, "Invalid Office request changed input keeper")
    return {"inputCharacters": len(text), "unknownOperationRefused": True, "invalidConvertStatus": result["status"], "unsupportedOfficeStatus": unavailable["status"], "officeExecutionClaimed": False}


BUILDERS["d-ui.mesh-receipt"] = _mesh_receipt
BUILDERS["d-ui.office-boundary"] = _office_boundary


CRASH_CHILD_CODE = """import os,sys
from pathlib import Path
from grant_agent.proof_credential_guard import install
root=Path(sys.argv[1]);install(root)
from grant_agent.edge_fixture_ui_planning_local import BUILDERS
BUILDERS[sys.argv[2]](root,'unicode',sys.argv[2])
os._exit(23)
"""


def _durable_extra(root, category, identity):
    """Crash and permission effects stay on real selected stores, not model data."""
    if category == "interrupted":
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        result = __import__("subprocess").run([sys.executable, "-c", CRASH_CHILD_CODE, str(root), identity], capture_output=True, timeout=60,
                                               env={**os.environ, "PYTHONPATH": str(REPO / "src")},
                                               **hidden_windows_subprocess_kwargs())
        require(result.returncode == 23, "Interrupted owner did not commit its durable operation: " + result.stderr.decode(errors="replace")[-400:])
        if identity == "d-ui.night-digest":
            value = json.loads((root / ".agent_control/overnight/morning_digest_latest.json").read_bytes())
            require(value["completedCount"] == 3 and len(value["completedItems"]) == 3, "Digest durable completion vanished after abrupt exit")
        else:
            from .ui_command_bus import UICommandBus
            state, events = sql_snapshot(UICommandBus(root))
            require(events, "Completed UI events disappeared after abrupt exit")
            if identity == "d-ui.usage-truth":
                require(state["indicators"]["usage"]["total"] == 100 and state["indicators"]["usage"]["used"] == 30, "Usage totals disappeared after abrupt exit")
            if identity == "d-ui.view-arrange":
                require(state["arrangement"]["dock"] == "left", "Arrangement disappeared after abrupt exit")
            if identity == "d-ui.view-controls":
                require(state["theme"] == "sunset" and any(event[1] == "view.scene" for event in events), "Theme/scene events disappeared after abrupt exit")
            if identity == "d-ui.view-schemas":
                require([event[2]["kind"] for event in events if event[1] == "pane.show"] == ["replay", "builder", "accounts"], "Advertised dispatched panes disappeared after abrupt exit")
        return {"ownedChildExitCode": 23, "completedWritesSurvivedAbruptExit": True, "automaticResumeClaimed": False}
    if identity == "d-ui.night-digest":
        from .night_mode import write_morning_digest
        gate = threading.Barrier(8)
        def write(index):
            gate.wait(timeout=10)
            return write_morning_digest(root, completed_items=["writer-" + str(index)], blocked_items=[], proof_commands=[],
                    changed_files=[], nas_sync_status="not requested", first_unchecked_item="owned next item")
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(write, range(8)))
        final = json.loads((root / ".agent_control/overnight/morning_digest_latest.json").read_bytes())
        markdown = (root / ".agent_control/overnight/morning_digest_latest.md").read_text(encoding="utf-8")
        require(len(values) == 8 and final["completedCount"] == 1 and
                any(final == {k: v for k, v in row.items() if k not in {"jsonPath", "markdownPath"}} for row in values) and
                final["completedItems"][0] in markdown, "Concurrent latest digest has mismatched JSON/markdown or partial data")
        return {"concurrentSameRootWriters": 8, "completeReturnedDigests": 8, "latestPairMatchesOneCompleteWrite": True}
    from .ui_command_bus import UICommandBus
    if category == "permissions":
        from .edge_fixture_models import _deny_read
        with workspace(root) as service:
            bus = service.bus; before = sql_snapshot(bus)
            with _deny_read(bus.path):
                if identity == "d-ui.usage-truth":
                    from .neyvia_analytics import publish_indicator
                    reject(lambda: publish_indicator(bus, {"type": "usage.updated", "usage": {"totalTokens": 10}}), (sqlite3.DatabaseError, OSError))
                else:
                    name, payload = ("view.arrange", {"dock": "left"}) if identity == "d-ui.view-arrange" else ("pane.show", {"kind": "builder", "target": "owned"}) if identity == "d-ui.view-schemas" else ("view.theme", {"theme": "sunset"})
                    reject(lambda: service.call(name, payload), (sqlite3.DatabaseError, OSError))
            require(sql_snapshot(bus) == before, "Denied UI store mutation changed keeper state/events")
        return {"actualDatabaseSharingDenied": True, "stateAndEventLedgerUnchanged": True}
    with workspace(root) as service:
        bus = service.bus; before = sql_snapshot(bus)
        if identity == "d-ui.usage-truth":
            from .neyvia_analytics import publish_indicator
            def operation(index):
                return publish_indicator(bus, {"type": "usage.updated", "runId": str(index), "usage": {"totalTokens": 10, "cachedInputTokens": 3}})
        elif identity == "d-ui.view-controls":
            def operation(index):
                return service.call("view.scene", {"save": "owned scene " + str(index)})
        else:
            def operation(index):
                return service.call("pane.show", {"kind": ["replay", "builder", "accounts"][index % 3], "target": "owned-" + str(index)})
        if category == "concurrency":
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(operation, range(16)))
            events = sql_snapshot(bus)[1][len(before[1]):]
            require(len(events) == 16 and len({event[0] for event in events}) == 16, "Concurrent actual command events lost a dispatched operation")
            if identity == "d-ui.view-controls":
                require({event[2]["save"] for event in events} == {"owned scene " + str(i) for i in range(16)}, "Concurrent scene dispatch lost selected names")
            return {"parallelCalls": 16, "uniqueDurableEvents": len(events)}
        operation(0)
        external = UICommandBus(root); external.emit("external-marker", {"id": "fresh"})
        operation(1)
        require(any(event[1] == "external-marker" for event in sql_snapshot(bus)[1]) and sql_snapshot(bus)[1][-1][1] == "pane.show",
                "Already opened command owner erased fresh unrelated external event")
        return {"staleOwnerPreservedFreshExternalEvent": True}


ORIGINAL_BUILDERS = dict(BUILDERS)
for _identity in ("d-ui.night-digest", "d-ui.usage-truth", "d-ui.view-arrange", "d-ui.view-controls", "d-ui.view-schemas"):
    def _dispatch(root, category, identity, originals=ORIGINAL_BUILDERS):
        original_categories = set(TEXT) | ({"permissions", "stale"} if identity == "d-ui.night-digest" else
            {"stale"} if identity in {"d-ui.usage-truth", "d-ui.view-controls"} else
            {"concurrency", "stale"} if identity == "d-ui.view-arrange" else set())
        return originals[identity](root, category, identity) if category in original_categories else _durable_extra(root, category, identity)
    BUILDERS[_identity] = _dispatch


def run(root, contracts, categories):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    rows = []
    for identity in sorted(IDS & set(contracts)):
        for category in categories:
            if category not in set(TEXT) | EXTRA.get(identity, set()):
                continue
            area = root / (identity.removeprefix("d-ui.") + "-" + category)
            area.mkdir(parents=True, exist_ok=False)
            row = {"id": f"ui-planning-local.{identity}.{category}", "category": category, "contracts": [identity],
                   "boundary": "Exact local production owner; generated supplied inputs and independently reopened SQL/files/hash/value observations, no rendering/provider/device claim"}
            started = time.perf_counter()
            try:
                row.update(status="passed", detail=BUILDERS[identity](area, category, identity))
            except Exception as error:
                row.update(status="failed", detail={"type": type(error).__name__, "error": str(error),
                    "traceback": traceback.format_exc()[-4000:], "scratchRoot": str(area)})
            row["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)
    return rows


def blocker(contract, category):
    identity = contract.get("id", "")
    if identity not in IDS or category in set(TEXT) | EXTRA.get(identity, set()):
        return None
    pure = {"d-ui.plan-order", "d-ui.plan-compact", "d-ui.plan-skills", "d-ui.compiler-dag", "d-ui.compiler-hash",
            "d-ui.product-boundary", "d-ui.night-notification", "d-ui.night-policy", "d-ui.workspace-integrity", "d-ui.dependency-context"}
    if identity in pure:
        return {"kind": "not_applicable", "reason": f"Audited {identity} at {contract.get('checkedAt', [])} is an argument-only synchronous planner/compiler/descriptor/message transform: no shared mutation, durable writer, worker, OS permission check, endpoint or revision-confirmation field exists for {category}. Risk/scopes and supplied readiness failure decisions are exercised separately where they enter actual owner inputs; no sent notification is claimed."}
    if category == "offline":
        return {"kind": "not_applicable", "reason": f"Audited {identity} owns selected local files/SQL or supplied policy/layout/usage/capsule input; it has no network operation. Recorded gateway/capacity decisions are supplied inputs, not proof of a disconnected device. No transport execution can be interrupted by this category at the exact owner."}
    if identity == "d-ui.compiler-authority" and category in {"concurrency", "interrupted", "stale"}:
        return {"kind": "not_applicable", "reason": "Audited NeyviaProgram.compile copies declared lane scopes/risk into a new permission envelope synchronously. It accepts no external grant, revision confirmation or worker state, and never executes a step. Declared permissions are separately perturbed in the real permissions fixture."}
    if identity == "d-ui.office-boundary":
        return {"kind": "not_applicable", "reason": f"The audited office boundary rejects unadvertised operation IDs/invalid supplied arguments and returns unavailable for adapters explicitly lacking executable support before filesystem/transport/runtime dispatch. {category} has no worker, revision or OS authority mechanism in these checked refusal branches; supported Office execution needs a separate real installed adapter journey."}
    if identity == "d-ui.selected-profile" and category in {"concurrency", "interrupted", "stale"}:
        return {"kind": "not_applicable", "reason": f"Exact selected-profile invariant is compilation of an explicitly supplied current task-profile ID/user message and authored-instruction precedence into a returned prompt. It has no shared mutation, resumable worker or revision admission for {category}; persisted prompt-library reads and mutation ownership are covered by their separate authored-prompt contracts."}
    if category == "interrupted" and identity in {"d-ui.workspace-snapshots", "d-ui.ocr-candidates", "d-ui.design-capsules", "d-ui.search-bounds", "d-ui.route-context", "d-ui.night-readiness", "d-ui.mesh-receipt"}:
        return {"kind": "not_applicable", "reason": f"Inspected exact {identity} reads current local source/SQL or supplied evidence into a synchronous return. Its checked owner owns no resumable worker, durable write or partially committed result; interrupted reads yield no result. Separate writer/store recovery contracts govern durable effects."}
    return {"kind": "fixture_gap", "reason": f"A separate real {category} mutation at {identity} owner is not implemented; successful ordinary/generated inputs cannot stand in for this pair."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from .proof_ports import C7_PORTS
    if args.port not in C7_PORTS:
        parser.error("Explicit assigned port 48741-48749 required")
    args.output.resolve().relative_to(REPO)
    root = REPO / ".agent_control/proofs/c7/ui-planning-local" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("HOME", "USERPROFILE", "CODEX_HOME", "HERMES_HOME", "OPENCLAW_STATE_DIR", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        folder = root / "home" / key.lower(); folder.mkdir(parents=True); os.environ[key] = str(folder)
    for key in ("NEYVIA_UI_STATE_ROOT", "NEYVIA_UI_BACKEND_URL", "FLUXIO_WORKSPACE_ROOT", "NEYVIA_NAS_ROOT", "FLUXIO_NAS_ROOT"):
        os.environ.pop(key, None)
    os.environ.update(NEYVIA_C7_PORT=str(args.port), NEYVIA_TOOL_AUTO_UPDATE="0", FLUXIO_RUNTIME_AUTO_UPDATE="0",
                      FLUXIO_WATCHDOG_AUTOSTART="0", NEYVIA_COORDINATOR_AUTOSTART="0", PYTHONDONTWRITEBYTECODE="1")
    from .proof_credential_guard import install
    install(root)
    observations = {"networkAttempts": 0, "childProcessesStarted": 0, "unauthorizedChildProcessesStarted": 0}
    import shutil
    git_executable = shutil.which("git")
    git_version_executables = {Path(git_executable).resolve()} if git_executable else set()
    if git_executable:
        for candidate in (Path(git_executable).parent.parent / "mingw64/bin/git.exe",
                          Path(git_executable).parent.parent / "cmd/git.exe"):
            if candidate.is_file():
                git_version_executables.add(candidate.resolve())
    def audit(event, values):
        if event in {"socket.connect", "socket.bind"}:
            observations["networkAttempts"] += 1
            raise PermissionError("Local planning fixture has no network authority")
        if event == "subprocess.Popen":
            observations["childProcessesStarted"] += 1
            executable, command = values[:2]
            from subprocess import list2cmdline
            expected = [[sys.executable, "-c", CRASH_CHILD_CODE,
                         str(root / (identity.removeprefix("d-ui.") + "-interrupted")), identity]
                        for identity in ("d-ui.night-digest", "d-ui.usage-truth", "d-ui.view-arrange", "d-ui.view-controls", "d-ui.view-schemas")]
            expected.extend([[str(path), "--version"] for path in git_version_executables])
            if (executable is None or Path(executable).resolve() in {Path(args[0]).resolve() for args in expected}) and any(
                    command == list2cmdline(arguments) if isinstance(command, str) else list(command) == arguments
                    for arguments in expected):
                return
            observations["unauthorizedChildProcessesStarted"] += 1
            raise PermissionError("Only exact guarded crash fixtures and read-only installed Git version discovery are authorized")
    sys.addaudithook(audit)
    contracts = {row["id"]: row for row in json.loads((REPO / "config/proofs/d-ui-planning.json").read_text(encoding="utf-8"))["contracts"]}
    sources = sorted(set(SOURCES))
    bindings = {name: digest(REPO / name) for name in sources}
    started = time.perf_counter()
    rows = run(root, contracts, CATEGORIES)
    stable = bindings == {name: digest(REPO / name) for name in sources}
    bytes_written = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    report = {"schema": "neyvia.c7c.ui-planning-local.v1", "ok": stable and all(row["status"] == "passed" for row in rows),
              "explicitPort": args.port, "sourceBindings": bindings, "sourceStable": stable, "scratchRoot": str(root),
              "cases": rows, "counts": {status: sum(row["status"] == status for row in rows) for status in ("passed", "failed")},
              "contractsExercised": sorted({identity for row in rows for identity in row["contracts"]}),
              "auditedNotApplicable": [{"contract": identity, "category": category, **reason}
                  for identity in sorted(IDS) for category in CATEGORIES
                  if (reason := blocker(contracts[identity], category)) and reason["kind"] == "not_applicable"],
              "scratchBytes": bytes_written, "writeBudgetBytes": 100_000_000, "withinWriteBudget": bytes_written <= 100_000_000,
              "allOwnedServicesClosed": True, "closedChildProcesses": [], **observations,
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    report["ok"] = report["ok"] and report["withinWriteBudget"] and not observations["networkAttempts"] and not observations["unauthorizedChildProcessesStarted"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("ok", "counts", "scratchBytes", "durationMs")}))
    print(json.dumps({"failed": [row for row in rows if row["status"] == "failed"]}))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
