from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_config import platform_config


MODEL_CATALOG_SCHEMA = "fluxio.model_catalog.v1"
DEPRECATED_CODEX_PREFIXES = ("gpt-5.3",)
DEFAULT_REASONING_EFFORTS = ["low", "medium", "high", "xhigh"]

BOOTSTRAP_CODEX_MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "gpt-6-astra",
        "label": "GPT-6 Astra",
        "description": "Complex reasoning, coding, research, and computer use. Account access required.",
        "defaultReasoningEffort": "low",
        "reasoningEfforts": ["low", "medium", "high", "xhigh", "max"],
        "multiAgentVersion": "",
    },
    {
        "id": "gpt-6-luna",
        "label": "GPT-6 Luna",
        "description": "Fast agentic coding model with adjustable reasoning.",
        "defaultReasoningEffort": "medium",
        "reasoningEfforts": ["low", "medium", "high", "xhigh", "max"],
        "multiAgentVersion": "",
    },
    {
        "id": "gpt-5.6-sol",
        "label": "GPT-5.6 Sol",
        "description": "Flagship model for complex professional work.",
        "defaultReasoningEffort": "low",
        "reasoningEfforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        "multiAgentVersion": "v2",
    },
    {
        "id": "gpt-5.6-terra",
        "label": "GPT-5.6 Terra",
        "description": "Balanced agentic coding model for everyday work.",
        "defaultReasoningEffort": "medium",
        "reasoningEfforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        "multiAgentVersion": "v2",
    },
    {
        "id": "gpt-5.6-luna",
        "label": "GPT-5.6 Luna",
        "description": "Fast and affordable agentic coding model.",
        "defaultReasoningEffort": "medium",
        "reasoningEfforts": ["low", "medium", "high", "xhigh", "max"],
        "multiAgentVersion": "v1",
    },
    {
        "id": "gpt-5.5",
        "label": "GPT-5.5",
        "description": "Frontier coding model.",
        "defaultReasoningEffort": "medium",
        "reasoningEfforts": DEFAULT_REASONING_EFFORTS,
        "multiAgentVersion": "",
    },
)


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.expanduser()).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path.expanduser())
    return result


def codex_model_cache_candidates(root: Path) -> list[Path]:
    config = platform_config(root)
    paths: list[Path] = []
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip()
    if codex_home:
        paths.append(Path(codex_home) / "models_cache.json")
    for name in ("FLUXIO_RUNTIME_HOME", "SYNTELOS_RUNTIME_HOME"):
        runtime_home = str(os.environ.get(name) or "").strip()
        if runtime_home:
            paths.append(Path(runtime_home) / ".codex" / "models_cache.json")
    paths.extend(
        [
            Path.home() / ".codex" / "models_cache.json",
            root / ".agent_control" / "models_cache.json",
            config.nas_projects_root / "syntelos" / "runtime" / "home" / ".codex" / "models_cache.json",
        ]
    )
    return _dedupe_paths(paths)


def _reasoning_efforts(row: dict[str, Any]) -> list[str]:
    raw = next(
        (
            row[key]
            for key in ("supported_reasoning_levels", "supportedReasoningLevels", "reasoningEfforts")
            if key in row
        ),
        None,
    )
    efforts: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        effort = str(item.get("effort") if isinstance(item, dict) else item or "").strip().lower()
        if effort and effort not in efforts:
            efforts.append(effort)
    return efforts if raw is not None else list(DEFAULT_REASONING_EFFORTS)


def _normalise_model(row: dict[str, Any], *, source: str, detected: bool) -> dict[str, Any] | None:
    model_id = str(row.get("slug") or row.get("id") or row.get("model") or "").strip()
    if not model_id:
        return None
    status = str(row.get("status") or "").strip().lower()
    deprecated = bool(row.get("deprecated") or row.get("is_deprecated")) or status == "deprecated"
    deprecated = deprecated or model_id.lower().startswith(DEPRECATED_CODEX_PREFIXES)
    visibility = str(row.get("visibility") or "list").strip().lower()
    supported_in_api = bool(row.get("supported_in_api", row.get("supportedInApi", True)))
    return {
        "id": model_id,
        "label": str(row.get("display_name") or row.get("displayName") or row.get("label") or model_id).strip(),
        "description": str(row.get("description") or "").strip(),
        "provider": "openai-codex",
        "defaultReasoningEffort": str(
            row.get("default_reasoning_level")
            or row.get("defaultReasoningEffort")
            or "medium"
        ).strip().lower(),
        "reasoningEfforts": _reasoning_efforts(row),
        "multiAgentVersion": str(row.get("multi_agent_version") or row.get("multiAgentVersion") or "").strip(),
        "supportedInApi": supported_in_api,
        "visibility": visibility,
        "detected": detected,
        "deprecated": deprecated,
        "selectable": supported_in_api and not deprecated and visibility == "list",
        "source": source,
    }


def build_model_catalog(root: Path, *, cache_paths: list[Path] | None = None) -> dict[str, Any]:
    root = root.resolve()
    models: dict[str, dict[str, Any]] = {}
    for row in BOOTSTRAP_CODEX_MODELS:
        normalised = _normalise_model(row, source="bootstrap", detected=False)
        if normalised:
            models[normalised["id"]] = normalised

    sources: list[dict[str, Any]] = []
    cache_payloads: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in codex_model_cache_candidates(root) if cache_paths is None else cache_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        fetched_at = _parse_timestamp(payload.get("fetched_at") or payload.get("fetchedAt"))
        cache_payloads.append((fetched_at or datetime.min.replace(tzinfo=timezone.utc), path, payload))

    for fetched_at, path, payload in sorted(cache_payloads, key=lambda item: item[0]):
        source = str(path)
        rows = payload.get("models") if isinstance(payload.get("models"), list) else []
        sources.append(
            {
                "path": source,
                "fetchedAt": str(payload.get("fetched_at") or payload.get("fetchedAt") or ""),
                "clientVersion": str(payload.get("client_version") or payload.get("clientVersion") or ""),
                "modelCount": len(rows),
            }
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalised = _normalise_model(row, source=source, detected=True)
            if normalised:
                existing = models.get(normalised["id"])
                if existing:
                    if not any(
                        key in row
                        for key in ("supported_reasoning_levels", "supportedReasoningLevels", "reasoningEfforts")
                    ):
                        normalised["reasoningEfforts"] = list(existing["reasoningEfforts"])
                    for key in ("label", "description", "defaultReasoningEffort", "multiAgentVersion"):
                        if not str(normalised.get(key) or "").strip() or (
                            key == "label" and normalised[key] == normalised["id"]
                        ):
                            normalised[key] = existing[key]
                models[normalised["id"]] = normalised

    order = [row["id"] for row in BOOTSTRAP_CODEX_MODELS]
    ordered = sorted(
        models.values(),
        key=lambda item: (
            item["deprecated"],
            order.index(item["id"]) if item["id"] in order else len(order),
            item["label"].lower(),
        ),
    )
    selectable = [item for item in ordered if item["selectable"]]
    deprecated = [item for item in ordered if item["deprecated"]]
    latest_source = max(cache_payloads, key=lambda item: item[0], default=None)
    latest_fetched_at = latest_source[0] if latest_source else None
    age_seconds = (
        max(0, int((datetime.now(timezone.utc) - latest_fetched_at).total_seconds()))
        if latest_fetched_at and latest_fetched_at.year > 1
        else None
    )
    result = {
        "schema": MODEL_CATALOG_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "automaticDetection": True,
        "sourceStatus": "detected" if cache_payloads else "bootstrap",
        "sourceAgeSeconds": age_seconds,
        "sourceStale": age_seconds is None or age_seconds > 7 * 24 * 60 * 60,
        "sources": sources,
        "models": ordered,
        "selectableModels": selectable,
        "deprecatedModels": deprecated,
    }

    from .proofs_c_models import check_catalog
    check_catalog(result, cache_payloads)
    return result
