"""Mounted draft, file-admission and owner-state witnesses for C8e.

No provider result, plan tool item, agent usage or native bridge session is
invented. Each unvisited source case remains explicitly unproved. The original
production proof runner is still the producer; these actions prove its consumer
boundary where it can be reached safely with the selected disposable owner.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from c8e_ui_effects import _home, _skip_setup, _fresh_summary, _search

ROOT = Path(__file__).resolve().parents[1]


def apply(bindings):
    result = copy.deepcopy(bindings)
    overlay = json.loads((ROOT / 'config/inception_c8e_state_effects.json').read_text(encoding='utf-8'))['bindings']
    for identity, values in overlay.items():
        result[identity].update(values)
        result[identity]['c8eEffect']['renderedWitness'] = 'c8e-state-' + values['c8eStateEffect']
    return result


def before_manual(worker, binding, inputs, root):
    if binding.get('c8eStateEffect'):
        worker.c8e_state_effect = {'group': binding['c8eStateEffect'], 'startedAt': time.time()}
    return getattr(worker, 'c8e_state_effect', None)


def _check(identity, passed, observed):
    return {'id': 'c8e.state.' + identity, 'passed': bool(passed), 'fresh': True,
            'boundary': 'rendered-user-action', 'observed': observed}


def _cases(identity):
    proof = json.loads((ROOT / 'config/proofs/proofs-e-models.json').read_text(encoding='utf-8'))
    return [{'caseId': c['case_id'], 'case': c['case']} for c in proof['coverage'] if identity in c['contracts']]


def _contract(identity, checks, reason=None):
    return {'id': identity, 'passed': bool(checks) and all(c['passed'] for c in checks) and not reason,
            'fresh': True, 'boundary': 'rendered-user-action',
            'observed': {'sourceCases': _cases(identity), 'actions': checks,
                         **({'missingPrerequisite': reason} if reason else {})}}


def _finish(worker, binding, checks, contracts, **observed):
    present = {c['id'] for c in contracts}
    for identity in binding['c8eEffect'].get('requiredContractIds', []):
        if identity not in present:
            contracts.append(_contract(identity, [], observed.get('unprovedReason',
                'No genuine source-case producer and mounted consumer was reached; a model-only receipt is insufficient.')))
    artifact = worker.screenshot('effect-state-' + binding['c8eStateEffect'])
    return checks, {'contractEffects': contracts,
                    'rendered': {'witness': 'c8e-state-' + binding['c8eStateEffect'],
                                 'artifact': artifact, 'url': worker.page.url}, **observed}


def _owner(worker, path, body=None):
    from c8e_prerequisites import owner, _record
    if body is not None:
        return owner(worker, path, body)
    row = worker.page.evaluate("""async path => {const r=await fetch(path,{credentials:'include'});
      return {httpStatus:r.status,body:await r.json()};}""",path)
    _record(worker,'owner:get:'+path,{},row)
    if row['httpStatus'] != 200 or row['body'].get('ok') is False:
        raise RuntimeError('Real scratch owner GET refused: '+json.dumps(row))
    return row['body'].get('data',row['body'])


def _pane(worker, kind, target):
    _skip_setup(worker)
    worker.tool('neyvia.pane.show', {'kind': kind, 'target': target})


def _conversation(worker, root, title):
    created = worker.tool('backend:create_neyvia_conversation_command',
        {'kind': 'chat', 'title': title, 'titleMode': 'off',
         'metadata': {'workspacePath': str(root), 'source': 'C8e-real-user-fixture'}})
    cid = created['conversationId']
    worker.tool('backend:append_neyvia_conversation_turn_command',
        {'conversationId': cid, 'role': 'user', 'content': 'Owned disposable user conversation for state controls.',
         'source': 'C8e-real-user-fixture'})
    identity = _fresh_summary(worker, cid)['id']
    worker.c8e_state_chat_titles = {**getattr(worker,'c8e_state_chat_titles',{}),identity:title}
    return identity, cid


def _open_chat(worker, identity):
    # The launcher consumes the shell's list loaded at boot. A new durable
    # transcript must be present in that actual list, not just an API receipt.
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-root').wait_for(timeout=15000)
    _skip_setup(worker)
    title = worker.c8e_state_chat_titles[identity]
    options = _search(worker,title)
    options.filter(has=worker.page.get_by_text(title,exact=True)).click()
    worker.page.wait_for_function('id=>new URL(location.href).searchParams.get("chat")===id',arg=identity,timeout=15000)
    worker.page.locator('.nx-composer textarea[aria-label="Message Neyvia"]').wait_for(timeout=15000)
    worker.page.get_by_text('Owned disposable user conversation for state controls.',exact=True).first.wait_for(timeout=15000)


def _missions(worker, binding, root):
    _home(worker)
    _pane(worker, 'mission', 'new')
    form = worker.page.locator('.nx-ms-new')
    form.wait_for(timeout=15000)
    checks, contracts, validation = [], [], []
    goal = form.locator('label').filter(has=worker.page.get_by_text('Goal', exact=True)).locator('input')
    folder = form.locator('label').filter(has=worker.page.get_by_text('Project folder', exact=True)).locator('input')
    acceptance = form.locator('label').filter(has=worker.page.get_by_text('Acceptance checks, one per line', exact=True)).locator('textarea')
    budget = form.locator('label').filter(has=worker.page.get_by_text('Token budget (optional)', exact=True)).locator('input')
    save = form.get_by_role('button', name='Save mission', exact=True)
    goal.fill(' C8e real dormant mission ')
    folder.fill('')
    missing = form.locator('.nx-ms-problems li').all_text_contents()
    expected = ['Choose the project folder it works in.', 'Task 1 needs a prompt.',
                "Add at least one acceptance check: how you'll know it's done."]
    validation.append(_check('mission-missing-prerequisites', missing == expected and save.is_disabled(),
                             {'problems': missing, 'expected': expected, 'saveDisabled': save.is_disabled()}))
    folder.fill(' ' + str(root) + ' ')
    form.get_by_role('textbox', name='Task 1 title', exact=True).fill(' First local task ')
    form.get_by_role('textbox', name='Task 1 prompt', exact=True).fill(' Inspect the owned fixture only. ')
    form.get_by_role('combobox', name='Task 1 harness', exact=True).select_option('neyvia')
    form.get_by_role('textbox', name='Task 1 model', exact=True).fill(' local-only-unused-draft ')
    acceptance.fill(' Owned fixture remains unchanged\n\n No task has started ')
    budget.fill('0')
    validation.append(_check('mission-nonpositive-budget', form.locator('.nx-ms-problems li').all_text_contents()
                             == ['The token budget must be a positive number.'] and save.is_disabled(),
                             {'problems': form.locator('.nx-ms-problems li').all_text_contents()}))
    budget.fill('101.6')
    form.get_by_role('button', name='Add a task', exact=True).click()
    form.get_by_role('textbox', name='Task 2 title', exact=True).fill(' Intermediate removed task ')
    form.get_by_role('textbox', name='Task 2 prompt', exact=True).fill(' Never execute this removed task. ')
    form.get_by_role('group', name='Task 2 starts after', exact=True).get_by_role('checkbox').check()
    form.get_by_role('button', name='Add a task', exact=True).click()
    form.get_by_role('textbox', name='Task 3 title', exact=True).fill(' Last local task ')
    form.get_by_role('textbox', name='Task 3 prompt', exact=True).fill(' Review only after the first task. ')
    form.get_by_role('combobox', name='Task 3 harness', exact=True).select_option('neyvia')
    form.get_by_role('group', name='Task 3 starts after', exact=True).get_by_role('checkbox').nth(0).check()
    form.get_by_role('group', name='Task 3 starts after', exact=True).get_by_role('checkbox').nth(1).check()
    form.get_by_role('button', name='Remove task 2', exact=True).click()
    validation.append(_check('mission-ready-after-real-constraints', not save.is_disabled()
                             and form.locator('.nx-ms-problems li').count() == 0,
                             {'taskCount': form.locator('fieldset').count(), 'saveDisabled': save.is_disabled()}))
    with worker.page.expect_request(lambda request: request.url.endswith('/api/ui/missions')
                                  and request.method == 'POST') as pending:
        save.click()
    request = pending.value.post_data_json
    view = worker.page.locator('.nx-ms-view')
    view.wait_for(timeout=15000)
    listed = _owner(worker, '/api/ui/missions')
    rows = [m for m in listed['missions'] if m['goal'] == 'C8e real dormant mission']
    mission = rows[0] if len(rows) == 1 else {}
    expected_tasks = [{'id': 't1', 'prompt': 'Inspect the owned fixture only.', 'title': 'First local task',
                       'harness': 'neyvia', 'model': 'local-only-unused-draft', 'needs': []},
                      {'id': 't3', 'prompt': 'Review only after the first task.', 'title': 'Last local task',
                       'harness': 'neyvia', 'needs': ['t1']}]
    request_check = _check('mission-real-create-trims-and-drops-removed-dependency',
        request == {'operation': 'create', 'goal': 'C8e real dormant mission', 'folder': str(root),
                    'acceptanceChecks': ['Owned fixture remains unchanged', 'No task has started'],
                    'budget': {'maxTokens': 102}, 'tasks': expected_tasks}
        and mission.get('status') == 'draft' and len(mission.get('tasks', [])) == 2,
        {'wireRequest': request, 'ownerMission': mission})
    checks.extend(validation + [request_check])
    contracts += [_contract('missions.draftProblems', validation), _contract('missions.createRequest', [request_check])]
    levels = worker.page.locator('.nx-ms-level-label').all_text_contents()
    progress = worker.page.locator('.nx-ms-progress').get_attribute('aria-label')
    shape_check = _check('mission-durable-draft-levels-counts', levels == ['First', 'Then (1)']
                          and progress == '0 of 2 tasks done'
                          and worker.page.locator('.nx-ms-task-title').all_text_contents() == ['First local task', 'Last local task'],
                          {'levels': levels, 'progress': progress, 'ownerMission': mission})
    checks.append(shape_check)
    worker.page.locator('.nx-ms-task').filter(has_text='First local task').click()
    prompt = worker.page.get_by_role('textbox', name='Task prompt', exact=True)
    prompt.fill('Actually redirected while dormant, still no provider launched.')
    redirect = worker.page.locator('.nx-ms-detail').get_by_role('button', name='Save new prompt', exact=True)
    with worker.page.expect_response(lambda response: response.url.endswith('/api/ui/missions')
                                    and response.request.method=='POST') as response:
        redirect.click()
    if response.value.status != 200 or response.value.json().get('ok') is False:
        raise RuntimeError('Actual dormant redirect was refused: '+response.value.text())
    changed = _owner(worker, '/api/ui/missions')['missions']
    selected = next(m for m in changed if m['id'] == mission['id'])
    checks.append(_check('mission-dormant-prompt-redirect-owner',
        next(t for t in selected['tasks'] if t['id'].endswith(':t1'))['prompt'] == 'Actually redirected while dormant, still no provider launched.'
        and all(t['status'] == 'waiting' for t in selected['tasks']), {'ownerMission': selected}))
    for action, phase in [('pause', 'paused'), ('stop', 'stopped')]:
        _owner(worker, '/api/ui/missions', {'operation': 'control', 'id': mission['id'], 'action': action})
        worker.page.locator('.nx-ms-phase').filter(has_text=phase.capitalize()).last.wait_for(timeout=15000)
        current = next(m for m in _owner(worker, '/api/ui/missions')['missions'] if m['id'] == mission['id'])
        checks.append(_check('mission-real-' + action + '-durable-phase', current['status'] == phase
            and all(t['status'] == ('blocked' if action=='stop' else 'waiting') for t in current['tasks']), {'ownerMission': current}))
    from c8e_ui_effects import _strict_refusal
    # The source explicitly promises recovery from cyclic/unknown stored draft
    # inputs. Change only these two unarmed owned rows, never a provider receipt,
    # then consume them through the real owner and mounted screen and restore
    # their exact original column bytes before performing any completion.
    task_ids = [next(t['id'] for t in mission['tasks'] if t['id'].endswith(':'+local_id)) for local_id in ['t1','t3']]
    db_path = (root/'.agent_control'/'nightshift.sqlite3').resolve()
    if not db_path.is_relative_to(root.resolve()):
        raise PermissionError('Malformed-input fixture must remain in this owned profile')
    originals = {}
    with sqlite3.connect(db_path) as db:
        for task_id in task_ids:
            row = db.execute('SELECT body,status,armed FROM tasks WHERE id=?',(task_id,)).fetchone()
            if row is None or row[2] or json.loads(row[0]).get('missionId')!=mission['id']:
                raise ValueError('Corrupt-state fixture needs exact own unarmed mission rows')
            originals[task_id] = (row[0],row[1])
        body = json.loads(originals[task_ids[0]][0]);body['needs']=[task_ids[1]]
        db.execute('UPDATE tasks SET body=?,status=? WHERE id=?',
                   (json.dumps(body),'future-c8e-input-state',task_ids[0]))
    malformed_check = None
    try:
        raw = next(m for m in _owner(worker,'/api/ui/missions')['missions'] if m['id']==mission['id'])
        worker.page.reload(wait_until='domcontentloaded')
        worker.page.locator('.nx-root').wait_for(timeout=15000)
        _pane(worker,'mission',mission['id'])
        worker.page.locator('.nx-ms-task').filter(has_text='First local task').wait_for(timeout=15000)
        worker.page.locator('.nx-ms-task').filter(has_text='First local task').click()
        detail = worker.page.locator('.nx-ms-detail header').inner_text()
        nodes = worker.page.locator('.nx-ms-task').evaluate_all('(nodes)=>nodes.map(n=>({text:n.innerText,className:n.className}))')
        levels = worker.page.locator('.nx-ms-level-label').all_text_contents()
        malformed_check = _check('mission-real-malformed-cycle-and-unknown-state',
            len(nodes)==2 and any('First local task' in n['text'] and 'is-waiting' in n['className'] for n in nodes)
            and 'waiting' in detail and levels==['Then (1)','Then (2)']
            and worker.page.locator('.nx-ms-counts').inner_text().startswith('0/2 done · 0 running · 1 blocked')
            and {t['id'] for t in raw['tasks']}==set(task_ids)
            and any(t['status']=='future-c8e-input-state' for t in raw['tasks'])
            and worker.page.locator('.nx-ms-progress').get_attribute('aria-label')=='0 of 2 tasks done'
            and not worker.page_errors,
            {'fixture':'Only own unarmed stored draft inputs, not execution/provider receipts',
             'rawOwnerMission':raw,'mountedNodes':nodes,'levels':levels,'detail':detail})
    finally:
        with sqlite3.connect(db_path) as db:
            for task_id,(body,status) in originals.items():
                db.execute('UPDATE tasks SET body=?,status=? WHERE id=?',(body,status,task_id))
            restored = {task_id:db.execute('SELECT body,status FROM tasks WHERE id=?',(task_id,)).fetchone() for task_id in task_ids}
        if restored != originals:
            raise RuntimeError('Own malformed draft columns were not restored byte-for-byte')
        worker.page.reload(wait_until='domcontentloaded')
        worker.page.locator('.nx-root').wait_for(timeout=15000)
        _pane(worker,'mission',mission['id'])
        worker.page.locator('.nx-ms-task').first.wait_for(timeout=15000)
    checks.append(malformed_check)
    evidence_file = root / 'c8' / 'mission-effect.txt'
    evidence_file.parent.mkdir(parents=True,exist_ok=True)
    evidence_file.write_text('Owned mission fixture, inspected and verified without launching a harness.\n',encoding='utf-8')
    digest = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    refusal = _strict_refusal(worker,'neyvia.nightshift.tick',
        {'id':task_ids[1],'evidence':{'type':'file','path':str(evidence_file)}},['Prerequisites are not done'])
    adverse = _check('mission-dependent-file-tick-refused-before-prerequisite',refusal['refused'],refusal)
    checks.append(adverse)
    progress_checks = [shape_check,malformed_check,adverse]
    for index,task_id in enumerate(task_ids):
        tick = worker.tool('neyvia.nightshift.tick',{'id':task_id,'evidence':{'type':'file','path':str(evidence_file)}})
        expected_progress = str(index+1)+' of 2 tasks done'
        worker.page.locator('.nx-ms-progress[aria-label="'+expected_progress+'"]').wait_for(timeout=15000)
        current = next(m for m in _owner(worker,'/api/ui/missions')['missions'] if m['id']==mission['id'])
        actual = next(t for t in current['tasks'] if t['id']==task_id)
        c = _check('mission-real-file-tick-progress-'+str(index+1), actual['status']=='done'
            and actual['evidence']['sha256']==digest and digest==hashlib.sha256(evidence_file.read_bytes()).hexdigest()
            and sum(t['status']=='done' for t in current['tasks'])==index+1,
            {'tick':tick,'ownerMission':current,'mountedProgress':expected_progress,'independentFileSha256':digest})
        checks.append(c);progress_checks.append(c)
    other = root/'c8'/'mission-other-evidence.txt'
    other.write_text('Different checked file is not the immutable completed evidence.\n',encoding='utf-8')
    refusal = _strict_refusal(worker,'neyvia.nightshift.tick',
        {'id':task_ids[0],'evidence':{'type':'file','path':str(other)}},['Completed task evidence is immutable'])
    immutable = _check('mission-completed-file-evidence-immutable',refusal['refused'],refusal)
    checks.append(immutable);progress_checks.append(immutable)
    contracts.append(_contract('missions.shapeMission',progress_checks))
    return _finish(worker, binding, checks, contracts, missionId=mission.get('id'),
        unprovedReason='Plan with Neyvia starts a real planning provider. The required owned provider route is unavailable; no generated plan or planner turn was substituted.')


def _read_spy(worker):
    worker.page.evaluate("""() => {if(window.__c8FileReads)return;
      window.__c8FileReads=[];const real=FileReader.prototype.readAsDataURL;
      FileReader.prototype.readAsDataURL=function(file){const row={name:file.name,mime:file.type,size:file.size};
        window.__c8FileReads.push(row);this.addEventListener('load',()=>{row.dataUrl=String(this.result);},{once:true});
        return real.call(this,file);};} """)


def _composer(worker, binding, root):
    identity, cid = _conversation(worker, root, 'C8e attachment controls')
    _open_chat(worker, identity)
    _read_spy(worker)
    checks, contracts = [], []
    # All buffers are owned local fixture bytes; no download and no send occurs.
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l4sAAAAASUVORK5CYII=')
    picked = worker.page.locator('.nx-composer input[type=file]').first
    def attach(files):
        picked.set_input_files(files)
    def reads():
        return worker.page.evaluate('() => window.__c8FileReads')
    attach([{'name': 'owned.png', 'mimeType': 'image/png', 'buffer': png}])
    worker.page.get_by_role('list', name='Images to send', exact=True).get_by_role('img', name='owned.png', exact=True).wait_for(timeout=15000)
    first = reads()[0]
    payload = first.get('dataUrl', '').partition(',')[2]
    checks.append(_check('composer-real-file-reader-base64-bytes', payload == base64.b64encode(png).decode()
        and first['size'] == len(png) and first['mime'] == 'image/png',
        {'name': first['name'], 'size': first['size'], 'base64Length': len(payload),
         'sha256': hashlib.sha256(base64.b64decode(payload)).hexdigest(),
         'fixtureSha256': hashlib.sha256(png).hexdigest()}))
    attach([{'name': 'oversized.png', 'mimeType': 'image/png', 'buffer': png + bytes(9*1024*1024)}])
    worker.page.get_by_role('alert').filter(has_text='oversized.png is larger than about 9 MB.').wait_for(timeout=10000)
    checks.append(_check('composer-oversized-metadata-before-file-reader', len(reads()) == 1
        and worker.page.locator('.nx-tray-item').count() == 1, {'reads': [{k:v for k,v in r.items() if k != 'dataUrl'} for r in reads()]}))
    worker.page.get_by_role('button', name='Dismiss', exact=True).last.click()
    attach([{'name': f'count-{i}.png', 'mimeType': 'image/png', 'buffer': png} for i in range(6)])
    worker.page.get_by_role('alert').filter(has_text='At most 6 images go with one message.').wait_for(timeout=15000)
    checks.append(_check('composer-six-count-before-extra-read', len(reads()) == 6
                         and worker.page.locator('.nx-tray-item').count() == 6,
                         {'readNames': [r['name'] for r in reads()], 'trayCount': worker.page.locator('.nx-tray-item').count()}))
    while worker.page.locator('.nx-tray-item').count():
        worker.page.locator('.nx-tray-item button').first.click()
    # Aggregate gate uses exact estimated base64 bytes, while every admitted file
    # still passes through the browser's real FileReader and the late byte gate.
    worker.page.get_by_role('button', name='Dismiss', exact=True).last.click()
    before = len(reads())
    large = png + bytes(7*1024*1024-len(png))
    attach([{'name': f'aggregate-{i}.png', 'mimeType': 'image/png', 'buffer': large} for i in range(3)])
    worker.page.get_by_role('alert').filter(has_text='The images together would be larger than about 18 MB.').wait_for(timeout=20000)
    checks.append(_check('composer-aggregate-metadata-gate', len(reads()) == before+2
                         and worker.page.locator('.nx-tray-item').count() == 2,
                         {'readNames': [r['name'] for r in reads()[before:]], 'trayCount': worker.page.locator('.nx-tray-item').count()}))
    while worker.page.locator('.nx-tray-item').count():
        worker.page.locator('.nx-tray-item button').first.click()
    checks.append(_check('composer-actual-remove-only-origin-draft', worker.page.get_by_role('list', name='Images to send', exact=True).count() == 0,
                         {'sessionId': identity, 'allReadNames': [r['name'] for r in reads()]}))
    contracts += [_contract('composer.stripDataUrl', [checks[0]]),
                  _contract('composer.base64Chars', [checks[0], checks[1], checks[3]]),
                  _contract('composer.planImageReads', checks[:4],
                    'Real supported, oversize, six-count and aggregate gates proved. Unsupported image MIME routes to the separate ordinary-file attachment path; no fake FileReader result was injected.'),
                  _contract('composer.admitImages', checks[:4],
                    'Real admitted bytes and refusal gates proved; the read/commit race and every supported MIME still need mounted coverage.'),
                  _contract('composer.attachResult', checks[:5],
                    'Actual successful read/commit/removal proved; slow read across a chat switch and read-error/late-race cases remain unproved.'),
                  _contract('composer.draftUpdate', [checks[-1]],
                    'Origin removal proved. Stable-empty subscription identity and a delayed read landing after a chat switch remain unproved.')]
    # The actual tool runner owns schema examples, argument parsing and labels.
    worker.page.get_by_role('button', name='More: images, files, tools, compact, branch', exact=True).click()
    worker.page.get_by_role('menuitem').filter(has_text='Run a Neyvia tool').click()
    runner = worker.page.get_by_role('region', name='Run a Neyvia tool', exact=True)
    runner.wait_for(timeout=15000)
    options = runner.get_by_role('listbox', name='Neyvia tools', exact=True)
    options.get_by_role('option').first.wait_for(timeout=20000)
    catalog = worker.tool('backend:get_native_tool_catalog_command', {'root': str(root)})['tools']
    query = runner.get_by_role('searchbox', name='Filter tools', exact=True)
    filter_checks = []
    for text in ['', 'files read', 'project', 'c8e-no-such-tool']:
        query.fill(text)
        terms = text.lower().split()
        rows = [t for t in catalog if all(term in (' '.join([t['name'],t.get('category',''),t.get('description',''),*t.get('aliases',[])])).lower() for term in terms)]
        # Name ordering is the browser's natural locale collation (which puts
        # app_sdk before app.open); Python's byte sorting is not that oracle.
        ordered = worker.page.evaluate('rows=>{const names=new Intl.Collator();return rows.sort((a,b)=>Number(Boolean(b.available))-Number(Boolean(a.available))||names.compare(a.name,b.name)).map(r=>r.name)}',rows)
        actual = options.locator('[role=option] code').all_text_contents()
        filter_checks.append(_check('composer-filter-' + (text.replace(' ','-') or 'all'), actual == ordered,
                                    {'query': text, 'expected': ordered, 'mounted': actual}))
    checks.extend(filter_checks)
    contracts.append(_contract('composer.filterTools', filter_checks))
    query.fill('neyvia.view.theme')
    options.get_by_role('option', name='neyvia.view.theme', exact=False).click()
    args = runner.get_by_role('textbox', name='Arguments (JSON)', exact=True)
    worker.page.wait_for_function("()=>document.querySelector('#nx-toolrun-args')?.value.includes('theme')",timeout=15000)
    schema = worker.tool('backend:get_native_tool_catalog_command', {'root': str(root),'describe':'neyvia.view.theme'})
    expected = {}
    fallback = {'string':'','integer':0,'number':0,'boolean':False,'array':[],'object':{}}
    for key in schema['inputSchema'].get('required',[]):
        field = schema['inputSchema'].get('properties',{}).get(key,{})
        expected[key] = field['enum'][0] if field.get('enum') else field.get('default',fallback.get(field.get('type'),''))
    skeleton = _check('composer-real-enum-schema-skeleton', json.loads(args.input_value()) == expected,
                      {'schema': schema['inputSchema'], 'mountedArguments': args.input_value()})
    checks.append(skeleton)
    contracts.append(_contract('composer.argumentSkeleton',[skeleton],
        'Real enum required-field schema proved; required integer/boolean/array/object/default schemas still need separate actual tools.'))
    parse_checks = []
    for value, fragment in [('[]','Arguments must be a JSON object'),('null','Arguments must be a JSON object'),('{bad','That isn\'t valid JSON'),('',None),('{"theme":"dark"}',None)]:
        args.fill(value)
        invalid = args.get_attribute('aria-invalid') == 'true'
        shown = runner.locator('.nx-pending-error').all_text_contents()
        parse_checks.append(_check('composer-arguments-' + str(len(parse_checks)), invalid == bool(fragment)
            and (not fragment or any(fragment in line for line in shown)), {'text':value,'invalid':invalid,'errors':shown}))
    checks.extend(parse_checks)
    contracts.append(_contract('composer.parseArguments',parse_checks))
    confirm = runner.get_by_role('checkbox')
    run = runner.get_by_role('button', name='Run (makes changes)', exact=True)
    gate = _check('composer-mutating-tool-confirmation-required', confirm.count() == 1 and run.is_disabled()
                  and 'Changes Neyvia' in runner.locator('.nx-toolrun-title').inner_text(),
                  {'disabled':run.is_disabled(),'title':runner.locator('.nx-toolrun-title').inner_text()})
    confirm.check()
    ready = _check('composer-mutating-tool-confirmation-enables-only-chosen-call', not run.is_disabled(), {'enabled':not run.is_disabled()})
    checks += [gate,ready]
    contracts.append(_contract('composer.toolMutates',[gate,ready],
        'Actual Neyvia mutation confirmation gate proved; read-only/default and every other mutation-class label still need mounted calls.'))
    scope = runner.locator('.nx-toolrun-scope').inner_text()
    checks.append(_check('composer-actual-ui-tool-owner-scope',scope == "Runs in Neyvia's own workspace (sidebar, projects, sessions), not in this chat's folder.",{'label':scope,'root':str(root)}))
    contracts.append(_contract('composer.toolScope',[checks[-1]],
        'Actual UI tool owner scope proved. Ordinary native read in a chat folder and C11 desktop tool scope remain unproved.'))
    return _finish(worker,binding,checks,contracts,conversationId=cid,
        unprovedReason='Image-capable provider transport/model routes and actual retry identity require a real local configured route; no provider response or send completion was seeded.')


def _agents(worker, binding, root):
    identity, cid = _conversation(worker, root, 'C8e real checklist publication')
    _open_chat(worker, identity)
    steps = [{'step': 'Read the owned scratch conversation', 'status': 'pending'},
             {'step': 'Inspect its actual mounted owner controls', 'status': 'pending'}]
    published = worker.tool('neyvia.plan.update', {'sessionId': identity, 'plan': steps,
                                                 'explanation':'User-authored pending checklist; no generated result.'})
    _open_chat(worker,identity)
    checklist = worker.page.get_by_role('region', name='Agent checklist', exact=True)
    shown = checklist.count() > 0
    checks = [_check('agents-real-plan-owner-publication',published.get('providerCalls') == 0
                     and len(published.get('plan',{}).get('items',[])) == 2,
                     {'publication':published,'sessionId':identity,'mountedChecklist':shown})]
    if shown:
        if checklist.get_by_role('button').first.get_attribute('aria-expanded')!='true':
            checklist.get_by_role('button').first.click()
        rendered = checklist.locator('.nx-checklist-text').all_text_contents()
        checks.append(_check('agents-real-plan-owner-consumer',rendered == [s['step'] for s in steps],{'rendered':rendered}))
    else:
        checks.append(_check('agents-plan-owner-consumer-missing',False,
            {'reason':'Actual owner stores pending plan, but connected Neyvia transcript reader does not expose the published bus plan to NxChecklist.'}))
        worker.tool('neyvia.plan.update', {'sessionId': identity,'plan':[]})
        return _finish(worker,binding,checks,[],conversationId=cid,
            unprovedReason='Actual owner pending plan was not consumed. No provider plan stream or replay/limit observations were fabricated.')
    other_id, other_cid = _conversation(worker,root,'C8e isolated pending checklist')
    other_steps=[{'step':'Keep this separate user-authored checklist pending','status':'pending'}]
    worker.tool('neyvia.plan.update',{'sessionId':other_id,'plan':other_steps})
    _open_chat(worker,identity)
    def state(expect_count,expect_title):
        region=worker.page.get_by_role('region',name='Agent checklist',exact=True)
        region.wait_for(timeout=15000)
        if region.get_by_role('button').first.get_attribute('aria-expanded')!='true':
            region.get_by_role('button').first.click()
        raw_count = region.locator('.nx-checklist-count').inner_text()
        return {'count':' '.join(raw_count.split()), 'rawCount':raw_count,
                'headline':region.locator('.nx-checklist-now').inner_text(),
                'items':region.locator('.nx-checklist-text').all_text_contents(),
                'expectedCount':expect_count,'expectedHeadline':expect_title}
    initial=state('0 of 2','Next: '+steps[0]['step'])
    checks.append(_check('agents-owner-plan-reload-and-session-isolation',initial['count']=='0 of 2'
        and initial['headline']=='Next: '+steps[0]['step'] and initial['items']==[s['step'] for s in steps],initial))
    steps[0]['status']='in_progress'
    worker.tool('neyvia.plan.update',{'sessionId':identity,'plan':steps})
    _open_chat(worker,identity)
    active=state('0 of 2',steps[0]['step'])
    checks.append(_check('agents-owner-plan-first-active-headline',active['count']=='0 of 2'
        and active['headline']==steps[0]['step'],active))
    # Complete the user-authored manual steps only after their actual effect.
    page=worker.tool('backend:connected_session_read_command',{'id':identity,'limit':160})
    user_items=[i for i in page.get('items',[]) if i.get('kind')=='user']
    read_ok=any(i.get('data',{}).get('text')=='Owned disposable user conversation for state controls.' for i in user_items)
    checks.append(_check('agents-first-manual-step-actually-read',read_ok,
                         {'userItems':user_items,'source':'Authenticated current connected-session read'}))
    if not read_ok:
        raise ValueError('Do not mark unread user conversation as completed')
    steps[0]['status']='completed'
    worker.tool('neyvia.plan.update',{'sessionId':identity,'plan':steps})
    _open_chat(worker,identity)
    partial=state('1 of 2','Next: '+steps[1]['step'])
    checks.append(_check('agents-owner-plan-verified-step-progress',partial['count']=='1 of 2'
        and partial['headline']=='Next: '+steps[1]['step'],partial))
    steps[1]['status']='in_progress'
    worker.tool('neyvia.plan.update',{'sessionId':identity,'plan':steps})
    _open_chat(worker,identity)
    second=state('1 of 2',steps[1]['step'])
    checks.append(_check('agents-owner-plan-next-active-headline',second['count']=='1 of 2'
                         and second['headline']==steps[1]['step'],second))
    worker.page.get_by_role('button',name='More: images, files, tools, compact, branch',exact=True).click()
    menu=worker.page.get_by_role('menu',exact=True)
    menu.get_by_role('menuitem').filter(has_text='Run a Neyvia tool').wait_for(state='visible',timeout=10000)
    labels=menu.get_by_role('menuitem').all_text_contents()
    actual_controls=any('Run a Neyvia tool' in label for label in labels)
    checks.append(_check('agents-second-manual-step-actually-inspected',actual_controls,{'mountedOwnerMenu':labels}))
    if not actual_controls:
        raise ValueError('Do not mark unobserved owner controls as completed')
    worker.page.keyboard.press('Escape')
    steps[1]['status']='completed'
    worker.tool('neyvia.plan.update',{'sessionId':identity,'plan':steps})
    _open_chat(worker,identity)
    checks.append(_check('agents-owner-complete-inactive-checklist-hides',worker.page.get_by_role('region',name='Agent checklist',exact=True).count()==0,
                         {'completed':'Both manual actions independently observed before publication','sessionId':identity}))
    worker.tool('neyvia.plan.update',{'sessionId':identity,'plan':[]})
    _open_chat(worker,identity)
    cleared=worker.tool('backend:connected_session_read_command',{'id':identity,'limit':160})
    checks.append(_check('agents-owner-explicit-clear-remains-after-reload',worker.page.get_by_role('region',name='Agent checklist',exact=True).count()==0
                         and (cleared.get('plan') or {}).get('items')==[],{'pagePlan':cleared.get('plan'),'sessionId':identity}))
    _open_chat(worker,other_id)
    isolated=state('0 of 1','Next: '+other_steps[0]['step'])
    checks.append(_check('agents-clear-does-not-touch-other-chat',isolated['count']=='0 of 1'
                         and isolated['items']==[other_steps[0]['step']],isolated))
    worker.tool('neyvia.plan.update',{'sessionId':other_id,'plan':[]})
    _open_chat(worker,other_id)
    return _finish(worker,binding,checks,[],conversationId=cid,
        unprovedReason='Owner publication, progress, isolation, reload and clear were observed. Authentic provider plan add/update/delete streams and replay/limit cases remain unproved; no provider tool items, token usage or timestamps were fabricated.')


def _autopilot(worker,binding,root):
    identity,cid = _conversation(worker,root,'C8e Autopilot permission controls')
    _open_chat(worker,identity)
    toggle = worker.page.get_by_role('button',name='Autopilot',exact=True)
    toggle.click()
    scope = worker.page.get_by_role('radiogroup',name='What Autopilot may do',exact=True)
    scope.wait_for(timeout=15000)
    checks=[]
    for label,value in [('Look and edit','edit'),('Look only','look')]:
        options=scope.get_by_role('radio')
        option=options.filter(has_text=label)
        labels=options.all_text_contents()
        option.click()
        saved=worker.page.evaluate('id=>JSON.parse(localStorage.getItem("nx.autopilot."+id))',identity)
        checks.append(_check('autopilot-scope-durable-'+value,saved == {'on':True,'scope':value}
                             and option.get_attribute('aria-checked')=='true',{'saved':saved,'labels':labels}))
    toggle.click()
    checks.append(_check('autopilot-disable-restores-empty-default',worker.page.evaluate(
        'id=>localStorage.getItem("nx.autopilot."+id)',identity) is None,{'sessionId':identity}))
    return _finish(worker,binding,checks,[],conversationId=cid,
        unprovedReason='Mounted per-chat permission controls were exercised. scopeTools/scopeOf and model-call attribution/checkLine require actual Autopilot Start and a genuine configured planner/executor route; toggle persistence is not an execution grant or completed run.')


def _conductor(worker,binding,root):
    _home(worker)
    _pane(worker,'mission','conductor:new')
    form=worker.page.locator('.nx-cd-new')
    form.wait_for(timeout=15000)
    goal=form.locator('label').filter(has=worker.page.get_by_text('Goal',exact=True)).locator('textarea')
    folder=form.locator('label').filter(has=worker.page.get_by_text('Folder',exact=True)).locator('input')
    acceptance=form.locator('label').filter(has=worker.page.get_by_text('Checks the verifier must prove, one per line',exact=True)).locator('textarea')
    goal.fill('C8e safe goal draft, never execute')
    folder.fill('')
    matrix=_owner(worker,'/api/ui/runtime')
    worker.page.locator('.nx-cd-route').first.wait_for(timeout=15000)
    missing=form.locator('.nx-cd-problems li').all_text_contents()
    checks=[_check('conductor-real-required-draft-gates',any('folder' in p.lower() for p in missing)
                   and any('check' in p.lower() for p in missing)
                   and form.get_by_role('button',name='Plan it',exact=True).is_disabled(),{'problems':missing,'profiles':matrix.get('profiles',{})})]
    folder.fill(str(root)); acceptance.fill('No owned fixture was executed')
    missing=form.locator('.nx-cd-problems li').all_text_contents()
    profiles=matrix.get('profiles',{})
    missing_routes=[name for name in ['planner','executor','verifier'] if not profiles.get(name)]
    checks.append(_check('conductor-real-missing-routes-named',all(any(name in p.lower() for p in missing) for name in missing_routes),
                         {'problems':missing,'missingRoutes':missing_routes,'profiles':profiles}))
    goal.fill(' ')
    missing=form.locator('.nx-cd-problems li').all_text_contents()
    checks.append(_check('conductor-empty-goal-refused',"Say what should be true when it's done." in missing
                         and form.get_by_role('button',name='Plan it',exact=True).is_disabled(),{'problems':missing}))
    goal.fill('C8e safe goal draft, never execute')
    runtimes=[r for r in matrix.get('runtimes',[]) if r.get('id') in ['codex','claude-code','opencode','neyvia']
              and r.get('connected') and r.get('options',{}).get('models') and r.get('options',{}).get('permissionModes')]
    if not runtimes:
        return _finish(worker,binding,checks,[_contract('conductor.planProblems',checks,
            'Missing-field/route gates observed. No real runtime reports app/model/mode choices for a ready form.')],unprovedReason='A genuine configured execution transport is absent; no profile was invented.')
    runtime=next((r for r in runtimes if r['id']=='neyvia'),runtimes[0])
    options=runtime['options']
    model=next((m for m in options['models'] if m.get('default')),options['models'][0])
    mode=next((m for m in options['permissionModes'] if m['id']=='read-only'),options['permissionModes'][0])
    chosen_route={'app':runtime['id'],'model':model['id'],'permissionMode':mode['id']}
    try:
        for name,label in [('planner','Planner'),('executor','Executor'),('verifier','Verifier')]:
            row=form.locator('.nx-cd-route').filter(has=worker.page.get_by_text(label,exact=True))
            row.get_by_role('combobox',name=label+' app',exact=True).select_option(runtime['id'])
            row.get_by_role('combobox',name=label+' model',exact=True).select_option(model['id'])
            row.get_by_role('combobox',name=label+' permission',exact=True).select_option(mode['id'])
            with worker.page.expect_response(lambda r:r.url.endswith('/api/ui/runtime') and r.request.method=='POST') as pending:
                row.get_by_role('button',name='Save',exact=True).click()
            if pending.value.status!=200 or pending.value.json().get('ok') is False:
                raise RuntimeError('Real reported route save refused: '+pending.value.text())
            saved=_owner(worker,'/api/ui/runtime')
            checks.append(_check('conductor-real-reported-route-saved-'+name,saved['profiles'].get(name)==chosen_route,
                {'profile':name,'saved':saved['profiles'].get(name),'reportedRuntime':runtime['id'],
                 'reportedModel':model['id'],'auth':runtime.get('auth'),'boundary':'Saved reported options only; no inference or transport-readiness claim'}))
        missing=form.locator('.nx-cd-problems li').all_text_contents()
        checks.append(_check('conductor-route-validation-ready-without-submit',not missing
                             and not form.get_by_role('button',name='Plan it',exact=True).is_disabled(),
                             {'problems':missing,'submission':'Never clicked; no provider request','reportedAuth':runtime.get('auth')}))
        ready_artifact=worker.screenshot('effect-conductor-route-ready')
    finally:
        for name in ['planner','executor','verifier']:
            _owner(worker,'/api/ui/runtime',{'action':'profile','name':name,'route':profiles.get(name)})
        restored=_owner(worker,'/api/ui/runtime')
        if restored.get('profiles',{})!=profiles:
            raise RuntimeError('Reported-route validation did not restore exact original own profiles')
        worker.page.reload(wait_until='domcontentloaded')
        worker.page.locator('.nx-root').wait_for(timeout=15000)
        _pane(worker,'mission','conductor:new')
        worker.page.locator('.nx-cd-new').wait_for(timeout=15000)
    return _finish(worker,binding,checks,[_contract('conductor.planProblems',checks)],
        readyRouteArtifact=ready_artifact,restoredProfiles=profiles,
        unprovedReason='Planner/executor/verifier profiles with actual configured models are required for real job records, dependency/receipt totals, terminal worker and paging cases. No classifier/acceptance turn or completed job was seeded.')


def _gamedev(worker,binding,root):
    _home(worker)
    checks=[]
    # Stage routing can be proved without opening native editor windows.
    for app,target,expected in [('godot','','godot'),('asset-checks','','assets'),('playtest','','babylon'),
                                *[('godot',tab,tab) for tab in ['babylon','godot','unity','roblox','blender','assets']],
                                ('playtest','invalid-tab','babylon')]:
        worker.tool('neyvia.app.open',{'app':app,'target':target})
        tab=worker.page.locator('#nx-gd-tab-'+expected)
        tab.wait_for(timeout=15000)
        worker.page.wait_for_function('id=>document.querySelector("#nx-gd-tab-"+id)?.getAttribute("aria-selected")==="true"',arg=expected,timeout=15000)
        checks.append(_check('gamedev-stage-'+app+'-'+(target or 'default'),tab.get_attribute('aria-selected')=='true',
                             {'app':app,'target':target,'selectedTab':expected}))
    status=worker.tool('backend:gamedev_status_command',{})
    return _finish(worker,binding,checks,[_contract('gamedev.tabForStage',checks,
        'All explicit tab targets and ready Godot/Asset-check/Playtest aliases mounted. Unity/Roblox launcher aliases remain declared coming and were not bypassed.')],ownerStatus=status,
        unprovedReason='Actual stage aliases/explicit target priority were mounted. Typed Godot/Unity form conditions, native selection affinity, and genuine bridge action receipts require connected C11 editors; no native session or action response was fabricated.')


def run_effects(worker,binding,inputs,root):
    group=binding.get('c8eStateEffect')
    if not group:
        return [],{}
    return {'missions':_missions,'composer':_composer,'agents':_agents,
            'autopilot':_autopilot,'conductor':_conductor,'gamedev':_gamedev}[group](worker,binding,Path(root))
