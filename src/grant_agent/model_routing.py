from __future__ import annotations

from .proofs_c_models import checked

import re
from typing import Any


CORE_ROUTE_ROLES = ("planner", "executor", "verifier")
SPECIALIZED_EXECUTOR_ROUTE_ROLES = ("frontend_executor", "backend_executor")
ROUTE_ROLE_ORDER = (
    "planner",
    "frontend_executor",
    "backend_executor",
    "executor",
    "verifier",
)
ROUTE_OVERRIDE_ROLES = set(ROUTE_ROLE_ORDER)

MINIMAX_PROVIDER_IDS = {"minimax", "minimax-cn", "minimax-portal", "minimax-oauth"}
KIMI_CODE_PROVIDER_IDS = {"kimi", "kimi-code", "kimi-coding"}
LEGACY_MINIMAX_MODELS = {
    "minimax-m2.7",
    "minimax-m2.7-highspeed",
    "minimax/m2.7",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.7-highspeed",
}

FRONTEND_ROUTE_HINTS = (
    "front end",
    "front-end",
    "frontend",
    "ui",
    "ux",
    "react",
    "css",
    "visual",
    "browser",
    "web app",
)
BACKEND_ROUTE_HINTS = (
    "back end",
    "back-end",
    "backend",
    "api",
    "server",
    "database",
    "db",
    "service",
    "worker",
)


def canonical_route_model(provider: object, model: object) -> str:
    normalized_provider = str(provider or "").strip().lower()
    value = str(model or "").strip()
    if normalized_provider in {"openai", "openai-codex"} and value.lower() == "gpt-5.6":
        return "gpt-5.6-sol"
    if normalized_provider in MINIMAX_PROVIDER_IDS and value.lower() in LEGACY_MINIMAX_MODELS:
        return "MiniMax-M3"
    if normalized_provider in KIMI_CODE_PROVIDER_IDS:
        if value.lower() in {"k3", "kimi-k3"}:
            return "k3"
        if value.lower() in {"kimi-k2.7-code", "k2.7-code"}:
            return "kimi-for-coding"
    if normalized_provider == "opencode-go" and value.lower() == "k3":
        return "kimi-k3"
    return value


def normalize_route_effort(value: object, fallback: str = "") -> str:
    normalized = str(value or "").strip().lower().replace("_", " ")
    compact = re.sub(r"[\s-]+", "", normalized)
    if not compact:
        return fallback
    if compact in {"default", "balanced", "normal", "standard"}:
        return "default"
    if compact in {"none", "minimal", "min", "low"}:
        return "low" if compact != "none" else "none"
    if compact in {"medium", "med", "mid"}:
        return "medium"
    if compact == "high":
        return "high"
    if compact in {"xhigh", "extrahigh", "veryhigh"}:
        return "xhigh"
    if compact in {"max", "highest"}:
        return "max"
    return fallback


def normalize_route_role(value: object) -> str:
    normalized = _visible_text(value)
    if not normalized:
        return ""
    if "planner" in normalized or re.search(r"\bplan(?:ning)?\b", normalized):
        return "planner"
    if "verifier" in normalized or re.search(r"\bverif(?:y|ier|ication)\b", normalized):
        return "verifier"
    if _has_frontend_hint(normalized):
        return "frontend_executor"
    if _has_backend_hint(normalized):
        return "backend_executor"
    if "executor" in normalized or re.search(r"\bexec(?:ute|ution|utor)?\b", normalized):
        return "executor"
    return ""


@checked("dictation")
def parse_route_dictation(
    text: object,
    *,
    default_runtime: str = "",
    canonicalize_models: bool = True,
) -> dict[str, Any]:
    source_text = str(text or "").strip()
    rows_by_role: dict[str, dict[str, str]] = {}
    parsed_segments: list[dict[str, str]] = []
    warnings: list[str] = []
    last_role = ""

    for segment in _split_route_dictation(source_text):
        effort_only = _extract_effort(segment)
        model_row = _extract_model(segment)
        if not model_row:
            if effort_only and last_role and last_role in rows_by_role:
                rows_by_role[last_role]["effort"] = effort_only
                parsed_segments.append(
                    {
                        "segment": segment,
                        "role": last_role,
                        "action": "corrected_effort",
                        "effort": effort_only,
                    }
                )
            elif _looks_like_route_segment(segment):
                warnings.append(f"No model detected in segment: {segment}")
            continue

        role = normalize_route_role(segment)
        if not role:
            warnings.append(f"No route role detected for model {model_row['model']} in segment: {segment}")
            continue

        provider = _infer_provider(segment, model_row)
        model = model_row["model"]
        if canonicalize_models:
            model = canonical_route_model(provider, model)
        runtime_id = _infer_runtime_id(
            segment,
            provider=provider,
            model=model,
            default_runtime=default_runtime,
        )
        effort = effort_only or _default_effort_for_role(role)
        row = {
            "role": role,
            "provider": provider,
            "model": model,
            "effort": effort,
        }
        if runtime_id:
            row["runtimeId"] = runtime_id
        budget_class = _budget_class_for_role(role, model)
        if budget_class:
            row["budgetClass"] = budget_class
        task_type = _task_type_for_role(role)
        if task_type:
            row["taskType"] = task_type
        route_intent = _route_intent_for_role(role)
        if route_intent:
            row["routeIntent"] = route_intent
        rows_by_role[role] = row
        last_role = role
        parsed_segments.append(
            {
                "segment": segment,
                "role": role,
                "provider": provider,
                "model": model,
                "effort": effort,
            }
        )

    route_overrides = [
        rows_by_role[role]
        for role in ROUTE_ROLE_ORDER
        if role in rows_by_role
    ]
    return {
        "schema": "fluxio.route_dictation.v1",
        "sourceText": source_text,
        "routeOverrides": route_overrides,
        "parsedSegments": parsed_segments,
        "warnings": warnings,
        "status": "parsed" if route_overrides else "empty",
    }


def _visible_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("_", " "))


def _split_route_dictation(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[;\n]+", ",", normalized)
    normalized = re.sub(r"(?<!\d)\.(?!\d)", ",", normalized)
    normalized = re.sub(
        r"\b(?:and then|then|and)\b(?=\s+(?:go back to\s+|maybe\s+)?(?:gpt|glm|deep\s*seek|deepseek|minimax|kimi|k3|openrouter|opencode|cursor|composer|composite|grok))",
        ",",
        normalized,
        flags=re.IGNORECASE,
    )
    return [
        re.sub(r"\s+", " ", item).strip(" ,")
        for item in normalized.split(",")
        if re.sub(r"\s+", " ", item).strip(" ,")
    ]


def _extract_model(segment: str) -> dict[str, str]:
    lowered = _visible_text(segment)
    if re.search(r"\bgrok[\s-]*(?:v)?4(?:[\s.-]*5)?\b|\bgrok[\s-]*4\.5\b", lowered):
        return {"family": "cursor", "model": "grok-4-5"}

    if re.search(r"\b(?:composer|composite)[\s-]*(?:v)?2(?:[\s.-]*5)?(?:[\s-]*fast)?\b", lowered):
        return {"family": "cursor", "model": "composer-2.5"}

    if re.search(r"\b(?:k3|kimi[\s-]*k3)[\s-]*256k\b", lowered):
        return {"family": "kimi", "model": "k3-256k"}
    if re.search(r"\bkimi[\s-]*for[\s-]*coding[\s-]*highspeed\b", lowered):
        return {"family": "kimi", "model": "kimi-for-coding-highspeed"}
    if re.search(r"\bkimi[\s-]*for[\s-]*coding\b", lowered):
        return {"family": "kimi", "model": "kimi-for-coding"}
    if re.search(r"\bkimi[\s-]*k2[.\s-]*7[\s-]*code\b", lowered):
        return {"family": "kimi", "model": "kimi-k2.7-code"}
    if re.search(r"\b(?:kimi[\s-]*)?k3\b|\bkimi[\s-]*k3\b", lowered):
        return {"family": "kimi", "model": "k3"}

    deepseek_slug = re.search(r"\bdeepseek/(deepseek-[a-z0-9.-]+)\b", lowered)
    if deepseek_slug:
        return {"family": "deepseek", "model": f"deepseek/{deepseek_slug.group(1)}"}
    if re.search(r"\bdeep\s*seek\b|\bdeepseek\b", lowered):
        if re.search(r"\bv?4\s*flash\b|\bv4flash\b|\b4\s*flash\b", lowered):
            return {"family": "deepseek", "model": "deepseek/deepseek-v4-flash"}
        if re.search(r"\br1\b", lowered):
            return {"family": "deepseek", "model": "deepseek/deepseek-r1"}
        return {"family": "deepseek", "model": "deepseek/deepseek-chat"}

    glm = re.search(r"\b(?:z[-\s]?ai[/\s-]*)?glm[\s-]*(\d+(?:\.\d+)?)\b", lowered)
    if glm:
        return {"family": "glm", "model": f"z-ai/glm-{glm.group(1)}"}

    minimax = re.search(
        r"\bminimax[\s-]*(?:m)?(\d+(?:\.\d+)?)(?:[\s-]*(highspeed|thinking|free))?\b",
        lowered,
    )
    if minimax:
        suffix = f"-{minimax.group(2)}" if minimax.group(2) else ""
        return {"family": "minimax", "model": f"MiniMax-M{minimax.group(1)}{suffix}"}

    gpt = re.search(r"\bgpt[\s-]*(\d+(?:\.\d+)?)(?:[\s-]*(sol|terra|luna|mini|codex))?\b", lowered)
    if gpt:
        suffix = f"-{gpt.group(2)}" if gpt.group(2) else ""
        return {"family": "gpt", "model": f"gpt-{gpt.group(1)}{suffix}"}

    return {}


def _infer_provider(segment: str, model_row: dict[str, str]) -> str:
    lowered = _visible_text(segment)
    if "opencode go" in lowered or "opencode-go" in lowered or "opencodego" in lowered:
        return "opencode-go"
    if "kimi code" in lowered or "kimi-code" in lowered or "kimi coding" in lowered:
        return "kimi-code"
    if "cursor" in lowered or "composer" in lowered or "composite" in lowered or "grok" in lowered:
        return "cursor"
    if "openrouter" in lowered:
        return "openrouter"
    if "minimax" in lowered:
        return "minimax"
    if "openai api" in lowered:
        return "openai"
    if "codex" in lowered or model_row.get("family") == "gpt":
        return "openai-codex"
    if model_row.get("family") == "cursor":
        return "cursor"
    if model_row.get("family") == "kimi":
        return "kimi-code"
    if model_row.get("family") in {"glm", "deepseek"}:
        return "openrouter"
    return "openai-codex"


def _infer_runtime_id(
    segment: str,
    *,
    provider: str,
    model: str,
    default_runtime: str,
) -> str:
    lowered = _visible_text(segment)
    if "opencode" in lowered:
        return "opencode"
    if provider == "kimi-code":
        return "kimi-code"
    if "cursor" in lowered or provider == "cursor":
        return "cursor"
    if "openclaw" in lowered:
        return "openclaw"
    if "hermes" in lowered:
        return "hermes"
    if provider == "openrouter" or model.lower().startswith(("z-ai/", "deepseek/")):
        return "opencode"
    return str(default_runtime or "").strip().lower()


def _extract_effort(segment: str) -> str:
    lowered = _visible_text(segment)
    if re.search(r"\b(?:max|highest)\b", lowered):
        return "max"
    if re.search(r"\b(?:x\s*high|xhigh|extra\s*high|very\s*high)\b", lowered):
        return "xhigh"
    if re.search(r"\bhigh\b", lowered):
        return "high"
    if re.search(r"\b(?:medium|med|mid)\b", lowered):
        return "medium"
    if re.search(r"\b(?:low|minimal|min)\b", lowered):
        return "low"
    return ""


def _has_frontend_hint(text: str) -> bool:
    if re.search(r"\b(?:not|no)\s+(?:front\s*end|front-end|frontend|ui)\b", text):
        return False
    return any(hint in text for hint in FRONTEND_ROUTE_HINTS)


def _has_backend_hint(text: str) -> bool:
    if re.search(r"\b(?:not|no)\s+(?:back\s*end|back-end|backend|api|server)\b", text):
        return False
    return any(hint in text for hint in BACKEND_ROUTE_HINTS)


def _default_effort_for_role(role: str) -> str:
    return "high" if role in {"planner", "verifier"} else "medium"


def _budget_class_for_role(role: str, model: str) -> str:
    normalized_model = model.lower()
    if (
        "mini" in normalized_model
        or "flash" in normalized_model
        or normalized_model == "k3-256k"
    ):
        return "efficient"
    if role in {"frontend_executor", "backend_executor"}:
        return role.replace("_executor", "")
    return "premium"


def _task_type_for_role(role: str) -> str:
    if role == "frontend_executor":
        return "frontend_design"
    if role == "backend_executor":
        return "backend_engineering"
    if role == "verifier":
        return "verification"
    if role == "planner":
        return "planning"
    return "general_coding"


def _route_intent_for_role(role: str) -> str:
    if role == "frontend_executor":
        return "frontend_execution"
    if role == "backend_executor":
        return "backend_execution"
    if role == "planner":
        return "mission_planning_and_route_control"
    if role == "verifier":
        return "independent_verification"
    if role == "executor":
        return "general_execution"
    return ""


def _looks_like_route_segment(segment: str) -> bool:
    lowered = _visible_text(segment)
    return bool(
        normalize_route_role(lowered)
        or _extract_effort(lowered)
        or re.search(
            r"\b(?:gpt|glm|deep\s*seek|deepseek|minimax|kimi|k3|openrouter|opencode)\b",
            lowered,
        )
    )
