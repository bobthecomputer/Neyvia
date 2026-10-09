import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {workflowAvailability} from '../web/src/neyvia/neyviaWorkflows.js';

const checks = [];
for (const [name, evidence] of [['cold null', null], ['not loaded', undefined], ['empty evidence', {}]]) {
  const actual = workflowAvailability({evidence});
  assert.deepEqual(actual, {model:false, cli:false, files:false, browser:false, mcp:false});
  checks.push({name, ok:true, actual});
}
const actual = workflowAvailability({evidence:null, workspacePath:'owned-folder', tools:[{toolId:'tool.playwright',agentReady:true}]});
assert.deepEqual(actual, {model:false,cli:false,files:true,browser:true,mcp:false});
checks.push({name:'Unknown model readiness preserves independent file/browser evidence',ok:true,actual});
const sources = Object.fromEntries(['web/src/neyvia/neyviaFrontendContracts.js','web/src/neyvia/neyviaWorkflows.js','scripts/verify_fix_workflow_readiness.mjs'].map(path=>[path,createHash('sha256').update(readFileSync(path)).digest('hex')]));
writeFileSync('scripts/evidence/FIX-workflow-readiness.json', JSON.stringify({ok:true,checks,sources,boundary:'Actual production function and executable contract, explicit input fixtures; real classic boot is verified by the final browser area. No provider-readiness claim.'},null,2)+'\n');
console.log('PASS4 actual workflow readiness checks');
