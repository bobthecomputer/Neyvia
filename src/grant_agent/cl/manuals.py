"""Authored CL manuals compile to the existing safe, typed manual runner.

Each record has editable archival metadata, not a whole-document opaque blob.
Its visible CL projection must agree with that record before compilation. This
keeps bindings, conditional branches and external schema constraints lossless.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import re
from typing import Any

from .schema import SchemaGraph, SchemaCompileError, _canonical, _type_declarations, schema_to_type, type_to_schema


def _schema_literal_order(text):
    """JSON Schema object keys are unordered; all values remain exact."""
    def canonical(match):
        schema = json.loads(json.loads(match.group(1)))
        return 'json:' + json.dumps(_canonical(schema), ensure_ascii=False)
    return re.sub(r'json:("(?:[^"\\]|\\.)*")', canonical, text)


@lru_cache(maxsize=1)
def _native_metadata() -> dict:
    from pathlib import Path
    from ..native_tools import NativeToolRegistry
    registry = NativeToolRegistry(Path(__file__).resolve().parents[3] / ".agent_control/cl/metadata-runtime")
    return {name: {"mutability_class": spec.mutability_class} for name, spec in registry._specs.items()}


def _readonly(row: dict, metadata: dict) -> bool:
    name = row["tool"]
    if name in {"neyvia.notes.write", "neyvia.notes.pin", "neyvia.notes.folder", "neyvia.notes.open"}:
        return False
    effect = row["effect"].strip()
    if re.match(r"(?:Persist|Write|Create|Save|Delete|Remove|Append|Replace|Move|Rename|Start|Run|Execute|Launch|Open|Pin|Set|Update|Enable|Disable|Cancel|Stop|Restore|Apply|Bind|Send|Capture|Build)\b", effect, re.I):
        return False
    return metadata.get(name, {}).get("mutability_class") in {"read", "none"}


def _value(value: Any, saved: str = "") -> str:
    if isinstance(value, dict) and set(value) in ({"$input"}, {"$path"}):
        return str(next(iter(value.values())))
    if isinstance(value, dict) and set(value) == {"$result"}:
        reference = value["$result"]
        return "result" + reference[len(saved):] if saved and (reference == saved or reference.startswith(saved + ".")) else reference
    if isinstance(value, dict):
        return "{" + " ".join(key + ":" + _value(value[key], saved) for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + " ".join(_value(item, saved) for item in value) + "]"
    return _canonical(value)


def _call(tool: str, arguments: dict, saved: str = "") -> str:
    return tool + "(" + " ".join(key + ":" + _value(arguments[key], saved) for key in sorted(arguments)) + ")"


def _params(schema: dict, render_type=schema_to_type) -> str:
    fields = []
    properties = schema.get("properties", {})
    properties = {**properties, **{key: {} for key in schema.get("required", []) if key not in properties}}
    for name, value in properties.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
            raise SchemaCompileError("Manual parameter is not a CL field name: " + name)
        fields.append(name + ("" if name in schema.get("required", []) else "?") + ":" + render_type(value))
    return " ".join(fields)


def _check_expr(row: dict, saved: str = "") -> str:
    rule = row["expect"]
    path = rule["path"]
    observer = _call(row["tool"], row["args"], saved)
    if isinstance(path, list) and any(not isinstance(item, (str, int)) for item in path):
        selected = observer + ''.join('[' + _value(item, saved) + ']' for item in path)
        if rule['op'] == 'schema':
            return 'matches(' + selected + ',' + _value(rule['schema'], saved) + ')'
        return selected + ('==' if rule['op'] == 'eq' else ' has ') + _value(rule['value'], saved)
    path = ".".join(str(item) for item in path) if isinstance(path, list) else path
    if rule["op"] == "exists":
        if not path:
            return observer + "!=null"
        parent, _, key = path.rpartition(".")
        return observer + ("." + parent if parent else "") + " has " + _canonical(key)
    selected = observer + ("." + path if path else "")
    if rule["op"] == "schema":
        return 'matches(' + selected + ',' + _value(rule['schema'], saved) + ')'
    return selected + ("==" if rule["op"] == "eq" else " has ") + _value(rule["value"], saved)


def _record_lines(section: str, key: str, row: Any, chapter: dict, schemas: dict, layer: str, metadata: dict, render_type=schema_to_type) -> list[str]:
    if section == "state":
        return ["S " + layer + "." + key + ":" + render_type(row["shape"]) + " = " + _call(row["tool"], row["args"])]
    if section == "actions":
        name = row["tool"]
        readonly = _readonly(row, metadata)
        # Existing manuals sometimes claim reversibility without an inverse.
        # Keep the original hint archived, but never advertise automatic undo.
        effect = "" if readonly else " !"
        lines = ["A " + name + "(" + _params(schemas[row["schema"]], render_type) + ") -> " + render_type(row["returns"]) + effect + " -- " + row["effect"].replace("\n", " "),
                 "I " + name + (" reads:" if readonly else " writes:") + _canonical(row["effect"]) + ("" if readonly else " undo:none ask:none") + " -- " + row["pre"].replace("\n", " ")]
        found = set()
        for procedure in chapter["procedures"].values():
            for step in procedure["steps"]:
                if step.get("action") == key and step.get("check"):
                    check = step["check"]
                    binding = (check, step["save"])
                    if binding not in found:
                        found.add(binding)
                        lines.append("C " + name + " " + check + ": " + _check_expr(chapter["checks"][check], step["save"]))
        if not found:
            lines.append("Q verify-" + key.replace(".", "-") + " " + _canonical("No authored observer check is bound to " + name) + " -> ask operator blocks:" + name)
        return lines
    if section == "checks":
        # Original standalone checks remain named and executable in the runner.
        lines = ["C " + row["tool"] + " " + key + ": " + _check_expr(row)]
        return lines
    if section == "procedures":
        steps = []
        for step in row["steps"]:
            if "judge" in step:
                options = [item.get("when", {}).get("option") for item in row["steps"] if item.get("when", {}).get("judge") == step["judge"]]
                option = next((item for item in options if item), None)
                steps.append("J " + step["judge"] + ("=" + option if option else ""))
            else:
                action = chapter["actions"][step["action"]]
                part = step["save"] + "=" + _call(action["tool"], step["args"])
                if step.get("check"):
                    part += " C " + step["check"]
                steps.append(part)
        return ["P " + key + "(" + _params(row["inputs"], render_type) + "): " + "; ".join(steps) + " -- " + row["goal"].replace("\n", " "),
                "V P " + key + ' -> script why:"typed manual runner; stops at every judgement"']
    if section == "judge":
        options = "|".join(row["options"])
        head = "J " + key + " " + options + ": " + _canonical(row["question"]) + " -- " + row["constraints"].replace("\n", " ")
        if row.get("kind", "human") == "model":
            # An autonomous critic may answer, but only against current evidence (see judgment_evidence).
            return [head, "V J " + key + " -> model:large evidence:" + ",".join(row["evidence"]) + ' why:"model judgment bound to current evidence"']
        return [head, "V J " + key + ' -> human:operator why:"explicit choice required"']
    if section == "pitfalls":
        return ["X " + row["failure"].replace("\n", " ") + " -> " + row["recovery"].replace("\n", " ")]
    if section == "frontier":
        return ["F " + row.replace("\n", " ")]
    if section == "guidance":
        return ["M " + layer + " " + _canonical(row) + ' src:"authored manual" state:verified']
    raise SchemaCompileError("Unknown manual section: " + section)


def render_chapter(chapter: dict, schemas: dict, layer: str = "manual", level: int = 2, tool_metadata: dict | None = None, *, source_version: str = "1.0") -> str:
    from .parser import filter_level, parse_document, render_document
    lines = ["CL 1", "L " + layer + " v1 -- " + chapter["title"].replace("\n", " ")]
    metadata = _native_metadata() if tool_metadata is None else tool_metadata
    graph = SchemaGraph()
    def render_type(schema):
        expression = schema_to_type(schema)
        if not expression.startswith(("{", "[", "json:")) and len(expression) < 20:
            return expression
        return graph.add(schema, "t" + str(len(graph.declarations) + 1))
    for section in ("state", "actions", "checks", "procedures", "judge", "pitfalls", "frontier", "guidance"):
        values = chapter[section]
        for key, row in (values.items() if isinstance(values, dict) else enumerate(values)):
            projected = _record_lines(section, str(key), row, chapter, schemas, layer, metadata, render_type)
            if source_version == "1.1":
                projected = ["F " + line[2:] if line.startswith("Q ") else line for line in projected if not line.startswith("I ")]
            lines += projected
    lines[2:2] = ["T " + name + " " + schema_to_type(schema) for name, schema in graph.declarations.items()]
    return filter_level(render_document(parse_document("\n".join(lines) + "\n")), level)


def manual_to_cl(data: dict, tool_metadata: dict | None = None) -> str:
    from ..manual_contracts import validate_structure
    from .parser import parse_document, render_document
    validate_structure(data)
    metadata = _native_metadata() if tool_metadata is None else tool_metadata
    graph = SchemaGraph()
    aliases = {name: graph.add(schema, "t" + str(len(graph.declarations) + 1)) for name, schema in data["schemas"].items()}
    def pack(value):
        if isinstance(value, list):
            return [pack(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {key: {"$cl_type": graph.add(item, "t" + str(len(graph.declarations) + 1))} if key in {"inputs", "shape", "returns"} else pack(item) for key, item in value.items()}
    packed = [(chapter_name, section, str(key), pack(row)) for chapter_name, chapter in data["chapters"].items()
              for section in ("state", "actions", "checks", "procedures", "judge", "pitfalls", "frontier", "guidance")
              for key, row in (chapter[section].items() if isinstance(chapter[section], dict) else enumerate(chapter[section]))]
    header = {"clVersion": "1.1", "schema": data["schema"], "id": data["id"], "kind": data["kind"], "schemas": aliases,
              "chapters": {name: {"title": row["title"]} for name, row in data["chapters"].items()},
              "tool_metadata": {row["tool"]: metadata.get(row["tool"], {}) for chapter in data["chapters"].values() for row in chapter["actions"].values()}}
    if "proofs" in data:
        header["proofs"] = {key: deepcopy(value) for key, value in data["proofs"].items() if key != "contracts"}
    lines = ["CL 1", "L " + data["id"] + " v1 -- Authored executable manual", "-- @manual " + _canonical(header)]
    lines += ["-- @proof " + _canonical(contract) for contract in data.get("proofs", {}).get("contracts", [])]
    lines += ["T " + name + " " + schema_to_type(schema) for name, schema in graph.declarations.items()]
    current = None
    for chapter_name, section, key, row in packed:
        chapter = data["chapters"][chapter_name]
        if chapter_name != current:
            current = chapter_name
            lines.append("L " + data["id"] + "." + chapter_name + " v1 -- " + chapter["title"].replace("\n", " "))
        lines.append("-- @record " + _canonical({"chapter": chapter_name, "section": section, "key": key, "data": row}))
        original = chapter[section][key] if isinstance(chapter[section], dict) else chapter[section][int(key)]
        lines += _source_lines(section, key, original, chapter, data["schemas"], data["id"], metadata, version="1.1")
    return render_document(parse_document("\n".join(lines) + "\n"))


def _source_lines(section, key, row, chapter, schemas, layer, metadata, *, version):
    """Keep archival guards lossless while reserving awareness for the 1.1 host."""
    lines = _record_lines(section, key, row, chapter, schemas, layer, metadata)
    if version != "1.1":
        return lines
    result = []
    for line in lines:
        if line.startswith("I "):
            continue  # effects and preconditions remain in the typed record
        if line.startswith("Q "):
            result.append("F " + line[2:])
        else:
            result.append(line)
    return result


def cl_to_manual(text: str) -> dict:
    from ..manual_contracts import validate_structure
    from .parser import parse_document, render_document
    document = parse_document(text)
    types = _type_declarations(text)
    header, records, projections, proofs = None, [], [], []
    for line in document.lines:
        if line.tag == "--" and line.body.startswith("@manual "):
            if header is not None:
                raise SchemaCompileError("Duplicate manual header")
            header = json.loads(line.body[8:])
        elif line.tag == "--" and line.body.startswith("@proof "):
            proofs.append(json.loads(line.body[7:]))
        elif line.tag == "--" and line.body.startswith("@record "):
            records.append(json.loads(line.body[8:]))
            projections.append([])
        elif records and line.tag not in {"--", "L", "T"}:
            projections[-1].append(line)
    if not header:
        raise SchemaCompileError("Authored CL manual has no metadata header")
    version = header.get("clVersion", "1.0")
    if version not in {"1.0", "1.1"}:
        raise SchemaCompileError("Unsupported authored manual CL version")
    if version == "1.1" and any(line.tag in {"I", "K", "Q"} for line in document.lines):
        raise SchemaCompileError("CL 1.1 manual awareness must be host-generated")
    def unpack(value):
        if isinstance(value, dict) and set(value) == {"$cl_type"}:
            if value["$cl_type"] not in types:
                raise SchemaCompileError("Manual references an unknown type")
            return type_to_schema(types[value["$cl_type"]], types)
        if isinstance(value, dict):
            return {key: unpack(item) for key, item in value.items()}
        if isinstance(value, list):
            return [unpack(item) for item in value]
        return value
    data = {key: deepcopy(header[key]) for key in ("schema", "id", "kind")}
    if "proofs" in header:
        if "contracts" in header["proofs"]:
            raise SchemaCompileError("Proof contracts must be individual authored @proof records")
        identities = [row.get("id") for row in proofs]
        if any(not isinstance(identity, str) or not identity for identity in identities) or len(set(identities)) != len(identities):
            raise SchemaCompileError("Proof contract identities must be nonempty and unique")
        data["proofs"] = {**deepcopy(header["proofs"]), "contracts": proofs}
    elif proofs:
        raise SchemaCompileError("Authored proof records require proof metadata")
    data["schemas"] = {name: type_to_schema(types[type_name], types) for name, type_name in header["schemas"].items()}
    data["chapters"] = {name: {"title": row["title"], **{section: [] if section in {"pitfalls", "frontier", "guidance"} else {} for section in ("state", "actions", "checks", "procedures", "judge", "pitfalls", "frontier", "guidance")}} for name, row in header["chapters"].items()}
    seen = set()
    for record in records:
        identity = (record["chapter"], record["section"], record["key"])
        if identity in seen:
            raise SchemaCompileError("Duplicate authored manual record")
        seen.add(identity)
        target = data["chapters"][record["chapter"]][record["section"]]
        if isinstance(target, list):
            if int(record["key"]) != len(target):
                raise SchemaCompileError("Manual list records must be contiguous")
            target.append(unpack(record["data"]))
        else:
            target[record["key"]] = unpack(record["data"])
    validate_structure(data)
    for record, actual in zip(records, projections):
        chapter = data["chapters"][record["chapter"]]
        target = chapter[record["section"]]
        row = target[int(record["key"])] if isinstance(target, list) else target[record["key"]]
        expected = _source_lines(record["section"], record["key"], row, chapter, data["schemas"], data["id"], header["tool_metadata"], version=version)
        expected_text = render_document(parse_document("\n".join(expected) + "\n"))
        from .parser import Document
        actual_text = render_document(Document(actual, pragma=False))
        if _schema_literal_order(expected_text) != _schema_literal_order(actual_text):
            raise SchemaCompileError("Visible CL disagrees with executable record: " + ".".join((record["chapter"], record["section"], record["key"])))
    return data
