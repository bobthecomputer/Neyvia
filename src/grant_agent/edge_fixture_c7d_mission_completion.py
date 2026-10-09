"""Exact mission completion fixtures; local simulations never prove execution."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from .edge_fixture_local import require, refused, sha, replacement_fault
from .edge_fixture_missions import exclusive, body, pool
from .edge_fixture_c7d_local import CATEGORIES, _isolate, _deny_child_creation

P = 'proofs-c.missions.'


def _acceptance(root, category):
    root = root.resolve()
    from .mission_acceptance_harness import MissionAcceptanceHarness
    from . import durability
    receipts = root / '.agent_control/neyvia/acceptance'
    def attempt(index=0):
        harness = MissionAcceptanceHarness(root)
        try:
            result = harness.run()
        finally:
            harness.broker.close()
        raw = json.loads(Path(result['receiptPath']).read_text(encoding='utf8'))
        require(raw == result and len(raw['journeys']) == 5 and raw['summary'] == {'passed':5,'total':5,'failed':[]}, 'Acceptance attempt durable summary differs')
        require(raw['simulated'] is True and all(raw[k] is False for k in ('networkUsed','paidComputeUsed','externalAccountsUsed')), 'Local simulation invented real execution')
        return result
    if category == 'empty':
        require(not receipts.exists(), 'Fresh attempt root already has history')
    if category == 'unicode':
        root = root / '雪 café 🙂'
        receipts = root / '.agent_control/neyvia/acceptance'
    first = attempt()
    before = {p.name:sha(p.read_bytes()) for p in receipts.glob('*.json')}
    error = None
    if category == 'permissions':
        with _deny_child_creation(receipts, root, deny_access_mask=0x10040, inherit_children=True):
            error = refused(attempt, OSError)
        require({p.name:sha(p.read_bytes()) for p in receipts.glob('*.json')} == before, 'Denied acceptance publisher changed prior receipts')
    elif category == 'interrupted':
        # Only the final acceptance publisher is cut. The preceding journeys
        # remain explicitly simulated; no completion receipt is acknowledged.
        original = durability.os.replace
        cuts = []
        def cut(source, target):
            if Path(target).parent.resolve() == receipts:
                cuts.append(str(target))
                raise KeyboardInterrupt('Owned acceptance publish cut')
            return original(source, target)
        durability.os.replace = cut
        try:
            error = refused(attempt, KeyboardInterrupt)
        finally:
            durability.os.replace = original
        require(cuts and {p.name:sha(p.read_bytes()) for p in receipts.glob('*.json')} == before, 'Interrupted acceptance publisher changed completed history')
    more = pool(attempt) if category == 'concurrency' else [attempt(i) for i in range(12 if category == 'huge' else 1)]
    all_rows = [first, *more]
    require(len({r['runId'] for r in all_rows}) == len(all_rows) and len({r['receiptPath'] for r in all_rows}) == len(all_rows), 'Acceptance attempts reused identity')
    require(all(sha((receipts/name).read_bytes()) == digest for name,digest in before.items()), 'Fresh attempts displaced old receipts')
    require(len(list(receipts.glob('*.json'))) == len(all_rows), 'Failed attempt invented completed receipt')
    return {'attempts':len(all_rows), 'simulated':True, 'renderedProof':False, 'externalExecution':False, 'distinctDurableReceipts':True, 'refusal':error}


def _orchestration(root, category):
    from .mission_control import ControlRoomStore
    from .models import Mission
    from . import cli, durability
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    store = ControlRoomStore(root)
    store.save_missions([Mission(mission_id='owned',workspace_id='scratch',runtime_id='local',objective=body(category),success_checks=[])])
    def arguments(index=0):
        return {'root':str(root),'mission_id':'owned','parallel_agents':10**9 if category=='huge' else index+1,'observation_count':10**9 if category=='huge' else index+2,'merge_policy':body(category) or None,'cross_mission_awareness':body(category) or None,'reason':body(category)}
    def current():
        return json.loads(store.missions_path.read_text(encoding='utf8'))[0]
    def one(args):
        out = io.StringIO()
        with redirect_stdout(out):
            status = cli.cmd_mission_orchestration(argparse.Namespace(**args))
        result = json.loads(out.getvalue())
        require(status == 0 and result['ok'], 'CLI orchestration refused valid local request')
        saved = current()['state']
        receipt = result['receipt']
        for camel,snake in [('parallelAgents','parallel_agents'),('observationCount','observation_count'),('mergePolicy','merge_policy'),('crossMissionAwareness','cross_mission_awareness')]:
            require(receipt[camel] == saved[snake] == saved['runtime_autonomy'][camel], 'Independent policy/runtime/receipt mismatch')
        return result
    first = one(arguments())
    old = store.missions_path.read_bytes()
    refusal = None
    if category == 'permissions':
        with exclusive(store.missions_path):
            refusal = refused(lambda: one(arguments(1)), OSError)
        require(store.missions_path.read_bytes() == old, 'Denied orchestration changed saved mission')
    elif category == 'interrupted':
        with replacement_fault(durability, store.missions_path, KeyboardInterrupt) as cuts:
            refusal = refused(lambda: one(arguments(1)), KeyboardInterrupt)
        require(cuts and store.missions_path.read_bytes() == old, 'Interrupted policy publication changed original state')
    if category == 'concurrency':
        program = "import argparse,json,sys;from grant_agent.cli import cmd_mission_orchestration;a=json.loads(sys.stdin.read());sys.exit(cmd_mission_orchestration(argparse.Namespace(**a)))"
        def launch(index):
            proc = subprocess.run([sys.executable,'-c',program], input=json.dumps(arguments(index)),text=True,encoding='utf8',capture_output=True,timeout=90,env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'PYTHONIOENCODING':'utf8'},**hidden_windows_subprocess_kwargs())
            return {'exit':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr[-2500:]}
        rows = pool(launch)
        failures = [r for r in rows if r['exit'] != 0]
        require(not failures, 'Concurrent actual orchestration writers failed: '+json.dumps(failures))
        receipts = [json.loads(r['stdout'])['receipt'] for r in rows]
        saved = current()['state']
        require(saved['parallel_agents'] in range(1,9) and saved['runtime_autonomy']['parallelAgents'] == saved['parallel_agents'], 'Final concurrent saved policy diverged')
        events=[json.loads(line) for line in store.events_path.read_text(encoding='utf8').splitlines()]
        policies=[e['metadata'] for e in events if e['kind']=='mission.orchestration_updated']
        canonical=lambda value:json.dumps(value,sort_keys=True)
        require(len(policies)==9 and {canonical(r) for r in policies[1:]}=={canonical(r) for r in receipts}, 'Durable independent event journal lost or changed an acknowledged writer receipt')
        for camel,snake in [('parallelAgents','parallel_agents'),('observationCount','observation_count'),('mergePolicy','merge_policy'),('crossMissionAwareness','cross_mission_awareness')]:
            require(saved[snake]==saved['runtime_autonomy'][camel]==policies[-1][camel], 'Final saved policy diverged from last durable acknowledgement')
        return {'actualWriterProcesses':8,'acknowledgedReceipts':len(receipts),'independentlyMatchedDurableEvents':8,'finalParallelAgents':saved['parallel_agents'],'modelInvoked':False}
    fresh = one(arguments(2))
    if category == 'stale':
        require(first['receipt']['parallelAgents'] != fresh['receipt']['parallelAgents'], 'Fresh request reused stale policy receipt')
    require(current()['objective'] == body(category), 'Orchestration changed mission goal')
    return {'parallelAgents':fresh['receipt']['parallelAgents'],'observationCount':fresh['receipt']['observationCount'],'reasonCharacters':len(fresh['receipt']['reason']),'actualCli':True,'refusal':refusal,'modelInvoked':False}


def _storage(root, category):
    from .cli import _mission_storage_pressure_blocker
    from types import SimpleNamespace
    path = root / '.agent_control/nas_storage_pressure_latest.json'
    path.parent.mkdir(parents=True)
    workspace = SimpleNamespace(root_path=str(root))
    now = datetime.now(timezone.utc).isoformat()
    base = {'schema':'fluxio.nas_storage_pressure.v1','checkedAt':now,'mount':str(root),'host':'owned-fixture','source':'provided-local-capacity','measuredUsageAvailable':False,'status':'unknown'}
    def publish(value):
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    def observe():
        return _mission_storage_pressure_blocker(root,workspace)
    publish(base)
    require(observe() == {}, 'Unknown capacity invented disk pressure')
    failed = {**base,'probeConnectFailed':True,'availableBytes':0,'usedPercent':100}
    publish(failed)
    require(observe() == {}, 'Failed probe invented measured capacity')
    if category == 'huge':
        publish({**base,'availableBytes':'9'*20000,'usedPercent':'Infinity'})
        require(observe() == {}, 'Non-finite oversized unknown measurement invented pressure')
    if category == 'empty':
        for value in ({},[],{'schema':base['schema'],'checkedAt':''}):
            publish(value)
            require(observe() == {}, 'Empty/invalid capacity invented admission blocker')
    critical = {**base,'measuredUsageAvailable':True,'status':'full','availableBytes':0,'usedPercent':100,'totalBytes':10**18 if category=='huge' else 1000}
    if category == 'huge':
        critical['usedPercent'] = '100.0'
    publish(critical)
    before = path.read_bytes()
    result = observe()
    require(result['code'] == 'nas_storage_pressure_block' and result['storage']['sourcePath'] == str(path.resolve()) and result['storage']['usedPercent'] == 100, 'Measured critical local receipt was not exactly bound')
    if category == 'permissions':
        with exclusive(path):
            require(observe() == {}, 'OS-denied local capacity invented pressure')
    if category == 'concurrency':
        require(all(r == result for r in pool(lambda _:observe())), 'Concurrent capacity readers changed decision')
    if category == 'stale':
        publish({**critical,'checkedAt':(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()})
        require(observe() == {}, 'Expired measurement blocked current admission')
        publish(critical)
        require(observe() == result, 'Current measured receipt stayed stale')
    if category == 'unicode':
        publish({**base,'status':'雪 full','nextAction':'café 🙂','availableBytes':None})
        require(observe() == {}, 'Unicode unknown status invented pressure')
        publish(critical)
    require(path.read_bytes() == before, 'Capacity read mutated exact supplied measurement')
    return {'measuredCapacityBlocks':True,'unknownFailedDeniedExpiredDoNotInventPressure':True,'nasContacted':False,'bytesPreserved':True}


def _policy(root, category):
    from .edge_fixture_missions import _policy as existing
    if category not in {'concurrency','stale','empty'}:
        return existing(root,category)['detail']
    from .security_runtime_policy import evaluate_security_action,audit_security_tool_coverage
    from .fluxio_harness import infer_task_route_profile
    from .mission_control import apply_agent_turn_mode_to_launch
    def check(index=0):
        target = 'owned-'+str(index)+'.invalid'
        scope = {'target':target,'authorizedBy':'owner','authorizationConfirmed':True,'environment':'lab','mode':'active','allowedTargets':[target],'allowedActionClasses':['probe']}
        approved = evaluate_security_action(scope,{'target':target,'actionClass':'probe','active':True})
        revoked = evaluate_security_action({**scope,'authorizationConfirmed':False},{'target':target,'actionClass':'probe','active':True})
        require(approved['allowed'] and not revoked['allowed'], 'Current exact authorization was ignored')
        coverage = audit_security_tool_coverage([{'toolId':'tool.windows-defender','executionReady':True,'state':'verified'}])
        stale = audit_security_tool_coverage([{'toolId':'tool.windows-defender','executionReady':False,'state':'unavailable'}])
        require(stale['missingPhases'] and not stale['ready'], 'Historical verified label masked unavailable tool')
        red = infer_task_route_profile('authorized red-team attack-surface assessment')
        blue = infer_task_route_profile('blue-team detection engineering and incident response')
        empty = infer_task_route_profile('')
        require(red['taskType']=='security_red_team' and blue['taskType']=='security_blue_team' and empty['taskType'] not in {'security_red_team','security_blue_team'}, 'Current route inherited stale security intent')
        standard = apply_agent_turn_mode_to_launch(turn_mode='standard',objective=target,success_checks=[],route_overrides=[],mode='Focus',budget_hours=2)
        deep = apply_agent_turn_mode_to_launch(turn_mode='1m',objective=target,success_checks=[],route_overrides=[{'role':'executor','effort':'low'}],mode='Focus',budget_hours=2)
        require(standard['objective']==target==deep['objective'] and standard['mode']=='Focus' and deep['mode']=='Deep Run' and deep['routeOverrides'][0]['effort']=='high', 'Current turn mode reused stale launch policy')
        return {'target':target,'revocationRefused':True,'red':red['taskType'],'blue':blue['taskType'],'empty':empty['taskType'],'unavailablePhases':stale['missingPhases'],'deepMode':deep['mode']}
    rows = pool(check) if category=='concurrency' else [check()]
    require(len({r['target'] for r in rows}) == len(rows), 'Independent caller contexts collapsed')
    return {'decisions':rows,'externalActions':0,'renderedProof':False}


def _gpu(root, category):
    from .continuity_policy import MissionContinuityStore
    store = MissionContinuityStore(root)
    store.create_or_update('gpu',patch={'gpuPolicy':{'maxConcurrentInstances':1,'maxEstimatedHourlyCost':5,'maxEstimatedSessionCost':4,'maxDurationMinutes':60,'idleReleaseMinutes':10,'requireApprovalForPaidStart':True}})
    path = store._record_path('gpu')
    before = path.read_bytes()
    def check(index=0):
        title = body(category)
        empty = store.evaluate_gpu_action('gpu',{}, {})
        require(empty['estimatedSessionCost'] is None and not empty['approvalRequired'], 'Empty proposal invented paid start/cost')
        decision = store.evaluate_gpu_action('gpu',{'action':'start_instance','title':title,'estimatedHourlyCost':3,'estimatedDurationMinutes':120},{'runningInstances':0})
        require(not decision['allowed'] and decision['estimatedSessionCost']==6 and decision['approvalRequired'], 'Stored GPU policy did not constrain current paid proposal')
        require(path.read_bytes()==before,'GPU policy observer mutated stored policy')
        return {'estimatedSessionCost':decision['estimatedSessionCost'],'approvalRequired':decision['approvalRequired'],'emptyEstimatedCost':empty['estimatedSessionCost'],'proposalTitleCharacters':len(title)}
    rows = pool(check) if category=='concurrency' else [check()]
    return {'decisions':rows,'paidComputeStarted':False,'bytesPreserved':True}


def _awareness(root, category):
    from .edge_fixture_local import _awareness as production_journey
    ids, detail = production_journey(root,category)
    require(set(ids) == AWARENESS_IDS, 'Awareness exact durable workflow omitted required bindings')
    return detail


def _artifact_stale(root, category):
    from .subprocess_utils import hidden_windows_subprocess_kwargs
    script = r"""
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const m=await import(pathToFileURL(path.join(process.argv[1],'web/src/neyvia/neyviaMissionProjection.js')));
let store=m.createMissionProjectionStore();
const old={artifactId:'owned',servedUrl:'/api/artifact?id=old',safeEndpoint:'/api/artifact',mediaType:'text/plain',label:'old',content:'UNEXPECTED_BYTES'};
store=m.mergeMissionArtifacts(store,'owned',[old]);
store=m.mergeMissionArtifacts(store,'other',[{...old,artifactId:'foreign'}]);
const before=JSON.stringify(store);
const next=m.mergeMissionArtifacts(store,'owned',[{...old,servedUrl:'/api/artifact?id=current',label:'雪 current'}]);
assert.equal(next.missions.owned.artifacts.length,1);
assert.equal(next.missions.owned.artifacts[0].contentRef.url,'/api/artifact?id=current');
assert.equal(next.missions.owned.artifacts[0].contentRef.endpoint,'/api/artifact');
assert.deepEqual(next.missions.other,store.missions.other);
assert.equal(JSON.stringify(store),before);
assert(!JSON.stringify(next).includes('UNEXPECTED_BYTES'));
assert.equal(m.mergeMissionArtifacts(next,'',[]),next);
console.log(JSON.stringify({currentReference:'/api/artifact?id=current',foreignMissionPreserved:true,priorModelPreserved:true,rawBytesExcluded:true,renderedProof:false,syntheticCallerModel:true}));
"""
    proc = subprocess.run(['node','--input-type=module','-e',script,str(Path(__file__).resolve().parents[2])],capture_output=True,text=True,encoding='utf8',timeout=30,**hidden_windows_subprocess_kwargs())
    require(proc.returncode==0,proc.stderr[-1800:])
    return json.loads(proc.stdout)


POLICY_IDS = {P+s for s in ('security-scope','security-coverage','security-route','turn-mode')}
AWARENESS_IDS = {'awareness.'+s for s in ('claim.persisted','claim.refresh','claim.overlaps','paths.overlap','list.projection','release.persisted')}
FAMILIES = {
    'acceptance':(_acceptance,{P+'acceptance-receipt'},set(CATEGORIES)-{'offline'}),
    'orchestration':(_orchestration,{P+'orchestration-durable'},set(CATEGORIES)-{'offline'}),
    'storage':(_storage,{P+'local-storage'},set(CATEGORIES)-{'offline','interrupted'}),
    'policy':(_policy,POLICY_IDS,{'empty','concurrency','stale'}),
    'gpu':(_gpu,{P+'gpu-policy'},{'empty','unicode','concurrency'}),
    'awareness':(_awareness,AWARENESS_IDS,{'empty','huge','permissions'}),
    'artifact-current':(_artifact_stale,{'mission.artifacts'},{'stale'}),
}


def run(root, contracts, categories):
    rows=[]
    for family,(builder,ids,supported) in FAMILIES.items():
        for category in categories:
            matched=sorted(ids.intersection(contracts))
            if family=='policy' and category=='empty':
                matched=[i for i in matched if i.endswith('security-route')]
            if family=='policy' and category=='stale':
                matched=[i for i in matched if not i.endswith('security-scope')]
            if not matched or category not in supported:
                continue
            scratch=Path(root)/family/category
            scratch.mkdir(parents=True,exist_ok=False)
            row={'id':f'mission-completion:{family}:{category}','contracts':matched,'category':category,'scratchRoot':str(scratch),'boundary':'actual local CLI/stores and exact current policy decisions; simulations explicitly excluded from external/model/rendered proof'}
            try:
                row.update(status='passed',detail=builder(scratch,category))
            except Exception as error:
                row.update(status='failed',detail={'type':type(error).__name__,'error':str(error)})
            rows.append(row)
    return rows


def blocker(contract,category):
    identity=contract['id']
    if identity in {P+'acceptance-receipt',P+'orchestration-durable',P+'local-storage'} and category=='offline':
        return {'kind':'not_applicable','reason':'This exact invariant concerns explicitly simulated network-free local harness summaries, local CLI policy publication or reading a caller-provided local capacity receipt. None admits a network/provider/NAS transport. The fixtures install a socket refusal guard; simulated flags remain explicit and no external/model/rendered execution is counted.'}
    if identity==P+'local-storage' and category=='interrupted':
        return {'kind':'not_applicable','reason':'The audited storage admission owner synchronously reads an already provided local capacity receipt and returns a policy blocker without modifying it or accepting a probe/mission worker. Unknown, failed, denied and expired measurement states are actually read and never invent pressure. There is no completion publisher to interrupt at this invariant; no NAS probe is invoked.'}
    if identity in POLICY_IDS and (category=='interrupted' or category=='permissions' and identity!=P+'security-scope'):
        return {'kind':'not_applicable','reason':'The exact security coverage/route/turn-mode/scope invariant evaluates supplied declarations, caller authorization metadata or launch projections synchronously. It does not grant OS access, execute a tool, read protected state or accept an asynchronous worker. Actual changed current inputs and concurrent decisions are checked; executable tool/mission effects retain their separate authority and interruption boundaries.'}
    if identity==P+'gpu-policy' and category=='interrupted':
        return {'kind':'not_applicable','reason':'The audited GPU policy owner reads an already durable local policy and decides cost/concurrency/duration/approval requirements; it accepts no GPU provider worker or paid start. Actual empty/unicode and concurrent current proposals read the stored policy without mutation. Continuity publication has its own real interruption fixture; a policy decision never proves paid execution.'}
    return None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--family',choices=sorted(FAMILIES))
    args=parser.parse_args()
    _isolate(args.root.resolve(),args.port)
    from .proof_contracts import source_digest,REPO
    names=['src/grant_agent/'+n+'.py' for n in ('edge_fixture_c7d_mission_completion','edge_fixture_missions','edge_fixture_c7d_local','edge_fixture_local','mission_acceptance_harness','mission_control','mission_control_integration','mission_control_operator_audit','mission_control_harness','mission_control_release','cli','durability','continuity_policy','security_runtime_policy','fluxio_harness','proofs_c_missions','neyvia_awareness','proofs_awareness')]
    names += ['web/src/neyvia/neyviaMissionProjection.js','web/src/neyvia/neyviaFrontendContracts.js']
    before={n:source_digest(REPO/n) for n in names}
    contracts={i:{} for family,(_,ids,_) in FAMILIES.items() if not args.family or family==args.family for i in ids}
    rows=run(args.root/'cases',contracts,CATEGORIES)
    stable=before=={n:source_digest(REPO/n) for n in names}
    report={'sourceStable':stable,'sourceBindings':before,'explicitPort':args.port,'rows':rows,'ok':stable and all(r['status']=='passed' for r in rows),'passedPairs':len({(i,r['category']) for r in rows if r['status']=='passed' for i in r['contracts']})}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','sourceBindings'}}))
    print(json.dumps([r for r in rows if r['status']!='passed']))
