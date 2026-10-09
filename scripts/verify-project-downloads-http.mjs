import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const proof = path.join(root, 'proof/project-downloads-20260925');
const fixturePath = 'proof/project-downloads-20260925/download-fixture';
await mkdir(path.join(root, fixturePath, 'src'), { recursive: true });
const text = '# Download verification\nCreated on the PC; retrieved through Tailscale.\n';
const binary = Buffer.from([0, 1, 255, 77, 0, 24, 128]);
await writeFile(path.join(root, fixturePath, 'README.md'), text);
await writeFile(path.join(root, fixturePath, 'src/sample.bin'), binary);
const base = process.env.NEYVIA_DOWNLOAD_URL || 'https://asuspsdlb.example.invalid:8443';
const bootstrap = await fetch('http://127.0.0.1:47881/api/auth/local-session', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
});
assert.equal(bootstrap.status, 200);
const cookie = bootstrap.headers.get('set-cookie')?.split(';')[0];
assert.ok(cookie);
const headers = { Cookie: cookie, Origin: base };
const route = (suffix = '', file = fixturePath, workspaceId = 'workspace_primary') =>
  `${base}/api/project-files${suffix}?${new URLSearchParams({ workspaceId, path: file })}`;
const anonymous = await fetch(route());
assert.equal(anonymous.status, 401);
const listing = await fetch(route(), { headers }).then(r => r.json());
assert.equal(listing.ok, true);
assert.ok(listing.data.entries.some(file => file.name === 'README.md'));
const preview = await fetch(route('/preview', `${fixturePath}/README.md`), { headers }).then(r => r.json());
assert.equal(preview.data.content, text);
const single = await fetch(route('/download', `${fixturePath}/src/sample.bin`), { headers });
assert.equal(single.status, 200);
assert.match(single.headers.get('content-disposition'), /attachment;/);
const bytes = Buffer.from(await single.arrayBuffer());
assert.deepEqual(bytes, binary);
await writeFile(path.join(proof, 'downloaded-sample.bin'), bytes);
const zipResponse = await fetch(route('/archive'), { headers });
assert.equal(zipResponse.status, 200);
const zip = Buffer.from(await zipResponse.arrayBuffer());
assert.equal(zip.subarray(0, 2).toString(), 'PK');
assert.equal(Number(zipResponse.headers.get('content-length')), zip.length);
await writeFile(path.join(proof, 'downloaded-fixture.zip'), zip);
const badPaths = ['../outside.txt', '.agent_control/neyvia_web_admin.json', 'C:/Windows/win.ini'];
for (const file of badPaths) {
  const response = await fetch(route('/download', file), { headers });
  assert.ok([400, 403, 404].includes(response.status));
}
const unknown = await fetch(route('', '', 'unregistered'), { headers });
assert.equal(unknown.status, 404);
const foreign = await fetch(route(), { headers: { ...headers, Origin: 'https://unrelated.invalid' } });
assert.equal(foreign.status, 403);

// The user-selected real project is only read. Its files are neither executed
// nor changed by this transfer check.
const projectResponse = await fetch(route('/archive', '', 'workspace_936abed1'), { headers });
assert.equal(projectResponse.status, 200);
const projectZip = Buffer.from(await projectResponse.arrayBuffer());
await writeFile(path.join(proof, 'downloaded-RentSecurity.zip'), projectZip);
const status = await fetch(`${base}/api/desktop-controller/status`, { headers }).then(r => r.json());
const receipt = {
  at: new Date().toISOString(), base,
  anonymousDenied: true, traversalDenied: true, protectedFilesDenied: true,
  foreignOriginDenied: true, registeredWorkspaceListed: true, textPreviewExact: true,
  binaryDownloadSha256: createHash('sha256').update(bytes).digest('hex'),
  fixtureZipBytes: zip.length, actualProjectZipBytes: projectZip.length,
  actualProjectZipSha256: createHash('sha256').update(projectZip).digest('hex'),
  desktopOnline: status.data?.online === true, deviceName: status.data?.deviceName,
};
await writeFile(path.join(proof, 'http-downloads.json'), JSON.stringify(receipt, null, 2));
console.log(JSON.stringify(receipt, null, 2));
