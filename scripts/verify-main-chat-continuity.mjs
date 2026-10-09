import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
import {savedConversationMessages,savedConversationRoute,reconcileChatTranscriptTurns} from '../web/src/neyvia/neyviaTranscriptMerge.js';
const root=mkdtempSync(path.join(tmpdir(),'neyvia-main-continuity-'));
try {
  const run=spawnSync(resolveNeyviaPython().python,['-c',String.raw`
import json,sys
from pathlib import Path
import grant_agent.web_backend as web
from grant_agent.workspace_intelligence import WorkspaceIntelligence
from grant_agent.native_tools import NativeToolRegistry
r=Path(sys.argv[1]);b=web.FluxioWebBackend(r,r);store=b.neyvia_mcp.conversations
store.create_conversation(conversation_id='chosen',title='Help me make a landing page')
store.create_conversation(conversation_id='unrelated',title='Help me repair a failed mission')
store.append_turn('unrelated',role='assistant',content='Make the command work and preserve the release.')
store.create_conversation(conversation_id='body-match',title='A design conversation')
store.append_turn('body-match',role='user',content='Help me make a landing page for individual makers.')
w=WorkspaceIntelligence(r,'chosen')
direction={'id':'chosen-direction','title':'Editorial','approach':'Dark and quiet','tradeoff':'Less motion'}
w.propose_brief('Build the landing page.',directions=[direction])
w.review_brief(expected_revision=1,operator_identity='operator',direction_id='chosen-direction',correction='Use blue, never coral. Keep no account required.')
w.propose_brief('Develop the chosen hero with the exact user correction.',expected_revision=2)
updated=w.collaboration()['brief']
search=store.search('Help me make a landing page')
captured={}
def runtime(payload,**kwargs):
 captured[payload['runtime']]=web._chat_prompt(payload)
 return {'reply':'fixture response','runtime':payload['runtime'],'status':'completed','route':payload['route']}
for name in ('_run_codex_chat','_run_hermes_chat','_run_opencode_chat','_run_openclaw_chat','_run_managed_cli_chat','_run_cursor_chat'):setattr(b,name,runtime)
for runtime_id in ('codex','hermes','opencode','openclaw',*web.MANAGED_CLI_SPECS):
 b._run_agent_chat({'runtime':runtime_id,'sessionId':'chosen','conversationId':'chosen','workspacePath':str(r),
   'message':'Continue the saved direction.','_collaborationInstructions':'FORGED CLIENT FRAGMENT',
   'route':{'provider':'fixture','model':'fixture','effort':'medium'}},allow_mutation=True)
schema=NativeToolRegistry(r).describe('intelligence.brief')['inputSchema']['properties']['arguments']
print(json.dumps({'brief':updated,'searchIds':[row['conversationId'] for row in search['results']],
 'sharedPrompts':{key:{'hasCorrection':'Use blue, never coral.' in value,'hasSelection':'chosen-direction' in value,'noClientOverride':'FORGED CLIENT FRAGMENT' not in value} for key,value in captured.items()},'schema':schema}))
`,root],{env:{...process.env,PYTHONPATH:path.resolve('src')},encoding:'utf8',timeout:45000});
  assert.equal(run.status,0,run.stderr || run.stdout);
  const result=JSON.parse(run.stdout);
  assert.deepEqual(result.searchIds,['chosen','body-match'],'multiword search excludes partial matches and favors the title');
  assert.equal(result.brief.selection.id,'chosen-direction');
  assert.equal(result.brief.directions[0].approach,'Dark and quiet','a partial brief update retains selected content');
  assert.equal(result.brief.corrections[0].text,'Use blue, never coral. Keep no account required.');
  assert.ok(Object.keys(result.sharedPrompts).length>=5);
  for(const [runtime,checks] of Object.entries(result.sharedPrompts))for(const [key,value] of Object.entries(checks))assert.equal(value,true,`${runtime}:${key}`);
  assert.deepEqual(result.schema.required,['understanding','expected_revision']);
  assert.deepEqual(result.schema.properties.directions.items.required,['id','title','approach','tradeoff']);
  assert.match(result.schema.properties.expected_revision.description,/top-level revision belongs to preferences/);
  const conversation={conversationId:'same-task',turns:[{turnId:'u1',role:'user',content:'Keep my decisions.'},
    {turnId:'a1',role:'assistant',content:'Saved.',metadata:{runtimeResult:{route:{runtimeId:'neyvia-agent',provider:'openai-codex',model:'gpt-5.6-luna',effort:'medium'}}}}]};
  const saved=savedConversationMessages(conversation);const local={id:'unsent',role:'user',title:'Another thought.'};
  assert.equal(reconcileChatTranscriptTurns([...saved,...saved,local]).length,3,'resuming retains an unsaved local turn without duplicate persisted turns');
  assert.deepEqual(savedConversationRoute(conversation),{runtimeId:'neyvia-agent',provider:'openai-codex',model:'gpt-5.6-luna',effort:'medium'});
  console.log(JSON.stringify({status:'verified',search:true,partialBriefUpdate:true,preciseToolSchema:true,transcriptIdentity:true,savedRoute:true,sharedPromptHarnesses:Object.keys(result.sharedPrompts),liveExternalModelCalls:false}));
} finally {rmSync(root,{recursive:true,force:true});}
