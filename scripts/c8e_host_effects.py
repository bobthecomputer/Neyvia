"""Fresh durable/OS observations of the original B host contract runners."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def apply(bindings):
    overlay = json.loads((ROOT / 'config/inception_c8e_host_effects.json').read_text(encoding='utf-8'))
    for identity, additions in overlay['bindings'].items():
        binding = bindings[identity]
        binding['c8eHostEffect'] = additions['area']
        binding['deadlineSeconds'] = 600
        effect = binding['c8eEffect']
        effect.update(producerAdmission='scoped-production-chapters', renderedWitness='c8e-host',
                      unprovedDefiningMechanisms=[], missingPrerequisite=None,
                      boundary=additions['boundary'])
        manifest = json.loads((ROOT / ('config/proofs/' + additions['area'] + '.json')).read_text(encoding='utf-8'))
        declared = additions['c8eEffect']['requiredContractIds']
        if declared != [row['id'] for row in manifest['contracts']]:
            raise ValueError('C8e host contract overlay differs from the production manifest')
        effect['requiredContractIds'] = declared
    return bindings


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _check(identity, passed, observed):
    return {'id': identity, 'passed': bool(passed), 'fresh': True, 'observed': observed,
            'boundary': 'Original production host procedure and independent durable/OS readback; no provider or native UI claim'}


def _engine(area_root, area):
    states = [_load(path) for path in (area_root / 'engine/runs').glob('*/state.json')]
    sessions = list((area_root / 'engine/runs').glob('*/metadata.json'))
    preflight_events = [json.loads(line) for path in (area_root / 'engine/runs').glob('*/timeline.jsonl')
                        for line in path.read_text(encoding='utf-8').splitlines()
                        if json.loads(line).get('kind') == 'preflight_failed']
    scenarios = {row.get('scenario') for row in area['checks']}
    required = {'parallel-consensus', 'resume-session', 'resume-checkpoint', 'unreadable-document',
                'bounded-context-rollover', 'risk-averse-merge', 'no-output-no-worker',
                'recent-evidence-fresh-lease-exemptions', 'block-receipt-idempotence', 'repair-step'}
    recorder = _load(area_root / 'recorder/.agent_control/mission_runs/proof-local/flight_recorder/snapshot.json')
    database = area_root / 'ecosystem/.agent_control/ecosystem.sqlite3'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        experiments = [dict(zip(('verdict', 'journal'), row)) for row in connection.execute('SELECT verdict,journal_json FROM experiments')]
    checks = [
        _check('c8e.host.engine-all-scenarios', required <= scenarios,
               {'expected': sorted(required), 'actual': sorted(s for s in scenarios if s)}),
        _check('c8e.host.engine-resumable-state', len(sessions) >= 7 and len(states) >= 6
               and len(preflight_events) == 1 and bool(preflight_events[0].get('metadata', {}).get('failures'))
               and any(len(s.get('completed_steps', [])) >= 3 and s.get('worker_merge_events') for s in states)
               and any(len(s.get('session_lineage', [])) >= 2 for s in states)
               and any(s.get('autopilot_pause_reason') in {'context_rollover', 'context_hard_stop'} for s in states),
               {'states': states, 'sessionCount': len(sessions), 'blockedPreflightEvents': preflight_events,
                'checkpointCount': len(list((area_root / 'engine/runs').rglob('*checkpoint*')))}),
        _check('c8e.host.engine-negative-experiment-durable', any(str(e['verdict']).startswith('failed:')
               and json.loads(e['journal'])[0]['observation'] == 'Digest recorded' for e in experiments), experiments),
        _check('c8e.host.engine-recorder-window', recorder['eventCount'] == len(recorder['events']) == 200
               and recorder['events'][0]['kind'] == 'checkpoint.5'
               and recorder['events'][-1]['kind'] == 'checkpoint.204', recorder),
    ]
    return checks


def _harness(area_root, area):
    import psutil
    calls = area['calls']
    by_name = {}
    for row in calls:
        by_name.setdefault(row['procedure'], []).append(row)
    required = {'native-file-sharing-read', 'blocked-late-event-cancel-and-outcomes',
                'arm-cancel-real-deadline-late-settlement', 'fifo-os-slot-release',
                'owned-dead-win32-probe', 'owned-process-crash-and-kernel-recovery',
                'early-cancellation-and-dead-owner-reconciliation', 'retention-hidden-owner-and-future-schema',
                'live-malformed-and-aged-contended-lease', 'real-owned-process-tree-cancellation',
                'native-detached-concurrent-start-and-cancel', 'public-profile-gateway-instruction-catalog',
                'owned-win32-access-failure'}
    pids = sorted({int(row[key]) for row in calls for key in ('pid', 'childPid', 'deadOwnedPid') if row.get(key)})
    from grant_agent.harness_jobs import _process_alive
    # Windows can retain terminated process metadata while an OS observer has
    # a handle. Existence alone is not the original producer's liveness test.
    liveness = [{'pid': pid, 'exists': psutil.pid_exists(pid), 'alive': _process_alive(pid)} for pid in pids]
    fences = by_name.get('owned-win32-access-failure', [])
    sharing = by_name.get('native-file-sharing-read', [])
    trees = by_name.get('real-owned-process-tree-cancellation', [])
    jobs, corrupt = [], []
    for path in area_root.rglob('harness-job-*.json'):
        try:
            jobs.append(_load(path))
        except json.JSONDecodeError:
            corrupt.append({'path': path.relative_to(area_root).as_posix(),
                            'bytes': path.read_text(encoding='utf-8')})
    checks = [
        _check('c8e.host.harness-all-procedures', required <= by_name.keys(),
               {'expected': sorted(required), 'actual': sorted(by_name)}),
        _check('c8e.host.harness-real-processes-stopped', bool(pids) and not any(r['alive'] for r in liveness), liveness),
        _check('c8e.host.harness-dacl-restoration', {r['mode'] for r in fences} == {'query-denied', 'stop-retry'}
               and all(r.get('finalDaclRestoreCode') == 0 and r.get('reaped') is True
                       and r.get('aliveAfterCleanup') is False for r in fences), fences),
        _check('c8e.host.harness-file-sharing', len(sharing) == 1
               and all(sharing[0].get(k) is True for k in ('transientReadRecovered', 'persistentReadRejected', 'handlesReleased'))
               and bool(sharing[0]['actualWinErrors']), sharing),
        _check('c8e.host.harness-corruption-preserved',
               {r['path'] for r in corrupt} == {
                   'unreadable/.agent_control/harness_jobs/harness-job-corrupt.json',
                   'legacy-execution/.agent_control/harness_jobs/harness-job-malformed.json'}
               and all(r['bytes'] == '{bad' for r in corrupt), corrupt),
        _check('c8e.host.harness-tree-budget-durable', {r['reason'] for r in trees} == {'operator', 'runtime_budget'}
               and all(r.get('descendantsStopped') is True for r in trees)
               and any(j.get('status') == 'cancelled' and j.get('budgetOutcome') == 'enforced'
                       and j.get('budget', {}).get('status') == 'exhausted' for j in jobs),
               {'trees': trees, 'terminalBudgets': [{'id': j.get('id'), 'status': j.get('status'),
                 'budget': j.get('budget'), 'budgetOutcome': j.get('budgetOutcome')} for j in jobs if j.get('status') == 'cancelled']}),
    ]
    return checks


def witness(worker, effect, root):
    """Called by c8e_effects.after_manual; never launches an alternate producer."""
    identity = effect['producerAreas'][0]
    report = worker.c8e_effect.get('producer', {})
    area = next((row for row in report.get('areas', []) if row.get('area') == identity), {})
    if not area.get('ok'):
        return [_check('c8e.host.original-producer', False, area)], {
            'contractEffects': [{'id': contract, 'passed': False, 'fresh': True,
                                'boundary': 'production-state', 'observed': area}
                               for contract in effect['requiredContractIds']]}
    scratch = Path(report['scratchRoot']).resolve()
    scratch.relative_to(Path(root).resolve())
    area_root = scratch / identity
    manifest_path = ROOT / 'config/proofs' / (identity + '.json')
    manifest = _load(manifest_path)
    required = {row['id'] for row in manifest['contracts']}
    observed = {row['contract'] for row in area.get('checks', []) if row.get('ok') is True}
    receipt = _load(area_root / 'contract-receipt.json')
    checks = [_check('c8e.host.exact-contracts-and-durable-receipt', observed == required
                     and set(area['contracts']) == required and receipt == area,
                     {'required': sorted(required), 'observed': sorted(observed),
                      'caseIds': [row['case_id'] for row in manifest['coverage']],
                      'manifestSha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()})]
    checks += _engine(area_root, area) if identity == 'proofs-b-engine' else _harness(area_root, area)
    passed = all(check['passed'] for check in checks)
    return checks, {'contractEffects': [{'id': contract, 'passed': passed, 'fresh': True,
                      'boundary': 'production-state',
                      'observed': {
                          'productionObservation': [row for row in area['checks'] if row['contract'] == contract],
                          'coverageCaseIds': [row['case_id'] for row in manifest['coverage'] if contract in row['contracts']],
                          'freshDurableChecks': [{'id': row['id'], 'passed': row['passed'],
                                                  'fresh': row['fresh']} for row in checks]}}
                     for contract in sorted(required)], 'hostScratchRoot': str(area_root),
                     'frontier': area.get('frontier', []), 'providerOrNativeUiProof': False}
