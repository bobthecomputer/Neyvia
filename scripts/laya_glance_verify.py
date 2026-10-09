"""Run the authored manual through Neyvia, compile and replay verified procedures."""
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
for key in ('NEYVIA_TOOL_AUTO_UPDATE','NEYVIA_COORDINATOR_AUTOSTART','FLUXIO_WATCHDOG_AUTOSTART'):
    os.environ[key]='0'
from grant_agent.neyvia_gateway import NeyviaToolGateway
from grant_agent.neyvia_manuals import unwrap

root=ROOT/'.agent_control/layag-contracts'
gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace',managed_capabilities=False)
run=str(time.time_ns())
report={'procedures':{}}
for procedure in ('prove-scenes','prove-pixels','prove-sdk-seam'):
    args={'id':'laya-glance','chapter':'scene','procedure':procedure,'inputs':{}}
    receipts=[]
    for i in range(2):
        result=gateway.call_native('neyvia.manual.run',args,action_id=f'layag-{procedure}-{run}-{i}')
        receipts.append(result)
        if not result.get('ok'):
            print(json.dumps(result,default=str)[-4000:])
            raise SystemExit(1)
    compiled=gateway.call_native('neyvia.manual.compile',{**args,'minRuns':2},action_id=f'layag-compile-{procedure}-'+run)
    receipts.append(compiled)
    script=unwrap(compiled)
    if not script.get('scriptId'):raise RuntimeError(str(script))
    replay=gateway.call_native('neyvia.manual.script.run',{'scriptId':script['scriptId'],'inputs':{}},action_id=f'layag-replay-{procedure}-'+run)
    receipts.append(replay)
    report['procedures'][procedure]={'passed':bool(replay.get('ok')),'runs':2,'compiledReplay':bool(replay.get('ok')),'receipts':receipts}
report['passed']=all(r['passed'] for r in report['procedures'].values())
(ROOT/'scripts/evidence/LAYAG-cl-contracts.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
print(json.dumps({'passed':report['passed'],**{k:v['passed'] for k,v in report['procedures'].items()}}))
