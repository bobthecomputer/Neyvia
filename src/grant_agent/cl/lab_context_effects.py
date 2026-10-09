"""Fresh isolated competition measurements and lossless context compaction."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from .record_effects import _files, _identity, _json, _measurement, _path, _receipt_check, _sources
from .effects import _measure_file

SUPPORTED = {'lab.instrument', 'lab.competition', 'lab.compare', 'context.compact'}


def _lab(protocol):
    from ..improvement_lab import ImprovementLab
    return ImprovementLab(protocol.gateway.root)


def _engine(protocol, args):
    from ..context_engine import DurableContextEngine, _safe_id
    identity = _safe_id(args['sessionId'])
    _path(protocol, '.agent_control/context/' + identity + '/ledger.sqlite3')
    maximum = args.get('maxContextTokens', 400000)
    return DurableContextEngine(protocol.gateway.root, identity, max_context_tokens=maximum,
        reserve_tokens=min(20000, max(1000, maximum // 10)))


def _events(protocol, engine):
    _measure_file(_path(protocol, engine.db_path))
    with engine._connection() as db:
        if db.execute('SELECT COUNT(*) FROM context_events').fetchone()[0] > 2000:
            raise ValueError('Context effect witness requires a bounded <=2000 event ledger')
    events = engine._events()
    if sum(len(event.content) for event in events) > 4_000_000:
        raise ValueError('Context effect witness exceeds bounded text')
    return events


def snapshot_for(protocol, name, args):
    if name == 'context.compact':
        engine = _engine(protocol, args)
        events = _events(protocol, engine)
        if not any(event.active for event in events):
            raise ValueError('A compaction effect requires actual active context')
        with engine._connection() as db:
            compactions = [dict(row) for row in db.execute('SELECT * FROM context_compactions ORDER BY created_at')]
        return {'events': [asdict(row) for row in events], 'compactions': compactions,
                'receipts': _files(protocol, engine.receipt_root),
                'sources': _sources(protocol, [row.artifact_path for row in events if row.artifact_path])}
    lab = _lab(protocol)
    before = {'files': _files(protocol, lab.base)}
    if name == 'lab.competition':
        from ..experiment_studio import ExperimentStudio
        studio = ExperimentStudio(protocol.gateway.root)
        source = _path(protocol, args['source'])
        _measure_file(source)
        before.update(source=str(source), sourceFiles=studio._files(source),
                      existingExperiments={candidate: (studio.base / hashlib.sha256(
                          (args['identity'] + ':' + candidate).encode()).hexdigest()[:32]).exists() for candidate in args['candidates']})
    elif name == 'lab.compare':
        from ..experiment_studio import ExperimentStudio
        studio = ExperimentStudio(protocol.gateway.root)
        definition = lab.quality._definition('competition', args['identity'])
        targets, snapshots = [], {}
        for candidate in definition['spec']['candidates']:
            identity = hashlib.sha256((args['identity'] + ':' + candidate).encode()).hexdigest()[:32]
            _path(protocol, studio.base / identity / 'manifest.json')
            manifest = studio.inspect(identity)
            snapshot = _path(protocol, manifest['snapshot'])
            _measure_file(snapshot)
            target = _path(protocol, snapshot / args['targets'][candidate])
            target.relative_to(snapshot)
            targets.append(str(target))
            snapshots[candidate] = manifest
        before.update(sources=_sources(protocol, targets), snapshots=snapshots, definition=definition)
    return before


def _instrument(protocol, args, value, before):
    lab = _lab(protocol)
    files = _files(protocol, lab.base)
    definition = lab.quality._definition('instrument', args['identity'])
    path = str(lab.base / ('instrument-' + _identity(args['identity']) + '.json'))
    return (definition['spec'] == args['spec'] and definition.get('sealed') is True and
            value == {'path': path} and path not in before['files'] and
            files == {**before['files'], path: _measure_file(_path(protocol, path))})


def _competition(protocol, args, value, before):
    from ..experiment_studio import ExperimentStudio
    lab, studio = _lab(protocol), ExperimentStudio(protocol.gateway.root)
    _files(protocol, lab.base)
    path = str(lab.base / ('competition-' + _identity(args['identity']) + '.json'))
    definition = lab.quality._definition('competition', args['identity'])
    spec = {'source': before['source'], 'candidates': args['candidates'], 'instruments': args['instruments']}
    if path in before['files'] or any(before['existingExperiments'].values()):
        return False
    if definition['spec'] != spec or _files(protocol, lab.base) != {**before['files'], path: _measure_file(_path(protocol, path))}:
        return False
    if studio._files(_path(protocol, before['source'])) != before['sourceFiles']:
        return False
    snapshots = []
    for candidate in args['candidates']:
        identity = hashlib.sha256((args['identity'] + ':' + candidate).encode()).hexdigest()[:32]
        _path(protocol, studio.base / identity / 'manifest.json')
        manifest = studio.inspect(identity)
        snapshot = _path(protocol, manifest['snapshot'])
        _measure_file(snapshot)
        if manifest['source'] != before['source'] or manifest['sourceSha256'] != before['sourceFiles'] or studio._files(snapshot) != manifest['snapshotSha256'] or manifest['snapshotSha256'] != before['sourceFiles']:
            return False
        snapshots.append({'candidate': candidate, 'experimentId': identity, 'path': str(snapshot)})
    return value == {'competitionId': args['identity'], 'candidates': snapshots, 'sharedBaseline': before['sourceFiles'], 'promoted': False}


def _compare(protocol, args, value, before):
    from ..experiment_studio import ExperimentStudio
    lab, studio = _lab(protocol), ExperimentStudio(protocol.gateway.root)
    files = _files(protocol, lab.base)
    definition = lab.quality._definition('competition', args['identity'])
    if definition != before['definition'] or _sources(protocol, list(before['sources'])) != before['sources']:
        return False
    spec = definition['spec']
    if set(args['targets']) != set(spec['candidates']) or len(value.get('candidates', [])) != len(spec['candidates']):
        return False
    rows, measurements = [], []
    for candidate, reported in zip(spec['candidates'], value['candidates']):
        identity = hashlib.sha256((args['identity'] + ':' + candidate).encode()).hexdigest()[:32]
        manifest = studio.inspect(identity)
        if manifest != before['snapshots'][candidate]:
            return False
        target = _path(protocol, Path(manifest['snapshot']) / args['targets'][candidate])
        target.relative_to(Path(manifest['snapshot']).resolve())
        saved = reported.get('measurements', [])
        if len(saved) != len(spec['instruments']):
            return False
        for instrument, row in zip(spec['instruments'], saved):
            if not _receipt_check(protocol, lab.quality, row, _measurement(protocol, lab.quality, instrument, str(target))):
                return False
        rows.append({'candidate': candidate, 'measurements': saved, 'eligible': all(row['withinLimit'] for row in saved)})
        measurements += saved
    expected = {'kind': 'competition', 'competitionId': args['identity'], 'definitionHash': definition['hash'],
                'candidates': rows, 'promoted': False, 'boundary': 'frozen artifact measurements; not independent user-journey proof'}
    receipts = [value, *measurements]
    paths = {row['receiptPath']: _measure_file(_path(protocol, row['receiptPath'])) for row in receipts}
    return (len(paths) == len(receipts) and not set(paths) & set(before['files']) and
            files == {**before['files'], **paths} and _receipt_check(protocol, lab.quality, value, expected))


def _compact(protocol, args, value, before):
    from ..context_engine import ContextLedgerEvent
    engine = _engine(protocol, args)
    if _sources(protocol, list(before['sources'])) != before['sources']:
        return False
    # Reconstruct pre-action events and the owner's declared protection budget.
    prior = [ContextLedgerEvent(**row) for row in before['events']]
    prior = [replace(row, pinned=False) if row.kind == 'checkpoint' and row.pinned and row.source == 'neyvia-context-engine' else row for row in prior]
    active = [row for row in prior if row.active]
    target = max(1, int(engine.max_context_tokens * max(.05, min(args.get('targetRatio', .25), .8))))
    budget = min(engine.protect_recent_tokens, target)
    protected = {row.event_id for row in active if row.pinned or engine._required(row)}
    tokens = sum(row.tokens for row in active if row.event_id in protected)
    for row in reversed(active):
        if row.event_id in protected:
            continue
        if len(protected) >= 8 and (tokens >= budget or tokens + row.tokens > budget):
            break
        protected.add(row.event_id); tokens += row.tokens
    archived = [row for row in active if row.event_id not in protected]
    summary = engine.compactor.summarize(archived, args.get('focus', '')) + '\nprotected_events=' + str(len(protected))
    fresh = _events(protocol, engine)
    if len(fresh) != len(prior) + 1:
        return False
    checkpoint = fresh[-1]
    old_expected = [asdict(replace(row, active=False)) if row in archived else asdict(row) for row in prior]
    if [asdict(row) for row in fresh[:-1]] != old_expected:
        return False
    expected_checkpoint = {'role': 'system', 'kind': 'checkpoint', 'content': summary, 'active': True, 'pinned': True,
        'importance': 1.0, 'source': 'neyvia-context-engine', 'artifact_path': '',
        'content_sha256': hashlib.sha256(summary.encode()).hexdigest(),
        'metadata': {'focus': args.get('focus', ''), 'archivedEventIds': [row.event_id for row in archived], 'protectedEventIds': sorted(protected)}}
    if any(asdict(checkpoint).get(k) != v for k, v in expected_checkpoint.items()):
        return False
    receipt = {k: v for k, v in value.items() if k != 'artifacts'}
    path = _path(protocol, receipt.get('receiptPath', ''))
    if path.parent != engine.receipt_root.resolve() or path.name != receipt.get('compactionId', '') + '.json':
        return False
    expected = {'schema': 'neyvia.context_compaction_receipt.v1', 'sessionId': engine.session_id, 'focus': args.get('focus', ''),
        'archivedCount': len(archived), 'archivedEventIds': [row.event_id for row in archived], 'protectedCount': len(protected),
        'protectedEventIds': sorted(protected), 'protectedTokens': tokens, 'checkpointEventId': checkpoint.event_id,
        'compactionStrategy': engine.compactor.strategy_id, 'ledgerPath': str(engine.db_path), 'receiptPath': str(path)}
    if any(receipt.get(k) != v for k, v in expected.items()) or _json(protocol, path) != receipt or value.get('artifacts') != [str(path)]:
        return False
    if str(path) in before['receipts'] or _files(protocol, engine.receipt_root) != {**before['receipts'], str(path): _measure_file(path)}:
        return False
    with engine._connection() as db:
        compactions = [dict(row) for row in db.execute('SELECT * FROM context_compactions ORDER BY created_at')]
    saved = {'compaction_id': receipt['compactionId'], 'created_at': receipt['createdAt'], 'focus': receipt['focus'],
        'archived_count': len(archived), 'protected_count': len(protected), 'checkpoint_event_id': checkpoint.event_id, 'receipt_path': str(path)}
    return compactions == [*before['compactions'], saved]


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    def verify(arguments, value, before):
        if not isinstance(value, dict) or not isinstance(before, dict):
            return False
        try:
            return {'lab.instrument': _instrument, 'lab.competition': _competition, 'lab.compare': _compare,
                    'context.compact': _compact}[name](protocol, arguments, value, before)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(args.get('identity') or args.get('sessionId')),
             'observerTool': 'fresh-frozen-artifact-and-durable-ledger', 'subject': {'identity': args.get('identity') or args.get('sessionId')},
             'expectation': 'Fresh isolated candidate measurements or lossless durable transcript transition under exact frozen criteria', 'check': verify}]
