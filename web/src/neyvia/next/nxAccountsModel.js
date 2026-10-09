// Accounts: pure helpers shared by the sign-in page and the Accounts screen.
import { ACCOUNT_CONTRACTS, checkedModelAction } from "./nxModelContracts.js";

export const USERNAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/;
export const PASSWORD_MIN = 8;

/** Up to two initials: "Paul Martin" -> "PM", "maya" -> "M". */
function _initials(name) {
  const words = String(name || "").trim().split(/[\s._-]+/).filter(Boolean);
  if (!words.length) return "?";
  const letters = words.length > 1 ? [words[0], words[words.length - 1]] : [words[0]];
  return letters.map(word => [...word][0].toUpperCase()).join("");
}

/** A stable hue per username, from ember and amber to leaf and moss (FNV-1a over the lowercased name). */
function _avatarHue(username) {
  let hash = 0x811c9dc5;
  for (const char of String(username || "").toLowerCase()) hash = Math.imul(hash ^ char.codePointAt(0), 0x01000193) >>> 0;
  // 0..129 spread over two arcs: sun (4..53) and leaf (90..169); blues and purples stay out.
  const step = hash % 130;
  return step < 50 ? 4 + step : 40 + step;
}

/** "just now", "5 min ago", "3 h ago", "yesterday", "12 days ago". */
function _lastSeen(iso, now = Date.now()) {
  const at = Date.parse(iso || "");
  if (!Number.isFinite(at)) return "";
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 6) return "active now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** Rough strength for a hint under the field: 0 too short, 1 weak, 2 fair, 3 strong. */
function _passwordStrength(password) {
  const value = String(password || "");
  if (value.length < PASSWORD_MIN) return 0;
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter(pattern => pattern.test(value)).length;
  const score = (value.length >= 14 ? 2 : value.length >= 10 ? 1 : 0) + (kinds >= 3 ? 1 : 0);
  return Math.max(1, Math.min(3, score));
}
export const STRENGTH_LABELS = ["Too short", "Weak", "Fair", "Strong"];

/** A password that is easy to read out and type on a phone: four short words of letters and digits. */
function _generatePassword(random = cryptoRandom) {
  const consonants = "bcdfghjkmnprstvz";
  const vowels = "aeiou";
  const part = () => Array.from({ length: 4 }, (_, index) => (index % 2 ? vowels : consonants)[random(index % 2 ? vowels.length : consonants.length)]).join("");
  return [part(), part(), `${random(90) + 10}`, part()].join("-");
}

function cryptoRandom(limit) {
  const values = new Uint32Array(1);
  globalThis.crypto.getRandomValues(values);
  return values[0] % limit;
}

/** What is wrong with the "add someone" form, or "" when it can be sent. */
function _newAccountProblem({ username, password }, taken = []) {
  const name = String(username || "").trim();
  if (!name) return "Choose a username.";
  if (!USERNAME_PATTERN.test(name)) return "Use letters, digits, dots, dashes or underscores, no spaces.";
  if (taken.some(existing => existing.toLowerCase() === name.toLowerCase())) return `There is already an account called ${name}.`;
  if (String(password || "").length < PASSWORD_MIN) return `The password needs at least ${PASSWORD_MIN} characters.`;
  return "";
}

/** A device row's icon kind: phone, tablet, desktop app or computer. */
function _deviceKind(device) {
  const text = String(device || "");
  if (/iPhone|Android/.test(text)) return "phone";
  if (/iPad/.test(text)) return "tablet";
  if (/desktop app/.test(text)) return "app";
  return "computer";
}

export function initials(name) { return checkedModelAction(ACCOUNT_CONTRACTS, "initials", [name], _initials(name)); }
export function avatarHue(username) { return checkedModelAction(ACCOUNT_CONTRACTS, "avatarHue", [username], _avatarHue(username)); }
export function lastSeen(iso, now = Date.now()) { return checkedModelAction(ACCOUNT_CONTRACTS, "lastSeen", [iso, now], _lastSeen(iso, now)); }
export function passwordStrength(password) { return checkedModelAction(ACCOUNT_CONTRACTS, "passwordStrength", [password], _passwordStrength(password)); }
export function generatePassword(random = cryptoRandom) {
  const draws = [];
  const result = _generatePassword(limit => { const value = random(limit); draws.push({ limit, value }); return value; });
  return checkedModelAction(ACCOUNT_CONTRACTS, "generatePassword", [random, draws], result);
}
export function newAccountProblem(account, taken = []) { return checkedModelAction(ACCOUNT_CONTRACTS, "newAccountProblem", [account, taken], _newAccountProblem(account, taken)); }
export function deviceKind(device) { return checkedModelAction(ACCOUNT_CONTRACTS, "deviceKind", [device], _deviceKind(device)); }
