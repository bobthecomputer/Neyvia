from __future__ import annotations

OPENCODE_GO_CATALOG_SOURCE = "https://opencode.ai/docs/go/"
OPENCODE_GO_CATALOG_CHECKED_AT = "2026-09-24"

OPENCODE_GO_MODEL_IDS = (
    "grok-4.6",
    "gpt-5.6-luna",
    "glm-5.3-flash",
    "glm-5.3",
    "glm-5.2",
    "glm-5.1",
    "kimi-k3",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "longcat-2.0",
    "deepseek-v4-pro",
    "deepseek-v4.1-flash",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
    "mimo-v2.5",
    "mimo-v2.5-pro",
    "minimax-m3",
    "minimax-m2.7",
    "minimax-m2.5",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2-contributor",
    "qwen3.8-max",
    "qwen3.8-flash",
    "qwen3.7-max",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "hy4-preview",
    "hy3",
    "omen-alpha",
)

OPENCODE_GO_MODEL_ALIASES = {
    **{model_id: model_id for model_id in OPENCODE_GO_MODEL_IDS},
    "deepseek/deepseek-chat": "deepseek-v4-pro",
    "deepseek/deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek/deepseek-v4-pro": "deepseek-v4-pro",
    "deepseek-chat": "deepseek-v4-pro",
    "grok45": "grok-4.5",
    "grok-4-5": "grok-4.5",
    "glm5": "glm-5.1",
    "glm5.1": "glm-5.1",
    "glm5.2": "glm-5.2",
    "glm_5": "glm-5.1",
    "glm_5.1": "glm-5.1",
    "glm_5.2": "glm-5.2",
    "k3": "kimi-k3",
    "kimi-k2": "kimi-k2.6",
    "moonshotai/kimi-k3": "kimi-k3",
    "minimax-coding-plan/minimax-m2.5": "minimax-m2.5",
    "minimax-coding-plan/minimax-m3": "minimax-m3",
    "minimax/minimax-m2.5": "minimax-m2.5",
    "minimax/minimax-m2.7": "minimax-m2.7",
    "minimax/minimax-m3": "minimax-m3",
    "moonshotai/kimi-k2.6": "kimi-k2.6",
    "qwen/qwen3.6-plus": "qwen3.6-plus",
    "qwen/qwen3.7-max": "qwen3.7-max",
    "qwen/qwen3.7-plus": "qwen3.7-plus",
    "z-ai/glm-5": "glm-5.1",
    "z-ai/glm-5.1": "glm-5.1",
    "z-ai/glm-5.2": "glm-5.2",
    "zai/glm-5": "glm-5.1",
    "zai/glm-5.1": "glm-5.1",
    "zai/glm-5.2": "glm-5.2",
}


def normalize_opencode_go_model(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    normalized = cleaned.lower()
    for prefix in ("opencode-go/", "opencodego/", "opencode/"):
        if normalized.startswith(prefix):
            cleaned = cleaned.split("/", 1)[1]
            normalized = cleaned.lower()
            break
    if normalized.startswith("openrouter/"):
        nested = cleaned.split("/", 1)[1]
        return OPENCODE_GO_MODEL_ALIASES.get(nested.lower(), nested)
    return OPENCODE_GO_MODEL_ALIASES.get(normalized, cleaned)


def native_go_transport_args(model: str) -> list[str]:
    """Use the published Go protocol without substituting the requested model."""
    if model not in OPENCODE_GO_MODEL_IDS or model.startswith(("minimax-", "qwen")):
        raise RuntimeError("This Go model requires an OpenCode or custom connection. Select OpenCode, or choose a GLM, Kimi, DeepSeek or Luna model for Neyvia Native.")
    transport = "responses" if model.startswith(("gpt-", "grok-", "muse-")) else "chat-completions"
    return ["--base-url", "https://opencode.ai/zen/go/v1", "--api-key-env", "OPENCODE_GO_API_KEY", "--transport", transport]
