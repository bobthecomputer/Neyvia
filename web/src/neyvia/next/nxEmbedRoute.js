// "Open here" in the Library and the Marketplace dispatch neyvia:open-embedded-workspace
// (NeyviaEcosystemHost.jsx). The classic UI that rendered those workspaces is gone, so the
// single shell answers the event by opening the matching surface it has.
export const EMBED_EVENT = "neyvia:open-embedded-workspace";

/** Where an embedded-workspace request opens in this shell, or null when nothing fits. */
export function embeddedRoute(detail) {
  const id = String(detail?.adapterId || "");
  const context = detail?.context || {};
  const ref = detail?.contentRef || {};
  const absolute = value => (typeof value === "string" && value.startsWith("/") && globalThis.location ? new URL(value, globalThis.location.origin).href : value || null);
  switch (id) {
    case "pdf-reader": return { kind: "app", app: "pdf", suite: "documents", target: ref.path || context.path || null };
    case "office-document": return { kind: "tool", app: "office-suite", target: null };
    case "image-playground": return { kind: "tool", app: "image-playground", target: null };
    case "app-preview": return { kind: "tool", app: "preview", target: context.jobId ? JSON.stringify({ jobId: String(context.jobId), root: String(context.root || "") }) : null };
    case "browser-capture": return { kind: "app", app: "browser", suite: "", target: absolute(ref.url) };
    case "marketplace-app": return ref.url ? { kind: "app", app: "browser", suite: "", target: absolute(ref.url) } : { kind: "tool", app: "marketplace", target: null };
    case "runtime-window": return { kind: "pane", pane: "runtime", target: "" };
    default: return null;
  }
}
