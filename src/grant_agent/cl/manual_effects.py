"""Quarantined manual edits verified from the owning version and patch stores."""
from __future__ import annotations

import json
import hashlib

from .effects import _call


SUPPORTED = {'neyvia.manual.frontier', 'neyvia.manual.demote', 'neyvia.manual.patch.apply'}


def snapshot_for(protocol, name, args):
    if name == 'neyvia.manual.patch.apply':
        patches = _call(protocol, 'neyvia.manual.patches', {'id': args['id']})['patches']
        patch = next((row for row in patches if row.get('patchId') == args['patchId']), None)
        if not patch:
            raise ValueError('Manual promotion requires the selected patch')
        return {'version': _call(protocol, 'neyvia.manual.versions', {'id': args['id']}), 'patch': patch}
    return _call(protocol, 'neyvia.manual.versions', {'id': args['id']})


def _verify(protocol, name, args, value, before):
    if name == 'neyvia.manual.patch.apply':
        return _verify_promotion(protocol, args, value, before)
    if value.get('id') != args['id'] or value.get('status') != 'quarantined' or value.get('baseSha256') != before.get('sha256'):
        return False
    identity = value.get('patchId')
    if not isinstance(identity, str) or len(identity) != 32:
        return False
    patch_path = protocol.gateway.root / '.neyvia/manual-patches' / (identity + '.json')
    try:
        raw = patch_path.read_bytes()
        saved = json.loads(raw)
    except (OSError, ValueError):
        return False
    observed = _call(protocol, 'neyvia.manual.patches', {'id': args['id']})
    current = _call(protocol, 'neyvia.manual.versions', {'id': args['id']})
    if saved != {k: v for k, v in value.items() if k != 'ok'} or saved not in observed.get('patches', []) or current != before:
        return False
    if raw != (json.dumps(saved, ensure_ascii=False, indent=2) + '\n').encode('utf-8'):
        # The owner writes canonical JSON atomically. A mismatched file means
        # this read did not observe the exact persisted patch bytes.
        return False
    if name == 'neyvia.manual.frontier':
        return saved.get('note') == args['note'] and saved.get('observed') == args['observed'] and saved.get('operations') == args.get('operations', [])
    from ..manual_state import escape
    wanted = [{'op': 'remove', 'path': '/chapters/' + escape(args['chapter']) + '/procedures/' + escape(args['procedure'])}]
    return saved.get('note') == args['reason'] and saved.get('observed') == {'obsoleteProcedure': args['procedure']} and saved.get('operations') == wanted


def _verify_promotion(protocol, args, value, before):
    if before['patch'].get('status') != 'quarantined':
        return False
    prior = before['version']['sha256']
    digest = value.get('sha256')
    if value.get('id') != args['id'] or value.get('patchId') != args['patchId'] or value.get('parentSha256') != prior:
        return False
    if digest == prior or not isinstance(digest, str) or len(digest) != 64:
        return False
    root = protocol.gateway.root / '.neyvia/manual-versions'
    parent_artifact = value.get('parentArtifactSha256')
    if not isinstance(parent_artifact, str) or len(parent_artifact) != 64:
        return False
    current = _call(protocol, 'neyvia.manual.versions', {'id': args['id']})
    if current.get('sha256') != digest or current.get('lineage', []) != before['version'].get('lineage', []) + [
            {key: value[key] for key in ('sha256', 'parentSha256', 'parentArtifactSha256',
                                         'patchId', 'reviewer', 'evidence', 'demoted', 'grounded')}]:
        return False
    new_file = root / args['id'] / (digest + '.json')
    old_file = root / args['id'] / (parent_artifact + '.json')
    try:
        new_raw, old_raw = new_file.read_bytes(), old_file.read_bytes()
        new_data = json.loads(new_raw)
    except (OSError, ValueError):
        return False
    if hashlib.sha256(new_raw).hexdigest() != digest or hashlib.sha256(old_raw).hexdigest() != parent_artifact:
        return False
    source_copy = root / args['id'] / (prior + '.cl')
    if prior != parent_artifact and (not source_copy.exists() or
                                     hashlib.sha256(source_copy.read_bytes()).hexdigest() != prior):
        return False
    from ..manual_versions import apply_operations
    if apply_operations(json.loads(old_raw), before['patch']['operations']) != new_data:
        return False
    patches = _call(protocol, 'neyvia.manual.patches', {'id': args['id']})['patches']
    patch = next((row for row in patches if row.get('patchId') == args['patchId']), None)
    return bool(patch and patch.get('status') == 'promoted' and patch.get('promotedSha256') == digest and
                patch.get('baseSha256') == prior and value.get('reviewer') == args['reviewer'] and
                value.get('evidence') == args['evidence'])


def checks_for(protocol, name, args):
    if name not in SUPPORTED or protocol.scope is not None and not {'neyvia.manual.patches', 'neyvia.manual.versions'} <= protocol.scope:
        return []
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True,
             'subjectKey': 'manual-patch:' + args['id'],
             'bindSubject': lambda arguments, value, previous: 'manual-patch:' + value['patchId'],
             'observerTool': 'neyvia.manual.patches', 'subject': {'id': args['id']},
             'expectation': 'Fresh quarantined patch bytes equal the selected request while the manual version remains unchanged',
             'check': lambda arguments, value, previous: _verify(protocol, name, arguments, value, previous)}]
