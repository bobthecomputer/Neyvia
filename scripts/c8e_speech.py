"""Run the installed speech engine on CPU with a task-local write/network fence."""
import argparse
import os
from pathlib import Path
import runpy
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--port', required=True, type=int)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
root = Path(args.root).resolve()
root.relative_to(repo / '.agent_control/proofs/C8')
from c8_scope import assigned_ports
if args.port not in assigned_ports():
    raise ValueError('Explicit C8 port required')
root.mkdir(parents=True, exist_ok=True)
temporary = root / 'temp'
temporary.mkdir(exist_ok=True)
os.environ.update(TEMP=str(temporary), TMP=str(temporary), PHONON2_DENSE_CACHE='0',
                  HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', OMP_NUM_THREADS='2',
                  HF_HOME=str(root / 'hf'), TORCH_HOME=str(root / 'torch'))
sys.path.insert(0, str(repo / 'src'))
from grant_agent.proof_credential_guard import install
install(root)
from c8_scope import install as scope
scope(allow_children=False, writable_root=root)
engine = Path('C:/Users/user/Projects/dictation-phonon2')
sys.path.insert(0, str(engine))
sys.argv = [str(engine / 'phonon2_engine.py'), '--port', str(args.port), '--device', 'cpu',
            '--model-dir', str(engine / 'models/phonon-2'), '--idle-exit-minutes', '0']
runpy.run_path(str(engine / 'phonon2_engine.py'), run_name='__main__')
