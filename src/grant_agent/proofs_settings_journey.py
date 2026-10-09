"""A user-facing Settings preference journey over the production local service."""
from __future__ import annotations

import time
import uuid
from pathlib import Path


CONTRACTS = ("p22.settings.preference-journey",)


def require(condition, detail):
    if not condition:
        raise ValueError("Contract p22.settings.preference-journey: " + detail)


def self_check(root=None):
    """Change a saved preference, read it back, then prove rejected input preserves it."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    state_base = Path(root) if root is not None else Path("D:/NeyviaRuns/P22/state/settings-journey")
    allowed_root = Path("D:/NeyviaRuns/P22").resolve()
    state_root = (state_base / uuid.uuid4().hex).resolve()
    if not state_root.is_relative_to(allowed_root):
        raise ValueError("Settings journey state must stay under D:/NeyviaRuns/P22")
    state_root.mkdir(parents=True, exist_ok=False)
    from .neyvia_workspace_tools import WorkspaceTools
    from .neyvia_settings import get, update, SettingsConflict

    service = WorkspaceTools(state_root)
    try:
        before = get(service)
        # Observe the real durable bus before the preference write. This root is
        # unique to this run, so every returned row below belongs to this journey.
        prior_events = service.bus.since()
        cursor = int(prior_events[-1]["id"]) if prior_events else 0
        requested = {"density": "grove", "look": {"textSize": "l"}}
        committed = update(service, requested, before["revision"], request_id="p22-settings-journey")
        require(committed["revision"] == before["revision"] + 1, "saving the preference must advance one revision")

        # Reopen the production service around the same SQLite state root. The
        # assertion is against a new Settings read plus its durable bus observer,
        # not the update response or an in-memory test double.
        service.close()
        service = WorkspaceTools(state_root)
        observed = get(service)
        require(observed["revision"] == committed["revision"], "reopening Settings must return the committed revision")
        require(observed["settings"]["density"] == "grove" and observed["settings"]["look"]["textSize"] == "l",
                "the selected Grove density and large text must survive a service reopen")
        new_events = service.bus.since(cursor)
        setting_events = [event for event in new_events if event["action"] == "settings.changed"
                          and event["payload"].get("settingsRequestId") == "p22-settings-journey"]
        require(len(setting_events) == 1, "the native durable event observer must see exactly one saved Settings event")
        require(setting_events[0]["payload"].get("changedKeys") == ["density", "look"],
                "the durable event must identify the selected preference fields")
        persisted = (observed["revision"], observed["settings"])
        event_cursor = int(new_events[-1]["id"]) if new_events else cursor

        try:
            update(service, {"look": {"textSize": "enormous"}}, observed["revision"], request_id="p22-settings-invalid")
        except ValueError as error:
            require("Text size is s, m or l" in str(error), "invalid text-size input must return the supported choice guidance")
        else:
            raise ValueError("Contract p22.settings.preference-journey: invalid text-size input was accepted")
        after_invalid = get(service)
        require((after_invalid["revision"], after_invalid["settings"]) == persisted,
                "rejected input must leave the user's saved preference unchanged")
        require(service.bus.since(event_cursor) == [], "rejected input must emit no durable observer event")

        try:
            update(service, {"density": "calm"}, before["revision"], request_id="p22-settings-stale")
        except SettingsConflict as error:
            require("Refresh and retry" in str(error), "stale revision must explain how to recover")
        else:
            raise ValueError("Contract p22.settings.preference-journey: stale preference update was accepted")
        after_stale = get(service)
        require((after_stale["revision"], after_stale["settings"]) == persisted,
                "a stale update must preserve the latest saved preference")
        require(service.bus.since(event_cursor) == [], "a stale revision must emit no durable observer event")

        case = {"id": "settings.preference-journey", "contracts": list(CONTRACTS), "ok": True,
                "revision": after_stale["revision"], "selected": {"density": "grove", "textSize": "l"}}
        return {"ok": True, "contracts": list(CONTRACTS), "cases": [case], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root), "frontier": "Exercises the native Settings service and durable bus; it makes no claim about a rendered browser control."}
    except Exception as error:
        return {"ok": False, "contracts": list(CONTRACTS), "cases": [{"id": "settings.preference-journey",
                "contracts": list(CONTRACTS), "ok": False, "error": str(error)}], "failures": [str(error)],
                "durationMs": round((time.perf_counter() - started) * 1000, 3), "stateRoot": str(state_root)}
    finally:
        service.close()
