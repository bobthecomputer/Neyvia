// The integrated browser's pure logic (plan 15 T20): what the address field
// means, what it suggests, how a tab's state reads, what reader mode keeps
// from a page, and where each native tab goes on screen. No I/O here.

export const SEARCH_URL = "https://duckduckgo.com/?q=";

const HOST = /^(localhost|\[[0-9a-f:]+\]|(\d{1,3}\.){3}\d{1,3}|([a-z0-9-]+\.)+[a-z][a-z0-9-]{1,62})(:\d{1,5})?([/?#].*)?$/i;
const LOCAL = /^(localhost|127\.|\[::1\]|0\.0\.0\.0)/i;

/**
 * What the single address/search field means.
 * -> {kind: "empty"} | {kind: "url", url} | {kind: "search", url, query} | {kind: "blocked", reason}
 */
export function parseAddress(raw) {
  const text = String(raw ?? "").trim();
  if (!text) return { kind: "empty" };
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(text)?.[1]?.toLowerCase();
  if (scheme === "http" || scheme === "https") {
    try {
      const url = new URL(text);
      if (url.username || url.password) return { kind: "blocked", reason: "Addresses with a name or password in them aren't opened." };
      return { kind: "url", url: url.href };
    } catch {
      return { kind: "search", query: text, url: SEARCH_URL + encodeURIComponent(text) };
    }
  }
  // "localhost:5173" parses as a scheme; anything else with a scheme (file:, javascript:) is not a web page.
  if (scheme && !/^localhost$/i.test(scheme) && !/^\d/.test(text.slice(scheme.length + 1)) && !/\s/.test(text)) {
    return { kind: "blocked", reason: "The browser opens web pages (http and https) only." };
  }
  if (!/\s/.test(text) && HOST.test(text)) {
    const url = new URL(`${LOCAL.test(text) ? "http" : "https"}://${text}`);
    return { kind: "url", url: url.href };
  }
  return { kind: "search", query: text, url: SEARCH_URL + encodeURIComponent(text) };
}

export function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

/** The address as people read it: no scheme, no trailing slash. */
export function displayUrl(url) {
  return String(url || "").replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/$/, "");
}

/** The search words when a URL is one of our search pages, so the field shows the query, not the URL. */
export function searchQueryOf(url) {
  if (!String(url || "").startsWith(SEARCH_URL)) return "";
  try { return new URL(url).searchParams.get("q") || ""; } catch { return ""; }
}

function score(query, { url, title }) {
  const q = query.toLowerCase();
  const plain = displayUrl(url).toLowerCase();
  const name = String(title || "").toLowerCase();
  if (plain.startsWith(q)) return 6;
  if (hostOf(url).startsWith(q)) return 5;
  if (name.split(/\W+/).some(word => word && word.startsWith(q))) return 4;
  if (plain.includes(q)) return 3;
  if (name.includes(q)) return 2;
  return 0;
}

/**
 * Autocomplete for the address field: open tabs ("switch to"), then history by
 * match quality, visit count and recency. One row per address.
 * -> [{type: "tab" | "history", url, title, tabId?}]
 */
export function suggest(input, { tabs = [], history = [] } = {}, limit = 6) {
  const query = String(input || "").trim();
  if (!query) {
    const seen = new Set();
    return [...history].reverse().filter(row => !seen.has(row.url) && seen.add(row.url)).slice(0, limit).map(row => ({ type: "history", url: row.url, title: row.title }));
  }
  const visits = new Map();
  for (const row of history) {
    const known = visits.get(row.url);
    visits.set(row.url, { url: row.url, title: row.title || known?.title, count: (known?.count || 0) + 1, at: Math.max(known?.at || 0, Number(row.at) || 0) });
  }
  const rows = [];
  for (const tab of tabs) {
    const value = score(query, tab);
    if (value) rows.push({ type: "tab", url: tab.url, title: tab.title, tabId: tab.id, rank: value + 1 });
  }
  const taken = new Set(rows.map(row => row.url));
  for (const row of visits.values()) {
    if (taken.has(row.url)) continue;
    const value = score(query, row);
    if (value) rows.push({ type: "history", url: row.url, title: row.title, rank: value + Math.min(1.5, Math.log10(row.count + 1)) + row.at / 1e13 });
  }
  return rows.sort((a, b) => b.rank - a.rank).slice(0, limit).map(({ rank, ...row }) => row);
}

/** One word (and tone) for a tab's state; "" means nothing to say. */
export function tabStatus(tab, view = {}) {
  if (!tab) return { word: "", tone: "idle" };
  const agent = tab.engine === "obscura";
  if (tab.status === "promoting") return { word: "Moving to a visible tab", tone: "live" };
  if (tab.status === "error") return { word: "Couldn't load", tone: "red" };
  if (agent && tab.status === "headless_runtime_needed") return { word: "Agent engine is off", tone: "idle" };
  if (agent && !tab.agentGranted) return { word: "Waiting for you", tone: "gold" };
  if (agent) return { word: "Agent", tone: "live" };
  if (tab.status === "runtime_needed") return { word: view.desktop ? "Starting" : "On your PC", tone: "idle" };
  if (tab.status === "suspended") return { word: "Sleeping", tone: "idle" };
  if (tab.loading || tab.status === "queued") return { word: "Loading", tone: "live" };
  if (tab.agentGranted) return { word: "Agent can act", tone: "gold" };
  return { word: "", tone: "idle" };
}

/** Tabs of one space: pinned, then everything else in the order it was opened (agent tabs sit in the same list). Mirrors are never listed. */
export function groupTabs(tabs = [], spaceId = "default") {
  const mine = tabs.filter(tab => !tab.mirrorOf && (tab.spaceId || "default") === spaceId);
  return {
    pinned: mine.filter(tab => tab.pinned && tab.engine !== "obscura"),
    agent: mine.filter(tab => tab.engine === "obscura"),
    open: mine.filter(tab => !tab.pinned && tab.engine !== "obscura"),
    list: mine.filter(tab => !tab.pinned || tab.engine === "obscura"),
  };
}

const clean = text => String(text || "").replace(/[ \t ]+/g, " ").trim();

/**
 * Reader mode from the page's own text projection (the same DOM projection
 * the agent reads). Keeps the title, headings and paragraphs; drops menus and
 * short link rows. -> {title, site, blocks: [{type: "h" | "p", text}], words, minutes}
 */
export function readerFrom(observation) {
  const lines = String(observation?.text || "").split(/\n+/).map(clean).filter(Boolean);
  const headings = new Map();
  for (const element of observation?.elements || []) {
    if (/^h[1-3]$/.test(element.role || "") || element.role === "heading") {
      const text = clean(element.name);
      if (text && text.length < 200) headings.set(text, element.role === "h1" ? 1 : 2);
    }
  }
  const title = clean(observation?.title) || [...headings.entries()].find(([, level]) => level === 1)?.[0] || "";
  const h1 = [...headings.entries()].find(([, level]) => level === 1)?.[0];
  // The article starts at its main heading when the page has one.
  const start = h1 ? Math.max(0, lines.indexOf(h1)) : 0;
  const blocks = [];
  for (const line of lines.slice(start)) {
    if (headings.has(line)) {
      if (line !== title && line !== h1) blocks.push({ type: "h", text: line });
      continue;
    }
    const words = line.split(" ").length;
    if (words >= 9 || (words >= 4 && /[.!?:;)]$/.test(line))) blocks.push({ type: "p", text: line });
  }
  // Drop a heading with nothing after it (a menu title).
  const kept = blocks.filter((block, index) => block.type === "p" || blocks[index + 1]?.type === "p");
  const words = kept.reduce((sum, block) => sum + block.text.split(" ").length, 0);
  return { title: h1 || title, site: hostOf(observation?.url), blocks: kept, words, minutes: Math.max(1, Math.round(words / 230)) };
}

const round = value => Math.max(0, Math.round(value));

/** A DOMRect as the native layout wants it (CSS logical pixels of the window). */
export function rectOf(box) {
  if (!box || box.width < 2 || box.height < 2) return null;
  return { x: round(box.left ?? box.x), y: round(box.top ?? box.y), width: round(box.width), height: round(box.height) };
}

/**
 * Where every live visible-engine tab goes: the slots the UI measured (main
 * view, split halves, peek card, picture-in-picture) or hidden. Overlays that
 * sit above the page (command bar, menus) hide them all, since native views
 * draw on top of the interface.
 */
export function layoutPlan(tabs = [], slots = [], covered = false) {
  const placed = new Map();
  for (const slot of slots) if (slot?.tabId && slot.rect && !placed.has(slot.tabId)) placed.set(slot.tabId, slot.rect);
  return tabs.filter(tab => tab.engine !== "obscura" && tab.live).map(tab => {
    const rect = covered ? null : placed.get(tab.id);
    return rect ? { tabId: tab.id, ...rect, visible: true } : { tabId: tab.id, x: 0, y: 0, width: 1, height: 1, visible: false };
  });
}

// ---------------------------------------------------------------- agents, seen through the browser

const PROVIDER_ID = { "claude-code": "claude", claude: "claude", codex: "codex", opencode: "opencode", neyvia: "neyvia" };
const PROVIDER_NAME = { claude: "Claude Code", codex: "Codex", opencode: "OpenCode", neyvia: "Neyvia" };

/** The mark and the name an agent tab shows: who opened it (tab.openedBy), else the run that drives it, else Neyvia's own. */
export function agentIdentity(tab, presence) {
  const raw = String(tab?.openedBy || presence?.app || "").toLowerCase();
  const id = PROVIDER_ID[raw] || "";
  return id ? { id, name: PROVIDER_NAME[id], known: true } : { id: "neyvia", name: "An agent", known: false };
}

/**
 * The agent's run for one headless tab, from the agent view's runs
 * (neyvia_agentview): who is driving, whether it is busy, and the element it
 * is about to act on or just acted on.
 * -> null | {app, title, working, waiting, focus: null | {phase, tool, value, label, role, box}}
 */
export function presenceOf(runs, tab) {
  if (!tab?.id) return null;
  const sid = `t${tab.id}`;
  const run = (runs || []).find(row => row.surfaces?.some(surface => surface.id === sid));
  if (!run) return null;
  const focus = run.focus && run.focus.surface === sid && run.focus.element ? run.focus : null;
  return {
    app: run.agent?.app || "", title: run.agent?.title || "", working: run.status === "working", waiting: run.status === "waiting",
    focus: focus ? { phase: focus.phase, tool: focus.tool, value: focus.say?.value ?? "", label: String(focus.element.label || "").trim(), role: focus.element.role || "", box: focus.element.box || null, bounds: focus.element.bounds || null } : null,
  };
}

const short = (text, max = 28) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/** What the soft highlight says, as a co-pilot would: "Typing in Quantity", "Clicking Add to basket". */
export function actionLabel(focus) {
  if (!focus) return "";
  const on = short(focus.label || focus.role || "this");
  const doing = focus.phase !== "done";
  switch (String(focus.tool || "")) {
    case "fill": case "type": return doing ? `Typing in ${on}` : `Typed in ${on}`;
    case "select": return doing ? `Choosing in ${on}` : `Chose in ${on}`;
    case "click": return doing ? `Clicking ${on}` : `Clicked ${on}`;
    case "submit": return doing ? `Submitting ${on}` : `Submitted ${on}`;
    case "scroll": return doing ? "Scrolling" : "Scrolled";
    case "focus": return doing ? `Looking at ${on}` : `Looked at ${on}`;
    default: return doing ? `Working on ${on}` : `Worked on ${on}`;
  }
}

/**
 * Where a headless tab stands, for its place in the tab list and its pill:
 * working (granted and busy), allowed (granted, between steps), waiting (the
 * agent hasn't been allowed), mine (Paul has it), asleep (engine off).
 */
export function agentState(tab, presence, { mine = false } = {}) {
  if (!tab || tab.engine !== "obscura") return "";
  if (tab.status === "headless_runtime_needed") return "asleep";
  if (tab.ownerTask?.status === "needs_owner") return "waiting";
  if (tab.agentGranted) return presence?.working ? "working" : "allowed";
  return mine ? "mine" : "waiting";
}

/** The pane's measured size as the agent's page wants it: whole CSS pixels, a sharp but bounded density. */
export function viewportOf(box, density = 1) {
  const width = Math.round(box?.width || 0), height = Math.round(box?.height || 0);
  if (width < 240 || height < 240) return null;
  return { width: Math.min(width, 4096), height: Math.min(height, 4096), scale: density >= 1.5 ? 2 : 1 };
}

/** Where a click on the shown frame lands on the page (CSS pixels of the headless viewport). */
export function framePoint(event, rect, frame) {
  if (!frame?.width || !frame?.height || rect.width <= 0 || rect.height <= 0) return null;
  const x = (event.clientX - rect.left) * (frame.width / rect.width), y = (event.clientY - rect.top) * (frame.height / rect.height);
  return x < 0 || y < 0 || x > frame.width || y > frame.height ? null : { x, y };
}

/** Paul's own tabs have no picture in the web build: show them through a read-only headless mirror of the same address. */
export function mirrorOf(tabs, tab) {
  return tab ? tabs.find(row => row.mirrorOf === tab.id && row.url === tab.url) || null : null;
}

/**
 * Where the highlight goes on the shown frame, in percent of it: from the element's real bounds (CSS pixels of the
 * headless viewport, the same pixels the frame shows), else from the agent view's own normalised box.
 */
export function highlightRect(focus, frame) {
  const b = focus?.bounds;
  if (b && frame?.width > 0 && frame?.height > 0 && [b.x, b.y, b.w, b.h].every(Number.isFinite) && b.w > 0 && b.h > 0) {
    return { x: (b.x / frame.width) * 100, y: (b.y / frame.height) * 100, w: (b.w / frame.width) * 100, h: (b.h / frame.height) * 100 };
  }
  const n = focus?.box;
  return n ? { x: n.x * 100, y: n.y * 100, w: n.w * 100, h: n.h * 100 } : null;
}
