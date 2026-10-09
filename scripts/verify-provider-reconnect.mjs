import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const run=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,tempfile
from pathlib import Path
import grant_agent.web_backend as web
web._openai_codex_oauth_status=lambda:{'authenticated':True}
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 normal=web._start_openclaw_codex_oauth({},root,public_url='https://example.invalid')
 explicit=web._start_openclaw_codex_oauth({},root,public_url='https://example.invalid',force_reconnect=True)
 print(json.dumps({'normalKeepsConnection':normal['authenticated'] is True,'explicitStartsFreshFlow':explicit['status']=='manual_required' and bool(explicit['authUrl']),'credentialsUnchanged':list(root.iterdir())==[]}))
`],{encoding:'utf8',timeout:30000});
assert.equal(run.status,0,run.stderr);const checks=JSON.parse(run.stdout);for(const [k,v] of Object.entries(checks))assert.equal(v,true,k);
console.log(JSON.stringify({status:'verified',checks,liveOAuth:false}));
