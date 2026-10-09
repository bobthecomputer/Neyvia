"""Observed runtime matrix and owner-selected routing limits; no provider fallback."""
from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor

from .ui_command_bus import bus_for

EXECUTABLES = {"codex": "codex", "claude-code": "claude", "opencode": "opencode", "hermes": "hermes",
               "cursor": "cursor", "kimi": "kimi", "grok": "grok", "openclaw": "openclaw"}
RANKS = {"ask": 0, "plan": 0, "read-only": 0, "manual": 1, "acceptEdits": 1, "auto": 1,
         "workspace": 1, "workspace-write": 1, "dontAsk": 2, "full": 2, "full-access": 2, "bypassPermissions": 2}
DEFINITIONS = [("runtime.list", "Read a bounded runtime matrix, readiness, routing profiles and owner ceilings. Detailed model schemas remain deferred to connected_provider_options_command.", {}, [])]
PROFILE_NAMES = ("planner", "executor", "verifier", "classifier")


def mission_route(root, task):
    """Resolve a profile once, before mission approval; saved tasks keep their route."""
    name = task.get("routingProfile")
    if name is None and not any(task.get(key) for key in ("harness", "model")) and task.get("owner") != "Paul":
        name = "executor" if bus_for(root).get("runtime.profiles", {}).get("executor") else None
    if name is None:
        return dict(task)
    if name not in PROFILE_NAMES:
        raise ValueError("Choose planner, executor, verifier or classifier routingProfile")
    profile = bus_for(root).get("runtime.profiles", {}).get(name)
    if not profile:
        raise ValueError("Routing profile is not configured: " + name)
    fields = {"harness": profile["app"], **{key: profile.get(key) for key in ("model", "effort", "permissionMode", "transport")}}
    if any(task.get(key) is not None and task[key] != value for key, value in fields.items()):
        raise ValueError("A profile route cannot also override its route fields")
    return {**task, **fields, "routingProfile": name}


def compact(service):
    result = matrix(service)
    for row in result["runtimes"]:
        options = row.pop("options", None)
        if options:
            row["modelCount"] = len(options.get("models", []))
            row["defaultModels"] = [model["id"] for model in options.get("models", []) if model.get("default")][:8]
            row["permissionModes"] = options.get("permissionModes", [])
            row["billing"] = options.get("billing")
    return {"ok": True, **result}


def enforce(root, app, options):
    from .connected_sessions.broker import ConnectedError
    policy = bus_for(root).get("runtime.policies", {}).get(app)
    if not policy:
        return
    mode = options.permission_mode
    if mode not in RANKS or RANKS[mode] > RANKS[policy["permissionCeiling"]]:
        raise ConnectedError("runtime_policy", "Choose an explicit permission mode within the runtime ceiling", 403)
    if policy.get("allowedModels") and options.model not in policy["allowedModels"]:
        raise ConnectedError("runtime_policy", "Choose an explicit model from the owner's allowed models", 403)


def matrix(service):
    broker = service.broker()
    def observe(app):
        adapter, ready, reason = broker.registry.availability(app)
        row = {"id": app, "installed": app == "neyvia" or bool(shutil.which(EXECUTABLES.get(app, app))),
               "kind": "native" if app == "neyvia" else "connected", "connected": bool(ready), "reason": reason,
               "capabilities": {}, "auth": {"status": "unknown"}, "version": None}
        if ready:
            try:
                options = broker.provider_options(app)
                row["options"] = options
                row["capabilities"] = {"start": bool(adapter.can_start_new()[0]) if hasattr(adapter, "can_start_new") else False,
                    "continue": callable(getattr(adapter, "start_turn", None)), "interrupt": callable(getattr(adapter, "interrupt", None)),
                    "approve": callable(getattr(adapter, "answer", None))}
                if app == "opencode":
                    row["version"] = options.get("version")
                row["optionErrors"] = options.get("errors")
                auth = getattr(adapter, "auth", None)
                if callable(auth):
                    from .connected_sessions.registry import bounded
                    status = bounded(lambda: auth(force=False), 10, "runtime-auth")
                    row["auth"] = {key: status[key] for key in ("status", "authenticated", "loggedIn", "authMethod", "type") if key in status}
            except Exception as exc:
                row["optionError"] = str(exc)[:300]
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(observe, ("neyvia", "codex", "claude-code", "opencode")))
    native_options = next((row.get("options") or {} for row in rows if row["id"] == "neyvia"), {})
    wrapped = {row["id"]: row for row in native_options.get("runtimes", [])}
    rows.extend({"id": app, "installed": bool(shutil.which(cli)), "kind": "planned", "connected": False,
                 "capabilities": {}, "auth": {"status": "unknown"}, "reason": "No verified connected adapter", "version": None}
                for app, cli in EXECUTABLES.items() if app not in {row["id"] for row in rows})
    for row in rows:
        runtime = wrapped.get({"kimi": "kimi-code", "grok": "grok-build"}.get(row["id"], row["id"]))
        if runtime and row["kind"] == "planned":
            row["kind"] = "wrapped"
            row["wrappedRoute"] = {"app": "neyvia", "runtime": runtime["id"], "permissionModes": runtime.get("permissionModes"),
                                   "state": "configured discovery; installation/auth/execution not implied"}
            row["reason"] = "Wrapped Neyvia route exists; no direct connected-session adapter"
    return {"runtimes": rows, "policies": service.bus.get("runtime.policies", {}),
            "profiles": service.bus.get("runtime.profiles", {}), "scope": "This backend and installed native CLIs; unknown fields are not inferred"}


def request(service, body, method):
    if method == "GET":
        from .proof_readiness import status
        return {**matrix(service), "selfCheck": status(service.bus.root)}
    kind = body.get("action")
    if kind == "policy":
        app, ceiling, models = body.get("app"), body.get("permissionCeiling"), body.get("allowedModels", [])
        if app not in {"neyvia", "codex", "claude-code", "opencode"} or ceiling not in {"read-only", "workspace", "full-access"}:
            raise ValueError("Choose a connected runtime and supported ceiling")
        if not isinstance(models, list) or not all(isinstance(model, str) and model for model in models):
            raise ValueError("allowedModels must be a list of model IDs")
        policies = service.bus.get("runtime.policies", {})
        policies[app] = {"permissionCeiling": ceiling, "allowedModels": list(dict.fromkeys(models))}
        service.bus.put("runtime.policies", policies)
        return {"ok": True, "policies": policies, "appliesTo": "new turns; running turns keep their original scope"}
    if kind == "profile":
        name = body.get("name")
        if name not in PROFILE_NAMES:
            raise ValueError("Unknown routing profile")
        route = body.get("route")
        if route is not None:
            if not isinstance(route, dict) or set(route) - {"app", "model", "effort", "permissionMode", "transport"}:
                raise ValueError("Use explicit route fields")
            options = service.broker().provider_options(route.get("app"))
            model = next((row for row in options.get("models", []) if row["id"] == route.get("model")), None)
            if not model or route.get("permissionMode") not in {row["id"] for row in options.get("permissionModes", [])}:
                raise ValueError("Choose a model and mode reported by that runtime")
            if route.get("effort") and route["effort"] not in model.get("efforts", []):
                raise ValueError("Effort is not reported for the selected model")
            from .connected_sessions.broker import ConnectedBroker
            enforce(service.bus.root, route["app"], ConnectedBroker._turn_options(route))
        profiles = service.bus.get("runtime.profiles", {})
        if route is None:
            profiles.pop(name, None)
        else:
            profiles[name] = route
        service.bus.put("runtime.profiles", profiles)
        return {"ok": True, "profiles": profiles, "appliesTo": "new mission tasks select routingProfile; executor is the default when no explicit route is supplied; approved tasks keep their saved route"}
    raise ValueError("Use policy or profile action")
