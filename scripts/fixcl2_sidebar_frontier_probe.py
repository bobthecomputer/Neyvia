"""Real offline CL sidebar grouping, model drift refusal, confirm, and undo."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from fixcl_verify import environment, guards  # noqa: E402

SOURCES = (
    'src/grant_agent/neyvia_sidebar.py', 'src/grant_agent/neyvia_sidebar_semantics.py',
    'src/grant_agent/cl/frontier_local_effects.py', 'src/grant_agent/cl/frontier_effects.py',
    'src/grant_agent/cl/codecs.py', 'src/grant_agent/cl/protocol.py',
    'src/grant_agent/cl/host.py', 'src/grant_agent/cl/integration.py',
    'manuals/sidebar.manual.json', 'manuals/cl/sidebar.cl',
    'scripts/fixcl2_acquire_sidebar_model.py', 'scripts/fixcl2_sidebar_frontier_probe.py',
)
MODEL_SOURCE = REPO / '.agent_control/t7/embedding-model'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
WEIGHTS_SHA = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def hashes():
    return {name: sha(REPO / name) for name in SOURCES}


def copy_model(root):
    # This public task-local source is read before installing the proof guard;
    # its special_tokens_map filename intentionally triggers the guard outside
    # disposable state. The six copied files are verified before use.
    raw = (MODEL_SOURCE / 'receipt.json').read_bytes()
    source = json.loads(raw)
    rows = source.get('files') or []
    if source.get('id') != 'sentence-transformers/all-MiniLM-L6-v2' or source.get('revision') != REVISION:
        raise ValueError('Public model revision differs')
    if len(rows) != 6 or sum(row['size'] for row in rows) > 200_000_000:
        raise ValueError('Public model byte cap differs')
    if next((row['sha256'] for row in rows if row['file'] == 'model.safetensors'), None) != WEIGHTS_SHA:
        raise ValueError('Public weights SHA differs')
    model = root / 'model'
    model.mkdir()
    file_hashes = {}
    for row in rows:
        name = row['file']
        if Path(name).name != name or (MODEL_SOURCE / name).stat().st_size != row['size']:
            raise ValueError('Unexpected public model file')
        if sha(MODEL_SOURCE / name) != row['sha256']:
            raise ValueError('Public model file SHA differs')
        shutil.copyfile(MODEL_SOURCE / name, model / name)
        if sha(model / name) != row['sha256']:
            raise ValueError('Disposable model copy SHA differs')
        file_hashes[name] = row['sha256']
    (model / 'receipt.json').write_bytes(raw)
    return model, {'id': source['id'], 'revision': REVISION,
                   'totalBytes': sum(row['size'] for row in rows),
                   'receiptSha256': hashlib.sha256(raw).hexdigest(),
                   'fileHashes': file_hashes}


def run(root, port):
    if port not in range(48821, 48830):
        raise ValueError('Explicit FIXCL2 port required')
    root.mkdir(parents=True, exist_ok=False)
    model, model_record = copy_model(root)
    guards(root)
    environment(root, port)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    os.environ.update(NEYVIA_SIDEBAR_EMBEDDING_MODEL=str(model),
                      HF_HOME=str(root / 'hf'), HF_HUB_CACHE=str(root / 'hf/hub'),
                      HF_TOKEN_PATH=str(root / 'hf/token'), XDG_CACHE_HOME=str(root / 'cache'),
                      HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_OFFLINE='1',
                      TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_PROGRESS_BARS='1')
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    prepare_broker_fixture(root)
    start = hashes()
    from grant_agent.neyvia_conversations import NeyviaConversationStore
    from grant_agent.neyvia_workspace_tools import workspace_for
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.cl.protocol import Protocol
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.neyvia_sidebar_semantics import source_identity

    store = NeyviaConversationStore(root)
    for title, question in (
            ('Lunar geology', 'What minerals are found in lunar basalt samples?'),
            ('Moon rocks', 'How do lunar basalt samples reveal Moon geology?')):
        chat = store.create_conversation(title=title)
        store.append_turn(chat['conversationId'], role='user', content=question)
        store.append_turn(chat['conversationId'], role='assistant',
                          content='The lunar samples contain mineral evidence.')
    backend = SimpleNamespace(root=root, neyvia_mcp=SimpleNamespace(conversations=store),
                              dispatch=lambda *_: None)
    service = workspace_for(root, backend)
    bus = bus_for(root)
    ids = [row['id'] for row in service.broker().list_sessions(limit=10, observe=False)['sessions']]
    if len(ids) != 2:
        raise AssertionError('The actual conversation adapter did not expose two sessions')
    before = bus.get('sessions', {})
    folders_before = bus.get('sidebar:folders', {})
    gateway = NeyviaToolGateway(root, allow_mutations=True, permission_mode='workspace')
    actions = {}

    def cl(label, source):
        result = Protocol(gateway).run(source, action_id='FIXCL2-sidebar-' + label)
        actions[label] = {'ok': result.get('ok'), 'status': result.get('status'),
                          'reason': result.get('reason'), 'error': result.get('error'),
                          'manualUse': [row['manualUse'] for row in result.get('results', [])
                                        if row.get('manualUse')],
                          'checks': [check.get('name') for row in result.get('results', [])
                                     for check in row.get('checks', [])]}
        return result

    def previews():
        return {key: bus.get(key)['result'] for key in bus.snapshot()
                if key.startswith('sidebar:preview:') and bus.get(key)}

    preview_script = ('G local: time.now()["unixSeconds"] > 0\nsidebar.preview(ids=' +
                      json.dumps(ids) + ', threshold=0.5)\ndone()')
    initial = cl('preview-initial', preview_script)
    initial_previews = previews()
    preview = next(iter(initial_previews.values()), None)
    preview_conserved = bus.get('sessions', {}) == before and bus.get('sidebar:folders', {}) == folders_before

    config = model / 'config.json'
    original = config.read_bytes()
    config.write_bytes(original + b'\n')
    try:
        source_identity()
    except ValueError:
        drift_refused = True
    else:
        drift_refused = False
    stale = cl('confirm-drifted', 'G local: time.now()["unixSeconds"] > 0\nsidebar.confirm(previewId=' +
               json.dumps(preview['previewId']) + ', confirmed=true)\ndone()') if preview else {'ok': False}
    drift_conserved = bus.get('sessions', {}) == before
    config.write_bytes(original)
    restored_digest = source_identity()[2] if preview else None

    fresh = cl('preview-fresh', preview_script)
    new_previews = previews()
    fresh_preview = next((row for key, row in new_previews.items() if key not in initial_previews), None)
    confirmed = cl('confirm', 'G local: time.now()["unixSeconds"] > 0\nsidebar.confirm(previewId=' +
                   json.dumps(fresh_preview['previewId']) + ', confirmed=true)\ndone()') if fresh_preview else {'ok': False}
    confirm_receipt = bus.get('sidebar:preview:' + fresh_preview['previewId'], {}).get('receipt') if fresh_preview else {}
    moved = confirm_receipt.get('moved', [])
    sessions_after_confirm = bus.get('sessions', {})
    undo_id = confirm_receipt.get('undoId')
    undone = cl('undo', 'G local: time.now()["unixSeconds"] > 0\nsidebar.undo(undoId=' +
                json.dumps(undo_id) + ')\ndone()') if undo_id else {'ok': False}
    undo_receipt = bus.get('sidebar:undo:' + undo_id, {}).get('receipt') if undo_id else {}
    uses = [row['payload'] for row in bus.since(0) if row['action'] == 'cl.manual.use']
    end = hashes()
    model_end = {name: sha(model / name) for name in model_record['fileHashes']}
    receipt = {'schema': 'neyvia.FIXCL2.sidebar.v2', 'root': str(root), 'port': port,
               'auditCells': ['AUD4.json#/transcripts/cl_sidebar',
                              'AUD4.json#/transcripts/manual_validation_sidebar'],
               'sourceHashesAtStart': start, 'sourceHashesAtEnd': end,
               'model': model_record, 'modelFileHashesAtEnd': model_end,
               'actions': actions, 'sessionIds': ids, 'initialPreview': preview,
               'freshPreview': fresh_preview, 'confirmedReceipt': confirm_receipt,
               'undoReceipt': undo_receipt, 'manualUses': uses,
               'frontier': ['English semantic quality beyond fixture subjects is unmeasured',
                            'Rendered sidebar controls require separate UI acknowledgement']}
    receipt['checks'] = {
        'public_model_pinned_under_200mb': model_record['totalBytes'] == 91567205,
        'actual_conversations_observed': len(ids) == 2 and all(s.startswith('external:neyvia:') for s in ids),
        'preview_cl_completed': initial.get('ok') is True and fresh.get('ok') is True,
        'preview_grouped_subjects': bool(preview and any(set(g['ids']) == set(ids) for g in preview['groups'])),
        'preview_conserved_assignments': preview_conserved,
        'model_drift_refused_before_write': drift_refused and stale.get('ok') is False and drift_conserved,
        'model_restored_exactly': bool(preview and restored_digest == preview['model']['sourceDigest']),
        'confirm_cl_completed': confirmed.get('ok') is True and set(moved) == set(ids) and
            all(sessions_after_confirm.get(sid, {}).get('project') for sid in ids),
        'undo_cl_completed': undone.get('ok') is True and set(undo_receipt.get('restored', [])) == set(ids) and
            bus.get('sessions', {}) == before,
        'current_sidebar_manual_receipts': len([u for u in uses if u.get('manual') == 'sidebar' and
                                                 u.get('status') == 'admitted']) >= 3,
        'effect_checks_present': all(actions.get(label, {}).get('checks') for label in
                                     ('preview-initial', 'preview-fresh', 'confirm', 'undo')),
        'model_files_conserved': model_end == model_record['fileHashes'],
        'source_unchanged': start == end,
    }
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = REPO / '.agent_control/proofs' / ('FIXCL2-sidebar-' + str(time.time_ns()))
    result = run(root, args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks': result['checks'], 'output': str(args.output)}))
    sys.exit(0 if all(result['checks'].values()) else 1)
