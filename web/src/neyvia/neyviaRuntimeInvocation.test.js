/**
 * Guards for the behaviours a user actually feels in the transcript.
 *
 * The repository had 146 backend tests and no frontend tests. That distribution
 * cannot catch this product's worst historical failure — the backend holding
 * real assistant messages while the interface showed nothing, or showed a
 * progress label where a reply belonged. A backend test passes happily in both
 * cases. These tests exist specifically to fail in those cases.
 *
 * Three promises are pinned here, because they are the ones that quietly break:
 *   1. Real assistant content survives into the transcript, and absent content
 *      is never replaced by an invented message.
 *   2. Opening a runtime inline never disturbs the conversation around it.
 *   3. Collapsing and expanding an inline window preserves the session rather
 *      than restarting it.
 *
 * Runs on Node's built-in test runner: `npm run test:frontend`. No test
 * framework dependency, so this guard cannot be skipped for being inconvenient.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  canTransitionInvocation,
  closeRuntimeInvocation,
  createRuntimeInvocation,
  emptyRuntimeInvocationRegistry,
  isInvocationResumable,
  invocationsOwnedBySession,
  NEYVIA_INVOCATION_PRESENTATIONS,
  recordRuntimeReturn,
  selectInlineInvocations,
  selectPrimaryRuntimeInvocation,
  transitionRuntimeInvocation,
  upsertRuntimeInvocation,
} from "./neyviaRuntimeInvocation.js";

/** A runtime the backend has confirmed is usable. */
const READY = { ready: true, state: "ready", detail: "test fixture" };

function readyInvocation(overrides = {}) {
  return createRuntimeInvocation({
    runtime: "claude-code",
    readiness: READY,
    ...overrides,
  });
}

/* ------------------------------------------------- 1. transcript integrity */

test("real assistant text survives into the transcript verbatim", () => {
  const invocation = transitionRuntimeInvocation(readyInvocation(), "active");
  const reply = "Here is the migration plan:\n\n1. Add the column\n2. Backfill";

  const returned = recordRuntimeReturn(invocation, {
    messages: [{ role: "assistant", content: reply }],
  });

  assert.equal(returned.returns.messages.length, 1);
  // Verbatim: not summarised, truncated, or replaced with a status line.
  assert.equal(returned.returns.messages[0].content, reply);
});

test("a turn that returned no message does not invent one", () => {
  // The failure this guards: a provider returns only tool activity, and the UI
  // presents a progress label as though the assistant had spoken.
  const invocation = transitionRuntimeInvocation(readyInvocation(), "active");

  const returned = recordRuntimeReturn(invocation, {
    messages: [],
    artifacts: [{ path: "plan.md" }],
  });

  assert.equal(returned.returns.messages.length, 0);
  assert.equal(returned.returns.artifacts.length, 1);
});

test("successive turns accumulate in order without loss", () => {
  let invocation = transitionRuntimeInvocation(readyInvocation(), "active");
  invocation = recordRuntimeReturn(invocation, {
    messages: [{ role: "assistant", content: "first" }],
  });
  invocation = transitionRuntimeInvocation(invocation, "active");
  invocation = recordRuntimeReturn(invocation, {
    messages: [{ role: "assistant", content: "second" }],
  });

  assert.deepEqual(
    invocation.returns.messages.map(message => message.content),
    ["first", "second"],
  );
});

/* --------------------------------------- 2. inline never interrupts around it */

test("opening a runtime inline leaves the surrounding session untouched", () => {
  let registry = emptyRuntimeInvocationRegistry();
  const primary = transitionRuntimeInvocation(
    readyInvocation({ mode: "primary-session", parentSessionId: "session-1" }),
    "active",
  );
  registry = upsertRuntimeInvocation(registry, primary);

  const inline = readyInvocation({
    mode: "inline-tool",
    parentSessionId: "session-1",
    purpose: "Check the failing test",
  });
  registry = upsertRuntimeInvocation(registry, inline);

  const primaryAfter = selectPrimaryRuntimeInvocation(registry, "session-1");
  assert.equal(primaryAfter.invocationId, primary.invocationId);
  // The conversation the user was in is still the conversation they are in.
  assert.equal(primaryAfter.state, "active");
  assert.equal(selectInlineInvocations(registry, "session-1").length, 1);
});

test("an inline invocation cannot exist without the session it returns into", () => {
  // Without a parent it would be a hidden side thread the user cannot get back to.
  const orphan = createRuntimeInvocation({
    mode: "inline-tool",
    runtime: "claude-code",
    readiness: READY,
    parentSessionId: null,
  });

  assert.equal(orphan.state, "blocked");
  assert.ok(orphan.problems.some(problem => problem.includes("parent session")));
});

test("inline invocations do not leak into unrelated sessions", () => {
  let registry = emptyRuntimeInvocationRegistry();
  registry = upsertRuntimeInvocation(
    registry,
    readyInvocation({ mode: "inline-tool", parentSessionId: "session-1" }),
  );
  registry = upsertRuntimeInvocation(
    registry,
    readyInvocation({ mode: "inline-tool", parentSessionId: "session-2" }),
  );

  assert.equal(selectInlineInvocations(registry, "session-1").length, 1);
  assert.equal(selectInlineInvocations(registry, "session-2").length, 1);
});

test("session cleanup candidates never include another session or an API-owned invocation", () => {
  let registry = emptyRuntimeInvocationRegistry();
  registry = upsertRuntimeInvocation(registry, readyInvocation({ parentSessionId: "session-1" }));
  registry = upsertRuntimeInvocation(registry, readyInvocation({ parentSessionId: "session-2" }));
  registry = upsertRuntimeInvocation(registry, readyInvocation({ parentSessionId: null }));

  assert.equal(invocationsOwnedBySession(registry, "session-1").length, 1);
  assert.equal(invocationsOwnedBySession(registry, "session-1")[0].parentSessionId, "session-1");
});

/* ------------------------------- 3. expand, collapse, and resume in place */

test("an inline window can be expanded to fullscreen", () => {
  assert.ok(NEYVIA_INVOCATION_PRESENTATIONS.includes("fullscreen"));

  const expanded = transitionRuntimeInvocation(
    readyInvocation({ mode: "inline-tool", parentSessionId: "session-1" }),
    "active",
    { presentation: "fullscreen" },
  );
  assert.equal(expanded.presentation, "fullscreen");
});

test("collapsing and reopening preserves the session instead of restarting it", () => {
  let invocation = transitionRuntimeInvocation(
    readyInvocation({ mode: "inline-tool", parentSessionId: "session-1" }),
    "active",
  );
  const sessionIdentity = invocation.invocationId;
  invocation = recordRuntimeReturn(invocation, {
    messages: [{ role: "assistant", content: "partial work" }],
  });

  const collapsed = transitionRuntimeInvocation(invocation, "suspended");
  assert.ok(isInvocationResumable(collapsed.state));

  const reopened = transitionRuntimeInvocation(collapsed, "active");
  assert.equal(reopened.state, "active");
  // Same session, same transcript — a collapse is not a teardown.
  assert.equal(reopened.invocationId, sessionIdentity);
  assert.equal(reopened.returns.messages[0].content, "partial work");
});

test("closing is terminal and cannot be silently resumed", () => {
  const closed = transitionRuntimeInvocation(
    transitionRuntimeInvocation(readyInvocation(), "active"),
    "closed",
  );

  assert.equal(closed.state, "closed");
  assert.equal(canTransitionInvocation("closed", "active"), false);
  assert.equal(isInvocationResumable("closed"), false);
});

test("an unavailable runtime stays visible as blocked rather than disappearing", () => {
  let registry = emptyRuntimeInvocationRegistry();
  const blocked = createRuntimeInvocation({
    runtime: "",
    parentSessionId: "session-1",
  });
  registry = upsertRuntimeInvocation(registry, blocked);

  assert.equal(blocked.state, "blocked");
  assert.equal(registry.invocations.length, 1);
});

/* ----------------------- 4. Builder and Agent Live read one shared state */

test("primary and inline selectors project the same registry, not separate copies", () => {
  // Builder and Agent Live must never disagree about what is running.
  let registry = emptyRuntimeInvocationRegistry();
  const primary = transitionRuntimeInvocation(
    readyInvocation({ mode: "primary-session", parentSessionId: "session-1" }),
    "active",
  );
  const inline = readyInvocation({ mode: "inline-tool", parentSessionId: "session-1" });
  registry = upsertRuntimeInvocation(registry, primary);
  registry = upsertRuntimeInvocation(registry, inline);

  const ids = new Set(registry.invocations.map(item => item.invocationId));
  assert.ok(ids.has(selectPrimaryRuntimeInvocation(registry, "session-1").invocationId));
  assert.ok(ids.has(selectInlineInvocations(registry, "session-1")[0].invocationId));

  // Closing through the registry is reflected in every projection at once.
  const afterClose = closeRuntimeInvocation(registry, inline.invocationId, "done");
  assert.equal(selectInlineInvocations(afterClose, "session-1").length, 0);
  assert.equal(
    selectPrimaryRuntimeInvocation(afterClose, "session-1").invocationId,
    primary.invocationId,
  );
});
