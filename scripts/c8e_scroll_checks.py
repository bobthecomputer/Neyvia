"""Authored untrusted pack inputs for the real no-inference validator journey.

These are input fixtures, never generated cards, provider results or approval
receipts. The production importer hashes the source; its existing store owner
saves the explicitly authored cards. All validation calls use the gateway.
"""
import copy
import hashlib
import json
from pathlib import Path


def prepare(worker, inputs, root):
    from grant_agent import neyvia_scroll as store
    root = Path(root)
    source = root / 'c8/authored-study.txt'
    text = 'A checksum identifies the exact bytes of a file. Changing one byte changes its checksum.'
    source.write_text(text, encoding='utf-8')
    created = worker.tool('neyvia.scroll.import', {'paths': [str(source)],
                          'packId': 'c8e-authored-validation', 'title': 'Authored validator input',
                          'subject': 'files'})
    inputs['pack'] = created['pack']['meta']['id']
    row = store.load(root, inputs['pack'])
    document = row['value']['sources'][0]['id']
    row['value']['concepts'] = [{'id': 'checksum', 'name': 'Checksum', 'chapter': 'files',
        'subject': 'files', 'prereqs': [], 'kind': 'term', 'definition': text}]
    base = {'subject': 'files', 'chapter': 'files', 'difficulty': .2, 'seconds': 15, 'lang': 'en',
            'source': {'doc': document, 'span': [0, len(text)]},
            'provenance': {'stage': 'explicit-authored-fixture', 'tier': 'script',
                           'runId': worker.args.run_id}, 'status': 'draft'}
    row['value']['cards'] = [
        {**copy.deepcopy(base), 'id': 'checksum.fact.01', 'type': 'fact', 'body': text,
         'concepts': {'teaches': ['checksum'], 'requires': [], 'tests': []}},
        {**copy.deepcopy(base), 'id': 'checksum.flashcard.01', 'type': 'flashcard',
         'body': 'What identifies the exact bytes of a file?', 'front': 'What identifies exact file bytes?',
         'back': 'A checksum.', 'explanation': 'The imported note says a checksum identifies the exact bytes.',
         'concepts': {'teaches': [], 'requires': ['checksum'], 'tests': ['checksum']}}]
    row['value']['generation'] = {'run': 'explicit-authored-fixture-no-inference', 'costs': {}}
    store.save(root, row)
    fixture = root / 'c8/authored-validator-input.json'
    fixture.write_text(json.dumps(row['value'], indent=2) + '\n', encoding='utf-8')
    worker.step_results['authoredValidatorInput'] = {'path': str(fixture),
        'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'generated': False, 'providerCalls': 0, 'approvalGranted': False}


def check(worker, inputs, root):
    from grant_agent import neyvia_scroll as store
    root = Path(root)
    valid = store.load(root, inputs['pack'])['value']
    checks = []
    for identity, edit, rule in (
        ('source-hash', lambda value: value['sources'][0].update(sha256='0' * 64), 'source-hash'),
        ('source-span', lambda value: value['cards'][0]['source'].update(span=[0, 100000]), 'source-span'),
        ('cycle', lambda value: value['concepts'][0].update(prereqs=['checksum']), 'dag'),
        ('graded-overlap', lambda value: value['cards'][1]['concepts'].update(teaches=['checksum']), 'graded-overlap')):
        row = store.load(root, inputs['pack']); row['value'] = copy.deepcopy(valid)
        edit(row['value']); store.save(root, row)
        try:
            reply = worker.tool('neyvia.scroll.validate', {'pack': inputs['pack']})
        except Exception as error:
            wire = getattr(error, 'reply', worker.calls[-1] if worker.calls else {})
            if not isinstance(wire, dict) or wire.get('httpStatus') != 200:
                raise
            reply = wire.get('body', {}).get('data', {})
            while isinstance(reply, dict) and 'tool' in reply and isinstance(reply.get('result'), dict):
                reply = reply['result']
            if not isinstance(reply, dict) or reply.get('ok') is not False or not isinstance(reply.get('errors'), list):
                raise
        persisted = json.loads((root / '.neyvia/scroll' / inputs['pack'] / 'last-validation.json').read_text())
        checks.append({'id': 'c8e.scroll.' + identity + '-rejected', 'passed': reply.get('ok') is False
                       and any(error['rule'] == rule for error in reply['errors']) and persisted == reply,
                       'fresh': True, 'observed': reply, 'boundary': 'production-state'})
    row = store.load(root, inputs['pack']); row['value'] = valid; store.save(root, row)
    restored = worker.tool('neyvia.scroll.validate', {'pack': inputs['pack']})
    checks.append({'id': 'c8e.scroll.valid-input-restored', 'passed': restored.get('ok') is True
                   and not restored['errors'], 'fresh': True, 'observed': restored,
                   'boundary': 'Actual authored input validation; no generation or provider proof'})
    if not all(row['passed'] for row in checks):
        raise RuntimeError('Real Scroll validator effect checks failed: ' + json.dumps(checks))
    return checks
