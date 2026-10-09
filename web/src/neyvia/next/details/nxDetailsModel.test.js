import assert from "node:assert/strict";
import test from "node:test";

import { calmVisible, creep, meterFraction, numberCells, wheelRest, wheelTarget, WHEEL_FACES } from "./nxDetailsModel.js";

const keys = value => numberCells(value, { locale: "en-US" }).cells.map(cell => cell.key);

test("digits keep their column when a place is added", () => {
  assert.deepEqual(keys(99), ["i1", "i0"]);
  assert.deepEqual(keys(100), ["i2", "i1", "i0"]);
  assert.deepEqual(keys(1234), ["i3", "m3", "i2", "i1", "i0"]);
  const decimals = numberCells(12.5, { decimals: 1, locale: "en-US" });
  assert.equal(decimals.text, "12.5");
  assert.deepEqual(decimals.cells.map(cell => cell.key), ["i1", "i0", "m1p", "f0"]);
  assert.equal(numberCells(Number.NaN, { locale: "en-US" }).text, "0");
});

test("a column rolls the short way in the value's direction and stays on the wheel", () => {
  assert.equal(wheelTarget(19, 0, 1), 20); // 9 -> 0 going up rolls one face forward
  assert.equal(wheelTarget(10, 9, -1), 9); // 0 -> 9 going down rolls one face back
  assert.equal(wheelTarget(13, 3, 1), 13);
  for (let at = 10; at < 20; at += 1) {
    for (let digit = 0; digit < 10; digit += 1) {
      for (const dir of [1, -1]) {
        const to = wheelTarget(at, digit, dir);
        assert.ok(to >= 0 && to < WHEEL_FACES, `${at}->${digit} (${dir}) left the wheel: ${to}`);
        assert.equal(((to % 10) + 10) % 10, digit);
        assert.ok(Math.abs(to - at) <= 9);
        assert.equal(wheelRest(to) % 10, digit);
        assert.ok(wheelRest(to) >= 10 && wheelRest(to) < 20);
      }
    }
  }
});

test("estimated progress never claims done while the work runs", () => {
  let last = -1;
  for (const ms of [0, 100, 1000, 5000, 10000, 60000, 600000]) {
    const value = creep(ms, 5000);
    assert.ok(value > last || (ms === 0 && value === 0));
    assert.ok(value < 0.9);
    last = value;
  }
  assert.equal(meterFraction({ startedAt: 0, estimateMs: 5000, now: 600000, done: true }), 1);
  assert.equal(meterFraction({ value: 3, max: 4 }), 0.75);
  assert.equal(meterFraction({ value: 9, max: 4 }), 1);
  assert.equal(meterFraction({}), null);
});

test("calm loading skips short waits and never flickers", () => {
  assert.deepEqual(calmVisible({ loading: true, since: 0, now: 100 }), { visible: false, wakeIn: 140 });
  assert.deepEqual(calmVisible({ loading: true, since: 0, now: 300 }), { visible: true, wakeIn: null });
  // Shown at 300, the work ends at 350: it stays until 780.
  assert.deepEqual(calmVisible({ loading: false, since: 0, shownAt: 300, now: 350 }), { visible: true, wakeIn: 430 });
  assert.deepEqual(calmVisible({ loading: false, since: 0, shownAt: 300, now: 800 }), { visible: false, wakeIn: null });
  assert.deepEqual(calmVisible({ loading: false, since: 0, now: 100 }), { visible: false, wakeIn: null });
});
