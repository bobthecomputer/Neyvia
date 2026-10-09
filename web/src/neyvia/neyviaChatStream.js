import { checkedChatAction, checkStreamTransition, checkPollDelivery } from "./neyviaChatContracts.js";
function createNeyviaChatStreamStateUnchecked() {
  return {answer: '', answerIdentity: '', reasoningSummary: '', toolCalls: [], activitySegments: [], nextToolCallIndex: 0, nextActivityIndex: 0, detail: '', compacting: false, changed: false};
}

function displayToolValue(value, limit = 24000) {
  if (value == null || value === '') return '';
  let text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  if (typeof value === 'string' && /^[\s]*[\[{]/.test(value)) {
    try { text = JSON.stringify(JSON.parse(value), null, 2); } catch { /* Preserve truncated or non-JSON output verbatim. */ }
  }
  return String(text || '').slice(0, limit);
}

function normalizeNeyviaChatStreamToolCallsUnchecked(calls) {
  return (Array.isArray(calls) ? calls : [])
    .filter(call => call?.kind
      ? String(call.kind).toLowerCase() === 'runtime.tool'
      : Boolean(call?.tool || call?.data?.tool))
    .map((call, index) => {
      const data = call?.data && typeof call.data === 'object' ? call.data : call;
      const output = data?.output ?? data?.result;
      let result = output;
      if (typeof output === 'string') {
        try { result = JSON.parse(output); } catch { result = null; }
      }
      // Older saved receipts marked JSON failure responses as completed.
      const resultFailed = result && typeof result === 'object' &&
        (result.ok === false || result.isError === true || result.is_error === true);
      const error = data?.error || (resultFailed ? result.failure?.message || result.error || result.message || output : '');
      return {
        id: String(data?.callId || data?.itemId || data?.id || `tool-call-${index + 1}`).slice(0, 240),
        tool: String(data?.tool || 'tool').slice(0, 240),
        status: error ? 'failed' : String(data?.toolStatus || data?.status || 'started').slice(0, 32),
        input: displayToolValue(data?.input ?? data?.command ?? data?.code),
        output: displayToolValue(output),
        error: displayToolValue(error, 8000),
        eventType: String(data?.eventType || '').slice(0, 240),
      };
    });
}

function normalizedSummarySegment(segment, index) {
  const text = String(segment?.text || segment?.message || segment?.output || segment?.summary || '').trim();
  return text ? {kind: 'reasoning_summary', id: String(segment?.id || `reasoning-${index + 1}`), text} : null;
}

const PUBLIC_SUMMARY_KINDS = new Set(['reasoning_summary', 'runtime_reasoning_summary', 'runtime_reasoning_summary_delta', 'summary']);
const PUBLIC_TOOL_KINDS = new Set(['tool', 'runtime_tool', 'tool_call', 'tool_result', 'runtime_tool_call', 'runtime_tool_result']);
const PROVIDER_REASONING_SOURCE = 'provider.reasoning_content';
const PROVIDER_THINKING_KINDS = new Set(['thinking_text', 'runtime_thinking', 'runtime_thinking_delta']);

/** Normalize only provider-authored public summaries and recorded tool events. */
export function normalizeNeyviaChatActivitySegments(segments) {
  const result = [];
  for (const [index, raw] of (Array.isArray(segments) ? segments : []).entries()) {
    const kind = String(raw?.kind || raw?.type || '').toLowerCase().replace(/[.-]/g, '_');
    if (PUBLIC_SUMMARY_KINDS.has(kind)) {
      const summary = normalizedSummarySegment(raw, index);
      if (summary) result.push(summary);
    } else if (PROVIDER_THINKING_KINDS.has(kind) && raw?.source === PROVIDER_REASONING_SOURCE) {
      const text = String(raw?.text || raw?.message || raw?.output || '');
      if (text) result.push({kind: 'thinking_text', id: String(raw.id || `thinking-${index + 1}`), text, source: PROVIDER_REASONING_SOURCE, identity: String(raw.identity || '')});
    } else if (PUBLIC_TOOL_KINDS.has(kind) || raw?.tool || raw?.data?.tool) {
      const call = normalizeNeyviaChatStreamToolCalls([{...raw, kind: 'runtime.tool'}])[0];
      if (call) result.push({kind: 'tool', ...call});
    }
  }
  return result;
}

function activitySegmentsFromToolTimeline(timeline) {
  return normalizeNeyviaChatActivitySegments((Array.isArray(timeline) ? timeline : []).map(item => {
    const data = item?.data && typeof item.data === 'object' ? item.data : item;
    const normalizedKind = String(item?.kind || '').toLowerCase().replace(/[.-]/g, '_');
    if (PUBLIC_SUMMARY_KINDS.has(normalizedKind)) {
      return {...data, id: item.id || data.id, kind: 'reasoning_summary', text: data.output || data.text || data.message || data.summary};
    }
    if (PROVIDER_THINKING_KINDS.has(normalizedKind) && data?.source === PROVIDER_REASONING_SOURCE) {
      return {...data, id: item.id || data.id, kind: 'thinking_text', text: data.text || data.message || data.output};
    }
    if (PUBLIC_TOOL_KINDS.has(normalizedKind) || item?.tool || item?.data?.tool) {
      return {...item, kind: 'runtime.tool'};
    }
    return item;
  }));
}

// Chat, mission, and restored transcript projections must carry the same trace.
function neyviaChatTraceFieldsUnchecked(turn = {}) {
  const live = Array.isArray(turn.toolCalls) ? turn.toolCalls : [];
  const topLevelSegments = Array.isArray(turn.activitySegments) && turn.activitySegments.length ? turn.activitySegments : turn.turnReceipt?.activitySegments;
  const explicitSegments = normalizeNeyviaChatActivitySegments(topLevelSegments);
  const receiptTimeline = Array.isArray(turn.turnReceipt?.toolTimeline) && turn.turnReceipt.toolTimeline.length
    ? turn.turnReceipt.toolTimeline
    : turn.toolTimeline;
  const timelineSegments = activitySegmentsFromToolTimeline(receiptTimeline);
  const recordedSegments = explicitSegments.length ? explicitSegments : timelineSegments;
  const summary = String(turn.reasoningSummary || turn.turnReceipt?.reasoningSummary || '');
  const toolCalls = normalizeNeyviaChatStreamToolCalls(live.length ? live : turn.turnReceipt?.toolTimeline);
  const legacySummary = summary ? [{kind: 'reasoning_summary', id: 'reasoning-legacy', text: summary}] : [];
  // A receipt timeline that recorded only tool rows still owns the turn's
  // summary; keep it rather than dropping the thought from restored history.
  const activitySegments = recordedSegments.length
    ? (recordedSegments.some(segment => segment.kind === 'reasoning_summary') ? recordedSegments : [...legacySummary, ...recordedSegments])
    : [...legacySummary, ...toolCalls.map(call => ({kind: 'tool', ...call}))];
  return {
    reasoningSummary: summary,
    toolCalls,
    activitySegments,
    activityOrderKnown: typeof turn.activityOrderKnown === 'boolean'
      ? turn.activityOrderKnown
      : typeof turn.turnReceipt?.activityOrderKnown === 'boolean'
        ? turn.turnReceipt.activityOrderKnown
        : Boolean(explicitSegments.length || timelineSegments.some(segment => ['reasoning_summary', 'thinking_text'].includes(segment.kind))),
  };
}

export function applyNeyviaChatStreamEvents(state, events) {
  let changed = false;
  for (const event of Array.isArray(events) ? events : []) {
    // Text deltas need no history copies. Tool rows are replaced, and only
    // the latest summary is edited in place, so snapshot the affected evidence.
    const before = { ...state, toolCalls: event?.kind === 'runtime.tool' ? [...state.toolCalls] : state.toolCalls,
      activitySegments: event?.kind === 'runtime.reasoning_summary_delta' ? (state.activitySegments.length ? [{ ...state.activitySegments.at(-1) }] : []) : state.activitySegments };
    const kind = String(event?.kind || '');
    const message = String(event?.message || '');
    if (kind === 'runtime.answer_start') {
      const identity = JSON.stringify([
        event?.data?.responseId, event?.data?.itemId, event?.data?.outputIndex,
      ]);
      if (identity !== state.answerIdentity) {
        state.answerIdentity = identity;
        state.answer = '';
        changed = true;
      }
    } else if (kind === 'runtime.answer_delta') {
      state.answer += message;
      changed = true;
    } else if (kind === 'runtime.reasoning_summary_delta') {
      state.reasoningSummary += message;
      const last = state.activitySegments[state.activitySegments.length - 1];
      if (last?.kind === 'reasoning_summary') last.text += message;
      else state.activitySegments.push({kind: 'reasoning_summary', id: `reasoning-${++state.nextActivityIndex}`, text: message});
      changed = true;
    } else if (kind === 'runtime.thinking_delta' && event?.data?.source === PROVIDER_REASONING_SOURCE) {
      const data = event.data;
      const identity = JSON.stringify([data.responseId, data.itemId, data.outputIndex]);
      const previous = state.activitySegments[state.activitySegments.length - 1];
      if (previous?.kind === 'thinking_text' && previous.source === PROVIDER_REASONING_SOURCE && previous.identity === identity) {
        previous.text += message;
      } else {
        state.activitySegments.push({
          kind: 'thinking_text',
          id: `thinking-${++state.nextActivityIndex}`,
          text: message,
          source: PROVIDER_REASONING_SOURCE,
          identity,
        });
      }
      changed = true;
    } else if (kind === 'runtime.tool') {
      const data = event?.data && typeof event.data === 'object' ? event.data : event || {};
      const tool = String(data.tool || message || 'tool');
      const eventType = String(data.eventType || event?.eventType || '');
      const status = String(data.toolStatus || data.status || (/output/i.test(eventType) ? 'completed' : 'started')).toLowerCase();
      const suppliedId = String(data.callId || data.itemId || event?.itemId || '');
      const existingIndex = suppliedId
        ? state.toolCalls.findIndex(call => call.id === suppliedId)
        : -1;
      const id = suppliedId || `tool-call-${++state.nextToolCallIndex}`;
      const previous = existingIndex >= 0 ? state.toolCalls[existingIndex] : null;
      const next = {
        id,
        tool,
        status: ['completed', 'failed', 'running', 'started'].includes(status) ? status : 'started',
        input: displayToolValue(data.input ?? data.command ?? data.code) || previous?.input || '',
        output: displayToolValue(data.output ?? data.result) || previous?.output || '',
        error: displayToolValue(data.error) || previous?.error || '',
        eventType,
      };
      if (next.error) next.status = 'failed';
      if (existingIndex >= 0) state.toolCalls[existingIndex] = next;
      else state.toolCalls.push(next);
      const segmentIndex = suppliedId ? state.activitySegments.findIndex(segment => segment.kind === 'tool' && segment.id === suppliedId) : -1;
      const segment = {kind: 'tool', ...next};
      if (segmentIndex >= 0) state.activitySegments[segmentIndex] = segment;
      else state.activitySegments.push(segment);
      state.detail = `${next.status === 'completed' ? 'Finished' : next.status === 'failed' ? 'Failed' : 'Using'} ${tool}`;
      changed = true;
    } else if (kind === 'runtime.stream_error') {
      state.detail = message || 'The provider stream ended before the reply completed.';
      state.compacting = false;
      changed = true;
    } else if (kind === 'runtime.progress') {
      const eventType = String(event?.data?.eventType || event?.eventType || '');
      if (eventType === 'context.compaction.started' || eventType === 'context.compaction.progress') {
        state.compacting = true;
        if (message) state.detail = message;
        changed = true;
      } else if (eventType === 'context.compaction.completed') {
        state.compacting = false;
        if (message) state.detail = message;
        changed = true;
      } else if (message) {
        state.detail = message;
        changed = true;
      }
    }
  }
  state.changed = changed;
  return state;
}

export function startNeyviaChatStreamPoll({turnId, poll, onEvents, onError, intervalMs = 280}) {
  let active = true;
  let cursor = 0;
  let timer = null;
  let wakeWait = null;
  let requestController = null;
  let lastPollError = '';

  const done = (async () => {
    while (active) {
      requestController = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const outcome = await Promise.resolve()
        .then(() => poll(turnId, cursor, requestController?.signal))
        .then(snapshot => ({snapshot}), error => ({error}));
      requestController = null;
      if (!active) break;
      if (outcome.error) {
        const message = String(outcome.error?.message || outcome.error || 'Stream polling failed');
        if (message !== lastPollError) {
          lastPollError = message;
          onError?.(message);
        }
      } else if (lastPollError) {
        lastPollError = '';
        onError?.('');
      }
      const snapshot = outcome.snapshot || null;
      if (snapshot && Number.isFinite(Number(snapshot.cursor))) cursor = Number(snapshot.cursor);
      const events = Array.isArray(snapshot?.events) ? snapshot.events : [];
      if (events.length) { checkPollDelivery({ active, events, cursor, snapshot }); onEvents(events); }
      if (events.some(event => String(event?.kind || '') === 'runtime.done')) active = false;
      if (!active) break;
      await new Promise(resolve => {
        wakeWait = resolve;
        timer = window.setTimeout(() => {
          timer = null;
          wakeWait = null;
          resolve();
        }, Math.max(40, Number(intervalMs) || 280));
      });
    }
  })();

  return {
    done,
    stop() {
      active = false;
      requestController?.abort();
      requestController = null;
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      const wake = wakeWait;
      wakeWait = null;
      wake?.();
    },
  };
}

export function createNeyviaChatStreamState(...args) { return checkedChatAction("streamState", args, createNeyviaChatStreamStateUnchecked(...args)); }

export function normalizeNeyviaChatStreamToolCalls(...args) { return checkedChatAction("normalizedCalls", args, normalizeNeyviaChatStreamToolCallsUnchecked(...args)); }

export function neyviaChatTraceFields(...args) { return checkedChatAction("trace", args, neyviaChatTraceFieldsUnchecked(...args)); }
