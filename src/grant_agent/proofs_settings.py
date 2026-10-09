"""Canonical Settings contracts checked inside its existing SQLite transaction."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

CONTRACTS = ("settings.revision-cas", "settings.invalid-preserves", "settings.canonical-mirrors",
             "settings.night-policy-event", "settings.legacy-theme", "settings.view-durable")


def require(condition, contract, detail):
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def snapshot(db):
    keys = ("settings", "cleanupPolicy", "nightshift.resources", "density", "theme")
    return {"state": {row["key"]: row["value"] for row in db.execute(
        "SELECT key,value FROM state WHERE key IN (?,?,?,?,?)", keys)},
        "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0]}


def check_revision(expected, actual):
    if expected is not None and (type(expected) is not int or expected != actual):
        from .neyvia_settings import SettingsConflict
        raise SettingsConflict("Settings changed. Refresh and retry with the current revision.")


def check_rejection(db, before):
    require(snapshot(db) == before, "settings.invalid-preserves", "rejected patch changed canonical state or emitted events")


def check_committed(db, patch, value, previous_revision, revision, events):
    from .neyvia_settings import THEMES
    stored = {row["key"]: json.loads(row["value"]) for row in db.execute(
        "SELECT key,value FROM state WHERE key IN ('settings','cleanupPolicy','nightshift.resources','density','theme')")}
    require(revision == previous_revision + 1 and stored["settings"] == {**value, "revision": revision},
            "settings.revision-cas", "successful update must persist exactly one revision increment")
    expected = {"cleanupPolicy": value["cleanup"], "nightshift.resources": value["nightShift"],
                "density": {"level": value["density"]}, "theme": THEMES[value["theme"]]}
    require(all(stored[key] == wanted for key, wanted in expected.items()),
            "settings.canonical-mirrors", "canonical policy and legacy view storage disagree")
    resource_events = [event for event in events if event["action"] == "nightshift.resources.updated"]
    require(len(resource_events) == int("nightShift" in patch) and (not resource_events or resource_events[0]["payload"] == value["nightShift"]),
            "settings.night-policy-event", "night-policy update must emit exactly its saved normalized policy")
    for event in events:
        persisted = db.execute("SELECT action,payload FROM events WHERE id=?", (int(event["id"]),)).fetchone()
        require(persisted is not None and persisted["action"] == event["action"] and json.loads(persisted["payload"]) == event["payload"],
                "settings.night-policy-event", "returned event differs from persisted transaction event")
    require(stored["theme"] == THEMES[value["theme"]], "settings.legacy-theme", "legacy theme differs from canonical preference")


def check_view(bus, key, requested):
    require(bus.get(key) == requested, "settings.view-durable", "view preference must be durable before returning success")


def self_check(root):
    from .neyvia_workspace_tools import WorkspaceTools
    from .neyvia_settings import get, update, SettingsConflict
    started = time.perf_counter()
    base = Path(root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="settings-", dir=base))
    service = WorkspaceTools(scratch)
    cases = []

    def run(identity, contracts, action):
        from .contract_gate import wants
        if not wants(contracts):
            return
        try:
            action()
            cases.append({"id": identity, "contracts": contracts, "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": contracts, "ok": False, "error": str(error)})

    def observed_storage():
        with service.bus.connect() as db:
            return snapshot(db)

    def budgets():
        patch = {"nightShift": {"perHarnessBudgets": {"codex": {"maxTokens": 1234, "maxSeconds": 120}},
                 "maxNightSeconds": 300, "quietGpuHours": {"start": "22:00", "end": "06:00", "timeZone": "UTC"}}}
        before = get(service)
        saved = update(service, patch, before["revision"])
        policy = service.bus.get("nightshift.resources")
        require(all(policy[key] == item for key, item in patch["nightShift"].items()), "settings.canonical-mirrors", "night budgets/quiet hours changed")
        require(saved["revision"] == before["revision"] + 1, "settings.revision-cas", "revision did not increment once")
        resource_events = [event for event in saved["events"] if event["action"] == "nightshift.resources.updated"]
        require(len(resource_events) == 1 and resource_events[0]["payload"] == policy, "settings.night-policy-event", "night budget event mismatch")
        state = observed_storage()
        try:
            update(service, {"density": "grove"}, before["revision"])
        except SettingsConflict:
            pass
        else:
            raise ValueError("Stale Settings revision was accepted")
        require(observed_storage() == state and get(service)["settings"]["nightShift"] == policy, "settings.invalid-preserves", "stale update changed saved state")

    def invalid(patch):
        revision, state = get(service)["revision"], observed_storage()
        try:
            update(service, patch, revision)
        except ValueError:
            pass
        else:
            raise ValueError("Invalid night controls were accepted")
        require(observed_storage() == state and get(service)["revision"] == revision, "settings.invalid-preserves", "invalid controls wrote state/events")

    def legacy():
        result = service.call("view.theme", {"theme": "light"})
        require(result["ok"] and result["theme"] == "light" and get(service)["settings"]["theme"] == "morning", "settings.legacy-theme", "legacy theme changed a parallel preference")
        require(service.call("view.ambient", {"on": False})["ok"] and service.bus.get("ambient") is False, "settings.view-durable", "ambient preference not saved")
        require(service.call("view.transparency", {"level": "summaries"})["ok"] and service.bus.get("transparency") == "summaries", "settings.view-durable", "transparency preference not saved")

    manual_receipts = []

    def manual_startup():
        from .native_tools import NativeToolRegistry
        from . import neyvia_manuals
        from .neyvia_settings import call
        registry = NativeToolRegistry(scratch)

        def dispatch(tool, args, action_id=""):
            require(tool.startswith("neyvia.settings."), "settings.startup-scope", "out-of-area startup action")
            return call(service, tool[len("neyvia."):], args)

        observed = neyvia_manuals.call(service, "manual.observe", {"id": "settings", "state": "current"}, dispatcher=dispatch, registry=registry)
        require(observed.get("ok"), "settings.startup-observer", "current Settings observer failed")
        completed = neyvia_manuals.call(service, "manual.run", {"id": "settings", "procedure": "reenter-setup", "inputs": {}}, dispatcher=dispatch, registry=registry)
        require(completed.get("ok") and completed.get("status") == "completed" and all(row["passed"] for row in completed["checks"]),
                "settings.startup-goal", f"setup procedure failed: {completed.get('error')}")
        manual_receipts.extend([{"id": "settings", "chapter": "overview", "observer": "current", "ok": True},
                                {"id": "settings", "chapter": "overview", "procedure": "reenter-setup", "runId": completed["runId"], "checks": len(completed["checks"]), "ok": True}])

    try:
        run("test_settings_preserve_night_budgets_quiet_hours_and_revision", list(CONTRACTS[:4]), budgets)
        for index, patch in enumerate([
            {"nightShift": {"perHarnessBudgets": {"codex": {"maxTokens": True}}}},
            {"nightShift": {"quietGpuHours": {"start": "24:01", "end": "06:00", "timeZone": "UTC"}}},
            {"nightShift": {"maxNightSeconds": 0}},
        ]):
            run(f"test_settings_reject_invalid_night_controls_without_writes[patch{index}]", ["settings.invalid-preserves"], lambda patch=patch: invalid(patch))
        run("test_legacy_theme_action_updates_canonical_preferences", ["settings.legacy-theme", "settings.view-durable"], legacy)
        run("grounded_settings_observer_and_procedure", [], manual_startup)
    finally:
        service.close()
    return {"ok": all(case["ok"] for case in cases), "contracts": list(CONTRACTS), "cases": cases,
            "failures": [case for case in cases if not case["ok"]], "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "scratchRoot": str(scratch), "manualReceipts": manual_receipts,
            "frontier": "Seven catalog/native-launch/policy lifecycle cases remain unmapped; retain the test file."}
