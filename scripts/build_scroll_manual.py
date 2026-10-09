"""Refresh the scroll manual's schemas from its real native definitions."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.neyvia_scroll import DEFINITIONS
path=ROOT/'manuals/scroll-generator.manual.json'
data=json.loads(path.read_text(encoding='utf-8'))
chapter=data['chapters']['overview']
for name,description,props,required in DEFINITIONS:
    tool='neyvia.'+name
    data['schemas'][tool]={'type':'object','properties':props,'required':required}
    chapter['actions'][name.removeprefix('scroll.')]={'tool':tool,'schema':tool,'returns':{'type':'object'},'pre':'Observe the selected workspace pack; approval is required before export','effect':description,'reversible':True}
chapter['state']['pack']['shape']={'type':'object','properties':{'ok':{'type':'boolean'},'packs':{'type':'array'}},'required':['ok','packs']}
chapter['state']['pack']['inputs']['properties']['pack']={'type':'string','minLength':1}
chapter['procedures']['validate-pack']['inputs']['properties']['pack']={'type':'string','minLength':1}
chapter['frontier']=[line for line in chapter['frontier'] if 'no T5' not in line]
compilation_frontier='Validated packs can compile after three real grounded manual runs. Compiled validation remains input/manual/provenance-bound and rechecks current cards.'
if compilation_frontier not in chapter['frontier']:
    chapter['frontier'].append(compilation_frontier)
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
index_path=ROOT/'config/neyvia_manuals.json'
index=json.loads(index_path.read_text(encoding='utf-8'))
if not any(row['id']=='scroll-generator' for row in index['manuals']):
    index['manuals'].append({'id':'scroll-generator','path':'manuals/scroll-generator.manual.json','description':'Source-bound Scroll Study generation, review, pack validation, costs and executable compiled checks'})
index_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
descriptor=ROOT/'apps/scroll-study/neyvia.app.json'
app=json.loads(descriptor.read_text(encoding='utf-8'))
app.update(stateApi='window.neyviaApp.state()',commitApi='window.neyviaApp.act(name,args,options)',transport='device-local-indexeddb',sdkSource={'branch':'track/a1-appsdk','commit':'0e4aab00','conventions':'CL 1.1 describe/state/act, action identity, revision guards and observer goals; feed reducer specializes the counter template'})
descriptor.write_text(json.dumps(app,indent=2)+'\n',encoding='utf-8')
print('Scroll manual and A1 device-local conventions refreshed')
