"""Migrated CL cases for budget authority and offline release parsing."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch, Mock


def require(condition, message):
    if not condition:
        raise ValueError(message)


def budget(root):
    from . import cli
    from .mission_control import CONTROL_PROJECT_ROOT_ENV, ControlRoomStore, _mission_runtime_budget_exhausted, mission_time_budget_window
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'README.md').write_text('# Runtime budget contract\n',encoding='utf-8')
    with patch.dict(os.environ,{CONTROL_PROJECT_ROOT_ENV:str(root)}):
        store=ControlRoomStore(root);workspace=store.load_workspaces()[0]
    def mission(hours):
        settings=cli._mission_budget_settings('Run a bounded diagnostic.',hours,'continue_until_blocked')
        return store.create_mission(workspace_id=workspace.workspace_id,runtime_id='hermes',objective='Run a bounded diagnostic.',
            success_checks=[],mode='Autopilot',verification_commands=[],max_runtime_seconds=settings['max_runtime_seconds'],
            run_until_behavior=settings['run_until_behavior'],deadline_at=settings['deadline_at'],runtime_budget_enforced=settings['enforced'])
    unlimited=mission(None)
    window=mission_time_budget_window(unlimited,now=datetime.now(timezone.utc)+timedelta(days=30))
    require(not unlimited.run_budget.enforced and unlimited.run_budget.max_runtime_seconds==0 and unlimited.state.time_budget_status=='unlimited'
            and not window['enforced'] and window['remainingSeconds']==0 and not _mission_runtime_budget_exhausted(unlimited),'Omitted budget acquired a time limit')
    completed={'status':'ok','autopilot_status':'completed','autopilot_pause_reason':'','remaining_steps':[],
               'effective_pause_on_handoff':False,'effective_max_runtime_seconds':None}
    with patch.object(cli,'_invoke_engine',return_value=completed) as invoke,patch.object(cli,'_sync_mission_from_result',return_value={'mission':{'mission_id':unlimited.mission_id}}):
        cli._run_mission_engine_cycles(store=store,mission=unlimited,workspace=workspace,project_profile='runtime budget contract')
    require(invoke.call_args.kwargs['max_runtime_override'] is None,'Omitted budget was forwarded to the engine')
    bounded=mission(2);bounded.state.status='running';bounded.state.elapsed_runtime_seconds=7200
    bounded.state.remaining_runtime_seconds=0;bounded.state.time_budget_status='budget_exhausted'
    require(bounded.run_budget.enforced and bounded.run_budget.max_runtime_seconds==7200 and _mission_runtime_budget_exhausted(bounded)
            and cli._auto_extend_runtime_budget_for_unattended_resume(bounded,trigger='manual_resume')=={},'Explicit budget was relaxed')
    legacy=mission(None);legacy.run_budget.max_runtime_seconds=43200;legacy.run_budget.focus_window_hours=12
    legacy.state.status='blocked';legacy.state.stop_reason=legacy.state.last_error='runtime_budget'
    legacy.state.time_budget_status='paused';legacy.state.remaining_runtime_seconds=0
    legacy.proof.blocked_by=['runtime_budget','keep-this-real-blocker']
    receipt=cli._auto_extend_runtime_budget_for_unattended_resume(legacy,trigger='manual_resume')
    require(receipt['reasonCode']=='implicit_runtime_budget_cleared' and receipt['addedSeconds']==0 and not legacy.run_budget.enforced
            and legacy.run_budget.max_runtime_seconds==0 and legacy.run_budget.deadline_at is None and legacy.state.time_budget_status=='unlimited'
            and legacy.state.status=='queued' and legacy.state.stop_reason is None and legacy.state.last_error is None
            and legacy.proof.blocked_by==['keep-this-real-blocker'],'Legacy budget repair changed a real blocker or invented hours')
    requested=root/'requested';authority=root/'authority';requested.mkdir();authority.mkdir()
    with patch.dict(os.environ,{CONTROL_PROJECT_ROOT_ENV:str(authority)}):
        configured=ControlRoomStore(requested)
    require(configured.requested_root==requested.resolve() and configured.root==authority.resolve()
            and configured.missions_path==authority.resolve()/'.agent_control/missions.json'
            and not (requested/'.agent_control/missions.json').exists(),'Authority root escaped its explicit configuration')
    return ['omitted budget and engine forwarding','explicit budget','legacy resume preserves blockers','configured authority root']


def releases(root):
    from . import runtime_updates as updates
    previous=dict(updates._CACHE);updates._CACHE.clear()
    try:
        require(updates.compare_version_tokens('2026.2.15','2026.4.14')<0 and updates.compare_version_tokens('v0.4.0','v0.9.0')<0,'Version order regressed')
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps({'version':'2026.4.14'}).encode()
        with patch.object(updates.urllib.request,'urlopen',return_value=response):
            payload=updates.latest_openclaw_release()
        require(payload['version']=='2026.4.14','NPM latest version was lost')
        response.read.return_value=json.dumps([{'name':'README.md'},{'name':'RELEASE_v0.8.0.md'},{'name':'RELEASE_v0.9.0.md'}]).encode()
        with patch.object(updates.urllib.request,'urlopen',return_value=response):
            payload=updates.latest_hermes_release()
        require(payload['version']=='v0.9.0' and 'RELEASE_v0.9.0.md' in payload['sourceUrl'],'GitHub release selection lost the newest version or its source')
    finally:
        updates._CACHE.clear();updates._CACHE.update(previous)
    return ['date and semantic version order','offline NPM response parsing','offline GitHub release selection']


def workspace(root):
    from .contract_gate import REPO
    from .subprocess_utils import capture_bounded_process
    captured=capture_bounded_process(['node','scripts/p22_workspace.mjs'],cwd=REPO,env=dict(os.environ),input_text=None,timeout=5)
    require(captured['returncode']==0 and not captured['timedOut'],captured['stderr'] or 'Workspace cases failed')
    observed=json.loads(captured['stdout'])
    require(observed['ok'],'Workspace cases did not pass')
    return observed['observed']


def codex_threads(root):
    from .connected_sessions.codex_items import summarize_thread
    folder=r'C:\P22-example\Research';prefix='\\\\?\\';device={'deviceId':'p22','deviceName':'Local'}
    def thread(source,cwd):
        return {'id':'01a10b6a-b309-7ed3-b223-3d6d6dda34a8','source':source,'cwd':cwd,'name':'',
                'preview':'Owned example','updatedAt':1791194000,'createdAt':1791190000,
                'status':{'type':'notLoaded'},'gitInfo':{'branch':'track/example'}}
    summary=summarize_thread(thread('exec',prefix+folder),device=device,projects=[])
    require(summary.cwd==folder and summary.project=='Research' and summary.background is True
            and summary.origin=='user' and summary.public()['background'] is True,'Background thread projection changed')
    require(summarize_thread(thread('vscode',folder),device=device,projects=[]).background is False,'Interactive thread marked background')
    projects=[{'id':'p','name':'Selected project','roots':[{'path':prefix+folder}]}]
    require(summarize_thread(thread('exec',prefix+folder+'\\sub'),device=device,projects=projects).project=='Selected project','Extended-prefix project root did not match')
    return ['extended-prefix path normalization','public background origin','interactive classification','project-root match']


def oauth_owner(root):
    from .provider_auth_broker import broker_codex_oauth,codex_broker_status
    # Credential authority already admits this owned synthetic subtree; no
    # saved operator account is read or a real refresh operation invoked.
    root=Path(root).parent/'.agent_control/proofs'/Path(root).name;runtime=root/'runtime';workspace=root/'workspace'
    tokens={'access':'p22-synthetic-access','refresh':'p22-synthetic-refresh','id_token':'p22-synthetic-identity'}
    result=broker_codex_oauth(tokens,{'accountId':'p22-synthetic','email':'p22@example.test'},workspace_root=workspace,runtime_root=runtime)
    files=list((runtime/'home/.cli-proxy-api').glob('*.json'))
    require(len(files)==1,'Refresh owner wrote duplicate credential stores')
    payload=json.loads(files[0].read_text(encoding='utf-8'))
    require(payload['refresh_token']==tokens['refresh'] and payload['type']=='codex','Refresh owner lost its synthetic credential')
    state=(workspace/'.agent_control/provider_auth_broker.json').read_text(encoding='utf-8')
    status=codex_broker_status(runtime)
    require(not any(value in state or value in json.dumps(status) for value in tokens.values())
            and result['owner']=='cliproxyapi' and status['authenticated'],'Public state leaked tokens or lost the sole owner')
    return ['one owned credential store','public state contains no supplied token','synthetic authenticated status']


def plan_hold(root):
    import time
    from types import SimpleNamespace
    from . import nightshift_ledger
    from .connected_sessions import plan_limits,live_limits
    from .nightshift_resources import Resources
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    service=SimpleNamespace(broker=SimpleNamespace(root=root),dispatch=lambda:None)
    with patch.object(plan_limits,'codex_limits',return_value=[]),patch.object(nightshift_ledger,'initialize',return_value=None),\
         patch.object(live_limits,'service_for',return_value=SimpleNamespace(snapshot=lambda:{'limits':[{**row,'stale':False} for row in plan_limits.claude_limits(root)]})):
        resources=Resources(service)
        try:
            soon=time.time()+3600
            for kind,used in [('five_hour',.74),('seven_day',.1)]:
                plan_limits.record_claude({'rateLimitType':kind,'utilization':used,'resetsAt':soon,'status':'allowed'},root)
            held=resources.plan_hold({'harness':'claude-code'},70)
            require(held and held.startswith('Holding: Claude Code 5-hour limit at 74%')
                    and 'plan-reset:claude-code' in resources.timers,'Fresh usage did not hold and schedule its reset')
            require(resources.plan_hold({'harness':'claude-code'},80) is None
                    and resources.plan_hold({'harness':'claude-code'},None) is None
                    and resources.plan_hold({'harness':'neyvia'},70) is None,'Plan hold ignored threshold or harness scope')
            plan_limits.record_claude({'rateLimitType':'five_hour','utilization':.9,'resetsAt':time.time()-60},root)
            require(resources.plan_hold({'harness':'claude-code'},70) is None,'Expired window kept new work held')
        finally:
            for timer in resources.timers.values():
                timer.cancel();timer.join(timeout=.2)
    return ['fresh threshold holds with reset timer','threshold and harness isolation','expired window releases work']


def run(root, contracts, categories):
    """C7 owns the same case functions used by the impact gate, without pytest."""
    from .proof_credential_guard import install
    install(root)
    rows=[]
    for identity,category,action in [('p22.runtime-budget','stale',budget),('p22.release-parsing','offline',releases),
                                     ('p22.workspace-selection','stale',workspace),('p22.codex-threads','unicode',codex_threads),
                                     ('p22.oauth-owner','permissions',oauth_owner),('p22.plan-hold','stale',plan_hold)]:
        if identity not in contracts or category not in categories:continue
        try:
            observed=action(Path(root)/identity)
            rows.append({'id':identity+'.migrated','contracts':[identity],'category':category,'status':'passed','observed':observed})
        except Exception as error:
            rows.append({'id':identity+'.migrated','contracts':[identity],'category':category,'status':'failed','error':str(error)})
    return rows
