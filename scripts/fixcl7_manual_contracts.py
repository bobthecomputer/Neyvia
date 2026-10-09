"""Author FIXCL7 acceptance in the owning Connected Language manual."""
from pathlib import Path
import json
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.cl.manuals import cl_to_manual,manual_to_cl
source=REPO/'manuals/cl/local-browser-sdk.cl'
manual=cl_to_manual(source.read_text(encoding='utf-8'))
chapter=manual['chapters']['evidence']
chapter['actions']['read-sdk-observation']={'tool':'workspace.read','schema':'workspace.read',
    'pre':'Use the bounded observation captured from the actual mounted child realm',
    'effect':'Read the exact mounted-runtime witness bytes','returns':{'type':'object'},'reversible':True}
chapter.setdefault('checks',{})['sdk-native-observation']={
    'tool':'workspace.read','args':{'path':{'$input':'observation'}},
    'expect':{'op':'schema','path':'content','schema':{'type':'string','allOf':[
        {'pattern':'"'+key+'"\\s*:\\s*true'} for key in (
            'actualMountedControlChangesState','nativeAppPixelsPresent','nativePhoneActuallyVisible',
            'previewActualPositiveCL','currentManualEffectReceipt')]}}}
chapter['procedures']['prove-sdk-mounted-observation']={
    'goal':'The actual mounted SDK child realm changes shared state and paints native iframe content',
    'inputs':{'type':'object','properties':{'observation':{'type':'string'}},'required':['observation']},
    'steps':[{'action':'read-sdk-observation','args':{'path':{'$input':'observation'}},
              'save':'mounted','check':'sdk-native-observation'}]}
manual['schemas']['workspace.read']={'type':'object','properties':{'path':{'type':'string'},
    'offset':{'type':'integer'},'limit':{'type':'integer'}},'required':['path']}
pitfall={'failure':'Phone layout passes but the iframe is blank',
    'recovery':'Require the mounted child identity, a real increment and native pixels. A separate same-URL context cannot replace the child realm.'}
if pitfall not in chapter['pitfalls']: chapter['pitfalls'].append(pitfall)
text=manual_to_cl(manual)
if cl_to_manual(text)!=manual:raise ValueError('Authored SDK contract failed its round trip')
source.write_text(text,encoding='utf-8',newline='\n')
print(json.dumps({'manual':manual['id'],'contract':'sdk-native-observation'}))
