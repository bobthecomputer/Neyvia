/** Stage a signed desktop base pack and add-ons without installing or downloading anything. */
import { createHash, createPrivateKey, createPublicKey, sign } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, copyFileSync, writeFileSync, statSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { checkSignedEnvelope, checkExternalDeclarations, validateReleaseOutput, validateSigningKeyPath } from './release-contracts.mjs';

export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const ignored = new Set(['__pycache__', '.pytest_cache', '.mypy_cache', '.agent_control', '.agent_runs', 'evidence', 'node_modules', 'target', 'dist', 'build', '.git']);
function inside(root, target) {
  const rel = relative(root, target);
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel);
}
function walk(root, prefix = '') {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = join(root, entry.name), rel = prefix + entry.name;
    if (ignored.has(entry.name) || /\.(pyc|pyo)$/i.test(entry.name)) return [];
    if (lstatSync(path).isSymbolicLink()) throw new Error(`Symlink is not a release payload: ${path}`);
    return entry.isDirectory() ? walk(path, rel + '/') : [rel];
  }).sort();
}
function copy(source, target) {
  if (lstatSync(source).isSymbolicLink()) throw new Error(`Symlink is not a release payload: ${source}`);
  if (lstatSync(source).isDirectory()) {
    for (const file of walk(source)) copy(join(source, file), join(target, file));
  } else {
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(source, target);
  }
}
export function signer(secretKeyFile, repository = REPO) {
  const keyPath = resolve(secretKeyFile);
  validateSigningKeyPath(repository, keyPath);
  return signerFromKey(createPrivateKey(readFileSync(keyPath)));
}
export function signerFromKey(key) {
  if (key.asymmetricKeyType !== 'ed25519') throw new Error('Use an Ed25519 PEM release key.');
  const raw = createPublicKey(key).export({ format: 'der', type: 'spki' }).subarray(-32);
  const id = createHash('sha256').update(raw).digest().subarray(0, 8);
  const pubkey = Buffer.concat([Buffer.from('Ed'), id, raw]).toString('base64');
  return { pubkey, sign(bytes, comment) {
    const packet = Buffer.concat([Buffer.from('Ed'), id, sign(null, bytes, key)]);
    const global = sign(null, Buffer.concat([packet.subarray(10), Buffer.from(comment)]), key);
    return checkSignedEnvelope(bytes, comment, pubkey, `untrusted comment: Neyvia manifest signature\n${packet.toString('base64')}\ntrusted comment: ${comment}\n${global.toString('base64')}\n`);
  } };
}
export function externalPackDeclarations(registry, repository = REPO) {
  const declarations = Object.entries(registry.packages).filter(([, value]) => !value.localComponents)
    .map(([id]) => JSON.parse(readFileSync(join(repository, registry.manifests[id]))));
  return checkExternalDeclarations(registry, declarations);
}
function emitPack(directory, metadata, signManifest) {
  const payload = join(directory, 'files');
  const files = walk(payload).map(path => {
    const bytes = readFileSync(join(payload, path));
    return { path, url: 'files/' + path.split('/').map(encodeURIComponent).join('/'), size: bytes.length, sha256: hash(bytes) };
  });
  const manifest = { schema: 'neyvia.base-pack/v1', ...metadata, totalSize: files.reduce((sum, f) => sum + f.size, 0), files };
  const bytes = Buffer.from(JSON.stringify(manifest, null, 2) + '\n');
  writeFileSync(join(directory, 'manifest.json'), bytes);
  writeFileSync(join(directory, 'manifest.json.minisig'), signManifest.sign(bytes, `pack=${manifest.packId} version=${manifest.version}`));
  return { packId: manifest.packId, files: files.length, bytes: manifest.totalSize, manifestSha256: hash(bytes), manifest: relative(REPO, join(directory, 'manifest.json')).replaceAll('\\', '/') };
}
export function prepareRelease(options) {
  const repo = resolve(options.repo || REPO), output = resolve(options.output);
  validateReleaseOutput(repo, output);
  const runtime = resolve(options.pythonRuntime);
  if (!existsSync(join(runtime, 'python.exe'))) throw new Error('Explicit Python runtime must contain python.exe.');
  const provenancePath = join(runtime, 'runtime-provenance.json');
  const runtimeProvenance = existsSync(provenancePath) ? JSON.parse(readFileSync(provenancePath)) : { scope: 'provided-runtime', requirementsMatch: null };
  if (runtimeProvenance.requirementsMatch === false && !options.allowLocalProof) throw new Error('Runtime has recorded version mismatches; use --allow-local-proof only for local proof.');
  const signManifest = signer(options.secretKey, repo);
  const registry = JSON.parse(readFileSync(join(repo, 'config/onboarding_packs.json')));
  const externalDeclarations = externalPackDeclarations(registry, repo);
  mkdirSync(output, { recursive: true });
  const base = join(output, 'base', 'files');
  copy(runtime, join(base, 'python'));
  for (const folder of ['src/grant_agent', 'scripts', 'config', 'manuals', '.codex/skills', 'plugins/neyvia', 'native/ios', 'sdk']) copy(join(repo, folder), join(base, folder));
  for (const file of ['pyproject.toml', 'src-tauri/resources/backend-requirements.txt']) {
    copy(join(repo, file), join(base, file === 'src-tauri/resources/backend-requirements.txt' ? 'backend-requirements.txt' : file));
  }
  const probeCode = "import sys,json,tomllib,importlib.metadata as m;from pathlib import Path;from packaging.requirements import Requirement;sys.path.insert(0,sys.argv[1]);import grant_agent.web_backend;import blake3,cryptography,ddgs,jsonschema,agents,PIL,websockets;rows=[Requirement(s) for s in tomllib.loads((Path(sys.argv[1]).parent/'pyproject.toml').read_text())['project']['dependencies']];bad=[str(r)+' (installed '+m.version(r.name)+')' for r in rows if (not r.marker or r.marker.evaluate()) and r.specifier and not r.specifier.contains(m.version(r.name),prereleases=True)];print(json.dumps({'python':sys.version.split()[0],'backendImport':True,'versionMismatches':bad}))";
  const probe = spawnSync(join(base, 'python', 'python.exe'), ['-I', '-B', '-c', probeCode, join(base, 'src')], { encoding: 'utf8', timeout: 180000, windowsHide: true });
  if (probe.status !== 0) throw new Error(`Staged Python cannot import the backend and dependencies. Supply a complete portable runtime. ${probe.stderr || probe.error?.message || ''}`);
  const runtimeProbe = JSON.parse(probe.stdout.trim());
  if (runtimeProbe.versionMismatches.length && !options.allowLocalProof) throw new Error(`Staged runtime versions do not match production requirements: ${runtimeProbe.versionMismatches.join('; ')}`);
  if (runtimeProbe.versionMismatches.length) { runtimeProvenance.requirementsMatch = false; runtimeProvenance.versionMismatches = runtimeProbe.versionMismatches; }
  const bridge = spawnSync(join(base, 'python', 'python.exe'), ['-I', '-B', '-m', 'grant_agent.desktop_bridge', '--root', join(output, 'bridge-proof-root')], {
    windowsHide: true,
    input: JSON.stringify({ command: 'onboarding_state_command', payload: {} }), encoding: 'utf8', timeout: 180000,
  });
  if (bridge.status !== 0) throw new Error(`Staged desktop module command failed: ${bridge.stderr || bridge.stdout || bridge.error?.message || ''}`);
  const bridgeAnswer = JSON.parse(bridge.stdout.trim());
  if (!bridgeAnswer.ok) throw new Error(`Staged desktop bridge rejected onboarding_state_command: ${bridge.stdout}`);
  const summaries = [emitPack(join(output, 'base'), { packId: 'base', version: options.version, channel: runtimeProvenance.requirementsMatch === false ? 'local-proof' : 'release', runtime: { python: 'python/python.exe', backend: '.' } }, signManifest)];
  for (const [id, definition] of Object.entries(registry.packages)) {
    if (!definition.localComponents) continue;
    const input = JSON.parse(readFileSync(join(repo, registry.manifests[id])));
    const dest = join(output, 'addons', id);
    for (const file of input.files) {
      const source = resolve(dirname(join(repo, registry.manifests[id])), decodeURIComponent(file.url));
      if (!inside(repo, source)) throw new Error(`Add-on source escapes worktree: ${id}`);
      const bytes = readFileSync(source);
      if (hash(bytes) !== file.sha256 || bytes.length !== file.size) throw new Error(`Stale add-on manifest: ${id}/${file.path}; run package_onboarding_packs.py first.`);
      const destination = resolve(dest, 'files', file.path);
      if (!inside(join(dest, 'files'), destination)) throw new Error('Unsafe add-on destination');
      copy(source, destination);
    }
    summaries.push(emitPack(dest, { packId: id, version: input.version, channel: 'local-components' }, signManifest));
  }
  const external = externalDeclarations.map(declaration => {
    const id = declaration.packId;
    const destination = join(output, 'external', id);
    mkdirSync(destination, { recursive: true });
    const bytes = Buffer.from(JSON.stringify(declaration, null, 2) + '\n');
    writeFileSync(join(destination, 'manifest.json'), bytes);
    writeFileSync(join(destination, 'manifest.json.minisig'), signManifest.sign(bytes, `pack=${id} version=${declaration.version}`));
    return { packId: id, status: declaration.deliveryStatus, needsPaul: declaration.needsPaul, sourceArtifacts: declaration.files.length };
  });
  const config = JSON.parse(readFileSync(join(repo, 'src-tauri/tauri.slim.conf.json')));
  writeFileSync(join(output, 'tauri.slim.conf.json'), JSON.stringify(config, null, 2) + '\n');
  writeFileSync(join(output, 'release-public-key.txt'), signManifest.pubkey + '\n');
  const receipt = { schema: 'neyvia.slim-release/v1', version: options.version, output, publicKey: signManifest.pubkey, runtimeProbe: { ...runtimeProbe, desktopModuleCommand: { command: 'onboarding_state_command', ok: bridgeAnswer.ok } }, runtimeProvenance, packs: summaries, external,
    build: { command: 'npm run tauri -- build --config src-tauri/tauri.slim.conf.json', environment: { NEYVIA_SLIM_INSTALLER: '1', NEYVIA_BASE_PACK_PUBLIC_KEY: signManifest.pubkey, NEYVIA_BASE_PACK_URL: options.baseUrl || 'SET_ME_TO_HTTPS_BASE_MANIFEST' }, executed: false } };
  writeFileSync(join(output, 'release-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  return receipt;
}
export function buildInstaller(receipt, { debug = false, repo = REPO } = {}) {
  const startedAt = Date.now();
  const url = new URL(receipt.build.environment.NEYVIA_BASE_PACK_URL);
  const integrationProof = process.env.NEYVIA_SLIM_PROOF_SCOPE === 'INT6';
  const c8ProofRoot = process.env.NEYVIA_C8_PROOF_ROOT;
  const c8Proof = process.env.NEYVIA_SLIM_PROOF_SCOPE === 'C8' && c8ProofRoot
    && /[\\/]\.agent_control[\\/]proofs[\\/]C8$/.test(resolve(c8ProofRoot))
    && inside(resolve(c8ProofRoot), REPO) && resolve(repo) === REPO;
  const localPort = Number(url.port);
  const allowedLocalPort = localPort >= 48161 && localPort <= 48169 || integrationProof && localPort >= 48351 && localPort <= 48359
    || c8Proof && localPort >= 48751 && localPort <= 48759;
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname) && allowedLocalPort)) throw new Error('Base URL must be HTTPS or an explicitly scoped track-local HTTP port.');
  const args = [join(repo, 'node_modules/@tauri-apps/cli/tauri.js'), 'build', '--config', join(repo, 'src-tauri/tauri.slim.conf.json')];
  if (debug) args.push('--debug');
  const target = integrationProof && process.env.NEYVIA_SLIM_TARGET_DIR ? resolve(process.env.NEYVIA_SLIM_TARGET_DIR) : join(repo, 'src-tauri/target');
  if (integrationProof && !inside(repo, target)) throw new Error('INT6 Cargo target must remain in the worktree.');
  if (integrationProof && process.env.NEYVIA_SLIM_FRONTEND_DIST) {
    const frontend = resolve(process.env.NEYVIA_SLIM_FRONTEND_DIST);
    if (!inside(repo, frontend) || !existsSync(join(frontend, 'index.html'))) throw new Error('INT6 requires an existing verified frontend in this worktree.');
    const configPath = join(repo, '.agent_control/INT6/slim-build.config.json');
    mkdirSync(dirname(configPath), { recursive: true });
    writeFileSync(configPath, JSON.stringify({ build: { beforeBuildCommand: null, frontendDist: relative(join(repo, 'src-tauri'), frontend).replaceAll('\\', '/') } }));
    args.push('--config', configPath);
  }
  const environment = { ...process.env, ...receipt.build.environment, CARGO_TARGET_DIR: target, ...(integrationProof ? { CARGO_NET_OFFLINE: 'true', NEYVIA_TOOL_AUTO_UPDATE: '0', NEYVIA_COORDINATOR_AUTOSTART: '0', FLUXIO_WATCHDOG_AUTOSTART: '0' } : {}) };
  delete environment.TAURI_CONFIG;
  const result = spawnSync(process.execPath, args, { cwd: repo, env: environment, stdio: 'inherit', windowsHide: true });
  if (result.status !== 0) throw new Error(`Slim installer build failed (${result.status}). Packs are preserved in ${receipt.output}.`);
  const bundle = join(target, debug ? 'debug' : 'release', 'bundle');
  receipt.build.executed = true;
  receipt.build.artifacts = walk(bundle).filter(file => /\.(exe|msi)$/.test(file) && statSync(join(bundle,file)).mtimeMs >= startedAt - 1000).map(file => {
    const bytes = readFileSync(join(bundle, file));
    return { path: relative(repo, join(bundle, file)).replaceAll('\\', '/'), size: bytes.length, sha256: hash(bytes) };
  });
  if (!receipt.build.artifacts.length) throw new Error('Tauri returned success without a Windows installer.');
  const formats = [...new Set(receipt.build.artifacts.map(file => file.path.endsWith('.msi') ? 'msi' : 'nsis'))];
  const guard = spawnSync(process.execPath, [join(repo,'scripts/check_installer_size.mjs'), '--slim', ...(debug ? ['--debug'] : []), '--bundles', formats.join(',')], {cwd:repo,env:environment,stdio:'inherit',windowsHide:true});
  if (guard.status !== 0) throw new Error('Slim installer failed its size/content gate.');
  const archive = join(receipt.output,'installers');
  mkdirSync(archive,{recursive:true});
  receipt.build.artifacts = receipt.build.artifacts.map(artifact=>{
    const destination = join(archive,artifact.sha256.slice(0,16)+'-'+basename(artifact.path));
    if (!existsSync(destination)) copyFileSync(join(repo,artifact.path),destination);
    return {...artifact,path:relative(repo,destination).replaceAll('\\','/'),buildPath:artifact.path};
  });
  writeFileSync(join(receipt.output, 'release-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  return receipt;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, all) => arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs, []));
    for (const name of ['output', 'python-runtime', 'secret-key', 'version']) if (!args[name] || args[name].startsWith('--')) throw new Error(`Required --${name}`);
    const receipt = prepareRelease({ output: args.output, pythonRuntime: args['python-runtime'], secretKey: args['secret-key'], version: args.version, baseUrl: args['base-url'], allowLocalProof: process.argv.includes('--allow-local-proof') });
    if (process.argv.includes('--build')) buildInstaller(receipt, { debug: process.argv.includes('--debug') });
    console.log(JSON.stringify(receipt, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
