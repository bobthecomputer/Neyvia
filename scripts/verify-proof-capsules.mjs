import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'); const python=resolveNeyviaPython(repo).python; const root=mkdtempSync(path.join(tmpdir(),'neyvia-proof-'));
try {
 const result=spawnSync(python,['-c',String.raw`
import hashlib,sys,json
from pathlib import Path
from grant_agent.proof_capsules import ProofCapsule,ProofCapsuleStore,ChangeSet
root=Path(sys.argv[1]); artifact=root/'journey.json'; artifact.write_bytes(b'actual journey receipt')
digest=hashlib.sha256(artifact.read_bytes()).hexdigest(); store=ProofCapsuleStore(root,'mission')
c=store.create(claim='Agent can upload a file in Preview',build={'revision':'abc123'},environment={'url':'http://localhost:3000','browser':'chrome'},starting_state={'route':'/preview','ready':True},journey=[{'step':'open Preview'},{'step':'upload file'}],actions=[{'intent':'choose upload input','observed':'file selected'}],artifacts=[{'path':'journey.json','sha256':digest,'kind':'receipt'}],result={'status':'passed'},reproduction={'command':'run preview and upload fixture'},limitations=['fixture uses local browser'])
checks={'initialUnproven':not c.verification,'artifactOnly':not c.prove(root)['claimProven'] and c.verification['semanticClaimStatus']=='artifact_integrity_only'}
checks['reload']=store.save(c).exists() and ProofCapsuleStore(root,'mission').load(c.capsule_id).content_hash==c.content_hash
tamper=False
try:
  ProofCapsule.from_dict({**c.to_dict(),'verification':{'claimProven':True},'contentHash':c.to_dict()['contentHash']})
  raise AssertionError('tampered verification accepted')
except ValueError as exc:
  tamper='hash mismatch' in str(exc)
checks['tamperRejected']=tamper
bad=ProofCapsule(claim='x',build={'revision':'a'},environment={'os':'win'},starting_state={},journey=[{'step':'x'}],actions=[{'action':'x'}],artifacts=[{'path':'journey.json','sha256':'0'*64}],result={'status':'passed'},reproduction={'command':'x'},verification={'claimProven':True})
checks['callerFlagRejected']=not bad.prove(root)['claimProven']
generated=root/'generated.js'; generated.write_text('generated from source',encoding='utf-8'); gd=hashlib.sha256(generated.read_bytes()).hexdigest()
change=ChangeSet('upload behavior',[{'path':'src/upload.ts','kind':'edited'}],[{'path':'generated.js','sha256':gd,'generatedFrom':['src/upload.ts']}],rollback_boundary={'previousRevision':'abc'})
checks['coherence']=change.verify_coherence(root)['sourceGeneratedCoherent'] and change.verification['rollbackBoundaryDeclared']
print(json.dumps(checks,separators=(',',':')))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
 assert.equal(result.status,0,result.stderr||result.stdout||result.error?.message); const checks=JSON.parse(result.stdout.trim()); for(const [name,value] of Object.entries(checks)) assert.equal(value,true,name); const evidence='PROOF_CAPSULES_VERIFIED: '+Object.keys(checks).join(', '); console.log(JSON.stringify({status:'verified',evidence,sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally { rmSync(root,{recursive:true,force:true}); }
