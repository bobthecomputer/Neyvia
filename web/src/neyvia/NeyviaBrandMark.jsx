import { ProviderMark } from "./next/ProviderMark.jsx";

function cx(...values) {
  return values.filter(Boolean).join(" ");
}

/**
 * Neyvia's sun mark: a broad tree against a banded southern sunset.
 * Same vector source as the app icons (scripts/brand/neyvia_sun_mark.py).
 */
export function NeyviaBrandMark({ className = "", size = "default", title = "Neyvia" }) {
  const dimension = size === "tiny" ? 17 : size === "compact" ? 22 : 28;
  return <ProviderMark id="neyvia" size={dimension} title={title || undefined} className={cx("fluxio-brand-mark", `fluxio-brand-mark-${size}`, className)} />;
}

export function providerToneSlug(value) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s_/]+/g, "-");
  if (normalized.includes("openai") || normalized.includes("codex")) return "provider-openai";
  if (normalized.includes("cursor")) return "provider-cursor";
  if (normalized.includes("minimax")) return "provider-minimax";
  if (normalized.includes("openrouter")) return "provider-openrouter";
  if (normalized.includes("glm") || normalized.includes("z-ai")) return "provider-glm";
  if (normalized.includes("deepseek")) return "provider-deepseek";
  if (normalized.includes("opencode")) return "provider-opencode";
  if (normalized.includes("anthropic")) return "provider-anthropic";
  return "provider-neutral";
}

export function routeRoleToneClass(role) {
  const normalized = String(role || "").trim().toLowerCase();
  if (normalized === "executor") return "agent-route-executor role-executor";
  if (normalized === "verifier") return "role-verifier";
  if (normalized === "planner") return "role-planner";
  if (normalized === "runtime") return "role-runtime";
  return "";
}
