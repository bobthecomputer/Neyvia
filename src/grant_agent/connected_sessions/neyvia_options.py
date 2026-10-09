"""What Neyvia offers for a chat: runtimes, models and permission modes.

The rows mirror the classic composer's pickers (``harness_registry.runtime_picker_choices``, the
Codex model catalog, the OpenCode Go and managed-CLI model lists) and the rules in
``send_agent_chat_command``, so the redesigned composer offers exactly what a send can honour.

A model row's ``id`` is ``<runtime>|<provider>|<model>``. ``TurnOptions`` has no runtime field, so
this one string carries the whole route; a bare model id is accepted too and keeps the session's
runtime and provider.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

NATIVE_RUNTIME = "neyvia-agent"
DEFAULT_PERMISSION_MODE = "read-only"

# Order of the runtime picker: Native first, then the harnesses people reach for most.
_RUNTIME_ORDER = ("neyvia-agent", "codex", "claude-code", "hermes", "opencode", "grok-build", "kimi-code",
                  "openclaw", "cursor")
_MODES = (
    ("read-only", "Read only", "Inspect the conversation without local actions."),
    ("workspace", "Workspace", "Use the selected harness's workspace editing mode and supported workspace tools."),
    ("full-access", "Full access", "Allow the selected harness to run commands without local approval prompts. "
     "Commands can access this computer, its files, and network. The workspace is the default working "
     "directory, not a sandbox."),
)
# Permission modes each runtime honours; any other mode is downgraded to read-only by the backend.
_WORKSPACE_MODE_RUNTIMES = frozenset({NATIVE_RUNTIME, "codex", "claude-code"})
_FULL_ACCESS_RUNTIMES = _WORKSPACE_MODE_RUNTIMES | {"hermes"}
_WORDS = {"gpt": "GPT", "glm": "GLM", "deepseek": "DeepSeek", "kimi": "Kimi", "longcat": "LongCat", "mimo": "MiMo",
          "minimax": "MiniMax", "qwen": "Qwen", "grok": "Grok"}


def normalize_runtime(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def is_native(runtime: Any) -> bool:
    return normalize_runtime(runtime) in {NATIVE_RUNTIME, "neyvia", "own"}


def route_id(runtime: str, provider: str, model: str) -> str:
    return f"{runtime}|{provider}|{model}"


def parse_route_id(value: Any) -> tuple[str, str, str] | None:
    parts = str(value or "").split("|")
    return (parts[0].strip(), parts[1].strip(), parts[2].strip()) if len(parts) == 3 and parts[0].strip() else None


def model_label(model: str, catalog_label: str = "") -> str:
    """A human model name: 'gpt-5.6-sol' -> 'GPT-5.6 Sol', 'deepseek-v4.1-flash' -> 'DeepSeek V4.1 Flash'."""
    if " " in catalog_label.strip():
        return catalog_label.strip()  # the catalog already spells it for people
    tokens = [token for token in re.split(r"-", model.split("/")[-1]) if token]
    if not tokens:
        return model
    if tokens[0].lower() == "gpt" and len(tokens) > 1:
        rest = " ".join(word.capitalize() for word in tokens[2:])
        return f"GPT-{tokens[1]}" + (f" {rest}" if rest else "")
    return " ".join(_WORDS.get(token.lower()) or token[:1].upper() + token[1:] for token in tokens)


def runtime_permission_modes(runtime: str) -> list[str]:
    runtime = normalize_runtime(runtime)
    return [mode for mode, _, _ in _MODES
            if mode == "read-only"
            or (mode == "workspace" and runtime in _WORKSPACE_MODE_RUNTIMES)
            or (mode == "full-access" and runtime in _FULL_ACCESS_RUNTIMES)]


def permission_mode_rows() -> list[dict[str, Any]]:
    return [{"id": mode, "label": label, "description": text} for mode, label, text in _MODES]


def runtime_rows() -> list[dict[str, Any]]:
    from ..harness_registry import runtime_picker_choices

    choices = {row["value"]: row for row in runtime_picker_choices() if not row.get("securityOnly")}
    ordered = [name for name in _RUNTIME_ORDER if name in choices] + sorted(set(choices) - set(_RUNTIME_ORDER))
    return [{"id": name, "label": choices[name].get("label") or name,
             "category": "native" if name == NATIVE_RUNTIME else "hybrid",
             "defaultModel": choices[name].get("defaultModel") or None,
             "permissionModes": runtime_permission_modes(name)} for name in ordered]


def _codex_models(root: Path) -> list[dict[str, Any]]:
    from ..model_catalog import build_model_catalog

    rows = []
    for item in build_model_catalog(root).get("selectableModels") or []:
        efforts = [effort for effort in item.get("reasoningEfforts") or [] if effort != "ultra"]
        rows.append({"model": item["id"], "label": model_label(item["id"], str(item.get("label") or "")),
                     "efforts": efforts, "defaultEffort": item.get("defaultReasoningEffort") or None})
    return rows


def _go_models() -> list[dict[str, Any]]:
    from ..opencode_go_models import OPENCODE_GO_MODEL_IDS
    from ..reasoning_capabilities import model_reasoning_capability

    rows = []
    for model in OPENCODE_GO_MODEL_IDS:
        if model.startswith(("minimax-", "qwen")):
            continue  # Neyvia Native cannot drive these; they need the OpenCode or a custom connection
        capability = model_reasoning_capability("opencode-go", model)
        efforts = list(capability["supportedEfforts"]) if capability.get("status") == "documented" else []
        rows.append({"model": model, "label": model_label(model), "efforts": efforts, "defaultEffort": None})
    return rows


def _plain_models(models: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"model": model, "label": model_label(model), "efforts": [], "defaultEffort": None} for model in models]


def model_rows(root: Path) -> list[dict[str, Any]]:
    """Every (runtime, provider, model) route the composer can pick, in picker order."""
    from ..runtimes.managed_cli import CLAUDE_AGENT_MODEL_ALIASES, KIMI_CODE_MODEL_IDS

    codex = _codex_models(root)
    groups = (
        (NATIVE_RUNTIME, "openai-codex", codex),
        (NATIVE_RUNTIME, "opencode-go", _go_models()),
        ("codex", "openai-codex", codex),
        ("claude-code", "claude-code", _plain_models(tuple(CLAUDE_AGENT_MODEL_ALIASES))),
        ("kimi-code", "kimi-code", _plain_models(tuple(KIMI_CODE_MODEL_IDS))),
        ("grok-build", "grok-build", _plain_models(("grok-4.5",))),
    )
    labels = {row["id"]: row["label"] for row in runtime_rows()}
    rows = []
    for runtime, provider, models in groups:
        for item in models:
            rows.append({"id": route_id(runtime, provider, item["model"]), "label": item["label"],
                         "runtime": runtime, "provider": provider, "model": item["model"],
                         "group": labels.get(runtime, runtime) + (" · OpenCode Go" if provider == "opencode-go" else ""),
                         "efforts": item["efforts"], "defaultEffort": item["defaultEffort"], "default": False})
    return rows
