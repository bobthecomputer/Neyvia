"""Cold process and warm transport timings for a real spawned CL procedure."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from fixcl_verify import REPO, environment, guards, percentile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--samples',type=int,default=5)
    args=parser.parse_args()
    if args.port not in range(48821,48830) or args.samples<3: parser.error('Assigned port and >=3 samples required')
    root=REPO/'.agent_control/proofs'/('FIXCL-cold-'+str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root,args.port)
    import os
    os.environ.pop('NEYVIA_UI_BACKEND_URL',None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.native_tools import NativeToolRegistry
    prepare_broker_fixture(root)
    registry=NativeToolRegistry(root)
    registry.call('neyvia.notes.folder',{'folder':str(root/'notes')})
    registry.call('neyvia.notes.write',{'path':'audit.md','body':'original'})
    lines='G: notes.read(path="audit.md").body == "Cold exact bytes" and notes.read(path="audit.md").pinned == True\nrun notes.write-and-pin(path="audit.md", body="Cold exact bytes", replace_note="replace")\ndone()'
    proof={'schema':'neyvia.FIXCL.cold.v1','port':args.port,'root':str(root),'boundary':'coldProcess includes child startup, imports, protocol admission, mutation, observers and transport; warmTransport reuses one live child with fresh action identities and observations','transcripts':[],'checks':{}}
    hashes={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (REPO/'src/grant_agent/cl').glob('*.py')}
    cold=[]; warm=[]
    child=None
    def request(identity):
        value={'jsonrpc':'2.0','id':identity,'method':'tools/call','params':{'name':'neyvia.cl','arguments':{'lines':lines,'actionId':identity}}}
        child.stdin.write(json.dumps(value)+'\n'); child.stdin.flush()
        response=json.loads(child.stdout.readline())
        result=response.get('result',{})
        passed=result.get('structuredContent',{}).get('ok') is True and result.get('isError') is not True
        proof['transcripts'].append({'identity':identity,'passed':passed,'response':response})
        return passed
    try:
        for n in range(args.samples):
            started=time.perf_counter()
            child=subprocess.Popen([sys.executable,str(REPO/'scripts/fixcl_verify.py'),'--stdio','--port',str(args.port),'--root',str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
            proof['checks']['cold-'+str(n)]=request('cold-process-'+str(n))
            cold.append(round((time.perf_counter()-started)*1000,3))
            print(json.dumps({'cold':n,'ms':cold[-1]}),flush=True)
            if n==args.samples-1:
                for k in range(args.samples*2):
                    started=time.perf_counter()
                    proof['checks']['warm-'+str(k)]=request('warm-transport-'+str(k))
                    warm.append(round((time.perf_counter()-started)*1000,3))
                    print(json.dumps({'warm':k,'ms':warm[-1]}),flush=True)
            child.stdin.close(); child.wait(timeout=15)
            proof['checks']['exit-'+str(n)]=child.returncode==0
            proof['transcripts'][-1]['stderr']=child.stderr.read()[-2000:]
            child=None
    finally:
        if child and child.poll() is None: child.terminate(); child.wait(timeout=10)
    proof['latency']={key:{'n':len(values),'samplesMs':values,'p50Ms':percentile(values,.5),'p95Ms':percentile(values,.95)} for key,values in [('coldProcess',cold),('warmTransport',warm)]}
    proof['checks']['sourceUnchanged']=hashes=={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (REPO/'src/grant_agent/cl').glob('*.py')}
    proof['sourceHashes']=hashes
    proof['checks']['exactBytes']=(root/'notes/audit.md').read_bytes()==b'Cold exact bytes'
    output=REPO/'scripts/evidence/FIXCL-cold-process.json'
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'receipt':str(output),'latency':proof['latency'],'passed':all(proof['checks'].values())}))
    return 0 if all(proof['checks'].values()) else 1


if __name__=='__main__': raise SystemExit(main())
