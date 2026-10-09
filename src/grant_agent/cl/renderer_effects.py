"""Pane effects are renderer observations, never merely queued UI events."""
from __future__ import annotations

import hashlib
import re
import time
import uuid

SUPPORTED = {"neyvia.pane.show", "neyvia.browser.task.pause"}
MAX_AGE_SECONDS = 30


def _content(root, kind, target):
    if kind != "file":
        return None
    from ..neyvia_panes import _guard, _decode, MAX_EDIT_BYTES
    path = _guard(root, target)
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_EDIT_BYTES:
        raise ValueError("Pane content observation is bounded to 2 MiB")
    decoded = _decode(path.read_bytes())
    if decoded is None:
        raise ValueError("File pane content observation requires displayable text")
    return hashlib.sha256(decoded[0].encode("utf-8")).hexdigest()


def show(workspace, arguments):
    payload = {"kind": arguments["kind"], "target": arguments["target"],
               "paneId": "pane-" + uuid.uuid4().hex,
               "observationRequired": True}
    if arguments.get("placement") is not None:
        if arguments["placement"] not in {"main", "side", "full", "bubble"}:
            raise ValueError("Unknown pane placement")
        payload["placement"] = arguments["placement"]
    if arguments.get("side") is not None:
        if arguments.get("placement") != "side" or arguments["side"] not in {"left", "right"}:
            raise ValueError("side only applies to a side panel")
        payload["side"] = arguments["side"]
    for key in ("runtimeSessionId", "ownerTaskId"):
        if arguments.get(key):
            payload[key] = arguments[key]
    digest = _content(workspace.bus.root, payload["kind"], payload["target"])
    if digest is not None:
        payload["expectedContentHash"] = digest
    workspace.bus.put("pane", payload)
    result = workspace.result("pane.show", payload)
    return {**result, "status": "pending_renderer", "paneId": payload["paneId"]}


def admit_ack(event, body, client):
    """Validate a content report at the existing authenticated event boundary."""
    if event["action"] != "pane.show" or not event["payload"].get("observationRequired"):
        return None
    report = body.get("observation")
    if report is None or body["ok"] is False:
        return {"eventId": str(event["id"]), "acknowledged": False}
    if not isinstance(report, dict):
        raise ValueError("observation must be a pane content report")
    request = event["payload"]
    for key in ("paneId", "kind", "target"):
        if report.get(key) != request[key]:
            raise ValueError("Renderer observation does not match the requested " + key)
    runtime = report.get("runtimeId")
    if not isinstance(runtime, str) or not runtime.strip() or len(runtime) > 128:
        raise ValueError("Renderer runtimeId is required")
    digest = report.get("contentHash")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("contentHash must be a lowercase SHA-256 digest")
    if not isinstance(report.get("visible"), bool) or not isinstance(report.get("mounted"), bool):
        raise ValueError("mounted and visible must be booleans")
    if request.get("expectedContentHash") and digest != request["expectedContentHash"]:
        raise ValueError("Renderer content hash differs from the requested content")
    return {"eventId": str(event["id"]), "paneId": request["paneId"],
            "runtimeId": runtime, "kind": request["kind"], "target": request["target"],
            "contentHash": digest, "visible": report["visible"], "mounted": report["mounted"],
            "acknowledged": True, "observedAt": time.time(), "client": client}


def observe(bus, event_id=None):
    with bus.connect() as db:
        row = db.execute("SELECT * FROM events WHERE action='pane.show' " +
            ("AND id=? " if event_id is not None else "") + "ORDER BY id DESC LIMIT 1",
            (int(event_id),) if event_id is not None else ()).fetchone()
    if row is None:
        return {"ok": True, "acknowledged": False, "visible": False, "mounted": False}
    import json
    request = json.loads(row["payload"])
    report = bus.get("renderer:pane:" + str(row["id"]), {})
    age = time.time() - report.get("observedAt", 0)
    fresh = report.get("acknowledged") is True and 0 <= age <= MAX_AGE_SECONDS
    current = bus.get("pane", {}).get("paneId") == request.get("paneId")
    expected = _content(bus.root, request.get("kind"), request.get("target"))
    required = request.get("expectedContentHash")
    content_matches = (required is None and expected is None) or (
        expected is not None and expected == report.get("contentHash") and expected == required)
    return {"ok": True, **report, "eventId": str(row["id"]), "request": request,
            "fresh": fresh, "current": current, "contentMatches": content_matches,
            "acknowledged": bool(fresh and current and content_matches),
            "visible": bool(report.get("visible") and fresh and current and content_matches),
            "mounted": bool(report.get("mounted") and fresh and current and content_matches)}


def snapshot_for(protocol, name, args):
    return _observe(protocol)


def _observe(protocol, event_id=None):
    from ..ui_command_bus import bus_for
    return observe(bus_for(protocol.gateway.root), event_id)


def checks_for(protocol, name, args):
    if name not in SUPPORTED or protocol.scope is not None and "neyvia.pane.observe" not in protocol.scope:
        return []
    def witness(arguments, value, previous):
        event = value.get("event", {})
        handoff = name == "neyvia.browser.task.pause"
        fresh = _observe(protocol, value.get("paneEventId") if handoff else event.get("id"))
        if not fresh.get("acknowledged") or not fresh.get("mounted") or not fresh.get("visible"):
            return None if not fresh.get("acknowledged") else False
        pinned = value.get("rendererObservation")
        observed = {key: fresh[key] for key in ("paneId", "runtimeId", "contentHash", "kind", "target")}
        if pinned is not None and pinned != observed:
            return False
        value["rendererObservation"] = observed
        if handoff:
            from ..neyvia_browser import service_for
            from ..ui_command_bus import bus_for
            from .fixcl4_render_effects import observe as shell_observe
            shell = shell_observe(bus_for(protocol.gateway.root))
            tab = service_for(protocol.gateway.root).tab({"tabId": arguments["tabId"]})
            window = next((win for win in shell.get("windows", []) if win.get("id") == "pane:browser:" + arguments["tabId"]), {})
            regions = {row["id"]: row["x"] for row in shell.get("dom", {}).get("regions", [])}
            return (fresh["paneId"] == value["paneId"] and fresh["target"] == arguments["tabId"]
                    and fresh["kind"] == "browser" and fresh["request"].get("ownerTaskId") == value["taskId"]
                    and fresh["request"].get("placement") == "side" and fresh["request"].get("side") == "right"
                    and shell.get("fresh") and window.get("placement") == "side"
                    and "panel" in regions and "main" in regions and regions["panel"] > regions["main"]
                    and tab.get("agentGranted") is False and tab.get("ownerTask", {}).get("status") == "needs_owner")
        return fresh["request"]["paneId"] == value["paneId"] and all(fresh[key] == arguments[key] for key in ("kind", "target"))
    def verify(arguments, value, previous):
        # A handoff opens a lazily loaded pane asynchronously. Wait only for
        # its actual renderer evidence; a queued event is still insufficient.
        deadline = time.monotonic() + (15 if name == "neyvia.browser.task.pause" else 2)
        while True:
            outcome = witness(arguments, value, previous)
            if outcome is True or time.monotonic() >= deadline:
                return outcome
            from ..ui_command_bus import bus_for
            with bus_for(protocol.gateway.root).changed:
                bus_for(protocol.gateway.root).changed.wait(min(.05, max(0, deadline - time.monotonic())))
    return [{"name": "effect-pane-renderer", "observer": True, "effect": True,
             "deferred": True, "observerTool": "neyvia.pane.observe", "subject": dict(args),
             "subjectKey": "pane:visible", "check": verify,
             "expectation": "Fresh mounted visible renderer with the exact pane, runtime and content hash"}]
