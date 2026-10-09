import { backendBase } from "./nxApi.js";
import { callTool, deliver } from "./nxBus.js";
import { docsCall } from "./nxDocsApi.js";

export { approxTokens, layerForOutput, outline, parsePerceptionTarget, perceptionTarget } from "./nxOutputsModel.js";

// The Outputs panel, app.open and the perception view: their user side
// (plans/15-handoff.md "## T8" and "## T18"). The same backend functions as
// the bot side: neyvia.artifact.publish/list/get/open, neyvia.app.open and
// neyvia.perception.observe/project.
//   POST /api/ui/outputs {op: publish|list|get|open, args}
//   POST /api/ui/navigation {app, target?}
//   POST /api/ui/tools/call {tool: "neyvia.perception.*", arguments}

export const OUTPUT_KINDS = ["file", "diff", "image", "report", "receipt"];
export const KIND_LABELS = { file: "Files", diff: "Changes", image: "Images", report: "Reports", receipt: "Receipts" };
export const KIND_ONE = { file: "File", diff: "Changes", image: "Image", report: "Report", receipt: "Receipt" };

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

/** One Outputs operation. Errors keep the backend's status: 404 missing, 409 changed. */
export const outputsCall = (op, args = {}) => docsCall("outputs", op, args);

/** Ask the backend to open an app (the same code as the model's app.open), then show it here. */
export async function openAppByName(app, target = "") {
  let response;
  try {
    response = await fetch(`${base()}/api/ui/navigation`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(target ? { app, target } : { app }),
    });
  } catch {
    throw new Error("The PC service can't be reached.");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `Couldn't open ${app} (HTTP ${response.status})`);
  const data = result?.data ?? result;
  // The answer carries the bus event; deliver it now (the stream would bring it a moment later).
  if (data?.event?.id) deliver(data.event, { direct: true });
  return data;
}

/** Open a published output: the backend checks its bytes, then shows it in the artifact or file pane. */
export async function openOutput(id) {
  const data = await outputsCall("open", { id });
  if (data?.event?.id) deliver(data.event, { direct: true });
  return data;
}

async function perception(tool, args) {
  const data = await callTool(`neyvia.perception.${tool}`, args);
  const result = data?.result ?? data;
  if (result?.ok === false) throw Object.assign(new Error(result.error || "The agent's view couldn't be read"), { data: result });
  return result;
}

/**
 * What an agent reads of a layer: observe, then (for a large value) project its state.
 * Returns { value, observe } where value is the neyvia.layer.v1 value ({layer, source, trust, state}).
 */
export async function observeLayer(layer, source) {
  const observe = await perception("observe", { layer, source });
  if (observe.observed) return { value: observe.observed, observe };
  const projected = await perception("project", { handle: observe.handle, path: "/state", limit: 100 });
  const state = projected.value ?? projected.projection ?? projected.result ?? projected;
  return { value: { layer, source, trust: "untrusted-data", state, projected: true, tooLarge: Boolean(projected.tooLarge) }, observe };
}

export const openBrowserSession = url => perception("browser.open", { url });
export const closeBrowserSession = browserId => perception("browser.close", { browserId }).catch(() => null);

/**
 * Open an app or pane from Paul's own click through the same backend path as the
 * model's app.open, so both are recorded on the bus the same way. A refusal
 * (an unfinished app) is said plainly; with the PC service unreachable the
 * screen still opens locally.
 */
export async function openFromUi(app, { suite = "", target = "", local } = {}) {
  try {
    return await openAppByName(app, target);
  } catch (error) {
    const { os } = await import("./nxOsStore.js");
    if (/can't be reached|HTTP 404|HTTP 5\d\d/.test(error.message)) {
      if (local) local(); else os.openApp(app, suite, target || null);
      return null;
    }
    os.notify({ level: "warning", message: error.message });
    return null;
  }
}
