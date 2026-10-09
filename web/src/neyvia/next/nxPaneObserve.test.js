import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { ackBody, normalizeText, paneRequest, projectText, reportReady, sha256Fallback, sha256Hex } from "./nxPaneObserve.js";

const node = text => createHash("sha256").update(Buffer.from(text, "utf8")).digest("hex");

test("SHA-256 matches node for text, empty, unicode and block edges", async () => {
  for (const text of ["", "abc", "Actual pane content\n", "é😀 ligne\nsuite", "x".repeat(55), "x".repeat(56), "x".repeat(64), "y".repeat(1000)]) {
    assert.equal(sha256Fallback(new TextEncoder().encode(text)), node(text));
    assert.equal(await sha256Hex(text), node(text));
  }
});

test("file text is hashed as the backend reads it: LF, no BOM", () => {
  assert.equal(normalizeText("\uFEFFa\r\nb\rc\n"), "a\nb\nc\n");
  assert.equal(projectText("  a \u00a0 b \n\n  c  "), "a b\nc");
});

test("only observation-required pane.show events become requests", () => {
  assert.equal(paneRequest("7", { kind: "file", target: "x" }), null);
  assert.equal(paneRequest("", { kind: "file", target: "x", paneId: "p", observationRequired: true }), null);
  assert.deepEqual(paneRequest(9, { kind: "file", target: "C:/a.txt", paneId: "pane-1", observationRequired: true, expectedContentHash: "ab" }),
    { eventId: "9", paneId: "pane-1", kind: "file", target: "C:/a.txt", expectedContentHash: "ab" });
});

test("acks carry the exact request identity and the observed runtime and content", () => {
  const request = paneRequest("12", { kind: "browser", target: "https://example.org/", paneId: "pane-x", observationRequired: true });
  const report = { runtimeId: "browser:obscura:tab-1", contentHash: node("page") };
  assert.equal(ackBody(request, { report: null, mounted: true, visible: true }), null, "still loading: nothing is claimed");
  assert.equal(ackBody(request, { report: { ...report, empty: true }, mounted: true, visible: true }), null, "empty content is not a loaded runtime");
  assert.equal(ackBody(request, { report: { ...report, contentHash: "0" }, mounted: true, visible: true }), null);
  assert.deepEqual(ackBody(request, { report, mounted: true, visible: true }, "ui-1"), {
    id: "12", ok: true, clientId: "ui-1",
    observation: { paneId: "pane-x", runtimeId: "browser:obscura:tab-1", kind: "browser", target: "https://example.org/", contentHash: report.contentHash, mounted: true, visible: true },
  });
  const hidden = ackBody(request, { report, mounted: true, visible: false });
  assert.equal(hidden.observation.visible, false);
  const gone = ackBody(request, { report, mounted: false, visible: true });
  assert.deepEqual([gone.observation.mounted, gone.observation.visible], [false, false]);
  assert.deepEqual(ackBody(request, { report: null, mounted: false }), { id: "12", ok: false, error: "The pane closed before its content loaded", clientId: undefined });
  assert.equal(ackBody(request, { failure: "Local-only is on", report, mounted: true, visible: true }).ok, false);
  assert.equal(ackBody(null, { report, mounted: true, visible: true }), null);
  assert.equal(reportReady({ runtimeId: "x".repeat(129), contentHash: report.contentHash }), false);
});
