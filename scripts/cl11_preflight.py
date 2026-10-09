"""Replay the disjoint development native/web recovery journeys with receipts."""
from pathlib import Path
import json
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.benchmark11_fixtures import Fixture11, DEV_TASKS, tool_schemas
from grant_agent.cl.host import HostContext
from grant_agent.cl.provider11 import native

root = REPO / '.agent_control/cl11/recovery' / uuid.uuid4().hex
root.mkdir(parents=True)
checks, receipts = {}, []
task = next(row for row in DEV_TASKS if row['id'] == 103)
fixture = Fixture11(task, root / 'window', port=48289)
try:
    host = HostContext(tool_schemas(), fixture.dispatch, contracts=fixture.contract,
                       procedures=fixture.procedures(), goals=task['goal'], root=fixture.root)
    def act(text):
        value = host.execute(text)
        receipts.append({'proposal': text, 'result': value})
        return value
    observed = act('win.observe()')
    early = act('done("too early")')
    checks['failed_goal_publishes_fresh_refs'] = early['status'] == 'refused' and 'S win ' in early['text']
    def ref(label):
        return next(name for name, row in host.refs.items() if name.startswith('e') and
                    row['generation'] == host.generations['win'] and row['value'].get('label') == label)
    field, button = ref('Dispatch text'), ref('Apply')
    run = act(f'run win.set_and_apply(field={field}, text="dev-control", apply={button})')
    done = act('done("Applied and observed")')
    checks['fresh_ref_procedure_and_done'] = run['ok'] and done['ok'] and fixture.check()['passed']
    checks['native_ids_hidden_in_text'] = ' id=' not in observed['text'] and ' id=' not in early['text']
finally:
    fixture.close()

task = next(row for row in DEV_TASKS if row['id'] == 104)
fixture = Fixture11(task, root / 'web', port=48289)
try:
    manifest = fixture.native_manifest()
    result = native('Complete using the supplied raw Playwright MCP tools. Open the fixture page, fill Result with '
                    'dev-confirmation, click Confirm, observe confirmation. Only this origin/directory. No other '
                    'files, downloads, configuration changes or tools. Fixture: '+json.dumps(manifest),
                    'claude-alone', root / 'claude-web', fixture_root=fixture.root,
                    browser_url=manifest['browserUrl'], timeout=120, claude_budget=.12)
    receipts.append({'native': result})
    checks['native_MCP_second_page_server_readback'] = result['passed'] and fixture.check()['passed']
    receipts.append({'server':fixture.web_record, 'independent':fixture.check()})
finally:
    fixture.close()

target = REPO / 'scripts/evidence/CL11-recovery.json'
target.write_text(json.dumps({'allPassed':all(checks.values()), 'checks':checks, 'receipts':receipts},
                             ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'allPassed':all(checks.values()), 'checks':checks, 'receipt':str(target)}))
raise SystemExit(0 if all(checks.values()) else 1)
