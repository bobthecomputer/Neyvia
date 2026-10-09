"""Commit-sized CL11 receipts: raw transcripts, integrity index, aggregate proof."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'src'))
from grant_agent.cl.benchmark11 import ensure_frozen

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8', newline='\n')

def export_file(job):
    path, destination = job
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_digest = digest(path)
    destination_digest = digest(destination) if destination.exists() else None
    if destination_digest != source_digest:
        shutil.copyfile(path, destination)
        destination_digest = digest(destination)
    if source_digest != destination_digest:
        raise RuntimeError('Evidence byte mismatch: '+str(destination))
    return {'path':destination.relative_to(REPO).as_posix(), 'sha256':source_digest,
            'bytes':destination.stat().st_size, 'source':path.relative_to(REPO).as_posix()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',choices=('scored-1','scored-2'),default='scored-1')
    parser.add_argument('--implementation-commit',default='2b662f0')
    args = parser.parse_args()
    target = REPO/'scripts/evidence/cl11'
    index = []
    jobs = []
    cohorts = ('dev-1','dev-2','dev-3','dev-4','scored-1','scored-2')
    journey_dirs = ('answer-proof','provenance-probe','native-observer-probe','data-probe','recovery','procedure-proof')
    for name in (*cohorts,'task-review','visual-cache',*journey_dirs):
        origin = REPO/'.agent_control/cl11'/name
        if not origin.exists():
            continue
        for path in sorted(origin.rglob('*')):
            if not path.is_file():
                continue
            relative = path.relative_to(origin)
            # Fixture source is reproducible from the frozen generator. Keep
            # observed UI/server receipts and actual image artifacts as proof.
            if name in journey_dirs:
                keep = path.name in {'events.jsonl','prompt.txt','answer.txt','stderr.txt','receipt.json',
                                     'window.json','web-record.json','final.png'} or path.suffix in {'.png','.gif'}
            elif 'fixture' in relative.parts:
                keep = path.name in {'window.json','web-record.json','final.png','native.stderr'} or path.suffix in {'.png','.gif'}
            else:
                keep = path.suffix in {'.json','.jsonl','.txt','.md','.png','.gif'}
            if not keep:
                continue
            destination = target/name/relative
            jobs.append((path, destination))
    # Each destination is disjoint. Preserve deterministic ordering while
    # overlapping Windows file-open latency; every copy still gets byte-hashed.
    with ThreadPoolExecutor(max_workers=8) as pool:
        index.extend(pool.map(export_file, jobs))
    proofs = {}
    for path in sorted((REPO/'scripts/evidence').glob('CL11-*.json')):
        # Verify the final index after sealing. Do not label an older index's
        # integrity result as a journey of this cohort or create a hash cycle.
        if path.name == 'CL11-integrity.json':
            continue
        destination = target/'journeys'/args.cohort/path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path,destination)
        value = json.loads(path.read_text(encoding='utf-8'))
        proofs[path.name] = {'allPassed':value.get('allPassed'), 'checks':value.get('checks'),
                             'cohort':value.get('cohort'), 'scope':value.get('scope'),
                             'observedFlags':{key:value[key] for key in ('preservedBusinessIdentifier',
                                  'unobservedCompletionAccepted','forgedReceiptAccepted') if key in value},
                             'receipt':destination.relative_to(REPO).as_posix(), 'sha256':digest(destination)}
        index.append({'path':destination.relative_to(REPO).as_posix(), 'sha256':digest(destination),
                      'bytes':destination.stat().st_size, 'source':path.relative_to(REPO).as_posix()})
    scored = REPO/'.agent_control/cl11'/args.cohort
    manifest = json.loads((scored/'manifest.json').read_text(encoding='utf-8'))
    ensure_frozen(manifest)
    results = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(scored.glob('task-*/*/*/rep-*/result.json'))]
    expected = {(row['task'],row['model'],row['arm'],row['repetition']) for row in manifest['schedule']}
    actual = {(row['task'],row['model'],row['arm'],row['repetition']) for row in results}
    summary = json.loads((scored/'summary.json').read_text(encoding='utf-8'))
    # Earlier proof artifacts remain immutable even when the current journey
    # receipts have been replayed. Include those retained bytes in this index.
    indexed = {row['path'] for row in index}
    for path in sorted((target/'journeys').rglob('*.json')):
        relative = path.relative_to(REPO).as_posix()
        if relative not in indexed:
            index.append({'path':relative, 'sha256':digest(path), 'bytes':path.stat().st_size,
                          'source':'retained local evidence commit'})
    index.sort(key=lambda row: row['path'])
    write(target/'index.json',index)
    benchmarks = {}
    for name in ('scored-1','scored-2'):
        summary_path = target/name/'summary.json'
        if summary_path.exists():
            old = json.loads(summary_path.read_text(encoding='utf-8'))
            benchmarks[name] = {'completed':old['completed'], 'expected':old['expected'],
                                'gates':old['gates'], 'invalid':old['invalid'],
                                'summary':summary_path.relative_to(REPO).as_posix(),
                                'originalLocalEvidenceCommit':'6a644511' if name == 'scored-1' else None}
    receipt = {'schema':'neyvia.cl11.end-to-end.v1', 'implementationCommits':list(dict.fromkeys(['1cc4f8c','2b662f0',args.implementation_commit])),
               'journeys':proofs, 'benchmark':{'expected':len(expected), 'observed':len(actual),
               'missingSlots':sorted(expected-actual), 'extraSlots':sorted(actual-expected),
               'frozenInputsVerified':True, 'gates':summary['gates'], 'invalid':summary['invalid'],
               'cohort':args.cohort, 'report':'docs/evidence/cl-benchmark-1.1.md', 'manifest':f'scripts/evidence/cl11/{args.cohort}/manifest.json',
               'summary':f'scripts/evidence/cl11/{args.cohort}/summary.json'},
               'rawEvidence':{'index':'scripts/evidence/cl11/index.json', 'sha256':digest(target/'index.json'),
                              'files':len(index), 'bytes':sum(row['bytes'] for row in index)},
               'benchmarks':benchmarks,
               'designAssumption':'The design marks nine tasks with a star but asks for ten native tasks; task 14 is the disclosed tenth.',
               'visualInspection':[{'task':9, 'arm':'b', 'model':'gpt-6.1-sol', 'repetition':1,
                                   'observed':'Actual native app textbox INITIAL / checked and label Applied: INITIAL / checked; screenshot inspected by lead.',
                                   'scope':'Disposable real Windows Forms app, production CUA driver; no public/native production availability claim.'},
                                   {'task':13, 'arm':'b', 'model':'gpt-6.1-sol', 'repetition':1,
                                    'observed':'Rendered table Ready rows 17 and 25, Result 42 units, status Confirmed: 42 units; screenshot inspected by lead.',
                                    'scope':'Owned local browser fixture and actual server confirmation receipt.'},
                                   {'cohort':'scored-1', 'task':22, 'arm':'claude-alone', 'model':'haiku', 'repetition':2,
                                    'observed':'Actual native screenshot shows Dispatch text 42 and Applied: 42. Raw native PowerShell events show control text and button messages; this baseline outcome was not a forged receipt.',
                                    'scope':'One inspected native baseline success; does not certify every native outcome or check/impact knowledge.'}],
               'boundaries':['Local track/cl commits only; no push, merge, NAS, credential reads or downloads.',
                             'Exact requested CLI routes without fallback; deployed weights not independently attested.',
                             'Legacy production CUA mutations without grounded observers are refused; fixture CUA proof is separately scoped.',
                             'Development cohorts and pre-repair failure receipts are retained; no scored-set tuning.']}
    if args.cohort == 'scored-2':
        receipt['visualInspection'].append({
            'cohort':'scored-2', 'task':22, 'arm':'claude-alone', 'model':'haiku', 'repetition':2,
            'observed':'Lead inspected the actual native screenshot: textbox 42 and label Applied: 42.',
            'scope':'One independently observed repaired-cohort native baseline outcome; no blanket native knowledge claim.'})
    for note in receipt['visualInspection']:
        name = note.setdefault('cohort',args.cohort)
        case = target/name/f"task-{note['task']:02d}"/note['model']/note['arm']/f"rep-{note['repetition']}"
        result = json.loads((case/'result.json').read_text(encoding='utf-8'))
        images = []
        for item in result.get('proof',[]):
            path = Path(item['path'])
            if note['task'] in {9,22} and 'frames' not in path.parts:
                continue
            relative = path.relative_to(REPO/'.agent_control/cl11'/name)
            saved = target/name/relative
            if digest(saved) != item['sha256']:
                raise RuntimeError('Inspected screenshot differs from outcome receipt: '+str(saved))
            images.append({'path':saved.relative_to(REPO).as_posix(),
                           'sha256':item['sha256']})
        if not images:
            raise RuntimeError('Inspected screenshot is absent: '+str(case))
        note['evidence'] = images
    write(REPO/'scripts/evidence/CL11.json', receipt)
    print(json.dumps({'scheduled':len(expected), 'observed':len(actual),'evidenceFiles':len(index),
                      'evidenceBytes':receipt['rawEvidence']['bytes'],'gates':summary['gates']}))

if __name__ == '__main__':
    main()
