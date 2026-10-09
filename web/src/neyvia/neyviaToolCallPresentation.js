import { checkedChatAction } from "./neyviaChatContracts.js";
/**
 * Turn a recorded tool call into what a person wants to see.
 *
 * Tool activity arrives as the exact JSON a model sent and a tool returned.
 * That is the right evidence and the wrong interface: "View tool input and
 * result" hides the one line that matters — the command that actually ran,
 * or the lines a file edit actually changed. This module reads the recorded
 * input and output and returns a presentation: the command with its shell,
 * working directory, exit code and output; or the file with a line diff.
 *
 * Two rules keep it honest:
 *   * Only recorded values are shown. A diff is drawn from the tool's own
 *     diff, or from content the model sent; nothing is reconstructed.
 *   * Payloads can be truncated for display, which breaks JSON. Fields are
 *     then read leniently and the presentation says it is incomplete.
 */

const TRUNCATION_MARK = "… [truncated]";
const MAX_DIFF_LINES = 400;
const MAX_OUTPUT_CHARS = 20_000;

function parseJsonObject(value) {
  if (value && typeof value === "object") return value;
  const text = String(value ?? "").trim();
  if (!text || !/^[[{]/.test(text)) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Read one string field from JSON text that may have been cut short.
 * Returns {value, complete} or null when the field is absent.
 */
function readJsonStringFieldUnchecked(text, key) {
  const source = String(text ?? "");
  const match = new RegExp(`"${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\s*:\\s*"`).exec(source);
  if (!match) return null;
  let index = match.index + match[0].length;
  let raw = "";
  while (index < source.length) {
    const char = source[index];
    if (char === "\\") {
      raw += source.slice(index, index + 2);
      index += 2;
      continue;
    }
    if (char === '"') {
      try {
        return { value: JSON.parse(`"${raw}"`), complete: true };
      } catch {
        return { value: raw, complete: true };
      }
    }
    raw += char;
    index += 1;
  }
  // Cut short: drop the truncation marker and any half-written escape, then decode.
  let trimmed = raw.endsWith(TRUNCATION_MARK) ? raw.slice(0, -TRUNCATION_MARK.length) : raw;
  const escapes = /(\\+)(u[0-9a-fA-F]{0,3})?$/.exec(trimmed);
  if (escapes && (escapes[1].length % 2 === 1)) trimmed = trimmed.slice(0, escapes.index + escapes[1].length - 1);
  try {
    return { value: JSON.parse(`"${trimmed}"`), complete: false };
  } catch {
    return { value: trimmed, complete: false };
  }
}

function readNumberField(text, key) {
  const match = new RegExp(`"${key}"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)`).exec(String(text ?? ""));
  return match ? Number(match[1]) : null;
}

function field(object, text, ...keys) {
  for (const key of keys) {
    const value = object?.[key];
    if (typeof value === "string" && value) return { value, complete: true };
  }
  for (const key of keys) {
    const lenient = readJsonStringField(text, key);
    if (lenient && lenient.value) return lenient;
  }
  return null;
}

function numberField(object, text, ...keys) {
  for (const key of keys) {
    const value = object?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  for (const key of keys) {
    const value = readNumberField(text, key);
    if (value !== null) return value;
  }
  return null;
}

/** Old tool output on Windows sometimes arrives as UTF-16 read as UTF-8. */
function repairUtf16TextUnchecked(value) {
  const text = String(value ?? "");
  const nulls = (text.match(/\u0000/g) || []).length;
  if (!nulls || nulls < text.length / 5) return text;
  return text.replace(/﻿/g, "").replace(/\u0000/g, "");
}

function boundedOutput(value) {
  const text = repairUtf16Text(value).replace(/\r\n/g, "\n").replace(/\n+$/, "");
  return text.length > MAX_OUTPUT_CHARS ? `${text.slice(0, MAX_OUTPUT_CHARS)}\n${TRUNCATION_MARK}` : text;
}

/** Canonical tool family, independent of gateway prefixes and harness naming. */
function toolFamilyUnchecked(tool) {
  const id = String(tool || "").trim().toLowerCase()
    .replace(/^mcp[._-]+neyvia[._-]+/, "")
    .replace(/^neyvia[._-]+/, "");
  if (/(^|[._-])(terminal[._-]exec|exec[._-]?command|shell|bash|powershell|run[._-]?command|command[._-]execution|local[._-]shell)($|[._-])/.test(id)) return "command";
  if (/(apply[._-]?patch|str[._-]replace|(^|[._-])edit($|[._-])|multi[._-]?edit|file[._-]change)/.test(id)) return "edit";
  if (/(workspace[._-]write|write[._-]?file|file[._-]write|(^|[._-])write$|create[._-]?file)/.test(id)) return "write";
  if (/(workspace[._-]read|read[._-]?file|file[._-]read|(^|[._-])read$|view[._-]?file|open[._-]?file)/.test(id)) return "read";
  if (/(search|grep|glob|find[._-]?files|list[._-]?dir|(^|[._-])ls$)/.test(id)) return "search";
  if (/(web[._-]fetch|browser[._-]navigate|http|url)/.test(id)) return "fetch";
  return "generic";
}

function leaf(path) {
  const text = String(path || "").replace(/[\\/]+$/, "");
  return text.split(/[\\/]/).pop() || text;
}

function splitLines(text) {
  const normalized = String(text ?? "").replace(/\r\n/g, "\n");
  if (!normalized) return [];
  const lines = normalized.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/**
 * Parse a unified diff into typed display lines with counts. Lines carry the
 * number they have in the new file (or the old one, for removals) when the
 * hunk headers say where they are.
 */
function parseUnifiedDiffUnchecked(text) {
  const lines = [];
  let added = 0;
  let removed = 0;
  let oldLine = null;
  let newLine = null;
  for (const line of splitLines(text)) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      lines.push({ type: "hunk", text: line });
    } else if (line.startsWith("@@")) {
      lines.push({ type: "hunk", text: line });
    } else if (line.startsWith("+")) {
      added += 1;
      lines.push({ type: "add", text: line.slice(1), number: newLine });
      if (newLine !== null) newLine += 1;
    } else if (line.startsWith("-")) {
      removed += 1;
      lines.push({ type: "del", text: line.slice(1), number: oldLine });
      if (oldLine !== null) oldLine += 1;
    } else if (!line.startsWith("\\")) {
      lines.push({ type: "ctx", text: line.startsWith(" ") ? line.slice(1) : line, number: newLine });
      if (newLine !== null) newLine += 1;
      if (oldLine !== null) oldLine += 1;
    }
  }
  return { lines, added, removed };
}

/** Parse the `*** Begin Patch` format some harnesses use for edits. */
function parseApplyPatch(text) {
  const files = [];
  let current = null;
  for (const line of splitLines(text)) {
    const header = /^\*\*\* (Add|Update|Delete) File: (.+)$/.exec(line);
    if (header) {
      current = { path: header[2].trim(), status: header[1].toLowerCase() === "add" ? "created" : header[1].toLowerCase() === "delete" ? "deleted" : "updated", body: [] };
      files.push(current);
      continue;
    }
    if (!current || /^\*\*\* (Begin|End) Patch/.test(line) || /^\*\*\* Move to:/.test(line)) continue;
    current.body.push(line);
  }
  return files.map(file => ({ ...file, ...parseUnifiedDiff(file.body.join("\n")) }));
}

function lineDiff(oldText, newText) {
  const before = splitLines(oldText);
  const after = splitLines(newText);
  // Keep shared leading/trailing lines as context; the middle is the change.
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1;
  let endBefore = before.length;
  let endAfter = after.length;
  while (endBefore > start && endAfter > start && before[endBefore - 1] === after[endAfter - 1]) {
    endBefore -= 1;
    endAfter -= 1;
  }
  const lines = [
    ...before.slice(Math.max(0, start - 2), start).map(text => ({ type: "ctx", text })),
    ...before.slice(start, endBefore).map(text => ({ type: "del", text })),
    ...after.slice(start, endAfter).map(text => ({ type: "add", text })),
    ...after.slice(endAfter, endAfter + 2).map(text => ({ type: "ctx", text })),
  ];
  return { lines, added: endAfter - start, removed: endBefore - start };
}

function limitDiff(diff) {
  if (diff.lines.length <= MAX_DIFF_LINES) return { ...diff, truncated: Boolean(diff.truncated) };
  return { ...diff, lines: diff.lines.slice(0, MAX_DIFF_LINES), truncated: true };
}

function toolResultOf(output) {
  const parsed = parseJsonObject(output);
  if (!parsed) return null;
  if (parsed.toolResult && typeof parsed.toolResult === "object") return { ...parsed, ...parsed.toolResult };
  if (parsed.result && typeof parsed.result === "object" && !Array.isArray(parsed.result)) return { ...parsed, ...parsed.result };
  return parsed;
}

function presentCommand(call, input, inputText, result, resultText) {
  const command = field(input, inputText, "command", "cmd", "script") || field(result, resultText, "command");
  if (!command) return null;
  const shell = field(input, inputText, "shell")?.value || field(result, resultText, "shell")?.value || "";
  const cwd = field(input, inputText, "cwd", "workdir", "workingDirectory")?.value || field(result, resultText, "cwd")?.value || "";
  const exitCode = numberField(result, resultText, "exitCode", "exit_code", "returncode");
  const durationMs = numberField(result, resultText, "durationMs", "duration_ms");
  const stdout = field(result, resultText, "stdout", "output")?.value || "";
  const stderr = field(result, resultText, "stderr")?.value || "";
  return {
    kind: "command",
    title: "Ran",
    subject: shell ? shell.replace(/^powershell$/i, "PowerShell").replace(/^cmd$/i, "cmd") : "command",
    command: {
      text: String(command.value).replace(/\r\n/g, "\n"),
      complete: command.complete,
      shell,
      cwd,
      cwdLabel: cwd ? leaf(cwd) : "",
      exitCode,
      durationMs,
      stdout: boundedOutput(stdout),
      stderr: boundedOutput(stderr),
      outputTruncated: Boolean(result?.stdoutTruncated || result?.stderrTruncated || result?.outputTruncated),
    },
  };
}

function presentWrite(family, input, inputText, result, resultText) {
  const patchText = field(input, inputText, "patch", "input")?.value || "";
  if (/\*\*\* Begin Patch/.test(patchText)) {
    const files = parseApplyPatch(patchText);
    if (files.length) {
      const first = files[0];
      return {
        kind: "edit",
        title: first.status === "created" ? "Created" : first.status === "deleted" ? "Deleted" : "Edited",
        subject: files.length > 1 ? `${leaf(first.path)} and ${files.length - 1} more` : leaf(first.path),
        path: first.path,
        diffs: files.map(file => ({ path: file.path, status: file.status, ...limitDiff(file) })),
      };
    }
  }
  const path = field(input, inputText, "path", "filePath", "file_path", "file", "target")?.value
    || field(result, resultText, "path")?.value || "";
  const recordedDiff = field(result, resultText, "diff")?.value || "";
  const oldString = field(input, inputText, "oldString", "old_string", "old_str", "search")?.value;
  const newString = field(input, inputText, "newString", "new_string", "new_str", "replace")?.value;
  const content = field(input, inputText, "content", "contents", "text", "file_text");
  const status = String(result?.status || readJsonStringField(resultText, "status")?.value || "").toLowerCase();
  // workspace.write only replaces a file when the model names its current hash.
  const expectsExisting = Boolean(field(input, inputText, "expectedSha256", "expected_sha256"));
  const created = ["created", "updated"].includes(status)
    ? status === "created"
    : family === "write" && !expectsExisting && !recordedDiff && typeof oldString !== "string";
  let diff = null;
  if (recordedDiff) {
    diff = { ...parseUnifiedDiff(recordedDiff), truncated: Boolean(result?.diffTruncated) };
  } else if (typeof oldString === "string" && typeof newString === "string") {
    diff = lineDiff(oldString, newString);
  } else if (content && created) {
    const lines = splitLines(content.value).map((text, index) => ({ type: "add", text, number: index + 1 }));
    diff = { lines, added: lines.length, removed: 0, truncated: !content.complete };
  }
  if (!path && !diff) return null;
  const added = numberField(result, resultText, "linesAdded");
  const removed = numberField(result, resultText, "linesRemoved");
  const finalDiff = diff ? limitDiff({
    ...diff,
    added: added ?? diff.added,
    removed: removed ?? diff.removed,
  }) : null;
  return {
    kind: family === "edit" ? "edit" : "write",
    title: created ? "Created" : "Edited",
    subject: path ? leaf(path) : "file",
    path,
    diffs: finalDiff ? [{ path, status: created ? "created" : "updated", ...finalDiff }] : [],
    diffUnavailable: !finalDiff && !created,
  };
}

function presentRead(input, inputText, result, resultText) {
  const path = field(input, inputText, "path", "filePath", "file_path", "file")?.value || field(result, resultText, "path")?.value;
  if (!path) return null;
  const content = field(result, resultText, "content", "text")?.value || "";
  return {
    kind: "read",
    title: "Read",
    subject: leaf(path),
    path,
    preview: boundedOutput(content),
    lineCount: content ? splitLines(content).length : null,
  };
}

function presentSearch(input, inputText) {
  const query = field(input, inputText, "query", "pattern", "q", "glob", "path")?.value;
  return query ? { kind: "search", title: "Searched", subject: query } : null;
}

function presentFetch(input, inputText) {
  const url = field(input, inputText, "url", "href", "target")?.value;
  return url ? { kind: "fetch", title: "Opened", subject: url } : null;
}

/**
 * @returns {{kind: string, title: string, subject: string, command?: object,
 *   diffs?: object[], path?: string, preview?: string, error: string, failed: boolean}}
 */
function presentToolCallUnchecked(call = {}) {
  const tool = String(call?.tool || "tool");
  const family = toolFamily(tool);
  const inputText = String(call?.input ?? "");
  const input = parseJsonObject(inputText) || {};
  const errorText = String(call?.error ?? "");
  // Failed tools often put their full result (exit code, stderr) in `error`.
  const resultText = String(call?.output || "") || errorText;
  const result = toolResultOf(resultText) || {};
  const failure = String(
    result?.failure?.message || (errorText && !parseJsonObject(errorText) ? errorText : "") || result?.error || "",
  ).trim();
  let presentation = null;
  if (family === "command") presentation = presentCommand(call, input, inputText, result, resultText);
  else if (family === "write" || family === "edit") presentation = presentWrite(family, input, inputText, result, resultText);
  else if (family === "read") presentation = presentRead(input, inputText, result, resultText);
  else if (family === "search") presentation = presentSearch(input, inputText);
  else if (family === "fetch") presentation = presentFetch(input, inputText);
  if (!presentation && field(input, inputText, "command")) presentation = presentCommand(call, input, inputText, result, resultText);
  return {
    kind: "generic",
    title: "",
    subject: "",
    ...(presentation || {}),
    family,
    error: failure,
    failed: String(call?.status || "").toLowerCase() === "failed" || Boolean(failure && result?.ok === false),
  };
}

/** One-line summary of a command's output for a collapsed row. */
function commandOutputSummaryUnchecked(command) {
  if (!command) return "";
  const lines = splitLines(command.stdout).length + splitLines(command.stderr).length;
  const parts = [];
  if (command.exitCode !== null && command.exitCode !== undefined) parts.push(`exit ${command.exitCode > 2 ** 31 ? command.exitCode - 2 ** 32 : command.exitCode}`);
  parts.push(lines ? `${lines} ${lines === 1 ? "line" : "lines"} of output` : "no output");
  return parts.join(" · ");
}

export function readJsonStringField(...args) { return checkedChatAction("stringField", args, readJsonStringFieldUnchecked(...args)); }

export function repairUtf16Text(...args) { return checkedChatAction("utf16", args, repairUtf16TextUnchecked(...args)); }

export function toolFamily(...args) { return checkedChatAction("family", args, toolFamilyUnchecked(...args)); }

export function parseUnifiedDiff(...args) { return checkedChatAction("diff", args, parseUnifiedDiffUnchecked(...args)); }

export function presentToolCall(...args) { return checkedChatAction("presentation", args, presentToolCallUnchecked(...args)); }

export function commandOutputSummary(...args) { return checkedChatAction("commandSummary", args, commandOutputSummaryUnchecked(...args)); }
