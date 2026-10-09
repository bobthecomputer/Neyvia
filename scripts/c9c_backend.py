"""Isolated production handlers for hidden Neyvia browser rubric proof."""
import argparse
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
p = argparse.ArgumentParser()
p.add_argument("--port", required=True, type=int)
p.add_argument("--root", required=True, type=Path)
args = p.parse_args()
root = args.root.resolve()
if args.port not in range(48761, 48770) or not root.is_relative_to(REPO / "scripts/evidence/C9c-runs"):
    raise ValueError("Explicit C9c port and scoped disposable root required")
root.mkdir(parents=True, exist_ok=True)
from grant_agent.proof_credential_guard import check_access, _ROOTS
_ROOTS.add(root)
def guard(event, values):
    if event in {"open", "sqlite3.connect"} and values:
        check_access(values[0])
    if event == "socket.connect":
        host, port = values[1][:2]
        if host not in {"127.0.0.1", "localhost", "::1"} or port not in range(48761, 48770):
            raise PermissionError("C9c backend connects only to owned proof ports")
sys.addaudithook(guard)
for key in ("NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART", "NEYVIA_COORDINATOR_AUTOSTART"):
    os.environ[key] = "0"
os.environ["NEYVIA_PROOF_CREDENTIAL_GUARD"] = "1"
os.environ["NEYVIA_UI_BACKEND_URL"] = f"http://127.0.0.1:{args.port}"
from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
from grant_agent.connected_sessions.broker import ConnectedBroker, _BROKERS
from grant_agent.neyvia_ui_api import bind_backend
static = root / "empty-web"
static.mkdir(exist_ok=True)
backend = FluxioWebBackend(root, static)
broker = ConnectedBroker(root, backend=backend, autostart=False)
_BROKERS[os.path.normcase(str(root))] = broker
bind_backend(backend)
server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", args.port), make_handler(backend))
print(f"C9c production handlers on explicit port {args.port}", flush=True)
try:
    server.serve_forever()
finally:
    broker.close()
    server.server_close()
