"""Serve the production HTTP handler on one explicitly owned INT2 scratch root."""
from pathlib import Path
import argparse
import os
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.port not in range(48601, 48610) or not root.is_relative_to(REPO / '.agent_control/int2'):
        parser.error('INT2 ports and scratch roots required')
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0',
                      FLUXIO_WATCHDOG_AUTOSTART='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
                      NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}',
                      SYNTELOS_ACCOUNT_USERNAME='int2-proof', SYNTELOS_ACCOUNT_PASSWORD='disposable-int2-fixture')
    from int2_pytest_guard import install
    install()
    from grant_agent.local_network_policy import install as install_network_policy
    install_network_policy(root)
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    from grant_agent.neyvia_ui_api import bind_backend
    backend = FluxioWebBackend(root, REPO / '.agent_control/int2/build-final')
    bind_backend(backend)
    server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', args.port), make_handler(backend))
    print(f'INT2 production handler ready on {args.port}', flush=True)
    # The proof intentionally starts no warm-up providers, updater or scheduler.
    try:
        server.serve_forever()
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
