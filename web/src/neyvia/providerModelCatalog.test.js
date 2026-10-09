import test from "node:test";
import assert from "node:assert/strict";
import { mergeRouteModelOptions, routeModelsForRuntime, routeModelDisplayLabel, VERIFIED_OPENCODE_GO_ROUTE_MODELS, BOOTSTRAP_CODEX_REASONING_EFFORTS, providerCatalogModelOptions, openCodeRouteForProviderModel, nativeProviderTransport } from "./providerModelCatalog.js";
import { OPENCODE_GO_REASONING_EFFORTS } from "./opencodeGoCapabilities.js";

test("DeepSeek V4.1 Flash is selectable through Go with the verified effort choices", () => {
  assert.ok(VERIFIED_OPENCODE_GO_ROUTE_MODELS.includes("opencode-go/deepseek-v4.1-flash"));
  assert.equal(routeModelDisplayLabel("opencode-go/deepseek-v4.1-flash"), "DeepSeek V4.1 Flash");
  assert.deepEqual(OPENCODE_GO_REASONING_EFFORTS["deepseek-v4.1-flash"], ["low", "high", "max"]);
});

test("runtime selection exposes Astra with documented efforts", () => {
  assert.ok(routeModelsForRuntime("codex").includes("gpt-6-astra"));
  assert.deepEqual(BOOTSTRAP_CODEX_REASONING_EFFORTS["gpt-6-astra"], ["low", "medium", "high", "xhigh", "max"]);
  assert.ok(routeModelsForRuntime("codex").includes("gpt-6-luna"));
  assert.equal(routeModelDisplayLabel("gpt-6-luna"), "GPT-6 Luna");
  assert.deepEqual(BOOTSTRAP_CODEX_REASONING_EFFORTS["gpt-6-luna"], ["low", "medium", "high", "xhigh", "max"]);
});

test("fallback choices cannot resurrect restricted or deprecated models", () => {
  const catalog = {models: [
    {id: "gpt-6-astra", selectable: false},
    {id: "hidden", visibility: "hide"},
    {id: "retired", deprecated: true},
  ], selectableModels: [{id: "new-model"}, {id: "gpt-5.6-sol"}]};
  assert.deepEqual(mergeRouteModelOptions(catalog, ["gpt-6-astra", "hidden", "retired", "gpt-5.6-sol", "gpt-5.3-codex", "custom"]), ["new-model", "gpt-5.6-sol", "custom"]);
  assert.deepEqual(mergeRouteModelOptions({}, ["gpt-6-astra", "gpt-6-astra"]), ["gpt-6-astra"]);
});

test("provider catalog preserves exact provider/model routing for OpenCode and surfaces setup truth", () => {
  // Sanitized Models.dev/OpenCode response shape; no credentials or config options.
  const catalog = {
    providerCount: 2,
    modelCount: 2,
    providers: [
      {id: "deepinfra", name: "Deep Infra", configured: false, setupStatus: "setup-needed", models: [
        {id: "deepseek-ai/DeepSeek-V3.2", name: "DeepSeek V3.2", routeId: "deepinfra/deepseek-ai/DeepSeek-V3.2", configured: false, reasoning: true, toolCall: true, inputModalities: ["text"]},
      ]},
      {id: "opencode-go", name: "OpenCode Go", configured: true, setupStatus: "configured", models: [
        {id: "deepseek-v4.1-flash", name: "DeepSeek V4.1 Flash", routeId: "opencode-go/deepseek-v4.1-flash", configured: true, reasoning: true, toolCall: true, inputModalities: ["text", "image"]},
      ]},
    ],
  };
  const rows = providerCatalogModelOptions(catalog);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].providerId, "opencode-go", "connected routes sort before setup-needed routes");
  assert.deepEqual(openCodeRouteForProviderModel(rows[0]), {
    runtimeId: "opencode", provider: "opencode-go", model: "deepseek-v4.1-flash", effort: "default",
  });
  assert.deepEqual(openCodeRouteForProviderModel(rows[1]), {
    runtimeId: "opencode", provider: "deepinfra", model: "deepseek-ai/DeepSeek-V3.2", effort: "default",
  });
  assert.equal(providerCatalogModelOptions(catalog, "deep infra").length, 1);
  assert.equal(rows.find(row => row.providerId === "deepinfra").providerSetupStatus, "setup-needed");
});

test("catalog distinguishes OpenCode availability from Native transport support", () => {
  assert.equal(nativeProviderTransport("openai"), "openai-compatible");
  assert.equal(nativeProviderTransport("anthropic"), "anthropic-messages");
  assert.equal(nativeProviderTransport("deepinfra"), "opencode-only");
  const [row] = providerCatalogModelOptions({providers:[{id:"deepinfra",models:[{id:"m",name:"M"}]}]}, "m");
  assert.deepEqual(openCodeRouteForProviderModel(row), {runtimeId:"opencode",provider:"deepinfra",model:"m",effort:"default"});
});
