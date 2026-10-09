"""Owned proof backend with protected-read and socket boundaries installed first."""
import faulthandler
import os
from pathlib import Path
import socket
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
root = (REPO / "scripts/evidence/C9b-runs/runtime").resolve()
root.mkdir(parents=True, exist_ok=True)

# All saved private data remains outside this backend's authority. Its newly
# generated local owner account is admitted only in its selected empty state.
from grant_agent.proof_credential_guard import check_access, _ROOTS
_ROOTS.add(root)
def guard(event, args):
    if event in {"open", "sqlite3.connect"} and args:
        check_access(args[0])
    if event == "socket.connect":
        host, port = args[1][:2]
        if host not in {"127.0.0.1", "::1", "localhost"} or not 48761 <= port <= 48769:
            raise PermissionError("C9b backend may connect only to owned proof ports")
sys.addaudithook(guard)
for key in ("NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "NEYVIA_COORDINATOR_AUTOSTART"):
    os.environ[key] = "0"
os.environ["NEYVIA_PROOF_CREDENTIAL_GUARD"] = "1"
os.environ["NEYVIA_UI_BACKEND_URL"] = "http://127.0.0.1:48761"
print("C9b guarded backend import", flush=True)
from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
from grant_agent.connected_sessions.broker import ConnectedBroker, _BROKERS
from grant_agent.neyvia_ui_api import bind_backend
print("C9b backend ready to bind", flush=True)
static = root / "empty-web"
static.mkdir(exist_ok=True)
backend = FluxioWebBackend(root, static)
broker = ConnectedBroker(root, backend=backend, autostart=False)
_BROKERS[os.path.normcase(str(root))] = broker
bind_backend(backend)
server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", 48761), make_handler(backend))
print("C9b production handlers on explicit port 48761; startup suite/CLI warmup disabled", flush=True)
try:
    server.serve_forever()
finally:
    broker.close()
    server.server_close()
