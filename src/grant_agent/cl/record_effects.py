"""Fresh local record and frozen-artifact checks; no inferred model quality.

Persistence, declared measurements and isolated byte copies are the defining
mechanisms here. Caller reports never become independently verified evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from .creative_effects import _owned, _identity
from .effects import _measure_file

SUPPORTED = {
    'behavior.create', 'behavior.observe', 'experiment.create', 'experiment.restore',
    'experience.note', 'experience.compare', 'experience.trace', 'experience.investigate',
    'quality.instrument', 'quality.holdout', 'quality.measure', 'quality.compare',
    'quality.examine', 'quality.challenge', 'taste.correction', 'orchestration.compile',
}


def _owner_protocol(protocol, name):
    # Product runs keep durable collaboration/quality records in action_root,
    # while experiments and transcript state remain in their isolated run root.
    # Observe the same root the gateway's owning handler uses.
    if name.startswith(('quality.', 'taste.', 'experience.')):
        return SimpleNamespace(gateway=SimpleNamespace(root=getattr(
            protocol.gateway, 'work_root', protocol.gateway.root)))
    return protocol


def _path(protocol, raw):
    return _owned(protocol, Path(protocol.gateway.root) / raw)


def _json(protocol, raw):
    return json.loads(_path(protocol, raw).read_text(encoding='utf-8'))


def _files(protocol, directory):
    path = _path(protocol, directory)
    if not path.exists():
        return {}
    _measure_file(path)
    return {str(p): _measure_file(_owned(protocol, p)) for p in path.glob('*.json')}


def _quality(protocol, args):
    from ..experimental_quality import ExperimentalQuality
    return ExperimentalQuality(protocol.gateway.root, _identity(args['workId']))


def _experience(protocol, args):
    from ..experience_learning import ExperienceStore
    return ExperienceStore(protocol.gateway.root, _identity(args['workId']))


def _taste(protocol, args):
    from ..contextual_learning import ContextualLearningStore
    return ContextualLearningStore(_path(protocol, '.agent_control/contextual_learning/' +
        _identity(args['workId']) + '.json'), scope_root=protocol.gateway.root)


def _sources(protocol, paths):
    return {str(_path(protocol, value)): _measure_file(_path(protocol, value)) for value in paths}


def snapshot_for(protocol, name, args):
    protocol = _owner_protocol(protocol, name)
    if name.startswith('behavior.'):
        from ..behavioral_experiments import BehavioralExperimentLedger
        ledger = BehavioralExperimentLedger(_path(protocol, '.agent_control/behavioral_experiments.json'))
        return deepcopy(ledger._read())
    if name.startswith('experience.'):
        store = _experience(protocol, args)
        source_paths = args.get('evidence', []) if name.endswith('.note') else (
            [args['baseline'], args['candidate']] if name.endswith('.compare') else [])
        return {'files': _files(protocol, store.base), 'sources': _sources(protocol, source_paths),
                'events': store.events_path.read_text(encoding='utf-8') if store.events_path.exists() else ''}
    if name == 'taste.correction':
        payload = args['arguments']
        return {'state': deepcopy(_taste(protocol, args)._read()),
                'sources': _sources(protocol, [payload['before_path'], payload['after_path']])}
    if name.startswith('quality.'):
        store = _quality(protocol, args)
        payload = args['arguments']
        paths = ([payload['target']] if name.endswith('.measure') else
                 [payload['baseline'], payload['candidate']] if name.endswith('.compare') else
                 payload['targets'] if name.endswith('.examine') else [])
        return {'files': _files(protocol, store.base), 'sources': _sources(protocol, paths)}
    if name.startswith('experiment.'):
        from ..experiment_studio import ExperimentStudio
        store = ExperimentStudio(protocol.gateway.root)
        identity = _identity(args['experimentId'])
        _path(protocol, store.base / identity / 'manifest.json')
        if name == 'experiment.create':
            source = _path(protocol, args['source'])
            _measure_file(source)
            return {'source': str(source), 'files': store._files(source),
                    'manifestExists': (store.base / identity / 'manifest.json').exists()}
        manifest = store.inspect(identity)
        snapshot = _path(protocol, manifest['snapshot'])
        _measure_file(snapshot)
        destination = _path(protocol, '.agent_control/experiment_restores/' + _identity(args['restoreId']))
        return {'manifest': manifest, 'snapshotFiles': store._files(snapshot),
                'destination': str(destination), 'destinationExists': destination.exists()}
    if name == 'orchestration.compile':
        from ..orchestration_language import compile_neyvia_program
        plan = compile_neyvia_program(args['source'])
        output = _path(protocol, args.get('outputPath') or '.agent_control/orchestration/' + plan['planHash'] + '.json')
        return {'plan': plan, 'path': str(output)}
    return None


def _behavior_check(protocol, name, args, value, previous):
    from ..behavioral_experiments import BehavioralExperimentLedger
    current = BehavioralExperimentLedger(_path(protocol, '.agent_control/behavioral_experiments.json'))._read()
    old, new = previous['experiments'], current['experiments']
    identity = _identity(args['experimentId'])
    if name == 'behavior.create':
        if identity in old or set(new) != set(old) | {identity}:
            return False
        definition = new[identity]['definition']
        expected = {key: args[key] for key in ('experimentId', 'baselineInput', 'variantInput', 'acceptance', 'requestedRoute', 'budget')}
        return (all(new[k] == row for k, row in old.items()) and new[identity]['observations'] == []
                and all(definition.get(k) == v for k, v in expected.items()) and definition.get('seed') is None
                and value.get('experiment') == definition)
    if identity not in old or set(new) != set(old) or any(new[k] != row for k, row in old.items() if k != identity):
        return False
    before, after = old[identity], new[identity]
    rows = after['observations']
    if after['definition'] != before['definition'] or len(rows) != len(before['observations']) + 1 or rows[:-1] != before['observations']:
        return False
    row = rows[-1]
    expected = {'variant': args['variant'], 'response': args['response'], 'actualRoute': args['actualRoute'],
                'latencyMs': args.get('latencyMs'), 'cost': args.get('cost'), 'status': 'observed', 'evidenceVerified': False}
    return all(row.get(k) == v for k, v in expected.items()) and value.get('experiment') == {k: v for k, v in row.items() if k != 'evidenceHash'}


def _experience_check(protocol, name, args, value, before):
    from ..experience_learning import _hash
    store = _experience(protocol, args)
    record = value.get('record') or {}
    identity = record.get('recordId')
    if not isinstance(identity, str) or _identity(identity) != identity:
        return False
    path = str(store.base / (identity + '.json'))
    fresh = _json(protocol, path)
    if fresh != record or record.get('recordHash') != _hash({k: v for k, v in record.items() if k != 'recordHash'}):
        return False
    if path in before['files'] or _files(protocol, store.base) != {**before['files'], path: _measure_file(Path(path))}:
        return False
    events = store.events_path.read_text(encoding='utf-8')
    if not events.startswith(before['events']) or json.loads(events[len(before['events']):]) != record:
        return False
    if _sources(protocol, list(before['sources'])) != before['sources']:
        return False
    if name == 'experience.trace':
        expected = {'kind': 'trace', 'traceId': args['traceId'], 'eventKind': args['eventKind'], 'payload': args['payload'],
                    'references': args.get('references', []), 'provenance': {'source': 'agent_report', 'verified': False}}
    elif name == 'experience.investigate':
        expected = {'kind': 'investigation', 'hypothesis': args['hypothesis'], 'experiment': args['experiment'],
                    'references': args.get('references', []), 'status': 'planned'}
    elif name == 'experience.note':
        expected = {'kind': 'note', **{k: args[k].strip() for k in ('lesson', 'conditions', 'invalidation')},
                    'status': 'proposed', 'source': 'agent_report', 'authorityGranted': False}
        root = Path(protocol.gateway.root).resolve()
        expected['evidence'] = [{'path': _path(protocol, p).relative_to(root).as_posix(),
                                 'sha256': before['sources'][str(_path(protocol, p))]['sha256']} for p in args['evidence']]
    else:
        from ..visual_specifications import inspect_image
        baseline = inspect_image(_path(protocol, args['baseline']))
        candidate = inspect_image(_path(protocol, args['candidate']))
        # Inspection timestamps describe each read, not an image property.
        # Preserve the original stamp while freshly comparing every property.
        provenance = record.get('provenance', {})
        for key, image in (('baseline', baseline), ('candidate', candidate)):
            stamp = provenance.get(key, {}).get('inspectedAt')
            if not isinstance(stamp, str) or not stamp:
                return False
            image['inspectedAt'] = stamp
        expected = {'kind': 'comparison', 'experienceId': args['workId'], 'userVersion': baseline['sha256'],
                    'provisionalVersion': candidate['sha256'], 'preference': args['preference'],
                    'observations': args.get('observations', {}),
                    'provenance': {'source': 'agent_critic', 'userPreferenceConfirmed': False, 'baseline': baseline, 'candidate': candidate}}
    return all(record.get(k) == v for k, v in expected.items())


def _measurement(protocol, store, instrument, target):
    spec = store._definition('instrument', instrument)['spec']
    path = _path(protocol, target)
    measured = _measure_file(path)
    out = {'instrument': instrument, 'path': str(path), 'sha256': measured['sha256']}
    if spec['kind'] == 'json_numeric':
        raw = _json(protocol, path)[spec['key']]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ValueError('Invalid numeric measurement')
        out.update(value=float(raw), withinLimit=float(raw) <= float(spec['max']))
    elif spec['kind'] == 'trace_timing':
        durations = [row['durationMs'] for row in _json(protocol, path)]
        if not durations or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in durations):
            raise ValueError('Invalid timing measurement')
        mean = math.fsum(durations) / len(durations)
        out.update(sampleCount=len(durations), durationsMs=durations[:100], omittedSamples=max(0, len(durations) - 100),
                   retrieval={'path': str(path), 'sha256': measured['sha256']}, meanMs=mean,
                   withinLimit=mean <= spec.get('maxMeanMs', float('inf')))
    else:
        from ..visual_specifications import inspect_image
        out.update(inspect_image(path))
        out.update(bytes=path.stat().st_size)
        out['withinLimit'] = (out['dimensions']['width'] >= spec.get('minWidth', 0) and
                              out['dimensions']['height'] >= spec.get('minHeight', 0) and
                              out['bytes'] <= spec.get('maxBytes', float('inf')))
    return out


def _receipt_check(protocol, store, row, expected):
    path = Path(str(row.get('receiptPath') or '')).resolve()
    if path.parent != store.base.resolve() or path.name != 'receipt-' + str(row.get('receiptId')) + '.json':
        return False
    actual = {k: v for k, v in row.items() if k not in {'receiptId', 'observedAt', 'receiptPath'}}
    # Image inspection stamps legitimately differ on a fresh read; dimensions,
    # alpha, format, mode, bytes and digest must still match exactly.
    if 'inspectedAt' in expected:
        if not isinstance(actual.get('inspectedAt'), str) or not actual['inspectedAt']:
            return False
        expected = {**expected, 'inspectedAt': actual['inspectedAt']}
    return _json(protocol, path) == row and actual == expected


def _quality_check(protocol, name, args, value, before):
    store = _quality(protocol, args)
    _files(protocol, store.base)  # Bound every fresh definition before owner reads.
    payload, result = args['arguments'], value.get('result')
    if value.get('workId') != args['workId'] or _sources(protocol, list(before['sources'])) != before['sources']:
        return False
    if name in {'quality.instrument', 'quality.holdout'}:
        kind = 'instrument' if name.endswith('.instrument') else 'holdout'
        path = str(store.base / (kind + '-' + _identity(payload['i']) + '.json'))
        definition = store._definition(kind, payload['i'])
        expected = {'schema': 'neyvia.quality.' + kind + '.v1', 'id': payload['i'], 'spec': payload['spec'], 'sealed': True,
                    'hash': hashlib.sha256(json.dumps(payload['spec'], sort_keys=True, allow_nan=False).encode()).hexdigest()}
        return result == path and definition == expected and path not in before['files'] and _files(protocol, store.base) == {
            **before['files'], path: _measure_file(Path(path))}
    if not isinstance(result, dict):
        return False
    if name == 'quality.challenge':
        store._definition('holdout', payload['holdout'])
        identity = _identity(result.get('id'))
        path = str(store.base / (identity + '.json'))
        expected = {'id': identity, 'holdout': payload['holdout'], 'proposal': payload['proposal'], 'status': 'pending_operator_promotion'}
        return identity.startswith('challenge-') and result == expected and _json(protocol, path) == expected and path not in before['files'] and _files(protocol, store.base) == {**before['files'], path: _measure_file(Path(path))}
    rows = [result]
    if name == 'quality.measure':
        expected = _measurement(protocol, store, payload['instrument'], payload['target'])
    elif name == 'quality.compare':
        a, b = result['baseline'], result['candidate']
        rows += [a, b]
        if not _receipt_check(protocol, store, a, _measurement(protocol, store, payload['instrument'], payload['baseline'])) or not _receipt_check(protocol, store, b, _measurement(protocol, store, payload['instrument'], payload['candidate'])):
            return False
        expected = {'baseline': a, 'candidate': b, 'regression': bool(a['withinLimit'] and not b['withinLimit']),
                    'status': 'accepted' if b['withinLimit'] else 'rejected', 'claim': 'declared instrument criteria only'}
    else:
        instruments = store._definition('holdout', payload['holdout'])['spec']['instruments']
        measurements = result['measurements']
        rows += measurements
        desired = [_measurement(protocol, store, i, target) for i in instruments for target in payload['targets']]
        if len(measurements) != len(desired) or not all(_receipt_check(protocol, store, row, expected) for row, expected in zip(measurements, desired)):
            return False
        expected = {'holdout': payload['holdout'], 'measurements': measurements,
                    'passed': all(row['withinLimit'] for row in measurements), 'claim': 'frozen declared criteria; not general model quality'}
    paths = {row['receiptPath']: _measure_file(_path(protocol, row['receiptPath'])) for row in rows}
    return (not (set(paths) & set(before['files'])) and len(paths) == len(rows) and
            _files(protocol, store.base) == {**before['files'], **paths} and _receipt_check(protocol, store, result, expected))


def _taste_check(protocol, args, value, before):
    from ..contextual_learning import _hash
    state = _taste(protocol, args)._read()
    payload = args['arguments']
    sources = _sources(protocol, list(before['sources']))
    if sources != before['sources']:
        return False
    root = Path(protocol.gateway.root).resolve()
    a, b = [sources[str(_path(protocol, payload[key]))] for key in ('before_path', 'after_path')]
    identity = _hash({'context': payload['context'], 'before': a['sha256'], 'after': b['sha256']})[:24]
    row = state['corrections'].get(identity)
    if identity in before['state']['corrections']:
        return state == before['state'] and value.get('result') == row
    expected = {'correctionId': identity, 'context': payload['context'],
                'before': {'path': Path(a['path']).relative_to(root).as_posix(), 'sha256': a['sha256']},
                'after': {'path': Path(b['path']).relative_to(root).as_posix(), 'sha256': b['sha256']},
                'correction': payload['correction'], 'agentId': payload.get('agent_id', ''), 'status': 'provisional', 'trustedOperator': False}
    prior = before['state']
    return (row == value.get('result') and all(row.get(k) == v for k, v in expected.items()) and
            state['preferences'] == prior['preferences'] and state['corrections'] == {**prior['corrections'], identity: row} and
            state['events'] == [*prior['events'], {'type': 'correction_recorded', 'correctionId': identity, 'at': row['recordedAt']}])


def _experiment_check(protocol, name, args, value, before):
    from ..experiment_studio import ExperimentStudio
    store = ExperimentStudio(protocol.gateway.root)
    _path(protocol, store.base / _identity(args['experimentId']) / 'manifest.json')
    manifest = store.inspect(args['experimentId'])
    if store.compare(args['experimentId'])['status'] != 'unchanged':
        return False
    if name == 'experiment.create':
        return (not before['manifestExists'] and manifest == value.get('manifest') and
                manifest['source'] == before['source'] and store._files(_path(protocol, before['source'])) == before['files'] and
                manifest['sourceSha256'] == manifest['snapshotSha256'] == before['files'] and
                manifest['launchRecipe'] == args.get('launchRecipe', {}) and manifest['resetRecipe'] == args.get('resetRecipe', {}))
    target = _path(protocol, before['destination'])
    _measure_file(target)
    return (not before['destinationExists'] and manifest == before['manifest'] and
            before['snapshotFiles'] == manifest['snapshotSha256'] == store._files(target) and
            value.get('restorePath') == str(target) and value.get('sha256') == manifest['snapshotSha256'])


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    identity = args.get('experimentId') or args.get('workId') or args.get('outputPath') or 'compiled-plan'
    def verify(arguments, value, before):
        if not isinstance(value, dict) or not isinstance(before, dict):
            return False
        try:
            owner = _owner_protocol(protocol, name)
            if name.startswith('behavior.'):
                return _behavior_check(protocol, name, arguments, value, before)
            if name.startswith('experience.'):
                return _experience_check(owner, name, arguments, value, before)
            if name.startswith('quality.'):
                return _quality_check(owner, name, arguments, value, before)
            if name.startswith('experiment.'):
                return _experiment_check(protocol, name, arguments, value, before)
            if name == 'taste.correction':
                return _taste_check(owner, arguments, value, before)
            from ..orchestration_language import compile_neyvia_program
            fresh = compile_neyvia_program(arguments['source'])
            return fresh == before['plan'] == _json(protocol, before['path']) and value == {
                **fresh, 'artifactPath': before['path'], 'artifacts': [before['path']]}
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            return False
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(identity), 'observerTool': 'fresh-local-owner-and-source-bytes',
             'subject': {'identity': identity}, 'expectation': 'Exact request, fresh owner integrity and unchanged artifact bytes; reported observations remain unverified',
             'check': verify}]
