import { backendBase } from "../nxApi.js";
import { exampleKeyframe } from "./nxAgentViewExample.js";

// The agent view's user side (src/grant_agent/neyvia_agentview.py):
//   GET  /api/ui/agentview/runs                                   every run with its surfaces and latest steps
//   GET  /api/ui/agentview/frame?run=&surface=&since=&fps=&after=  changed regions since a frame version + new steps
//   GET  /api/ui/agentview/timeline?run=                           keyframes, steps and comments of a run
//   GET  /api/ui/agentview/keyframe?run=&id=                       one keyframe (JPEG)
//   POST /api/ui/agentview {op: "feedback", args}                  a comment bound to a frame/action, delivered to the agent

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function read(response, what) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body?.ok === false) {
    throw Object.assign(new Error(body?.error || `${what} failed (HTTP ${response.status})`), { status: response.status });
  }
  return body?.data ?? body;
}

async function get(path, params, what) {
  const query = new URLSearchParams(Object.entries(params || {}).filter(([, value]) => value != null && value !== "").map(([k, v]) => [k, String(v)]));
  let response;
  try {
    response = await fetch(`${base()}/api/ui/agentview/${path}${query.size ? `?${query}` : ""}`, { credentials: "include", headers: { Accept: "application/json" } });
  } catch {
    throw new Error("The PC service can't be reached.");
  }
  return read(response, what);
}

// The tour's "Watch an agent work" chapter shows the real cards on made-up runs (nxAgentViewExample.js).
// It holds them only while its scene is on screen; a real run key is never answered from them.
let example = null;
export function holdExampleRuns(runs) { example = runs; return () => { if (example === runs) example = null; }; }

export const listRuns = () => (example ? Promise.resolve({ runs: example }) : get("runs", {}, "Agent runs"));
export const readTimeline = run => get("timeline", { run }, "Time-lapse");
export const readFrame = ({ run, surface, since, fps, after }) => get("frame", { run, surface, since, fps, after }, "Live frame");
export const keyframeUrl = (run, id) => exampleKeyframe(run) || `${base()}/api/ui/agentview/keyframe?run=${encodeURIComponent(run)}&id=${encodeURIComponent(id)}`;

export async function sendFeedback(args) {
  let response;
  try {
    response = await fetch(`${base()}/api/ui/agentview`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "feedback", args }),
    });
  } catch {
    throw new Error("The PC service can't be reached.");
  }
  return read(response, "Comment");
}
