"""Typed contracts for the N-E-Y-V-I-A capability operating system.

The contracts are intentionally dependency-free so the web backend, CLI,
workers, and future UI can share the same payloads without importing a
framework-specific model layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


CAPABILITY_CATALOG_SCHEMA = "neyvia.capability_catalog.v1"
CAPABILITY_PACK_SCHEMA = "neyvia.capability_pack.v1"
CAPABILITY_PLAN_SCHEMA = "neyvia.capability_plan.v1"
CAPABILITY_RUN_SCHEMA = "neyvia.capability_run.v1"
ARTIFACT_GRAPH_SCHEMA = "neyvia.artifact_graph.v1"
PREVIEW_EVENT_SCHEMA = "neyvia.capability_preview.v1"
TELEMETRY_RECEIPT_SCHEMA = "neyvia.capability_telemetry.v1"
ADAPTER_CATALOG_SCHEMA = "neyvia.capability_adapters.v1"
PERMISSION_DECISION_SCHEMA = "neyvia.permission_decision.v1"

CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
VALID_RESOURCE_CLASSES = frozenset({"light", "standard", "heavy", "accelerated", "remote"})
VALID_PREVIEW_PHASES = frozenset({"plan", "live", "result"})
VALID_PERMISSION_CLASSES = frozenset(
    {
        "context.read",
        "artifact.read",
        "artifact.write",
        "workspace.read",
        "workspace.write",
        "process.execute",
        "network.read",
        "network.write",
        "secret.use",
        "external.side_effect",
        "compute.spend",
        "device.control",
        "security.assess",
        "tool.manage",
        "destructive",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_strings(values: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return result


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class ArtifactSelector:
    artifact_id: str = ""
    path: str = ""
    media_type: str = "application/octet-stream"
    name: str = ""
    selection: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: object) -> "ArtifactSelector":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            artifact_id=str(data.get("artifactId") or data.get("artifact_id") or "").strip(),
            path=str(data.get("path") or "").strip(),
            media_type=str(
                data.get("mediaType")
                or data.get("media_type")
                or data.get("mimeType")
                or "application/octet-stream"
            ).strip(),
            name=str(data.get("name") or "").strip(),
            selection=dict(data.get("selection") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "path": self.path,
            "mediaType": self.media_type,
            "name": self.name,
            "selection": dict(self.selection),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    pack_id: str
    name: str
    description: str
    verbs: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    input_types: tuple[str, ...] = ()
    output_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    adapter: str = "neyvia.agent"
    required_permissions: tuple[str, ...] = ("context.read",)
    resource_class: str = "standard"
    preview_types: tuple[str, ...] = ("plan", "live", "result")
    verifier: str = "evidence"
    tutorial_levels: tuple[str, ...] = ("guided", "standard", "advanced", "expert")
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, pack_id: str, payload: object) -> "CapabilitySpec":
        data = payload if isinstance(payload, dict) else {}
        capability_id = _required_text(
            data.get("capabilityId") or data.get("capability_id") or data.get("id"),
            "capabilityId",
        ).lower()
        if not CAPABILITY_ID_PATTERN.fullmatch(capability_id):
            raise ValueError(f"Invalid capabilityId: {capability_id}")
        resource_class = str(data.get("resourceClass") or "standard").strip().lower()
        if resource_class not in VALID_RESOURCE_CLASSES:
            raise ValueError(
                f"Capability {capability_id} has invalid resourceClass {resource_class!r}"
            )
        permissions = tuple(
            item.lower() for item in normalized_strings(data.get("requiredPermissions"))
        ) or ("context.read",)
        unknown_permissions = sorted(set(permissions).difference(VALID_PERMISSION_CLASSES))
        if unknown_permissions:
            raise ValueError(
                f"Capability {capability_id} has unknown permissions: {unknown_permissions}"
            )
        preview_types = tuple(
            item.lower() for item in normalized_strings(data.get("previewTypes"))
        ) or ("plan", "live", "result")
        unknown_phases = sorted(set(preview_types).difference(VALID_PREVIEW_PHASES))
        if unknown_phases:
            raise ValueError(
                f"Capability {capability_id} has unknown preview phases: {unknown_phases}"
            )
        return cls(
            capability_id=capability_id,
            pack_id=pack_id,
            name=_required_text(data.get("name"), "name"),
            description=_required_text(data.get("description"), "description"),
            verbs=tuple(item.lower() for item in normalized_strings(data.get("verbs"))),
            roles=tuple(item.lower() for item in normalized_strings(data.get("roles"))),
            input_types=tuple(
                item.lower() for item in normalized_strings(data.get("inputTypes"))
            ),
            output_types=tuple(
                item.lower() for item in normalized_strings(data.get("outputTypes"))
            ),
            tags=tuple(item.lower() for item in normalized_strings(data.get("tags"))),
            adapter=str(data.get("adapter") or "neyvia.agent").strip().lower(),
            required_permissions=permissions,
            resource_class=resource_class,
            preview_types=preview_types,
            verifier=str(data.get("verifier") or "evidence").strip().lower(),
            tutorial_levels=tuple(
                item.lower() for item in normalized_strings(data.get("tutorialLevels"))
            )
            or ("guided", "standard", "advanced", "expert"),
            metadata=dict(data.get("metadata") or {}),
        )

    def as_dict(
        self,
        *,
        available: bool | None = None,
        availability_reason: str = "",
        score: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "capabilityId": self.capability_id,
            "packId": self.pack_id,
            "name": self.name,
            "description": self.description,
            "verbs": list(self.verbs),
            "roles": list(self.roles),
            "inputTypes": list(self.input_types),
            "outputTypes": list(self.output_types),
            "tags": list(self.tags),
            "adapter": self.adapter,
            "requiredPermissions": list(self.required_permissions),
            "resourceClass": self.resource_class,
            "previewTypes": list(self.preview_types),
            "verifier": self.verifier,
            "tutorialLevels": list(self.tutorial_levels),
            "metadata": dict(self.metadata),
        }
        if available is not None:
            payload["available"] = bool(available)
            payload["availabilityReason"] = str(availability_reason or "")
        if score is not None:
            payload["score"] = round(float(score), 4)
        return payload


@dataclass(frozen=True)
class CapabilityPack:
    pack_id: str
    name: str
    description: str
    domains: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    capabilities: tuple[CapabilitySpec, ...] = ()
    default_experience: str = "standard"
    safety_notes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: object) -> "CapabilityPack":
        data = payload if isinstance(payload, dict) else {}
        pack_id = _required_text(
            data.get("packId") or data.get("pack_id") or data.get("id"),
            "packId",
        ).lower()
        if not CAPABILITY_ID_PATTERN.fullmatch(pack_id):
            raise ValueError(f"Invalid packId: {pack_id}")
        capabilities = tuple(
            CapabilitySpec.from_payload(pack_id, item)
            for item in (data.get("capabilities") or [])
        )
        if not capabilities:
            raise ValueError(f"Capability pack {pack_id} has no capabilities")
        return cls(
            pack_id=pack_id,
            name=_required_text(data.get("name"), "name"),
            description=_required_text(data.get("description"), "description"),
            domains=tuple(item.lower() for item in normalized_strings(data.get("domains"))),
            roles=tuple(item.lower() for item in normalized_strings(data.get("roles"))),
            capabilities=capabilities,
            default_experience=str(
                data.get("defaultExperience") or "standard"
            ).strip().lower(),
            safety_notes=tuple(normalized_strings(data.get("safetyNotes"))),
            metadata=dict(data.get("metadata") or {}),
        )

    def as_dict(self, *, include_capabilities: bool = True) -> dict[str, Any]:
        payload = {
            "schema": CAPABILITY_PACK_SCHEMA,
            "packId": self.pack_id,
            "name": self.name,
            "description": self.description,
            "domains": list(self.domains),
            "roles": list(self.roles),
            "defaultExperience": self.default_experience,
            "safetyNotes": list(self.safety_notes),
            "metadata": dict(self.metadata),
            "capabilityCount": len(self.capabilities),
        }
        if include_capabilities:
            payload["capabilities"] = [item.as_dict() for item in self.capabilities]
        return payload


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    label: str
    kind: str
    available: bool
    reason: str = ""
    executable: str = ""
    version: str = ""
    resource_class: str = "standard"
    supports_execution: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "label": self.label,
            "kind": self.kind,
            "available": self.available,
            "reason": self.reason,
            "executable": self.executable,
            "version": self.version,
            "resourceClass": self.resource_class,
            "supportsExecution": self.supports_execution,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PermissionDecision:
    permission: str
    status: str
    reason: str
    requires_approval: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PERMISSION_DECISION_SCHEMA,
            "permission": self.permission,
            "status": self.status,
            "reason": self.reason,
            "requiresApproval": self.requires_approval,
        }


@dataclass(frozen=True)
class PreviewEvent:
    run_id: str
    phase: str
    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.phase not in VALID_PREVIEW_PHASES:
            raise ValueError(f"Unsupported preview phase: {self.phase}")
        _required_text(self.run_id, "runId")
        _required_text(self.kind, "kind")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PREVIEW_EVENT_SCHEMA,
            "runId": self.run_id,
            "phase": self.phase,
            "kind": self.kind,
            "summary": self.summary,
            "payload": dict(self.payload),
            "artifactIds": list(self.artifact_ids),
            "createdAt": self.created_at,
        }


def validate_catalog_payload(payload: object) -> list[CapabilityPack]:
    if not isinstance(payload, dict):
        raise ValueError("Capability catalog must be a JSON object")
    schema = str(payload.get("schema") or CAPABILITY_CATALOG_SCHEMA)
    if schema != CAPABILITY_CATALOG_SCHEMA:
        raise ValueError(f"Unsupported capability catalog schema: {schema}")
    packs = [CapabilityPack.from_payload(item) for item in (payload.get("packs") or [])]
    if not packs:
        raise ValueError("Capability catalog contains no packs")
    pack_ids = [item.pack_id for item in packs]
    if len(pack_ids) != len(set(pack_ids)):
        raise ValueError("Capability pack identifiers must be unique")
    capability_ids = [
        capability.capability_id
        for pack in packs
        for capability in pack.capabilities
    ]
    if len(capability_ids) != len(set(capability_ids)):
        raise ValueError("Capability identifiers must be unique across packs")
    return packs


def dataclass_payload(value: object) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"Expected dataclass value, got {type(value).__name__}")
