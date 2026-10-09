"""Faithful actual PDF canvases in Neyvia's installed headless browser.

Reuse the authenticated mounted-pane/SSE harness, with current-source rendering
and richer PDF fixtures. No fake canvas, ACK or state observation is injected.
All listener and asyncio IPC ports are explicit command-line arguments.
"""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error

REPO = Path(__file__).resolve().parents[1]


def pdf_fixture():
    from grant_agent import pdf_compat
    from PIL import Image
    image = Image.new('RGB', (16, 16), (20, 180, 70))
    for x in range(8):
        for y in range(16): image.putpixel((x, y), (40, 70, 230))
    encoded = io.BytesIO(); image.save(encoded, format='PNG')
    doc = pdf_compat.Canvas(600, 800)
    for number, word in enumerate(('first', 'second')):
        if number: doc.add_page(600, 800)
        doc.text((50, 100), 'FIXCL4 ' + word + ' page exact text', size=18)
        doc.rect((50, 200, 150, 250), fill=(1, 0, 0))
        doc.circle((250, 230), 35, stroke=(0, 0, 1), fill=(0, 1, 1))
        doc.text((450, 450), 'ROTATED COURIER', size=22, font='cour', rotate=90)
        doc.image((50, 300, 210, 460), encoded.getvalue())
        doc.bezier((260, 360), (280, 290), (390, 500), (410, 370), color=(0.8, 0.1, 0.6), width=8, opacity=0.7)
    return doc.tobytes()


def pdf_extension(receipt, checks, cl, dom, ui, session, root, service, state):
    from grant_agent.neyvia_pdf_api import rasterize
    import time
    clicked = dom('''async () => { for(let i=0;i<30;i++) {
      const button=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Skip setup');
      if(button){button.click();return true;} await new Promise(resolve=>setTimeout(resolve,300));
    } return false; }''')
    checks['pdf.actualSkipSetupClicked'] = clicked is True
    for _ in range(80):
        if dom('() => !document.querySelector(".nx-onb-scrim")'): break
        time.sleep(.3)
    checks['pdf.actualSetupDismissed'] = dom('() => !document.querySelector(".nx-onb-scrim")')
    fixture = pdf_fixture(); path = root / 'faithful.pdf'; path.write_bytes(fixture)
    digest = hashlib.sha256(fixture).hexdigest()
    checks['pdfFixtureContainsRealGraphicsAndImages'] = b'/Subtype/Image' in fixture.replace(b' ', b'')
    operations = [
        ('open', f'pdf.open(source={json.dumps(str(path))},page=1)', 'pdf.state()["state"]["page"] == 1'),
        ('goto', 'pdf.goto(page=2)', 'pdf.state()["state"]["page"] == 2'),
        ('zoom', 'pdf.zoom(scale=1.25)', 'pdf.state()["state"]["scale"] == 1.25'),
        ('search', 'pdf.search(query="FIXCL4")', 'pdf.state()["state"]["search"]["hits"] == 2'),
        ('highlight', 'pdf.highlight(page=2,text="FIXCL4",note="Faithful rendered witness")', 'pdf.state()["state"]["highlights"][0]["note"] == "Faithful rendered witness"'),
        ('rect-highlight', 'pdf.highlight(page=2,rects=[[50,550,150,600]],note="Exact rectangle overlay")', 'pdf.state()["state"]["highlights"][1]["note"] == "Exact rectangle overlay"'),
    ]
    for key, action, goal in operations:
        token = session()
        result = cl('pdf-' + key, 'action', 'G: ' + goal + '\n' + action + '\ndone()', token)
        if not result.get('ok'):
            # The owner may still be drawing after an action's finite wait.
            # Reconcile the same action via fresh done; never redispatch it.
            initial_marks = list((service.bus.get('app:pdf') or {}).get('highlights', []))
            for attempt in range(8):
                time.sleep(1)
                result = cl('pdf-' + key, 'freshDone' + str(attempt), 'done()', token)
                if result.get('ok'): break
            checks['pdf.' + key + '.recoveryNeverDuplicatesHighlights'] = initial_marks == (service.bus.get('app:pdf') or {}).get('highlights', [])
        checks['pdf.' + key + '.freshPositiveCL'] = result.get('ok') is True
        if not result.get('ok'):
            receipt['journeys']['pdf-' + key]['failureOwner'] = service.bus.get('app:pdf')
            receipt['journeys']['pdf-' + key]['failureDOM'] = dom('() => ({text:document.body.innerText,errors:[...document.querySelectorAll(".nx-pdf-page-error")].map(e=>e.innerText)})')
            break
        visual = dom('''async () => {
          const sha=async data=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(x=>x.toString(16).padStart(2,'0')).join('');
          const pages=[];
          for(const box of document.querySelectorAll('.nx-pdf-page')) {
            const canvas=box.querySelector('canvas'), context=canvas.getContext('2d');
            if(!canvas.width || !canvas.height)continue;
            const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
            pages.push({number:Number(box.dataset.page),width:canvas.width,height:canvas.height,
              sha256:await sha(pixels),renderer:canvas.dataset.pdfRenderer,
              red:Array.from(context.getImageData(Math.floor(canvas.width*100/600),Math.floor(canvas.height*225/800),1,1).data),
              greenImage:Array.from(context.getImageData(Math.floor(canvas.width*180/600),Math.floor(canvas.height*380/800),1,1).data)});
          }
          return {pages,textLayer:[...document.querySelectorAll('.textLayer span')].map(e=>e.innerText).join(' '),
            errors:[...document.querySelectorAll('.nx-pdf-page-error')].map(e=>e.innerText),
            overlays:document.querySelectorAll('.nx-pdf-mark').length};
        }''')
        owner = service.bus.get('app:pdf') or {}
        receipt['journeys']['pdf-' + key]['actualCanvas'] = visual
        receipt['journeys']['pdf-' + key]['actualOwner'] = owner
        checks['pdf.' + key + '.noRenderingError'] = not visual['errors']
        checks['pdf.' + key + '.actualSelectableText'] = 'FIXCL4 first page exact text' in visual['textLayer']
        for canvas in visual['pages']:
            report = owner.get('renderedPages', {}).get(str(canvas['number'])) or {}
            if not report: continue
            _, expected = rasterize(fixture, canvas['number'], report['scale'])
            checks[f'pdf.{key}.page{canvas["number"]}.entireFaithfulCanvas'] = (
                canvas['sha256'] == expected['pixelSha256'] == report['pixelSha256']
                and canvas['width'] == expected['width'] and canvas['height'] == expected['height'])
            checks[f'pdf.{key}.page{canvas["number"]}.actualRedVector'] = canvas['red'] == [255,0,0,255]
            checks[f'pdf.{key}.page{canvas["number"]}.actualEmbeddedImage'] = canvas['greenImage'] == [20,180,70,255]
        if key.endswith('highlight'):
            checks['pdf.' + key + '.actualMountedOverlay'] = visual['overlays'] >= (2 if key == 'rect-highlight' else 1)
        checks['pdf.' + key + '.sourceConserved'] = hashlib.sha256(path.read_bytes()).hexdigest() == digest
    checks['pdf.completedAllSixJourneys'] = all(checks.get('pdf.' + op[0] + '.freshPositiveCL') for op in operations)
    if checks['pdf.completedAllSixJourneys']:
        saved = path.read_bytes(); path.write_bytes(saved + b'\n% Actual source-byte drift\n')
        checks['pdf.changedActualSourceRefusesDone'] = cl('pdf-rect-highlight', 'sourceDrift', 'done()', token).get('ok') is False
        path.write_bytes(saved)
        checks['pdf.restoredActualSourceRevalidatesDone'] = cl('pdf-rect-highlight', 'sourceRestored', 'done()', token).get('ok') is True
        checks['pdf.invalidPageRefused'] = cl('pdf-invalid', 'page', 'pdf.goto(page=999)\ndone()', session()).get('ok') is False
        # A canvas behind a real modal is not a visible PDF journey.
        service.bus.emit('onboarding.open', {'step':'welcome'})
        for _ in range(50):
            if dom('() => !!document.querySelector(".nx-onb-scrim")'): break
            time.sleep(.1)
        time.sleep(1)
        checks['pdf.actualOccludingSetupMounted'] = dom('() => !!document.querySelector(".nx-onb-scrim")')
        checks['pdf.occludedCanvasRefusesDone'] = cl('pdf-rect-highlight', 'occluded', 'done()', token).get('ok') is False
        dom('() => { document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true})); return true; }')
        for _ in range(50):
            if dom('() => !document.querySelector(".nx-onb-scrim")'): break
            time.sleep(.1)
        time.sleep(1)
        checks['pdf.actualOccludingSetupClosed'] = dom('() => !document.querySelector(".nx-onb-scrim")')
        checks['pdf.visibleCanvasRevalidatesDone'] = cl('pdf-rect-highlight', 'visibleAgain', 'done()', token).get('ok') is True
    screenshot = root / 'faithful-pdf.png'
    ui(lambda: state['page'].screenshot(path=str(screenshot)))
    committed = REPO / 'scripts/evidence' / (pdf_extension.wave + '-faithful-pdf.png')
    committed.write_bytes(screenshot.read_bytes())
    receipt['screenshot'] = {'path':str(screenshot), 'sha256':hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                            'committedPath':committed.relative_to(REPO).as_posix(),
                            'committedSha256':hashlib.sha256(committed.read_bytes()).hexdigest()}
    if checks['pdf.completedAllSixJourneys']:
        checks['pdf.actualCloseButtonClicked'] = dom("() => { const button=[...document.querySelectorAll('button')].find(e=>e.getAttribute('aria-label')==='Close PDF'); if(!button)return false;button.click();return true; }")
        for _ in range(50):
            if (service.bus.get('app:pdf') or {}).get('status') == 'closed': break
            time.sleep(.1)
        checks['pdf.actualClosedOwnerReported'] = (service.bus.get('app:pdf') or {}).get('status') == 'closed'
        checks['pdf.unmountedCanvasRefusesDone'] = cl('pdf-rect-highlight', 'closed', 'done()', token).get('ok') is False
    receipt['pdfVisualReady'] = checks['pdf.completedAllSixJourneys'] and all(v for k,v in checks.items() if k.startswith('pdf.'))


def main():
    existing = REPO / 'scripts/fixcl3_renderer_probe.py'
    spec = importlib.util.spec_from_file_location('fixcl4_mounted_renderer', existing)
    module = importlib.util.module_from_spec(spec)
    # Only rename the evidence destination; the production mount harness and
    # its assigned-port/executable/credential boundaries stay intact.
    source = existing.read_text(encoding='utf-8')
    if '--wave' not in sys.argv: sys.argv.extend(['--wave', 'FIXCL4'])
    pdf_extension.wave = sys.argv[sys.argv.index('--wave') + 1]
    owners = ['src/grant_agent/neyvia_pdf_api.py', 'src/grant_agent/web_backend_http.py',
              'web/src/neyvia/next/NxPdfApp.jsx', 'web/src/neyvia/next/NxPdfPage.jsx',
              'web/src/neyvia/next/nxPdfModel.js', 'scripts/fixcl4_render_pdf_probe.py']
    source = source.replace('    start = hashes(sources)',
        '    sources[0:0] = [REPO / name for name in ' + repr(owners) + ']\n    start = hashes(sources)')
    exec(compile(source, str(existing), 'exec'), module.__dict__)
    module.pdf_extension = pdf_extension
    if '--pdf-only' not in sys.argv: sys.argv.append('--pdf-only')
    code = module.main()
    output = REPO / 'scripts/evidence' / (pdf_extension.wave + '-renderer-pdf.json')
    receipt = json.loads(output.read_bytes())
    receipt['probeHash'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt['boundary'] += ' PDF canvases contain actual PDFium RGBA through the authenticated owner endpoint; entire canvas digests, vectors, embedded images, rotated font and Bezier curves are checked against full-document rendering.'
    receipt['ok'] = code == 0 and receipt.get('pdfVisualReady') is True
    receipt['passed'] = receipt['ok']
    output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return 0 if receipt['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
