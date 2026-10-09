"""Exercise C4 host safety on disposable real files, without model calls/ports.

Native ref generations use explicit fixtures here; real native/window journeys
are proved separately by the cohort runner, not claimed by these checks.
"""
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.cl.host import HostContext, model_value
from grant_agent.cl.turn_context import TurnContext, ContextBudgetError
from grant_agent.cl.renderer import StaleHandleError
from grant_agent.cl.tokens import count_tokens

def patch(value, operations):
    value = json.loads(json.dumps(value))
    for operation in operations:
        parts = [part.replace('~1', '/').replace('~0', '~') for part in operation['path'].split('/')[1:]]
        if not parts:
            value = operation.get('value')
            continue
        parent = value
        for part in parts[:-1]: parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
        if operation['op'] == 'remove':
            del parent[key]
        elif isinstance(parent, list) and operation['op'] == 'add': parent.insert(key, operation['value'])
        else: parent[key] = operation['value']
    return value

(REPO / '.agent_control' / 'c4-host').mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=REPO / '.agent_control' / 'c4-host') as folder:
    root = Path(folder)
    paths = {name: root / (name + '.json') for name in ('alpha', 'beta')}
    paths['alpha'].write_text(json.dumps({'title':'Alpha','items':[1,2,3],'obsolete':True}), encoding='utf-8')
    paths['beta'].write_text(json.dumps({'title':'Beta','items':[9]}), encoding='utf-8')
    generation = 0
    def dispatch(name, args, action_id=''):
        global generation
        path = paths[args.get('path','alpha')]
        state = json.loads(path.read_text(encoding='utf-8'))
        if name == 'files.read': return state
        if name == 'files.replace':
            path.write_text(json.dumps(args['state'], ensure_ascii=False), encoding='utf-8')
            return {'ok':True}
        if name == 'win.observe':
            generation += 1
            return {'elements':[{'element_token':f'token-{args["path"]}-{generation}-{i}',
                                 'role':'textbox','label':'Duplicate','value':state['title']}
                                for i in range(2)]}
        raise AssertionError(name)
    common = {'type':'object','properties':{'path':{'type':'string'}},'required':['path']}
    tools = [
        {'name':'files.read','inputSchema':common,'annotations':{'readOnlyHint':True}},
        {'name':'win.observe','inputSchema':common,'annotations':{'readOnlyHint':True}},
        {'name':'files.replace','effect':'!','inputSchema':{'type':'object','properties':{
            'path':{'type':'string'},'state':{'type':'object'}},'required':['path','state']}},
    ]
    contracts = {'files.replace':{'snapshot':lambda args:dispatch('files.read',args),
        'observation_identity':lambda args:('files.read',{'path':args['path']}),
        'checks_factory':lambda args:[{'name':'readback','observer':True,
            'check':lambda args,result,before:dispatch('files.read',args) == args['state']}],
        'impact':{'writes':'disposable json','undo':'restore original bytes'}}}
    host = HostContext(tools,dispatch,contracts=contracts,root=root,observation_mode='diff')
    first = host.execute('files.read(path="alpha")')
    again_unack = host.execute('files.read(path="alpha")')
    assert ' full\n' in first['text'] and ' full\n' in again_unack['text']
    host.acknowledge_observations()
    unchanged = host.execute('files.read(path="alpha")')
    assert ' unchanged base=' in unchanged['text']
    beta = host.execute('files.read(path="beta")')
    assert ' full\n' in beta['text']
    baseline = next(row for row in host.observation_baselines.values() if row['inputs']['path']=='alpha')
    before = baseline['visible']
    host.execute('G: files.read(path="alpha").title == "Changed"')
    changed = host.execute('files.replace(path="alpha", state={"title":"Changed","items":[1,4]})\ndone("verified")')
    assert changed['ok'] and changed['doneStatus']=='ok', changed
    mutation_lines = changed['results'][0]['cl'].splitlines()
    assert len([line for line in mutation_lines if line.startswith('D files ')]) <= 1, 'Duplicate mutation patch'
    assert not any(line.startswith('D files ') for line in mutation_lines[:next(i for i,line in enumerate(mutation_lines) if line.startswith('S files '))]), 'Unbased mutation patch before state header'
    after = json.loads(paths['alpha'].read_text(encoding='utf-8'))
    operations = HostContext._observation_changes(before,after)
    assert patch(before,operations)==after
    assert {'op':'remove','path':'/obsolete'} in operations and {'op':'remove','path':'/items/2'} in operations
    raw_receipt = host.resolve(changed['results'][0]['receipt'])
    assert raw_receipt['before']==before and raw_receipt['after']==after and raw_receipt['checks'][0]['passed']
    native_a = host.execute('win.observe(path="alpha")')
    refs_a = [ref for ref in host.live_refs() if ref.startswith('e')]
    native_b = host.execute('win.observe(path="beta")')
    assert all(ref in host.live_refs() for ref in refs_a), 'Unrelated subject invalidated native refs'
    host.acknowledge_observations()
    refreshed = host.execute('win.observe(path="alpha")')
    assert ' refresh base=' in refreshed['text'] and 'E refs=' in refreshed['text']
    assert all(ref not in host.live_refs() for ref in refs_a)
    try: host.resolve(refs_a[0]); raise AssertionError('Stale ref accepted')
    except StaleHandleError: pass
    new_a = [ref for ref in host.live_refs() if ref.startswith('e') and host.refs[ref]['value']['value']=='Changed']
    mapping = json.loads(next(line.split('=',1)[1] for line in refreshed['text'].splitlines() if line.startswith('E refs=')))
    assert set(mapping.values())=={'/elements/0','/elements/1'}, mapping
    stale_page = host.execute('project(' + refs_a[0] + ')')
    assert not stale_page['ok'], 'Projection accepted a stale native ref'
    page_ref = host._put({'a/b':{'~key':'abcdef'},'next':2,'last':3})
    projected = host.execute('project(' + page_ref + ',path="/a~1b/~0key",start=2,count=2)')
    assert projected['results'][0]['result'] == 'cd'
    assert projected['results'][0]['page']['nextStart'] == 4
    projected = host.execute('project(' + page_ref + ',start=1,count=1)')
    assert projected['results'][0]['result'] == {'next':2}
    assert not host.execute('project(' + page_ref + ',start=-1)')['ok']
    assert not host.execute('project(' + page_ref + ',count=0)')['ok']
    context = TurnContext('Keep the exact immutable task and verify actual files.',
                          'Emit CL actions; use project(ref) and context.read(handle) for missing state.',
                          token_budget=1600,archive_dir=root/'archive',recent_results=2)
    failed_handle = context.append('result','R files.replace refused\nX cannot mutate without permission\n',{'ok':False,'status':'refused'})
    original = '\n'.join(f'Observation {i}: measured label and result {i*i}' for i in range(900))
    archive_handle = context.append('result',original,{'ok':True})
    context.append('proposal','files.read(path="alpha")')
    prompt = context.prompt(host=host,guidance=host.help('files'))
    assert prompt.startswith(context.prefix) and context.task in prompt
    assert count_tokens(prompt)<=1600 and context.metrics['compactions']>0
    assert archive_handle in prompt and failed_handle in prompt and 'CURRENT ' in prompt
    assert context.read('index',count=4000)
    output = json.loads(context.read(archive_handle,start=30,count=120))
    assert output['text']==original[30:150] and output['nextStart']==150
    assert TurnContext(context.task,context.prefix,archive_dir=root/'archive').read(archive_handle,start=30,count=120)==context.read(archive_handle,start=30,count=120)
    try: TurnContext(' '.join(f'large-{i}' for i in range(500)), 'Small prefix',token_budget=100,archive_dir=root/'reject'); raise AssertionError('Oversized task accepted')
    except ContextBudgetError: pass
    assert not (root/'reject').exists()
    host.acknowledge_observations(context.acknowledgeable_state_refs,replace=True)
    assert not host.observation_baselines, 'Compacted-away state incorrectly acknowledged'
    full_again = host.execute('files.read(path="alpha")')
    assert ' full\n' in full_again['text']
    record_path = root/'archive'/(archive_handle+'.json')
    bad = json.loads(record_path.read_text(encoding='utf-8'))
    bad['record']['content']='tampered'
    record_path.write_text(json.dumps(bad),encoding='utf-8')
    try: context.read(archive_handle); raise AssertionError('Tampered history accepted')
    except ValueError: pass
    from grant_agent.cl.host import unwrap
    failed_native = {'tool':'neyvia.notes.read','ok':False,'status':'failed','result':{},'error':'owned service unavailable'}
    assert unwrap(failed_native)['ok'] is False and unwrap(failed_native)['error']=='owned service unavailable'
    paths['alpha'].write_text(json.dumps({'title':'actual payload '+('abcdefghij0123456789 '*900)}),encoding='utf-8')
    host.acknowledge_observations([],replace=True)
    large=host.execute('files.read(path="alpha")')
    latest_ref=next(row['stateRef'] for row in host.observation_states.values() if row['inputs'].get('path')=='alpha' and row['observer']=='files.read')
    pages=TurnContext('Read alpha using complete paged history.', 'Use explicit history pages.',
                      token_budget=1200,archive_dir=root/'paged-archive')
    pages.append('result',large['text'],{'ok':True})
    bounded=pages.prompt(host=host)
    assert 'HISTORY PAGE ' in bounded and count_tokens(bounded)<=1200
    assert latest_ref not in pages.acknowledgeable_state_refs, 'Partial history page acknowledged as full state'
    oversized_ref=host._put({'content':'abcde '*1000})
    projected=host.execute('project('+oversized_ref+')')
    assert 'large field; value available by page' in projected['text']
    assert '/content' in projected['text'] and projected['results'][0]['result']['content']=='abcde '*1000
    receipt = {'ok':True,'scope':'actual disposable JSON files via production CL HostContext; native token fixtures only',
        'checks':['unacknowledged full','acknowledged unchanged','observer subject isolation','lossless removals',
                  'real mutation/readback/done goal','raw receipt preservation','native subject isolation','ref refresh/staleness',
                  'duplicate native path bindings','exact o200k context cap','durable paged history','immutable task refusal',
                  'compacted state not acknowledged','integrity rejection','native failure envelope preserved',
                  'single based mutation observation','paged dict/string JSON Pointer projection','stale projection refused',
                  'latest result explicit history page','partial page not acknowledged','oversized field exact raw preservation'],
        'tokens':context.metrics,'archiveCharacters':len(original),'statePatch':operations,
        'runs':{'first':first,'unchanged':unchanged,'mutation':changed,'refresh':refreshed},
        'prompt':prompt}
    output = REPO / 'scripts' / 'evidence' / 'C4-host.json'
    output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'checks':receipt['checks'],'tokens':context.metrics,'receipt':str(output)}))
