"""Run the product's blocking startup proof gate in an owned hidden scope."""
import argparse
import hashlib
from pathlib import Path
import json
import os
import runpy
import sys

REPO = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--label', required=True)
parser.add_argument('--build-dir', type=Path, required=True)
parser.add_argument('--local-small-state', action='store_true')
parser.add_argument('--ports', default='48879-48889', help='Explicit assigned range: backend, six fixture ports, then socketpair wakeup ports')
parser.add_argument('--syncthing', type=Path, help='Explicitly prepared, hash-pinned Syncthing v2.1.5 executable for native sync contracts')
parser.add_argument('--obscura', type=Path, help='Explicitly prepared headless Obscura executable for the rendered browser journey')
args = parser.parse_args()
if args.obscura:
    if not args.obscura.is_file(): parser.error('Prepared Obscura executable not found')
    os.environ['NEYVIA_OBSCURA_EXE'] = str(args.obscura.resolve())
if args.syncthing:
    if not args.syncthing.is_file(): parser.error('Prepared Syncthing executable not found')
    os.environ['NEYVIA_PROOF_SYNCTHING_EXE'] = str(args.syncthing.resolve())
first, _, last = args.ports.partition('-')
PORTS = list(range(int(first), int(last or first) + 1))
if len(PORTS) < 9 or 47881 in PORTS: parser.error('At least nine explicit assigned ports are required, never 47881')
if not args.label.replace('-', '').isalnum(): parser.error('Invalid label')
if not (args.build_dir / 'index.html').is_file(): parser.error('Built index.html is required')
STATE = REPO / '.agent_control/INTN/sc' / hashlib.sha256(args.label.encode()).hexdigest()[:12] if args.local_small_state else Path(r'D:\NeyviaRuns\INTN\self-check') / args.label
STATE.mkdir(parents=True, exist_ok=True)
os.environ['INT3_EXTRA_WRITE_ROOTS'] = json.dumps([str((Path(r'D:\NeyviaRuns\INTN\self-check') / args.label / 'proofs').resolve())]) if args.local_small_state else '[]'
sys.pycache_prefix = str(STATE / 'bytecode')
os.environ['PYTHONPYCACHEPREFIX'] = sys.pycache_prefix
os.environ['NEYVIA_PROVISIONING_ROOT'] = str(STATE / 'provisioning')
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))
for key in list(os.environ):
    if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'AUTH_FILE')):
        os.environ.pop(key)
for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'HERMES_HOME', 'TEMP', 'TMP'):
    folder = STATE / 'home' / key.lower()
    folder.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(folder)
os.environ.update(NEYVIA_MOBILE_PROBE_DEVICES='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
    NEYVIA_PROOF_CREDENTIAL_GUARD='1', PYTHONDONTWRITEBYTECODE='1', INT3_WORKSPACE_ROOT=str(STATE), INT3_LINE_COVERAGE='0',
    INT3_NO_BROWSER_LAUNCH='1', INT3_ALLOWED_PORTS=json.dumps(PORTS),
    INT3_MAP_EPHEMERAL_BIND='1', GIT_CEILING_DIRECTORIES=str(STATE), NEYVIA_PROOF_COMPACT_ROOT='1',
    INT3_GUARD_LOG=str(STATE / 'guard.jsonl'), NEYVIA_PROOF_SOCKETPAIR_PORTS=','.join(map(str, PORTS[7:])),
    TIKTOKEN_CACHE_DIR=r'D:\NeyviaRuns\INTN\python\tokenizer-rerun\tokenizer-cache')
from grant_agent.proof_ports import configure_ports
configure_ports(PORTS[1:7])
import int3_pytest_guard
from grant_agent.subprocess_utils import install_hidden_subprocess_default
install_hidden_subprocess_default()
sys.argv = [str(REPO / 'scripts/run_web_backend.py'), '--host', '127.0.0.1', '--port', str(PORTS[0]), '--root', str(STATE),
    '--static-root', str(args.build_dir.resolve()), '--skip-runtime-auto-update', '--proof-self-check-blocking']
runpy.run_path(sys.argv[0], run_name='__main__')
