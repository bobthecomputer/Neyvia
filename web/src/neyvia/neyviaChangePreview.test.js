import test from "node:test";
import assert from "node:assert/strict";
import { classifyChangedPath, classifyPreviewTarget, recommendPreview } from "./neyviaChangePreview.js";

test("stylesheets and components are high confidence", () => {
  assert.equal(classifyChangedPath("web/src/neyvia/neyviaChips.css").confidence, "high");
  assert.equal(classifyChangedPath("src/components/Sidebar.tsx").confidence, "high");
});

test("a path signal beats the extension", () => {
  // A .css file under tests/ is still a test, not a visual change.
  assert.equal(classifyChangedPath("tests/theme.css").confidence, "none");
  assert.equal(classifyChangedPath("src/Sidebar.test.tsx").confidence, "none");
});

test("build output and docs are never previewed", () => {
  assert.equal(classifyChangedPath("dist/assets/app.css").confidence, "none");
  assert.equal(classifyChangedPath("docs/DESIGN.md").confidence, "none");
});

test("a purely non-visual change offers no preview", () => {
  const result = recommendPreview(["src/grant_agent/cli.py", "README.md"]);
  assert.equal(result.recommended, false);
  assert.equal(result.label, "No visible changes expected");
});

test("a mixed set recommends a preview and names only the visual files", () => {
  const result = recommendPreview([
    { path: "web/src/neyvia/neyviaChips.css" },
    { path: "tests/test_thing.py" },
  ]);
  assert.equal(result.recommended, true);
  assert.deepEqual(result.visualPaths, ["web/src/neyvia/neyviaChips.css"]);
  assert.deepEqual(result.ignoredPaths, ["tests/test_thing.py"]);
});

test("the wording claims a file could change the screen, never that it did", () => {
  // Knowing an edit was visual would require a diff; overclaiming here would
  // train the reader to distrust the preview prompt.
  const result = recommendPreview(["src/components/Thing.tsx"]);
  assert.match(result.label, /worth checking/);
  assert.doesNotMatch(result.label, /changed the|did change/);
});

test("confidence degrades for files that only might matter", () => {
  assert.equal(recommendPreview(["config/tokens.json"]).confidence, "high"); // tokens path signal
  assert.equal(recommendPreview(["src/util.ts"]).confidence, "medium");
});

test("web previews, executables, and captured desktop windows stay distinct", () => {
  assert.equal(classifyPreviewTarget({ url: "http://127.0.0.1:4173" }).kind, "web");
  assert.equal(classifyPreviewTarget({ executablePath: "dist/Neyvia.exe" }).kind, "executable");
  assert.equal(classifyPreviewTarget({ windowId: "neyvia-main", processId: 42 }).kind, "desktop-window");
  assert.equal(classifyPreviewTarget({ captureUrl: "/proof/window.png" }).kind, "desktop-capture");
});

test("an executable invites a real launch and capture, not a fake preview", () => {
  const result = recommendPreview([], [{ executablePath: "dist/Neyvia.exe" }]);
  assert.equal(result.recommended, true);
  assert.equal(result.targetReady, false);
  assert.equal(result.supportsDesktop, true);
  assert.match(result.label, /capture its window/i);
});

test("a captured desktop app is ready for inspection", () => {
  const result = recommendPreview([], [{ captureUrl: "/proof/window.png", processId: 42 }]);
  assert.equal(result.targetReady, true);
  assert.match(result.label, /ready to inspect/i);
});
