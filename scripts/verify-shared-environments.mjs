import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs'; import {tmpdir} from 'node:os'; import path from 'node:path'; import {fileURLToPath} from 'node:url'; import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-env-'));
try { const r=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
from grant_agent.shared_environments import SharedEnvironmentStore
root=Path(sys.argv[1]); lock=root/'requirements.lock'
import zipfile,hashlib
wheel=root/'fixture_demo-0.0.1-py3-none-any.whl'
with zipfile.ZipFile(wheel,'w') as z:
 z.writestr('fixture_demo/__init__.py','VALUE = 42\n')
 z.writestr('fixture_demo-0.0.1.dist-info/METADATA','Metadata-Version: 2.1\nName: fixture-demo\nVersion: 0.0.1\n')
 z.writestr('fixture_demo-0.0.1.dist-info/WHEEL','Wheel-Version: 1.0\nGenerator: Neyvia disposable proof\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
 z.writestr('fixture_demo-0.0.1.dist-info/RECORD','')
lock.write_text('fixture-demo @ '+wheel.as_uri()+' --hash=sha256:'+hashlib.sha256(wheel.read_bytes()).hexdigest()+'\n')
s=SharedEnvironmentStore(root); a=s.create('fixture',lock_path=lock,interpreter=sys.executable); b=s.create('fixture',lock_path=lock,interpreter=sys.executable); run=s.run(a,['-c','import fixture_demo; print(fixture_demo.VALUE)']); lock.write_bytes(b'not a valid hash-pinned requirement!!!'); invalid=False; forged=False
try: s.create('fixture',lock_path=lock,interpreter=sys.executable)
except (ValueError,RuntimeError): invalid=True
try: s.run({**a,'python':sys.executable},['-c','print(0)'])
except ValueError: forged=True
print(json.dumps({'created':a['ready'] and not a['reused'],'reused':b['reused'],'run':run['exitCode']==0 and run['stdout'].strip()=='42','invalidLockRejected':invalid,'forgedManifestRejected':forged,'receiptPersisted':Path(run['receiptPath']).is_file()}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:180000}); assert.equal(r.status,0,r.stderr||r.stdout); const p=JSON.parse(r.stdout.trim()); assert.equal(p.created,true); assert.equal(p.reused,true); assert.equal(p.run,true); assert.equal(p.invalidLockRejected,true); assert.equal(p.forgedManifestRejected,true); assert.equal(p.receiptPersisted,true); console.log(JSON.stringify({status:'verified',proof:p})); } finally {rmSync(root,{recursive:true,force:true});}
