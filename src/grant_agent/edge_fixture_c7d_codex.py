"""Confined Node JSON-RPC peer exercises host semantics, never a provider/model."""
from __future__ import annotations
import json
import os
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NAMES = {"answer", "auth", "available", "events", "goal", "goal_notes", "lifecycle", "list", "live", "lock", "login", "media", "options", "page", "plugin_login", "summary", "thread", "wire", "writer"}
IDS = {"providers.codex." + name for name in NAMES} | {"providers.rpc.backoff", "providers.rpc.response", "providers.process.hidden"}
TEXT = {"empty": "", "huge": "owned supplied protocol input " * 4096, "unicode": "雪 café e\u0301 العربية"}
PURE = {"providers.codex.available", "providers.codex.events", "providers.codex.goal_notes", "providers.codex.summary"}
PEER = r'''
const fs=require('node:fs'),readline=require('node:readline');const worldPath=process.argv[2];const world=()=>JSON.parse(fs.readFileSync(worldPath,'utf8'));const send=x=>process.stdout.write(JSON.stringify(x)+'\n');let goal=null;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line),w=world(),p=m.params||{};fs.appendFileSync(w.log,JSON.stringify(m)+'\n');let result={};
 if(!m.method||m.id==null)return;
 if(m.method==='initialize')result={userAgent:'owned-node-protocol'};
 else if(m.method==='owned/echo')result=p;
 else if(m.method==='owned/stop')process.exit(3);
 else if(m.method==='owned/wait')return;
 else if(m.method==='thread/list'){const rows=w.threads.filter(t=>!!t.archived===!!p.archived).sort((a,b)=>b.updatedAt-a.updatedAt);const start=Number(p.cursor||0),limit=p.limit||100;result={data:rows.slice(start,start+limit),nextCursor:start+limit<rows.length?String(start+limit):null}}
 else if(m.method==='project/list')result={data:[],nextCursor:null};
 else if(m.method==='thread/read'){const t=w.threads.find(x=>x.id===p.threadId);if(!t){send({id:m.id,error:{code:-32600,message:'thread not found'}});return}result={thread:t}}
 else if(m.method==='thread/turns/list'){const rows=(w.turns[p.threadId]||[]).slice();if(p.sortDirection==='desc')rows.reverse();const start=Number(p.cursor||0),limit=p.limit||100;result={data:rows.slice(start,start+limit),nextCursor:start+limit<rows.length?String(start+limit):null}}
 else if(m.method==='thread/items/list')result={data:[{item:{type:'userMessage',id:'owned-image',content:[{type:'localImage',path:w.image}]}}],nextCursor:null};
 else if(m.method==='config/read')result={config:{model:'owned',model_reasoning_effort:'high'}};
 else if(m.method==='model/list')result={data:[{id:'owned',model:'owned',displayName:w.text,supportedReasoningEfforts:[{reasoningEffort:'high',description:'Owned supplied value'}],defaultReasoningEffort:'high',isDefault:true}],nextCursor:null};
 else if(m.method==='skills/list')result={data:[],errors:[]};
 else if(m.method==='plugin/list'||m.method==='plugin/installed')result={marketplaces:[]};
 else if(m.method==='app/list'||m.method==='mcpServerStatus/list')result={data:[],nextCursor:null};
 else if(m.method==='account/read')result={account:w.account,requiresOpenaiAuth:true};
 else if(m.method==='account/login/start')result={verificationUrl:'https://auth.example.invalid/owned',userCode:'OWNED-ONLY',loginId:'private-field-must-not-leak'};
 else if(m.method==='thread/goal/get')result={goal};
 else if(m.method==='thread/goal/set'){goal={objective:p.objective,status:'active',updatedAt:1790000000};result={goal}}
 else if(m.method==='thread/goal/clear'){goal=null;result={cleared:true}}
 else if(m.method==='thread/start'||m.method==='thread/resume'||m.method==='thread/fork')result={thread:w.threads[0]};
 else if(m.method==='turn/start'){const turn={id:'owned-turn',status:'inProgress',items:[]};result={turn};setTimeout(()=>{send({method:'turn/started',params:{threadId:w.threads[0].id,turn}});if(w.hold)return;send({method:'item/completed',params:{threadId:w.threads[0].id,turnId:turn.id,item:{type:'agentMessage',id:'owned-final',text:w.text}}});send({method:'turn/completed',params:{threadId:w.threads[0].id,turn:{...turn,status:'completed'}}})},25)}
 else if(m.method==='turn/interrupt'){result={};send({method:'turn/completed',params:{threadId:p.threadId,turn:{id:p.turnId,status:'interrupted',items:[]}}})}
 else if(m.method==='thread/unsubscribe')result={};
 else {send({id:m.id,error:{code:-32601,message:'Unsupported owned protocol method '+m.method}});return}
 send({id:m.id,result});
});
'''


def require(value, detail):
    if not value:
        raise AssertionError(detail)


def rejected(action, code=None):
    try:
        action()
    except Exception as error:
        if code:
            require(getattr(error, 'code', None) == code, 'Precise refusal code differs: ' + str(getattr(error, 'code', None)))
        return error
    raise AssertionError('Invalid/stale/unavailable supplied action accepted')


@contextmanager
def held_writer(path):
    """Own a real Windows byte lock; a denied file read is not lock ownership."""
    import msvcrt
    with path.open('r+b') as file:
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def exercise(root, category, identity):
    from .connected_sessions.codex import CodexAdapter, _Emitter, _Run, _Pending
    from .connected_sessions.codex_items import media_token
    from .connected_sessions.codex_writer import active_writer
    from .connected_sessions.model import TurnOptions
    from .edge_fixture_models import _deny_read
    text = TEXT.get(category, 'owned supplied protocol input')
    peer = root / 'peer.cjs'; peer.write_text(PEER, encoding='utf-8')
    world_path = root / 'supplied-world.json'; log = root / 'wire.jsonl'
    home = root / 'provider-home'; sessions = home / 'sessions'; sessions.mkdir(parents=True)
    locks = home / 'thread-writer-locks'; locks.mkdir()
    lock = locks / 'owned.lock'; lock.write_bytes(b'0')
    rollout = sessions / 'owned.jsonl'; rollout.write_text(json.dumps({'type':'event_msg','payload':{'type':'task_started','turn_id':'owned','started_at':1790000000}})+'\n')
    picture = root / 'owned.png'; picture.write_bytes(text.encode() or b'owned supplied bytes')
    thread = {'id':'owned','name':text,'cwd':str(root),'updatedAt':1790000000,'createdAt':1789999000,'model':'owned','source':'vscode','path':str(rollout),'gitInfo':{'branch':'owned'}}
    turn_count = 150 if category == 'huge' else 4
    turns = [{'id':'turn-'+str(i),'status':'completed','completedAt':1790000000+i,'startedAt':1789999999+i,'items':[{'id':'user-'+str(i),'type':'userMessage','content':[{'type':'text','text':(text or 'owned') if i == turn_count-1 else 'owned'}]},{'id':'assistant-'+str(i),'type':'agentMessage','text':(text or 'owned') if i == turn_count-1 else 'owned'}]} for i in range(turn_count)]
    world = {'log':str(log),'text':text or 'owned','image':str(picture),'account':None,'threads':[thread,{**thread,'id':'archived','archived':True,'updatedAt':1789000000}],'turns':{'owned':turns}}
    def save():
        world_path.write_text(json.dumps(world),encoding='utf-8')
    save()
    owner = CodexAdapter(command=['node',str(peer),str(world_path)],state_root=root,device={'deviceId':'c7d-owned','deviceName':'Owned scratch'},list_ttl=0,rpc_timeout=2)
    owner._conn._environment = {**os.environ,'CODEX_HOME':str(home)}
    sid = owner._sid('owned')
    def wire():
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []
    try:
        if identity == 'providers.codex.available':
            require(owner.available() == (True,None), 'Actual supplied installed Node command availability changed')
            missing = CodexAdapter(command=[str(root/'missing.exe')],state_root=root)
            try:
                require(not missing.available()[0] and missing.available()[1], 'Missing supplied command advertised availability')
            finally:
                missing.close()
            return {'actualCommandResolution':True,'modelProviderAvailable':False}
        if identity == 'providers.codex.events':
            collected=[];emit=_Emitter(lambda:collected.append)
            event={'type':'run.state','sessionId':sid,'runId':'owned','state':'running','pendingRequest':None,'error':None,'text':text}
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _:emit(event),range(8 if category=='huge' else 1)))
            require(all(row==event for row in collected),'Serialized event emitter changed supplied data')
            return {'actualEmitterProjection':True,'providerObserved':False}
        if identity == 'providers.codex.goal_notes':
            goal={'objective':text or 'owned','status':'active'}
            owner._goals['owned']=goal;owner._goal_expect['owned']=('set',time.monotonic())
            stale=owner._note_goal('owned','thread/goal/cleared',{})
            require(not stale['_neyvia']['emit'] and owner._goals['owned']==goal,'Opposite stale goal snapshot consumed pending set expectation')
            current=owner._note_goal('owned','thread/goal/updated',{'goal':goal})
            require(current['_neyvia']['emit'] and 'owned' not in owner._goal_expect,'Matching goal notification did not acknowledge expected current set')
            return {'actualSuppliedGoalNotificationAdmission':True,'providerObserved':False}
        if identity == 'providers.codex.lock':
            require(active_writer('owned',str(rollout)) is False,'Actual released owned OS writer lock appeared occupied')
            with held_writer(lock):
                require(active_writer('owned',str(rollout)) is True,'Actual Windows shared-file writer denial was not observed')
            require(active_writer('owned',str(rollout)) is False and active_writer('x'*251,str(rollout)) is None,'Released or oversized writer identity probe changed')
            return {'actualWindowsWriterOwnership':True,'releasedReadback':True,'providerObserved':False}
        if identity == 'providers.codex.summary':
            result=owner._summary(thread,live={sid:('working','app')},fetch=False)
            require(result.model=='owned' and result.git_branch=='owned' and result.live_owner=='app' and not result.capabilities.continue_session and not result.capabilities.stop,'Supplied foreign-writer metadata invented controls')
            return {'actualSuppliedThreadSummary':True,'providerObserved':False}
        if identity == 'providers.rpc.backoff':
            for _ in range(100 if category=='huge' else 3):
                owner._conn._register_failure()
            require(owner._conn._failures==(100 if category=='huge' else 3) and owner._conn._next_start_at>time.monotonic(),'Actual startup failure did not apply bounded retry schedule')
            return {'actualBackoffState':True,'childStarted':False}
        if identity in {'providers.codex.writer','providers.codex.live'}:
            with held_writer(lock):
                if identity=='providers.codex.writer':
                    require(owner._elsewhere(thread)['owner']=='app','Actual occupied writer lock lost foreign app ownership')
                else:
                    require(owner.live_status()[sid]==('working','app'),'Actual occupied writer lock disappeared from protocol live metadata')
            owner._drop_cache('live')
            require(owner._elsewhere(thread) is None and sid not in owner.live_status(),'Released owned lock retained cached active foreign writer')
            return {'actualWindowsLockAndProtocolProjection':True,'providerObserved':False}
        if identity=='providers.codex.answer':
            rejected(lambda:owner.answer('missing',text or 'missing',{'decision':'approve'}),'run_not_active')
            require(not wire(),'Absent pending run answer reached protocol child')
            owner._rpc('owned/echo',{})
            generation=owner._conn.generation
            run=_Run('owned-answer',lambda:lambda _:None);run.session_id=sid;run.thread_id='owned'
            pending=_Pending('owned-request',81,generation,'item/commandExecution/requestApproval',{}, {'kind':'approval','choices':['approve','deny','cancel']})
            run.pending[pending.request_id]=pending;owner._runs[run.run_id]=run
            rejected(lambda:owner.answer(run.run_id,pending.request_id,{'decision':text or 'invalid'}),'invalid_decision')
            if category in {'stale','offline','interrupted'}:
                owner._conn.close()
                rejected(lambda:owner.answer(run.run_id,pending.request_id,{'decision':'deny'}),'request_expired')
                require(pending.request_id in run.pending,'Undelivered generation-expired answer consumed pending request')
                owner._runs.pop(run.run_id)
                return {'actualExpiredGenerationRefusal':True,'pendingRetained':True,'providerObserved':False}
            if category=='concurrency':
                import threading
                barrier=threading.Barrier(8)
                def answer(_):
                    barrier.wait(timeout=10)
                    try: owner.answer(run.run_id,pending.request_id,{'decision':'deny'});return 'delivered'
                    except Exception as error: return getattr(error,'code',type(error).__name__)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results=list(pool.map(answer,range(8)))
                require(results.count('delivered')==1 and all(v in {'delivered','request_not_pending'} for v in results),'Concurrent pending answer delivered more than once: '+str(results))
            else:
                owner.answer(run.run_id,pending.request_id,{'decision':'deny'})
            owner._rpc('owned/echo',{})
            require(any(row.get('id')==81 and row.get('result')=={'decision':'decline'} for row in wire()),'Actual typed deny was absent from owned child stdin')
            require(not run.pending,'Delivered deny retained pending request')
            rejected(lambda:owner.answer(run.run_id,pending.request_id,{'decision':'approve'}),'request_not_pending')
            owner._runs.pop(run.run_id)
            return {'actualAbsentRunAndTypedDenyDelivery':True,'providerObserved':False,'generationExpiryRetainsPending':category in {'stale','offline','interrupted','permissions'}}
        if category=='offline':
            peer.write_text('process.exit(3)')
            owner._conn._max_start_wait=.01
            if identity=='providers.codex.auth':
                require(owner.auth(force=True)['kind']=='unknown','Unavailable protocol child invented account billing')
            elif identity=='providers.codex.options':
                value=owner.options();require(not value['models'] and value.get('errors') and value['auth']['kind']=='unknown','Unavailable protocol child invented model catalog')
            else:
                rejected(lambda:owner._rpc('owned/echo',{'text':text}))
            return {'actualUnavailableOwnedNodeChild':True,'providerObserved':False}
        if category=='permissions':
            with _deny_read(peer):
                if identity=='providers.codex.auth':
                    require(owner.auth(force=True)['kind']=='unknown','Denied protocol source read invented auth')
                elif identity=='providers.codex.options':
                    require(not owner.options()['models'],'Denied protocol source read invented model list')
                else:
                    rejected(lambda:owner._rpc('owned/echo',{'text':text}))
            return {'actualWindowsProtocolSourceDenied':True,'providerObserved':False}
        if identity in {'providers.rpc.response','providers.codex.wire','providers.process.hidden'}:
            value=owner._rpc('owned/echo',{'text':text});require(value=={'text':text},'Actual Node stdio roundtrip changed supplied bytes')
            generation=owner._conn._generation
            owner._conn.respond(generation,81,{'supplied':text})
            owner._rpc('owned/echo',{})
            require(any(row.get('id')==81 and row.get('result')=={'supplied':text} for row in wire()),'Actual generation-bound response was absent from child stdin')
            rejected(lambda:owner._conn.respond(generation+1,82,{}))
            if category=='concurrency':
                with ThreadPoolExecutor(max_workers=8) as pool:
                    values=list(pool.map(lambda i:owner._rpc('owned/echo',{'index':i}),range(16)))
                require(values==[{'index':i} for i in range(16)],'Actual concurrent typed stdio requests crossed response identities')
            if category=='interrupted':
                rejected(lambda:owner._rpc('owned/wait',{},timeout=.1))
            return {'actualNodeStdioRoundtrip':True,'actualGenerationRefusal':True,'providerObserved':False,'visibleWindowOpened':False}
        if identity=='providers.codex.thread':
            require(owner._thread_meta('owned')['id']=='owned','Actual protocol thread lookup changed identity')
            rejected(lambda:owner._thread_meta('missing'),'session_not_found')
        elif identity=='providers.codex.list':
            result=owner.list_sessions();require(len(result)==1 and result[0].id==sid,'Actual protocol list included archived session by default')
            require(len(owner.list_sessions(include_archived=True))==2,'Explicit archived session list lost supplied session')
        elif identity=='providers.codex.page':
            page=owner.read(sid,limit=999999 if category=='huge' else 3)
            messages = [item for item in page.items if item.kind in {'user_message', 'assistant_message', 'user', 'assistant'}]
            require(0<len(page.items)<=200 and messages,'Actual protocol page lacked bounded message items')
            for item in messages:
                observed=item.data['text']
                require(observed in {text or 'owned','owned'} or (category=='huge' and observed.startswith(text[:1024]) and 'omitted' in observed and len(observed.encode())<=48100 and item.data.get('truncated')),'Actual protocol page altered bytes without a bounded explicit truncation receipt')
            if category=='stale':
                before=[item.seq for item in messages];world['turns']['owned'].append({'id':'newest','status':'completed','startedAt':1790000300,'completedAt':1790000301,'items':[{'id':'new-user','type':'userMessage','content':[{'type':'text','text':'fresh'}]}]});save();owner._drop_cache('turn-index:owned')
                current=owner.read(sid,limit=200)
                require(any(item.data.get('text')=='fresh' for item in current.items),'Fresh selected protocol page retained previous cached tail')
        elif identity=='providers.codex.media':
            token=media_token(str(picture));value=owner.read_media(sid,token);require(value[0]==picture.read_bytes() and value[1]=='image/png','Actual opaque image handle changed owned bytes')
            rejected(lambda:owner.read_media(sid,text or 'invalid'),'invalid_media')
        elif identity=='providers.codex.auth':
            require(owner.auth(force=True)=={'kind':'signed-out','label':'no sign-in'},'Supplied signed-out protocol auth acquired billing')
            world['account']={'type':'chatgpt','planType':'plus','email':'private-generated@example.invalid'};save()
            value=owner.auth(force=True);require(value=={'kind':'subscription','label':'your ChatGPT Plus plan'} and 'email' not in json.dumps(value),'Actual supplied public billing projection leaked identity')
        elif identity=='providers.codex.login':
            value=owner.sign_in();require(value['state']=='code' and value['userCode']=='OWNED-ONLY' and 'loginId' not in value,'Actual login protocol projection leaked private wire field or lost supplied user code')
        elif identity=='providers.codex.plugin_login':
            rejected(lambda:owner.plugin_login(text or 'unknown'),'plugin_unknown')
        elif identity=='providers.codex.options':
            value=owner.options();require(value['models'][0]['id']=='owned' and [row['id'] for row in value['permissionModes']]==['ask','auto','full'] and value['auth']['kind']=='signed-out','Actual supplied protocol catalog lost stable model/grant/public auth fields')
        elif identity=='providers.codex.goal':
            rejected(lambda:owner.goal(sid,'set',''),'goal_required');rejected(lambda:owner.goal(sid,'invalid',text),'invalid_action')
            value=owner.goal(sid,'set',text or 'owned goal');require(value['text']==(text.strip() or 'owned goal'),'Actual goal protocol set changed supplied objective')
            require(owner.goal(sid,'clear') is None and owner.goal(sid,'get') is None,'Actual goal clear/get resurrected previous supplied objective')
        elif identity=='providers.codex.lifecycle':
            events=[]
            if category=='empty':
                rejected(lambda:owner.start_turn(None,'',TurnOptions(),cwd=str(root),run_id='empty',emit=events.append),'empty_message');require(not events,'Empty request emitted run before refusal')
            if category in {'concurrency','interrupted','stale'}:
                world['hold']=True;save()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    task=pool.submit(owner.start_turn,sid,text or 'owned',TurnOptions(),cwd=str(root),run_id='owned-run',emit=events.append)
                    deadline=time.monotonic()+10
                    while not (owner._runs.get('owned-run') and owner._runs['owned-run'].turn_ready.is_set()):
                        require(time.monotonic()<deadline,'Owned turn never reached interruptible boundary');time.sleep(.01)
                    rejected(lambda:owner.start_turn(sid,'other',TurnOptions(),cwd=str(root),run_id='conflict',emit=lambda _:None),'session_busy')
                    owner.interrupt('owned-run');result=task.result(timeout=15)
                terminal=[row for row in events if row['type']=='run.state'][-1]
                require(result==sid and terminal['state']=='interrupted' and 'owned-run' not in owner._runs,'Actual interrupted lifecycle retained worker or claimed completion')
                require(any(row.get('method')=='turn/interrupt' for row in wire()),'Interrupt receipt lacked actual child protocol request')
            else:
                result=owner.start_turn(sid,text or 'owned',TurnOptions(),cwd=str(root),run_id='owned-run',emit=events.append)
                require(result==sid and [row for row in events if row['type']=='run.state'][-1]['state']=='completed','Actual Node protocol lifecycle returned without terminal identity-bound receipt')
        else:
            raise AssertionError('No exact owner builder '+identity)
        return {'actualNodeProtocolOwner':True,'generatedProtocolInputs':True,'providerObserved':False,'modelExecuted':False,'accountSignedIn':False}
    finally:
        owner.close()


def blocker(contract,category):
    identity=contract.get('id','')
    if identity not in IDS:
        return None
    if identity in PURE and category not in TEXT:
        return {'kind':'not_applicable','reason':f'Exact {identity} projects supplied metadata/event/goal-expectation state or resolves a configured command descriptor. It does not execute a model, admit account authority, compare a shared store revision or start a resumable worker.'}
    if identity in {'providers.codex.lock','providers.rpc.backoff'} and category in {'offline','interrupted'}:
        return {'kind':'not_applicable','reason':f'Exact {identity} probes one root-local OS lock, computes retry state or refuses an absent pending local run before transport. It has no endpoint operation or durable interruption result.'}
    if identity=='providers.rpc.backoff' and category not in TEXT:
        return {'kind':'not_applicable','reason':'Exact retry-delay increment runs synchronously under the connection start lock and stores no durable state, permission grant, transport observation or shared revision; actual startup failure/unavailable child is exercised at connection owners.'}
    if identity in {'providers.codex.lock','providers.codex.writer','providers.codex.live'} and category in {'concurrency','stale','permissions','interrupted','offline'}:
        return {'kind':'not_applicable','reason':f'Exact {identity} is a read-only current OS ownership observation, including real occupied/released Windows lock within every fixture. It has no writer/CAS/resumable worker or permission decision; source-sharing denial is the measured ownership signal, not an attempted model grant.'}
    if category in {'concurrency','stale','interrupted'} and identity not in {'providers.rpc.response','providers.codex.wire','providers.process.hidden','providers.codex.answer','providers.codex.lifecycle'} and not(identity=='providers.codex.page' and category=='stale'):
        return {'kind':'not_applicable','reason':f'Exact {identity} projects one bounded supplied protocol response or request; no cross-request CAS/shared durable-store or resumable interruption guarantee is admitted in this invariant. Actual concurrent RPC response routing and generation refusal are exercised separately.'}
    return None
