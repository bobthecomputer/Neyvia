import test from 'node:test';
import assert from 'node:assert/strict';
import { collectCompletedChatTurns, createCompletionSound } from './neyviaCompletionSound.js';

test('completion chimes once per observed pending turn, never for history or cancellation', () => {
  const pending = new Set();
  const turn = { id: 'a', role: 'assistant', pending: false, source: 'backend-runtime-reply' };
  assert.deepEqual(collectCompletedChatTurns({ chat: [turn] }, pending), []);
  collectCompletedChatTurns({ chat: [{ ...turn, pending: true }] }, pending);
  assert.deepEqual(collectCompletedChatTurns({ chat: [turn] }, pending), ['a']);
  assert.deepEqual(collectCompletedChatTurns({ chat: [turn] }, pending), []);
  collectCompletedChatTurns({ chat: [{ ...turn, pending: true }] }, pending);
  assert.deepEqual(collectCompletedChatTurns({ chat: [{ ...turn, source: 'chat-cancelled' }] }, pending), []);
});

test('sound schedules two quiet tones and disposes its audio context', async () => {
  const started = [], stopped = [];
  let closed = false;
  class Context {
    state = 'running'; currentTime = 2;
    createOscillator() { return { frequency: {}, connect() {}, disconnect() {}, start(t) { started.push(t); }, stop(t) { stopped.push(t); } }; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {} }; }
    close() { closed = true; return Promise.resolve(); }
  }
  const sound = createCompletionSound({ AudioContext: Context });
  assert.equal(await sound.play(), true);
  assert.equal(started.length, 2); assert.equal(stopped.length, 2);
  sound.dispose(); assert.equal(closed, true);
  assert.equal(await createCompletionSound({}).play(), false);
});
