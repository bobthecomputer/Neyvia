"""Bootstrap the worktree's real compact MCP/CL gateway with bounded output."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid
import hashlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lines', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--manual', default='workspace')
    parser.add_argument('--chapter', default='terminal')
    parser.add_argument('--private', action='store_true')
    parser.add_argument('--private-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--procedure', help='Execute the loaded typed procedure directly if CL lacks a grounded goal observer')
    args = parser.parse_args()
    if args.private and not args.private_child:
        from grant_agent.cua_desktop import AgentDesktop
        from grant_agent.cua_guard import ZeroDisturbanceGuard
        area = ROOT / '.agent_control/proofs/C8/c8h-gateway-host' / uuid.uuid4().hex
        area.mkdir(parents=True)
        executable = area / 'python.exe'
        shutil.copy2(sys.executable, executable)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        argv = [str(executable), str(Path(__file__).resolve()), *sys.argv[1:], '--private-child']
        guard = ZeroDisturbanceGuard().start()
        try:
            with AgentDesktop(profile_root=area) as desktop:
                desktop.admit_pinned_console(argv, digest)
                process = desktop.launch(argv, cwd=ROOT, env={'PYTHONHOME': str(Path(sys.base_prefix)),
                    'PATH': str(Path(sys.base_prefix)) + ';' + os.environ['PATH']})
                guard.register_pid(process.pid)
                code = process.wait(360)
        finally:
            final_guard = guard.close()
        receipt = json.loads(args.receipt.read_text()) if args.receipt.exists() else {}
        receipt['privateHostGuard'] = final_guard
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'privateGatewayExit': code, 'guardPassed': final_guard['ok']}))
        return code if final_guard['ok'] else 2
    for name in ('NEYVIA_COORDINATOR_AUTOSTART', 'NEYVIA_TOOL_AUTO_UPDATE', 'FLUXIO_WATCHDOG_AUTOSTART'):
        os.environ[name] = '0'
    os.environ['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src'), str(ROOT / 'scripts')))
    area = ROOT / '.agent_control/proofs/C8/c8h-harness' / uuid.uuid4().hex
    area.mkdir(parents=True)
    os.environ['NEYVIA_PROOF_CREDENTIAL_GUARD'] = '1'
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install_hidden_subprocess_default()
    if args.manual == 'native-runtime':
        from grant_agent.proof_ports import configure_ports
        from c8_scope import assigned_ports
        configure_ports(sorted(assigned_ports())[:6])
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(area)
    prepare_broker_fixture(area)
    from grant_agent.neyvia_mcp_stdio import CompactNeyviaMCPServer
    grants = {'neyvia.native.runtime.self-check'} if args.manual == 'native-runtime' else None
    server = CompactNeyviaMCPServer(area, permission_mode='full-access', native_mutation_tools=grants)
    request = lambda identity, name, arguments: server.handle({'jsonrpc': '2.0', 'id': identity,
        'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})
    init = server.handle({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {}})
    loaded = request(1, 'neyvia.manual.load', {'id': args.manual, 'chapter': args.chapter})
    result = (request(2, 'neyvia.manual.run', {'id': args.manual, 'chapter': args.chapter,
        'procedure': args.procedure, 'inputs': {}}) if args.procedure else
        request(2, 'neyvia.cl', {'lines': args.lines}))
    receipt = {'manualLoaded': loaded, 'result': result, 'initialized': init, 'root': str(area)}
    for key, name in {'contract':'conpty-contract.json', 'nativeContract':'native-contract.json',
            'remoteContract':'remote-contract.json'}.items():
        proof = area / name
        if proof.exists():
            receipt[key] = json.loads(proof.read_text())
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    structured = (result or {}).get('result', {}).get('structuredContent', {})
    print(json.dumps({'receipt': str(args.receipt), 'ok': structured.get('ok'),
        'text': structured.get('text', '')[:2200], 'error': result.get('error')}))
    return 0 if structured.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
