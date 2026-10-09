/**
 * Guards for the tool / app / CLI distinction and for file-change counts.
 *
 * The count tests are the important ones: the failure they prevent is a file
 * summary that shows "+0 −0" for an edit whose line counts were never reported,
 * which reads as "nothing changed" and is undetectable by the person reading it.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  SURFACE_APP,
  SURFACE_CLI,
  SURFACE_META,
  SURFACE_TOOL,
  classifyWorkSurface,
  describeFileChanges,
  normalizeFileChange,
  summarizeFileChanges,
} from "./neyviaWorkSurfaces.js";

/* ------------------------------------------------------------ kinds */

test("a CLI is yours to drive", () => {
  for (const id of ["claude-code", "opencode", "hermes", "cursor"]) {
    assert.equal(classifyWorkSurface(id), SURFACE_CLI, `${id} is a CLI`);
  }
  assert.equal(SURFACE_META[SURFACE_CLI].drivenBy, "you");
});

test("an app is used by the model and openable by you", () => {
  for (const id of ["pdf", "image", "thunder"]) {
    assert.equal(classifyWorkSurface(id), SURFACE_APP, `${id} is an app`);
  }
  assert.equal(SURFACE_META[SURFACE_APP].openable, true);
});

test("a plain tool is model-only and not openable", () => {
  assert.equal(classifyWorkSurface("search"), SURFACE_TOOL);
  assert.equal(SURFACE_META[SURFACE_TOOL].openable, false);
  assert.equal(SURFACE_META[SURFACE_TOOL].drivenBy, "model");
});

test("a route-prefixed CLI still classifies as a CLI", () => {
  assert.equal(classifyWorkSurface("claude-code.session"), SURFACE_CLI);
});

test("registry categories promote a surface to an app", () => {
  assert.equal(classifyWorkSurface("whatever", { category: "design" }), SURFACE_APP);
  assert.equal(classifyWorkSurface("whatever", { category: "orchestration" }), SURFACE_APP);
});

test("an unknown surface understates rather than promotes itself", () => {
  // Misclassifying downwards hides a surface; upwards invites the reader to
  // open something that cannot be opened.
  assert.equal(classifyWorkSurface("something_new"), SURFACE_TOOL);
});

/* ---------------------------------------------------------- changes */

test("counts are read from whichever field the provider used", () => {
  assert.deepEqual(normalizeFileChange({ path: "a.css", added: 40, removed: 2 }), {
    path: "a.css", kind: "edited", added: 40, removed: 2, counted: true,
  });
  assert.equal(normalizeFileChange({ file: "b.js", insertions: 7 }).added, 7);
  assert.equal(normalizeFileChange({ name: "c.py", deletions: 3 }).removed, 3);
});

test("a change with no counts is marked uncounted, not zeroed", () => {
  const change = normalizeFileChange({ path: "d.ts", kind: "edited" });
  assert.equal(change.counted, false);
  assert.equal(change.added, null);
  assert.equal(change.removed, null);
});

test("a bare path string is still a usable change", () => {
  assert.deepEqual(normalizeFileChange("src/app.js"), {
    path: "src/app.js", kind: "edited", added: null, removed: null, counted: false,
  });
});

test("a change with no path is discarded", () => {
  assert.equal(normalizeFileChange({ added: 5 }), null);
  assert.equal(normalizeFileChange(null), null);
});

test("a summary refuses to total lines it never saw", () => {
  const summary = summarizeFileChanges([
    { path: "a.css", added: 40, removed: 2 },
    { path: "b.js" },
  ]);
  assert.equal(summary.fileCount, 2);
  assert.equal(summary.partial, true, "one file had no counts");
  assert.match(summary.label, /2 files changed/);
});

test("a fully uncounted set reports files without inventing zeroes", () => {
  const summary = summarizeFileChanges(["a.js", "b.js", "c.js"]);
  assert.equal(summary.added, null);
  assert.equal(summary.removed, null);
  assert.equal(summary.label, "3 files changed");
  assert.doesNotMatch(summary.label, /\+0|−0/, "must not render zero counts");
});

test("a genuinely empty edit says so, and differs from an unmeasured one", () => {
  // These two must never render identically.
  const measured = describeFileChanges(1, 0, 0);
  const unmeasured = describeFileChanges(1, null, null);
  assert.equal(measured, "1 file changed, no lines added or removed");
  assert.equal(unmeasured, "1 file changed");
  assert.notEqual(measured, unmeasured);
});

test("the summary line reads the way a person would say it", () => {
  assert.equal(describeFileChanges(0, null, null), "No files changed");
  assert.equal(describeFileChanges(1, 40, 0), "1 file changed, +40");
  assert.equal(describeFileChanges(3, 40, 12), "3 files changed, +40 −12");
});

test("negative or nonsense counts are treated as absent", () => {
  const change = normalizeFileChange({ path: "a.js", added: -5, removed: "many" });
  assert.equal(change.counted, false);
});
