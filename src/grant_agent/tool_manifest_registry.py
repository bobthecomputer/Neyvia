"""Validated inventory for external tools that extend Neyvia capabilities.

Executable discovery answers only whether a binary can be found.  This registry
answers the stricter questions required for agent use: what exact upstream tool
was selected, which operations are intentionally exposed, whether its installation
was verified, and which permissions and artifacts belong to each operation.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from .proofs_a_capabilities import checked_action
from .proofs_a_capability_tools import check_tool_manifest, check_tool_snapshot, check_tool_search
from .proofs_b_adapters import checked as _proofs_b_checked

from .capability_contracts import (
    CAPABILITY_ID_PATTERN,
    VALID_PERMISSION_CLASSES,
    canonical_hash,
    normalized_strings,
    utc_now,
)


TOOL_SUITE_LOCK_SCHEMA = "neyvia.tool_suite_lock.v1"
TOOL_MANIFEST_SCHEMA = "neyvia.tool_manifest.v1"
TOOL_OPERATION_SCHEMA = "neyvia.tool_operation.v1"
TOOL_READINESS_SCHEMA = "neyvia.tool_execution_readiness.v2"

VALID_TOOL_STATES = frozenset(
    {"planned", "installing", "installed", "verified", "blocked", "retired"}
)
VALID_WORKER_CLASSES = frozenset(
    {"windows", "nas", "wsl", "container", "gpu", "remote_apple"}
)
VALID_HEALTH_STATES = frozenset(
    {"pending", "healthy", "degraded", "unhealthy", "unreachable"}
)
VALID_READINESS_KINDS = frozenset(
    {"contract", "executable", "trust", "service", "device", "worker", "production"}
)
VALID_READINESS_STATES = frozenset(
    {"ready", "blocked", "unprovisioned", "unavailable", "pending", "unverified"}
)
VALID_READINESS_LEVELS = frozenset({"execution", "production"})


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _validate_https_url(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field_name} must be an https URL")
    return text


def _contains_secret_key(value: object) -> bool:
    forbidden = {
        "token",
        "password",
        "secret",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "sessionkey",
        "privatekey",
        "credentials",
        "cookie",
        "authorization",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "").replace("_", "")
            if normalized in forbidden or _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


@dataclass(frozen=True)
class ToolOperationManifest:
    operation_id: str
    name: str
    description: str
    permissions: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    artifact_roles: tuple[str, ...] = ()
    verifier: str = ""
    supports_preview: bool = False
    supports_cancel: bool = True
    destructive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: object) -> "ToolOperationManifest":
        data = payload if isinstance(payload, dict) else {}
        operation_id = _required_text(data.get("operationId"), "operationId").lower()
        if not CAPABILITY_ID_PATTERN.fullmatch(operation_id):
            raise ValueError(f"Invalid operationId: {operation_id}")
        permissions = tuple(
            item.lower() for item in normalized_strings(data.get("permissions"))
        )
        unknown = sorted(set(permissions).difference(VALID_PERMISSION_CLASSES))
        if unknown:
            raise ValueError(
                f"Operation {operation_id} has unknown permissions: {unknown}"
            )
        input_schema = dict(data.get("inputSchema") or {})
        output_schema = dict(data.get("outputSchema") or {})
        if input_schema.get("type") != "object":
            raise ValueError(f"Operation {operation_id} inputSchema must be an object")
        if output_schema.get("type") != "object":
            raise ValueError(f"Operation {operation_id} outputSchema must be an object")
        destructive = bool(data.get("destructive", False))
        if destructive and "destructive" not in permissions:
            raise ValueError(
                f"Destructive operation {operation_id} must declare destructive permission"
            )
        return cls(
            operation_id=operation_id,
            name=_required_text(data.get("name"), "name"),
            description=_required_text(data.get("description"), "description"),
            permissions=permissions,
            input_schema=input_schema,
            output_schema=output_schema,
            artifact_roles=tuple(normalized_strings(data.get("artifactRoles"))),
            verifier=str(data.get("verifier") or "").strip(),
            supports_preview=bool(data.get("supportsPreview", False)),
            supports_cancel=bool(data.get("supportsCancel", True)),
            destructive=destructive,
            metadata=dict(data.get("metadata") or {}),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": TOOL_OPERATION_SCHEMA,
            "operationId": self.operation_id,
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
            "inputSchema": dict(self.input_schema),
            "outputSchema": dict(self.output_schema),
            "artifactRoles": list(self.artifact_roles),
            "verifier": self.verifier,
            "supportsPreview": self.supports_preview,
            "supportsCancel": self.supports_cancel,
            "destructive": self.destructive,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ToolManifest:
    tool_id: str
    name: str
    upstream: str
    homepage: str
    repository: str
    releases: str
    license: str
    selected_version: str
    version_policy: str
    state: str
    wave: int
    workers: tuple[str, ...]
    adapters: tuple[str, ...]
    capabilities: tuple[str, ...]
    features: tuple[str, ...]
    operations: tuple[ToolOperationManifest, ...]
    install_path: str = ""
    package_sha256: str = ""
    health: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    readiness: dict[str, Any] = field(default_factory=dict)

    @classmethod
    @checked_action(check_tool_manifest)
    def from_payload(cls, payload: object) -> "ToolManifest":
        data = payload if isinstance(payload, dict) else {}
        if _contains_secret_key(data):
            raise ValueError("Tool manifests must not contain secret-bearing fields")
        tool_id = _required_text(data.get("toolId"), "toolId").lower()
        if not CAPABILITY_ID_PATTERN.fullmatch(tool_id):
            raise ValueError(f"Invalid toolId: {tool_id}")
        state = str(data.get("state") or "planned").strip().lower()
        if state not in VALID_TOOL_STATES:
            raise ValueError(f"Tool {tool_id} has invalid state {state!r}")
        workers = tuple(
            item.lower() for item in normalized_strings(data.get("workers"))
        )
        unknown_workers = sorted(set(workers).difference(VALID_WORKER_CLASSES))
        if unknown_workers:
            raise ValueError(
                f"Tool {tool_id} has unknown worker classes: {unknown_workers}"
            )
        health = dict(data.get("health") or {"status": "pending"})
        health_status = str(health.get("status") or "pending").strip().lower()
        if health_status not in VALID_HEALTH_STATES:
            raise ValueError(
                f"Tool {tool_id} has invalid health status {health_status!r}"
            )
        package_sha256 = str(data.get("packageSha256") or "").strip().lower()
        if package_sha256 and (
            len(package_sha256) != 64
            or any(character not in "0123456789abcdef" for character in package_sha256)
        ):
            raise ValueError(f"Tool {tool_id} packageSha256 must be a SHA-256 hex digest")
        operations = tuple(
            ToolOperationManifest.from_payload(item)
            for item in (data.get("operations") or [])
        )
        operation_ids = [item.operation_id for item in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError(f"Tool {tool_id} has duplicate operation identifiers")
        if state == "verified":
            if not package_sha256:
                raise ValueError(f"Verified tool {tool_id} must have packageSha256")
            if not operations:
                raise ValueError(f"Verified tool {tool_id} must expose typed operations")
        readiness = dict(data.get("readiness") or {})
        prerequisites = readiness.get("prerequisites") or []
        if not isinstance(prerequisites, list):
            raise ValueError(f"Tool {tool_id} readiness.prerequisites must be an array")
        normalized_prerequisites: list[dict[str, Any]] = []
        seen_prerequisites: set[str] = set()
        for index, raw_prerequisite in enumerate(prerequisites):
            prerequisite = (
                raw_prerequisite if isinstance(raw_prerequisite, dict) else {}
            )
            prerequisite_id = _required_text(
                prerequisite.get("id"),
                f"readiness.prerequisites[{index}].id",
            ).lower()
            if not CAPABILITY_ID_PATTERN.fullmatch(prerequisite_id):
                raise ValueError(
                    f"Tool {tool_id} has invalid readiness prerequisite "
                    f"{prerequisite_id!r}"
                )
            if prerequisite_id in seen_prerequisites:
                raise ValueError(
                    f"Tool {tool_id} has duplicate readiness prerequisite "
                    f"{prerequisite_id}"
                )
            seen_prerequisites.add(prerequisite_id)
            kind = str(prerequisite.get("kind") or "").strip().lower()
            if kind not in VALID_READINESS_KINDS:
                raise ValueError(
                    f"Tool {tool_id} readiness prerequisite {prerequisite_id} "
                    f"has invalid kind {kind!r}"
                )
            status = str(prerequisite.get("status") or "").strip().lower()
            if status not in VALID_READINESS_STATES:
                raise ValueError(
                    f"Tool {tool_id} readiness prerequisite {prerequisite_id} "
                    f"has invalid status {status!r}"
                )
            required_for = tuple(
                item.lower()
                for item in normalized_strings(prerequisite.get("requiredFor"))
            )
            if not required_for:
                raise ValueError(
                    f"Tool {tool_id} readiness prerequisite {prerequisite_id} "
                    "must declare requiredFor"
                )
            unknown_levels = sorted(
                set(required_for).difference(VALID_READINESS_LEVELS)
            )
            if unknown_levels:
                raise ValueError(
                    f"Tool {tool_id} readiness prerequisite {prerequisite_id} "
                    f"has invalid requiredFor values: {unknown_levels}"
                )
            normalized_prerequisites.append(
                {
                    "id": prerequisite_id,
                    "kind": kind,
                    "status": status,
                    "requiredFor": list(required_for),
                    "reason": _required_text(
                        prerequisite.get("reason"),
                        f"readiness.prerequisites[{index}].reason",
                    ),
                    "evidence": str(prerequisite.get("evidence") or "").strip(),
                }
            )
        readiness["prerequisites"] = normalized_prerequisites
        production_validated = readiness.get("productionValidated", False)
        if not isinstance(production_validated, bool):
            raise ValueError(
                f"Tool {tool_id} readiness.productionValidated must be a boolean"
            )
        readiness["productionValidated"] = production_validated
        readiness["productionEvidence"] = str(
            readiness.get("productionEvidence") or ""
        ).strip()
        if (
            readiness["productionValidated"]
            and not readiness["productionEvidence"]
        ):
            raise ValueError(
                f"Tool {tool_id} productionValidated requires productionEvidence"
            )
        return cls(
            tool_id=tool_id,
            name=_required_text(data.get("name"), "name"),
            upstream=_required_text(data.get("upstream"), "upstream"),
            homepage=_validate_https_url(data.get("homepage"), "homepage"),
            repository=_validate_https_url(data.get("repository"), "repository"),
            releases=_validate_https_url(data.get("releases"), "releases"),
            license=_required_text(data.get("license"), "license"),
            selected_version=_required_text(
                data.get("selectedVersion"), "selectedVersion"
            ),
            version_policy=_required_text(
                data.get("versionPolicy"), "versionPolicy"
            ),
            state=state,
            wave=max(0, int(data.get("wave") or 0)),
            workers=workers,
            adapters=tuple(
                item.lower() for item in normalized_strings(data.get("adapters"))
            ),
            capabilities=tuple(
                item.lower() for item in normalized_strings(data.get("capabilities"))
            ),
            features=tuple(normalized_strings(data.get("features"))),
            operations=operations,
            install_path=str(data.get("installPath") or "").strip(),
            package_sha256=package_sha256,
            health=health,
            resource=dict(data.get("resource") or {}),
            metadata=dict(data.get("metadata") or {}),
            readiness=readiness,
        )

    @property
    def health_status(self) -> str:
        return str(self.health.get("status") or "pending").strip().lower()

    @property
    def contract_ready(self) -> bool:
        return (
            self.state == "verified"
            and bool(self.package_sha256)
            and bool(self.operations)
        )

    @property
    def blocked_prerequisites(self) -> tuple[dict[str, Any], ...]:
        blocked: list[dict[str, Any]] = []
        if self.state != "verified":
            blocked.append(
                {
                    "id": "manifest-state",
                    "kind": "contract",
                    "status": "blocked",
                    "requiredFor": ["execution", "production"],
                    "reason": f"Tool manifest state is {self.state}, not verified.",
                    "evidence": "",
                }
            )
        if not self.package_sha256:
            blocked.append(
                {
                    "id": "package-hash",
                    "kind": "contract",
                    "status": "unverified",
                    "requiredFor": ["execution", "production"],
                    "reason": "No pinned package or executable SHA-256 is declared.",
                    "evidence": "",
                }
            )
        if not self.operations:
            blocked.append(
                {
                    "id": "typed-operations",
                    "kind": "contract",
                    "status": "unprovisioned",
                    "requiredFor": ["execution", "production"],
                    "reason": "No typed operations are declared.",
                    "evidence": "",
                }
            )
        if self.health_status != "healthy":
            blocked.append(
                {
                    "id": "health",
                    "kind": "service",
                    "status": "unavailable",
                    "requiredFor": ["execution", "production"],
                    "reason": (
                        f"Tool health is {self.health_status}, not healthy."
                    ),
                    "evidence": str(self.health.get("probe") or ""),
                }
            )
        if not self.install_path:
            blocked.append(
                {
                    "id": "install-path",
                    "kind": "executable",
                    "status": "unprovisioned",
                    "requiredFor": ["execution", "production"],
                    "reason": "No executable or implementation path is declared.",
                    "evidence": "",
                }
            )
        blocked.extend(
            dict(item)
            for item in (self.readiness.get("prerequisites") or [])
            if item.get("status") != "ready"
        )
        if not bool(self.readiness.get("productionValidated", False)):
            blocked.append(
                {
                    "id": "production-validation",
                    "kind": "production",
                    "status": "unverified",
                    "requiredFor": ["production"],
                    "reason": (
                        "Production validation is not explicitly declared; "
                        "execution evidence must not be promoted to production proof."
                    ),
                    "evidence": "",
                }
            )
        blocked.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
        return tuple(blocked)

    def _ready_for(self, level: str) -> bool:
        return not any(
            level in item.get("requiredFor", [])
            for item in self.blocked_prerequisites
        )

    @property
    def execution_ready(self) -> bool:
        """Manifest-declared prerequisites only; not a live-host claim."""

        return self.contract_ready and self._ready_for("execution")

    @property
    def production_ready(self) -> bool:
        """Production prerequisites only; live execution must be added by a host."""

        return False

    @property
    def agent_ready(self) -> bool:
        """Preserve the v1 manifest-level agentReady contract."""

        return (
            self.state == "verified"
            and self.health_status == "healthy"
            and bool(self.package_sha256)
            and bool(self.operations)
        )

    @_proofs_b_checked("readiness")
    def readiness_as_dict(
        self,
        runtime_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = dict(runtime_readiness or {})
        runtime_evaluated = bool(runtime.get("evaluated", False))
        runtime_ready = bool(runtime.get("ready", False)) if runtime_evaluated else False
        blocked = [dict(item) for item in self.blocked_prerequisites]
        blocked.extend(
            dict(item) for item in (runtime.get("blockedPrerequisites") or [])
        )
        if not runtime_evaluated:
            blocked.append(
                {
                    "id": "live-host-evaluation",
                    "kind": "worker",
                    "status": "unverified",
                    "requiredFor": ["execution", "production"],
                    "reason": (
                        "Execution readiness requires a current host, executable, "
                        "version, hash, and adapter evaluation."
                    ),
                    "evidence": "",
                }
            )
        blocked.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
        execution_ready = (
            runtime_evaluated
            and runtime_ready
            and self.contract_ready
            and not any(
                "execution" in item.get("requiredFor", [])
                for item in blocked
            )
        )
        production_ready = (
            execution_ready
            and bool(self.readiness.get("productionValidated", False))
            and not any(
                "production" in item.get("requiredFor", [])
                for item in blocked
            )
        )
        return {
            "schema": TOOL_READINESS_SCHEMA,
            "contractReady": self.contract_ready,
            "executionReady": execution_ready,
            "executionReadinessEvaluated": runtime_evaluated,
            "productionReady": production_ready,
            "productionEvidence": str(
                self.readiness.get("productionEvidence") or ""
            ),
            "runtimeEvidence": dict(runtime.get("evidence") or {}),
            "blockedPrerequisites": blocked,
        }

    def as_dict(
        self,
        *,
        include_operations: bool = True,
        runtime_readiness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        readiness = self.readiness_as_dict(runtime_readiness)
        payload = {
            "schema": TOOL_MANIFEST_SCHEMA,
            "toolId": self.tool_id,
            "name": self.name,
            "upstream": self.upstream,
            "homepage": self.homepage,
            "repository": self.repository,
            "releases": self.releases,
            "license": self.license,
            "selectedVersion": self.selected_version,
            "versionPolicy": self.version_policy,
            "state": self.state,
            "wave": self.wave,
            "workers": list(self.workers),
            "adapters": list(self.adapters),
            "capabilities": list(self.capabilities),
            "features": list(self.features),
            "installPath": self.install_path,
            "packageSha256": self.package_sha256,
            "health": dict(self.health),
            "resource": dict(self.resource),
            "metadata": dict(self.metadata),
            "operationCount": len(self.operations),
            "agentReady": self.agent_ready,
            "contractReady": readiness["contractReady"],
            "executionReady": readiness["executionReady"],
            "executionReadinessEvaluated": readiness[
                "executionReadinessEvaluated"
            ],
            "productionReady": readiness["productionReady"],
            "blockedPrerequisites": readiness["blockedPrerequisites"],
            "readiness": readiness,
        }
        if include_operations:
            payload["operations"] = [item.as_dict() for item in self.operations]
        return payload


class ToolManifestRegistry:
    """Load and query the pinned tool-selection inventory."""

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path).resolve()
        self.adapters: Any | None = None
        self.tools: dict[str, ToolManifest] = {}
        self.native_capabilities: dict[str, dict[str, Any]] = {}
        self.storage_policy: dict[str, Any] = {}
        self.loaded_at = ""
        self.lock_hash = ""
        self.reload()

    def bind_adapters(self, adapters: Any) -> None:
        """Attach current-host adapter evidence after adapter discovery."""

        self.adapters = adapters

    @staticmethod
    def _host_worker_classes() -> tuple[str, ...]:
        if os.name == "nt":
            return ("windows",)
        if os.environ.get("WSL_DISTRO_NAME"):
            return ("wsl",)
        if sys.platform.startswith("linux"):
            return ("container",)
        return ()

    def _runtime_readiness(self, tool: ToolManifest) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        host_workers = self._host_worker_classes()
        if not set(tool.workers).intersection(host_workers):
            blockers.append(
                {
                    "id": "host-worker",
                    "kind": "worker",
                    "status": "unprovisioned",
                    "requiredFor": ["execution", "production"],
                    "reason": (
                        "The current host worker class is not declared for this tool."
                    ),
                    "evidence": ",".join(host_workers) or "unknown",
                }
            )
        adapter_rows: list[dict[str, Any]] = []
        registry = self.adapters
        if registry is not None:
            for adapter_id in tool.adapters:
                adapter_rows.append(registry.descriptor(adapter_id).as_dict())
        executable_rows = [
            row
            for row in adapter_rows
            if bool(row.get("available")) and bool(row.get("supportsExecution"))
        ]
        if not executable_rows:
            blockers.append(
                {
                    "id": "live-adapter",
                    "kind": "service",
                    "status": "unavailable",
                    "requiredFor": ["execution", "production"],
                    "reason": (
                        "No current adapter is both available and execution-capable."
                    ),
                    "evidence": "",
                }
            )
        selected = executable_rows[0] if executable_rows else {}
        metadata = dict(selected.get("metadata") or {})
        identity_verified = bool(metadata.get("runtimeIdentityVerified", False))
        if not identity_verified:
            blockers.append(
                {
                    "id": "runtime-identity",
                    "kind": "executable",
                    "status": "unverified",
                    "requiredFor": ["execution", "production"],
                    "reason": (
                        "The current executable existence, version, and hash "
                        "have not all been matched to the manifest."
                    ),
                    "evidence": str(
                        metadata.get("runtimeIdentityError")
                        or metadata.get("managedPathMissing")
                        or ""
                    ),
                }
            )
        blockers.sort(key=lambda item: (str(item["kind"]), str(item["id"])))
        return {
            "evaluated": registry is not None,
            "ready": registry is not None and not blockers,
            "blockedPrerequisites": blockers,
            "evidence": {
                "hostWorkerClasses": list(host_workers),
                "adapterId": str(selected.get("adapterId") or ""),
                "adapterKind": str(selected.get("kind") or ""),
                "executable": str(selected.get("executable") or ""),
                "resolvedVersion": str(metadata.get("resolvedVersion") or ""),
                "resolvedSha256": str(metadata.get("resolvedSha256") or ""),
                "runtimeIdentityVerified": identity_verified,
            },
        }

    def _tool_payload(
        self,
        tool: ToolManifest,
        *,
        include_operations: bool,
    ) -> dict[str, Any]:
        return tool.as_dict(
            include_operations=include_operations,
            runtime_readiness=self._runtime_readiness(tool),
        )

    def reload(self) -> None:
        payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        if payload.get("schema") != TOOL_SUITE_LOCK_SCHEMA:
            raise ValueError(
                f"Expected {TOOL_SUITE_LOCK_SCHEMA} in {self.lock_path}"
            )
        tools = [ToolManifest.from_payload(item) for item in payload.get("tools") or []]
        tool_ids = [item.tool_id for item in tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("Tool suite lock contains duplicate tool identifiers")
        if not tools:
            raise ValueError("Tool suite lock must contain at least one tool")
        native_rows: dict[str, dict[str, Any]] = {}
        for raw_row in payload.get("nativeCapabilities") or []:
            row = raw_row if isinstance(raw_row, dict) else {}
            capability_id = _required_text(
                row.get("capabilityId"), "nativeCapabilities.capabilityId"
            ).lower()
            if not CAPABILITY_ID_PATTERN.fullmatch(capability_id):
                raise ValueError(f"Invalid native capabilityId: {capability_id}")
            if capability_id in native_rows:
                raise ValueError(
                    f"Duplicate native capability ownership: {capability_id}"
                )
            services = normalized_strings(row.get("nativeServices"))
            if not services:
                raise ValueError(
                    f"Native capability {capability_id} must name nativeServices"
                )
            native_rows[capability_id] = {
                "capabilityId": capability_id,
                "executionOwner": "neyvia.native",
                "nativeServices": services,
                "reason": _required_text(
                    row.get("reason"), "nativeCapabilities.reason"
                ),
            }
        self.tools = {item.tool_id: item for item in tools}
        self.native_capabilities = native_rows
        self.storage_policy = dict(payload.get("storagePolicy") or {})
        self.loaded_at = utc_now()
        self.lock_hash = canonical_hash(
            {
                "storagePolicy": self.storage_policy,
                "tools": [
                    self.tools[key].as_dict(include_operations=True)
                    for key in sorted(self.tools)
                ],
                "nativeCapabilities": [
                    self.native_capabilities[key]
                    for key in sorted(self.native_capabilities)
                ],
            }
        )

    def describe(self, tool_id: str) -> dict[str, Any]:
        normalized = str(tool_id or "").strip().lower()
        try:
            return self._tool_payload(
                self.tools[normalized],
                include_operations=True,
            )
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {tool_id}") from exc

    @checked_action(check_tool_search)
    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        agent_ready_only: bool = False,
        execution_ready_only: bool = False,
    ) -> dict[str, Any]:
        terms = {
            term
            for term in str(query or "").casefold().replace("_", " ").split()
            if term
        }
        rows: list[tuple[float, ToolManifest, list[str], dict[str, Any]]] = []
        for tool in self.tools.values():
            payload = self._tool_payload(tool, include_operations=False)
            if agent_ready_only and not tool.agent_ready:
                continue
            if execution_ready_only and not payload["executionReady"]:
                continue
            fields = {
                "toolId": tool.tool_id,
                "name": tool.name,
                "upstream": tool.upstream,
                "features": " ".join(tool.features),
                "capabilities": " ".join(tool.capabilities),
                "adapters": " ".join(tool.adapters),
                "operations": " ".join(
                    f"{item.operation_id} {item.name} {item.description}"
                    for item in tool.operations
                ),
            }
            if not terms:
                score = 1.0
                matched = []
            else:
                score = 0.0
                matched: list[str] = []
                weights = {
                    "toolId": 10.0,
                    "name": 9.0,
                    "upstream": 6.0,
                    "operations": 6.0,
                    "capabilities": 5.0,
                    "features": 3.0,
                    "adapters": 3.0,
                }
                for field, text in fields.items():
                    normalized = text.casefold()
                    hits = sorted(term for term in terms if term in normalized)
                    if hits:
                        score += len(hits) * weights[field]
                        matched.extend(hits)
            if score > 0:
                rows.append((score, tool, sorted(set(matched)), payload))
        rows.sort(key=lambda item: (-item[0], item[1].tool_id))
        selected = rows[: max(1, min(int(limit), 50))]
        return {
            "schema": TOOL_SUITE_LOCK_SCHEMA,
            "query": str(query or ""),
            "results": [
                {
                    **payload,
                    "score": round(score, 3),
                    "matched": matched,
                }
                for score, tool, matched, payload in selected
            ],
            "summary": {
                "matches": len(rows),
                "returned": len(selected),
                "agentReadyOnly": bool(agent_ready_only),
                "executionReadyOnly": bool(execution_ready_only),
                "operationsDeferred": True,
            },
        }

    @checked_action(check_tool_snapshot)
    def snapshot(self, *, include_operations: bool = False) -> dict[str, Any]:
        rows = [
            self._tool_payload(
                self.tools[key],
                include_operations=include_operations,
            )
            for key in sorted(self.tools)
        ]
        return {
            "schema": TOOL_SUITE_LOCK_SCHEMA,
            "generatedAt": utc_now(),
            "loadedAt": self.loaded_at,
            "lockPath": str(self.lock_path),
            "lockHash": self.lock_hash,
            "operationsDeferred": not include_operations,
            "storagePolicy": dict(self.storage_policy),
            "tools": rows,
            "nativeCapabilities": [
                self.native_capabilities[key]
                for key in sorted(self.native_capabilities)
            ],
            "summary": {
                "tools": len(rows),
                "nativeCapabilities": len(self.native_capabilities),
                "planned": sum(1 for item in rows if item["state"] == "planned"),
                "installed": sum(1 for item in rows if item["state"] == "installed"),
                "verified": sum(1 for item in rows if item["state"] == "verified"),
                "blocked": sum(1 for item in rows if item["state"] == "blocked"),
                "agentReady": sum(1 for item in rows if item["agentReady"]),
                "contractReady": sum(1 for item in rows if item["contractReady"]),
                "executionReady": sum(1 for item in rows if item["executionReady"]),
                "productionReady": sum(1 for item in rows if item["productionReady"]),
                "typedOperations": sum(item["operationCount"] for item in rows),
            },
        }
