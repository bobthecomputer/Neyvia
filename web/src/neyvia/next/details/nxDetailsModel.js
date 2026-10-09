// Pure logic behind the small details (nxDetails.jsx). No DOM, no timers: each function
// is tested in nxDetailsModel.test.js because a mistake here fails silently (a counter
// that rolls the long way round, a progress bar that says "done" before the work is).

const DIGIT = /[0-9]/;

/**
 * Split a number into columns for the rolling number. Digits are keyed by their place
 * relative to the decimal point (i0 = ones, i1 = tens, f0 = tenths), so 99 -> 100 keeps
 * the ones and tens columns and only adds a hundreds column; separators are keyed by
 * how many digits sit to their right. `text` is the formatted value a screen reader hears.
 */
export function numberCells(value, { decimals = 0, locale } = {}) {
  const amount = Number.isFinite(value) ? value : 0;
  const places = Math.max(0, Math.min(6, Math.trunc(decimals) || 0));
  let text;
  try {
    text = new Intl.NumberFormat(locale, { minimumFractionDigits: places, maximumFractionDigits: places }).format(amount);
  } catch {
    text = amount.toFixed(places);
  }
  const chars = [...text];
  // The decimal separator is the last non-digit with only `places` digits after it.
  let point = chars.length;
  if (places) {
    let seen = 0;
    for (let index = chars.length - 1; index >= 0; index -= 1) {
      if (DIGIT.test(chars[index])) seen += 1;
      else if (seen === places) { point = index; break; }
    }
  }
  const cells = [];
  let intPlace = chars.slice(0, point).filter(char => DIGIT.test(char)).length;
  let fracPlace = 0;
  let digitsRight = chars.filter(char => DIGIT.test(char)).length;
  chars.forEach((char, index) => {
    if (DIGIT.test(char)) {
      digitsRight -= 1;
      if (index < point) { intPlace -= 1; cells.push({ kind: "digit", key: `i${intPlace}`, digit: Number(char) }); }
      else { cells.push({ kind: "digit", key: `f${fracPlace}`, digit: Number(char) }); fracPlace += 1; }
    } else {
      cells.push({ kind: "mark", key: `m${digitsRight}${index === point ? "p" : ""}`, char });
    }
  });
  return { text, cells };
}

// The wheel is three stacked bands of 0-9 (30 faces); a column rests in the middle band
// [10, 20). A move goes at most 9 faces in its direction, so it never leaves 0..29.
export const WHEEL_FACES = 30;

/** Where a column's wheel goes next: the nearest face showing `digit` in direction `dir`. */
export function wheelTarget(position, digit, dir) {
  const at = Number.isFinite(position) ? position : 10;
  const face = ((at % 10) + 10) % 10;
  if (face === digit) return at;
  const step = dir < 0 ? -(((face - digit) % 10) + 10) % 10 : (((digit - face) % 10) + 10) % 10;
  return at + step;
}

/** After a roll ends, the same face in the middle band (moved without a transition). */
export function wheelRest(position) {
  const face = ((Math.round(position) % 10) + 10) % 10;
  return 10 + face;
}

/**
 * Progress for work with an estimate but no real fraction. It moves quickly at first and
 * slows down, and never passes `hold` (0.9) until the work says it is done, so a job that
 * outruns its estimate keeps creeping instead of sitting at 100 % while still running.
 */
export function creep(elapsedMs, estimateMs, hold = 0.9) {
  const estimate = Math.max(1, Number(estimateMs) || 1);
  const t = Math.max(0, Number(elapsedMs) || 0) / estimate;
  // 1 - 1/(1+t)^3: about 88 % of `hold` at the estimate, then an ever slower approach that
  // stays strictly below `hold` (an exponential rounds to it in floating point).
  return hold * (1 - 1 / (1 + t) ** 3);
}

/** A fraction 0..1 for the meter: real value when known, creep when estimated, 1 when done. */
export function meterFraction({ value, max = 1, done = false, startedAt, estimateMs, now = Date.now() } = {}) {
  if (done) return 1;
  if (Number.isFinite(value) && Number(max) > 0) return Math.max(0, Math.min(1, value / max));
  if (Number.isFinite(startedAt) && Number(estimateMs) > 0) return creep(now - startedAt, estimateMs);
  return null;
}

/**
 * Calm loading: show a loading state only when the wait is long enough to notice
 * (`delay`), and once shown keep it at least `min` so it never flickers. Returns whether
 * it is visible now and, when that will change by itself, after how many ms to look again.
 */
export function calmVisible({ loading, since, shownAt, now = Date.now(), delay = 240, min = 480 }) {
  if (Number.isFinite(shownAt)) {
    const left = shownAt + min - now;
    if (left > 0) return { visible: true, wakeIn: left };
    return { visible: Boolean(loading), wakeIn: null };
  }
  if (!loading || !Number.isFinite(since)) return { visible: false, wakeIn: null };
  const wait = since + delay - now;
  return wait > 0 ? { visible: false, wakeIn: wait } : { visible: true, wakeIn: null };
}
