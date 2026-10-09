import { createNeyviaClient } from "/api/sdk/neyvia-sdk.js";

// The feed owns study state. Shared identity, memory and models stay in Neyvia.
const sdk = createNeyviaClient({ appId: "scroll-study" });
let sessionId = "";
let lastReceipt = null;
const requestId = () => `scroll-study-${crypto.randomUUID()}`;

const services = Object.freeze({
  sdk,
  async connect() {
    const status = await sdk.providerStatus("codex");
    const memory = await sdk.recall({ intent: "Continue studying", app: "scroll-study", task: "study", entities: [window.SS_PACK?.id || "course"] });
    lastReceipt = { provider: status, memory };
    return lastReceipt;
  },
  async rememberStudy() {
    const state = window.neyviaApp.state();
    lastReceipt = await sdk.remember({ requestId: requestId(), key: "scroll-study-progress",
      content: JSON.stringify({ course: window.SS_PACK?.id, index: state.index, done: state.done }),
      kind: "fact", cues: { app: ["scroll-study"], entities: [window.SS_PACK?.id || "course"] } });
    return lastReceipt;
  },
  async ask(message, { cwd, model = "", app = "codex" } = {}) {
    if (!cwd) throw new Error("Choose the study project's folder for the provider call");
    const result = await sdk.modelCall({ app, cwd, message, model, permissionMode: "read-only", requestId: requestId() });
    sessionId = result.sessionId;
    lastReceipt = result;
    return result;
  },
  async result(id = sessionId) {
    if (!id) throw new Error("Ask a question first");
    sessionId = id;
    lastReceipt = await sdk.modelResult(id);
    return lastReceipt;
  },
  receipt: () => lastReceipt,
});
window.scrollStudyServices = services;

function mount() {
  const host = document.createElement("section");
  host.className = "ss-neyvia";
  host.innerHTML = '<button type="button" data-services aria-expanded="false" aria-controls="neyvia-services-panel">Neyvia services</button><div id="neyvia-services-panel" hidden><p>Use your Neyvia sign-in, shared memory and model providers.</p><button type="button" data-connect>Connect</button> <button type="button" data-save>Remember progress</button><form><label>Project folder<input name="cwd" required placeholder="C:/your/study/project"></label><label>Question<input name="message" required placeholder="Explain the current concept"></label><button type="submit">Ask Neyvia</button> <button type="button" data-result>Read answer</button></form><pre role="status"></pre></div>';
  document.querySelector(".ss-top").appendChild(host);
  const output = host.querySelector("pre");
  host.querySelector("[data-services]").onclick = event => {
    const panel = host.querySelector("#neyvia-services-panel");
    panel.hidden = !panel.hidden;
    host.dataset.open = String(!panel.hidden);
    event.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
  };
  const describe = value => {
    if (value.provider) return `Using ${value.provider.label || "Neyvia's connected provider"}. Shared memory: ${value.memory.selected.length} saved item(s).`;
    if (value.memory?.id) return "Progress remembered by Neyvia.";
    if (value.items) return value.items.filter(item => item.kind === "assistant").map(item => item.data?.text || "").filter(Boolean).join("\n\n") || "The model is still answering. Read answer again shortly.";
    return "Question sent through Neyvia. Read answer when the model finishes.";
  };
  const show = async task => {
    try { output.textContent = "Working…"; output.textContent = describe(await task()); }
    catch (error) { output.textContent = error.message; }
  };
  host.querySelector("[data-connect]").onclick = () => show(() => services.connect());
  host.querySelector("[data-save]").onclick = () => show(() => services.rememberStudy());
  host.querySelector("[data-result]").onclick = () => show(() => services.result());
  host.querySelector("form").onsubmit = event => {
    event.preventDefault(); const data = new FormData(event.target);
    void show(() => services.ask(String(data.get("message")), { cwd: String(data.get("cwd")) }));
  };
}
if (window.neyviaApp) mount(); else window.addEventListener("neyvia-app-ready", mount, { once: true });
