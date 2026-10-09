// Usage pane model: formatting and shaping for GET /api/ui/usage. Pure functions, no I/O.
// Rule: plan traffic is shown as tokens and plan percent, never as a price; a price exists only for API-key rows.

export const RANGES = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

export const APP_ORDER = ["claude-code", "codex", "opencode"];
// Dates follow the interface language (English), not the PC's regional format, so labels match the rest of the UI.
const UI_LOCALE = "en-GB";
const APP_NAMES = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode" };
const AGENT_NAMES = { "claude-code": "Claude Code", codex: "Codex", "neyvia-agent": "Neyvia agent", opencode: "OpenCode" };
const PROVIDER_NAMES = { anthropic: "Claude", openai: "Codex / OpenAI", "opencode-go": "OpenCode Go", "openai-codex": "Codex login", deepseek: "DeepSeek", openrouter: "OpenRouter", google: "Google" };
const SOURCE_NAMES = { "codex-rollout": "Codex session log", "codex-cli": "Codex app", "claude-mod": "Claude Code mod", "claude-usage": "Claude /usage", "claude-statusline": "Claude status line", "claude-stream": "Claude chat stream" };

export const appName = app => APP_NAMES[app] || app;
export const agentName = agent => AGENT_NAMES[agent] || agent;
export const providerName = provider => PROVIDER_NAMES[provider] || provider;
export const sourceName = source => SOURCE_NAMES[source] || source || "reader";

/** 1234567 -> "1.23M". Always says the magnitude; the unit ("tokens") is written by the caller. */
export function fmtTokens(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Number(value);
  const abs = Math.abs(n);
  const trim = (x, digits) => x.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  if (abs >= 1e9) return `${trim(n / 1e9, abs >= 1e10 ? 1 : 2)}B`;
  if (abs >= 1e6) return `${trim(n / 1e6, abs >= 1e7 ? 1 : 2)}M`;
  if (abs >= 1e3) return `${trim(n / 1e3, abs >= 1e4 ? 0 : 1)}K`;
  return String(Math.round(n));
}

export const fmtPercent = (share, digits = 0) => (share == null || !Number.isFinite(Number(share)) ? "—" : `${(Number(share) * 100).toFixed(digits)}%`);

export function fmtUsd(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  const n = Number(value);
  if (n > 0 && n < 0.01) return "<$0.01";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** New work in a bucket: input that was not read from cache, plus output. */
export const freshTokens = cell => Math.max(0, (cell?.input || 0) - (cell?.cached || 0)) + (cell?.output || 0);
export const allTokens = cell => (cell?.input || 0) + (cell?.output || 0);

export function dayLabel(day, index, count) {
  const date = new Date(`${day}T12:00:00`);
  if (count <= 8) return date.toLocaleDateString(UI_LOCALE, { weekday: "short", day: "numeric" });
  return index % 5 === 0 || index === count - 1 ? date.toLocaleDateString(UI_LOCALE, { month: "short", day: "numeric" }) : "";
}

/** "Nice" axis maximum and three ticks, so the axis never invents precision. */
export function axis(max) {
  if (!(max > 0)) return { top: 1, ticks: [0] };
  const exp = 10 ** Math.floor(Math.log10(max));
  const step = [1, 2, 2.5, 5, 10].map(m => m * exp).find(s => s * 4 >= max) || 10 * exp;
  const top = Math.ceil(max / step) * step;
  return { top, ticks: [0, top / 2, top] };
}

/** Series for the stacked chart: one entry per agent seen, in a stable order, each with its colour token. */
const AGENT_COLORS = { "claude-code": "var(--nx-gold)", codex: "var(--nx-accent)", opencode: "var(--nx-text-2)", "neyvia-agent": "var(--nx-red)" };
const AGENT_ORDER = ["claude-code", "codex", "opencode", "neyvia-agent"];
export function chartModel(byDay = [], mode = "fresh") {
  const measure = mode === "all" ? allTokens : freshTokens;
  const names = [];
  for (const day of byDay) for (const agent of Object.keys(day.agents || {})) if (!names.includes(agent)) names.push(agent);
  names.sort((a, b) => (AGENT_ORDER.indexOf(a) + 1 || 9) - (AGENT_ORDER.indexOf(b) + 1 || 9) || a.localeCompare(b));
  const series = names.map(name => ({ name, label: agentName(name), color: AGENT_COLORS[name] || "var(--nx-faint)" }));
  const columns = byDay.map(day => {
    const parts = series.map(s => ({ ...s, value: measure(day.agents?.[s.name]) }));
    return { day: day.day, parts, total: parts.reduce((sum, p) => sum + p.value, 0) };
  });
  const scale = axis(Math.max(0, ...columns.map(c => c.total)));
  return { series, columns, scale, empty: columns.every(c => c.total === 0) };
}

export function planGroups(plans = [], providers = []) {
  const groups = APP_ORDER.map(app => ({ app, rows: [], provider: providers.find(p => p.app === app) || null }));
  for (const row of plans) {
    let group = groups.find(g => g.app === row.app);
    if (!group) { group = { app: row.app, rows: [], provider: providers.find(p => p.app === row.app) || null }; groups.push(group); }
    group.rows.push(row);
  }
  for (const group of groups) group.rows.sort((a, b) => (a.window === "five_hour" || a.window === "5h" ? 0 : 1) - (b.window === "five_hour" || b.window === "5h" ? 0 : 1));
  return groups;
}

export function ageText(iso, now = Date.now()) {
  const time = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((now - time) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

export function resetText(iso) {
  const time = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(time)) return "";
  return new Date(time).toLocaleString(UI_LOCALE, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Headline numbers. API-equivalent (all priced usage) and billed (API-key rows only) are separate and never added. */
export function headline(data) {
  const totals = data?.totals || {};
  const cost = data?.cost || {};
  return {
    fresh: Math.max(0, (totals.input || 0) - (totals.cached || 0)) + (totals.output || 0),
    cached: totals.cached || 0,
    output: totals.output || 0,
    cacheShare: totals.cacheShare,
    equivalentUsd: cost.apiEquivalentTotalUsd ?? null,
    billedUsd: cost.billedTotalUsd ?? null,
    apiRows: cost.apiRows || 0,
    pricedShare: cost.pricedShare ?? null,
    unpriced: cost.unpricedModels || [],
  };
}

const BILLING = { api: "API key", plan: "Plan login", free: "Free tier", unknown: "Billing unknown" };
export const billingLabel = billing => BILLING[billing] || BILLING.unknown;

export function partsText(parts) {
  if (!parts) return "";
  const money = value => (value > 0 && value < 0.01 ? "<$0.01" : `$${value.toFixed(2)}`);
  return `API-equivalent: input ${money(parts.input)} · cache reads ${money(parts.cached)} · cache writes ${money(parts.cacheWrite)} · output ${money(parts.output)}`;
}
