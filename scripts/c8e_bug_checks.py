"""Confined real effects for four previously unauthored runtime procedures.

This is a journey adapter, not a provider/browser/device substitute. Each mode
calls its existing production owner, retains its actual durable output, and
refuses to reuse an already exercised root. The web worker independently reads
those files after this adapter returns.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys


MODES = ('host-runtime', 'nearby-send-runtime', 'neyvia-core', 'runtime-provider')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def host(root, folder, marker):
    from grant_agent.native_tools import NativeToolRegistry
    from grant_agent.progressive_tools import ProgressiveToolSpec, ProgressiveToolSurface
    from grant_agent.neyvia_stage_scheduler import build_progressive_step_handler, execute_neyvia_stages
    registry = NativeToolRegistry(root)
    surface = ProgressiveToolSurface()
    surface.register(ProgressiveToolSpec(name='workspace.write', description='Production workspace writer',
        input_schema=registry.describe('workspace.write')['inputSchema'],
        annotations={'readOnlyHint': False, 'requiresApproval': True}),
        handler=lambda args: registry.call('workspace.write', args))
    handler = build_progressive_step_handler(root, progressive=surface)
    refusal = handler({'step_id': 'denied', 'action': 'tool', 'tool': 'workspace.write',
        'risk': 'workspace_write', 'arguments': {'path': str(folder / 'denied.txt'), 'content': marker}}, {})
    assert not refusal['ok'] and refusal['metadata']['approval_required']
    assert not (folder / 'denied.txt').exists()
    destination = folder / 'staged.txt'
    arguments = json.dumps({'path': str(destination), 'content': marker})
    source = ('NEYVIA/1\nGOAL text="Write actual scoped artifact"\n'
        'LANE worker runtime=neyvia-native model=none effort=none permissions=write\n'
        f"STEP write lane=worker action=tool tool=workspace.write risk=workspace_write args='{arguments}'\n")
    approved = build_progressive_step_handler(root, progressive=surface, approved_mutations=True,
        approval_id='C8e-disposable-journey')
    result = execute_neyvia_stages(root, source, mission_id='c8e-real-stage', step_handler=approved)
    assert result['ok'] and result['completedStepIds'] == ['write']
    assert destination.read_text(encoding='utf-8') == marker
    durable = json.loads(Path(result['receiptPath']).read_text(encoding='utf-8'))
    assert durable['completedStepIds'] == ['write']
    save(folder / 'effect.json', {'refusedMutation': refusal, 'stageReceipt': result,
        'durableReceipt': durable, 'actualContent': destination.read_text(encoding='utf-8')})


def nearby(root, folder, marker):
    from grant_agent.nearby_send import NearbySendService
    source = folder / 'payload.txt'
    source.write_text(marker, encoding='utf-8')
    service = NearbySendService(root)
    from c8_scope import fixture_port
    plan = service.build_plan([source], recipient_endpoint=f'http://127.0.0.1:{fixture_port()}')
    payload = source.read_bytes()
    item = plan['files'][0]
    assert item['sha256'] == hashlib.sha256(payload).hexdigest()
    assert item['size'] == len(payload) and plan['summary']['totalBytes'] == len(payload)
    assert item['chunks'][0]['sha256'] == hashlib.sha256(payload).hexdigest()
    assert service._verify_planned_file(item)['sha256'] == item['sha256']
    save(folder / 'preview.json', plan)
    denied = service.send(plan, approved=False)
    assert denied['status'] == 'approval_required'
    assert not service.active_state_path.exists()
    source.write_text(marker + 'changed after preview\n', encoding='utf-8')
    try:
        service._verify_planned_file(item)
    except ValueError as error:
        assert 'Source changed after transfer preview' in str(error)
        changed_refusal = str(error)
    else:
        raise AssertionError('Changed source was accepted')
    save(folder / 'effect.json', {'preview': plan, 'actualSourceAfterChange': source.read_text(encoding='utf-8'),
        'approvalRefusal': denied, 'sourceChangeRefusal': changed_refusal,
        'boundary': 'Actual source preview and admission; no transfer or physical recipient claim'})


def core(root, folder, marker):
    from grant_agent.neyvia_application_contract import register_sdk_application, load_sdk_applications
    identity = 'c8e.' + root.name
    first = register_sdk_application(root, {'applicationId': identity, 'name': 'C8e initial', 'services': ['agents']})
    second = register_sdk_application(root, {'applicationId': identity, 'name': marker.strip(), 'services': ['memory']})
    assert first['registered'] and not first['updated'] and second['registered'] and second['updated']
    rows = [row for row in load_sdk_applications(root) if row['applicationId'] == identity]
    assert len(rows) == 1 and rows[0]['name'] == marker.strip() and rows[0]['services'] == ['agents', 'memory']
    prior = load_sdk_applications(root)
    refused = register_sdk_application(root, {'applicationId': identity + '.bad', 'services': ['not-a-service']})
    assert not refused['registered'] and load_sdk_applications(root) == prior
    save(folder / 'effect.json', {'registered': first, 'updated': second, 'readback': rows,
        'invalidManifestRefusal': refused, 'boundary': 'Real SDK registration persistence; no app launch claim'})


def runtime(root, folder, marker):
    from grant_agent.native_commands import execute_local_command
    from grant_agent.runtime_wrapper import replay_runtime_wrapper
    command = "from pathlib import Path; Path('runtime-child.txt').write_text('C8e actual hidden child output', encoding='utf-8')"
    result = execute_local_command({'shell': 'python', 'command': command, 'cwd': str(root), 'timeoutMs': 10000},
        default_cwd=root)
    assert result['ok'] and result['exitCode'] == 0
    assert (root / 'runtime-child.txt').read_text(encoding='utf-8') == 'C8e actual hidden child output'
    # Replay the real bounded execution result, not a constructed completed provider receipt.
    receipt = folder / 'execution.json'
    save(receipt, result)
    events = folder / 'events.jsonl'
    events.write_text('{malformed}\n' + json.dumps({'status': result['status'], 'message': marker,
        'childOutput': (root / 'runtime-child.txt').read_text(encoding='utf-8')}) + '\n', encoding='utf-8')
    replay = replay_runtime_wrapper(event_stream_path=events, receipt_paths=[receipt, folder / 'missing.json'])
    assert replay['receiptCount'] == 1 and replay['receipts'][0] == result
    assert replay['eventCount'] == 1 and replay['events'][0]['message'] == marker
    assert replay['latestStatus'] == 'completed'
    missing = replay_runtime_wrapper(event_stream_path=folder / 'absent-events.jsonl',
        receipt_paths=[folder / 'missing.json'])
    assert missing['receiptCount'] == 0 and missing['eventCount'] == 0 and missing['latestStatus'] != 'completed'
    save(folder / 'effect.json', {'actualChild': result, 'replay': replay, 'missingReplay': missing,
        'boundary': 'Hidden local Python child and file replay; no model/provider inference claim'})


def run(mode, root_value):
    if mode not in MODES:
        raise ValueError('Unknown C8e effect mode')
    root = Path(root_value).resolve()
    if root != Path.cwd().resolve():
        raise PermissionError('C8e effect root must be the owned subprocess cwd')
    sys.dont_write_bytecode = True
    # The child receives only the frozen candidate source selected by C8. Its
    # own hooks matter: Python audit hooks do not cross a subprocess boundary.
    source = Path(os.environ['NEYVIA_C8_SOURCE']).resolve(strict=True)
    sys.path.insert(0, str(source / 'src'))
    sys.path.insert(0, str(source / 'scripts'))
    from grant_agent.proof_credential_guard import install as guard_credentials
    from c8_scope import install as guard_scope
    guard_credentials(root)
    guard_scope(allow_children=False, writable_root=root,
        headless_driver_source=source / 'src/grant_agent/perception_browser.py')
    folder = root / 'c8e-effects' / mode
    folder.mkdir(parents=True, exist_ok=False)
    marker = f'C8e {mode} at {root}\n'
    {'host-runtime': host, 'nearby-send-runtime': nearby, 'neyvia-core': core,
        'runtime-provider': runtime}[mode](root, folder, marker)
    print(json.dumps({'mode': mode, 'effectPath': str(folder / 'effect.json'), 'marker': marker}))


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
