"""Validate the bounded effect predicate before any browser action is executed."""
from __future__ import annotations

import json


EXPECT_SCHEMA = {"type": "object", "properties": {"path": {"type": "string", "maxLength": 1000},
                 "equals": {}, "contains": {"type": "string", "maxLength": 20000}},
                 "required": ["path"], "additionalProperties": False,
                 "oneOf": [{"required": ["equals"]}, {"required": ["contains"]}]}


def validate_expect(args):
    expected = args.get("expect")
    if expected is None:
        return
    if (not isinstance(expected, dict) or set(expected) - {"path", "equals", "contains"}
            or ("equals" in expected) == ("contains" in expected)
            or not isinstance(expected.get("path"), str)
            or not expected["path"].startswith("/") or len(expected["path"]) > 1000
            or any(key in {"__proto__", "prototype", "constructor"} for key in expected["path"].split("/"))
            or "contains" in expected and not isinstance(expected["contains"], str)
            or len(json.dumps(expected, ensure_ascii=False)) > 22000):
        raise ValueError("Effect check requires a bounded JSON Pointer and exactly equals or contains")
