"""Deterministic Python and TypeScript bindings for Neyvia public schemas.

The generated bindings describe wire data only.  Semantic validation and every
workspace-sensitive decision remain owned by ModuleMarketplace and
ApplicationSurfaceService.
"""

from __future__ import annotations

import hashlib
import keyword
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .application_surface import application_surface_schema
from .proofs_e_sv import enforced


GENERATOR_VERSION = "neyvia.sdk-codegen/v1"
GENERATION_RECEIPT_SCHEMA = "neyvia.sdk-binding-generation/v1"
PYTHON_OUTPUT = Path("src/grant_agent/generated/neyvia_contracts.py")
TYPESCRIPT_OUTPUT = Path("sdk/typescript/src/generated/neyvia-contracts.ts")

_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "const",
        "description",
        "enum",
        "format",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "required",
        "then",
        "title",
        "type",
        "uniqueItems",
    }
)
_SAFE_FORMATS = frozenset({"uri"})
_IDENTIFIER_PARTS = re.compile(r"[^A-Za-z0-9]+")


class LossySchemaError(ValueError):
    """Raised when a schema cannot be represented without weakening it."""

    def __init__(self, pointer: str, keyword: str, reason: str) -> None:
        self.pointer = pointer
        self.keyword = keyword
        self.reason = reason
        super().__init__(f"{pointer}: unsupported {keyword!r}: {reason}")


@dataclass(frozen=True)
class SchemaSource:
    name: str
    root_type: str
    path: Path
    schema: dict[str, Any]
    sha256: str


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_bytes(value: object) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _pointer_child(pointer: str, key: object) -> str:
    encoded = str(key).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{encoded}" if pointer else f"/{encoded}"


def _type_name(*parts: str) -> str:
    words: list[str] = []
    for part in parts:
        words.extend(item for item in _IDENTIFIER_PARTS.split(part) if item)
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if not name or name[0].isdigit():
        raise LossySchemaError("/", "identifier", f"cannot normalize {parts!r}")
    return name


def _python_literal_source(value: object) -> str:
    if value is None or isinstance(value, (str, bool)):
        return repr(value)
    if isinstance(value, int):
        return repr(value)
    raise TypeError(f"unsupported Python literal {value!r}")


def _assert_python_literal(value: object, *, pointer: str, keyword_name: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    raise LossySchemaError(
        pointer,
        keyword_name,
        "Python Literal supports only strings, exact integers, booleans, and null",
    )


def _assert_supported(schema: object, *, pointer: str = "") -> None:
    if not isinstance(schema, dict):
        raise LossySchemaError(pointer or "/", "schema", "must be an object")
    unknown = sorted(set(schema) - _ALLOWED_SCHEMA_KEYS)
    if unknown:
        raise LossySchemaError(
            pointer or "/",
            unknown[0],
            "keyword is outside the portable binding subset",
        )
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in {
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
        "null",
    }:
        raise LossySchemaError(
            _pointer_child(pointer, "type"),
            "type",
            "union and non-JSON types are not supported",
        )
    reference = schema.get("$ref")
    if reference is not None and not re.fullmatch(r"#/\$defs/[A-Za-z0-9_.-]+", str(reference)):
        raise LossySchemaError(
            _pointer_child(pointer, "$ref"),
            "$ref",
            "only local $defs references are supported",
        )
    fmt = schema.get("format")
    if fmt is not None and fmt not in _SAFE_FORMATS:
        raise LossySchemaError(
            _pointer_child(pointer, "format"),
            "format",
            f"{fmt!r} has no portable binding representation",
        )
    if "const" in schema:
        _assert_python_literal(
            schema["const"],
            pointer=_pointer_child(pointer, "const"),
            keyword_name="const",
        )
    if "enum" in schema:
        for index, value in enumerate(schema["enum"]):
            _assert_python_literal(
                value,
                pointer=_pointer_child(_pointer_child(pointer, "enum"), index),
                keyword_name="enum",
            )
    for constraint_name in ("minimum", "maximum", "minItems", "maxItems"):
        value = schema.get(constraint_name)
        if isinstance(value, int) and abs(value) > 9_007_199_254_740_991:
            raise LossySchemaError(
                _pointer_child(pointer, constraint_name),
                constraint_name,
                "integer exceeds the exact JavaScript range",
            )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise LossySchemaError(
            _pointer_child(pointer, "properties"),
            "properties",
            "must be an object",
        )
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise LossySchemaError(
            _pointer_child(pointer, "required"),
            "required",
            "must be an array of property names",
        )
    missing = sorted(set(required) - set(properties))
    if missing:
        raise LossySchemaError(
            _pointer_child(pointer, "required"),
            "required",
            f"references undeclared property {missing[0]!r}",
        )
    if properties and schema.get("additionalProperties", True) is not False:
        raise LossySchemaError(
            _pointer_child(pointer, "additionalProperties"),
            "additionalProperties",
            "typed objects must be explicitly closed",
        )
    if isinstance(schema.get("additionalProperties"), dict):
        raise LossySchemaError(
            _pointer_child(pointer, "additionalProperties"),
            "additionalProperties",
            "mixed named and map properties are not supported",
        )
    if schema.get("type") == "array" and "items" not in schema:
        raise LossySchemaError(
            _pointer_child(pointer, "items"),
            "items",
            "typed arrays must declare one item schema",
        )
    all_of = schema.get("allOf", [])
    if not isinstance(all_of, list):
        raise LossySchemaError(
            _pointer_child(pointer, "allOf"), "allOf", "must be an array"
        )
    for index, branch in enumerate(all_of):
        branch_pointer = _pointer_child(_pointer_child(pointer, "allOf"), index)
        if not isinstance(branch, dict) or set(branch) != {"if", "then"}:
            raise LossySchemaError(
                branch_pointer,
                "allOf",
                "only discriminated required-field conditionals are supported",
            )
        condition = branch.get("if")
        consequence = branch.get("then")
        if (
            not isinstance(condition, dict)
            or set(condition) != {"properties"}
            or not isinstance(condition.get("properties"), dict)
            or len(condition["properties"]) != 1
            or not isinstance(consequence, dict)
            or set(consequence) != {"required"}
        ):
            raise LossySchemaError(
                branch_pointer,
                "if/then",
                "conditional must select one const and add required fields",
            )
        discriminator_schema = next(iter(condition["properties"].values()))
        if not isinstance(discriminator_schema, dict) or set(discriminator_schema) != {"const"}:
            raise LossySchemaError(
                branch_pointer,
                "if",
                "discriminator must be a single const",
            )
        conditional_required = consequence.get("required")
        if (
            not isinstance(conditional_required, list)
            or any(item not in properties for item in conditional_required)
        ):
            raise LossySchemaError(
                branch_pointer,
                "then",
                "conditional required fields must be declared properties",
            )
    for key, child in properties.items():
        if not key.isidentifier() or keyword.iskeyword(key):
            raise LossySchemaError(
                _pointer_child(_pointer_child(pointer, "properties"), key),
                "identifier",
                "Python wire fields must already be valid non-keyword identifiers",
            )
        _assert_supported(child, pointer=_pointer_child(_pointer_child(pointer, "properties"), key))
    item_schema = schema.get("items")
    if item_schema is not None:
        if not isinstance(item_schema, dict):
            raise LossySchemaError(
                _pointer_child(pointer, "items"),
                "items",
                "tuple arrays are not supported",
            )
        _assert_supported(item_schema, pointer=_pointer_child(pointer, "items"))
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        raise LossySchemaError(
            _pointer_child(pointer, "$defs"), "$defs", "must be an object"
        )
    for key, child in definitions.items():
        _assert_supported(child, pointer=_pointer_child(_pointer_child(pointer, "$defs"), key))


def load_schema_sources(root: str | Path) -> tuple[SchemaSource, ...]:
    project_root = Path(root).resolve()
    specs = (
        (
            "moduleManifest",
            "NeyviaModuleManifest",
            project_root / "config" / "neyvia_module_manifest_schema.json",
        ),
        (
            "applicationSurface",
            "NeyviaApplicationSurface",
            project_root / "config" / "neyvia_application_surface_schema.json",
        ),
    )
    sources: list[SchemaSource] = []
    for name, root_type, path in specs:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LossySchemaError("/", "source", f"cannot read {path.name}: {exc}") from exc
        Draft202012Validator.check_schema(payload)
        _assert_supported(payload)
        sources.append(
            SchemaSource(
                name=name,
                root_type=root_type,
                path=path,
                schema=payload,
                sha256=hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
            )
        )
    runtime_surface_version = (
        (application_surface_schema().get("properties") or {})
        .get("schema_version", {})
        .get("const")
    )
    persisted_surface_version = (
        (sources[1].schema.get("properties") or {})
        .get("schema_version", {})
        .get("const")
    )
    if runtime_surface_version != persisted_surface_version:
        raise LossySchemaError(
            "/applicationSurface/properties/schema_version/const",
            "authority",
            "runtime and persisted application-surface versions diverge",
        )
    return tuple(sources)


def validate_portable_schema(schema: dict[str, Any]) -> None:
    """Reject constructs that either target language would have to weaken."""

    Draft202012Validator.check_schema(schema)
    _assert_supported(schema)


class _Renderer:
    def __init__(self, source: SchemaSource) -> None:
        self.source = source
        self.prefix = source.root_type
        self.definitions = dict(source.schema.get("$defs") or {})
        self.objects: dict[str, dict[str, Any]] = {}
        self.aliases: dict[str, dict[str, Any]] = {}
        self._names_by_pointer: dict[str, str] = {}
        self._pointers_by_name: dict[str, str] = {}
        self._register_named(self.source.root_type, self.source.schema, "/")
        for key in sorted(self.definitions):
            self._register_named(
                _type_name(self.prefix, key),
                self.definitions[key],
                f"/$defs/{key}",
            )

    def _register_named(self, name: str, schema: dict[str, Any], pointer: str) -> None:
        previous = self._names_by_pointer.get(pointer)
        if previous and previous != name:
            raise LossySchemaError(pointer, "identifier", "normalized name collision")
        previous_pointer = self._pointers_by_name.get(name)
        if previous_pointer and previous_pointer != pointer:
            raise LossySchemaError(
                pointer,
                "identifier",
                f"normalizes to {name!r}, already used by {previous_pointer}",
            )
        self._names_by_pointer[pointer] = name
        self._pointers_by_name[name] = pointer
        if schema.get("type") == "object" and schema.get("properties"):
            self.objects[name] = schema
            for key, child in sorted(schema["properties"].items()):
                self._register_nested(child, name, key, f"{pointer}/properties/{key}")
        else:
            self.aliases[name] = schema

    def _register_nested(
        self,
        schema: dict[str, Any],
        parent: str,
        key: str,
        pointer: str,
    ) -> None:
        if "$ref" in schema:
            return
        candidate = schema
        suffix = key
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            candidate = schema["items"]
            suffix = f"{key}Item"
        if candidate.get("type") == "object" and candidate.get("properties"):
            name = _type_name(parent, suffix)
            self._register_named(name, candidate, pointer)

    def ref_name(self, reference: str) -> str:
        key = reference.rsplit("/", 1)[-1]
        if key not in self.definitions:
            raise LossySchemaError(reference, "$ref", "definition does not exist")
        return _type_name(self.prefix, key)

    def nested_name(self, parent: str, key: str, schema: dict[str, Any]) -> str:
        if schema.get("type") == "array":
            return _type_name(parent, f"{key}Item")
        return _type_name(parent, key)

    def py_type(self, schema: dict[str, Any], parent: str, key: str = "") -> str:
        if "$ref" in schema:
            return self.ref_name(str(schema["$ref"]))
        if "const" in schema:
            return f"Literal[{_python_literal_source(schema['const'])}]"
        if "enum" in schema:
            return "Literal[" + ", ".join(
                _python_literal_source(item) for item in schema["enum"]
            ) + "]"
        schema_type = schema.get("type")
        if schema_type == "string":
            return "str"
        if schema_type == "integer":
            return "int"
        if schema_type == "number":
            return "int | float"
        if schema_type == "boolean":
            return "bool"
        if schema_type == "null":
            return "None"
        if schema_type == "array":
            item_schema = schema["items"]
            item_type = (
                _type_name(parent, f"{key}Item")
                if (
                    "$ref" not in item_schema
                    and item_schema.get("type") == "object"
                    and item_schema.get("properties")
                )
                else self.py_type(item_schema, parent, key)
            )
            return f"list[{item_type}]"
        if schema_type == "object" and schema.get("properties"):
            return self.nested_name(parent, key, schema)
        if not schema:
            return "JsonValue"
        if schema_type == "object":
            return (
                "EmptyJsonObject"
                if schema.get("additionalProperties") is False
                else "JsonObject"
            )
        raise LossySchemaError("/", "type", f"cannot render {schema_type!r}")

    def ts_type(self, schema: dict[str, Any], parent: str, key: str = "") -> str:
        if "$ref" in schema:
            return self.ref_name(str(schema["$ref"]))
        if "const" in schema:
            return json.dumps(schema["const"], ensure_ascii=False)
        if "enum" in schema:
            return " | ".join(json.dumps(item, ensure_ascii=False) for item in schema["enum"])
        schema_type = schema.get("type")
        if schema_type == "string":
            return "string"
        if schema_type in {"integer", "number"}:
            return "number"
        if schema_type == "boolean":
            return "boolean"
        if schema_type == "null":
            return "null"
        if schema_type == "array":
            item_schema = schema["items"]
            item_type = (
                _type_name(parent, f"{key}Item")
                if (
                    "$ref" not in item_schema
                    and item_schema.get("type") == "object"
                    and item_schema.get("properties")
                )
                else self.ts_type(item_schema, parent, key)
            )
            return f"Array<{item_type}>"
        if schema_type == "object" and schema.get("properties"):
            return self.nested_name(parent, key, schema)
        if not schema:
            return "JsonValue"
        if schema_type == "object":
            return (
                "EmptyJsonObject"
                if schema.get("additionalProperties") is False
                else "JsonObject"
            )
        raise LossySchemaError("/", "type", f"cannot render {schema_type!r}")

    @staticmethod
    def _conditional_variants(schema: dict[str, Any]) -> list[tuple[str, object, set[str]]]:
        variants: list[tuple[str, object, set[str]]] = []
        for branch in schema.get("allOf") or []:
            condition_properties = branch["if"]["properties"]
            discriminator, discriminator_schema = next(iter(condition_properties.items()))
            variants.append(
                (
                    discriminator,
                    discriminator_schema["const"],
                    set(branch["then"]["required"]),
                )
            )
        return variants

    def render_python_declarations(self) -> list[str]:
        lines: list[str] = []
        for name in sorted(self.objects):
            schema = self.objects[name]
            variants = self._conditional_variants(schema)
            if variants:
                discriminator_names = {item[0] for item in variants}
                discriminator_values = {item[1] for item in variants}
                if len(discriminator_names) != 1:
                    raise LossySchemaError("/", "allOf", "multiple discriminators are unsupported")
                discriminator = next(iter(discriminator_names))
                declared = set(schema["properties"][discriminator].get("enum") or [])
                if declared != discriminator_values:
                    raise LossySchemaError(
                        "/", "allOf", "conditional variants must cover the discriminator enum"
                    )
                variant_names: list[str] = []
                for _, value, extra_required in variants:
                    variant_name = _type_name(name, str(value))
                    variant_names.append(variant_name)
                    lines.append(f"class {variant_name}(TypedDict, total=False):")
                    required = set(schema.get("required") or []) | extra_required
                    for key, child in sorted(schema["properties"].items()):
                        child_type = (
                            f"Literal[{_python_literal_source(value)}]"
                            if key == discriminator
                            else self.py_type(child, name, key)
                        )
                        marker = "Required" if key in required else "NotRequired"
                        lines.append(f"    {key}: {marker}[{child_type}]")
                    lines.append("")
                lines.append(f"{name}: TypeAlias = {' | '.join(variant_names)}")
                lines.append("")
                continue
            lines.append(f"class {name}(TypedDict, total=False):")
            required = set(schema.get("required") or [])
            for key, child in sorted(schema["properties"].items()):
                marker = "Required" if key in required else "NotRequired"
                lines.append(f"    {key}: {marker}[{self.py_type(child, name, key)}]")
            lines.append("")
        ordered_aliases: list[str] = []
        visited: set[str] = set()

        def visit_alias(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            schema = self.aliases[name]

            def visit_references(value: object) -> None:
                if isinstance(value, dict):
                    reference = value.get("$ref")
                    if reference:
                        dependency = self.ref_name(str(reference))
                        if dependency in self.aliases:
                            visit_alias(dependency)
                    for child in value.values():
                        visit_references(child)
                elif isinstance(value, list):
                    for child in value:
                        visit_references(child)

            visit_references(schema)
            ordered_aliases.append(name)

        for alias_name in sorted(self.aliases):
            visit_alias(alias_name)
        for name in ordered_aliases:
            lines.append(f"{name}: TypeAlias = {self.py_type(self.aliases[name], name)}")
        return lines

    def render_typescript_declarations(self) -> list[str]:
        lines: list[str] = []
        for name in sorted(self.objects):
            schema = self.objects[name]
            variants = self._conditional_variants(schema)
            if variants:
                variant_names: list[str] = []
                for discriminator, value, extra_required in variants:
                    variant_name = _type_name(name, str(value))
                    variant_names.append(variant_name)
                    lines.append(f"export interface {variant_name} {{")
                    required = set(schema.get("required") or []) | extra_required
                    for key, child in sorted(schema["properties"].items()):
                        optional = "" if key in required else "?"
                        child_type = (
                            json.dumps(value, ensure_ascii=False)
                            if key == discriminator
                            else self.ts_type(child, name, key)
                        )
                        lines.append(f"  {json.dumps(key)}{optional}: {child_type};")
                    lines.append("}")
                    lines.append("")
                lines.append(f"export type {name} = {' | '.join(variant_names)};")
                lines.append("")
                continue
            lines.append(f"export interface {name} {{")
            required = set(schema.get("required") or [])
            for key, child in sorted(schema["properties"].items()):
                optional = "" if key in required else "?"
                lines.append(
                    f"  {json.dumps(key)}{optional}: {self.ts_type(child, name, key)};"
                )
            lines.append("}")
            lines.append("")
        for name in sorted(self.aliases):
            lines.append(f"export type {name} = {self.ts_type(self.aliases[name], name)};")
        return lines


def render_python(sources: tuple[SchemaSource, ...]) -> bytes:
    lines = [
        "# Generated by grant_agent.sdk_codegen; DO NOT EDIT.",
        f"# Generator: {GENERATOR_VERSION}",
        "from __future__ import annotations",
        "",
        "import json",
        "",
        "from typing import Literal, Never, NotRequired, Required, TypeAlias, TypedDict",
        "",
        "JsonScalar: TypeAlias = str | int | float | bool | None",
        'JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]',
        'JsonObject: TypeAlias = dict[str, "JsonValue"]',
        "EmptyJsonObject: TypeAlias = dict[Never, Never]",
        "",
    ]
    for source in sources:
        lines.extend(_Renderer(source).render_python_declarations())
        lines.append("")
    lines.append("SCHEMA_SHA256 = {")
    for source in sources:
        lines.append(f"    {source.name!r}: {source.sha256!r},")
    lines.extend(["}", "", "SCHEMAS: dict[str, JsonObject] = {"])
    for source in sources:
        schema_text = _canonical_json(source.schema)
        lines.append(f"    {source.name!r}: json.loads({schema_text!r}),")
    lines.extend(["}", ""])
    return "\n".join(lines).encode("utf-8")


def render_typescript(sources: tuple[SchemaSource, ...]) -> bytes:
    lines = [
        "// Generated by grant_agent.sdk_codegen; DO NOT EDIT.",
        f"// Generator: {GENERATOR_VERSION}",
        "",
        "export type JsonScalar = string | number | boolean | null;",
        "export type JsonValue = JsonScalar | Array<JsonValue> | { [key: string]: JsonValue };",
        "export type JsonObject = { [key: string]: JsonValue };",
        "export type EmptyJsonObject = Record<string, never>;",
        "",
    ]
    for source in sources:
        lines.extend(_Renderer(source).render_typescript_declarations())
        lines.append("")
    lines.append("export const SCHEMA_SHA256 = {")
    for source in sources:
        lines.append(f"  {json.dumps(source.name)}: {json.dumps(source.sha256)},")
    lines.extend(["} as const;", "", "export const SCHEMAS = {"])
    for source in sources:
        schema_text = json.dumps(source.schema, ensure_ascii=False, sort_keys=True, indent=2)
        indented = "\n".join(f"  {line}" for line in schema_text.splitlines())
        lines.append(f"  {json.dumps(source.name)}: {indented.strip()},")
    lines.extend(["} as const;", ""])
    return "\n".join(lines).encode("utf-8")


@enforced("sv.sdk.bindings")
def generated_bindings(root: str | Path) -> dict[Path, bytes]:
    sources = load_schema_sources(root)
    return {
        PYTHON_OUTPUT: render_python(sources),
        TYPESCRIPT_OUTPUT: render_typescript(sources),
    }


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@enforced("sv.sdk.generation")
def generate_sdk_bindings(root: str | Path, *, check: bool = False) -> dict[str, Any]:
    project_root = Path(root).resolve()
    outputs = generated_bindings(project_root)
    rows: list[dict[str, Any]] = []
    matches = True
    for relative_path, content in sorted(outputs.items(), key=lambda item: item[0].as_posix()):
        target = project_root / relative_path
        current = target.read_bytes() if target.is_file() else None
        matched = current == content
        if not check:
            _atomic_write_bytes(target, content)
            matched = target.read_bytes() == content
        matches = matches and matched
        rows.append(
            {
                "path": relative_path.as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "matched": matched,
            }
        )
    sources = load_schema_sources(project_root)
    return {
        "schema": GENERATION_RECEIPT_SCHEMA,
        "generatorVersion": GENERATOR_VERSION,
        "check": check,
        "ok": matches,
        "sources": [
            {
                "name": source.name,
                "path": source.path.relative_to(project_root).as_posix(),
                "sha256": source.sha256,
            }
            for source in sources
        ],
        "outputs": rows,
    }
