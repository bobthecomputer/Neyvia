"""Actual offline empty-lock uv environment and fresh task-file CL witnesses."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import sys
import time
from fixcl_verify import REPO, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Assigned explicit port required')
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('Existing local uv is required; no installation performed')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-environment-' + str(time.time_ns()))
    root.mkdir(parents=True)
    environment(root, args.port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    os.environ.update(UV_OFFLINE='1', UV_PYTHON_DOWNLOADS='never', UV_NO_CONFIG='1', UV_NO_PROGRESS='1',
                      UV_CACHE_DIR=str(root / '.agent_control/environment_download_cache'))
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(root); install_hidden_subprocess_default(); prepare_broker_fixture(root)
    def guard(event, values):
        if event in {'socket.connect', 'socket.bind'}:
            raise PermissionError('Offline environment proof forbids network and listeners')
        if event == 'subprocess.Popen':
            command = values[1]
            first = command[0] if isinstance(command, (list, tuple)) else shlex.split(command, posix=False)[0].strip('"')
            executable = Path(os.fsdecode(values[0] or first)).resolve()
            if executable not in {Path(sys.executable).resolve(), Path(uv).resolve()} and not executable.is_relative_to(root):
                raise PermissionError('Only installed Python/uv and the task-owned interpreter may execute')
    sys.addaudithook(guard)
    from grant_agent.neyvia_gateway import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.shared_environments import SharedEnvironmentStore
    proof = {'schema': 'neyvia.FIXCL3.environment.v1', 'root': str(root), 'port': args.port,
        'boundary': 'Actual offline empty dependency lock, isolated interpreter and saved Python task with independently observed NEW output bytes. No dependency installation, model quality or OS sandbox claim.',
        'uv': uv, 'offline': True, 'checks': {}, 'transcripts': {}, 'witnesses': []}
    paths = [REPO / p for p in ('src/grant_agent/cl/environment_effects.py', 'src/grant_agent/shared_environments.py',
        'src/grant_agent/creative_tools.py', 'manuals/local-environment.manual.json', 'manuals/cl/local-environment.cl',
        'scripts/fixcl3_environment_probe.py')]
    hashes = lambda: {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof['sourceHashesAtStart'] = hashes()
    (root / 'requirements.lock').write_bytes(b'')
    content = b'fresh isolated environment task bytes\n'
    output_digest = hashlib.sha256(content).hexdigest()
    script = root / 'task.py'
    script.write_text('from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_bytes(' + repr(content) + ')\nprint("declared task output written")\n', encoding='utf-8')
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    def run(label, tool, payload):
        protocol = Protocol(gateway)
        inputs = ','.join(k + '=' + json.dumps(v) for k,v in payload.items())
        identity = 'FIXCL3-environment-' + label
        result = protocol.run('G local: time.now()["unixSeconds"] > 0\nrun local-environment.verify-' + tool.replace('.', '-') + '(' + inputs + ')\ndone()', action_id=identity)
        proof['transcripts'][label] = result
        print(json.dumps({'label': label, 'ok': result.get('ok'), 'status': result.get('status')}), flush=True)
        return protocol, result, identity
    create_args = {'environmentId': 'offline-fixture', 'lockPath': 'requirements.lock', 'timeout': 30}
    protocol, created, identity = run('create', 'environment.create', create_args)
    proof['checks']['createCLDone'] = created.get('ok') is True
    manifests = list((root / '.agent_control/environments/offline-fixture').glob('*/manifest.json'))
    proof['checks']['actualManifestExists'] = len(manifests) == 1
    if manifests:
        manifest_path = manifests[0]
        manifest = SharedEnvironmentStore(root)._load(manifest_path)
        proof['checks']['createFreshCompletion'] = protocol.run('done()', action_id=identity).get('ok') is True
        clean = (manifest_path.parent / 'requirements.lock').read_bytes()
        (manifest_path.parent / 'requirements.lock').write_bytes(b'changed pinned lock')
        proof['checks']['changedPinnedLockRefusesDone'] = protocol.run('done()', action_id=identity).get('ok') is False
        (manifest_path.parent / 'requirements.lock').write_bytes(clean)
        proof['witnesses'].append({'tool': 'environment.create', 'actionIdentity': identity, 'positiveCL': created,
                                  'freshDriftRefused': proof['checks']['changedPinnedLockRefusesDone']})
        outputs = [{'path': 'fresh-output.bin', 'sha256': output_digest}]
        run_args = {'manifestPath': str(manifest_path), 'args': [str(script), str(root / 'fresh-output.bin')], 'timeout': 20, 'outputs': outputs}
        protocol, executed, identity = run('run', 'environment.run', run_args)
        proof['checks']['runCLDone'] = executed.get('ok') is True
        proof['checks']['exactFreshTaskBytes'] = (root / 'fresh-output.bin').is_file() and (root / 'fresh-output.bin').read_bytes() == content
        proof['checks']['runFreshCompletion'] = protocol.run('done()', action_id=identity).get('ok') is True
        clean = (root / 'fresh-output.bin').read_bytes()
        (root / 'fresh-output.bin').write_bytes(b'changed task output')
        proof['checks']['changedTaskBytesRefuseDone'] = protocol.run('done()', action_id=identity).get('ok') is False
        (root / 'fresh-output.bin').write_bytes(clean)
        clean = script.read_bytes(); script.write_bytes(b'changed executed script')
        proof['checks']['changedScriptRefusesDone'] = protocol.run('done()', action_id=identity).get('ok') is False
        script.write_bytes(clean)
        proof['witnesses'].append({'tool': 'environment.run', 'actionIdentity': identity, 'positiveCL': executed,
            'freshDriftRefused': proof['checks']['changedTaskBytesRefuseDone'], 'scriptDriftRefused': proof['checks']['changedScriptRefusesDone']})
        failure = root / 'fail.py'; failure.write_text('import sys\nprint("retained failure")\nsys.exit(7)\n', encoding='utf-8')
        failure_args = {'manifestPath': str(manifest_path), 'args': [str(failure)], 'timeout': 20,
                        'outputs': [{'path': 'failure-must-not-exist.bin', 'sha256': output_digest}]}
        _, failed, _ = run('nonzero', 'environment.run', failure_args)
        receipts = [json.loads(p.read_bytes()) for p in manifest_path.parent.glob('run-*.json')]
        proof['checks']['nonzeroExecutionRetainedAndRefused'] = failed.get('ok') is False and any(row.get('exitCode') == 7 and row.get('status') == 'failed' and row.get('arguments') == [str(failure)] for row in receipts)
        proof['checks']['failedExecutionNoDeclaredOutput'] = not (root / 'failure-must-not-exist.bin').exists()
        unsupported = {'manifestPath': str(manifest_path), 'args': ['-c', 'print("unsupported inline execution")'], 'timeout': 20,
                       'outputs': [{'path': 'inline-output.bin', 'sha256': output_digest}]}
        prior_receipts = set(manifest_path.parent.glob('run-*.json'))
        _, refused, _ = run('inline-refused', 'environment.run', unsupported)
        proof['checks']['inlineExecutionRefusedBeforeDispatch'] = refused.get('ok') is False and set(manifest_path.parent.glob('run-*.json')) == prior_receipts
        correct = next((row for row in receipts if row.get('exitCode') == 0), {})
        proof['checks']['actualArgvSourceAndInterpreterBound'] = correct.get('arguments') == run_args['args'] and correct.get('script', {}).get('sha256') == hashlib.sha256(script.read_bytes()).hexdigest() and correct.get('interpreterSha256') == hashlib.sha256(Path(manifest['python']).read_bytes()).hexdigest()
    uses = [event['payload'] for event in bus_for(root).since(0) if event['action'] == 'cl.manual.use']
    proof['manualUses'] = [row for row in uses if row.get('manual') == 'local-environment' and row.get('status') == 'admitted' and row.get('effectChecks')]
    for tool, label in (('environment.create', 'create'), ('environment.run', 'run')):
        proof['checks'][tool + '-manualReceipt'] = any(row.get('tool') == tool and row.get('actionIdentity', '').startswith('FIXCL3-environment-' + label + ':') for row in proof['manualUses'])
    proof['sourceHashesAtEnd'] = hashes()
    proof['checks']['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['ok'] = len(proof['witnesses']) == 2 and all(proof['checks'].values())
    destination = REPO / 'scripts/evidence/FIXCL3-environment.json'
    destination.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': proof['ok'], 'receipt': str(destination), 'failed': [k for k,v in proof['checks'].items() if not v]}))
    return 0 if proof['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
