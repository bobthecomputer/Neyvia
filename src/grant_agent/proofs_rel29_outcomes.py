"""Release-29 owner outcomes on disposable local state; no provider calls."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
import uuid


def refused(action, errors=(ValueError, AssertionError)):
    try:
        action()
    except errors as error:
        return str(error)
    raise AssertionError('Invalid outcome was admitted')


def agents(root):
    from .agents_overview import overview, check_graph
    from .neyvia_nightshift import call
    from .proofs_local_session_fixture import service_for
    service,broker,transport = service_for(root)
    try:
        with patch('grant_agent.nightshift.workspace_for',lambda *args,**kwargs:service):
            task = call(service, 'nightshift.create', {'title':'Local pending review','prompt':'Read local evidence',
                        'owner':'Paul','folder':str(root)})
        identity = task['id']
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            graph = overview(service)
            if not graph.get('loading') and any(row.get('id')=='nightshift:'+identity for row in graph['nodes']):
                break
            time.sleep(.05)
        else:
            raise AssertionError('Persisted pending task absent from refreshed live graph: '+json.dumps(graph))
        check_graph(graph)
        node = next(row for row in graph['nodes'] if row['id']=='nightshift:'+identity)
        assert node['newTokens'] is None and node['state']=='waiting', json.dumps(node)
        for mutation in ('duplicate','cycle','edge','tokens','totals'):
            changed = deepcopy(graph)
            if mutation=='duplicate': changed['nodes'].append(deepcopy(node))
            elif mutation=='cycle': changed['nodes'][0]['parentId']=changed['nodes'][0]['id']
            elif mutation=='edge': changed['edges'].append({'from':'missing','to':node['id']})
            elif mutation=='tokens': changed['nodes'][0]['newTokens']=-1
            else: changed['totals']['working']+=1
            refused(lambda: check_graph(changed))
        return {'nodes':len(graph['nodes']),'totals':graph['totals'],'revision':graph['revision'],
                'persistedWaitingTask':identity,'invalidGraphsRefused':5,'boundary':'Actual cached aggregate over persisted local owners; no provider run'}
    finally:
        broker.close()
        service.close()


def autopilot(root):
    from . import neyvia_autopilot as owner
    from .neyvia_workspace_tools import WorkspaceTools
    service = WorkspaceTools(root)
    try:
        from . import neyvia_manuals as manuals
        _,_,manual=manuals.get_manual('notes',root/'.neyvia')
        scope={entry['tool'] for chapter in manual['chapters'].values()
               for group in ('actions','checks') for entry in chapter[group].values()}
        rows = owner.catalog(service, None, scope)
        assert rows, 'Live scoped catalog has no notes procedure'
        row = rows[0]
        canonical = row['id']
        assert owner.resolve_manual_id('manuals/'+canonical+'.manual.json',rows)==canonical
        assert owner.resolve_manual_id('unknown-alias',rows,chapter=row['chapter'],procedure=row['procedure'])==canonical
        refused(lambda: owner.resolve_manual_id('nonexistent',rows))
        selected = {'id':'nonexistent','chapter':'missing','procedure':'missing','inputsJson':'{}',
                    'verify':{'tool':'','argsJson':'{}','path':'','op':'eq','expectedJson':'true'}}
        run = {'runId':uuid.uuid4().hex,'status':'planning','items':[],'startedAt':time.time(),'maxSeconds':60,'maxModelCalls':4,
               'models':[],'tokens':{},'efficiency':False,'text':'Select a live notes manual'}
        owner.save(service,run)
        calls=[]
        def provider(prompt,schema,folder,**kwargs):
            calls.append(deepcopy(schema))
            answer=deepcopy(selected)
            if len(calls)>1: answer.update({key:row[key] for key in ('id','chapter','procedure')})
            return {'answer':{'selection':answer,'guidance':'','reason':'finite catalog decision'},
                    'model':'local-selection-fixture','tokens':{},'elapsedMs':0,'receiptPath':''}
        with patch('grant_agent.autopilot_model.decide',provider):
            answer=owner.selection_model(service,run,'frontier','Select a grounded procedure',owner.RECOVERY,rows)
        assert answer['selection']['id']==canonical and len(calls)==2 and len(run['manualSelectionRetries'])==1
        assert all(set(call['properties']['selection']['properties']['id']['enum'])=={'',*[r['id'] for r in rows]} for call in calls)
        assert len(run['models'])==2 and not run.get('items'), 'Selection must not dispatch or replay effects'
        return {'catalogIds':sorted({r['id'] for r in rows}),'aliasResolved':True,'invalidSelectionCalls':len(calls),
                'budgetAccounted':len(run['models']),'effectsDispatched':0,'boundary':'Live scoped manual catalog and production planner accounting; finite decision transport fixture'}
    finally:
        service.close()


def memory(root):
    from .cue_memory import MemoryContext
    from .neyvia_memory_tools import launcher_scope, launcher_context
    host, project, runtime = root/'host', root/'project', root/'chat-runtime'
    context=MemoryContext(host,'fixture-owner',project,source_id='fixture-chat')
    stream=io.StringIO(); handler=logging.StreamHandler(stream)
    logger=logging.getLogger('grant_agent.neyvia_memory_tools');logger.addHandler(handler)
    try:
        with patch.dict(os.environ,{'NEYVIA_MEMORY_HOST_ROOT':str(host),'NEYVIA_MEMORY_SCOPE':launcher_scope(context)}):
            admitted=launcher_context(runtime,project=project)
            assert admitted==context and admitted.root==host.resolve()
            assert launcher_context(runtime,project=root/'other-project') is None
            with patch.dict(os.environ,{'NEYVIA_MEMORY_HOST_ROOT':str(runtime)}):
                assert launcher_context(runtime,project=project) is None
            for invalid in ('{','[]','null',json.dumps({'root':str(host),'owner':'','project_path':str(project)})):
                with patch.dict(os.environ,{'NEYVIA_MEMORY_SCOPE':invalid}):
                    assert launcher_context(runtime,project=project) is None
        assert all(value not in stream.getvalue() for value in ('fixture-owner',str(host),str(project),'fixture-chat'))
        with patch.dict(os.environ,{'NEYVIA_MEMORY_SCOPE':''}): assert launcher_context(runtime) is None
        return {'trustedHostBound':True,'separateRuntimeAccepted':True,'mismatchedAndMalformedDisabled':6,'contentFreeLog':stream.getvalue().splitlines()}
    finally:
        logger.removeHandler(handler)


def comments(root):
    from .neyvia_comments import Store, call
    from .proofs_local_session_fixture import service_for
    service,broker,transport=service_for(root)
    try:
        row=call(service,'comments.add',{'target':'fixture.txt','targetKind':'artifact','anchor':{'kind':'text','path':'fixture.txt','startLine':1,'endLine':1},'text':'Verify this change'})['comment']
        call(service,'comments.edit',{'id':row['id'],'text':'Read the changed file','expectedRevision':1})
        refused(lambda: call(service,'comments.edit',{'id':row['id'],'text':'stale','expectedRevision':1}))
        store=Store(root)
        for table in ('events','deliveries'):
            with store.connect(write=True) as db:
                if table=='deliveries': store.record(db,'append-only','fingerprint','failed',{'ok':False})
            for operation in ('UPDATE '+table+' SET seq=seq','DELETE FROM '+table):
                refused(lambda: _sql(store,operation), (sqlite3.IntegrityError,))
        # The existing broker is a finite local receiver here: acceptance comes
        # from a real persisted connected-session turn, never an invented send.
        result=call(service,'comments.send',{'id':row['id'],'requestId':'comments-success',
                    'newSession':{'app':'codex','cwd':str(root)}})
        assert result['ok'] and result['runId']
        replay=call(service,'comments.send',{'id':row['id'],'requestId':'comments-success',
                    'newSession':{'app':'codex','cwd':str(root)}})
        assert replay['replayed'] and replay['messageId']==result['messageId']
        with patch.object(broker,'send',side_effect=RuntimeError('controlled receiver rejection')):
            args={'id':row['id'],'requestId':'comments-failure','sessionId':'fixture-session'}
            refused(lambda: call(service,'comments.send',args))
            refused(lambda: call(service,'comments.send',args))
        call(service,'comments.delete',{'id':row['id']})
        assert not call(service,'comments.list',{})['comments']
        persisted=Store(root)
        with persisted.connect() as db:
            latest=persisted.get(db,row['id']); count=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            assert latest['status']=='deleted' and count>=4
            assert persisted.delivery(db,'comments-failure')['state']=='failed'
        return {'events':count,'tombstonePersisted':True,'immutableTables':2,'acceptedDelivery':result['runId'],
                'replaySameReceipt':True,'failedRetryRefused':True,'boundary':'Actual comment store and broker with finite local adapter; no external session send'}
    finally:
        broker.close()
        service.close()


def _sql(store,statement):
    with store.connect(write=True) as db: db.execute(statement)



def film_presentation(root):
    """Exercise the shipped transcript parser and pure presentation owners."""
    import subprocess
    from .connected_sessions.claude_transcript import ItemStore
    envelope = '<agent-message from="Pear">[Subagent hand-back] internal authority. The report follows:\n  Retained report bytes.</agent-message>'
    notification = '<task-notification><task-id>helper-2</task-id><status>failed</status><result>Exact failure report</result></task-notification>'
    path=root/'transcript.jsonl'
    path.write_text(''.join(json.dumps({'type':'user','uuid':str(i),'timestamp':'2026-10-09T10:00:00Z','message':{'role':'user','content':[{'type':'text','text':text}]}})+'\n' for i,text in enumerate((envelope,notification,'Human request'))),encoding='utf-8')
    store=ItemStore(path,'film-fixture',str(root));store.refresh()
    notices=[item for item in store.items if item.kind=='notice' and item.data.get('report')]
    assert [(x.data['helper'],x.data['report']) for x in notices]==[('Pear','Retained report bytes.'),('helper-2','Exact failure report')]
    assert notices[1].data['level']=='error' and not any('internal authority' in json.dumps(item.data) for item in store.items)
    assert [item.data['text'] for item in store.items if item.kind=='user']==['Human request']
    store.refresh();assert len([item for item in store.items if item.data.get('report')])==2
    repo=Path(__file__).resolve().parents[2]
    script = r"""
import assert from 'node:assert/strict';
import { visibleTranscriptItems } from './web/src/neyvia/next/nxTransparencyModel.js';
import { stripView } from './web/src/neyvia/next/nxLayaModel.js';
const notice=id=>({id,kind:'reasoning',data:{exposure:'not_reported'}});
const items=[{id:'u1',kind:'user',data:{}},notice('n1'),notice('n2'),{id:'shared',kind:'reasoning',data:{exposure:'shared',summary:'Kept'}},{id:'u2',kind:'user',data:{}},notice('n3'),{id:'tool',kind:'tool',data:{status:'ok'}},{id:'withheld',kind:'reasoning',data:{exposure:'withheld',hidden:true}}];
for(const level of ['everything','summaries','minimal']) {
 const result=visibleTranscriptItems(items,level);
 assert.ok(result.some(x=>x.id==='withheld'));
 assert.ok(!result.some(x=>x.id==='n2'));
 if(level!=='minimal') {assert.ok(!result.some(x=>x.id==='n3')); assert.ok(result.some(x=>x.id==='shared'));}
}
for(const savings of [0,null,undefined,-1]) {
 const v=stripView({totals:{answered:0,escalated:3,tokensSavedEstimate:savings},service:{ready:true}});
 assert.equal(v.text,'LAYA 0/3'); assert.equal(v.tone,'green');
}
assert.equal(stripView({totals:{answered:2,escalated:1,tokensSavedEstimate:25},service:{ready:true}}).text,'LAYA 2/3 · ~25 tok saved');
assert.equal(stripView(null).text,'LAYA —');
console.log(JSON.stringify({quietTurnDeduplicated:true,visibleToolsSuppressNotice:true,withheldPreserved:true,zeroSavingsHidden:true,positiveSavingsKept:true}));
"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=repo,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    return {'parserNotices':len(notices),'humanBubbles':1,'refreshIdempotent':True,**json.loads(result.stdout)}


def film_usage(root):
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from .connected_sessions.claude_usage import ClaudeTranscriptUsage
    from .nightshift_ledger import recover_claude_usage
    start=datetime(2026,10,9,10,tzinfo=timezone.utc);end=datetime(2026,10,9,11,tzinfo=timezone.utc)
    def record(identity,stamp,inp=10):
        return {'type':'assistant','timestamp':stamp,'message':{'id':identity,'model':'claude-haiku-5-5','usage':{'input_tokens':inp,'output_tokens':4,'cache_read_input_tokens':20,'cache_creation_input_tokens':3}}}
    path=root/'session.jsonl';child=path.with_suffix('')/'subagents'/'child.jsonl';child.parent.mkdir(parents=True)
    rows=[record('outside','2026-10-09T09:00:00Z'),record('main','2026-10-09T10:10:00Z'),record('main','2026-10-09T10:10:00Z')]
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    child.write_text(json.dumps(record('child','2026-10-09T10:20:00Z',5))+'\n'+json.dumps(record('late','2026-10-09T12:00:00Z'))+'\n',encoding='utf-8')
    usage=ClaudeTranscriptUsage(start,end);observed=usage.poll(path)
    assert observed['requests']==2 and observed['inputTokens']==61 and observed['cachedInputTokens']==40 and observed['cacheCreationInputTokens']==6 and observed['totalTokens']==69
    assert usage.poll(path) is None
    empty=root/'missing.jsonl';assert ClaudeTranscriptUsage(start,end).poll(empty) is None
    dbpath=root/'attempts.sqlite3'
    def connect():return sqlite3.connect(dbpath)
    with connect() as db:
        db.execute('CREATE TABLE attempts(run_id TEXT PRIMARY KEY,usage TEXT,finished TEXT)');db.execute('INSERT INTO attempts VALUES(?,?,?)',('saved',None,end.isoformat()))
    saved={'sessionId':'exact-session','state':'completed','startedAt':start.isoformat(),'updatedAt':end.isoformat()}
    def locate(identity):
        assert identity=='exact-session';return None,path
    service=SimpleNamespace(connect=connect,broker=SimpleNamespace(store=SimpleNamespace(load=lambda identity:saved if identity=='saved' else None),_adapter=lambda app:SimpleNamespace(_locate=locate)))
    row={'harness':'claude-code','finished':end.isoformat(),'run_id':'saved'}
    assert recover_claude_usage(service,row,{})==observed
    with connect() as db:assert json.loads(db.execute('SELECT usage FROM attempts').fetchone()[0])==observed
    assert recover_claude_usage(service,{**row,'run_id':'absent'}, {})=={}
    assert recover_claude_usage(service,{**row,'finished':None}, {})=={}
    return {'usage':observed,'exactSessionWindowRecovered':True,'missingAndUnfinishedRemainUnknown':True,'durableUsageVerified':True}

CASES=(('agents.live-overview',agents),('autopilot.live-manual-selection',autopilot),
       ('memory.launcher-host-binding',memory),
       (('transparency.helper-reports','transparency.quiet-unreported','efficiency.laya-zero-savings'),film_presentation),
       ('nightshift.claude-session-usage',film_usage),(('comments.append-only','comments.send'),comments))


def self_check(scratch):
    from .contract_gate import wants
    scratch=Path(scratch);cases=[]
    for identities,action in CASES:
        identities=[identities] if isinstance(identities,str) else list(identities)
        active=[identity for identity in identities if wants(identity)]
        if not active: continue
        root=scratch/str(uuid.uuid4());root.mkdir(parents=True)
        try:
            observed=action(root)
            cases.append({'id':active[0],'contracts':active,'ok':True,'observed':observed})
        except Exception as error:
            cases.append({'id':active[0],'contracts':active,'ok':False,'error':type(error).__name__+': '+str(error)})
    return {'ok':bool(cases) and all(case['ok'] for case in cases),'cases':cases,
            'contracts':[identity for case in cases if case['ok'] for identity in case['contracts']]}
