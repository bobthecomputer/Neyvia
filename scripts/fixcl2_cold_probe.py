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
    parser.add_argument('--require-bytecode',action='store_true')
    parser.add_argument('--empty-bytecode',action='store_true',
                        help='Run fresh children with an isolated empty cache for first-install cost')
    args=parser.parse_args()
    if args.port not in range(48821,48830) or args.samples<3: parser.error('Assigned port and >=3 samples required')
    if args.require_bytecode and args.empty_bytecode: parser.error('Choose provisioned or empty bytecode')
    root=REPO/'.agent_control/proofs'/('FIXCL2-cold-'+str(time.time_ns()))
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
    from grant_agent.neyvia_agent import NeyviaToolGateway
    restricted=NeyviaToolGateway(root,allow_mutations=True,action_scope='FIXCL2-cold-denial',
        allowed_mutation_tools={'terminal.exec'},permission_mode='workspace')
    denied=restricted.call_native('terminal.exec',{'command':'Write-Output FIXCL2_DENIED'},action_id='denied-terminal')
    lines='G: notes.read(path="audit.md").body == "Cold exact bytes" and notes.read(path="audit.md").pinned == True\nrun notes.write-and-pin(path="audit.md", body="Cold exact bytes", replace_note="replace")\ndone()'
    proof={'schema':'neyvia.FIXCL2.cold.v1','port':args.port,'root':str(root),'boundary':'coldProcess includes child startup, imports, protocol admission, mutation, observers and transport; warmTransport reuses one live child with fresh action identities and observations','transcripts':[],'checks':{}}
    from grant_agent.neyvia_gateway import NeyviaToolGateway as CompactGateway
    proof['checks']['gatewayFacadeIdentity']=NeyviaToolGateway is CompactGateway
    proof['checks']['catalogProviderDeferred']=restricted._capabilities_loaded is False
    import importlib.util
    import struct
    bytecode_sources = [REPO/'src/grant_agent'/name for name in
                        ('neyvia_gateway.py', 'native_tools.py', 'neyvia_workspace_tools.py',
                         'neyvia_manuals.py', 'proof_contracts.py', 'creative_tools.py')]
    bytecode_sources.append(REPO/'scripts/fixcl_verify.py')
    def current_bytecode(path):
        compiled = Path(importlib.util.cache_from_source(str(path)))
        if not compiled.is_file(): return False
        header = compiled.read_bytes()[:16]
        if len(header) != 16 or header[:4] != importlib.util.MAGIC_NUMBER: return False
        flags, stamp, size = struct.unpack_from('<III', header, 4)
        source_stat = path.stat()
        return flags == 0 and stamp == int(source_stat.st_mtime) and size == source_stat.st_size
    proof['bytecodeBoundary'] = {
        'mode': 'empty' if args.empty_bytecode else 'provisioned',
        'childPycachePrefix': str(root/'empty-bytecode') if args.empty_bytecode else '',
        'runtimeDontWriteBytecode': sys.dont_write_bytecode,
        'provisionedSources': [str(path.relative_to(REPO)) for path in bytecode_sources
                               if current_bytecode(path)],
        'note': ('Empty-mode children use a disposable blank prefix with bytecode writes disabled.'
                 if args.empty_bytecode else
                 'Fresh Python processes share only precompiled local bytecode; none shares protocol, gateway, manual, observer, or action state.'),
    }
    if args.require_bytecode:
        proof['checks']['bytecodeProvisioned'] = len(proof['bytecodeBoundary']['provisionedSources']) == len(bytecode_sources)
    proof['checks']['workspaceTerminalDenied']=denied.get('status')=='approval_required'
    proof['checks']['workspaceTerminalUndiscoverable']=restricted._native_discovery(
        restricted.native.describe('terminal.exec'))['allowedInRun'] is False
    def source_hashes():
        paths = [*(REPO/'src/grant_agent/cl').glob('*.py'),
                 *(REPO/'manuals/cl').glob('*.cl'), *(REPO/'manuals').glob('*.manual.json')]
        paths += [REPO/'src/grant_agent'/name for name in
                  ('neyvia_manuals.py', 'native_tools.py', 'neyvia_agent.py',
                   'neyvia_gateway.py', 'neyvia_cl.py', 'neyvia_mcp_stdio.py',
                   'neyvia_impact.py', 'proof_contracts.py', 'creative_tools.py',
                   'neyvia_workspace_tools.py', 'neyvia_notes_tools.py',
                   'neyvia_files_tools.py', 'adaptive_work.py', 'ui_command_bus.py')]
        paths.append(REPO/'config/fixcl_manual_cache.json')
        paths += [REPO/'scripts/build_fixcl_manual_cache.py', REPO/'scripts/fixcl2_cold_probe.py']
        return {str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    hashes=source_hashes()
    cold=[]; warm=[]
    child=None
    def request(identity, program=lines):
        value={'jsonrpc':'2.0','id':identity,'method':'tools/call','params':{'name':'neyvia.cl','arguments':{'lines':program,'actionId':identity}}}
        child.stdin.write(json.dumps(value)+'\n'); child.stdin.flush()
        response=json.loads(child.stdout.readline())
        result=response.get('result',{})
        passed=result.get('structuredContent',{}).get('ok') is True and result.get('isError') is not True
        proof['transcripts'].append({'identity':identity,'passed':passed,'response':response})
        return passed
    try:
        for n in range(args.samples):
            started=time.perf_counter()
            child_env = dict(os.environ)
            if args.empty_bytecode:
                child_env['PYTHONPYCACHEPREFIX'] = str(root/'empty-bytecode')
                child_env['PYTHONDONTWRITEBYTECODE'] = '1'
            child=subprocess.Popen([sys.executable,str(REPO/'scripts/fixcl_verify.py'),'--stdio','--port',str(args.port),'--root',str(root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=child_env)
            proof['checks']['cold-'+str(n)]=request('cold-process-'+str(n))
            cold.append(round((time.perf_counter()-started)*1000,3))
            print(json.dumps({'cold':n,'ms':cold[-1]}),flush=True)
            if n==args.samples-1:
                for k in range(args.samples*2):
                    started=time.perf_counter()
                    proof['checks']['warm-'+str(k)]=request('warm-transport-'+str(k))
                    warm.append(round((time.perf_counter()-started)*1000,3))
                    print(json.dumps({'warm':k,'ms':warm[-1]}),flush=True)
                proof['checks']['secondLayerFilesRead']=request('second-layer-files',
                    'files.list(path='+json.dumps(str(root))+')')
                proof['checks']['retainedGoalAfterSecondLayer']=request('retained-goal','done()')
                proof['checks']['secondLayerVisible']='R files.list ok' in proof['transcripts'][-2]['response'].get('result',{}).get('structuredContent',{}).get('text','')
            child.stdin.close(); child.wait(timeout=15)
            proof['checks']['exit-'+str(n)]=child.returncode==0
            proof['transcripts'][-1]['stderr']=child.stderr.read()[-2000:]
            child=None
    finally:
        if child and child.poll() is None: child.terminate(); child.wait(timeout=10)
    proof['latency']={key:{'n':len(values),'samplesMs':values,'p50Ms':percentile(values,.5),'p95Ms':percentile(values,.95)} for key,values in [('coldProcess',cold),('warmTransport',warm)]}
    proof['checks']['sourceUnchanged']=hashes==source_hashes()
    proof['sourceHashes']=hashes
    proof['checks']['exactBytes']=(root/'notes/audit.md').read_bytes()==b'Cold exact bytes'
    from grant_agent.cl.protocol import Protocol
    inspection_gateway = NeyviaToolGateway(root, allow_mutations=False, permission_mode='read-only')
    layered = Protocol(inspection_gateway, lazy_manuals=True)
    layered.describe(name='notes.read')
    original_host = layered.host
    layered.describe(name='files.list')
    proof['checks']['incrementalHostIdentity'] = layered.host is original_host
    from grant_agent import proof_contracts
    for tool in ('neyvia.notes.read', 'neyvia.notes.write', 'neyvia.notes.pin'):
        narrowed = proof_contracts._action_rows(tool, proof_contracts._stamp())
        complete = proof_contracts.catalog()[0].get(tool, [])
        proof['checks']['validatorParity-'+tool] = [row['id'] for row in narrowed] == [row['id'] for row in complete]
    # Exercise the production loader on copied manuals. A digest mismatch must
    # run the strict compiler and reject stale or malformed source/artifacts.
    from grant_agent import neyvia_manuals as manual_loader
    import shutil
    scratch=root/'cache-adverse'
    record=next(row for row in manual_loader.records() if row['id']=='notes')
    for relative in (record['clSource'],record['path']):
        target=scratch/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(REPO/relative,target)
    original_repo=manual_loader.REPO
    try:
        manual_loader.REPO=scratch
        proof['checks']['cachedArtifactAccepted']=manual_loader.document(record)[1]['id']=='notes'
        artifact=scratch/record['path']
        artifact.write_text('{}\n',encoding='utf-8')
        try: manual_loader.document(record)
        except ValueError as exc: proof['checks']['staleArtifactRejected']='stale' in str(exc)
        else: proof['checks']['staleArtifactRejected']=False
        shutil.copyfile(REPO/record['path'],artifact)
        source=scratch/record['clSource']
        source.write_bytes(source.read_bytes().replace(b'CL 1',b'CL 2',1))
        try: manual_loader.document(record)
        except ValueError: proof['checks']['changedSourceRejected']=True
        else: proof['checks']['changedSourceRejected']=False
    finally:
        manual_loader.REPO=original_repo
    proof['checks']['sourceUnchanged']=hashes==source_hashes()
    output=REPO/'scripts/evidence'/('FIXCL2-cold-empty.json' if args.empty_bytecode else 'FIXCL2-cold.json')
    output.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'receipt':str(output),'latency':proof['latency'],'passed':all(proof['checks'].values())}))
    return 0 if all(proof['checks'].values()) else 1


if __name__=='__main__': raise SystemExit(main())
