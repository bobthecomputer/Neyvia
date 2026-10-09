"""Start the task-owned backend hidden, with all automatic services disabled."""
import json
import os
from pathlib import Path
import subprocess
import sys
import argparse

repo = Path(__file__).resolve().parents[1]
out = Path('D:/NeyviaRuns/REL')
out.mkdir(parents=True,exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--static-root', type=Path, default=out/'build-bus')
parser.add_argument('--obscura', type=Path, default=out/'obscura.exe')
args = parser.parse_args()
for path in (args.static_root, args.obscura):
    if not path.resolve().is_relative_to(out.resolve()): raise ValueError('Runtime artifacts must stay in REL evidence')
if not (args.static_root/'index.html').is_file() or not args.obscura.is_file(): raise ValueError('Existing built UI and engine required')
env = {**os.environ,'NEYVIA_TOOL_AUTO_UPDATE':'0','NEYVIA_COORDINATOR_AUTOSTART':'0',
    'FLUXIO_WATCHDOG_AUTOSTART':'0','NEYVIA_LAYA_AUTOSTART':'0',
    'NEYVIA_BROWSER_PROOF_PORTS':'48961-48969','NEYVIA_BROWSER_UI_ORIGIN':'http://127.0.0.1:48962',
    'NEYVIA_OBSCURA_EXE':str(args.obscura)}
runtime = repo/'.agent_control/rel/runtime-fast'
with (out/'backend.stdout.log').open('ab') as stdout, (out/'backend.stderr.log').open('ab') as stderr:
    entry = [str(repo/'scripts/run_web_backend.py')]
    child = subprocess.Popen([sys.executable,*entry,'--host','127.0.0.1',
        '--port','48961','--root',str(runtime),'--static-root',str(args.static_root),
        '--skip-runtime-auto-update','--skip-proof-self-check'],cwd=repo,env=env,
        stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
(repo/'.agent_control/rel/backend.pid').write_text(str(child.pid),encoding='ascii')
print(json.dumps({'pid':child.pid,'port':48961,'root':str(runtime),'automaticServices':False}))
