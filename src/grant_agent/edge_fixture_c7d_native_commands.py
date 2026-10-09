"""Actual local native session and signed operator authority edge fixtures."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
CATEGORIES={'empty','huge','unicode','concurrency','interrupted','permissions','offline','stale'}
SESSION_IDS={'native.'+name for name in ('options','refusal','lifecycle','create','restore','cancel','foreign')}
OPERATOR_IDS={'native.operator.'+name for name in ('pinned-verifier','signature','final-gate','wire','retry')}
COMMAND_IDS={'native.commands.'+name for name in ('approval','cancel','deadline','final-gate','idempotency','receipt','scope','secret-free','single-flight','uncertainty')}
COMMAND_CASES={
    'native.commands.approval': {'concurrency','interrupted','stale'},
    'native.commands.cancel': {'concurrency','interrupted','stale'},
    'native.commands.deadline': {'concurrency','interrupted','permissions'},
    'native.commands.final-gate': {'concurrency','interrupted'},
    'native.commands.idempotency': {'concurrency','interrupted','permissions','stale'},
    'native.commands.receipt': {'concurrency','interrupted','permissions','stale'},
    'native.commands.scope': {'concurrency','interrupted','stale'},
    'native.commands.secret-free': {'concurrency','interrupted','permissions','stale'},
    'native.commands.single-flight': {'interrupted','permissions','stale'},
    'native.commands.uncertainty': {'concurrency','interrupted','permissions'},
}
IDS=SESSION_IDS|OPERATOR_IDS|COMMAND_IDS
TEXT={'empty':'','huge':'owned bounded input '*4096,'unicode':'雪 café e\u0301 العربية'}
AUDITS={}
for identity in OPERATOR_IDS:
    AUDITS[(identity,'offline')]=f"Exact {identity} consumes a supplied public verifier, canonical signing bytes or selected local SQLite authority. It has no remote signer, provider endpoint or transport operation; actual cryptographic verification is performed locally, and physical device delivery remains separate. Connectivity outage has no mechanism at this owner."
AUDITS[('native.operator.pinned-verifier','interrupted')]="Exact OperatorDecisionVerifier.__init__/status synchronously reads an explicitly selected public PEM and returns an in-memory verifier/status. It writes no key or durable approval and starts no worker. A caller exit cannot leave a partially committed authority at this loader; signed decision persistence is separately exercised."
AUDITS[('native.operator.wire','interrupted')]="Exact signing-wire preparation/inspection/validation synchronously reads a pending approval and returns or validates bytes, without persisting a signature or launching a resumable worker. There is no wire mutation to interrupt. Actual exit after committed signature and retry is exercised under native.operator.retry."
for identity in SESSION_IDS:
    AUDITS[(identity,'offline')]=f"Exact {identity} reads the selected local conversation/catalog/run store or dispatches into the supplied in-process backend. It accepts no network address and establishes no network connection. The actual executor process boundary is exercised separately without attributing provider/model or remote connectivity proof to this local adapter owner."
for identity in ('native.options','native.refusal','native.foreign'):
    AUDITS[(identity,'interrupted')]=f"Exact {identity} is a synchronous read/projection or pre-mutation request admission. It owns no durable writer or background worker to leave partially committed state on caller exit. Lifecycle dispatch interruption is independently exercised under native.lifecycle/create/restore."
for category in ('huge','unicode'):
    AUDITS[('native.cancel',category)]="Exact _cancel receives an internally generated ASCII turn identifier bounded by the chat-run store, not message text, attachment bytes or a free-form identifier. Unicode/oversized message admission has no input path at this acknowledgement owner; actual stop registration, stale retry and OS denial are exercised separately."


def require(value,message):
    if not value: raise AssertionError(message)


def refuse(action,types=(ValueError,PermissionError,KeyError,sqlite3.Error)):
    try: action()
    except types as error: return {'type':type(error).__name__,'message':str(error)[:800]}
    raise AssertionError('Forbidden/adverse actual owner call succeeded')


def _authority(root, category):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from .native_pairing import NativePairingStore
    from .native_device_operator_authority import OperatorAuthorizedDeviceCommandStore
    from .native_device_operator_signing_wire import prepare_signing_request,inspect_signing_request
    workspace=root/'workspace';workspace.mkdir()
    private=Ed25519PrivateKey.generate();public=private.public_key()
    path=root/('public-雪.pem' if category=='unicode' else 'public-verifier.pem')
    path.write_bytes(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    key_id='sha256:'+hashlib.sha256(public.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).hexdigest()
    pairing=NativePairingStore(workspace);request=pairing.create('phone',scopes=['device.commands'])
    device=pairing.redeem(request['pairingId'],request['pairingToken'],'Owned local protocol fixture')
    store=OperatorAuthorizedDeviceCommandStore(workspace,operator_public_key_path=path,operator_key_id=key_id)
    store.publish_capabilities(device['deviceId'],device['deviceSecret'],['app.open'])
    arguments={'route':TEXT.get(category,'owned'),'enabled':True,'ordinal':1}
    if category=='huge':arguments={'route':'owned','bounded':'x'*15000}
    context={'actor_id':'agent:owned','session_id':'session:owned','run_id':'run:owned'}
    requested=store.request_approval(device['deviceId'],'app.open',arguments=arguments,**context)
    wire=prepare_signing_request(store,requested['approvalId'],decided_by='human:owned',note=TEXT.get(category,'owned note')[:500])
    inspected=inspect_signing_request(wire)
    signature=base64.b64encode(private.sign(inspected['signingBytes'])).decode('ascii')
    return store,device,private,path,key_id,requested,wire,signature,arguments,context


def _approval_rows(store):
    with store.connection() as db:
        return {table:[list(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in ('device_command_approvals','device_command_operator_authority','device_commands')}


def _signed_child(root,path,key_id,wire,signature,*,enqueue=False,device=None,arguments=None,context=None):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    program="import os,sys,json;from pathlib import Path;from grant_agent.proof_credential_guard import install;r=Path(sys.argv[1]);install(r);from grant_agent.native_device_operator_authority import OperatorAuthorizedDeviceCommandStore;from grant_agent.native_device_operator_signing_wire import submit_operator_signature;d=json.load(sys.stdin);s=OperatorAuthorizedDeviceCommandStore(r/'workspace',operator_public_key_path=r/d['path'],operator_key_id=d['key']);submit_operator_signature(s,d['wire'],signature_base64=d['signature']);"
    if enqueue:program+="s.enqueue(d['device'],'app.open',arguments=d['arguments'],idempotency_key='owned-after-exit',approval_id=d['wire']['approvalId'],**d['context']);"
    program+="os._exit(23)"
    payload={'path':path.name,'key':key_id,'wire':wire,'signature':signature,'device':device['deviceId'] if device else None,'arguments':arguments,'context':context}
    result=subprocess.run([sys.executable,'-c',program,str(root)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf8',timeout=40,env={**os.environ,'PYTHONPATH':str(REPO/'src')},**hidden_windows_subprocess_kwargs())
    require(result.returncode==23,'Actual signed-authority caller did not exit after owner commit: '+result.stderr[-2000:])
    return result.returncode


def _operator(root,identity,category):
    from .native_device_operator_authority import OperatorDecisionVerifier,OperatorAuthorizedDeviceCommandStore,OPERATOR_DECISION_SCHEMA
    from .native_device_operator_signing_wire import inspect_signing_request,submit_operator_signature,validate_signing_request_against_store
    from .edge_fixture_models import _deny_read
    store,device,private,path,key_id,requested,wire,signature,arguments,context=_authority(root,category)
    before=_approval_rows(store)
    def submit():return submit_operator_signature(store,wire,signature_base64=signature)
    def reopen():return OperatorAuthorizedDeviceCommandStore(store.root,operator_public_key_path=path,operator_key_id=key_id)
    if identity.endswith('pinned-verifier'):
        status=OperatorDecisionVerifier(store.root,public_key_path=path,key_id=key_id).status()
        require(status['ready'] and status['publicKeyPinnedOutsideWorkspace'] and not status['privateKeyLoaded'],'Actual external public verifier readiness was false')
        if category=='empty':
            from .native_device_operator_authority import OperatorDecisionVerifier
            require(not OperatorDecisionVerifier(store.root,public_key_path='',key_id='').status()['ready'],'Missing public verifier invented readiness')
        elif category=='huge':refuse(lambda:OperatorDecisionVerifier(store.root,public_key_path=path,key_id='sha256:'+'a'*65537))
        elif category=='permissions':
            with _deny_read(path):refuse(lambda:OperatorDecisionVerifier(store.root,public_key_path=path,key_id=key_id))
        elif category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:OperatorDecisionVerifier(store.root,public_key_path=path,key_id=key_id).status(),range(8)))
            require(all(row==status for row in rows),'Concurrent public verifier reads disagreed')
        elif category=='stale':
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            path.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            refuse(lambda:OperatorDecisionVerifier(store.root,public_key_path=path,key_id=key_id))
        require(_approval_rows(store)==before,'Public verifier loading changed durable approval authority')
        return {'actualEd25519PublicLoader':True,'externalToMutableWorkspace':True,'privateKeyPersisted':False,'actualAuthorityUnchanged':True}
    if identity.endswith('wire'):
        inspected=inspect_signing_request(wire)
        require(inspected['review']['arguments']==arguments and hashlib.sha256(inspected['signingBytes']).hexdigest()==wire['signingBytesSha256'],'Actual signing bytes lost review/digest transaction')
        if category=='empty':refuse(lambda:inspect_signing_request({}))
        elif category=='huge':
            edited=copy.deepcopy(wire);edited['signingBytesBase64']='A'*65537;refuse(lambda:inspect_signing_request(edited))
        elif category=='unicode':require('雪'.encode() in inspected['signingBytes'],'Actual canonical signing bytes lost Unicode')
        elif category=='permissions':
            with _deny_read(store.path):refuse(lambda:validate_signing_request_against_store(store,wire))
        elif category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(lambda _:validate_signing_request_against_store(store,wire),range(8)))
            require(all(row['signingBytes']==inspected['signingBytes'] for row in rows),'Concurrent wire validation changed exact bytes')
        elif category=='stale':
            with store.connection(immediate=True) as db:db.execute('UPDATE device_command_approvals SET arguments_json=? WHERE approval_id=?',(json.dumps({'route':'changed'}),requested['approvalId']))
            refuse(lambda:validate_signing_request_against_store(store,wire))
        else:raise AssertionError('Unknown wire category')
        if category!='stale':require(_approval_rows(store)==before,'Wire preparation/validation created authority')
        return {'actualCanonicalSigningBytes':len(inspected['signingBytes']),'privateKeyRequiredByNeyvia':False,'editedWireRejected':category in {'empty','huge','stale'}}
    if category=='permissions':
        with _deny_read(store.path):refuse(submit)
        require(_approval_rows(store)==before,'OS-denied signature submission changed authority')
        if identity.endswith('final-gate'):
            submit();command=store.enqueue(device['deviceId'],'app.open',arguments=arguments,idempotency_key='owned-final-denial',approval_id=requested['approvalId'],**context)
            before=_approval_rows(store)
            with _deny_read(store.path):refuse(lambda:store.claim(device['deviceId'],device['deviceSecret']))
            require(_approval_rows(store)==before,'OS-denied final claim consumed authority')
        return {'actualWindowsSQLiteReadDenial':True,'independentAuthorityRowsPreserved':True}
    if category in {'empty','huge'}:
        edited=copy.deepcopy(wire)
        bad='' if category=='empty' else 'A'*65537
        refuse(lambda:submit_operator_signature(store,edited,signature_base64=bad))
        require(_approval_rows(store)==before,'Rejected signature length changed authority')
    if category=='stale':
        if identity.endswith('signature') or identity.endswith('retry'):
            second=store.request_approval(device['deviceId'],'app.open',arguments=arguments,**context)
            edited=copy.deepcopy(wire);edited['approvalId']=second['approvalId'];refuse(lambda:submit_operator_signature(store,edited,signature_base64=signature))
            require(store.get_approval(second['approvalId'])['status']=='pending','Replay minted another approval')
        elif identity.endswith('final-gate'):
            submit();command=store.enqueue(device['deviceId'],'app.open',arguments=arguments,idempotency_key='owned-tamper',approval_id=requested['approvalId'],**context)
            with store.connection(immediate=True) as db:db.execute('UPDATE device_command_approvals SET decided_by=? WHERE approval_id=?',('human:tampered',requested['approvalId']))
            require(store.claim(device['deviceId'],device['deviceSecret']) is None,'Tampered durable authority passed actual final claim gate')
            require(store.get(command['commandId'])['errorCode']=='authorization-invalid','Tampered final gate lost explicit refusal')
            return {'actualDurableTamperReverified':True,'physicalDeviceExecutionProven':False}
    if category=='interrupted':_signed_child(root,path,key_id,wire,signature,enqueue=identity.endswith('final-gate'),device=device,arguments=arguments,context=context)
    decided=reopen().get_approval(requested['approvalId']) if category=='interrupted' and identity.endswith('final-gate') else submit()
    require(decided['status'] in {'approved','consumed'} and decided['operatorDecisionSignatureVerified'] and not decided['humanIdentityCryptographicallyVerified'],'Actual cryptographic decision lost its exact local authority boundary')
    if category=='concurrency':
        with ThreadPoolExecutor(max_workers=8) as pool:decisions=list(pool.map(lambda _:submit(),range(8)))
        require(all(row['approvalId']==requested['approvalId'] and row['operatorDecisionSignatureVerified'] for row in decisions),'Concurrent exact-signature retries disagreed')
    if identity.endswith('retry'):
        first=_approval_rows(store);second=submit();require(_approval_rows(store)==first and second['approvalId']==requested['approvalId'],'Lost acknowledgement retry changed durable authority or minted an approval')
    if identity.endswith('final-gate'):
        if category=='interrupted':
            with store.connection() as db: command_id=db.execute('SELECT command_id FROM device_commands').fetchone()[0]
            command=store.get(command_id)
        else:command=store.enqueue(device['deviceId'],'app.open',arguments=arguments,idempotency_key='owned-final',approval_id=requested['approvalId'],**context)
        if category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(lambda _:store.claim(device['deviceId'],device['deviceSecret']),range(8)))
            require(sum(row is not None for row in claims)==1,'Concurrent final gate delivered one command more than once')
            claim=next(row for row in claims if row is not None)
        else:claim=reopen().claim(device['deviceId'],device['deviceSecret'])
        require(claim['commandId']==command['commandId'] and claim['arguments']==arguments,'Actual final gate delivered a different transaction')
    rows=_approval_rows(store)
    require(len(rows['device_command_operator_authority'])==1,'Actual decision/retry minted duplicate authority rows')
    return {'actualEd25519SignatureVerified':True,'durableAuthorityRows':1,'actualCallerExit':23 if category=='interrupted' else None,'humanIdentityProven':False,'physicalDeviceExecutionProven':False}


def _session_backend(root, *, fail=False):
    """Keep production dispatch/persistence; replace only external execution."""
    import threading
    from types import SimpleNamespace
    from .web_backend import FluxioWebBackend
    from .neyvia_conversations import NeyviaConversationStore
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    store=NeyviaConversationStore(root)
    backend=object.__new__(FluxioWebBackend)
    backend.root=root;backend._neyvia_mcp=SimpleNamespace(conversations=store)
    backend._lazy_services_lock=threading.RLock();backend._agent_chat_persistence_lock=threading.RLock()
    backend._agent_chat_persistence_inflight={};backend._provider_env=lambda:{}
    observations=[]
    def finite(payload):
        from .chat_stream import append_chat_stream
        program="let input='';for await(const c of process.stdin)input+=c;const d=JSON.parse(input);if(d.fail)process.exit(23);process.stdout.write(JSON.stringify({reply:'Owned finite protocol reply: '+d.message.slice(0,256)}));"
        child=subprocess.run(['node','--input-type=module','-e',program],input=json.dumps({'message':payload['message'],'fail':fail}),capture_output=True,text=True,encoding='utf8',timeout=30,**hidden_windows_subprocess_kwargs())
        observations.append({'exitCode':child.returncode,'inputCharacters':len(payload['message']),'externalModelExecuted':False})
        if child.returncode:raise RuntimeError('Owned finite protocol child exited '+str(child.returncode))
        parsed=json.loads(child.stdout)
        append_chat_stream(root,payload['assistantTurnId'],{'kind':'runtime.answer_delta','message':parsed['reply']})
        return {'reply':parsed['reply'],'runtime':payload['runtime'],'sessionId':payload['sessionId'],'route':payload['route'],'status':'completed','elapsedMs':1,'filesChanged':[]}
    backend._run_neyvia_chat=finite
    return backend,store,observations


def _session(root,identity,category):
    from contextlib import ExitStack
    from datetime import datetime,timezone,timedelta
    from .connected_sessions.neyvia import create_adapter,_Run
    from .connected_sessions.neyvia_items import LiveTurn
    from .connected_sessions.model import TurnOptions
    from .connected_sessions.broker import ConnectedError
    from .chat_run_control import active_chat_run,chat_run_status
    from .edge_fixture_models import _deny_read
    backend,store,observations=_session_backend(root,fail=category=='interrupted')
    adapter=create_adapter(backend)
    options=TurnOptions(model='neyvia-agent|openai-codex|gpt-5.6-sol',permission_mode='workspace')
    def count():return len(adapter._query('SELECT conversation_id FROM conversations'))
    def turn(sid=None,message=None,opts=None,run_id=None):
        events=[];error=None
        try:result=adapter.start_turn(sid,TEXT.get(category,'owned message') if message is None else message,opts or options,cwd=str(root),run_id=run_id or uuid.uuid4().hex,emit=events.append)
        except (ConnectedError,sqlite3.Error,OSError) as exc:result=None;error=exc
        return result,events,error
    if identity=='native.options':
        sid=None if category=='empty' else adapter._sid('missing-'+TEXT.get(category,'owned'))
        if category=='permissions':
            row=store.create_conversation();sid=adapter._sid(row['conversationId'])
            with _deny_read(store.database_path):refuse(lambda:adapter.options(sid),(sqlite3.Error,OSError))
            return {'actualWindowsSQLiteReadDenial':True,'conversationRows':count()}
        before=count()
        if category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:adapter.options(sid),range(8)))
            require(all(row==results[0] for row in results),'Concurrent actual catalog options disagreed')
            result=results[0]
        else:result=adapter.options(sid)
        require(result['models'] and result['runtimes'] and sum(bool(row['default']) for row in result['models'])==1,'Actual catalog/default selection was not truthful and unique')
        require(count()==before,'Actual options lookup created conversations')
        return {'actualCatalogRows':len(result['models']),'uniqueDefault':True,'missingSessionFallback':sid is not None,'unchangedDurableStore':True}
    if identity=='native.refusal':
        opts=TurnOptions(model=options.model,permission_mode='invalid-雪' if category=='unicode' else 'invalid')
        sid=None
        if category=='empty':opts=TurnOptions(model=options.model,permission_mode='workspace',images=[{'mime':'image/png','data':''}])
        if category=='huge':opts=TurnOptions(model=options.model,permission_mode='workspace',images=[{'mime':'image/png','data':'YQ=='}]*7)
        if category=='stale':sid=adapter._sid('does-not-exist');opts=options
        if category=='permissions':
            row=store.create_conversation()
            with store._connection() as db:
                db.execute('UPDATE conversations SET archived_at=? WHERE conversation_id=?',('2020-01-01T00:00:00Z',row['conversationId']));db.commit()
            sid=adapter._sid(row['conversationId'])
        before=count()
        def invalid(_):
            result,events,error=turn(sid,'owned',opts)
            require(isinstance(error,ConnectedError) and not events and result is None,'Rejected request mutated/emitted before admission')
            return type(error).__name__
        if category=='concurrency':
            with ThreadPoolExecutor(max_workers=8) as pool:rejections=list(pool.map(invalid,range(8)))
        else:rejections=[invalid(0)]
        require(count()==before and not observations and not adapter._runs,'Actual refused input created a conversation, worker or retained ownership')
        if category=='permissions':require(adapter._row(row['conversationId'])['archivedAt'] is not None,'Invalid permission restored archived conversation')
        return {'actualAdmissionRefusals':len(rejections),'emittedEvents':0,'conversationCountUnchanged':True,'protocolChildren':0}
    if identity=='native.cancel':
        live=LiveTurn('owned-session','owned-cancel-turn',1);run=_Run('owned-run','owned-conversation','owned-cancel-turn',live)
        if category=='empty':
            adapter._cancel(run);require(run.cancel_sent>0 and not run.cancel_ok,'Unregistered cancellation manufactured an acknowledgement')
        elif category=='interrupted':
            from .subprocess_utils import hidden_windows_subprocess_kwargs
            program="import os,sys;from pathlib import Path;from grant_agent.chat_run_control import active_chat_run\nwith active_chat_run(Path(sys.argv[1]),sys.argv[2]):os._exit(23)"
            child=subprocess.run([sys.executable,'-c',program,str(root),run.turn_id],capture_output=True,timeout=30,**hidden_windows_subprocess_kwargs())
            require(child.returncode==23,'Actual registered caller did not exit23')
            adapter._cancel(run);require(run.cancel_ok,'Dead actual registered owner was not reconciled by cancellation')
        else:
            if category=='stale':adapter._cancel(run);require(not run.cancel_ok,'Cancellation acknowledged a missing stale registration')
            with active_chat_run(root,run.turn_id):
                if category=='permissions':
                    path=root/'.agent_control/chat_runs'/f'{run.turn_id}.json'
                    before=path.read_bytes()
                    with _deny_read(path):adapter._cancel(run)
                    require(not run.cancel_ok and path.read_bytes()==before,'OS-denied cancellation claimed acknowledgement or changed registration')
                elif category=='concurrency':
                    runs=[_Run(str(i),run.conversation_id,run.turn_id,LiveTurn('owned-session',run.turn_id,1)) for i in range(8)]
                    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(adapter._cancel,runs))
                    require(all(r.cancel_ok and r.cancel_sent>0 for r in runs),'Concurrent actual stop requests lost acknowledgements')
                else:adapter._cancel(run);require(run.cancel_ok,'Actual late registration cancellation was not acknowledged')
        return {'actualBackendCancellationDispatch':True,'actualAcknowledgement':run.cancel_ok,'actualRegisteredCallerExit':23 if category=='interrupted' else None,'processKillRequested':False}
    if identity=='native.foreign':
        if category=='empty':require(adapter._foreign_runs()=={},'Empty real foreign-run store invented work');return {'actualEmptyForeignRunScan':True}
        n=32 if category=='huge' else 1
        with ExitStack() as stack:
            cids=[]
            for number in range(n):
                now=datetime.now(timezone.utc).isoformat()
                row=store.create_conversation(conversation_id=('conversation-雪' if category=='unicode' else 'conversation-owned')+str(number),title=TEXT.get(category,'owned')[:500])
                store.append_turn(row['conversationId'],role='user',content=TEXT.get(category,'owned') or 'owned',now=now)
                cids.append(row['conversationId']);stack.enter_context(active_chat_run(root,'owned-foreign-'+str(number)))
            if category=='stale':
                with store._connection() as db:
                    db.execute('UPDATE conversation_turns SET created_at=?',((datetime.now(timezone.utc)-timedelta(seconds=601)).isoformat(),));db.commit()
                require(adapter._foreign_runs()=={},'Stale saved request exceeded attribution window but remained assigned')
            elif category=='permissions':
                path=root/'.agent_control/chat_runs/owned-foreign-0.json'
                with _deny_read(path):require(adapter._foreign_runs()=={},'Unreadable actual foreign run was invented as active')
            elif category=='concurrency':
                with ThreadPoolExecutor(max_workers=8) as pool:maps=list(pool.map(lambda _:adapter._foreign_runs(),range(8)))
                require(all(m==maps[0] for m in maps) and len(maps[0])==n,'Concurrent attribution reads disagreed')
            else:
                matched=adapter._foreign_runs();require(set(matched)==set(cids) and len(set(matched.values()))==n,'Actual foreign runs were not attributed one-to-one')
        return {'actualRegisteredForeignRuns':n,'actualSavedUserRequests':n,'nearestTimestampMatching':True,'foreignExecutionProven':False}
    require(identity in {'native.lifecycle','native.create','native.restore'},'Unknown native session contract')
    sid=None
    if identity=='native.restore':
        row=store.create_conversation(title=TEXT.get(category,'owned')[:500])
        with store._connection() as db:
            db.execute('UPDATE conversations SET archived_at=? WHERE conversation_id=?',('2020-01-01T00:00:00Z',row['conversationId']));db.commit()
        sid=adapter._sid(row['conversationId'])
    if category=='permissions':
        before=count()
        with _deny_read(store.database_path):result,events,error=turn(sid,'owned')
        require(error is not None and not events and count()==before and not adapter._runs,'OS-denied create/restore changed durable sessions or ownership')
        if sid:require(adapter._row(row['conversationId'])['archivedAt'] is not None,'OS-denied restore unarchived a conversation')
        return {'actualWindowsSQLiteDenialBeforeEvents':True,'conversationCountUnchanged':True}
    if category=='stale' and sid:
        # Caller snapshot says archived; actual durable row has already been restored.
        store.restore_conversation(row['conversationId'])
    if category=='concurrency':
        if sid:
            archived=[sid]
            for _ in range(7):
                created=store.create_conversation()
                with store._connection() as db:
                    db.execute('UPDATE conversations SET archived_at=? WHERE conversation_id=?',('2020-01-01T00:00:00Z',created['conversationId']));db.commit()
                archived.append(adapter._sid(created['conversationId']))
            with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(lambda s:turn(s,'owned concurrent restore'),archived))
            require(all(not adapter._row(adapter._conversation_id(s))['archivedAt'] for s in archived),'Concurrent admitted sends did not durably restore each selected conversation')
        else:
            with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(lambda i:turn(None,'owned concurrent '+str(i),run_id='owned-'+str(i)),range(8)))
    else:outcomes=[turn(sid)]
    for result,events,error in outcomes:
        require(events and events[0]['type']=='session.updated' if sid is None else bool(events),'Actual creation did not emit initial session before user')
        require(events[-1]['type']=='session.updated' and not adapter._runs,'Actual adapter lost terminal summary or ownership cleanup')
        emitted_session=events[-1]['session']['id']
        require(all(event.get('sessionId',emitted_session)==emitted_session and (event.get('session') or {}).get('id',emitted_session)==emitted_session for event in events),'Actual emitted events disagreed on session identity')
        if category not in {'interrupted','empty'}:require(error is None,'Actual finite protocol journey failed: '+str(error))
        if category=='interrupted':require(observations and observations[-1]['exitCode']==23 and any(event.get('type')=='run.state' and event.get('state')=='failed' for event in events),'Actual nonzero executor process was hidden in terminal events')
        if result:
            current=adapter._row(adapter._conversation_id(result));require(current['metadata'].get('workspacePath')==str(root) if sid is None else not current['archivedAt'],'Actual durable workspace/restore disagreed with emitted session')
    return {'actualBackendDispatch':True,'actualFiniteProtocolProcesses':observations,'turnJourneys':len(outcomes),'terminalSummaries':len(outcomes),'durableConversationRows':count(),'retainedAdapterRuns':len(adapter._runs),'providerModelExecutionProven':False,'archivedInputEstablishedAsFixture':bool(sid)}


def _session_child(root,identity,category):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    from .proof_ports import c7_port_block
    port = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))[0]
    env=os.environ.copy()
    env.update(PYTHONPATH=str(REPO/'src'),FLUXIO_WEB_BACKEND_URL=f'http://127.0.0.1:{port}',NEYVIA_COORDINATOR_AUTOSTART='0',FLUXIO_WATCHDOG_AUTOSTART='0')
    for key in ('NEYVIA_NAS_ROOT','FLUXIO_NAS_ROOT','CODEX_HOME','HOME','USERPROFILE'):env[key]=str(root)
    program="import sys,json;from pathlib import Path;from grant_agent.proof_credential_guard import install;root=Path(sys.argv[1]);install(root);from grant_agent.edge_fixture_c7d_native_commands import _session;print(json.dumps(_session(root,sys.argv[2],sys.argv[3]),ensure_ascii=True))"
    child=subprocess.run([sys.executable,'-c',program,str(root),identity,category],env=env,capture_output=True,text=True,encoding='utf8',timeout=150,**hidden_windows_subprocess_kwargs())
    require(child.returncode==0,'Actual native fixture worker failed: '+child.stderr[-3500:])
    return json.loads(child.stdout.strip().splitlines()[-1])


def blocker(contract,category):
    reason=AUDITS.get((contract['id'],category))
    return {'kind':'not_applicable','reason':reason} if reason else None


def run(root,contracts,categories):
    from .proof_credential_guard import install
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);install(root)
    rows=[];jobs=[]
    for identity in sorted(IDS&contracts.keys()):
        selected=COMMAND_CASES.get(identity, categories)
        for category in categories:
            if category not in selected:continue
            if (identity,category) in AUDITS:continue
            target=root/(identity.rsplit('.',1)[-1]+'-'+category+'-'+uuid.uuid4().hex[:8]);target.mkdir()
            boundary='Actual NativeDeviceCommandStore SQLite effects with independent durable readback' if identity in COMMAND_IDS else ('Actual owned local SQLite and Ed25519 operator authority' if identity in OPERATOR_IDS else 'Actual production local adapter, backend dispatcher, SQLite/readback, cancellation and attribution; external executor is an owned finite Node protocol process')
            row={'id':'c7d-native-commands.'+identity+'.'+category,'contracts':[identity],'category':category,'boundary':boundary+'; no physical device execution, human identity, provider/model or rendered proof','scratchRoot':str(target)}
            jobs.append((identity,category,target,row))
    def execute(job):
        identity,category,target,row=job
        try:
            if identity in COMMAND_IDS:
                from .edge_fixture_commands_adverse import run as adverse
                detail=adverse(target,identity,category)
            else:detail=_operator(target,identity,category) if identity in OPERATOR_IDS else _session_child(target,identity,category)
            row.update(status='passed',detail=detail)
        except Exception as error:row.update(status='failed',detail={'type':type(error).__name__,'error':str(error)})
        return row
    # Cases use disjoint roots; every native case gets an isolated guarded process.
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(execute,jobs))
    return rows
