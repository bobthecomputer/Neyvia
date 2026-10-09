"""Fresh A1 generation + A2 rendered controls through the production SDK browser.

No installs or implicit app ports. Keeps generated source, screenshots and receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
os.environ['NEYVIA_TOOL_AUTO_UPDATE'] = '0'
os.environ['FLUXIO_WATCHDOG_AUTOSTART'] = '0'
from grant_agent import app_sdk
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.port not in range(48681, 48690):
        parser.error('FIX2 owns ports 48681–48689 only')
    root = REPO / '.agent_control/FIX2/sdk' / uuid.uuid4().hex
    root.mkdir(parents=True)
    evidence = {'item':6, 'startedAt':time.time(), 'root':str(root), 'port':args.port,
                'browser':'Production AppBrowser (isolated installed Chromium); Chrome plugin unavailable',
                'checks':[], 'ok':False}
    log = (root / 'server.log').open('w', encoding='utf-8')
    server = browser = None
    def check(name, passed, **detail):
        evidence['checks'].append({'name':name, 'passed':bool(passed), **detail})
        if not passed:
            raise RuntimeError(name)
    try:
        manifest = app_sdk.read(app_sdk.DETAILS_MANIFEST)
        generated = {}
        for kind in sorted(app_sdk.KINDS):
            result = app_sdk.new_app(root, {'kind':kind, 'path':kind, 'name':'FIX2 '+kind+' details'})
            generated[kind] = result
            project = root / kind
            for entry in manifest['kit']['copy']:
                check(kind+' kit '+entry['to'], sha(REPO / entry['from']) == sha(project / 'www' / entry['to']))
            check(kind+' bundled credits', sha(REPO / 'docs/design/details-library.md') == sha(project / 'www/details/CREDITS.md'))
        evidence['generation'] = generated
        project = root / 'pwa'
        built = app_sdk.build_app(root, {'project':'pwa', 'platform':'pwa'})
        evidence['build'] = built
        check('PWA build includes kit', sha(Path(built['artifact']).parent/'details/details.js') == sha(project/'www/details/details.js'))
        server = subprocess.Popen([sys.executable, str(project/'server.py'), '--port', str(args.port)],
                                  cwd=REPO, stdout=log, stderr=log, **hidden_windows_subprocess_kwargs())
        url = 'http://127.0.0.1:'+str(args.port)
        deadline = time.monotonic()+10
        while True:
            try:
                with urlopen(url+'/identity.json', timeout=1) as response:
                    identity = json.load(response)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.1)
        check('Running generated identity', identity['instance'] == app_sdk.descriptor(project)['instance'])
        verification = app_sdk.verify_app(root, {'project':'pwa', 'url':url})
        evidence['clVerification'] = verification
        check('Production CL goal/click/reload journey', verification['ok'], completion=verification['completion'])
        browser = app_sdk.AppBrowser(url)
        browser.sdk('state')

        def _details(worker, sid, operation):
            row = worker.sessions[sid]
            page = row['page']
            if operation == 'copy-allow' or operation == 'copy-deny':
                cdp = row['context'].new_cdp_session(page)
                context_id = cdp.send('Target.getTargetInfo')['targetInfo']['browserContextId']
                for unsanitized in (False, True):
                    cdp.send('Browser.setPermission', {'permission':{'name':'clipboard-write', 'allowWithoutSanitization':unsanitized},
                             'setting':'granted' if operation == 'copy-allow' else 'denied', 'origin':url, 'browserContextId':context_id})
                page.bring_to_front()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.locator('#copy').click()
                try:
                    page.wait_for_function('expected => document.querySelector("#copy").dataset.state === expected',
                                           arg='done' if operation == 'copy-allow' else 'failed', timeout=5000)
                except Exception:
                    raise RuntimeError(operation+': '+json.dumps({'errors':errors, 'observation':worker._observe(sid)}))
                return page.locator('#copy').get_attribute('data-state')
            if operation == 'credit':
                return {'text':page.locator('.details-credit').inner_text(),
                        'visible':page.locator('.details-credit').is_visible(),
                        'rare':page.locator('.details-credit a').first.get_attribute('href'),
                        'roll':page.locator('#count-value').get_attribute('class')}
            if operation == 'dark':
                page.emulate_media(color_scheme='dark', reduced_motion='reduce')
                return worker._observe(sid)
            if operation == 'snapshot':
                path=REPO/'scripts/evidence/fix2-sdk-dark.png'
                page.screenshot(path=str(path),full_page=True)
                return {'path':str(path), 'sha256':sha(path)}
            raise ValueError(operation)
        browser.browser._details = types.MethodType(_details, browser.browser)
        def detail(operation):
            return browser.browser.run('details', browser.sid, operation)
        def click(name):
            for _ in range(8):
                delivery = browser.click(name)
                if delivery.get('ok'):
                    return delivery
                if delivery.get('status') != 'stale_projection':
                    raise RuntimeError('Rendered click refused: '+json.dumps(delivery))
                time.sleep(.1)  # Observe again after the kit's finite entrance motion.
            raise RuntimeError('Rendered control kept changing: '+name)

        credits = detail('credit')
        check('Rendered kit and visible credit link', credits['visible'] and credits['rare']=='https://rareui.com'
              and 'NumberFlow' in credits['text'] and 'nxd-roll' in credits['roll'], observation=credits)
        click('Reset')
        check('Reset asks before changing shared state', browser.sdk('state')['count']==1 and 'Reset the count?' in browser.observe()['text'])
        click('Keep count')
        check('Keep closes confirmation and preserves count', browser.sdk('state')['count']==1 and 'Reset the count?' not in browser.observe()['text'])
        check('Real clipboard allowed feedback', detail('copy-allow') == 'done')
        check('Real denied clipboard failure feedback', detail('copy-deny') == 'failed')
        click('Reset')
        click('Reset count')
        browser.sdk('wait', {'count':0})
        browser.sdk('reload')
        check('Confirmed reset persists across reload', browser.sdk('state')['count']==0)
        state = browser.sdk('state')
        req = Request(url+'/__neyvia/commit', data=json.dumps({'expectedRevision':state['revision']-1,
                      'state':{'count':99}}).encode(), headers={'X-Neyvia-App':'1','Content-Type':'application/json'})
        try:
            urlopen(req, timeout=5)
            refused = {}
        except HTTPError as error:
            refused = {'status':error.code, 'response':json.load(error)}
        check('Real stale host write refuses without mutation', refused.get('status')==409
              and app_sdk.state_api(project)==state, receipt=refused)
        click('Increment')
        browser.sdk('wait', {'count':1})
        evidence['finalObservation'] = detail('dark')
        light = REPO/'scripts/evidence/fix2-sdk-light.png'
        shutil.copy2(verification['screenshot'], light)
        evidence['screenshots'] = [detail('snapshot'), {'path':str(light), 'sha256':sha(light)}]
        check('Dark reduced-motion rendered count and credit', 'Count: 1' in evidence['finalObservation']['text'])
        evidence['sourceHashes'] = {str(path.relative_to(REPO)).replace('\\','/'):sha(path) for path in
            [REPO/'src/grant_agent/app_sdk.py', Path(__file__), *sorted((REPO/'config/app_sdk/web').glob('*')), app_sdk.DETAILS_MANIFEST]}
        evidence['ok'] = True
    except Exception as error:
        evidence['error'] = str(error)
    finally:
        if browser:
            browser.close()
        if server:
            server.terminate()
            server.wait(timeout=10)
        log.close()
        evidence['finishedAt'] = time.time()
        output = REPO / 'scripts/evidence/fix2-sdk.json'
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'ok':evidence['ok'], 'receipt':str(output), 'checks':len(evidence['checks']), 'error':evidence.get('error')}))
    return 0 if evidence['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
