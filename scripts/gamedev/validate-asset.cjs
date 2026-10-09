// The official Khronos validator plus confined, bounded resource resolution.
const fs = require('node:fs');
const path = require('node:path');
const validator = require('./vendor/gltf-validator');
const [assetName, workspace] = process.argv.slice(2);
const root = fs.realpathSync(workspace), asset = fs.realpathSync(assetName);
const inside = p => p === root || p.startsWith(root + path.sep);
if (!inside(asset)) throw Error('Asset outside workspace');
const maxBytes = 32 * 1024 * 1024;
let totalBytes = 0;
const bounded = p => {
  const real = fs.realpathSync(p);
  if (!inside(real)) throw Error('Resource outside workspace');
  const size = fs.statSync(real).size;
  totalBytes += size;
  if (totalBytes > maxBytes) throw Error('Resources exceed 32 MB');
  return fs.readFileSync(real);
};
validator.validateBytes(new Uint8Array(bounded(asset)), {
  uri: path.basename(asset), maxIssues: 100,
  externalResourceFunction: async uri => {
    const decoded = decodeURIComponent(uri);
    if (/^[a-z][a-z0-9+.-]*:/i.test(decoded) || path.isAbsolute(decoded)) throw Error('External URLs/absolute resources are forbidden');
    const resolved = path.resolve(path.dirname(asset), decoded);
    if (!inside(resolved)) throw Error('Resource traversal');
    return new Uint8Array(bounded(resolved));
  },
}).then(report => {
  const messages = report.issues.messages || [];
  process.stdout.write(JSON.stringify({valid: report.issues.numErrors === 0,
    validator: 'Khronos glTF Validator', validatorVersion: validator.version(),
    errors: messages.filter(m => m.severity === 0), warnings: messages.filter(m => m.severity === 1),
    summary: report.info || {}, issueCounts: report.issues}));
}).catch(error => {process.stderr.write(String(error)); process.exitCode = 1;});
