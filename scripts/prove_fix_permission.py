"""Exercise the actual stdio CLI permission modes with disposable local files."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    root = REPO / '.agent_control/proofs' / ('fix-permission-' + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONPATH=str(REPO / 'src'), PYTHONUTF8='1',
        NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0',
        FLUXIO_WATCHDOG_AUTOSTART='0', NEYVIA_UI_BACKEND_URL='http://127.0.0.1:48661')
    rows = []
    for mode in ('read-only', 'workspace', 'full-access'):
        folder = root / mode
        folder.mkdir(exist_ok=True)
        (folder / 'config').mkdir(exist_ok=True)
        # Public empty fixture configuration prevents fallback to saved brokers.
        (folder / 'config/neyvia_secret_broker.json').write_text('{"stack":{},"policy":{}}\n', encoding='utf-8')
        target = 'permission.txt'
        text = 'FIX permission ' + mode
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'neyvia.access.context', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'neyvia.native.call', 'arguments': {
                'toolId': 'workspace.write', 'arguments': {'path': target, 'content': text}, 'actionId': 'FIX-permission-' + mode}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'neyvia.terminal.exec', 'arguments': {
                'command': "print('FIX_COMMAND_OK')", 'shell': 'python', 'actionId': 'FIX-command-' + mode}}},
        ]
        invocation = ['-m', 'grant_agent.neyvia_mcp_stdio', '--root', str(folder), '--permission-mode', mode]
        # The guard is installed before the production entry point imports its owners.
        bootstrap = "import runpy,sys; from grant_agent.proof_credential_guard import install; install(sys.argv[3]); sys.argv=sys.argv[1:]; runpy.run_module('grant_agent.neyvia_mcp_stdio',run_name='__main__')"
        run = subprocess.run([sys.executable, '-c', bootstrap, 'neyvia-mcp', '--root', str(folder), '--permission-mode', mode],
            cwd=REPO, env=environment, input='\n'.join(map(json.dumps, requests)) + '\n',
            capture_output=True, text=True, encoding='utf-8', timeout=120)
        replies = [json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
        artifact = folder / target
        written = artifact.exists() and artifact.read_text(encoding='utf-8') == text
        command_ok = 'FIX_COMMAND_OK' in json.dumps(replies[-1].get('result', {})) and not replies[-1].get('result', {}).get('isError') if replies else False
        good = run.returncode == 0 and len(replies) == 4 and written == (mode != 'read-only') and command_ok == (mode == 'full-access')
        rows.append({'mode': mode, 'invocation': invocation, 'exitCode': run.returncode,
            'writtenBytesMatch': written, 'commandSucceeded': command_ok, 'passed': good,
            'responses': replies, 'stderr': run.stderr[-2000:]})
    source = REPO / 'src/grant_agent/neyvia_mcp_stdio.py'
    receipt = {'schema': 'neyvia.FIX.permission.v1', 'passed': all(row['passed'] for row in rows),
        'rows': rows, 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'boundary': 'Actual production stdio CLI with no explicit mutation list; disposable files and real Python child command; no public service'}
    destination = REPO / 'scripts/evidence/FIX-permission.json'
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': receipt['passed'], 'rows': [{k: row[k] for k in ('mode', 'writtenBytesMatch', 'commandSucceeded', 'passed')} for row in rows]}))
    return int(not receipt['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
