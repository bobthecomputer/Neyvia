"""Author, adapt, validate, and persist workspace-scoped N-E-Y-V-I-A tools.

The factory uses declarative manifests. Command tools never invoke a shell:
their executable comes from an already discovered adapter and arguments are
passed as an argv list. Composite tools may call only an explicit internal
operation allowlist supplied by CapabilityService.
"""

from __future__ import annotations

from .proofs_c_models import checked

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from .capability_contracts import canonical_hash, normalized_strings, utc_now
from .model_tool_intelligence import strict_schema
from .proofs_a_capabilities import checked_action
from .proofs_a_capability_tools import check_authored_save


AUTHORED_TOOL_SCHEMA = "neyvia.authored_tool.v1"
AUTHORED_TOOL_CATALOG_SCHEMA = "neyvia.authored_tool_catalog.v1"
TOOL_ADAPTATION_SCHEMA = "neyvia.tool_adaptation.v1"
TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
ALLOWED_KINDS = frozenset({"command", "composite", "delegated"})
ALLOWED_OUTPUT_PARSERS = frozenset({"text", "json"})
TEMPLATE_PATTERN = re.compile(r"\{\{\s*input\.([a-zA-Z0-9_.-]+)\s*\}\}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", raw).strip(".-_")
    if "." not in normalized:
        normalized = f"custom.{normalized or 'tool'}"
    return normalized


def _resolve_input(arguments: dict[str, Any], path: str) -> Any:
    current: Any = arguments
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise KeyError(f"Missing authored-tool input: {path}")
        current = current[segment]
    return current


def render_templates(value: Any, arguments: dict[str, Any]) -> Any:
    """Render input references without evaluating code or shell expressions."""

    if isinstance(value, dict):
        return {
            str(key): render_templates(child, arguments)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [render_templates(child, arguments) for child in value]
    if not isinstance(value, str):
        return value
    full = TEMPLATE_PATTERN.fullmatch(value)
    if full:
        return _resolve_input(arguments, full.group(1))

    def replace(match: re.Match[str]) -> str:
        resolved = _resolve_input(arguments, match.group(1))
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)

    return TEMPLATE_PATTERN.sub(replace, value)


class AuthoredToolStore:
    """Durable manifest store with deterministic validation and adaptation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.directory = (
            self.root / ".agent_control" / "capability_os" / "authored_tools"
        )
        self._lock = threading.RLock()
        self._catalog_cache: dict[str, Any] | None = None

    def _target(self, tool_id: str) -> Path:
        return self.directory / f"{tool_id}.json"

    def validate(self, manifest: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        tool_id = str(manifest.get("toolId") or "").strip().lower()
        name = str(manifest.get("name") or "").strip()
        description = str(manifest.get("description") or "").strip()
        kind = str(manifest.get("kind") or "").strip().lower()
        if manifest.get("schema") != AUTHORED_TOOL_SCHEMA:
            errors.append(f"schema must equal {AUTHORED_TOOL_SCHEMA}")
        if not TOOL_ID_PATTERN.fullmatch(tool_id):
            errors.append(
                "toolId must be namespaced lowercase text such as custom.word-count"
            )
        if not name:
            errors.append("name is required")
        if not description:
            errors.append("description is required")
        if kind not in ALLOWED_KINDS:
            errors.append(f"kind must be one of {sorted(ALLOWED_KINDS)}")
        input_schema = manifest.get("inputSchema")
        if not isinstance(input_schema, dict):
            errors.append("inputSchema must be an object")
        elif input_schema.get("type", "object") != "object":
            errors.append("inputSchema root type must be object")
        permissions = normalized_strings(manifest.get("permissions"))
        if kind == "command":
            command = manifest.get("command")
            if not isinstance(command, dict):
                errors.append("command tools require a command object")
            else:
                if not str(command.get("adapterId") or "").strip():
                    errors.append("command.adapterId is required")
                argv = command.get("argvTemplate")
                if not isinstance(argv, list) or not argv:
                    errors.append("command.argvTemplate must be a non-empty list")
                elif len(argv) > 64 or not all(
                    isinstance(item, str) and len(item) <= 8192 for item in argv
                ):
                    errors.append(
                        "command.argvTemplate accepts at most 64 bounded string arguments"
                    )
                timeout = command.get("timeoutSeconds", 30)
                try:
                    timeout_value = int(timeout)
                except (TypeError, ValueError):
                    timeout_value = 0
                if timeout_value < 1 or timeout_value > 900:
                    errors.append("command.timeoutSeconds must be between 1 and 900")
                parser = str(command.get("outputParser") or "text").lower()
                if parser not in ALLOWED_OUTPUT_PARSERS:
                    errors.append(
                        f"command.outputParser must be one of {sorted(ALLOWED_OUTPUT_PARSERS)}"
                    )
            if "process.execute" not in permissions:
                errors.append("command tools must declare process.execute permission")
        if kind == "composite":
            steps = manifest.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append("composite tools require at least one step")
            elif len(steps) > 50:
                errors.append("composite tools support at most 50 steps")
            else:
                step_ids: set[str] = set()
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        errors.append(f"steps[{index}] must be an object")
                        continue
                    step_id = str(step.get("stepId") or "").strip()
                    operation = str(step.get("operation") or "").strip()
                    if not step_id:
                        errors.append(f"steps[{index}].stepId is required")
                    elif step_id in step_ids:
                        errors.append(f"duplicate stepId: {step_id}")
                    step_ids.add(step_id)
                    if not operation:
                        errors.append(f"steps[{index}].operation is required")
                    if not isinstance(step.get("arguments", {}), dict):
                        errors.append(f"steps[{index}].arguments must be an object")
        if kind == "delegated":
            delegated = manifest.get("delegated")
            if not isinstance(delegated, dict):
                errors.append("delegated tools require a delegated object")
            elif not str(delegated.get("adapterId") or "").strip():
                errors.append("delegated.adapterId is required")
            warnings.append(
                "Delegated tools remain unavailable until their adapter session is healthy."
            )
        normalized = dict(manifest)
        normalized["schema"] = AUTHORED_TOOL_SCHEMA
        normalized["toolId"] = tool_id
        normalized["name"] = name
        normalized["description"] = description
        normalized["kind"] = kind
        normalized["permissions"] = permissions
        normalized.setdefault("inputSchema", {"type": "object", "properties": {}})
        normalized.setdefault("outputSchema", {"type": "object"})
        normalized.setdefault("version", "1.0.0")
        normalized.setdefault("tags", [])
        normalized.setdefault("provenance", {})
        strict_input, strict_eligible, strict_warnings = strict_schema(
            normalized["inputSchema"]
        )
        normalized["modelSchema"] = {
            "strictEligible": strict_eligible,
            "strictInputSchema": strict_input if strict_eligible else None,
        }
        warnings.extend(strict_warnings)
        provenance = normalized.get("provenance")
        if kind == "delegated" and not isinstance(provenance, dict):
            errors.append("delegated tool provenance must be an object")
        elif kind == "delegated" and not str(
            (provenance or {}).get("originalName")
            or (normalized.get("delegated") or {}).get("remoteToolName")
            or ""
        ).strip():
            errors.append("delegated tools must preserve their original tool name")
        return {
            "schema": "neyvia.authored_tool_validation.v1",
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "normalized": normalized,
            "manifestHash": canonical_hash(normalized),
        }

    @checked_action(check_authored_save)
    @checked("authored-save")
    def save(
        self,
        manifest: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        validation = self.validate(manifest)
        if not validation["valid"]:
            return {
                "ok": False,
                "status": "invalid",
                "validation": validation,
            }
        if not approved:
            return {
                "ok": False,
                "status": "approval_required",
                "requiredPermission": "workspace.write",
                "validation": validation,
            }
        normalized = dict(validation["normalized"])
        normalized["updatedAt"] = utc_now()
        target = self._target(normalized["toolId"])
        with self._lock:
            _atomic_json(target, normalized)
            self._catalog_cache = None
        return {
            "ok": True,
            "status": "saved",
            "tool": normalized,
            "path": str(target),
            "manifestHash": validation["manifestHash"],
        }

    def list_tools(self) -> dict[str, Any]:
        with self._lock:
            if self._catalog_cache is not None:
                return {
                    **self._catalog_cache,
                    "tools": [
                        dict(item) for item in self._catalog_cache["tools"]
                    ],
                    "loadErrors": [
                        dict(item)
                        for item in self._catalog_cache["loadErrors"]
                    ],
                }
        tools: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if self.directory.exists():
            for path in sorted(self.directory.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    validation = self.validate(payload)
                    if not validation["valid"]:
                        raise ValueError("; ".join(validation["errors"]))
                    item = dict(validation["normalized"])
                    item["path"] = str(path)
                    item["manifestHash"] = validation["manifestHash"]
                    tools.append(item)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    errors.append({"path": str(path), "error": str(exc)})
        result = {
            "schema": AUTHORED_TOOL_CATALOG_SCHEMA,
            "generatedAt": utc_now(),
            "tools": tools,
            "loadErrors": errors,
        }
        with self._lock:
            self._catalog_cache = result
        return {
            **result,
            "tools": [dict(item) for item in result["tools"]],
            "loadErrors": [dict(item) for item in result["loadErrors"]],
        }

    def describe(self, tool_id: str) -> dict[str, Any]:
        normalized = str(tool_id or "").strip().lower()
        for tool in self.list_tools()["tools"]:
            if tool["toolId"] == normalized:
                return tool
        raise KeyError(f"Unknown authored tool: {tool_id}")

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        terms = {
            item
            for item in re.findall(r"[a-z0-9]+", str(query).casefold())
            if len(item) > 1
        }
        scored: list[tuple[int, dict[str, Any]]] = []
        for tool in self.list_tools()["tools"]:
            haystack = " ".join(
                [
                    tool["toolId"],
                    tool["name"],
                    tool["description"],
                    *normalized_strings(tool.get("tags")),
                ]
            ).casefold()
            score = sum(
                5 if term in tool["toolId"] else 1
                for term in terms
                if term in haystack
            )
            if not terms or score:
                row = {
                    "toolId": tool["toolId"],
                    "name": tool["name"],
                    "description": tool["description"],
                    "kind": tool["kind"],
                    "permissions": tool["permissions"],
                    "score": score,
                }
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["toolId"]))
        return [item for _, item in scored[: max(1, min(int(limit), 50))]]

    @checked("adapt")
    def adapt(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Convert common external definitions into a reviewable native draft."""

        source_type = str(payload.get("sourceType") or "").strip().lower()
        source = payload.get("source")
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        warnings: list[str] = []
        if source_type in {"openai_function", "mcp"}:
            function = (
                source.get("function")
                if isinstance(source.get("function"), dict)
                else source
            )
            source_name = str(function.get("name") or "imported-tool")
            adapter_id = str(payload.get("adapterId") or "").strip()
            source_metadata = (
                payload.get("sourceMetadata")
                if isinstance(payload.get("sourceMetadata"), dict)
                else {}
            )
            server = str(
                source_metadata.get("server")
                or payload.get("server")
                or source.get("server")
                or ""
            ).strip()
            manifest = {
                "schema": AUTHORED_TOOL_SCHEMA,
                "toolId": _safe_id(payload.get("toolId") or source_name),
                "name": str(function.get("title") or source_name),
                "description": str(
                    function.get("description")
                    or "Imported delegated tool requiring adapter review."
                ),
                "kind": "delegated",
                "version": "1.0.0",
                "permissions": normalized_strings(payload.get("permissions")),
                "inputSchema": dict(
                    function.get("parameters")
                    or function.get("inputSchema")
                    or {"type": "object", "properties": {}}
                ),
                "outputSchema": dict(
                    payload.get("outputSchema")
                    or function.get("outputSchema")
                    or {"type": "object"}
                ),
                "delegated": {
                    "adapterId": adapter_id,
                    "remoteToolName": source_name,
                    "sourceType": source_type,
                },
                "provenance": {
                    "sourceKind": source_type,
                    "provider": str(
                        source_metadata.get("provider")
                        or ("mcp" if source_type == "mcp" else "openai")
                    ),
                    "server": server,
                    "originalName": source_name,
                    "originalTitle": str(function.get("title") or source_name),
                    "sourceVersion": str(
                        source_metadata.get("version")
                        or source.get("version")
                        or ""
                    ),
                    "sourceUrl": str(source_metadata.get("sourceUrl") or ""),
                    "license": str(source_metadata.get("license") or ""),
                    "adapterId": adapter_id,
                    "importedAt": utc_now(),
                    "trustLevel": str(
                        source_metadata.get("trustLevel") or "external-unverified"
                    ),
                    "sourceHash": canonical_hash(source),
                },
                "tags": ["adapted", source_type],
            }
            if not adapter_id:
                warnings.append(
                    "Select an approved adapter before this draft can execute."
                )
        elif source_type == "command":
            source_metadata = (
                payload.get("sourceMetadata")
                if isinstance(payload.get("sourceMetadata"), dict)
                else {}
            )
            manifest = {
                "schema": AUTHORED_TOOL_SCHEMA,
                "toolId": _safe_id(
                    payload.get("toolId") or source.get("name") or "command-tool"
                ),
                "name": str(source.get("name") or "Adapted command tool"),
                "description": str(
                    source.get("description") or "Workspace command adapter."
                ),
                "kind": "command",
                "version": "1.0.0",
                "permissions": normalized_strings(
                    payload.get("permissions") or ["process.execute"]
                ),
                "inputSchema": dict(
                    source.get("inputSchema")
                    or {"type": "object", "properties": {}}
                ),
                "outputSchema": dict(
                    source.get("outputSchema") or {"type": "object"}
                ),
                "command": {
                    "adapterId": str(source.get("adapterId") or ""),
                    "argvTemplate": list(source.get("argvTemplate") or []),
                    "workingDirectory": str(
                        source.get("workingDirectory") or "."
                    ),
                    "timeoutSeconds": int(source.get("timeoutSeconds") or 30),
                    "outputParser": str(source.get("outputParser") or "text"),
                },
                "provenance": {
                    "sourceKind": "command",
                    "provider": str(source_metadata.get("provider") or "workspace"),
                    "server": "",
                    "originalName": str(source.get("name") or "command-tool"),
                    "originalTitle": str(source.get("name") or "Adapted command tool"),
                    "sourceVersion": str(source_metadata.get("version") or ""),
                    "sourceUrl": str(source_metadata.get("sourceUrl") or ""),
                    "license": str(source_metadata.get("license") or ""),
                    "adapterId": str(source.get("adapterId") or ""),
                    "importedAt": utc_now(),
                    "trustLevel": str(
                        source_metadata.get("trustLevel") or "workspace-reviewed"
                    ),
                    "sourceHash": canonical_hash(source),
                },
                "tags": ["adapted", "command"],
            }
        else:
            raise ValueError(
                "sourceType must be openai_function, mcp, or command"
            )
        validation = self.validate(manifest)
        validation["warnings"] = [
            *warnings,
            *validation.get("warnings", []),
        ]
        return {
            "schema": TOOL_ADAPTATION_SCHEMA,
            "status": "draft",
            "sourceType": source_type,
            "manifest": manifest,
            "validation": validation,
            "nextAction": "Review the manifest, then call tool.author.save with approved=true.",
        }

    def resolve_working_directory(self, value: object) -> Path:
        candidate = Path(str(value or "."))
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(
                "Authored tool workingDirectory must remain inside the workspace"
            ) from exc
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(f"Working directory does not exist: {resolved}")
        return resolved
