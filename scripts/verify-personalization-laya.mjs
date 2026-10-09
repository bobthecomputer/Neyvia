import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = mkdtempSync(path.join(tmpdir(), 'neyvia-personalization-'));
try {
  const python = resolveNeyviaPython(repo).python;
  const script = String.raw`
import json,sys
from pathlib import Path
from grant_agent.personalization import PersonalizationStore
from grant_agent.working_memory import WorkingMemoryStore
from grant_agent.collaboration_prompt import collaboration_instructions
from grant_agent.contextual_learning import ContextualLearningStore
from grant_agent.laya_computer_use import LayaComputerUse
from grant_agent.native_tools import NativeToolRegistry, register_with_progressive_surface
from grant_agent.progressive_tools import ProgressiveToolSurface
from grant_agent.capability_service import CapabilityService
from grant_agent.web_backend import FluxioWebBackend
import grant_agent.laya_computer_use as laya
root=Path(sys.argv[1]); store=PersonalizationStore(root)
initial=store.snapshot()
unauthorized=False
try: store.update({'visualDirection':'Warm typography'},expected_revision=0,operator_identity='')
except PermissionError: unauthorized=True
saved=store.update({'workingStyle':'Be concise','visualDirection':'Warm typography','visualAvoid':'Card piles'},expected_revision=0,operator_identity='operator')
conflict=False
try: store.update({'visualDirection':'Cold'},expected_revision=0,operator_identity='operator')
except ValueError: conflict=True
memory=WorkingMemoryStore(root,'conversation')
memory.record_decision('Keep the current visual hierarchy.',source='user',scope='visual')
before=root/'before.txt'; after=root/'after.txt'; before.write_text('Card pile',encoding='utf-8'); after.write_text('Clean hierarchy',encoding='utf-8')
taste=ContextualLearningStore(root/'.agent_control'/'contextual_learning'/'conversation.json',scope_root=root)
correction=taste.record_correction('product-ui',before_path='before.txt',after_path='after.txt',correction='Use clean hierarchy')
taste.record_preference(correction['correctionId'],preference=True,source='operator')
prompt=collaboration_instructions(root,'conversation',session_id='conversation',task_query='Improve the product interface design')
after.write_text('Changed artifact',encoding='utf-8')
stale_prompt=collaboration_instructions(root,'conversation',session_id='conversation',task_query='Improve the product interface design')
reopened=PersonalizationStore(root).snapshot()
surface=ProgressiveToolSurface()
register_with_progressive_surface(surface,NativeToolRegistry(root))
native_laya=surface.describe('laya.native.neyvia_navigation')
class FakeIntelligence:
    def run_bounded(self,payload,executor):
        return executor('laya.native.neyvia_navigation',{}, {'approved':True})
service=CapabilityService.__new__(CapabilityService)
service._ensure_model_tool_intelligence=lambda: FakeIntelligence()
plan_denied=service.run_model_tool_plan({'approved':False})
backend=FluxioWebBackend.__new__(FluxioWebBackend)
backend.root=root
direct_denied=backend.dispatch('call_native_tool_command',{'tool':'laya.native.neyvia_navigation'})
original=laya._post
try:
    laya._post=lambda route,payload,timeout: {'format':'laya-native-computer-capabilities-v1','provider_attached':True,'execution_enabled':True,'supported_workflows':[]}
    unavailable=LayaComputerUse(root).run_neyvia_navigation()
    calls=[]
    def fake_post(route,payload,timeout):
        calls.append(route)
        if route.endswith('capabilities'):
            return {'format':'laya-native-computer-capabilities-v1','provider_attached':True,'execution_enabled':True,'supported_workflows':['neyvia_desktop_navigation']}
        return {'format':'laya-native-computer-run-v1','status':'completed','reason':'postcondition_verified','execution_performed':True,'outcome_unknown':False,'provider_id':'luna-uia-background-host','worker_receipt':{'format':'laya-luna-neyvia-desktop-v1','passed':False,'execution_performed':True,'window':{'pid':123},'initial_page':'chat','final_page':'chat','trace':[{'from':'chat','to':'chat','after_page':'chat','before_hash':'a'*64}]}}
    laya._post=fake_post
    rejected=LayaComputerUse(root).run_neyvia_navigation()
finally: laya._post=original
print(json.dumps({'authRequired':unauthorized,'revisionCheck':conflict,'durableProfile':reopened['revision']==1 and reopened['preferences']==saved['preferences'],'promptProfile':'Warm typography' in prompt and 'Card piles' in prompt and 'authenticated_operator_workspace_profile' in prompt,'promptWorkingMemory':'Keep the current visual hierarchy.' in prompt and 'semantic.memory.retrieve' in prompt,'visualTasteApplied':'Use clean hierarchy' in prompt and 'transferVerified' in prompt,'staleTasteExcluded':'Use clean hierarchy' not in stale_prompt and correction['correctionId'] in stale_prompt,'layaActionPermission':native_laya['permissions']==['external.side_effect'] and native_laya['annotations']['requiresApproval'] is True,'layaPlanRequiresGrant':plan_denied['status']=='approval_required' and plan_denied['requiredPermission']=='external.side_effect','layaBackendRequiresGrant':direct_denied['status']=='approval_required' and direct_denied['requiredPermission']=='external.side_effect','layaUnsupportedBlocked':unavailable['status']=='blocked' and unavailable['executionPerformed'] is False,'layaFalsePositiveRejected':rejected['status']=='action_uncertain' and rejected['verifiedTransitions']==0 and len(calls)==2},separators=(',',':')))
`;
  const result = spawnSync(python, ['-c', script, root], {
    cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, 'src') },
    encoding: 'utf8', timeout: 30000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout || result.error?.message);
  const checks = JSON.parse(result.stdout.trim());
  for (const [name, passed] of Object.entries(checks)) assert.equal(passed, true, name);
  console.log(JSON.stringify({ status: 'verified', checks }));
} finally {
  rmSync(root, { recursive: true, force: true });
}
