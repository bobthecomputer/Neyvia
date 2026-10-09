export const OPENCODE_GO_CATALOG_SOURCE = "https://opencode.ai/docs/go/";
export const OPENCODE_GO_CATALOG_CHECKED_AT = "2026-09-24";
export const MANAGED_CLI_CATALOG_CHECKED_AT = "2026-07-30";
export const ASTRA_CATALOG_CHECKED_AT = "2026-09-05";
export const ASTRA_CATALOG_SOURCE = "https://developers.openai.com/api/docs/models/gpt-6-astra";

export const BOOTSTRAP_CODEX_REASONING_EFFORTS = Object.freeze({
  "gpt-6-astra": ["low", "medium", "high", "xhigh", "max"],
  "gpt-6-luna": ["low", "medium", "high", "xhigh", "max"],
  "gpt-5.6-sol": ["low", "medium", "high", "xhigh", "max", "ultra"],
  "gpt-5.6-terra": ["low", "medium", "high", "xhigh", "max", "ultra"],
  "gpt-5.6-luna": ["low", "medium", "high", "xhigh", "max"],
});

// A fallback must never resurrect an explicitly hidden or unavailable model.
export function mergeRouteModelOptions(catalog = {}, fallbackModels = []) {
  const rows = Array.isArray(catalog.models) ? catalog.models : [];
  const blocked = new Set(rows.filter(row => row && (
    row.selectable === false || row.deprecated === true || row.supportedInApi === false ||
    (row.visibility && row.visibility !== "list")
  )).map(row => String(row.id || row.slug || "").toLowerCase()));
  const detected = Array.isArray(catalog.selectableModels) ? catalog.selectableModels : [];
  const seen = new Set();
  return [...detected.map(row => row?.id || row?.slug), ...fallbackModels].filter(id => {
    if (!id) return false;
    const key = String(id).toLowerCase();
    if (seen.has(key) || blocked.has(key) || key.startsWith("gpt-5.3")) return false;
    seen.add(key);
    return true;
  });
}

export const MANAGED_CLI_RUNTIME_ROUTES = Object.freeze({
  codex: Object.freeze({
    provider: "openai-codex",
    defaultModel: "gpt-5.6-sol",
    models: Object.freeze(Object.keys(BOOTSTRAP_CODEX_REASONING_EFFORTS)),
    source: "local-codex-runtime-adapter",
  }),
  "kimi-code": Object.freeze({
    provider: "kimi-code",
    defaultModel: "k3",
    routineModel: "k3-256k",
    models: Object.freeze([
      "k3",
      "k3-256k",
      "kimi-for-coding",
      "kimi-for-coding-highspeed",
    ]),
    source: "https://www.kimi.com/code/docs/en/kimi-code/models.html",
  }),
  "claude-code": Object.freeze({
    provider: "claude-code",
    defaultModel: "sonnet",
    models: Object.freeze(["sonnet", "opus", "haiku", "fable"]),
    source: "https://code.claude.com/docs/en/cli-reference",
  }),
  "grok-build": Object.freeze({
    provider: "grok-build",
    defaultModel: "grok-4.5",
    models: Object.freeze(["grok-4.5"]),
    source: "https://docs.x.ai/build/cli/reference",
  }),
});

export function managedCliRouteForRuntime(runtimeId) {
  return MANAGED_CLI_RUNTIME_ROUTES[String(runtimeId || "").trim().toLowerCase()] || null;
}

export function routeModelsForRuntime(runtimeId, fallbackModels = []) {
  const route = managedCliRouteForRuntime(runtimeId);
  return route ? [...route.models] : [...fallbackModels];
}

// This list mirrors the provider's current advertised catalog. Keep legacy IDs
// out of this array so old saved routes can still render without being offered
// as normal choices for new work.
export const VERIFIED_OPENCODE_GO_MODEL_IDS = Object.freeze([
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
]);

export const VERIFIED_OPENCODE_GO_ROUTE_MODELS = Object.freeze(
  VERIFIED_OPENCODE_GO_MODEL_IDS.map(modelId => `opencode-go/${modelId}`),
);

export function routeModelDisplayLabel(value, fallback = "Not reported") {
  const raw = String(value || "").trim();
  if (!raw) return fallback;
  const normalized = raw.toLowerCase();
  if (normalized === "gpt-6-astra") return "GPT-6 Astra";
  if (normalized === "gpt-6-luna") return "GPT-6 Luna";
  const opencodeGoModel = normalized.startsWith("opencode-go/") ? normalized.split("/", 2)[1] : normalized;
  const opencodeGoLabels = {
    "grok-4.6": "Grok 4.6",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "glm-5.3-flash": "GLM 5.3 Flash",
    "glm-5.3": "GLM 5.3",
    "kimi-k3": "Kimi K3",
    "longcat-2.0": "LongCat 2.0",
    "deepseek-v4-flash-vision-exp": "DeepSeek V4 Flash Vision (experimental)",
    "muse-spark-1.3-contributor": "Muse Spark 1.3 Contributor",
    "muse-spark-1.2-contributor": "Muse Spark 1.2 Contributor",
    "qwen3.8-max": "Qwen3.8 Max",
    "qwen3.8-flash": "Qwen3.8 Flash",
    "hy4-preview": "Hy4 Preview",
    "hy3": "Hy3",
    "omen-alpha": "Omen Alpha",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "glm-5": "GLM 5",
    "glm-5.1": "GLM 5.1",
    "glm-5.2": "GLM 5.2",
    "hy3-preview": "HY3 Preview",
    "kimi-k2.5": "Kimi K2.5",
    "kimi-k2.6": "Kimi K2.6",
    "kimi-k2.7-code": "Kimi K2.7 Code",
    "mimo-v2-omni": "MiMo V2 Omni",
    "mimo-v2-pro": "MiMo V2 Pro",
    "mimo-v2.5": "MiMo V2.5",
    "mimo-v2.5-pro": "MiMo V2.5 Pro",
    "minimax-m2.5": "MiniMax M2.5",
    "minimax-m2.7": "MiniMax M2.7",
    "minimax-m3": "MiniMax M3",
    "qwen3.5-plus": "Qwen3.5 Plus",
    "qwen3.6-plus": "Qwen3.6 Plus",
    "qwen3.7-max": "Qwen3.7 Max",
    "qwen3.7-plus": "Qwen3.7 Plus",
  };
  if (opencodeGoLabels[opencodeGoModel]) return opencodeGoLabels[opencodeGoModel];
  if (["glm-5.2", "z-ai/glm-5.2", "openrouter/z-ai/glm-5.2", "opencode-go/glm-5.2"].includes(normalized)) {
    return "GLM 5.2";
  }
  if (normalized === "minimax-m3") return "MiniMax M3";
  if (normalized === "minimax-m3-thinking") return "MiniMax M3 Thinking";
  if (/^gpt-5\.6-(sol|terra|luna)$/.test(normalized)) {
    return `GPT-5.6 ${normalized.split("-").pop().replace(/^./, letter => letter.toUpperCase())}`;
  }
  return raw.replace(/^gpt(?=[-_]|\d)/i, "GPT");
}

/** Flatten the backend's public Models.dev/OpenCode catalog into picker rows. */
export function providerCatalogModelOptions(catalog = {}, query = "") {
  const needle = String(query || "").trim().toLocaleLowerCase();
  const providers = Array.isArray(catalog.providers) ? catalog.providers : [];
  return providers.flatMap(provider => {
    const providerId = String(provider?.id || "").trim();
    const providerName = String(provider?.name || providerId).trim();
    const models = Array.isArray(provider?.models) ? provider.models : [];
    return models.map(model => {
      const modelId = String(model?.id || "").trim();
      const routeId = String(model?.routeId || `${providerId}/${modelId}`).trim();
      return {
        providerId,
        providerName,
        providerConfigured: Boolean(provider?.configured),
        credentialsPresent: Boolean(provider?.credentialsPresent),
        routeListed: Boolean(model?.routeListed ?? model?.configured),
        providerSetupStatus: String(provider?.setupStatus || "setup-needed"),
        modelId,
        routeId,
        name: String(model?.name || modelId),
        description: String(model?.description || ""),
        reasoning: Boolean(model?.reasoning),
        toolCall: Boolean(model?.toolCall),
        attachment: Boolean(model?.attachment),
        modalities: Array.isArray(model?.inputModalities) ? model.inputModalities : [],
        contextLimit: model?.contextLimit || null,
        configured: Boolean(model?.configured),
      };
    }).filter(row => {
      if (!row.modelId || !row.providerId) return false;
      return !needle || `${row.providerName} ${row.providerId} ${row.name} ${row.modelId} ${row.description}`
        .toLocaleLowerCase().includes(needle);
    });
  }).sort((a, b) => Number(b.providerConfigured) - Number(a.providerConfigured) ||
    a.providerName.localeCompare(b.providerName) || a.name.localeCompare(b.name));
}

/** OpenCode owns the provider adapter, so preserve its exact provider/model ids. */
export function openCodeRouteForProviderModel(row) {
  if (!row?.providerId || !row?.modelId) return null;
  return {
    runtimeId: "opencode",
    provider: String(row.providerId),
    // Keep the scoped route model exactly as the provider catalog declares it.
    // The runtime boundary adds the provider prefix for wire IDs; prompt scope
    // must continue to match this unmodified provider/model pair.
    model: String(row.modelId),
    effort: "default",
  };
}

/** Native is deliberately a smaller set of known transports than OpenCode. */
export function nativeProviderTransport(providerId) {
  const provider = String(providerId || "").toLowerCase();
  if (["openai", "openai-codex"].includes(provider)) return "openai-compatible";
  if (["anthropic", "claude"].includes(provider)) return "anthropic-messages";
  if (["opencode", "opencode-go", "openrouter", "minimax", "minimax-coding-plan"].includes(provider)) return "provider-specific";
  return "opencode-only";
}
