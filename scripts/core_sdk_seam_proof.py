"""Evidence: an out-of-repo caller judges its own scene with its own predicates (plan 23 SDK seam).

Three routes, one judge:
  1. in process:   scene_core.normalize(domain, raw) + scene_core.judge(scene, predicates)
  2. standalone SDK over HTTP: neyvia_sdk.NeyviaClient(url).judge_scene(raw, predicates=..., domain=...)
     against an isolated backend this script starts privately on CORE port 49117
  3. refusals: code-shaped predicates (unknown operator, attribute-walking field, extra keys,
     non-numeric ordering, bad regex) are rejected as data errors; nothing is evaluated.

The scene is a trading-shaped probe written here, not market data. No order endpoint exists.
Usage: python scripts/core_sdk_seam_proof.py   -> scripts/evidence/CORE-sdk-seam.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
PORT = 49117
RUN = Path('D:/NeyviaRuns/CORE/sdk-seam')

RAW = {'surface': 'paper-book', 'nodes': [
    {'id': 'book', 'kind': 'position', 'attributes': {'symbol': 'BTC-USD'}, 'measurements': {'exposure': 0.31, 'limit': 0.25}},
    {'id': 'feed', 'kind': 'quote', 'attributes': {'note': "__import__('os').system('calc')"}, 'measurements': {'ageSeconds': 95}},
    {'id': 'backtest', 'kind': 'backtest', 'attributes': {}, 'measurements': {'trainEnd': '2026-06-30', 'signalStart': '2026-06-01'}}]}
PREDICATES = [
    {'id': 'risk-limit-breach', 'condition': {'all': [{'field': 'kind', 'op': 'eq', 'value': 'position'},
                                                       {'field': 'measurements.exposure', 'op': 'gt', 'value': 0.25}]},
     'severity': 'error', 'evidence': ['measurements.exposure', 'measurements.limit'],
     'fix': {'action': 'config.reduce-size', 'arguments': {'review': 'human'}}},
    {'id': 'stale-data', 'condition': {'all': [{'field': 'kind', 'op': 'eq', 'value': 'quote'},
                                                {'field': 'measurements.ageSeconds', 'op': 'gt', 'value': 60}]},
     'severity': 'warning', 'evidence': ['measurements.ageSeconds'], 'fix': {'action': 'data.refresh', 'arguments': {}}},
    {'id': 'code-as-data', 'condition': {'field': 'attributes.note', 'op': 'eq', 'value': '0'},
     'severity': 'error', 'evidence': ['attributes.note'], 'fix': {'action': 'review', 'arguments': {}}}]
EXPECTED = [('risk-limit-breach', 'book'), ('stale-data', 'feed')]
BAD = {
    'unknown-operator': {'field': 'kind', 'op': '__import__', 'value': 'os'},
    'attribute-walk': {'field': "kind'].__class__", 'op': 'eq', 'value': 1},
    'extra-code-key': {'field': 'kind', 'op': 'eq', 'value': 1, 'code': 'print(1)'},
    'string-ordering': {'field': 'kind', 'op': 'gt', 'value': '1'},
    'bad-regex': {'field': 'kind', 'op': 'matches', 'value': '('},
}


def pairs(verdict):
    return sorted((f['predicate'], f['node']) for f in verdict['findings'])


def in_process():
    from grant_agent import scene_core
    started = time.perf_counter()
    scene = scene_core.normalize('trading-probe', RAW)
    verdict = scene_core.judge(scene, PREDICATES, record=False)
    refused = {}
    for name, condition in BAD.items():
        try:
            scene_core.judge(scene, [{'id': name, 'condition': condition, 'severity': 'error', 'evidence': [], 'fix': {'action': 'review'}}], record=False)
            refused[name] = 'ACCEPTED'
        except Exception as exc:
            refused[name] = f'{type(exc).__name__}: {exc}'
    return {'findings': pairs(verdict), 'admitted': verdict['admitted'], 'unknown': verdict['unknown'],
            'sceneSha256': scene['sha256'], 'ms': round((time.perf_counter() - started) * 1000, 1), 'refused': refused}


def over_http():
    import placement_shots as shots
    from neyvia_sdk import NeyviaClient, NeyviaError
    shots.BACKEND, shots.SCRATCH, shots.SMALL_STATE = PORT, RUN / 'runtime', None
    shots.free(PORT)
    env = shots.isolated_env()
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'src'), *[p for p in sys.path if Path(p).name == 'site-packages']])
    build = RUN / 'static'
    build.mkdir(parents=True, exist_ok=True)
    (build / 'index.html').write_text('<!doctype html><title>sdk seam</title>', encoding='utf-8')
    log = (RUN / 'backend.log').open('wb')
    backend = subprocess.Popen([shots.PYTHON, 'scripts/run_web_backend.py', '--host', '127.0.0.1', '--port', str(PORT),
                                '--root', str(RUN / 'state').replace('\\', '/'), '--static-root', str(build).replace('\\', '/'),
                                '--skip-runtime-auto-update', '--skip-proof-self-check'],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        shots.await_http(f'http://127.0.0.1:{PORT}/api/health', backend)
        client = NeyviaClient(f'http://127.0.0.1:{PORT}', timeout=60)
        client.sign_in()
        started = time.perf_counter()
        verdict = client.judge_scene(RAW, predicates=PREDICATES, domain='trading-probe', record=False)
        ms = round((time.perf_counter() - started) * 1000, 1)
        receipt = {k: verdict.get(k) for k in ('tool', 'ok', 'receipt_id', 'duration_ms', 'schema')}
        verdict = verdict.get('result', verdict)  # SDK results are normal Neyvia native-tool receipts
        bad = client.judge_scene(RAW, predicates=[{'id': 'x', 'condition': BAD['unknown-operator'], 'severity': 'error',
                                                   'evidence': [], 'fix': {'action': 'review'}}], domain='trading-probe', record=False)
        bad = bad.get('result', bad)
        started = time.perf_counter()
        client.judge_scene(RAW, predicates=PREDICATES, domain='trading-probe', record=False)
        warm = round((time.perf_counter() - started) * 1000, 1)  # first call includes native gateway start
        return {'findings': pairs(verdict), 'admitted': verdict.get('admitted'), 'unknown': verdict.get('unknown'),
                'sceneSha256': verdict.get('sceneSha256'), 'roundTripMs': ms, 'warmRoundTripMs': warm, 'receipt': receipt, 'refusal': bad}
    except NeyviaError as exc:
        return {'error': f'{exc.code}: {exc}'}
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=15)
        except subprocess.TimeoutExpired:
            backend.kill()
        log.close()


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    local = in_process()
    remote = over_http()
    refusal = remote.get('refusal') or {}
    checks = {
        'in-process-findings': local['findings'] == sorted(EXPECTED),
        'in-process-refusals': all(v != 'ACCEPTED' for v in local['refused'].values()),
        'sdk-http-findings': remote.get('findings') == sorted(EXPECTED),
        'same-scene-binding': remote.get('sceneSha256') == local['sceneSha256'],
        'sdk-http-refusal': refusal.get('accepted') is False and 'Unknown predicate operator' in str(refusal.get('reason')),
        'code-text-stays-data': ('code-as-data', 'feed') not in [tuple(p) for p in remote.get('findings') or []],
    }
    report = {'schema': 'neyvia.core-sdk-seam.v1', 'command': 'python scripts/core_sdk_seam_proof.py',
              'inProcess': local, 'sdkHttp': remote, 'checks': checks, 'passed': all(checks.values())}
    (ROOT / 'scripts/evidence/CORE-sdk-seam.json').write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], **checks}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
