"""Fresh owner checks for workspace setup, dictation policy and script extraction."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time

from .effects import _file, _measure_file

SUPPORTED = {'neyvia.onboarding.save', 'neyvia.dictation.names',
             'neyvia.dictation.process', 'neyvia.efficiency.extract'}


def readonly(name, args):
    if name in {'neyvia.onboarding.recommend', 'neyvia.efficiency.metrics',
                'neyvia.efficiency.transitions', 'neyvia.impact', 'neyvia.time.budget'}:
        return True
    if name in {'neyvia.onboarding.base_pack', 'neyvia.onboarding.pack'}:
        return args.get('action', 'status') == 'status'
    if name == 'neyvia.dictation.names':
        return args.get('action', 'list') == 'list'
    if name == 'neyvia.dictation.process':
        return args.get('final', True) is False
    return None


def _dictionary(protocol):
    from ..neyvia_dictation import _read_policy
    return _read_policy(protocol.gateway.root, 'names', {})


def _history(protocol):
    from ..neyvia_dictation import _read_policy
    return _read_policy(protocol.gateway.root, 'history', [])


def _prompt(protocol, args):
    from ..neyvia_dictation import language_history, _name_map
    from ..neyvia_prompt_dictation import process_prompt
    answer = process_prompt(args['text'], language_history(protocol.gateway.root),
        args.get('final', True) is not False, _name_map(protocol.gateway.root))
    return answer


def _source(protocol, args):
    from ..neyvia_efficiency import canonical, pointer, unique_object, reject_constant
    if args.get('strategy', 'cascade') != 'cascade' or args.get('useScript', True) is not True:
        raise ValueError('CL extraction currently proves only the exact script cascade; model routes remain frontier')
    observed = _file(protocol, args['path'])
    if observed.get('kind') != 'file' or observed['bytes'] > 64 * 1024:
        raise ValueError('Extraction needs a complete local JSON file of at most 64 KiB')
    path = Path(observed['path'])
    parsed = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return {'source': observed, 'answer': {'valueJson': canonical(pointer(parsed, args['field'])),
        'sourceSha256': observed['sha256']}}


def snapshot_for(protocol, name, args):
    if name == 'neyvia.onboarding.save':
        from ..neyvia_onboarding import read_state
        return deepcopy(read_state(protocol.gateway.root))
    if name == 'neyvia.dictation.names':
        return deepcopy(_dictionary(protocol))
    if name == 'neyvia.dictation.process':
        answer = _prompt(protocol, args)
        if answer.get('route') == 'qwen':
            raise ValueError('French/mixed processing requires a separately admitted local engine observation')
        return {'history': deepcopy(_history(protocol)), 'answer': answer, 'started': time.time()}
    if name == 'neyvia.efficiency.extract':
        return _source(protocol, args)
    return None


def _save(protocol, args, value, before):
    from ..neyvia_onboarding import _dir, _strings, read_state
    expected = deepcopy(before)
    for key in ('interests', 'apps', 'packs'):
        if key in args:
            expected[key] = _strings(args[key], key)
    for key in ('tier', 'runtime'):
        if key in args:
            expected[key] = str(args[key] or '')
    if 'completed' in args:
        expected['completed'] = bool(args['completed'])
    fresh = read_state(protocol.gateway.root)
    stored = json.loads((_dir(protocol.gateway.root) / 'state.json').read_bytes())
    expected.update(firstRun=False, updatedAt=stored.get('updatedAt'))
    return (bool(stored.get('updatedAt')) and fresh == expected and
        stored == {key:item for key,item in expected.items() if key != 'firstRun'} and value.get('state') == fresh)


def _names(protocol, args, value, before):
    from ..neyvia_prompt_dictation import BUILTIN_NAMES
    from ..neyvia_dictation import names
    canonical = str(args.get('to') or '').strip()
    canonical = next((key for key in BUILTIN_NAMES if key.casefold() == canonical.casefold()), canonical)
    aliases = args.get('from') or []
    aliases = [aliases] if isinstance(aliases, str) else aliases
    aliases = [key.casefold().strip() for key in aliases]
    expected = deepcopy(before)
    if args.get('action', 'list') == 'add':
        expected[canonical] = sorted(set(expected.get(canonical, [])) | set(aliases))
    elif canonical in expected:
        expected[canonical] = [key for key in expected[canonical] if key not in aliases]
        if not expected[canonical]:
            del expected[canonical]
    return _dictionary(protocol) == expected and names(protocol.gateway.root, {'action':'list'}) == value


def _process(protocol, args, value, before):
    answer = before['answer']
    if any(value.get(key) != item for key,item in answer.items()):
        return False
    rows = _history(protocol)
    if args.get('final', True) is False:
        return rows == before['history']
    if answer['language'] not in {'en','fr','mixed'}:
        return rows == before['history'] and value.get('stable') == answer['text'] and value.get('provisional') == ''
    return (bool(rows) and rows[:-1] == before['history'][-19:] and
        rows[-1].get('language') == answer['language'] and
        isinstance(rows[-1].get('at'), (int,float)) and before['started'] <= rows[-1]['at'] <= time.time() and
        value.get('stable') == answer['text'] and value.get('provisional') == '')


def _extraction(protocol, args, value, before):
    if _source(protocol, args) != before or value.get('answer') != before['answer']:
        return False
    base = Path(protocol.gateway.root).resolve() / '.neyvia/efficiency'
    receipt_path = Path(value['receiptPath']).resolve()
    receipt_path.relative_to(base / 'receipts')
    final = json.loads(receipt_path.read_bytes())
    validation_path = Path(final['validationReceiptPath']).resolve()
    validation_path.relative_to(base / 'receipts')
    validated = json.loads(validation_path.read_bytes())
    cache = json.loads((base / 'cache.json').read_bytes())
    telemetry = json.loads((base / 'latency.json').read_bytes())
    row = cache[final['key']]
    _measure_file(validation_path)
    # Cache digest binds canonical owner JSON, rather than formatted file bytes.
    from ..transition_memory import digest as canonical_digest
    source_name = Path(before['source']['path']).relative_to(Path(protocol.gateway.root).resolve()).as_posix()
    return (final.get('status') == 'completed' and final.get('route') == 'script' and
        final.get('modelCalls') == [] and final.get('answer') == before['answer'] and
        final.get('preconditions') == {'path':source_name, 'sourceSha256':before['source']['sha256'], 'field':args['field']} and
        validated.get('answer') == before['answer'] and row.get('answer') == before['answer'] and
        row.get('receiptPath') == str(validation_path) and row.get('sha256') == canonical_digest(validated) and
        any(item.get('key') == final['key'] and item.get('route') == 'script' and item.get('status') == 'completed' for item in telemetry) and
        value.get('route') == 'script' and value.get('modelCalls') == [])


def checks_for(protocol, name, args):
    if name not in SUPPORTED or readonly(name, args):
        return []
    verify = {'neyvia.onboarding.save':_save, 'neyvia.dictation.names':_names,
              'neyvia.dictation.process':_process, 'neyvia.efficiency.extract':_extraction}[name]
    def check(arguments, value, previous):
        try:
            return verify(protocol, arguments, value, previous)
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return [{'name':'effect-' + name.removeprefix('neyvia.').replace('.','-'),
        'observer':True,'effect':True,'subject':deepcopy(args),
        'subjectKey':name + ':' + str(args.get('path') or args.get('to') or 'workspace'),
        'observerTool':'configuration-owner-state',
        'expectation':'Fresh owner state preserves unrelated fields and contains exactly the requested effect',
        'check':check}]
