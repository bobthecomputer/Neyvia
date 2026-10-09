/**
 * Guards for what a tool calls itself in the transcript.
 *
 * The registry covers 44 tools well. The failure was at its edges: anything
 * unregistered fell back to the literal word "Tool", which told the reader
 * nothing and hid which tool had actually run. Newer tools — connected browser,
 * Thunder Compute — had never been registered at all and leaked raw function
 * names like `observe_tab` into the conversation.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  humanizeNeyviaToolId,
  neyviaToolPhaseLabel,
  resolveNeyviaToolId,
} from "./neyviaToolVisuals.js";

/* ------------------------------------------- newly registered tool families */

test("connected-browser tools speak plainly through every phase", () => {
  assert.equal(neyviaToolPhaseLabel("observe_tab", "running"), "Reading the page");
  assert.equal(neyviaToolPhaseLabel("observe_tab", "success"), "Read the page");
  assert.equal(neyviaToolPhaseLabel("observe_tab", "error"), "Could not read the page");
});

test("backend command names resolve to their tool family", () => {
  assert.equal(resolveNeyviaToolId("connected_chrome_observe_command"), "browser.read");
  assert.equal(resolveNeyviaToolId("thunder_execute_proposal_command"), "browser.act");
  assert.equal(resolveNeyviaToolId("thunder_open_console_command"), "thunder");
});

test("an unverified browser action does not claim success", () => {
  // The wording has to match what the backend can actually prove.
  assert.equal(
    neyviaToolPhaseLabel("connected_chrome_act_command", "error"),
    "Action could not be verified",
  );
});

/* --------------------------------------------------- the fallback behaviour */

test("an unregistered tool shows its own name, not the word Tool", () => {
  const label = neyviaToolPhaseLabel("summarise_invoice", "running");
  assert.notEqual(label, "Tool");
  assert.equal(label, "Summarise invoice");
});

test("command wrappers are stripped from the name a person reads", () => {
  assert.equal(humanizeNeyviaToolId("rebuild_search_index_command"), "Rebuild search index");
});

test("camelCase identifiers are split into words", () => {
  assert.equal(humanizeNeyviaToolId("fetchUserProfile"), "Fetch user profile");
});

test("MCP tools read as server then action", () => {
  // Server names arrive at runtime and can never be pre-registered, so the
  // shape has to be derived rather than looked up.
  assert.equal(humanizeNeyviaToolId("mcp.linear.create_issue"), "Linear · create issue");
  assert.equal(humanizeNeyviaToolId("mcp_github_open_pull_request"), "Github · open pull request");
});

test("an empty identifier still yields something printable", () => {
  assert.equal(humanizeNeyviaToolId(""), "Tool");
  assert.equal(humanizeNeyviaToolId(null), "Tool");
});

/* ------------------------------------------- the 44 existing labels survive */

test("existing registered labels are unchanged", () => {
  // The fallback must not shadow the curated names, which are better than
  // anything derived from an identifier.
  assert.equal(neyviaToolPhaseLabel("search", "idle"), "Web Search");
  assert.equal(neyviaToolPhaseLabel("search", "running"), "Scanning results");
  assert.equal(neyviaToolPhaseLabel("pdf", "idle"), "PDF Reader");
});

test("acronyms survive sentence casing", () => {
  // "PDF" must not become "pdf" on its way to a chip.
  assert.equal(humanizeNeyviaToolId("export_PDF_report"), "Export PDF report");
  assert.equal(humanizeNeyviaToolId("refresh_API_token"), "Refresh API token");
});
