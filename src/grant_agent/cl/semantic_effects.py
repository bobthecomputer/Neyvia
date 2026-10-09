"""Subject-bound observations for durable semantic native actions.

These predicates establish persistence and exact request lineage.  A proof
capsule's existence never establishes that its claim is true.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path


SUPPORTED = {
    'semantic.recovery.create', 'semantic.proof.create',
    'semantic.changeset.create', 'semantic.mission.create',
    'semantic.application.register', 'semantic.autonomy.admit',
    'semantic.autonomy.revoke',
}

_ARTIFACTS = {
    'semantic.recovery.create': ('recovery_objects', 'recovery', 'recoveryId'),
    'semantic.proof.create': ('proof_capsules', 'proof', 'proofId'),
    'semantic.changeset.create': ('change_sets', 'changeSet', 'changeId'),
    'semantic.mission.create': ('missions', 'mission', 'missionId'),
    'semantic.application.register': ('living_applications', 'application', 'applicationId'),
}


def _hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError('Semantic observation requires a bounded regular file')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path):
    _hash(path)
    return json.loads(path.read_text(encoding='utf-8'))


def _root(protocol) -> Path:
    return Path(protocol.gateway.root).resolve()


def _directory(protocol, name, args) -> Path:
    root = _root(protocol)
    family = _ARTIFACTS[name][0]
    if name == 'semantic.recovery.create':
        from ..recovery_objects import RecoveryObjectStore
        return RecoveryObjectStore(root, 'semantic-tools').base.resolve()
    if name == 'semantic.proof.create':
        from ..proof_capsules import ProofCapsuleStore
        return ProofCapsuleStore(root, str(args.get('sessionId') or 'semantic-tools')).base.resolve()
    return (root / '.agent_control' / family).resolve()


def _files(directory: Path):
    if not directory.exists():
        return {}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Semantic artifact directory is not regular')
    paths = list(directory.iterdir())
    if len(paths) > 256:
        raise ValueError('Semantic artifact directory is too large to observe')
    return {p.name: _hash(p) for p in paths if p.suffix == '.json'}


def _sources(protocol, name, args):
    rows = args.get('artifacts', []) if name == 'semantic.proof.create' else (
        args.get('generated_artifacts', []) if name == 'semantic.changeset.create' else [])
    if name == 'semantic.changeset.create':
        rows = [*args.get('source_modifications', []), *rows]
    if name == 'semantic.application.register' and (args.get('source') or {}).get('path'):
        rows = [args['source']]
    observed = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get('path') or not row.get('sha256'):
            raise ValueError('Semantic source requires path and sha256')
        path = (Path(protocol.gateway.root) / str(row['path'])).resolve()
        path.relative_to(_root(protocol))
        measured = _hash(path)
        if measured != str(row['sha256']).lower():
            raise ValueError('Semantic source hash changed before action')
        observed[str(path)] = measured
    return observed


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    if name.startswith('semantic.autonomy.'):
        from ..semantic_tools import SemanticToolRuntime
        path = SemanticToolRuntime(_root(protocol))._managed_path('autonomy', args['policyId'])
        state = _json(path)
        if state.get('operatorAuthority') is not True:
            raise ValueError('A trusted persisted operator policy is required')
        return {'path': str(path), 'hash': _hash(path), 'state': state}
    directory = _directory(protocol, name, args)
    return {'directory': str(directory), 'files': _files(directory),
            'sources': _sources(protocol, name, args)}


def _request_matches(name, args, record):
    if name == 'semantic.recovery.create':
        expected = {'failedOperation': args['failedOperation'],
                    'confirmedSteps': args.get('confirmedSteps', []),
                    'uncertainEffects': args.get('uncertainEffects', []),
                    'retrySafety': args.get('retrySafety', 'requires_reconciliation'),
                    'availableRecoveryPaths': args.get('availableRecoveryPaths', []),
                    'requiredAuthority': args.get('requiredAuthority', []),
                    'status': 'open'}
        from ..recovery_objects import RecoveryObject
        RecoveryObject.from_dict(record)
    elif name == 'semantic.proof.create':
        expected = {'claim': args['claim'], 'build': args['build'],
                    'environment': args['environment'], 'startingState': args['startingState'],
                    'journey': args['journey'], 'actions': args['actions'],
                    'artifacts': args['artifacts'], 'result': args['result'],
                    'reproduction': args['reproduction']}
        from ..proof_capsules import ProofCapsule
        ProofCapsule.from_dict(record)
        if record.get('verification', {}).get('claimProven') is True:
            return False
    elif name == 'semantic.changeset.create':
        expected = {'intendedBehavior': args['intended_behavior'],
                    'sourceModifications': args['source_modifications'],
                    'generatedArtifacts': args.get('generated_artifacts', []),
                    'rollbackBoundary': args['rollback_boundary']}
        body = {key: value for key, value in record.items() if key != 'contentHash'}
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if record.get('contentHash') != hashlib.sha256(encoded.encode()).hexdigest():
            return False
    elif name == 'semantic.mission.create':
        expected = {'missionId': args['missionId'], 'desiredOutcome': args['desiredOutcome'],
                    'status': 'planned'}
        if args.get('acceptanceGates'):
            statements = [g['statement'] if isinstance(g, dict) else str(g) for g in args['acceptanceGates']]
            if [g.get('statement') for g in record.get('acceptanceGates', [])] != statements:
                return False
        if any(g.get('status') != 'pending' for g in record.get('acceptanceGates', [])):
            return False
    else:
        expected = {'applicationId': args['applicationId'],
                    'source': args.get('source') or {},
                    'buildRecipe': args.get('buildRecipe') or {},
                    'health': args.get('health') or {},
                    'rollback': args.get('rollback') or {}}
        if record.get('deployments') or record.get('proofs'):
            return False
    return all(record.get(key) == value for key, value in expected.items())


def _artifact_check(protocol, name, args, value, before):
    if not isinstance(value, dict) or value.get('ok') is False:
        return False
    directory = Path(before['directory'])
    path = Path(str(value.get('artifactPath') or '')).resolve()
    path.relative_to(directory)
    if path.parent != directory or value.get('artifacts') != [str(path)]:
        return False
    if path.name in before['files'] or _files(directory) != {
            **before['files'], path.name: _hash(path)}:
        return False
    if _sources(protocol, name, args) != before['sources']:
        return False
    _, field, identity = _ARTIFACTS[name]
    record = _json(path)
    persisted_identity = 'capsuleId' if name == 'semantic.proof.create' else identity
    if record != value.get(field) or record.get(persisted_identity) != value.get(identity):
        return False
    requested_identity = 'capsuleId' if name == 'semantic.proof.create' else identity
    if requested_identity in args and record.get(persisted_identity) != args[requested_identity]:
        return False
    return _request_matches(name, args, record)


def _policy_check(name, args, value, before):
    if not isinstance(value, dict) or value.get('policyId') != args['policyId']:
        return False
    path = Path(before['path'])
    after = _json(path)
    old = before['state']
    if _hash(path) == before['hash'] or value.get('artifacts') != [str(path)]:
        return False
    if len(after.get('history', [])) != len(old.get('history', [])) + 1 or after['history'][:-1] != old.get('history', []):
        return False
    if name == 'semantic.autonomy.admit':
        decision = value.get('decision') or {}
        cost = float(args.get('cost') or 0)
        return (value.get('ok') is True and value.get('status') == 'admitted' and
                decision == after['history'][-1] and decision.get('allowed') is True and
                decision.get('executed') is False and decision.get('action') == args['action'] and
                decision.get('reasons') == [] and math.isfinite(cost) and cost >= 0 and
                after.get('budgetUsed') == float(old.get('budgetUsed', 0)) + cost and
                all(after.get(key) == old.get(key) for key in old if key not in {'history', 'budgetUsed'}))
    reason = str(args.get('reason') or 'operator revoked').strip() or 'revoked'
    return (value.get('policy') == {key: after.get(key) for key in value.get('policy', {})} and
            after.get('revoked') is True and after.get('revocationReason') == reason and
            after['history'][-1].get('event') == 'revoked' and
            after['history'][-1].get('reason') == reason and
            all(after.get(key) == old.get(key) for key in old if key not in {'history', 'revoked', 'revocationReason'}))


def checks_for(protocol, name, args):
    if name not in SUPPORTED:
        return []
    subject = {key: deepcopy(args[key]) for key in (
        'recoveryId', 'capsuleId', 'change_id', 'missionId', 'applicationId', 'policyId', 'action') if key in args}
    def bind(arguments, value, previous):
        identity = value.get('policyId') if name.startswith('semantic.autonomy.') else value.get(_ARTIFACTS[name][2])
        return name + ':' + str(identity)
    def check(arguments, value, previous):
        try:
            return (_policy_check(name, arguments, value, previous) if name.startswith('semantic.autonomy.')
                    else _artifact_check(protocol, name, arguments, value, previous))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False
    return [{'name': 'effect-' + name.replace('.', '-'), 'observer': True, 'effect': True,
             'subjectKey': name + ':' + str(next(iter(subject.values()), 'new')),
             'bindSubject': bind, 'observerTool': 'semantic-persisted-artifact',
             'subject': subject,
             'expectation': 'Exact requested semantic transition persists under selected workspace with unchanged source hashes',
             'check': check}]
