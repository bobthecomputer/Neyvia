import { NxError, backendBase, callNx, isDesktopApp } from "./nxApi.js";
import { busClientId, deliver } from "./nxBus.js";
import { getOs } from "./nxOsStore.js";

// Voice control (plan 15 T3, contract in plans/15-handoff.md "## T3").
// A spoken (or typed) command goes to the backend's deterministic grammar, which
// acts through the same command bus and tools a model uses, and answers with a
// receipt: what it understood, one sentence to say, the bus events it emitted.
// The events are applied here too (the bus drops duplicates by id), so the
// screen reacts even when the live stream lags.

/** The built-in copy of the grammar, shown while the backend can't list its own. */
export const VOICE_GRAMMAR = [
  { intent: "app.open", description: "Open an app", examples: ["open notes", "show files", "open mobile studio", "ouvre les notes"] },
  { intent: "pane.show", description: "Open a page", examples: ["open settings", "show runtimes", "tidy my chats"] },
  { intent: "stage.close", description: "Close the app and go back to the chat", examples: ["close", "go home", "back to the chat"] },
  { intent: "launcher.open", description: "Search everything", examples: ["open the launcher", "search for release notes"] },
  { intent: "dashboard.open", description: "See every agent at work", examples: ["show agents", "what's running"] },
  { intent: "session.open", description: "Open a chat by its name", examples: ["open chat quantization", "go to the plotter chat"] },
  { intent: "newchat.open", description: "Start a new chat (you still press Send or say \"send\")", examples: ["new codex chat in dictation", "new claude chat", "nouvelle conversation codex"] },
  { intent: "composer.send", description: "Send what's in the message box", examples: ["send", "send it", "envoie"] },
  { intent: "run.answer", description: "Answer the approval on screen", examples: ["approve", "deny", "approuve"] },
  { intent: "run.stop", description: "Stop the chat on screen", examples: ["stop", "stop the run"] },
  { intent: "view.theme", description: "Change the colours", examples: ["dark theme", "morning theme", "night green theme", "terminal theme", "paper theme", "ember theme"] },
  { intent: "view.layout", description: "Show more or less", examples: ["calm", "workshop", "grove mode"] },
  { intent: "sidebar.toggle", description: "Hide or show the sidebar", examples: ["hide the sidebar", "show the sidebar"] },
  { intent: "dictation.start", description: "Dictate into the message box or a note", examples: ["dictate", "take a note"] },
  { intent: "voice.help", description: "This list", examples: ["what can I say", "help"] },
];

function route() {
  const params = new URLSearchParams(globalThis.location?.search || "");
  const chat = params.get("chat") || "";
  // Without an open chat the new-chat box is on screen (the home widgets sit under it).
  return { sessionId: chat || null, view: chat ? "chat" : "new" };
}

/** What is on screen: the only things "approve", "stop" and "send" may act on. */
export function voiceContext() {
  const os = getOs();
  const { sessionId, view } = route();
  const stage = os.stage ? (os.stage.type === "app" ? { type: "app", app: os.stage.app } : { type: "pane", kind: os.stage.kind, target: os.stage.target || "" }) : null;
  return {
    stage, sessionId, view,
    approvalIds: os.notices.filter(notice => notice.approvalId).map(notice => notice.approvalId),
    clientId: busClientId(),
  };
}

// Browser and phone: the owner-only voice route of the PC service. Desktop: the named commands
// through the bridge (they forward to the same route). Design fixtures: callNx.
const fixtures = () => Boolean(import.meta.env?.DEV) && new URLSearchParams(globalThis.location?.search || "").get("fixtures") === "1";
async function voiceCall(command, payload) {
  if (isDesktopApp() || fixtures()) return callNx(command, payload);
  const read = command === "voice_commands_command";
  let response;
  try {
    response = await fetch(`${backendBase()}/api/ui/voice${read ? "/commands" : ""}`, read
      ? { credentials: "include" }
      : { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command, ...payload }) });
  } catch {
    throw new NxError("The PC service can't be reached.", { code: "network" });
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    throw new NxError(result?.error || `Voice command failed (HTTP ${response.status})`, { status: response.status, data: result, code: response.status === 401 ? "login_required" : "" });
  }
  return result?.data ?? result;
}

const newId = () => globalThis.crypto?.randomUUID?.() || `v-${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** True when the PC service doesn't know the voice commands yet (an older backend). */
export function isVoiceUnavailable(error) {
  return /unknown|unsupported|not allowed|not supported|no such command/i.test(String(error?.message || "")) || error?.status === 404;
}

/**
 * Run one command. Returns the backend's receipt ({ status, intent, say, events, choices, error }).
 * Throws only when the service can't be reached or doesn't have voice commands.
 */
export async function runVoiceCommand(text, { language = "", dryRun = false, requestId = newId() } = {}) {
  let answer;
  try {
    answer = await voiceCall("voice_command_command", { text: String(text || "").slice(0, 500), language, requestId, dryRun, context: voiceContext() });
  } catch (error) {
    // A refused / unmatched command can come back as ok: false; it is still a receipt, not a failure.
    const data = error?.data;
    answer = data?.status && data?.requestId ? data : data?.data?.status && data?.data?.requestId ? data.data : null;
    if (!answer) throw error;
  }
  if (!dryRun) for (const event of Array.isArray(answer?.events) ? answer.events : []) deliver(event, { direct: true });
  return answer || { status: "failed", error: "No answer from Neyvia." };
}

let listed = null;
/** The grammar the backend understands (for the help sheet), or the built-in copy. */
export function loadVoiceCommands() {
  listed ||= voiceCall("voice_commands_command", {})
    .then(answer => (Array.isArray(answer?.commands) && answer.commands.length ? { ...answer, source: "backend" } : { commands: VOICE_GRAMMAR, source: "built-in" }))
    .catch(error => { listed = null; return { commands: VOICE_GRAMMAR, source: "built-in", unavailable: isVoiceUnavailable(error) }; });
  return listed;
}
