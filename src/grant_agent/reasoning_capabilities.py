from __future__ import annotations

import re
from typing import Any


EFFORT_ORDER = ("none", "low", "medium", "high", "xhigh", "max")


def normalize_reasoning_effort(value: object, fallback: str = "default") -> str:
    compact = re.sub(r"[\s_-]+", "", str(value or "").strip().lower())
    aliases = {
        "": fallback,
        "default": "default",
        "balanced": "default",
        "normal": "default",
        "standard": "default",
        "minimal": "none",
        "off": "none",
        "none": "none",
        "low": "low",
        "medium": "medium",
        "med": "medium",
        "high": "high",
        "xhigh": "xhigh",
        "extrahigh": "xhigh",
        "veryhigh": "xhigh",
        "max": "max",
        "maximum": "max",
        "ultra": "ultra",
        "ultrareasoning": "ultra",
    }
    return aliases.get(compact, fallback)


def model_reasoning_capability(provider: object, model: object) -> dict[str, Any]:
    """Return only capabilities that are documented or deliberately unsupported.

    Unknown custom/provider models stay capability-light. This prevents Neyvia from
    inventing a reasoning parameter that the selected provider may reject.
    """
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_model.startswith("openai/"):
        normalized_model = normalized_model.split("/", 1)[1]
    if normalized_model.startswith(("opencode-go/", "opencodego/")):
        normalized_model = normalized_model.split("/", 1)[1]
    is_openai = normalized_provider in {"openai", "openai-codex", "codex"}
    if normalized_provider in {"opencode-go", "opencodego"} and normalized_model == "deepseek-v4.1-flash":
        return {
            "status": "documented",
            "supportedEfforts": ["low", "high", "max"],
            "wireParameter": "reasoning_effort",
            "source": "https://api-docs.deepseek.com/guides/thinking_mode/",
        }
    if normalized_provider in {"opencode-go", "opencodego", "zai"} and normalized_model == "glm-5.3-flash":
        return {
            "status": "documented",
            "supportedEfforts": ["low", "high", "max"],
            "wireParameter": "reasoning_effort",
            "source": "https://huggingface.co/zai-org/GLM-5.3-Flash",
        }
    if is_openai and normalized_model == "gpt-6-astra":
        return {
            "status": "documented",
            "supportedEfforts": ["low", "medium", "high", "xhigh", "max"],
            "wireParameter": "reasoning.effort",
            "source": "https://developers.openai.com/api/docs/models/gpt-6-astra",
        }
    if is_openai and normalized_model.startswith(("gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")):
        return {
            "status": "documented",
            "supportedEfforts": list(EFFORT_ORDER),
            "wireParameter": "reasoning.effort",
            "source": "openai-gpt-5.6-model-docs",
        }
    if is_openai and normalized_model.startswith("gpt-5.4"):
        return {
            "status": "documented",
            "supportedEfforts": ["none", "low", "medium", "high", "xhigh"],
            "wireParameter": "reasoning.effort",
            "source": "openai-gpt-5.4-model-docs",
        }
    if is_openai and normalized_model.startswith("gpt-5.3-codex"):
        return {
            "status": "documented",
            "supportedEfforts": ["low", "medium", "high", "xhigh"],
            "wireParameter": "reasoning.effort",
            "source": "openai-gpt-5.3-codex-model-docs",
        }
    if normalized_provider in {"minimax", "minimax-cn", "minimax-oauth", "minimax-portal"}:
        return {
            "status": "unsupported",
            "supportedEfforts": [],
            "wireParameter": "",
            "source": "minimax-provider-contract",
        }
    return {
        "status": "unknown",
        "supportedEfforts": [],
        "wireParameter": "",
        "source": "capability-light-default",
    }


def resolve_reasoning_effort(
    *,
    provider: object,
    model: object,
    requested_effort: object,
) -> dict[str, Any]:
    requested = normalize_reasoning_effort(requested_effort)
    capability = model_reasoning_capability(provider, model)
    supported = list(capability["supportedEfforts"])
    resolution = {
        "provider": str(provider or ""),
        "model": str(model or ""),
        "requestedEffort": requested,
        "effectiveEffort": "",
        "wireEffort": "",
        "strategy": "",
        **capability,
    }
    if requested in {"", "default"}:
        resolution["strategy"] = "provider_default"
        return resolution
    if requested == "ultra":
        resolution["strategy"] = "product_effort_not_emitted"
        return resolution
    if requested in supported:
        resolution["effectiveEffort"] = requested
        resolution["wireEffort"] = requested
        resolution["strategy"] = "exact"
        return resolution
    if supported and requested in EFFORT_ORDER:
        requested_index = EFFORT_ORDER.index(requested)
        lower_or_equal = [
            effort for effort in supported if EFFORT_ORDER.index(effort) <= requested_index
        ]
        if lower_or_equal:
            effective = lower_or_equal[-1]
            resolution["effectiveEffort"] = effective
            resolution["wireEffort"] = effective
            resolution["strategy"] = "clamped_to_supported"
            return resolution
    resolution["strategy"] = (
        "omitted_unsupported" if capability["status"] == "unsupported" else "omitted_unknown"
    )
    return resolution


def adapt_reasoning_route(route: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    requested = route.get("requestedEffort", route.get("effort", "default"))
    resolution = resolve_reasoning_effort(
        provider=route.get("provider"),
        model=route.get("model"),
        requested_effort=requested,
    )
    adapted = dict(route)
    adapted["effort"] = resolution["wireEffort"] or "default"
    return adapted, resolution
