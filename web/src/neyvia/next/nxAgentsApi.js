import { backendBase, callNx } from "./nxApi.js";

// The user side of the Conductor (plan 15 T9) and Autopilot (T17). Both are
// owner-only and durable on the PC, so polling a read is the truth and survives
// a backend restart. The bot side is the same state: neyvia.conductor.* and
// neyvia.autopilot.*.
//   Conductor: conductor_{plan,get,list,control}_command through /api/backend
//              (desktop: the same commands over IPC).
//   Autopilot: POST/GET /api/ui/autopilot; when this PC's service answers that
//              route with 404 (an older build), the same function through
//              POST /api/ui/tools/call {tool:"neyvia.autopilot.<op>"}.
//   Routes:    GET/POST /api/ui/runtime {action:"profile", name, route}.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function request(path, body) {
  let response;
  try {
    response = await fetch(`${base()}${path}`, body ? {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : { credentials: "include" });
  } catch {
    throw Object.assign(new Error("The PC service can't be reached."), { status: 0 });
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) {
    const message = response.status === 401 ? "This browser is signed out of your PC. Reload the page to sign in again."
      : result?.error || `Your PC refused that (${response.status}).`;
    throw Object.assign(new Error(message), { status: response.status, data: result?.data ?? null });
  }
  return result?.data ?? result;
}

// ---- conductor ---------------------------------------------------------------

export const conductorList = ({ limit = 25, offset = 0 } = {}) => callNx("conductor_list_command", { limit, offset });
export const conductorGet = id => callNx("conductor_get_command", { id }).then(result => result.job);
export const conductorControl = (id, action) => callNx("conductor_control_command", { id, action }).then(result => result.job);
export const conductorPlan = ({ requestId, goal, folder, acceptanceChecks, maxRuntimeSeconds }) =>
  callNx("conductor_plan_command", { requestId, goal, folder, acceptanceChecks, ...(maxRuntimeSeconds ? { maxRuntimeSeconds } : {}) });

// ---- routing profiles (Runtime matrix) ------------------------------------------

export const runtimeMatrix = () => request("/api/ui/runtime");
export const saveProfile = (name, route) => request("/api/ui/runtime", { action: "profile", name, route });

// ---- autopilot ---------------------------------------------------------------

let autopilotRoute = "http"; // "http" until the service says it has no /api/ui/autopilot
async function autopilot(operation, args = {}) {
  if (autopilotRoute === "http") {
    try {
      if (operation === "get") return await request(`/api/ui/autopilot?runId=${encodeURIComponent(args.runId)}`);
      if (operation === "list") return await request("/api/ui/autopilot");
      return await request("/api/ui/autopilot", { operation, ...args });
    } catch (error) {
      if (error.status !== 404 || !/route/i.test(error.message)) throw error;
      autopilotRoute = "tool";
    }
  }
  const answer = await request("/api/ui/tools/call", { tool: `neyvia.autopilot.${operation}`, arguments: args });
  const result = answer?.result ?? answer;
  if (result?.ok === false && !result.run) throw new Error(result.error || "Autopilot refused that");
  return result;
}

/** Start in the background; a retry with the same requestId returns the same run. */
export const autopilotStart = ({ requestId, text, sessionId, scopeTools, maxModelCalls, maxSeconds }) =>
  autopilot("start", { requestId, text, scopeTools, background: true, ...(sessionId ? { sessionId } : {}),
    ...(maxModelCalls ? { maxModelCalls } : {}), ...(maxSeconds ? { maxSeconds } : {}) });
export const autopilotGet = runId => autopilot("get", { runId });
export const autopilotList = () => autopilot("list");
export const autopilotStop = runId => autopilot("stop", { runId });
export const autopilotResume = runId => autopilot("resume", { runId, background: true });
