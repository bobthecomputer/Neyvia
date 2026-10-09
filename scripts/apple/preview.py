"""Owned headless rendered journey. Temporary auth in memory; no credential reads."""
import argparse, os, secrets, subprocess, sys, time, urllib.request
import socket
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
from grant_agent.laya_host import _KillOnClose
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', required=True)
parser.add_argument('--backend-port', type=int, default=49111)
parser.add_argument('--vite-port', type=int, default=49119)
parser.add_argument('--root',type=Path,help='Owned runtime and receipt root')
args=parser.parse_args()
if 'NEYVIA_PROOF_PORT_MAP' in os.environ:
    from grant_agent.proof_ports import proof_port
    args.backend_port,args.vite_port=proof_port(48461),proof_port(48462)
elif any(not 49111 <= port <= 49119 for port in (args.backend_port,args.vite_port)):
    parser.error('Ports must be within the caller-assigned block')
repo=Path(__file__).resolve().parents[2]
root=(args.root or repo/'.agent_control/apple/preview').resolve();root.mkdir(parents=True,exist_ok=True)
with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1',args.backend_port)) == 0:
        raise RuntimeError('Assigned backend port is occupied; preserve its owner')
env={**os.environ,'SYNTELOS_ACCOUNT_PASSWORD':secrets.token_urlsafe(32),
     'NEYVIA_MOBILE_PROBE_DEVICES':'0',
     'NEYVIA_TOOL_AUTO_UPDATE':'0','FLUXIO_WATCHDOG_AUTOSTART':'0','NEYVIA_COORDINATOR_AUTOSTART':'0',
     'NEYVIA_LAYA_AUTOSTART':'0',
     'FLUXIO_RUNTIME_AUTO_UPDATE':'0','APPLE_PREVIEW_PROJECT':str(Path(args.project).resolve()),
     'FLUXIO_LOCAL_SESSION_BOOTSTRAP':'1','APPLE_PREVIEW_ROOT':str(root),
     'APPLE_PREVIEW_ENGINE_PORT':str(args.vite_port),
     'APPLE_PREVIEW_ORIGIN':f'http://127.0.0.1:{args.backend_port}',
     'NEYVIA_BROWSER_UI_ORIGIN':f'http://127.0.0.1:{args.backend_port}'}
logpath=root/'backend.log'
with logpath.open('w',encoding='utf-8') as log:
    children=_KillOnClose()
    process=subprocess.Popen([sys.executable,'scripts/run_web_backend.py','--host','127.0.0.1','--port',str(args.backend_port),
                              '--root',str(root/'runtime'),'--skip-runtime-auto-update','--skip-proof-self-check'],cwd=repo,env=env,stdout=log,stderr=log,
                              **hidden_windows_subprocess_kwargs())
    if os.name=='nt' and not children.add(process):
        process.terminate();process.wait()
        raise RuntimeError('Owned Apple backend could not acquire its kill-on-close job')
    try:
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Owned backend failed; inspect task-local log')
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{args.backend_port}/api/health',timeout=2).close();break
            except OSError:time.sleep(.25)
        else:raise RuntimeError('Owned backend did not start within 60 seconds')
        renderer=subprocess.Popen(['node','scripts/apple/preview.mjs'],cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',**hidden_windows_subprocess_kwargs())
        if os.name=='nt' and not children.add(renderer):
            renderer.terminate();renderer.wait()
            raise RuntimeError('Owned Apple renderer could not acquire its kill-on-close job')
        stdout,stderr=renderer.communicate()
        print(stdout);print(stderr,file=sys.stderr)
        if renderer.returncode:raise SystemExit(renderer.returncode)
    finally:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait()
