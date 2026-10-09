"""Real CL durable admission/control calls; no model/job-generation substitution."""
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
    root = REPO / '.agent_control/proofs' / ('FIXCL3-jobs-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.cl import jobs_effects
    prepare_broker_fixture(root)
    bind_fixture_broker(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL3-jobs', permission_mode='workspace')
    service = workspace_for(root)
    result = {'schema': 'neyvia.FIXCL3.jobs.v1', 'root': str(root), 'journeys': {}, 'checks': {},
              'boundary': 'Exact local plan compilation, dormant graph supervision, task arming behind unmet prerequisite, stopping a seeded saved autopilot fixture and exact starter bytes. No generated provider work, visible mobile preview, APK/IPA build or device installation is claimed.'}
    paths = [REPO / 'src/grant_agent/cl/jobs_effects.py', REPO / 'src/grant_agent/neyvia_nightshift.py', REPO / 'scripts/fixcl3_jobs_probe.py']
    paths += [REPO / 'manuals' / (name + '.manual.json') for name in ('mission-plan', 'nightshift', 'autopilot', 'mobile-studio')]
    paths += [REPO / 'manuals/cl' / (name + '.cl') for name in ('mission-plan', 'nightshift', 'autopilot', 'mobile-studio')]
    hashes = lambda: {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    result['sourceHashesAtStart'] = hashes()
    call = lambda name, args: unwrap(gateway.native.call('neyvia.' + name, args))
    def action(key, name, args, goal, approve=False):
        protocol = Protocol(gateway, lazy_manuals=True)
        initial_subject = jobs_effects.snapshot_for(protocol, 'neyvia.' + name, args) if name == 'mobile.create' else None
        arguments = ','.join(k + '=' + json.dumps(v) for k, v in args.items())
        lines = 'G: ' + goal + '\n' + name + '(' + arguments + ')\ndone()'
        output = protocol.run(lines, action_id=key)
        if approve:
            result['journeys'][key + '-before-approval'] = output
            result['checks'][key + '-approval-required'] = not output['ok']
            with service.bus.connect() as db:
                rows = [(row['key'], json.loads(row['value'])) for row in db.execute("SELECT key,value FROM state WHERE key LIKE 'approval:%'")]
            pending = [(k, v) for k, v in rows if v.get('status') != 'approved' and v.get('approved') is not True]
            # Each operation has its own exact details, not a blanket approval.
            if name == 'nightshift.start':
                pending = [(k, v) for k, v in pending if v.get('details', {}).get('action') == 'start' and v['details'].get('args') == args]
            if name == 'mobile.create':
                pending = [(k, v) for k, v in pending if v.get('details') == args]
            if len(pending) != 1:
                raise RuntimeError('One exact disposable approval required: ' + key + ' ' + repr(pending))
            result.setdefault('fixtureApprovals', []).append(pending[0][1])
            service.approve(pending[0][0].split(':', 1)[1])
            if name == 'mobile.create':
                # Artifact-write retry is conservatively marked uncertain even
                # when its native result only requested approval. Reconcile
                # the exact empty subject before using a separate action ID.
                fresh_subject = jobs_effects.snapshot_for(protocol, 'neyvia.' + name, args)
                result['checks'][key + '-approval-target-unchanged'] = fresh_subject == initial_subject
                if fresh_subject != initial_subject:
                    raise RuntimeError('Approval changed the intended mobile target; no recovery action allowed')
                protocol = Protocol(gateway, lazy_manuals=True)
                output = protocol.run(lines, action_id=key + '-after-exact-approval')
            else:
                output = protocol.run(lines, action_id=key)
        result['journeys'][key] = output
        result['checks'][key] = bool(output['ok'] and protocol.completion().get('status') == 'completed')
        if not result['checks'][key]:
            raise RuntimeError(key + ': ' + json.dumps(output) + ' completion=' + json.dumps(protocol.completion()))
        return protocol

    # compile_plan checks distinct existing Git worktree markers, never invokes Git.
    for name in ('track-a', 'track-b'):
        (root / name / '.git').mkdir(parents=True)
    plan = root / 'PLAN.md'
    plan.write_text('# Two dormant fixture tasks\n\n| Track | Worktree | Backend | Vite |\n|---|---|---|---|\n| alpha | track-a | 48821 | 48822 |\n| beta | track-b | 48823 | 48824 |\n\n## §0 Shared rules\nPreserve disposable fixtures.\n## §1 alpha: first task\nWrite fixture alpha.\n## §2 beta: second task\nWrite fixture beta.\n', encoding='utf-8')
    mission_goal = 'mission.list()["missions"][0]["id"] == "plan-fixture"'
    compiled = action('mission-from-plan', 'mission.from_plan', {'id': 'plan-fixture', 'planPath': str(plan), 'folder': str(root), 'acceptanceChecks': ['Both fixtures checked'], 'builder': {'model': 'claude-sonnet-4-5'}, 'verifier': {'model': 'gpt-6-sol'}}, mission_goal)
    plan.write_text(plan.read_text(encoding='utf-8') + '\nChanged after admission\n', encoding='utf-8')
    result['checks']['plan-source-drift-refuses'] = compiled.completion().get('status') == 'incomplete'
    # Redirect/pause/stop remain entirely dormant: no providers are dispatched.
    action('mission-redirect', 'mission.control', {'id': 'plan-fixture', 'action': 'redirect', 'taskId': 'plan-fixture:alpha-build', 'prompt': 'Exact revised local fixture'}, 'mission.list()["missions"][0]["tasks"][0]["prompt"] == "Exact revised local fixture"')
    action('mission-pause', 'mission.control', {'id': 'plan-fixture', 'action': 'pause'}, 'mission.list()["missions"][0]["status"] == "paused"')
    stopped = action('mission-stop', 'mission.control', {'id': 'plan-fixture', 'action': 'stop'}, 'mission.list()["missions"][0]["status"] == "stopped"')
    from grant_agent.nightshift import nightshift_for
    night = nightshift_for(root, None)
    with night.connect() as db:
        db.execute("UPDATE missions SET status='draft' WHERE id='plan-fixture'")
    result['checks']['mission-status-drift-refuses'] = stopped.completion().get('status') == 'incomplete'
    call('nightshift.create', {'id': 'owner-input', 'prompt': 'Wait for disposable fixture review', 'owner': 'Paul', 'folder': str(root)})
    call('nightshift.create', {'id': 'agent-waiting', 'prompt': 'Read disposable fixture once prerequisite complete', 'needs': ['owner-input'], 'folder': str(root), 'harness': 'codex', 'model': 'gpt-6-sol'})
    tasks = call('nightshift.tasks', {})['tasks']
    index = next(i for i, row in enumerate(tasks) if row['id'] == 'agent-waiting')
    armed = action('nightshift-arm-waiting', 'nightshift.start', {'ids': ['agent-waiting']}, f'nightshift.tasks()["tasks"][{index}]["armed"] == true', approve=True)
    saved = call('nightshift.tasks', {})['tasks'][index]
    result['checks']['armed-behind-unmet-prerequisite-no-run'] = saved['armed'] and saved['status'] == 'waiting' and saved['runId'] is None
    disarmed = action('nightshift-stop-waiting', 'nightshift.stop', {'id': 'agent-waiting'}, f'nightshift.tasks()["tasks"][{index}]["status"] == "blocked"')
    result['checks']['prior-arming-completion-invalidated'] = armed.completion().get('status') == 'incomplete'
    night.block('agent-waiting', 'Fresh changed reason')
    result['checks']['stop-reason-drift-refuses'] = disarmed.completion().get('status') == 'incomplete'
    # Saved owner fixture is explicitly not a generated provider run. Stop is a
    # real owner call preserving all item/usage data in this local state.
    from grant_agent.neyvia_autopilot import save, load
    run_id = 'a' * 32
    fixture = {'schema': 'neyvia.autopilot.v1', 'runId': run_id, 'requestId': 'fixture', 'status': 'paused', 'items': [], 'models': [], 'tokens': {}, 'scopeTools': ['workspace.read'], 'startedAt': time.time(), 'fixture': 'disposable saved control state; no provider execution'}
    save(service, fixture)
    auto = action('autopilot-stop-saved-fixture', 'autopilot.stop', {'runId': run_id}, 'autopilot.get(runId="' + run_id + '")["run"]["status"] == "stopped"')
    changed = load(service, run_id)
    changed['tokens'] = {'changed': 1}
    save(service, changed)
    result['checks']['autopilot-retained-data-drift-refuses'] = auto.completion().get('status') == 'incomplete'
    parent = root / 'phone'
    parent.mkdir()
    mobile = action('mobile-create-starter', 'mobile.create', {'path': str(parent), 'name': 'Local Phone Fixture', 'bundleId': 'com.neyvia.localfixture'}, 'time.now()["unixSeconds"] > 0', approve=True)
    result['checks']['starter-six-files'] = len([p for p in parent.rglob('*') if p.is_file()]) == 6
    (parent / 'www/app.js').write_bytes(b'changed source\n')
    result['checks']['starter-byte-drift-refuses'] = mobile.completion().get('status') == 'incomplete'
    scoped = Protocol(gateway, lazy_manuals=True)
    refused = scoped.run('G: time.now()["unixSeconds"] > 0\nnightshift.stop(id="agent-waiting")\ndone()', action_id='missing-observer', scope_tools=['neyvia.nightshift.stop', 'time.now'])
    result['journeys']['scope-observer-refused'] = refused
    result['checks']['missing-owner-scope-refuses-before-call'] = not refused['ok']
    result['sourceHashesAtEnd'] = hashes()
    result['checks']['sourceUnchanged'] = result['sourceHashesAtStart'] == result['sourceHashesAtEnd']
    result['ok'] = all(result['checks'].values())
    night.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'ok': result['ok'], 'checks': result['checks']}))
    sys.exit(0 if result['ok'] else 1)
