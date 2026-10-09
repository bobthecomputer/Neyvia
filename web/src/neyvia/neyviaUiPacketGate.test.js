import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const shellSourceUrl = new URL("./NeyviaWorkspace.jsx", import.meta.url);
const surfaceSourceUrl = new URL("./NeyviaShellSurfaces.jsx", import.meta.url);
const finishCssUrl = new URL("./neyviaProductFinish.css", import.meta.url);
const shellCssUrl = new URL("./neyviaShell.css", import.meta.url);
const mainSourceUrl = new URL("../main.tsx", import.meta.url);

test("default product surfaces keep raw proof budgets behind exhaustive detail", async () => {
  const [shellSource, surfaceSource] = await Promise.all([
    readFile(shellSourceUrl, "utf8"),
    readFile(surfaceSourceUrl, "utf8"),
  ]);

  assert.match(shellSource, /detailLevel === "exhaustive"/);
  assert.doesNotMatch(shellSource, /detailLevel !== "minimal"/);
  assert.match(surfaceSource, /<details[\s\S]*data-neyvia-proof-strip="true"/);
  assert.match(surfaceSource, /className="neyvia-proof-details"/);
});

test("phone Agent Live owns the viewport instead of sharing it with preview", async () => {
  const css = await readFile(finishCssUrl, "utf8");

  assert.match(css, /max-width: 700px[\s\S]*agent-companion-panel[\s\S]*display: none !important/);
  assert.match(css, /grid-template-rows: auto minmax\(0, 1fr\) auto !important/);
  assert.match(css, /fluxos-composer\[data-composer-mode\][\s\S]*position: relative !important/);
});

test("expanded domain experiences use the page scroll owner", async () => {
  const [shellCss, finishCss] = await Promise.all([
    readFile(shellCssUrl, "utf8"),
    readFile(finishCssUrl, "utf8"),
  ]);

  assert.match(shellCss, /\.neyvia-domain-list\s*\{[\s\S]*max-height: none;[\s\S]*overflow: visible;/);
  assert.match(finishCss, /data-neyvia-surface="library"[\s\S]*\.neyvia-domain-list[\s\S]*overflow: visible !important/);
});

test("product finish loads after workspace chrome so release constraints win", async () => {
  const mainSource = await readFile(mainSourceUrl, "utf8");
  const workspaceIndex = mainSource.indexOf('import "./neyvia/neyviaSessionWorkspaceRoot.css";');
  const finishIndex = mainSource.indexOf('import "./neyvia/neyviaProductFinish.css";');

  assert.ok(workspaceIndex >= 0, "workspace chrome stylesheet must remain imported");
  assert.ok(finishIndex > workspaceIndex, "product finish must be the final global visual authority");
});

test("harness telemetry is disclosed on demand instead of becoming a metric wall", async () => {
  const harnessSource = await readFile(new URL("./HarnessesSurface.jsx", import.meta.url), "utf8");

  assert.match(harnessSource, /<details[\s\S]*className="neyvia-harnesses__pulse"/);
  assert.match(harnessSource, /<summary>[\s\S]*Observed evidence/);
});

test("mobile Settings uses a wrapped grid rather than a clipped tab scroller", async () => {
  const css = await readFile(finishCssUrl, "utf8");

  assert.match(css, /data-neyvia-surface="settings"[\s\S]*\.fluxos-settings-nav[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\) !important/);
  assert.match(css, /\.fluxos-settings-nav > button[\s\S]*white-space: normal !important/);
});

test("Session map freezes the covered conversation scroll owner", async () => {
  const css = await readFile(finishCssUrl, "utf8");

  assert.match(css, /body:has\(\.neyvia-workspace-drawer-backdrop\)[\s\S]*\.fluxos-thread[\s\S]*overflow: hidden !important/);
});

test("Workflows uses tonal blocks rather than divider and timeline lines", async () => {
  const css = await readFile(finishCssUrl, "utf8");

  assert.match(css, /data-neyvia-surface="workflows"[\s\S]*\.neyvia-workflow-list > article::before[\s\S]*display: none !important/);
  assert.match(css, /\.neyvia-workflow-action button[\s\S]*box-shadow: none !important/);
});
