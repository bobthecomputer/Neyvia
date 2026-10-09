"""Exact durable supervision effects; admission never proves provider execution."""
from __future__ import annotations

from copy import deepcopy
import html
import json
import os
from pathlib import Path
import re

from . import durable_effects
from .effects import _call, _measure_file

SUPPORTED = durable_effects.SUPPORTED | {
    'neyvia.mission.from_plan', 'neyvia.mission.control',
    'neyvia.nightshift.start', 'neyvia.nightshift.stop',
    'neyvia.autopilot.stop', 'neyvia.mobile.create',
}
READS = {'neyvia.nightshift.tasks', 'neyvia.nightshift.task', 'neyvia.nightshift.summary',
         'neyvia.evolver.genome', 'neyvia.evolver.job', 'neyvia.evolver.lineage'}


def readonly(name, args):
    if name in READS:
        return True
    return durable_effects.readonly(name, args)


def _service(protocol):
    from ..neyvia_workspace_tools import workspace_for
    return workspace_for(protocol.gateway.root)


def _tasks(protocol):
    return {row['id']: row for row in _call(protocol, 'neyvia.nightshift.tasks', {})['tasks']}


def _selected(tasks, args):
    selected = set(tasks)
    if args.get('taskId'):
        if args['taskId'] not in tasks:
            raise ValueError('Unknown mission task')
        selected = {args['taskId']}
        while True:
            expanded = selected | {key for key, row in tasks.items() if set(row['needs']) & selected}
            if expanded == selected:
                break
            selected = expanded
    return selected


def _mobile_target(protocol, args):
    parent = _service(protocol).safe_path(args['path'])
    slug = re.sub(r'[^a-z0-9]+', '-', args['name'].strip().casefold()).strip('-') or 'app'
    return parent if parent.is_dir() and not any(parent.iterdir()) else parent / slug


def snapshot_for(protocol, name, args):
    if name in durable_effects.SUPPORTED:
        return durable_effects.snapshot_for(protocol, name, args)
    if name == 'neyvia.mission.from_plan':
        from ..neyvia_mission_plan import compile_plan
        path = _service(protocol).safe_path(args['planPath'])
        if path.suffix.lower() != '.md' or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Effect requires a bounded Markdown plan')
        compiled = compile_plan(path.read_text(encoding='utf-8-sig'), folder=args['folder'],
                                folders=args.get('folders'), builder=args.get('builder'), verifier=args.get('verifier'))
        from ..neyvia_runtime import mission_route
        routed = [mission_route(protocol.gateway.root, row) for row in compiled['tasks']]
        return {'source': _measure_file(path), 'compiled': compiled,
                'routed': routed,
                'prior': durable_effects._mission(protocol, args['id']) if args.get('id') else None}
    if name == 'neyvia.mission.control':
        mission = durable_effects._mission(protocol, args['id'])
        if not mission:
            raise ValueError('Unknown mission')
        tasks = {row['id']: row for row in mission['tasks']}
        selected = _selected(tasks, args)
        # Active provider control needs its own terminal provider observation.
        if any(tasks[key]['status'] == 'running' for key in selected):
            raise ValueError('Active provider supervision requires a terminal provider witness')
        return {'mission': mission, 'tasks': tasks, 'selected': sorted(selected)}
    if name in {'neyvia.nightshift.start', 'neyvia.nightshift.stop'}:
        tasks = _tasks(protocol)
        selected = args['ids'] if name.endswith('.start') else [args['id']]
        if not selected or len(set(selected)) != len(selected) or any(key not in tasks for key in selected):
            raise ValueError('Select unique saved task IDs')
        if any(tasks[key]['status'] == 'running' for key in selected):
            raise ValueError('Active provider control requires a terminal provider witness')
        return {'tasks': {key: tasks[key] for key in selected}}
    if name == 'neyvia.autopilot.stop':
        from ..neyvia_autopilot import load
        return load(_service(protocol), args['runId'])
    if name == 'neyvia.mobile.create':
        target = _mobile_target(protocol, args)
        return {'target': str(target), 'before': _measure_file(target)}
    return None


def _conserved_task(old, fresh, changes):
    expected = {**old, **changes}
    return fresh is not None and set(fresh) == set(expected) and all(fresh.get(key) == value for key, value in expected.items() if key != 'updatedAt')


def _task_control(protocol, name, args, before):
    fresh = _tasks(protocol)
    for key, old in before['tasks'].items():
        if name.endswith('.start'):
            changes = {} if old['owner'] == 'Paul' else {
                'armed': True, 'status': 'waiting' if old['status'] == 'blocked' else old['status']}
            # An actual launch must be proved through a provider owner; arming is
            # witnessed only while waiting behind prerequisites or resource gates.
            if not _conserved_task(old, fresh.get(key), changes):
                return False
        else:
            changes = {} if old['status'] == 'done' else {'armed': False, 'status': 'blocked', 'reason': 'Stopped by owner'}
            if not _conserved_task(old, fresh.get(key), changes):
                return False
    return True


def _mission_control(protocol, args, before):
    fresh = durable_effects._mission(protocol, args['id'])
    if fresh is None:
        return False
    selected = set(before['selected'])
    action = args['action']
    old_mission = before['mission']
    expected_status = {'pause': 'paused', 'stop': 'stopped', 'start': 'running'}.get(action, old_mission['status']) if not args.get('taskId') else old_mission['status']
    if fresh['status'] != expected_status:
        return False
    for key in ('id', 'goal', 'folder', 'budget', 'acceptanceChecks', 'taskIds', 'plan', 'holdAtPlanPercent'):
        if fresh.get(key) != old_mission.get(key):
            return False
    current = {row['id']: row for row in fresh['tasks']}
    if set(current) != set(before['tasks']):
        return False
    for key, old in before['tasks'].items():
        changes = {}
        if key in selected:
            if action == 'start' and old['owner'] != 'Paul':
                changes = {'armed': True, 'status': 'waiting' if old['status'] == 'blocked' else old['status']}
            elif action == 'pause':
                changes = {'armed': False}
            elif action == 'stop' and old['status'] != 'done':
                changes = {'armed': False, 'status': 'blocked', 'reason': 'Stopped by owner'}
            elif action == 'redirect' and key == args.get('taskId'):
                from ..nightshift import nightshift_for
                patched = {**old, **{field: args[field] for field in ('prompt', 'model', 'effort', 'permissionMode') if field in args}}
                if any(field in args for field in ('model', 'effort', 'permissionMode')):
                    patched.pop('routingProfile', None)
                prepared = nightshift_for(protocol.gateway.root, None).prepare(patched)
                changes = {**prepared, 'armed': False, 'status': 'waiting', 'runId': None, 'evidence': None, 'reason': None}
                if 'routingProfile' not in prepared and 'routingProfile' in current[key]:
                    return False
                old = {field: value for field, value in old.items() if field != 'routingProfile' or field in prepared}
        if not _conserved_task(old, current.get(key), changes):
            return False
    return True


def _verify(protocol, name, args, value, before):
    if name == 'neyvia.mission.from_plan':
        if _measure_file(Path(before['source']['path'])) != before['source']:
            return False
        expected = {**args, 'tasks': before['compiled']['tasks'], 'goal': args.get('goal') or Path(args['planPath']).stem}
        if not durable_effects._mission_check(protocol, expected, value, before):
            return False
        fresh = durable_effects._mission(protocol, args.get('id') or value['mission']['id'])
        from ..nightshift import nightshift_for
        service = nightshift_for(protocol.gateway.root, None)
        identity = fresh['id']
        budget = args.get('budget') or {}
        limits = {key: amount for key, amount in budget.items() if key != 'maxTokens'}
        if budget.get('maxTokens'):
            limits['maxTaskTokens'] = min(limits.get('maxTaskTokens') or budget['maxTokens'], budget['maxTokens'])
        tasks = {row['id']: row for row in fresh['tasks']}
        for row in before['routed']:
            prepared = service.prepare({**row, 'id': identity + ':' + row['id'], 'missionId': identity,
                                        'needs': [identity + ':' + item for item in row.get('needs', [])], 'limits': limits})
            saved = tasks.get(prepared['id'])
            if not saved or any(saved.get(key) != item for key, item in prepared.items()):
                return False
        return fresh.get('holdAtPlanPercent') == args.get('holdAtPlanPercent', 70) and fresh.get('plan') == {
            'path': before['source']['path'], 'sha256': before['compiled']['planSha256'], 'allocations': before['compiled']['allocations']}
    if name == 'neyvia.mission.control':
        return value.get('id') == args['id'] and value.get('action') == args['action'] and _mission_control(protocol, args, before)
    if name in {'neyvia.nightshift.start', 'neyvia.nightshift.stop'}:
        return _task_control(protocol, name, args, before)
    if name == 'neyvia.autopilot.stop':
        from ..neyvia_autopilot import load
        fresh = load(_service(protocol), args['runId'])
        expected = deepcopy(before)
        if before['status'] != 'completed':
            expected.update(stopRequested=True, status='stopped')
        return (value.get('run') == fresh and _service(protocol).bus.get('autopilot:' + args['runId']) == fresh and
                all(fresh.get(key) == item for key, item in expected.items() if key != 'elapsedMs') and
                set(fresh) == set(expected) | {'elapsedMs'})
    if name == 'neyvia.mobile.create':
        from ..neyvia_mobile_studio import STARTER_HTML, STARTER_CSS, STARTER_JS, state
        target = Path(before['target'])
        if before['before'].get('exists') and before['before'].get('entries') != 0:
            return False
        name_value = args['name'].strip()
        slug = re.sub(r'[^a-z0-9]+', '-', name_value.casefold()).strip('-') or 'app'
        bundle = args.get('bundleId') or 'com.neyvia.' + (re.sub(r'[^a-z0-9]', '', slug) or 'app')
        package = bundle.replace('-', '_')
        files = {'www/index.html': STARTER_HTML.replace('__NAME__', html.escape(name_value)),
                 'www/app.css': STARTER_CSS, 'www/app.js': STARTER_JS,
                 'app.json': json.dumps({'expo': {'name': name_value, 'slug': slug, 'version': '1.0.0', 'ios': {'bundleIdentifier': bundle}, 'android': {'package': package}}}, indent=2) + '\n',
                 'capacitor.config.json': json.dumps({'appId': package, 'appName': name_value, 'webDir': 'www'}, indent=2) + '\n',
                 '.gitignore': 'node_modules/\n.agent_control/\nandroid/app/build/\n*.p12\n*.mobileprovision\n'}
        if value.get('created') != str(target) or value.get('bundleId') != bundle or state(_service(protocol)).get('project') != str(target):
            return False
        return all((target / path).is_file() and (target / path).read_bytes() == content.replace('\n', os.linesep).encode('utf-8') for path, content in files.items())
    return False


def checks_for(protocol, name, args):
    if name in durable_effects.SUPPORTED:
        return durable_effects.checks_for(protocol, name, args)
    if name not in SUPPORTED:
        return []
    observer = ('neyvia.mission.list' if '.mission.' in name else
                'neyvia.nightshift.tasks' if '.nightshift.' in name else
                'neyvia.autopilot.get' if '.autopilot.' in name else 'mobile-starter-files')
    if protocol.scope is not None and observer != 'mobile-starter-files' and observer not in protocol.scope:
        return []
    subject = args.get('id') or args.get('runId') or args.get('ids') or args.get('path') or 'new'
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': name + ':' + str(subject),
             'bindSubject': lambda arguments, value, previous: name + ':' + str(arguments.get('id') or arguments.get('runId') or arguments.get('ids') or value.get('created') or value.get('mission', {}).get('id')),
             'observerTool': observer, 'subject': deepcopy(args),
             'expectation': 'Fresh retained subject equals requested local admission/control; no provider, rendered preview, build or install claim',
             'check': lambda arguments, value, previous: _verify(protocol, name, arguments, value, previous)}]
