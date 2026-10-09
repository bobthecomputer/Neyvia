"""Actual native conversation/CPU embedding/owner HTTP grouping and undo journey."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def verify(root, port, model, receipt):
    from grant_agent.neyvia_conversations import NeyviaConversationStore
    from grant_agent.ui_command_bus import bus_for
    from grant_agent.connected_sessions.codex_items import map_thread_item
    from grant_agent.neyvia_sidebar_projection import project
    from grant_agent.neyvia_sidebar import subject_name
    root.mkdir(parents=True, exist_ok=True)
    # The proof guard deliberately refuses token-named JSON outside disposable
    # state. Stage only the known hash-pinned public model inventory, never a
    # whole directory or saved HuggingFace/provider state.
    manifest = json.loads((model / 'receipt.json').read_text(encoding='utf-8'))
    allowed = {'config.json', 'model.safetensors', 'special_tokens_map.json',
               'tokenizer.json', 'tokenizer_config.json', 'vocab.txt'}
    assert manifest['id'] == 'sentence-transformers/all-MiniLM-L6-v2'
    assert manifest['revision'] == '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
    assert manifest['bytes'] < 200_000_000
    staged = root / 'embedding-model'
    staged.mkdir()
    for ancestor in [model, *model.parents]:
        assert not ancestor.is_symlink() and not ancestor.is_junction(), ancestor
    for row in manifest['files']:
        assert row['file'] in allowed
        source = model / row['file']
        assert source.is_file() and not source.is_symlink()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row['sha256']
        shutil.copyfile(source, staged / row['file'])
        assert hashlib.sha256((staged / row['file']).read_bytes()).hexdigest() == row['sha256']
    (staged / 'receipt.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    store = NeyviaConversationStore(root)
    stamp = datetime.now(timezone.utc).isoformat()
    prompts = [
        'Design an accessible website with keyboard navigation and visible focus.',
        'Improve an accessible website with keyboard navigation and visible focus.',
        'Explain sourdough bread fermentation and how to maintain the starter.',
        'Describe sourdough bread fermentation and how to maintain the starter.',
    ]
    for index, prompt in enumerate(prompts):
        cid = f'grouping_{index}'
        store.create_conversation(conversation_id=cid, title=f'New session - {stamp} - {index}',
                                  metadata={'workspacePath': str(root)}, now=stamp)
        store.append_turn(cid, role='user', content=prompt, now=stamp)
        store.append_turn(cid, role='assistant', content='Saved owner prompt for grouping review.', now=stamp)
    env = {**os.environ, 'NEYVIA_TOOL_AUTO_UPDATE': '0', 'FLUXIO_WATCHDOG_AUTOSTART': '0',
           'NEYVIA_COORDINATOR_AUTOSTART': '0', 'FLUXIO_RUNTIME_AUTO_UPDATE': '0',
           'NEYVIA_UI_STATE_ROOT': str(root), 'NEYVIA_CONNECTED_SERVICE_PORT': str(port),
           'NEYVIA_SIDEBAR_EMBEDDING_MODEL': str(staged),
           'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
           'NEYVIA_SIDEBAR_ALLOWED_ROOTS': json.dumps([str(root)]),
           'SYNTELOS_ACCOUNT_USERNAME': 'fixb-grouping',
           'SYNTELOS_ACCOUNT_PASSWORD': 'disposable-grouping-fixture'}
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f'http://127.0.0.1:{port}'
    evidence = {'schema': 'neyvia.FIXb.sidebar-grouping.v1', 'at': stamp,
                'root': str(root), 'port': port, 'checks': [], 'modelPath': str(staged),
                'publicModelStaging': {'source': str(model), 'manifest': manifest,
                                       'guardUnchanged': True, 'downloadBytes': 0}}

    def request(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'})
        with opener.open(req, timeout=180) as response:
            value = json.load(response)
        return value.get('data', value)

    def sidebar(op, args=None):
        return request('/api/ui/sidebar', {'command': f'sidebar_{op}_command', **(args or {})})

    def record(name, **data):
        evidence['checks'].append({'name': name, 'passed': True, **data})
        print('PASS ' + name, flush=True)

    with (root / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve',
                                   '--root', str(root), '--port', str(port), '--model', str(model)], cwd=REPO, env=env,
                                  stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 90
            while True:
                try:
                    assert request('/api/health')['ok']
                    break
                except OSError:
                    assert server.poll() is None, 'Owned backend exited'
                    assert time.monotonic() < deadline, 'Owned backend not ready'
                    time.sleep(.2)
            request('/api/auth/local-session', {})
            initial = sidebar('state', {'limit': 50})
            ids = [row['id'] for row in initial['sessions'] if row['id'].rsplit(':', 1)[-1].startswith('grouping_')]
            assert len(ids) == 4, initial
            before = bus_for(root).get('sessions', {})
            preview = sidebar('preview', {'ids': ids})
            assert preview['ok'] and preview['status'] == 'preview', preview
            assert len(preview['groups']) == 2, preview
            names = {group['name'] for group in preview['groups']}
            assert names == {'Keyboard navigation', 'Sourdough bread fermentation'}, preview
            assert bus_for(root).get('sessions', {}) == before
            record('Real local embedding preview names two subjects from shared prompts and moves nothing', preview=preview)
            retry = sidebar('preview', {'ids': list(reversed(ids))})
            assert {group['name'] for group in retry['groups']} == names
            record('Changing conversation order does not change group names', preview=retry)
            refused = sidebar('confirm', {'previewId': preview['previewId']})
            assert refused['status'] == 'confirmation_required'
            assert bus_for(root).get('sessions', {}) == before
            record('Unconfirmed preview refuses every move', receipt=refused)
            confirmed = sidebar('confirm', {'previewId': preview['previewId'], 'confirmed': True})
            assert confirmed['status'] == 'completed' and len(confirmed['moved']) == 4
            observed = sidebar('state', {'ids': ids})
            assert {folder['name'] for folder in observed['subjectFolders']} == names, observed
            assert all(row['projectOverride']['name'] in names for row in observed['sessions'])
            replayed = sidebar('confirm', {'previewId': preview['previewId'], 'confirmed': True})
            assert replayed['replayed'] and replayed['moved'] == confirmed['moved']
            record('Explicit owner confirmation persists subject names and idempotent receipt', receipt=confirmed, observed=observed)
            undone = sidebar('undo', {'undoId': confirmed['undoId']})
            assert len(undone['restored']) == 4
            restored = sidebar('state', {'ids': ids})
            assert not restored['subjectFolders'] and all(row.get('projectOverride') is None for row in restored['sessions'])
            record('Undo restores prior assignments and removes empty named subject folders', receipt=undone)
            assert subject_name([{'subject': 'hello'}, {'subject': 'bonjour'}]) == 'Related conversations'
            assert subject_name([{'subject': 'Create 2026 111'}, {'subject': 'Review 2026 111'}]) == 'Related conversations'
            record('No shared informative phrase gives honest generic label; dates/request verbs cannot name subjects')
            missing = subprocess.run([sys.executable, '-c',
                "import json;from grant_agent.neyvia_sidebar_semantics import encode;"
                "\ntry:encode(None,['ordinary subject']);raise AssertionError('Missing model accepted')"
                "\nexcept FileNotFoundError:print(json.dumps({'ok':True,'status':'model_unavailable'}))"],
                cwd=REPO, env={**env, 'PYTHONPATH': str(REPO / 'src'),
                               'NEYVIA_SIDEBAR_EMBEDDING_MODEL': str(root / 'absent-model')},
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            assert missing.returncode == 0, missing.stderr
            record('Absent local model refuses explicitly without downloading or substituting embeddings', observed=json.loads(missing.stdout))
            lifecycle = []
            for index, (activity, expected) in enumerate([('started', 'running'), ('completed', 'ok'),
                                                        ('failed', 'error'), ('interrupted', 'interrupted')]):
                item = {'type': 'subAgentActivity', 'id': f'fixture-{index}', 'kind': activity,
                        'agentThreadId': 'controlled-child', 'agentPath': '/root/controlled-child'}
                mapped = map_thread_item(item, seq=index, at=stamp)
                projection = project({'app': 'codex'}, {'items': [entry.public() for entry in mapped]})
                assert projection['agents'][0]['status'] == expected, projection
                lifecycle.append({'activity': activity, 'expected': expected, 'observed': projection['agents']})
            record('Existing production Codex mapper and sidebar observer retain four explicit lifecycle states', controlledFixtures=lifecycle)
            evidence['passed'] = True
            evidence['ok'] = True
        except BaseException as exc:
            evidence['passed'] = False
            evidence['ok'] = False
            evidence['error'] = str(exc)
            raise
        finally:
            server.terminate()
            server.wait(timeout=20)
            evidence['ownedServerStopped'] = server.poll() is not None
            evidence['sourceHashes'] = {str(path.relative_to(REPO)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in [REPO / 'src/grant_agent/neyvia_sidebar.py', REPO / 'manuals/cl/sidebar.cl',
                                                     REPO / 'src/grant_agent/connected_sessions/codex_items.py',
                                                     REPO / 'src/grant_agent/neyvia_sidebar_semantics.py',
                                                     REPO / 'src/grant_agent/neyvia_sidebar_projection.py']}
            evidence['boundary'] = 'Real durable native owner conversations, verified pinned local CPU embeddings and authenticated production sidebar HTTP. Codex lifecycle cases are controlled canonical fixtures; prior real T7 receipt already proves completed child. No live-history/provider/UI/physical or model-quality claim.'
            evidence['sources'] = evidence['sourceHashes']
            evidence['limitations'] = [evidence['boundary'], 'Shared-phrase labels name embedding-confirmed clusters; they do not replace semantic similarity and may remain Related conversations when paraphrases share no informative phrase.']
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, default=REPO / 'scripts/evidence/FIXb-sidebar-grouping.json')
    args = parser.parse_args()
    assert args.port in range(48661, 48670)
    assert args.root.resolve().is_relative_to(REPO / '.agent_control')
    if args.serve:
        from verify_fix_sidebar import serve
        serve(args.root.resolve(), args.port)
    else:
        verify(args.root.resolve(), args.port, args.model.resolve(), args.receipt.resolve())
