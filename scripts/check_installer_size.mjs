/**
 * Enforce the Neyvia core installer's size budget and content rules.
 *
 * Neyvia's premise is a small core that installs optional CLIs, models, and
 * marketplace applications on demand. Nothing enforces that premise on its own:
 * a single transitive dependency can quietly add tens of megabytes to the core,
 * and nobody notices until the download is the thing users complain about. This
 * check fails the build instead.
 *
 * It enforces two separate things, because size alone is a lagging indicator:
 *   1. Artifact sizes against `src-tauri/installer-budget.json`.
 *   2. Forbidden content in the staged resources — model weights, FFmpeg, GPU
 *      runtimes, node_modules — which are wrong in the core at *any* size.
 *
 * Run after `tauri build`. Exits non-zero on any violation.
 * Dependency-free by design: a packaging guard that needs packages installed is
 * a guard that gets skipped.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { checkInstallerBudgetObservation } from "./release-contracts.mjs";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const MIB = 1024 * 1024;
const mib = (bytes) => `${(bytes / MIB).toFixed(2)} MiB`;


/** Largest file matching a suffix under a directory, or null. */
function findArtifact(directory, suffix) {
  if (!existsSync(directory)) return null;
  const matches = readdirSync(directory)
    .filter((name) => name.toLowerCase().endsWith(suffix))
    .map((name) => ({ path: join(directory, name), size: statSync(join(directory, name)).size }))
    .sort((a, b) => b.size - a.size);
  return matches[0] ?? null;
}

function walk(directory) {
  const files = [];
  if (!existsSync(directory)) return files;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walk(full));
    else files.push(full);
  }
  return files;
}

/** Inspect actual staged artifacts/resources without building, installing or changing them. */
export function inspectInstallerBudget({ repository = repoRoot, targetRoot = process.env.CARGO_TARGET_DIR, slim = false, debug = false, bundles = ["msi", "nsis"] } = {}) {
const cargoTargetRoot = targetRoot ? resolve(repository, targetRoot) : join(repository, "src-tauri", "target");
const releaseRoot = join(cargoTargetRoot, debug ? "debug" : "release");
const budgetPath = join(repository, "src-tauri", "installer-budget.json");
if (!existsSync(budgetPath)) throw new Error(`Missing budget file: ${relative(repository, budgetPath)}`);
const budget = JSON.parse(readFileSync(budgetPath, "utf8"));
const selectedBundles = new Set(bundles);
if (!selectedBundles.size || [...selectedBundles].some(value => !["msi", "nsis"].includes(value))) throw new Error("--bundles must contain msi, nsis, or both");
const violations = [], reasons = [];
const report = [];

// --- artifact sizes --------------------------------------------------------

const artifacts = [
  { key: "msi", found: findArtifact(join(releaseRoot, "bundle", "msi"), ".msi") },
  { key: "nsis", found: findArtifact(join(releaseRoot, "bundle", "nsis"), ".exe") },
];

for (const { key, found } of artifacts.filter(item => selectedBundles.has(item.key))) {
  const limit = budget.budgets?.[key];
  if (!limit) continue;
  if (!found) {
    reasons.push("missing:" + key);
    violations.push(`${limit.label}: requested artifact was not built.`);
    continue;
  }
  const withinBudget = found.size <= limit.maxBytes;
  report.push(
    `  ${limit.label}: ${mib(found.size)} / ${mib(limit.maxBytes)} ${withinBudget ? "OK" : "OVER"}`,
  );
  if (!withinBudget) {
    reasons.push("artifact-budget:" + key);
    violations.push(
      `${limit.label} is ${mib(found.size)}, over its ${mib(limit.maxBytes)} budget. ` +
        `Something heavy was added to the core installer.`,
    );
  }
}

// --- staged resources ------------------------------------------------------

const stagedRoot = join(releaseRoot, "backend");
const stagedFiles = walk(stagedRoot);
const stagedBytes = stagedFiles.reduce((total, file) => total + statSync(file).size, 0);

if (slim) {
  report.push(`  Shell-only resources: ${stagedFiles.length} backend files`);
  if (stagedFiles.length !== 0) { reasons.push("slim-backend"); violations.push("Slim installer contains bundled backend files."); }
} else if (stagedFiles.length === 0) {
  reasons.push("backend-missing");
  violations.push(
    `No staged backend resources found at ${relative(repository, stagedRoot)}. ` +
      `The installer would ship without its backend — run \`npm run tauri -- build\` first.`,
  );
} else {
  const limit = budget.budgets?.stagedResources;
  if (limit) {
    const withinBudget = stagedBytes <= limit.maxBytes;
    report.push(
      `  ${limit.label}: ${mib(stagedBytes)} / ${mib(limit.maxBytes)} ${withinBudget ? "OK" : "OVER"} (${stagedFiles.length} files)`,
    );
    if (!withinBudget) {
      reasons.push("resources-budget");
      violations.push(
        `${limit.label} total ${mib(stagedBytes)}, over its ${mib(limit.maxBytes)} budget.`,
      );
    }
  }

  // --- forbidden content ---------------------------------------------------

  for (const rule of budget.forbiddenContent ?? []) {
    const pattern = new RegExp(rule.pattern, "i");
    const offenders = stagedFiles
      .map((file) => relative(stagedRoot, file).split("\\").join("/"))
      .filter((relativePath) => pattern.test(relativePath));
    if (offenders.length > 0) {
      reasons.push("forbidden:" + rule.pattern);
      violations.push(
        `Forbidden content in the core installer (${offenders.length} file(s) matching /${rule.pattern}/): ` +
          `${rule.reason}\n      e.g. ${offenders.slice(0, 3).join(", ")}`,
      );
    }
  }
}

return checkInstallerBudgetObservation({ budget, selectedBundles, artifacts, stagedFiles: stagedFiles.map(file => relative(stagedRoot, file).split("\\").join("/")), stagedBytes, slim },
  { ok: violations.length === 0, violations, reasons, report, stagedFileCount: stagedFiles.length });
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args=process.argv.slice(2),bundleArgs=args.filter(value=>!["--slim","--debug"].includes(value));
    if(bundleArgs.length && (bundleArgs.length!==2 || bundleArgs[0]!=="--bundles"))throw Error("Usage: node scripts/check_installer_size.mjs [--bundles msi,nsis]");
    const result=inspectInstallerBudget({slim:args.includes("--slim"),debug:args.includes("--debug"),bundles:bundleArgs.length?bundleArgs[1].split(",").map(value=>value.trim().toLowerCase()):undefined});
    console.log("Neyvia core installer budget:");for(const line of result.report)console.log(line);
    if(!result.ok){console.error(`\nInstaller budget check FAILED (${result.violations.length}):`);for(const violation of result.violations)console.error(`  - ${violation}`);console.error("\nThe core installer must stay thin. If this growth is required, raise the budget in src-tauri/installer-budget.json and record why.");process.exitCode=1;}
    else console.log("\nInstaller budget check passed: the core stayed thin.");
  }catch(error){console.error(error.message);process.exitCode=1;}
}
