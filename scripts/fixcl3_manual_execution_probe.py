"""Real checked cohorts, zero-model compiled writes and exact failure recovery."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from fixcl_verify import REPO, environment, guards


def run(port, output):
    if port not in range(48821, 48830):
        raise ValueError('Explicit assigned FIXCL3 port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-manual-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.ui_command_bus import bus_for
    bus = bus_for(root)
    notes = root / 'notes'
    notes.mkdir()
    bus.put('notes:folder', str(notes))
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    actions = {}
    def native(name, args, identity):
        protocol = Protocol(gateway)
        return unwrap(protocol.action_output(name, gateway.call_native(name, args, action_id=identity)))
    # A real reviewed workspace-local manual extension creates a deterministic
    # write+read verifier fixture; source/manuals in the checkout stay unchanged.
    procedure = {'goal': 'Write one scoped disposable note and freshly verify its exact body',
        'inputs': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'body': {'type': 'string'}},
                   'required': ['path', 'body'], 'additionalProperties': False},
        'steps': [{'action': 'notes.write', 'args': {'path': {'$input': 'path'}, 'body': {'$input': 'body'}},
                   'save': 'written', 'check': 'body-saved'}]}
    version = native('neyvia.manual.versions', {'id': 'notes'}, 'fixture-version')
    patch = native('neyvia.manual.frontier', {'id': 'notes', 'note': 'Disposable deterministic checked-write journey',
        'observed': {'fixture': True}, 'operations': [{'op': 'add',
            'path': '/chapters/overview/procedures/fixture-verified-write', 'value': procedure}]}, 'fixture-patch')
    promoted = native('neyvia.manual.patch.apply', {'id': 'notes', 'patchId': patch['patchId'],
        'expectedSha256': version['sha256'], 'approved': True, 'reviewer': 'FIXCL3 disposable fixture',
        'evidence': ['Explicitly scoped local fixture using existing real notes action and body observer']}, 'fixture-promote')
    source_paths = [REPO / 'src/grant_agent/cl/manual_execution_effects.py',
        REPO / 'manuals/manuals-next.manual.json', REPO / 'manuals/cl/manuals-next.cl', Path(__file__)]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    before_hashes = hashes()
    def cl(label, name, args):
        protocol = Protocol(gateway)
        source = 'G local: time.now()["unixSeconds"] > 0\n' + name + '(' + ', '.join(
            key + '=' + json.dumps(value, ensure_ascii=False) for key, value in args.items()) + ')\ndone()'
        result = protocol.run(source, action_id='FIXCL3-manual-' + label)
        if result.get('status') == 'frontier' and protocol._effect_sources() != protocol.effect_source_bindings:
            # Another authorized owner changed effect code while this context
            # was admitted. The host refused before dispatch. Preserve that
            # refusal and create one new context against current exact source.
            actions[label + '-stale-source-refusal'] = result
            protocol = Protocol(gateway)
            result = protocol.run(source, action_id='FIXCL3-manual-' + label)
        actions[label] = result
        (root / 'partial-actions.json').write_text(json.dumps(actions, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        return protocol, result
    inputs = {'path': 'cohort.md', 'body': '# Exact cohort\nA real checked body.\n'}
    args = {'id': 'notes', 'chapter': 'overview', 'procedure': 'fixture-verified-write', 'inputs': inputs}
    cohort = [cl('run-' + str(index), 'manual.run', args)[1] for index in range(3)]
    ordinary = [json.loads(path.read_text(encoding='utf-8')) for path in (root / '.neyvia/manual-runs').glob('*.json')]
    compile_args = {**args, 'minRuns': 3}
    _, compiled = cl('compile', 'manual.compile', compile_args)
    plans = list((root / '.neyvia/manual-scripts').glob('*.json'))
    plan = json.loads(plans[0].read_text(encoding='utf-8')) if plans else {}
    script_args = {'scriptId': plan.get('scriptId', ''), 'inputs': inputs}
    script_protocol, script = cl('script-run', 'manual.script.run', script_args)
    completion_before = script_protocol.completion()
    (notes / 'cohort.md').write_text('Fresh drift outside expected body.\n', encoding='utf-8')
    completion_after = script_protocol.completion()
    (notes / 'cohort.md').write_text(inputs['body'], encoding='utf-8')
    before = (notes / 'cohort.md').read_bytes()
    _, changed_inputs = cl('script-input-drift', 'manual.script.run', {**script_args, 'inputs': {**inputs, 'body': 'Unlearned body'}})
    input_refusal = changed_inputs.get('ok') is False and (notes / 'cohort.md').read_bytes() == before
    plan_file = plans[0] if plans else None
    original_plan = plan_file.read_bytes() if plan_file else b''
    if plan_file:
        forged = json.loads(original_plan)
        forged['zeroToken'] = not forged['zeroToken']
        plan_file.write_text(json.dumps(forged, indent=2) + '\n', encoding='utf-8')
    _, tampered = cl('script-artifact-drift', 'manual.script.run', script_args)
    plan_refusal = tampered.get('ok') is False and (notes / 'cohort.md').read_bytes() == before
    if plan_file:
        plan_file.write_bytes(original_plan)
    try:
        native('neyvia.manual.run', {'id': 'notes', 'chapter': 'overview',
            'procedure': 'capture-tagged-idea', 'inputs': {'path': 'missing.md', 'idea': 'Recover #proof', 'tag': 'proof'}}, 'actual-missing-note-failure')
    except RuntimeError:
        pass  # The normal gateway correctly raises on this real failed action.
    failures = [json.loads(path.read_text(encoding='utf-8')) for path in (root / '.neyvia/manual-runs').glob('*.json')]
    failed = next(row for row in failures if row['status'] == 'failed')
    missing_before_recovery = not (notes / 'missing.md').exists()
    failure_path = root / '.neyvia/manual-runs' / (failed['runId'] + '.json')
    failure_bytes = failure_path.read_bytes()
    bind_args = {'runId': failed['runId'], 'chapter': 'overview', 'procedure': 'fixture-verified-write',
                 'inputs': {'path': 'missing.md', 'body': 'Recovery writes the missing disposable note.\n'}}
    _, bound = cl('recovery-bind', 'manual.recovery.bind', bind_args)
    recipes = list((root / '.neyvia/manual-recoveries').glob('*.json'))
    recipe = json.loads(recipes[0].read_text(encoding='utf-8')) if recipes else {}
    recover_args = {'runId': failed['runId'], 'recipeId': recipe.get('recipeId', '')}
    _, recovered = cl('recover', 'manual.recover', recover_args)
    run_count = len(list((root / '.neyvia/manual-runs').glob('*.json')))
    _, replayed = cl('recover-replay', 'manual.recover', recover_args)
    uses = [row['payload'] for row in bus.since(0) if row['action'] == 'cl.manual.use']
    checks = {
        'real_checked_cohort_completed': all(row.get('ok') is True for row in cohort) and len(ordinary) == 3 and all(row['status'] == 'completed' and row['checks'] for row in ordinary),
        'compile_cl_completed_from_three_distinct_real_runs': compiled.get('ok') is True and len({row['runId'] for row in plan.get('sourceRuns', [])}) == 3,
        'zero_token_compiled_plan': plan.get('zeroToken') is True,
        'script_cl_completed_fresh_body': script.get('ok') is True and completion_before.get('status') == 'completed',
        'completion_rereads_real_nested_effect': completion_after.get('status') == 'incomplete',
        'changed_inputs_refused_before_write': input_refusal,
        'tampered_compiled_artifact_refused_before_write': plan_refusal,
        'actual_failed_missing_file_run_retained': failed.get('status') == 'failed' and missing_before_recovery and 'missing.md' in failed.get('error', ''),
        'recovery_bind_cl_completed': bound.get('ok') is True and recipe.get('sourceRunId') == failed['runId'],
        'recover_cl_completed_new_verified_effect': recovered.get('ok') is True and (notes / 'missing.md').read_text(encoding='utf-8') == bind_args['inputs']['body'],
        'original_failure_bytes_preserved': failure_path.read_bytes() == failure_bytes,
        'recovery_retry_no_duplicate_run': replayed.get('ok') is True and len(list((root / '.neyvia/manual-runs').glob('*.json'))) == run_count,
        'every_adapter_positive_current_manual_receipt': all(any(u['tool'] == name and u['status'] == 'admitted' for u in uses) for name in (
            'neyvia.manual.run', 'neyvia.manual.compile', 'neyvia.manual.script.run', 'neyvia.manual.recovery.bind', 'neyvia.manual.recover')),
        'source_unchanged': hashes() == before_hashes}
    result = {'schema': 'neyvia.FIXCL3.manual-execution.v1', 'root': str(root), 'port': port,
        'sourceHashesAtStart': before_hashes, 'sourceHashesAtEnd': hashes(), 'fixtureManualPromotion': promoted,
        'actions': actions, 'ordinaryRuns': ordinary, 'compiledPlan': plan, 'actualFailedRun': failed,
        'recoveryRecipeAtBinding': recipe, 'completionBeforeDrift': completion_before,
        'completionAfterDrift': completion_after, 'manualUses': uses, 'checks': checks,
        'boundary': ['Actual note writes/read verifiers, retained real failure and exact compiler cohorts',
                     'Pending judgement runs cannot claim completed CL effects; user must explicitly resume',
                     'Only procedures with authored executable verifiers on every nested mutation admitted']}
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
