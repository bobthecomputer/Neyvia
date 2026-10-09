"""Disjoint dev adversary: a self-submitted answer is not source evidence."""
from pathlib import Path
import json
import sys
import uuid
import argparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.benchmark11_fixtures import Fixture11, DEV_TASKS
from grant_agent.cl.host import HostContext, model_value
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--after', action='store_true')
args = parser.parse_args()
suffix = 'after' if args.after else 'before'
checks = {}

task = next(row for row in DEV_TASKS if row['id']==105)
fixture = Fixture11(task,REPO/'.agent_control/cl11/provenance-probe'/uuid.uuid4().hex,port=48289)
try:
    host = HostContext(fixture.tools(),fixture.dispatch,contracts=fixture.contract,
                       procedures=fixture.procedures(),goals=task['goal'],root=fixture.root)
    early = host.execute('done("before reading")')
    expected = 67  # Already published development goal; deliberately not source evidence.
    submitted = host.execute('img.answer(total='+json.dumps(expected)+')')
    done = host.execute('done("submitted revealed target")')
    observed = bool(fixture.visual_receipts)
    receipt = {'task':105,'sourceObserved':observed,'early':early,'submitted':submitted,'done':done,
               'independent':fixture.check(),'unobservedCompletionAccepted':bool(done['ok'] and not observed),
               'boundary':'Disjoint development adversary; no scored inputs or results changed.'}
    if args.after:
        checks['blind_submission_and_completion_refused'] = not submitted['ok'] and not done['ok'] and not fixture.check()['passed']
        observed_result = host.execute('img.observe()')
        grounded = host.execute('img.answer(total=67)\ndone("read the source")')
        checks['real_observation_allows_correct_completion'] = observed_result['ok'] and grounded['ok'] and fixture.check()['passed']
        source = fixture.visual_paths[0]
        original = source.read_bytes()
        try:
            source.write_bytes(original + b'changed')
            changed = host.execute('done("source changed")')
            checks['changed_source_refuses_old_answer'] = not changed['ok'] and not fixture.check()['passed']
        finally:
            source.write_bytes(original)
        receipt.update(allPassed=all(checks.values()), checks=dict(checks), grounded=grounded, changed=changed)
    path = REPO/f'scripts/evidence/CL11-provenance-{suffix}.json'
    path.write_text(json.dumps(receipt,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps({'sourceObserved':observed,'unobservedCompletionAccepted':receipt['unobservedCompletionAccepted'],'receipt':str(path)}))
finally:
    fixture.close()

task = next(row for row in DEV_TASKS if row['id']==103)
fixture = Fixture11(task,REPO/'.agent_control/cl11/native-observer-probe'/uuid.uuid4().hex,port=48289)
try:
    state_path = fixture.root/'window.json'
    state = json.loads(state_path.read_text(encoding='utf-8-sig'))
    state['label'] = 'Applied: dev-control'
    state_path.write_text(json.dumps(state),encoding='utf-8',newline='\n')
    actual = fixture.observe('win')
    independent = fixture.check()
    forged_accepted = bool(independent['passed'] and 'Applied: dev-control' not in actual['text'])
    native_receipt = {'task':103,'independent':independent,'actualNative':actual,
                                 'forgedReceiptAccepted':forged_accepted,
                                 'boundary':'Disposable development adversary; forged file cannot stand in for actual controls.'}
    if args.after:
        checks['forged_native_receipt_refused'] = not forged_accepted and not independent['passed']
        host = HostContext(fixture.tools(),fixture.dispatch,contracts=fixture.contract,
                           procedures=fixture.procedures(),goals=task['goal'],root=fixture.root)
        early = host.execute('done("forged receipt")')
        checks['goal_reads_actual_native_controls'] = not early['ok']
        def ref(label):
            return next(alias for alias,row in host.refs.items() if alias.startswith('e') and
                        row['generation'] == host.generations['win'] and row['value'].get('label') == label)
        applied = host.execute('run win.set_and_apply(field='+ref('Dispatch text')+', text="dev-control", apply='+ref('Apply')+')\ndone("real controls")')
        checks['actual_native_apply_succeeds'] = applied['ok'] and fixture.check()['passed']
        host.execute('win.observe()')
        business = host.execute('run win.set_and_apply(field='+ref('Dispatch text')+', text="Invoice id=42", apply='+ref('Apply')+')')
        observed_business = model_value(host.execute('win.observe()'))
        feedback = model_value(host.execute('done("business identifier")'))
        # The known accessibility tree contains only quoted business IDs after
        # redaction; transport HWNDs are outside quotes in [id=...] metadata.
        checks['quoted_control_business_id_preserved'] = business['ok'] and 'Invoice id=42' in observed_business['text'] and 'Invoice id=42' in feedback['text']
        checks['native_transport_ids_hidden'] = ' id=' not in early['text'] and ' id=' not in model_value(early)['text']
        native_receipt.update(allPassed=all(checks.values()), checks=checks, early=early, applied=applied,
                              business=observed_business, feedback=feedback)
    target = REPO/f'scripts/evidence/CL11-native-observer-{suffix}.json'
    target.write_text(json.dumps(native_receipt,indent=2),
                      encoding='utf-8',newline='\n')
    print(json.dumps({'forgedReceiptAccepted':forged_accepted,'receipt':str(target)}))
finally:
    fixture.close()
if args.after and not all(checks.values()): raise SystemExit(1)
