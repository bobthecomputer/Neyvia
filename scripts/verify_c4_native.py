"""Read-only preflight for the R4 owner-granted Character Map target."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO / 'src'))
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port',required=True,type=int)
args=p.parse_args()
if not 48731<=args.port<=48739: raise ValueError('Explicit owned C4b port required')
os.environ.update(NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}',NEYVIA_TOOL_AUTO_UPDATE='0',
                  FLUXIO_WATCHDOG_AUTOSTART='0',NEYVIA_COORDINATOR_AUTOSTART='0')
from grant_agent.neyvia_cua import service_for
from grant_agent.cua_upstream import runtime_status
root=REPO / '.agent_control/c4' / ('native-presence-'+str(time.time_ns()))
root.mkdir(parents=True)
service=service_for(root)
try:
    session=service.request('open',{'apps':['charmap'],'chatId':'c4-target-presence','app':'neyvia'},owner=True)
    state=service.request('windows',{'sessionId':session['id']})
    value={'schema':'neyvia.c4-native-preflight.v1','runtime':runtime_status(),
           'port':args.port,'session':session,'state':state,'targetPresent':bool(state['windows']),
           'completedR4Task':False,'actions':[],
           'blocker':None if state['windows'] else 'The requested existing Character Map window is absent',
           'nextAction':'Paul opens Character Map, then rerun t5 with a fresh run-id',
           'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    service.request('end',{'sessionId':session['id']},owner=True)
except Exception as exc:
    value={'schema':'neyvia.c4-native-preflight.v1','runtime':runtime_status(),'port':args.port,
           'completedR4Task':False,'actions':[],'targetPresent':None,
           'blocker':f'{type(exc).__name__}: {exc}',
           'nextAction':'Paul opens Character Map and verifies native access, then rerun t5 with a fresh run-id',
           'sourceSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
finally:
    service.shutdown()
target=REPO / 'scripts/evidence/C4-native.json'
target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(value,ensure_ascii=False),flush=True)
