"""Independently read committed evidence bytes and check scheduled slot coverage."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from cl11_semantic_native_review import parse, text

REPO = Path(__file__).resolve().parents[1]
index_path = REPO / 'scripts/evidence/cl11/index.json'
aggregate = json.loads((REPO / 'scripts/evidence/CL11.json').read_text(encoding='utf-8'))
rows = json.loads(index_path.read_text(encoding='utf-8'))
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
def verify_artifact(row):
    path = (REPO / row['path']).resolve()
    if not path.is_relative_to(REPO / 'scripts/evidence/cl11'):
        return 'Outside evidence scope: ' + row['path']
    if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
        return 'Artifact mismatch: ' + row['path']
    return None

with ThreadPoolExecutor(max_workers=8) as pool:
    errors = [error for error in pool.map(verify_artifact,rows) if error]
if digest(index_path) != aggregate['rawEvidence']['sha256']:
    errors.append('Aggregate index digest mismatch')
cohort = REPO / 'scripts/evidence/cl11' / aggregate['benchmark']['cohort']
manifest = json.loads((cohort / 'manifest.json').read_text(encoding='utf-8'))
key = lambda row: (row['task'], row['model'], row['arm'], row['repetition'])
expected = {key(row) for row in manifest['schedule']}
actual_rows = [json.loads(path.read_text(encoding='utf-8'))
               for path in cohort.glob('task-*/*/*/rep-*/result.json')]
actual = {key(row) for row in actual_rows}
if expected != actual or len(actual_rows) != len(expected):
    errors.append('Missing, extra, or duplicate scheduled slots')
semantic_runs = 0
for name in ('CL11-native-semantic-review.json','CL11-native-semantic-review-cohort-2.json'):
    review_path = REPO/'scripts/evidence'/name
    if not review_path.exists():
        continue
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if len(review['runs']) != 60 or review['reviewedRuns'] != 60:
        errors.append('Incomplete semantic review: '+name)
    for run in review['runs']:
        semantic_runs += 1
        def archived(relative):
            suffix = PurePosixPath(relative).relative_to(PurePosixPath('.agent_control/cl11'))
            path = (REPO/'scripts/evidence/cl11'/suffix).resolve()
            if not path.is_relative_to(REPO/'scripts/evidence/cl11'):
                raise ValueError('Outside semantic source scope')
            return path
        event_path, result_path = archived(run['eventsPath']), archived(run['resultPath'])
        if digest(event_path) != run['eventsSha256'] or digest(result_path) != run['resultSha256']:
            errors.append('Semantic source digest mismatch: '+run['eventsPath'])
        raw = parse(event_path)
        actions = {a['line']:a for a in raw['actions']}
        visible_lines = set(actions) | {a.get('resultLine') for a in actions.values()} | {s['line'] for s in raw['visibleStatements']}
        for action in run['actions']:
            source = actions[action['line']]
            if any(action.get(k) != source.get(k) for k in ('id','tool','input','resultLine','returnStatus','exitCode')):
                errors.append('Semantic action source mismatch: '+run['eventsPath']+':'+str(action['line']))
            if 'output' in source and action.get('visibleOutputSha256') != hashlib.sha256(text(source['output']).encode('utf-8')).hexdigest():
                errors.append('Semantic output digest mismatch: '+run['eventsPath']+':'+str(action['line']))
        annotation = run['semanticReview']
        for field in ('impactKnown','undoKnown','undoAvailable','recoveryMechanismKnown'):
            claim = annotation.get(field,{})
            refs = claim.get('statementLines',[]) + claim.get('supportLines',[])
            if any(n not in visible_lines for n in refs) or (claim.get('value')=='yes' and not refs):
                errors.append('Unsupported semantic line reference: '+run['eventsPath']+' '+field)
        if any(n not in actions for n in annotation['reviewedStateReadbackLines']):
            errors.append('Missing readback action reference: '+run['eventsPath'])
        predicates = [a for a in run['actions'] if a.get('predicateClassification')]
        completed_reads = sum(status.startswith('completed_') for status in annotation.get('stateReadbackStatusByLine',{}).values())
        if len(predicates) != run['explicitPredicateToolCalls'] or completed_reads != run['completedReviewedStateReadbacks']:
            errors.append('Semantic count mismatch: '+run['eventsPath'])
        if sum(a.get('exitCode')==0 for a in predicates) != run['predicateZeroExit']:
            errors.append('Semantic zero-exit count mismatch: '+run['eventsPath'])
projection_path = REPO/'scripts/evidence/CL11-projection-review.json'
projection_verified = False
if projection_path.exists():
    projection = json.loads(projection_path.read_text(encoding='utf-8'))
    for finding in projection['findings']:
        path = (REPO/'scripts/evidence/cl11'/PurePosixPath(finding['resultPath']).relative_to('.agent_control/cl11')).resolve()
        if not path.is_relative_to(REPO/'scripts/evidence/cl11'):
            raise ValueError('Outside projection source scope')
        run = json.loads(path.read_text(encoding='utf-8'))
        action = run['actions'][finding['actionIndex']]
        rendered = (action.get('result') or {}).get('text','')
        if (digest(path) != finding['resultSha256'] or
            hashlib.sha256(rendered.encode('utf-8')).hexdigest() != finding['renderedTextSha256'] or
            action.get('proposal') != finding['proposal'] or
            len(re.findall(r'\[id=\d+\b',rendered)) != finding['bracketedNativeIds']):
            errors.append('Projection defect evidence mismatch: '+finding['resultPath'])
    if (len(projection['findings']) != projection['affectedActions'] or
        len({r['resultPath'] for r in projection['findings']}) != projection['affectedRuns']):
        errors.append('Projection defect count mismatch')
    projection_verified = True
result = {'allPassed': not errors, 'cohort': cohort.name, 'files': len(rows),
          'scheduled': len(expected), 'observed': len(actual_rows), 'errors': errors,
          'indexSha256': digest(index_path), 'semanticRunsVerified':semantic_runs,
          'projectionDefectEvidenceVerified':projection_verified,
          'semanticScope':'Source bytes, visible action inputs/results, line references and count consistency verified; selected semantic claims also inspected by lead. This does not infer understanding from outcomes.'}
(REPO / 'scripts/evidence/CL11-integrity.json').write_text(
    json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(result))
raise SystemExit(0 if not errors else 1)
