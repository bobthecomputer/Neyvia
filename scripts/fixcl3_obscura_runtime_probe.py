"""Real Obscura PDF transport/parser witnesses and native canvas limitations."""
from __future__ import annotations
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('fixture-port', 'engine-port', 'ipc-port'):
        parser.add_argument('--' + name, type=int, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--obscura', type=Path, required=True)
    args = parser.parse_args()
    args.dist, args.obscura = args.dist.resolve(), args.obscura.resolve()
    ports = [args.fixture_port, args.engine_port, args.ipc_port]
    if len(set(ports)) != 3 or any(p not in range(48821, 48830) for p in ports):
        parser.error('Three distinct assigned ports required')
    for supplied in (args.dist, args.obscura):
        if any(supplied.resolve().is_relative_to(Path(r'C:\Users\user\Projects') / name)
               for name in ('Neyvia', 'Neyvia-next')):
            parser.error('Protected tree is outside this task')
    if not args.dist.is_dir() or not args.obscura.is_file():
        parser.error('Existing built artifact and own browser required')
    sys.path.insert(0, str(REPO / 'src'))
    from fixcl3_renderer_probe import pdf_fixture
    from grant_agent.proof_credential_guard import install
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    from grant_agent.browser_obscura import ObscuraEngine, ProfileWorker
    root = REPO / '.agent_control/proofs' / ('FIXCL3-runtime-' + str(time.time_ns()))
    root.mkdir(parents=True)
    install(root)
    install_hidden_subprocess_default()
    os.environ['NEYVIA_BROWSER_PROOF_PORTS'] = ','.join(map(str, ports))
    # Windows asyncio IPC retains its native socketpair mechanism on an assigned port.
    def pair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        with socket.socket(family, type, proto) as listener:
            listener.bind(('127.0.0.1', args.ipc_port))
            listener.listen(1)
            client = socket.socket(family, type, proto)
            client.connect(listener.getsockname())
            server, _ = listener.accept()
            return server, client
    if sys.platform == 'win32':
        socket.socketpair = pair
    fixture = pdf_fixture()
    requests = []
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path in ('/fixture.pdf', '/diag', '/classic.js'):
                data = (fixture if self.path == '/fixture.pdf' else
                        b'self.onmessage=event=>self.postMessage(event.data)' if self.path == '/classic.js' else
                        b'<html><body>Owned runtime diagnosis</body></html>')
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf' if self.path == '/fixture.pdf' else
                                 'text/javascript' if self.path == '/classic.js' else 'text/html')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith('/assets/'):
                super().do_GET()
            else:
                self.send_error(404)
        def log_message(self, *_):
            pass
    sources = [Path(__file__), REPO / 'src/grant_agent/browser_obscura.py']
    pdfjs = next(args.dist.glob('assets/pdf.min-*.js'))
    pdfworker = next(args.dist.glob('assets/pdf.worker.min-*.mjs'))
    def hashes():
        return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources + [pdfjs, pdfworker]}
    before = hashes()
    version = subprocess.run([str(args.obscura), '--version'], capture_output=True,
                             text=True, check=True, timeout=10).stdout.strip()
    executable_sha256 = hashlib.sha256(args.obscura.read_bytes()).hexdigest()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.fixture_port),
        functools.partial(Handler, directory=str(args.dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    engine = ObscuraEngine(root / 'engine', args.obscura, port=args.engine_port, fixtures=True)
    worker = ProfileWorker(engine.endpoint, engine.token, True, root / 'profile')
    def observe():
        worker._open('runtime', f'http://127.0.0.1:{args.fixture_port}/diag')
        page = worker.pages['runtime']['page']
        logs = []
        page.on('pageerror', lambda error: logs.append(str(error)))
        result = page.evaluate("""async options => {
          const timed=p=>Promise.race([p,new Promise((_,reject)=>setTimeout(()=>reject(Error('Runtime proof deadline')),15000))]);
          const result={};
          const response=await fetch('/fixture.pdf');
          result.http={status:response.status,url:response.url,type:response.headers.get('content-type'),length:response.headers.get('content-length')};
          result.bytes=Array.from(new Uint8Array(await response.arrayBuffer()));
          const mod=await import(options.pdfjs);mod.GlobalWorkerOptions.workerSrc=options.worker;
          const doc=await timed(mod.getDocument({url:'/fixture.pdf',withCredentials:true,isEvalSupported:false}).promise);
          result.pages=doc.numPages;result.text=[];
          for(let n=1;n<=doc.numPages;n++)result.text.push((await(await doc.getPage(n)).getTextContent()).items.map(i=>i.str).join(' '));
          await doc.destroy();
          let calls=0;
          const reader=new ReadableStream({pull(c){calls++;if(calls===1)c.enqueue(new Uint8Array([7,11,19]));else c.close()}}).getReader();
          const first=await timed(reader.read()),end=await timed(reader.read());
          result.pull={calls,first:Array.from(first.value),firstDone:first.done,endDone:end.done};
          const failed=new ReadableStream({pull(){throw Error('Actual producer error')}}).getReader();
          try{await timed(failed.read())}catch(error){result.producerError=String(error)}
          const canvas=document.createElement('canvas');canvas.width=32;canvas.height=32;
          const ctx=canvas.getContext('2d');
          result.canvas={getTransform:typeof ctx.getTransform};
          ctx.fillStyle='#ff0000';ctx.translate(8,8);ctx.fillRect(0,0,4,4);
          result.canvas.atOrigin=Array.from(ctx.getImageData(0,0,1,1).data);
          result.canvas.atTranslated=Array.from(ctx.getImageData(9,9,1,1).data);
          try{new Worker(URL.createObjectURL(new Blob([''],{type:'text/javascript'})),{type:'module'})}
          catch(error){result.moduleWorkerError=error.name}
          const classic=new Worker('/classic.js');
          try{result.classicWorker=await new Promise((resolve,reject)=>{
            classic.onmessage=event=>resolve(event.data);classic.onerror=error=>reject(Error(error.message));
            setTimeout(()=>classic.postMessage('Actual classic worker echo'),200);
            setTimeout(()=>reject(Error('Classic worker echo deadline')),3000);
          })}catch(error){result.classicWorkerError=String(error)}finally{classic.terminate()}
          return result;
        }""", {'pdfjs': '/' + pdfjs.relative_to(args.dist).as_posix(),
                 'worker': '/' + pdfworker.relative_to(args.dist).as_posix()})
        result['logs'] = logs
        return result
    try:
        result = worker.executor.submit(observe).result(timeout=60)
        actual = bytes(result.pop('bytes'))
        result['bodySha256'] = hashlib.sha256(actual).hexdigest()
        checks = {'actualHttpStatus': result['http']['status'] == 200,
                  'actualDeclaredLength': int(result['http']['length']) == len(actual),
                  'actualFixtureBytes': actual == fixture,
                  'realTwoPageParser': result['pages'] == 2,
                  'exactParsedText': result['text'] == ['FIXCL3 first page exact text', 'FIXCL3 second page exact text'],
                  'actualProducerPull': result['pull'] == {'calls': 2, 'first': [7,11,19], 'firstDone': False, 'endDone': True},
                  'actualProducerError': result.get('producerError') == 'Error: Actual producer error',
                  'unsupportedModuleWorkerExplicit': result.get('moduleWorkerError') == 'NotSupportedError',
                  'actualClassicWorkerPreserved': result.get('classicWorker') == 'Actual classic worker echo',
                  'sourceBytesUnchanged': before == hashes()}
        canvas = result['canvas']
        visual = {'nativeGetTransform': canvas['getTransform'] == 'function',
                  'nativeTransformPixels': canvas['atOrigin'] == [0,0,0,0] and canvas['atTranslated'] == [255,0,0,255]}
        receipt = {'ok': all(checks.values()), 'root': str(root), 'assignedPorts': ports,
                   'parserChecks': checks, 'visualChecks': visual, 'visualReady': all(visual.values()),
                   'capabilities': worker.runtime_capabilities, 'observed': result,
                   'executable': {'path': str(args.obscura), 'version': version,
                                  'sha256': executable_sha256},
                   'fixtureSha256': hashlib.sha256(fixture).hexdigest(), 'fixtureBytes': len(fixture),
                   'requests': requests, 'sourceHashesAtStart': before, 'sourceHashesAtEnd': hashes(),
                   'outsideRequirement': 'A Neyvia browser engine with actual Canvas2D transforms and getTransform; Obscura 0.2.4 official latest has neither in this witnessed runtime.',
                   'upstreamRelease': 'https://github.com/h4ckf0r0day/obscura/releases/tag/v0.2.4'}
        output = REPO / 'scripts/evidence/FIXCL3-obscura-runtime.json'
        output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'receipt': str(output), 'parser': receipt['ok'], 'visual': receipt['visualReady']}))
        return 0 if receipt['ok'] else 1
    finally:
        worker.close()
        engine.close()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
