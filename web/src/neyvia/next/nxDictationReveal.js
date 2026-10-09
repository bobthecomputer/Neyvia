// Words appear as they are spoken. The engines answer a few words at a time (local Phonon-2 about every 0.4 s, cloud
// providers in deltas); this paces the grey provisional words so each batch is written out one word after another
// across the gap to the next answer, instead of landing all at once. Settled (stable) words are never delayed, and a
// revision (the engine changed its mind) snaps back to the words that still agree and paces the rest.

import { checkedDictationAction } from "./nxDictationContracts.js";

const MIN_GAP_MS = 120;
const MAX_GAP_MS = 450;

const split = text => String(text || "").split(/\s+/).filter(Boolean);

/** Pure pacing step: how many of `target` words show `elapsedMs` after the batch arrived. First word at once. */
export function wordsShown(args) {
  const { startShown, total, elapsedMs, gapMs } = args;
  const backlog = Math.max(0, total - startShown);
  const fraction = Math.min(1, Math.max(0, elapsedMs) / Math.max(MIN_GAP_MS, gapMs));
  const shown = backlog ? Math.min(total, startShown + Math.max(1, Math.ceil(backlog * fraction))) : total;
  return checkedDictationAction("wordsShown", [{ ...args, gapMs: Math.max(MIN_GAP_MS, gapMs) }], shown);
}

export function createReveal() {
  let words = [];
  let shown = 0;
  let startShown = 0;
  let arrivedAt = 0;
  let lastArrival = 0;
  let gapMs = 300;
  return {
    /** A new answer: `settled` words are already final, `provisional` is the grey tail. Times in ms. */
    push(settled, provisional, now) {
      const next = [...split(settled), ...split(provisional)];
      let common = 0;
      while (common < words.length && common < next.length && words[common] === next[common]) common++;
      shown = Math.min(shown, common);
      if (lastArrival) gapMs = Math.min(MAX_GAP_MS, Math.max(MIN_GAP_MS, now - lastArrival));
      lastArrival = now;
      words = next;
      startShown = Math.max(shown, split(settled).length);
      shown = startShown;
      arrivedAt = now;
      this.settledCount = split(settled).length;
    },
    settledCount: 0,
    /** Number of grey words to show now, and whether more are still coming. */
    visible(now) {
      shown = Math.max(shown, wordsShown({ startShown, total: words.length, elapsedMs: now - arrivedAt, gapMs }));
      return { provisionalWords: Math.max(0, shown - this.settledCount), pending: shown < words.length, words: words.slice(this.settledCount, shown) };
    },
    reset() { words = []; shown = 0; startShown = 0; arrivedAt = 0; lastArrival = 0; gapMs = 300; this.settledCount = 0; },
  };
}
