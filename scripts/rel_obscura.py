"""Hidden renderer through Neyvia's own Obscura engine; owned REL URLs only."""
from pathlib import Path
import argparse
import base64
import json
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent.browser_obscura import ObscuraEngine, ProfileWorker

PAGE_ERRORS = []
NETWORK = []
def record_network(event, request, status=None):
    from urllib.parse import urlsplit
    url = urlsplit(request.url)
    NETWORK.append({'event':event,'origin':url.scheme+'://'+url.netloc,'path':url.path,'status':status,
        'failure':request.failure if event == 'failed' else None})
    if len(NETWORK) > 180: NETWORK.pop(0)
connect = ProfileWorker._connect
def observed_connect(worker):
    connect(worker)
    if not getattr(worker, '_rel_errors_bound', False):
        def bind(page):
            page.on('pageerror', lambda error: PAGE_ERRORS.append(str(error)[:1200]))
            page.on('request', lambda request: record_network('request',request))
            page.on('response', lambda response: record_network('response',response.request,response.status))
            page.on('requestfailed', lambda request: record_network('failed',request))
        worker.context.on('page', bind)
        worker._rel_errors_bound = True
ProfileWorker._connect = observed_connect

def rel_dom(worker, tab_id, operation, name=None):
    page = worker.pages[tab_id]['page']
    if operation == 'click':
        return page.evaluate("""name => {
            const controls = [...document.querySelectorAll('button')].filter(e =>
                (e.getAttribute('aria-label') || e.textContent.trim()) === name &&
                e.getBoundingClientRect().width > 0 && !e.disabled);
            if (controls.length !== 1) throw Error('Expected one visible button: '+name);
            controls[0].dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); return {clicked:name};
        }""", name)
    return page.evaluate("""() => [...document.querySelectorAll('.nx-onb-scrim,.nx-onb,.nx-tour-screen,.nx-tour-canvas,.nx-tour-caption,.nx-tour-controls')].map(e => {
        const s=getComputedStyle(e), r=e.getBoundingClientRect();
        return {class:e.className,rect:{x:r.x,y:r.y,width:r.width,height:r.height},background:s.backgroundColor,
            zIndex:s.zIndex,opacity:s.opacity,position:s.position,transform:s.transform,inert:e.inert,
            panel:s.getPropertyValue('--nx-panel'),caption:e.classList.contains('nx-tour-caption')?e.innerText:null,
            scene:e.classList.contains('nx-tour-canvas')?{text:e.innerText.slice(0,1200),children:[...e.children].map(c=>c.className)}:null};
    })""")
ProfileWorker._rel_dom = rel_dom

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--queue', type=Path, help='Task-local JSONL command queue for hidden, noninteractive hosts')
    parser.add_argument('--profile-root', type=Path, default=Path('D:/NeyviaRuns/REL/renderer'), help='Isolated renderer storage; use a fresh root after restoring backend scratch')
    parser.add_argument('--output', type=Path, default=Path('D:/NeyviaRuns/REL/renderer.json'))
    parser.add_argument('--executable', type=Path, default=Path('D:/NeyviaRuns/REL/obscura.exe'), help='Explicit existing renderer; provenance is recorded, never silently substituted')
    parser.add_argument('--idle-seconds', type=int, default=600, help='Close owned renderer after bounded queue inactivity, including controller death')
    args = parser.parse_args()
    if not args.profile_root.resolve().is_relative_to(Path('D:/NeyviaRuns/REL').resolve()):
        raise ValueError('Renderer storage must stay in REL evidence')
    if not args.executable.resolve().is_relative_to(Path('D:/NeyviaRuns/REL').resolve()):
        raise ValueError('Renderer executable must stay in REL evidence')
    engine = ObscuraEngine(args.profile_root, str(args.executable),
        port=48964, fixtures=True, assigned_ports='48961-48969', color_scheme='dark', reduced_motion='reduce', request_timeout_ms=60000)
    results = []
    from rel_harness import server
    adapter = server()
    try:
        def steps():
            yield from json.loads(args.recipe.read_text(encoding='utf-8'))
            if args.queue:
                consumed = 0
                last_command = time.monotonic()
                while True:
                    lines = [line for line in args.queue.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
                    if consumed >= len(lines):
                        if time.monotonic() - last_command >= min(max(args.idle_seconds, 30), 600): return
                        # Sync Playwright dispatches interception callbacks only
                        # during calls. Keep the real page observed while idle.
                        engine.run('rel', 'observe', 'shell')
                        time.sleep(.5)
                        continue
                    value = json.loads(lines[consumed])
                    consumed += 1
                    last_command = time.monotonic()
                    if value.get('close'): return
                    yield value
            if args.interactive:
                print('REL renderer ready for JSON steps; {"close":true} ends it.',flush=True)
                for line in sys.stdin:
                    value = json.loads(line)
                    if value.get('close'): return
                    yield value
        for step in steps():
            if 'navigate' in step:
                from urllib.parse import urlsplit
                url = urlsplit(step['navigate'])
                if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.port not in range(48961,48970):
                    raise ValueError('Only owned REL URLs may be rendered')
                if engine.profiles:
                    value = engine.run('rel', 'navigate', 'shell', step['navigate'])
                else:
                    value = engine.run('rel', 'open', 'shell', step['navigate'])
                results.append(value)
            elif 'observe' in step:
                value = engine.run('rel', 'observe', 'shell')
                results.append(value)
                print(json.dumps({'title':value.get('title'), 'controls':[{'id':e['id'],'role':e['role'],'name':e['name'],'enabled':e.get('enabled')} for e in value.get('elements',[]) if e['role'] in {'button','textbox','combobox','menuitem'}][-28:]}),flush=True)
            elif 'waitForText' in step:
                deadline = time.monotonic() + min(step.get('seconds',30),45)
                while time.monotonic() < deadline:
                    value = engine.run('rel', 'observe', 'shell')
                    if step['waitForText'] in value.get('text',''): break
                    time.sleep(.5)
                else:
                    results.append(value)
                    print(json.dumps({'errors':PAGE_ERRORS,'missingText':step['waitForText'],'network':NETWORK[-20:]}),flush=True)
                    raise RuntimeError('Rendered text not observed: '+step['waitForText'])
                results.append(value)
            elif 'clickName' in step or 'clickIfNamed' in step:
                value = engine.run('rel','observe','shell')
                name = step.get('clickName',step.get('clickIfNamed'))
                targets = [element for element in value['elements'] if element.get('name') == name]
                if not targets and 'clickIfNamed' in step: continue
                if len(targets) != 1: raise ValueError('Expected one current named control: '+name)
                clicked = engine.run('rel','action','shell',{'revision':value['revision'],'element':targets[0]['id'],'action':'click'})
                results.append(clicked)
                if not clicked.get('ok'): raise RuntimeError('Native click effect unconfirmed: '+name)
            elif 'waitForImage' in step:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    engine.run('rel', 'observe', 'shell')
                    observed = adapter.call('tools_call', {'tool':'neyvia.image.state','arguments':{}})
                    state = json.loads(next(block['text'] for block in observed['content'] if block['type'] == 'text'))
                    preview, requested = state.get('state') or {}, state.get('requested') or {}
                    if preview.get('fresh') and preview.get('status') == 'ready' and preview.get('assetId') == requested.get('id'):
                        break
                    time.sleep(.5)
                else: raise RuntimeError('Fresh decoded requested image was not observed')
                asset = json.dumps(requested['id'])
                lines = f'G: image.state().state.assetId == {asset}\nrun image-studio.verify-live-preview(assetId={asset})\ndone()'
                result = adapter.call('tools_call', {'tool':'neyvia.cl','arguments':{'lines':lines}})
                results.append({'imagePreview':state,'cl':lines,'result':result})
                print(json.dumps({'assetId':requested['id'],'previewContractPassed':not result.get('isError')}),flush=True)
                if result.get('isError'): raise RuntimeError('Fresh image preview contract failed')
            elif 'domClickName' in step:
                results.append(engine.profiles['rel'].run('rel_dom','shell','click',step['domClickName']))
            elif 'tourGeometry' in step:
                value = engine.profiles['rel'].run('rel_dom','shell','geometry')
                results.append({'tourGeometry':value})
                print(json.dumps(value),flush=True)
            elif 'cl' in step:
                result = adapter.call('tools_call',{'tool':'neyvia.cl','arguments':{'lines':step['cl']}})
                results.append({'cl':step['cl'],'result':result})
                print(json.dumps(result,ensure_ascii=False)[:1800],flush=True)
                if bool(result.get('isError')) != bool(step.get('expectError')):
                    raise RuntimeError('CL outcome differed; inspect its preserved receipt')
            elif 'tool' in step:
                result = adapter.call('tools_call',{'tool':step['tool'],'arguments':step.get('arguments',{})})
                results.append(result)
                print(json.dumps(result,ensure_ascii=False)[:2500],flush=True)
            elif 'diagnostics' in step:
                print(json.dumps({'pageErrors':PAGE_ERRORS,'network':NETWORK[-20:]}),flush=True)
            elif 'screenshot' in step:
                value = engine.run('rel','frame','shell')
                target = Path(step['screenshot']).resolve()
                if not target.is_relative_to(Path('D:/NeyviaRuns/REL').resolve()): raise ValueError('Screenshot must stay in REL evidence')
                target.write_bytes(base64.b64decode(value['dataUrl'].split(',',1)[1]))
                results.append({'screenshot':str(target),'revision':value['revision']})
            else: raise ValueError('Unknown bounded renderer step')
            args.output.write_text(json.dumps({'engine':engine.status(),'pageErrors':PAGE_ERRORS,'network':NETWORK,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        args.output.write_text(json.dumps({'engine':engine.status(),'pageErrors':PAGE_ERRORS,'network':NETWORK,'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        engine.close()

if __name__ == '__main__': main()
