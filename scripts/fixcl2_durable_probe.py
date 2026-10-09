"""Real CL host journeys for retained mission and Night Shift actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, bind_fixture_broker, environment, guards


def run(port):
    if port not in range(48821, 48830):
        raise ValueError('Assigned FIXCL ports only')
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-durable-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    bound_paths = [REPO / item for item in (
        'src/grant_agent/cl/durable_effects.py', 'src/grant_agent/cl/frontier_effects.py',
        'src/grant_agent/cl/effects.py', 'src/grant_agent/cl/protocol.py', 'src/grant_agent/cl/host.py',
        'src/grant_agent/neyvia_workspace_tools.py', 'src/grant_agent/nightshift.py',
        'src/grant_agent/nightshift_resources.py', 'src/grant_agent/mission_control.py',
        'manuals/neyvia.manual.json', 'manuals/cl/neyvia.cl',
        'manuals/mission-plan.manual.json', 'manuals/cl/mission-plan.cl',
        'manuals/nightshift.manual.json', 'manuals/cl/nightshift.cl',
        'scripts/fixcl2_durable_probe.py')]
    source_hashes = lambda: {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in bound_paths}
    source_start = source_hashes()
    prepare_broker_fixture(root)
    bind_fixture_broker(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL2-durable', permission_mode='workspace')
    host = Protocol(gateway)
    quoted = json.dumps
    proof = root / 'evidence.txt'
    proof.write_bytes(b'# Exact evidence bytes\n')
    result = {'schema': 'neyvia.FIXCL2.durable.v1', 'root': str(root), 'journeys': {}, 'checks': {}}
    from grant_agent.cl import durable_effects

    def owner_action(key, name, args):
        previous = durable_effects.snapshot_for(host, name, args)
        output = unwrap(gateway.native.call(name, args))
        checks = durable_effects.checks_for(host, name, args)
        passed = bool(checks) and all(row['check'](args, output, previous) for row in checks)
        result['journeys'][key] = {'native': output, 'effectChecks': [row['name'] for row in checks], 'passed': passed}
        result['checks'][key] = passed
        return output

    owner_action('native-dormant-task', 'neyvia.nightshift.create',
                 {'id': 'N1', 'prompt': 'Read native fixture', 'folder': str(root), 'harness': 'codex', 'model': 'gpt-6-sol'})
    owner_action('native-file-evidence', 'neyvia.nightshift.tick',
                 {'id': 'N1', 'evidence': {'type': 'file', 'path': str(proof)}})
    owner_action('native-mission-graph', 'neyvia.mission.create',
                 {'id': 'NM', 'goal': 'Persist a graph', 'folder': str(root),
                  'tasks': [{'id': 'A', 'prompt': 'First branch', 'harness': 'codex', 'model': 'gpt-6-sol'},
                            {'id': 'B', 'prompt': 'Second branch', 'harness': 'codex', 'model': 'gpt-6-sol', 'needs': ['A']}],
                  'acceptanceChecks': ['A and B have evidence']})

    def journey(key, lines, action_id=None, protocol=None):
        output = (protocol or host).run(lines, action_id=action_id or key)
        result['journeys'][key] = output
        return output

    first = journey('dormant-task', 'G: time.now()["unixSeconds"] > 0\nnightshift.create(id="D1",prompt="Read fixture",folder=' + quoted(str(root)) + ',harness="codex",model="gpt-6-sol")\ndone()')
    observed = unwrap(gateway.native.call('neyvia.nightshift.tasks', {}))['tasks']
    task = next((row for row in observed if row['id'] == 'D1'), None)
    result['checks']['dormantTask'] = bool(first['ok'] and task and task['status'] == 'waiting' and not task['armed'] and not task['runId'])

    tick = journey('file-evidence', 'G: time.now()["unixSeconds"] > 0\nnightshift.tick(id="D1",evidence={"type":"file","path":' + quoted(str(proof)) + '})\ndone()')
    observed = unwrap(gateway.native.call('neyvia.nightshift.tasks', {}))['tasks']
    task = next((row for row in observed if row['id'] == 'D1'), None)
    result['checks']['fileEvidence'] = bool(tick['ok'] and task and task['status'] == 'done' and task['evidence']['sha256'])

    mission = journey('mission-draft', 'G: time.now()["unixSeconds"] > 0\nmission.create(id="M1",goal="Prove a dormant task graph",folder=' + quoted(str(root)) + ',tasks=[{"id":"A","prompt":"First branch","harness":"codex","model":"gpt-6-sol"},{"id":"B","prompt":"Second branch","harness":"codex","model":"gpt-6-sol","needs":["A"]}],acceptanceChecks=["A and B have evidence"])\ndone()')
    missions = unwrap(gateway.native.call('neyvia.mission.list', {}))['missions']
    saved = next((row for row in missions if row['id'] == 'M1'), None)
    result['checks']['missionGraph'] = bool(mission['ok'] and saved and saved['status'] == 'draft' and
        {row['id']: row['needs'] for row in saved['tasks']} == {'M1:A': [], 'M1:B': ['M1:A']} and
        all(not row['armed'] and row['status'] == 'waiting' for row in saved['tasks']))

    # Real external byte drift must revoke completion despite an unrelated true G.
    proof.write_bytes(b'Changed evidence after completion\n')
    stale = host.completion()
    result['journeys']['stale-evidence'] = stale
    result['checks']['staleEvidenceRefusesDone'] = stale['status'] == 'incomplete' and any(
        row.get('name') == 'nightshift.tick' and row.get('passed') is False for row in stale.get('goalChecks', []))

    projects = root / 'projects'
    folder = projects / 'folder-one'
    folder_lines = 'G: time.now()["unixSeconds"] > 0\nfolder.create(path=' + quoted(str(projects)) + ',name="folder-one")\ndone()'
    folder_host = Protocol(gateway)
    pending = journey('project-root-awaits-owner', folder_lines, protocol=folder_host)
    result['checks']['projectRootApprovalGate'] = not pending['ok'] and not folder.exists()
    from grant_agent.neyvia_workspace_tools import workspace_for
    workspace = workspace_for(root)
    with workspace.bus.connect() as db:
        approvals = [(row['key'], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
    expected_key = 'folder:' + os.path.normcase(str(projects))
    exact = [(key, record) for key, record in approvals if record.get('key') == expected_key]
    if len(exact) != 1:
        raise RuntimeError('Expected one exact disposable project-root approval: ' + str(pending.get('status')) + ' ' + str(pending.get('text', ''))[-500:])
    workspace.approve(exact[0][0].split(':', 1)[1])
    created_folder = journey('approved-folder', folder_lines, action_id='project-root-awaits-owner', protocol=folder_host)
    project_host = Protocol(gateway)
    created_project = journey('registered-project', 'G: time.now()["unixSeconds"] > 0\nproject.create(name="project-one")\ndone()', protocol=project_host)
    registrations = unwrap(gateway.native.call('neyvia.folder.list', {}))['folders']
    result['checks']['folderCreatedAndRegistered'] = bool(created_folder['ok'] and folder.is_dir() and
        any(row['path'] == str(folder) and row['name'] == 'folder-one' for row in registrations))
    result['checks']['projectCreatedAndRegistered'] = bool(created_project['ok'] and (projects / 'project-one').is_dir() and
        any(row['path'] == str(projects / 'project-one') and row['name'] == 'project-one' for row in registrations))

    board_text = '## TASKS\n- [ ] A1 · Codex · needs: none · First dormant task\n- [ ] A2 · Codex · needs: A1 · Second dormant task\n'
    import_host = Protocol(gateway)
    imported = import_host.run('G: time.now()["unixSeconds"] > 0\nnightshift.import(text=' + quoted(board_text) + ',folder=' + quoted(str(root)) + ')\ndone()', action_id='import-board')
    result['journeys']['import-board'] = imported
    imported_tasks = {row['id']: row for row in unwrap(gateway.native.call('neyvia.nightshift.tasks', {}))['tasks'] if row['id'] in {'A1', 'A2'}}
    result['checks']['importedPrerequisites'] = bool(imported['ok'] and set(imported_tasks) == {'A1', 'A2'} and
        imported_tasks['A2']['needs'] == ['A1'] and all(row['status'] == 'waiting' and not row['armed'] for row in imported_tasks.values()))

    block_host = Protocol(gateway)
    blocked = block_host.run('G: time.now()["unixSeconds"] > 0\nnightshift.block(id="A2",reason="Fixture dependency held")\ndone()', action_id='block-task')
    result['journeys']['block-task'] = blocked
    saved_block = next((row for row in unwrap(gateway.native.call('neyvia.nightshift.tasks', {}))['tasks'] if row['id'] == 'A2'), None)
    result['checks']['blockedExactTask'] = bool(blocked['ok'] and saved_block and saved_block['status'] == 'blocked' and
        saved_block['reason'] == 'Fixture dependency held' and not saved_block['armed'] and saved_block['needs'] == ['A1'])

    night_host = Protocol(gateway)
    before_night = unwrap(gateway.native.call('neyvia.nightshift.summary', {}))['night']['nightId']
    night_lines = 'G: time.now()["unixSeconds"] > 0\nnightshift.begin()\ndone()'
    pending_night = night_host.run(night_lines, action_id='begin-night')
    result['journeys']['begin-awaits-owner'] = pending_night
    result['checks']['nightApprovalGate'] = bool(not pending_night['ok'] and
        unwrap(gateway.native.call('neyvia.nightshift.summary', {}))['night']['nightId'] == before_night)
    with workspace.bus.connect() as db:
        approvals = [(row['key'], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
    exact_night = [(key, row) for key, row in approvals if (row.get('details') or {}).get('action') == 'begin'
                   and (row.get('details') or {}).get('args') == {}]
    if len(exact_night) != 1:
        raise RuntimeError('Expected one exact disposable Night Shift begin approval')
    workspace.approve(exact_night[0][0].split(':', 1)[1])
    started_night = night_host.run(night_lines, action_id='begin-night')
    result['journeys']['begin-night'] = started_night
    after_night = unwrap(gateway.native.call('neyvia.nightshift.summary', {}))['night']['nightId']
    result['checks']['newNightRetained'] = bool(started_night['ok'] and after_night != before_night)

    policy_host = Protocol(gateway)
    policy_before = unwrap(gateway.native.call('neyvia.nightshift.resources', {}))
    policy_lines = 'G: time.now()["unixSeconds"] > 0\nnightshift.resources(maxNightSeconds=7200,holdAtPlanPercent=60)\ndone()'
    pending_policy = policy_host.run(policy_lines, action_id='night-budget')
    result['journeys']['budget-awaits-owner'] = pending_policy
    result['checks']['budgetApprovalGate'] = bool(not pending_policy['ok'] and
        unwrap(gateway.native.call('neyvia.nightshift.resources', {})) == policy_before)
    with workspace.bus.connect() as db:
        approvals = [(row['key'], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
    exact_policy = [(key, row) for key, row in approvals if (row.get('details') or {}).get('action') == 'resources'
                    and (row.get('details') or {}).get('args') == {'maxNightSeconds': 7200, 'holdAtPlanPercent': 60}]
    if len(exact_policy) != 1:
        raise RuntimeError('Expected one exact disposable Night Shift budget approval')
    workspace.approve(exact_policy[0][0].split(':', 1)[1])
    saved_policy = policy_host.run(policy_lines, action_id='night-budget')
    result['journeys']['night-budget'] = saved_policy
    policy_after = unwrap(gateway.native.call('neyvia.nightshift.resources', {}))
    result['checks']['budgetRetained'] = bool(saved_policy['ok'] and policy_after['maxNightSeconds'] == 7200 and
        policy_after['holdAtPlanPercent'] == 60 and all(policy_after[key] == value for key, value in policy_before.items()
            if key not in {'maxNightSeconds', 'holdAtPlanPercent'}))
    source_end = source_hashes()
    result['sourceHashesAtStart'] = source_start
    result['sourceHashesAtEnd'] = source_end
    result['checks']['sourceUnchanged'] = source_start == source_end
    result['ok'] = all(result['checks'].values())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'ok': receipt['ok'], 'checks': receipt['checks'], 'root': receipt['root']}))
    if not receipt['ok']:
        sys.exit(1)
