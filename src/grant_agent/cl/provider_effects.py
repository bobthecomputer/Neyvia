"""Fresh provider owner observations; scheduling is never model completion."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from .effects import _bus, _measure_file

SUPPORTED = {'neyvia.session.new', 'neyvia.claude.mods', 'codex.assets.import'}


def readonly(name, args):
    if name == 'neyvia.claude.runs' or name == 'neyvia.claude.mods' and 'enabled' not in args:
        return True
    return None


def _session_owner(protocol, args):
    from ..neyvia_workspace_tools import workspace_for, harness_mode
    from ..connected_sessions.runs import request_fingerprint
    from ..connected_sessions.registry import normalize_app
    broker = workspace_for(protocol.gateway.root).broker()
    folder = str(Path(args['folder']).expanduser().resolve())
    options = broker._turn_options({'model': args.get('model'),
        'permissionMode': harness_mode(args['app'], args.get('permissionMode') or 'read-only')})
    fingerprint = request_fingerprint('new', [normalize_app(args['app']), os.path.normcase(folder)], args['prompt'], options)
    return broker, fingerprint


def _import_manifest(protocol, args):
    from ..codex_import import CodexAssetImporter, _slug
    # An explicit source avoids silently choosing the user's private account.
    if not args.get('codexHome'):
        raise ValueError('CL asset import requires an explicit reviewed codexHome')
    importer = CodexAssetImporter(protocol.gateway.root, args['codexHome'])
    audit = importer.audit()
    audit.pop('generatedAt', None)
    audit.pop('mode', None)
    files = {}
    for skill in audit['personalSkills']:
        base = Path(skill['sourcePath']).parent
        accepted, _ = importer._safe_skill_files(base)
        for path in accepted:
            files['skills/' + _slug(skill['skillId']) + '/' + path.relative_to(base).as_posix()] = _measure_file(path)
    instructions = audit['globalInstructions']
    if instructions.get('present') and instructions.get('sizeBytes', 0) <= 2 * 1024 * 1024:
        files['instructions/AGENTS.md'] = _measure_file(Path(instructions['path']))
    return {'audit': audit, 'files': files}


def snapshot_for(protocol, name, args):
    if name == 'neyvia.session.new':
        broker, fingerprint = _session_owner(protocol, args)
        broker.store.has_request(args['requestId'], fingerprint)
        return {'fingerprint': fingerprint, 'sessions': deepcopy(_bus(protocol).get('sessions', {}))}
    if name == 'neyvia.claude.mods':
        return deepcopy(_bus(protocol).get('claudeCodeMods'))
    if name == 'codex.assets.import':
        return _import_manifest(protocol, args)
    return None


def _verify_session(protocol, args, value, before):
    broker, fingerprint = _session_owner(protocol, args)
    if fingerprint != before['fingerprint'] or not broker.store.has_request(args['requestId'], fingerprint):
        return False
    # Read the persisted row, not the returned broker envelope or live cache.
    saved = broker.store.load(args['requestId'])
    run = value.get('run', {})
    identity = value.get('id')
    sessions = _bus(protocol).get('sessions', {})
    expected = {'id': identity, 'app': args['app'], 'folder': str(Path(args['folder']).expanduser().resolve())}
    if not saved or not identity or saved.get('sessionId') != identity or saved.get('app') != args['app']:
        return False
    if saved.get('state') not in {'running', 'waiting_approval', 'waiting_input', 'completed'}:
        return False
    return (run.get('runId') == args['requestId'] and run.get('sessionId') == identity and
            sessions.get(identity) == expected and all(sessions.get(key) == row
                for key, row in before['sessions'].items() if key != identity))


def _verify_import(protocol, args, value, before):
    if _import_manifest(protocol, args) != before:
        return False
    root = Path(protocol.gateway.root).resolve() / '.agent_control/imports/codex'
    snapshot = Path(value['snapshotRoot']).resolve()
    snapshot.relative_to(root)
    catalog_path = snapshot / 'catalog.json'
    if Path(value['catalogPath']).resolve() != catalog_path:
        return False
    digest = _measure_file(catalog_path)['sha256']
    receipt = json.loads((snapshot / 'import-receipt.json').read_bytes())
    pointer = json.loads((root / 'latest.json').read_bytes())
    catalog = json.loads(catalog_path.read_bytes())
    # Gateway projections remove secret-named fields and localize dates. The
    # persisted owner receipt remains authoritative for those fields.
    stable = set(receipt) - {'secretsImported', 'createdAt'}
    if any(value.get(key) != receipt[key] for key in stable):
        return False
    if pointer.get('catalogPath') != str(catalog_path) or pointer.get('catalogSha256') != digest or value.get('catalogSha256') != digest:
        return False
    for relative, source in before['files'].items():
        target = snapshot / relative
        observed = _measure_file(target)
        if observed.get('sha256') != source['sha256'] or observed.get('bytes') != source['bytes']:
            return False
    actual = {path.relative_to(snapshot).as_posix() for path in snapshot.rglob('*') if path.is_file()}
    if actual != set(before['files']) | {'catalog.json', 'import-receipt.json'}:
        return False
    rows = catalog.get('importedSkills', [])
    return (len(rows) == value['importedSkillCount'] and all(row.get('enabled') is False and
            row.get('promotionState') == 'imported' for row in rows) and
            all(catalog.get(key) == item for key, item in before['audit'].items()) and receipt.get('secretsImported') is False and
            value.get('rawSessionsImported') is False)


def checks_for(protocol, name, args):
    if name not in SUPPORTED or readonly(name, args):
        return []

    def verify(arguments, value, previous):
        try:
            if name == 'neyvia.session.new':
                return _verify_session(protocol, arguments, value, previous)
            if name == 'codex.assets.import':
                return _verify_import(protocol, arguments, value, previous)
            from ..claude_code_mods import settings
            saved = _bus(protocol).get('claudeCodeMods', {})
            observed = settings(_bus(protocol))
            return (saved.get('enabled') is arguments['enabled'] and
                    observed.get('enabled') is arguments['enabled'] and
                    all(value.get(key) == item for key, item in observed.items()))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    subject = ({'requestId': args['requestId'], 'app': args['app'], 'folder': args['folder']}
               if name == 'neyvia.session.new' else {'codexHome': args['codexHome']}
               if name == 'codex.assets.import' else {'enabled': args['enabled']})
    return [{'name': 'effect-' + name.removeprefix('neyvia.').replace('.', '-'),
             'observer': True, 'effect': True, 'subject': subject,
             'subjectKey': name + ':' + str(args.get('requestId') or args.get('codexHome') or 'workspace'),
             'observerTool': 'provider-owner-durable-state',
             'expectation': 'Fresh provider owner persistence matches the exact requested subject; no model outcome inferred',
             'check': verify}]
