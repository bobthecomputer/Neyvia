"""Fresh independent effects for locally satisfied prerequisites."""
import hashlib
import json
from pathlib import Path
import time


def run(worker, binding, inputs, root):
    checks = []
    def check(identity, passed, observed):
        checks.append({'id': identity, 'passed': bool(passed), 'fresh': True, 'observed': observed})
        if not passed:
            raise RuntimeError(identity + ': actual defining effect failed: ' + str(observed))
    identity = binding['id']
    if binding.get('localPreparation') == 'gltf-triangle':
        expected = worker.step_results['prerequisiteTriangle']
        scene = Path(root) / 'c8/scene.gltf'
        buffer = scene.with_name('triangle.bin')
        good = worker.tool('neyvia.gamedev.asset_validate', {'path': str(scene)})
        mesh = json.loads(scene.read_text(encoding='utf-8'))
        check('c8e.gltf.actual-indexed-triangle-valid', good.get('valid') is True and
              good.get('validator') == 'Khronos glTF Validator' and good.get('issueCounts', {}).get('numErrors') == 0 and
              good.get('summary', {}).get('totalVertexCount') == 3 and
              good.get('summary', {}).get('totalTriangleCount') == 1 and
              good.get('sha256') == expected['sceneSha256'] and
              mesh['meshes'][0]['primitives'][0]['attributes']['POSITION'] == 0 and
              mesh['accessors'][0]['count'] == 3 and mesh['accessors'][1]['count'] == 3 and
              len(buffer.read_bytes()) == expected['bufferBytes'], good)
        broken = scene.with_name('scene-corrupt.gltf')
        broken_buffer = scene.with_name('triangle-corrupt.bin')
        negative = json.loads(scene.read_text(encoding='utf-8'))
        negative['buffers'][0]['uri'] = broken_buffer.name
        broken.write_text(json.dumps(negative, indent=2) + '\n', encoding='utf-8')
        broken_buffer.write_bytes(buffer.read_bytes()[:8])
        refused = worker.tool('neyvia.gamedev.asset_validate', {'path': str(broken)})
        check('c8e.gltf.corrupt-external-buffer-refused', refused.get('valid') is False and
              refused.get('validator') == 'Khronos glTF Validator' and refused.get('issueCounts', {}).get('numErrors', 0) > 0 and
              any(error.get('code') == 'BUFFER_BYTE_LENGTH_MISMATCH' for error in refused.get('errors', [])),
              {'report': refused, 'declaredBytes': negative['buffers'][0]['byteLength'],
               'actualBytes': broken_buffer.stat().st_size})
        after = worker.tool('neyvia.gamedev.asset_validate', {'path': str(scene)})
        check('c8e.gltf.original-mesh-buffer-unchanged', after.get('valid') is True and
              after.get('sha256') == expected['sceneSha256'] and
              hashlib.sha256(scene.read_bytes()).hexdigest() == expected['sceneSha256'] and
              hashlib.sha256(buffer.read_bytes()).hexdigest() == expected['bufferSha256'],
              {'freshReport': after, 'original': expected})
    if binding.get('localPreparation') == 'terminal-suggestion':
        artifact = Path(worker.step_results['prerequisiteTerminal']['path'])
        pane = worker.page.locator('.nx-tp-host')
        pane.wait_for(state='visible', timeout=30000)
        deadline = time.monotonic() + 30
        selected = None
        rendered = ''
        while time.monotonic() < deadline:
            state = worker.tool('neyvia.terminal.list', {})
            matches = [row for row in state['terminals'] if row.get('typed') == inputs['command']]
            rendered = pane.inner_text()
            if len(matches) == 1 and matches[0].get('alive') and all(
                    word in rendered.replace("\n", "").replace("\r", "") for word in ('manual-terminal-proof.txt', '739')):
                selected = matches[0]
                break
            time.sleep(.2)
        import psutil
        launch_path = Path(root) / 'c8/terminal-launch.json'
        launch = json.loads(launch_path.read_text(encoding='utf-8'))
        owned_shell = psutil.Process(launch['pid'])
        actual_argv, actual_cwd = owned_shell.cmdline(), owned_shell.cwd()
        scoped_paths = [Path(value).resolve() for value in launch['scopedEnvironment'].values()]
        check('c8e.terminal.actual-owned-profile-isolated', actual_argv == launch['argv'] and
              '-NoProfile' in actual_argv and actual_cwd == str(Path(root).resolve()) and
              all(value.is_relative_to(Path(root).resolve()) for value in scoped_paths) and
              Path(launch['historySavePath']).resolve().is_relative_to(Path(root).resolve()) and
              '-HistorySaveStyle SaveNothing -PredictionSource None' in actual_argv[-1],
              {'actualArgv': actual_argv, 'actualCwd': actual_cwd,
               'actualBirthTime': owned_shell.create_time(), 'launchReceipt': launch,
               'launchReceiptSha256': hashlib.sha256(launch_path.read_bytes()).hexdigest()})
        # Wait beyond the product's delayed typing before checking that the
        # suggestion itself never executes the command.
        time.sleep(1)
        before = worker.tool('neyvia.terminal.read', {'id': selected['id'], 'chars': 8000}) if selected else {}
        screenshot = worker.directory / 'terminal-suggested-before-enter.png'
        worker.page.screenshot(path=str(screenshot), full_page=True)
        check('c8e.terminal.rendered-suggestion-awaits-enter', selected is not None and
              selected.get('cwd') == str(Path(root).resolve()) and not artifact.exists() and
              all(word in before.get('text', '').replace("\n", "").replace("\r", "") for word in ('manual-terminal-proof.txt', '739')),
              {'terminal': selected, 'actualOutput': before, 'rendered': rendered,
               'outputAbsent': not artifact.exists(), 'capture': str(screenshot),
               'captureSha256': hashlib.sha256(screenshot.read_bytes()).hexdigest()})
        try:
            def accepted_enter(response):
                if not response.url.endswith('/api/ui/panes') or response.request.method != 'POST':
                    return False
                submitted = response.request.post_data_json
                args = submitted.get('args', {})
                return submitted.get('op') == 'terminal.input' and args.get('id') == selected['id'] and args.get('data') == '\r'
            with worker.page.expect_response(accepted_enter, timeout=30000) as accepted:
                pane.locator('.xterm-helper-textarea').press('Enter')
            response = accepted.value
            body = response.json()
            check('c8e.terminal.single-enter-accepted-by-product', response.status == 200 and body.get('ok') is True,
                  {'url': response.url, 'request': response.request.post_data_json, 'status': response.status, 'body': body})
            deadline = time.monotonic() + 30
            while not artifact.exists() and time.monotonic() < deadline:
                # Scoped request routing needs Playwright message pumping.
                worker.page.wait_for_timeout(100)
            after = worker.tool('neyvia.terminal.read', {'id': selected['id'], 'chars': 8000})
            payload = artifact.read_bytes() if artifact.is_file() else b''
            check('c8e.terminal.enter-runs-real-command', payload == b'manual terminal returned 739',
                  {'terminal': after, 'path': str(artifact), 'bytes': len(payload),
                   'sha256': hashlib.sha256(payload).hexdigest(), 'content': payload.decode('utf-8')})
        finally:
            worker.page.get_by_role('button', name='End this terminal', exact=True).click()
        deadline = time.monotonic() + 15
        while True:
            remaining = worker.tool('neyvia.terminal.list', {})
            if all(row['id'] != selected['id'] for row in remaining['terminals']) or time.monotonic() >= deadline:
                break
            time.sleep(.1)
        check('c8e.terminal.closed-through-rendered-control',
              all(row['id'] != selected['id'] for row in remaining['terminals']), remaining)
    if binding.get('localPreparation') == 'authored-validator-input':
        from c8e_scroll_checks import check as check_scroll
        checks.extend(check_scroll(worker, inputs, root))
    if binding.get('actualSlimReceipt'):
        import shutil
        import subprocess
        source = Path(binding['actualSlimReceipt']).resolve()
        repo = Path(__file__).resolve().parents[1]
        source.relative_to(repo / '.agent_control/proofs/C8')
        result = subprocess.run([shutil.which('node'), str(repo / 'scripts/c8e_verify_slim.mjs'), str(source)],
                                cwd=repo, capture_output=True, text=True, encoding='utf-8', timeout=300,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        observed = json.loads(result.stdout) if result.returncode == 0 else {'stderr': result.stderr[-2000:]}
        check('c8e.slim.actual-build-packages-and-corruption-refusals',
              result.returncode == 0 and observed.get('passed') is True, observed)
        staged = Path(root) / inputs['path']
        check('c8e.slim.inspected-exact-producer-report',
              hashlib.sha256(staged.read_bytes()).hexdigest() == observed['receiptSha256'],
              {'sourceReceipt': str(source), 'inspectedPath': str(staged), 'sha256': observed['receiptSha256']})
    if identity == 'onboarding/overview/stage-chosen-pack':
        deadline = time.monotonic() + 60
        while True:
            state = worker.tool('neyvia.onboarding.pack', {'packId': inputs['packId'], 'action': 'status'})
            row = state['packs'][0]
            if row['state'] in {'installed', 'failed', 'unavailable'} or time.monotonic() >= deadline:
                break
            time.sleep(.2)
        verified = []
        if row.get('state') == 'installed':
            manifest = json.loads((Path(row['target']) / 'installed.json').read_text(encoding='utf-8'))
            for entry in manifest.get('files', []):
                path = Path(row['target']) / entry['path']
                verified.append({'path': str(path), 'passed': path.is_file() and path.stat().st_size == entry['size'] and
                    hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']})
        check('c8e.pack.real-installed-payloads', row['state'] == 'installed' and row.get('stagedOnly') is True and
              bool(verified) and all(v['passed'] for v in verified), {'state': row, 'files': verified})
    if identity == 'settings/overview/propose-change':
        current = worker.tool('neyvia.settings.get', {})
        patch = inputs['patch']
        check('c8e.settings.applied-change', current['revision'] > inputs['expectedRevision'] and
              all(current['settings'].get(k) == v for k, v in patch.items()) and patch != {'density': 'calm'}, current)
        refused = False
        try:
            worker.tool('neyvia.settings.propose', {'patch': {'density': 'grove'}, 'expectedRevision': inputs['expectedRevision']})
        except Exception as error:
            refused = 'Settings changed' in str(error)
        after = worker.tool('neyvia.settings.get', {})
        check('c8e.settings.stale-refusal', refused and after['revision'] == current['revision'] and
              after['settings'] == current['settings'], {'refused': refused, 'after': after})
    if binding.get('localPreparation') == 'paired-local-peer':
        procedure = identity.rsplit('/', 1)[1]
        if procedure in {'take-file', 'send-to-inbox', 'verify-taken-file'}:
            device = worker.step_results['prerequisitePeer']['device']
            transfers = worker.tool('neyvia.devices.transfers', {})
            matches = [t for t in transfers['transfers'] if t.get('deviceId', t.get('device')) == device]
            if not matches:
                matches = transfers['transfers']
            deadline = time.monotonic() + 30
            while matches and matches[-1]['status'] not in {'done', 'failed'} and time.monotonic() < deadline:
                time.sleep(.2)
                transfers = worker.tool('neyvia.devices.transfers', {})
                matches = transfers['transfers']
            transfer = matches[-1] if matches else {}
            destination = Path(transfer.get('to', ''))
            source = Path(root) / 'c8/input.txt' if procedure == 'send-to-inbox' else Path(worker.step_results['prerequisitePeer']['source'])
            payload = source.read_bytes()
            observed = {'transfer': transfer, 'destination': str(destination),
                        'sourceSha256': hashlib.sha256(payload).hexdigest(),
                        'destinationSha256': hashlib.sha256(destination.read_bytes()).hexdigest() if destination.is_file() else None}
            check('c8e.peer.actual-transfer-bytes', transfer.get('status') == 'done' and destination.is_file() and
                  destination.read_bytes() == payload and transfer.get('size') == len(payload), observed)
    return checks
