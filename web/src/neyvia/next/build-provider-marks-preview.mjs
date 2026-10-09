// Builds provider-marks-preview.html: every registry mark at 12/16/20/28/48px on dark and
// light, in colour and mono, with the SVGs inlined. Run from the repo root:
//   node web/src/neyvia/next/build-provider-marks-preview.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { PROVIDER_MARKS, providerMarkIds } from "./providerMarksData.js";
import { providerMarkSvgString } from "./providerMarkModel.js";

const here = (name) => fileURLToPath(new URL(name, import.meta.url));
const css = readFileSync(here("providerMark.css"), "utf8");

const SIZES = [12, 16, 20, 28, 48];
const STRIP_SIZES = [16, 20, 28];
const FALLBACK_IDS = ["acme", "zed-editor", "42", ""];
const THEMES = [
  { theme: "dark", label: "Dark #0f1115", bg: "#0f1115", fg: "#c9d1e0", line: "#232936" },
  { theme: "light", label: "Light #ffffff", bg: "#ffffff", fg: "#3a4254", line: "#dfe3ea" },
];
const MODES = [
  { mono: false, label: "Colour" },
  { mono: true, label: "Mono (currentColor)" },
];

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

function rowFor(id, mono) {
  const entry = PROVIDER_MARKS[id];
  const cells = SIZES.map((size) => `<td class="c" style="width:${size + 28}px"><span class="box" style="width:${size}px;height:${size}px">${providerMarkSvgString(id, { size, mono })}</span></td>`).join("");
  return `<tr><th scope="row"><code>${esc(id)}</code><small>${esc(entry.label)}</small></th>${cells}</tr>`;
}

function stripFor(size, mono) {
  return `<div class="strip" data-size="${size}">${providerMarkIds.map((id) => `<span class="box" style="width:${size}px;height:${size}px" title="${esc(id)}">${providerMarkSvgString(id, { size, mono })}</span>`).join("")}</div>`;
}

function fallbackStrip(mono) {
  return `<div class="strip">${FALLBACK_IDS.map((id) => SIZES.map((size) => `<span class="box" style="width:${size}px;height:${size}px">${providerMarkSvgString(id, { size, mono, title: id || undefined })}</span>`).join("")).join('<i class="sep"></i>')}</div>`;
}

function panel({ theme, label, bg, fg, line }, { mono, label: modeLabel }) {
  return `<section class="panel" id="${theme}-${mono ? "mono" : "colour"}" data-theme="${theme}" style="--bg:${bg};--fg:${fg};--line:${line}">
  <h2>${esc(label)} <span>${esc(modeLabel)}</span></h2>
  <div class="strips">${STRIP_SIZES.map((size) => stripFor(size, mono)).join("")}</div>
  <table><thead><tr><th></th>${SIZES.map((size) => `<th>${size}</th>`).join("")}</tr></thead><tbody>${providerMarkIds.map((id) => rowFor(id, mono)).join("")}</tbody></table>
  <h3>Fallback for unknown ids</h3>
  ${fallbackStrip(mono)}
</section>`;
}

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Neyvia provider marks</title>
<style>
${css}
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #07080b; color: #c9d1e0; font: 13px/1.4 "Segoe UI", system-ui, sans-serif; }
h1 { margin: 0 0 4px; font-size: 18px; }
.lede { margin: 0 0 16px; color: #8a93a6; }
.tools { margin: 0 0 20px; color: #8a93a6; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.panel { background: var(--bg); color: var(--fg); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px 20px; }
.panel h2 { margin: 0 0 12px; font-size: 14px; }
.panel h2 span { font-weight: 400; opacity: .65; margin-left: 6px; }
.panel h3 { margin: 18px 0 8px; font-size: 12px; font-weight: 600; opacity: .7; }
.strips { display: grid; gap: 8px; margin-bottom: 14px; }
.strip { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; }
.sep { width: 1px; align-self: stretch; background: var(--line); }
table { width: 100%; border-collapse: collapse; }
th, td { border-top: 1px solid var(--line); }
thead th { border-top: 0; font-weight: 500; opacity: .6; text-align: center; padding: 0 0 6px; }
tbody th { text-align: left; font-weight: 400; padding: 6px 8px 6px 0; white-space: nowrap; }
tbody th code { font: 12px "Cascadia Code", ui-monospace, monospace; display: block; }
tbody th small { opacity: .55; }
td.c { text-align: center; padding: 6px 0; }
.box { display: inline-flex; align-items: center; justify-content: center; vertical-align: middle; }
.box svg { display: block; }
body.show-boxes .box { outline: 1px dashed rgba(255, 64, 200, .55); outline-offset: 0; }
body.show-boxes .box svg { background: rgba(255, 64, 200, .07); }
</style>
</head>
<body>
<h1>Neyvia provider marks</h1>
<p class="lede">${providerMarkIds.length} marks from providerMarksData.js. Rows are ${SIZES.join(" / ")} px. The strips show every mark at ${STRIP_SIZES.join(", ")} px to compare optical weight.</p>
<p class="tools"><label><input type="checkbox" onchange="document.body.classList.toggle('show-boxes', this.checked)"> Show 1:1 boxes (centring check)</label></p>
<div class="grid">
${THEMES.flatMap((theme) => MODES.map((mode) => ({ theme, mode }))).sort((a, b) => Number(a.mode.mono) - Number(b.mode.mono)).map(({ theme, mode }) => panel(theme, mode)).join("\n")}
</div>
</body>
</html>
`;

writeFileSync(here("provider-marks-preview.html"), html);
console.log(`wrote provider-marks-preview.html (${providerMarkIds.length} marks, ${Math.round(html.length / 1024)} KB)`);
