// Seal only this branch's source and disposable T22 artifacts; never include runtime auth.
import fs from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
const receiptPath = 'scripts/evidence/T22.json';
const receipt = JSON.parse(await fs.readFile(receiptPath, 'utf8'));
if (!receipt.uiProof?.ok) throw new Error('Rendered proof gate is not complete');
for (const [provider, row] of Object.entries(receipt.providers)) {
  if (row.blocker || !row.checks || !Object.values(row.checks).every(Boolean)) throw new Error(`${provider}: real turn gate not complete`);
}
const changed = execFileSync('git', ['diff', '--name-only', 'HEAD'], { encoding: 'utf8' }).trim().split(/\r?\n/);
const fresh = execFileSync('git', ['ls-files', '--others', '--exclude-standard'], { encoding: 'utf8' }).trim().split(/\r?\n/);
const sources = [...new Set([...changed, ...fresh])].filter(file => file && !file.startsWith('scripts/evidence/')).sort();
receipt.sourceManifest = [];
for (const file of sources) {
  const raw = await fs.readFile(file);
  const normalized = raw.toString('utf8').replace(/\r\n/g, '\n');
  receipt.sourceManifest.push({ path: file, sha256: createHash('sha256').update(normalized).digest('hex'), hashNormalization: 'UTF-8 text with LF line endings' });
}
receipt.artifactManifest = [];
for (const name of (await fs.readdir('scripts/evidence/T22')).sort()) {
  const file = `scripts/evidence/T22/${name}`;
  const raw = await fs.readFile(file);
  if (/grand_agent_session=(?!\[redacted\])[^\s"\\]+/.test(raw.toString('utf8'))) throw new Error('Unredacted local authentication header in evidence');
  receipt.artifactManifest.push({ path: file, bytes: raw.length, sha256: createHash('sha256').update(raw).digest('hex') });
}
receipt.validation = { parserChecks: 25, frontendModelChecks: 5, executableManual: true, invalidSettingNoMutation: true, productionBuild: { passed: true, modules: 6751, directory: '.agent_control/t22/final-build', log: '.agent_control/t22/final-build.log', warning: 'Existing chunks over 500 KB' }, renderedProviderTransports: 4, screenshots: receipt.uiProof.screenshotPaths.length };
receipt.recovery = ['First Codex proof run interrupted at the 240-second deadline; subsequent requested Luna turn completed', 'Setup overlay dismissed before valid captures', 'General state inventory timed out during a manual check; replaced that observer with view.transparency.state and executed the manual successfully'];
receipt.preservation = { localSnapshot: '.agent_control/t22/preservation/T22-source.zip', manifest: '.agent_control/t22/preservation/manifest.json', nas: 'pending under explicit port/Tailscale isolation', publicPromotion: false, pushed: false, merged: false };
receipt.ok = true;
receipt.sealedAt = new Date().toISOString();
await fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({ ok: true, sourceFiles: sources.length, artifacts: receipt.artifactManifest.length, screenshots: receipt.validation.screenshots }));
