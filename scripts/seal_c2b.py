"""Independently verify C2b raw receipts and append scoped research results."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_client.contracts import digest
from grant_agent.laya_client.browser_client import project_grounded_state
from efficiency_log import validate, ledger_lock, read_ledger


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def quantile(values, p):
    return sorted(values)[min(len(values)-1, math.ceil(len(values)*p)-1)]


def metrics(rows, threshold):
    supported = {'Choose the observed page topic.': 'title', 'Choose the correct current website.': 'hostname',
                 'Choose the actual observed page URL.': 'url', 'What is the observed document loading state?': 'readyState'}
    eligible = [r for r in rows if r.get('decision_profile') == 'public_observed_fields@1'
                and r.get('advisory_field') == supported.get(r['question']['instructions'])]
    accepted = [r for r in eligible if r['confidence'] >= threshold]
    return {'accepted': len(accepted), 'accepted_correct': sum(r['correct'] for r in accepted),
            'precision': statistics.mean(r['correct'] for r in accepted) if accepted else None,
            'coverage': len(accepted)/len(rows), 'eligible': len(eligible)}


def verify():
    native = read('scripts/evidence/C2b-native.json')
    assert native['ok'] and native['sourceStable'] and native['ownedProcessesStopped']
    assert len(native['checks']) == 13 and all(c['ok'] for c in native['checks'])
    for p, expected in native['sourceHashes'].items():
        assert sha(p) == expected, p
    assert sha(native['native']['path']) == native['native']['sha256']
    for image in native['screenshots']:
        assert sha(image['path']) == image['sha256']
    public = read('scripts/evidence/C2b-public.json')
    tasks = read('scripts/evidence/C2-tasks.json')['tasks']
    results = [r for r in public['tasks'] if r['split'] == 'heldout']
    assert len(results) == len(tasks) >= 20
    assert {r['id'] for r in results} == {r['id'] for r in tasks}
    for r in public['tasks']:
        assert sha(r['observationPath']) == r['observationSha256']
        assert r['success'] == all(r['actualChecks'].values())
        assert r['steps'] >= 2 and r['providerCostUSD'] == 0
    assert not next(r for r in results if r['checks']['meanings'])['success']
    laya = read('scripts/evidence/C2b-laya-advisory.json')
    spec = read('scripts/evidence/C2b-laya-calibration.json')
    freeze = read('scripts/evidence/C2b-laya-threshold-freeze.json')
    assert laya['calibration'] == spec and spec['identity_digest'] == digest(laya['identity'])
    assert laya['identity']['candidate'] == 'g3-c2' and laya['identity']['device'] == 'cpu'
    assert laya['identity']['weights_frozen'] and not laya['identity']['state_cache'] and not laya['identity']['answer_memory']
    assert sha('src/grant_agent/laya_client/fast_cpu.py') == laya['identity']['adapter_sha256']
    for directory, head in laya['identity']['head_artifacts'].items():
        assert sha(str(Path(directory) / 'manifest.json')) == head['manifest_sha256']
        assert sha(str(Path(directory) / 'head.npz')) == head['head_sha256']
        project = Path(directory).parents[3]
        for name, expected_hash in laya['identity']['source_sha256'].items():
            assert sha(str(project / 'laya_system1' / name)) == expected_hash
    assert sha('src/grant_agent/laya_client/browser_client.py') == spec['advisory_browser_client_sha256']
    rows = laya['rows']
    cases = [json.loads(line) for line in (ROOT / 'scripts/evidence/C2b-decisions-advisory.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    assert digest(cases) == spec['dataset_digest']
    by_id = {r['id']: r for r in rows}
    assert len(cases) == len(rows)
    for case in cases:
        assert all(by_id[case['id']][k] == v for k,v in case.items())
    fit = [r for r in rows if r['split'] == 'calibration']
    hold = [r for r in rows if r['split'] == 'heldout']
    assert len(fit) == 40 and len(hold) >= 200
    assert len({r['id'] for r in rows}) == len(rows)
    assert not {r['group'] for r in fit} & {r['group'] for r in hold}
    assert freeze['frozen_before_any_heldout_inference'] and freeze['eligible_fit_count'] == 40
    assert freeze['advisory_threshold'] == spec['advisory_threshold']
    assert freeze['fit_predictions_digest'] == digest(fit)
    possible = []
    for threshold in sorted({r['confidence'] for r in fit}):
        m = metrics(fit, threshold)
        if m['accepted'] >= 20 and m['precision'] >= .95:
            possible.append((m['accepted'], threshold))
    expected = max(possible, default=(0, 1.000001), key=lambda pair: (pair[0], -pair[1]))[1]
    assert expected == spec['advisory_threshold']
    assert spec['validated'] is False and spec['acceptance_threshold'] > 1
    decision_ids = []
    for row in rows:
        assert row['correct'] == (row['prediction'] == row['gold'])
        assert row['confidence'] == max(row['p'].values())
        assert len(row['repeats']) == 3
        assert all((r['answer'], r['p']) == (row['prediction'], row['p']) for r in row['repeats'])
        assert all(r['runtime']['execution'] == 'cpu-only-r5' for r in row['repeats'])
        decision_ids.extend(r['decision_id'] for r in row['repeats'])
        provenance = row['provenance']
        if provenance.get('observation_path'):
            p = provenance['observation_path']
            assert sha(p) == provenance['observation_sha256'], p
            obs = read(p)
            if row.get('decision_profile') == 'public_observed_fields@1':
                assert row['state'] == project_grounded_state(obs, {'decision_profile': 'public_observed_fields@1'})
                field = row['advisory_field']
                actual = urlsplit(obs['url']).hostname if field == 'hostname' else obs[field]
                assert row['question']['criteria'][row['gold']] == actual
            elif row.get('family') == 'grounded_action':
                wanted = row['expected_check']
                targets = [e for e in obs['elements'] if e['id'] == wanted['element']]
                assert len(targets) == 1 and targets[0]['enabled'] and not targets[0]['secret']
                target = targets[0]
                assert sum(e['role'] == target['role'] and e['name'] == target['name'] for e in obs['elements'] if e['enabled'] and not e['secret'] and 'click' in e['actions']) == 1
                assert target['name'] in row['question']['criteria'][row['gold']]
            elif row.get('domain') == 'computer':
                assert row['state'] == obs and provenance['historical_replay_only'] is True
    assert len(set(decision_ids)) == len(decision_ids), 'Repeated IDs may indicate cached answers'
    actual = metrics(hold, spec['advisory_threshold'])
    for k in ('accepted', 'accepted_correct', 'precision', 'coverage'):
        assert actual[k] == spec['heldout'][k], k
    for name in ('http_ms', 'model_ms'):
        timings = [v for r in rows for v in r[name]]
        assert statistics.median(timings) == laya['latency_ms'][name]['p50']
        assert quantile(timings, .95) == laya['latency_ms'][name]['p95']
    loop = read('scripts/evidence/C2b-loop.json')
    assert not loop.get('error') and len(loop['checks']) >= 7 and all(c['ok'] for c in loop['checks'])
    for p, expected in loop['sourceHashes'].items():
        assert sha(p) == expected, p
    assert loop['healthBefore']['pid'] == loop['healthAfter']['pid']
    assert loop['healthBefore']['identity'] == loop['healthAfter']['identity'] == laya['identity']
    resident = read('scripts/evidence/C2b-laya-runtime.json')
    cleanup = read('scripts/evidence/C2b-laya-cleanup.json')
    assert resident['identity'] == laya['identity'] and resident['pid'] == cleanup['owned_pid'] == loop['healthAfter']['pid']
    assert cleanup['pid_absent'] and cleanup['listener_absent']
    paths = ['scripts/evidence/C2b-native.json', 'scripts/evidence/C2b-public.json', 'scripts/evidence/C2-tasks.json',
             'scripts/evidence/C2b-laya-advisory.json', 'scripts/evidence/C2b-laya-calibration.json',
             'scripts/evidence/C2b-laya-threshold-freeze.json', 'scripts/evidence/C2b-loop.json',
             'scripts/evidence/C2b-action-capture.json', 'scripts/evidence/C2b-laya-action-fit-probe.json',
             'scripts/evidence/C2b-decisions-advisory.jsonl', 'scripts/evidence/C2b-threshold-independence.json',
             'scripts/evidence/C2b-laya-runtime.json', 'scripts/evidence/C2b-laya-cleanup.json',
             'scripts/evidence/C2b-comparators/claude-probe.json', 'scripts/evidence/C2b-comparators/openai-probe.json']
    missing = ['Action-selection System 1 accuracy failed; all action candidates escalate.',
               'Claude-in-Chrome paired tasks blocked by expired authentication; Paul must sign in.',
               'Codex exec browser tool failed its trusted-process initialization; no OpenAI paired score.',
               'Supplied-entry Cambridge lookup subset is scripted; autonomous discovery and general WebVoyager/Mind2Web success unproven.',
               'Full production shell startup, physical computer takeover and general computer-use decision accuracy unproven.',
               'Native startup and end-to-end actions exceed the earlier browser microbenchmark latency targets.']
    summary = {'schema': 'neyvia.C2b-verification@1', 'C2b_complete': False, 'verified_recorded_boundary': True,
               'receipts': {p: sha(p) for p in paths}, 'LAYA': {'heldout': spec['heldout'],
               'eligible_field_decisions': actual['eligible'], 'determinism': laya['determinism'], 'latency_ms': laya['latency_ms'],
               'action_heldout': spec['action_heldout'], 'action_enabled': False},
               'native': {'checks_passed': len(native['checks']), 'startup_ms': native['native']['startupMs'], 'screenshot': native['screenshots']},
               'public_tasks': {'count': len(results), 'extracted_fields_pass': sum(r['success'] for r in results),
               'steps': [r['steps'] for r in results], 'latency_ms': {'p50': statistics.median(r['ms'] for r in results),
               'p95': quantile([r['ms'] for r in results], .95)}, 'provider_cost_usd': sum(r['providerCostUSD'] for r in results)},
               'live_loop_checks': len(loop['checks']), 'missing': missing}
    (ROOT / 'scripts/evidence/C2b.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def ledger_rows():
    ci = {'method': 'not-estimable', 'reason': 'Correlated pages and one native fixture; descriptive run receipts only.'}
    def result(suffix, study, source, method, metrics, models):
        receipt = {'id': 'run', 'path': source, 'sha256': sha(source), 'kind': 'raw'}
        return {'schema': 'neyvia.efficiency-result.v1', 'id': 'C2b-' + suffix, 'study': study, 'method': method,
                'models': models, 'tasks': {'description': study, 'repetitions': 3 if suffix == 'cpu' else 1,
                'independent_unit': 'page/window group'}, 'limitations': read('scripts/evidence/C2b.json')['missing'],
                'receipts': [receipt], 'metrics': [{'name': name, 'unit': unit, 'calculation': calc, 'ci_request': ci} for name,unit,calc in metrics],
                'evidence_status': 'raw-verified'}
    select = lambda pointer, **extra: {'receipt': 'run', 'pointer': pointer, **extra}
    op = lambda name, *args: {'op': name, 'args': list(args)}
    yield result('cpu', 'C2b frozen resident g3-c2 CPU advisory and failed action transfer', 'scripts/evidence/C2b-laya-advisory.json',
        'Threshold fitted on 40 earlier page-field decisions and frozen before 426 heldout decisions: 312 fresh control choices, 104 fresh page fields and 10 historical UIA decisions. Unsupported families escalate. Field precision is raw model precision before deterministic postcheck.',
        [('accepted_precision', 'fraction', select('/calibration/heldout/precision')),
         ('heldout_coverage', 'fraction', select('/calibration/heldout/coverage')),
         ('http_p50', 'ms', op('median', select('/rows', field='/http_ms'))),
         ('http_p95', 'ms', select('/latency_ms/http_ms/p95')),
         ('deterministic_cases', 'count', op('sum', select('/rows', field='/deterministic'))),
         ('fresh_action_accuracy', 'fraction', op('mean', select('/rows', where={'/split':'heldout','/family':'grounded_action'},field='/correct')))],
         ['laya/g3-c2 frozen CPU head; no memory or base cache'])
    yield result('native', 'C2b actual native WebView2 startup and styled iframe effects', 'scripts/evidence/C2b-native.json',
        'Offline native probe built from the shared production browser runtime; actual WebView2 and Obscura form effects, false postcondition and auth-stop paths. Lead inspected emitted screenshot. Startup fix is in probe event-loop setup.',
        [('checks_passed', 'count', op('sum', select('/checks',field='/ok'))), ('native_startup', 'ms', select('/native/startupMs'))], ['no-model: real WebView2/Obscura'])
    yield result('public', 'C2b 21 live public Cambridge supplied-entry lookup tasks', 'scripts/evidence/C2b-public.json',
        'Exact WebVoyager task text retained with starting entry URLs supplied equally to every arm; extracted fields checked in retained actual Neyvia observations. Meaning-count task fails. No autonomous discovery score.',
        [('field_check_success', 'count', op('sum', select('/tasks', where={'/split':'heldout'},field='/success'))),
         ('steps_p50', 'steps', op('median', select('/tasks',where={'/split':'heldout'},field='/steps'))),
         ('latency_p50', 'ms', op('median',select('/tasks',where={'/split':'heldout'},field='/ms'))),
         ('paid_provider_cost', 'USD', op('sum',select('/tasks',where={'/split':'heldout'},field='/providerCostUSD')))], ['no-model: scripted Neyvia live acquisition'])
    for arm in ('claude','openai'):
        yield result(arm, 'C2b ' + arm + ' browser capability probe (blocked paired tasks)',
            'scripts/evidence/C2b-comparators/' + arm + '-probe.json',
            'Lead attempted actual CLI browsing capability. Retained stdout/stderr show the blocking condition; no benchmark success, task count or provider-cost estimate is invented.',
            [('capability_probe_elapsed', 'ms', select('/elapsedMs'))], [arm + ': capability probe only'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--append', action='store_true')
    args = parser.parse_args()
    summary = verify()
    if args.append:
        ledger = ROOT / 'docs/research/results.jsonl'
        with ledger_lock(ledger):
            old = {r['id']: r for r in read_ledger(ledger)}
            rows = [validate(r, ROOT, prepare=True) for r in ledger_rows()]
            for row in rows:
                if row['id'] in old:
                    assert row == old[row['id']], 'Existing C2b row changed'
            with ledger.open('a', encoding='utf-8', newline='\n') as stream:
                for row in rows:
                    if row['id'] not in old:
                        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',',':')) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
    print(json.dumps({k:v for k,v in summary.items() if k != 'receipts'}, indent=2))


if __name__ == '__main__':
    main()
