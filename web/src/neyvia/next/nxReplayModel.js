import { checkedProofsEModel } from "./nxProofsEContracts.js";
// Session replay: a chat's recorded items laid on a timeline that plays back
// fast. Long silences (the agent thinking, the user away) are squeezed to a
// short pause, so two hours of work can be watched in a minute or two without
// losing the order or the rhythm of what happened. Pure functions; NxReplay
// renders them.

export const SPEEDS = [1, 4, 16, 60];
export const IDLE_CAP_MS = 4000; // the longest pause the replay keeps, in recorded time

const toMs = value => {
  const parsed = typeof value === "number" ? value : Date.parse(value || "");
  return Number.isFinite(parsed) ? parsed : null;
};

/**
 * Items in order with their recorded time `t` (ms since the first item) and
 * their replay time `rt` (the same, with every gap capped at `idleCap`).
 * Items without a timestamp take their neighbour's time, so nothing jumps.
 */
function raw_buildTimeline(items, { idleCap = IDLE_CAP_MS } = {}) {
  const ordered = [...(items || [])].filter(item => item && !item.optimistic).sort((a, b) => Number(a.seq) - Number(b.seq));
  const stamps = ordered.map(item => toMs(item.at));
  // Fill gaps forward, then backward for a leading run without timestamps.
  let last = null;
  for (let index = 0; index < stamps.length; index += 1) { if (stamps[index] == null) stamps[index] = last; else last = Math.max(stamps[index], last ?? stamps[index]); }
  const first = stamps.find(value => value != null) ?? 0;
  let previous = first;
  let replay = 0;
  const entries = ordered.map((item, index) => {
    const at = stamps[index] ?? first;
    const gap = Math.max(0, at - previous);
    replay += Math.min(gap, idleCap);
    previous = Math.max(previous, at);
    return { item, t: at - first, rt: replay, at };
  });
  const duration = entries.length ? entries[entries.length - 1].t : 0;
  const replayDuration = entries.length ? entries[entries.length - 1].rt : 0;
  return { entries, duration, replayDuration, startedAt: first || null };
}

/** How many entries have appeared by replay position `rt` (binary search). */
function raw_visibleCount(timeline, rt) {
  const { entries } = timeline;
  let low = 0;
  let high = entries.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (entries[mid].rt <= rt) low = mid + 1; else high = mid;
  }
  return low;
}

/** Recorded wall-clock moment at a replay position, for the "what time was it" readout. */
function raw_recordedAt(timeline, rt) {
  const count = visibleCount(timeline, rt);
  return count ? timeline.entries[count - 1].at : timeline.startedAt;
}

/** Wall time a playback takes at `speed`. */
const raw_playbackMs = (timeline, speed) => Math.ceil(timeline.replayDuration / Math.max(1, speed));

/** "2h 14m", "3m 05s", "12s". */
function raw_formatSpan(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** Ticks for the scrubber: one per item that changes the story, coloured by kind. */
function raw_timelineMarks(timeline) {
  const total = timeline.replayDuration || 1;
  return timeline.entries
    .filter(({ item }) => ["user", "assistant", "tool", "approval", "question", "diff", "compaction"].includes(item.kind))
    .map(({ item, rt }) => ({
      id: item.id,
      at: rt / total,
      tone: item.kind === "user" ? "user" : item.kind === "tool" ? (item.data?.status === "error" ? "error" : "tool")
        : item.kind === "approval" || item.kind === "question" ? "needs" : item.kind === "assistant" ? "reply" : "other",
    }));
}

// Public observers check the executable manual claims on every invocation.
export function buildTimeline(...args) { return checkedProofsEModel("replay.buildTimeline", args, raw_buildTimeline(...args)); }
export function visibleCount(...args) { return checkedProofsEModel("replay.visibleCount", args, raw_visibleCount(...args)); }
export function recordedAt(...args) { return checkedProofsEModel("replay.recordedAt", args, raw_recordedAt(...args)); }
export function playbackMs(...args) { return checkedProofsEModel("replay.playbackMs", args, raw_playbackMs(...args)); }
export function timelineMarks(...args) { return checkedProofsEModel("replay.timelineMarks", args, raw_timelineMarks(...args)); }
export function formatSpan(...args) { return checkedProofsEModel("replay.formatSpan", args, raw_formatSpan(...args)); }
