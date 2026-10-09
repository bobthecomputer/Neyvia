import assert from "node:assert/strict";
import test from "node:test";

import { deriveNeyviaWorkspaceReadiness } from "./neyviaWorkspaceReadiness.js";

test("readiness distinguishes chat from orchestration", () => {
  const result = deriveNeyviaWorkspaceReadiness({
    providers: [{ status: true }],
    runtimes: [],
  });

  assert.equal(result.chatReady, true);
  assert.equal(result.orchestrationReady, false);
  assert.equal(result.mark, "Chat ready");
  assert.equal(result.detail, "2 setup items remain before multi-agent orchestration.");
  assert.deepEqual(result.blockers.map(item => item.id), ["workspace", "runtimes"]);
});

test("readiness only accepts detected runtime catalog entries", () => {
  const base = {
    providers: [{ hasSecret: true }],
    workspaceId: "ws-1",
  };
  const missing = deriveNeyviaWorkspaceReadiness({
    ...base,
    progressiveSetup: { cliCatalog: { entries: [{ state: "not_detected" }] } },
  });
  const detected = deriveNeyviaWorkspaceReadiness({
    ...base,
    progressiveSetup: { cliCatalog: { entries: [{ state: "detected_ready" }] } },
  });

  assert.equal(missing.orchestrationReady, false);
  assert.equal(detected.orchestrationReady, true);
});

test("readiness does not show a false login blocker while provider truth is loading", () => {
  const result = deriveNeyviaWorkspaceReadiness({
    providers: [],
    readinessPending: true,
  });

  assert.equal(result.chatReady, false);
  assert.equal(result.readinessPending, true);
  assert.equal(result.mark, "Checking setup");
  assert.equal(result.headline, "Preparing Neyvia");
  assert.deepEqual(result.blockers, []);
});
