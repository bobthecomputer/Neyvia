"""Real local observer streams, immutable paging and large delta artifacts."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, guards, typed_projection


def run(port, output):
    if port != 48829:
        raise ValueError('Explicit assigned projection port48829 required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-projection-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.cl import manual_projection_effects as adapter
    bus = bus_for(root)
    notes = root / 'notes'
    notes.mkdir()
    bus.put('notes:folder', str(notes))
    for name in ('alpha', 'beta'):
        (notes / (name + '.md')).write_text('# ' + name + '\nFirst observation body.\n', encoding='utf-8')
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    actions = {}
    sources = [REPO / 'src/grant_agent/cl/manual_projection_effects.py',
               REPO / 'manuals/manuals-next.manual.json', REPO / 'manuals/cl/manuals-next.cl', Path(__file__)]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    start = hashes()
    def cl(label, name, args, selected_gateway=gateway):
        protocol = Protocol(selected_gateway, lazy_manuals=True)
        source = 'G local: time.now()["unixSeconds"] > 0\n' + name + '(' + ', '.join(
            key + '=' + json.dumps(value, ensure_ascii=False) for key, value in args.items()) + ')\ndone()'
        result = protocol.run(source, action_id='FIXCL3-projection-' + label)
        if result.get('status') == 'frontier' and protocol._effect_sources() != protocol.effect_source_bindings:
            actions[label + '-stale-source-refusal'] = result
            protocol = Protocol(selected_gateway, lazy_manuals=True)
            result = protocol.run(source, action_id='FIXCL3-projection-' + label)
        actions[label] = result
        (root / 'partial-actions.json').write_text(json.dumps(actions, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        return protocol, result
    def handles():
        return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (root / '.neyvia/manual-state').glob('*.json')}
    obs_args = {'id': 'notes', 'chapter': 'overview', 'state': 'current', 'stream': 'small'}
    initial_protocol, initial = cl('observe-snapshot', 'manual.observe', obs_args)
    first_rows = handles()
    first = next(iter(first_rows))
    first_raw = (root / '.neyvia/manual-state' / (first + '.json')).read_bytes()
    before_completion = initial_protocol.completion()
    (notes / 'alpha.md').write_text('# Alpha changed\nA fresh body has appeared.\n', encoding='utf-8')
    after_completion = initial_protocol.completion()
    _, diff = cl('observe-diff', 'manual.observe', obs_args)
    after_rows = handles()
    second = next(identity for identity in after_rows if identity not in first_rows)
    project_args = {'handle': second, 'path': '/notes', 'offset': 0, 'limit': 1}
    _, projected = cl('project-page', 'manual.project', project_args)
    _, project_procedure = cl('project-procedure', 'run manuals-next.verified-project', project_args)
    protocol = Protocol(gateway, lazy_manuals=True)
    expected = adapter._projection(protocol, project_args)
    original_second = (root / '.neyvia/manual-state' / (second + '.json')).read_bytes()
    forged = json.loads(original_second)
    forged['value']['notes'][0]['title'] = 'Same handle, corrupted content'
    (root / '.neyvia/manual-state' / (second + '.json')).write_text(json.dumps(forged, indent=2) + '\n', encoding='utf-8')
    _, corrupt = cl('project-corrupt-handle', 'manual.project', project_args)
    (root / '.neyvia/manual-state' / (second + '.json')).write_bytes(original_second)
    size_before = len(handles())
    _, wrong_stream = cl('observe-cross-stream-refusal', 'manual.observe', {**obs_args, 'stream': 'other', 'previousHandle': first})
    _, restricted = cl('observe-source-scope-refusal', 'manual.observe', {**obs_args, 'scopeTools': ['neyvia.time.now']})
    scope_conserved = len(handles()) == size_before
    readonly_gateway = NeyviaToolGateway(root, allow_mutations=False, permission_mode='read-only')
    _, readonly_projection = cl('project-read-only-caller', 'manual.project', project_args, readonly_gateway)
    _, readonly_observe = cl('observe-read-only-caller-refusal', 'manual.observe', obs_args, readonly_gateway)
    readonly_conserved = len(handles()) == size_before
    _, reset = cl('observe-reset', 'manual.observe', {**obs_args, 'reset': True})
    reset_rows = handles()
    reset_handle = next(identity for identity in reset_rows if identity not in after_rows)
    for index in range(60):
        (notes / f'large-{index:02}.md').write_text('# Large subject ' + str(index) + '\n' + 'A' * 650 + '\n', encoding='utf-8')
    large_args = {**obs_args, 'stream': 'large'}
    _, large = cl('observe-large-handle', 'manual.observe', large_args)
    large_rows = handles()
    large_handle = next(identity for identity in large_rows if identity not in reset_rows)
    _, too_large = cl('project-too-large', 'manual.project', {'handle': large_handle, 'path': '', 'offset': 0, 'limit': 20})
    _, bounded = cl('project-deeper-bounded', 'manual.project', {'handle': large_handle, 'path': '/notes', 'offset': 5, 'limit': 2})
    for index in range(60):
        (notes / f'large-{index:02}.md').write_text('# Changed subject ' + str(index) + '\n' + 'B' * 650 + '\n', encoding='utf-8')
    _, large_diff = cl('observe-large-diff-handle', 'manual.observe', large_args)
    final_rows = handles()
    additions = {k: v for k, v in final_rows.items() if k not in large_rows}
    diff_handle = next((k for k, v in additions.items() if isinstance(v['value'], list)), None)
    if diff_handle:
        _, delta_page = cl('project-diff-page', 'manual.project', {'handle': diff_handle, 'path': '', 'offset': 0, 'limit': 2})
    else:
        delta_page = {'ok': False}
    uses = [row['payload'] for row in bus.since(0) if row['action'] == 'cl.manual.use']
    checks = {
        'snapshot_positive_cl_and_fresh_source_completion': initial.get('ok') is True and before_completion.get('status') == 'completed',
        'source_drift_invalidates_observation_completion': after_completion.get('status') == 'incomplete',
        'diff_positive_cl_new_immutable_artifact': diff.get('ok') is True and second != first,
        'old_snapshot_bytes_immutable': (root / '.neyvia/manual-state' / (first + '.json')).read_bytes() == first_raw,
        'projection_positive_cl_exact_independent_page': projected.get('ok') is True and expected['value'] == after_rows[second]['value']['notes'][:1] and expected['nextOffset'] == 1,
        'pure_projection_manual_procedure_completed': project_procedure.get('ok') is True,
        'corrupt_handle_refused': corrupt.get('ok') is False,
        'cross_stream_and_scope_refused_before_new_handle': wrong_stream.get('ok') is False and restricted.get('ok') is False and scope_conserved,
        'projection_preserves_read_only_authority': readonly_projection.get('ok') is True and readonly_observe.get('ok') is False and readonly_conserved,
        'reset_creates_snapshot_instead_of_diff': reset.get('ok') is True and reset_handle != second,
        'large_observation_creates_handle': large.get('ok') is True and len(json.dumps(large_rows[large_handle]['value'])) > 4000,
        'large_projection_bounded_without_value_paste': too_large.get('ok') is True and len(json.dumps(large_rows[large_handle]['value'])) > 8000,
        'deeper_projection_completes': bounded.get('ok') is True,
        'large_delta_has_independent_retained_handle': large_diff.get('ok') is True and diff_handle is not None and delta_page.get('ok') is True,
        'typed_scalar_wire_projection': all(typed_projection(actions[label].get('text', '')) for label in ('observe-snapshot', 'project-page', 'observe-large-handle', 'project-deeper-bounded')),
        'both_adapters_current_manual_receipts': all(any(u['tool'] == name and u['status'] == 'admitted' for u in uses) for name in ('neyvia.manual.observe', 'neyvia.manual.project')),
        'pure_projection_fresh_gate_executed': all(any(check.get('name') == 'effect-manual-project' and check.get('passed') is True
            for row in actions[label].get('results', []) for check in row.get('checks', [])) for label in ('project-page', 'project-read-only-caller', 'project-deeper-bounded')),
        'source_unchanged': hashes() == start}
    result = {'schema': 'neyvia.FIXCL3.projection.v1', 'root': str(root), 'port': port,
        'sourceHashesAtStart': start, 'sourceHashesAtEnd': hashes(), 'actions': actions, 'checks': checks,
        'firstHandle': first, 'secondHandle': second, 'resetHandle': reset_handle, 'largeHandle': large_handle,
        'largeDiffHandle': diff_handle, 'expectedPageIndependentlyRead': expected,
        'initialCompletion': before_completion, 'completionAfterSourceDrift': after_completion,
        'manualUses': uses, 'handleFileHashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / '.neyvia/manual-state').glob('*.json')},
        'boundary': ['Real Notes source observer, immutable handle/stream artifacts and independent projection byte checks',
                     'Projection returns retained immutable values; it does not claim old source values are current',
                     'Volatile or mutating source observers cannot claim a freshly verified retained local observation']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'checks': checks}))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(args.port, args.output))
