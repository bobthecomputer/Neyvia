"""Actual gateway creation, CAS edit and standalone observer proof, no model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import zipfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO / 'src'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
if not 48731 <= args.port <= 48739: raise ValueError('Explicit owned C4b port required')
os.environ.update(NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}',NEYVIA_TOOL_AUTO_UPDATE='0',
                  FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0')
from grant_agent.neyvia_agent import NeyviaToolGateway
from grant_agent.cl.protocol import Protocol
from grant_agent.cl.integration import _goal

root=REPO / '.agent_control/c4' / ('production-'+str(time.time_ns()))
root.mkdir(parents=True)
p=Protocol(NeyviaToolGateway(root,allow_mutations=True,permission_mode='full-access'))
h=p.host
h.observation_mode='diff'
rows=[]
def call(text):
    value=p.run(text)
    rows.append({'proposal':text,'result':value})
    return value
checks={}
call('G: len(workspace.read(path="proof.txt")["content"]) > 0')
created=call('run workspace.create-and-read(path="proof.txt",content="first °→±")\ndone()')
checks['grounded_procedure_creates_and_finishes']=created['ok'] and p.completion()['status']=='completed'
checks['actual_unicode_bytes']=(root / 'proof.txt').read_bytes()=='first °→±'.encode()
read=call('workspace.read(path="proof.txt")')
checks['standalone_text_read_not_css_procedure']=read['ok'] and 'first °→±' in read['text']
h.acknowledge_observations()
changed=call('run workspace.replace-and-read(path="proof.txt",content="second",replace="replace")\ndone()')
checks['existing_procedure_cas_and_readback']=changed['ok'] and (root / 'proof.txt').read_bytes()==b'second'
recreate=call('run workspace.create-and-read(path="proof.txt",content="overwrite")')
checks['create_refuses_existing']=not recreate['ok'] and (root / 'proof.txt').read_bytes()==b'second'
bad=call('workspace.write(path="proof.txt",content="stale",expectedSha256="'+'0'*64+'")')
checks['stale_hash_refused']=not bad['ok'] and (root / 'proof.txt').read_bytes()==b'second'
schema=_goal({'tool':'workspace.read','args':{'path':'proof.txt'},
              'expect':{'op':'schema','path':'content','schema':{'type':'string','pattern':'^first'}}})
checks['procedure_schema_remains_enforced']=h.evaluate(schema)['passed'] is False
fetched=call('web.fetch(url="https://devguide.python.org/versions/",maxChars=12000)')
checks['real_fetch_read_class_and_document_payload']=fetched['ok'] and 'doc_' in fetched['text'] and '3.' in fetched['text'] and '\nS web ' in fetched['text']
from grant_agent.neyvia_notes_tools import call_notes
os.environ['NEYVIA_NOTES_DIR']=str(root / 'Notes')
original='# Ideas\n\nPreserve this note.\n'
call_notes(root,'write',{'path':'Ideas.md','body':original},local=True)
call_notes(root,'pin',{'path':'Ideas.md','pinned':True},local=True)
body='# Weekend plan\n\n#home #todo\n\n- [ ] Laundry\n- [ ] Groceries\n- [ ] Clean desk\n- [ ] Walk\n'
call_notes(root,'write',{'path':'Weekend plan.md','body':body},local=True)
call_notes(root,'pin',{'path':'Weekend plan.md','pinned':True},local=True)
before=call_notes(root,'read',{'path':'Weekend plan.md'},local=True)
call_notes(root,'write',{'path':'Weekend plan.md','body':'Call grandma Sunday 11:00','mode':'append',
                       'expectedModified':before['modified']},local=True)
note=call_notes(root,'read',{'path':'Weekend plan.md'},local=True)
ideas=call_notes(root,'read',{'path':'Ideas.md'},local=True)
checks['local_notes_real_create_pin_append_readback']=note['pinned'] and 'Call grandma Sunday 11:00' in note['body']
checks['local_notes_preserve_other_pinned_note']=ideas['pinned'] and ideas['body']==original
from grant_agent.cl.parser import logical_lines,parse_action
adverse=REPO / '.agent_control/c4/c4b-typed-panel/efficient/t1-ui/result.json'
sealed=REPO / 'scripts/evidence/C4b/c4b-typed-panel.zip'
if sealed.is_file():
    with zipfile.ZipFile(sealed) as archive:
        original=json.loads(archive.read('c4b-typed-panel/efficient/t1-ui/result.json'))
elif adverse.is_file():
    original=json.loads(adverse.read_text(encoding='utf-8'))
else:
    raise ValueError('Preserved multiline adverse receipt is required for C4b replay')
proposals=original['run']['actions']
proposal=next(row['proposal'] for row in proposals if "content='''" in row['proposal'])
lines=[line for line in logical_lines(proposal) if line.strip()]
authored=next(parse_action(line).arguments['content'] for line in lines if 'workspace.create-and-read(' in line)
replayed=call(proposal)
checks['preserved_real_multiline_proposal_executes_one_batch']=len(lines)<=24 and replayed['ok']
checks['multiline_artifact_exact_bytes']=(root / 'index.html').read_bytes()==authored.encode('utf-8')
receipt={'passed':all(checks.values()),'checks':checks,'rows':rows,'root':str(root),
         'sourceSha256':{name:hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in
                        ('src/grant_agent/cl/integration.py','src/grant_agent/cl/protocol.py','src/grant_agent/cl/parser.py','src/grant_agent/cl/host.py','src/grant_agent/neyvia_notes_tools.py','manuals/cl/workspace.cl')}}
target=REPO / 'scripts/evidence/C4-production.json'
target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':receipt['passed'],'checks':checks},ensure_ascii=False),flush=True)
raise SystemExit(0 if receipt['passed'] else 1)
