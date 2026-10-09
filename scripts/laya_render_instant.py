"""Actual NxLaya screen, real store writes and report polling, owned Obscura."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
RUN = Path('D:/NeyviaRuns/laya-train/instant-ui')
sys.path.insert(0, str(REPO / 'src'))
os.environ['NEYVIA_TOOL_AUTO_UPDATE'] = '0'
from grant_agent.browser_obscura import ObscuraEngine
from grant_agent.laya_ledger import report
from grant_agent.neyvia_laya_capabilities import call
from playwright.sync_api import sync_playwright


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    root = REPO / '.agent_control/laya-train-runtime' / ('instant-ui-' + str(time.time_ns()))
    entry = RUN / 'entry.jsx'
    entry.write_text("import React from 'react';import {createRoot} from 'react-dom/client';\n"
        + f"import {{NxLayaApp}} from {json.dumps((REPO / 'web/src/neyvia/next/NxLaya.jsx').as_posix())};\n"
        + f"import {json.dumps((REPO / 'web/src/neyvia/next/nxTokens.css').as_posix())};\n"
        + f"import {json.dumps((REPO / 'web/src/neyvia/next/nxOs.css').as_posix())};\n"
        + "createRoot(document.getElementById('root')).render(<NxLayaApp/>);", encoding='utf-8')
    options = {'entryPoints': [str(entry)], 'outfile': str(RUN / 'bundle.js'), 'bundle': True,
               'jsx': 'automatic', 'nodePaths': [str(REPO / 'node_modules')], 'define': {'process.env.NODE_ENV': '"production"', 'import.meta.env': '{}'}}
    subprocess.run(['node', '-e', 'require("esbuild").buildSync(JSON.parse(process.argv[1]))', json.dumps(options)], cwd=REPO, check=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/api/ui/laya'):
                data = json.dumps(report(root, probe_service=False)).encode()
                mime = 'application/json'
            elif self.path in ('/bundle.js', '/bundle.css'):
                data = (RUN / self.path[1:]).read_bytes(); mime = 'text/javascript' if self.path.endswith('.js') else 'text/css'
            else:
                data = b'<!doctype html><html><meta charset="utf-8"><link rel="stylesheet" href="/bundle.css"><body class="nx"><div id="root"></div><script src="/bundle.js"></script></body></html>'
                mime = 'text/html'
            self.send_response(200); self.send_header('Content-Type', mime); self.end_headers(); self.wfile.write(data)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 48996), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    provision = json.loads((REPO / 'scripts/evidence/C13-obscura-provision.json').read_bytes())
    executable = Path(provision['executable'])
    if hashlib.sha256(executable.read_bytes()).hexdigest() != provision['executableSha256']:
        raise ValueError('Pinned Obscura identity changed')
    engine = ObscuraEngine(RUN / 'obscura', executable, port=48992, fixtures=True, public_resources=True, assigned_ports='48991-48999')
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(engine.endpoint, headers={'Authorization': 'Bearer ' + engine.token})
            page = browser.new_page(viewport={'width': 1000, 'height': 800})
            errors = []; page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto('http://127.0.0.1:48996', wait_until='networkidle')
            page.get_by_text('LAYA, the small local model', exact=True).wait_for()
            before = page.get_by_text('LAYA learned this', exact=True).count() == 0
            result = call('efficiency.laya_learn', {'domain': 'routing', 'input': 'Save the meeting note', 'label': 'notes', 'source': 'visible-journey'}, root)
            page.get_by_text('LAYA learned this', exact=True).wait_for(timeout=20000)
            observed = page.get_by_label('LAYA learning').inner_text()
            page.screenshot(path=str(RUN / 'learned.png'))
            answer = call('efficiency.laya_query', {'domain': 'routing', 'input': 'Save the meeting note'}, root)
            call('efficiency.laya_forget', {'source': 'visible-journey'}, root)
            page.get_by_text('LAYA learned this', exact=True).wait_for(state='hidden', timeout=20000)
            receipt = {'passed': before and 'notes' in observed and answer['answer']=='notes' and not errors,
                       'learn': result, 'answer': answer, 'visibleText': observed, 'forgottenSignalDisappeared': True,
                       'errors': errors, 'screenshot': str(RUN / 'learned.png'),
                       'boundary': 'Actual NxLayaApp and polling, native capability dispatch and real ledger/store; isolated HTTP adapter, not the full backend login journey.'}
            (REPO / 'scripts/evidence/LAYAT-instant-ui.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print(json.dumps(receipt), flush=True)
            browser.close()
    finally:
        engine.close(); server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
