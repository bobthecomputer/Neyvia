"""Observe the real blocking backend gate and retain its source-bound receipts on D."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--ports', default='48879-48889')
    parser.add_argument('--syncthing', type=Path)
    parser.add_argument('--obscura', type=Path)
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum(): parser.error('Invalid label')
    output = Path(r'D:\NeyviaRuns\INTN\self-check') / args.label
    output.mkdir(parents=True, exist_ok=False)
    state = ROOT / '.agent_control/INTN/sc' / hashlib.sha256(args.label.encode()).hexdigest()[:12]
    if state.exists(): parser.error('State label must be fresh')
    # Large proof snapshots go directly to D; small database/home state stays C.
    proof_output = output / 'proofs'
    proof_output.mkdir()
    (state / '.agent_control').mkdir(parents=True)
    import _winapi
    _winapi.CreateJunction(str(proof_output), str(state / '.agent_control/proofs'))
    sources = sorted((ROOT / 'src/grant_agent').rglob('*.py')) + sorted((ROOT / 'manuals/cl').glob('*.cl'))
    sources += [ROOT / 'config/fixcl_manual_cache.json', ROOT / 'scripts/intn_blocking_self_check.py', Path(__file__)]
    hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,**hidden_windows_subprocess_kwargs()).strip()
    started = time.time()
    readiness = state / '.agent_control/proofs/readiness.json'
    command = [sys.executable,str(ROOT / 'scripts/intn_blocking_self_check.py'),'--label',args.label,
               '--build-dir',str(args.build_dir.resolve()),'--local-small-state','--ports',args.ports]+(['--syncthing',str(args.syncthing)] if args.syncthing else [])+(['--obscura',str(args.obscura)] if args.obscura else [])
    with (output/'backend.log').open('wb') as stream:
        child = subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,**hidden_windows_subprocess_kwargs())
        (output/'running.json').write_text(json.dumps({'pid':child.pid,'commit':commit,'runtimeStateRoot':str(state)}))
        deadline = time.monotonic() + 5700
        status = {}
        while child.poll() is None and time.monotonic() < deadline:
            try: status = json.loads(readiness.read_text(encoding='utf-8'))
            except (OSError,ValueError): pass
            if status.get('state') in ('passed','failed','error'): break
            time.sleep(1)
        if child.poll() is None:
            stopped = subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,**hidden_windows_subprocess_kwargs())
            # taskkill fails harmlessly when the backend exited between the poll and the kill.
            if stopped.returncode and child.poll() is None: raise RuntimeError('Owned proof backend could not be stopped')
        code = child.wait(timeout=20)
    # The child may publish its final receipt and exit between polls.
    try:
        status = json.loads(readiness.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    # The unguarded controller copies only this run's disposable proof tree.
    if (state/'.agent_control/proofs').is_dir() and (state/'.agent_control/proofs').resolve() != (output/'proofs').resolve():
        shutil.copytree(state/'.agent_control/proofs',output/'proofs',ignore=shutil.ignore_patterns('__pycache__'))
    if (state/'guard.jsonl').is_file(): shutil.copyfile(state/'guard.jsonl',output/'guard.jsonl')
    changed = [name for name,digest in hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    receipt = {'schema':'neyvia.intn.blocking-startup.v1','commit':commit,'started':started,'finished':time.time(),
        'runtimeStateRoot':str(state),'largeOutputsRoot':str(output),'readiness':status,'backendExitCode':code,
        'sourceHashes':hashes,'sourceChangedDuringRun':changed,
        'runtimeBytes':sum(p.stat().st_size for p in state.rglob('*') if p.is_file()),
        'ok':status.get('state')=='passed' and status.get('complete') is True and status.get('contractsOk') is True and not changed}
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('ok','readiness','runtimeBytes','sourceChangedDuringRun')}),flush=True)
    return 0 if receipt['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
