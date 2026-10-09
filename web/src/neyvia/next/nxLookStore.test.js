import assert from "node:assert/strict";
import test from "node:test";

// A tiny localStorage, before the store reads it at import.
const memory = new Map();
globalThis.localStorage = {
  getItem: key => (memory.has(key) ? memory.get(key) : null),
  setItem: (key, value) => memory.set(key, String(value)),
  removeItem: key => memory.delete(key),
};
memory.set("nx.os.look", JSON.stringify({ font: "windows", textSize: "l", background: { kind: "solid", color: "#13241b", dim: 10 } }));

const { applyPrefs, getOs, initialOsState, os, reduceUiAction } = await import("./nxOsStore.js");

test("the last look on this device paints first, before the PC answers", () => {
  const look = getOs().look;
  assert.equal(look.font, "windows");
  assert.equal(look.textSize, "l");
  assert.equal(look.background.kind, "solid");
});

test("setLook applies and remembers on this device", () => {
  os.setLook({ font: "editorial", textSize: "s", background: { kind: "preset", preset: "horizon" } });
  assert.equal(getOs().look.font, "editorial");
  const saved = JSON.parse(memory.get("nx.os.look"));
  assert.equal(saved.font, "editorial");
  assert.equal(saved.background.preset, "horizon");
});

test("canonical Settings from the PC win and keep the same object when unchanged", () => {
  const state = initialOsState({});
  const look = { font: "inter", textSize: "m", background: { kind: "theme", preset: "", color: "", image: "", dim: 0, blur: 0 }, sun: { follow: false, intoNight: false, sunrise: "07:00", sunset: "19:30" } };
  const first = applyPrefs(state, { revision: 3, settings: { theme: "forest", density: "calm", look } });
  assert.deepEqual(first.look, look);
  const again = applyPrefs(first, { revision: 4, settings: { theme: "forest", density: "calm", look: { ...look } } });
  assert.equal(again.look, first.look, "a poll with the same look re-renders nothing");
  // An older revision never overwrites a newer one.
  const stale = applyPrefs(again, { revision: 2, settings: { theme: "forest", density: "calm", look: { ...look, font: "geist" } } });
  assert.equal(stale.look.font, "inter");
  // While a look change is on its way to the PC, a refresh does not undo it.
  const pending = applyPrefs(again, { revision: 5, settings: { theme: "forest", density: "calm", look: { ...look, font: "geist" } } }, { look: false });
  assert.equal(pending.look.font, "inter");
});

test("a settings.changed event (another window saved) updates the look", () => {
  const state = applyPrefs(initialOsState({}), { revision: 1, settings: { theme: "forest", density: "calm", look: { font: "neyvia" } } });
  const next = reduceUiAction(state, "settings.changed", { revision: 2, settings: { theme: "sunset", density: "calm", look: { font: "geist", textSize: "l" } } });
  assert.equal(next.look.font, "geist");
  assert.equal(next.look.textSize, "l");
  assert.equal(next.theme, "sunset");
});
