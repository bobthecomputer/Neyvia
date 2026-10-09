// Plain-words presentation of source apps and mods (the store in Marketplace > Apps & mods).
// Pure functions over what SourceMarketplace returns; nothing here calls the backend.

const SERVICE_WORDS = {
  "provider-routing": "Your AI models, through the sign-ins you already have in Neyvia",
  memory: "Neyvia memory: recall and save",
  tools: "Neyvia tools",
  sessions: "Start chats and read their replies",
  events: "Neyvia events",
  laya: "LAYA answer checks",
  cl: "Executable manuals",
};

const words = value => String(value || "")
  .replace(/([a-z])([A-Z])/g, "$1 $2")
  .replace(/[-_.]+/g, " ")
  .trim()
  .toLowerCase();
const sentence = value => { const text = words(value); return text ? text[0].toUpperCase() + text.slice(1) : ""; };
const list = items => items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;

/** Short version id, as Git shows commits. */
export const shortVersion = version => String(version || "").slice(0, 7);

/** The one state a card shows: blocked beats update beats enabled beats installed. */
export function storeState(item, updates = {}) {
  if (item.state === "available") return { id: "available", label: "", tone: "idle" };
  if (item.state === "integrity-blocked") return { id: "blocked", label: "Changed on disk", tone: "red" };
  if (updates[item.id]?.available) return { id: "update", label: "Update available", tone: "gold" };
  if (item.state === "active") return { id: "enabled", label: "Enabled", tone: "green" };
  return { id: "installed", label: "Installed", tone: "idle" };
}

export const kindLabel = kind => (kind === "app" ? "App" : "Mod");
export const sourceLabel = item => (item.sourceKind === "github" ? "GitHub" : item.origin === "example" ? "Example in Neyvia" : "Local folder");

/** Which drawn glyph stands for a package that ships no icon of its own: by what it does, then by kind. */
const GLYPH_RULES = [
  [/effect|motion|after/i, "layers"], [/film|cinema|movie/i, "clapperboard"], [/laya|video|clip/i, "video"],
  [/hyperframe|frame|timeline/i, "frame"], [/photo|image|picture|camera/i, "aperture"], [/hello|greet|welcome/i, "message"],
  [/scroll|study|course|learn/i, "study"], [/note|write|doc/i, "notes"], [/code|build|dev/i, "code"],
];
export function glyphKey(item) {
  const text = `${item?.id || ""} ${item?.name || ""}`;
  for (const [pattern, key] of GLYPH_RULES) if (pattern.test(text)) return key;
  return item?.kind === "app" ? "app" : "mod";
}

/** Two letters for a monogram, and a stable tone so the grid isn't one colour. */
export function monogram(name, id) {
  const parts = String(name || id || "?").split(/[\s-_]+/).filter(Boolean);
  const letters = (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase();
  let hash = 0;
  for (const char of String(id || name)) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return { letters, tone: ["accent", "gold", "green", "amber"][hash % 4] };
}

/** "C:\Users\user\Projects\app" -> "…\Projects\app"; GitHub URLs -> "owner/repo". */
export function shortSource(source) {
  const text = String(source || "");
  const github = text.match(/^https:\/\/github\.com\/([^/]+\/[^/]+?)(?:\.git)?\/?$/);
  if (github) return github[1];
  const parts = text.split(/[\\/]/).filter(Boolean);
  return parts.length > 3 ? `…\\${parts.slice(-2).join("\\")}` : text;
}

/** Search and filter (All, Apps, Mods, Installed). */
export function filterItems(items, { filter = "all", query = "" } = {}) {
  const needle = query.trim().toLowerCase();
  return items.filter(item => {
    if (filter === "app" && item.kind !== "app") return false;
    if (filter === "mod" && item.kind !== "mod") return false;
    if (filter === "installed" && item.state === "available") return false;
    if (!needle) return true;
    return [item.name, item.id, item.summary, item.kind].join(" ").toLowerCase().includes(needle);
  });
}

/** Parse one CL manual into what a person reads: actions in plain words and declared limits. */
export function readManual(text) {
  const actions = [];
  const limits = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trim();
    const action = line.match(/^A\s+([\w.]+)\((.*?)\)\s*(?:->\s*(.*?))?\s*[~!]?\s*(?:--\s*(.*))?$/);
    if (action) {
      actions.push(describeAction(action[1], action[2], action[3] || "", action[4] || ""));
      continue;
    }
    // Generated "no observer bound" lines are bookkeeping, not limits the author declared.
    const limit = line.match(/^F\s+(?!verify-)(.+)$/);
    if (limit) limits.push(limit[1].replace(/^"|"$/g, ""));
  }
  return { actions, limits };
}

function describeAction(name, args, returns, description) {
  const leaf = name.split(".").pop();
  if (description) return { name, text: description };
  if (leaf === "state") {
    const fields = (returns.match(/\[([^\]]*)\]/)?.[1] || "").split(/\s+/).filter(Boolean).map(words);
    return { name, text: fields.length ? `Shows where you are: ${list(fields.slice(0, 6))}${fields.length > 6 ? " and more" : ""}` : "Shows where you are" };
  }
  if (leaf === "act") {
    const choices = [...args.matchAll(/"([^"]+)"/g)].map(match => words(match[1]));
    return { name, text: choices.length ? `Lets you and agents ${list(choices)}` : "Lets you and agents act in it" };
  }
  if (leaf === "checks") return { name, text: "Reports whether its own goals are met" };
  if (leaf === "text") return { name, text: "Shares the text on its page with agents" };
  return { name, text: sentence(name.replace(/^neyvia\.|^app\./, "")) };
}

/** What an item asks for, as a checklist: services, its actions' reach, dependencies, the gate. */
export function permissionRows(item) {
  const rows = [];
  // Permissions the item declares in its own words (local tools it runs, files it touches, network).
  for (const text of item.permissions || []) rows.push({ id: `declared:${text}`, text: String(text), detail: "declared by the item" });
  const services = item.services?.length ? item.services : item.manifest?.services || [];
  for (const service of services) rows.push({ id: `service:${service}`, text: SERVICE_WORDS[service] || sentence(service), detail: service });
  for (const action of item.actions || []) {
    rows.push({ id: `action:${action.name}`, text: action.mutability === "read"
      ? `Adds an agent action that only reads: ${action.description || sentence(action.name)}`
      : `Adds an agent action that can change things: ${action.description || sentence(action.name)}`, detail: action.name });
  }
  for (const dependency of item.dependencies || []) rows.push({ id: `dep:${dependency}`, text: `Needs ${sentence(dependency)} turned on`, detail: dependency });
  if (!rows.length) rows.push({ id: "none", text: "Uses no Neyvia services" });
  rows.push({ id: "gate", text: item.kind === "app" ? "Its window and every Neyvia call stop while it is off" : "Its actions stop while it is off" });
  return rows;
}

/** Declared contracts, readable: invariant sentences first, then named checks (G1..Gn collapse to one line). */
export function contractRows(contracts) {
  const body = Array.isArray(contracts) ? { checks: contracts } : contracts || {};
  const rows = (body.invariants || []).map(text => ({ id: `inv:${text}`, text }));
  const checks = (body.checks || []).map(String);
  const goals = checks.filter(check => /^G\d+$/.test(check));
  if (goals.length) rows.push({ id: "goals", text: `${goals.length} goal ${goals.length === 1 ? "check" : "checks"} run by its manual`, detail: goals.length > 1 ? `${goals[0]}–${goals[goals.length - 1]}` : goals[0] });
  for (const check of checks.filter(check => !/^G\d+$/.test(check))) {
    const [scope, ...rest] = check.split(".");
    rows.push({ id: `check:${check}`, text: sentence(rest.join(".") || scope), detail: check });
  }
  return rows;
}

const PLAIN_ERRORS = [
  [/Source folder is missing/i, () => "That folder isn't on this PC. Check the path and try again."],
  [/exactly one neyvia\.app\.json or neyvia\.module\.json/i, () => "That folder isn't a Neyvia app or mod. It needs one neyvia.app.json or neyvia.module.json."],
  [/executable \.cl manual and contracts/i, () => "It has no manual (.cl) or contracts file, so it can't be reviewed. Add them and try again."],
  [/observer goals and public actions/i, () => "Its manual doesn't say what it does or how to check it. Add goals (G) and actions (A)."],
  [/unique lowercase instance\/id/i, () => "Its manifest needs a lowercase id, like my-app."],
  [/static web entry point/i, () => "The app has no www/index.html to open."],
  [/Use a GitHub HTTPS git URL/i, () => "Use a GitHub address like https://github.com/owner/repo, and a branch or tag if you want one."],
  [/HTTP Error 404|Not Found/i, () => "GitHub couldn't find that repository, branch or tag."],
  [/HTTP Error 40[13]/i, () => "GitHub refused access. Sign in to GitHub in Neyvia, then try again."],
  [/Active dependency: (.+)/i, (match, intent) => intent === "enable"
    ? `Turn on ${match[1]} first; this one needs it.`
    : `${match[1]} needs this one. Turn ${match[1]} off first.`],
  [/Needed by: (.+)/i, match => `${match[1]} needs this one. Remove ${match[1]} first.`],
  [/Installed source changed/i, () => "Its installed files changed on disk. Update it to take a fresh copy, then turn it on."],
  [/Live Neyvia source is outside/i, () => "Neyvia's own working folder can't be installed from. Use a copy, or a GitHub address."],
  [/exceeds 200 MB|200 MB download limit/i, () => "That source is bigger than 200 MB."],
  [/signed package/i, () => "A signed package with the same id is already installed."],
  [/symbolic links? or junctions?|symbolic link/i, () => "The source contains links to other folders. Copy the real files in and try again."],
  [/Source changed during snapshot/i, () => "The folder changed while it was being copied. Try again."],
  [/change an app into a mod|mod into an app/i, () => "An installed item with that id is a different kind. Remove it first."],
  [/Update changed item identity/i, () => "The source now has a different id. Install it as a new item instead."],
  [/Update requires active dependencies/i, () => "Turn on the things it needs, then update."],
  [/is not installed/i, () => "It isn't installed any more. The list has been refreshed."],
  [/Failed to fetch|NetworkError|Load failed/i, () => "Neyvia's backend didn't answer. Check it is running, then try again."],
];

/** Errors in plain words; the original stays available for Copy details. */
export function plainError(failure, intent = "") {
  const raw = String(failure?.message || failure || "").replace(/^(Error|ValueError):\s*/i, "").trim();
  for (const [pattern, say] of PLAIN_ERRORS) {
    const match = raw.match(pattern);
    if (match) return { text: say(match, intent), raw };
  }
  return { text: raw || "That didn't work. Try again.", raw };
}

/** Local time like "6 Oct, 16:09". */
export function when(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
