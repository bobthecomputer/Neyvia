"""Bind FIXCL2 real-run receipts, current coverage and bounded AUD4 updates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from fixcl_verify import REPO, environment

EVIDENCE = REPO / 'scripts/evidence'
AUD4 = Path(r'C:\Users\user\Projects\nx-audit4\scripts\evidence\AUD4.json')
PRIMARY = ('authority', 'terminal', 'cold', 'cold-empty', 'documents', 'durable',
           'frontier-local', 'coordination', 'semantic', 'renderer', 'work', 'creative', 'browser', 'sidebar')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_receipt(name):
    path = EVIDENCE / ('FIXCL2-' + name + '.json')
    proof = json.loads(path.read_bytes())
    if proof.get('ok') is False:
        raise ValueError('Failed real run: ' + str(path))
    checks = proof.get('checks', {})
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        raise ValueError('Unpassed real checks: ' + name + ' ' + str([key for key, value in checks.items() if value is not True]))
    start = proof.get('sourceHashesAtStart', proof.get('sourceHashes', {}))
    end = proof.get('sourceHashesAtEnd', start)
    if not start or start != end:
        raise ValueError('Missing or changed source boundary: ' + name)
    for relative, digest in start.items():
        target = REPO / relative
        if not target.resolve().is_relative_to(REPO) or sha(target) != digest:
            raise ValueError('Receipt source drift: ' + name + ' ' + relative)
    return proof


def witnesses(proofs):
    found = {}
    def visit(value, receipt, pointer):
        if isinstance(value, dict):
            use = value.get('manualUse')
            uses = use if isinstance(use, list) else [use]
            if value.get('ok') is True:
                for index, use in enumerate(uses):
                    if not isinstance(use, dict) or not use.get('effectChecks'):
                        continue
                    key = use['tool']
                    found.setdefault(key, []).append({'receipt': receipt, 'pointer': pointer,
                        'manualUseIndex': index if isinstance(value.get('manualUse'), list) else None,
                        'procedure': use['procedure'], 'actionIdentity': use['actionIdentity'],
                        'manual': use['manual'], 'sourceSha256': use['sourceSha256']})
            for key, child in value.items():
                visit(child, receipt, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, receipt, pointer + '/' + str(index))
    for name, proof in proofs.items():
        visit(proof, 'FIXCL2-' + name + '.json', '')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48821, 48830):
        parser.error('Assigned explicit port required')
    scratch = REPO / '.agent_control/proofs' / ('FIXCL2-seal-' + str(time.time_ns()))
    scratch.mkdir(parents=True)
    import sys
    sys.path.insert(0, str(REPO / 'src'))
    from grant_agent.proof_credential_guard import install
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install(scratch); install_hidden_subprocess_default()
    def audit_scope(event, values):
        if event in {'socket.connect', 'socket.bind'}:
            address = values[1]
            if isinstance(address, tuple) and (address[0] not in {'127.0.0.1', 'localhost', '::1'} or address[1] not in range(48821, 48830)):
                raise PermissionError('Seal uses only assigned loopback ports')
        if event == 'subprocess.Popen':
            command = values[1]
            permitted = [['git', 'cat-file', '--batch'],
                         ['git', 'log', '7eb28830..HEAD', '--format=%H %s']]
            if not any(command == candidate or command == subprocess.list2cmdline(candidate) for candidate in permitted):
                raise PermissionError('Seal admits only its two exact read-only Git commands')
    sys.addaudithook(audit_scope)
    environment(scratch, args.port)
    import os
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(scratch)
    proofs = {name: verify_receipt(name) for name in PRIMARY}
    compile_path = EVIDENCE / 'FIXCL2-manual-compile.json'
    compilation = json.loads(compile_path.read_bytes())
    if compilation['mode'] != 'check' or not all(row['equal'] is True for row in compilation['results']):
        raise ValueError('Manual projection check did not pass')
    codec_path = EVIDENCE / 'FIXCL2-codec-invariants.json'
    codec = json.loads(codec_path.read_bytes())
    if codec.get('ok') is not True or len(codec.get('checks', [])) != 10:
        raise ValueError('Codec invariant check did not pass')
    cold = proofs['cold']['latency']
    if cold['coldProcess']['n'] < 5 or cold['warmTransport']['n'] < 10:
        raise ValueError('At least five fresh process and ten warm samples required')
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl.effects import inventory
    protocol = Protocol(NeyviaToolGateway(scratch, allow_mutations=True, permission_mode='workspace'))
    current = inventory(protocol)
    previous = json.loads((EVIDENCE / 'FIXCL.json').read_bytes())
    baseline = {row['tool']: row for row in previous['coverage']['actionInventory']}
    statuses = {status: sum(row['effectStatus'] == status for row in current)
                for status in ('grounded_adapter', 'read_only', 'frontier')}
    transitions = [dict(row, before=baseline[row['tool']]['effectStatus']) for row in current
                   if row['tool'] in baseline and baseline[row['tool']]['effectStatus'] != row['effectStatus']]
    actual = witnesses(proofs)
    audit = json.loads(AUD4.read_bytes())
    # Retain original cells and distinguish actual effects from request delivery,
    # contract clients, stored jobs and unexecuted native/provider surfaces.
    boundaries = {
        0: ('authority', 'terminal', 'cold'), 2: ('cold',), 3: ('authority',),
        8: ('authority', 'renderer'), 18: ('terminal',), 20: ('documents',), 22: ('documents',),
        10: ('browser',), 21: ('browser',),
        26: ('documents',), 31: ('frontier-local',), 33: ('durable', 'frontier-local', 'sidebar'),
        30: ('coordination',), 32: ('semantic',), 29: ('work', 'creative'),
    }
    descriptions = {
        0: 'Exact Notes bytes/pin through owner HTTP and spawned MCP; real terminal completion, nonzero and drift refusal.',
        2: 'Real fresh stdio processes and retained warm goals; no claim that every new adapter was executed over MCP.',
        3: 'Authenticated owner HTTP uses the same CL host; guest, unsigned, cross-origin, scope, raw mutation and autopilot bypass refused.',
        8: 'Independent mounted file and owned-browser journeys pass against the current backend and Claude-supplied built UI. Real backend SSE frames are relayed into an EventSource stand-in; native streaming and desktop WebView2 remain unproved.',
        18: 'Actual hidden command writes exact fixture bytes once; stored result and independent task-effect drift both block completion.',
        20: 'Actual bounded local HTTP document fetch and cached passages/citations. Network fetch writes cache and remains mutation-gated.',
        22: 'Real PDF metadata/text and conservative renderer predicates; unmounted open/search refuse done. No rendered PDF positive proof.',
        26: 'Actual retained real study pack import, review, archive, preview and send; corrupt bytes refuse completion. No new model generation claimed.',
        31: 'Real session/sidebar conservation and manual quarantine, demotion, patch promotion and source/artifact integrity checks.',
        33: 'Actual dormant tasks, prerequisite graph, evidence bytes, task blocking, owner-approved nights/budgets and session/sidebar state. Live provider jobs remain frontier.',
        30: 'Exact workflow receipt and current source/request binding; this does not establish external deliverable quality.',
        32: 'Exact local semantic records, proof artifact hashes and trusted policy state. Creating a proof capsule does not establish the quality of its claim.',
        29: 'Adaptive-work, situation and attention transitions are checked against exact persisted local records and conserved event history. Attention observations are caller reports; situation plans are deterministic proposals, not model-generated quality or objective perception proof.',
        10: 'Actual installed Neyvia headless browser and local fixture controls: persisted tab identity and current DOM/state effects. Queued desktop-only browser effects are not promoted without observed completion.',
        21: 'Browser receipt coverage is limited to the exact tool/operation list and concrete runtime reported in FIXCL2-browser.json; unavailable perception/device pathways remain frontier.',
    }
    matrix = []
    for index, names in boundaries.items():
        row = audit['matrix'][index]
        matrix.append({'index': index, 'surface': row['surface'], 'owner': row['owner'],
            'before': row['cells'], 'after': {'status': 'bounded_real_run',
                'boundary': descriptions[index],
                'receipts': ['FIXCL2-' + name + '.json#/checks' for name in names]}})
    source_paths = list((REPO / 'src/grant_agent/cl').glob('*.py'))
    source_paths += [REPO / 'src/grant_agent' / name for name in (
        'neyvia_agent.py', 'native_tools.py', 'neyvia_cl.py', 'neyvia_ui_api.py',
        'neyvia_workspace_tools.py', 'ui_command_bus.py', 'neyvia_panes.py',
        'neyvia_manuals.py', 'neyvia_mcp_stdio.py', 'neyvia_impact.py',
        'manual_versions.py', 'manual_contracts.py', 'neyvia_pdf_tools.py',
        'proof_contracts.py', 'verified_operations.py', 'neyvia_gateway.py', 'semantic_missions.py')]
    source_paths += list((REPO / 'manuals/cl').glob('*.cl')) + list((REPO / 'manuals').glob('*.manual.json'))
    source_paths += [REPO / 'config/fixcl_manual_cache.json']
    for proof in proofs.values():
        for relative in proof.get('sourceHashesAtStart', proof.get('sourceHashes', {})):
            # UI source and the supplied built artifact have their own renderer
            # bindings; this byte gate covers the backend and proof programs.
            if not relative.replace('\\', '/').startswith('web/'):
                source_paths.append(REPO / relative)
    source_paths = sorted(set(source_paths))
    if compilation['manuals'] != len(list((REPO / 'manuals/cl').glob('*.cl'))):
        raise ValueError('Manual count changed after compilation')
    for row in compilation['results']:
        if hashlib.sha256(Path(row['source']).read_text(encoding='utf-8').encode()).hexdigest() != row['source_sha256']:
            raise ValueError('Manual projection source drift: ' + row['id'])
    # Bind committed raw bytes, including the checked cache manifest. A clean
    # semantic Git diff alone cannot prove these exact-byte source receipts.
    git = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=REPO,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for path in source_paths:
            relative = path.relative_to(REPO).as_posix()
            git.stdin.write(('HEAD:' + relative + '\n').encode()); git.stdin.flush()
            header = git.stdout.readline().split()
            if header[-1] == b'missing':
                raise ValueError('Uncommitted product source: ' + relative)
            committed = git.stdout.read(int(header[2])); git.stdout.read(1)
            if path.read_bytes() != committed:
                raise ValueError('Product bytes differ from committed source: ' + relative)
    finally:
        git.stdin.close(); git.wait()
    commits = subprocess.check_output(['git', 'log', '7eb28830..HEAD', '--format=%H %s'], cwd=REPO, text=True).splitlines()
    receipt = {'schema': 'neyvia.FIXCL2.v1', 'status': 'partial_with_explicit_frontiers',
        'baseline': {'head': '7eb28830', 'receiptSha256': sha(EVIDENCE / 'FIXCL.json'),
            'AUD4Sha256': sha(AUD4), 'frontierActions': 188, 'coldProcessP50Ms': 28100},
        'checks': {'allPrimaryRealRunsPassed': True, 'receiptSourceBindingsCurrent': True,
            'coldSampleCounts': True, 'manualProjectionEqual': True,
            'codecInvariantsPassed': True, 'productBytesMatchCommittedSource': True},
        'coverage': {'registeredActions': len(current), 'statuses': statuses,
            'actionInventory': current, 'changedActions': transitions,
            'newObservers': [row for row in current if row['tool'] not in baseline],
            'realEffectActionWitnesses': actual,
            'newAdaptersWithoutSuccessfulCLActionWitness': [row['tool'] for row in transitions
                if row['effectStatus'] == 'grounded_adapter' and row['tool'] not in actual],
            'boundary': 'Classification and adapter presence are distinct from successful real action journeys.'},
        'latency': {'targetMs': 3000, 'targetMetP50': cold['coldProcess']['p50Ms'] < 3000,
            'measurements': cold, 'boundary': proofs['cold']['boundary']},
        'emptyBytecodeLatency': proofs['cold-empty']['latency'],
        'bytecodeBoundary': proofs['cold'].get('bytecodeBoundary'),
        'rendererBoundary': proofs['renderer']['boundary'],
        'matrixBeforeAfter': matrix,
        'productSourceHashes': {path.relative_to(REPO).as_posix(): sha(path) for path in source_paths},
        'receipts': {name: {'sha256': sha(EVIDENCE / ('FIXCL2-' + name + '.json')),
            'checks': proofs[name]['checks']} for name in PRIMARY},
        'secondaryChecks': {'manuals': compilation['manuals'],
            'manualReceiptSha256': sha(compile_path), 'codecReceiptSha256': sha(codec_path)},
        'localCommits': commits,
        'limitations': ['Remaining frontier actions refuse before execution; no all-actions completion claim.',
            'Rendered proof uses Claude-supplied built UI with relayed real SSE frames; native EventSource and desktop WebView2 were not proved.',
            'PDF positive renderer, provider generation/jobs, native devices, remote peers and NAS effects were not executed/proved in these disposable runs.',
            'Five process samples describe this local run, not a latency SLA.'],
        'authority': {'branch': 'track/fix-cl', 'ports': list(range(48821, 48830)),
            'push': False, 'merge': False, 'NAS': False, 'savedCredentialReads': False,
            'visibleWindows': False, 'publicPromotion': False}}
    output = EVIDENCE / 'FIXCL2.json'
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'receipt': str(output), 'coverage': statuses, 'changedActions': len(transitions), 'latency': receipt['latency']}))


if __name__ == '__main__':
    main()
