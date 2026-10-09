"""Pinned local embeddings and real stored-user-transcript sidebar journeys."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / '.agent_control/proofs/C8/c8e-embedding'
MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
MAX_BYTES = 200_000_000
FILES = {
    'config.json': (612, '72b987fd805cfa2b58c4c8c952b274a11bfd5a00'),
    'model.safetensors': (90_868_376, '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'),
    'special_tokens_map.json': (112, 'e7b0375001f109a6b8873d756ad4f7bbb15fbaa5'),
    'tokenizer.json': (466_247, 'cb202bfe2e3c98645018a6d12f182a434c9d3e02'),
    'tokenizer_config.json': (350, 'c79f2b6a0cea6f4b564fed1938984bace9d30ff0'),
    'vocab.txt': (231_508, 'fb140275c155a9c7c5a3b3e0e77a9e839594a938'),
}
PROMPTS = [
    ('Tomato garden beds', 'Plan growing tomatoes in raised garden beds. Explain soil watering and summer vegetable harvest.'),
    ('Tomato garden watering', 'Growing tomatoes in raised garden beds needs soil watering and a summer vegetable harvest plan.'),
    ('Planet telescope observations', 'Observe Saturn rings and Jupiter moons through a telescope. Plan clear night astronomy observations.'),
    ('Planet astronomy telescope', 'Plan clear night astronomy observations of Saturn rings and Jupiter moons through a telescope.'),
]


def _allowed(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and not parsed.username and not parsed.password and (
        host == 'huggingface.co' or host.endswith('.huggingface.co') or host.endswith('.hf.co'))


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not _allowed(newurl):
            raise PermissionError('Pinned public model download redirected outside Hugging Face delivery hosts')
        redirected = super().redirect_request(request, fp, code, message, headers, newurl)
        if redirected is not None:
            redirected.remove_header('Authorization')
            redirected.remove_header('Cookie')
        return redirected


def _validate(name, content):
    size, expected = FILES[name]
    if len(content) != size:
        raise ValueError('Pinned model file size mismatch: ' + name)
    sha256 = hashlib.sha256(content).hexdigest()
    digest = sha256 if name.endswith('.safetensors') else hashlib.sha1(
        b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    if digest != expected:
        raise ValueError('Pinned model file digest mismatch: ' + name)
    return sha256


def download():
    """Only six fixed public files; bounded before and during every transfer."""
    target = MODEL_ROOT.resolve()
    target.relative_to(ROOT / '.agent_control/proofs/C8')
    expected_total = sum(size for size, _ in FILES.values())
    if expected_total > MAX_BYTES:
        raise ValueError('Public model exceeds the authorized 200 MB total')
    target.mkdir(parents=True, exist_ok=True)
    client = build_opener(ProxyHandler({}), PublicRedirects())
    rows, actual_total = [], 0
    for name, (size, pinned) in FILES.items():
        path = target / name
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
        started = time.monotonic()
        if path.exists():
            content = path.read_bytes()
        else:
            request = Request(url, headers={'User-Agent': 'Neyvia-C8e-public-model-fixture/1'})
            with client.open(request, timeout=60) as response:
                declared = response.headers.get('Content-Length')
                if declared is not None and (int(declared) != size or actual_total + int(declared) > MAX_BYTES):
                    raise ValueError('Unexpected declared model transfer size; stopped before download')
                chunks, length = [], 0
                while chunk := response.read(min(1024 * 1024, size - length + 1)):
                    length += len(chunk)
                    if length > size or actual_total + length > MAX_BYTES:
                        raise ValueError('Model transfer exceeded pinned size or authorization')
                    chunks.append(chunk)
                content = b''.join(chunks)
            _validate(name, content)
            with path.open('xb') as stream:
                stream.write(content)
        sha256 = _validate(name, content)
        actual_total += len(content)
        rows.append({'file': name, 'source': url, 'revision': REVISION, 'size': len(content),
                     'sha256': sha256, 'pinnedDigest': pinned, 'elapsedMs': round((time.monotonic() - started) * 1000)})
        print(json.dumps({'file': name, 'verifiedBytes': len(content)}), flush=True)
    receipt = {'schema': 'neyvia.c8e.embedding-model.v1', 'id': MODEL_ID, 'revision': REVISION,
               'modelCard': f'https://huggingface.co/{MODEL_ID}', 'totalBytes': actual_total,
               'downloadLimit': MAX_BYTES, 'createdAt': datetime.now(timezone.utc).isoformat(),
               'authority': 'Public unauthenticated pinned downloads; no accounts, credential files, install, or remote code',
               'files': rows}
    (target / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def install_backend(broker, backend):
    """Attach only the real product adapter to this already isolated broker."""
    from grant_agent.connected_sessions.neyvia import create_adapter
    broker.register_adapter('neyvia', lambda _backend: create_adapter(backend))


def apply(bindings):
    additions = json.loads((ROOT / 'config/inception_c8e_sidebar.json').read_text(encoding='utf-8'))['bindings']
    result = copy.deepcopy(bindings)
    for identity, values in additions.items():
        result[identity].update(copy.deepcopy(values))
    return result


def _seed(worker, prompts=PROMPTS):
    records = []
    for title, prompt in prompts:
        created = worker.tool('backend:create_neyvia_conversation_command', {'kind': 'chat', 'title': title, 'titleMode': 'off'})
        cid = created['conversationId']
        worker.tool('backend:append_neyvia_conversation_turn_command',
                    {'conversationId': cid, 'role': 'user', 'content': prompt, 'source': 'C8e-authored-user-fixture'})
        records.append({'conversationId': cid, 'title': title, 'prompt': prompt})
    deadline = time.monotonic() + 15
    while True:
        listed = worker.tool('backend:connected_sessions_list_command', {'app': 'neyvia', 'limit': 100, 'includeHarness': False})
        rows = listed.get('sessions', [])
        if all(sum(row.get('id', '').endswith(':' + record['conversationId']) for row in rows) == 1 for record in records):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Real Neyvia transcript adapter did not list every fresh stored conversation before deadline')
        worker.page.wait_for_timeout(250)
    for record in records:
        matched = [row for row in rows if row.get('id', '').endswith(':' + record['conversationId'])]
        if len(matched) != 1:
            raise RuntimeError('Real Neyvia transcript adapter did not return exactly one stored conversation')
        record['id'] = matched[0]['id']
    return records


def _state(worker, ids):
    state = worker.tool('neyvia.sidebar.state', {'ids': ids})
    if state.get('errors') or {row['id'] for row in state['sessions']} != set(ids):
        raise RuntimeError('Fresh sidebar observation did not read every requested genuine transcript')
    return {row['id']: row for row in state['sessions']}


def _assignments(state):
    return {identity: {'present': 'project' in row, 'value': row.get('project')}
            for identity, row in state.items()}


def _groups(preview, ids):
    groups = preview.get('groups', [])
    expected = {frozenset(ids[:2]), frozenset(ids[2:])}
    observed = {frozenset(row['ids']) for row in groups}
    if len(groups) != 2 or observed != expected:
        raise RuntimeError('Real sentence embeddings did not separate both authored topic pairs: ' + json.dumps(groups))
    if preview.get('skipped') or any(group['confidence'] < .5 for group in groups):
        raise RuntimeError('Transcript fixtures were skipped or grouping fell below the production threshold')
    return {identity: group['target']['id'] for group in groups for identity in group['ids']}


def prepare(worker, binding, inputs, root):
    if not binding.get('c8eSidebar'):
        return
    records = _seed(worker)
    ids = [row['id'] for row in records]
    before = _state(worker, ids)
    context = {'records': records, 'ids': ids, 'before': _assignments(before)}
    procedure = binding['id'].rsplit('/', 1)[1]
    if procedure == 'preview-subjects':
        inputs['ids'] = ids
    else:
        preview = worker.tool('neyvia.sidebar.preview', {'ids': ids})
        context.update(preview=preview, targets=_groups(preview, ids))
        if procedure == 'confirm-preview':
            inputs['previewId'] = preview['previewId']
        elif procedure == 'undo-grouping':
            confirmed = worker.tool('neyvia.sidebar.confirm', {'previewId': preview['previewId'], 'confirmed': True})
            if set(confirmed['moved']) != set(ids) or not confirmed.get('undoId'):
                raise RuntimeError('Actual fixture grouping did not return all moves and an undo identity')
            context['confirmed'] = confirmed
            # A later explicit user move must survive the reviewed undo.
            worker.tool('neyvia.session.move', {'id': ids[0], 'project': None})
            context['laterMove'] = _assignments(_state(worker, ids))[ids[0]]
            inputs['undoId'] = confirmed['undoId']
    worker.step_results['c8eSidebarPrerequisite'] = context


def _stale_refusal(worker, context):
    extras = _seed(worker, PROMPTS[:2])
    ids = [row['id'] for row in extras]
    preview = worker.tool('neyvia.sidebar.preview', {'ids': ids})
    if not preview['groups']:
        raise RuntimeError('Stale-preview challenge had no actual semantic group')
    before = _assignments(_state(worker, ids))
    worker.tool('backend:append_neyvia_conversation_turn_command',
                {'conversationId': extras[0]['conversationId'], 'role': 'user',
                 'content': 'A fresh change to the watering plan invalidates the old reviewed preview.', 'source': 'C8e-stale-preview-challenge'})
    try:
        response = worker.tool('neyvia.sidebar.confirm', {'previewId': preview['previewId'], 'confirmed': True})
    except Exception:
        raw = worker.calls[-1]['body'].get('data', {})
        response = raw.get('result', raw)
    if response.get('status') != 'stale_preview' or response.get('moved'):
        raise RuntimeError('Changed user transcript did not refuse the stale semantic preview')
    if _assignments(_state(worker, ids)) != before:
        raise RuntimeError('Stale semantic preview changed assignments')
    return {'returnedStatus': response['status'], 'conflicts': response['conflicts'],
            'assignmentsBefore': before, 'assignmentsAfter': _assignments(_state(worker, ids))}


def check(worker, binding, inputs, root):
    if not binding.get('c8eSidebar'):
        return None
    context = worker.step_results['c8eSidebarPrerequisite']
    ids = context['ids']
    procedure = binding['id'].rsplit('/', 1)[1]
    state = _state(worker, ids)
    assignments = _assignments(state)
    details = {'fixtureRecords': context['records'], 'assignmentsBefore': context['before'], 'assignmentsAfter': assignments}
    if procedure == 'preview-subjects':
        preview = worker.step_results['preview']
        details['targets'] = _groups(preview, ids)
        if assignments != context['before']:
            raise RuntimeError('Semantic preview moved a genuine conversation')
    elif procedure == 'confirm-preview':
        receipt = worker.step_results['receipt']
        if set(receipt.get('moved', [])) != set(ids) or receipt.get('conflicts'):
            raise RuntimeError('Confirm did not move exactly the reviewed genuine conversations')
        if any(assignments[identity]['value'] != context['targets'][identity] for identity in ids):
            raise RuntimeError('Fresh sidebar state does not reflect confirmed topic folders')
        replay = worker.tool('neyvia.sidebar.confirm', {'previewId': inputs['previewId'], 'confirmed': True})
        if not replay.get('replayed') or replay.get('undoId') != receipt.get('undoId') or replay.get('moved') != receipt.get('moved'):
            raise RuntimeError('Same semantic confirmation did not replay exactly once')
        details['idempotentConfirmation'] = replay
    else:
        receipt = worker.step_results['receipt']
        if set(receipt.get('restored', [])) != set(ids[1:]) or {row['id'] for row in receipt.get('conflicts', [])} != {ids[0]}:
            raise RuntimeError('Undo failed to restore untouched conversations or preserve the later explicit move')
        if assignments[ids[0]] != context['laterMove'] or any(assignments[identity] != context['before'][identity] for identity in ids[1:]):
            raise RuntimeError('Fresh sidebar state differs from expected restore/later-move preservation')
        replay = worker.tool('neyvia.sidebar.undo', {'undoId': inputs['undoId']})
        if not replay.get('replayed') or replay['restored'] != receipt['restored']:
            raise RuntimeError('Same semantic undo did not replay its exact retained effect')
        details['idempotentUndo'] = replay
    details['stalePreviewRefusal'] = _stale_refusal(worker, context)
    if _assignments(_state(worker, ids)) != assignments:
        raise RuntimeError('Confirmation/undo replay or stale challenge changed retained assignments')
    return {'id': 'c8e-semantic-sidebar-effect', 'passed': True, 'fresh': True, 'observed': details,
            'boundary': 'Actual local MiniLM CPU embeddings and production conversation/assignment storage through authenticated product routes'}


def probe():
    """Exercise the existing encoder without creating any service or provider."""
    sys.path[:0] = [str(ROOT / 'src'), 'C:/Users/user/Projects/dictation-workbench-recovery-20260825/.venv/Lib/site-packages']
    os.environ.update(NEYVIA_SIDEBAR_EMBEDDING_MODEL=str(MODEL_ROOT), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HOME=str(MODEL_ROOT / 'hf-cache'), TORCH_HOME=str(MODEL_ROOT / 'torch-cache'))
    temporary = MODEL_ROOT / 'temp'
    temporary.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temporary), TMP=str(temporary))
    from grant_agent.neyvia_sidebar_semantics import encode, similarity
    vectors, model = encode(None, [title + '\n' + text.split('.', 1)[0] + '.' for title, text in PROMPTS])
    matrix = [[similarity(first, second) for second in vectors] for first in vectors]
    if len(vectors) != 4 or any(len(vector) != 384 for vector in vectors) or matrix[0][1] < .5 or matrix[2][3] < .5 or max(matrix[0][2], matrix[0][3], matrix[1][2], matrix[1][3]) >= .5:
        raise RuntimeError('Actual local embeddings failed the intended two-topic separation: ' + json.dumps(matrix))
    result = {'model': model, 'dimensions': [len(vector) for vector in vectors], 'similarity': matrix, 'passed': True}
    (MODEL_ROOT / 'encoder-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['download', 'probe'])
    args = parser.parse_args()
    result = download() if args.action == 'download' else probe()
    print(json.dumps({key: result[key] for key in result if key != 'files'}), flush=True)
