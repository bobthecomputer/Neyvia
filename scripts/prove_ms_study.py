"""Real note -> Luna/T14 -> reviewed pack proof, with retained measured usage.

No provider mock, invented source, hidden route replacement or pytest runner.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.neyvia_scroll import call, load, stats, logger
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.scroll_generation import generate_cards
from grant_agent.scroll_pack import read_scrollpack
from grant_agent.scroll_pack import validate_pack


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def mutation_checks(pack, sources):
    cases = {}
    unnamed = copy.deepcopy(pack)
    unnamed['meta'].pop('studyFormat')
    cases['mathsMissingDefaultFormat'] = (unnamed, 'schema')
    missing = copy.deepcopy(pack)
    missing['cards'].remove(next(c for c in missing['cards'] if c['type'] == 'when'))
    cases['missingPart'] = (missing, 'seven-part')
    invented = copy.deepcopy(pack)
    next(c for c in invented['cards'] if c['type'] == 'course_example')['courseQuote'] = 'Invented course example'
    cases['inventedCourseExample'] = (invented, 'course-example')
    unchanged = copy.deepcopy(pack)
    variant = next(c for c in unchanged['cards'] if c['type'] == 'exercise_variant')
    variant['front'] = next(c['front'] for c in unchanged['cards'] if c['id'] == variant['variantOf'])
    cases['unchangedVariation'] = (unchanged, 'exercise-variant')
    unchecked = copy.deepcopy(pack)
    next(c for c in unchecked['cards'] if c['type'] == 'your_exercise')['answerCheck']['ok'] = False
    cases['rejectedIndependentSolution'] = (unchecked, 'answer-check')
    result = {}
    for name, (candidate, rule) in cases.items():
        validation = validate_pack(candidate, sources)
        result[name] = {'ok': not validation['ok'] and any(e['rule'] == rule for e in validation['errors']),
                        'errors': validation['errors']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--note', type=Path, default=REPO / 'scripts/fixtures/ms-chain-rule-course.md')
    parser.add_argument('--pack', default='ms-course')
    parser.add_argument('--output', type=Path, default=REPO / 'scripts/evidence/MS-runs/study')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--regenerate', action='store_true', help='Run a fresh generation job using exact validated T14 replay when available')
    args = parser.parse_args()
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0')
    root, output = args.root.resolve(), args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    service = workspace_for(root)
    receipt = {'schema': 'neyvia.ms.study-proof.v1', 'root': str(root), 'pack': args.pack,
               'note': str(args.note.resolve()), 'noteSha256': hashlib.sha256(args.note.read_bytes()).hexdigest(),
               'source': ['https://openstax.org/books/calculus-volume-1/pages/3-3-differentiation-rules',
                          'https://openstax.org/books/calculus-volume-1/pages/3-6-the-chain-rule'],
               'checks': {}, 'limitations': ['This run proves pack generation and validator behavior; browser feedback and real retention need separate proof.',
                                             'Dollar cost is unknown without an authoritative configured price; observed token and time cost remain measured.']}
    started = time.monotonic()
    def perform(op, values):
        result = call(service, 'scroll.' + op, values)
        write(output / (op + '.json'), result)
        return result
    perform('import', {'paths': [str(args.note.resolve())], 'packId': args.pack, 'title': 'Differentiation: OpenStax course note', 'subject': 'math'})
    row = load(root, args.pack)
    if not args.resume or not row['value'].get('concepts'):
        perform('concepts', {'pack': args.pack})
    row = load(root, args.pack)
    if args.regenerate or not args.resume or not row['value'].get('cards'):
        request = 'seven-part-' + str(int(time.time()))
        perform('generate', {'pack': args.pack, 'requestId': request})
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            progress = perform('job', {'requestId': request})
            status = progress['job']['state']
            print(json.dumps({'job': request, 'state': status, 'stage': progress['job']['stage'], 'progress': progress['job']['progress']}), flush=True)
            if status in {'completed', 'failed'}:
                break
            time.sleep(10)
        if status != 'completed':
            raise RuntimeError('Real generation did not complete: ' + json.dumps(progress))
    row = load(root, args.pack)
    validation = perform('validate', {'pack': args.pack})
    if not validation['ok']:
        raise RuntimeError('Real generated pack failed validation: ' + json.dumps(validation))
    # A pending card always blocks exporting, even when the schema is valid.
    try:
        call(service, 'scroll.pack', {'pack': args.pack})
    except ValueError as error:
        receipt['checks']['pendingExportBlocked'] = 'Review every card' in str(error)
    flagged = [c['id'] for c in row['value']['cards'] if c.get('flag')]
    if flagged:
        raise RuntimeError('Independent review flagged cards; retained for real resolution: ' + ', '.join(flagged))
    perform('review', {'pack': args.pack, 'decisions': [{'cardId': c['id'], 'action': 'approve'} for c in row['value']['cards']]})
    exported = perform('pack', {'pack': args.pack})
    archived, texts = read_scrollpack(Path(exported['path']))
    receipt['checks'].update(archiveRoundtrip=archived['meta']['studyFormat'] == 'paul-seven-part.v1',
                            exactSources=texts == row['sources']['source_texts'],
                            independentlyCheckedExercises=all(c.get('answerCheck', {}).get('ok') is True for c in archived['cards'] if c['type'] in {'your_exercise', 'exercise_variant'}))
    write(output / 'pack.json', archived)
    write(output / 'sources.json', texts)
    rejected = mutation_checks(archived, texts)
    write(output / 'validator-adverse-cases.json', rejected)
    receipt['checks']['adverseCasesRejected'] = all(case['ok'] for case in rejected.values())
    # Exact repeat replays T14 memory/cache and revalidates every candidate.
    repeat_rows = []
    repeated = generate_cards(root, row['value'], row['sources'], {}, 'ms-exact-replay', repeat_rows.append)
    receipt['checks']['warmNoModelCalls'] = not any(r['tier'] in {'small', 'big'} for r in repeat_rows)
    receipt['checks']['warmSameCards'] = [(c['id'], c.get('back'), c['body']) for c in repeated['cards']] == [(c['id'], c.get('back'), c['body']) for c in row['value']['cards']]
    write(output / 'warm-generation.json', repeat_rows)
    observed = perform('stats', {'pack': args.pack})
    preview = perform('preview', {'pack': args.pack})
    receipt.update(cards=len(archived['cards']), concepts=len(archived['concepts']), stats=observed,
                   elapsedMs=round((time.monotonic()-started)*1000, 3), preview=preview)
    receipt['ok'] = validation['ok'] and all(receipt['checks'].values())
    write(output / 'proof.json', receipt)
    print(json.dumps({'ok': receipt['ok'], 'cards': receipt['cards'], 'concepts': receipt['concepts'], 'costPerCard': observed['costPerCard'], 'proof': str(output/'proof.json')}), flush=True)
    if not receipt['ok']:
        raise RuntimeError('One or more mechanism checks failed')


if __name__ == '__main__':
    main()
