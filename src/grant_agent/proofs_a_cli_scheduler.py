"""Checks at scheduler transactions and isolated real local worker procedures."""
from __future__ import annotations
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from .proofs_a_cli import require


@contextmanager
def environment(**values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def substitute(owner, name, value):
    previous = getattr(owner, name)
    try:
        setattr(owner, name, value)
        yield
    finally:
        setattr(owner, name, previous)


def check(identity, args, result):
    from . import cluster as c
    if identity == 'a-cli.scheduler.root':
        configured = str(os.environ.get('FLUXIO_CLUSTER_ROOT') or os.environ.get('FLUXIO_CONTROL_PROJECT_ROOT') or '').strip()
        expected = Path(configured if configured and args['use_configured_root'] else args['root']).expanduser().resolve()
        require(result == expected, identity, 'registry ignored explicit configured root')
    elif identity == 'a-cli.scheduler.capabilities':
        if result['hostType'] == 'nas_control' and c.nas_execution_policy() == 'efficient':
            require('app.self_repair' in result['capabilities'] and 'frontend.build' not in result['capabilities'], identity, 'efficient controller overstates capability')
            require(('browser.verify' in result['capabilities']) == c._browser_preflight_proves_available(Path(args['root']).resolve()), identity, 'browser capability lacks passing receipt')
        require(result['maxConcurrentJobs'] >= 0 and result['concurrencyMode'] == ('limited' if result['maxConcurrentJobs'] else 'unlimited'), identity, 'capacity classification differs')
    elif identity == 'a-cli.scheduler.job':
        registry = args['self']
        stored = registry.get_job(result['jobId'])
        require(stored['jobId'] == result['jobId'], identity, 'queued job missing from database')
        key = str(args['dedupe_key'] or '').strip()
        if key:
            with registry._connect() as db:
                count = db.execute("SELECT COUNT(*) FROM jobs WHERE dedupe_key=? AND status IN ('queued','leased','running')", (key,)).fetchone()[0]
            require(count <= 1, identity, 'duplicate active canonical job')
    elif identity == 'a-cli.scheduler.claim':
        job, lease = result.get('job'), result.get('lease')
        require(bool(job) == bool(lease), identity, 'job and lease admission disagree')
        if job:
            require(job['status'] in {'leased', 'running'} and job['leaseId'] == lease['leaseId'] and job['jobId'] == lease['jobId'] and job['assignedHost'] == result['host']['hostId'], identity, 'claim receipt lost exact job/lease/host affinity')
    elif identity == 'a-cli.scheduler.choose':
        if result:
            require(result['online'] and set(args['job'].get('requiredCapabilities', [])) <= set(result['capabilities']), identity, 'chosen host lacks availability or requested capabilities')
    elif identity == 'a-cli.scheduler.roles':
        session = args['session']
        expected = ['runtime.launch']
        if any(word in (session.target_role+' '+session.target_phase).lower() for word in ('browser','playwright','frontend','ui')):
            expected = ['browser.verify', 'runtime.launch']
        require(result == expected, identity, 'role authority inferred from prompt words')
    elif identity == 'a-cli.scheduler.worker':
        if result['claimed']:
            require(result['job']['status'] == result['result']['status'], identity, 'worker completion receipt differs from durable terminal job')
            registry = c.ClusterRegistry(args['root'])
            events = registry.list_events(job_id=result['job']['jobId'], limit=100)
            require(any(event['kind'] == 'job.' + result['job']['status'] for event in events), identity, 'worker terminal event absent')
        elif args['max_concurrent_jobs'] is not None:
            require(result['host']['maxConcurrentJobs'] == c.normalize_concurrency_limit(args['max_concurrent_jobs']), identity, 'empty worker poll failed to advertise capacity')
    elif identity == 'a-cli.scheduler.execute':
        if 'returnCode' in result and result['status'] in {'completed', 'failed'}:
            require((result['status'] == 'completed') == (result['returnCode'] == 0), identity, 'child return code was falsely completed')
    elif identity == 'a-cli.scheduler.threads':
        import concurrent.futures
        completion, admission, thread = result
        require(isinstance(completion, concurrent.futures.Future) and isinstance(admission, concurrent.futures.Future) and completion is not admission and isinstance(thread, threading.Thread), identity, 'unlimited attempt did not return independent completion/admission channel')
    elif identity == 'a-cli.scheduler.lifecycle':
        from .worker import WORKER_STATE_SCHEMA, _worker_state_path
        require(result['schema'] == WORKER_STATE_SCHEMA and result['status'] == args['status'] and result['hostId'] == args['host_id'] and result['lastError'] == args['error'], identity, 'worker lifecycle receipt differs from transition')
        require(json.loads(_worker_state_path(args['root']).read_text(encoding='utf-8')) == result, identity, 'worker lifecycle state not persisted')


def check_stale(db, host_id):
    row = db.execute('SELECT online,current_load FROM hosts WHERE host_id=?', (host_id,)).fetchone()
    require(row and not row['online'] and row['current_load'] == 0, 'a-cli.scheduler.stale', 'stale host still advertises availability')


def check_expired(db, lease_id, job_id):
    row = db.execute('SELECT status FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
    job = db.execute('SELECT status,lease_id FROM jobs WHERE job_id=?', (job_id,)).fetchone()
    require(row and row['status'] == 'expired' and (not job or job['lease_id'] != lease_id or job['status'] not in {'leased','running'}), 'a-cli.scheduler.expire', 'expired lease still owns running job')


def check_load(db, host_id, load):
    identity = 'a-cli.scheduler.load'
    expected = db.execute("SELECT COUNT(*) FROM leases l JOIN jobs j ON j.job_id=l.job_id WHERE l.host_id=? AND l.status='active' AND j.status IN ('leased','running')", (host_id,)).fetchone()[0]
    host = db.execute('SELECT current_load FROM hosts WHERE host_id=?', (host_id,)).fetchone()
    require(load == expected and (host is None or host['current_load'] == expected), identity, 'host load differs from active durable leases')


def check_lease(db, job_id, host_id, lease_id):
    identity = 'a-cli.scheduler.lease'
    lease = db.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
    job = db.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
    require(lease and job and lease['status'] == 'active' and lease['host_id'] == host_id and job['assigned_host'] == host_id and job['lease_id'] == lease_id and job['status'] == 'leased', identity, 'created lease did not own exact queued job')
    scopes = json.loads(job['planned_file_scope_json'])
    others = db.execute("SELECT j.* FROM jobs j JOIN leases l ON l.lease_id=j.lease_id WHERE j.job_id!=? AND j.workspace_id=? AND j.status IN ('leased','running') AND l.status='active'", (job_id, job['workspace_id'])).fetchall()
    from .cluster import _scopes_overlap, _normalized_scope
    require(not any(_scopes_overlap(_normalized_scope(scopes), _normalized_scope(json.loads(other['planned_file_scope_json']))) for other in others), identity, 'lease overlaps another active writer')


def check_worker_environment(job, env):
    identity = 'a-cli.scheduler.environment'
    payload = job.get('payload') or {}
    control = str(payload.get('controlProjectRoot') or payload.get('control_project_root') or '').strip()
    if control:
        require(env['FLUXIO_CONTROL_PROJECT_ROOT'] == str(Path(control).expanduser().resolve()), identity, 'job execution lost authoritative control root')
    configured = os.environ.get('FLUXIO_CLUSTER_ROOT')
    if configured:
        require(env.get('FLUXIO_CLUSTER_ROOT') == configured, identity, 'control-root binding moved cluster database')


def procedure(root, goal, rejects):
    from . import cluster as c, worker as w
    from .models import DelegatedRuntimeSession
    from .runtime_supervisor import _cluster_required_capabilities
    root = Path(root) / 'scheduler'; root.mkdir()
    # Detector fixtures are explicit and avoid reading user credential files.
    with environment(FLUXIO_CLUSTER_ROOT=None, FLUXIO_CONTROL_PROJECT_ROOT=None, FLUXIO_HOST_ID='PROOF-WORKER', FLUXIO_NAS_EXECUTION_POLICY='efficient'), substitute(c, '_detect_runtime_names', lambda root: []):
        with environment(FLUXIO_CLUSTER_ROOT=str(root / 'shared')):
            shared, legacy = c.ClusterRegistry(root / 'mission'), c.ClusterRegistry(root / 'mission', use_configured_root=False)
            goal('a-cli.scheduler.root', shared.root == (root / 'shared').resolve() and legacy.root == (root / 'mission').resolve() and shared.db_path != legacy.db_path)
        caps = c.build_local_worker_capabilities(root, host_id='nas.example.invalid')
        goal('a-cli.scheduler.capabilities', 'app.self_repair' in caps['capabilities'] and 'browser.verify' not in caps['capabilities'])
        marker = root / 'scratch-browser'; marker.write_text('declared fixture executable marker')
        receipt = root / '.agent_control' / 'browser_dependency_preflight.json'; receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({'status': 'passed', 'browserProofAvailable': True, 'chromeExecutable': str(marker)}))
        caps = c.build_local_worker_capabilities(root, host_id='nas.example.invalid')
        goal('a-cli.scheduler.capabilities', 'browser.verify' in caps['capabilities'] and 'frontend.build' not in caps['capabilities'])
        planner = DelegatedRuntimeSession(delegated_id='plan', runtime_id='hermes', launch_command='plan and verify UI later', target_phase='plan', target_role='planner')
        browser = DelegatedRuntimeSession(delegated_id='browser', runtime_id='hermes', launch_command='run checks', target_phase='verify', target_role='browser_verifier')
        goal('a-cli.scheduler.roles', _cluster_required_capabilities(planner) == ['runtime.launch'] and _cluster_required_capabilities(browser) == ['browser.verify', 'runtime.launch'])
        registry = c.ClusterRegistry(root / 'registry')
        job = registry.upsert_job(dedupe_key='stable', mission_id='mission', workspace_id='workspace', runtime_id='hermes')
        duplicate = registry.upsert_job(dedupe_key='stable', mission_id='mission', workspace_id='workspace', runtime_id='hermes')
        goal('a-cli.scheduler.job', job['jobId'] == duplicate['jobId'] and not job['deduplicated'] and duplicate['deduplicated'] and len(registry.list_jobs()) == 1)
        registry.heartbeat_host({'hostId': 'PROOF-STALE', 'hostType': 'workstation', 'capabilities': ['runtime.launch']})
        with registry._connect() as db:
            db.execute("UPDATE hosts SET last_heartbeat_at='2020-01-01T00:00:00+00:00' WHERE host_id='PROOF-STALE'")
        goal('a-cli.scheduler.stale', registry.mark_stale_hosts(stale_seconds=1) == 1 and not registry.get_host('PROOF-STALE')['online'])
        registry = c.ClusterRegistry(root / 'scope')
        registry.heartbeat_host({'hostId': 'PROOF-WORKER', 'hostType': 'workstation', 'capabilities': ['runtime.launch'], 'maxConcurrentJobs': 2})
        first = registry.upsert_job(mission_id='first', workspace_id='same', runtime_id='hermes', planned_file_scope=['src/app.py'])
        second = registry.upsert_job(mission_id='second', workspace_id='same', runtime_id='hermes', planned_file_scope=['src'])
        # Conflict must observe an active lease. Expiry is forced explicitly
        # below; a one-second TTL raced shared-disk durable writes here.
        assigned = registry.assign_job(first['jobId'])
        conflict = registry.assign_job(second['jobId'])
        goal('a-cli.scheduler.lease', assigned['ok'] and not conflict['ok'] and conflict['error'] == 'file_scope_conflict' and conflict['job']['status'] == 'queued')
        with registry._connect() as db:
            db.execute("UPDATE leases SET expires_at='2020-01-01T00:00:00+00:00' WHERE lease_id=?", (assigned['lease']['leaseId'],))
        goal('a-cli.scheduler.expire', registry.expire_stale_leases() == 1 and registry.get_job(first['jobId'])['status'] == 'queued' and not registry.get_job(first['jobId'])['leaseId'])
        registry = c.ClusterRegistry(root / 'selection')
        registry.heartbeat_host({'hostId': 'nas.example.invalid', 'hostType': 'nas_control', 'capabilities': ['runtime.launch'], 'workspaceMappings': {'workspace': str(root)}})
        registry.heartbeat_host({'hostId': 'PROOF-WORKER', 'hostType': 'workstation', 'role': 'primary_worker', 'capabilities': ['runtime.launch', 'browser.verify'], 'workspaceMappings': {'workspace': str(root)}})
        candidate = registry.upsert_job(mission_id='select', workspace_id='workspace', runtime_id='hermes', planned_file_scope=['src/app.py'])
        chosen = registry.assign_job(candidate['jobId'], allow_remote=True, allow_nas_fallback=False)
        goal('a-cli.scheduler.choose', chosen['ok'] and chosen['host']['hostId'] == 'PROOF-WORKER')
        registry = c.ClusterRegistry(root / 'scan')
        host = {'hostId': 'PROOF-WORKER', 'hostType': 'workstation', 'capabilities': ['runtime.launch'], 'maxConcurrentJobs': 1}
        with registry._connect() as observer:
            observer.execute('SELECT COUNT(*) FROM jobs').fetchone()
            for index in range(55):
                registry.upsert_job(mission_id=f'incompatible-{index}', workspace_id=f'workspace-{index}', runtime_id='hermes', required_capabilities=['gpu.missing'])
        compatible = registry.upsert_job(mission_id='compatible', workspace_id='compatible', runtime_id='hermes', required_capabilities=['runtime.launch'])
        goal('a-cli.scheduler.claim', registry.claim_next_job(host)['job']['jobId'] == compatible['jobId'])
        registry = c.ClusterRegistry(root / 'capacity')
        host['maxConcurrentJobs'] = 2
        for index in range(2):
            registry.upsert_job(mission_id=f'isolated-{index}', workspace_id=f'workspace:mission:{index}', runtime_id='hermes', planned_file_scope=['.'])
        first_claim, second_claim = registry.claim_next_job(host), registry.claim_next_job(host)
        goal('a-cli.scheduler.claim', bool(first_claim['job']) and bool(second_claim['job']) and registry.claim_next_job(host)['job'] is None)
        goal('a-cli.scheduler.load', registry.get_host('PROOF-WORKER')['currentLoad'] == 2)
        registry.complete_job(job_id=first_claim['job']['jobId'], lease_id=first_claim['lease']['leaseId'], host_id='PROOF-WORKER', status='completed')
        goal('a-cli.scheduler.load', registry.get_host('PROOF-WORKER')['currentLoad'] == 1)
        registry = c.ClusterRegistry(root / 'unlimited')
        host['maxConcurrentJobs'] = 0
        with registry._connect() as observer:
            observer.execute('SELECT COUNT(*) FROM jobs').fetchone()
            jobs = [registry.upsert_job(mission_id=f'unlimited-{index}', workspace_id=f'workspace:mission:{index}', runtime_id='hermes', planned_file_scope=['.']) for index in range(12)]
            claims = [registry.claim_next_job(host) for _ in jobs]
        goal('a-cli.scheduler.claim', [claim['job']['jobId'] for claim in claims] == [job['jobId'] for job in jobs] and registry.claim_next_job(host)['job'] is None)
        persisted = registry.get_host('PROOF-WORKER')
        goal('a-cli.scheduler.load', persisted['currentLoad'] == 12 and persisted['maxConcurrentJobs'] == 0 and persisted['concurrencyMode'] == 'unlimited')
        work = root / 'local-execution'; work.mkdir()
        registry = c.ClusterRegistry(work)
        job = registry.upsert_job(mission_id='execute', workspace_id='local', runtime_id='hermes', planned_file_scope=['out.txt'], payload={'command': [sys.executable, '-I', '-c', "from pathlib import Path; Path('out.txt').write_text('ok')"], 'executionRoot': str(work)})
        result = w.run_local_worker_once(work, host_id='PROOF-WORKER')
        goal('a-cli.scheduler.worker', result['claimed'] and registry.get_job(job['jobId'])['status'] == 'completed' and (work / 'out.txt').read_text() == 'ok' and any(event['kind'] == 'job.completed' for event in registry.list_events(job_id=job['jobId'])))
        idle = w.run_local_worker_once(work, host_id='PROOF-WORKER', max_concurrent_jobs=2)
        goal('a-cli.scheduler.worker', not idle['claimed'] and registry.get_host('PROOF-WORKER')['maxConcurrentJobs'] == 2)
        with environment(FLUXIO_CLUSTER_ROOT=str(root / 'shared-worker')):
            result = w.execute_job({'missionId': 'one', 'workspaceId': 'one', 'payload': {'executionRoot': str(work), 'controlProjectRoot': str(root / 'authority'), 'command': [sys.executable, '-I', '-c', "import os,json; print(json.dumps({key:os.environ.get(key) for key in ['FLUXIO_CONTROL_PROJECT_ROOT','FLUXIO_CLUSTER_ROOT']}))"]}}, {}, root=work)
        observed = json.loads(result['stdout'])
        goal('a-cli.scheduler.environment', observed['FLUXIO_CONTROL_PROJECT_ROOT'] == str((root / 'authority').resolve()) and observed['FLUXIO_CLUSTER_ROOT'] == str(root / 'shared-worker') and result['status'] == 'completed')
        goal('a-cli.scheduler.execute', result['returnCode'] == 0)
        _thread_admission(goal)
        _worker_lifecycle(root, goal)


def _thread_admission(goal):
    from .worker import _start_unlimited_worker_attempt
    gate = threading.Event()
    lock = threading.Lock()
    started = 0
    def transport(observer):
        nonlocal started
        with lock:
            index = started; started += 1
        claimed = index < 12
        observer(claimed)
        if claimed:
            gate.wait(timeout=5)
        return {'ok': True, 'claimed': claimed}
    attempts = []
    try:
        for index in range(13):
            completion, admission, thread = _start_unlimited_worker_attempt(transport)
            attempts.append((completion, thread))
            require(admission.result(timeout=2) == (index < 12), 'a-cli.scheduler.threads', 'admission differs from started worker')
        goal('a-cli.scheduler.threads', started == 13 and all(not completion.done() for completion, _ in attempts[:12]))
    finally:
        gate.set()
        for completion, thread in attempts:
            completion.result(timeout=2); thread.join(timeout=2)


def _worker_lifecycle(root, goal):
    import io
    from contextlib import redirect_stdout
    from . import worker as w
    work = root / 'worker-lifecycle'; work.mkdir()
    with redirect_stdout(io.StringIO()):
        exit_code = w.main(['--root', str(work), '--host-id', 'PROOF-WORKER', '--once'])
    state = json.loads((work / '.agent_control' / 'worker_state.json').read_text())
    goal('a-cli.scheduler.lifecycle', exit_code == 0 and state['schema'] == w.WORKER_STATE_SCHEMA and state['status'] == 'stopped' and state['hostId'] == 'PROOF-WORKER' and not (work / '.agent_control' / 'worker.pid').exists())
    def interrupted_poll(*args, **kwargs):
        raise RuntimeError('controlled durable registry unavailable')
    with substitute(w, 'run_local_worker_once', interrupted_poll), redirect_stdout(io.StringIO()):
        exit_code = w.main(['--root', str(work), '--host-id', 'PROOF-WORKER', '--once'])
    state = json.loads((work / '.agent_control' / 'worker_state.json').read_text())
    goal('a-cli.scheduler.lifecycle', exit_code == 1 and state['status'] == 'stopped' and 'controlled durable registry unavailable' in state['lastError'] and not (work / '.agent_control' / 'worker.pid').exists())


def check_rehome(legacy_registry, legacy_before, shared_job, session):
    identity='a-cli.scheduler.rehome'
    require(legacy_registry.get_job(legacy_before['jobId']) == legacy_before,identity,'legacy job changed while rehoming into shared queue')
    require(session.cluster_job_id == shared_job['jobId'] and session.cluster_job_id != legacy_before['jobId'] and shared_job['payload']['legacyClusterJobId'] == legacy_before['jobId'] and shared_job['payload']['legacyClusterRoot'] == str(legacy_registry.root),identity,'shared job lost legacy lineage or session identity')


def check_queued(session, step, attempts_before):
    identity='a-cli.scheduler.queued'
    require(not session.acknowledged and (step is None or step.status == 'in_progress' and step.attempts == attempts_before),identity,'queued delegated work consumed an attempt or became acknowledged')


def check_unlimited_admission(max_jobs, executor, completion, admission, thread):
    identity='a-cli.scheduler.unlimited-loop'
    require(max_jobs == 0 and executor is None and completion is not admission and (thread.is_alive() or completion.done()),identity,'unlimited admission used a fixed pool or conflated execution with claim notification')


def migration_procedure(root, goal):
    from .cluster import ClusterRegistry
    from .runtime_supervisor import DelegatedRuntimeSupervisor
    from .models import DelegatedRuntimeSession, PlanRevision, PlannedStep
    from .fluxio_harness import FluxioHarness
    root=Path(root)/'rehome'; root.mkdir()
    mission=root/'mission'; mission.mkdir()
    with environment(FLUXIO_CONTROL_PROJECT_ROOT=None,FLUXIO_CLUSTER_ROOT=str(root/'shared')):
        legacy=ClusterRegistry(mission,use_configured_root=False)
        session=DelegatedRuntimeSession(delegated_id='legacy',runtime_id='hermes',launch_command='controlled runtime command',mission_id='legacy-mission',status='queued',session_path=str(mission/'.agent_control/runtime_sessions/legacy.json'),workspace_root=str(mission),execution_root=str(mission),source_step_id='work',target_phase='execute',target_role='executor',cluster_job_id='job_legacy')
        supervisor=DelegatedRuntimeSupervisor(mission); supervisor._write_session(session)
        legacy.upsert_job(job_id='job_legacy',mission_id='legacy-mission',workspace_id='workspace:mission:legacy',runtime_id='hermes',required_capabilities=['runtime.launch'],payload={'command':session.launch_command,'sessionPath':session.session_path})
        before=legacy.get_job('job_legacy')
        refreshed=supervisor.refresh_session(session)
        jobs=ClusterRegistry(mission).list_jobs()
        goal('a-cli.scheduler.rehome',len(jobs)==1 and refreshed.cluster_job_id!='job_legacy' and jobs[0]['jobId']==refreshed.cluster_job_id and jobs[0]['payload']['legacyClusterJobId']=='job_legacy' and legacy.get_job('job_legacy')==before)
        step=PlannedStep(step_id='work',title='Scoped queued work')
        revision=PlanRevision(revision_id='one',trigger='initial',summary='Controlled queue',steps=[step])
        notes=[]; risks=[]
        from dataclasses import asdict
        rows,status,trigger=FluxioHarness._reconcile_delegated_sessions([asdict(refreshed)],[revision],supervisor,notes,risks,'Finish local work',[])
        goal('a-cli.scheduler.queued',status=='running' and trigger=='' and step.status=='in_progress' and step.attempts==0 and not rows[0]['acknowledged'] and risks==[])


def unlimited_loop_procedure(root, goal):
    """Production admission loop, registry leases and twelve actual local children."""
    import concurrent.futures
    import contextlib
    import io
    import time
    from . import worker as w
    from . import cluster as c
    from .cluster import ClusterRegistry
    root=Path(root)/'unlimited-loop'; root.mkdir()
    registry=ClusterRegistry(root); release=root/'release'
    for index in range(12):
        registry.upsert_job(mission_id=f'burst-{index}',workspace_id=f'workspace:mission:burst-{index}',runtime_id='hermes',required_capabilities=['command.run'],payload={'executionRoot':str(root),'command':[sys.executable,'-I','-c',"from pathlib import Path; import time; p=Path('release'); end=time.time()+25\nwhile not p.exists() and time.time()<end: time.sleep(.02)\nprint('controlled child completed')"], 'timeoutSeconds':30})
    real_wait=concurrent.futures.wait; admitted=0; peak=0; attempts=[]; deadline=time.monotonic()+25
    original=w.run_local_worker_once
    def actual_poll(*args,**kwargs):
        def observed(claimed):
            nonlocal admitted,peak
            attempts.append(bool(claimed))
            if claimed:
                admitted+=1; peak=max(peak,registry.get_host('PROOF-WORKER')['currentLoad'])
            if kwargs.get('claim_observer'):
                kwargs['claim_observer'](claimed)
        return original(*args,**{**kwargs,'claim_observer':observed})
    def bounded_wait(fs,*,timeout=None,return_when=None):
        if len(attempts)>=13:
            release.write_text('release owned child processes')
            raise KeyboardInterrupt
        require(time.monotonic()<deadline,'a-cli.scheduler.unlimited-loop','unlimited production loop failed to admit bounded burst')
        return real_wait(fs,timeout=min(float(timeout or 1),.1),return_when=return_when)
    try:
        with environment(FLUXIO_CLUSTER_ROOT=None,FLUXIO_CONTROL_PROJECT_ROOT=None,FLUXIO_HOST_ID='PROOF-WORKER'), substitute(c,'_detect_runtime_names',lambda *args: []), substitute(w,'run_local_worker_once',actual_poll), substitute(concurrent.futures,'wait',bounded_wait), contextlib.redirect_stdout(io.StringIO()):
            code=w.main(['--root',str(root),'--host-id','PROOF-WORKER','--max-jobs','unlimited','--poll-seconds','.05'])
        goal('a-cli.scheduler.unlimited-loop',code==130 and len(attempts)==13 and admitted==peak==12)
    finally:
        release.write_text('release owned child processes')
        # Admission owns its deadline; draining begins only after release.
        # Reusing the elapsed admission budget raced durable completion writes.
        completion_deadline = time.monotonic() + 25
        while time.monotonic()<completion_deadline and any(job['status'] in {'leased','running'} for job in registry.list_jobs()):
            time.sleep(.05)
        require(all(job['status']=='completed' for job in registry.list_jobs()),'a-cli.scheduler.unlimited-loop','owned child jobs did not complete after release')
