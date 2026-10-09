// Independently inspect the actual guarded producer; never execute its installer.
import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve, relative, isAbsolute, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkSignedEnvelope } from './release-contracts.mjs';
import { inspectInstallerBudget } from './check_installer_size.mjs';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const path = resolve(process.argv[2]);
const scope = join(repo, '.agent_control/proofs/C8');
function inside(root, target) {
  const rel = relative(root, target);
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) throw Error('Actual producer path escapes C8 scratch');
  return target;
}
inside(scope, path);
const producer = JSON.parse(readFileSync(path));
if (producer.schema !== 'neyvia.c8e.slim-build/v1' || !producer.passed ||
    !producer.desktopGuard?.passed || producer.desktopGuard.coverage !== 'Started before any producer child; PID and creation-time attribution') {
  throw Error('Actual fully guarded successful producer required');
}
const task = inside(scope, resolve(producer.task));
inside(task, path);
if (resolve(producer.receiptPath) !== path) throw Error('Actual producer receipt identity differs');
const candidate = inside(task, resolve(producer.candidate));
const receiptPath = inside(task, resolve(producer.releaseReceiptPath));
const bytes = readFileSync(receiptPath), receipt = JSON.parse(bytes);
if (JSON.stringify(receipt) !== JSON.stringify(producer.releaseReceipt) ||
    !receipt.build?.executed || !receipt.build.artifacts?.length) {
  throw Error('Actual build, installer artifacts and unchanged installer budget required');
}
const hash = value => createHash('sha256').update(value).digest('hex');
const budgetBytes = readFileSync(join(repo, 'src-tauri/installer-budget.json'));
if (!budgetBytes.equals(readFileSync(join(candidate, 'src-tauri/installer-budget.json')))) throw Error('Installer budget changed in the build copy');
const budget = inspectInstallerBudget({ repository: candidate, slim: true,
  targetRoot: join(candidate, 'src-tauri/target'), bundles: [...new Set(receipt.build.artifacts.map(row => row.path.endsWith('.msi') ? 'msi' : 'nsis'))] });
if (!budget.ok) throw Error('Actual installer violates the unchanged size/content budget');
const artifacts = receipt.build.artifacts.map(row => {
  const target = inside(candidate, resolve(candidate, row.path));
  const data = readFileSync(target);
  const header = row.path.endsWith('.msi') ? data.subarray(0, 8).toString('hex') === 'd0cf11e0a1b11ae1' : data.subarray(0, 2).toString() === 'MZ';
  if (data.length !== row.size || hash(data) !== row.sha256 || !header) {
    throw Error('Built executable bytes differ from the actual producer');
  }
  return { path: target, size: data.length, sha256: hash(data), executableHeaderVerified: header };
});
const output = dirname(receiptPath);
const manifests = receipt.packs.map(row => inside(candidate, resolve(candidate, row.manifest)));
const localManifests = new Set(manifests);
for (const folder of readdirSync(join(output, 'external'))) manifests.push(join(output, 'external', folder, 'manifest.json'));
const packages = manifests.map(target => {
  inside(output, target);
  const data = readFileSync(target), manifest = JSON.parse(data), signature = readFileSync(target + '.minisig', 'utf8');
  const comment = `pack=${manifest.packId} version=${manifest.version}`;
  checkSignedEnvelope(data, comment, receipt.publicKey, signature);
  const damaged = Buffer.from(data); damaged[0] ^= 1;
  let badBytesRefused = false, badCommentRefused = false;
  try { checkSignedEnvelope(damaged, comment, receipt.publicKey, signature); } catch { badBytesRefused = true; }
  try { checkSignedEnvelope(data, comment + '-changed', receipt.publicKey, signature); } catch { badCommentRefused = true; }
  if (!badBytesRefused || !badCommentRefused) throw Error('Signed payload corruption was accepted');
  const payloads = localManifests.has(target) ? manifest.files.map(row => {
    const source = inside(join(dirname(target), 'files'), resolve(dirname(target), 'files', row.path));
    const content = readFileSync(source);
    if (content.length !== row.size || hash(content) !== row.sha256) throw Error('Signed pack payload differs');
    return { path: row.path, size: content.length, sha256: hash(content) };
  }) : [];
  return { packId: manifest.packId, manifestSha256: hash(data), signatureVerified: true,
    badBytesRefused, badCommentRefused, payloads, deliveryStatus: manifest.deliveryStatus,
    localPayloadsRequired: localManifests.has(target) };
});
console.log(JSON.stringify({ passed: true, receiptSha256: hash(bytes), artifacts, packages,
  budget, budgetSha256: hash(budgetBytes), boundary: 'Actual installer build and signed local packages; no installer launch, hosting or external activation' }));
