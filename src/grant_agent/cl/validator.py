"""Practical CL conformance checks; unknown verification is not success."""
from __future__ import annotations

import re
from typing import Any

from .parser import CLParseError, NAME, parse_document, tokenize
from .schema import SchemaCompileError, normalize_type_expression, split_top, type_to_schema


LIMITATIONS = [
    "Static validation does not prove live observers, permission gates, execution, impacts, handle freshness or claimed undo.",
    "Expression tokenization checks syntax boundaries, not complete expression typing or truth.",
    "Bare enum literals and undeclared lowercase type names are ambiguous in the CL grammar; explicit named declarations resolve known references.",
    "Runtime-only documents have no action declarations; check/action resolution is checked only when signatures are present.",
]


def _signature(body: str) -> tuple[str, str, str]:
    tokens = tokenize(body)
    if len(tokens) < 3 or tokens[1].text != "(" or not re.fullmatch(NAME, tokens[0].text):
        raise CLParseError("Missing signature")
    depth = 0
    for token in tokens[1:]:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
            if depth == 0:
                return tokens[0].text, body[tokens[1].end:token.start], body[token.end:].strip()
    raise CLParseError("Unclosed signature")


def validate_document(text: str, external_actions: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[dict] = []
    def error(code, line, detail):
        errors.append({"rule": code, "line": line, "detail": detail})
    try:
        document = parse_document(text)
    except (CLParseError, ValueError) as exc:
        return {"syntax_ok": False, "semantic_ok": False, "ok": False,
                "errors": [{"rule": "R1", "line": None, "detail": str(exc)}], "limitations": LIMITATIONS}
    types, actions, impacts, checks, procedures, judges = {}, {}, {}, [], [], set()
    syntax_count = 0
    for number, line in enumerate(document.lines, 1):
        if line.tag == "T":
            match = re.match(r"(" + NAME + r")(.*)", line.body)
            if not match or not match[2].strip():
                error("R1", number, "Malformed type declaration")
                syntax_count += 1
            else:
                types[match[1]] = match[2].strip()
        elif line.tag == "A":
            try:
                name, parameters, tail = _signature(line.body)
                match = re.fullmatch(r"(?:->\s+(.+?))?(?:\s*([~!]))?(?:\s*=\s+.+)?", tail)
                if not match:
                    raise CLParseError("Invalid action tail")
            except CLParseError:
                error("R1", number, "Malformed action signature")
                syntax_count += 1
            else:
                actions[name] = {"line": number, "params": parameters, "returns": match[1], "effect": match[2]}
        elif line.tag == "I":
            name = line.body.split(" ", 1)[0]
            impacts.setdefault(name, []).append((number, line.body))
        elif line.tag == "C":
            match = re.fullmatch(r"(" + NAME + r")\s+(" + NAME + r")(?:\((.*?)\))?:\s*(.+)", line.body)
            if not match:
                error("R1", number, "Malformed check declaration")
                syntax_count += 1
            else:
                checks.append({"line": number, "action": match[1], "name": match[2], "params": match[3], "expression": match[4]})
        elif line.tag == "P":
            procedures.append((number, line.body))
        elif line.tag == "J":
            match = re.match(r"(" + NAME + r")\s+([^:]+):", line.body)
            if not match or len(split_top(match[2], "|")) < 2:
                error("R5", number, "Judgement requires at least two options")
            else:
                judges.add(match[1])
        elif line.tag == "M":
            if not re.search(r"\bsrc:", line.body) or not re.search(r"\bstate:(?:quarantine|verified|promoted)\b", line.body):
                error("R13", number, "Memory needs source and a valid promotion state")
    for name, expression in types.items():
        try:
            type_to_schema(expression, types)
        except (SchemaCompileError, ValueError, TypeError) as exc:
            error("R4", None, f"Invalid type {name}: {exc}")
    def validate_params(parameters, number):
        seen = set()
        try:
            for parameter in split_top(normalize_type_expression(parameters)):
                name, separator, expression = parameter.partition(":")
                if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*\??", name):
                    raise SchemaCompileError("Invalid parameter name:type")
                name = name.rstrip("?")
                if name in seen:
                    raise SchemaCompileError("Duplicate parameter " + name)
                seen.add(name)
                # Type compiler also handles defaults inside record fields.
                type_to_schema("{" + parameter + "}", types)
        except (SchemaCompileError, ValueError, TypeError) as exc:
            error("R4", number, str(exc))
    lookup = {**(external_actions or {}), **actions}
    for name, action in actions.items():
        validate_params(action["params"], action["line"])
        if action["returns"]:
            try:
                type_to_schema(action["returns"], types)
            except (SchemaCompileError, ValueError, TypeError) as exc:
                error("R4", action["line"], "Invalid return type: " + str(exc))
        bound_impacts = impacts.get(name, [])
        if not bound_impacts:
            error("R2", action["line"], name + " has no impact declaration")
        if action["effect"]:
            for key in ("writes", "undo", *( ("ask",) if action["effect"] == "!" else () )):
                if not any(re.search(r"\b" + key + ":", body) for _, body in bound_impacts):
                    error("R2", action["line"], name + " lacks " + key + " impact")
            observer_checks = []
            for check in checks:
                if check["action"] != name or check["params"] is not None or check["name"] == "pre":
                    continue
                called = re.findall(r"(" + NAME + r")\(", check["expression"])
                observers = [call for call in called if call in lookup and lookup[call].get("effect") is None]
                if observers or re.search(r"\b(?:el|target|element)\.[A-Za-z_]", check["expression"]):
                    observer_checks.append(check)
            if not observer_checks:
                error("R3", action["line"], name + " has no automatic post-action observer check")
    for check in checks:
        if actions and check["action"] not in lookup:
            error("R4", check["line"], "Check is bound to unknown action " + check["action"])
        if actions:
            for called in re.findall(r"(" + NAME + r")\(", check["expression"]):
                if called not in lookup and called not in {"len", "bytes", "lower", "count", "now"}:
                    error("R4", check["line"], "Check calls an undeclared observer " + called)
        if check["params"] is not None:
            validate_params(check["params"], check["line"])
        try:
            tokenize(check["expression"])
        except CLParseError as exc:
            error("R1", check["line"], str(exc))
            syntax_count += 1
    check_names = {check["name"] for check in checks}
    for number, body in procedures:
        try:
            name, parameters, tail = _signature(body)
            if not tail.startswith(":"):
                raise CLParseError("Procedure requires a body separator")
        except CLParseError:
            error("R1", number, "Malformed procedure")
            syntax_count += 1
            continue
        validate_params(parameters, number)
        try:
            steps = split_top(tail[1:].strip(), ";")
        except SchemaCompileError as exc:
            error("R1", number, str(exc))
            syntax_count += 1
            continue
        for step in steps:
            if step.startswith("J "):
                judge = step[2:].split("=", 1)[0].strip()
                if judge not in judges:
                    error("R5", number, "Unknown judgement " + judge)
                continue
            called = re.match(r"(?:(" + NAME + r")=)?(" + NAME + r")\(", step)
            if not called or called[2] not in lookup:
                error("R5", number, "Procedure step calls an undeclared action: " + step)
            for name in re.findall(r"\bC\s+(" + NAME + r")", step):
                if name not in check_names:
                    error("R4", number, "Procedure attaches unknown check " + name)
    return {"syntax_ok": syntax_count == 0, "semantic_ok": not errors,
            "ok": not errors, "lines": len(document.lines), "actions": len(actions),
            "types": len(types), "checks": len(checks), "errors": errors, "limitations": LIMITATIONS}


validate = validate_document
