// Account-display and PDF model claims are checked before results reach the UI.
// Inputs, especially passwords, never appear in errors or proof receipts.
export class ModelContractError extends Error {
  constructor(id) { super(`Model contract ${id} failed`); this.name = "ModelContractError"; this.contract = id; }
}
const same = (a, b) => {
  if (Object.is(a, b)) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && same(a[key], b[key]));
};
function strength(value) {
  const text = String(value || "");
  if (text.length < 8) return 0;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].map(pattern => Number(pattern.test(text))).reduce((sum, count) => sum + count, 0);
  return Math.max(1, Math.min(3, Number(text.length >= 10) + Number(text.length >= 14) + Number(kinds >= 3)));
}
function initialsClaim(value) {
  const parts = String(value || "").trim().split(/[\s._-]+/).filter(Boolean);
  return parts.length ? Array.from(parts[0])[0].toUpperCase() + (parts.length > 1 ? Array.from(parts.at(-1))[0].toUpperCase() : "") : "?";
}
function hueClaim(value) {
  const hash = Array.from(String(value || "").toLowerCase()).reduce((state, letter) => Math.imul(state ^ letter.codePointAt(0), 16777619) >>> 0, 2166136261);
  const offset = hash % 130;
  return offset + (offset < 50 ? 4 : 40);
}
function seenClaim(iso, now) {
  const at = Date.parse(iso || "");
  if (!Number.isFinite(at)) return "";
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  const hours = Math.round(minutes / 60), days = Math.round(hours / 24);
  return minutes < 6 ? "active now" : minutes < 60 ? `${minutes} min ago` : hours < 24 ? `${hours} h ago` : days === 1 ? "yesterday" : `${days} days ago`;
}
function accountProblem({ username, password }, taken) {
  const name = String(username || "").trim();
  const checks = [
    [!name, "Choose a username."],
    [!/^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/.test(name), "Use letters, digits, dots, dashes or underscores, no spaces."],
    [taken.some(existing => existing.toLowerCase() === name.toLowerCase()), `There is already an account called ${name}.`],
    [String(password || "").length < 8, "The password needs at least 8 characters."],
  ];
  return checks.find(([fails]) => fails)?.[1] || "";
}

const rectangle = (item, start = 0, length = item.str.length) => {
  const height = item.height || Math.abs(item.transform[3]) || 10;
  // Keep multiplication order identical to PDF model to avoid introducing
  // a floating-point tolerance that could hide a shifted highlight.
  return [item.transform[4] + item.width * start / Math.max(1, item.str.length), item.transform[5] - height * 0.22, item.transform[4] + item.width * (start + length) / Math.max(1, item.str.length), item.transform[5] + height * 0.88];
};
function searchClaim(pages, query, limit = 500) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return [];
  const expected = [];
  for (const { page, items } of pages) for (const item of items) {
    const chunks = item.str.toLowerCase().split(needle);
    let offset = 0;
    for (const prefix of chunks.slice(0, -1)) {
      offset += prefix.length;
      if (expected.length < limit) expected.push({ page, rect: rectangle(item, offset, needle.length), text: item.str.slice(Math.max(0, offset - 30), offset + needle.length + 30) });
      offset += needle.length;
    }
  }
  return expected;
}

export const ACCOUNT_CONTRACTS = Object.freeze({
  initials: { id: "accounts.initials", claim: "Display first/last Unicode initials and an unknown fallback", check: ([name], result) => result === initialsClaim(name) },
  avatarHue: { id: "accounts.avatar", claim: "Case-insensitive FNV identity selects only the established sun/leaf arcs", check: ([name], result) => result === hueClaim(name) },
  lastSeen: { id: "accounts.last-seen", claim: "Elapsed time maps to the correct rounded minutes/hours/days label; invalid dates are blank", check: ([iso, now], result) => result === seenClaim(iso, now) },
  passwordStrength: { id: "accounts.strength", claim: "Hints reflect minimum length, length bonuses and character diversity", check: ([password], result) => result === strength(password) },
  generatePassword: { id: "accounts.generated-password", claim: "Every password consumes thirteen fresh random draws; those draws determine three pronounceable parts and a 10–99 number", check: ([_random, draws], result) => {
    const consonants = "bcdfghjkmnprstvz", vowels = "aeiou";
    const limits = [consonants.length, vowels.length, consonants.length, vowels.length];
    const expectedLimits = [...limits, ...limits, 90, ...limits];
    if (!Array.isArray(draws) || draws.length !== 13 || !draws.every((row, index) => row.limit === expectedLimits[index] && Number.isInteger(row.value) && row.value >= 0 && row.value < row.limit)) return false;
    const part = offset => draws.slice(offset, offset + 4).map((row, index) => (index % 2 ? vowels : consonants)[row.value]).join("");
    return result === `${part(0)}-${part(4)}-${draws[8].value + 10}-${part(9)}` && strength(result) >= 2;
  } },
  newAccountProblem: { id: "accounts.form", claim: "First actionable account error wins; usernames are unique ignoring case and passwords have >=8 characters", check: ([account, taken = []], result) => result === accountProblem(account, taken) },
  deviceKind: { id: "accounts.device", claim: "Recognized phone/tablet/desktop app names select their icons; other devices use computer", check: ([device], result) => { const text = String(device || ""); return result === (/iPhone|Android/.test(text) ? "phone" : /iPad/.test(text) ? "tablet" : /desktop app/.test(text) ? "app" : "computer"); } },
});
const zoomSteps = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3];
function pdfNameClaim(source, result) {
  if (source?.file?.name) return result === String(source.file.name);
  if (typeof result !== "string" || !result || result === "raw" || /[?#\\/]/.test(result)) return false;
  let text = String(source?.value ?? source ?? "");
  try { text = decodeURIComponent(text); } catch { /* keep it raw */ }
  try { text = decodeURIComponent(text); } catch { /* already decoded */ }
  return result === "document.pdf" || ("/" + text.replaceAll("\\", "/")).split(/[/?&=#]/).includes(result);
}

export const PDF_CONTRACTS = Object.freeze({
  itemRect: { id: "pdf.text-geometry", claim: "Character highlights preserve PDF baseline, proportional x range and descender bounds", check: (args, result) => same(result, rectangle(...args)) },
  searchTexts: { id: "pdf.search", claim: "Return every bounded nonoverlapping case-insensitive occurrence in page/run order with actual text geometry", check: (args, result) => same(result, searchClaim(...args)) },
  stepZoom: { id: "pdf.zoom", claim: "Zoom moves to nearest supported step in the requested direction and clamps at endpoints", check: ([scale, direction], result) => { const allowed = zoomSteps.filter(step => direction > 0 ? step > scale + 0.01 : step < scale - 0.01); return result === (direction > 0 ? allowed[0] ?? 3 : allowed.at(-1) ?? 0.5); } },
  displayName: { id: "pdf.display-name", claim: "A PDF is named by its file name, never an encoded route, query or internal path", check: ([source], result) => pdfNameClaim(source, result) },
  clampPage: { id: "pdf.page", claim: "Page navigation rounds/coerces input and stays within 1..page count", check: ([page, count], result) => Object.is(result, Math.min(Math.max(1, Math.round(Number(page) || 1)), Math.max(1, count || 1))) },
});

export function checkedModelAction(contracts, name, args, result) {
  const claim = contracts[name];
  if (!claim || !claim.check(args, result)) throw new ModelContractError(claim?.id || name);
  return result;
}
