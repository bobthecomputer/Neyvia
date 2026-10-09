"""Mission CLI contracts and bounded production command procedures.

Provider and detector seams in the procedure are explicit controlled transports;
the CLI, routing, Git isolation and persisted mission state remain production code.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .proofs_a_cli import require
from .proofs_a_cli_scheduler import environment, substitute


def check(identity, args, result):
    from . import cli
    if identity == 'a-cli.preferences.engine':
        if args['verify_commands'] is not None:
            require(result['effective_verify_commands'] == list(args['verify_commands']), identity, 'explicit verification commands changed')
        require(result['effective_harness'] == cli._normalize_harness_preference(args['harness_preference']), identity, 'selected harness changed')
        for supplied, field in [('max_runtime_override','effective_max_runtime_seconds'), ('parallel_agents_override','effective_parallel_agents')]:
            if args[supplied] is not None:
                require(result[field] == args[supplied], identity, 'explicit engine limit changed')
        persisted = args['mission_state'] or {}
        if args['parallel_agents_override'] is None and persisted.get('parallel_agents') is not None:
            require(result['effective_parallel_agents'] == max(1,int(persisted['parallel_agents'])), identity, 'saved mission concurrency changed')
        if args['pause_on_handoff'] is not None:
            require(result['effective_pause_on_handoff'] == bool(args['pause_on_handoff']), identity, 'handoff preference changed')
        if result['effective_harness'] == 'legacy_autonomous_engine':
            from .profiles import ProfileRegistry
            profiles = ProfileRegistry(Path(args['root']) / 'config' / 'profiles.json')
            selected = profiles.resolve(args['profile_name'], Path(args['root'])) if args['profile_name'] is not None or args['mode_name'] == 'profile' else None
            expected_profile = selected.name if selected else (args['profile_name'] or 'builder')
            require(result['execution_policy']['profile_name'] == expected_profile, identity, 'legacy resolved profile execution policy changed')
    elif identity == 'a-cli.preferences.budget':
        explicit = max(0,int(args['relative_stop_minutes'] or 0))*60
        relative = explicit or cli._parse_objective_relative_runtime_seconds(args['objective'])
        current = args['now'] or cli._now_local()
        if relative:
            expected = max(60,int(relative))
            delta = (datetime.fromisoformat(result['deadline_at']) - current.astimezone(timezone.utc)).total_seconds()
            require(result['max_runtime_seconds'] == expected and (delta == expected if args['now'] is not None else abs(delta-expected) < 2), identity, 'relative timer changed deadline or duration')
        if result['deadline_at']:
            require(result['run_until_behavior'] == 'continue_until_blocked' and result['enforced'] is True and result['max_runtime_seconds'] >= 60, identity, 'deadline did not govern continuous run contract')
    elif identity == 'a-cli.preferences.continue':
        if args['result'].get('autopilot_pause_reason') == 'delegated_runtime_running':
            require(result is False, identity, 'delegated runtime caused duplicate mission loop')
    elif identity == 'a-cli.preferences.poll':
        require(result >= 1 if args['mission'].run_budget.run_until_behavior == 'continue_until_blocked' else result == 0, identity, 'mission polling does not match continuation mode')
    elif identity == 'a-cli.preferences.docs':
        if result.get('error'):
            return
        mission = args['store'].get_mission(args['mission_id'])
        require(mission is not None, identity, 'mission result was not persisted')
        files = [str(f) for f in (args['result'].get('changed_files') or []) if str(f).strip()]
        files += [str(f) for session in mission.delegated_runtime_sessions for f in session.changed_files if str(f).strip()]
        if args['result'].get('autopilot_status') == 'completed' and files and all(cli._is_docs_only_path(f) for f in files) and not cli._mission_expects_docs_only_output(mission) and not mission.state.verification_failures and not any(s.status == 'waiting_for_approval' for s in mission.delegated_runtime_sessions):
            require(mission.state.status == 'blocked' and mission.state.last_error == 'docs_only_completion_without_product_changes', identity, 'documentation-only completion counted as product work')
    elif identity == 'a-cli.preferences.queue':
        from .cluster import ClusterRegistry
        job = ClusterRegistry(args['root']).get_job(result['jobId'])
        require(job and job['missionId'] == args['mission'].mission_id and job['jobKind'] == 'mission_resume' and job['status'] in {'queued','leased','running'}, identity, 'resume receipt does not identify an active durable job')
        payload = job['payload']; root = str(args['root'])
        require(payload['controlProjectRoot'] == payload['executionRoot'] == root and payload['workspaceRoot'] == str(args['workspace'].root_path) and payload['command'][payload['command'].index('--root')+1] == root and payload['dispatchSource'] == 'composer_arrow', identity, 'resume command lost authoritative control or workspace root')
    elif identity == 'a-cli.preferences.dispatch':
        if result.get('reason') == 'mission_resume_already_running':
            require(result.get('skipped') and result.get('pid') in result.get('activePids',[]), identity, 'active process was not deduplicated')
        if result.get('queue') == 'cluster_registry':
            from .mission_control import ControlRoomStore
            from .cluster import ClusterRegistry
            store = ControlRoomStore(args['root']); job = ClusterRegistry(store.root).get_job(result['jobId'])
            require(job and job['payload']['controlProjectRoot'] == str(store.root), identity, 'cluster resume queued outside authoritative mission store')
    elif identity == 'a-cli.preferences.pid':
        expected = args['completed'].returncode == 0 and f',"{args["pid"]}",' in args['completed'].stdout.strip()
        require(result == expected, identity, 'localized tasklist absence mistaken for live process')
    elif identity == 'a-cli.preferences.started':
        if result == 0:
            from .mission_control import ControlRoomStore
            values=args['args']; missions=ControlRoomStore(Path(values.root)).load_missions()
            mission=next((m for m in reversed(missions) if m.objective == values.objective),None)
            require(mission is not None,identity,'successful start did not persist its mission')
            relative=max(0,int(getattr(values,'relative_stop_minutes',0) or 0))*60 or cli._parse_objective_relative_runtime_seconds(values.objective)
            if relative:
                require(mission.run_budget.max_runtime_seconds == max(60,int(relative)) and mission.run_budget.run_until_behavior == 'continue_until_blocked' and mission.run_budget.deadline_at,identity,'mission dropped requested relative timer')
    elif identity == 'a-cli.preferences.mark-dispatch':
        mission=args['mission']; dispatch=args['dispatch']
        require(mission.state.status == ('blocked' if dispatch.get('blocked') else 'running'),identity,'dispatch state does not follow dispatch result')
    elif identity == 'a-cli.preferences.compact':
        require(result['schema'] == 'fluxio.mission_action_compact_receipt.v1' and result['mission']['mission_id'] == args['mission'].mission_id and result['mission']['state']['status'] == args['mission'].state.status and 'snapshot' not in result,identity,'compact action receipt lost mission identity or included full snapshot')


def check_cycle(mission, result, remaining, checkpoint):
    identity='a-cli.preferences.cycle'
    from .mission_control import mission_runtime_budget_enforced
    require(result['effective_pause_on_handoff'] == (mission.run_budget.run_until_behavior != 'continue_until_blocked'),identity,'mission handoff pause ignored continuation mode')
    if mission_runtime_budget_enforced(mission):
        require(result['effective_max_runtime_seconds'] == remaining,identity,'engine received wrong remaining mission budget')
    if checkpoint:
        require(Path(checkpoint).is_file(),identity,'mission resume selected a missing checkpoint')


def check_workspace(args, store, workspace, payload):
    identity = 'a-cli.preferences.workspace'
    persisted = store.get_workspace(workspace.workspace_id)
    require(persisted is not None and vars(persisted) == vars(workspace), identity, 'workspace preference write was not durable')
    for field in ('preferred_harness','routing_strategy','commit_message_style','execution_target_preference'):
        if hasattr(args,field):
            require(getattr(workspace,field) == getattr(args,field), identity, 'workspace preference changed: '+field)
    from .mission_control import normalize_minimax_auth_mode, normalize_openai_codex_auth_mode
    for field, normalizer in [('minimax_auth_mode',normalize_minimax_auth_mode),('openai_codex_auth_mode',normalize_openai_codex_auth_mode)]:
        if hasattr(args,field):
            require(getattr(workspace,field) == normalizer(getattr(args,field)), identity, 'workspace authentication preference changed')
    require(workspace.auto_optimize_routing == (str(getattr(args,'auto_optimize_routing','false')).lower() in {'true','1','yes','on'}), identity, 'automatic routing preference changed')
    require(('snapshot' not in payload) if getattr(args,'skip_snapshot',False) else ('snapshot' in payload), identity, 'workspace snapshot selection changed')


def check_spawn_options(platform, options):
    require(options['start_new_session'] == (platform != 'win32') and options['stdin'] == subprocess.DEVNULL and options['close_fds'], 'a-cli.preferences.spawn', 'background child lost detached session or inherited interactive input')


def check_stop_history(before, after):
    require(all(next((s for s in after if s.delegated_id == old.delegated_id),None) == old for old in before if old.status in {'completed','failed','stopped'}), 'a-cli.preferences.stop', 'mission stop rewrote terminal delegated history')


def check_watchdog(state, preserved, mode):
    identity = 'a-cli.preferences.watchdog'
    if mode == 'one_shot' and preserved:
        require(state['loopMode'] == 'ongoing' and state['processPid'] == preserved['processPid'] and state['runsCompleted'] == preserved.get('runsCompleted',state['runsCompleted']) and state['oneShotProcessPid'] == os.getpid(), identity, 'one-shot pass replaced active scoped loop identity')
    elif mode == 'ongoing':
        require(state['processPid'] == os.getpid() and state['processAlive'] and state['supervisorActive'], identity, 'scoped ongoing pass lost own process liveness')


def procedure(root, goal, rejects):
    from . import cli
    from .mission_control import ControlRoomStore, DelegatedRuntimeSession
    root = Path(root) / 'mission-cli'; root.mkdir(); cli.bootstrap_project(root)
    (root/'README.md').write_text('# Disposable CLI proof\n')
    for command in [['git','init','--quiet'],['git','add','.'],['git','-c','user.name=PROOFS-a','-c','user.email=proofs-a@localhost','commit','--quiet','-m','Local proof fixture']]:
        subprocess.run(command,cwd=root,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**hidden_windows_subprocess_kwargs())
    def command(function, **values):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=function(argparse.Namespace(**values))
        require(code == 0,'a-cli.preferences.workspace','production CLI command failed: '+output.getvalue())
        return json.loads(output.getvalue())
    base = dict(root=str(root), name='CLI preferences',path=str(root),default_runtime='hermes',user_profile='builder',preferred_harness='legacy_autonomous_engine',routing_strategy='uniform_quality',route_overrides_json='[{"role":"planner","provider":"minimax","model":"MiniMax-M2.7","effort":"high"}]',auto_optimize_routing='true',openai_codex_auth_mode='none',minimax_auth_mode='minimax-portal-oauth',commit_message_style='detailed',execution_target_preference='isolated_worktree',workspace_id=None,skip_snapshot=False)
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None,FLUXIO_CLUSTER_ROOT=None,FLUXIO_CONTROL_ROOM_FAST='1',FLUXIO_MISSION_ACTION_COMPACT='1',FLUXIO_MISSION_DISPATCH_MODE='cluster_worker'):
        saved=command(cli.cmd_workspace_save,**base)
        with substitute(ControlRoomStore,'build_snapshot',lambda self: (_ for _ in ()).throw(RuntimeError('unexpected full snapshot'))):
            quick=command(cli.cmd_workspace_save,**{**base,'workspace_id':saved['workspace']['workspace_id'],'skip_snapshot':True})
        goal('a-cli.preferences.workspace',saved['workspace']['preferred_harness']=='legacy_autonomous_engine' and saved['workspace']['auto_optimize_routing'] and saved['workspace']['route_overrides'][0]['model']=='MiniMax-M2.7' and saved['workspace']['minimax_auth_mode']=='minimax-portal-oauth' and saved['snapshot']['workspaces'][0]['preferred_harness']=='legacy_autonomous_engine' and saved['snapshot']['workspaces'][0]['execution_target_preference']=='isolated_worktree' and saved['snapshot']['workspaces'][0]['route_overrides'][0]['model']=='MiniMax-M2.7' and 'snapshot' not in quick)
        # Explicit controlled engine transports record the real orchestrator's inputs.
        dispatches=[]
        def transport(self,**kwargs):
            dispatches.append(kwargs)
            return {'status':'ok','session_path':str(root/'.agent_runs'/'controlled-provider'),'autopilot_status':'completed','remaining_steps':[],'verification_failures':[],'changed_files':['app.py']}
        invoke=dict(root=root,objective='Bounded local routing procedure',docs=[],mode_name='autopilot',profile_name='hands_free_builder',persona_override=None,iterations=1,verify_commands=[],project_profile='PROOFS-a controlled engine boundary',resume_from=None,resume_checkpoint=None,checkpoint_every=1,pause_on_verification_failure=True,runtime_id='hermes',mission_id='proof-legacy',harness_preference='legacy_autonomous_engine',routing_strategy_override='uniform_quality',execution_target_preference='isolated_worktree')
        with substitute(cli.AutonomousEngine,'run',transport), substitute(cli.FluxioHarness,'run',transport):
            legacy=cli._invoke_engine(**invoke)
            goal('a-cli.preferences.engine',dispatches[-1]['verify_commands']==[] and legacy['effective_verify_commands']==[] and legacy['harness_id']==legacy['effective_harness']=='legacy_autonomous_engine' and legacy['execution_scope']['execution_root']!=str(root) and legacy['execution_scope']['execution_target']=='worktree' and legacy['execution_policy']['profile_name']=='hands_free_builder' and all(next(row for row in legacy['route_configs'] if row['role']==role)['model']=='gpt-5.6-sol' for role in ['planner','executor']))
            for harness in ['legacy_autonomous_engine','fluxio_hybrid']:
                result=cli._invoke_engine(**{**invoke,'harness_preference':harness,'execution_target_preference':'workspace_root','mission_state':{'parallel_agents':4},'resume_from':'controlled-provider'})
                goal('a-cli.preferences.engine',result['status']=='ok' and dispatches[-1]['parallel_agents']==4 and 'mission_state' not in dispatches[-1])
        now=datetime(2026,5,7,12,tzinfo=timezone.utc)
        for objective,minutes,seconds in [('Run for 2 days and keep going',0,172800),('Run until 8 a.m.',0,72000),('Finish bounded task',35,2100)]:
            budget=cli._mission_budget_settings(objective,12,'pause_on_failure',relative_stop_minutes=minutes,now=now)
            goal('a-cli.preferences.budget',budget['max_runtime_seconds']==seconds and budget['run_until_behavior']=='continue_until_blocked' and budget['deadline_at'])
        for mode in ['continue_until_blocked','pause_on_failure']:
            mission=argparse.Namespace(run_budget=argparse.Namespace(run_until_behavior=mode,deadline_at=None))
            goal('a-cli.preferences.continue',not cli._mission_should_continue_after_result(mission,{'status':'ok','autopilot_status':'paused','autopilot_pause_reason':'delegated_runtime_running','remaining_steps':['wait']}))
            goal('a-cli.preferences.poll',cli._mission_poll_interval_seconds(mission)>=1 if mode=='continue_until_blocked' else cli._mission_poll_interval_seconds(mission)==0)
        store=ControlRoomStore(root); workspace=store.get_workspace(saved['workspace']['workspace_id'])
        mission=store.create_mission(workspace_id=workspace.workspace_id,runtime_id='hermes',objective='Implement product feature',success_checks=[],mode='Autopilot',verification_commands=[],max_runtime_seconds=3600)
        response=cli._sync_mission_from_result(store,mission.mission_id,{'autopilot_status':'completed','changed_files':['README.md','docs/plan.md'],'remaining_steps':[],'verification_failures':[]})
        goal('a-cli.preferences.docs',not response.get('error') and store.get_mission(mission.mission_id).state.last_error=='docs_only_completion_without_product_changes' and store.get_mission(mission.mission_id).state.status=='blocked')
        with environment(FLUXIO_MISSION_WORKER_HOST_ID='proof-worker'):
            first=cli._launch_async_mission_resume(root,mission.mission_id); duplicate=cli._launch_async_mission_resume(root,mission.mission_id)
        goal('a-cli.preferences.queue',first['jobId'].startswith('job_') and first['queue']=='cluster_registry' and first['worker']=='grant_agent.worker' and first['preferredHost']=='proof-worker' and duplicate['skipped'] and duplicate['jobId']==first['jobId'])
        goal('a-cli.preferences.dispatch',duplicate['reason']=='mission_resume_already_queued')
        requested=root/'requested-control'; requested.mkdir()
        authority=root/'authoritative-control'; authority.mkdir()
        with environment(FLUXIO_CONTROL_PROJECT_ROOT=str(authority)):
            authoritative=ControlRoomStore(requested)
            workspace=authoritative.load_workspaces()[0]
            routed=authoritative.create_mission(workspace_id=workspace.workspace_id,runtime_id='hermes',objective='Authority routed resume',success_checks=[],mode='Autopilot',verification_commands=[],max_runtime_seconds=0)
            queued=cli._launch_async_mission_resume(requested,routed.mission_id)
            from .cluster import ClusterRegistry
            job=ClusterRegistry(authority).get_job(queued['jobId'])
            goal('a-cli.preferences.dispatch',job['payload']['controlProjectRoot']==str(authority) and job['payload']['command'][job['payload']['command'].index('--root')+1]==str(authority))
        # Controlled Popen swaps only the provider command for an inert actual child.
        observed=[]; children=[]; original_popen=subprocess.Popen
        def child_transport(command,**options):
            observed.append(options)
            child=original_popen([sys.executable,'-I','-c','print("inert transport completed")'],**options)
            children.append(child)
            return child
        try:
            with environment(FLUXIO_MISSION_DISPATCH_MODE='local_process'), substitute(cli.sys,'platform','linux'), substitute(cli.subprocess,'Popen',child_transport):
                launched=cli._launch_async_mission_resume(root,mission.mission_id)
            goal('a-cli.preferences.spawn',launched['pid']==children[0].pid and observed[0]['start_new_session'] is True)
        finally:
            for child in children:
                child.wait(timeout=5)
        localized=subprocess.CompletedProcess(['tasklist'],0,'Information : aucune tâche en service ne correspond aux critères spécifiés.\n','')
        goal('a-cli.preferences.pid',not cli._tasklist_has_pid(42944,localized))
        for platform in ['win32','linux']:
            options={'start_new_session':platform!='win32','stdin':subprocess.DEVNULL,'close_fds':True}
            check_spawn_options(platform,options)
        goal('a-cli.preferences.spawn',True)
        rejects('a-cli.preferences.spawn',lambda:check_spawn_options('linux',{'start_new_session':False,'stdin':subprocess.DEVNULL,'close_fds':True}))
        completed=DelegatedRuntimeSession(delegated_id='completed-history',runtime_id='hermes',launch_command='controlled',mission_id=mission.mission_id,status='completed')
        _commands_procedure(root, goal, command, transport, dispatches)


def _commands_procedure(root, goal, command, transport, dispatches):
    from . import cli
    from .models import RuntimeInstallStatus, DelegatedRuntimeSession, RunState
    from .mission_control import ControlRoomStore
    from .mission_watchdog import write_watchdog_supervisor_state
    from .checkpoints import CheckpointStore
    from types import SimpleNamespace
    status=RuntimeInstallStatus(runtime_id='hermes',label='Controlled CLI transport',detected=True,doctor_summary='Fixture transport declared ready')
    adapter=SimpleNamespace(doctor=lambda root:status)
    fixed=datetime(2026,4,16,22,tzinfo=timezone.utc)
    routes=[{'role':'planner','provider':'openai','model':'gpt-5.5','effort':'high'},{'role':'backend','provider':'openai','model':'gpt-5.5','effort':'high'},{'role':'frontend','provider':'openai','model':'gpt-5.5','effort':'high'},{'role':'verifier','provider':'openrouter','model':'openrouter/deepseek/deepseek-v4-pro','effort':'high'}]
    with substitute(cli,'runtime_adapter_map',lambda:{'hermes':adapter}), substitute(cli,'load_telegram_destination',lambda root:''), substitute(cli,'detect_default_verification_commands',lambda root:[]), substitute(cli.FluxioHarness,'run',transport):
        for name,objective,minutes,seconds,selected_routes in [('deadline','Work on app until 8 a.m.',0,36000,[]),('relative','Refine product copy',35,2100,[]),('routes','Use selected model routes',0,7200,routes)]:
            local=root/name; local.mkdir(); cli.bootstrap_project(local)
            store=ControlRoomStore(local); workspace=store.load_workspaces()[0]
            workspace.preferred_harness='fluxio_hybrid'; workspace.execution_target_preference='workspace_root'; store.save_workspaces([workspace])
            with substitute(cli,'_now_local',lambda:fixed), substitute(cli,'mission_time_budget_window',lambda mission:{'remainingSeconds':seconds}):
                started=command(cli.cmd_mission_start,root=str(local),workspace_id=workspace.workspace_id,runtime='hermes',objective=objective,success_check=[],mode='Autopilot',budget_hours=2 if name=='routes' else 4,relative_stop_minutes=minutes,run_until='pause_on_failure',profile='advanced',route_overrides_json=json.dumps(selected_routes),escalation_destination='',launch_async=False)
            run=dispatches[-1]
            goal('a-cli.preferences.started',started['mission']['run_budget']['max_runtime_seconds']==seconds and (started['mission']['run_budget']['deadline_at'] and started['mission']['run_budget']['run_until_behavior']=='continue_until_blocked' if name!='routes' else started['mission']['route_configs']==routes and run['route_overrides']==routes))
            goal('a-cli.preferences.cycle',run['max_runtime_seconds']==seconds and (not run['autopilot_guardrails']['pause_on_handoff'] if name!='routes' else True))
        local=root/'resume'; local.mkdir(); cli.bootstrap_project(local)
        store=ControlRoomStore(local); workspace=store.load_workspaces()[0]
        mission=store.create_mission(workspace_id=workspace.workspace_id,runtime_id='hermes',objective='Resume latest safe checkpoint',success_checks=[],mode='Autopilot',verification_commands=[],max_runtime_seconds=7200,run_until_behavior='continue_until_blocked')
        session=local/'.agent_runs/continuity'
        checkpoint=CheckpointStore(session).save(session_id='continuity',iteration=3,run_state=RunState(objective=mission.objective,plan_steps=['Resume'],acceptance_checks=[]),context={'used_tokens':120},doc_sources=[])
        mission.state.latest_session_id='continuity'; mission.state.status='running'; store.update_mission(mission)
        with substitute(cli,'mission_time_budget_window',lambda mission:{'remainingSeconds':1800}):
            resumed=command(cli.cmd_mission_action,root=str(local),mission_id=mission.mission_id,action='resume',launch_async=False)
        goal('a-cli.preferences.cycle',dispatches[-1]['resume_from_session_id']=='continuity' and dispatches[-1]['resume_from_checkpoint_path']==str(checkpoint) and not dispatches[-1]['autopilot_guardrails']['pause_on_handoff'])
        async_root=root/'async'; async_root.mkdir(); cli.bootstrap_project(async_root)
        async_store=ControlRoomStore(async_root); workspace=async_store.load_workspaces()[0]
        async_started=command(cli.cmd_mission_start,root=str(async_root),workspace_id=workspace.workspace_id,runtime='hermes',objective='Dispatch bounded mission in background',success_check=[],mode='Autopilot',budget_hours=48,run_until='continue_until_blocked',profile='builder',escalation_destination='',launch_async=True)
        dispatched=command(cli.cmd_mission_action,root=str(async_root),mission_id=async_started['mission']['mission_id'],action='resume',launch_async=True)
        goal('a-cli.preferences.mark-dispatch',async_started['launchedAsync'] and async_started['mission']['state']['status']=='running' and async_started['dispatch']['jobId']==dispatched['dispatch']['jobId'] and dispatched['mission']['state']['status']=='running')
        goal('a-cli.preferences.compact',dispatched['schema']=='fluxio.mission_action_compact_receipt.v1' and dispatched['launchedAsync'] and 'snapshot' not in dispatched)
        # Duplicate live process receipt: own child with matching inert command labels.
        child=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(20)','grant_agent.cli','mission-action','--mission-id','duplicate-owned','--action','resume'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**hidden_windows_subprocess_kwargs())
        try:
            events=async_root/'.agent_control/mission_events.jsonl'
            with events.open('a',encoding='utf-8') as handle:
                handle.write(json.dumps({'mission_id':'duplicate-owned','kind':'mission.resume_dispatched','metadata':{'pid':child.pid,'logPath':str(async_root/'owned.log'),'command':['grant_agent.cli','mission-action','--mission-id','duplicate-owned','--action','resume']}})+'\n')
            duplicate=cli._launch_async_mission_resume(async_root,'duplicate-owned')
            goal('a-cli.preferences.dispatch',duplicate['skipped'] and duplicate['pid']==child.pid and duplicate['reason']=='mission_resume_already_running')
        finally:
            child.terminate(); child.wait(timeout=5)
        completed=DelegatedRuntimeSession(delegated_id='completed-history',runtime_id='hermes',launch_command='controlled',mission_id=mission.mission_id,status='completed')
        queued=DelegatedRuntimeSession(delegated_id='queued-history',runtime_id='hermes',launch_command='controlled',mission_id=mission.mission_id,status='queued')
        mission=store.get_mission(mission.mission_id); mission.delegated_runtime_sessions=[completed,queued]; store.update_mission(mission)
        stopped=command(cli.cmd_mission_action,root=str(local),mission_id=mission.mission_id,action='stop',launch_async=False)
        history=store.get_mission(mission.mission_id).delegated_runtime_sessions
        goal('a-cli.preferences.stop',history[0]==completed and history[1].status=='stopped')
    # Only isolated state is used; no existing service or task is read or restarted.
    watch=root/'watchdog'; watch.mkdir(); cli.bootstrap_project(watch)
    args=argparse.Namespace(root=str(watch),stale_minutes=60,no_write_report=False,notify_telegram=False,notify_ntfy=False,interval_seconds=1200,advance_self_improvement=False)
    write_watchdog_supervisor_state(watch,{'schema':'fluxio.mission_watchdog_supervisor.v1','root':str(watch),'processPid':os.getpid(),'status':'clear','loopMode':'ongoing','supervisorActive':True,'processAlive':True,'startedAt':'2026-07-01T00:00:00+00:00','lastRunAt':'2026-07-01T00:00:00+00:00','runsCompleted':7,'intervalSeconds':1200,'staleMinutes':60})
    with substitute(cli,'_watchdog_loop_pid_active',lambda pid:pid==os.getpid()), substitute(cli,'write_browser_dependency_preflight',lambda root:{'schema':'fluxio.browser_dependency_preflight.v1','status':'passed','browserProofAvailable':True}):
        once=cli._run_mission_watchdog_pass(args=args,root=watch,started_at='2026-07-01T00:05:00+00:00',runs_completed=1,loop_mode='one_shot')
        ongoing=cli._run_mission_watchdog_pass(args=args,root=watch,started_at='2026-07-01T00:05:00+00:00',runs_completed=1,loop_mode='ongoing')
    goal('a-cli.preferences.watchdog',once['supervisor']['loopMode']=='ongoing' and once['supervisor']['processPid']==os.getpid() and once['supervisor']['runsCompleted']==7 and once['supervisor']['oneShotProcessPid']==os.getpid() and ongoing['supervisor']['processPid']==os.getpid() and ongoing['supervisor']['processAlive'] and ongoing['supervisor']['supervisorActive'])
