import {spawnSync} from 'node:child_process';
import {resolveNeyviaPython} from './resolve-neyvia-python.mjs';
const result=spawnSync(resolveNeyviaPython(process.cwd()).python,['-c',String.raw`
import json,tempfile
from pathlib import Path
from types import SimpleNamespace
from grant_agent.web_backend import FluxioWebBackend,_normalize_conversation_sessions
from grant_agent.neyvia_conversations import NeyviaConversationStore
from grant_agent.desktop_bridge import ALLOWED_DESKTOP_COMMANDS
from grant_agent.chat_run_control import active_chat_run
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);store=NeyviaConversationStore(root)
 backend=FluxioWebBackend.__new__(FluxioWebBackend)
 backend.root=root;backend._neyvia_mcp=SimpleNamespace(conversations=store)
 cid='existing-chat';store.create_conversation(conversation_id=cid,metadata={'systemPromptProfile':'keep-existing'})
 ids=(cid,'user-1','assistant-1')
 payload={'conversationId':cid,'sessionId':cid,'message':'Existing user request'}
 backend._ensure_agent_chat_user_turn(payload,ids)
 backend._ensure_agent_chat_user_turn(payload,ids)
 command='set_neyvia_conversation_goal_mode_command'
 assert command in ALLOWED_DESKTOP_COMMANDS
 changed=backend.dispatch(command,{'conversationId':cid,'goalMode':True})
 assert changed['metadata']['goalMode'] is True
 assert changed['metadata']['systemPromptProfile']=='keep-existing'
 backend.dispatch('save_conversation_state_command', {'chatSessions':[{'id':cid,'goalMode':False}]})
 reloaded=backend.dispatch('get_conversation_state_command', {'summaryMode':'bootstrap','activeChatSessionId':cid})
 assert reloaded['chatSessions'][0]['goalMode'] is True, 'canonical preference must beat stale UI index'
 assert backend.dispatch('get_conversation_session_state_command', {'sessionId':cid})['session']['goalMode'] is True
 assert len(store.get_conversation(cid,include_turns=True)['turns'])==1
 try:backend.dispatch(command,{'conversationId':cid,'goalMode':'false'})
 except ValueError:pass
 else:raise AssertionError('must reject ambiguous booleans')
 result={'reply':'Verified task complete','goalLoop':{'checkpoint':{'status':'completed'}}}
 backend._persist_agent_chat_result(payload,ids,result)
 assert store.get_conversation(cid,include_turns=True)['turns'][-1]['metadata']['runtimeResult']['goalLoop']['checkpoint']['status']=='completed'
 with store._connection() as db:
  db.execute("UPDATE conversations SET last_meaningful_activity_at='2000-01-01T00:00:00Z' WHERE conversation_id=?",(cid,));db.commit()
 with active_chat_run(root,'active-fixture'):
  backend._maintain_conversation_archive()
  assert store.get_conversation(cid)['archivedAt'] is None
 backend._archive_checked_at=0
 backend._maintain_conversation_archive()
 command='get_archived_neyvia_conversations_command'
 assert command in ALLOWED_DESKTOP_COMMANDS
 assert [r['conversationId'] for r in backend.dispatch(command,{})['conversations']]==[cid]
 command='restore_neyvia_conversation_command'
 assert command in ALLOWED_DESKTOP_COMMANDS
 assert backend.dispatch(command,{'conversationId':cid})['archivedAt'] is None
 assert backend.dispatch('set_neyvia_conversation_goal_mode_command',{'conversationId':cid,'goalMode':False})['metadata']['goalMode'] is False
 normalized=_normalize_conversation_sessions([{'id':'legacy'},{'id':'enabled','goalMode':True},{'id':'disabled','goalMode':False}])
 byid={r['id']:r for r in normalized}
 assert 'goalMode' not in byid['legacy'] and byid['enabled']['goalMode'] is True and byid['disabled']['goalMode'] is False
 print(json.dumps({'passed':True,'existingChatGoalToggle':True,'duplicateSendIdempotent':True,'goalReceiptPersists':True,'archiveAndRestoreCommands':True,'legacyDefaultsPreserved':True}))
`],{cwd:process.cwd(),encoding:'utf8',timeout:60000,env:{...process.env,PYTHONPATH:process.cwd()+'/src'}});
if(result.status!==0)throw new Error(result.stderr||result.stdout||String(result.error));
console.log(result.stdout.trim());

