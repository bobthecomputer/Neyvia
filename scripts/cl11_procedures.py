"""Real, disposable development journeys for the preferred CL procedures."""
from pathlib import Path
import json
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.benchmark11_fixtures import Fixture11, DEV_TASKS, tasks
from grant_agent.cl.host import HostContext

root = REPO / '.agent_control/cl11/procedure-proof' / uuid.uuid4().hex
checks, receipts = {}, []

def journey(task, name, callback):
    fixture = Fixture11(task, root / name, port=48289)
    try:
        host = HostContext(fixture.tools(), fixture.dispatch, contracts=fixture.contract,
                           procedures=fixture.procedures(), goals=task['goal'], root=fixture.root)
        def act(text):
            result = host.execute(text)
            receipts.append({'journey':name, 'proposal':text, 'result':result})
            return result
        def ref(layer, label):
            return next(alias for alias, row in host.refs.items() if alias.startswith('e') and
                        row['generation'] == host.generations[layer] and
                        row['value'].get('label', row['value'].get('name')) == label)
        callback(fixture, host, act, ref)
    finally:
        fixture.close()

def window(fixture, host, act, ref):
    act('win.observe()')
    result = act('run win.fill_and_save(first='+ref('win','Dispatch text')+', first_text="development-save", second='+
                 ref('win','Project code')+', second_text="DEV-17", save='+ref('win','Save')+')')
    state = json.loads((fixture.root / 'window.json').read_text(encoding='utf-8-sig'))
    checks['native_two_fields_save'] = result['ok'] and state['label'] == 'Saved: development-save | DEV-17'
journey(next(t for t in DEV_TASKS if t['id']==103), 'window', window)

def form(fixture, host, act, ref):
    act('web.observe()')
    result = act('run web.fill_form(name_field='+ref('web','Name')+', name="Development", project_field='+
                 ref('web','Project')+', project="Trial", code_field='+ref('web','Code')+', code="DEV-7", submit='+ref('web','Submit')+')')
    checks['web_three_fields_fresh_revision_submit'] = result['ok'] and fixture.web_record['submitted'] == {'name':'Development','project':'Trial','code':'DEV-7'}
form_task = {**next(t for t in tasks() if t['id']==14), 'id':107, 'scenario':14,
             'goal':'web.state().submitted.name == "Development"'}
journey(form_task, 'form', form)

def files(fixture, host, act, ref):
    result = act('run files.tidy_three_and_undo(source1="inbox/orchard.txt", dest1="projects/Orchard/trial.txt", source2="inbox/harbor.txt", dest2="projects/Harbor/trial.txt", source3="inbox/meadow.txt", dest3="projects/Meadow/trial.txt")')
    checks['three_actual_moves_one_slot_undo'] = result['ok'] and all((fixture.root/path).read_bytes()==fixture.originals[source]
        for path,source in [('projects/Orchard/trial.txt','inbox/orchard.txt'),('projects/Harbor/trial.txt','inbox/harbor.txt'),('inbox/meadow.txt','inbox/meadow.txt')])
    result = act('run files.recycle(path="temporary")')
    checks['real_recycle_bin_observed'] = result['ok'] and not (fixture.root/'temporary').exists() and fixture._inventory()['recoverable']
    for layer in ('notes','files','win','web','img'):
        checks['L1_'+layer+'_20_rows'] = len(host._signatures(layer).splitlines()) + 3 <= 20
journey(next(t for t in DEV_TASKS if t['id']==102), 'files', files)

def chart(fixture, host, act, ref):
    result = act('run img.read_and_answer(answer={"total":67})')
    checks['actual_visual_source_and_submission'] = result['ok'] and fixture.check()['passed']
journey(next(t for t in DEV_TASKS if t['id']==105), 'chart', chart)

target = REPO/'scripts/evidence/CL11-procedures.json'
target.write_text(json.dumps({'allPassed':all(checks.values()), 'checks':checks, 'receipts':receipts}, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps({'allPassed':all(checks.values()), 'checks':checks, 'receipt':str(target)}))
raise SystemExit(0 if all(checks.values()) else 1)
