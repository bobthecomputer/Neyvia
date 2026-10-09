"""Run the complete authored C8 catalog in isolated, parallel headless batches."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import wave

from run_c8_inception import REPO, ENV, HIDDEN, pin_source, launch, stop, write, port, git
from c8_desktop_guard import DesktopGuard
from c8_journey import Candidate
from c8d_worker import expand
from c8_scope import assigned_ports


def fixture_files(binding, root, url):
    args = argparse.Namespace(state_root=str(root), candidate_url=url, binding=binding)
    if binding.get("c8eEffect", {}).get("renderedWitness") == "c8e-browser":
        from c8e_browser_checks import prepare_fixture
        prepare_fixture(root)
    if binding.get('actualSlimReceipt'):
        source = Path(binding['actualSlimReceipt']).resolve()
        source.relative_to(REPO / '.agent_control/proofs/C8')
        producer = json.loads(source.read_text(encoding='utf-8'))
        if (producer.get('schema') != 'neyvia.c8e.slim-build/v1' or producer.get('passed') is not True
                or producer.get('desktopGuard', {}).get('passed') is not True
                or producer.get('desktopGuard', {}).get('coverage') != 'Started before any producer child; PID and creation-time attribution'):
            raise ValueError('A successful fully guarded actual slim producer is required')
        actual = Path(producer['releaseReceiptPath']).resolve()
        task = Path(producer['task']).resolve()
        task.relative_to(REPO / '.agent_control/proofs/C8')
        source.relative_to(task)
        actual.relative_to(task)
        if Path(producer['receiptPath']).resolve() != source:
            raise ValueError('Actual slim producer receipt identity differs')
        if json.loads(actual.read_text(encoding='utf-8')) != producer['releaseReceipt']:
            raise ValueError('Actual slim producer and retained release receipt differ')
        target = root / 'c8/actual-slim-release.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual, target)
        write(root / 'c8/slim-producer.json', producer)
    if binding.get('c8eSidebar'):
        (root / 'c8').mkdir(parents=True, exist_ok=True)
        write(root / 'c8/sidebar-fixture.json', {'model': '.agent_control/proofs/C8/c8e-embedding',
            'runtime': 'Installed Python 3.13 Torch/Transformers packages; CPU only; authored user transcripts'})
    if binding.get('c8eUiEffect') or binding.get('c8eStateEffect') or binding.get('c8eTranscript'):
        write(root / 'c8/ui-fixture.json', {'adapter': 'Real task-owned Neyvia transcripts; no provider accounts'})
    if binding.get('c8eUiEffect'):
        base_path = REPO / 'config/base_pack/test-manifest.json'
        base_manifest = json.loads(base_path.read_text(encoding='utf-8'))
        for row in base_manifest['files']:
            source = (base_path.parent / row['url']).resolve()
            source.relative_to(REPO)
            row['url'] = source.as_uri()
        write(root / 'c8/base-ui-manifest.json', base_manifest)
    if binding.get('id') == 'onboarding/overview/stage-chosen-pack' or binding.get('c8eUiEffect'):
        # The bundled developer pack points at editable source. Pin the current
        # real bytes in an explicitly task-local manifest instead of trusting
        # stale packaging sizes or manufacturing an installed receipt.
        manifest = json.loads((REPO / 'config/onboarding_packs/pack.creator-sdk/manifest.json').read_text())
        for row in manifest['files']:
            source = (REPO / row['path']).resolve()
            source.relative_to(REPO)
            payload = source.read_bytes()
            row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest(), url=source.as_uri())
        manifest.update(version='0.0.0-c8e', totalSize=sum(r['size'] for r in manifest['files']), baseUrl=REPO.as_uri() + '/')
        (root / 'c8').mkdir(parents=True, exist_ok=True)
        write(root / 'c8/creator-sdk-manifest.json', manifest)
    if binding.get('speechFixture'):
        source = REPO / '.agent_control/proofs/C8/c8e-speech/known-speech.wav'
        (root / 'c8').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, root / 'c8/known-speech.wav')
    if binding.get('videoFixture'):
        source = REPO / '.agent_control/proofs/C8/c8e-video/known-video.mp4'
        receipt = json.loads(source.with_name('receipt.json').read_text(encoding='utf-8'))
        if source.stat().st_size != receipt['size'] or hashlib.sha256(source.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('Actual generated video fixture differs from its probe receipt')
        (root / 'c8').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, root / 'c8/known-video.mp4')
        shutil.copyfile(source.with_name('receipt.json'), root / 'c8/video-fixture-receipt.json')
    if binding.get('installedObscura'):
        source = Path(binding['installedObscura']).resolve()
        known = Path('C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f/obscura-v0.2.4/extracted/obscura.exe').resolve()
        if source != known or not source.is_file():
            raise ValueError('Only the explicitly observed installed Obscura runtime is admitted')
        (root / 'c8').mkdir(parents=True, exist_ok=True)
        for name in ('obscura.exe', 'obscura-worker.exe'):
            shutil.copyfile(source.parent / name, root / 'c8' / name)
    for entry in binding.get('files', []):
        path = Path(expand(entry['path'], args))
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        path.relative_to(root.resolve())
        path.parent.mkdir(parents=True, exist_ok=True)
        kind = entry.get('kind')
        if kind == 'png':
            from PIL import Image
            Image.new('RGB', (entry.get('width', 64), entry.get('height', 48)), '#285946').save(path)
        elif kind == 'wav':
            with wave.open(str(path), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(b'\0\0' * 1600)
        elif kind == 'pdf':
            phrase = entry.get('text', 'C8d evidence document').replace('(', '[').replace(')', ']')
            stream = ('BT /F1 12 Tf 50 700 Td (' + phrase + ') Tj ET').encode('ascii')
            objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                       b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
                       b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
                       b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
            payload = b'%PDF-1.4\n'; offsets = [0]
            for index, content in enumerate(objects, 1):
                offsets.append(len(payload)); payload += str(index).encode() + b' 0 obj\n' + content + b'\nendobj\n'
            xref = len(payload)
            payload += b'xref\n0 6\n0000000000 65535 f \n' + b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
            payload += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
            path.write_bytes(payload)
        else:
            path.write_bytes(expand(entry.get('content', ''), args).encode('utf-8'))
    for name in binding.get('sourceCopies', []):
        source = (REPO / name).resolve(); source.relative_to(REPO)
        target = (root / name).resolve(); target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for name in binding.get('gitProjects', []):
        target = (root / name).resolve(); target.relative_to(root)
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', '-c', 'core.hooksPath=NUL', 'init', str(target)],
                       cwd=root, env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull},
                       capture_output=True, check=True, **HIDDEN)
    if binding.get('priorReport'):
        source = (REPO / binding['priorReport']).resolve()
        source.relative_to(REPO / 'scripts/evidence')
        retained = json.loads(source.read_text(encoding='utf-8'))
        if 'rows' in retained:
            retained = {'results': [row['result'] for row in retained['rows']
                                    if isinstance(row.get('result'), dict) and 'startedAt' in row['result']],
                        'provenance': retained['provenance']}
        if not isinstance(retained.get('results'), list) or not isinstance(retained.get('provenance'), dict):
            raise ValueError('A real prior raw Inception receipt is required')
        target = root / '.neyvia/inception/latest.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        write(target, retained)


def execute(binding, stable, build, chosen, run_id, scratch, evidence):
    name = binding['id'].replace('/', '__').replace('@', '_')
    output = evidence / name; output.mkdir(parents=True)
    # Keep disposable Windows/Git payload paths below legacy MAX_PATH while
    # retaining the full authored identity in the evidence directory/receipt.
    root = scratch / ('j-' + hashlib.sha256(binding['id'].encode()).hexdigest()[:12])
    root.mkdir(parents=True)
    process = handle = None
    started = time.time()
    deadline = binding.get('deadlineSeconds', 180)
    if type(deadline) is not int or not 60 <= deadline <= 600:
        raise ValueError('Journey deadline must be an explicit bounded 60-600 seconds')
    result = {'id': binding['id'], 'sourceHash': binding['sourceHash'], 'status': 'failed',
              'failureClassification': 'environment', 'startedAt': started, 'journey': binding['journey'],
              'executionMode': 'headless'}
    try:
        url = f'http://127.0.0.1:{chosen}'
        fixture_files(binding, root, url)
        process, handle, url = launch(REPO, root, build, chosen, output / 'backend.log')
        client = Candidate(url)
        with (output / 'worker.log').open('wb') as log:
            worker = subprocess.Popen([sys.executable, '-B', str(REPO / 'scripts/c8d_worker.py'),
                    '--stable-source', str(stable), '--candidate-url', url, '--run-id', run_id,
                    '--journey', binding['journey'], '--output', str(output), '--state-root', str(root)],
                    cwd=REPO, env={**os.environ, **ENV}, stdin=subprocess.PIPE, stdout=log, stderr=log, **HIDDEN)
            try:
                worker.communicate(json.dumps({'binding': binding, 'cookies': client.cookies()}).encode(), timeout=deadline)
            except subprocess.TimeoutExpired:
                stop(worker)
                raise TimeoutError(f'Headless journey exceeded {deadline} seconds; owned worker stopped')
        result_path = output / 'result.json'
        if not result_path.is_file():
            raise RuntimeError('Worker exited without receipt; inspect ' + str(output / 'worker.log'))
        result = json.loads(result_path.read_text(encoding='utf-8'))
        result.update(exitCode=worker.returncode, workerReceipt=str(result_path), target=url)
    except Exception as error:
        result.update(error=str(error), finishedAt=time.time(), exitCode=1, target=f'http://127.0.0.1:{chosen}')
    finally:
        if process:
            stop(process)
        if handle:
            handle.close()
        write(output / 'result.json', result)
    print(json.dumps({key: result.get(key) for key in ('id', 'status', 'failureClassification')})[:-1] +
          ', "error": ' + json.dumps(str(result.get('error', ''))[:350]) + '}', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stable-ref', required=True)
    parser.add_argument('--stable-port', type=port, required=True)
    parser.add_argument('--ports', type=port, nargs='+', required=True)
    parser.add_argument('--build-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--bindings-file', help='Reviewed task-local authored bindings; validation remains mandatory')
    parser.add_argument('--only', nargs='*', help='Exact journey IDs for causal repair replays')
    parser.add_argument('--c8e', action='store_true', help='Apply authored prerequisite and defining-effect bindings')
    parser.add_argument('--peer-port', type=port, help='Explicit owned local peer for C8e transfers')
    parser.add_argument('--speech-port', type=port, help='Explicit previously launched task-owned CPU speech engine')
    parser.add_argument('--slim-receipt', help='Actual fully guarded C8e slim build producer receipt')
    args = parser.parse_args()
    if args.stable_port in args.ports or len(set(args.ports)) != len(args.ports):
        raise ValueError('Separate explicit ports are required')
    reserved = {int(p) for p in os.environ.get('NEYVIA_C8_RESERVED_PORTS', '').split(',') if p}
    reserved.update({args.stable_port, *args.ports})
    if args.peer_port is not None:
        reserved.add(args.peer_port)
    if args.speech_port is not None:
        reserved.add(args.speech_port)
    os.environ['NEYVIA_C8_RESERVED_PORTS'] = ','.join(map(str, sorted(reserved)))
    ENV['NEYVIA_C8_RESERVED_PORTS'] = os.environ['NEYVIA_C8_RESERVED_PORTS']
    build = Path(args.build_dir).resolve(); build.relative_to(REPO / '.agent_control')
    if not (build / 'index.html').is_file():
        raise ValueError('Candidate build is required')
    output = Path(args.output).resolve(); output.relative_to(REPO / 'scripts/evidence')
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.neyvia_inception import inventory, validate_bindings, aggregate, source_files
    catalog = inventory()
    bindings_path = Path(args.bindings_file).resolve() if args.bindings_file else REPO / 'config/inception_journeys.json'
    if args.bindings_file:
        bindings_path.relative_to(REPO / '.agent_control')
    bindings = json.loads(bindings_path.read_text(encoding='utf-8'))
    if args.c8e:
        ENV['NEYVIA_C8E_TERMINAL_TRANSPORT'] = '1'
        from c8_scope import fixture_port
        terminal_port = fixture_port()
        ENV['NEYVIA_C8_TERMINAL_PORT'] = str(terminal_port)
        reserved.add(terminal_port)
        os.environ['NEYVIA_C8_RESERVED_PORTS'] = ','.join(map(str, sorted(reserved)))
        ENV['NEYVIA_C8_RESERVED_PORTS'] = os.environ['NEYVIA_C8_RESERVED_PORTS']
        from c8e_prerequisites import apply as prerequisites
        from c8e_effects import apply as effects
        bindings = effects(prerequisites(bindings))
        from c8e_sidebar import apply as sidebar
        bindings = sidebar(bindings)
        from c8e_extra_effects import apply as extra_effects
        bindings = extra_effects(bindings)
        from c8e_ui_effects import apply as ui_effects
        bindings = ui_effects(bindings)
        from c8e_session_checks import apply as session_effects
        bindings = session_effects(bindings)
        from c8e_host_effects import apply as host_effects
        bindings = host_effects(bindings)
        from c8e_state_effects import apply as state_effects
        bindings = state_effects(bindings)
        if args.slim_receipt:
            bindings['slim-installer/overview/inspect-release'].update(actualSlimReceipt=str(Path(args.slim_receipt).resolve()), prerequisites=[])
        for binding in bindings.values():
            binding['c8e'] = True
            if binding.get('installedObscura') or binding.get('id') == 'neyvia/panes/suggest-command':
                binding['exclusiveSidePort'] = terminal_port
        if args.peer_port is None or args.peer_port in [args.stable_port, *args.ports]:
            raise ValueError('C8e requires a separate explicit local peer port')
        for binding in bindings.values():
            binding['peerUrl'] = f'http://127.0.0.1:{args.peer_port}'
        if args.speech_port:
            if args.speech_port in [args.stable_port, args.peer_port, *args.ports]:
                raise ValueError('Separate explicit speech port required')
            ENV['NEYVIA_DICTATION_ENGINE_URL'] = f'http://127.0.0.1:{args.speech_port}'
            for identity in ('dictation/overview/@check/ready', 'dictation/overview/transcribe-file', 'dictation/prompts/warm-engine'):
                bindings[identity].setdefault('setup', []).insert(0, {'tool': 'backend:dictation_settings_command',
                    'args': {'settings': {'port': args.speech_port, 'device': 'cpu', 'qwenFallback': False, 'enabled': True}}, 'save': 'speechSettings'})
            bindings['dictation/overview/transcribe-file']['inputs'].update(path='${root}/c8/known-speech.wav', engine='phonon2')
            bindings['dictation/overview/transcribe-file']['speechFixture'] = True
    if args.only and set(args.only) - set(bindings):
        raise ValueError('Unknown replay identity')
    validation = validate_bindings(catalog, {key: bindings[key] for key in args.only} if args.only else bindings)
    if not validation['valid'] or (validation['unbound'] and not args.only):
        raise ValueError('Complete valid authored bindings required: ' + json.dumps(validation))
    run_id = uuid.uuid4().hex
    scratch = REPO / '.agent_control/proofs/C8' / run_id
    if args.c8e:
        for binding in bindings.values():
            binding['peerRoot'] = str(scratch / 'peer')
    evidence = REPO / 'scripts/evidence/C8-runs' / run_id; evidence.mkdir(parents=True)
    commit = git('rev-parse', '--verify', args.stable_ref + '^{commit}')
    pin = pin_source(commit, scratch / 'stable')
    rows = {row['id']: row for row in catalog['rows']}
    from grant_agent.neyvia_manuals import get_manual
    manuals = {identity: get_manual(identity)[2] for identity in catalog['manualHashes']}
    authored = [{'id': key, **binding, 'row': rows[key], 'manual': manuals[rows[key]['manual']], 'contracts': rows[key].get('checkContracts', {})}
                for key, binding in bindings.items() if not args.only or key in args.only]
    results, history = [], []
    started = time.time()
    provenance = {'runId': run_id, 'stableCommit': commit, 'candidateCommit': git('rev-parse', 'HEAD'),
                  'candidateUrl': f'http://127.0.0.1:{args.ports[0]}', 'stable': pin,
                  'candidate': {'commit': git('rev-parse', 'HEAD'), 'url': f'http://127.0.0.1:{args.ports[0]}',
                                'build': str(build), 'buildHashes': {p.relative_to(build).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                                   for p in sorted(build.rglob('*')) if p.is_file()}},
                  'candidateSourceHashes': {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in source_files()},
                  'executionMode': 'headless', 'startedAt': started, 'workers': len(args.ports),
                  'candidateStateIsolation': 'Fresh backend state, authenticated local session and headless browser for every journey',
                  'authority': 'Owned scratch only; no credentials/NAS, external providers, visible desktop launch or global CLI updates. Hash-pinned public MiniLM, Tauri 2, Syncthing and headless decoder archives total less than 156 MB; acquisition receipts retain exact bytes.',
                  'socketBoundary': ','.join(map(str, sorted(assigned_ports()))) + ' loopback only; browser requests restricted to candidate origin',
                  'captureRuntime': 'Explicit installed Playwright through NativeToolRegistry.browser_runtime; fresh locally authenticated contexts. Default CDP ephemeral-port renderer is not exercised.',
                  'journeyTargets': {b['id']: f'http://127.0.0.1:{args.ports[i % len(args.ports)]}' for i, b in enumerate(authored)}}
    guard = DesktopGuard(); guard.start()
    stable_process = stable_handle = peer_process = peer_handle = None
    try:
        stable_process, stable_handle, stable_url = launch(scratch / 'stable', scratch / 'stable/.agent_control/proofs/state',
                scratch / 'stable-static', args.stable_port, evidence / 'stable.log')
        provenance['stable']['url'] = stable_url
        if args.speech_port:
            from urllib.request import urlopen
            with urlopen(f'http://127.0.0.1:{args.speech_port}/v1/health', timeout=30) as response:
                health = json.load(response)
            if health.get('state') != 'ready' or health.get('device') != 'cpu':
                raise ValueError('An actual ready CPU speech engine is required')
            guard.attach(int(health['pid']))
            provenance['speechEngine'] = {'url': ENV['NEYVIA_DICTATION_ENGINE_URL'], 'health': health,
                'boundary': 'Task-owned CPU service started by scripts/c8e_speech.py; no microphone or GPU service touched'}
        if args.c8e:
            fixture_files({'files': [{'path': 'c8/input.txt', 'content': 'C8e real local peer file 739\n'}]}, scratch / 'peer', f'http://127.0.0.1:{args.peer_port}')
            peer_process, peer_handle, peer_url = launch(REPO, scratch / 'peer', build, args.peer_port, evidence / 'peer.log')
            provenance['localPeer'] = {'url': peer_url, 'root': str(scratch / 'peer'), 'boundary': 'Owned second backend on this PC; no second-PC latency or device proof'}
        # Keep each port exclusively owned until its worker/service has stopped,
        # then immediately refill that slot instead of waiting for a slow batch.
        remaining = list(authored)
        with ThreadPoolExecutor(max_workers=len(args.ports), thread_name_prefix='c8d') as pool:
            pending = {}
            def submit(chosen):
                occupied = {b.get('exclusiveSidePort') for _, b in pending.values() if b.get('exclusiveSidePort')}
                binding = next((b for b in remaining if not b.get('exclusiveSidePort') or b['exclusiveSidePort'] not in occupied), None)
                if binding is None:
                    return
                remaining.remove(binding)
                provenance['journeyTargets'][binding['id']] = f'http://127.0.0.1:{chosen}'
                future = pool.submit(execute, binding, scratch / 'stable', build, chosen, run_id, scratch, evidence)
                pending[future] = (chosen, binding)
                history.append({'slot': chosen, 'id': binding['id'], 'startedAt': time.time()})
            for chosen in args.ports:
                submit(chosen)
            while pending:
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    chosen, _ = pending.pop(future)
                    result = future.result(); results.append(result)
                    with (evidence / 'progress.jsonl').open('a', encoding='utf-8', newline='\n') as ledger:
                        ledger.write(json.dumps(result, ensure_ascii=False) + '\n')
                occupied_slots = {slot for slot, _ in pending.values()}
                for chosen in args.ports:
                    if chosen not in occupied_slots:
                        submit(chosen)
                write(evidence / 'checkpoint.json', {'results': results, 'provenance': provenance, 'batches': history})
    except Exception as error:
        provenance['runErrors'] = [str(error)]
    finally:
        if stable_process: stop(stable_process)
        if stable_handle: stable_handle.close()
        if peer_process: stop(peer_process)
        if peer_handle: peer_handle.close()
        provenance.update(finishedAt=time.time(), desktopGuard=guard.finish())
        report = aggregate(catalog, results, provenance)
        report['batches'] = history
        report['executionBoundary'] = 'Authored mounted UI actions and fresh invariant-specific effects, plus actual authenticated candidate tool calls; every unmatched or shallow effect stays blocked. No native proof is claimed.'
        write(output, report); write(evidence / 'report.json', report)
        write(evidence / 'raw.json', {'results': results, 'provenance': provenance})
        print(json.dumps({'receipt': str(output), 'runId': run_id, 'counts': report['counts'], 'errors': report['errors'],
                          'desktopGuardPassed': provenance['desktopGuard']['passed']}), flush=True)
    return 0 if report['releaseGate'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
