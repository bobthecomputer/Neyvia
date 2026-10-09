"""Independently bind Claude's mounted-pane journey to the current FIXCL2 backend."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]


def hashes(paths):
    return {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-port', type=int, required=True)
    parser.add_argument('--ui-port', type=int, required=True)
    parser.add_argument('--pane-port', type=int, required=True)
    parser.add_argument('--fixture-port', type=int, required=True)
    parser.add_argument('--ipc-port', type=int, action='append', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--obscura', type=Path, required=True)
    args = parser.parse_args()
    ports = [args.backend_port, args.ui_port, args.pane_port, args.fixture_port]
    owned_ports = [*ports, *args.ipc_port]
    if len(set(owned_ports)) != len(owned_ports) or any(port not in range(48821, 48830) for port in owned_ports):
        parser.error('Distinct assigned ports required, including Windows asyncio IPC')
    forbidden = [Path(r'C:\Users\user\Projects\Neyvia'), Path(r'C:\Users\user\Projects\Neyvia-next')]
    for supplied in (args.dist, args.obscura):
        if any(supplied.resolve().is_relative_to(path) for path in forbidden):
            parser.error('Protected tree is outside this task')
    if not args.dist.is_dir() or not args.obscura.is_file():
        parser.error('Existing built UI and installed Neyvia browser required')
    for port in owned_ports:
        with socket.socket() as candidate:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            candidate.bind(('127.0.0.1', port))
    sources = [*(REPO / 'src/grant_agent/cl').glob('*.py'),
               *(REPO / 'manuals/cl').glob('*.cl'), *(REPO / 'manuals').glob('*.manual.json')]
    sources += [REPO / 'src/grant_agent' / name for name in
                ('neyvia_cl.py', 'neyvia_ui_api.py', 'neyvia_gateway.py', 'neyvia_panes.py',
                 'neyvia_workspace_tools.py', 'ui_command_bus.py', 'native_tools.py',
                 'neyvia_manuals.py', 'proof_contracts.py')]
    sources += [*sorted((REPO / 'web/src/neyvia/next').glob('Nx*Pane*.jsx')),
                REPO / 'web/src/neyvia/next/nxPaneObserve.js',
                REPO / 'web/src/neyvia/next/nxBus.js',
                REPO / 'web/src/neyvia/next/nxOsStore.js',
                REPO / 'web/src/neyvia/next/NxStage.jsx',
                REPO / 'web/proof/FIXCL-renderer/renderer_probe.py', Path(__file__)]
    start = hashes(sources)
    built = {path.relative_to(args.dist).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in args.dist.rglob('*') if path.is_file()}
    output = REPO / 'scripts/evidence/FIXCL2-renderer.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    attempted = REPO / '.agent_control/proofs' / ('FIXCL2-renderer-run-' + str(time.time_ns()) + '.json')
    attempted.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.proof_credential_guard import install
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(attempted.parent)
    install_hidden_subprocess_default()
    import playwright
    driver = Path(playwright.__file__).parent / 'driver/node.exe'
    admitted_executables = {args.obscura.resolve(), driver.resolve()}
    ipc_ports = iter(args.ipc_port)
    # Windows implements socketpair through a temporary TCP listener. Preserve
    # that mechanism while assigning its listener instead of binding port zero.
    def assigned_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        if family not in (socket.AF_INET, socket.AF_INET6) or type != socket.SOCK_STREAM or proto != 0:
            raise ValueError('Unsupported asyncio IPC socket shape')
        address = '127.0.0.1' if family == socket.AF_INET else '::1'
        client = server = None
        with socket.socket(family, type, proto) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((address, next(ipc_ports)))
            listener.listen(1)
            try:
                client = socket.socket(family, type, proto)
                client.setblocking(False)
                try:
                    client.connect(listener.getsockname())
                except (BlockingIOError, InterruptedError):
                    pass
                client.setblocking(True)
                server, _ = listener.accept()
                if server.getsockname() != client.getpeername() or client.getsockname() != server.getpeername():
                    raise ConnectionError('Unexpected asyncio IPC peer')
                return server, client
            except BaseException:
                if server is not None: server.close()
                if client is not None: client.close()
                raise
    if sys.platform == 'win32':
        socket.socketpair = assigned_socketpair
    def audit(event, values):
        if event in {'socket.bind', 'socket.connect'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in owned_ports):
                raise PermissionError('Renderer proof uses only its assigned loopback ports')
        if event == 'subprocess.Popen':
            command = values[1]
            if isinstance(command, (list, tuple)):
                admitted = Path(command[0]).resolve() in admitted_executables
            else:
                admitted = any(command.startswith(subprocess.list2cmdline([str(executable)]) + ' ')
                               or command == subprocess.list2cmdline([str(executable)])
                               for executable in admitted_executables)
            if not admitted:
                raise PermissionError('Renderer proof refuses an unowned process')
    sys.addaudithook(audit)
    spec = importlib.util.spec_from_file_location('fixcl_owned_renderer', sources[-2])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PORT, module.UI_ENGINE, module.PANE_ENGINE, module.FIXTURE = ports
    # The existing production journey receives assigned ports through its globals.
    # Its mounted panes, event store, HTTP calls and ACK mechanism are unchanged.
    sys.argv = [str(sources[-2]), '--dist', str(args.dist), '--obscura', str(args.obscura),
                '--out', str(attempted)]
    failure = None
    try:
        module.main()
    except Exception as exc:
        failure = exc
    if not attempted.exists():
        if failure: raise failure
        raise RuntimeError('Renderer journey did not produce a receipt')
    proof = json.loads(attempted.read_bytes())
    proof['sourceHashesAtStart'] = start
    proof['assignedPorts'] = owned_ports
    proof['sourceHashesAtEnd'] = hashes(sources)
    proof['checks']['sourceUnchanged'] = start == proof['sourceHashesAtEnd']
    proof['builtArtifactHashes'] = built
    proof['checks']['builtArtifactUnchanged'] = built == {
        path.relative_to(args.dist).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in args.dist.rglob('*') if path.is_file()}
    proof['buildBoundary'] = 'Independent execution of Claude-supplied built artifact against current source-bound backend; no new frontend build claimed.'
    proof['ok'] = failure is None and len(proof['checks']) >= 35 and all(value is True for value in proof['checks'].values())
    proof['passed'] = proof['ok']
    if failure: proof['runError'] = type(failure).__name__ + ': ' + str(failure)
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'ok': proof['ok'], 'checks': len(proof['checks'])}))
    if failure: raise failure
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
