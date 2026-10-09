"""Fresh frozen CPU floor and live-browser route checks; no training."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid


def self_check(scratch):
    from .contract_gate import wants
    identity='laya.frozen-cpu-floor'
    if not wants(identity):return {'ok':False,'contracts':[],'cases':[]}
    root=Path(scratch)/uuid.uuid4().hex;root.mkdir(parents=True)
    try:
        from .proof_ports import proof_port
        from .subprocess_utils import capture_bounded_process
        repo=Path(__file__).resolve().parents[2]
        home=os.environ.get('NEYVIA_GATE_RESOURCE_HOME')
        if not home:raise ValueError('Frozen floor needs its explicit read-only public resource home')
        command=[sys.executable,str(repo/'scripts/laya3d_regression.py'),'after','--root',str(root),
                 '--port',str(proof_port(48461)),'--resource-home',home]
        captured=capture_bounded_process(command,cwd=repo,env=dict(os.environ),input_text=None,timeout=1800)
        (root/'stdout.log').write_text(captured['stdout'],encoding='utf-8');(root/'stderr.log').write_text(captured['stderr'],encoding='utf-8')
        report=json.loads((root/'after/regression.json').read_text(encoding='utf-8'))
        spec=importlib.util.spec_from_file_location('gate_floor',repo/'scripts/laya3d_regression.py')
        owner=importlib.util.module_from_spec(spec);sys.path.insert(0,str(repo/'scripts'));spec.loader.exec_module(owner)
        gates=owner.admission(report)
        assert captured['returncode']==0 and not captured['timedOut'] and all(gates.values()), json.dumps(gates)
        # Exercise the actual runner's nonzero exit on each independently bad floor.
        for field in ('jevbench','retained','layout'):
            bad=json.loads(json.dumps(report))
            if field=='jevbench':bad['jevbench']['correct']=137
            elif field=='retained':bad['changedDecisionIds']=['changed']
            else:bad['layout']['correct']=47
            path=root/(field+'-regression.json');path.write_text(json.dumps(bad))
            failed=capture_bounded_process([sys.executable,str(repo/'scripts/laya3d_regression.py'),'after','--check-report',str(path)],
                      cwd=repo,env=dict(os.environ),input_text=None,timeout=30)
            assert failed['returncode']!=0 and not failed['timedOut']
        from .laya_host import DEFAULTS
        assert DEFAULTS['architecture']=='transformer'
        observed={'gates':gates,'freshReport':str(root/'after/regression.json'),'failedFloorExitVerified':3,
                  'defaultArchitecture':DEFAULTS['architecture'],'browserRouting':report['browserRouting'],
                  'boundary':'Fresh public 231-case CPU replay, all 93 retained decisions and 48 layouts; no training'}
        cases=[{'id':identity,'contracts':[identity],'ok':True,'observed':observed}]
    except Exception as error:
        cases=[{'id':identity,'contracts':[identity],'ok':False,'error':type(error).__name__+': '+str(error),'logs':str(root)}]
    return {'ok':cases[0]['ok'],'cases':cases,'contracts':[identity] if cases[0]['ok'] else []}
