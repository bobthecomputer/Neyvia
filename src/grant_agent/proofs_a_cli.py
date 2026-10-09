"""CLI and durable coordination manual contracts; no external runtime authority.

The decorators run at production entry points. Startup procedures use new local
state and real parsers/databases, without opening the user's CLI configuration.
"""
from __future__ import annotations

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proof_ports import proof_port, proof_text

import hashlib
import inspect
import json
import os
import time
from functools import wraps
from pathlib import Path


def require(condition, identity, message):
    if not condition:
        raise ValueError(f"Contract {identity}: {message}")


def check_plugin_skills(manuals, skills, render):
    for name, (manual, description) in manuals.items():
        path = Path(skills) / name / 'SKILL.md'
        require(path.is_file() and path.read_text(encoding='utf-8') == render(name, manual, description),'a-cli.mods.skills','generated plugin skill differs from its current manual')


def checked(identity):
    def decorate(action):
        signature = inspect.signature(action)
        @wraps(action)
        def invoke(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = action(*args, **kwargs)
            check(identity, bound.arguments, result)
            return result
        return invoke
    return decorate


def _cursor_content(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        fragments = []
        for item in value:
            if isinstance(item, str):
                fragments.append(item)
            elif isinstance(item, dict):
                if str(item.get('type') or '').lower() in {'', 'text', 'output_text'} and isinstance(item.get('text'), str):
                    fragments.append(item['text'])
                elif isinstance(item.get('content'), str):
                    fragments.append(item['content'])
        return '\n'.join(text.strip() for text in fragments if text.strip())
    if isinstance(value, dict):
        return _cursor_content(value.get('content') or value.get('text') or value.get('result'))
    return ''


def check(identity, args, result):
    if identity.startswith('a-cli.preferences.'):
        from .proofs_a_cli_preferences import check as preferences_check
        return preferences_check(identity, args, result)
    if identity.startswith('a-cli.scheduler.'):
        from .proofs_a_cli_scheduler import check as scheduler_check
        return scheduler_check(identity, args, result)
    if identity.startswith(('a-cli.assets.', 'a-cli.continuity.', 'a-cli.setup.')):
        from .proofs_a_cli_lifecycle import check as lifecycle_check
        return lifecycle_check(identity, args, result)
    if identity == 'a-cli.cursor.text':
        payload = args['payload']
        message = payload.get('message')
        candidates = [message.get('content')] if isinstance(message, dict) else []
        candidates += [payload.get(key) for key in ('content', 'text', 'result', 'summary')]
        delta = payload.get('delta')
        if isinstance(delta, dict):
            candidates.append(delta.get('content') or delta.get('text'))
        expected = next((text for candidate in candidates if (text := _cursor_content(candidate))), '')
        require(result == expected, identity, 'text differs from ordered structured event content')
    elif identity == 'a-cli.catalog.selection':
        from . import cli_catalog as c
        for row in result['entries']:
            selected = args['with_sizes'] and row['runtimeId'] in c.CATALOG and (args['size_runtime_ids'] is None or row['runtimeId'] in args['size_runtime_ids'])
            require(('size' in row) == bool(selected),identity,'size lookup expanded beyond selected runtime')
        require(result['optional'] and result['continueWithoutAny'],identity,'optional runtime catalog blocked setup')
    elif identity == 'a-cli.catalog.classify':
        from . import cli_catalog as c
        status, entry = args['status'], args['entry']
        if entry and c._platform_name() not in entry.platforms:
            expected = c.STATE_UNSUPPORTED
            require('not supported' in result[1].lower(), identity, 'unsupported reason missing')
        elif not status.detected:
            expected = c.STATE_AVAILABLE if status.install_hint else c.STATE_UNAVAILABLE
        elif any(any(word in issue.lower() for word in ('auth', 'login', 'sign in', 'token', 'api key', 'credential')) for issue in status.issues):
            expected = c.STATE_CONNECTION_REQUIRED
        elif status.update_available:
            expected = c.STATE_UPDATE_RECOMMENDED
            require((status.latest_version or 'a newer version') in result[1], identity, 'update version missing')
        else:
            expected = c.STATE_READY
        require(result[0] == expected and isinstance(result[1], str), identity, 'classification overstates readiness or install route')
    elif identity == 'a-cli.catalog.fact':
        from . import cli_catalog as c
        value = args['value']
        unknown = value in (None, '', c.UNVERIFIED)
        require(result == {'value': None if unknown else value, 'confidence': c.UNVERIFIED if unknown else args['confidence_when_present']}, identity, 'unknown fact was invented')
    elif identity == 'a-cli.catalog.size':
        entry = args['entry']
        require(isinstance(result, dict) and 'bytes' in result, identity, 'size observation missing')
        if entry.package_kind != 'npm' or not entry.package_name:
            require(result['bytes'] is None and bool(result.get('detail')), identity, 'size invented without declared package')
    elif identity == 'a-cli.catalog.actions':
        from . import cli_catalog as c
        state = args['state']
        require(state in c.STATE_LABELS and bool(c.STATE_LABELS[state]), identity, 'state lacks label')
        if state in {c.STATE_READY, c.STATE_UPDATE_RECOMMENDED} and not args['managed_owned']:
            expected = []
        elif state == c.STATE_READY:
            expected = ['repair', 'uninstall']
        elif state == c.STATE_UPDATE_RECOMMENDED:
            expected = ['update', 'repair', 'uninstall']
        elif state == c.STATE_CONNECTION_REQUIRED:
            expected = ['connect', 'repair', 'uninstall'] if args['managed_owned'] else ['connect']
        elif state == c.STATE_AVAILABLE:
            expected = ['install', 'skip'] if args['managed_install'] else ['skip']
        else:
            expected = ['skip']
        require(result == expected, identity, 'actions exceed managed ownership or install authority')
    elif identity == 'a-cli.catalog.recommend':
        from . import cli_catalog as c
        by_id = {row['runtimeId']: row for row in args['catalog'].get('entries', [])}
        expected = []
        for goal in args['goals']:
            for runtime in c.GOAL_AFFINITY.get(goal, ()):
                if runtime in expected or runtime not in by_id or by_id[runtime]['state'] in {c.STATE_UNSUPPORTED, c.STATE_UNAVAILABLE}:
                    continue
                expected.append(runtime)
                if len(expected) >= args['limit']:
                    break
            if len(expected) >= args['limit']:
                break
        require([row['runtimeId'] for row in result] == expected and all(row.get('because') for row in result), identity, 'recommendation ordering/availability/reason differs')
    elif identity == 'a-cli.mods.launch':
        from . import claude_code_mods as m
        env = os.environ if args['environ'] is None else args['environ']
        if not env.get('NEYVIA_UI_STATE_ROOT') or not env.get('NEYVIA_UI_BACKEND_URL'):
            require(result == {}, identity, 'plugin enabled without selected service')
        elif result:
            parts = result['CLAUDE_CODE_PLUGIN_DIRS'].split(os.pathsep)
            own = os.path.normcase(str(m.PLUGIN_DIR))
            expected = [str(m.PLUGIN_DIR)] + [part for part in str(env.get('CLAUDE_CODE_PLUGIN_DIRS') or '').split(os.pathsep) if part.strip() and os.path.normcase(part.strip()) != own]
            require(parts == expected and bool(result.get('NEYVIA_PYTHON')), identity, 'plugin order/deduplication or Python missing')
    elif identity == 'a-cli.archive.inspect':
        from .communication_archive import MAX_ARCHIVE_MESSAGES, MAX_BODY_PREVIEW
        limit = max(1, min(int(args['limit'] or MAX_ARCHIVE_MESSAGES), MAX_ARCHIVE_MESSAGES))
        rows = result['messages']
        require(result['messageCount'] == len(rows) <= limit and result['attachmentCount'] == sum(len(row['attachments']) for row in rows), identity, 'preview count/bound differs')
        require(len(result['sourceDigest']) == 64 and all(len(row['bodyPreview']) <= MAX_BODY_PREVIEW for row in rows), identity, 'digest or body preview bound missing')
        if Path(args['source_path']).suffix.casefold() == '.msg':
            require(result['status'] == 'adapter-required' and not rows and bool(result['limitations']), identity, 'unsupported MSG content inferred')
        else:
            require(result['status'] == 'ready' and (not result['truncated'] or bool(result['limitations'])), identity, 'truncated result lacks explanation')
    elif identity == 'a-cli.archive.summary':
        message = args['message']
        require(result['subject'] == str(message.get('Subject') or '(no subject)') and result['from'] == str(message.get('From') or '') and result['to'] == str(message.get('To') or ''), identity, 'parsed headers differ')
        expected = [{'filename': str(part.get_filename() or 'attachment'), 'mediaType': str(part.get_content_type() or 'application/octet-stream'), 'bytes': len(part.get_payload(decode=True) or b'')} for part in message.walk() if part.get_content_disposition() == 'attachment' or part.get_filename()]
        require(result['attachments'] == expected, identity, 'attachment metadata differs from parsed content')
        from .communication_archive import MAX_BODY_PREVIEW
        preview = ''
        for part in message.walk():
            if part.get_content_disposition() == 'attachment' or part.get_content_type() != 'text/plain':
                continue
            try:
                content = part.get_content()
            except (AttributeError, LookupError, UnicodeError):
                content = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
            compact = ' '.join(str(content or '').split())
            if compact:
                preview = compact[:MAX_BODY_PREVIEW]
                break
        require(result['bodyPreview'] == preview, identity, 'body preview differs from first parsed plain-text part')
    elif identity == 'a-cli.archive.import':
        require(args['payload'].get('userInitiated') is True and result['state'] == 'imported-local', identity, 'import lacked explicit initiation')
        service = args['self']
        with service._connection() as connection:
            persisted = connection.execute('SELECT * FROM communication_imports WHERE import_id = ?', (result['importId'],)).fetchone()
        require(persisted is not None and persisted['source_digest'] == result['sourceDigest'] and json.loads(persisted['summary_json']) == result['summary'], identity, 'import receipt differs from persisted parser summary')
    elif identity == 'a-cli.crash.submit':
        store = args['self']
        with store._connection() as db:
            rows = db.execute('SELECT task_id, payload_json FROM durable_tasks WHERE mission_id = ? AND idempotency_key = ?', (args['mission_id'], args['idempotency_key'])).fetchall()
        require(len(rows) == 1 and rows[0]['task_id'] == result['taskId'] and json.loads(rows[0]['payload_json']) == result['payload'], identity, 'submission lost durable unique identity or original payload')
        if not result['deduplicated']:
            require(result['payload'] == (args['payload'] or {}) and result['status'] == 'queued', identity, 'new task lost payload or queue state')
    elif identity == 'a-cli.crash.claim':
        if result is not None:
            require(result['status'] == 'working' and result['workerId'] == args['worker_id'] and bool(result['leaseUntil']) and result['attempts'] >= 1, identity, 'claim lacked working owner lease')
    elif identity == 'a-cli.crash.transition':
        require(result['status'] == args['status'] and result['taskId'] == args['task_id'], identity, 'transition target differs')
        for key in ('result', 'checkpoint', 'error'):
            if args[key] is not None:
                require(result[key] == args[key], identity, 'transition discarded supplied ' + key)
        if args['status'] != 'working':
            require(result['workerId'] is None and result['leaseUntil'] is None, identity, 'non-working transition retained execution lease')
    elif identity == 'a-cli.crash.recover':
        require(len(result) == len(set(result)), identity, 'recovered task repeated')
        # A worker may immediately reclaim a recovered row; immutable event
        # history proves recovery without racing mutable status.
        for task_id in result:
            require(any(event['kind'] == 'recovered.interrupted' for event in args['self'].task_events(task_id)), identity, 'recovery event missing')
    elif identity == 'a-cli.crash.result':
        store = args['self']
        with store._connection() as db:
            rows = db.execute('SELECT item_id, payload_json FROM result_items WHERE result_set_id = ? AND dedupe_key = ?', (args['result_set_id'], result['dedupeKey'])).fetchall()
        require(len(rows) == 1 and rows[0]['item_id'] == result['itemId'] and json.loads(rows[0]['payload_json']) == result['payload'], identity, 'result item differs from unique persisted content')
    elif identity == 'a-cli.crash.summary':
        require(result['resultSetId'] == args['result_set_id'] and result['total'] == sum(result['byStatus'].values()) and len(result['samples']) <= max(0, min(int(args['sample_limit']), 20)), identity, 'result summary count or sample bound differs')
    elif identity == 'a-cli.crash.time':
        from datetime import datetime
        if args['deadline_at'] is None:
            require(result['shouldContinue'] and not result['skipOptional'] and result['remainingSeconds'] is None, identity, 'no deadline unexpectedly prevented work')
        else:
            remaining = max(0., (datetime.fromisoformat(args['deadline_at'].replace('Z', '+00:00')) - datetime.fromisoformat(result['now'].replace('Z', '+00:00'))).total_seconds())
            needed = max(0., float(args['estimated_next_seconds'])) + max(0., float(args['verification_reserve_seconds']))
            enough = remaining >= needed
            require(result['remainingSeconds'] == remaining and result['requiredSeconds'] == needed and result['skipOptional'] == (args['optional'] and not enough) and result['shouldContinue'] == (enough or not args['optional']) and result['deadlineRisk'] == (not enough), identity, 'deadline reserve or optional-work decision differs')
    elif identity == 'a-cli.crash.autonomy':
        # Recursion checks each parent; this check independently forbids a grant
        # outside the current lease. Rejected decisions are covered by the
        # production reasons plus the scratch scoped/revoked/expiry procedure.
        lease = result['lease']
        if result['allowed']:
            policy, context = lease['policy'], args['context'] or {}
            require(lease['active'] and ('*' in policy.get('allowedActions', []) or args['action'] in policy.get('allowedActions', [])), identity, 'grant outside active action lease')
            require(not context.get('destructive') or policy.get('destructiveAllowed', False), identity, 'destruction granted outside lease')
            require(not context.get('publicCommunication') or policy.get('publicCommunicationAllowed', False), identity, 'public communication granted outside lease')
            require(float(context.get('spend', 0) or 0) <= float(policy.get('maxSpend', 0) or 0), identity, 'grant exceeded spend')
            if context.get('path') and policy.get('allowedRoots'):
                path = Path(context['path']).resolve()
                require(any(path.is_relative_to(Path(root).resolve()) for root in policy['allowedRoots']), identity, 'grant escaped root')
        elif not lease['active']:
            require(result['reason'] == 'lease_inactive', identity, 'inactive lease denial misclassified')
    elif identity == 'a-cli.installer.integrity':
        import base64
        archive = Path(result).resolve()
        require(archive.is_relative_to(Path(args['staging']).resolve()) and archive.is_file(), identity, 'archive escaped staging or does not exist')
        digest = hashlib.sha512()
        with archive.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        require('sha512-' + base64.b64encode(digest.digest()).decode('ascii') == args['release']['integrity'], identity, 'archive differs from published integrity')


def check_mod_report(body, runs, session, previous):
    """Called under the existing report lock, before the mutation commits."""
    from . import claude_code_mods as m
    identity = 'a-cli.mods.report'
    row = runs[session]
    require(len(runs) <= m.MAX_RUNS and len(row['files']) <= m.MAX_FILES and len(row['files']) == len(set(row['files'])), identity, 'run/file bounds or uniqueness failed')
    if body['kind'] == 'checklist':
        expected = [{'text': ' '.join(str(item.get('text') or '').split())[:300], 'status': item['status']} for item in body['items'] if isinstance(item, dict) and item.get('status') in m._ITEM_STATES and ' '.join(str(item.get('text') or '').split())[:300]]
        require(row['checklist'] == expected, identity, 'checklist accepted unknown state or unbounded text')
    if body['kind'] == 'edit':
        value = ' '.join(str(body.get('path') or '').split())[:500]
        files = previous.get('files', [])
        expected = files if value in files else [*files, value][-m.MAX_FILES:]
        require(row['files'] == expected, identity, 'edited file history lost order or bound')


def installer_capture(root, runtime_id):
    from . import cli_installer as i
    entry = i._entry(runtime_id)
    launcher = i._launcher_path(root, entry.command_name) if entry.command_name else None
    manifest_path = i._manifest_path(root, runtime_id)
    return {'path': os.environ.get('PATH'), 'launcher': launcher,
            'launcherBytes': launcher.read_bytes() if launcher and launcher.is_file() else None,
            'manifestBytes': manifest_path.read_bytes() if manifest_path.is_file() else None}


def installer_check(root, runtime_id, action, kwargs, result, capture):
    from . import cli_installer as i
    identity = 'a-cli.installer.action'
    require(os.environ.get('PATH') == capture['path'] and result.get('systemPathChanged', False) is False, identity, 'installer changed process/system PATH')
    require(result['schema'] == i.INSTALLER_SCHEMA and json.loads(Path(result['receiptPath']).read_text(encoding='utf-8')) == result, identity, 'installer receipt differs from durable action')
    launcher = capture['launcher']
    status = result['status']
    if not kwargs.get('approved') or not str(kwargs.get('approval_id') or '').strip():
        require(status == 'approval_required', identity, 'unapproved action was executed')
    if status in {'failed', 'launcher_conflict', 'approval_required', 'unsupported', 'prerequisite_missing'}:
        if capture['launcherBytes'] is not None:
            require(launcher.is_file() and launcher.read_bytes() == capture['launcherBytes'], identity, 'failed action replaced existing launcher')
        if capture['manifestBytes'] is not None:
            require(i._manifest_path(root, runtime_id).read_bytes() == capture['manifestBytes'], identity, 'failed action replaced previous manifest')
    if status == 'completed':
        manifest = i.load_manifest(runtime_id, runtime_root=root)
        require(manifest and manifest['state'] == 'active' and manifest['version'] == result['version'] and manifest['integrity'] == result['integrity'] and launcher.is_file(), identity, 'successful install lacks active manifest/launcher')
        require(launcher.read_text(encoding='utf-8') == i._launcher_text(i._launcher_target(Path(manifest['installDir']), manifest['commandName'])).replace('\r\n', '\n'), identity, 'launcher does not target verified installation')
        if result['previousInstallRetained']:
            require(Path(manifest['previousInstallDir']).is_dir(), identity, 'previous installation was not retained')
    if status in {'uninstalled', 'already_absent'}:
        require(i.load_manifest(runtime_id, runtime_root=root) is None and all(not Path(path).exists() and Path(path).resolve().is_relative_to(root.resolve()) for path in result['removed']), identity, 'uninstall removed outside owned root or retained reported path')


def self_check(root):
    from email.message import EmailMessage
    import mailbox
    from . import cli_catalog as c, claude_code_mods as m
    from .communication_archive import inspect_communication_archive
    from .cursor_bridge import _message_text
    from .ecosystem_fabric import NeyviaEcosystemFabric
    from .models import RuntimeInstallStatus
    from .ui_command_bus import bus_for
    started = time.perf_counter()
    root = Path(root).resolve() / ('a-cli-' + str(time.time_ns()))
    root.mkdir(parents=True)
    checks, rejections = [], []
    def goal(identity, ok, detail='startup procedure goal failed'):
        require(ok, identity, detail)
        checks.append({'contract': identity, 'ok': True})
    def rejects(identity, action):
        try:
            action()
        except (ValueError, RuntimeError):
            rejections.append({'contract': identity, 'rejected': True})
        else:
            require(False, identity, 'invalid action accepted')
    selected_contracts = set(json.loads(os.environ['NEYVIA_GATE_CONTRACTS'])) if os.environ.get('NEYVIA_GATE_CONTRACTS') else None
    def finish():
        frontier = json.loads((Path(__file__).resolve().parents[2] / 'config/proofs/a-cli.json').read_text(encoding='utf-8')).get('frontier', [])
        return {'ok': True, 'contracts': sorted({row['contract'] for row in checks}), 'checks': checks,
                'rejections': rejections, 'elapsedMs': round((time.perf_counter() - started) * 1000, 3), 'frontier': frontier}
    def procedures():
        if not selected_contracts or any(name.startswith('a-cli.crash.') for name in selected_contracts):
            _crash_procedure(root, goal, rejects)
        if not selected_contracts or any(name.startswith('a-cli.installer.') for name in selected_contracts):
            _installer_procedure(root, goal)
        if not selected_contracts or any(name.startswith('a-cli.scheduler.') for name in selected_contracts):
            from .proofs_a_cli_scheduler import procedure, migration_procedure, unlimited_loop_procedure
            if selected_contracts != {'a-cli.scheduler.unlimited-loop'}:
                procedure(root, goal, rejects)
                migration_procedure(root, goal)
            if not selected_contracts or 'a-cli.scheduler.unlimited-loop' in selected_contracts:
                unlimited_loop_procedure(root, goal)
        if not selected_contracts or any(name.startswith(('a-cli.assets.', 'a-cli.setup.', 'a-cli.continuity.')) for name in selected_contracts):
            from .proofs_a_cli_lifecycle import procedure
            procedure(root, goal, rejects)
        if not selected_contracts or any(name.startswith('a-cli.preferences.') for name in selected_contracts):
            from .proofs_a_cli_preferences import procedure
            procedure(root, goal, rejects)
    families = ('a-cli.crash.', 'a-cli.installer.', 'a-cli.scheduler.', 'a-cli.assets.',
                'a-cli.setup.', 'a-cli.continuity.', 'a-cli.preferences.')
    if selected_contracts and all(name.startswith(families) for name in selected_contracts):
        procedures()
        return finish()
    def status(**kwargs):
        return RuntimeInstallStatus(runtime_id='proof-cli', label='Proof CLI', **kwargs)
    for value, entry, state in [
        (status(detected=True, doctor_summary='healthy'), None, c.STATE_READY),
        (status(detected=True, version='1.0', latest_version='2.0', update_available=True), None, c.STATE_UPDATE_RECOMMENDED),
        (status(detected=True, issues=['login required']), None, c.STATE_CONNECTION_REQUIRED),
        (status(detected=False, install_hint='declared installer'), None, c.STATE_AVAILABLE),
        (status(detected=False), None, c.STATE_UNAVAILABLE),
        (status(detected=False), c.CatalogEntry('proof-cli', '', platforms=('Plan9',)), c.STATE_UNSUPPORTED),
    ]:
        goal('a-cli.catalog.classify', c.classify(value, entry)[0] == state)
    for state in c.STATE_LABELS:
        goal('a-cli.catalog.actions', bool(c._actions_for(state)))
    goal('a-cli.catalog.fact', c.CATALOG['openclaw'].publisher is None and c._fact(None) == {'value': None, 'confidence': c.UNVERIFIED})
    goal('a-cli.catalog.size', c.resolve_package_size(c.CATALOG['cursor'])['bytes'] is None)
    from .proofs_a_cli_scheduler import substitute
    resolved = []
    def package_size(entry):
        resolved.append(entry.runtime_id)
        return {'version':'1.0.0','bytes':123}
    statuses = [RuntimeInstallStatus(runtime_id=key,label=key,detected=False,install_hint='Controlled installer') for key in ['claude-code','opencode']]
    with substitute(c,'detect_runtime_statuses',lambda *a,**kw:statuses), substitute(c,'resolve_package_size',package_size):
        selected=c.build_catalog(root,with_sizes=True,size_runtime_ids={'opencode'})
    rows={row['runtimeId']:row for row in selected['entries']}
    goal('a-cli.catalog.selection',resolved==['opencode'] and 'size' not in rows['claude-code'] and rows['opencode']['size']['bytes']==123)
    catalog = {'entries': [{'runtimeId': runtime, 'label': runtime, 'state': state, 'usefulFor': 'code'} for runtime, state in [('claude-code', c.STATE_AVAILABLE), ('opencode', c.STATE_AVAILABLE), ('cursor', c.STATE_AVAILABLE)]]}
    goal('a-cli.catalog.recommend', len(c.recommend(catalog, ['software'], limit=2)) == 2)
    catalog['entries'][0]['state'] = c.STATE_UNAVAILABLE
    goal('a-cli.catalog.recommend', all(row['runtimeId'] != 'claude-code' for row in c.recommend(catalog, ['software'])))
    event = {'message': {'content': [{'type': 'text', 'text': 'Cursor'}, {'type': 'text', 'text': 'reply'}]}}
    goal('a-cli.cursor.text', _message_text(event) == 'Cursor\nreply' and _message_text({'result': 'Done'}) == 'Done')
    rejects('a-cli.cursor.text', lambda: check('a-cli.cursor.text', {'payload': event}, 'invented text'))
    env = {'NEYVIA_UI_STATE_ROOT': str(root), 'NEYVIA_UI_BACKEND_URL': proof_text('http://127.0.0.1:48468'), 'CLAUDE_CODE_PLUGIN_DIRS': os.pathsep.join(['other-plugin', str(m.PLUGIN_DIR)])}
    bus = bus_for(root)
    goal('a-cli.mods.launch', m.launch_env(env)['CLAUDE_CODE_PLUGIN_DIRS'].split(os.pathsep) == [str(m.PLUGIN_DIR), 'other-plugin'])
    bus.put(m.SETTING, {'enabled': False})
    goal('a-cli.mods.launch', m.launch_env(env) == {} and m.launch_env({'NEYVIA_UI_STATE_ROOT': str(root)}) == {})
    import contextlib, io, runpy
    builder=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/build_claude_plugin_skills.py'))
    with contextlib.redirect_stdout(io.StringIO()):
        skills_current=builder['main'](['--check'])
    goal('a-cli.mods.skills',skills_current == 0)
    m.record_report(bus, {'session': 'proof', 'kind': 'checklist', 'items': [{'text': 'x' * 500, 'status': 'completed'}, {'text': 'skip', 'status': 'unknown'}]})
    with bus.connection_scope():
        for index in range(m.MAX_FILES + 5):
            m.record_report(bus, {'session': 'proof', 'kind': 'edit', 'path': f'file-{index}.py'})
    row = bus.get(m.RUNS)['proof']
    goal('a-cli.mods.report', row['checklist'] == [{'text': 'x' * 300, 'status': 'completed'}] and len(row['files']) == m.MAX_FILES and row['files'][-1] == f'file-{m.MAX_FILES + 4}.py')
    for body in [{'session': 'bad session', 'kind': 'turn', 'state': 'idle'}, {'session': 'proof', 'kind': 'turn', 'state': 'invalid'}, {'session': 'proof', 'kind': 'invalid'}]:
        rejects('a-cli.mods.report', lambda body=body: m.record_report(bus, body))
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = 'sender@example.test', 'recipient@example.test', 'Scratch export'
    message.set_content('Hello from the archive')
    message.add_attachment(b'receipt', maintype='application', subtype='pdf', filename='receipt.pdf')
    source = root / 'message.eml'
    source.write_bytes(message.as_bytes())
    inspection = inspect_communication_archive(source)
    goal('a-cli.archive.summary', inspection['messages'][0]['subject'] == 'Scratch export' and inspection['messages'][0]['bodyPreview'] == 'Hello from the archive' and inspection['messages'][0]['attachments'][0]['filename'] == 'receipt.pdf')
    archive = mailbox.Maildir(root / 'maildir', create=True)
    archive.add(message); archive.add(message); archive.flush(); archive.close()
    preview = inspect_communication_archive(root / 'maildir', limit=1)
    goal('a-cli.archive.inspect', preview['format'] == 'maildir' and preview['messageCount'] == 1 and preview['truncated'] is True and len(preview['sourceDigest']) == 64)
    service = NeyviaEcosystemFabric(root, database_path=root / 'ecosystem.sqlite3')
    account = service.register_communication_account({'label': 'Proof local mail', 'route': 'file-import', 'state': 'connected', 'permissions': ['read']})
    receipt = service.import_communication_archive({'accountId': account['accountId'], 'sourcePath': str(source), 'userInitiated': True})
    goal('a-cli.archive.import', service.communication_snapshot()['imports'][0]['importId'] == receipt['importId'])
    rejects('a-cli.archive.import', lambda: service.import_communication_archive({'accountId': account['accountId'], 'sourcePath': str(source)}))
    unsupported = root / 'archive.msg'
    unsupported.write_bytes(b'controlled unsupported input')
    goal('a-cli.archive.inspect', service.inspect_communication_archive({'sourcePath': str(unsupported), 'userInitiated': True})['status'] == 'adapter-required')
    procedures()
    return finish()


def _crash_procedure(root, goal, rejects):
    from datetime import datetime, timedelta, timezone
    from .crashproof import CrashProofStore
    root = root / 'durability'
    store = CrashProofStore(root)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    def later(seconds):
        return (datetime.fromisoformat(now.replace('Z', '+00:00')) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')
    first = store.submit_task(mission_id='stable', kind='research', idempotency_key='stable-query', payload={'query': 'durability'})
    again = store.submit_task(mission_id='stable', kind='research', idempotency_key='stable-query', payload={'query': 'changed'})
    restarted = CrashProofStore(root)
    goal('a-cli.crash.submit', again['taskId'] == first['taskId'] and again['deduplicated'] and restarted.get_task(first['taskId'])['payload'] == {'query': 'durability'} and len(restarted.list_tasks(mission_id='stable')) == 1)
    claimed = restarted.claim_next(worker_id='proof-worker', lease_seconds=30, now=now)
    goal('a-cli.crash.claim', claimed['status'] == 'working')
    recovered = CrashProofStore(root).recover_interrupted(now=later(31))
    goal('a-cli.crash.recover', recovered == [first['taskId']] and store.get_task(first['taskId'])['status'] == 'queued' and [event['kind'] for event in store.task_events(first['taskId'])] == ['submitted', 'claimed', 'recovered.interrupted'])
    store.claim_next(worker_id='proof-worker')
    waiting = store.transition_task(first['taskId'], 'waiting', checkpoint={'step': 4}, next_wakeup_at=later(3600))
    complete = store.transition_task(first['taskId'], 'completed', result={'title': 'ready'})
    goal('a-cli.crash.transition', waiting['checkpoint']['step'] == 4 and complete['result'] == {'title': 'ready'})
    rejects('a-cli.crash.transition', lambda: store.transition_task(first['taskId'], 'working'))
    results = store.create_result_set(mission_id='results', kind='sources')['resultSetId']
    item = store.add_result_item(results, payload={'title': 'evidence'}, source='scratch:evidence')
    duplicate = store.add_result_item(results, payload={'title': 'evidence'}, source='scratch:evidence')
    # Keep WAL open during bulk fixture population. Every production write
    # still commits independently with FULL durability; close before observing.
    with store._connection() as observer:
        observer.execute('SELECT COUNT(*) FROM durable_tasks').fetchone()
        for index in range(99):
            store.add_result_item(results, payload={'index': index}, source=f'scratch:{index}', status='failed' if index == 3 else 'completed')
    goal('a-cli.crash.result', duplicate['itemId'] == item['itemId'] and duplicate['deduplicated'])
    summary = store.summarize_result_set(results, sample_limit=3)
    goal('a-cli.crash.summary', summary['total'] == 100 and summary['byStatus'] == {'completed': 99, 'failed': 1} and len(summary['samples']) == 3)
    optional = store.time_snapshot(now=now, deadline_at=later(90), estimated_next_seconds=60, verification_reserve_seconds=45, optional=True)
    required = store.time_snapshot(now=now, deadline_at=later(90), estimated_next_seconds=60, verification_reserve_seconds=45, optional=False)
    goal('a-cli.crash.time', optional['skipOptional'] and not optional['shouldContinue'] and required['shouldContinue'] and required['deadlineRisk'])
    scope = root / 'workspace'
    scope.mkdir()
    parent = store.create_autonomy_lease(mission_id='lease', duration_seconds=600, now=now, policy={'allowedActions': ['*'], 'allowedRoots': [str(scope)], 'allowedDomains': ['docs.example.test'], 'maxSpend': 0, 'destructiveAllowed': False, 'publicCommunicationAllowed': False})
    child = store.create_autonomy_lease(mission_id='lease', parent_lease_id=parent['leaseId'], duration_seconds=300, now=now, policy={'allowedActions': ['file.write'], 'allowedRoots': [str(scope)], 'maxSpend': 0})
    grant = store.autonomy_allows(child['leaseId'], action='file.write', context={'path': scope / 'result.json'}, now=later(10))
    outside = store.autonomy_allows(child['leaseId'], action='file.write', context={'path': root / 'outside.json'}, now=later(10))
    destructive = store.autonomy_allows(child['leaseId'], action='file.write', context={'path': scope / 'result.json', 'destructive': True}, now=later(10))
    expired = store.autonomy_allows(child['leaseId'], action='file.write', context={'path': scope / 'result.json'}, now=later(301))
    goal('a-cli.crash.autonomy', grant['allowed'] and outside['reason'] == 'path_out_of_scope' and destructive['reason'] in {'destructive_not_granted', 'parent_denied'} and expired['reason'] == 'lease_inactive' and not store.revoke_autonomy_lease(parent['leaseId'], now=later(20))['active'])
    goal('a-cli.crash.autonomy', not store.autonomy_allows(child['leaseId'], action='file.write', context={'path': scope / 'result.json'}, now=later(21))['allowed'])
    with store._connection() as observer:
        observer.execute('SELECT COUNT(*) FROM durable_tasks').fetchone()
        for index in range(28):
            store.submit_task(mission_id='batch', kind='model.train', idempotency_key=f'model:{index}', payload={'modelIndex': index, 'wakePolicy': 'terminal_or_input_only'})
    batch = CrashProofStore(root).list_tasks(mission_id='batch')
    goal('a-cli.crash.submit', len(batch) == len({task['taskId'] for task in batch}) == 28 and all(task['status'] == 'queued' and task['payload']['wakePolicy'] == 'terminal_or_input_only' for task in batch))


def _installer_procedure(root, goal):
    """Exercise installer state machine via an explicitly controlled npm transport.

    The transport runs a child process that creates tiny local archive bytes and
    a launcher. It proves coordinator integrity/promotion/rollback, not npm or
    the Anthropic provider, and never invokes a system installation.
    """
    import base64
    import subprocess
    import sys
    from . import cli_installer as i
    archive_bytes = b'isolated installer transport archive'
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(archive_bytes).digest()).decode('ascii')
    fixture = root / 'installer_transport.py'
    fixture.write_text("""import json, os, sys
from pathlib import Path
args=json.loads(sys.argv[1]); mode=sys.argv[2]
if mode=='fail':
    print('controlled pack failure', file=sys.stderr); raise SystemExit(1)
if 'pack' in args:
    destination=Path(args[args.index('--pack-destination')+1])
    archive=destination/'local-archive.tgz'
    archive.write_bytes(b'tampered' if mode=='tamper' else b'isolated installer transport archive')
    print(json.dumps([{'filename': archive.name}]))
elif 'install' in args:
    prefix=Path(args[args.index('--prefix')+1])
    target=prefix/'node_modules'/'.bin'/('claude.cmd' if os.name=='nt' else 'claude')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('@echo off\\necho 1.0.0\\n' if os.name=='nt' else '#!/bin/sh\\necho 1.0.0\\n')
    if os.name!='nt': target.chmod(0o755)
    print('controlled local install')
else: print('1.0.0')
""", encoding='utf-8')
    def resolver(package, *, version='latest'):
        return {'package': package, 'version': '1.0.0', 'integrity': integrity, 'tarball': 'scratch:local-archive', 'downloadBytes': len(archive_bytes), 'unpackedBytes': 32, 'registry': 'controlled-local-transport'}
    mode = 'normal'
    launched = []
    def runner(command, **kwargs):
        # The installer owns hiding its child windows; the transport must receive that, not add its own.
        launched.append(kwargs.get('creationflags', 0))
        if os.name == 'nt' and not kwargs.get('creationflags', 0) & subprocess.CREATE_NO_WINDOW:
            raise AssertionError('The controlled installer transport did not receive hidden process flags')
        if isinstance(command, str):
            # Version probes use cmd shell quoting, not an npm argv list.
            # Execute the staged launcher itself so broken launchers still fail.
            return subprocess.run(command, **kwargs)
        return subprocess.run([sys.executable, '-I', str(fixture), json.dumps(command), mode], creationflags=kwargs.pop('creationflags', 0), **kwargs)
    managed = root / 'managed'
    def act(operation, **kwargs):
        return i.perform_cli_action(root, 'claude-code', operation, runtime_root=managed, npm_path='controlled-transport', resolver=resolver, runner=runner, **kwargs)
    blocked = act('install')
    first = act('install', approved=True, approval_id='proof-install')
    goal('a-cli.installer.action', blocked['status'] == 'approval_required' and first['ok'] and Path(first['launcherPath']).is_file() and i.installer_status('claude-code', runtime_root=managed)['ready'] and bool(launched) and (os.name != 'nt' or all(flags & subprocess.CREATE_NO_WINDOW for flags in launched)), f"install: {first.get('status')}: {first.get('detail')}")
    goal('a-cli.installer.integrity', first['integrity'] == integrity)
    launcher = Path(first['launcherPath']); original = launcher.read_bytes()
    mode = 'fail'
    failed = act('repair', approved=True, approval_id='proof-fail')
    goal('a-cli.installer.action', failed['status'] == 'failed' and failed['previousInstallPreserved'] and launcher.read_bytes() == original and i.installer_status('claude-code', runtime_root=managed)['ready'])
    mode = 'tamper'
    tampered = act('update', approved=True, approval_id='proof-integrity')
    goal('a-cli.installer.integrity', tampered['status'] == 'failed' and 'integrity' in tampered['detail'].lower() and launcher.read_bytes() == original)
    mode = 'normal'
    real_write = i.atomic_write_text
    interrupted = False
    def fault_write(path, text, **kwargs):
        nonlocal interrupted
        if Path(path) == launcher and not interrupted:
            interrupted = True
            raise OSError('controlled interruption before atomic launcher promotion')
        return real_write(path, text, **kwargs)
    try:
        i.atomic_write_text = fault_write
        rollback = act('update', approved=True, approval_id='proof-rollback')
    finally:
        i.atomic_write_text = real_write
    goal('a-cli.installer.action', interrupted and rollback['status'] == 'failed' and launcher.read_bytes() == original and i.installer_status('claude-code', runtime_root=managed)['ready'])
    repaired = act('repair', approved=True, approval_id='proof-repair')
    unrelated = managed / 'unrelated.txt'; unrelated.write_text('keep', encoding='utf-8')
    removed = act('uninstall', approved=True, approval_id='proof-uninstall')
    goal('a-cli.installer.action', repaired['previousInstallRetained'] and removed['status'] == 'uninstalled' and not i.installer_status('claude-code', runtime_root=managed)['managed'] and unrelated.read_text(encoding='utf-8') == 'keep')
    collision_root = root / 'collision'
    collision_launcher = i._launcher_path(collision_root, 'claude')
    collision_launcher.parent.mkdir(parents=True)
    collision_launcher.write_text('unrelated owner', encoding='utf-8')
    collision = i.perform_cli_action(root, 'claude-code', 'install', approved=True, approval_id='proof-collision', runtime_root=collision_root, npm_path='controlled-transport', resolver=lambda *a, **k: require(False, 'a-cli.installer.action', 'collision reached resolver'), runner=runner)
    goal('a-cli.installer.action', collision['status'] == 'launcher_conflict' and collision['collision']['kind'] == 'unmanaged_launcher_collision' and collision_launcher.read_text(encoding='utf-8') == 'unrelated owner')
    shared_root = root / 'managed-collision'
    shared_launcher = i._launcher_path(shared_root, 'claude').resolve()
    install_dir = shared_root / 'packages' / 'other-runtime' / '1'
    install_dir.mkdir(parents=True)
    manifest_path = shared_root / 'manifests' / 'other-runtime.json'; manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps({'schema': i.MANIFEST_SCHEMA, 'state': 'active', 'runtimeId': 'other-runtime', 'installDir': str(install_dir), 'launcherPath': str(shared_launcher)}), encoding='utf-8')
    shared = i.perform_cli_action(root, 'claude-code', 'install', approved=True, approval_id='proof-other-owner', runtime_root=shared_root, npm_path='controlled-transport', resolver=resolver, runner=runner)
    goal('a-cli.installer.action', shared['status'] == 'launcher_conflict' and shared['collision'] == {'kind': 'managed_launcher_collision', 'ownerRuntimeId': 'other-runtime', 'launcherPath': str(shared_launcher)} and not shared_launcher.exists())
