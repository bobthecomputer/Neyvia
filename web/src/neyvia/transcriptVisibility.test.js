import { dialogueBody } from "./transcriptVisibility.js";
/**
 * Guards for the filter that decides whether a message reaches the screen.
 *
 * This is the layer where "the backend has it but I can't see it" actually
 * happens. The tests below pin every recognised provider source, so renaming
 * one fails here instead of silently emptying a transcript, and pin that a
 * hidden turn can always say why it was hidden.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  describeHiddenTurn,
  isRealAgentDialogueSource,
  isRealRuntimeReplySource,
  REAL_AGENT_DIALOGUE_SOURCES,
  REAL_RUNTIME_REPLY_SOURCES,
  transcriptTurnText,
} from "./transcriptVisibility.js";

const assistantTurn = (overrides = {}) => ({
  role: "assistant",
  title: "Here is the answer you asked for.",
  source: "backend-model-message",
  pending: false,
  ...overrides,
});

/* ------------------------------------------------ recognised provider paths */

test("every recognised dialogue source is accepted", () => {
  // Pinning the list means a rename breaks a test, not a user's transcript.
  assert.deepEqual(
    [...REAL_AGENT_DIALOGUE_SOURCES],
    [
      "operator-submitted",
      "runtime-error",
    "backend-runtime-error",
    "backend-runtime-empty",
      "chat-cancelled",
      "chat-interrupted",
      "backend-model-message",
      "backend-runtime-reply",
      "runtime-stream",
      "runtime-compartment",
      "runtime_compartment",
    ],
  );
  for (const source of REAL_AGENT_DIALOGUE_SOURCES) {
    assert.equal(isRealAgentDialogueSource(source), true, `${source} must be shown`);
  }
});

test("provider replies are a subset that excludes the operator's own messages", () => {
  assert.equal(isRealRuntimeReplySource("operator-submitted"), false);
  for (const source of REAL_RUNTIME_REPLY_SOURCES) {
    assert.equal(isRealAgentDialogueSource(source), true);
  }
});

test("a failed request stays visible without claiming a provider reply", () => {
  assert.equal(describeHiddenTurn(assistantTurn({ source: "runtime-error", title: "The runtime could not answer this chat turn." })), null);
  assert.equal(isRealRuntimeReplySource("runtime-error"), false);
});

test("source matching tolerates casing and whitespace", () => {
  // A provider path that reports "Backend-Model-Message" is the same path.
  assert.equal(isRealAgentDialogueSource("  Backend-Model-Message  "), true);
});

test("a real assistant message with a known source is shown", () => {
  assert.equal(describeHiddenTurn(assistantTurn()), null);
});

/* --------------------------------------------- hidden turns explain themselves */

test("an unrecognised source explains itself instead of vanishing", () => {
  // The exact historical failure: backend returns a real reply, screen stays empty.
  const reason = describeHiddenTurn(assistantTurn({ source: "backend-model-reply-v2" }));

  assert.ok(reason, "an unrecognised source must produce a reason");
  assert.match(reason, /backend-model-reply-v2/);
  assert.match(reason, /REAL_AGENT_DIALOGUE_SOURCES/);
});

test("a turn with no text anywhere says so", () => {
  const reason = describeHiddenTurn({ role: "assistant", source: "backend-model-message" });
  assert.match(reason, /no text/i);
});

test("a pending turn is identified as pending rather than as missing", () => {
  assert.match(describeHiddenTurn(assistantTurn({ pending: true })), /pending/i);
});

test("a non-transcript role is named in the reason", () => {
  assert.match(describeHiddenTurn(assistantTurn({ role: "system" })), /role/i);
});

test("content classifiers are reported by name when they hide a turn", () => {
  const reason = describeHiddenTurn(assistantTurn(), {
    isRouteMetadataText: () => true,
  });
  assert.match(reason, /route metadata/i);
});

/* -------------------------------------------------------------- text gathering */

test("turn text is gathered from every field a provider might use", () => {
  // A reply carried in `content` must not be treated as an empty turn just
  // because it did not arrive in `title`.
  assert.equal(transcriptTurnText({ content: "from content" }), "from content");
  assert.equal(transcriptTurnText({ message: "from message" }), "from message");
  assert.equal(transcriptTurnText({ text: "from text" }), "from text");
  assert.equal(transcriptTurnText({ title: "a", detail: "b" }), "a\nb");
});


test("a successful live reply displays its text instead of the runtime receipt", () => {
  assert.equal(dialogueBody({ source: "backend-runtime-reply", title: "Bonjour !", detail: "Opencode · opencode-go/glm-5.3-flash · High · workspace" }), "Bonjour !");
  assert.equal(dialogueBody({ source: "backend-runtime-error", title: "Request failed", detail: "Credentials missing" }), "Credentials missing");
  assert.equal(dialogueBody({ source: "runtime-compartment", title: "Assistant", content: "Saved reply" }), "Saved reply");
});

test("a streaming reply displays incoming answer text ahead of progress detail", () => {
  assert.equal(dialogueBody({ source: "runtime-stream", title: "Hello, welcome!", detail: "Reasoning summary · plan" }), "Hello, welcome!");
  assert.equal(dialogueBody({ source: "runtime-pending", title: "Thinking...", detail: "Reasoning summary · plan" }), "Thinking...");
});
