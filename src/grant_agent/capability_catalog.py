"""Capability-pack catalog, fast routing, and deterministic plan compiler."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .capability_adapters import CapabilityAdapterRegistry
from .capability_contracts import (
    CAPABILITY_CATALOG_SCHEMA,
    CAPABILITY_PLAN_SCHEMA,
    ArtifactSelector,
    CapabilityPack,
    CapabilitySpec,
    canonical_hash,
    normalized_strings,
    utc_now,
    validate_catalog_payload,
)
from .capability_runtime import CapabilityPermissionEngine
from .proofs_a_capabilities import checked_action, check_catalog, check_search, check_description, check_capability_plan


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9.+#_-]*")

QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "3d": ("blender", "mesh", "scene", "model", "unity", "gltf"),
    "ai": ("model", "assistant", "training", "evaluation", "automation"),
    "analyse": ("analyze", "analysis"),
    "android": ("adb", "emulator", "mobile", "app"),
    "book": ("literature", "manuscript", "publishing", "critic"),
    "camera": ("photo", "capture", "image"),
    "excel": ("spreadsheet", "workbook", "formula", "chart"),
    "ios": ("iphone", "xcode", "simulator", "mobile"),
    "latex": ("tex", "document", "compile", "pdf"),
    "mod": ("game", "modding", "unity", "asset"),
    "ocr": ("scan", "scanned", "extract", "document", "text"),
    "pdf": ("document", "page", "ocr", "citation"),
    "photo": ("image", "photography", "retouch"),
    "powerpoint": ("presentation", "slides", "deck"),
    "professor": ("teacher", "education", "curriculum", "grading"),
    "redteam": ("red-team", "security", "attacker", "audit"),
    "researcher": ("research", "science", "literature", "citation"),
    "student": ("education", "learning", "tutorial", "quiz", "flashcard"),
    "unity": ("game", "3d", "scene", "playtest", "build"),
    "video": ("media", "timeline", "transcode", "subtitle"),
    "word": ("document", "docx", "authoring", "tracked"),
    "writer": ("writing", "editor", "manuscript", "publishing"),
}


def _tokens(value: object) -> set[str]:
    return set(TOKEN_PATTERN.findall(str(value or "").lower()))


def _expanded_tokens(value: object) -> set[str]:
    tokens = _tokens(value)
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(QUERY_EXPANSIONS.get(token, ()))
    return expanded


class CapabilityRegistry:
    """Load validated packs once and provide bounded schema-free search."""

    def __init__(
        self,
        catalog_path: str | Path,
        *,
        adapters: CapabilityAdapterRegistry,
        extra_catalog_dir: str | Path | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.extra_catalog_dir = (
            Path(extra_catalog_dir) if extra_catalog_dir is not None else None
        )
        self.adapters = adapters
        self.packs: dict[str, CapabilityPack] = {}
        self.capabilities: dict[str, CapabilitySpec] = {}
        self._search_documents: dict[str, dict[str, set[str]]] = {}
        self.catalog_hash = ""
        self.loaded_at = ""
        self.load_errors: list[dict[str, str]] = []
        self.pack_sources: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Capability catalog not found: {self.catalog_path}"
            ) from exc
        packs = validate_catalog_payload(payload)
        pack_sources = {item.pack_id: str(self.catalog_path) for item in packs}
        known_capability_ids = {
            capability.capability_id
            for pack in packs
            for capability in pack.capabilities
        }
        load_errors: list[dict[str, str]] = []
        if self.extra_catalog_dir is not None and self.extra_catalog_dir.exists():
            for path in sorted(self.extra_catalog_dir.glob("*.json")):
                try:
                    extra_payload = json.loads(path.read_text(encoding="utf-8"))
                    if (
                        isinstance(extra_payload, dict)
                        and extra_payload.get("schema") == CAPABILITY_CATALOG_SCHEMA
                    ):
                        extra_packs = validate_catalog_payload(extra_payload)
                    else:
                        extra_packs = [CapabilityPack.from_payload(extra_payload)]
                    pending_pack_ids = [pack.pack_id for pack in extra_packs]
                    if len(pending_pack_ids) != len(set(pending_pack_ids)):
                        raise ValueError("Custom file contains duplicate pack identifiers")
                    pending_capability_ids = [
                        capability.capability_id
                        for pack in extra_packs
                        for capability in pack.capabilities
                    ]
                    if len(pending_capability_ids) != len(set(pending_capability_ids)):
                        raise ValueError("Custom file contains duplicate capability identifiers")
                    for pack in extra_packs:
                        if pack.pack_id in pack_sources:
                            raise ValueError(
                                f"Duplicate capability pack identifier: {pack.pack_id}"
                            )
                    collisions = sorted(
                        known_capability_ids.intersection(pending_capability_ids)
                    )
                    if collisions:
                        raise ValueError(
                            "Duplicate capability identifiers: " + ", ".join(collisions)
                        )
                    for pack in extra_packs:
                        packs.append(pack)
                        pack_sources[pack.pack_id] = str(path)
                    known_capability_ids.update(pending_capability_ids)
                except Exception as exc:
                    load_errors.append({"path": str(path), "error": str(exc)})
        self.packs = {item.pack_id: item for item in packs}
        self.capabilities = {
            capability.capability_id: capability
            for pack in packs
            for capability in pack.capabilities
        }
        self.catalog_hash = canonical_hash(
            [self.packs[key].as_dict() for key in sorted(self.packs)]
        )
        self.loaded_at = utc_now()
        self.load_errors = load_errors
        self.pack_sources = pack_sources
        self._search_documents = {}
        for capability in self.capabilities.values():
            pack = self.packs[capability.pack_id]
            self._search_documents[capability.capability_id] = {
                "id": _tokens(capability.capability_id),
                "name": _tokens(capability.name),
                "description": _tokens(capability.description),
                "verbs": set(capability.verbs),
                "roles": set(capability.roles).union(pack.roles),
                "types": set(capability.input_types).union(capability.output_types),
                "tags": set(capability.tags),
                "domains": set(pack.domains).union(_tokens(pack.name)),
            }

    def pack_rows(self, *, include_capabilities: bool = False) -> list[dict[str, Any]]:
        return [
            self.packs[key].as_dict(include_capabilities=include_capabilities)
            for key in sorted(self.packs)
        ]

    @checked_action(check_description)
    def describe(self, capability_id: str) -> dict[str, Any]:
        normalized = str(capability_id or "").strip().lower()
        capability = self.capabilities.get(normalized)
        if capability is None:
            raise KeyError(f"Unknown capability: {capability_id}")
        available, reason = self.adapters.available(capability.adapter)
        payload = capability.as_dict(
            available=available,
            availability_reason=reason,
        )
        payload["pack"] = self.packs[capability.pack_id].as_dict(
            include_capabilities=False
        )
        payload["adapterDescriptor"] = self.adapters.descriptor(
            capability.adapter
        ).as_dict()
        return payload

    @checked_action(check_search)
    def search(
        self,
        query: str,
        *,
        artifacts: list[ArtifactSelector] | tuple[ArtifactSelector, ...] = (),
        roles: list[str] | tuple[str, ...] = (),
        domains: list[str] | tuple[str, ...] = (),
        limit: int = 12,
        include_unavailable: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query_text = str(query or "").strip()
        query_tokens = _expanded_tokens(query_text)
        role_tokens = _expanded_tokens(" ".join(normalized_strings(roles)))
        domain_tokens = _expanded_tokens(" ".join(normalized_strings(domains)))
        artifact_tokens: set[str] = set()
        for artifact in artifacts:
            artifact_tokens.update(_expanded_tokens(artifact.name))
            artifact_tokens.update(_expanded_tokens(artifact.path))
            artifact_tokens.update(_expanded_tokens(artifact.media_type))
            suffix = Path(artifact.path).suffix.lower().lstrip(".") if artifact.path else ""
            if suffix:
                artifact_tokens.add(suffix)
        combined_tokens = query_tokens.union(role_tokens, domain_tokens, artifact_tokens)
        normalized_phrase = " ".join(sorted(query_tokens))

        scored: list[tuple[float, CapabilitySpec, bool, str, list[str]]] = []
        for capability_id, document in self._search_documents.items():
            capability = self.capabilities[capability_id]
            available, reason = self.adapters.available(capability.adapter)
            if not include_unavailable and not available:
                continue
            score = 0.0
            matched: list[str] = []
            weights = {
                "id": 9.0,
                "name": 8.0,
                "verbs": 7.0,
                "roles": 6.0,
                "types": 5.0,
                "tags": 4.0,
                "domains": 4.0,
                "description": 1.5,
            }
            for field, field_tokens in document.items():
                overlap = combined_tokens.intersection(field_tokens)
                if overlap:
                    score += len(overlap) * weights[field]
                    matched.extend(sorted(overlap))
            if query_text and query_text.lower() in capability.name.lower():
                score += 18.0
            if normalized_phrase and normalized_phrase in " ".join(
                sorted(document["name"].union(document["verbs"]))
            ):
                score += 4.0
            if role_tokens.intersection(document["roles"]):
                score += 8.0
            if domain_tokens.intersection(document["domains"]):
                score += 8.0
            if artifact_tokens.intersection(document["types"]):
                score += 10.0
            if not combined_tokens:
                score = 1.0
            if score <= 0:
                continue
            scored.append((score, capability, available, reason, sorted(set(matched))))

        scored.sort(
            key=lambda row: (
                -row[0],
                not row[2],
                row[1].capability_id,
            )
        )
        bounded = max(1, min(int(limit), 50))
        rows: list[dict[str, Any]] = []
        for score, capability, available, reason, matched in scored[:bounded]:
            row = capability.as_dict(
                available=available,
                availability_reason=reason,
                score=score,
            )
            row["matchedTerms"] = matched[:12]
            rows.append(row)
        duration_ms = (time.perf_counter() - started) * 1000.0
        return {
            "schema": CAPABILITY_CATALOG_SCHEMA,
            "query": query_text,
            "results": rows,
            "summary": {
                "returned": len(rows),
                "catalogCapabilities": len(self.capabilities),
                "catalogPacks": len(self.packs),
                "availableResults": sum(1 for item in rows if item["available"]),
                "durationMs": round(duration_ms, 3),
                "schemasDeferred": True,
            },
        }

    @checked_action(check_catalog)
    def snapshot(self, *, include_capabilities: bool = False) -> dict[str, Any]:
        adapter_snapshot = self.adapters.snapshot()
        available = 0
        for capability in self.capabilities.values():
            is_available, _reason = self.adapters.available(capability.adapter)
            available += int(is_available)
        return {
            "schema": CAPABILITY_CATALOG_SCHEMA,
            "catalogHash": self.catalog_hash,
            "loadedAt": self.loaded_at,
            "packs": self.pack_rows(include_capabilities=include_capabilities),
            "summary": {
                "packs": len(self.packs),
                "capabilities": len(self.capabilities),
                "availableCapabilities": available,
                "unavailableCapabilities": len(self.capabilities) - available,
                "schemasDeferred": not include_capabilities,
                "loadErrors": len(self.load_errors),
            },
            "adapters": adapter_snapshot,
            "loadErrors": list(self.load_errors),
            "packSources": dict(self.pack_sources),
        }


class CapabilityPlanner:
    """Compile selected capabilities into a transparent, permissioned stage graph."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        permission_engine: CapabilityPermissionEngine,
    ) -> None:
        self.registry = registry
        self.permission_engine = permission_engine

    @checked_action(check_capability_plan)
    def plan(
        self,
        goal: str,
        *,
        artifacts: list[ArtifactSelector] | tuple[ArtifactSelector, ...] = (),
        roles: list[str] | tuple[str, ...] = (),
        domains: list[str] | tuple[str, ...] = (),
        experience: str = "standard",
        permission_mode: str = "workspace_safe",
        approved_permissions: list[str] | tuple[str, ...] = (),
        max_capabilities: int = 4,
    ) -> dict[str, Any]:
        normalized_goal = str(goal or "").strip()
        if not normalized_goal:
            raise ValueError("goal is required")
        search = self.registry.search(
            normalized_goal,
            artifacts=artifacts,
            roles=roles,
            domains=domains,
            limit=max(12, int(max_capabilities) * 4),
            include_unavailable=True,
        )
        candidates = list(search["results"])
        if not candidates:
            raise ValueError("No capability matched the requested goal")

        maximum = max(1, min(int(max_capabilities), 8))
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        top_score = float(candidates[0].get("score") or 0.0)
        for candidate in candidates:
            capability_id = str(candidate["capabilityId"])
            if capability_id in selected_ids:
                continue
            score = float(candidate.get("score") or 0.0)
            if selected and score < max(6.0, top_score * 0.38):
                continue
            selected.append(candidate)
            selected_ids.add(capability_id)
            if len(selected) >= maximum:
                break
        if not selected:
            selected = [candidates[0]]

        required_permissions = sorted(
            {
                permission
                for item in selected
                for permission in (item.get("requiredPermissions") or [])
            }
        )
        decisions = self.permission_engine.decide(
            required_permissions,
            mode=permission_mode,
            approved_permissions=approved_permissions,
            workspace_scoped=True,
        )
        permission_summary = self.permission_engine.summarize(decisions)

        stages: list[dict[str, Any]] = []
        previous_stage_ids: list[str] = []
        if artifacts:
            inspect_steps = [
                {
                    "stepId": f"inspect_{index + 1}",
                    "kind": "artifact_inspection",
                    "adapter": "builtin.artifact.inspect",
                    "arguments": artifact.as_dict(),
                    "after": [],
                    "status": "ready" if artifact.path else "context_only",
                    "parallelSafe": True,
                }
                for index, artifact in enumerate(artifacts)
            ]
            stages.append(
                {
                    "stageId": "stage_0_inspect",
                    "label": "Inspect selected artifacts",
                    "parallelSafe": len(inspect_steps) > 1,
                    "steps": inspect_steps,
                }
            )
            previous_stage_ids = [item["stepId"] for item in inspect_steps]

        capability_steps: list[dict[str, Any]] = []
        for index, item in enumerate(selected, start=1):
            capability_steps.append(
                {
                    "stepId": f"capability_{index}",
                    "kind": "capability",
                    "capabilityId": item["capabilityId"],
                    "adapter": item["adapter"],
                    "after": list(previous_stage_ids),
                    "status": "ready" if item["available"] else "adapter_required",
                    "availabilityReason": item["availabilityReason"],
                    "requiredPermissions": list(item["requiredPermissions"]),
                    "resourceClass": item["resourceClass"],
                    "previewTypes": list(item["previewTypes"]),
                    "parallelSafe": item["resourceClass"] not in {"heavy", "remote"},
                }
            )
        stages.append(
            {
                "stageId": f"stage_{len(stages)}_capabilities",
                "label": "Run selected capabilities",
                "parallelSafe": all(
                    bool(item["parallelSafe"]) for item in capability_steps
                ),
                "steps": capability_steps,
            }
        )
        verify_dependencies = [item["stepId"] for item in capability_steps]
        stages.append(
            {
                "stageId": f"stage_{len(stages)}_verify",
                "label": "Verify outputs and assemble proof",
                "parallelSafe": False,
                "steps": [
                    {
                        "stepId": "verify_results",
                        "kind": "verification",
                        "verifiers": sorted(
                            {
                                str(item.get("verifier") or "evidence")
                                for item in selected
                            }
                        ),
                        "after": verify_dependencies,
                        "status": "ready",
                        "parallelSafe": False,
                    }
                ],
            }
        )

        unavailable = [
            item["capabilityId"] for item in selected if not item["available"]
        ]
        resource_classes = sorted(
            {str(item["resourceClass"]) for item in selected}
        )
        payload: dict[str, Any] = {
            "schema": CAPABILITY_PLAN_SCHEMA,
            "planId": f"capplan_{uuid.uuid4().hex[:20]}",
            "goal": normalized_goal,
            "summary": (
                f"{len(selected)} capabilities across "
                f"{len({item['packId'] for item in selected})} packs"
            ),
            "experience": str(experience or "standard").strip().lower(),
            "roles": normalized_strings(roles),
            "domains": normalized_strings(domains),
            "artifacts": [item.as_dict() for item in artifacts],
            "capabilityIds": [item["capabilityId"] for item in selected],
            "capabilities": selected,
            "stages": stages,
            "permissionMode": self.permission_engine.normalize_mode(permission_mode),
            "permissionSummary": permission_summary,
            "readiness": {
                "status": (
                    "blocked"
                    if permission_summary["denied"]
                    else "adapter_required"
                    if unavailable
                    else "approval_required"
                    if permission_summary["approvalRequired"]
                    else "ready"
                ),
                "unavailableCapabilities": unavailable,
                "missingAdapterCount": len(unavailable),
                "canCreateRun": not bool(permission_summary["denied"]),
                "canExecuteImmediately": (
                    not unavailable
                    and bool(permission_summary["canRunWithoutApproval"])
                ),
            },
            "estimated": {
                "resourceClasses": resource_classes,
                "heavyWorkerCount": sum(
                    1
                    for item in selected
                    if item["resourceClass"] in {"heavy", "accelerated", "remote"}
                ),
                "previewPhases": ["plan", "live", "result"],
                "modelSchemasLoaded": 0,
                "capabilitySchemasLoaded": len(selected),
            },
            "routing": {
                "searchDurationMs": search["summary"]["durationMs"],
                "candidatesConsidered": len(candidates),
                "schemasDeferred": True,
                "selectionStrategy": "deterministic_weighted_topk",
            },
            "createdAt": utc_now(),
        }
        payload["planHash"] = canonical_hash(
            {key: value for key, value in payload.items() if key != "planId"}
        )
        return payload
