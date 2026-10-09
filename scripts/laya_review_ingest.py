"""Persist provenance-bound review episodes; evaluation families stay excluded."""
import json
from collections import Counter
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('D:/NeyviaRuns/laya-train/review')
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.laya_instant import Episodes
from grant_agent.laya_instant_ingest import ingest
from grant_agent.laya_curriculum import load, rank, outcome_input
from laya_harvest_c7_outcomes import label as outcome_label, digest
from laya_review_curves import bucket, read


def main():
    runtime = DATA / 'learned-runtime'
    local = Episodes(runtime)
    report = {'runtime': str(runtime), 'areas': {}, 'started': time.time()}
    augmented = list({r['id']: r for pattern in ('routing-[01].json', 'procedures-[01].json')
                      for p in DATA.glob(pattern) for r in read(p)['accepted']}.values())
    extra = read(DATA/'wave2/action-paraphrases.json')['accepted']
    model = load('manual-router')
    model['rows'] = [r for r in model['rows'] if r.get('kind') == 'actions']
    for row in extra:
        ranked = rank(model, row['input'], 1)
        if not ranked or ranked[0].get('tool') != row['expectedAction']:
            raise ValueError('Paraphrase no longer resolves: ' + row['id'])
    augmented = list({r['id']: r for r in augmented + extra}.values())
    c7 = read(DATA/'wave2/c7-outcomes.json')['records']
    checked_hashes = {}
    c7_rows = []
    for row in c7:
        evidence = row['evidence']
        path = row['source']['path']
        if path not in checked_hashes:
            checked_hashes[path] = digest(Path(path))
        if checked_hashes[path] != row['source']['sha256']:
            raise ValueError('C7 operation receipt changed: ' + path)
        if outcome_label(evidence['observed']) != row['label'] or outcome_input({'toolId': evidence['operation'], 'result': evidence['observed']}) != row['input']:
            raise ValueError('C7 outcome/projection mismatch: ' + path)
        family = evidence['operation'].split('.')[0]
        c7_rows.append({**row, 'domain': 'outcomes', 'family': family,
            'source': path + '#' + evidence['operation'] + ':' + str(evidence['occurrence']),
            'evidence': {**evidence, 'sha256': checked_hashes[path], 'contractFamily': row['family']}})
    report['independentReview'] = {'actionParaphrasesReresolved': len(extra), 'c7OperationsReprojected': len(c7_rows), 'c7ReceiptsHashed': len(checked_hashes)}
    routing_logs = []
    for row in read(DATA/'wave2/routing-logs.json')['records']:
        source = row['source']
        for log in source.get('logs', []):
            if digest(Path(log['path'])) != log['sha256']:
                raise ValueError('Routing log changed: ' + log['path'])
        manual = read(ROOT/'manuals'/f"{row['label']}.manual.json")
        if manual['id'] != row['label']:
            raise ValueError('Unknown routing manual')
        routing_logs.append({**row, 'domain': 'routing',
            'source': source.get('promptDefinition', source.get('taskDefinition')),
            'evidence': {'provenance': source, 'observations': row['evidence'], 'expectedActions': row['expectedActions']}})
    report['independentReview']['realRoutingFamilies'] = len(routing_logs)
    for area, rows in [('contracts', read(DATA/'contracts.json')), ('routing', read(DATA/'routing.json') + augmented),
                       ('outcomes', read(DATA/'outcomes.json')), ('c7-outcomes', c7_rows), ('routing-logs', routing_logs)]:
        counts = Counter()
        with local.import_batch():
            for index, row in enumerate(rows):
                heldout = bucket(row['family']) == (4 if area.startswith('routing') else 0)
                evidence = {**row.get('evidence', {}), 'family': row['family'], 'evaluationRole': 'holdout' if heldout else 'train'}
                source = row['source'] + '#' + str(evidence.get('caseId', evidence.get('pointer', row.get('id', index))))
                result = local.learn(row.get('domain', area), row['input'], row['label'], source,
                    evidence=evidence, split=evidence['evaluationRole'])
                counts['learned' if result['learned'] else 'existing'] += 1
                counts[evidence['evaluationRole']] += 1
                if (index+1) % 100 == 0:
                    print(area, index+1, 'staged', flush=True)
        report['areas'][area] = dict(counts)
        (DATA/'ingestion.json').write_text(json.dumps(report, indent=2))
    report['personal'] = ingest(runtime)
    local.refresh()
    report['status'] = local.status()
    report['finished'] = time.time()
    (DATA/'ingestion.json').write_text(json.dumps(report, indent=2))
    (ROOT/'scripts/evidence/LAYAT-review-ingestion.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report['areas']), flush=True)


if __name__ == '__main__':
    main()
