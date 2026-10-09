"""Owner-bound receipt proof for the local workflow recorder.

Workflow receipts are deterministic, but the returned digest alone cannot prove
that a file was written or that its source evidence still has the claimed bytes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .effects import _call, _measure_file


SUPPORTED = {'neyvia.workflow.record'}


def readonly(name, args):
    if name in {'neyvia.intent.checklist', 'neyvia.workflow.details'}:
        return True
    return None


def _evidence(protocol, args):
    root = Path(protocol.gateway.root).resolve()
    observed = {}
    for identity, descriptor in args['evidence'].items():
        if not isinstance(identity, str) or not isinstance(descriptor, dict) or set(descriptor) != {'path', 'sha256'}:
            raise ValueError('Workflow evidence requires exact local file descriptors')
        path = (root / descriptor['path']).resolve()
        path.relative_to(root)
        state = _measure_file(path)
        if state.get('kind') != 'file' or state['bytes'] > 1_000_000 or state['sha256'] != descriptor['sha256']:
            raise ValueError('Workflow source evidence is missing, oversized, or changed')
        content = json.loads(path.read_bytes())
        if not isinstance(content, dict) or not content:
            raise ValueError('Workflow source evidence must contain a measurement object')
        observed[identity] = {'path': str(path), 'sha256': state['sha256'], 'bytes': state['bytes']}
    return observed


def _expected(protocol, args):
    check = _call(protocol, 'neyvia.workflow.check', args)
    if check.get('accepted') is not True:
        raise ValueError('Workflow check does not accept this report')
    payload = {'schema': 'neyvia.workflow-receipt.v1', **check,
               'report': args['report'], 'evidenceFiles': args['evidence']}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return digest, encoded


def snapshot_for(protocol, name, args):
    if name not in SUPPORTED:
        return None
    sources = _evidence(protocol, args)
    digest, _ = _expected(protocol, args)
    target = Path(protocol.gateway.root).resolve() / 'workflow-receipts' / (digest + '.json')
    return {'sources': sources, 'digest': digest, 'target': str(target),
            'before': _measure_file(target)}


def checks_for(protocol, name, args):
    if name not in SUPPORTED or protocol.scope is not None and 'neyvia.workflow.check' not in protocol.scope:
        return []

    def verify(arguments, value, previous):
        if not isinstance(value, dict) or not isinstance(previous, dict):
            return False
        try:
            if _evidence(protocol, arguments) != previous['sources']:
                return False
            digest, encoded = _expected(protocol, arguments)
            target = Path(previous['target'])
            if digest != previous['digest'] or target != Path(protocol.gateway.root).resolve() / 'workflow-receipts' / (digest + '.json'):
                return False
            if value.get('sha256') != digest or value.get('receipt') != str(target):
                return False
            observed = _measure_file(target)
            return bool(observed.get('kind') == 'file' and observed.get('bytes') == len(encoded) and
                        observed.get('sha256') == digest and target.read_bytes() == encoded)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False

    return [{'name': 'effect-workflow-record', 'observer': True, 'effect': True,
             'subjectKey': 'workflow:record',
             'bindSubject': lambda arguments, value, previous: 'workflow:receipt:' + previous['digest'],
             'observerTool': 'neyvia.workflow.check',
             'subject': {'manual': args.get('manual'), 'evidence': args.get('evidence')},
             'expectation': 'Fresh workflow check accepts unchanged evidence and exact receipt bytes persist under the selected root',
             'check': verify}]
