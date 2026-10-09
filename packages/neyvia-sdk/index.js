/** Neyvia app SDK ABI 1. Browser calls retain the host's owner session cookie. */
/** Compatibility numbers apps declare in neyvia.app.json "requires" (see src/grant_agent/compat.py). */
export const SDK_ABI = 1;
export const NEYVIA_API = "1.0.0";
export class NeyviaError extends Error {
  constructor(message, { code = "", status = 0 } = {}) {
    super(message);
    this.name = "NeyviaError";
    this.code = code;
    this.status = status;
  }
}

export function createNeyviaClient({ baseUrl = "", appId = "", fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetch is required");
  const root = baseUrl.replace(/\/$/, "");
  if (root && new URL(root, globalThis.location?.href || "http://127.0.0.1/").origin !== globalThis.location?.origin) {
    throw new TypeError("Neyvia browser SDK requires the same origin as its host");
  }
  async function post(path, body) {
    let response;
    try {
      response = await fetchImpl(`${root}${path}`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(appId ? { "X-Neyvia-App": appId } : {}) }, body: JSON.stringify(body),
      });
    } catch {
      throw new NeyviaError("Neyvia's local service is unavailable", { code: "network" });
    }
    const answer = await response.json().catch(() => ({}));
    if (!response.ok || answer?.ok !== true) {
      throw new NeyviaError(answer?.error || `Neyvia request failed (HTTP ${response.status})`, {
        code: answer?.code || (response.status === 401 ? "login_required" : ""), status: response.status,
      });
    }
    return answer.data;
  }
  const command = (name, payload = {}) => post("/api/backend", { command: name, payload });
  const tool = (name, args = {}) => post("/api/ui/tools/call", { tool: name, arguments: args });
  return Object.freeze({
    command, tool,
    applications: () => command("get_neyvia_application_registry_command"),
    signIn: () => post("/api/auth/local-session", {}),
    providers: (app = "codex") => command("connected_provider_options_command", { app }),
    providerStatus: (app = "codex") => command("connected_app_auth_command", { app }),
    signInProvider: (app = "codex") => command("connected_app_sign_in_command", { app }),
    recall: (situation, { sessionId = "", budget = 256 } = {}) =>
      command("memory_recall_command", { situation, budget, ...(sessionId ? { sessionId } : {}) }),
    remember: ({ key, content, requestId, kind = "fact", cues = {}, sessionId = "" }) =>
      command("memory_remember_command", { key, content, requestId, kind, cues, exportPolicy: "local",
        ...(sessionId ? { sessionId } : {}) }),
    modelCall: ({ app, cwd, message, requestId, model = "", permissionMode = "read-only" }) =>
      command("connected_session_new_command", { app, cwd, message, requestId,
        options: { permissionMode, ...(model ? { model } : {}) } }),
    modelResult: (sessionId, { limit = 200 } = {}) =>
      command("connected_session_read_command", { id: sessionId, limit }),
    verify: ({ question, candidate, evidence }) =>
      tool("neyvia.efficiency.laya_verify", { question, candidate, evidence }),
    manual: (layer, { chapter = "", level = 1 } = {}) =>
      tool("neyvia.cl.describe", { layer, level, ...(chapter ? { chapter } : {}) }),
    cl: (lines) => tool("neyvia.cl", { lines }),
    judgeScene: ({ scene, predicates, domain = "", user = "", record = true }) =>
      tool("neyvia.laya.judge", { scene, user, record, ...(predicates ? { predicates } : {}), ...(domain ? { domain } : {}) }),
    registerApp: ({ applicationId, name, services, summary = "", version = "", permissions = [] }) =>
      command("register_sdk_application_command", { applicationId, name, services, summary, version, permissions }),
  });
}
