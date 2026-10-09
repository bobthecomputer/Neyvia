"""Final production tool calls after schema/provenance guard changes."""
import hashlib
import json
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.neyvia_perception import call
from grant_agent.neyvia_manuals import document,validate,render
from grant_agent.native_tools import NativeToolRegistry
from grant_agent import manual_state

root=(REPO/'scripts/evidence/.t18-runtime').resolve()
w=workspace_for(root)
rows=[]
(root/'multiline.csv').write_bytes(b'id,note\n000739,"hello\nworld"\n')
o=call(w,'perception.observe',{'layer':'file','source':{'path':'multiline.csv'},'reset':True})
p=call(w,'perception.project',{'handle':o['handle'],'path':'/state/rows/1'})
rows.append({'name':'csv-multiline-exact','passed':p['value']==['000739','hello\nworld'],'receipt':p})
before=hashlib.sha256((root/'notes/sample.md').read_bytes()).hexdigest()
refused=False
try:
    call(w,'perception.observe',{'layer':'app','source':{'tool':'neyvia.notes.write','arguments':{'path':'sample.md','body':'bad'}}})
except PermissionError:
    refused=True
rows.append({'name':'mutating-app-observer-refused','passed':refused and before==hashlib.sha256((root/'notes/sample.md').read_bytes()).hexdigest()})
a=w.call('manual.run',{'id':'perception','chapter':'file','procedure':'read-and-review','inputs':{'source':{'path':'numbers.json'}}})
b=w.call('manual.run',{'id':'perception','chapter':'file','procedure':'read-and-review','runId':a['runId'],'decisions':{'coverage':'answer'}})
rows.append({'name':'current-manual-judge-resume','passed':a['status']=='judge' and b['status']=='completed','start':a,'resume':b})
manual=document({'id':'perception','path':'manuals/perception.manual.json'})[1]
v=validate(manual,NativeToolRegistry(root))
rows.append({'name':'current-fourteen-procedures-grounded','passed':v['grounded'] and len(v['procedures'])==14})
image=call(w,'perception.observe',{'layer':'image','source':{'path':'chart.png'},'reset':True})
state=manual_state.read(root/'.neyvia/perception',image['handle'])['value']
rows.append({'name':'cached-visual-provenance-preserved','passed':state['state']['interpretation']['model']=='gpt-6-luna' and image['extraction']['cacheHit'],'receipt':image})
data={'gates':rows,'allPassed':all(r['passed'] for r in rows)}
(REPO/'scripts/evidence/T18-final.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
(REPO/'scripts/evidence/T18-manual.txt').write_text('\n'.join(render(c,manual['schemas']) for c in manual['chapters'].values()),encoding='utf-8')
print(json.dumps({'passed':sum(r['passed'] for r in rows),'total':len(rows)}))
raise SystemExit(0 if data['allPassed'] else 1)
