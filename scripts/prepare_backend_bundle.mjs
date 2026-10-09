/** Stage the Python backend used by the installed Neyvia desktop app. */

import { cpSync, existsSync, lstatSync, mkdirSync, readdirSync, renameSync, statSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from 'node:crypto';
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const runtimeOnly = process.argv.includes('--runtime-only');
const evidenceRoot = join(repoRoot, 'scripts', 'evidence');
const targetFlag = process.argv.indexOf("--target-root");
const explicitTarget = targetFlag < 0 ? null : process.argv[targetFlag + 1];
if (targetFlag >= 0 && (!explicitTarget || !isAbsolute(explicitTarget))) throw new Error("Explicit staging target must be absolute");
const targetRoot = explicitTarget ? resolve(explicitTarget) : resolve(repoRoot, "src-tauri", "target");
const stagedRoot = resolve(targetRoot, "backend-bundle");
const stagedRelative = relative(targetRoot, stagedRoot);
if (!stagedRelative || stagedRelative.startsWith("..") || isAbsolute(stagedRelative) || !stagedRoot.startsWith(targetRoot + sep)) {
  throw new Error("Backend staging path is outside the selected target.");
}
for (let parent = targetRoot; ; parent = dirname(parent)) {
  if (existsSync(parent) && lstatSync(parent).isSymbolicLink()) throw new Error("Backend staging refuses linked target parents");
  if (dirname(parent) === parent) break;
}

const sources = [
  [join(repoRoot, "src", "grant_agent"), join(stagedRoot, "src", "grant_agent")],
  [join(repoRoot, "scripts"), join(stagedRoot, "scripts")],
  [join(repoRoot, "config"), join(stagedRoot, "config")],
  [join(repoRoot, "manuals"), join(stagedRoot, "manuals")],
  [join(repoRoot, ".codex", "skills"), join(stagedRoot, ".codex", "skills")],
  // "Add Neyvia to my Claude Code" installs from these (src/grant_agent/claude_mod.py).
  [join(repoRoot, "plugins", "neyvia"), join(stagedRoot, "plugins", "neyvia")],
  [join(repoRoot, ".claude-plugin", "marketplace.json"), join(stagedRoot, ".claude-plugin", "marketplace.json")],
  [join(repoRoot, "src-tauri", "resources", "backend-requirements.txt"), join(stagedRoot, "backend-requirements.txt")],
];
// Preserve the generated module map in installed source workspaces too.
// Ownership includes manifests/configuration that deliberately have no source hash.
const moduleRegistry = JSON.parse(readFileSync(join(repoRoot, 'config', 'neyvia.modules.json'), 'utf8'));
// Module loading also checks declared documentation/assets, even when the
// behavior registry intentionally omits them from source ownership.
const declaredModuleFiles = [];
for (const entry of readdirSync(join(repoRoot, 'apps'), { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  if (lstatSync(join(repoRoot, 'apps', entry.name)).isSymbolicLink()) throw new Error('Linked module directory: ' + entry.name);
  const manifest = join(repoRoot, 'apps', entry.name, 'neyvia.module.json');
  if (existsSync(manifest)) {
    if (lstatSync(manifest).isSymbolicLink()) throw new Error('Linked module manifest: ' + entry.name);
    declaredModuleFiles.push(...JSON.parse(readFileSync(manifest, 'utf8')).files);
  }
}
for (const name of new Set([...moduleRegistry.ownedFiles, ...declaredModuleFiles])) {
  const source = resolve(repoRoot, name);
  const rel = relative(repoRoot, source);
  if (!rel || rel.startsWith('..') || isAbsolute(rel) || !existsSync(source) || !statSync(source).isFile()) {
    throw new Error('Invalid registered module source: ' + name);
  }
  for (let parent = source; parent !== repoRoot; parent = dirname(parent)) {
    if (lstatSync(parent).isSymbolicLink()) throw new Error('Linked registered module source: ' + name);
  }
  const alreadyStaged = sources.some(([root]) => {
    const child = relative(root, source);
    return !child || (!child.startsWith('..') && !isAbsolute(child) && statSync(root).isDirectory());
  });
  if (!alreadyStaged) sources.push([source, join(stagedRoot, rel)]);
}
sources.push([join(repoRoot, 'MODULES.md'), join(stagedRoot, 'MODULES.md')],
  [join(repoRoot, 'modules'), join(stagedRoot, 'modules')]);
if (runtimeOnly) {
  // The runtime reads these admitted metadata/fixture records directly.
  // Full historical proof trees remain in source and D receipts, outside the
  // installed backend. Existing full-source staging remains available.
  for (const name of [
    'FOLLOW-license-desktop-metadata.json','FOLLOW-license-cache-metadata.json',
    'FOLLOW-license-python-metadata.json','FOLLOW-license-python-requirements.txt',
    'C2h-engine-admission.json','C2g-engine-fragment-admission.json','C2g-engine-admission.json',
    'C2g-engine-pr1080-verified-build.json','PROOFS-b-revalidation.json',
    'C13g-motion/positive/report.json','C13g-contracts/connectors/report.json','C13g-contracts/font-geometry/report.json',
  ]) {
    const file = join(evidenceRoot, name);
    if (existsSync(file)) sources.push([file, join(stagedRoot,'scripts','evidence',name)]);
  }
}
const excludedNames = new Set(["__pycache__", ".pytest_cache", ".mypy_cache", ".agent_control", ".agent_runs", '.git', 'node_modules']);
const privateSources = new Set([resolve(repoRoot, 'config/neyvia_secret_broker.json')]);
const include = source => {
  if (privateSources.has(resolve(source))) return false;
  if (runtimeOnly && resolve(source) === evidenceRoot) return false;
  const name = source.split(/[\\/]/).at(-1);
  if (excludedNames.has(name) || /\.(pyc|pyo)$/i.test(name)) return false;
  return !lstatSync(source).isSymbolicLink();
};

for (const [source] of sources) {
  if (!existsSync(source)) throw new Error(`Required backend source is missing: ${relative(repoRoot, source)}`);
}
if (existsSync(stagedRoot)) renameSync(stagedRoot, `${stagedRoot}.previous-${Date.now()}`);
for (const [source, destination] of sources) {
  mkdirSync(dirname(destination), { recursive: true });
  if (process.platform === "win32" && statSync(source).isDirectory() && resolve(source) !== resolve(repoRoot, 'config')) {
    // Bounded parallel copy avoids serial metadata waits on large proof trees.
    // /E never deletes; /XJ excludes linked files and directories like the
    // cross-platform filter. Robocopy 0..7 are successful copy outcomes.
    const result = spawnSync("robocopy.exe", [source, destination, "/E", "/XJ", "/MT:6", "/R:0", "/W:0",
      "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD", ...excludedNames, ...(runtimeOnly ? [evidenceRoot] : []), "/XF", "*.pyc", "*.pyo", ...privateSources],
      { windowsHide: true, encoding: "utf8" });
    if (result.error || result.status === null || result.status >= 8) {
      throw new Error(`Backend copy failed for ${relative(repoRoot, source)}: ${result.error?.message || result.stdout || result.stderr || result.status}`);
    }
  } else {
    cpSync(source, destination, { recursive: true, filter: include });
  }
}

// The plugin's manual skills are generated here, from the manuals being staged, so an installed app never
// carries stale ones. The version file lets the installed backend report which build it is.
{
  const python = process.env.NEYVIA_BUILD_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const made = spawnSync(python, [join(repoRoot, "scripts", "build_claude_plugin_skills.py"), "--out", join(stagedRoot, "plugins", "neyvia", "skills")],
    { cwd: repoRoot, encoding: "utf8", windowsHide: true, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  if (made.status !== 0) throw new Error(`Claude plugin skills were not generated: ${made.stderr || made.stdout}`);
  writeFileSync(join(stagedRoot, "VERSION"), JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8")).version + "\n");
}

const required = [
  "src/grant_agent/cli.py",
  "plugins/neyvia/.claude-plugin/plugin.json",
  ".claude-plugin/marketplace.json",
  "VERSION",
  "src/grant_agent/web_backend.py",
  "src/grant_agent/chat_stream.py",
  "src/grant_agent/codex_app_server_stream.py",
  "scripts/verify_authenticated_live_agent.py",
  "config/tool_suite_lock.json",
  "config/capability_packs.json",
  "config/neyvia_manuals.json",
  "config/fixcl_manual_cache.json",
  "manuals/cl/proofs.cl",
  ".codex/skills/jbheaven-enhanced-workflow/SKILL.md",
  "backend-requirements.txt",
  "MODULES.md",
  "config/neyvia.modules.json",
];
for (const item of required) {
  if (!existsSync(join(stagedRoot, item))) throw new Error(`Staged backend is incomplete: ${item}`);
}

function stats(directory) {
  let files = 0;
  let bytes = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) {
      const nested = stats(full);
      files += nested.files;
      bytes += nested.bytes;
    } else {
      files++;
      bytes += statSync(full).size;
    }
  }
  return { files, bytes };
}
const result = stats(stagedRoot);
const sourceHashes = {};
const versionFile = join(stagedRoot, 'VERSION');
const expectedVersion = JSON.parse(readFileSync(join(repoRoot, 'package.json'), 'utf8')).version + '\n';
if (readFileSync(versionFile, 'utf8') !== expectedVersion) throw new Error('Staged backend version drifted');
sourceHashes.VERSION = createHash('sha256').update(readFileSync(versionFile)).digest('hex');
for (const name of required.filter(name => name !== 'backend-requirements.txt' && name !== 'VERSION')) {
  const digest = file => createHash('sha256').update(readFileSync(file)).digest('hex');
  if (digest(join(repoRoot,name)) !== digest(join(stagedRoot,name))) throw new Error(`Staged source drifted: ${name}`);
  sourceHashes[name] = digest(join(stagedRoot,name));
}
const moduleSourceHashes = {};
for (const [name, expected] of Object.entries(moduleRegistry.sourceHashes)) {
  const raw = readFileSync(join(stagedRoot, name));
  const text = raw.toString('utf8');
  const normalized = Buffer.from(text, 'utf8').equals(raw) ? Buffer.from(text.replace(/\r\n/g, '\n'), 'utf8') : raw;
  const actual = createHash('sha256').update(normalized).digest('hex');
  if (actual !== expected) throw new Error('Staged module source drifted: ' + name);
  moduleSourceHashes[name] = actual;
}
writeFileSync(join(stagedRoot,'backend-bundle-manifest.json'),JSON.stringify({schema:'neyvia.backend-bundle.v1',
  mode:runtimeOnly?'runtime-only':'full-source', files:result.files,bytes:result.bytes,requiredSourceHashes:sourceHashes,moduleSourceHashes,
  excludedProofHistory:runtimeOnly,excludedNames:[...excludedNames],generatedAt:new Date().toISOString()},null,2)+'\n');
console.log(`Backend bundle ready: ${result.files} files, ${(result.bytes / 1024 / 1024).toFixed(2)} MiB.`);
