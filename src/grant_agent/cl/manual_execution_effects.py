"""Fresh manual-run effects and exact compiler/recovery provenance admission."""
from __future__ import annotations
import json
import re
from copy import deepcopy

from .creative_effects import _owned
from .effects import _call, _measure_file

SUPPORTED = {'neyvia.manual.run', 'neyvia.manual.compile', 'neyvia.manual.script.run',
             'neyvia.manual.recovery.bind', 'neyvia.manual.recover'}


def readonly(name, args):
    return False if name in SUPPORTED else None


def _root(protocol):
    return _owned(protocol, protocol.gateway.root / '.neyvia')


def _file(protocol, folder, identity, width):
    if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{' + str(width) + '}', identity):
        raise ValueError('Invalid retained manual artifact identity')
    return _owned(protocol, _root(protocol) / folder / (identity + '.json'))


def _read(path):
    _measure_file(path)
    raw = path.read_bytes()
    saved = json.loads(raw)
    if raw != (json.dumps(saved, ensure_ascii=False, indent=2) + '\n').encode('utf-8'):
        raise ValueError('Manual artifact is not exact owning atomic JSON')
    return saved


def _service(protocol):
    from ..neyvia_workspace_tools import workspace_for
    return workspace_for(protocol.gateway.root)


def _manual(protocol, identity):
    from ..neyvia_manuals import get_manual, validate
    _, digest, data = get_manual(identity, _root(protocol))
    validate(data, protocol.gateway.native)
    return digest, data


def _verify_plan(protocol, plan):
    from .. import manual_compiler as owner
    from ..neyvia_manuals import chapter_entry
    root = _root(protocol)
    digest, data = _manual(protocol, plan['id'])
    if digest != plan['sha256']:
        return False
    chapter_name, chapter, procedure = chapter_entry(data, plan['chapter'], 'procedures', plan['procedure'])
    events = owner._events(root)
    traces = []
    for row in plan['sourceRuns']:
        trace = owner._verified_trace(root, events[row['runId']], data, chapter_name, chapter,
                                      plan['procedure'], procedure, digest, protocol.gateway.native)
        if trace['evidenceSha256'] != row['evidenceSha256'] or trace['inputSha256'] != plan['inputSha256']:
            return False
        traces.append(trace)
    return owner._plan(data, chapter_name, plan['procedure'], procedure, digest, traces, plan['minRuns']) == plan


def _target(protocol, name, args):
    from ..manual_compiler import _load_plan
    from ..manual_recovery import failed_run, signature
    if name == 'neyvia.manual.script.run':
        plan = _load_plan(_service(protocol), args['scriptId'])
        if not _verify_plan(protocol, plan):
            raise ValueError('Compiled provenance is no longer verified')
        return plan['id'], plan['chapter'], plan['procedure'], plan
    if name in {'neyvia.manual.recovery.bind', 'neyvia.manual.recover'}:
        failure_path = _file(protocol, 'manual-runs', args['runId'], 32)
        failure = failed_run(_root(protocol), args['runId'])
        if name.endswith('.bind'):
            return failure['id'], args['chapter'], args['procedure'], {'failure': failure, 'failureFile': _measure_file(failure_path)}
        recipe = _read(_file(protocol, 'manual-recoveries', args['recipeId'], 32))
        if recipe['failureSignature'] != signature(failure) or recipe['id'] != failure['id'] or recipe['sha256'] != failure['sha256']:
            raise ValueError('Recovery provenance does not match the original failure')
        return recipe['id'], recipe['chapter'], recipe['procedure'], {'failure': failure, 'recipe': recipe, 'failureFile': _measure_file(failure_path)}
    return args['id'], args.get('chapter'), args['procedure'], None


def snapshot_for(protocol, name, args):
    from ..neyvia_manuals import chapter_entry, resolve
    identity, chapter_name, procedure_name, source = _target(protocol, name, args)
    digest, data = _manual(protocol, identity)
    chapter_name, chapter, procedure = chapter_entry(data, chapter_name, 'procedures', procedure_name)
    # A schema-valid action receipt alone cannot prove nested writes. Every
    # potentially mutating step must have an executable authored verifier.
    for step in procedure['steps']:
        if 'action' not in step:
            continue
        action = chapter['actions'][step['action']]
        if protocol._mutating(action['tool'], step['args']) and not step.get('check'):
            raise ValueError('Manual CL effect needs an authored verifier on every nested mutation')
    runs = _root(protocol) / 'manual-runs'
    return {'id': identity, 'sha256': digest, 'chapter': chapter_name, 'procedure': procedure_name,
            'source': deepcopy(source), 'runs': {p.stem: _measure_file(p) for p in runs.glob('*.json')},
            'recipes': {p.stem: _measure_file(p) for p in (_root(protocol) / 'manual-recoveries').glob('*.json')},
            'inputs': deepcopy(args.get('inputs'))}


def _verify_run(protocol, value, previous, args, compiled=None):
    from ..neyvia_manuals import chapter_entry, expect, resolve
    from ..manual_compiler import _events, _verified_trace
    saved = _read(_file(protocol, 'manual-runs', value.get('runId'), 32))
    if (args.get('runId') and args['runId'] != saved['runId'] or
            not args.get('runId') and saved['runId'] in previous['runs']):
        return False
    if saved.get('status') != 'completed' or value.get('status') != 'completed':
        return False
    if any(saved.get(key) != previous[key] for key in ('id', 'sha256', 'chapter', 'procedure')):
        return False
    if any(value.get(key) != item for key, item in saved.items()):
        return False
    digest, data = _manual(protocol, saved['id'])
    if digest != saved['sha256']:
        return False
    chapter_name, chapter, procedure = chapter_entry(data, saved['chapter'], 'procedures', saved['procedure'])
    if saved['nextStep'] != len(procedure['steps']):
        return False
    events = _events(_root(protocol))[saved['runId']]
    if compiled is None:
        _verified_trace(_root(protocol), events, data, chapter_name, chapter, saved['procedure'], procedure, digest, protocol.gateway.native)
    else:
        if saved.get('compiledArtifactId') != compiled['scriptId'] or not _verify_plan(protocol, compiled):
            return False
        if not events or events[0]['event'] != 'start' or events[-1]['event'] != 'completed' or any(
                row.get('runId') != saved['runId'] or row.get('sha256') != digest or row.get('compiledArtifactId') != compiled['scriptId'] for row in events):
            return False
    if 'inputs' in args and saved['inputs'] != args['inputs']:
        return False
    verified = 0
    for number, step in enumerate(procedure['steps']):
        if 'action' not in step or step.get('when') and saved['decisions'].get(step['when']['judge']) != step['when']['option']:
            continue
        action = chapter['actions'][step['action']]
        arguments = resolve(step['args'], saved['inputs'], saved['results'], protocol.gateway.root)
        if not step.get('check'):
            if protocol._mutating(action['tool'], arguments):
                return False
            continue
        check = chapter['checks'][step['check']]
        check_args = resolve(check['args'], saved['inputs'], saved['results'], protocol.gateway.root)
        if protocol._mutating(check['tool'], check_args):
            return False
        fresh = _call(protocol, check['tool'], check_args)
        if not expect(fresh, check['expect'], saved['inputs'], saved['results'], protocol.gateway.root):
            return False
        if not any(row.get('step') == number and row.get('check') == step['check'] and row.get('passed') is True for row in saved['checks']):
            return False
        verified += 1
    return verified > 0


def _verify(protocol, name, args, value, previous):
    if not isinstance(value, dict) or not isinstance(previous, dict):
        return False
    if name == 'neyvia.manual.compile':
        from ..manual_compiler import _load_plan, digest
        plan = _load_plan(_service(protocol), value.get('scriptId'))
        if any(value.get(key) != item for key, item in plan.items()) or not _verify_plan(protocol, plan):
            return False
        observed = _call(protocol, 'neyvia.manual.compiled', {'id': previous['id']})
        return (any(row == {**plan, 'stale': False} for row in observed['scripts']) and
                plan['id'] == previous['id'] and plan['sha256'] == previous['sha256'] and
                plan['chapter'] == previous['chapter'] and plan['procedure'] == previous['procedure'] and
                plan['minRuns'] == args.get('minRuns', 3) and
                ('inputs' not in args or plan['inputSha256'] == digest(args['inputs'])))
    if name == 'neyvia.manual.recovery.bind':
        from ..manual_recovery import signature
        recipe = _read(_file(protocol, 'manual-recoveries', value.get('recipeId'), 32))
        failure = previous['source']['failure']
        return (recipe['recipeId'] not in previous['recipes'] and recipe == {k: v for k, v in value.items() if k != 'ok'} and
                recipe['failureSignature'] == signature(failure) and recipe['sourceRunId'] == args['runId'] and
                recipe['id'] == previous['id'] and recipe['sha256'] == previous['sha256'] and
                recipe['chapter'] == previous['chapter'] and recipe['procedure'] == previous['procedure'] and
                recipe['inputs'] == args['inputs'] and recipe.get('scopeTools') == failure.get('scopeTools') and
                recipe['status'] == 'bound' and _measure_file(_file(protocol, 'manual-runs', args['runId'], 32)) == previous['source']['failureFile'])
    if name == 'neyvia.manual.recover':
        recipe = _read(_file(protocol, 'manual-recoveries', args['recipeId'], 32))
        before = previous['source']['recipe']
        if (any(recipe.get(k) != v for k, v in before.items() if k not in {'attempts', 'status', 'recoveryRunId'}) or
                recipe.get('status') != 'verified' or recipe.get('recoveryRunId') != value.get('runId') or
                recipe.get('attempts', {}).get(args['runId']) != {'status': 'completed', 'runId': value.get('runId')} or
                value.get('recipeId') != args['recipeId'] or value.get('recoveredFailureRunId') != args['runId'] or
                _measure_file(_file(protocol, 'manual-runs', args['runId'], 32)) != previous['source']['failureFile']):
            return False
        replay = before.get('attempts', {}).get(args['runId'], {}).get('runId')
        return _verify_run(protocol, value, previous, {'inputs': recipe['inputs'], **({'runId': replay} if replay else {})})
    compiled = previous['source'] if name == 'neyvia.manual.script.run' else None
    return _verify_run(protocol, value, previous, args, compiled)


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    if name == 'neyvia.manual.compile' and protocol.scope is not None and 'neyvia.manual.compiled' not in protocol.scope:
        return []
    def check(arguments, value, previous):
        try:
            return _verify(protocol, name, arguments, value, previous)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subjectKey': 'manual-execution:' + name,
             'bindSubject': lambda arguments, value, previous: 'manual-artifact:' + str(value.get('scriptId') or value.get('recipeId') or value.get('runId')),
             'observerTool': 'neyvia.manual.compiled' if name.endswith('.compile') else 'owned-manual-artifact-and-authored-checks',
             'subject': deepcopy(args),
             'expectation': 'Fresh exact durable artifact, current manual/source cohorts and authored effect verifiers agree',
             'check': check}]
