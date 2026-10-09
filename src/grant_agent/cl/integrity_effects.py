"""Fresh artifact verification; never promote a capsule's semantic claim."""
from copy import deepcopy

SUPPORTED = {'semantic.proof.verify'}


def _capsule(protocol, args):
    from ..proof_capsules import ProofCapsuleStore
    store = ProofCapsuleStore(protocol.gateway.root, 'semantic-tools')
    path = store._path(args['proofId'])
    from .semantic_effects import _json
    data = _json(path)
    from ..proof_capsules import ProofCapsule
    capsule = ProofCapsule.from_dict(data)
    if capsule.capsule_id != args['proofId']:
        raise ValueError('Capsule identity drift')
    from .effects import _measure_file
    artifacts = []
    for row in capsule.artifacts:
        candidate = protocol.gateway.root / row['path']
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('Proof artifact refuses links')
        target = candidate.resolve()
        if not target.is_relative_to(protocol.gateway.root.resolve()):
            raise ValueError('Proof artifact is outside the selected workspace')
        artifacts.append(_measure_file(target))
    return {'capsule': data, 'artifacts': artifacts, 'path': str(path)}


def snapshot_for(protocol, name, args):
    return _capsule(protocol, args)


def checks_for(protocol, name, args):
    if name not in SUPPORTED or args.get('sessionId'):
        return []
    def check(arguments, value, previous):
        try:
            fresh = _capsule(protocol, arguments)
            if fresh['artifacts'] != previous['artifacts']:
                return False
            from ..proof_capsules import ProofCapsule
            capsule = ProofCapsule.from_dict(deepcopy(previous['capsule']))
            recomputed = capsule.prove(protocol.gateway.root)
            actual = fresh['capsule'].get('verification', {})
            stamp = actual.get('verifiedAt')
            recomputed['verifiedAt'] = stamp
            # Recompute the content hash after aligning the timestamp.
            capsule.verification['verifiedAt'] = stamp
            expected = capsule.to_dict()
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()
            return (0 <= age <= 30 and actual == recomputed and
                    actual.get('claimProven') is False and
                    actual.get('artifactsVerified') is True and
                    fresh['capsule'] == expected == value.get('proof') and
                    value.get('verification') == actual and value.get('proofId') == arguments['proofId'])
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return [{'name': 'effect-semantic-proof-verify', 'observer': True, 'effect': True,
             'subjectKey': 'proof-integrity:' + args['proofId'],
             'observerTool': 'proof-capsule-and-current-artifact-bytes',
             'subject': {'proofId': args['proofId']},
             'expectation': 'Current artifact hashes equal the capsule; exact independent integrity verdict persists, claim remains unproven',
             'check': check}]
