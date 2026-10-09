import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-release-environment-'));
try{
 const p=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'scripts'))
from resolve_release_python import resolve
from publish_nas_candidate import _managed_python_for_release,PublishError
b=Path(sys.argv[1]);release=b/'release';release.mkdir();(release/'uv.lock').write_text('frozen dependency contract')
digest=hashlib.sha256((release/'uv.lock').read_bytes()).hexdigest();e=b/'runtime/neyvia-environments'/digest
checks={}
try:resolve(b,release)
except RuntimeError:checks['unpreparedRefused']=True
(e/'bin').mkdir(parents=True);(e/'bin/python').write_text('fixture interpreter identity')
ready=e/'.neyvia-environment.json';ready.write_text(json.dumps({'status':'ready','lockSha256':digest}))
checks['selectsMatchingEnvironment']=resolve(b,release)==e/'bin/python'
checks['oldReleaseKeepsBaseEnvironment']=_managed_python_for_release(b,release)==b/'.venv/bin/python'
(release/'scripts').mkdir();(release/'scripts/resolve_release_python.py').write_text('release environment contract')
checks['publisherSelectsMatchingEnvironment']=_managed_python_for_release(b,release)==e/'bin/python'
ready.write_text(json.dumps({'status':'ready','lockSha256':'other'}))
try:resolve(b,release)
except RuntimeError:checks['wrongLockRefused']=True
ready.write_text(json.dumps({'status':'preparing','lockSha256':digest}))
try:resolve(b,release)
except RuntimeError:checks['unfinishedRefused']=True
try:_managed_python_for_release(b,release)
except PublishError:checks['publisherRefusesUnpreparedRelease']=True
print(json.dumps(checks))
`,root],{encoding:'utf8',timeout:15000});
 assert.equal(p.status,0,p.stderr);const checks=JSON.parse(p.stdout);for(const [k,v] of Object.entries(checks))assert.equal(v,true,k);
 console.log(JSON.stringify({status:'verified',checks,boundary:'Dependency identity/readiness selection; actual NAS package imports are verified separately.'}));
}finally{rmSync(root,{recursive:true,force:true});}
