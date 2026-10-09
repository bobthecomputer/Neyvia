"""Production HTTP handler on an owned MEM port, without live-tree access."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def install_guard(root):
    protected = tuple((Path('C:/Users/user/Projects') / name).resolve() for name in ('Neyvia', 'Neyvia-next'))
    def audit(event, args):
        if event in {'open', 'sqlite3.connect'} and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if any(path == target or path.is_relative_to(target) for target in protected):
                raise PermissionError('MEM refuses live and dependency worktree access')
            if re.search(r'(?i)(?:nas_access_runbook|nas_codex2_|credential|password|(?:^|[_.-])(?:auth|oauth|secrets)(?:[_.-]|$))', path.name) and path.suffix.casefold() not in {'.py', '.pyc', '.js', '.mjs'} and not path.is_relative_to(root):
                raise PermissionError('MEM refuses saved credential file access')
        if event in {'socket.connect', 'socket.bind'} and len(args) > 1 and isinstance(args[1], tuple):
            host, port = args[1][:2]
            if host not in {'127.0.0.1', 'localhost', '::1'} or port not in range(48971, 48980):
                raise PermissionError('MEM requires an assigned loopback port')
    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=48971)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.port not in range(48971, 48980) or not root.is_relative_to(REPO / '.agent_control/mem'):
        parser.error('Use a MEM scratch root and assigned port')
    if not os.environ.get('SYNTELOS_ACCOUNT_PASSWORD'):
        parser.error('Parent supplies an ephemeral in-memory account')
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
                      FLUXIO_RUNTIME_AUTO_UPDATE='0', NEYVIA_UI_STATE_ROOT=str(root), FLUXIO_WORKSPACE_ROOT=str(root),
                      NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}', NEYVIA_CONNECTED_SERVICE_PORT=str(args.port))
    root.mkdir(parents=True, exist_ok=True)
    install_guard(root)
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    backend = FluxioWebBackend(root, REPO / '.agent_control/mem/build')
    if os.environ.get('MEM_SECOND_PASSWORD'):
        from grant_agent.web_backend import _user_record
        # Disposable synthetic identity, hashed by the real authentication owner.
        backend.admin_config['users'].append(_user_record('mem-second', password=os.environ['MEM_SECOND_PASSWORD'], source='mem-disposable-proof'))
    from grant_agent.laya_host import start, stop
    start(root)
    server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', args.port), make_handler(backend))
    print('MEM production handler ready', flush=True)
    try:
        server.serve_forever()
    finally:
        stop()
        server.server_close()


if __name__ == '__main__':
    main()
