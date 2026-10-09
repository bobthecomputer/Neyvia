"""Real Git/worktree lifecycle with confined local session transport."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
import uuid

from .proofs_rel29_outcomes import refused

CONTRACTS=('parallel.clean-start','parallel.separate-worktrees','parallel.question-answer',
           'parallel.committed-done','parallel.ordered-conflict','parallel.resolution',
           'parallel.finish-authority','parallel.safe-settle','parallel.orphan-settle',
           'parallel.failed-start-settle','parallel.availability-retry')


def repository(root):
    from .neyvia_parallel_git import git
    root.mkdir(parents=True)
    (root/'value.txt').write_text('base\n')
    git(root,'init','-b','main');git(root,'config','user.name','Gate fixture')
    git(root,'config','user.email','gate-fixture@localhost')
    git(root,'add','value.txt');git(root,'commit','-m','Fixture base')
    return root


def committed(folder,value):
    from .neyvia_parallel_git import git
    (Path(folder)/'value.txt').write_text(value+'\n')
    git(folder,'add','value.txt');git(folder,'commit','-m','Fixture '+value)


def lifecycle(root):
    from . import neyvia_parallel as owner
    from . import neyvia_parallel_git as vcs
    from .proofs_local_session_fixture import service_for
    service,broker,transport=service_for(root/'state')
    repo=repository(root/'repo')
    args={'repo':str(repo),'goal':'Combine local fixture changes','main':{'agent':'codex'},
          'checkCommand':subprocess.list2cmdline([sys.executable,'-c',"from pathlib import Path; assert Path('value.txt').read_text().strip() == 'combined'"]),
          'tracks':[{'id':name,'title':name,'brief':'Write local committed evidence','agent':'codex'} for name in ('first','second')]}
    observed={}
    try:
        base=vcs.git(repo,'rev-parse','HEAD').stdout.strip()
        (repo/'dirty.txt').write_text('preserve this uncommitted fixture\n')
        refused(lambda:owner.start(service,args));(repo/'dirty.txt').unlink()
        for bad in ({'tracks':[]},{'tracks':args['tracks']*2},{'main':{'agent':'unsupported'}},
                    {'tracks':[args['tracks'][0]]*9},{'main':{'agent':'opencode'}}):
            refused(lambda bad=bad:owner.start(service,{**args,**bad}))
        assert len(vcs.worktrees(repo))==1 and not transport.calls
        observed['parallel.clean-start']={'invalidStartsRefused':6,'noSessionOrWorktreeSideEffects':True}
        run=owner.start(service,args)['run']
        lanes=[run['main'],*run['tracks']]
        assert len({row['worktree'] for row in lanes})==3 and len({row['session'] for row in lanes})==3
        assert all(vcs.git(row['worktree'],'rev-parse','HEAD').stdout.strip()==base for row in lanes)
        assert vcs.git(repo,'rev-parse','HEAD').stdout.strip()==base and vcs.clean(repo)
        observed['parallel.separate-worktrees']={'worktrees':vcs.worktrees(repo),'sessions':[row['session'] for row in lanes],'base':base}
        first,second=run['tracks']
        refused(lambda:owner.action(service,run,'done',{'track':'first','summary':'absent commit'}))
        owner.action(service,run,'ask',{'track':'first','question':'Which value?'})
        committed(first['worktree'],'first')
        refused(lambda:owner.action(service,run,'done',{'track':'first','summary':'unanswered'}))
        question=first['questions'][0]
        owner.action(service,run,'answer',{'track':'first','questionId':question['id'],'answer':'Use first'})
        assert question['answer']=='Use first' and question['delivery']['runId']
        observed['parallel.question-answer']={'question':deepcopy(question),'localTurns':len(transport.calls)}
        (Path(second['worktree'])/'dirty.txt').write_text('keep dirty\n')
        refused(lambda:owner.action(service,run,'done',{'track':'second','summary':'dirty'}))
        (Path(second['worktree'])/'dirty.txt').unlink();committed(second['worktree'],'second')
        owner.action(service,run,'done',{'track':'first','summary':'first changes'})
        owner.action(service,run,'done',{'track':'second','summary':'second changes'})
        observed['parallel.committed-done']={'absentCommitDirtyAndQuestionRefused':True,'commitsAhead':[row['commitsAhead'] for row in run['tracks']]}
        assert run['state']=='conflict' and run['tracks'][0]['state']=='merged' and second['state']=='conflict'
        conflict=deepcopy(run['conflict'])
        assert conflict['previousTracks']==['first'] and conflict['files']==['value.txt'] and conflict['sides'] and conflict['summaries']
        observed['parallel.ordered-conflict']=conflict
        refused(lambda:owner.action(service,run,'resolved',{}))
        folder=Path(run['integrationWorktree']);(folder/'value.txt').write_text('<<<<<<< unresolved\n')
        vcs.git(folder,'add','value.txt');refused(lambda:owner.action(service,run,'resolved',{}))
        (folder/'value.txt').write_text('combined\n');vcs.git(folder,'add','value.txt')
        owner.action(service,run,'resolved',{})
        assert run['state']=='ready' and run['checks']['passed'] and not run['conflict']
        assert all(row['state']=='merged' for row in run['tracks'])
        observed['parallel.resolution']={'unmergedAndMarkersRefused':True,'checks':run['checks']}
        owner.action(service,run,'finish',{})
        assert not run['finish'] and vcs.git(repo,'rev-parse','HEAD').stdout.strip()==base
        run['settings']['allowFinish']=True
        (repo/'dirty.txt').write_text('preserve');refused(lambda:owner.action(service,run,'finish',{}));(repo/'dirty.txt').unlink()
        run['checks']['passed']=False;refused(lambda:owner.action(service,run,'finish',{}));run['checks']['passed']=True
        committed(repo,'base diverged');refused(lambda:owner.action(service,run,'finish',{}),(ValueError,RuntimeError))
        assert not run['finish']
        observed['parallel.finish-authority']={'ownerConsentDirtyChecksAndDivergedBaseRefused':True,'basePreserved':True}
        (Path(first['worktree'])/'dirty.txt').write_text('preserve');refused(lambda:owner.action(service,run,'settle',{}))
        assert all(Path(row['worktree']).exists() for row in lanes)
        (Path(first['worktree'])/'dirty.txt').unlink()
        owner.action(service,run,'settle',{})
        assert run['state']=='settled' and all(not Path(row['worktree']).exists() for row in lanes)
        assert len(vcs.worktrees(repo))==1 and vcs.git(repo,'show-ref','--verify','refs/heads/'+run['integrationBranch']).returncode==0
        receipt=deepcopy(run['receipt']);owner.action(service,run,'settle',{});assert run['receipt']==receipt
        observed['parallel.safe-settle']={'receipt':receipt,'dirtyWorkPreservedOnRefusal':True,'integrationBranchRetained':True,'idempotent':True}
        return observed
    finally:
        broker.close();service.close()


def recovery(root):
    from . import neyvia_parallel as owner
    from . import neyvia_parallel_git as vcs
    from .proofs_local_session_fixture import service_for
    service,broker,transport=service_for(root/'state')
    repo=repository(root/'repo')
    args={'repo':str(repo),'goal':'Partial start recovery','main':{'agent':'codex'},'sparsePaths':['../outside'],
          'tracks':[{'id':name,'title':name,'brief':'Retained recovery lane','agent':'codex'} for name in ('orphan','absent','keeper')]}
    try:
        refused(lambda:owner.start(service,args))
        path=next(owner.store(service.bus.root).glob('*.json'));run=json.loads(path.read_text())
        assert run['state']=='failed' and run['startFailure']['settleable'] and not transport.calls
        owner.action(service,run,'settle',{})
        assert run['state']=='settled' and all(row['status']=='removed' for row in run['receipt']['tracks'])
        partial=deepcopy(run['receipt'])
        refused(lambda:owner.start(service,args))
        path=max(owner.store(service.bus.root).glob('*.json'),key=lambda p:p.stat().st_mtime_ns);run=json.loads(path.read_text())
        for row in run['tracks']:
            vcs.git(repo,'worktree','add','-b',row['branch'],row['worktree'],run['baseCommit'])
            row['checkoutReady']=True
        orphan,absent,keeper=run['tracks'];committed(keeper['worktree'],'unmerged keeper')
        metadata=Path((Path(orphan['worktree'])/'.git').read_text().strip().removeprefix('gitdir: ')).resolve()
        metadata.relative_to(repo/'.git/worktrees');shutil.rmtree(metadata)
        external=root/'outside-keeper';external.mkdir();(external/'kept.txt').write_text('keeper bytes')
        from .subprocess_utils import hidden_windows_subprocess_kwargs
        subprocess.run(['cmd','/c','mklink','/J',str(Path(orphan['worktree'])/'node_modules'),str(external)],check=True,capture_output=True,**hidden_windows_subprocess_kwargs())
        removed=Path(absent['worktree']);removed.resolve().relative_to(repo/'.neyvia-worktrees'/run['id']);shutil.rmtree(removed)
        owner.action(service,run,'settle',{})
        assert (external/'kept.txt').read_text()=='keeper bytes'
        assert vcs.git(repo,'rev-parse',keeper['branch']).stdout.strip()!=run['baseCommit']
        assert len(run['receipt']['tracks'])==4 and len(vcs.worktrees(repo))==1
        assert any(row['method']=='orphan_removed' for row in run['receipt']['tracks'])
        receipt=deepcopy(run['receipt']);owner.action(service,run,'settle',{});assert run['receipt']==receipt
        return {'parallel.failed-start-settle':{'receipt':partial,'noSessionLaunched':True},
                'parallel.orphan-settle':{'receipt':receipt,'outsideKeeperIntact':True,'unmergedCommitKept':True,'idempotent':True}}
    finally:
        broker.close();service.close()


def availability(root):
    from .connected_sessions import registry
    from .connected_sessions.broker import ConnectedBroker
    from .proofs_local_session_fixture import LocalTransport
    adapter=LocalTransport(root,'claude-code');broker=ConnectedBroker(root,adapters={'claude-code':adapter},autostart=False)
    original=registry.bounded;calls=[]
    def bounded(fn,timeout,label):
        if label=='available':
            calls.append(timeout)
            if len(calls)==1: raise registry.ConnectedError('adapter_timeout','Controlled loaded-host timeout')
        return original(fn,timeout,label)
    try:
        broker.registry._availability['claude-code']=(time.monotonic(),False,'cached discovery failure')
        with patch.object(registry,'bounded',bounded):
            run=broker.new('claude-code',str(root),'Local availability proof','available-proof')
        assert calls==[45.0,45.0] and run['sessionId'] and len(adapter.calls)==1
        return {'availabilityBudgets':calls,'cachedFailedDiscoveryBypassed':True,'sessionCreations':len(adapter.calls)}
    finally: broker.close()



def film_native(root):
    from types import SimpleNamespace
    from . import neyvia_parallel as owner
    from . import claude_code_host as mod
    from .proofs_local_session_fixture import service_for
    service,broker,transport=service_for(root/'state');service.backend=SimpleNamespace(root=service.bus.root)
    repo=repository(root/'repo');auth={'username':'fixture-owner','sessionId':'fixture-auth'}
    try:
        run=owner.start(service,{'repo':str(repo),'goal':'Native mod completion proof','main':{'agent':'codex'},'tracks':[{'id':'worker','title':'Worker','brief':'Commit a retained result','agent':'codex'}]})['run']
        track=run['tracks'][0]
        def wait_idle(identity):
            deadline=time.monotonic()+15
            while broker.get_run(identity)['state'] in owner.ACTIVE:
                assert time.monotonic()<deadline,'Local receiver did not finish'
                time.sleep(.01)
        for row in [run['main'],*run['tracks']]:wait_idle(row['runId'])
        owner.action(service,run,'ask',{'track':'worker','question':'Which value?'})
        wait_idle(track['questions'][0]['delivery']['runId'])
        calls=len(transport.calls);identity=track['questions'][0]['id']
        owner.action(service,run,'ask',{'track':'worker','question':'Which value?'})
        assert len(track['questions'])==1 and len(transport.calls)==calls and track['questions'][0]['id']==identity
        duplicate=deepcopy(track['questions'][0]);duplicate['id']='historical-duplicate';track['questions'].append(duplicate)
        owner.action(service,run,'ask',{'track':'worker','question':'Unrelated question?'})
        owner.action(service,run,'answer',{'track':'worker','questionId':identity,'answer':'Use result'})
        assert all(q['answer']=='Use result' for q in track['questions'] if q['question']=='Which value?')
        assert track['questions'][-1]['answer'] is None
        committed(track['worktree'],'result')
        owner.save(service.bus.root,run,'fixture.ready',{})
        body={'session':'fixture-claude','tool':'neyvia.parallel.done','args':{'run':run['id'],'track':'worker','summary':'Committed result'}}
        # The transport is finite, but native catalog, auth, CL recovery, effect
        # observer and Git store all execute their production implementations.
        with patch('grant_agent.neyvia_workspace_tools.workspace_for',return_value=service):
            forbidden=mod.call_tool(service,service.bus.root,body,auth={**auth,'username':'other'},owner='fixture-owner')
            assert not forbidden['ok']
            blocked=mod.call_tool(service,service.bus.root,body,auth=auth,owner='fixture-owner')
            assert not blocked['ok'] or blocked.get('result',{}).get('doneStatus')!='ok'
            assert owner.load(service.bus.root,run['id'])['tracks'][0]['state']!='merged'
            fresh=owner.load(service.bus.root,run['id']);owner.action(service,fresh,'answer',{'track':'worker','answer':'Answered unrelated'})
            owner.save(service.bus.root,fresh,'fixture.answered',{})
            dirty=Path(track['worktree'])/'dirty.txt';dirty.write_text('preserve')
            blocked=mod.call_tool(service,service.bus.root,body,auth=auth,owner='fixture-owner')
            assert not blocked['ok'] or blocked.get('result',{}).get('doneStatus')!='ok'
            assert dirty.read_text()=='preserve';dirty.unlink()
            result=mod.call_tool(service,service.bus.root,body,auth=auth,owner='fixture-owner')
            assert result['ok'] and result['result'].get('doneStatus')=='ok',result
        fresh=owner.load(service.bus.root,run['id'])
        assert fresh['tracks'][0]['state']=='merged' and fresh['tracks'][0]['summary']=='Committed result'
        checks=result['result'].get('checks',[])
        return {'parallel.pending-question-retry':{'sameQuestionId':identity,'duplicateDeliveryPrevented':True,'historicalDuplicatesAnswered':True,'unrelatedPreserved':True},
                'parallel.mod-worker-done':{'authenticatedMod':True,'observerBoundDone':True,'freshMergedState':fresh['tracks'][0]['state'],'dirtyAndUnansweredRefused':True,'clReceipt':result['result']}}
    finally:
        broker.close();service.close()

def self_check(scratch):
    from .contract_gate import wants
    cases=[];scratch=Path(scratch)
    groups=[(CONTRACTS[:8],lifecycle),(CONTRACTS[8:10],recovery),((CONTRACTS[10],),availability),(('parallel.pending-question-retry','parallel.mod-worker-done'),film_native)]
    for identities,action in groups:
        active=[identity for identity in identities if wants(identity)]
        if not active: continue
        root=scratch/uuid.uuid4().hex;root.mkdir(parents=True)
        try:
            observations=action(root)
            if action is availability: observations={active[0]:observations}
            cases.extend({'id':identity,'contracts':[identity],'ok':True,'observed':observations[identity]} for identity in active)
        except Exception as error:
            import traceback
            cases.extend({'id':identity,'contracts':[identity],'ok':False,'error':type(error).__name__+': '+str(error),'traceback':traceback.format_exc()} for identity in active)
    return {'ok':bool(cases) and all(case['ok'] for case in cases),'cases':cases,
            'contracts':[case['id'] for case in cases if case['ok']],
            'boundary':'Production Git/state/broker owners and real disposable worktrees; finite child-process session transport, no provider run'}
