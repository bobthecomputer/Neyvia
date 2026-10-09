"""Owned hidden browser journey through the production Memory and chat paths.

Synthetic accounts only. No saved credential reads or public service operations.
The owning CL manual binds this runner and its independent final store checks.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chat', action='store_true')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--receipt', type=Path, default=REPO/'scripts/evidence/MEM-browser.json')
    args = parser.parse_args()
    root = REPO / '.agent_control/mem/browser' / uuid.uuid4().hex
    root.mkdir(parents=True)
    secret, second_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    config = root / '.neyvia/laya/config.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'enabled': True, 'port': 48973, 'device': 'cpu'}), encoding='utf-8')
    from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs
    for port in (48971, 48973):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    environment = dict(os.environ, SYNTELOS_ACCOUNT_USER='mem-owner', SYNTELOS_ACCOUNT_PASSWORD=secret,
                       MEM_SECOND_PASSWORD=second_secret, NEYVIA_TOOL_AUTO_UPDATE='0', NEYVIA_COORDINATOR_AUTOSTART='0',
                       FLUXIO_WATCHDOG_AUTOSTART='0', FLUXIO_RUNTIME_AUTO_UPDATE='0')
    observations, report = [], {'ok': False, 'root': str(root), 'checks': {}, 'observations': []}
    log = (root/'backend.log').open('w', encoding='utf-8')
    child = subprocess.Popen([sys.executable, str(REPO/'scripts/mem_server.py'), '--root', str(root)], env=environment,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, **hidden_windows_subprocess_kwargs())
    from playwright.sync_api import sync_playwright
    browser = None
    try:
        with sync_playwright() as pw:
            request = pw.request.new_context(base_url='http://127.0.0.1:48971')
            deadline = time.monotonic() + 150
            while True:
                if child.poll() is not None:
                    raise RuntimeError('Owned backend exited; inspect task-local backend.log')
                try:
                    if request.get('/api/health', timeout=2000).ok:
                        break
                except Exception:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError('Owned backend startup deadline')
                time.sleep(.25)
            print('MEM production HTTP ready', flush=True)
            response = request.post('/api/auth/login', data={'username': 'mem-owner', 'password': secret})
            if not response.ok:
                raise RuntimeError('Disposable owner login refused')
            # This fixture represents an already configured PC. Use the real
            # setup API to avoid an unrelated first-run download or late modal.
            configured = request.post('/api/backend', data={'command': 'onboarding_save_command',
                'payload': {'dismissed': True}})
            if not configured.ok or configured.json().get('ok') is False:
                raise RuntimeError('Disposable setup dismissal refused')
            browser = pw.chromium.launch(headless=True, args=['--disable-gpu'])
            context = browser.new_context(storage_state=request.storage_state(), viewport={'width': 1280, 'height': 900})
            def route(route):
                parsed = urlsplit(route.request.url)
                if parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port == 48971:
                    route.continue_()
                else:
                    route.abort()
            context.route('**/*', route)
            from c8_headless import block_service_workers
            block_service_workers(context)
            page = context.new_page()
            page.on('pageerror', lambda error: print('MEM browser error: ' + str(error)[:350], flush=True))
            page.goto('http://127.0.0.1:48971/control?ui=next', wait_until='domcontentloaded')
            try:
                page.wait_for_selector('.nx', timeout=45000)
            except Exception:
                page.screenshot(path=str(root/'failed-page.png'))
                (root/'failed-page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                raise
            # Open the real shell launcher, then the registered Memory app.
            page.get_by_role('button', name='Apps (Ctrl Space)', exact=True).click()
            page.get_by_role('combobox', name='Search').fill('Memory')
            page.get_by_role('option').filter(has_text='Memory').first.click(timeout=30000)
            panel = page.locator('.nx-memory')
            panel.get_by_role('button', name='Remember something').click(timeout=30000)
            panel.get_by_label('Subject', exact=True).fill('panel signal')
            panel.get_by_label('Memory', exact=True).fill('violet-ten')
            panel.get_by_label('When needed', exact=False).fill('panel signal')
            panel.get_by_role('button', name='Save memory', exact=True).click()
            panel.get_by_text('Saved on this PC.', exact=True).wait_for()
            row = panel.locator('.nx-memory-row').filter(has_text='panel signal')
            row.get_by_text('violet-ten', exact=True).wait_for()
            row.get_by_role('button', name='Edit', exact=True).click()
            (root/'after-edit.txt').write_text(panel.inner_text(), encoding='utf-8')
            page.screenshot(path=str(root/'after-edit.png'))
            panel.get_by_label('Memory', exact=True).fill('amber-eleven')
            panel.get_by_role('button', name='Save memory', exact=True).click()
            row.get_by_text('amber-eleven', exact=True).wait_for()
            panel.get_by_label('Check what comes to mind').fill('panel signal')
            panel.get_by_role('button', name='Preview recall').click()
            panel.get_by_text('1 recalled', exact=False).wait_for()
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.receipt.with_suffix('.png')), full_page=True)
            report['checks']['panelTeachEditRecall'] = True

            def command(name, body=None, client=request):
                response = client.post('/api/backend', data={'command': name, 'payload': body or {}}, timeout=180000)
                value = response.json()
                observations.append({'command': name, 'http': response.status, 'ok': value.get('ok')})
                if not response.ok or value.get('ok') is False:
                    return {'ok': False, 'http': response.status, 'response': value}
                return value.get('data', value)

            # Observe the real owned local LAYA service once it has warmed.
            deadline = time.monotonic() + 150
            while True:
                try:
                    health = request.get('http://127.0.0.1:48973/v1/health', timeout=2000).json()
                    if health.get('status') == 'ready':
                        break
                except Exception:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError('LAYA did not become ready on the owned port')
                time.sleep(.25)
            local_packet = command('memory_recall_command', {'situation': {'intent': 'panel signal'}})
            report['layaRecall'] = local_packet
            report['layaHealth'] = {'status': health['status'], 'identity': health.get('identity')}
            report['checks']['layaAttemptRecorded'] = local_packet.get('laya') is not None
            report['layaAcceptedSelection'] = local_packet.get('route') == 'laya'
            if not report['checks']['layaAttemptRecorded']:
                raise RuntimeError('No real LAYA advisory receipt returned')
            records = command('memory_list_command')['memories']
            target = next(record for record in records if record['key'] == 'panel signal')
            # Another authenticated account, with forged identity fields and guessed ID.
            second = pw.request.new_context(base_url='http://127.0.0.1:48971')
            second_login = second.post('/api/auth/login', data={'username': 'mem-second', 'password': second_secret})
            if not second_login.ok:
                raise RuntimeError('Second disposable identity failed authentication')
            other = command('memory_list_command', {'owner': 'mem-owner', '_memoryUser': 'mem-owner'}, second)
            guessed = command('memory_inspect_command', {'id': target['id'], 'owner': 'mem-owner'}, second)
            if other.get('memories') or guessed.get('http') != 404:
                raise RuntimeError('Authenticated isolation failed')
            report['checks']['authenticatedOtherUserAndForgedOwnerDenied'] = True
            # Race a real server mutation against the open editor, then verify stale-save UI.
            row.get_by_role('button', name='Edit', exact=True).click()
            payload = {key: target[key] for key in ('id', 'key', 'content', 'kind', 'cues', 'expiresAt', 'exportPolicy')}
            payload.update(expectedRevision=target['revision'], content='olive-twelve', requestId=uuid.uuid4().hex)
            changed = command('memory_correct_command', payload)
            if changed.get('ok') is False:
                raise RuntimeError('Concurrent owner correction failed')
            panel.get_by_label('Memory', exact=True).fill('stale-panel-value')
            panel.get_by_role('button', name='Save memory', exact=True).click()
            panel.get_by_role('alert').filter(has_text='Someone changed this memory').wait_for()
            panel.get_by_role('button', name='Reload current version').click()
            if panel.get_by_label('Memory', exact=True).input_value() != 'olive-twelve':
                raise RuntimeError('Reload did not observe the concurrent correction')
            panel.get_by_role('button', name='Cancel', exact=True).click()
            report['checks']['stalePanelEditRefusedAndReloaded'] = True
            row.get_by_role('button', name='Forget', exact=True).click()
            row.get_by_role('button', name='Keep memory').click()
            row.get_by_role('button', name='Forget', exact=True).click()
            row.get_by_role('button', name='Forget this memory').click()
            panel.get_by_text('No memories in this project yet.', exact=False).wait_for()
            panel.get_by_label('Check what comes to mind').fill('panel signal')
            panel.get_by_role('button', name='Preview recall').click()
            panel.get_by_text('No matching memory', exact=False).wait_for()
            report['checks']['panelForgetAndFreshEmptyRecall'] = True
            # Reopen the page. Persistence is observed through the actual auth route.
            page.reload(wait_until='domcontentloaded')
            reopened = command('memory_recall_command', {'situation': {'intent': 'panel signal'}})
            if reopened['tokens'] != 0:
                raise RuntimeError('Deleted memory resurrected on reload')
            report['checks']['pageReloadNoResurrection'] = True
            report['emptyRecall'] = reopened

            if args.chat:
                report['chat'] = chat_journey(command, root, args.model, second, page, args.receipt)
            report['ok'] = True
            report['observations'] = observations
            context.close()
            browser.close()
            browser = None
            second.dispose()
            request.dispose()
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass  # Playwright also closes it when its context exits.
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
        log.close()
        report['ownedBackendStopped'] = child.poll() is not None
        args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': report['ok'], 'checks': report['checks'], 'root': str(root)}))


def chat_journey(command, root, model, second_user, page, receipt):
    project = root/'project-a'
    project.mkdir()
    options = {'model': model, 'effort': 'low', 'permissionMode': 'ask'}
    def new(message, folder=project):
        folder.mkdir(exist_ok=True)
        cursor = command('connected_events_poll_command', {'waitSeconds': 0})['cursor']
        admission = {'app': 'codex', 'cwd': str(folder), 'message': message,
            'requestId': uuid.uuid4().hex, 'options': options}
        for attempt in range(3):
            result = command('connected_session_new_command', admission)
            if result.get('response', {}).get('code') != 'adapter_unavailable':
                break
            if attempt < 2:
                print('MEM same-model admission unavailable; retrying the owned request', flush=True)
                time.sleep(15)
        if result.get('ok') is False:
            raise RuntimeError('Real Codex chat admission failed: ' + json.dumps(result)[:600])
        deadline = time.monotonic() + 300
        session_id = result.get('sessionId')
        while result.get('state') not in {'completed', 'failed', 'cancelled', 'interrupted'}:
            if time.monotonic() > deadline:
                command('connected_session_stop_command', {'runId': result['runId']})
                raise TimeoutError('Real Codex chat deadline; owned run requires inspection')
            events = command('connected_events_poll_command', {'cursor': cursor, 'waitSeconds': 1})
            cursor = events['cursor']
            for event in events['events']:
                if event.get('runId') == result['runId'] and event.get('type') == 'run.state':
                    session_id = event.get('sessionId') or session_id
                    result.update(event)
            if result.get('pendingRequest'):
                command('connected_session_stop_command', {'runId': result['runId']})
                raise RuntimeError('Memory acknowledgement unexpectedly requested approval; owned run stopped')
        if result['state'] != 'completed' or not session_id:
            raise RuntimeError('Real Codex turn failed: ' + json.dumps(result)[:700])
        page = command('connected_session_read_command', {'id': session_id})
        answer = '\n'.join(item.get('data', {}).get('text', '') for item in page['items'] if item.get('kind') == 'assistant').strip()
        print('MEM real chat completed: ' + message[:40], flush=True)
        return {'sessionId': session_id, 'answer': answer, 'run': page['run'], 'admissionAttempts': attempt + 1}

    taught = new('/remember --share launch signal = mint-seven')
    query = 'Recall the launch signal. Reply with exactly its value; if absent reply UNKNOWN. Do not use tools.'
    first = new(query)
    if first['answer'] != 'mint-seven':
        raise RuntimeError('Fresh chat did not recall the taught value: ' + first['answer'])
    page.goto('http://127.0.0.1:48971/control?ui=next&chat=' + quote(first['sessionId'], safe=''), wait_until='domcontentloaded')
    # An open app hides chat side-panel buttons in the normal shell density.
    # Use the registered app launcher, which also receives the selected session.
    page.get_by_role('button', name='Apps (Ctrl Space)', exact=True).click(timeout=30000)
    page.get_by_role('combobox', name='Search').fill('Memory')
    page.get_by_role('option').filter(has_text='Memory').first.click(timeout=30000)
    project_panel = page.locator('.nx-memory').first
    try:
        project_panel.get_by_text('mint-seven', exact=True).wait_for(timeout=90000)
    except Exception:
        page.screenshot(path=str(root/'failed-project-page.png'), full_page=True)
        (root/'failed-project-page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
        raise
    if 'project-a' not in project_panel.inner_text():
        raise RuntimeError('Rendered Memory panel did not use the selected chat project')
    visible_user = page.locator('.nx-user-text').first
    visible_user.wait_for()
    if visible_user.inner_text() != query:
        raise RuntimeError('Internal memory packet leaked into the visible user turn')
    page.screenshot(path=str(receipt.with_name('MEM-project-panel.png')), full_page=True)
    other_user_read = command('connected_session_read_command', {'id': first['sessionId']}, second_user)
    other_events = command('connected_events_poll_command', {'cursor': 0, 'waitSeconds': 0}, second_user)
    private_sessions = {taught['sessionId'], first['sessionId']}
    private_runs = {taught['run']['runId'], first['run']['runId']}
    if other_user_read.get('http') != 403 or any(event.get('sessionId') in private_sessions or event.get('runId') in private_runs for event in other_events['events']):
        raise RuntimeError('Another account could read a memory-bearing chat or its event stream')
    rows = command('memory_list_command', {'sessionId': taught['sessionId']})['memories']
    memory = next(row for row in rows if row['key'] == 'launch signal')
    corrected_chat = new('/correct launch signal = coral-eight')
    corrected = command('memory_inspect_command', {'sessionId': taught['sessionId'], 'id': memory['id']})
    if corrected.get('ok') is False or corrected['memory']['revision'] != 2 or corrected['memory']['content'] != 'coral-eight':
        raise RuntimeError('Explicit chat correction failed')
    revoked = command('connected_session_send_command', {'id': first['sessionId'], 'message': query,
        'requestId': uuid.uuid4().hex, 'options': options})
    if revoked.get('http') != 409 or revoked.get('response', {}).get('code') != 'memory_context_revoked':
        raise RuntimeError('Opaque stale chat was allowed to continue')
    second = new(query)
    if second['answer'] != 'coral-eight':
        raise RuntimeError('Correction did not supersede prior recall: ' + second['answer'])
    project_panel.get_by_role('button', name='Refresh memories').click()
    project_panel.get_by_text('coral-eight', exact=True).wait_for()
    isolated = new(query, root/'project-b')
    if isolated['answer'] != 'UNKNOWN' or isolated['run']['memoryRecall']['tokens'] != 0:
        raise RuntimeError('Other-project chat received a memory')
    forgotten = command('memory_forget_command', {'sessionId': taught['sessionId'], 'id': memory['id'],
        'expectedRevision': corrected['memory']['revision'], 'requestId': uuid.uuid4().hex})
    if forgotten.get('ok') is False:
        raise RuntimeError('Chat-scoped forgetting refused')
    third = new(query)
    if third['answer'] != 'UNKNOWN' or third['run']['memoryRecall']['tokens'] != 0:
        raise RuntimeError('Deleted memory reached a new chat')
    project_panel.get_by_role('button', name='Refresh memories').click()
    project_panel.get_by_text('No memories in this project yet.', exact=False).wait_for()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='Full screen (Alt+Shift+Up)', exact=True).first.click()
    page.wait_for_function("document.querySelector('.nx-memory')?.getBoundingClientRect().width >= 370")
    project_panel.get_by_role('button', name='Remember something').click()
    project_panel.get_by_label('Subject', exact=True).fill('phone signal')
    project_panel.get_by_label('Memory', exact=True).fill('indigo-thirteen')
    project_panel.get_by_label('When needed', exact=False).fill('phone signal')
    project_panel.get_by_role('button', name='Save memory', exact=True).click()
    phone_row = project_panel.locator('.nx-memory-row').filter(has_text='phone signal')
    phone_row.get_by_text('indigo-thirteen', exact=True).wait_for()
    phone_row.get_by_role('button', name='Edit', exact=True).click()
    project_panel.get_by_label('Memory', exact=True).fill('jade-fourteen')
    project_panel.get_by_role('button', name='Save memory', exact=True).click()
    phone_row.get_by_text('jade-fourteen', exact=True).wait_for()
    page.screenshot(path=str(receipt.with_name('MEM-project-phone.png')), full_page=True)
    phone_row.get_by_role('button', name='Forget', exact=True).click()
    phone_row.get_by_role('button', name='Forget this memory', exact=True).click()
    project_panel.get_by_text('No memories in this project yet.', exact=False).wait_for()
    return {'teach': taught, 'correctionChat': corrected_chat, 'freshRecall': first, 'correctedRecall': second, 'otherProject': isolated,
            'deletedRecall': third, 'oldChatRefused': revoked, 'otherAccountChatRead': other_user_read,
            'otherAccountEventsFiltered': True, 'renderedSelectedProjectLifecycle': True, 'phoneMemoryFullWidth': True,
            'phoneTeachEditForget': True, 'hostContextHiddenInChat': True,
            'tokenAccounting': 'Exact recall section o200k count; provider usage reported separately on each run'}


if __name__ == '__main__':
    main()
