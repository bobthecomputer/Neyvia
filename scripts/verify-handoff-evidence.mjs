import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python;
const root=mkdtempSync(path.join(tmpdir(),'neyvia-handoff-evidence-'));
try {
 const result=spawnSync(python,['-c',String.raw`
import hashlib,json,sys
from pathlib import Path
from grant_agent.efficient_workflow import verification_result,continuation_checkpoint,continuation_instructions,compact_dependency_context
root=Path(sys.argv[1]); artifact=root/'measurement.json';artifact.write_text('{"observed":42}')
digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
def verify(evidence):
    return verification_result(json.dumps({'verdict':'pass','summary':'Model claim','evidence':evidence}),root=root)
assert verify(['I checked it'])['status']=='unverified'
assert verify([])['status']=='unverified'
valid={'path':'measurement.json','sha256':digest}
for verdict,status in [('fail','failed'),('unverified','unverified')]:
    handback=json.dumps({'verdict':verdict,'summary':'Existing observations','evidence':[valid]})
    assert verification_result(handback,root=root)['status']==status
    fence=chr(96)*3
    wrapped='Verification receipt written.\n'+fence+'json\n'+handback+'\n'+fence+'\nFurther explanation.'
    rejected=verification_result(wrapped,root=root)
    assert rejected['status']=='unverified'
    assert rejected['verification']['errorCode']=='invalid_verification_handback'
    assert 'Reuse existing observations' in rejected['verification']['summary']
    retry=continuation_checkpoint({'nodeId':'verifier','lifecycleStage':'failed',
        'progress':{'invocationId':'malformed-receipt'},'resultSummary':{'result':rejected}})
    assert 'Reuse existing observations' in retry['latestFailure']['blockers'][0]
    assert retry['latestFailure']['sourceInvocationId']=='malformed-receipt'
assert verification_result(json.dumps({'verdict':'unknown'}),root=root)['status']=='unverified'
checked=verify([valid,'A measurement was recorded; quality is still a model judgment.'])
assert checked['status']=='completed'
assert checked['verification']['artifactChecks'][0]['status']=='matched'
assert 'semantic claims remain model-reported' in checked['verification']['evidenceStatus']
for bad in ({'path':'missing.json','sha256':digest}, {'path':'measurement.json','sha256':'bad'},
            {'path':str(artifact),'sha256':digest}, {'path':'../outside.json','sha256':digest},
            {'path':'measurement.json','sha256':'0'*64}, {}, 12):
    assert verify([valid,bad])['status']=='unverified',bad
assert verify([valid]*33)['status']=='unverified'
artifact.write_text('{"observed":43}')
assert verify([valid])['verification']['artifactChecks'][0]['status']=='mismatch'
checkpoint=continuation_checkpoint({'nodeId':'worker','lifecycleStage':'completed','progress':{'invocationId':'observed-before-change'},
    'resultSummary':{'result':{**checked,'reply':json.dumps({'verdict':'pass','evidence':[valid],'completed':['measurement artifact']})}}})
assert checkpoint['artifactVerification']['checks'][0]['sha256']==digest
assert 'prior harness observation' in checkpoint['artifactVerification']['freshness']
resumed=continuation_instructions({'objective':'Continue remaining quality checks','progress':{'continuationCheckpoint':checkpoint}},[])
assert digest in resumed['objective'] and 'recheck artifacts' in resumed['objective']
dependency=json.loads(compact_dependency_context({'worker':{'result':checked}})[0]['content'])
assert dependency['verification']['artifactChecks'][0]['sha256']==digest
assert 'semantic claims remain model-reported' in dependency['verification']['evidenceStatus']
print('HANDOFF_EVIDENCE_VERIFIED: narrative-only rejection, actual hashes, mismatch/missing/unsafe/malformed evidence, bounded checks, and retry provenance')
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
 assert.equal(result.status,0,result.stderr||result.stdout||result.error?.message);
 console.log(result.stdout.trim());
} finally {rmSync(root,{recursive:true,force:true});}
