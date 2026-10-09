"""Bind the sealed paired panel and real pressure probes without rewriting archives."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from seal_c4 import REPO, read, digest, sum_tokens, price
from grant_agent.cl.provider11 import usage_counts


def source_binding(name, expected):
    if digest(REPO / name) == expected:
        return name
    archived = REPO / 'scripts/evidence/C4b/sources' / (expected + Path(name).suffix)
    if not archived.is_file() or digest(archived) != expected:
        raise ValueError('Missing exact historical source: ' + name)
    return archived.relative_to(REPO).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pressure', nargs='+', required=True, metavar='RUN=RECEIPT')
    args = parser.parse_args()
    target = REPO / 'scripts/evidence/C4b.json'
    index = read(target)
    archive = REPO / index['archive']['path']
    if digest(archive) != index['archive']['sha256']:
        raise ValueError('Sealed panel archive changed')
    with zipfile.ZipFile(archive) as bundle:
        manifest = read(REPO / 'scripts/evidence/C4b/manifest.json')
        if set(bundle.namelist()) != {row['path'] for row in manifest}:
            raise ValueError('Panel manifest membership mismatch')
        for row in manifest:
            raw = bundle.read(row['path'])
            if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('Panel entry mismatch: ' + row['path'])
    for row in index['rows']:
        row['sourceBindings'] = {name:source_binding(name, expected)
                                 for name, expected in row['sourceSha256'].items()}
    probes = []
    seen = set()
    for spec in args.pressure:
        run_id, receipt_name = spec.split('=', 1)
        if Path(run_id).name != run_id or run_id in {'.', '..'} or run_id in seen:
            raise ValueError('Unique bounded run names required')
        seen.add(run_id)
        receipt_path = REPO / 'scripts/evidence' / receipt_name
        if receipt_path.parent != REPO / 'scripts/evidence':
            raise ValueError('One receipt filename required')
        receipt = read(receipt_path)
        run = receipt['run']
        archive = REPO / 'scripts/evidence/C4b' / (run_id + '.zip')
        usage = []
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError('Pressure archive integrity failure')
            for name in sorted(bundle.namelist()):
                if name.startswith('run/turn-') and name.endswith('/receipt.json'):
                    provider = json.loads(bundle.read(name))
                    if provider['requestedModel'] != 'gpt-6-luna' or provider['effort'] != 'medium':
                        raise ValueError('Pressure model/effort drift')
                    events = [json.loads(line) for line in bundle.read(name.replace('receipt.json','events.jsonl')).decode().splitlines() if line.strip()]
                    completed = [event['usage'] for event in events if event.get('type') == 'turn.completed']
                    if completed and usage_counts(completed[-1]) != usage_counts(provider.get('usage')):
                        raise ValueError('Pressure raw usage mismatch')
                    usage.append(usage_counts(provider.get('usage')))
            if sum_tokens(usage) != run['tokens']:
                raise ValueError('Pressure total usage mismatch')
            if any(turn['hostPromptTokens'] > receipt['budget'] for turn in run['turns']):
                raise ValueError('Pressure host budget exceeded')
            if receipt['passed']:
                if not (run['passed'] and receipt['quality']['passed'] and run['contextMetrics']['compactions'] > 0):
                    raise ValueError('Pressure acceptance inconsistent')
                if receipt.get('task','bugfix') == 'source-inspection':
                    history = json.loads(bundle.read('run/history/index.json'))['records']
                    first = json.loads(bundle.read('run/history/' + history[0]['handle'] + '.json'))['record']
                    if first['content'].strip() != 'workspace.read(path="host-source.py",maxChars=100000)':
                        raise ValueError('Required first source read changed')
                    if hashlib.sha256(bundle.read('workspace/host-source.py')).hexdigest() != receipt['quality']['inputSha256']:
                        raise ValueError('Actual source input changed')
        bindings = {name:source_binding(name, expected) for name, expected in run['sourceSha256'].items()}
        probes.append({'run':run_id, 'receipt':receipt_path.relative_to(REPO).as_posix(),
                       'receiptSha256':digest(receipt_path), 'accepted':receipt['passed'],
                       'task':receipt.get('task','bugfix'), 'budget':receipt['budget'],
                       'tokens':run['tokens'], 'costUsd':price(run['tokens']),
                       'contextMetrics':run['contextMetrics'], 'sourceBindings':bindings,
                       'archive':{'path':archive.relative_to(REPO).as_posix(), 'sha256':digest(archive),
                                  'compressedBytes':archive.stat().st_size}})
    latest = read(REPO / 'scripts/evidence/C4b-compaction.json')
    latest_sources = {name:digest(REPO / name) for name in index['sourceSha256']}
    latest_sources.update({name:digest(REPO / name) for name in ('scripts/verify_c4_compaction.py','scripts/finalize_c4b.py')})
    if latest['passed'] and any(digest(REPO / name) != expected for name,expected in latest['run']['sourceSha256'].items()):
        raise ValueError('Successful pressure run does not bind the current implementation')
    index['latestSourceSha256'] = latest_sources
    index['pressureProbes'] = probes
    index['pressureObservedTokens'] = sum_tokens([probe['tokens'] for probe in probes])
    index['pressureObservedCostUsd'] = price(index['pressureObservedTokens'])
    index['totalObservedIncludingPressure'] = sum_tokens([index['allRecoveryObservedTokens'], index['pressureObservedTokens']])
    index['totalObservedCostUsdIncludingPressure'] = price(index['totalObservedIncludingPressure'])
    index['proofReceipts'] = {name:digest(REPO / 'scripts/evidence' / name)
                              for name in ('C4-host.json','C4-production.json','C4-native.json','C4b-compaction.json')}
    host, production = read(REPO / 'scripts/evidence/C4-host.json'), read(REPO / 'scripts/evidence/C4-production.json')
    index['realCompactionVerified'] = latest['passed']
    index['mechanismVerified'] = host['ok'] and production['passed'] and index['hostBudgetVerified'] and latest['passed']
    index['limits'] += [limit for limit in (
        'Paired R4 runs preceded the explicit newest-history page fix and did not trigger their 8000-token cap; their exact historical source bindings are retained.',
        '2000-2200-token bug-fix pressure runs fail despite preserved readable state. They are adverse evidence, not accepted tasks.',
        'Pressure source-inspection uses a task clarification naming the action dispatcher after a failed wrong-helper search; it is separate from R4 savings.'
    ) if limit not in index['limits']]
    target.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:index[key] for key in ('mechanismVerified','realCompactionVerified','pressureObservedTokens','totalObservedCostUsdIncludingPressure')}))


if __name__ == '__main__':
    main()
