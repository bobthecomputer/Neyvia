"""Actual MCP discovery/calls and the desktop's persistent stdio worker protocol."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from run_c11_cohort import write_receipt


def journey(call):
    identity = None
    records = []
    try:
        opened = call('open', {'app': 'Command Prompt'})
        records.append(opened)
        identity = opened['sessionId']
        marker = 'Public surface note ' + identity
        records.append(call('edit', {'sessionId': identity, 'value': marker}))
        records.append(call('persist', {'sessionId': identity}))
        checked = call('observe', {'sessionId': identity, 'expected': marker, 'persisted': True})
        records.append(checked)
        if not checked.get('ok'):
            raise RuntimeError('Public native surface saved-state check failed')
    finally:
        if identity:
            records.append(call('close', {'sessionId': identity}))
    return {'ok': records[-1]['ok'], 'calls': records}


def run():
    scratch = ROOT / '.agent_control/proofs/c11g-native-surfaces' / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    for name in ('NEYVIA_COORDINATOR_AUTOSTART', 'NEYVIA_TOOL_AUTO_UPDATE', 'FLUXIO_WATCHDOG_AUTOSTART'):
        os.environ[name] = '0'
    from grant_agent.proof_credential_guard import install
    install(scratch)
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    from grant_agent.cua_native_procedures import SCHEMAS, hosted_native_applications
    from grant_agent.neyvia_manuals import unwrap
    guard = ZeroDisturbanceGuard().start()
    result = {'schema': 'neyvia.c11g.native-public-surfaces.v1', 'ok': False,
        'sourceSha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            'src/grant_agent/neyvia_mcp.py', 'src/grant_agent/native_tool_worker.py', 'src/grant_agent/native_tools.py',
            'src/grant_agent/cua_native_procedures.py', 'src-tauri/src/lib.rs', 'scripts/prove_c11g_native_surfaces.py')},
        'boundary': 'Actual MCP tool calls and real persistent desktop worker; native Tauri window/IPC itself is source-wired but not launched'}
    worker = None
    try:
        from grant_agent.neyvia_mcp import NeyviaMCPServer
        mcp_root = scratch / 'mcp'
        # The broad MCP catalog constructs its secret-broker metadata service.
        # Supply an empty workspace-local configuration so catalog discovery
        # cannot fall back to any saved account configuration. No broker call
        # participates in the native application journey.
        from grant_agent.proof_credential_guard import prepare_broker_fixture
        prepare_broker_fixture(mcp_root)
        result['secretBrokerConfiguration'] = 'Empty disposable workspace metadata; no saved credentials read'
        host = NeyviaMCPServer(mcp_root)
        catalog = host.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        expected = {'neyvia.nativeapp.' + name for name in SCHEMAS}
        names = {tool['name'] for tool in catalog['result']['tools']}
        if not expected <= names:
            raise RuntimeError('MCP catalog lacks native app operations')
        result['mcpDiscovered'] = sorted(expected)
        def mcp_call(operation, args):
            response = host.handle({'jsonrpc': '2.0', 'id': operation, 'method': 'tools/call',
                'params': {'name': 'neyvia.nativeapp.' + operation, 'arguments': args}})
            if response.get('error') or response['result'].get('isError'):
                raise RuntimeError('Actual MCP call failed: ' + str(response.get('error', response['result']))[:250])
            return response['result'].get('structuredContent') or json.loads(response['result']['content'][0]['text'])
        result['mcp'] = journey(mcp_call)
        hosted_native_applications(mcp_root).shutdown()
        worker_root = scratch / 'worker'
        worker_root.mkdir()
        code = "import sys;sys.path.insert(0,sys.argv[1]);from grant_agent.proof_credential_guard import install;install(sys.argv[2]);from grant_agent.native_tool_worker import main;raise SystemExit(main(['--root',sys.argv[2]]))"
        worker = subprocess.Popen([sys.executable, '-B', '-c', code, str(ROOT / 'src'), str(worker_root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW)
        guard.register_pid(worker.pid)
        lines = queue.Queue()
        def read():
            for line in worker.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        index = 0
        def worker_call(operation, args):
            nonlocal index
            index += 1
            worker.stdin.write(json.dumps({'id': index, 'tool': 'neyvia.nativeapp.' + operation, 'arguments': args}) + '\n')
            worker.stdin.flush()
            line = lines.get(timeout=60)
            if line is None:
                raise RuntimeError('Native worker ended before response')
            response = json.loads(line)
            if response.get('id') != index or not response.get('ok') or not response['data'].get('ok'):
                raise RuntimeError('Persistent native worker refused request')
            result.setdefault('workerRawCalls', []).append(response)
            return unwrap(response['data'])
        result['worker'] = journey(worker_call)
        worker.stdin.write(json.dumps({'id': 'close', 'command': 'shutdown'}) + '\n')
        worker.stdin.flush()
        if not json.loads(lines.get(timeout=30)).get('ok'):
            raise RuntimeError('Worker shutdown refused')
        worker.wait(timeout=30)
        result['workerExitCode'] = worker.returncode
        result['ok'] = result['mcp']['ok'] and result['worker']['ok'] and worker.returncode == 0
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:350]
        result['sourceFrames'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-8:]]
    finally:
        if worker and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=5)
        hosted_native_applications(scratch / 'mcp').shutdown()
        result['guard'] = guard.close()
        result['ok'] = result['ok'] and result['guard']['ok']
        write_receipt(ROOT / 'scripts/evidence/C11g-apps-native-surfaces.json', result)
    print(json.dumps({'ok': result['ok'], 'error': result.get('error')}))
    return result['ok']


if __name__ == '__main__':
    raise SystemExit(0 if run() else 2)
