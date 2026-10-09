"""Real quiet Recycle Bin conservation through CL and spawned MCP."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from fixcl_verify import REPO, environment, guards, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830): parser.error('Assigned ports only')
    root = REPO / '.agent_control/proofs' / ('FIXCL-recycle-' + str(time.time_ns()))
    root.mkdir(parents=True)
    guards(root); environment(root, args.port)
    import os
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    prepare_broker_fixture(root)
    body = b'Own disposable Recycle Bin conservation\n'
    path = root / 'own-disposable.txt'
    path.write_bytes(body)
    lines = 'G: files.stat(path=' + json.dumps(str(path)) + ',preview=True)["preview"] == ' + json.dumps(body.decode()) + '\nfiles.trash(path=' + json.dumps(str(path)) + ')\nfiles.undo()\ndone()'
    proof = {'schema':'neyvia.FIXCL.recycle.v1', 'root':str(root), 'port':args.port,
             'sourceHashesAtStart':source_hashes(), 'transcripts':{}, 'checks':{},
             'boundary':'Only the named disposable file; Windows owner quiet Recycle Bin API and direct byte restoration; no UI claim or permanent deletion'}
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL-recycle', permission_mode='workspace')
    host = Protocol(gateway)
    value = host.run(lines, action_id='native-recycle')
    proof['transcripts']['native'] = value
    proof['checks']['nativeConservesBytes'] = value['ok'] and path.read_bytes() == body
    path.write_bytes(b'External changed bytes')
    changed = host.run('G: time.now()["unixSeconds"] > 0\ndone()', action_id='adverse-recycle')
    proof['transcripts']['adverse'] = changed
    proof['checks']['weakGoalCannotHideChangedRestoration'] = not changed['ok']
    path.write_bytes(body)
    child = subprocess.Popen([sys.executable, str(REPO/'scripts/fixcl_verify.py'), '--stdio', '--layers', '--port', str(args.port), '--root', str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    responses = queue.Queue()
    def read_lines():
        for line in child.stdout: responses.put(line)
    reader = threading.Thread(target=read_lines, daemon=True); reader.start()
    try:
        request = {'jsonrpc':'2.0', 'id':'recycle-MCP', 'method':'tools/call', 'params':{'name':'neyvia.cl', 'arguments':{'lines':lines}}}
        child.stdin.write(json.dumps(request)+'\n'); child.stdin.flush()
        response = json.loads(responses.get(timeout=90))
        proof['spawnedMCP'] = response
        value = response.get('result', {})
        proof['checks']['MCPConservesBytes'] = response.get('id') == 'recycle-MCP' and value.get('structuredContent', {}).get('ok') is True and value.get('isError') is not True and path.read_bytes() == body
        child.stdin.close(); child.wait(timeout=15)
        proof['checks']['MCPExited'] = child.returncode == 0
        proof['stderr'] = child.stderr.read()[-3000:]
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=10)
    proof['sourceHashesAtEnd'] = source_hashes()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    output = REPO / 'scripts/evidence/FIXCL-recycle.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps({'receipt':str(output), 'checks':proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


if __name__ == '__main__': raise SystemExit(main())
