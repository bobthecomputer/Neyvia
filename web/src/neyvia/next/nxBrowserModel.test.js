import assert from "node:assert/strict";
import test from "node:test";

import { layoutPlan, parseAddress, readerFrom, suggest } from "./nxBrowserModel.js";

// The one field decides between "open this address" and "search for this";
// a wrong guess sends Paul's words to a site or a site name to the search engine.
test("address field: addresses, searches and refused schemes", () => {
  assert.deepEqual(parseAddress("  "), { kind: "empty" });
  assert.equal(parseAddress("example.com").url, "https://example.com/");
  assert.equal(parseAddress("en.wikipedia.org/wiki/Arc").url, "https://en.wikipedia.org/wiki/Arc");
  assert.equal(parseAddress("localhost:5173").url, "http://localhost:5173/");
  assert.equal(parseAddress("127.0.0.1:8080/x").url, "http://127.0.0.1:8080/x");
  assert.equal(parseAddress("https://a.dev/p?q=1").url, "https://a.dev/p?q=1");
  assert.equal(parseAddress("example.com:8443").url, "https://example.com:8443/");
  assert.equal(parseAddress("arc browser spaces").kind, "search");
  assert.match(parseAddress("arc browser").url, /duckduckgo\.com\/\?q=arc%20browser$/);
  assert.equal(parseAddress("hello").kind, "search");
  assert.equal(parseAddress("javascript:alert(1)").kind, "blocked");
  assert.equal(parseAddress("file:///C:/Windows").kind, "blocked");
  assert.equal(parseAddress("https://user:pw@site.com").kind, "blocked");
});

test("autocomplete: open tabs first, one row per address, frequent visits rank higher", () => {
  const history = [
    { url: "https://github.com/a", title: "A", at: 1 },
    { url: "https://github.com/b", title: "B", at: 2 },
    { url: "https://github.com/b", title: "B", at: 3 },
    { url: "https://news.example/github", title: "Git news", at: 4 },
  ];
  const tabs = [{ id: "t1", url: "https://github.com/a", title: "A" }];
  const rows = suggest("git", { tabs, history });
  assert.equal(rows[0].type, "tab");
  assert.equal(rows[0].tabId, "t1");
  assert.equal(rows.filter(row => row.url === "https://github.com/a").length, 1);
  assert.equal(rows[1].url, "https://github.com/b");
  assert.deepEqual(suggest("", { history }).map(row => row.url), ["https://news.example/github", "https://github.com/b", "https://github.com/a"]);
});

test("reader keeps the article, drops menus", () => {
  const observation = {
    title: "Arc (web browser) - Wikipedia", url: "https://en.wikipedia.org/wiki/Arc",
    text: "Main menu\nContents\nArc (web browser)\nFrom Wikipedia, the free encyclopedia\nArc is a freeware web browser developed by The Browser Company and released in 2023 for macOS.\nHistory\nThe Browser Company was founded in 2019 by Josh Miller and Hursh Agrawal in New York.\nSee also",
    elements: [{ role: "h1", name: "Arc (web browser)" }, { role: "h2", name: "History" }, { role: "h2", name: "See also" }],
  };
  const reader = readerFrom(observation);
  assert.equal(reader.title, "Arc (web browser)");
  assert.equal(reader.site, "en.wikipedia.org");
  assert.deepEqual(reader.blocks.map(block => block.type), ["p", "h", "p"]);
  assert.ok(!reader.blocks.some(block => block.text === "Main menu" || block.text === "See also"));
});

test("native layout: measured slots show, everything else hides, overlays hide all", () => {
  const tabs = [{ id: "a", live: true }, { id: "b", live: true }, { id: "c", live: false }, { id: "d", live: true, engine: "obscura" }];
  const plan = layoutPlan(tabs, [{ tabId: "a", rect: { x: 10, y: 20, width: 300, height: 200 } }]);
  assert.deepEqual(plan.map(row => [row.tabId, row.visible]), [["a", true], ["b", false]]);
  assert.equal(plan[0].x, 10);
  assert.ok(layoutPlan(tabs, [{ tabId: "a", rect: { x: 0, y: 0, width: 9, height: 9 } }], true).every(row => !row.visible));
});
