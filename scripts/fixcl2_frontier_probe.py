"""Real CL calls on disposable owner state for the FIXCL2 local frontier layer."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from fixcl_verify import environment, guards  # noqa: E402


def source_hashes():
    paths = [REPO / 'src/grant_agent/cl' / name for name in (
        'effects.py', 'frontier_effects.py', 'frontier_local_effects.py', 'manual_effects.py',
        'codecs.py', 'protocol.py', 'host.py', 'integration.py')]
    paths += [REPO / 'manuals' / name for name in (
        'neyvia.manual.json', 'manuals-next.manual.json', 'cl/neyvia.cl', 'cl/manuals-next.cl')]
    paths.append(REPO / 'src/grant_agent/manual_versions.py')
    paths.append(REPO / 'src/grant_agent/manual_contracts.py')
    paths.append(Path(__file__))
    return {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def run(root: Path, port: int):
    if port not in range(48821, 48830):
        raise ValueError('Use the assigned explicit FIXCL2 port range')
    root.mkdir(parents=True, exist_ok=False)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    source_start = source_hashes()
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    bus = bus_for(root)
    identity = 'fixture-chat'
    project = str(root / 'fixture-project')
    Path(project).mkdir()
    bus.put('projects', {project: {'name': 'Fixture project', 'path': project}})
    bus.put('sessions', {identity: {'id': identity, 'app': 'codex', 'folder': str(root), 'archived': True}})
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    cases = [
        ('pin', f'G local: state()["sessions"]["{identity}"]["pinned"] == True\nsession.pin(id="{identity}", pinned=True)\ndone()'),
        ('rename', f'G local: state()["sessions"]["{identity}"]["title"] == "Reviewed chat"\nsession.rename(id="{identity}", title="Reviewed chat")\ndone()'),
        ('move', 'G local: state()["sessions"]["fixture-chat"]["project"] == ' + json.dumps(project) + '\nsession.move(id="fixture-chat", project=' + json.dumps(project) + ')\ndone()'),
        ('restore', f'G local: state()["sessions"]["{identity}"]["archived"] == False\nsession.archive(id="{identity}", archived=False)\ndone()'),
        ('sidebar-policy', 'G local: sidebar.policy()["policy"]["noFolderDays"] == 7\nsidebar.policy(policy={"noFolderDays":7,"projectDays":14,"tidyThreshold":5,"autoArchive":false})\ndone()'),
        ('manual-frontier', 'G local: time.now()["unixSeconds"] > 0\nmanual.frontier(id="manuals-next", note="FIXCL2 observed procedure gap", observed={"kind":"fixture","subject":"manuals-next"})\ndone()'),
        ('manual-demote', 'G local: time.now()["unixSeconds"] > 0\nmanual.demote(id="manuals-next", chapter="versions", procedure="inspect-history", reason="FIXCL2 reviewed obsolete example")\ndone()'),
    ]
    results = {}
    for key, source in cases:
        protocol = Protocol(gateway)
        result = protocol.run(source, action_id='fixcl2-' + key)
        results[key] = {'ok': result.get('ok'), 'status': result.get('status'),
                        'text': result.get('text'), 'reason': result.get('reason'), 'error': result.get('error'),
                        'checks': [check.get('name') for row in result.get('results', []) for check in row.get('checks', [])],
                        'manualUse': [row.get('manualUse', {}) for row in result.get('results', []) if row.get('manualUse')]}
    denied = protocol.run('session.pin(id="missing-chat", pinned=True)', action_id='fixcl2-missing')
    results['missing-session'] = {'ok': denied.get('ok'), 'status': denied.get('status'),
                                  'error': denied.get('error')}
    before_policy = bus.get('cleanupPolicy')
    observer_denied = Protocol(gateway).run(
        'G local: sidebar.policy(policy={"noFolderDays":99})["policy"]["noFolderDays"] == 99\ndone()',
        action_id='fixcl2-observer-argument')
    results['mutation-as-observer'] = {'ok': observer_denied.get('ok'), 'status': observer_denied.get('status'),
                                       'text': observer_denied.get('text'),
                                       'policyUnchanged': bus.get('cleanupPolicy') == before_policy}
    from grant_agent.neyvia_manuals import unwrap
    patches = unwrap(gateway.native.call('neyvia.manual.patches', {'id': 'manuals-next'}))['patches']
    selected = next(row for row in patches if row.get('note') == 'FIXCL2 reviewed obsolete example')
    current_version = unwrap(gateway.native.call('neyvia.manual.versions', {'id': 'manuals-next'}))['sha256']
    review_path = root / '.neyvia/manual-patches' / (selected['patchId'] + '.json')
    promote_source = ('G local: time.now()["unixSeconds"] > 0\nmanual.patch.apply(id="manuals-next",patchId=' +
                      json.dumps(selected['patchId']) + ',expectedSha256=' + json.dumps(current_version) +
                      ',approved=true,reviewer="FIXCL2 controlled fixture",evidence=[' +
                      json.dumps(str(review_path)) + '])\ndone()')
    promoted = Protocol(gateway).run(promote_source, action_id='fixcl2-manual-promote')
    promote_failure = next((row.get('result', {}).get('error') or row.get('error')
                            for row in promoted.get('results', []) if not row.get('ok')), None)
    results['manual-promote'] = {'ok': promoted.get('ok'), 'status': promoted.get('status'),
                                 'text': promoted.get('text'), 'reason': promoted.get('reason'),
                                 'error': promote_failure,
                                 'checks': [check.get('name') for row in promoted.get('results', []) for check in row.get('checks', [])],
                                 'manualUse': [row.get('manualUse', {}) for row in promoted.get('results', []) if row.get('manualUse')]}
    adverse = {'staleExpectedRefused': False, 'corruptVersionRefused': False, 'restoredVersionValid': False,
               'recursiveCandidatesRefused': {}}
    from grant_agent.manual_contracts import validate_grounding
    base_manual = json.loads((REPO / 'manuals/manuals-next.manual.json').read_text(encoding='utf-8'))
    for chapter, action in (('scripts', 'run'), ('scripts', 'script.run'), ('versions', 'recover')):
        candidate = copy.deepcopy(base_manual)
        procedure = next(iter(candidate['chapters'][chapter]['procedures'].values()))
        procedure['steps'].append({'action': action, 'args': {}, 'save': 'recursive-fixture'})
        try:
            validate_grounding(candidate, gateway.native)
        except ValueError as exc:
            adverse['recursiveCandidatesRefused'][action] = 'Recursive manual execution' in str(exc)
        else:
            adverse['recursiveCandidatesRefused'][action] = False
    for section in ('state', 'checks'):
        candidate = copy.deepcopy(base_manual)
        if section == 'state':
            candidate['chapters']['versions'][section]['forbidden-edit-observer'] = {
                'tool': 'neyvia.manual.frontier', 'args': {}, 'inputs': {'type': 'object'},
                'shape': {'type': 'object'}}
        else:
            candidate['chapters']['versions'][section]['forbidden-edit-check'] = {
                'tool': 'neyvia.manual.frontier', 'args': {}, 'expect': {'path': 'ok', 'op': 'exists'}}
        try:
            validate_grounding(candidate, gateway.native)
        except ValueError as exc:
            adverse['recursiveCandidatesRefused'][section] = 'Recursive manual execution' in str(exc)
        else:
            adverse['recursiveCandidatesRefused'][section] = False
    if promoted.get('ok') is True:
        new_version = unwrap(gateway.native.call('neyvia.manual.versions', {'id': 'manuals-next'}))['sha256']
        stale_patch = unwrap(gateway.native.call('neyvia.manual.frontier', {
            'id': 'manuals-next', 'note': 'FIXCL2 stale hash fixture', 'observed': {'fixture': True},
            'operations': [{'op': 'add', 'path': '/chapters/versions/guidance/-',
                            'value': 'Stale hash fixture only'}]}))
        stale = gateway.native.call('neyvia.manual.patch.apply', {
            'id': 'manuals-next', 'patchId': stale_patch['patchId'],
            'expectedSha256': current_version, 'approved': True,
            'reviewer': 'FIXCL2 controlled fixture', 'evidence': [str(review_path)]})
        adverse['staleExpectedRefused'] = stale.get('ok') is False and unwrap(
            gateway.native.call('neyvia.manual.versions', {'id': 'manuals-next'}))['sha256'] == new_version
        version_file = root / '.neyvia/manual-versions/manuals-next' / (new_version + '.json')
        exact_bytes = version_file.read_bytes()
        try:
            version_file.write_bytes(b'corrupt fixture bytes\n')
            damaged = gateway.native.call('neyvia.manual.versions', {'id': 'manuals-next'})
            adverse['corruptVersionRefused'] = damaged.get('ok') is False
        finally:
            version_file.write_bytes(exact_bytes)
        adverse['restoredVersionValid'] = (hashlib.sha256(version_file.read_bytes()).hexdigest() == new_version
                                           and unwrap(gateway.native.call('neyvia.manual.versions',
                                                                          {'id': 'manuals-next'}))['sha256'] == new_version)
    source_end = source_hashes()
    return {'schema': 'neyvia.FIXCL2.frontier.v1', 'root': str(root), 'port': port,
            'results': results, 'fresh': bus.get('sessions', {}).get(identity),
            'sourceHashesAtStart': source_start, 'sourceHashesAtEnd': source_end,
            'adverse': adverse,
            'checks': {'all_actions': all(results[k]['ok'] is True and results[k]['checks'] and
                                         results[k]['manualUse'] for k in ('pin', 'rename', 'move', 'restore', 'sidebar-policy',
                                                                          'manual-frontier', 'manual-demote', 'manual-promote')),
                       'missing_refused': denied.get('ok') is False,
                       'mutation_as_observer_refused': observer_denied.get('ok') is False and bus.get('cleanupPolicy') == before_policy,
                       'manual_stale_refused': adverse['staleExpectedRefused'],
                       'manual_corruption_refused_and_restored': adverse['corruptVersionRefused'] and adverse['restoredVersionValid'],
                       'recursive_candidate_refused': all(adverse['recursiveCandidatesRefused'].get(key) is True
                                                          for key in ('run', 'script.run', 'recover', 'state', 'checks')),
                       'source_unchanged': source_start == source_end}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-frontier-' + str(time.time_ns()))
    result = run(root, args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'checks': result['checks'], 'output': str(args.output)}))
    sys.exit(0 if all(result['checks'].values()) else 1)
