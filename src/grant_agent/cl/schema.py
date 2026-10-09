"""Lossless JSON Schema and MCP bridges for Connected Language.

The normalized schema graph is independent of CL's surface punctuation. Equal
schemas share one declaration; external constraints remain explicit metadata.
"""
from __future__ import annotations

# evolve-helper: skip-repeated-validation
import threading as _evolve_threading
_EVOLVE_VALIDATED = {}
_EVOLVE_VALIDATED_MAX = 4096
_EVOLVE_VALIDATED_LOCK = _evolve_threading.Lock()
def _evolve_once(label, call, *args):
    """Skip a repeated call of a PURE validator on an identical JSON input in this process.

    Purity assumption: the outcome depends only on the JSON value of the arguments, the call
    has no side effects, success returns None and failure raises. Only successes are kept;
    errors and non-None results are never remembered. Bounded LRU of SHA-256 digests.
    """
    import hashlib as _hashlib
    import json as _json
    try:
        payload = _json.dumps([label, args], sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return call(*args)
    key = _hashlib.sha256(payload.encode('utf-8')).digest()
    with _EVOLVE_VALIDATED_LOCK:
        if key in _EVOLVE_VALIDATED:
            _EVOLVE_VALIDATED[key] = _EVOLVE_VALIDATED.pop(key)
            return None
    result = call(*args)
    if result is None:
        with _EVOLVE_VALIDATED_LOCK:
            _EVOLVE_VALIDATED[key] = True
            while len(_EVOLVE_VALIDATED) > _EVOLVE_VALIDATED_MAX:
                del _EVOLVE_VALIDATED[next(iter(_EVOLVE_VALIDATED))]
    return result


from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from typing import Any


class SchemaCompileError(ValueError):
    """A schema cannot be compiled without changing its meaning."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identifier(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
    return clean if clean and not clean[0].isdigit() else "schema_" + clean


def _property_orders(value, path=()):
    """CL parameter order is observable even when JSON object order is not."""
    rows = []
    if isinstance(value, dict):
        if isinstance(value.get("properties"), dict):
            rows.append([list(path), list(value["properties"])])
        for name in sorted(value):
            rows.extend(_property_orders(value[name], (*path, name)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_property_orders(item, (*path, index)))
    return rows


@dataclass
class SchemaGraph:
    """Deduplicated declarations with the original schemas kept losslessly."""

    declarations: dict[str, Any] = field(default_factory=dict)
    _names: dict[str, str] = field(default_factory=dict, repr=False)

    def add(self, schema: Any, preferred_name: str = "root") -> str:
        if not isinstance(schema, (dict, bool)):
            raise SchemaCompileError("A JSON Schema must be an object or boolean")
        try:
            key = _canonical(schema)
        except (TypeError, ValueError) as exc:
            raise SchemaCompileError("Schema is not valid finite JSON") from exc
        if json.loads(key) != schema:
            raise SchemaCompileError("Schema contains values that are not lossless JSON")
        from jsonschema import SchemaError
        from jsonschema.validators import validator_for
        try:
            _evolve_once('validator_for(schema).check_schema', validator_for(schema).check_schema, schema)
        except SchemaError as exc:
            raise SchemaCompileError(f"Invalid JSON Schema: {exc}") from exc
        key += "\n" + _canonical(_property_orders(schema))
        if key in self._names:
            return self._names[key]
        base = _identifier(preferred_name)
        name, suffix = base, 2
        while name in self.declarations:
            name = f"{base}_{suffix}"
            suffix += 1
        self.declarations[name] = deepcopy(schema)
        self._names[key] = name
        return name

    def schema(self, name: str) -> Any:
        try:
            return deepcopy(self.declarations[name])
        except KeyError as exc:
            raise SchemaCompileError(f"Unknown schema declaration: {name}") from exc


def split_top(text: str, separators: str = " ,") -> list[str]:
    """Split CL outside quoted strings and nested constructs."""
    parts, start, depth, quoted, escaped = [], 0, 0, False, False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
            if depth < 0:
                raise SchemaCompileError("Unbalanced CL type")
        elif depth == 0 and char in separators:
            if text[start:index].strip():
                parts.append(text[start:index].strip())
            start = index + 1
    if quoted or depth:
        raise SchemaCompileError("Unclosed CL string or type")
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


_BASES = {
    "str": {"type": "string"}, "int": {"type": "integer"},
    "num": {"type": "number"}, "bool": {"type": "boolean"},
    "null": {"type": "null"}, "any": {},
    "time": {"type": "string", "format": "date-time"},
    "dur": {"type": "string", "format": "duration"},
    "url": {"type": "string", "format": "uri"},
    **{name: {"type": "string", "x-cl": name} for name in ("path", "id", "handle")},
    "word": {"type": "string", "x-cl": "word", "pattern": "^[A-Za-z_][A-Za-z0-9_-]*$"},
    "rect": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4, "x-cl": "rect"},
    "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
    "bytes": {"type": "string", "contentEncoding": "base64"},
}


def normalize_type_expression(expression: str) -> str:
    """Accept canonical-renderer spacing without modifying quoted schema data."""
    return re.sub(r'"(?:\\.|[^"\\])*"|\bstr\s+~', lambda match: match[0] if match[0].startswith('"') else "str~", expression.strip())


def type_to_schema(expression: str, types: dict[str, Any] | None = None, _stack: tuple[str, ...] = ()) -> Any:
    """Compile the normative CL type grammar; reject unknown names."""
    expression = normalize_type_expression(expression)
    if expression.startswith("json:"):
        encoded = json.loads(expression[5:])
        if not isinstance(encoded, str):
            raise SchemaCompileError("json: requires a JSON-quoted schema string")
        schema = json.loads(encoded)
        SchemaGraph().add(schema)
        return schema
    alternatives = split_top(expression, "|")
    if len(alternatives) > 1:
        values = [type_to_schema(item, types, _stack) for item in alternatives]
        if all(set(item) == {"const"} for item in values):
            return {"enum": [item["const"] for item in values]}
        if all(set(item) == {"type"} for item in values):
            return {"type": [item["type"] for item in values]}
        return {"anyOf": values}
    if expression in _BASES:
        return deepcopy(_BASES[expression])
    if expression.startswith("str~"):
        return {"type": "string", "pattern": json.loads(expression[4:])}
    bounded = re.fullmatch(r"(.+)#(-?\d*(?:\.\d+)?\.\.-?\d*(?:\.\d+)?)", expression)
    if bounded:
        schema = type_to_schema(bounded[1], types, _stack)
        lower, upper = bounded[2].split("..", 1)
        prefix = "Length" if schema.get("type") == "string" else "Items" if schema.get("type") == "array" else None
        if prefix is None:
            raise SchemaCompileError("Count bounds require a string or array")
        for key, value in (("min" + prefix, lower), ("max" + prefix, upper)):
            if value:
                schema[key] = int(value)
        return schema
    ranged = re.fullmatch(r"(-?\d*(?:\.\d+)?)\.\.(-?\d*(?:\.\d+)?)", expression)
    if ranged:
        values = [value for value in ranged.groups() if value]
        schema = {"type": "number" if any("." in value for value in values) else "integer"}
        for key, value in zip(("minimum", "maximum"), ranged.groups()):
            if value:
                schema[key] = float(value) if "." in value else int(value)
        return schema
    if expression.startswith("[") and expression.endswith("]"):
        return {"type": "array", "items": type_to_schema(expression[1:-1], types, _stack)}
    if expression.startswith("{") and expression.endswith("}"):
        props, required, opened = {}, [], False
        for token in split_top(expression[1:-1]):
            if token == "..":
                opened = True
                continue
            field, separator, value = token.partition(":")
            if not separator:
                raise SchemaCompileError("CL record fields require name:type")
            hidden = field.startswith("^")
            field = field.lstrip("^")
            optional = field.endswith("?")
            name = field.rstrip("?")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) or name in props:
                raise SchemaCompileError(f"Invalid or duplicate CL field: {name}")
            default = split_top(value, "=")
            if len(default) > 2:
                raise SchemaCompileError("Malformed CL field default")
            item = type_to_schema(default[0], types, _stack)
            if len(default) == 2:
                try:
                    item["default"] = json.loads(default[1])
                except json.JSONDecodeError:
                    item["default"] = default[1]
            if hidden:
                item["x-cl-level"] = 2
            props[name] = item
            if not optional:
                required.append(name)
        result = {"type": "object", "properties": props, "required": required}
        if not opened:
            result["additionalProperties"] = False
        return result
    extended = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.-]*)(\{.*\})", expression)
    if extended:
        return {"allOf": [{"$ref": "#/$defs/" + extended[1]}, type_to_schema(extended[2], types, _stack)]}
    if types and expression in types:
        if expression in _stack:
            raise SchemaCompileError("Recursive named types require the json: schema escape")
        return type_to_schema(types[expression], types, (*_stack, expression))
    try:
        return {"const": json.loads(expression)}
    except json.JSONDecodeError:
        if re.fullmatch(r"[A-Za-z_./][A-Za-z0-9_./-]*", expression):
            return {"const": expression}
        raise SchemaCompileError(f"Unknown CL type: {expression}")


def schema_to_type(schema: Any) -> str:
    """Use compact syntax only when it reconstructs the exact original schema."""
    SchemaGraph().add(schema)
    candidate = None
    for name, value in _BASES.items():
        if value == schema:
            return name
    if isinstance(schema, dict):
        if "const" in schema and set(schema) == {"const"}:
            candidate = _canonical(schema["const"])
        elif "enum" in schema and set(schema) == {"enum"} and len(schema["enum"]) > 1:
            candidate = "|".join(_canonical(item) for item in schema["enum"])
        elif "anyOf" in schema and set(schema) == {"anyOf"}:
            candidate = "|".join(schema_to_type(item) for item in schema["anyOf"])
        elif isinstance(schema.get("type"), list) and set(schema) == {"type"}:
            names = {value["type"]: name for name, value in _BASES.items() if set(value) == {"type"}}
            if all(item in names for item in schema["type"]):
                candidate = "|".join(names[item] for item in schema["type"])
        elif schema.get("type") == "object" and "properties" in schema:
            fields = []
            for name, value in schema["properties"].items():
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
                    break
                item = deepcopy(value)
                hidden = item.pop("x-cl-level", None) == 2
                default = "=" + _canonical(item.pop("default")) if "default" in item else ""
                fields.append(("^" if hidden else "") + name + ("" if name in schema.get("required", []) else "?") + ":" + schema_to_type(item) + default)
            else:
                if "additionalProperties" not in schema:
                    fields.append("..")
                candidate = "{" + " ".join(fields) + "}"
        elif schema.get("type") == "array" and "items" in schema:
            candidate = "[" + schema_to_type(schema["items"]) + "]"
            if "minItems" in schema or "maxItems" in schema:
                candidate += "#" + str(schema.get("minItems", "")) + ".." + str(schema.get("maxItems", ""))
        elif schema.get("type") in ("integer", "number") and ("minimum" in schema or "maximum" in schema):
            candidate = str(schema.get("minimum", "")) + ".." + str(schema.get("maximum", ""))
        elif schema.get("type") == "string":
            if "pattern" in schema:
                candidate = "str~" + _canonical(schema["pattern"])
            elif "minLength" in schema or "maxLength" in schema:
                candidate = "str#" + str(schema.get("minLength", "")) + ".." + str(schema.get("maxLength", ""))
    if candidate is not None:
        try:
            if type_to_schema(candidate) == schema:
                return candidate
        except (SchemaCompileError, ValueError, TypeError):
            pass
    # JSON objects are unordered, but parameter declaration order is observable
    # for positional CL calls. Keep input property order in the escape hatch.
    return "json:" + _canonical(json.dumps(schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _type_declarations(text: str) -> dict[str, str]:
    from .parser import parse_document
    types = {}
    for line in parse_document(text).lines:
        if line.tag == "T":
            match = re.match(r"([A-Za-z_][A-Za-z0-9_.-]*)(.*)", line.body)
            if not match or not match[2].strip() or match[1] in types:
                raise SchemaCompileError("Invalid or duplicate CL type declaration")
            types[match[1]] = match[2].strip()
    return types


def json_schema_to_cl(schema: Any, name: str = "root") -> str:
    name = _identifier(name)
    return f"CL 1\nL schema v1\nT {name} {schema_to_type(schema)}\n"


def cl_to_json_schema(text: str, root: str | None = None) -> Any:
    types = _type_declarations(text)
    if not types:
        raise SchemaCompileError("CL document has no schema type")
    name = root or next(iter(types))
    if name not in types:
        raise SchemaCompileError(f"Unknown schema root: {name}")
    return type_to_schema(types[name], types)


def mcp_to_cl(tool_or_list: Any) -> str:
    """Compile complete MCP rows; archival comments preserve extension metadata."""
    rows = [tool_or_list] if isinstance(tool_or_list, dict) else list(tool_or_list)
    graph, actions, metadata, names = SchemaGraph(), [], {}, set()
    for tool in rows:
        name = tool.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name) or name in names:
            raise SchemaCompileError(f"Invalid or duplicate MCP tool name: {name}")
        names.add(name)
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise SchemaCompileError(f"MCP tool inputSchema must be an object: {name}")
        params = []
        declared = schema.get("properties", {})
        arguments = {**declared, **{key: {} for key in schema.get("required", []) if key not in declared}}
        for key, value in arguments.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
                raise SchemaCompileError(f"Tool argument is not a CL field name: {name}.{key}")
            type_name = graph.add(value, "t" + str(len(graph.declarations) + 1))
            params.append(key + ("" if key in schema.get("required", []) else "?") + ":" + type_name)
        output = graph.add(tool["outputSchema"], "t" + str(len(graph.declarations) + 1)) if "outputSchema" in tool else "any"
        annotations = tool.get("annotations", {})
        mutability = tool.get("mutability_class")
        readonly = annotations.get("readOnlyHint", mutability in {"read", "none"})
        effect = "" if readonly else " !"
        gloss = tool.get("description", "").replace("\r", " ").replace("\n", " ")
        actions.append(f"A {name}({' '.join(params)}) -> {output}{effect}" + (" -- " + gloss if gloss else ""))
        actions.append(f"I {name} reads:tool" if readonly else f"I {name} writes:tool undo:none" + (" ask:none -- authority remains in the existing tool gateway" if effect == " !" else ""))
        # Input object keywords and MCP extensions are data, never authority.
        metadata[name] = {"tool": {key: deepcopy(value) for key, value in tool.items() if key not in {"inputSchema", "outputSchema"}},
                          "input": {key: deepcopy(value) for key, value in schema.items() if key != "properties"},
                          "properties": list(declared) if "properties" in schema else None,
                          "output": "outputSchema" in tool}
    lines = ["CL 1", "L tools v1 -- MCP tool signatures", "-- @mcp " + _canonical(metadata)]
    lines += [f"T {name} {schema_to_type(schema)}" for name, schema in graph.declarations.items()]
    return "\n".join(lines + actions) + "\n"


def cl_to_mcp(text: str) -> list[dict[str, Any]]:
    from .parser import parse_document
    types = _type_declarations(text)
    metadata = {}
    for raw in text.splitlines():
        if raw.startswith("-- @mcp "):
            if metadata:
                raise SchemaCompileError("Duplicate MCP archival metadata")
            metadata = json.loads(raw[len("-- @mcp "):])
    result, seen = [], set()
    for line in parse_document(text).lines:
        if line.tag != "A":
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.-]*)\((.*)\)(?:\s+->\s+(.+?))?(?:\s+([~!]))?", line.body)
        if not match or match[1] in seen:
            raise SchemaCompileError("Invalid or duplicate CL MCP action signature")
        name, parameters, output, effect = match.groups()
        seen.add(name)
        props, required = {}, []
        for param in split_top(parameters):
            key, separator, kind = param.partition(":")
            if not separator or not key:
                raise SchemaCompileError("Invalid CL MCP parameter")
            optional = key.endswith("?")
            key = key.rstrip("?")
            if key in props:
                raise SchemaCompileError("Duplicate CL MCP parameter")
            props[key] = type_to_schema(kind, types)
            if not optional:
                required.append(key)
        original = metadata.get(name)
        if original:
            tool = deepcopy(original["tool"])
            header = deepcopy(original["input"])
            if set(header.get("required", [])) != set(required):
                raise SchemaCompileError(f"Signature disagrees with archival required fields: {name}")
            tool["inputSchema"] = header
            if original["properties"] is not None:
                tool["inputSchema"]["properties"] = {key: props[key] for key in original["properties"]}
            if original["output"]:
                tool["outputSchema"] = type_to_schema(output or "any", types)
        else:
            tool = {"name": name, "description": line.gloss or "", "inputSchema": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
                    "annotations": {"readOnlyHint": effect is None}}
            if effect == "!":
                tool["annotations"]["destructiveHint"] = True
            if output:
                tool["outputSchema"] = type_to_schema(output, types)
        result.append(tool)
    if metadata and set(metadata) != seen:
        raise SchemaCompileError("MCP archival metadata contains missing actions")
    return result
