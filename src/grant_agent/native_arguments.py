"""Normalize unambiguous typed transport values only against declared tool schemas."""
from __future__ import annotations

import json


def normalize(schema, value, path="", changes=None, depth=0):
    changes = changes if changes is not None else []
    if depth > 32:
        raise ValueError("Tool arguments exceed the supported nesting depth")
    expected = schema.get("type")
    original = value
    if expected == "object" and value == "" and schema.get("x-empty-text-is-empty-object"):
        value = {}
    if isinstance(value, str) and isinstance(expected, str) and expected in {"integer", "number", "boolean", "array", "object"}:
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        valid = {"integer": type(parsed) is int, "number": type(parsed) in {int, float},
                 "boolean": type(parsed) is bool, "array": isinstance(parsed, list), "object": isinstance(parsed, dict)}
        if valid.get(expected):
            value = parsed
    if expected == "array" and isinstance(value, dict) and set(value) == {"item"}:
        value = value["item"] if isinstance(value["item"], list) else [value["item"]]
    if type(value) is not type(original):
        changes.append({"field": path, "from": type(original).__name__, "to": type(value).__name__})
    if isinstance(value, dict) and expected == "object":
        properties = schema.get("properties") or {}
        return {key: normalize(properties[key], item, path + "." + key if path else key, changes, depth + 1) if key in properties else item
                for key, item in value.items()}
    if isinstance(value, list) and expected == "array" and schema.get("items"):
        return [normalize(schema["items"], item, f"{path}[{index}]", changes, depth + 1) for index, item in enumerate(value)]
    return value
