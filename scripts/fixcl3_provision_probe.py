"""Fresh source/cache startup and real bounded local-peer sidebar provisioning."""
from __future__ import annotations
import argparse
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
SOURCES = ('scripts/run_web_backend.py', 'scripts/build_fixcl_manual_cache.py',
           'scripts/fixcl2_acquire_sidebar_model.py', 'scripts/fixcl3_provision_probe.py',
           'src/grant_agent/local_provisioning.py', 'src/grant_agent/sidebar_model_assets.py',
           'src/grant_agent/neyvia_sidebar_semantics.py', 'src/grant_agent/neyvia_mcp_stdio.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(checkout, root, output):
    # The harness owns the surrounding original-repository proof root. Load
    # its credential guard independently so cloning source does not redefine
    # the fixture boundary as the cloned repository's sibling runtime folder.
    spec = importlib.util.spec_from_file_location('provision_guard', REPO / 'src/grant_agent/proof_credential_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    guard.install(root)
    sys.path.insert(0, str(checkout / 'src'))
    from grant_agent.local_network_policy import install as privacy_install
    privacy_install(root)
    from grant_agent.ui_command_bus import bus_for
    bus = bus_for(root)
    from grant_agent.sidebar_model_assets import ensure_model, model_path, validate, expected_receipt
    from grant_agent.neyvia_sidebar_semantics import encode, source_identity
    checks = {'default_target_initially_missing': not model_path().exists()}
    base = os.environ.pop('NEYVIA_SIDEBAR_ASSET_BASE_URL')
    bus.put('settings', {'localOnly': True})
    refused = False
    try:
        ensure_model()
    except PermissionError:
        refused = True
    checks['local_only_refuses_official_download_before_target_creation'] = refused and not model_path().exists()
    bus.put('settings', {'localOnly': False})
    os.environ['NEYVIA_SIDEBAR_ASSET_BASE_URL'] = base
    vectors, model = encode(None, ['Lunar basalt geology', 'Moon rock mineral geology'])
    acquired = source_identity()
    checks['lazy_encode_acquires_default_model'] = model_path().is_dir() and len(vectors) == 2
    checks['real_cpu_vectors_from_exact_pins'] = all(len(row) == 384 for row in vectors) and model['device'] == 'cpu' and acquired[1] == expected_receipt()
    requests_before = (root / 'peer-requests.json').read_text(encoding='utf-8')
    encode(None, ['Lunar basalt geology'])
    checks['warm_model_no_transfer'] = (root / 'peer-requests.json').read_text(encoding='utf-8') == requests_before
    (root / 'corrupt-peer').write_text('config.json', encoding='utf-8')
    bad_target = root / 'corrupt-model'
    refused = False
    try:
        ensure_model(bad_target)
    except ValueError:
        refused = True
    checks['actual_corrupt_peer_transfer_refused_before_admission'] = refused and not (bad_target / 'config.json').exists() and not (bad_target / 'receipt.json').exists() and not list(bad_target.glob('*.part'))
    (root / 'corrupt-peer').unlink()
    config = model_path() / 'config.json'
    original = config.read_bytes()
    config.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    refused = False
    try:
        encode(None, ['Lunar basalt geology'])
    except ValueError:
        refused = True
    checks['same_size_drift_refused_without_silent_repair'] = refused and config.read_bytes() != original
    config.write_bytes(original)
    receipt_file = model_path() / 'receipt.json'
    original_receipt = receipt_file.read_bytes()
    forged = json.loads(original_receipt)
    forged['revision'] = '0' * 40
    receipt_file.write_text(json.dumps(forged), encoding='utf-8')
    refused = False
    try:
        source_identity()
    except ValueError:
        refused = True
    checks['forged_revision_refused'] = refused
    receipt_file.write_bytes(original_receipt)
    checks['restored_model_exact'] = validate(model_path()) == expected_receipt()
    result = {'checks': checks, 'model': acquired[1], 'modelIdentity': model,
              'vectors': {'count': len(vectors), 'dimensions': len(vectors[0])}}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if all(checks.values()) else 1


def run(port, output):
    if port not in range(48821, 48830):
        raise ValueError('Explicit assigned FIXCL3 port required')
    root = REPO / '.agent_control/proofs' / ('FIXCL3-provision-' + str(time.time_ns()))
    root.mkdir(parents=True)
    checkout = root / 'fresh-source'
    checkout.mkdir()
    for directory in ('src', 'config', 'manuals'):
        shutil.copytree(REPO / directory, checkout / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (checkout / 'scripts').mkdir()
    for name in ('run_web_backend.py', 'fixcl_verify.py'):
        shutil.copyfile(REPO / 'scripts' / name, checkout / 'scripts' / name)
    source_before = {name: sha(REPO / name) for name in SOURCES}
    checks = {'fresh_source_has_no_pyc': not list(checkout.rglob('*.pyc')),
              'fresh_source_has_no_model': not (checkout / '.agent_control/t7/embedding-model').exists()}
    env = dict(os.environ, NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_RUNTIME_AUTO_UPDATE='0',
               NEYVIA_COORDINATOR_AUTOSTART='0', FLUXIO_WATCHDOG_AUTOSTART='0',
               NEYVIA_PROOF_CREDENTIAL_GUARD='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               PYTHONDONTWRITEBYTECODE='1',
               FLUXIO_WORKSPACE_ROOT=str(root), NEYVIA_REMOTE_PROOF_PORTS=str(port),
               NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{port}',
               HF_HOME=str(root / 'hf'), HF_HUB_CACHE=str(root / 'hf/hub'),
               HF_TOKEN_PATH=str(root / 'hf/token'), XDG_CACHE_HOME=str(root / 'cache'),
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_PROGRESS_BARS='1')
    for name in ('NEYVIA_SIDEBAR_EMBEDDING_MODEL', 'PYTHONPYCACHEPREFIX', 'NEYVIA_UI_STATE_ROOT'):
        env.pop(name, None)
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    backend_root = checkout / '.agent_control/proofs/runtime'
    backend_root.mkdir(parents=True)
    env['FLUXIO_WORKSPACE_ROOT'] = str(backend_root)
    command = [sys.executable, str(checkout / 'scripts/run_web_backend.py'), '--host', '127.0.0.1',
               '--port', str(port), '--root', str(backend_root), '--skip-runtime-auto-update', '--skip-proof-self-check']
    started = time.monotonic()
    with (root / 'backend.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=checkout, env=env, stdout=log, stderr=log, **kwargs)
        health = None
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(.1)
        finally:
            process.terminate()
            process.wait(timeout=15)
    backend_ms = round((time.monotonic() - started) * 1000)
    provision_path = checkout / '.agent_control/provisioning/bytecode.json'
    provisioning = json.loads(provision_path.read_text(encoding='utf-8')) if provision_path.exists() else {}
    checks['normal_backend_health_from_fresh_source'] = bool(health and health.get('ok'))
    checks['backend_automatically_provisioned_all_bytecode'] = provisioning.get('ok') is True and provisioning.get('sources') == provisioning.get('cached')
    checks['explicit_provisioning_with_implicit_import_writes_disabled'] = provisioning.get('implicitImportWritesDisabled') is True and provisioning.get('ok') is True
    # This peer is a retained local fixture of exact previously acquired public
    # pinned bytes. It does not establish public Internet/CDN availability.
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.sidebar_model_assets import FILES, validate
    peer_source = REPO / '.agent_control/t7/embedding-model'
    validate(peer_source)
    requests = []
    request_file = root / 'peer-requests.json'
    request_file.write_text('[]', encoding='utf-8')

    class Peer(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            name = self.path.removeprefix('/pinned/')
            if not self.path.startswith('/pinned/') or name not in FILES:
                self.send_error(404)
                return
            corrupt = (root / 'corrupt-peer').exists() and name == 'config.json'
            requests.append({'file': name, 'bytes': FILES[name][0], 'corrupt': corrupt})
            request_file.write_text(json.dumps(requests), encoding='utf-8')
            self.send_response(200)
            self.send_header('Content-Length', str(FILES[name][0]))
            self.end_headers()
            with (peer_source / name).open('rb') as source:
                if corrupt:
                    raw = source.read()
                    self.wfile.write(raw[:-1] + bytes([raw[-1] ^ 1]))
                else:
                    shutil.copyfileobj(source, self.wfile, 1024 * 1024)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Peer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    worker_result = root / 'model-result.json'
    env['NEYVIA_SIDEBAR_ASSET_BASE_URL'] = f'http://127.0.0.1:{port}/pinned'
    try:
        child = subprocess.run([sys.executable, str(Path(__file__)), '--worker', str(checkout),
                                '--root', str(root), '--output', str(worker_result)],
                               cwd=checkout, env=env, capture_output=True, text=True, timeout=120, **kwargs)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    (root / 'worker.log').write_text(child.stdout + child.stderr, encoding='utf-8')
    model = json.loads(worker_result.read_text(encoding='utf-8')) if worker_result.exists() else {}
    checks.update(model.get('checks', {}))
    checks['model_worker_completed'] = child.returncode == 0
    checks['actual_local_peer_transfer_bounded'] = len(requests) == 7 and sum(row['bytes'] for row in requests) == 91567817
    after = {name: sha(REPO / name) for name in SOURCES}
    checks['sources_unchanged_during_proof'] = source_before == after
    result = {'schema': 'neyvia.FIXCL3.provision.v1', 'root': str(root), 'port': port,
              'sourceHashesAtStart': source_before, 'sourceHashesAtEnd': after,
              'backend': {'command': command, 'health': health, 'firstStartupMs': backend_ms,
                          'bytecode': provisioning},
              'model': model, 'localPeerTransfers': requests, 'checks': checks,
              'boundary': ['Fresh source copy on this system Python; dependencies already installed',
                           'Backend existing --skip-proof-self-check scopes proof to cache provisioning/health; full startup matrix separate',
                           'Actual HTTP model transfer from local peer, exact production immutable pins',
                           'Public Internet/CDN reachability and other-machine dependency availability unproven']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'checks': checks}))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    sys.exit(worker(args.worker, args.root, args.output) if args.worker else run(args.port, args.output))
