import test from "node:test";
import assert from "node:assert/strict";
import { missionRouteSelections, coherentRoutePatch, readComposerRoute, rememberComposerRoute, readConversationRoute, rememberConversationRoute, forgetConversationRoute } from "./neyviaChatRoute.js";
import { describeHiddenTurn, isRealRuntimeReplySource } from "./transcriptVisibility.js";

test("Claude subscription explicitly selects Hermes instead of a direct native API route", () => {
  const provider = "claude-subscription-directsdk-experimental";
  for (const runtimeId of ["neyvia-agent", "codex", "claude-code", "hermes"]) {
    assert.deepEqual(coherentRoutePatch("provider", provider, { runtimeId, model: "gpt-6-astra" }),
      { provider, runtimeId: "hermes", model: "sonnet", effort: "default" });
  }
});

test("Go model selection changes the actual runtime and strips exactly one provider prefix", () => {
  const route = coherentRoutePatch("model", "opencode-go/glm-5.3-flash", { runtimeId: "hermes", provider: "openai-codex", model: "gpt-5.6-sol" });
  assert.deepEqual(route, { runtimeId: "opencode", provider: "opencode-go", model: "glm-5.3-flash", effort: "default" });
  assert.equal(coherentRoutePatch("model", "glm-5.3", route).runtimeId, "opencode");
  assert.equal(coherentRoutePatch("model", "gpt-6-astra", route).runtimeId, "codex");
});

test("a GPT model explicitly selected through Go stays on Go", () => {
  assert.deepEqual(coherentRoutePatch("model", "opencode-go/gpt-5.6-luna"), {
    runtimeId: "opencode", provider: "opencode-go", model: "gpt-5.6-luna", effort: "default",
  });
});

test("DeepSeek V4.1 Flash selection reaches the Go provider", () => {
  assert.deepEqual(coherentRoutePatch("model", "opencode-go/deepseek-v4.1-flash"), {
    runtimeId: "opencode", provider: "opencode-go", model: "deepseek-v4.1-flash", effort: "default",
  });
});

test("the backend's actual failure and empty-result sources survive transcript filtering", () => {
  for (const source of ["backend-runtime-error", "backend-runtime-empty"]) {
    assert.equal(describeHiddenTurn({ role: "assistant", source, title: "The runtime failed before a readable reply.", detail: "No usable credentials found for provider 'opencode-go'." }), null);
    assert.equal(isRealRuntimeReplySource(source), false);
  }
});


test("composer selections survive reopening and remain scoped to their workspace", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  rememberComposerRoute(storage, "one", "executor", coherentRoutePatch("model", "opencode-go/glm-5.3-flash"));
  rememberComposerRoute(storage, "one", "executor", { effort: "medium" });
  assert.equal(readComposerRoute(storage, "one").runtime, "opencode");
  assert.equal(readComposerRoute(storage, "one").roles.executor.model, "glm-5.3-flash");
  assert.equal(readComposerRoute(storage, "one").roles.executor.effort, "medium");
  assert.deepEqual(readComposerRoute(storage, "two"), {});
});

test("native runtime survives model and provider changes, and stale reasoning resets", () => {
  const current = { runtimeId: "neyvia-agent", provider: "opencode-go", model: "glm-5.3-flash", effort: "max" };
  for (const [field, value] of [["model", "gpt-5.6-luna"], ["model", "opencode-go/kimi-k2.6"], ["provider", "openai-codex"]]) {
    const next = coherentRoutePatch(field, value, current);
    assert.equal(next.runtimeId, "neyvia-agent");
    assert.equal(next.effort, "default");
  }
});

test("an empty chat retains its own DeepSeek route while another chat is opened", () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key),
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const deepseek = { runtimeId: "neyvia-agent", provider: "opencode-go", model: "deepseek-v4.1-flash", effort: "max" };
  const luna = { runtimeId: "neyvia-agent", provider: "openai-codex", model: "gpt-6-luna", effort: "low" };
  rememberConversationRoute(storage, "conversation_empty", deepseek);
  rememberConversationRoute(storage, "conversation_other", luna);
  assert.deepEqual(readConversationRoute(storage, "conversation_empty"), deepseek);
  assert.deepEqual(readConversationRoute(storage, "conversation_other"), luna);
  forgetConversationRoute(storage, "conversation_empty");
  assert.equal(readConversationRoute(storage, "conversation_empty"), null);
});

test("switching away from DeepSeek Harness clears its route and survives reload", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  const previous = { runtimeId: "deepseek-harness", provider: "deepseek-harness", model: "", effort: "high" };
  const native = coherentRoutePatch("runtimeId", "neyvia-agent", previous);
  assert.deepEqual(native, { runtimeId: "neyvia-agent", provider: "openai-codex", model: "gpt-5.6-sol", effort: "default" });
  rememberComposerRoute(storage, "one", "executor", native);
  assert.equal(readComposerRoute(storage, "one").runtime, "neyvia-agent");
  assert.equal(readComposerRoute(storage, "one").roles.executor.provider, "openai-codex");
  const hermes = coherentRoutePatch("runtimeId", "hermes", native);
  rememberComposerRoute(storage, "one", "executor", hermes);
  assert.deepEqual(readComposerRoute(storage, "one").roles.executor, { runtimeId: "hermes", provider: "hermes", model: "", effort: "default" });
});

test("legacy saved Native plus DeepSeek Harness route is repaired on read", () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  values.set("neyvia.composer.route:one", JSON.stringify({
    runtime: "neyvia-agent",
    roles: { executor: { runtimeId: "neyvia-agent", provider: "deepseek-harness", model: "", effort: "default" } },
  }));
  const repaired = readComposerRoute(storage, "one");
  assert.equal(repaired.roles.executor.provider, "openai-codex");
  assert.equal(repaired.roles.executor.model, "gpt-5.6-sol");
  assert.equal(JSON.parse(values.get("neyvia.composer.route:one")).roles.executor.provider, "openai-codex");
});

test("mission launch preserves each prepared role and explicit model default", () => {
  const rows = missionRouteSelections(["planner", "executor", "verifier"], {planner:{model:"gpt-5.6-luna", provider:"openai-codex", effort:"low"}}, [{role:"verifier",model:"glm-5.3",provider:"opencode-go",effort:"max"}], "executor", {model:"glm-5.3-flash",provider:"opencode-go",effort:"default"});
  assert.deepEqual(rows.map(row => [row.role,row.model,row.effort]), [["planner","gpt-5.6-luna","low"],["executor","glm-5.3-flash","default"],["verifier","glm-5.3","max"]]);
});
