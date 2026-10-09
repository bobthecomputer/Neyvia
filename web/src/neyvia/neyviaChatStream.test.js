import test from "node:test";
import assert from "node:assert/strict";
import { applyNeyviaChatStreamEvents, createNeyviaChatStreamState, neyviaChatTraceFields } from "./neyviaChatStream.js";
import { mergeStreamedTrace } from "./neyviaChatRecovery.js";

test("provider summaries and tools retain their stream order while tool status updates stay in place", () => {
  const state = createNeyviaChatStreamState();
  applyNeyviaChatStreamEvents(state, [
    {kind: "runtime.reasoning_summary_delta", message: "Plan "},
    {kind: "runtime.reasoning_summary_delta", message: "first."},
    {kind: "runtime.tool", data: {callId: "a", tool: "search", toolStatus: "started"}},
    {kind: "runtime.reasoning_summary_delta", message: "Next step."},
    {kind: "runtime.tool", data: {callId: "a", tool: "search", toolStatus: "completed", output: "found"}},
    {kind: "runtime.tool", data: {callId: "b", tool: "read", toolStatus: "completed"}},
  ]);
  assert.deepEqual(state.activitySegments.map(segment => segment.kind === "tool"
    ? {kind: segment.kind, id: segment.id, status: segment.status}
    : {kind: segment.kind, id: segment.id, text: segment.text}), [
    {kind: "reasoning_summary", id: "reasoning-1", text: "Plan first."},
    {kind: "tool", id: "a", status: "completed"},
    {kind: "reasoning_summary", id: "reasoning-2", text: "Next step."},
    {kind: "tool", id: "b", status: "completed"},
  ]);
});

test("automatic context compaction has a distinct live state that clears when work resumes", () => {
  const state = createNeyviaChatStreamState();
  assert.equal(state.compacting, false);
  applyNeyviaChatStreamEvents(state, [{
    kind: "runtime.progress",
    message: "Compacting saved conversation automatically",
    data: {eventType: "context.compaction.started"},
  }]);
  assert.equal(state.compacting, true);
  assert.equal(state.detail, "Compacting saved conversation automatically");

  applyNeyviaChatStreamEvents(state, [{
    kind: "runtime.progress",
    message: "Compacting saved conversation",
    data: {eventType: "context.compaction.progress", summaryCalls: 2},
  }]);
  assert.equal(state.compacting, true);

  applyNeyviaChatStreamEvents(state, [{
    kind: "runtime.progress",
    message: "Conversation compacted; continuing",
    data: {eventType: "context.compaction.completed"},
  }]);
  assert.equal(state.compacting, false);
  assert.equal(state.detail, "Conversation compacted; continuing");
});

test("saved receipt timeline restores chronology, while legacy combined fields report unknown order", () => {
  const ordered = neyviaChatTraceFields({turnReceipt: {toolTimeline: [
    {kind: "runtime.reasoning_summary", message: "Before"},
    {kind: "runtime.tool", data: {callId: "a", tool: "search", status: "completed"}},
    {kind: "runtime.reasoning_summary", message: "After"},
  ]}});
  assert.equal(ordered.activityOrderKnown, true);
  assert.deepEqual(ordered.activitySegments.map(item => item.kind), ["reasoning_summary", "tool", "reasoning_summary"]);

  const legacy = neyviaChatTraceFields({reasoningSummary: "Summary", toolCalls: [{id: "a", tool: "search", status: "completed"}]});
  assert.equal(legacy.activityOrderKnown, false);
  assert.deepEqual(legacy.activitySegments.map(item => item.kind), ["reasoning_summary", "tool"]);
  assert.equal(neyviaChatTraceFields({...legacy, reasoningSummary: "Summary", toolCalls: [{id: "a", tool: "search", status: "completed"}]}).activityOrderKnown, false);
});

test("stream recovery carries the ordered public activity segments onto the restored turn", () => {
  const segments = [
    {kind: "reasoning_summary", id: "reasoning-1", text: "Check"},
    {kind: "tool", id: "x", tool: "read", status: "completed"},
  ];
  const restored = mergeStreamedTrace({id: "turn", title: "Thinking", pending: true}, {
    answer: "Done", activitySegments: segments, toolCalls: [segments[1]],
  });
  assert.deepEqual(restored.activitySegments, segments);
  assert.equal(restored.activityOrderKnown, true);
});

test("full summaries and every ordered activity segment survive normalization", () => {
  const state = createNeyviaChatStreamState();
  const longSummary = "provider summary ".repeat(180);
  const events = [{kind: "runtime.reasoning_summary_delta", message: longSummary}];
  for (let index = 0; index < 55; index += 1) {
    events.push({kind: "runtime.tool", data: {callId: `call-${index}`, tool: "read", status: "completed"}});
    events.push({kind: "runtime.reasoning_summary_delta", message: `step ${index}.`});
  }
  applyNeyviaChatStreamEvents(state, events);
  const trace = neyviaChatTraceFields({reasoningSummary: state.reasoningSummary, activitySegments: state.activitySegments, toolCalls: state.toolCalls});
  const streamedSummaryLength = Array.from({length: 55}, (_, index) => `step ${index}.`).join("").length;
  assert.equal(trace.reasoningSummary.length, longSummary.length + streamedSummaryLength);
  assert.equal(trace.activitySegments.length, 111);
  assert.equal(trace.toolCalls.length, 55);
  assert.equal(trace.activitySegments.at(-1).text, "step 54.");
});

test("saved raw reasoning events are ignored; only public summary kinds are rendered", () => {
  const trace = neyviaChatTraceFields({turnReceipt: {toolTimeline: [
    {kind: "runtime.reasoning", message: "private chain content"},
    {kind: "runtime.reasoning_summary", message: "public summary"},
  ]}});
  assert.deepEqual(trace.activitySegments.map(segment => segment.text), ["public summary"]);
  assert.equal(trace.activitySegments.some(segment => segment.text.includes("private chain")), false);
});

test("provider reasoning deltas require the explicit public source and stay interleaved", () => {
  const state = createNeyviaChatStreamState();
  applyNeyviaChatStreamEvents(state, [
    {kind: "runtime.thinking_delta", message: "Thinking ", data: {source: "provider.reasoning_content", responseId: "r1", itemId: "i1", outputIndex: 0}},
    {kind: "runtime.thinking_delta", message: "before tool", data: {source: "provider.reasoning_content", responseId: "r1", itemId: "i1", outputIndex: 0}},
    {kind: "runtime.tool", data: {callId: "t1", tool: "search", status: "completed"}},
    {kind: "runtime.thinking_delta", message: "Thinking after tool", data: {source: "provider.reasoning_content", responseId: "r1", itemId: "i2", outputIndex: 1}},
    {kind: "runtime.thinking_delta", message: "must remain hidden", data: {responseId: "r1", itemId: "i3", outputIndex: 2}},
    {kind: "runtime.reasoning_summary_delta", message: "Provider summary after tool."},
  ]);
  assert.deepEqual(state.activitySegments.map(({kind, text}) => ({kind, text})), [
    {kind: "thinking_text", text: "Thinking before tool"},
    {kind: "tool", text: undefined},
    {kind: "thinking_text", text: "Thinking after tool"},
    {kind: "reasoning_summary", text: "Provider summary after tool."},
  ]);
  assert.equal(state.activitySegments.some(segment => segment.text?.includes("must remain hidden")), false);

  const restored = neyviaChatTraceFields({turnReceipt: {toolTimeline: [
    {kind: "runtime.reasoning_summary", message: "Summary before"},
    {kind: "runtime.tool", data: {callId: "restore-tool", tool: "read", status: "completed"}},
    {kind: "runtime.thinking", data: {source: "provider.reasoning_content", message: "Thinking restored after"}},
  ]}});
  assert.deepEqual(restored.activitySegments.map(({kind, text}) => ({kind, text})), [
    {kind: "reasoning_summary", text: "Summary before"},
    {kind: "tool", text: undefined},
    {kind: "thinking_text", text: "Thinking restored after"},
  ]);
});

test("long provider thinking survives streaming, serialization and restored history without truncation", () => {
  const state = createNeyviaChatStreamState();
  const text = "Full provider thinking line.\n".repeat(8000) + "END_OF_THINKING";
  applyNeyviaChatStreamEvents(state, [{kind: "runtime.thinking_delta", message: text, data: {source: "provider.reasoning_content", responseId: "long"}}]);
  const restored = neyviaChatTraceFields(JSON.parse(JSON.stringify({activitySegments: state.activitySegments})));
  assert.equal(restored.activitySegments[0].text, text);
});
