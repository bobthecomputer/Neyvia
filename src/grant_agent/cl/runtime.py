"""CL execution adapts syntax to existing tools; it never grants authority."""
from __future__ import annotations

from copy import deepcopy
import time
from jsonschema import Draft202012Validator

from .parser import BareWord, Handle, Quantity, Action
from .renderer import HandleStore, StaleHandleError, encode_value, render_receipt, render_state, render_delta


def prepare_action(action, schema, *, store=None):
    arguments = dict(action.arguments)
    names = list(schema.get("properties", {}))
    if len(action.positional) > len(names):
        raise ValueError("Too many positional arguments")
    for name, value in zip(names, action.positional):
        if name in arguments:
            raise ValueError("Duplicate positional/named argument: " + name)
        arguments[name] = value

    def coerce(value, field, name=""):
        if isinstance(value, Handle):
            if store is None:
                raise ValueError("A handle belongs to the context that observed it")
            value = store.resolve(value)
        if field.get("x-cl") == "id" and isinstance(value, (int, BareWord)):
            value = str(value)
        if isinstance(value, BareWord):
            if field.get("type") == "string" and field.get("x-cl") not in {"path", "id", "url", "word", "handle"} and not field.get("enum") and "const" not in field:
                raise ValueError("str arguments must be quoted: " + name)
            value = str(value)
        if isinstance(value, Quantity):
            if field.get("format") != "duration" or value.unit not in {"ms", "s", "m", "h", "d"}:
                raise ValueError("Quantity does not match the declared type: " + name)
            seconds = value.value * {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}[value.unit]
            value = "PT" + str(seconds) + "S"
        if isinstance(value, dict):
            return {key: coerce(item, field.get("properties", {}).get(key, {}), key) for key, item in value.items()}
        if isinstance(value, list):
            return [coerce(item, field.get("items", {}), name) for item in value]
        if isinstance(value, Action):
            raise ValueError("Nested action calls cannot bypass the checked gateway")
        return value

    arguments = {name: coerce(value, schema.get("properties", {}).get(name, {}), name) for name, value in arguments.items()}
    for name, field in schema.get("properties", {}).items():
        if name not in arguments and "default" in field:
            arguments[name] = deepcopy(field["default"])
    Draft202012Validator(schema).validate(arguments)
    return arguments


def state_layer(name, value):
    layer = value.get("layer") if isinstance(value, dict) else None
    if not isinstance(layer, str):
        layer = name.removeprefix("neyvia.").split(".")[0]
    return layer


def execute_action(text, describe, dispatch, *, action_id="", checks=None, impact=None,
                   observe=None, store=None, read_renderer=None):
    """Parse and validate exactly one call before entering the caller's gateway."""
    from .parser import parse_action

    action = parse_action(text)
    description = describe(action.name)
    tool = description.get("tool", description)
    schema = tool.get("inputSchema", tool.get("input_schema"))
    if not isinstance(schema, dict):
        raise ValueError("The exact action has no grounded input schema")
    arguments = prepare_action(action, schema, store=store)
    if checks is None and impact is None and observe is None:
        return dispatch(action.name, arguments, action_id=action_id)
    store = store or HandleStore()
    started = time.monotonic()
    checks = list(checks or [])
    mutating = (tool.get("effect") in {"~", "!"} or
                tool.get("annotations", {}).get("readOnlyHint") is False or
                tool.get("mutability_class", "read") not in {"read", "none"})
    automatic = [check for check in checks if not check.get("parameters")]
    selected = {name: args for name, args in action.checks}
    requested = [check for check in checks if check["name"] in selected]
    if selected.keys() - {check["name"] for check in checks}:
        raise ValueError("Unknown attached check")
    if mutating and not any(row.get("observer") for row in automatic):
        value = {"ok": False, "status": "frontier", "error": "Effect has no grounded automatic observer check; no action ran"}
        alias = store.put(value, "r")
        return {**value, "cl": render_receipt(action.name, "frontier", 0, alias), "receipt": alias}
    try:
        before = observe() if mutating and observe else None
    except Exception as exc:
        value = {"ok": False, "status": "unknown", "error": "Pre-action observer failed; no action ran: " + str(exc)}
        alias = store.put(value, "r")
        return {**value, "cl": render_receipt(action.name, "unknown", 0, alias), "receipt": alias}
    performed = []
    for check in automatic:
        if check.get("pre"):
            passed = bool(check["check"](arguments, None, before))
            performed.append((check["name"], passed))
            if not passed:
                value = {"ok": False, "status": "refused", "error": "Precondition failed"}
                alias = store.put(value, "r")
                return {**value, "cl": render_receipt(action.name, "refused", 0, alias, performed), "receipt": alias}
    try:
        output = dispatch(action.name, arguments, action_id=action_id)
    except Exception as exc:
        output = {"ok": False, "status": "unknown", "error": "Dispatch outcome unknown; inspect before retry: " + str(exc)}
    value = output
    while isinstance(value, dict) and isinstance(value.get("result"), dict):
        value = value["result"]
    status = "ok"
    if isinstance(output, dict) and output.get("ok") is False or isinstance(value, dict) and value.get("ok") is False:
        marker = str(value.get("status", output.get("status", "fail")))
        status = "ask" if "approval" in marker else "stale" if "stale" in marker or marker == "conflict" else "unknown" if marker in {"unknown", "action_uncertain", "unknown_side_effects"} else "refused" if "denied" in marker or "contract" in marker else "fail"
    after = None
    if mutating and status == "ok" and observe:
        try:
            after = observe()
        except Exception:
            status = "unknown"
    if status == "ok":
        for check in automatic + [row for row in requested if row not in automatic]:
            if check.get("pre"):
                continue
            try:
                passed = check["check"]({**arguments, **selected.get(check["name"], {})}, value, before)
                passed = bool(passed) if passed is not None else None
            except Exception:
                passed = None
            performed.append((check["name"], passed))
        if any(passed is False for _, passed in performed):
            status = "fail"
        elif any(passed is None for _, passed in performed):
            status = "unknown"
    read_text = None
    if status == "ok" and not mutating and read_renderer:
        try:
            read_text = read_renderer(value)
        except Exception:
            status = "unknown"
            performed.append(("state-projection", None))
    elapsed = round(1000 * (time.monotonic() - started))
    retained = {"tool": action.name, "arguments": arguments, "result": output, "before": before,
                "after": after, "checks": [{"name": name, "passed": passed} for name, passed in performed], "status": status}
    alias = store.put(retained, "r")
    text = render_receipt(action.name, status, elapsed, alias, performed)
    if after is not None:
        from ..manual_state import changes
        delta = changes(before, after)
        text += "S effect same\n" if not delta else render_delta("effect", delta, store=store)
        text += render_state(state_layer(action.name, after), after, store=store)
    elif status == "ok" and not mutating:
        text += read_text if read_text is not None else render_state(state_layer(action.name, value), value, store=store)
    if impact is not None:
        realized = {key: arguments.get(str(item), item) for key, item in impact.items()}
        text += "I " + action.name + " " + " ".join(key + ":" + encode_value(item) for key, item in realized.items()) + "\n"
    return {"ok": status == "ok", "status": status, "result": output, "cl": text,
            "receipt": alias, "checks": retained["checks"]}


def execute_gateway(text, gateway, *, action_id=""):
    """Keep managed and native calls in their original approval/receipt path."""
    def dispatch(name, arguments, *, action_id):
        description = gateway.describe(name)
        if description.get("kind") == "managed":
            raise ValueError("A managed suite needs an exact operation; use the described managed-call gateway")
        return gateway.call_native(name, arguments, action_id=action_id)

    return execute_action(text, gateway.describe, dispatch, action_id=action_id)


def describe_tool(row, *, level=2):
    from .schema import mcp_to_cl
    from .parser import filter_level

    tool = row.get("tool", row)
    return filter_level(mcp_to_cl(tool), level)


def describe_registry(registry, *, level=0, family=""):
    from .schema import mcp_to_cl
    from .parser import filter_level

    rows = registry.list_tools(include_unavailable=True, include_schemas=True)
    if family:
        rows = [row for row in rows if row["name"].startswith(family + ".")]
        if not rows:
            raise ValueError("Unknown tool family")
    return filter_level(mcp_to_cl(rows), level)
