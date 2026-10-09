#!/usr/bin/env node
'use strict';
// Reads only session_meta, turn_context.model and token_count numeric fields.
// No transcript text, rate-limit details, credentials or provider calls are retained.
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const crypto = require('node:crypto');
const FIELDS = ['input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens'];
const zero = () => Object.fromEntries(FIELDS.map(k => [k, 0]));
const add = (a, b) => FIELDS.forEach(k => a[k] += b[k] || 0);
async function readUsage(file) {
  if (!/^rollout-.*\.jsonl$/.test(path.basename(file))) throw Error('Only Codex rollout JSONL logs are accepted');
  let meta = null, model = null, previous = null, segment = 0;
  const deltas = [], issues = [], inheritedMetadata = [], segments = [];
  const lines = readline.createInterface({ input: fs.createReadStream(file), crlfDelay: Infinity });
  for await (const line of lines) {
    let row;
    try { row = JSON.parse(line); } catch { continue; } // Interrupted tail is normal for a live log.
    const p = row.payload || {};
    if (row.type === 'session_meta') {
      const header = { id: p.id, cwd: p.cwd, source: p.source, timestamp: p.timestamp, agentPath:p.agent_path || null, parentThreadId:p.parent_thread_id || null };
      // Forks prepend their own identity, then inherit the parent's header.
      // Later inherited metadata is not the owner of new numeric usage events.
      if (!meta) meta = header;
      else if (header.id !== meta.id) inheritedMetadata.push(header);
    } else if (row.type === 'turn_context') {
      model = p.model || model;
    } else if (row.type === 'event_msg' && p.type === 'token_count' && p.info?.total_token_usage) {
      const current = Object.fromEntries(FIELDS.map(k => [k, Number(p.info.total_token_usage[k]) || 0]));
      const time = Date.parse(row.timestamp);
      if (!Number.isFinite(time)) continue;
      if (previous) {
        const delta = Object.fromEntries(FIELDS.map(k => [k, current[k] - previous.usage[k]]));
        if (FIELDS.some(k => delta[k] < 0) || time < previous.time) {
          issues.push({ code:time < previous.time?'timestamp_regression':'counter_reset', at:row.timestamp, segment });
          segment++;
          segments.push({ id:segment, from:row.timestamp, model, initialUsageExcluded:current });
        } else if (delta.total_tokens > 0) {
          const sameModel = previous.model === model;
          if (!sameModel) issues.push({ code:'model_transition_ambiguous_window', at:row.timestamp, previousModel:previous.model, model });
          const fingerprint = crypto.createHash('sha256').update(JSON.stringify({from:previous.time,to:time,before:previous.usage,after:current})).digest('hex');
          deltas.push({ from:previous.time, to:time, model:sameModel?model:null, modelCandidates:sameModel?undefined:[previous.model,model], segment, fingerprint, tokens:delta });
        }
      } else {
        issues.push({ code: 'initial_cumulative_usage_unattributed', at: row.timestamp, tokens: current });
        segments.push({ id:segment, from:row.timestamp, model, initialUsageExcluded:current });
      }
      previous = { time, usage: current, model };
    }
  }
  return { file, meta, inheritedMetadata, segments, deltas, issues };
}
function estimate(tokens, model, tariff) {
  if (!tariff || tariff.model !== model) return null;
  const required = ['inputUSDPerMillion', 'cachedInputUSDPerMillion', 'outputUSDPerMillion'];
  if (required.some(k => !Number.isFinite(tariff[k]) || tariff[k] < 0)) throw Error('Tariff must explicitly supply nonnegative input, cached input and output USD per million');
  if (tokens.cache_write_input_tokens && !Number.isFinite(tariff.cacheWriteUSDPerMillion)) return null;
  // Reasoning is a subset of output; cached reads are a subset of input.
  return ((tokens.input_tokens - tokens.cached_input_tokens - tokens.cache_write_input_tokens) * tariff.inputUSDPerMillion + tokens.cached_input_tokens * tariff.cachedInputUSDPerMillion + tokens.cache_write_input_tokens * (tariff.cacheWriteUSDPerMillion || 0) + tokens.output_tokens * tariff.outputUSDPerMillion) / 1e6;
}
async function meter({ run, files, cwd, tariff = null, cutoff = null }) {
  const cutoffMs = cutoff === null ? Infinity : Date.parse(cutoff);
  if (Number.isNaN(cutoffMs)) throw Error('Meter cutoff must be an explicit ISO timestamp');
  const tasks = run.tasks.map(t => ({ id: t.id, start: Date.parse(t.startedAt), end: Date.parse(t.finishedAt), exclusiveTokens: zero(), overlappingTokenWindows: [] }));
  const sources = [], shared = [], totals = zero(), seen = new Map(), duplicates = [], cutoffExcluded = [];
  for (const file of files) {
    const log = await readUsage(file);
    if (cwd && path.resolve(log.meta?.cwd || '').toLowerCase() !== path.resolve(cwd).toLowerCase()) continue;
    let included = 0;
    for (const delta of log.deltas) {
      const matches = tasks.filter(t => Number.isFinite(t.start) && Number.isFinite(t.end) && delta.to >= t.start && delta.from <= t.end);
      if (!matches.length) continue;
      if (delta.to > cutoffMs) {
        cutoffExcluded.push({sessionId:log.meta?.id,fingerprint:delta.fingerprint,from:new Date(delta.from).toISOString(),to:new Date(delta.to).toISOString(),taskIds:matches.map(t=>t.id),reason:'Window ends after explicit cutoff; no partial-token interpolation.'});
        continue;
      }
      if (seen.has(delta.fingerprint)) {
        duplicates.push({fingerprint:delta.fingerprint,path:file,sessionId:log.meta?.id,original:seen.get(delta.fingerprint),from:new Date(delta.from).toISOString(),to:new Date(delta.to).toISOString()});
        continue;
      }
      seen.set(delta.fingerprint,{path:file,sessionId:log.meta?.id});
      included++;
      add(totals, delta.tokens);
      const item = { sessionId: log.meta?.id, agentPath:log.meta?.agentPath, segment:delta.segment, fingerprint:delta.fingerprint, from: new Date(delta.from).toISOString(), to: new Date(delta.to).toISOString(), model: delta.model, modelCandidates:delta.modelCandidates, tokens: delta.tokens, taskIds: matches.map(t => t.id), estimatedUSD: estimate(delta.tokens, delta.model, tariff) };
      if (matches.length === 1 && delta.from >= matches[0].start && delta.to <= matches[0].end) {
        add(matches[0].exclusiveTokens, delta.tokens);
        (matches[0].exclusiveWindows ||= []).push(item);
      } else {
        const index = shared.push(item) - 1;
        matches.forEach(t => t.overlappingTokenWindows.push(index));
      }
    }
    sources.push({ path: file, sessionId: log.meta?.id, agentPath:log.meta?.agentPath, source: log.meta?.source, inheritedMetadata:log.inheritedMetadata, segments:log.segments, includedWindows: included, issues: log.issues });
  }
  return { schema: 'neyvia.C2d.codex-token-meter@2', meteredAt: new Date().toISOString(), method: 'Positive deltas between cumulative token_count observations; no interpolation or division across overlapping task spans.', costBoundary: 'Exclusive temporal windows remain session activity, not proven task causation. Overlapping windows are ambiguous and counted once in union totals. Initial cumulative event is excluded. Reasoning tokens are included in output, cached tokens in input. Dollar cost is an explicit tariff estimate only; subscription cost is unmeasured.', tariff, cutoff: { at: cutoff, excludedWindows:cutoffExcluded, boundary:'Only complete numeric windows ending by cutoff are retained; later crossing windows remain unmeasured rather than interpolated.' }, sources, deduplication: { method: 'Exact absolute time bounds and before/after cumulative numeric counters; different session headers do not suppress distinct usage. First metadata identifies log owner; inherited headers remain separately recorded.', excludedWindows: duplicates.length, duplicates }, unionTokens: totals, sharedWindows: shared, tasks: tasks.map(t => ({ id: t.id, startedAt: Number.isFinite(t.start) ? new Date(t.start).toISOString() : null, finishedAt: Number.isFinite(t.end) ? new Date(t.end).toISOString() : null, attribution: !Number.isFinite(t.end) ? 'task_not_finished' : t.overlappingTokenWindows.length ? 'ambiguous_overlap' : t.exclusiveTokens.total_tokens ? 'exclusive_temporal_windows_only' : 'unmeasured', exclusiveTokens: t.exclusiveTokens, estimatedExclusiveUSD: t.exclusiveWindows?.length && t.exclusiveWindows.every(w => w.estimatedUSD !== null) ? t.exclusiveWindows.reduce((sum, w) => sum + w.estimatedUSD, 0) : null, overlappingTokenWindows: t.overlappingTokenWindows })) };
}
async function main() {
  const args = process.argv.slice(2), values = {};
  for (let i = 0; i < args.length; i += 2) (values[args[i]] ||= []).push(args[i + 1]);
  const runPath = values['--run']?.[0] || 'scripts/evidence/C2c-webvoyager.json';
  let files = values['--session'] || [];
  if (values['--session-dir']) files = files.concat(fs.readdirSync(values['--session-dir'][0]).filter(f => /^rollout-.*\.jsonl$/.test(f)).map(f => path.join(values['--session-dir'][0], f)));
  if (!files.length) throw Error('Pass --session <rollout.jsonl> (repeatable), or --session-dir <one dated session directory>');
  const report = await meter({ run: JSON.parse(fs.readFileSync(runPath, 'utf8')), files: [...new Set(files)], cwd: values['--cwd']?.[0] || process.cwd(), tariff: values['--tariff'] ? JSON.parse(values['--tariff'][0]) : null, cutoff:values['--cutoff']?.[0] || null });
  report.run = runPath;
  if (values['--out']) fs.writeFileSync(values['--out'][0], JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ tasks: report.tasks.length, sources: report.sources.length, unionTokens: report.unionTokens, ambiguousTasks: report.tasks.filter(t => t.attribution === 'ambiguous_overlap').length, dollarCost: report.tariff ? 'explicit tariff estimate' : null, out: values['--out']?.[0] || null }));
}
module.exports = { readUsage, meter, estimate };
if (require.main === module) main().catch(e => { console.error(e.message); process.exitCode = 1; });
