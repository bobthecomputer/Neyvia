import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const root = await mkdtemp(path.join(tmpdir(), 'neyvia-preview-search-'));
const server = createServer((req, res) => {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.end('<html><title>Inspection fixture</title><body><p>alpha ALPHA a.b aXb</p>' +
    '<script>hiddenScript</script><p>' + 'x'.repeat(100100) + '</p></body></html>');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try {
  const url = `http://127.0.0.1:${server.address().port}/`;
  const python = spawn(resolveNeyviaPython(process.cwd()).python, ['-c',
    'import json,sys\nfrom grant_agent.native_tools import NativeToolRegistry\nr=NativeToolRegistry(sys.argv[1])\nfor line in sys.stdin:\n print(json.dumps(r.call("preview.inspect",json.loads(line))),flush=True)', root],
    { env: { ...process.env, PYTHONPATH: path.resolve('src') } });
  let output = '', errors = '';
  python.stdout.on('data', data => { output += data; });
  python.stderr.on('data', data => { errors += data; });
  const cases = [{url,query:'alpha',limit:1}, {url,query:'alpha',offset:6},
    {url,query:'a.b'}, {url,query:'hiddenScript'}, {url,query:'absent'}, {url:'file:///secret'},
    {url,mode:'bytes'}, {url,mode:'bytes',offset:512}, {url,mode:'bytes',offset:100000}, {url}];
  python.stdin.end(cases.map(value => JSON.stringify(value)).join('\n') + '\n');
  const code = await new Promise(resolve => python.on('close', resolve));
  assert.equal(code, 0, errors);
  const rows = output.trim().split('\n').map(line => JSON.parse(line));
  assert(rows.slice(0,5).every(row => row.ok));
  assert.equal(rows[0].result.matches.length, 1);
  assert(rows[0].result.nextOffset > rows[0].result.matches[0].offset);
  assert.equal(rows[2].result.matches.length, 1, 'literal search must not interpret regex');
  assert.equal(rows[3].result.matches.length, 0, 'scripts must not enter readable text');
  assert.equal(rows[4].result.matches.length, 0);
  assert.equal(rows[0].result.indexTruncated, true);
  assert.equal(rows[0].result.contentSha256, rows[2].result.contentSha256);
  assert.equal(rows[5].ok, false, 'non-HTTP targets must be rejected');
  assert(rows.slice(6).every(row => row.ok));
  assert(rows[6].result.text.startsWith('00000000  3c 68 74 6d 6c'));
  assert.equal(rows[6].result.nextOffset, 512);
  assert(rows[7].result.text.startsWith('00000200'));
  assert.equal(rows[6].result.contentSha256, rows[7].result.contentSha256);
  assert.equal(rows[8].result.nextOffset, null);
  assert.equal(rows[8].result.text, '');
  assert.equal(rows[9].result.nextOffset, 4000);
  console.log('PASS: preview search, literal matching, pagination, script exclusion, bounded index, content identity, invalid target');
} finally {
  server.close();
  await rm(root, { recursive: true, force: true });
}
