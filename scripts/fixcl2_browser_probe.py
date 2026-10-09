"""Real hidden Obscura browser journey with fresh native and CL effect gates."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
EXE = Path(r'C:\Users\user\Projects\nx-c2-browser\.agent_control\C2f\obscura-v0.2.4\extracted\obscura.exe')
SOURCES = (
    'src/grant_agent/cl/browser_effects.py', 'src/grant_agent/cl/frontier_effects.py',
    'src/grant_agent/cl/codecs.py', 'src/grant_agent/browser_obscura.py',
    'src/grant_agent/cl/protocol.py', 'src/grant_agent/neyvia_manuals.py',
    'src/grant_agent/neyvia_browser.py', 'src/grant_agent/neyvia_workspace_tools.py',
    'manuals/browser.manual.json', 'manuals/cl/browser.cl',
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/next':
            body = b'<!doctype html><title>Second fixture</title><h1>Second page</h1><a href="/first">Back link</a>'
        else:
            body = (b'<!doctype html><title>First fixture</title><h1 id="heading">Original heading</h1>'
                    b'<label for="note">Local note</label><input id="note" value="">'
                    b'<button id="change" onclick="document.querySelector(\'#heading\').textContent=\'Clicked heading\'">Change heading</button>'
                    b'<a href="/next">Next page</a>')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *arguments):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine-port', type=int, required=True)
    parser.add_argument('--fixture-port', type=int, required=True)
    args = parser.parse_args()
    if (args.engine_port, args.fixture_port) != (48825, 48826):
        parser.error('Browser proof owns only hidden engine 48825 and local fixture 48826')
    if not EXE.is_file():
        raise FileNotFoundError('Installed Obscura engine is absent')
    root = REPO / '.agent_control' / 'proofs' / ('FIXCL2-browser-' + str(time.time_ns()))
    root.mkdir(parents=True)
    os.environ.pop('NEYVIA_UI_BACKEND_URL', None)  # Use this process's selected-root owner service.
    os.environ.update(NEYVIA_OBSCURA_EXE=str(EXE), NEYVIA_BROWSER_PROOF_PORTS='48825,48826',
                      NEYVIA_TOOL_AUTO_UPDATE='0', FLUXIO_WATCHDOG_AUTOSTART='0',
                      NEYVIA_COORDINATOR_AUTOSTART='0')
    from grant_agent.proof_credential_guard import prepare_broker_fixture
    from grant_agent.neyvia_agent import NeyviaToolGateway
    from grant_agent.neyvia_manuals import unwrap
    from grant_agent.cl.protocol import Protocol
    from grant_agent.cl import browser_effects as effects
    from grant_agent.neyvia_browser import service_for

    prepare_broker_fixture(root)
    gateway = NeyviaToolGateway(root, allow_mutations=True, action_scope='FIXCL2-browser', permission_mode='workspace')
    protocol = Protocol(gateway)
    service = service_for(root)
    proof = {'schema': 'neyvia.FIXCL2.browser.v1', 'root': str(root),
             'ports': {'engine': args.engine_port, 'fixture': args.fixture_port},
             'auditCells': ['AUD4.json#/transcripts/cl_browser',
                            'AUD4.json#/transcripts/manual_validation_browser',
                            'AUD4.json#/transcripts/manual_validation_perception'],
             'checks': {}, 'actions': [], 'observations': [],
             'frontier': ['WebView2 commands require native acknowledgements; capture, promote and LAYA decisions remain frontier']}
    before_path = REPO / 'scripts/evidence/FIXCL2-browser-before.json'
    proof['manualBeforeFailure'] = json.loads(before_path.read_text(encoding='utf-8'))
    proof['manualBeforeFailureSha256'] = digest(before_path)
    proof['checks']['before_receipt_is_real_failure'] = (
        proof['manualBeforeFailure'].get('status') == 'failed'
        and proof['manualBeforeFailure'].get('error') == "'tabId'"
        and 'tabId' not in proof['manualBeforeFailure'].get('results', {}).get('opened', {}))
    proof['sourceHashesAtStart'] = {name: digest(REPO / name) for name in SOURCES}
    server = ThreadingHTTPServer(('127.0.0.1', args.fixture_port), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(name, arguments):
        previous = effects.snapshot_for(protocol, name, arguments)
        checks = effects.checks_for(protocol, name, arguments)
        assert checks, name
        raw = gateway.call_native(name, arguments, action_id='fixcl2-browser-' + str(len(proof['actions']) + 1))
        try:
            value = unwrap(protocol.action_output(name, raw))
        except RuntimeError as exc:
            raise AssertionError((name, str(exc), raw)) from exc
        checked = checks[0]['check'](arguments, value, previous)
        proof['checks'][name + ':' + str(arguments.get('op') or arguments.get('action') or 'open')] = checked
        proof['actions'].append({'tool': name, 'op': arguments.get('op') or arguments.get('action') or 'open',
                                 'ok': value.get('ok') is not False, 'tabId': value.get('tabId') or arguments.get('tabId')})
        if not checked:
            raise AssertionError((name, arguments, value))
        return value, previous

    try:
        started = service.request('headless.start', {'port': args.engine_port, 'allowLocalFixtures': True}, owner=True)
        proof['checks']['installed_hidden_engine'] = (started.get('connected') is True and
            started.get('engine') == 'obscura' and started.get('port') == args.engine_port and
            started.get('stealth') is False)
        first = f'http://127.0.0.1:{args.fixture_port}/first'
        second = f'http://127.0.0.1:{args.fixture_port}/next'
        opened, before = call('neyvia.browser.open', {'url': first, 'engine': 'obscura'})
        tab_id = opened['tabId']
        projection = service.projection(tab_id)
        proof['observations'].append({'phase': 'open', 'url': projection['url'],
            'revision': projection['revision'], 'textSha256': hashlib.sha256(projection['text'].encode()).hexdigest()})
        proof['checks']['real_first_page_content'] = ('Original heading' in projection['text'] and
            projection['title'] == 'First fixture' and projection['readyState'] == 'complete')
        proof['checks']['queued_webview2_not_admitted'] = effects.checks_for(
            protocol, 'neyvia.browser.open', {'url': first, 'engine': 'webview2'}) == []
        service.request('tab.grant', {'tabId': tab_id, 'enabled': True}, owner=True)
        captured = Protocol(gateway).run('G: time.now()["unixSeconds"] > 0\n'
            'run browser.capture-owned-native-page(tabId=' + json.dumps(tab_id) + ')\ndone()',
            action_id='fixcl7-browser-native-capture')
        proof['captureContract'] = captured
        proof['checks']['actual_capture_observed'] = captured.get('ok') is True
        proof['checks']['unobserved_promotion_not_admitted'] = effects.checks_for(
            protocol, 'neyvia.browser.promote', {'tabId': tab_id}) == []
        service.request('tab.grant', {'tabId': tab_id, 'enabled': True}, owner=True)

        note = next(row for row in projection['elements'] if row['name'] == 'Local note')
        fill_args = {'tabId': tab_id, 'revision': projection['revision'],
                     'element': note['id'], 'action': 'fill', 'value': 'Owner-observed value'}
        filled, before = call('neyvia.browser.action', fill_args)
        proof['checks']['fill_exact_dom_value'] = any(row.get('value') == 'Owner-observed value'
            for row in filled['observation']['elements'] if row.get('id') == note['id'])
        proof['observations'].append({'phase': 'fill', 'url': filled['observation']['url'],
            'revision': filled['observation']['revision'],
            'textSha256': hashlib.sha256(filled['observation']['text'].encode()).hexdigest()})
        proof['checks']['stale_revision_refused'] = not effects.checks_for(
            protocol, 'neyvia.browser.action', fill_args)[0]['check'](
                fill_args, filled, {**before, 'projection': {**before['projection'], 'revision': 'wrong'}})
        current_revision = service.projection(tab_id)['revision']
        stale = gateway.call_native('neyvia.browser.action', fill_args, action_id='fixcl2-browser-stale-revision')
        proof['checks']['owner_stale_action_refused'] = (stale.get('ok') is False and
            service.projection(tab_id)['revision'] == current_revision)

        projection = service.projection(tab_id)
        button = next(row for row in projection['elements'] if row['name'] == 'Change heading')
        clicked, before = call('neyvia.browser.action', {'tabId': tab_id, 'revision': projection['revision'],
            'element': button['id'], 'action': 'click'})
        proof['checks']['click_changed_actual_dom'] = 'Clicked heading' in clicked['observation']['text']
        proof['observations'].append({'phase': 'click', 'url': clicked['observation']['url'],
            'revision': clicked['observation']['revision'],
            'textSha256': hashlib.sha256(clicked['observation']['text'].encode()).hexdigest()})
        navigated, before = call('neyvia.browser.tab', {'tabId': tab_id, 'op': 'navigate', 'url': second})
        proof['checks']['navigation_actual_second_page'] = ('Second page' in navigated['observation']['text'] and
            service.projection(tab_id)['url'] == second)
        proof['observations'].append({'phase': 'navigate', 'url': navigated['observation']['url'],
            'revision': navigated['observation']['revision'],
            'textSha256': hashlib.sha256(navigated['observation']['text'].encode()).hexdigest()})
        back, before = call('neyvia.browser.tab', {'tabId': tab_id, 'op': 'back'})
        proof['checks']['back_actual_first_page'] = back['observation']['url'] == first
        proof['observations'].append({'phase': 'back', 'url': back['observation']['url'],
            'revision': back['observation']['revision'],
            'textSha256': hashlib.sha256(back['observation']['text'].encode()).hexdigest()})
        updated, before = call('neyvia.browser.tab', {'tabId': tab_id, 'op': 'update', 'pinned': True})
        proof['checks']['tab_pinned_durable'] = updated['tab']['pinned'] is True

        # CL uses the same owner runtime and exact fresh observer for a new tab.
        cl_url = f'http://127.0.0.1:{args.fixture_port}/next'
        cl = Protocol(gateway).run('G effect: browser.state()["tabs"][-1]["url"] == '
            + json.dumps(cl_url) + '\nbrowser.open(url=' + json.dumps(cl_url)
            + ',engine="obscura")\ndone()', action_id='fixcl2-browser-cl-open')
        proof['checks']['cl_open_and_done'] = cl.get('ok') is True and cl.get('status') == 'ok'
        proof['actions'].append({'tool': 'neyvia.cl', 'case': 'browser.open', 'ok': cl.get('ok'),
                                 'status': cl.get('status'), 'text': cl.get('text', '')[-800:]})

        manual = unwrap(protocol.action_output('neyvia.manual.run', gateway.call_native(
            'neyvia.manual.run', {'id': 'browser', 'chapter': 'backend',
                'procedure': 'open-obscura-tab', 'inputs': {'url': first}},
            action_id='fixcl2-browser-manual-open')))
        proof['manualAfter'] = manual
        manual_tab = manual.get('results', {}).get('opened', {}).get('tabId')
        proof['checks']['manual_obscura_open_completed'] = (manual.get('status') == 'completed' and
            bool(manual_tab) and all(check.get('passed') is True for check in manual.get('checks', [])) and
            service.projection(manual_tab).get('readyState') == 'complete')
        proof['actions'].append({'tool': 'neyvia.manual.run', 'case': 'browser/open-obscura-tab',
                                 'status': manual.get('status'), 'checks': len(manual.get('checks', [])),
                                 'tabId': manual_tab})

        procedure_cl = Protocol(gateway).run('G effect: browser.state()["tabs"][-1]["url"] == '
            + json.dumps(first) + '\nrun browser.open-obscura-tab(url=' + json.dumps(first)
            + ')\ndone()', action_id='fixcl2-browser-cl-manual-open')
        proof['checks']['cl_manual_procedure_and_done'] = (
            procedure_cl.get('ok') is True and procedure_cl.get('status') == 'ok')
        proof['actions'].append({'tool': 'neyvia.cl', 'case': 'browser.open-obscura-tab',
                                 'ok': procedure_cl.get('ok'), 'status': procedure_cl.get('status'),
                                 'text': procedure_cl.get('text', '')[-800:]})

        closed, before = call('neyvia.browser.tab', {'tabId': tab_id, 'op': 'close'})
        proof['checks']['closed_page_absent'] = all(tab['id'] != tab_id for tab in service.state['tabs'])
        proof['checks']['source_unchanged'] = True
    finally:
        service.request('headless.stop', {}, owner=True)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    proof['checks']['owned_engine_stopped'] = service.headless is None
    proof['sourceHashesAtEnd'] = {name: digest(REPO / name) for name in SOURCES}
    proof['sourceUnchanged'] = proof['sourceHashesAtStart'] == proof['sourceHashesAtEnd']
    proof['checks']['source_unchanged'] = proof['sourceUnchanged']
    output = REPO / 'scripts/evidence/FIXCL2-browser.json'
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(output), 'passed': all(proof['checks'].values()), 'checks': proof['checks']}))
    return 0 if all(proof['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
