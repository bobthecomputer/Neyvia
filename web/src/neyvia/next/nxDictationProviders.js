// Where speech becomes words: the choices shown in Settings > Voice. The PC service decides what is available
// (status.providers) and falls back to the local engine with a plain note; this only shapes it for the page.

import { checkedDictationAction } from "./nxDictationContracts.js";

const ORDER = ["local", "openai", "codex", "browser"];
const SHORT = {
  local: "Runs on this PC. Works offline, nothing is sent anywhere.",
  openai: "Streams to OpenAI as you talk. Needs an OpenAI API key; billed by OpenAI per minute, not part of a ChatGPT plan.",
  codex: "Codex's own voice session. Needs Codex signed in with an API key (plan sign-ins are refused for voice). Experimental.",
  browser: "Your browser's built-in speech input. The browser's vendor hears the audio.",
};

/** Rows for the radio list: [{id, label, hint, available, reason, selected, badge}], recommended first. */
export function providerChoices(status) {
  const wanted = status?.providerWanted || "local";
  const rows = Array.isArray(status?.providers) ? status.providers : [];
  const choices = ORDER.map(id => rows.find(row => row.id === id)).filter(Boolean).map(row => ({
    id: row.id,
    label: row.label,
    hint: SHORT[row.id] || row.needs || "",
    available: row.available !== false,
    reason: row.available === false ? row.reason || "Not available right now." : "",
    selected: row.id === wanted,
    badge: row.id === "local" ? "Default" : row.experimental ? "Experimental" : row.offline ? "Offline" : "",
  }));
  return checkedDictationAction("providerChoices", [status], choices);
}

/** One sentence under the list: what is in use now when it differs from the choice. */
export function providerSummary(status) {
  if (!status) return "";
  if (status.providerNote) return status.providerNote;
  const active = status.provider || "local";
  const wanted = status.providerWanted || "local";
  if (wanted === "browser") return "Dictation uses the browser's speech input.";
  return active === wanted ? "" : `Using ${active} for now.`;
}
