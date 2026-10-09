"""Reuse source-bound execution of passing outcomes, never declared ownership."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import codecs
import json
from pathlib import Path
import types

SCHEMA = 'neyvia.contract-execution-cache.v1'


def outcome_passes(report):
    """A positive summary cannot override any explicit failed witness."""
    if not isinstance(report, dict) or report.get('ok') is not True or report.get('failures'):
        return False
    for field in ('cases', 'checks', 'outcomes', 'contracts'):
        for row in report.get(field, []):
            if isinstance(row, dict) and (row.get('ok') is False
                    or str(row.get('status', '')).casefold() in {'fail', 'failed', 'error'}):
                return False
    return True


def _content_hashes(raw):
    raw_sha = hashlib.sha256(raw).hexdigest()
    try:
        normalized = raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
    except UnicodeDecodeError:
        normalized = raw
    return hashlib.sha256(normalized).hexdigest(), raw_sha


def _snapshot_entry(path, snapshot=None):
    path = Path(path).resolve()
    key = str(path)
    if snapshot is not None and key in snapshot:
        return snapshot[key]
    hashes = _path_hashes(path)
    entry = {'hashes': hashes}
    if snapshot is not None:
        snapshot[key] = entry
    return entry


def _path_hashes(path):
    """Hash source bytes with bounded buffers, preserving LF-normalized digests."""
    raw_hash, normalized_hash = hashlib.sha256(), hashlib.sha256()
    decoder = codecs.getincrementaldecoder('utf-8')()
    valid_utf8, carry = True, b''
    with Path(path).open('rb') as source:
        while chunk := source.read(65536):
            raw_hash.update(chunk)
            if valid_utf8:
                try: decoder.decode(chunk, final=False)
                except UnicodeDecodeError: valid_utf8 = False
            combined = carry + chunk
            carry = b'\r' if combined.endswith(b'\r') else b''
            normalized_hash.update((combined[:-1] if carry else combined).replace(b'\r\n', b'\n'))
    normalized_hash.update(carry)
    if valid_utf8:
        try: decoder.decode(b'', final=True)
        except UnicodeDecodeError: valid_utf8 = False
    raw_sha = raw_hash.hexdigest()
    return normalized_hash.hexdigest() if valid_utf8 else raw_sha, raw_sha


def _digests(path, snapshot=None):
    # Reuse bytes only inside an explicit admission snapshot. Never key a
    # correctness decision to timestamps, which are not content-change tokens
    # on every supported filesystem.
    return _snapshot_entry(path, snapshot)['hashes']


def digest(path, snapshot=None):
    return _digests(path, snapshot)[0]


def hashes(path, snapshot=None):
    return set(_digests(path, snapshot))


def _json(path, snapshot):
    entry = _snapshot_entry(path, snapshot)
    if 'json' not in entry:
        with Path(path).resolve().open(encoding='utf-8') as source:
            parsed = json.load(source)
        if _path_hashes(path) != entry['hashes']:
            raise ValueError('Receipt changed during measured-cache validation')
        entry['json'] = parsed
    return entry['json']


def spec_digest(row):
    spec = {key: value for key, value in row.items() if key not in {'areas', 'source'}}
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_cache(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'schema': SCHEMA, 'records': []}
    if data.get('schema') != SCHEMA or not isinstance(data.get('records'), list):
        raise ValueError('Invalid measured coverage cache')
    return data


def write_cache(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from .durability import atomic_write_json
    atomic_write_json(path, {'schema': SCHEMA, 'records': records})


def owned_receipt(repo, path):
    path=Path(path).resolve()
    if not any(path.is_relative_to(parent.resolve()) for parent in
               [Path('D:/NeyviaRuns'),repo/'.agent_control/p22']):
        raise ValueError('Execution receipt must stay in the owned evidence roots')
    return path


def source_path(repo, name):
    if not isinstance(name,str) or Path(name).is_absolute():raise ValueError('Invalid relative source binding')
    path=(repo/name).resolve()
    if not path.is_relative_to(repo.resolve()):raise ValueError('Source binding escapes candidate')
    return path


def scope_binding(repo, trace, *, snapshot=None):
    """Validate scoped observations without granting the scope execution credit."""
    scope = trace.get('traceScope')
    if scope is None: return None  # Previously measured and browser receipts.
    if not isinstance(scope, dict) or scope.get('schema') != 'neyvia.python-trace-scope.v1':
        raise ValueError('Invalid execution trace scope')
    path = owned_receipt(repo, scope['path'])
    if _digests(path, snapshot)[1] != scope.get('sha256'):
        raise ValueError('Execution trace scope changed')
    document = _json(path, {} if snapshot is None else snapshot)
    if (not isinstance(document, dict) or not isinstance(document.get('files'), dict)
            or document.get('files') != scope.get('files') or document.get('pathPolicy') != scope.get('pathPolicy')):
        raise ValueError('Scope receipt differs from the executed scope')
    policy = scope['pathPolicy']
    if not isinstance(policy, dict): raise ValueError('Invalid trace path-policy binding')
    if policy.get('origin') == 'repository': policy_path = repo/'config/contract_path_policy.json'
    elif policy.get('origin') == 'bundled-default': policy_path = Path(__file__).resolve().parents[2]/'config/contract_path_policy.json'
    else: raise ValueError('Unknown trace path-policy origin')
    if _digests(policy_path, snapshot)[1] != policy.get('sha256'):
        raise ValueError('Trace path policy changed')
    for name, row in trace.get('files', {}).items():
        declared = document['files'].get(name)
        if not isinstance(declared, dict) or not isinstance(row, dict): raise ValueError('Observed file is outside the trace scope')
        if (row.get('lineData') is True and declared.get('lineData') is True
                and not set(row.get('lines', [])) <= set(declared.get('lines', []))):
            raise ValueError('Observed lines are outside the trace scope')
    return {'path': str(path), 'sha256': scope['sha256'], 'pathPolicy': policy}


def measured_record(repo, area, identities, trace, contracts, *, receipt=None, manifest=None):
    """Call only after all requested witnesses and the outcome itself passed."""
    if trace.get('ok') is not True or trace.get('sourceStable') is not True:
        raise ValueError('Failed or unstable execution cannot supply coverage')
    if not set(identities) <= set(trace.get('contracts', [])):
        raise ValueError('Trace omitted requested passing outcome identities')
    scoped = scope_binding(repo, trace)
    files, bindings, absent = {}, {}, set()
    for name, row in trace.get('files', {}).items():
        path = (repo/name).resolve()
        if not path.is_relative_to(repo.resolve()) or not path.is_file():
            raise ValueError('Execution source is outside the candidate: '+name)
        if row.get('sha256') not in hashes(path):
            raise ValueError('Executed source changed before receipt admission: '+name)
        files[name] = {**row, 'sha256': digest(path)}
        bindings[name] = files[name]['sha256']
    # Specifications and their actual adapter are inputs to the observation.
    if manifest:
        paths = [manifest.get('_source', 'config/proofs/'+area+'.json')]
        module = manifest.get('module', '')
        runner = manifest.get('runner')
        if module: paths.append('src/'+module.replace('.', '/')+'.py')
        if runner: paths.append(runner)
        paths.extend(manifest.get('sourceFiles', []))
        for name in paths:
            path = source_path(repo, name)
            if path.is_file(): bindings[name] = digest(path)
            else: absent.add(name)
    from .contract_gate import sites
    for identity in identities:
        spec=contracts[identity]
        names={spec.get('source')} | {name for site in spec.get('checkedAt',[]) for name in sites(site)}
        for name in names:
            if name:
                if source_path(repo,name).is_file():bindings[name]=digest(repo/name)
                else:absent.add(name)
    if not receipt:raise ValueError('A passing execution receipt is required')
    path=owned_receipt(repo,receipt)
    if json.loads(path.read_text(encoding='utf-8')) != trace:
        raise ValueError('Execution receipt differs from the admitted observation')
    receipt_row = {'path': str(path), 'sha256': digest(path)}
    return {'area': area, 'measurementUnit':'passing outcome group', 'contracts': sorted(identities), 'files': files,
            'sourceBindings': bindings, 'absentSources': sorted(absent),
            'specs': {identity: spec_digest(contracts[identity]) for identity in identities},
            'receipt': receipt_row, 'scopeBinding': scoped}


def fresh(record, repo, contracts, *, snapshot=None):
    if not isinstance(record,dict):return False
    if not record.get('contracts') or not record.get('files'):
        return False
    # An omitted snapshot is local to this call, so later calls always reread
    # current bytes while all checks within this call see the same receipt.
    snapshot = {} if snapshot is None else snapshot
    try:
        for identity in record['contracts']:
            if identity not in contracts or record.get('specs', {}).get(identity) != spec_digest(contracts[identity]):return False
        if any(source_path(repo,name).exists() for name in record.get('absentSources',[])):return False
        from .contract_gate import sites
        for identity in record['contracts']:
            spec=contracts[identity]
            required={spec.get('source')} | {name for site in spec.get('checkedAt',[]) for name in sites(site)}
            if any(name and name not in record['sourceBindings'] and name not in record.get('absentSources',[])
                   for name in required):return False
        if any(digest(source_path(repo,name), snapshot) != sha for name, sha in record['sourceBindings'].items()): return False
        receipt = record.get('receipt')
        if not receipt:return False
        path=owned_receipt(repo,receipt['path'])
        trace = _json(path, snapshot)
        if digest(path, snapshot) != receipt['sha256']:return False
        if trace.get('ok') is not True or trace.get('sourceStable') is not True:return False
        if record.get('scopeBinding') != scope_binding(repo, trace, snapshot=snapshot):return False
        if set(record['contracts']) != set(trace.get('contracts',[])):return False
        if set(record['files']) != set(trace.get('files',{})):return False
        for name,row in record['files'].items():
            observed=trace['files'][name]
            if observed.get('sha256') not in hashes(source_path(repo,name), snapshot):return False
            if row.get('sha256') != record['sourceBindings'].get(name):return False
            if row.get('lines') != observed.get('lines') or row.get('lineData') != observed.get('lineData'):return False
            if row.get('kind') != observed.get('kind'):return False
    except (OSError,ValueError,KeyError,TypeError):
        return False
    return True


def import_index(repo, path, contracts, manifests):
    """Admit only the independently passing worker receipts in a measured batch."""
    path=owned_receipt(repo,path)
    index=json.loads(path.read_text(encoding='utf-8'))
    if index.get('schema') != 'neyvia.execution-measurement.v1':raise ValueError('Unknown measurement index')
    records=[]
    selected = [(area, None) for area in index.get('areasPassing', []) if isinstance(area, str)]
    passing_areas = {area for area, _ in selected}
    for partial in index.get('areasPartial', []):
        if not isinstance(partial, dict) or partial.get('ok') is not True or partial.get('status') != 'partial':
            continue
        area = partial.get('area')
        if (not isinstance(area, str) or not area or Path(area).name != area
                or area in passing_areas):
            continue
        requested = partial.get('requestedContracts')
        passed = partial.get('passedContracts')
        excluded = partial.get('excludedIDs', partial.get('notAvailableContracts', {}))
        if isinstance(excluded, dict):
            excluded = list(excluded)
        if (not isinstance(requested, list) or not requested
                or not all(isinstance(item, str) and item for item in requested)
                or len(set(requested)) != len(requested)
                or not isinstance(passed, list)
                or not all(isinstance(item, str) and item for item in passed)
                or len(set(passed)) != len(passed) or set(passed) != set(requested)
                or not isinstance(excluded, list)
                or not all(isinstance(item, str) and item for item in excluded)
                or set(requested) & set(excluded)):
            continue
        selected.append((area, set(requested)))
        passing_areas.add(area)
    for area, partial_contracts in selected:
        folder=path.parent/area
        outcome=json.loads((folder/'outcomes.json').read_text(encoding='utf-8'))
        trace_path=folder/'execution.json'
        trace=json.loads(trace_path.read_text(encoding='utf-8'))
        if not outcome_passes(outcome):raise ValueError('Failed or contradictory outcome in passing measurement index')
        witnessed={identity for case in outcome.get('cases',[]) if case.get('ok') is True
                   for identity in case.get('contracts',[case.get('id')]) if identity}
        witnessed.update(row if isinstance(row,str) else row.get('id') for row in outcome.get('contracts',[])
                         if isinstance(row,str) or row.get('status')=='passed')
        witnessed.update(row.get('id') for row in outcome.get('outcomes',[]) if row.get('status')=='PASS')
        identities=trace.get('contracts',[])
        if not identities or not set(identities)<=witnessed:raise ValueError('Measured outcome omitted passing witnesses')
        if partial_contracts is not None:
            if (trace.get('ok') is not True or trace.get('sourceStable') is not True
                    or set(identities) != partial_contracts):
                continue
        records.append(measured_record(repo,area,identities,trace,contracts,receipt=trace_path,manifest=manifests.get(area)))
    return records


def executable_lines(path):
    """Python comments/blank lines have no executable changed-line obligation."""
    if Path(path).suffix != '.py': return None
    try: code = compile(Path(path).read_text(encoding='utf-8-sig'), str(path), 'exec')
    except (OSError, SyntaxError): return None
    pending, lines = [code], set()
    while pending:
        current = pending.pop()
        lines.update(line for _, _, line in current.co_lines() if line)
        pending.extend(value for value in current.co_consts if isinstance(value, types.CodeType))
    return lines


def admission(repo, details, records, contracts):
    snapshot = {}
    valid = [row for row in records if fresh(row, repo, contracts, snapshot=snapshot)]
    observed = defaultdict(list)
    for record in valid:
        for name, row in record['files'].items(): observed[name].append((record, row))
    coverage, uncovered, missing_lines, no_executable = {}, [], {}, []
    for name, change in details.items():
        if change['status'] == 'deleted': continue
        entries = observed.get(name, [])
        lines = set(change.get('lines', []))
        executable = executable_lines(repo/name)
        if change.get('lineData') is True and executable is not None:
            lines &= executable
            if not lines:
                no_executable.append(name)
                continue
        passed, seen = set(), set()
        for record, row in entries:
            # Opening an input (including for hashing) is not execution.
            # Keep these reads bound for invalidation, never as coverage credit.
            if row.get('kind') == 'configuration-read':continue
            measured = set(row.get('lines', []))
            seen.update(measured)
            if change.get('lineData') is not True or row.get('lineData') is not True or bool(lines & measured):
                passed.update(record['contracts'])
        if passed: coverage[name] = sorted(passed)
        else: uncovered.append(name)
        if lines and lines-seen: missing_lines[name] = sorted(lines-seen)
    return {'coverage': coverage, 'uncovered': sorted(uncovered), 'unexecutedChangedLines': missing_lines,
            'noExecutableChanges': no_executable, 'validRecords': len(valid)}


def impacted(records, changed, contracts):
    """An old trace is an impact edge even when its hashes require remeasurement."""
    changed = set(changed)
    return {identity for row in records if changed & set(row.get('sourceBindings', {}))
            for identity in row.get('contracts', []) if identity in contracts}
