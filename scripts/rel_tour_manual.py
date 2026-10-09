"""Author release-tour verification in the existing executable manual."""
from copy import deepcopy
from pathlib import Path
from rel_agent_manual import load, save, chapter, synchronize_schemas, NativeToolRegistry

path, data = load('onboarding')
registry = NativeToolRegistry(Path('D:/NeyviaRuns/REL/manual-runtime'))
section = chapter('Release tour: every universal feature and the mounted player')
original = data['chapters']['overview']
for action in ('onboarding.recommend', 'onboarding.open'):
    section['actions'][action] = deepcopy(original['actions'][action])
data['schemas']['rel_view_state'] = deepcopy(registry._specs['neyvia.view.state'].input_schema)
section['checks']['tour-mounted'] = {'tool':'neyvia.view.state','args':{},
    'expect':{'path':'state.dom.setup.mounted','op':'eq','value':True}}
section['procedures']['open-release-tour'] = {'goal':'Open the real tour player and observe the mounted setup view.',
    'inputs':{'type':'object','properties':{}},
    'steps':[{'action':'onboarding.open','args':{'step':'tour'},'save':'opened','check':'tour-mounted'}]}
steps = []
for identity in ('basics','runtimes','notes','studio','laya','look','placement','watching','factory','connectors','images'):
    key = 'includes-' + identity
    section['checks'][key] = {'tool':'neyvia.onboarding.recommend','args':{'interests':[]},
        'expect':{'path':'chapters','op':'contains','value':identity}}
    steps.append({'action':'onboarding.recommend','args':{'interests':[]},'save':identity,'check':key})
section['procedures']['verify-universal-features'] = {'goal':'Ensure every new feature is shown even when no interest is selected.',
    'inputs':{'type':'object','properties':{}},'steps':steps}
section['guidance'] = ['The player uses shipped entry components and explicitly labelled examples. Availability still depends on this PC, provider sign-in and installed toolchains. These catalog checks prove coverage; inspect the rendered player separately.']
section['frontier'] = ['No tour scene proves a microphone, paid generation, connector or recorded agent run is available.']
data['chapters']['release-tour'] = section
synchronize_schemas(data, registry)
save(path, data)
