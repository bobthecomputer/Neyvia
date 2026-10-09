"""Check or reconcile authored CL action schemas with the registered native tools.

Repair writes CL sources only; run cl_compile_manuals.py afterwards. Excluded
manuals remain in the check, so another owner's drift is never hidden.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def project_changes(source, data, changed_schemas, changed_records):
    """Preserve unrelated source text, proof records and parameter ordering."""
    from grant_agent.cl.manuals import _source_lines, cl_to_manual
    from grant_agent.cl.schema import schema_to_type
    lines = source.splitlines(keepends=True)
    header_index = next(i for i, line in enumerate(lines) if line.startswith('-- @manual '))
    header = json.loads(lines[header_index][len('-- @manual '):])
    occupied = {line.split()[1] for line in lines if line.startswith('T ')}
    declarations = []
    for name in sorted(changed_schemas):
        alias = 'live_schema_' + str(len(occupied) + 1)
        while alias in occupied: alias += '_'
        occupied.add(alias)
        header['schemas'][name] = alias
        declarations.append('T ' + alias + ' ' + schema_to_type(data['schemas'][name]) + '\n')
    output, i = [], 0
    while i < len(lines):
        line = lines[i]
        if i == header_index:
            output.append('-- @manual ' + json.dumps(header, sort_keys=True, separators=(',', ':')) + '\n')
            output.extend(declarations)
        elif line.startswith('-- @record '):
            record = json.loads(line[len('-- @record '):])
            if (record['chapter'], record['section'], record['key']) in changed_records:
                chapter = data['chapters'][record['chapter']]
                if record['key'] in chapter[record['section']]:
                    row = chapter[record['section']][record['key']]
                    record['data'] = row
                    output.append('-- @record ' + json.dumps(record, separators=(',', ':')) + '\n')
                    output.extend(value + '\n' for value in _source_lines(
                        record['section'], record['key'], row, chapter, data['schemas'],
                        data['id'], header['tool_metadata'], version=header.get('clVersion', '1.0')))
                i += 1
                while i < len(lines) and not lines[i].startswith(('-- @record ', 'L ', 'T ', '--')): i += 1
                continue
            output.append(line)
        else: output.append(line)
        i += 1
    updated = ''.join(output)
    if cl_to_manual(updated) != data: raise ValueError('Repaired CL projection differs: ' + data['id'])
    return updated


def reconcile(data, registry):
    from jsonschema import Draft202012Validator
    revised = deepcopy(data)
    schemas, records, tools, live_schemas = set(), set(), set(), {}
    for chapter_name, chapter in revised['chapters'].items():
        for key, action in chapter['actions'].items():
            name = action['schema']
            live = registry.describe(action['tool'])['inputSchema']
            if name in live_schemas and live_schemas[name] != live:
                raise ValueError('Actions with different live schemas share ' + name)
            live_schemas[name] = live
            if data['schemas'][name] != live:
                revised['schemas'][name] = deepcopy(live)
                schemas.add(name); tools.add(action['tool']); records.add((chapter_name, 'actions', key))
    for chapter_name, chapter in revised['chapters'].items():
        for key, procedure in chapter['procedures'].items():
            for step in procedure['steps']:
                if 'action' not in step: continue
                action = chapter['actions'][step['action']]
                if action['schema'] not in schemas: continue
                fields = revised['schemas'][action['schema']].get('properties', {})
                for name, reference in step['args'].items():
                    if not isinstance(reference, dict) or set(reference) not in ({'$input'}, {'$path'}): continue
                    field = next(iter(reference.values()))
                    inputs = procedure['inputs'].get('properties', {})
                    if field not in inputs or name not in fields: continue
                    old, live = inputs[field], fields[name]
                    if 'const' in old and Draft202012Validator(live).is_valid(old['const']): continue
                    if any(old.get(k) != v for k, v in live.items()
                           if k not in {'description', 'title', 'default', '$schema', 'examples'}):
                        inputs[field] = deepcopy(live)
                        if 'default' in old and Draft202012Validator(live).is_valid(old['default']):
                            inputs[field]['default'] = old['default']
                        records.add((chapter_name, 'procedures', key))
    return revised, schemas, records, sorted(tools)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual', action='append')
    parser.add_argument('--exclude', action='append', default=[], help='Report but never edit this manual')
    parser.add_argument('--check', action='store_true', help='Read-only drift, artifact and semantic validation')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0')
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.neyvia_manuals import validate
    from grant_agent.cl.manuals import cl_to_manual
    registry = NativeToolRegistry(REPO / '.agent_control/rel29-cl-drift/runtime')
    rows, pending = [], []
    for path in sorted((REPO / 'manuals/cl').glob('*.cl')):
        raw = path.read_bytes(); source = raw.decode('utf-8')
        if '-- @manual ' not in source: continue  # CL-Skills have no native schema catalog.
        data = cl_to_manual(source)
        if args.manual and data['id'] not in args.manual: continue
        revised, schemas, records, tools = reconcile(data, registry)
        excluded = data['id'] in args.exclude
        candidate = data if args.check or excluded else revised
        row = {'manual': data['id'], 'source': path.relative_to(REPO).as_posix(),
               'sourceSha256': hashlib.sha256(raw).hexdigest(), 'driftingActions': tools, 'excluded': excluded}
        try: validate(candidate, registry); row['grounded'] = True
        except Exception as error: row.update(grounded=False, validationError=str(error))
        if args.check:
            artifact = REPO / 'manuals' / (data['id'] + '.manual.json')
            row['artifactEqual'] = artifact.is_file() and json.loads(artifact.read_bytes()) == data
        elif schemas and not excluded:
            if not row['grounded']: raise ValueError(data['id'] + ': ' + row['validationError'])
            updated = project_changes(source, revised, schemas, records)
            ending = '\r\n' if b'\r\n' in raw else '\n'
            pending.append((path, raw, updated.replace('\r\n', '\n').replace('\n', ending).encode('utf-8')))
        rows.append(row)
        if tools or not row['grounded']: print(json.dumps(row), flush=True)
    # Prepare every candidate first; refuse to overwrite edits made during repair.
    for path, original, _ in pending:
        if path.read_bytes() != original: raise ValueError('CL source changed during repair: ' + str(path))
    for path, _, revised in pending: path.write_bytes(revised)
    report = {'schema': 'neyvia.cl.native-schema-drift.v1', 'checkedManuals': len(rows),
              'driftingManuals': sum(bool(row['driftingActions']) for row in rows),
              'validationFailures': sum(not row['grounded'] for row in rows),
              'repairedManuals': len(pending), 'manuals': rows}
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'manuals'}))
    if args.check and (report['driftingManuals'] or report['validationFailures']
                       or any(not row['artifactEqual'] for row in rows)): return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
