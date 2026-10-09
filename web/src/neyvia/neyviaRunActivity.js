import { checkedChatAction } from "./neyviaChatContracts.js";
import { checkedFrontendAction, frontendContractBefore } from "./neyviaFrontendContracts.js";
import {humanizeNeyviaToolId, inferNeyviaToolPhase} from './neyviaToolVisuals.js';

const text = value => typeof value === 'string' ? value.trim() : value == null ? '' : JSON.stringify(value, null, 2);
function visibleRunActivityEventsUnchecked(events) {
  const relevant = (Array.isArray(events) ? events : []).filter(event => {
    const kind = text(event?.kind || event?.type).toLowerCase();
    if (['runtime.answer_delta', 'runtime.reasoning_summary_delta', 'runtime.model_message', 'runtime.roundtrip', 'operator.message'].includes(kind)) return false;
    if (kind === 'runtime.progress' && !event?.tool && !/fail|error|block/i.test(text(event?.status || event?.message))) return false;
    return true;
  });
  const rows = [];
  const byItemId = new Map();
  for (const event of relevant) {
    const itemId = text(event?.itemId);
    if (text(event?.kind || event?.type).toLowerCase() !== 'runtime.tool' || !itemId) {
      rows.push(event);
      continue;
    }
    const earlierIndex = byItemId.get(itemId);
    if (earlierIndex === undefined) {
      byItemId.set(itemId, rows.length);
      rows.push(event);
      continue;
    }
    const earlier = rows[earlierIndex];
    rows[earlierIndex] = {
      ...earlier,
      ...event,
      command: event.command || earlier.command,
      code: event.code || earlier.code,
      input: event.input || earlier.input,
      output: event.output || earlier.output,
      goal: event.goal || earlier.goal,
    };
  }
  return rows;
}
function presentRunActivityUnchecked(event, index = 0) {
  const source = event && typeof event === 'object' && !Array.isArray(event) ? event : {summary: text(event)};
  const kind = text(source.kind || source.type || source.eventType || source.event_type);
  const tool = text(source.tool || source.toolName || source.tool_name || source.name || source.function?.name);
  const category = /app|application/.test(kind) ? 'App' : /tool|function/.test(kind) || tool ? 'Tool' : /command|shell/.test(kind) ? 'Command' : /context/.test(kind) ? 'Context' : /model|assistant/.test(kind) ? 'Model' : 'Runtime';
  const status = text(source.status || source.phase);
  return {
    key: `${text(source.id || source.eventId || source.event_id) || kind || 'activity'}-${index}`,
    category, tool, title: humanizeNeyviaToolId(tool || kind || 'Runtime activity'),
    summary: text(source.goal || source.summary || source.message || source.detail || source.title || source.outputSummary || source.output_summary),
    input: text(source.command || source.code || source.input || source.arguments || source.parameters || source.function?.arguments || source.invocation),
    inputLabel: source.command ? 'Command' : source.code ? 'Code' : 'Input',
    output: text(source.output || source.result || source.response),
    status, phase: inferNeyviaToolPhase({...source, status}),
    at: text(source.at || source.timestamp || source.createdAt || source.created_at),
    raw: source,
  };
}

// Receipts can contain untrusted tool output. Only actual web/application routes
// are openable; filesystem paths remain copyable evidence.
function safeReceiptHrefUnchecked(value) {
  const href = String(value || '').trim();
  if (!href || /[\u0000-\u001f\u007f]/.test(href)) return '';
  if (href.startsWith('/') && !href.startsWith('//') && !href.includes('\\')) return href;
  try { return ['http:', 'https:'].includes(new URL(href).protocol) ? href : ''; } catch { return ''; }
}

function runDurationLabelUnchecked(value) {
  if (value == null || value === '') return 'Not recorded';
  const ms = Number(value);
  if (!Number.isFinite(ms) || ms < 0) return 'Not recorded';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round(ms % 60000 / 1000)}s`;
}

export function safeReceiptHref(...args) {
  const before = frontendContractBefore("activity.href", args);
  return checkedFrontendAction("activity.href", args, safeReceiptHrefUnchecked(...args), before);
}

export function runDurationLabel(...args) {
  const before = frontendContractBefore("activity.duration", args);
  return checkedFrontendAction("activity.duration", args, runDurationLabelUnchecked(...args), before);
}

export function visibleRunActivityEvents(...args) { return checkedChatAction("visibleActivity", args, visibleRunActivityEventsUnchecked(...args)); }

export function presentRunActivity(...args) { return checkedChatAction("activity", args, presentRunActivityUnchecked(...args)); }
