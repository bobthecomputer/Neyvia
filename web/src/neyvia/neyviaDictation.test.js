import test from "node:test";
import assert from "node:assert/strict";
import { createDictation } from "./neyviaDictation.js";

function fixture() {
  let engine;
  const text = [], states = [];
  class Recognition {
    constructor() { engine = this; }
    start() { this.onstart(); }
    stop() { this.onend(); }
    abort() { this.aborted = true; }
  }
  const capture = createDictation(Recognition, { language: "fr-FR", onText: value => text.push(value), onState: value => states.push(value) });
  const result = (value, final) => Object.assign([{ transcript: value }], { isFinal: final });
  return { capture, engine, text, states, result };
}

test("interim speech is previewed; repeated final results append only once", () => {
  const f = fixture();
  f.capture.start();
  assert.equal(f.engine.lang, "fr-FR");
  f.engine.onresult({ resultIndex: 0, results: [f.result("Bonjour", false)] });
  assert.deepEqual(f.text, []);
  const event = { resultIndex: 0, results: [f.result("Bonjour", true), f.result("Neyvia", true)] };
  f.engine.onresult(event); f.engine.onresult(event);
  assert.deepEqual(f.text, ["Bonjour", "Neyvia"]);
  f.capture.stop();
  assert.equal(f.states.at(-1).status, "idle");
});

test("permission failure stays actionable after the speech service ends", () => {
  const f = fixture(); f.capture.start();
  f.engine.onerror({ error: "not-allowed" }); f.engine.onend();
  assert.equal(f.states.at(-1).status, "error");
  assert.match(f.states.at(-1).message, /site settings/);
});

test("navigation aborts capture and detaches callbacks", () => {
  const f = fixture(); f.capture.start(); f.capture.dispose();
  assert.equal(f.engine.aborted, true);
  assert.equal(f.engine.onresult, null);
});

test("unsupported browsers get an honest alternative instead of a no-op microphone", () => {
  assert.throws(() => createDictation(null, {}), /unavailable.*Chrome/);
});
