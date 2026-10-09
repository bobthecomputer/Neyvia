import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const scratch = mkdtempSync(path.join(tmpdir(), 'neyvia-codex-skill-access-'));
const fixtureHome = path.join(scratch, 'codex-home');
const workspace = path.join(scratch, 'workspace');
const proc = spawnSync(python, ['-c', String.raw`
import hashlib, json, os, subprocess, sys
from pathlib import Path
from grant_agent.codex_skill_access import CodexSkillAccess

home, workspace, scratch = map(Path, sys.argv[1:4])
(home/'skills'/'demo').mkdir(parents=True)
(home/'skills'/'demo'/'SKILL.md').write_text('---\nname: Demo\ndescription: fixture skill\n---\nFollow the fixture instructions.\n', encoding='utf-8')
(home/'skills'/'demo'/'guide.md').write_text('Referenced guide.\n', encoding='utf-8')
(home/'prompts').mkdir(parents=True)
(home/'prompts'/'compose.md').write_text('Reusable fixture prompt.\n', encoding='utf-8')
(home/'config.toml').write_text('[plugins."fixture@market"]\nenabled = false\n', encoding='utf-8')
plugin = home/'plugins'/'cache'/'market'/'fixture'/'1.0.0'
(plugin/'.codex-plugin').mkdir(parents=True)
(plugin/'skills'/'plugdemo').mkdir(parents=True)
(plugin/'.codex-plugin'/'plugin.json').write_text(json.dumps({'name':'fixture','skills':'./skills/'}), encoding='utf-8')
(plugin/'skills'/'plugdemo'/'SKILL.md').write_text('---\nname: Plugin Demo\ndescription: disabled fixture\n---\nDisabled instructions.\n', encoding='utf-8')
(workspace/'.codex'/'skills'/'workdemo').mkdir(parents=True)
(workspace/'.codex'/'skills'/'workdemo'/'SKILL.md').write_text('---\nname: Workspace Demo\n---\nWorkspace instructions.\n', encoding='utf-8')
(scratch/'external').mkdir()
(scratch/'external'/'outside.md').write_text('outside', encoding='utf-8')
link_created = False
try:
    junction = subprocess.run(['cmd', '/c', 'mklink', '/J', str(home/'skills'/'demo'/'escape-dir'), str(scratch/'external')], capture_output=True)
    link_created = junction.returncode == 0
except (OSError, NotImplementedError):
    pass

access = CodexSkillAccess(home, workspace)
catalog = access.discover()
ids = {row['skillId']: row for row in catalog['skills']}
personal = access.read('codex:personal:demo')
assert personal['text'].replace(chr(13), '').endswith('Follow the fixture instructions.'+chr(10))
assert personal['sha256'] == ids['codex:personal:demo']['instructionSha256'], (personal['sha256'], ids['codex:personal:demo']['instructionSha256'])
assert access.read('codex:personal:demo', 'guide.md')['text'].replace(chr(13), '') == 'Referenced guide.'+chr(10)
assert 'codex:workspace:workdemo' in ids
assert ids['codex:plugin:fixture@market:plugdemo']['enabled'] is False
blocked_disabled = False
try:
    access.read('codex:plugin:fixture@market:plugdemo')
except PermissionError as exc:
    blocked_disabled = str(exc) == 'plugin_disabled'
assert blocked_disabled
blocked_traversal = False
try:
    access.read('codex:personal:demo', '../outside.md')
except ValueError:
    blocked_traversal = True
assert blocked_traversal
blocked_symlink = None
if link_created:
    try:
        access.read('codex:personal:demo', 'escape-dir/outside.md')
    except ValueError as exc:
        blocked_symlink = str(exc)
    assert blocked_symlink in {'symlink_not_allowed', 'path_outside_allowed_root'}
assert any(row['promptId'] == 'codex:prompt:compose' for row in catalog['prompts'])
prompt = access.read_prompt('codex:prompt:compose')
assert prompt['text'].replace(chr(13), '') == 'Reusable fixture prompt.'+chr(10)
print(json.dumps({'fixture':'passed','personalHash':personal['sha256'],'disabledPluginBlocked':blocked_disabled,
                  'traversalBlocked':blocked_traversal,'symlinkCreated':link_created,
                  'symlinkBlocked':blocked_symlink,'workspaceSkillDiscovered':True,'promptRead':True}))
`, fixtureHome, workspace, scratch], {
  cwd: repo,
  env: {...process.env, PYTHONPATH: path.join(repo, 'src')},
  encoding: 'utf8',
  timeout: 90000,
});

try {
  assert.equal(proc.status, 0, proc.stdout + proc.stderr);
  const fixture = JSON.parse(proc.stdout.trim());
  assert.equal(fixture.fixture, 'passed');
  assert.equal(fixture.disabledPluginBlocked, true);
  assert.equal(fixture.traversalBlocked, true);
  assert.ok(['symlink_not_allowed', 'path_outside_allowed_root'].includes(fixture.symlinkBlocked));

  const real = spawnSync(python, ['-c', String.raw`
import json, sys
from grant_agent.codex_skill_access import CodexSkillAccess
access = CodexSkillAccess()
catalog = access.discover(include_disabled=False)
skill_id = 'codex:personal:codex-in-app-browser'
row = next((item for item in catalog['skills'] if item['skillId'] == skill_id), None)
if row is None:
    raise SystemExit('known installed skill missing: '+skill_id)
result = access.read(skill_id)
print(json.dumps({'skillId':skill_id,'name':row['name'],'sha256':result['sha256'],'sizeBytes':result['sizeBytes']}))
`], {
    cwd: repo,
    env: {...process.env, PYTHONPATH: path.join(repo, 'src')},
    encoding: 'utf8',
    timeout: 90000,
  });
  assert.equal(real.status, 0, real.stderr || real.stdout);
  const installed = JSON.parse(real.stdout.trim());
  assert.equal(installed.skillId, 'codex:personal:codex-in-app-browser');
  assert.match(installed.sha256, /^[a-f0-9]{64}$/);
  console.log(JSON.stringify({status: 'verified', fixture, realInstalledSkill: installed}));
} finally {
  rmSync(scratch, {recursive: true, force: true});
}
