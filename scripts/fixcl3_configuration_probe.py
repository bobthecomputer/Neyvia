"""Real CL configuration calls and independently re-read owner drift refusals."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from fixcl_verify import REPO, guards, environment


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--output',type=Path,default=REPO/'scripts/evidence/FIXCL3-configuration.json')
    args=parser.parse_args()
    if args.port != 48824: parser.error('Configuration proof uses explicit port48824 environment; no listener')
    root=REPO/'.agent_control/proofs'/('FIXCL3-configuration-'+str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root,args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol, unwrap
    from grant_agent.cl.configuration_effects import SUPPORTED, snapshot_for, checks_for
    from grant_agent.neyvia_onboarding import load_catalog, _dir
    from grant_agent.neyvia_dictation import _policy_path
    from grant_agent.ui_command_bus import bus_for
    gateway=NeyviaToolGateway(root,allow_mutations=True,permission_mode='workspace')
    bus=bus_for(root)
    paths=[REPO/'src/grant_agent/cl/configuration_effects.py',Path(__file__),REPO/'scripts/fixcl3_configuration_manual.py']
    paths += [REPO/'manuals'/name for layer in ('onboarding','dictation','efficiency') for name in (layer+'.manual.json','cl/'+layer+'.cl')]
    hashes=lambda:{path.relative_to(REPO).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    proof={'schema':'neyvia.fixcl3-configuration.v1','root':str(root),'port':args.port,
        'checks':{},'transcripts':{},'witnesses':[],'sourceHashesAtStart':hashes(),
        'frontier':{'onboarding.runtimes':'Harness detection includes account/CLI probes; no saved account access authorized.',
            'onboarding.base_pack(start/pause),onboarding.pack(install)':'Downloaded/staged pack worker effects require distinct byte/status ownership witnesses.',
            'settings.setup,onboarding.open':'Display requires observed renderer acknowledgement; no client connected in this configuration fixture.',
            'settings.network_check':'Owner self-check uses sentinel destinations outside assigned ports; not invoked.',
            'dictation.transcribe,dictation.process(qwen)':'Actual microphone/audio and multilingual ASR need separately admitted engines.',
            'efficiency.extract(model routes)':'Script route proven; direct model routes and provider-backed cascade require actual provider evidence.'}}
    catalog=load_catalog()
    source=root/'exact.json'
    source.write_bytes(b'{"invoice":{"id":"000042","count":17}}\n')
    cases=[
        ('onboarding-save','neyvia.onboarding.save',{'interests':[catalog['interests'][0]['id']],
            'tier':'beginner','apps':[],'packs':[],'runtime':'','completed':True}),
        ('dictation-add','neyvia.dictation.names',{'action':'add','to':'FixtureName','from':['fixture name']}),
        ('dictation-process','neyvia.dictation.process',{'text':'please write fixture name with seventeen widgets','final':True}),
        ('efficiency-extract','neyvia.efficiency.extract',{'path':'exact.json','field':'/invoice/id','strategy':'cascade','useScript':True}),
    ]
    if {tool for _,tool,_ in cases}!=SUPPORTED: raise ValueError('Every admitted adapter needs one real CL witness')
    def call(case,tool,arguments):
        protocol=Protocol(gateway,lazy_manuals=True)
        code=tool.removeprefix('neyvia.')+'('+','.join(key+'='+json.dumps(value) for key,value in arguments.items())+')'
        result=protocol.run('G observed: time.now()["unixSeconds"] > 0\n'+code+'\ndone()',action_id='fixcl3-config-'+case)
        proof['transcripts'][case]=result
        print(json.dumps({'case':case,'ok':result.get('ok'),'status':result.get('status')}),flush=True)
        args.output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        return protocol,result
    for case,tool,arguments in cases:
        before_protocol=Protocol(gateway,lazy_manuals=True)
        before=snapshot_for(before_protocol,tool,arguments)
        protocol,result=call(case,tool,arguments)
        rows=[row for row in result.get('results',[]) if row.get('name')==tool or row.get('name')==tool.removeprefix('neyvia.')]
        row=rows[0] if rows else {}
        positive=bool(result.get('ok') is True and 'R done ok' in result.get('text','') and row.get('manualUse') and
            any(check.get('name','').startswith('effect-') and check.get('passed') is True for check in row.get('checks',[])))
        proof['checks'][case+'-positive-cl-effect-manual']=positive
        if positive:
            value=unwrap(protocol.action_output(tool,row['result']))
            verify=checks_for(protocol,tool,arguments)[0]['check']
            proof['checks'][case+'-independent-fresh-pass']=verify(arguments,value,before) is True
            if tool=='neyvia.onboarding.save':
                path=_dir(root)/'state.json'; data=json.loads(path.read_bytes()); data['completed']=False
                original=path.read_bytes(); path.write_text(json.dumps(data),encoding='utf-8')
            elif tool=='neyvia.dictation.names':
                path=_policy_path(root,'names'); data=json.loads(path.read_bytes()); data['FixtureName']=['wrong alias']
                original=path.read_bytes(); path.write_text(json.dumps(data),encoding='utf-8')
            elif tool=='neyvia.dictation.process':
                path=_policy_path(root,'history'); data=json.loads(path.read_bytes()); data[-1]['language']='fr'
                original=path.read_bytes(); path.write_text(json.dumps(data),encoding='utf-8')
            else:
                path=source; original=source.read_bytes(); path.write_bytes(b'{"invoice":{"id":"000043","count":17}}\n')
            proof['checks'][case+'-fresh-drift-refused']=verify(arguments,value,before) is False
            path.write_bytes(original)
            proof['witnesses'].append({'tool':tool,'case':case,'manualUse':row['manualUse'],'positiveChecks':row['checks']})
    # Exact conditional observer shapes; no install, engine or external provider.
    pure=[('recommend','neyvia.onboarding.recommend',{'tier':'beginner'}),
        ('base-pack-status','neyvia.onboarding.base_pack',{'action':'status'}),
        ('addon-status','neyvia.onboarding.pack',{'action':'status'}),
        ('dictionary-list','neyvia.dictation.names',{'action':'list'}),
        ('provisional-prompt','neyvia.dictation.process',{'text':'seventeen widgets','final':False}),
        ('cascade-metrics','neyvia.efficiency.metrics',{}),
        ('learned-transitions','neyvia.efficiency.transitions',{}),
        ('source-impact','neyvia.impact',{'paths':['src/grant_agent/cl/configuration_effects.py'],'gaps':False}),
        ('time-advisory','neyvia.time.budget',{'estimatedNextSeconds':10,'verificationReserveSeconds':5})]
    history_path=_policy_path(root,'history')
    history_before=history_path.read_bytes() if history_path.exists() else b''
    for case,tool,arguments in pure:
        protocol,result=call(case,tool,arguments)
        proof['checks'][case+'-actual-readonly-cl']=result.get('ok') is True and protocol._mutating(tool,arguments) is False
    proof['checks']['provisional-history-unchanged']=history_before==(history_path.read_bytes() if history_path.exists() else b'')
    for case,arguments in [('model-extraction',{'path':'exact.json','field':'/invoice/id','strategy':'direct-small'}),
                           ('nonfinite-source',{'path':'bad.json','field':'/x'})]:
        if case=='nonfinite-source': (root/'bad.json').write_bytes(b'{"x":NaN}')
        _,result=call(case,'neyvia.efficiency.extract',arguments)
        proof['checks'][case+'-refused-before-dispatch']=result.get('ok') is False
    _,result=call('builtin-name-removal','neyvia.dictation.names',{'action':'remove','to':'Neyvia','from':['neyvia']})
    proof['checks']['builtin-name-removal-refused']=result.get('ok') is False
    proof['sourceHashesAtEnd']=hashes()
    proof['checks']['own-source-unchanged']=proof['sourceHashesAtStart']==proof['sourceHashesAtEnd']
    proof['checks']['every-new-adapter-positive-witness']={row['tool'] for row in proof['witnesses']}==SUPPORTED
    proof['manualReceipts']=[row['payload'] for row in bus.since() if row['action']=='cl.manual.use']
    args.output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'ok':all(proof['checks'].values()),'checks':proof['checks'],'receipt':str(args.output)}),flush=True)
    raise SystemExit(0 if all(proof['checks'].values()) else 1)


if __name__=='__main__':main()
