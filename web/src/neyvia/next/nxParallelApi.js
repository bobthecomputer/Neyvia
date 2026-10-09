import { backendBase } from "./nxApi.js";

// Parallel branches (plan 29): the pane's side of GET/POST /api/ui/parallel (src/grant_agent, PARALLEL-contract.md).
// A model starts and steers a run with neyvia.parallel.* (mcp__neyvia__parallel_*); the same implementation answers here.
// Under `vite dev` with ?fixtures=1 the design fixture answers instead, with the same shapes.

const fixtures = () => import.meta.env?.DEV === true && new URLSearchParams(globalThis.location?.search || "").get("fixtures") === "1";

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

/** Every run, newest first: { ok, runs }. Throws when the PC service can't be reached or the person isn't signed in. */
export async function readParallel({ signal } = {}) {
  if (fixtures()) return (await import("./nxParallelFixture.js")).fixtureParallelRead();
  let response;
  try { response = await fetch(`${base()}/api/ui/parallel`, { credentials: "include", signal }); }
  catch (error) { if (error?.name === "AbortError") throw error; throw new Error("The PC service can't be reached."); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw Object.assign(new Error(result?.error || `Parallel runs could not be read (HTTP ${response.status}).`), { status: response.status });
  return result?.data ?? result; // HTTP wraps a result as { ok, data }
}

/**
 * One action on a run: merge | resolved | finish | settle | stop | answer. Resolves with the reply ({ ok, run, ... });
 * a refused one rejects with the backend's reason. State is read again afterwards either way, because files and
 * sessions may already have changed.
 */
export async function parallelAction(operation, body = {}) {
  if (fixtures()) {
    await new Promise(resolve => setTimeout(resolve, 350));
    return (await import("./nxParallelFixture.js")).fixtureParallelAction({ operation, ...body });
  }
  let response;
  try {
    response = await fetch(`${base()}/api/ui/parallel`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, ...body }) });
  } catch { throw new Error("The PC service can't be reached."); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw Object.assign(new Error(result?.error || `${operation} failed (HTTP ${response.status}).`), { status: response.status });
  return result?.data ?? result;
}
