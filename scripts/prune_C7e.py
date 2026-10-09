"""Prune task-local redundant evidence after referenced observations are sealed."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

from compact_C7d_evidence import references, protected as original_protected, sha

REPO = Path(__file__).resolve().parents[1]


def files_in(root):
    """Enumerate validated task roots without resolving every file repeatedly."""
    root = root.resolve()
    root.relative_to(REPO / '.agent_control')
    found = set()
    for base, directories, names in os.walk(root):
        directories[:] = [name for name in directories
                          if not (Path(base) / name).is_symlink() and not (Path(base) / name).is_junction()]
        for name in names:
            path = Path(base) / name
            if not path.is_symlink() and path.is_file():
                found.add(path)
    return found


def protected(path):
    name = path.name.lower()
    return (original_protected(path)
            or name in {'auth-profiles.json', 'oauth_creds.json', 'account.json',
                        '.claude.json', '.credentials.json', 'openclaw.json',
                        'neyvia_web_admin.json', 'grand_agent_web_admin.json',
                        'cookies-wal', 'cookies-shm', 'local state', 'web data'}
            or re.search(r'credential|password|api[_-]?key|secret|nas_codex2_', name, re.I) is not None
            or path.suffix.lower() in {'.pem', '.key', '.pfx', '.p12'}
            or name == 'config.xml' and 'owned-native-home' in {p.lower() for p in path.parts})


def refuse_credential_open(event, args):
    # Retention may enumerate protected fixture names, but it must never open
    # them for parsing, hashing or archiving, even if a receipt references one.
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        value = args[0].decode(sys.getfilesystemencoding()) if isinstance(args[0], bytes) else args[0]
        path = Path(value).resolve()
        if path.is_relative_to(REPO / '.agent_control') and protected(path):
            raise PermissionError('C7 retention refuses credential contents before open')


def compact_observation(path):
    path = Path(path).resolve()
    path.relative_to(REPO / 'scripts/evidence')
    raw = path.read_bytes()
    value = json.loads(raw)
    if 'fullReceipt' in value:
        return
    archive = path.with_name(path.stem + '-full.json.gz')
    archive.write_bytes(gzip.compress(raw, mtime=0))
    if gzip.decompress(archive.read_bytes()) != raw:
        raise ValueError('Compacted observation differs')
    summary = {key: value[key] for key in ('schema', 'ok', 'explicitPort', 'category', 'sourceStable', 'sourceBindings', 'engine',
               'headlessHost', 'categoryChecks', 'captures', 'desktopGuard', 'boundary') if key in value}
    summary['fullReceipt'] = {'path': archive.relative_to(REPO).as_posix(), 'sha256': sha(archive), 'bytes': archive.stat().st_size}
    if 'runs' in value:
        from collections import Counter
        summary['runCounts'] = dict(Counter(r['status'] for r in value['runs']))
        summary['observations'] = len(value.get('observations', []))
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'path': path.relative_to(REPO).as_posix(), 'rawBytes': len(raw), 'archiveBytes': archive.stat().st_size}))


def text_references():
    names = subprocess.run(['git', 'ls-files', '-z', 'scripts/evidence/C7*.json', 'scripts/evidence/C7*.gz'], cwd=REPO, capture_output=True, check=True).stdout.decode().split('\0')
    found = set()
    def walk(value):
        if isinstance(value, dict):
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
        elif isinstance(value, str):
            found.add(value.replace('\\', '/').casefold())
    for name in names:
        if not name: continue
        raw = (REPO / name).read_bytes()
        walk(json.loads(gzip.decompress(raw) if name.endswith('.gz') else raw))
    return found


def retain_committed_references(files, names):
    """Follow nested committed family receipts as well as top-level receipts."""
    found = references(files)
    aliases = {alias.casefold(): path for path in files for alias in
               (str(path), path.as_posix(), str(path.relative_to(REPO)), path.relative_to(REPO).as_posix())}
    pending = [path for alias, path in aliases.items() if alias in names and path not in found]
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        if protected(path) or path.suffix not in {'.json', '.gz'} or path.stat().st_size > 128 * 1024 * 1024:
            continue
        try:
            raw = path.read_bytes()
            values = [json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)]
        except (ValueError, OSError, EOFError):
            continue
        while values:
            value = values.pop()
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, list):
                values.extend(value)
            elif isinstance(value, str) and len(value) < 1024:
                child = aliases.get(value.replace('\\', '/').casefold())
                if child is not None and child not in found:
                    pending.append(child)
    return found


def _deadline_shape(report, family_names):
    """Fail closed unless this is an exact-family, explicitly incomplete report."""
    if (not isinstance(report, dict) or report.get('schema') != 'neyvia.c7e-deadline.v1'
            or report.get('ok') is not True or report.get('complete') is not False
            or report.get('fixturesComplete') is not False
            or report.get('fixtureCompletion') != 'not_claimed'
            or report.get('sourceCurrent') is not True
            or report.get('unsealedDiagnosticsAreCompletionEvidence') is not False):
        raise ValueError('A source-current incomplete C7e deadline receipt is required')
    if type(report.get('explicitPort')) is not int or report['explicitPort'] not in range(48741, 48750):
        raise ValueError('Deadline report lacks an explicit assigned proof port')
    states = report.get('familyStates')
    if not isinstance(states, list) or [row.get('family') for row in states if isinstance(row, dict)] != list(family_names):
        raise ValueError('Deadline report must account for the exact registered family set in order')
    receipts = report.get('familyReceipts')
    if not isinstance(receipts, list) or any(not isinstance(row, dict) for row in receipts):
        raise ValueError('Deadline family receipts must be a list')
    receipt_names = [row.get('family') for row in receipts]
    if len(set(receipt_names)) != len(receipt_names) or not set(receipt_names) <= set(family_names):
        raise ValueError('Deadline report contains duplicate or unknown family receipts')
    if report.get('completedFamilies') != len(receipts):
        raise ValueError('Deadline completed-family count differs from its receipts')
    proof_roots = report.get('proofRoots')
    if (not isinstance(proof_roots, list) or not proof_roots
            or any(not isinstance(value, str) for value in proof_roots)
            or len(set(proof_roots)) != len(proof_roots)):
        raise ValueError('Deadline report must retain its exact selected proof roots')
    for row in states:
        if (row.get('state') not in {'completed_source_current', 'in_progress_unsealed', 'pending_unobserved'}
                or any(type(row.get(key)) is not int or row[key] < 0 for key in
                       ('casesTotal', 'fixtureCasesTotal', 'authorityCasesTotal', 'passing', 'failing', 'blocked', 'builtUnverified', 'unbuilt'))
                or sum(row[key] for key in ('passing', 'failing', 'blocked', 'builtUnverified', 'unbuilt')) != row['casesTotal']):
            raise ValueError('Invalid deadline family state or case accounting')
    totals = report.get('caseTotals')
    if not isinstance(totals, dict):
        raise ValueError('Deadline case totals are missing')
    for key in ('casesTotal', 'passing', 'failing', 'blocked', 'builtUnverified', 'unbuilt'):
        if totals.get(key) != sum(row[key] for row in states):
            raise ValueError('Deadline aggregate differs from family accounting: ' + key)
    for key in ('caseInventory', 'authorityReceipt'):
        ref = report.get(key)
        if (not isinstance(ref, dict) or not isinstance(ref.get('path'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', str(ref.get('sha256', '')))):
            raise ValueError('Invalid deadline provenance reference: ' + key)
    diagnostics = report.get('unsealedCaseProgress')
    if not isinstance(diagnostics, list) or any(not isinstance(entry, dict) for entry in diagnostics):
        raise ValueError('Deadline unsealed diagnostics must be a list')
    for entry in diagnostics:
        if entry.get('family') not in family_names or entry.get('completionReceipt') is not False:
            raise ValueError('Unsealed diagnostics cannot act as completion receipts')
    return report


def _repo_reference(value, base, *, directory=False):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid deadline reference path')
    relative = Path(value)
    if relative.is_absolute() or any(part in {'.', '..'} for part in relative.parts):
        raise ValueError('Deadline reference escapes its scoped root')
    path = REPO / relative
    resolved = path.resolve(strict=True)
    resolved.relative_to(base.resolve())
    cursor = REPO
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or cursor.is_junction():
            raise ValueError('Deadline references cannot cross symlink or junction boundaries')
    if not (resolved.is_dir() if directory else resolved.is_file()):
        raise ValueError('Deadline reference is not a file')
    return resolved


def _deadline_references(report, report_path):
    proof_root = (REPO / '.agent_control/proofs/c7').resolve()
    inventory_path = _repo_reference(report['caseInventory']['path'], (REPO / 'scripts/evidence'))
    authority_path = _repo_reference(report['authorityReceipt']['path'], (REPO / 'scripts/evidence'))
    if sha(inventory_path) != report['caseInventory']['sha256'] or sha(authority_path) != report['authorityReceipt']['sha256']:
        raise ValueError('Deadline inventory or authority receipt changed')
    refs = {report_path, inventory_path, authority_path}
    from grant_agent.proof_contracts import source_digest
    source_bindings = report.get('sourceBindings')
    seal_source = _repo_reference('scripts/seal_C7e_deadline.py', REPO)
    if source_bindings != {'scripts/seal_C7e_deadline.py': source_digest(seal_source)}:
        raise ValueError('Deadline report generator source binding is stale')
    refs.add(seal_source)
    stamp = report.get('sealedAtUtc')
    if not isinstance(stamp, str):
        raise ValueError('Deadline report seal timestamp is missing')
    try:
        parsed_stamp = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Deadline report seal timestamp is invalid') from exc
    if parsed_stamp.tzinfo is None or parsed_stamp.utcoffset() != timezone.utc.utcoffset(parsed_stamp):
        raise ValueError('Deadline report seal timestamp must be UTC')
    for field, filename, value_key in (('bugs', 'C7e-bugs.json', 'counts'),
                                       ('tokenUsage', 'C7e-tokens.json', 'loggedTotals')):
        metadata = report.get(field)
        if not isinstance(metadata, dict):
            raise ValueError('Deadline report is missing ' + field + ' accounting')
        path = _repo_reference(metadata.get('path'), REPO / 'scripts/evidence')
        raw = path.read_bytes()
        current_value = json.loads(raw)
        if (path.name != filename or sha(path) != metadata.get('sha256')
                or metadata.get('counts') != current_value.get(value_key)):
            raise ValueError('Deadline ' + field + ' evidence changed')
        refs.add(path)
    roots = []
    for value in report['proofRoots']:
        roots.append(_repo_reference(value, proof_root, directory=True))
    for entry in report.get('proofIndexes', []):
        path = _repo_reference(entry['path'], proof_root)
        if sha(path) != entry['sha256'] or not any(path == root / 'semantic-fixtures/families.json' for root in roots):
            raise ValueError('Selected proof index changed or escaped its root')
        refs.add(path)
    for row in report['familyReceipts']:
        path = _repo_reference(row.get('path'), proof_root)
        if sha(path) != row.get('sha256'):
            raise ValueError('Deadline family receipt changed: ' + str(row.get('family')))
        refs.add(path)
        if not any(path.is_relative_to(root / 'semantic-fixtures') for root in roots):
            raise ValueError('Family receipt is outside the selected deadline proof roots')
    for family in report['unsealedCaseProgress']:
        for file in family.get('files', []):
            path = _repo_reference(file.get('path'), proof_root)
            if sha(path) != file.get('sha256'):
                raise ValueError('Deadline progress receipt changed: ' + str(path))
            refs.add(path)
            if not any(path.is_relative_to(root / 'semantic-fixtures') for root in roots):
                raise ValueError('Progress receipt is outside the selected deadline proof roots')
    return refs, roots, inventory_path


def validate_deadline(path):
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.edge_fixture_catalog import BUILDERS
    import importlib.util

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = REPO / candidate
    report_path = _repo_reference(candidate.relative_to(REPO).as_posix(), REPO / 'scripts/evidence')
    report = json.loads(report_path.read_bytes())
    _deadline_shape(report, BUILDERS)
    refs, roots, inventory = _deadline_references(report, report_path)
    module_path = REPO / 'scripts/seal_C7e_deadline.py'
    spec = importlib.util.spec_from_file_location('seal_C7e_deadline_prune_validation', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module._report(report['explicitPort'], roots, inventory)
    extras = {'sealedAtUtc', 'sourceBindings', 'bugs', 'tokenUsage'}
    if set(report) != set(current) | extras or _canonical(current) != _canonical({key: value for key, value in report.items() if key not in extras}):
        raise ValueError('Deadline receipt differs from current source-bound proof state')
    return report, refs


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, separators=(',', ':')))
    return value


def require_committed(paths):
    """Require every deadline ref to match the committed HEAD blob before prune."""
    for path in sorted({Path(item).resolve(strict=True) for item in paths}):
        path.relative_to(REPO)
        if protected(path) or path.is_symlink() or path.is_junction():
            raise ValueError('Protected or indirect reference cannot authorize pruning')
        relative = path.relative_to(REPO).as_posix()
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', '--', relative], cwd=REPO,
                                 capture_output=True, check=False)
        if tracked.returncode:
            raise ValueError('Deadline and every referenced file must be committed before pruning: ' + relative)
        head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD:' + relative], cwd=REPO,
                              capture_output=True, text=True, check=False)
        working = subprocess.run(['git', 'hash-object', '--path=' + relative, '--', relative], cwd=REPO,
                                 capture_output=True, text=True, check=False)
        if head.returncode or working.returncode or head.stdout.strip() != working.stdout.strip():
            raise ValueError('Deadline reference differs from committed HEAD: ' + relative)


def add_reference_names(names, paths):
    for path in paths:
        path = Path(path).resolve()
        names.update({str(path).casefold(), path.as_posix().casefold(),
                      path.relative_to(REPO).as_posix().casefold()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--deadline', type=Path, help='Prune only against a revalidated, exact-family incomplete deadline receipt')
    parser.add_argument('--compact-observation', type=Path)
    parser.add_argument('--checkpoint', action='store_true', help='Prune stopped-worker scratch using a current progress receipt; never claim completion')
    parser.add_argument('--historical-checkpoint', action='store_true', help='Retain intact historical checkpoint evidence after source edits; never claim current case passes')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.compact_observation:
        compact_observation(args.compact_observation)
        return
    if args.deadline:
        if args.campaign or args.checkpoint or args.historical_checkpoint:
            parser.error('--deadline is a separate retention mode')
        sys.addaudithook(refuse_credential_open)
        sys.path.insert(0, str(REPO / 'src'))
        deadline_report, deadline_refs = validate_deadline(args.deadline)
        if args.apply:
            # Committed receipts bind raw local observations by exact hash.
            # Raw ignored proof files remain local evidence, not Git source.
            require_committed(path for path in deadline_refs
                              if not path.is_relative_to(REPO / '.agent_control'))
        used = text_references()
        add_reference_names(used, deadline_refs)
        campaign = None
        receipt = None
    else:
        if not args.campaign:
            parser.error('Finished campaign required for pruning')
        sys.addaudithook(refuse_credential_open)
        campaign = args.campaign.resolve()
        campaign.relative_to(REPO / '.agent_control/proofs/c7')
        receipt = json.loads((REPO / 'scripts/evidence/C7e.json').read_bytes())
        if not (campaign / 'semantic-fixtures/families.json').is_file():
            raise ValueError('A sealed family index is required')
        if args.historical_checkpoint and not args.checkpoint:
            parser.error('--historical-checkpoint requires --checkpoint')
        if args.checkpoint:
            if receipt.get('schema') != 'neyvia.c7e-progress.v1' or receipt.get('complete'):
                raise ValueError('A current incomplete progress receipt is required')
            if receipt.get('sourceCurrent') is not (not args.historical_checkpoint):
                raise ValueError('Checkpoint source-current declaration differs from retention mode')
            from grant_agent.edge_fixture_catalog import completed_receipts
            current = (json.loads((campaign / 'semantic-fixtures/families.json').read_bytes())
                       if args.historical_checkpoint else completed_receipts(campaign / 'semantic-fixtures'))
            projected = []
            for entry in current:
                path = Path(entry['path']).resolve()
                path.relative_to(campaign / 'semantic-fixtures')
                if sha(path) != entry['sha256']:
                    raise ValueError('Historical family bytes differ')
                family = json.loads(path.read_bytes())
                if family['family'] != entry['family'] or not family['sourceStable'] or not entry['sourceStable']:
                    raise ValueError('Invalid original family binding')
                rows = family['rows']
                projected.append({**{k: entry[k] for k in ('family', 'path', 'sha256', 'sourceStable')},
                                  'cases': len(rows), 'counts': dict(Counter(row['status'] for row in rows))})
            if projected != receipt['familyReceipts']:
                raise ValueError('Checkpoint families differ from the current intact family index')
        elif not receipt['ok'] or not receipt['fixturesAccounted']:
            raise ValueError('A finished, sealed full campaign is required')
        used = text_references()
    # Each inherited loose duplicate must match the verified recovery archive.
    loose = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard', '-z', 'scripts/evidence/C7d*'], cwd=REPO, capture_output=True, check=True).stdout.decode().split('\0')
    redundant = []
    with zipfile.ZipFile(REPO / 'scripts/evidence/C7e-recovered.zip') as archive:
        manifest = {r['path']: r for r in json.loads(archive.read('manifest.json'))}
        for name in loose:
            if not name: continue
            path = (REPO / name).resolve()
            path.relative_to(REPO / 'scripts/evidence')
            if name not in manifest or sha(path) != manifest[name]['sha256']:
                raise ValueError('Unarchived or changed inherited work: ' + name)
            if name.casefold() not in used and path.as_posix().casefold() not in used:
                redundant.append(path)
    if args.apply:
        for path in redundant:
            path.unlink()
    if args.deadline:
        roots = [Path(value).resolve() for value in deadline_report['proofRoots']]
    else:
        roots = [p for base in (REPO / '.agent_control', REPO / '.agent_control/proofs') for p in base.iterdir()
                 if p.name.lower().startswith('c7') and p.is_dir() and not p.is_symlink() and not p.is_junction()]
    files = set()
    for root in roots:
        files.update(files_in(root))
        print(json.dumps({'retentionStage': 'enumerated', 'root': root.name, 'files': len(files)}), flush=True)
    retained = retain_committed_references(files, used)
    # Explicit wheel preserves the dependency reproducibly; extracted libraries
    # are disposable after all workers stop. Protected fixture bytes are unread.
    candidates = files - retained
    before = sum(p.stat().st_size for p in files)
    report = {'schema': 'neyvia.c7e-retention.v1', 'ok': True, 'applied': args.apply,
              'mode': 'deadline-incomplete' if args.deadline else 'checkpoint' if args.checkpoint else 'sealed-campaign', 'completionClaimed': False,
              'caseSourceCurrentClaimed': not args.historical_checkpoint,
              'bytesBefore': before, 'filesBefore': len(files), 'referencedFiles': len(retained),
              'unreferencedFiles': len(candidates), 'inheritedLooseDuplicates': len(redundant),
              'protectedReferencesUnread': sum(protected(p) for p in retained)}
    if args.deadline:
        report.update(deadlineReceipt={'path': Path(args.deadline).resolve().relative_to(REPO).as_posix(),
                                       'sha256': sha(args.deadline)},
                      deadlineComplete=False, deadlineFamilyCount=deadline_report['completedFamilies'],
                      deadlineCaseTotals=deadline_report['caseTotals'],
                      scopeGap='C7 task-local retention only; no service-wide Neyvia retention behavior is claimed.')
    print(json.dumps(report), flush=True)
    if not args.apply:
        return
    manifest = [{'path': p.relative_to(REPO).as_posix(), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(retained) if not protected(p)]
    for path in sorted(candidates):
        path.relative_to(REPO / '.agent_control')
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Prune scope changed')
        if not path.stat().st_mode & stat.S_IWRITE:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
        path.unlink()
    for row in manifest:
        if sha(REPO / row['path']) != row['sha256']:
            raise ValueError('Retained proof changed')
    prefix = 'C7e-deadline-retention' if args.deadline else 'C7e-checkpoint-retention' if args.checkpoint else 'C7e-retention'
    target = REPO / 'scripts/evidence' / (prefix + '-manifest.json.gz')
    raw = json.dumps(manifest, separators=(',', ':')).encode()
    target.write_bytes(gzip.compress(raw, mtime=0))
    if gzip.decompress(target.read_bytes()) != raw:
        raise ValueError('Retention manifest differs')
    report.update(bytesAfter=sum(p.stat().st_size for p in retained), allRetainedUnprotectedBytesVerified=True,
                  manifest={'path': target.relative_to(REPO).as_posix(), 'sha256': sha(target), 'bytes': target.stat().st_size},
                  boundary='Only validated task C7 roots and archive-verified inherited loose duplicates; protected credential fixture contents never read, hashed or archived.')
    (REPO / 'scripts/evidence' / (prefix + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
