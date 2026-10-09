"""Progressive tool discovery: search → describe → call (schemas off by default)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ProgressiveToolSpec:
    name: str
    description: str
    title: str = ""
    category: str = "general"
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    availability_reason: str = ""


class ProgressiveToolSurface:
    """Hot-path discovery that never dumps full schemas unless describe() is called."""

    def __init__(self, specs: list[ProgressiveToolSpec] | None = None) -> None:
        self._specs: dict[str, ProgressiveToolSpec] = {
            spec.name: spec for spec in (specs or [])
        }
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(
        self,
        spec: ProgressiveToolSpec,
        handler: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._specs[spec.name] = spec
        if handler is not None:
            self._handlers[spec.name] = handler

    def list_tools(
        self,
        *,
        include_schemas: bool = False,
        include_unavailable: bool = True,
    ) -> list[dict[str, Any]]:
        del include_unavailable  # catalog is local/static in this surface
        rows: list[dict[str, Any]] = []
        for spec in sorted(self._specs.values(), key=lambda item: item.name):
            row: dict[str, Any] = {
                "name": spec.name,
                "title": spec.title or spec.name,
                "description": spec.description,
                "category": spec.category,
                "aliases": list(spec.aliases),
                "tags": list(spec.tags),
                "available": bool(spec.available),
                "availabilityReason": spec.availability_reason,
            }
            if include_schemas:
                row["inputSchema"] = dict(spec.input_schema or {})
                row["outputSchema"] = dict(spec.output_schema or {})
            if spec.annotations:
                row["annotations"] = dict(spec.annotations)
            if spec.permissions:
                row["permissions"] = list(spec.permissions)
            if spec.provenance:
                row["provenance"] = dict(spec.provenance)
            rows.append(row)
        from .proofs_a_control import check_tool_discovery
        check_tool_discovery(self._specs, rows, include_schemas)
        return rows

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        terms = {term for term in re.findall(r"[a-z0-9]+", str(query).lower()) if len(term) > 1}
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in self.list_tools(include_schemas=False):
            haystack = " ".join(
                [row["name"], row["description"], row["category"], *row.get("aliases", [])]
            ).lower()
            score = sum(4 if term in row["name"] else 1 for term in terms if term in haystack)
            if not terms or score:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        return [row for _, row in scored[: max(1, min(int(limit), 20))]]

    def describe(self, name: str) -> dict[str, Any]:
        spec = self._specs.get(str(name or "").strip())
        if spec is None:
            raise KeyError(f"Unknown progressive tool: {name}")
        result = {
            "name": spec.name,
            "description": spec.description,
            "title": spec.title or spec.name,
            "category": spec.category,
            "aliases": list(spec.aliases),
            "tags": list(spec.tags),
            "inputSchema": dict(spec.input_schema or {}),
            "outputSchema": dict(spec.output_schema or {}),
            "available": bool(spec.available),
            "availabilityReason": spec.availability_reason,
            "annotations": dict(spec.annotations),
            "permissions": list(spec.permissions),
            "provenance": dict(spec.provenance),
        }
        from .proofs_a_control import check_tool_description
        check_tool_description(spec, result)
        return result

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        tool_name = str(name or "").strip()
        if tool_name not in self._specs:
            raise KeyError(f"Unknown progressive tool: {name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise RuntimeError(f"No handler registered for progressive tool: {tool_name}")
        return handler(dict(arguments or {}))

    def discovery_contract(self) -> dict[str, Any]:
        return {
            "schema": "neyvia.progressive_tools.v1",
            "flow": ["search", "describe", "call"],
            "schemasDeferred": True,
            "includeSchemasDefault": False,
            "search": "search",
            "describe": "describe",
            "call": "call",
        }


def catalog_rows_without_schemas(
    tools: list[dict[str, Any]],
    *,
    include_schemas: bool = False,
) -> list[dict[str, Any]]:
    """Strip inputSchema from MCP/native catalog rows unless explicitly requested."""
    rows: list[dict[str, Any]] = []
    for tool in tools:
        row = dict(tool)
        if not include_schemas:
            row.pop("inputSchema", None)
            row.pop("input_schema", None)
        rows.append(row)
    return rows
