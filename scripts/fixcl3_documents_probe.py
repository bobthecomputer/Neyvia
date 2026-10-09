"""Run actual PDF/Scroll owner actions and fresh document effect predicates."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


SOURCE_FILES = (
    'scripts/fixcl3_documents_probe.py',
    'src/grant_agent/cl/document_effects.py', 'src/grant_agent/cl/pdf_effects.py',
    'src/grant_agent/cl/scroll_effects.py', 'src/grant_agent/cl/frontier_effects.py',
    'src/grant_agent/cl/codecs.py', 'src/grant_agent/native_tools.py',
    'src/grant_agent/neyvia_pdf_tools.py', 'src/grant_agent/neyvia_scroll.py',
    'manuals/pdf.manual.json', 'manuals/cl/pdf.cl',
    'manuals/scroll-generator.manual.json', 'manuals/cl/scroll-generator.cl',
    'manuals/tools-depth.manual.json', 'manuals/cl/tools-depth.cl',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port != 48829:
        parser.error('Document probe owns only port 48829')
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL3-documents-' + str(time.time_ns()))
    root.mkdir(parents=True)
    os.environ.update(NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0',
                      NEYVIA_COORDINATOR_AUTOSTART='0', NEYVIA_UI_BACKEND_URL=f'http://127.0.0.1:{args.port}')
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.neyvia_scroll import store, load
    from grant_agent.cl import document_effects as effects
    from grant_agent.cl.protocol import Protocol

    prepare_broker_fixture(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL3-documents', permission_mode='workspace')
    protocol = Protocol(gateway)
    proof = {'schema': 'neyvia.FIXCL3.documents.v1', 'root': str(root), 'port': args.port,
             'auditCells': ['AUD4.json#/transcripts/cl_pdf',
                            'AUD4.json#/transcripts/manual_validation_pdf',
                            'AUD4.json#/transcripts/manual_validation_scroll-generator',
                            'AUD4.json#/transcripts/manual_validation_tools-depth',
                            'AUD4.json#/transcripts/manual_validation_perception'],
             'checks': {}, 'actions': [], 'frontier': []}
    proof['sourceHashesAtStart'] = {name: digest(REPO / name) for name in SOURCE_FILES}

    action_number = 0
    def call(name, arguments):
        nonlocal action_number
        action_number += 1
        result = unwrap(protocol.action_output(name, gateway.call_native(
            name, arguments, action_id=f'fixcl2-doc-{action_number}')))
        proof['actions'].append({'tool': name, 'args': arguments, 'ok': result.get('ok') is not False})
        if result.get('ok') is False:
            raise AssertionError(f'{name}: {result}')
        return result

    study = root / 'study-notes.md'
    study.write_bytes((REPO / 'scripts/evidence/A3B-runs/raw/study-notes.md').read_bytes())
    imported = {'paths': [str(study)], 'packId': 'doc-probe', 'title': 'Study notes', 'subject': 'learning'}
    before = effects.snapshot_for(protocol, 'neyvia.scroll.import', imported)
    result = call('neyvia.scroll.import', imported)
    proof['checks']['scroll_import_effect'] = effects.checks_for(protocol, 'neyvia.scroll.import', imported)[0]['check'](imported, result, before)
    proof['checks']['scroll_import_false_result_refused'] = not effects.checks_for(protocol, 'neyvia.scroll.import', imported)[0]['check'](imported, {'pack': {'meta': {'id': 'wrong'}}}, before)
    repeat_before = effects.snapshot_for(protocol, 'neyvia.scroll.import', imported)
    replay = call('neyvia.scroll.import', imported)
    proof['checks']['scroll_import_replay_bound'] = effects.checks_for(protocol, 'neyvia.scroll.import', imported)[0]['check'](imported, replay, repeat_before)
    proof['checks']['scroll_import_source_hash'] = load(root, 'doc-probe')['sources']['records'][0]['sha256'] == digest(study)
    cl_import = Protocol(gateway).run(
        'G effect: scroll.state()["packs"][0]["id"] == "cl-probe"\n'
        + 'scroll.import(paths=' + json.dumps([str(study)]) + ',packId="cl-probe")\n'
        + 'done()', action_id='fixcl2-cl-import')
    proof['checks']['scroll_cl_import_and_done'] = cl_import.get('ok') is True and load(root, 'cl-probe')['sources']['records'][0]['sha256'] == digest(study)
    proof['actions'].append({'tool': 'neyvia.cl', 'case': 'scroll.import', 'ok': cl_import.get('ok'), 'status': cl_import.get('status'), 'text': cl_import.get('text', '')[-1000:]})

    # Reuse an archived real Luna-generated study pack as a disposable fixture.
    # Only its original source path is rebound to the local, byte-identical copy.
    archived = REPO / 'scripts/evidence/A3B-runs/raw'
    source_db = sqlite3.connect(archived / 'scroll-state.sqlite3')
    source_db.row_factory = sqlite3.Row
    original = source_db.execute('SELECT * FROM packs WHERE id=?', ('learning-notes',)).fetchone()
    finished_job = source_db.execute("SELECT * FROM jobs WHERE pack=? AND state='completed' LIMIT 1", ('learning-notes',)).fetchone()
    source_db.close()
    assert original is not None and finished_job is not None
    prior = dict(original)
    value, sources = json.loads(prior['value']), json.loads(prior['sources'])
    old_source = sources['records'][0]
    assert old_source['sha256'] == digest(study)
    for record in sources['records']:
        record['path'] = str(study)
    for record in value['sources']:
        record['path'] = str(study)
    with store(root) as (db, _):
        db.execute('INSERT INTO packs VALUES(?,?,?,?,?,?)',
                   (prior['id'], json.dumps(value, ensure_ascii=False), json.dumps(sources, ensure_ascii=False),
                    prior['review'], prior['updated'], prior['revision']))
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)', tuple(finished_job))
    proof['fixture'] = {'origin': 'A3B-runs/raw real generated pack', 'pack': prior['id'],
                        'cards': len(value['cards']), 'sourceSha256': digest(study)}
    from grant_agent.neyvia_scroll import validate
    proof['checks']['archived_real_pack_valid'] = validate(root, load(root, 'learning-notes'))['ok']
    stat_before = load(root, 'learning-notes')['revision']
    cl_stats = Protocol(gateway).run('scroll.stats(pack="learning-notes")', action_id='fixcl2-read-scroll-stats')
    cl_job = Protocol(gateway).run('scroll.job(requestId=' + json.dumps(finished_job['id']) + ')', action_id='fixcl2-read-scroll-job')
    proof['checks']['scroll_stats_typed_read'] = cl_stats.get('ok') is True and 'E ' in cl_stats.get('text', '')
    proof['checks']['scroll_job_typed_read'] = cl_job.get('ok') is True and 'E ' in cl_job.get('text', '')
    proof['checks']['scroll_reads_preserve_revision'] = load(root, 'learning-notes')['revision'] == stat_before
    approved = next(card for card in value['cards'] if json.loads(prior['review'])[card['id']]['status'] == 'approved')
    review_args = {'pack': 'learning-notes', 'decisions': [{'cardId': approved['id'], 'action': 'approve'}]}
    before = effects.snapshot_for(protocol, 'neyvia.scroll.review', review_args)
    reviewed = call('neyvia.scroll.review', review_args)
    proof['checks']['scroll_review_effect'] = effects.checks_for(protocol, 'neyvia.scroll.review', review_args)[0]['check'](review_args, reviewed, before)
    wrong_review = {'pack': 'learning-notes', 'decisions': [{'cardId': 'never-generated-card', 'action': 'approve'}]}
    proof['checks']['scroll_review_wrong_subject_refused'] = not effects.checks_for(protocol, 'neyvia.scroll.review', wrong_review)[0]['check'](wrong_review, reviewed, before)

    pack_args = {'pack': 'learning-notes'}
    before = effects.snapshot_for(protocol, 'neyvia.scroll.pack', pack_args)
    packed = call('neyvia.scroll.pack', pack_args)
    proof['checks']['scroll_pack_effect'] = effects.checks_for(protocol, 'neyvia.scroll.pack', pack_args)[0]['check'](pack_args, packed, before)
    proof['checks']['scroll_pack_archive_hash'] = packed.get('sha256') == digest(Path(packed['path'])) if packed.get('path') else False
    cl_pack = Protocol(gateway).run(
        'G effect: scroll.state(pack="learning-notes")["active"]["id"] == "learning-notes"\n'
        'scroll.pack(pack="learning-notes")\n'
        'done()', action_id='fixcl2-cl-pack')
    proof['checks']['scroll_cl_pack_and_done'] = cl_pack.get('ok') is True and cl_pack.get('status') == 'ok' and Path(packed['path']).is_file()
    proof['actions'].append({'tool': 'neyvia.cl', 'case': 'scroll.pack', 'ok': cl_pack.get('ok'), 'status': cl_pack.get('status'), 'text': cl_pack.get('text', '')[-1000:]})

    before = effects.snapshot_for(protocol, 'neyvia.scroll.preview', pack_args)
    previewed = call('neyvia.scroll.preview', pack_args)
    proof['checks']['scroll_preview_effect'] = effects.checks_for(protocol, 'neyvia.scroll.preview', pack_args)[0]['check'](pack_args, previewed, before)
    proof['checks']['scroll_preview_has_url'] = bool(previewed['preview']['url'])

    before = effects.snapshot_for(protocol, 'neyvia.scroll.send', pack_args)
    sent = call('neyvia.scroll.send', pack_args)
    proof['checks']['scroll_send_effect'] = effects.checks_for(protocol, 'neyvia.scroll.send', pack_args)[0]['check'](pack_args, sent, before)
    proof['actions'][-1]['url'] = '<one-time-capability-redacted>'
    archive_path = Path(before['archive']['path'])
    original_archive = archive_path.read_bytes()
    try:
        archive_path.write_bytes(b'corrupted disposable archive')
        proof['checks']['scroll_corrupt_archive_refused'] = not effects.checks_for(
            protocol, 'neyvia.scroll.send', pack_args)[0]['check'](pack_args, sent, before)
    finally:
        archive_path.write_bytes(original_archive)

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'<html><title>Local study source</title><body><main>Recall follows spaced practice. The source is local.</main></body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, format, *arguments):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), SourceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fetched = call('web.fetch', {'url': f'http://127.0.0.1:{args.port}/study', 'maxChars': 2000})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    document = fetched['document']
    from grant_agent.web_documents import WebDocuments
    web_store = WebDocuments(root)
    cached_before = web_store.get(document)
    passage = Protocol(gateway).run('web.passages(document=' + json.dumps(document)
        + ',query="spaced practice")', action_id='fixcl2-read-web-passages')
    citation = Protocol(gateway).run('web.cite(document=' + json.dumps(document)
        + ',start=0,end=20)', action_id='fixcl2-read-web-cite')
    proof['actions'].extend((
        {'tool': 'neyvia.cl', 'case': 'web.passages', 'ok': passage.get('ok'), 'status': passage.get('status'), 'text': passage.get('text', '')[-900:]},
        {'tool': 'neyvia.cl', 'case': 'web.cite', 'ok': citation.get('ok'), 'status': citation.get('status'), 'text': citation.get('text', '')[-900:]},
    ))
    proof['checks']['web_local_http_fetch_real'] = fetched['contentSha256'] and fetched['textSha256'] and 'spaced practice' in fetched['text']
    proof['checks']['web_passages_typed_read'] = passage.get('ok') is True and 'E ' in passage.get('text', '')
    proof['checks']['web_cite_typed_read'] = citation.get('ok') is True and 'E ' in citation.get('text', '')
    proof['checks']['web_cached_source_unchanged'] = web_store.get(document) == cached_before
    proof['checks']['exact_readonly_classification'] = all(effects.readonly(name, {}) is True for name in
        ('neyvia.pdf.extract_text', 'neyvia.scroll.job', 'neyvia.scroll.stats', 'web.passages', 'web.cite'))
    proof['checks']['write_actions_not_readonly'] = (all(effects.readonly(name, {}) is None for name in
        ('web.fetch', 'video.digest')) and effects.readonly('neyvia.pdf.search', {}) is False)

    # A fresh renderer report is absent in this headless owner probe. A PDF
    # command must fail its effect predicate rather than treating its event as proof.
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)
    pdf = root / 'sample.pdf'
    shutil.copyfile(REPO / 'web/public/tour/sample-notes.pdf', pdf)
    pdf_args = {'source': str(pdf), 'page': 1}
    before = effects.snapshot_for(protocol, 'neyvia.pdf.open', pdf_args)
    opened = call('neyvia.pdf.open', pdf_args)
    proof['checks']['pdf_real_metadata'] = opened.get('pages', 0) >= 1
    extracted = call('neyvia.pdf.extract_text', {'page': 1})
    proof['checks']['pdf_real_text_extracted'] = bool(extracted.get('text')) and extracted.get('page') == 1
    cl_extract = Protocol(gateway).run('pdf.extract_text(page=1)', action_id='fixcl2-read-pdf-text')
    proof['checks']['pdf_extract_typed_read'] = cl_extract.get('ok') is True and 'E ' in cl_extract.get('text', '')
    proof['checks']['pdf_unrendered_effect_refused'] = not effects.checks_for(protocol, 'neyvia.pdf.open', pdf_args)[0]['check'](pdf_args, opened, before)
    proof['checks']['pdf_source_conserved'] = effects.snapshot_for(protocol, 'neyvia.pdf.open', pdf_args)['source']['sha256'] == before['source']['sha256']
    highlight_args = {'page': 1, 'rects': [[1, 1, 10, 10]]}
    highlight_checks = effects.checks_for(protocol, 'neyvia.pdf.highlight', highlight_args)
    proof['checks']['pdf_rectangles_adapter_refuses_unmounted'] = bool(highlight_checks) and all(
        row['check'](highlight_args, opened, before) is False for row in highlight_checks if row.get('effect'))
    cl_pdf = Protocol(gateway).run('G effect: pdf.state()["requested"]["source"] == '
        + json.dumps(str(pdf)) + '\npdf.goto(page=1)\ndone()', action_id='fixcl2-cl-pdf-unmounted')
    proof['checks']['pdf_cl_unmounted_refused'] = cl_pdf.get('ok') is False and cl_pdf.get('status') != 'ok'
    proof['actions'].append({'tool': 'neyvia.cl', 'case': 'pdf.goto-unmounted', 'ok': cl_pdf.get('ok'), 'status': cl_pdf.get('status'), 'text': cl_pdf.get('text', '')[-1000:]})
    cl_search = Protocol(gateway).run('G effect: pdf.state()["requested"]["source"] == '
        + json.dumps(str(pdf)) + '\npdf.search(query="Notes")\ndone()', action_id='fixcl2-cl-pdf-search-unmounted')
    proof['checks']['pdf_search_cl_unmounted_refused'] = cl_search.get('ok') is False and cl_search.get('status') != 'ok'
    proof['actions'].append({'tool': 'neyvia.cl', 'case': 'pdf.search-unmounted', 'ok': cl_search.get('ok'), 'status': cl_search.get('status'), 'text': cl_search.get('text', '')[-1000:]})
    proof['frontier'].append('PDF renderer never mounted in this backend-only run; open/visible-page/highlight/zoom effect remains unproven')
    proof['sourceHashesAtEnd'] = {name: digest(REPO / name) for name in SOURCE_FILES}
    proof['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['checks']['source_unchanged'] = proof['sourceUnchanged']

    output = REPO / 'scripts/evidence/FIXCL3-documents.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(output), 'passed': all(proof['checks'].values()), 'checks': proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
