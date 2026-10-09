import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=resolveNeyviaPython(repo).python;
const root=mkdtempSync(path.join(tmpdir(),'neyvia-experience-learning-'));
try {
 const result=spawnSync(python,['-c',String.raw`
import json,sys,hashlib
from grant_agent.experience_learning import ExperienceStore
s=ExperienceStore(sys.argv[1],'conversation-fixture')
c=s.compare(experience_id='exp-1',user_version='user-v1',provisional_version='candidate-v1',preference='undecided',provenance={'turnId':'turn-1'},observations={'latencyMs':120})
t=s.trace(trace_id='trace-1',event_kind='timing',payload={'durationMs':120},references=[c['recordId']],provenance={'turnId':'turn-1'})
i=s.investigate(hypothesis='Candidate reduces repeated setup',experiment={'type':'matched-replay'},references=[c['recordId'],t['recordId']])
candidate=s.candidate(skill_id='skill-fixture',version='v2',changes={'reason':'reduce setup'},evidence_ids=[])
from pathlib import Path
from grant_agent.verified_operations import VerifiedOperationStore
artifact=Path(sys.argv[1])/'candidate.txt'; artifact.write_text('evaluated candidate bytes')
digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
VerifiedOperationStore(sys.argv[1],'conversation-fixture').execute('eval-receipt-1','candidate.evaluate',authority=True,effect=lambda:{'ok':True},verify=lambda:{'verified':artifact.read_text()=='evaluated candidate bytes','candidateId':candidate['candidateId'],'artifactHash':digest})
fabricated=False
try: s.evaluate_candidate(candidate_id=candidate['candidateId'],artifact_hash='a'*64,receipt_id='missing',verdict='pass',provenance={'source':'fixture'})
except ValueError: fabricated=True
e=s.evaluate_candidate(candidate_id=candidate['candidateId'],artifact_hash=digest,receipt_id='eval-receipt-1',verdict='pass',provenance={'artifactPath':str(artifact)})
candidate['evidenceIds']=[c['recordId'],t['recordId'],e['recordId']]
candidate['recordHash']=hashlib.sha256(json.dumps({k:v for k,v in candidate.items() if k!='recordHash'},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
from grant_agent.durability import atomic_write_json
atomic_write_json(s.base/f"{candidate['recordId']}.json",candidate)
refused=False
try: s.promote(candidate['candidateId'],authority={'trusted':True,'authorityKind':'model','authorityId':'model'},evidence_ids=candidate['evidenceIds'])
except (PermissionError,ValueError): refused=True
promoted=s.promote(candidate['candidateId'],authority={'trusted':True,'authorityKind':'operator','authorityId':'operator-1'},evidence_ids=candidate['evidenceIds'])
reloaded=ExperienceStore(sys.argv[1],'conversation-fixture')
print(json.dumps({'fabricated':fabricated,'refused':refused,'promotion':promoted,'snapshot':reloaded.snapshot()}))
`,root],{cwd:repo,env:{...process.env,PYTHONPATH:path.join(repo,'src')},encoding:'utf8',timeout:30000});
 assert.equal(result.status,0,result.stderr||result.stdout||result.error?.message);
 const out=JSON.parse(result.stdout.trim());
 assert.equal(out.refused,true); assert.equal(out.fabricated,true);
 assert.equal(out.promotion.status,'promoted');
 assert.equal(out.snapshot.recordCount,6);
 assert.equal(out.snapshot.records.some(row=>row.kind==='comparison'&&row.preference==='undecided'),true);
 assert.equal(out.snapshot.records.some(row=>row.kind==='trace'&&row.eventKind==='timing'),true);
 assert.equal(out.snapshot.records.some(row=>row.kind==='promotion'),true);
 console.log('EXPERIENCE_LEARNING_VERIFIED: durable comparison/trace/investigation lineage, reload, malicious promotion refusal, and trusted evidence-gated promotion');
} finally { rmSync(root,{recursive:true,force:true}); }
