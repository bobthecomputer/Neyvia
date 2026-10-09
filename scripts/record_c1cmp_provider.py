"""Import a lead's real provider attempt, scored by the shared independent checker."""
import argparse
import hashlib
import json
from pathlib import Path
from c1_comparison_checker import check_fixture, load, safe_path, ROOT
from c1_comparison_execution import save, summarize


def record(fixture_path, execution_path):
    fixture = load(fixture_path)
    if fixture['arm'] not in {'claude_computer_use', 'openai_computer_use'}:
        raise ValueError('Provider importer cannot replace Neyvia attempts')
    execution_path = safe_path(execution_path)
    execution = load(execution_path)
    # These measurements must be exported from the real provider run. Missing
    # provider usage/cost remains null with a reason rather than an estimate.
    if execution.get('fixtureToken') != fixture['token'] or not execution.get('model'):
        raise ValueError('Provider execution must identify this exact fixture and actual model')
    elapsed = (int(execution['endedUnixNs']) - int(execution['startedUnixNs'])) / 1e6
    if elapsed < 0:
        raise ValueError('Invalid provider clock')
    if not isinstance(execution.get('actions'), int) or execution['actions'] < 0:
        raise ValueError('Actual provider action count required')
    if (execution.get('tokens') is None or execution.get('cost') is None) and not execution.get('metricsReason'):
        raise ValueError('Unavailable usage/cost needs an explicit reason')
    checked = check_fixture(fixture)
    certified = bool(execution.get('ownedDisposableTarget') and execution.get('cleanupOnlyOwnedTarget'))
    result_path = ROOT / 'scripts/evidence/C1CMP.json'
    result = load(result_path)
    previous = next(r for r in result['attempts'] if r['id'] == fixture['id'] and r['arm'] == fixture['arm']
        and r['repetition'] == fixture['repetition'] and Path(r['fixture']).resolve() == fixture_path.resolve())
    row = {'id': fixture['id'], 'app': fixture['app'], 'arm': fixture['arm'], 'repetition': fixture['repetition'],
        'fixture': str(fixture_path), 'series': previous['series'], 'model': execution['model'],
        'elapsedMs': elapsed, 'actions': execution.get('actions'), 'tokens': execution.get('tokens'),
        'cost': execution.get('cost'), 'currency': execution.get('currency'),
        'metricsReason': execution.get('metricsReason'), 'checker': checked,
        'executionEvidence': str(execution_path), 'executionSha256': hashlib.sha256(execution_path.read_bytes()).hexdigest(),
        'ownershipEvidence': execution.get('ownershipEvidence'),
        'ok': checked['ok'] and certified and elapsed <= fixture['timeBudgetSeconds'] * 1000,
        'metricBoundary': 'Lead-exported real provider clock/actions/usage; artifact and revision checks independently rerun here'}
    row['status'] = 'passed' if row['ok'] else 'failed'
    target = safe_path(ROOT / previous['receipt'])
    row['receipt'] = target.relative_to(ROOT).as_posix()
    if previous['status'] not in {'pending_lead', 'unsupported_adapter'}:
        raise ValueError('An executed provider attempt cannot be overwritten')
    result['attempts'][result['attempts'].index(previous)] = row
    save(target, row)
    summarize(result)
    save(result_path, result)
    print(json.dumps(row))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--execution', type=Path, required=True)
    args = parser.parse_args()
    record(args.fixture, args.execution)
