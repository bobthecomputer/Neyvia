import assert from "node:assert/strict";
import test from "node:test";

import {
  AGENT_COMPANION_DEFAULT_WIDTH,
  AGENT_COMPANION_MIN_WIDTH,
  isLegacyAgentCompanionSurface,
  normalizeAgentCompanionWidth,
  readAgentCompanionState,
  writeAgentCompanionState,
} from "./neyviaAgentCompanionState.js";

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
  };
}

test("legacy Preview and Browser surfaces resolve to the Agent companion", () => {
  assert.equal(isLegacyAgentCompanionSurface("preview"), true);
  assert.equal(isLegacyAgentCompanionSurface("browser"), true);
  assert.equal(isLegacyAgentCompanionSurface("workbench"), true);
  assert.equal(isLegacyAgentCompanionSurface("agent"), false);
});

test("companion state is remembered independently for each conversation", () => {
  const storage = memoryStorage();

  writeAgentCompanionState(storage, "chat-alpha", { open: true, width: 468 });
  writeAgentCompanionState(storage, "mission-bravo", { open: false, width: 612 });

  assert.deepEqual(readAgentCompanionState(storage, "chat-alpha"), {
    open: true,
    width: 468,
  });
  assert.deepEqual(readAgentCompanionState(storage, "mission-bravo"), {
    open: false,
    width: 612,
  });
  assert.deepEqual(readAgentCompanionState(storage, "new-conversation"), {
    open: false,
    width: AGENT_COMPANION_DEFAULT_WIDTH,
  });
});

test("companion width stays readable when pointer or keyboard input exceeds bounds", () => {
  assert.equal(normalizeAgentCompanionWidth(120), AGENT_COMPANION_MIN_WIDTH);
  assert.equal(normalizeAgentCompanionWidth(900, 640), 640);
  assert.equal(normalizeAgentCompanionWidth("invalid"), AGENT_COMPANION_DEFAULT_WIDTH);
});
