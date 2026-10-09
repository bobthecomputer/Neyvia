"""Append real provider/manual completion procedures, preserving old chapters."""
from pathlib import Path
import json
import sys

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.manuals import cl_to_manual,manual_to_cl
from grant_agent.neyvia_autopilot import DEFINITIONS as AUTOPILOT
from grant_agent.neyvia_conductor import DEFINITIONS as CONDUCTOR


def append(identity,definitions,names):
    artifact=REPO/'manuals'/(identity+'.manual.json')
    source=REPO/'manuals/cl'/(identity+'.cl')
    data=json.loads(artifact.read_bytes());text=source.read_text(encoding='utf-8')
    if cl_to_manual(text)!=data:
        raise ValueError('Source/artifact mismatch before edit: '+identity)
    if 'fixcl4-real' in data['chapters']:
        return
    chapter={'title':'Actual provider and manual completion','state':{},'actions':{},'checks':{},'procedures':{},'judge':{},
      'pitfalls':[{'failure':'A queued admission or provider call is called completed','recovery':'Read the retained owner and require actual terminal provider/manual receipts and fresh acceptance.'}],
      'frontier':['Selected provider unavailability or model refusal is retained as a failure; no provider substitution or fabricated output.'],
      'guidance':['Reuse the exact request identity and original scope. Completed resumes verify retained effects without replaying completed work.']}
    for short,description,properties,required in definitions:
        if short not in names:
            continue
        tool='neyvia.'+short;schema={'type':'object','properties':properties,'required':required}
        data['schemas'][tool]=schema
        chapter['actions'][short]={'tool':tool,'schema':tool,'returns':{'type':'object'},
          'pre':'Explicit selected provider, original caller tool scope and bounded owned workspace',
          'effect':description,'reversible':False}
        chapter['procedures']['verify-'+short.replace('.','-')]={'goal':description,'inputs':schema,
          'steps':[{'action':short,'args':{key:{'$input':key} for key in properties},'save':'effect'}]}
    data['chapters']['fixcl4-real']=chapter
    generated=manual_to_cl(data,{('neyvia.'+name):{} for name in names})
    # New alias schemas can change compiler type identities. Recompile the
    # complete lossless document instead of stitching incompatible T names.
    result=generated
    if cl_to_manual(result)!=data:
        raise ValueError('Additive manual did not roundtrip: '+identity)
    for target,content in ((artifact,json.dumps(data,indent=2,ensure_ascii=False)+'\n'),(source,result)):
        ending='\r\n' if b'\r\n' in target.read_bytes() else '\n'
        target.write_bytes(content.replace('\n',ending).encode())


if __name__=='__main__':
    append('autopilot',AUTOPILOT,{'autopilot.start','autopilot.resume'})
    append('conductor',CONDUCTOR,{'conductor.plan','conductor.control'})
    print(json.dumps({'ok':True,'manuals':['autopilot','conductor']}))
