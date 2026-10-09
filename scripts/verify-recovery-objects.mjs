import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = resolveNeyviaPython(repo).python;
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-recovery-objects-'));
try {
  const result = spawnSync(python, ['-c', String.raw`
import sys,json
from pathlib import Path
from grant_agent.recovery_objects import RecoveryObject,RecoveryObjectStore,SCHEMA
root=Path(sys.argv[1]); store=RecoveryObjectStore(root,'mission-1')
r=store.create({'operationId':'deploy-7','intent':'deploy exact build','authority':'release.deploy'}, recovery_id='recovery-deploy-7', operation_id='deploy-7', confirmed_steps=[{'step':'precondition checked','revision':'abc'}], uncertain_effects=[{'effect':'service may have restarted','confidence':'unknown'}], retry_safety='requires_reconciliation', available_recovery_paths=[{'id':'inspect-health','safe':True},{'id':'rollback','requiresAuthority':'release.rollback'}], required_authority=['release.deploy'], lineage={'parentOperation':'deploy-7'})
checks={'created':r.status=='open' and bool(r.content_hash)}
r.add_evidence('health_probe',detail='HTTP returned timeout',path='evidence/health.json',sha256='a'*64)
r.append_repair(diagnosis='deployment response timed out after process handoff', mechanism_changed='reconcile service revision before retry', proof={'status':'passed','artifact':'proof.json','sha256':'b'*64}, recurrence_applicability='all deployments sharing the handoff client', outcome='verified', failure_signature='deploy.timeout.handoff')
r.transition('recovered',note='reconciled revision and verified health')
saved=store.save(r); checks['saved']=saved.exists()
fresh=RecoveryObjectStore(root,'mission-1').load('recovery-deploy-7')
checks['reload']=fresh.to_dict()['schema']==SCHEMA and fresh.status=='recovered'
checks['evidenceRepair']=fresh.evidence[0]['sha256']=='a'*64 and fresh.repair_ledger[0]['regressionProof']['status']=='passed'
checks['listing']=RecoveryObjectStore(root,'mission-1').list(status='recovered')[0]['recoveryId']=='recovery-deploy-7'
tamper=False
try:
  RecoveryObject.from_dict({**fresh.to_dict(),'contentHash':'bad'})
except ValueError as exc:
  tamper='hash mismatch' in str(exc)
checks['tamperRejected']=tamper
print(json.dumps(checks,separators=(',',':')))
`, root], {cwd: repo, env: {...process.env, PYTHONPATH: path.join(repo, 'src')}, encoding: 'utf8', timeout: 30000});
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const checks = JSON.parse(result.stdout.trim());
  for (const [name, value] of Object.entries(checks)) assert.equal(value, true, name);
  const evidence = 'RECOVERY_OBJECTS_VERIFIED: ' + Object.keys(checks).join(', ');
  console.log(JSON.stringify({status:'verified', evidence, sha256:createHash('sha256').update(evidence).digest('hex')}));
} finally {
  rmSync(root, {recursive:true, force:true});
}
