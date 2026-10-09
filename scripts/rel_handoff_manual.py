"""Author owner hand-off checks in the existing Connected Language manual."""
from copy import deepcopy
from rel_agent_manual import load, save, NativeToolRegistry
from pathlib import Path

path, data = load('browser')
registry = NativeToolRegistry(Path('D:/NeyviaRuns/REL/manual-runtime'))
for chapter in data['chapters'].values():
    for action in chapter['actions'].values():
        spec = registry._specs.get(action['tool'])
        if spec:
            data['schemas'][action['schema']] = deepcopy(spec.input_schema)
section = data['chapters']['goal-cascade']
section['actions']['browser.state'] = deepcopy(next(action for chapter in data['chapters'].values()
    for action in chapter['actions'].values() if action['tool'] == 'neyvia.browser.state'))
section['actions']['browser.task.pause']['effect'] = 'Revoke agent control, persist needs_owner, and open the same owned live tab in the right pane. CL requires an actual mounted pane before completion.'
section['actions']['browser.task.pause']['returns']['properties'].update(paneId={'type':'string'},paneEventId={'type':'string'})
section['checks']['owner-pane-visible'] = {'tool':'neyvia.pane.observe','args':{'eventId':{'$result':'handoff.paneEventId'}}, 'expect':{'path':'visible','op':'eq','value':True}}
section['checks']['owner-pane-tab'] = {'tool':'neyvia.pane.observe','args':{'eventId':{'$input':'eventId'}}, 'expect':{'path':'target','op':'eq','value':{'$input':'tabId'}}}
section['procedures']['request-owner-handoff'] = {'goal':'Pause on an observed wall, revoke agent control and witness the same live browser tab in the right pane. Only the owner can clear the wall and resume.',
    'inputs': deepcopy(data['schemas']['neyvia.browser.task.pause']),
    'steps':[{'action':'browser.task.pause','args':{'tabId':{'$input':'tabId'},'goal':{'$input':'goal'},'requirements':{'$input':'requirements'}},'save':'handoff','check':'owner-pane-visible'}]}
checked = deepcopy(section['procedures']['request-owner-handoff'])
checked['inputs']['required'].append('checks')
checked['steps'][0]['args']['checks'] = {'$input':'checks'}
checked['goal'] += ' Preserve explicit completion predicates for owner resume.'
section['procedures']['request-checked-owner-handoff'] = checked
for key, field, expected in [('owner-paused','ownerTask.status','needs_owner'),('agent-revoked','agentGranted',False),('owner-resumed','ownerTask.status','done'),('agent-restored','agentGranted',True)]:
    section['checks'][key] = {'tool':'neyvia.browser.state','args':{},'expect':{'path':'tabs.0.'+field,'op':'eq','value':expected}}
section['checks']['sole-controlled-tab'] = {'tool':'neyvia.browser.state','args':{},'expect':{'path':'tabs','op':'schema','schema':{'type':'array','minItems':1,'maxItems':1}}}
section['checks']['owner-resumed-tab'] = {'tool':'neyvia.browser.state','args':{},'expect':{'path':'tabs','op':'schema','schema':{
    'type':'array','contains':{'type':'object','required':['id','ownerTask','agentGranted'],'properties':{
        'id':{'const':{'$input':'tabId'}},'agentGranted':{'const':True},'ownerTask':{'type':'object','required':['status'],'properties':{'status':{'const':'done'}}}}}}}}
section['procedures']['verify-owner-resumed'] = {'goal':'Observe completion and restored grant on the exact controlled task tab after an explicit owner resume.',
    'inputs':{'type':'object','properties':{'tabId':{'type':'string'}},'required':['tabId']},
    'steps':[{'action':'browser.state','args':{},'save':'completed','check':'owner-resumed-tab'}]}
section['guidance'] = [text for text in section['guidance'] if not text.startswith('Use request-owner-handoff on')]
section['guidance'] += ['Use request-owner-handoff on a freshly observed CAPTCHA or bot check; use request-checked-owner-handoff to retain explicit completion predicates. The same tab, profile and runtime stay in use; no solver or engine switch is introduced. The right pane remains interactive for the owner. Resume task is owner-only and re-observes the page; an uncleared wall remains needs_owner, and a second resume refuses. A queued pane is not rendered proof.']
save(path, data)
