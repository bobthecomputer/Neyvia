"""C8e prerequisite inventory and real scratch-owner preparation.

Preparation uses authenticated product endpoints. It never writes a returned
identity, completed receipt, provider response, or approval grant into state.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'config/inception_c8e_prerequisites.json'


def _repair_bindings():
    code = "from pathlib import Path; Path('manual-terminal-proof.txt').write_text('manual terminal returned 739', encoding='utf-8')"
    python = 'C:/Users/user/AppData/Local/Programs/Python/Python313/python.exe'
    return {
        'game-dev/bridges/validate-export-before-engine-load': {
            'localPreparation': 'gltf-triangle', 'prerequisites': []},
        'mission-plan/orchestration/prepare': {'files': [{
            'path': 'c8/plan.md', 'content': '# C8 dormant plan\n\n## §0 Shared rules\nUse only disposable local files. Never start work.\n| Track | Worktree | Backend | Vite |\n|---|---|---|---|\n| fixture | ${root}/c8 | assigned at runtime | assigned at runtime |\n\n## §1 fixture: inspect artifact\nRead the C8 artifact.\n'}]},
        'neyvia/panes/suggest-command': {
            'localPreparation': 'terminal-suggestion',
            'inputs': {'command': f'& \'{python}\' -c "{code}"'},
            'terminalFixture': True, 'deadlineSeconds': 180},
    }


def _triangle(worker, root):
    """An actual indexed mesh with a local buffer, not an empty scene."""
    import struct
    folder = Path(root) / 'c8'
    folder.mkdir(parents=True, exist_ok=True)
    payload = struct.pack('<9f3H2x', 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    manifest = {
        'asset': {'version': '2.0'}, 'scene': 0,
        'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'mode': 4}]}],
        'buffers': [{'uri': 'triangle.bin', 'byteLength': len(payload)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36, 'target': 34962},
                        {'buffer': 0, 'byteOffset': 36, 'byteLength': 6, 'target': 34963}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                       'min': [0, 0, 0], 'max': [1, 1, 0]},
                      {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR',
                       'min': [0], 'max': [2]}],
    }
    scene = folder / 'scene.gltf'
    buffer = folder / 'triangle.bin'
    scene.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    buffer.write_bytes(payload)
    worker.step_results['prerequisiteTriangle'] = {
        'sceneSha256': hashlib.sha256(scene.read_bytes()).hexdigest(),
        'bufferSha256': hashlib.sha256(payload).hexdigest(),
        'bufferBytes': len(payload), 'vertices': 3, 'indices': [0, 1, 2],
    }


def apply(bindings):
    """Add authored prerequisites without replacing other agents' bindings."""
    overlay = json.loads(OVERLAY.read_text(encoding='utf-8'))
    result = copy.deepcopy(bindings)
    for identity, additions in overlay['bindings'].items():
        for key, value in additions.items():
            if key in {'inputs', 'dynamicInputs'}:
                result[identity].setdefault(key, {}).update(copy.deepcopy(value))
            elif key in {'files', 'setup', 'sourceCopies'}:
                result[identity].setdefault(key, []).extend(copy.deepcopy(value))
            else:
                result[identity][key] = copy.deepcopy(value)
    return result


def stage(binding, root):
    """Copy installed explicit engines into owned scratch before backend start."""
    if not binding.get('installedObscura'):
        return
    root = Path(root).resolve()
    root.relative_to(ROOT / '.agent_control/proofs/C8')
    installed = Path(binding['installedObscura']).resolve()
    allowed = Path('C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f/obscura-v0.2.4/extracted/obscura.exe').resolve()
    if installed != allowed:
        raise PermissionError('Only the explicitly inspected installed Obscura binary is admitted')
    destination = root / 'c8'
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for source in (installed, installed.with_name('obscura-worker.exe')):
        target = destination / source.name
        shutil.copyfile(source, target)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            raise RuntimeError('Installed Obscura copy failed byte verification')
        manifest.append({'source': str(source), 'target': str(target), 'sha256': sha})
    (destination / 'obscura-installed.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def _record(worker, tool, arguments, row, target=None):
    path = worker.directory / f'call-{len(worker.calls):03d}.json'
    envelope = {'target': target or worker.args.candidate_url,
                'tool': tool, 'arguments': arguments, **row}
    path.write_text(json.dumps(envelope, indent=2) + '\n', encoding='utf-8')
    worker.calls.append({**envelope, 'receipt': str(path),
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return row


def owner(worker, path, arguments, client=None):
    """Owner endpoint admitted only for this test profile and assigned peer."""
    client = client or worker.candidate
    row = client.post(path, arguments)
    _record(worker, 'owner:' + path, arguments, {'httpStatus': 200, 'body': row}, client.url)
    if row.get('ok') is False:
        raise RuntimeError('Scratch owner prerequisite refused: ' + json.dumps(row))
    return row.get('data', row)


def _request_tool(worker, name, args):
    from grant_agent.neyvia_manuals import unwrap
    row = worker.candidate.post('/api/ui/tools/call', {'tool': name, 'arguments': args})
    _record(worker, name, args, {'httpStatus': 200, 'body': row})
    if row.get('ok') is False and row.get('data', {}).get('status') != 'approval_required':
        raise RuntimeError('Product prerequisite refused: ' + json.dumps(row))
    data = row.get('data', {})
    # unwrap intentionally returns failed NativeToolReceipt envelopes intact.
    # The approval ID is an authoritative action result inside that envelope.
    # Extract only this declared refusal, retaining the full envelope above.
    if data.get('status') == 'approval_required':
        refusal = data.get('result', data)
        if not isinstance(refusal, dict) or refusal.get('status') != 'approval_required' or not refusal.get('approvalId'):
            raise RuntimeError('Approval refusal omitted its returned approval identity')
        return refusal
    return unwrap(data)


def approve_request(worker, name, args):
    """Exercise refusal then approve precisely the returned scratch request."""
    row = _request_tool(worker, name, args)
    if row.get('status') != 'approval_required' or not row.get('approvalId'):
        if row.get('ok') is False:
            raise RuntimeError('Unexpected product prerequisite result: ' + json.dumps(row))
        return row
    return owner(worker, '/api/ui/approve', {'id': row['approvalId']})


def _peer(worker, binding, inputs, root):
    from c8_journey import Candidate
    peer_url = binding.get('peerUrl')
    if not peer_url:
        raise RuntimeError('Missing locally owned peerUrl; second physical PC is not required for web transfer proof')
    peer = Candidate(peer_url)
    # Production hello binds each service's own advertised URL; no discovery.
    for url in (worker.args.candidate_url, peer_url):
        with urlopen(Request(url + '/api/peer/v1/hello'), timeout=10) as response:
            hello = json.load(response)
        _record(worker, 'peer:hello', {}, {'httpStatus': 200, 'body': hello}, url)
    paired = owner(worker, '/api/ui/devices', {'op': 'pair', 'args': {'url': peer_url, 'name': 'C8e disposable local peer'}})
    requests = owner(worker, '/api/ui/devices', {'op': 'requests', 'args': {}}, peer)
    selected = [row for row in requests['requests'] if row['fromUrl'] == worker.args.candidate_url]
    if len(selected) != 1:
        raise RuntimeError('Exact scratch peer request was not returned')
    # The peer backend is configured with its own safe default share/inbox.
    owner(worker, '/api/ui/devices', {'op': 'approve', 'args': {'request': selected[0]['id']}}, peer)
    identity = paired['device']['id']
    for _ in range(40):
        state = worker.tool('neyvia.devices.list', {})
        matched = [row for row in state['devices'] if row['id'] == identity]
        if matched and matched[0]['status'] == 'paired':
            break
        time.sleep(.1)
    else:
        raise RuntimeError('Owner-approved local pairing did not finish')
    places = worker.tool('neyvia.devices.files.list', {'device': identity})
    shared = next(row for row in places['places'] if row['kind'] == 'shared')
    remote = str(Path(shared['path']) / 'input.txt')
    inputs['device'] = identity
    procedure = binding['id'].rsplit('/', 1)[1]
    if procedure == 'read-remote-range':
        inputs['path'] = remote
    elif procedure == 'take-file':
        inputs.update({'from': remote, 'to': str(root / 'c8/taken')})
    elif procedure == 'send-to-inbox':
        approve_request(worker, 'neyvia.devices.files.send',
                        {'device': identity, 'from': str(root / 'c8/input.txt')})
    elif procedure == 'verify-taken-file':
        taken = worker.tool('neyvia.devices.files.fetch',
                            {'device': identity, 'from': remote, 'to': str(root / 'c8/taken'), 'wait': 30})
        transfer = taken['transfer']
        if transfer['status'] != 'done':
            raise RuntimeError('Real prerequisite Take did not complete: ' + json.dumps(transfer))
        inputs.pop('device', None)
        inputs.update({'id': transfer['id'], 'to': transfer['to'], 'size': transfer['size']})
    worker.step_results['prerequisitePeer'] = {'device': identity, 'source': remote}


def prepare(worker, binding, inputs, root):
    """Run before binding.setup; mutates only inputs and retained step results."""
    mode = binding.get('localPreparation')
    if mode == 'obscura':
        from c8_scope import fixture_port
        owner(worker, '/api/ui/browser', {'op': 'headless.start', 'args': {'port': fixture_port(), 'allowLocalFixtures': True}})
    elif mode == 'paired-local-peer':
        _peer(worker, binding, inputs, Path(root))
    elif mode == 'image-export-grant':
        row = owner(worker, '/api/ui/tools/preflight',
                    {'tool': 'neyvia.image.export', 'arguments': {'path': inputs['path']}})
        if row.get('approvalId'):
            owner(worker, '/api/ui/approve', {'id': row['approvalId']})
    elif mode == 'night-budget-grant':
        approve_request(worker, 'neyvia.nightshift.resources',
                        {'maxNightSeconds': inputs['nightSeconds'], 'holdAtPlanPercent': inputs['holdPercent']})
    elif mode == 'workflow-host-report':
        _workflow(worker, binding, inputs, Path(root))
    elif mode == 'authored-validator-input':
        from c8e_scroll_checks import prepare as prepare_scroll
        prepare_scroll(worker, inputs, Path(root))
    elif mode == 'gltf-triangle':
        _triangle(worker, root)
    elif mode == 'terminal-suggestion':
        artifact = Path(root) / 'manual-terminal-proof.txt'
        if artifact.exists():
            raise RuntimeError('Terminal proof requires a fresh absent output, not an existing artifact')
        worker.step_results['prerequisiteTerminal'] = {'path': str(artifact), 'absent': True}


def _workflow(worker, binding, inputs, root):
    """Author stages while actually executing a guarded artifact workflow.

    Host receipts retain measurements and links to original product responses.
    Zero tokens means precisely zero model transports, not a missing estimate.
    """
    manual = binding['id'].split('/')[0]
    folder = root / 'c8/workflow'
    folder.mkdir(parents=True, exist_ok=True)
    frozen = {'tool': 'workspace.read', 'path': 'c8/workflow/value.txt', 'criterion': 'content equals 739 newline'}
    check_hash = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    evidence = {}

    def host(identity, values, call=None):
        path = folder / (identity + '.json')
        if call is not None:
            values = {**values, 'productReceipt': call['receipt'], 'productReceiptSha256': call['sha256']}
        values = {'schema': 'neyvia.c8e.workflow-host-measurement.v1',
                  'authority': 'Actual local product calls; no model transport invoked', **values}
        path.write_text(json.dumps(values, indent=2) + '\n', encoding='utf-8')
        evidence[identity] = {'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        return identity

    def event(stage, **data):
        return {'stage': stage, 'data': data}

    initial = worker.tool('workspace.write', {'path': frozen['path'], 'content': 'before\n'})
    baseline = worker.tool('workspace.read', {'path': frozen['path']})
    host('baseline', {'checkHash': check_hash, 'value': int(baseline['content'] == '739\n'), 'noise': 0}, worker.calls[-1])
    started = time.monotonic()
    candidate = worker.tool('workspace.write', {'path': frozen['path'], 'content': '739\n', 'expectedSha256': baseline['sha256']})
    attempted = worker.calls[-1]
    measured = worker.tool('workspace.read', {'path': frozen['path']})
    success = measured['content'] == '739\n' and measured['sha256'] == hashlib.sha256(b'739\n').hexdigest()
    latency = (time.monotonic() - started) * 1000
    host('attempt', {'path': 'script', 'success': success, 'cheaperFailures': []}, attempted)
    host('measure', {'checkHash': check_hash, 'value': int(success), 'path': 'script', 'tokens': 0,
                     'modelCalls': 0, 'latencyMs': latency, 'success': success}, worker.calls[-1])
    host('log', {'kind': 'research-ledger', 'measurement': 'measure', 'modelCalls': 0, 'tokens': 0})
    # Challenge the exact optimistic-concurrency mechanism with the stale hash.
    stale_refused = False
    try:
        worker.tool('workspace.write', {'path': frozen['path'], 'content': 'incorrect overwrite', 'expectedSha256': baseline['sha256']})
    except Exception as error:
        stale_refused = bool(worker.calls and worker.calls[-1].get('httpStatus') in {200, 400, 409}
                             and any(term in str(error).lower() for term in ('hash', 'changed', 'conflict', 'stale')))
    unchanged = worker.tool('workspace.read', {'path': frozen['path']})
    stale_refused = stale_refused and unchanged['sha256'] == measured['sha256']
    host('stale-refusal', {'success': stale_refused, 'currentSha256': unchanged['sha256'], 'staleSha256': baseline['sha256']}, worker.calls[-2])
    if not success or not stale_refused:
        raise RuntimeError('Workflow task failed exact artifact/CAS checks; report cannot claim quality')
    quality = 1.0  # Independent frozen host assessment: exact bytes plus stale refusal.
    if manual == 'hill-climb':
        events = [event('baseline', receipt='baseline'), event('change', changes=['Guarded value replacement'], candidate='CAS artifact'),
                  event('measure', receipt='measure'), event('decision', keep=True, reason='Identical frozen exact-byte check improved from 0 to 1 with noise 0'),
                  event('log', receipt='log'), event('stop', rule='Stop after exact-byte success and stale-write refusal; no additional mechanisms')]
    elif manual == 'efficiency':
        events = [event('paths', available=['script']), event('attempt', path='script', receipt='attempt', reason='An exact guarded artifact replacement has a deterministic tool path'),
                  event('measure', receipt='measure'), event('log', receipt='log')]
    elif manual == 'research':
        sources = []
        for path, finding in [('manuals/workspace.manual.json', 'Existing writes require matching observed SHA256'),
                              ('src/grant_agent/workspace_actions.py', 'Product action layer returns structured effects and observations')]:
            read = worker.tool('workspace.read', {'path': path})
            host('source-' + str(len(sources)), {'success': bool(read['content']), 'sha256': read['sha256']}, worker.calls[-1])
            sources.append({'source': path, 'finding': finding})
        events = [event('question', question='Does observed-hash CAS preserve a newly written artifact against a stale writer?'),
                  event('prior-art', sources=sources), event('claim', prediction='The stale hash is refused and current bytes survive', falsifier='Stale overwrite succeeds or current hash changes'),
                  event('test', receipt='stale-refusal'), event('result', supported=True, limitations=['One disposable text artifact on the authenticated local tool boundary; no native or concurrent process race claim'])]
    elif manual == 'critique-review':
        events = [event('plan', mechanism='Read current hash, CAS-write selected bytes, independently read exact content/hash'),
                  event('attack', risks=[{'failure': 'Blind write destroys current text', 'evidence': 'baseline and stale-refusal host receipts'},
                                        {'failure': 'Action receipt claims success without saved bytes', 'evidence': 'measure independently reads expected bytes and SHA256'}]),
                  event('verify', receipts=['measure', 'stale-refusal']), event('decision', done=True, missing=[])]
    elif manual == 'creativity':
        events = [event('reframe', question='How can disposable artifact edits preserve user work and prove their effect?', borrowedField='Optimistic concurrency in databases', constraintFlip='Use observed versions as the permission to replace'),
                  event('diverge', options=[{'id':'cas','family':'version comparison','mechanism':'Require current SHA256 before replacement','benefit':'Detect stale observations','cost':2},
                    {'id':'append','family':'append log','mechanism':'Append a new journal entry','benefit':'Retain previous content','cost':1},
                    {'id':'copy','family':'immutable artifacts','mechanism':'Write a new named artifact','benefit':'Avoid original overwrite','cost':2}]),
                  event('criteria', weights={'novelty':1,'usefulness':3,'cost':1}),
                  event('choose', option='cas', reason='Current task requires exact replacement; CAS meets preservation and independent effect verification at two local calls')]
    else:
        frame = worker.screenshot('workflow-render')
        artifact = Path(frame['path'])
        target = folder / artifact.name
        shutil.copyfile(artifact, target)
        observation = worker.observe()
        host('render', {'rendered': True, 'success': True, 'artifact': target.relative_to(root).as_posix(),
                        'artifactSha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'observation': observation})
        events = [event('reference', source='Rendered existing candidate operator shell', principle='The primary workspace uses the full selected mode'),
                  event('details', choices=[{'pattern':'Reduced motion','purpose':'Keep task verification stable and respect movement preferences'},
                                           {'pattern':'Compact navigation','purpose':'Leave working space visible'}]),
                  event('render', receipt='render'), event('critique', defects=[], tasteReason='Observed candidate loads the full operator shell and presents the selected workspace; this report checks the existing surface, not a native redesign'),
                  event('decision', done=True, remaining=[])]
    inputs.update(report={'events': events, 'result': {'artifact': frozen['path'], 'verifiedSha256': measured['sha256'],
                  'modelCalls': 0, 'tokenAuthority': 'No model transport was invoked'}}, evidence=evidence, outcomeQuality=quality, tokens=0)


def ledger():
    return json.loads(OVERLAY.read_text(encoding='utf-8'))['prerequisites']


def author():
    previous = json.loads((ROOT / 'scripts/evidence/C8d-final-adjudications.json').read_text(encoding='utf-8'))
    rows = {key: value for key, value in previous['classifications'].items()
            if value['status'] == 'failed' and value['category'] == 'environment'}
    definitions = {
        'autopilot': ('provider', 'An authorized real planning/intent model transport plus returned production autopilot.start run with completed effect checks. The empty C8 broker and blocked credentials cannot create this run; seed replay only after a real learned run.'),
        'browser': ('local-runtime', 'Explicit installed Obscura executable, owner engine_start command, explicitly assigned C8 port and fixture grant. No Chromium substitution.'),
        'conductor': ('provider', 'Planner, executor and verifier routing profiles backed by a real authorized model transport; production conductor.plan must return the saved job identity. Placeholder job IDs are invalid.'),
        'cross-pc': ('local', 'Second independently rooted Neyvia backend on assigned loopback port, owner pair request/approval, scratch-only read share/inbox, and returned hash-verified production transfer identity. No physical second PC is needed to prove this web boundary.'),
        'dictation': ('local-runtime', 'Installed Phonon-2 engine with cached model weights and CPU dependencies, started hidden on an assigned port with qwen fallback disabled. A known spoken audio fixture is needed for transcript effect; silence alone is shallow. No microphone is needed for file transcription.'),
        'game-dev': ('local', 'Installed Node executing packages/game-dev/validate-asset.cjs on the authored scratch glTF; admit only this exact validator command. Editor action review additionally requires actual C11 editor bridge completion.'),
        'image-studio': ('local', 'Owner grant returned by production image.export preflight for this exact scratch output parent; initial file must be absent and existing image opened. Then verify fresh exported pixels and dimensions.'),
        'mobile-studio': ('local-runtime', 'JDK java/javac, Android SDK adb/platform/build-tools, Gradle wrapper and a native Android project. PATH inspection found none of java,javac,adb,gradle. app_sdk.new(kind=web) is not an Android project.'),
        'neyvia-reference': ('provider', 'A genuine retained connected run from an authorized model harness; watch.create must use returned runId and verify the actual terminal transition. Empty adapters cannot create a real run.'),
        'neyvia': ('provider', 'A real connected-session identity returned by an authorized installed harness run in this scratch root, then owner overlay move/rename and fresh list/read. Invented session IDs cannot satisfy broker.find_summary.'),
        'nightshift': ('local', 'Owner approval of exact resources patch maxNightSeconds=60 and holdAtPlanPercent=80 within test profile; fresh resources read must reflect both and no task starts.'),
        'onboarding': ('local', 'A catalog-recognized local pack with production manifest/signature/hash validation. Existing pack.creator-sdk is suitable; c8-local-fixture is not cataloged. Stage and verify every installed byte in scratch.'),
        'perception': ('provider', 'Real authorized installed visual model transport with image/video decoding support. The C8 saved-credential guard and child-process fence reject Codex visual extraction; no fake OCR/provider response is permitted. A real video fixture replaces PNG masquerading as video.'),
        'scroll-generator': ('provider', 'Actual source import plus a model-generated pack retaining source citations, nonempty concepts/cards and generation/run provenance; independently check claim entailment and sequencing. Empty card arrays are not a generated pack.'),
        'settings': ('local', 'Return exact owner approvalId from settings.propose and approve via scratch owner endpoint; approval commits requested patch at observed revision. Re-read actual settings and revision; never pre-grant a different fingerprint.'),
        'sidebar': ('local-runtime', 'Local CPU all-MiniLM-L6-v2 model and hash-pinned receipt, torch+transformers runtime, and actual dormant transcript-backed sessions with overlapping subjects. No model receipt exists at this worktree .agent_control/t7/embedding-model; empty ids would be shallow even after model installation.'),
        'slim-installer': ('local-build', 'Run stage_portable_python.py and prepare_slim_release.mjs with an ephemeral scratch signing key and installed build toolchain; retain actual neyvia.slim-release/v1 report, package hashes/signature verification and executable build receipt. No marker-only release JSON.'),
    }
    workflow = ('local-report', 'Real chronological workflow stages authored from this task, real tool host receipts with file+SHA256 links, measured latency/transport-reported token usage and an independent outcome assessment; empty reports/evidence cannot establish adherence.')
    overrides = {
        'design/check-loop/build-check': ('local', 'Hidden installed Node/Vite build command rooted at scratch copied source, explicit output under scratch and local cache outside node_modules junction; admit exact argv only.'),
        'design/check-loop/check-render': ('local', 'Authenticated owned candidate origin, installed Playwright capture runtime and existing waitFor .nx-root; sufficient per-row timeout with actual screenshot artifact and rendered assertions, not an observer success bit.'),
        'design/craft/craft-check': ('local', 'Actual local component source copies plus approved hidden Node design checker with request file, output and journal confined to scratch. Require capture artifact and fresh defect observations.'),
        'design/details/prove-details': ('local', 'Installed system Python runs exact c8e_design_checks.py details-lab/details-shell/details-kit adapters over existing production helpers, installed headless runtime and assigned candidate URL; outputs and captures remain in scratch.'),
        'game-dev/bridges/review-completed-action': ('C11', 'Actual completed editor bridge request from C11 isolated agent desktop; no native editor launch or fabricated action receipt.'),
    }
    local_inspection = {
        'android': {'installedCommandsFound': [], 'missingCommands': ['java', 'javac', 'adb', 'gradle'],
                    'missingStandardLocations': ['C:/Users/user/AppData/Local/Android/Sdk', 'C:/Program Files/Java'],
                    'reason': 'No installed Android toolchain was found by the production command lookup or these standard locations; the authored web SDK project also lacks native Android/Gradle files.'},
        'sidebar': {'missingLocations': ['.agent_control/t7/embedding-model/receipt.json',
                                        'C:/Users/user/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2'],
                    'reason': 'No inspected installed local model can be activated without acquiring new model files. Empty transcript IDs remain a distinct missing real-effect prerequisite.'},
        'slim': {'installedCommandsFound': ['cargo', 'rustc'], 'missingCommandsInPath': ['cl', 'clang', 'cmake'],
                 'missingLocalBuildDirectory': 'src-tauri/target',
                 'scopeBlockers': ['stage_portable_python.py requires output inside its repo/src-tauri/target',
                                   'prepare_slim_release.mjs requires a signing key outside its repo',
                                   'buildInstaller only allows local HTTP ports48161-48169 or INT6 ports48351-48359; assigned task C8 ports are rejected'],
                 'reason': 'A fresh nested scratch source with external-to-that-source ephemeral key could satisfy staging scopes; actual installer build still needs an approved C8 base URL and complete offline native compiler/dependencies. Staging a signed pack alone is not an executable installer run.'},
        'modelRoutes': {'brokerAdapters': [], 'loadDefaults': False,
                        'reason': 'The C8 backend intentionally initializes no harness adapters and its proof guard denies saved credential access. No real connected session/run, planning job, visual provider or generated study pack exists in that profile. This is a local missing route/authority boundary; no outside account absence was verified.'},
    }
    result = []
    for identity, row in rows.items():
        family = identity.split('/')[0]
        category, missing = overrides[identity] if identity in overrides else workflow if identity.endswith('/verify-and-record') else definitions[family]
        result.append({'id': identity, 'missingPrerequisite': missing,
                       'resolutionClass': category, 'status': 'unattempted',
                       'previousObservedCause': row.get('observedStructuredCause'),
                       'previousReceipt': row['rawReceipt'],
                       'previousReceiptSha256': row['rawReceiptSha256'],
                       'needsPaul': family == 'mobile-studio',
                       'boundary': 'C11 native' if category == 'C11' else 'owned web scratch'})
        if family in {'mobile-studio', 'sidebar', 'slim-installer'}:
            result[-1]['localInspection'] = local_inspection[{'mobile-studio':'android', 'sidebar':'sidebar', 'slim-installer':'slim'}[family]]
        if family == 'mobile-studio':
            result[-1]['needsPaulReason'] = 'No installed JDK/Android SDK or native Android project was found. The shared rules forbid system installs; a toolchain installation or a separately prepared isolated Android environment needs Paul\'s decision.'
        if category == 'provider':
            result[-1]['localInspection'] = local_inspection['modelRoutes']
    bindings = {}
    for identity in rows:
        if identity.startswith('cross-pc/'):
            bindings[identity] = {'localPreparation': 'paired-local-peer', 'prerequisites': [],
                                  'files': [{'path': 'c8/input.txt', 'content': 'C8 journey artifact\n'}]}
        elif identity.endswith('/verify-and-record'):
            bindings[identity] = {'localPreparation': 'workflow-host-report', 'prerequisites': [],
                                  'sourceCopies': ['manuals/workspace.manual.json', 'src/grant_agent/workspace_actions.py']}
    bindings.update({
        'browser/backend/observe-tab': {'localPreparation': 'obscura', 'prerequisites': [],
                                      'installedObscura': 'C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f/obscura-v0.2.4/extracted/obscura.exe'},
        'image-studio/overview/export-reviewed-image': {'localPreparation': 'image-export-grant', 'prerequisites': []},
        'nightshift/board/night-budget': {'localPreparation': 'night-budget-grant', 'prerequisites': []},
        'settings/overview/propose-change': {'ownerApproval': True, 'ownerApprove': ['neyvia.settings.propose'], 'inputs': {'patch': {'density': 'workshop'}}, 'prerequisites': []},
        'onboarding/overview/stage-chosen-pack': {'inputs': {'packId': 'pack.creator-sdk'}, 'prerequisites': [], 'deadlineSeconds': 300},
        'design/check-loop/check-render': {'deadlineSeconds': 300},
        'game-dev/bridges/review-completed-action': {'nativeOnly': {'needs': 'C11', 'tool': 'game_dev.receipt',
            'step': 'Review actual editor bridge completion on C11 isolated desktop', 'reason': 'This prerequisite is native editor behavior.'}},
    })
    bindings.update(_repair_bindings())
    value = {'schema': 'neyvia.inception.prerequisites.v1', 'baselineEnvironmentFailures': len(rows),
             'source': 'scripts/evidence/C8d-final-adjudications.json',
             'authority': 'Authored local inputs and owner actions only; resolution remains unattempted until fresh real receipts.',
             'prerequisites': result, 'bindings': bindings,
             'needsPaul': [{'id': entry['id'], 'reason': entry['needsPaulReason']} for entry in result if entry.get('needsPaul')],
             'needsPaulReason': 'Only an installed Android environment requires a new installation decision. No missing microphone, second physical PC, purchase, or outside account was established. C11 and provider routing remain separate authority/track prerequisites.'}
    OVERLAY.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return {'rows': len(result), 'bindings': len(bindings)}


if __name__ == '__main__':
    print(json.dumps(author()))
