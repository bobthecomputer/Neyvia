// Semantic checks run before chat state or recorded tool evidence reaches its consumers.
// Errors contain only a contract identity, never tool output or credential values.
export class ChatContractError extends Error { constructor(name) { super(`Chat contract ${name} failed`); this.name = "ChatContractError"; this.contract = `proofs-e.chat.${name}`; } }
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const text = v => typeof v === "string" ? v.trim() : v == null ? "" : JSON.stringify(v, null, 2);
const display = (v, limit = 24000) => { if (v == null || v === "") return ""; let out = typeof v === "string" ? v : JSON.stringify(v, null, 2); if (typeof v === "string" && /^\s*[\[{]/.test(v)) try { out = JSON.stringify(JSON.parse(v), null, 2); } catch { /* truncated evidence is retained */ } return String(out || "").slice(0, limit); };
export function toolCallClaim(call, index = 0) {
  const d = call?.data && typeof call.data === "object" ? call.data : call, output = d?.output ?? d?.result;
  let parsed = output; if (typeof output === "string") try { parsed = JSON.parse(output); } catch { parsed = null; }
  const failed = parsed && typeof parsed === "object" && (parsed.ok === false || parsed.isError === true || parsed.is_error === true), error = d?.error || (failed ? parsed.failure?.message || parsed.error || parsed.message || output : "");
  return { id: String(d?.callId || d?.itemId || d?.id || `tool-call-${index + 1}`).slice(0, 240), tool: String(d?.tool || "tool").slice(0, 240), status: error ? "failed" : String(d?.toolStatus || d?.status || "started").slice(0, 32), input: display(d?.input ?? d?.command ?? d?.code), output: display(output), error: display(error, 8000), eventType: String(d?.eventType || "").slice(0, 240) };
}
function normalizedCalls(calls) { return (Array.isArray(calls) ? calls : []).filter(c => c?.kind ? String(c.kind).toLowerCase() === "runtime.tool" : Boolean(c?.tool || c?.data?.tool)).map(toolCallClaim); }
function phase(row = {}) {
  const tone = String(row.tone || "").toLowerCase(), status = String(row.status || "").toLowerCase();
  if (["failed", "error", "down", "danger"].includes(tone) || ["failed", "error", "timeout", "timed_out"].includes(status)) return "error";
  if (["cancelled", "canceled", "uncertain", "unknown", "blocked", "waiting_approval"].includes(status)) return "idle";
  if (row.pending || status === "running" || status === "streaming") return "running";
  if (["good", "completed", "success"].includes(tone) || ["success", "completed", "succeeded"].includes(status)) return "success";
  return ["call", "queued"].includes(status) ? "call" : ["composing", "writing"].includes(status) ? "composing" : "idle";
}
function humanize(raw) {
  const words = s => s.replace(/[._-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/\s+/g, " ").trim().split(" ").map(w => w === w.toUpperCase() ? w : w.toLowerCase()).join(" ");
  const value = String(raw || "").trim(); if (!value) return "Tool";
  const mcp = /^mcp[._-]+([^._-]+)[._-]+(.+)$/i.exec(value); if (mcp) { const server = words(mcp[1]), action = words(mcp[2]); return `${server[0].toUpperCase()}${server.slice(1)} · ${action[0].toLowerCase()}${action.slice(1)}`; }
  const out = words(value.replace(/_command$/i, "").replace(/^(tool|fn|handler)[._-]+/i, "")); return out ? out[0].toUpperCase() + out.slice(1) : "Tool";
}
function activityClaim(event, index = 0) {
  const s = event && typeof event === "object" && !Array.isArray(event) ? event : { summary: text(event) };
  const kind = text(s.kind || s.type || s.eventType || s.event_type), tool = text(s.tool || s.toolName || s.tool_name || s.name || s.function?.name), status = text(s.status || s.phase);
  const category = /app|application/.test(kind) ? "App" : /tool|function/.test(kind) || tool ? "Tool" : /command|shell/.test(kind) ? "Command" : /context/.test(kind) ? "Context" : /model|assistant/.test(kind) ? "Model" : "Runtime";
  return { key: `${text(s.id || s.eventId || s.event_id) || kind || "activity"}-${index}`, category, tool, title: humanize(tool || kind || "Runtime activity"), summary: text(s.goal || s.summary || s.message || s.detail || s.title || s.outputSummary || s.output_summary), input: text(s.command || s.code || s.input || s.arguments || s.parameters || s.function?.arguments || s.invocation), inputLabel: s.command ? "Command" : s.code ? "Code" : "Input", output: text(s.output || s.result || s.response), status, phase: phase({ ...s, status }), at: text(s.at || s.timestamp || s.createdAt || s.created_at), raw: s };
}
function visibleClaim(events) {
  const out = [], positions = new Map();
  for (const e of Array.isArray(events) ? events : []) { const kind = text(e?.kind || e?.type).toLowerCase(); if (["runtime.answer_delta", "runtime.reasoning_summary_delta", "runtime.model_message", "runtime.roundtrip", "operator.message"].includes(kind) || kind === "runtime.progress" && !e?.tool && !/fail|error|block/i.test(text(e?.status || e?.message))) continue; const id = text(e?.itemId); if (kind !== "runtime.tool" || !id || !positions.has(id)) { if (kind === "runtime.tool" && id) positions.set(id, out.length); out.push(e); } else { const i = positions.get(id), previous = out[i]; out[i] = { ...previous, ...e }; for (const k of ["command", "code", "input", "output", "goal"]) out[i][k] = e[k] || previous[k]; } }
  return out;
}
export function stringFieldClaim(value, key) {
  const source = String(value ?? ""), start = new RegExp(`"${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\s*:\\s*"`).exec(source); if (!start) return null;
  let raw = "", closed = false;
  for (let i = start.index + start[0].length; i < source.length; i++) { if (source[i] === "\\") { raw += source.slice(i, i + 2); i++; } else if (source[i] === '"') { closed = true; break; } else raw += source[i]; }
  if (!closed) { raw = raw.replace(/… \[truncated\]$/, ""); const suffix = /(\\+)(u[0-9a-fA-F]{0,3})?$/.exec(raw); if (suffix && suffix[1].length % 2) raw = raw.slice(0, suffix.index + suffix[1].length - 1); }
  let decoded = raw; try { decoded = JSON.parse(`"${raw}"`); } catch { /* expose retained evidence */ } return { value: decoded, complete: closed };
}
const lines = v => { const list = String(v ?? "").replace(/\r\n/g, "\n").split("\n"); if (list.at(-1) === "") list.pop(); return list; };
function diffClaim(value) {
  const output = [], counters = { old: null, current: null }; let added = 0, removed = 0;
  for (const raw of lines(value)) { if (/^(\+\+\+|---)/.test(raw)) continue; const h = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw); if (raw.startsWith("@@")) { if (h) { counters.old = Number(h[1]); counters.current = Number(h[2]); } output.push({ type: "hunk", text: raw }); continue; } if (raw.startsWith("\\")) continue; const type = raw[0] === "+" ? "add" : raw[0] === "-" ? "del" : "ctx", number = type === "del" ? counters.old : counters.current; output.push({ type, text: ["+", "-", " "].includes(raw[0]) ? raw.slice(1) : raw, number }); if (type === "add") added++; if (type === "del") removed++; if (type !== "add" && counters.old !== null) counters.old++; if (type !== "del" && counters.current !== null) counters.current++; }
  return { lines: output, added, removed };
}
function familyClaim(tool) {
  const id = String(tool || "").trim().toLowerCase().replace(/^mcp[._-]+neyvia[._-]+/, "").replace(/^neyvia[._-]+/, "");
  const patterns = [["command", /(^|[._-])(terminal[._-]exec|exec[._-]?command|shell|bash|powershell|run[._-]?command|command[._-]execution|local[._-]shell)($|[._-])/], ["edit", /(apply[._-]?patch|str[._-]replace|(^|[._-])edit($|[._-])|multi[._-]?edit|file[._-]change)/], ["write", /(workspace[._-]write|write[._-]?file|file[._-]write|(^|[._-])write$|create[._-]?file)/], ["read", /(workspace[._-]read|read[._-]?file|file[._-]read|(^|[._-])read$|view[._-]?file|open[._-]?file)/], ["search", /(search|grep|glob|find[._-]?files|list[._-]?dir|(^|[._-])ls$)/], ["fetch", /(web[._-]fetch|browser[._-]navigate|http|url)/]];
  return patterns.find(([, p]) => p.test(id))?.[0] || "generic";
}
const object = v => { try { const parsed = typeof v === "object" ? v : JSON.parse(String(v)); return parsed && typeof parsed === "object" ? parsed : null; } catch { return null; } };
const leaf = v => String(v || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
const repaired = v => { const s = String(v ?? ""); return (s.match(/\u0000/g) || []).length >= s.length / 5 && s.includes("\u0000") ? s.replace(/﻿|\u0000/g, "") : s; };
const bounded = v => { const s = repaired(v).replace(/\r\n/g, "\n").replace(/\n+$/, ""); return s.length > 20000 ? `${s.slice(0, 20000)}\n… [truncated]` : s; };
function presentationClaim([call = {}], result) {
  const inputText = String(call?.input ?? ""), input = object(inputText) || {}, errorText = String(call?.error ?? ""), resultText = String(call?.output || "") || errorText, raw = object(resultText) || {}, output = { ...raw, ...(raw.toolResult && typeof raw.toolResult === "object" ? raw.toolResult : raw.result && typeof raw.result === "object" && !Array.isArray(raw.result) ? raw.result : {}) };
  const field = (o, src, keys) => keys.map(k => typeof o[k] === "string" && o[k] ? { value: o[k], complete: true } : null).find(Boolean) || keys.map(k => stringFieldClaim(src, k)).find(v => v?.value);
  const number = (...keys) => keys.map(k => typeof output[k] === "number" && Number.isFinite(output[k]) ? output[k] : null).find(v => v !== null) ?? keys.map(k => new RegExp(`"${k}"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)`).exec(resultText)).find(Boolean)?.[1] ?? null;
  const family = familyClaim(call?.tool || "tool"), failure = String(output.failure?.message || (errorText && !object(errorText) ? errorText : "") || output.error || "").trim();
  if (result.family !== family || result.error !== failure || result.failed !== (String(call?.status || "").toLowerCase() === "failed" || Boolean(failure && output.ok === false))) return false;
  const command = field(input, inputText, ["command", "cmd", "script"]) || field(output, resultText, ["command"]);
  if ((family === "command" || result.kind === "command") && command) { const shell = field(input, inputText, ["shell"])?.value || field(output, resultText, ["shell"])?.value || "", cwd = field(input, inputText, ["cwd", "workdir", "workingDirectory"])?.value || field(output, resultText, ["cwd"])?.value || ""; return result.kind === "command" && result.title === "Ran" && result.subject === (shell ? shell.replace(/^powershell$/i, "PowerShell").replace(/^cmd$/i, "cmd") : "command") && same(result.command, { text: command.value.replace(/\r\n/g, "\n"), complete: command.complete, shell, cwd, cwdLabel: cwd ? leaf(cwd) : "", exitCode: number("exitCode", "exit_code", "returncode") == null ? null : Number(number("exitCode", "exit_code", "returncode")), durationMs: number("durationMs", "duration_ms") == null ? null : Number(number("durationMs", "duration_ms")), stdout: bounded(field(output, resultText, ["stdout", "output"])?.value || ""), stderr: bounded(field(output, resultText, ["stderr"])?.value || ""), outputTruncated: Boolean(output.stdoutTruncated || output.stderrTruncated || output.outputTruncated) }); }
  const path = field(input, inputText, ["path", "filePath", "file_path", "file", "target"])?.value || field(output, resultText, ["path"])?.value || "";
  if (family === "read" && path) { const content = field(output, resultText, ["content", "text"])?.value || ""; return result.kind === "read" && result.title === "Read" && result.path === path && result.subject === leaf(path) && result.preview === bounded(content) && result.lineCount === (content ? lines(content).length : null); }
  if (["write", "edit"].includes(family)) {
    const patch = field(input, inputText, ["patch", "input"])?.value || "";
    if (patch.includes("*** Begin Patch")) { const files = [], regex = /^\*\*\* (Add|Update|Delete) File: (.+)$/gm; let h; while ((h = regex.exec(patch))) files.push({ at: h.index, end: regex.lastIndex, path: h[2].trim(), status: { Add: "created", Update: "updated", Delete: "deleted" }[h[1]] }); if (files.length) return result.kind === "edit" && result.title === (files[0].status === "created" ? "Created" : files[0].status === "deleted" ? "Deleted" : "Edited") && result.path === files[0].path && result.subject === `${leaf(files[0].path)}${files.length > 1 ? ` and ${files.length - 1} more` : ""}` && result.diffs.length === files.length && files.every((f, i) => { const rawLines = patch.slice(f.end, files[i + 1]?.at ?? patch.length).replace(/^\r?\n/, "").split(/\r?\n/); if (rawLines.at(-1) === "") rawLines.pop(); const body = rawLines.filter(l => !/^\*\*\* (Begin|End) Patch|^\*\*\* Move to:/.test(l)).join("\n"), d = diffClaim(body), actual = result.diffs[i]; return actual.path === f.path && actual.status === f.status && actual.added === d.added && actual.removed === d.removed && same(actual.lines, d.lines.slice(0, 400)); }); }
    const old = field(input, inputText, ["oldString", "old_string", "old_str", "search"])?.value, updated = field(input, inputText, ["newString", "new_string", "new_str", "replace"])?.value, recorded = field(output, resultText, ["diff"])?.value || "", content = field(input, inputText, ["content", "contents", "text", "file_text"]), status = String(output.status || stringFieldClaim(resultText, "status")?.value || "").toLowerCase(), expects = Boolean(field(input, inputText, ["expectedSha256", "expected_sha256"]));
    const created = ["created", "updated"].includes(status) ? status === "created" : family === "write" && !expects && !recorded && typeof old !== "string";
    if (path && (result.path !== path || result.subject !== leaf(path) || result.title !== (created ? "Created" : "Edited"))) return false;
    let expected = null;
    if (recorded) expected = diffClaim(recorded);
    else if (typeof old === "string" && typeof updated === "string") { const a = lines(old), b = lines(updated); let start = 0, endA = a.length, endB = b.length; while (start < a.length && start < b.length && a[start] === b[start]) start++; while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; } expected = { added: endB - start, removed: endA - start, lines: [...a.slice(Math.max(0, start - 2), start).map(text => ({ type: "ctx", text })), ...a.slice(start, endA).map(text => ({ type: "del", text })), ...b.slice(start, endB).map(text => ({ type: "add", text })), ...b.slice(endB, endB + 2).map(text => ({ type: "ctx", text }))] }; }
    else if (content && created) { const added = lines(content.value); expected = { added: added.length, removed: 0, lines: added.map((text, i) => ({ type: "add", text, number: i + 1 })) }; }
    if (expected) { const d = result.diffs?.[0]; return Boolean(d) && result.kind === family && d.path === path && d.status === (created ? "created" : "updated") && d.added === (number("linesAdded") == null ? expected.added : Number(number("linesAdded"))) && d.removed === (number("linesRemoved") == null ? expected.removed : Number(number("linesRemoved"))) && same(d.lines, expected.lines.slice(0, 400)); }
    if (path) return result.kind === family && result.diffs.length === 0 && result.diffUnavailable === !created;
  }
  return ["generic", "search", "fetch", "command"].includes(result.kind);
}
function traceClaim([turn = {}], result) {
  const live = Array.isArray(turn.toolCalls) && turn.toolCalls.length ? turn.toolCalls : turn.turnReceipt?.toolTimeline, summary = String(turn.reasoningSummary || turn.turnReceipt?.reasoningSummary || "");
  const explicit = Array.isArray(turn.activitySegments) && turn.activitySegments.length || Array.isArray(turn.turnReceipt?.activitySegments) && turn.turnReceipt.activitySegments.length || Array.isArray(turn.turnReceipt?.toolTimeline) && turn.turnReceipt.toolTimeline.length || Array.isArray(turn.toolTimeline) && turn.toolTimeline.length;
  return result.reasoningSummary === summary && same(result.toolCalls, normalizedCalls(live)) && (!summary || result.activitySegments.some(s => s.kind === "reasoning_summary")) && (typeof turn.activityOrderKnown !== "boolean" || result.activityOrderKnown === turn.activityOrderKnown) && (explicit || result.toolCalls.every(c => result.activitySegments.some(s => s.kind === "tool" && s.id === c.id && s.output === c.output)));
}
export const CHAT_CONTRACTS = Object.freeze({
  streamState: ([value], r) => same(r, { answer: "", answerIdentity: "", reasoningSummary: "", toolCalls: [], activitySegments: [], nextToolCallIndex: 0, nextActivityIndex: 0, detail: "", compacting: false, changed: false }),
  normalizedCalls: ([calls], r) => same(r, normalizedCalls(calls)),
  trace: traceClaim,
  phase: ([row], r) => r === phase(row),
  chip: ([chip, message = {}], r) => { const source = typeof chip === "object" && chip ? { ...message, ...chip } : message, raw = typeof chip === "object" && chip ? String(chip.toolId || chip.tool_id || chip.toolName || chip.label || chip.title || chip.text || chip.id || "").trim() : String(chip || "").trim(); let expected = phase(source); if (chip?.phase) expected = phase({ status: chip.phase }); else if (!(typeof chip === "object" && chip && (chip.status || chip.tone) || expected === "error")) { if (/\b(tool[-_\s]?call|calling|queued|invok)/i.test(raw)) expected = "call"; else if (/\b(tool[-_\s]?result|result)\b/i.test(raw) && !message.pending) expected = "idle"; else if (/\b(error|fail)/i.test(raw)) expected = "error"; else if (/\b(agent[-_\s]?write|compos|stream|writing)\b/i.test(raw) || message.pending) expected = message.pending ? "composing" : "running"; else if (/\b(running|in progress)\b/i.test(raw)) expected = "running"; } return r.phase === expected; },
  activity: (args, r) => same(r, activityClaim(...args)),
  visibleActivity: ([events], r) => same(r, visibleClaim(events)),
  stringField: ([value, key], r) => same(r, stringFieldClaim(value, key)),
  utf16: ([value], r) => r === repaired(value),
  diff: ([value], r) => same(r, diffClaim(value)),
  family: ([tool], r) => r === familyClaim(tool),
  presentation: presentationClaim,
  commandSummary: ([command], r) => { if (!command) return r === ""; const count = lines(command.stdout).length + lines(command.stderr).length, exit = command.exitCode; return r === `${exit != null ? `exit ${exit > 2 ** 31 ? exit - 2 ** 32 : exit} · ` : ""}${count ? `${count} ${count === 1 ? "line" : "lines"} of output` : "no output"}`; },
  surfaces: ([surfaces], r) => same(r, surfaces.map(s => s.id)) && new Set(r).size === r.length && ["workflows", "ios-studio", "lumaforge", "frameweave", "citecraft", "aegis-range", "cueledger"].every(id => r.includes(id)),
});
export function checkedChatAction(name, args, result) { if (!CHAT_CONTRACTS[name]?.(args, result)) throw new ChatContractError(name); return result; }
export function checkStreamTransition(before, event, after) {
  const ensure = okay => { if (!okay) throw new ChatContractError("streamTransition"); }, kind = String(event?.kind || ""), message = String(event?.message || "");
  if (kind === "runtime.answer_start") { const identity = JSON.stringify([event?.data?.responseId, event?.data?.itemId, event?.data?.outputIndex]); ensure(after.answerIdentity === identity && after.answer === (identity === before.answerIdentity ? before.answer : "")); }
  else if (kind === "runtime.answer_delta") ensure(after.answer === before.answer + message && after.answerIdentity === before.answerIdentity);
  else if (kind === "runtime.reasoning_summary_delta") ensure(after.reasoningSummary === before.reasoningSummary + message && after.activitySegments.at(-1).text === (before.activitySegments.at(-1)?.kind === "reasoning_summary" ? before.activitySegments.at(-1).text + message : message));
  else if (kind === "runtime.tool") { const d = event?.data && typeof event.data === "object" ? event.data : event || {}, supplied = String(d.callId || d.itemId || event?.itemId || ""), prior = supplied ? before.toolCalls.find(c => c.id === supplied) : null, type = String(d.eventType || event?.eventType || ""), status = String(d.toolStatus || d.status || (/output/i.test(type) ? "completed" : "started")).toLowerCase(), expected = { id: supplied || `tool-call-${before.nextToolCallIndex + 1}`, tool: String(d.tool || message || "tool"), status: ["completed", "failed", "running", "started"].includes(status) ? status : "started", input: display(d.input ?? d.command ?? d.code) || prior?.input || "", output: display(d.output ?? d.result) || prior?.output || "", error: display(d.error) || prior?.error || "", eventType: type }; if (expected.error) expected.status = "failed"; const calls = [...before.toolCalls], i = prior ? calls.indexOf(prior) : -1; if (i >= 0) calls[i] = expected; else calls.push(expected); ensure(same(after.toolCalls, calls) && after.activitySegments.some(s => same(s, { kind: "tool", ...expected })) && after.detail === `${expected.status === "completed" ? "Finished" : expected.status === "failed" ? "Failed" : "Using"} ${expected.tool}`); }
  else if (kind === "runtime.stream_error") ensure(after.detail === (message || "The provider stream ended before the reply completed.") && !after.compacting);
  else if (kind === "runtime.progress") { const type = String(event?.data?.eventType || event?.eventType || ""); if (type === "context.compaction.completed") ensure(!after.compacting); if (["context.compaction.started", "context.compaction.progress"].includes(type)) ensure(after.compacting); if (message) ensure(after.detail === message); }
  return after;
}
export function checkPollDelivery({ active, events, cursor, snapshot }) { if (!active || !same(events, Array.isArray(snapshot?.events) ? snapshot.events : []) || Number.isFinite(Number(snapshot?.cursor)) && cursor !== Number(snapshot.cursor)) throw new ChatContractError("pollDelivery"); }
