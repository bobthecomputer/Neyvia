import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveNeyviaPython } from './resolve-neyvia-python.mjs';
const repo = process.cwd(), root = mkdtempSync(path.join(tmpdir(), 'neyvia-collaboration-resume-'));
try {
  const run = spawnSync(resolveNeyviaPython(repo).python, ['-c', String.raw`
import json,os,sys
from pathlib import Path
from grant_agent.workspace_intelligence import WorkspaceIntelligence
from grant_agent.experience_learning import ExperienceStore
from grant_agent.context_engine import DurableContextEngine
from grant_agent.neyvia_agent import NeyviaAgentConfig,NeyviaToolGateway,_role_instructions
from grant_agent.agent_questions import request_question,answer_question,question_context
r=Path(sys.argv[1]);runtime=r/'runtime';runtime.mkdir()
w=WorkspaceIntelligence(r,'task-a');e=ExperienceStore(r,'task-a');checks={}
try:e.note(lesson='Use stable controls',conditions='Browser task',invalidation='Changed control identity',evidence=['receipt.json'])
except PermissionError:checks['learningOffEnforced']=True
w.configure_collaboration({'learning':True,'directions':'varied'},expected_revision=0,operator_identity='operator')
artifact=r/'receipt.json';artifact.write_text('{"control":"listening","changes":1}',encoding='utf8')
note=e.note(lesson='Use the stable listening control identity and inspect the receipt before retrying.',conditions='Browser listening task',invalidation='Navigation or changed control state',evidence=['receipt.json'])
directions=[{'id':'one','title':'One approach','approach':'Keep existing start screen','tradeoff':'More gradual change'}]
w.propose_brief('Improve browser listening',directions=directions)
w.review_brief(expected_revision=1,operator_identity='operator',direction_id='one',correction='Never replace the microphone device.')
try:w.propose_brief('New understanding',expected_revision=2,directions=[])
except ValueError:checks['selectedDirectionProtected']=True
w.propose_brief('Improve browser listening with better evidence',expected_revision=2,directions=directions)
checks['correctionSurvivesRevision']=w.collaboration()['brief']['corrections'][0]['text']=='Never replace the microphone device.'
packet=DurableContextEngine(r,'task-a',max_context_tokens=4096,reserve_tokens=128).build_bundle('browser listening',token_budget=1600)
checks['contextRetrievesExperience']=packet['experienceNotes']['notes'][0]['recordId']==note['recordId']
checks['contextPreservesCorrection']=packet['collaboration']['brief']['corrections'][0]['text']=='Never replace the microphone device.'
os.environ['NEYVIA_PROOF_ROOT']=str(r);os.environ['NEYVIA_PROOF_CONVERSATION_ID']='task-a'
instructions=_role_instructions(NeyviaAgentConfig(root=runtime,control_root=runtime,session_id='different-runtime-session',enable_specialists=False))
checks['runtimeReadsParentScope']='Never replace the microphone device.' in instructions and note['recordId'] in instructions
gateway=NeyviaToolGateway(runtime,allow_mutations=True,action_scope='task-a',action_root=r,allowed_mutation_tools={'intelligence.brief','lab.rehearse','experience.note'})
read=gateway.call_native('intelligence.collaboration',{'workId':'task-a','arguments':{}})
checks['gatewayReadsSameScope']='Never replace the microphone device.' in json.dumps(read)
checks['gatewayRejectsOtherScope']=gateway.call_native('experience.relevant',{'workId':'task-b'})['status']=='work_scope_mismatch'
blocked=gateway.call_native('lab.rehearse',{'experiment_id':'absent','script':'run.js'},action_id='rehearsal-off')
checks['rehearsalDisabledBeforeEffect']=blocked['status']=='experience_disabled' and gateway.actions.inspect('rehearsal-off')['status']=='not_started'
read_only=NeyviaToolGateway(runtime,allow_mutations=False,action_scope='task-a',action_root=r)
checks['readOnlyCanSaveScopedBrief']=read_only.call_native('intelligence.brief',{'arguments':{'understanding':'Preserve the chosen listening design','expected_revision':3,'directions':directions}},action_id='read-only-brief')['ok']
checks['preferenceDoesNotGrantMutation']=read_only.call_native('work.focus',{'workId':'task-a','text':'still needs a work-state grant'},action_id='denied')['status']=='approval_required'
artifact.write_text('{"control":"replacement","changes":2}',encoding='utf8')
stale=e.relevant('browser listening')
checks['changedEvidenceMarkedStale']=stale['notes'][0]['status']=='stale' and not stale['notes'][0]['evidenceCurrent']
checks['unrelatedScopeHasNoNotes']=ExperienceStore(r,'task-b').relevant('browser listening')['notes']==[]
checks['boundedExperience']=len(json.dumps(e.relevant('',max_characters=600),ensure_ascii=False,separators=(',',':')))<=600
w.review_brief(expected_revision=4,operator_identity='operator',correction='x'*2000)
bounded=w.collaboration_context(max_characters=800)
checks['oversizeBriefRequiresRetrieval']=bounded['requiresBriefRetrieval'] and bounded['brief']['requiresRetrieval']
q=request_question(runtime,'old-runtime','Which audience?',context='Alternative concepts for the landing page',conversation_id='task-a')
try:answer_question(runtime,q['questionId'],'wrong task',conversation_id='task-b')
except ValueError:checks['wrongTaskAnswerRejected']=True
answer_question(runtime,q['questionId'],'Beginners, with no account required.',conversation_id='task-a')
resumed=question_context(runtime,'new-runtime',conversation_id='task-a')
checks['answerSurvivesRuntimeChange']=resumed['entries'][0]['answer']=='Beginners, with no account required.'
checks['answerNotSharedWithOtherTask']=question_context(runtime,'new-runtime',conversation_id='task-b')['entries']==[]
checks['runtimeIncludesExactAnswer']='Beginners, with no account required.' in _role_instructions(NeyviaAgentConfig(root=runtime,control_root=runtime,session_id='new-runtime',enable_specialists=False))
import hashlib
obligation=w.attach_obligation('receipt.json',hashlib.sha256(artifact.read_bytes()).hexdigest(),{'type':'json_path','path':'changes','equals':2})['obligations'][-1]['id']
question=w.ask_self('Did the intended transition occur once?','Whether to repeat the browser action')
checks['selfQuestionStartsOpen']=w.self_questions()['questions'][0]['status']=='open'
answered=w.answer_self(question['id'],'The saved trace reports two changes; do not repeat it blindly.',[obligation],0)
checks['selfAnswerUsesActualChecks']=answered['status']=='supported_report' and not answered['authorityGranted'] and answered['evidence'][0]['status']=='verified'
try:w.answer_self(question['id'],'overwrite', [obligation],0)
except ValueError:checks['staleSelfAnswerRejected']=True
artifact.write_text('{"changes":3}',encoding='utf8')
checks['selfAnswerInvalidatedByChangedEvidence']=w.self_questions()['questions'][0]['status']=='needs_recheck'
print(json.dumps(checks))
`, root], { cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, 'src') }, encoding: 'utf8', timeout: 45000 });
  assert.equal(run.status, 0, run.stderr || run.stdout);
  const checks = JSON.parse(run.stdout.trim());
  for (const [name, value] of Object.entries(checks)) assert.equal(value, true, name);
  const receipt = { status: 'verified', boundary: 'production context reconstruction, tool gateway, and invalidation; live model behavior not yet claimed', checks };
  mkdirSync(path.join(repo, 'proof/system-improvement'), { recursive: true });
  writeFileSync(path.join(repo, 'proof/system-improvement/continuation-checks.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} finally {
  if (path.dirname(path.resolve(root)) !== path.resolve(tmpdir()) || !path.basename(root).startsWith('neyvia-collaboration-resume-')) throw Error('Unexpected temporary cleanup path');
  rmSync(root, { recursive: true, force: true });
}
