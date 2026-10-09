"""Observe an alternate real filing destination; never manufacture its status."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.taste_fewshot import save
from grant_agent.taste_episode_export import destinations,append

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--arm',required=True,choices=['luna-alone','fusion-v2','sol-alone'])
    parser.add_argument('--port',type=int,required=True);parser.add_argument('--engine-port',type=int,required=True)
    args=parser.parse_args();source=REPO/'proof/r12'/args.arm/'T2/work/rare-ui.html'
    source_bytes=source.read_bytes();digest=hashlib.sha256(source_bytes).hexdigest()
    out=Path('D:/NeyviaRuns/r12/diagnostics')/(args.arm+'-alternate-'+digest[:12]);out.mkdir(parents=True,exist_ok=True)
    snapshot=out/'source.html';snapshot.write_bytes(source_bytes)
    recipe={'#filing-pad':{'target':'#filing-pad','keys':['Space'],
        'actionKeys':['Space','ArrowDown','Enter'],'assert':'#filing-status','expect':'Discard sample'}}
    save(out/'journeys.json',recipe)
    command=['node',str(REPO/'scripts/c13i_alternate.mjs'),'--html',str(snapshot),'--out',str(out/'alternate'),
        '--port',str(args.port),'--engine-port',str(args.engine_port)]
    call=subprocess.run(command,cwd=REPO,capture_output=True,text=True,encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW)
    report=json.loads((out/'alternate/report.json').read_bytes())
    if report['html_sha256']!=digest:raise ValueError('Probe source binding changed')
    modes=[m for c in report['variants'][0]['controls'] for m in c['modes']]
    result={'arm':args.arm,'sourceSha256':digest,'sourceSnapshot':str(snapshot),'reportPath':str(out/'alternate/report.json'),
        'reportSha256':hashlib.sha256((out/'alternate/report.json').read_bytes()).hexdigest(),
        'destinations':modes,'keyboardPassed':report['passed'],
        'scope':'Two alternate real destinations with delivered keyboard input; not full-page coverage.'}
    save(REPO/'proof/r12/diagnostics'/(args.arm+'-alternate.json'),result)
    append(destinations(result))
    print(json.dumps(result))
if __name__=='__main__':main()
