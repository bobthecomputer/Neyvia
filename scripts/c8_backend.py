"""Start unmodified selected Neyvia source with an explicit empty harness scope.

Notes/Settings journeys do not grant access to the operator's CLI accounts.
ConnectedBroker's existing adapter-injection seam expresses that boundary;
unsupported harnesses report unavailable rather than connecting to a profile.
"""
import argparse
import atexit
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True)
parser.add_argument("--root", required=True)
parser.add_argument("--port", required=True, type=int)
parser.add_argument("--static-root", required=True)
args = parser.parse_args()
from c8_scope import install as install_socket_scope, assigned_ports, run_root
repo = Path(__file__).resolve().parents[1]
source, root = Path(args.source).resolve(), Path(args.root).resolve()
if source != repo and not source.is_relative_to(repo / ".agent_control") and not source.is_relative_to(run_root(repo)):
    raise ValueError("Only candidate or task-local pinned source is permitted")
if not root.is_relative_to(run_root(repo)) or args.port not in assigned_ports():
    raise ValueError("C8 requires disposable task state and an assigned explicit port")
root.mkdir(parents=True, exist_ok=True)
sidebar_fixture = source == repo and (root / 'c8/sidebar-fixture.json').is_file()
if sidebar_fixture:
    packages = Path('C:/Users/user/Projects/dictation-workbench-recovery-20260825/.venv/Lib/site-packages')
    if not (packages / 'torch').is_dir() or not (packages / 'transformers').is_dir():
        raise RuntimeError('Inspected installed CPU embedding packages are unavailable')
    sys.path.insert(0, str(packages))
    os.environ.update(NEYVIA_SIDEBAR_EMBEDDING_MODEL=str(repo / '.agent_control/proofs/C8/c8e-embedding'),
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HOME=str(root / 'c8/hf'), TORCH_HOME=str(root / 'c8/torch'))
os.environ.update(PYTHONPATH=os.pathsep.join((str(source / 'src'), str(repo / 'scripts'))),
                  NEYVIA_C8_SOURCE=str(source))
if source == repo and (root / "c8/browser-capacity-fixture.json").is_file():
    os.environ["PYTHONPATH"] = str(root / "c8/harness-fence") + os.pathsep + os.environ["PYTHONPATH"]
os.environ.update(NEYVIA_PEER_ALLOW_LOOPBACK='1',
                  NEYVIA_PEER_DEFAULT_SHARE=str(root / 'c8'),
                  NEYVIA_PEER_DEFAULT_INBOX=str(root / 'c8/inbox'))
(root / 'c8/inbox').mkdir(parents=True, exist_ok=True)
if (root / 'c8/creator-sdk-manifest.json').is_file():
    import json
    os.environ['NEYVIA_ONBOARDING_PACK_MANIFESTS'] = json.dumps({'pack.creator-sdk': str(root / 'c8/creator-sdk-manifest.json')})
if (root / 'c8/base-ui-manifest.json').is_file():
    os.environ['NEYVIA_BASE_PACK_MANIFEST'] = str(root / 'c8/base-ui-manifest.json')
if (root / 'c8/obscura.exe').is_file():
    from c8_scope import assigned_ports
    os.environ.update(NEYVIA_OBSCURA_EXE=str(root / 'c8/obscura.exe'),
                      NEYVIA_BROWSER_PROOF_PORTS=','.join(map(str, sorted(assigned_ports()))))
temporary = root / 'temp'
temporary.mkdir(exist_ok=True)
os.environ.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
from c8_headless import install as install_headless
install_headless(root, args.port)
install_socket_scope(allow_children=False, writable_root=root,
                     headless_driver_source=source / 'src/grant_agent/perception_browser.py')
sys.path.insert(0, str(source / "src"))
from grant_agent.proof_credential_guard import install, prepare_broker_fixture
install(root)
# Existing root-local configuration seam: an empty disposable vault catalog
# prevents conversation creation from consulting any operator account config.
prepare_broker_fixture(root)
from grant_agent.local_network_policy import install as install_network
install_network(root)
from c8_headless import install_capture_runtime
install_capture_runtime(root)
if source == repo and os.environ.get('NEYVIA_C8E_TERMINAL_TRANSPORT') == '1':
    terminal_port = int(os.environ['NEYVIA_C8_TERMINAL_PORT'])
    from c8e_terminal import install as install_terminal_transport
    install_terminal_transport(terminal_port, root)
    from grant_agent import neyvia_onboarding as onboarding
    import subprocess
    def scoped_pack_worker(pack_root, pack_id=None):
        if Path(pack_root).resolve() != root or pack_id not in (None, 'pack.creator-sdk'):
            raise PermissionError('Only the installed local C8e pack is admitted')
        with (root / 'c8/pack-worker.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(repo / 'scripts/c8e_onboarding.py'), '--root', str(root),
                              '--pack-id', pack_id or 'base'], cwd=root, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    onboarding._spawn_worker = scoped_pack_worker
from grant_agent.connected_sessions import broker as brokers
broker = brokers.ConnectedBroker(root, adapters={}, load_defaults=False, autostart=False)
brokers._BROKERS[os.path.normcase(str(root))] = broker
atexit.register(broker.close)
from grant_agent.web_backend import main, FluxioWebBackend
if sidebar_fixture or (root / 'c8/ui-fixture.json').is_file():
    original_backend_init = FluxioWebBackend.__init__
    def sidebar_backend_init(self, *values, **options):
        original_backend_init(self, *values, **options)
        from c8e_sidebar import install_backend
        install_backend(broker, self)
    FluxioWebBackend.__init__ = sidebar_backend_init
raise SystemExit(main(["--host", "127.0.0.1", "--port", str(args.port), "--root", str(root),
                      "--static-root", args.static_root, "--skip-runtime-auto-update", "--skip-proof-self-check"]))
