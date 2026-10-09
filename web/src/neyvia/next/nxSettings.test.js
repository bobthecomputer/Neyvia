import assert from "node:assert/strict";
import test from "node:test";

import { applyPrefs, initialOsState, reduceUiAction } from "./nxOsStore.js";

const record = (revision, settings) => ({ revision, settings: { density: "calm", theme: "forest", localOnly: false, ...settings } });

test("canonical Settings translate the theme and never go back to an older revision", () => {
  let state = applyPrefs(initialOsState({ theme: "light", density: "grove" }), record(4, { theme: "night-green", density: "workshop" }));
  assert.equal(state.theme, "night");
  assert.equal(state.density, "workshop");
  state = applyPrefs(state, record(3, { theme: "morning" }));
  assert.equal(state.theme, "night", "a late answer for revision 3 must not undo revision 4");
  state = reduceUiAction(state, "settings.changed", record(5, { theme: "sunset" }));
  assert.equal(state.theme, "sunset");
  assert.equal(state.prefs.revision, 5);
  assert.throws(() => reduceUiAction(state, "settings.changed", { settings: {} }), /revision/);
});

test("a pending look change keeps showing while the record refreshes", () => {
  const state = applyPrefs(initialOsState({ theme: "light" }), record(2, { theme: "forest" }), { look: false });
  assert.equal(state.theme, "light");
  assert.equal(state.prefs.settings.theme, "forest");
});

test("setup.open opens setup at the start without resetting anything", () => {
  const state = reduceUiAction(initialOsState({}), "setup.open", { resume: true });
  assert.equal(state.onboarding.step, "welcome");
  assert.equal(state.onboarding.resume, true);
});
