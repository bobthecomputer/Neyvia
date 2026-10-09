"""Author bounded first-run failure checks in the executable onboarding manual."""
from copy import deepcopy
from rel_agent_manual import load, save

path, data = load('onboarding')
_, shell = load('neyvia')
section = data['chapters']['release-tour']
action = deepcopy(shell['chapters']['panes']['actions']['window-state'])
data['schemas'][action['schema']] = deepcopy(shell['schemas'][action['schema']])
section['actions']['view.state'] = action
warning = 'Large local saves are unavailable. Saved data has been kept. Keep this window open until server sync completes, then reload to retry.'
for key, field, value in [('workspace-mounted','mounted',True),
                          ('storage-warning-visible','storage.warningVisible',True),
                          ('storage-warning-honest','storage.text',warning)]:
    section['checks'][key] = {'tool':'neyvia.view.state','args':{},
        'expect':{'path':'state.dom.'+field,'op':'eq','value':value}}
section['procedures']['verify-storage-warning'] = {
    'goal':'Verify the mounted workspace remains usable when large local storage fails, with a visible retained-data warning. This is a disposable failure-path contract.',
    'inputs':{'type':'object','properties':{}},
    'steps':[{'action':'view.state','args':{},'save':key,'check':key}
        for key in ['workspace-mounted','storage-warning-visible','storage-warning-honest']]}
save(path, data)

path, data = load('image-studio')
section = data['chapters']['overview']
data['schemas'][action['schema']] = deepcopy(shell['schemas'][action['schema']])
section['actions']['view.state'] = deepcopy(action)
for key, field, value in [('preview-ready','state.status','ready'),
                          ('preview-fresh','state.fresh',True),
                          ('preview-asset','state.assetId',{'$input':'assetId'})]:
    section['checks'][key] = {'tool':'neyvia.image.state','args':{},'expect':{'path':field,'op':'eq','value':value}}
section['checks']['preview-shell-fresh'] = {'tool':'neyvia.view.state','args':{},'expect':{'path':'state.fresh','op':'eq','value':True}}
section['checks']['preview-window-visible'] = {'tool':'neyvia.view.state','args':{},'expect':{'path':'state.dom.windows','op':'schema','schema':{
    'type':'array','contains':{'type':'object','required':['id','visible','placement'],'properties':{
        'id':{'const':'app:image-studio'},'visible':{'const':True},'placement':{'enum':['main','side','full']}}}}}}
section['procedures']['verify-live-preview'] = {'goal':'Verify the exact decoded asset reported by Image Studio and its current visible shell window. Opening a file alone is not preview proof.',
    'inputs':{'type':'object','properties':{'assetId':{'type':'string'}},'required':['assetId']},
    'steps':[{'action':tool,'args':{},'save':key,'check':key} for tool,key in [
        ('image.state','preview-ready'),('image.state','preview-fresh'),('image.state','preview-asset'),('view.state','preview-shell-fresh'),('view.state','preview-window-visible')]]}
save(path,data)
