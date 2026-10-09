import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile, symlink } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temp = await mkdtemp(path.join(os.tmpdir(), 'neyvia-project-files-'));
const state = path.join(temp, 'state');
const project = path.join(temp, 'project');
const outside = path.join(temp, 'outside.txt');
const outsideDir = path.join(temp, 'outside-dir');
const binary = Buffer.from([0, 1, 2, 255, 7]);
const text = '# Project\nA useful artifact.\n';
await mkdir(path.join(state, '.agent_control'), { recursive: true });
await mkdir(project);
await mkdir(path.join(project, 'src'));
await mkdir(path.join(project, 'node_modules', 'pkg'), { recursive: true });
await mkdir(path.join(project, '.git', 'objects'), { recursive: true });
await mkdir(path.join(project, 'target', 'debug'), { recursive: true });
await mkdir(path.join(project, '.cache', 'build'), { recursive: true });
await writeFile(path.join(project, 'README.md'), text);
await writeFile(path.join(project, 'bundle.bin'), binary);
await writeFile(path.join(project, '.env'), 'SHOULD_NOT_EXPORT=secret\n');
await writeFile(path.join(project, '.env.example'), 'PUBLIC_EXAMPLE=value\n');
await writeFile(path.join(project, 'node_modules', 'pkg', 'index.js'), 'cache');
await writeFile(path.join(project, '.git', 'objects', 'secret'), 'metadata');
await writeFile(path.join(project, 'target', 'debug', 'cache.bin'), 'rust-build-cache');
await writeFile(path.join(project, '.cache', 'build', 'cache.bin'), 'tool-cache');
await writeFile(path.join(project, 'src', 'app.js'), 'export const app = true;\n');
await writeFile(path.join(project, 'NEYVIA_EXPORT.json'), '{"userFile":true}\n');
await writeFile(outside, 'outside');
await mkdir(outsideDir);
await writeFile(path.join(outsideDir, 'secret.txt'), 'outside folder data');
let fileSymlinkAvailable = false;
let directoryLinkAvailable = false;
try { await symlink(outside, path.join(project, 'escape.txt')); fileSymlinkAvailable = true; } catch { /* Windows may not grant fixture symlink privileges. */ }
try { await symlink(outsideDir, path.join(project, 'linked-dir'), 'junction'); directoryLinkAvailable = true; } catch { /* Windows may not grant fixture symlink privileges. */ }
await writeFile(path.join(state, '.agent_control', 'workspaces.json'), JSON.stringify([
  { workspace_id: 'project-a', name: 'Project A', root_path: project },
  { workspace_id: 'disabled-project', name: 'Disabled Project', root_path: project, enabled: false },
]));

const py = String.raw`
import hashlib, json, os, sys, zipfile
from datetime import datetime
from pathlib import Path
from grant_agent.project_files import (
    ProjectFilesError, create_project_archive, list_project_entries,
    open_project_download, preview_project_file,
)
root, project, outside = map(Path, sys.argv[1:4])
file_symlink_available = sys.argv[4] == 'true'
directory_link_available = sys.argv[5] == 'true'
results = {}
page = list_project_entries(root, 'project-a', limit=2)
results['listing'] = page
assert page['workspace'] == {'id': 'project-a', 'name': 'Project A'}
assert 'root' not in page and 'absoluteRoot' not in page
assert page['hasMore'] and page['nextOffset'] == 2
all_rows = list_project_entries(root, 'project-a', limit=250)
assert all_rows['total'] >= 4
assert not any(x['name'] in {'.env', '.git', 'node_modules'} for x in all_rows['entries'])
preview = preview_project_file(root, 'project-a', 'README.md')
assert preview['content'].startswith('# Project') and preview['truncated'] is False
long_preview = preview_project_file(root, 'project-a', 'README.md', max_bytes=8)
assert long_preview['truncated'] and len(long_preview['content'].encode('utf-8')) <= 8
try:
    preview_project_file(root, 'project-a', '.env')
    raise AssertionError('secret preview unexpectedly allowed')
except ProjectFilesError as exc:
    assert exc.status_code == 403
try:
    list_project_entries(root, 'not-registered')
    raise AssertionError('unregistered workspace unexpectedly allowed')
except ProjectFilesError as exc:
    assert exc.status_code == 404
try:
    list_project_entries(root, 'disabled-project')
    raise AssertionError('disabled workspace unexpectedly allowed')
except ProjectFilesError as exc:
    assert exc.status_code == 404
try:
    preview_project_file(root, 'project-a', '../outside.txt')
    raise AssertionError('path traversal unexpectedly allowed')
except ProjectFilesError:
    pass
if file_symlink_available:
    for operation in (lambda: preview_project_file(root, 'project-a', 'escape.txt'), lambda: open_project_download(root, 'project-a', 'escape.txt')):
        try:
            operation()
            raise AssertionError('direct symlink access unexpectedly allowed')
        except ProjectFilesError as exc:
            assert exc.status_code == 403
if directory_link_available:
    try:
        preview_project_file(root, 'project-a', 'linked-dir/secret.txt')
        raise AssertionError('nested junction access unexpectedly allowed')
    except ProjectFilesError as exc:
        assert exc.status_code == 403
download = open_project_download(root, 'project-a', 'bundle.bin')
try:
    data = download.file.read()
    results['download'] = {'filename': download.filename, 'size': download.size, 'sha256': hashlib.sha256(data).hexdigest()}
finally:
    download.close()
try:
    preview_project_file(root, 'project-a', 'bundle.bin')
    raise AssertionError('binary preview unexpectedly allowed')
except ProjectFilesError:
    pass
archive = create_project_archive(root, 'project-a')
try:
    with zipfile.ZipFile(archive.path) as z:
        names = z.namelist()
        assert 'README.md' in names and 'src/app.js' in names and '.env.example' in names and 'NEYVIA_EXPORT.json' in names
        manifest_path = json.loads(z.read(next(name for name in names if name.startswith('NEYVIA_EXPORT.manifest-'))))['policy']['manifestPath']
        assert manifest_path != 'NEYVIA_EXPORT.json'
        assert '.env' not in names and not any(x.startswith('.git/') or x.startswith('node_modules/') for x in names)
        assert not any(x.startswith('target/') or x.startswith('.cache/') for x in names)
        manifest = json.loads(z.read(manifest_path))
        assert manifest['skipped']['credential_or_secret'] >= 1
        assert manifest['skipped']['protected_metadata'] >= 1
        assert manifest['skipped']['generated_dependency_or_cache'] >= 3
        if file_symlink_available or directory_link_available:
            assert manifest['skipped']['symlink_or_escape'] >= 1
        assert manifest['policy']['excluded'] and manifest['filesIncluded'] == len(names) - 1
        for item in manifest['files']:
            assert hashlib.sha256(z.read(item['path'])).hexdigest() == item['sha256']
        source_stat = (project / 'README.md').stat()
        # ZIP's DOS timestamp stores seconds at two-second precision.
        archived_mtime = datetime(*z.getinfo('README.md').date_time).timestamp()
        assert 0 <= source_stat.st_mtime - archived_mtime < 2
        results['archive'] = {'filename': archive.filename, 'bytes': archive.size, 'manifest': manifest}
finally:
    archive.cleanup()

# Deterministically mutate a same-size source file while it is being read. The
# archive must fail with 409 and delete its temporary partial ZIP.
readme = project / 'README.md'
original_bytes = readme.read_bytes()
original_stat = readme.stat()
path_open = Path.open
class MutatingReader:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.mutated = False
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)
    def fileno(self):
        return self.wrapped.fileno()
    def read(self, size=-1):
        data = self.wrapped.read(size)
        if not self.mutated:
            self.mutated = True
            with open(readme, 'wb') as changed:
                changed.write(b'X' * len(original_bytes))
        return data
def intercept_open(self, mode='r', *args, **kwargs):
    opened = path_open(self, mode, *args, **kwargs)
    if self == readme and mode == 'rb':
        return MutatingReader(opened)
    return opened
Path.open = intercept_open
try:
    try:
        create_project_archive(root, 'project-a')
        raise AssertionError('same-size concurrent mutation unexpectedly produced an archive')
    except ProjectFilesError as exc:
        assert exc.status_code == 409
finally:
    Path.open = path_open
    readme.write_bytes(original_bytes)
    os.utime(readme, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
print(json.dumps(results))
`;

try {
  const run = spawnSync('python', ['-c', py, state, project, outside, String(fileSymlinkAvailable), String(directoryLinkAvailable)], {
    cwd: repo,
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: [path.join(repo, 'src'), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
    timeout: 30_000,
  });
  if (run.status !== 0) throw new Error(run.stderr || run.stdout || `python exited ${run.status}`);
  const results = JSON.parse(run.stdout.trim());
  assert.equal(results.download.sha256, createHash('sha256').update(binary).digest('hex'));
  assert.equal(results.download.size, binary.length);
  assert.ok(results.archive.manifest.files.some(file => file.path === 'README.md'));
  console.log('Project file export integration: PASS');
  console.log('Registered workspace listing and pagination: PASS');
  console.log('Bounded text preview and binary preview refusal: PASS');
  console.log('Single-file binary download hash: PASS');
  console.log('Traversal and unregistered workspace rejection: PASS');
  console.log('Disabled workspace and direct symlink rejection: PASS');
  console.log('ZIP collision handling, target/cache exclusion, policy and hashes: PASS');
  console.log('ZIP mtime preservation and concurrent same-size mutation rejection: PASS');
} finally {
  await rm(temp, { recursive: true, force: true });
}
