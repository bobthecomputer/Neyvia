import { backendBase } from "./nxApi.js";
import { docsCall } from "./nxDocsApi.js";

// The file, artifact and terminal panes' user side: POST /api/ui/panes {op, args}
// (src/grant_agent/neyvia_panes.py). A model opens the same panes with
// neyvia.pane.show and reads the terminals with neyvia.terminal.list/read.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

export const panesCall = (op, args) => docsCall("panes", op, args);

/** The live output of one terminal (Server-Sent Events, resumable from a cursor). */
export function terminalStreamUrl(id, cursor = 0) {
  return `${base()}/api/ui/panes/terminal?id=${encodeURIComponent(id)}&cursor=${cursor}`;
}

/** A backend-relative URL (a sandboxed artifact page) made absolute for an iframe. */
export function backendUrl(path) {
  return `${base()}${path}`;
}

export const isUrl = value => /^https?:\/\//i.test(String(value || ""));

/** The indentation a file already uses, so Tab in the editor matches it. */
export function indentUnit(text) {
  const lines = String(text || "").split("\n").slice(0, 400);
  let tabs = 0;
  const widths = new Map();
  for (const line of lines) {
    if (line.startsWith("\t")) tabs += 1;
    const spaces = /^( +)\S/.exec(line);
    if (spaces) widths.set(spaces[1].length, (widths.get(spaces[1].length) || 0) + 1);
  }
  const spaced = [...widths.values()].reduce((sum, count) => sum + count, 0);
  if (tabs > spaced) return "\t";
  if (!spaced) return "  ";
  const smallest = Math.min(...[...widths.keys()].filter(width => widths.get(width) > 1).concat([8]));
  return " ".repeat(smallest === 4 ? 4 : 2);
}
