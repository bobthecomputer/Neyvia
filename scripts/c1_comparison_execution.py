"""Owned attempts and paired scoring for the immutable computer-use panel."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
PYTHON = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def source_hashes():
    paths = [*sorted((ROOT / 'src/grant_agent').glob('cua_*.py')),
        *sorted((ROOT / 'scripts').glob('c1_comparison*.py')),
        ROOT / 'scripts/run_c1_comparison.py', ROOT / 'scripts/c1_openai_arm.py',
        ROOT / 'scripts/verify_c1c_apps.py']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load_native_seed(fixture, state):
    """Load the same paired seed bytes into the newly admitted native host."""
    import shutil
    from c1_comparison_checker import live_read
    paths = fixture['fixturePaths']
    source = Path(paths['artifact' if 'office' in state else 'input'])
    if 'office' in state:
        office, previous = state['office'], state['document']
        target = office.root / (fixture['token'] + source.suffix)
        shutil.copyfile(source, target)
        if fixture['app'] == 'Microsoft PowerPoint':
            previous.Close()
            document = office.application.Presentations.Open(str(target), False, False, False)
        elif fixture['app'] == 'Microsoft Excel':
            previous.Close(False)
            document = office.application.Workbooks.Open(str(target), 0, False)
            office.application.Calculate()
        else:
            previous.Close(False)
            document = office.application.Documents.Open(str(target), False, False, False)
        office.documents.remove(previous)
        office.documents.append(document)
        state['document'] = document
        # Preserve the loaded seed and save the completed version as a new
        # token-owned output. PowerPoint SaveAs on its existing open path can
        # retain the old package despite updated in-memory text.
        state['path'] = office.root / (fixture['token'] + '-final' + source.suffix)
        paths['artifact'] = str(state['path'])
    else:
        target = state.get('input') or (state['root'] / 'draft.txt' if fixture['id'] in {'cmd-note', 'powershell-note'} else state['path'])
        shutil.copyfile(source, target)
        paths['input'] = str(target)
    value, provenance = live_read(fixture, state)
    if value != fixture['token']:
        raise RuntimeError('Initial state differs from the paired fixture token')
    return {'value': value, 'provenance': provenance, 'preparedSeedSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'initialSeedSha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'nativeLoadedPairedSeed': True}


def native_attempt(fixture, row):
    from grant_agent.cua_native_procedures import NativeApplications
    from c1_comparison_checker import observe_fixture, check_fixture
    paths = fixture['fixturePaths']
    runtime = NativeApplications(ROOT / '.agent_control/c1cmp' / fixture['token'], register_exit=False)
    session = None
    try:
        opened = runtime.open({'app': fixture['app']})
        session = opened['sessionId']
        state = runtime.sessions[session]
        row['ownership'] = opened['ownership']
        row['initialFixtureReadback'] = load_native_seed(fixture, state)
        row['firstObservationMs'] = (time.perf_counter() - row.pop('_started')) * 1000
        # The host owns a new native document; use its true paths, never a copied receipt.
        native_root = state['root'] if 'root' in state else state['office'].root
        paths['artifact'] = str(state['path']) if state.get('path') else paths.get('artifact')
        if state.get('input'):
            paths['input'] = str(state['input'])
        elif fixture['id'] in {'cmd-note', 'powershell-note'}:
            paths['input'] = str(native_root / 'draft.txt')
        elif fixture['id'] == 'git-note':
            paths['input'] = str(state['path'])
        save(Path(fixture['_path']), fixture)
        for phase, phrase in enumerate(fixture['phrases'], 1):
            started = time.perf_counter()
            step = {'phase': phase}
            try:
                row['actions'] += 1
                step['outcome'] = runtime.edit({'sessionId': session, 'value': phrase})
                step['observation'] = observe_fixture(fixture, phase, runtime=state)
                if step['observation']['value'] != phrase:
                    raise RuntimeError('Independent revision readback failed')
            except Exception as exc:
                step['error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            finally:
                step['elapsedMs'] = (time.perf_counter() - started) * 1000
                row['steps'].append(step)
        persisted = runtime.persist({'sessionId': session})
        row['actions'] += 1
        paths['artifact'] = str(state['path'])
        save(Path(fixture['_path']), fixture)
        row['persist'] = persisted
        row['nativeReopenReadback'] = runtime.observe({'sessionId': session, 'expected': fixture['phrases'][-1], 'persisted': True})
        row['checker'] = check_fixture(fixture)
        row['ok'] = row['checker']['ok'] and row['nativeReopenReadback']['ok']
    finally:
        if session:
            row['close'] = runtime.close({'sessionId': session})
            row['guard'] = row['close']['guard']
            row['ok'] = row.get('ok', False) and row['close']['ok']
        elif runtime.failed_opens:
            row['guard'] = runtime.failed_opens[-1]['guard']


def ui_attempt(fixture, row):
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    from grant_agent.cua_native import NativeWorker
    from grant_agent.cua_desktop import AgentDesktop
    from run_c11_cohort import owned_window, choose_task, action_request, task_ready, stable_owned_editor
    from c1_comparison_checker import observe_fixture, check_fixture
    catalog = json.loads((ROOT / 'config/cua-everyday-tasks.json').read_text(encoding='utf-8'))
    task = next(t for t in catalog['apps'] if t['app'] == fixture['app'])
    task = {**task, 'values': fixture['phrases']}
    exe = Path(task['exe'])
    if not exe.is_file():
        raise RuntimeError('Frozen installed application executable absent: ' + str(exe))
    original_area = Path(fixture['fixturePaths']['root'])
    token = fixture['token']
    editor = fixture['id'].endswith('-find')
    folder = fixture['app'].replace(' ', '-') + '-' + token
    area = ROOT / '.agent_control/c1cmp' / folder
    area.mkdir(parents=True, exist_ok=False)
    fixture['preparedRoot'] = str(original_area)
    fixture['fixturePaths']['root'] = str(area)
    port = {'Visual Studio Code': 48704, 'Cursor': 48706, 'Antigravity': 48707}.get(fixture['app'], 48703)
    document = Path(fixture['fixturePaths']['input']) if fixture['app'] != 'Character Map' else None
    if document:
        original_document = document
        document = area / (token + original_document.suffix)
        document.write_bytes(original_document.read_bytes())
        fixture['fixturePaths']['input'] = str(document)
    launch = [str(exe)]
    if document:
        profile = area / ('editor-profile' if editor else 'browser-profile')
        profile.mkdir(exist_ok=True)
        if editor:
            settings = profile / 'User/settings.json'
            settings.parent.mkdir(parents=True, exist_ok=True)
            save(settings, {'workbench.startupEditor': 'none', 'security.workspace.trust.enabled': False,
                'telemetry.telemetryLevel': 'off', 'update.mode': 'none'})
        launch += ['--user-data-dir=' + str(profile), '--disable-gpu', '--force-renderer-accessibility',
            '--new-window', '--remote-debugging-port=' + str(port),
            '--remote-allow-origins=http://127.0.0.1:' + str(port)]
        if editor:
            launch += ['--extensions-dir=' + str(area / 'extensions'), '--disable-extensions',
                '--skip-welcome', '--skip-release-notes', str(document)]
        else:
            launch += ['--no-first-run', '--no-default-browser-check', '--disable-features=Translate', document.as_uri()]
    guard = ZeroDisturbanceGuard().start()
    worker = NativeWorker(guard=guard, desktop=AgentDesktop(profile_root=ROOT))
    try:
        process = worker.launch(launch, cwd=area, environment=task.get('route', 'agent-desktop'))
        row['launch'] = launch
        row['launcherPid'] = process.pid
        # Editor first use can take 28 seconds. The parent still enforces the
        # frozen 60-second total; this startup allowance does not add a budget.
        window = owned_window(worker, time.monotonic() + 35, token if document else None)
        if not window:
            row['ownedWindowsAtDeadline'] = worker.request('windows', timeout=4)
            row['launchExitCode'] = process.poll()
            raise RuntimeError('No uniquely owned isolated window within startup deadline')
        if editor:
            window = stable_owned_editor(worker, window, token)
        identity = window['windowId']
        row['ownership'] = worker.desktop.register_fixture(identity, area, token)
        row['window'] = window
        fixture['target'] = {'windowId': identity, 'pid': window['pid'], 'port': port,
            'document': str(document) if document else None, 'desktop': worker.desktop.name}
        save(Path(fixture['_path']), fixture)
        if editor:
            worker.request('action', {'windowId': identity, 'action': 'key', 'key': 'CTRL+F', 'allowForeground': False}, timeout=4)
            row['actions'] += 1
        observed, ready = task_ready(worker, task, window, 8)
        row['firstObservationMs'] = (time.perf_counter() - row.pop('_started')) * 1000
        row['readiness'] = ready
        if not ready['ready']:
            raise RuntimeError('No safe actionable frozen task field')
        for phase in range(1, 6):
            started = time.perf_counter()
            step = {'phase': phase}
            try:
                observed = worker.request('inspect', {'windowId': identity, 'maxDepth': 12, 'maxNodes': 500}, timeout=4)
                node = choose_task(observed.get('tree', []), task, phase - 1)
                if node is None:
                    raise RuntimeError('No uniquely identified fresh field')
                row['actions'] += 1
                outcome = worker.request('cycle', action_request(task, node, phase - 1, identity, observed['tree']), timeout=4)
                step['outcome'] = {k: outcome.get(k) for k in ('effect', 'mechanism', 'check')}
                # Prefer a stable observed semantic field identity over a renderer index.
                selector = {'role': node['role']}
                if node.get('automationId'):
                    selector['automationId'] = node['automationId']
                elif node.get('name'):
                    selector['name'] = node['name']
                else:
                    selector['id'] = node['id']
                step['observation'] = observe_fixture(fixture, phase, runtime={'worker': worker, 'windowId': identity, 'selector': selector})
                if step['observation']['value'] != fixture['phrases'][phase - 1]:
                    raise RuntimeError('Independent control readback failed')
            except Exception as exc:
                step['error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            finally:
                step['elapsedMs'] = (time.perf_counter() - started) * 1000
                row['steps'].append(step)
        row['checker'] = check_fixture(fixture)
        row['ok'] = row['checker']['ok']
    finally:
        worker.close()
        worker.desktop.close()
        row['guard'] = guard.close()
        row['ok'] = row.get('ok', False) and row['guard']['ok']


def child_attempt(path, receipt):
    fixture = json.loads(path.read_text(encoding='utf-8'))
    fixture['_path'] = str(path)
    started = time.perf_counter()
    row = {'id': fixture['id'], 'app': fixture['app'], 'repetition': fixture['repetition'],
        'arm': 'neyvia', 'fixture': str(path), 'ok': False, 'actions': 0, 'steps': [],
        'tokens': {'input': 0, 'output': 0, 'reasoning': 0}, 'cost': 0,
        'model': 'deterministic_native_procedure', 'currency': 'USD', '_started': started, 'sourceSha256': source_hashes()}
    try:
        (ui_attempt if fixture['id'] in {'charmap-compose', 'vscode-find', 'chrome-form', 'edge-form',
            'cursor-find', 'antigravity-find'} else native_attempt)(fixture, row)
    except Exception as exc:
        row['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        row.pop('_started', None)
        row['elapsedMs'] = (time.perf_counter() - started) * 1000
        row['sourceDrift'] = [p for p, sha in row['sourceSha256'].items() if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != sha]
        row['ok'] = row['ok'] and row['elapsedMs'] <= fixture['timeBudgetSeconds'] * 1000 and not row['sourceDrift']
        row['status'] = 'passed' if row['ok'] else 'failed'
        save(receipt, row)
    print(json.dumps({k: row.get(k) for k in ('id', 'repetition', 'ok', 'error', 'elapsedMs')}), flush=True)


def execute(args, preflight):
    from c1_comparison_checker import prepare_fixtures
    if args.child:
        child_attempt(args.child, args.receipt)
        return
    fixture_area = ROOT / 'scripts/evidence/C1CMP-fixtures'
    if args.series != 'baseline':
        fixture_area /= args.series
    index = fixture_area / 'index.json'
    prepared = json.loads(index.read_text(encoding='utf-8'))['attempts'] if index.exists() else prepare_fixtures(fixture_area)
    if not args.run:
        print(json.dumps({'preflight': preflight, 'prepared': prepared}))
        return
    data = json.loads(args.manifest.read_text(encoding='utf-8'))
    result = json.loads(args.receipt.read_text(encoding='utf-8')) if args.receipt.exists() else {
        'schema': 'neyvia.c1.frozen-comparison-executed.v1', 'at': datetime.now(timezone.utc).isoformat(),
        'freeze': preflight, 'manifestSha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'attempts': [], 'claudePreparation': prepared,
        'visibleDesktopException': 'User authorized competitor arms during this run only; Neyvia zero disturbance required',
        'missingPlanSection': 'plans/15-complete-everything.md contains no C1CMP section on disk'}
    arms = [args.arm] if args.arm else ['neyvia', 'openai_computer_use', 'claude_computer_use']
    result['activeSeries'] = args.series
    result['claudePreparationIndex'] = str(index)
    if 'openai_computer_use' in arms:
        from c1_openai_arm import probe
        probe_path = ROOT / 'scripts/evidence/C1-openai-probe/result.json'
        result['openaiProbe'] = json.loads(probe_path.read_text(encoding='utf-8')) if probe_path.exists() else probe(data['protocol']['timeBudgetSecondsPerAttempt'])
    for repetition in range(1, data['protocol']['repetitionsPerTask'] + 1):
        for task in data['tasks']:
            for arm in arms[repetition % len(arms):] + arms[:repetition % len(arms)]:
                if any(r['id'] == task['id'] and r['repetition'] == repetition and r['arm'] == arm
                        and r.get('series', 'baseline') == args.series for r in result['attempts']):
                    continue
                prepared_fixture = next(f for f in prepared if f['arm'] == arm and f['id'] == task['id'] and f['repetition'] == repetition)
                path = Path(prepared_fixture['manifest'])
                attempt_area = ROOT / 'scripts/evidence/C1CMP-attempts'
                if args.series != 'baseline':
                    attempt_area /= args.series
                target = attempt_area / arm / task['id'] / ('rep-' + str(repetition) + '.json')
                target.parent.mkdir(parents=True, exist_ok=True)
                row = {'id': task['id'], 'app': task['app'], 'repetition': repetition, 'arm': arm,
                    'fixture': str(path), 'receipt': target.relative_to(ROOT).as_posix(), 'ok': False}
                row['series'] = args.series
                if arm == 'neyvia':
                    with target.with_suffix('.log').open('wb') as log:
                        process = subprocess.Popen([PYTHON, str(ROOT / 'scripts/run_c1_comparison.py'),
                            '--child', str(path), '--receipt', str(target)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)
                        try:
                            code = process.wait(timeout=data['protocol']['timeBudgetSecondsPerAttempt'])
                        except subprocess.TimeoutExpired:
                            from c1_openai_arm import stop_owned
                            stop_owned(process)
                            code = process.returncode
                            row.update(status='budget_exceeded', error='Frozen 60 second budget reached', elapsedMs=60000)
                    if target.exists():
                        row.update(json.loads(target.read_text(encoding='utf-8')))
                    else:
                        row.update(status=row.get('status', 'crashed'), error=row.get('error', 'No completed certified child receipt'))
                    row['childExitCode'] = code
                    row['ok'] = row['ok'] and code == 0
                else:
                    from c1_comparison_checker import check_fixture
                    row.update(status='pending_lead' if arm == 'claude_computer_use' else 'unsupported_adapter',
                        actions=0, elapsedMs=None, tokens=None, cost=None,
                        checker=check_fixture(path),
                        reason='Claude arm is prepared for execution by lead' if arm == 'claude_computer_use'
                        else 'Official @oai/sky import succeeded; list_apps failed: sky requires node_repl; configure NODE_REPL_TRUSTED_SERVICES',
                        metricReason='No task run; unavailable metrics are null, never estimated')
                    save(target, row)
                result['attempts'].append(row)
                summarize(result)
                save(args.receipt, result)
                print(json.dumps({k: row.get(k) for k in ('id', 'repetition', 'arm', 'status', 'error')}), flush=True)
    summarize(result)
    result['manifestUnchanged'] = result['manifestSha256'] == hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    save(args.receipt, result)


def summarize(result):
    from verify_c1c_apps import percentile
    result['summary'] = {}
    result['perTask'] = {}
    for arm in ['neyvia', 'openai_computer_use', 'claude_computer_use']:
        rows = [r for r in result['attempts'] if r['arm'] == arm]
        times = [r['elapsedMs'] for r in rows if r.get('elapsedMs') is not None]
        atomic = [step['elapsedMs'] for r in rows for step in r.get('steps', [])]
        first = [r['firstObservationMs'] for r in rows if r.get('firstObservationMs') is not None]
        result['summary'][arm] = {'scheduled': max(75, len(rows)), 'recorded': len(rows), 'passed': sum(r['ok'] for r in rows),
            'completedAttempts': sum(r['status'] in {'passed', 'failed', 'budget_exceeded', 'crashed'} for r in rows),
            'taskP50Ms': percentile(times, .5), 'taskP95Ms': percentile(times, .95),
            'atomicP50Ms': percentile(atomic, .5), 'atomicP95Ms': percentile(atomic, .95),
            'firstObservationP50Ms': percentile(first, .5), 'firstObservationP95Ms': percentile(first, .95),
            'firstObservationMaxMs': max(first) if first else None,
            'actions': sum(r.get('actions', 0) for r in rows),
            'tokens': 0 if arm == 'neyvia' else None, 'cost': 0 if arm == 'neyvia' else None,
            'metricsReason': None if arm == 'neyvia' else 'Provider task arm has not executed; separate OpenAI probe usage is recorded',
            'zeroAttributedDisturbance': all(r.get('guard', {}).get('ok') for r in rows) if arm == 'neyvia' and rows else None}
        result['perTask'][arm] = {identity: {'recorded': len(selected), 'passed': sum(r['ok'] for r in selected),
            'attempts': [{k: r.get(k) for k in ('series', 'repetition', 'status', 'ok', 'elapsedMs', 'actions', 'tokens', 'cost', 'reason', 'receipt')}
                for r in selected]} for identity in sorted({r['id'] for r in rows})
            if (selected := [r for r in rows if r['id'] == identity])}
    result['seriesSummary'] = {series: {arm: {'recorded': len(selected), 'passed': sum(r['ok'] for r in selected),
        'zeroDisturbanceCertified': all(r.get('guard', {}).get('ok') for r in selected) if arm == 'neyvia' and selected else None}
        for arm in result['summary'] if (selected := [r for r in result['attempts'] if r['arm'] == arm and r.get('series', 'baseline') == series])}
        for series in sorted({r.get('series', 'baseline') for r in result['attempts']})}
    result['completeComparison'] = all(result['seriesSummary'].get(result.get('activeSeries', 'baseline'), {}).get(arm, {}).get('passed') == 75
        for arm in result['summary'])
    result['failedAttemptsRetained'] = True
