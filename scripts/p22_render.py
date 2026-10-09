"""One owned Obscura journey for the P22 PDF/surface/copy outcome contracts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'src'), str(REPO / 'scripts')]


def run(build, root, only, ports=(49081,49082), wait_for_build=False):
    started = time.perf_counter()
    import placement_shots as shots
    admission_path = Path(os.environ.get('NEYVIA_P22_ENGINE_ADMISSION', r'D:\NeyviaRuns\engines\obscura-c2h\4028d3ec7e4a-d25dbe93fae7\ADMISSION.json'))
    admission = json.loads(admission_path.read_text(encoding='utf-8'))
    for key in ['engineBinary', 'workerBinary']:
        row = admission[key]
        if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Prepared Obscura admission differs: ' + key)
    root.mkdir(parents=True, exist_ok=True)
    shots.EXE = Path(admission['engineBinary']['path'])
    from grant_agent.contract_gate import assigned_ports
    ports=assigned_ports(ports)
    shots.BACKEND, shots.ENGINE = ports
    shots.OUT = shots.SCRATCH = root
    shots.SMALL_STATE = Path('D:/NeyviaRuns/P22/state/render') / (root.parent.name + '-' + root.name)
    shots.SMALL_STATE.mkdir(parents=True,exist_ok=True)
    shots.BUILD, shots.THEME = build, 'dark'
    # Keep code dependencies visible after HOME/APPDATA isolation. This adds
    # installed package directories only, never the operator's settings.
    isolated = shots.isolated_env
    package_paths = [path for path in sys.path if Path(path).name == 'site-packages']
    def render_env():
        env = isolated()
        # Keep coverage.py's sitecustomize bootstrap first in PYTHONPATH while
        # retaining the isolated runtime's normal source and package imports.
        trace_root = os.environ.get('NEYVIA_P22_TRACE_ROOT')
        inherited = [trace_root] if trace_root else []
        env['PYTHONPATH'] = os.pathsep.join([*inherited, str(REPO/'src'), *package_paths])
        for name in ('NEYVIA_P22_TRACE_ROOT','NEYVIA_P22_TRACE_REPO','NEYVIA_P22_TRACE_SRC', 'NEYVIA_P22_TRACE_SCOPE', 'NEYVIA_P22_TRACE_SINCE',
                     'NEYVIA_P22_TRACE_SCOPE_SHA256', 'NEYVIA_P22_TRACE_ID'):
            if name in os.environ:
                env[name] = os.environ[name]
        return env
    shots.isolated_env = render_env
    report = {'schema':'neyvia.p22-render.v1','ok':False,'checks':[],'errors':[], 'engineAdmission':str(admission_path), 'build':str(build)}
    rig = shots.Rig(report, direct_cdp=True)
    # Attach to the page as it is created. BrowserContext's page event fires
    # synchronously from new_page(), before Rig.session performs its first
    # navigation, so V8 sees the initial application mount as well as later
    # interactions. Raw offsets are retained for the source-map mapper; this
    # runner does not pretend offsets are source lines.
    execution = {'schema':'neyvia.v8-precise-coverage.v1','available':False,
                 'contracts':[], 'scripts':[], 'startedBeforeNavigation':False}
    coverage_session = {'cdp':None, 'debuggerEnabled':False, 'profilerEnabled':False,
                        'started':False, 'error':None}
    source_receipt = build / 'source-receipt.json'
    source_receipt_before = None
    source_state_before = None
    trace_root = Path('D:/NeyviaRuns/P22/render-traces') / (root.parent.name + '-' + root.name)
    backend_trace = None
    backend_execution = {'available':False,'contracts':[]}

    def start_v8_coverage(page):
        try:
            cdp = rig.context.new_cdp_session(page)
            coverage_session['cdp'] = cdp
            cdp.send('Debugger.enable')
            coverage_session['debuggerEnabled'] = True
            cdp.send('Profiler.enable')
            coverage_session['profilerEnabled'] = True
            cdp.send('Profiler.startPreciseCoverage', {'callCount':True,'detailed':True})
            coverage_session['started'] = True
            execution['startedBeforeNavigation'] = True
        except Exception as error:
            coverage_session['error'] = str(error)[:500]

    source = (REPO / 'web/src/neyvia/next/nxOutcomeObservation.js').read_text(encoding='utf-8').replace('export function ', 'function ')
    observer = '() => { ' + source + '; return shellOutcomes(document.querySelector(".nx-root")); }'
    def observe(names):
        return rig.js('() => { '+source+'; return shellOutcomes(document.querySelector(".nx-root"),{only:'+json.dumps(names)+'}); }')
    try:
        contract_ids = sorted(set(_contracts_for(only)))
        from grant_agent.contract_execution import start_children as start_trace
        backend_trace = start_trace(REPO, trace_root, contract_ids)
        rig.start()
        browser_new_context = rig.browser.new_context
        def instrumented_new_context(*args, **kwargs):
            context = browser_new_context(*args, **kwargs)
            context.on('page', start_v8_coverage)
            return context
        rig.browser.new_context = instrumented_new_context
        if wait_for_build:
            # Backend and engine startup overlap compilation. The build marker
            # is written only after Vite finishes every asset.
            until=time.monotonic()+55
            while not (build/'source-receipt.json').is_file():
                if time.monotonic()>=until:raise TimeoutError('Fresh build did not finish before the render deadline')
                time.sleep(.1)
        source_receipt_before = hashlib.sha256(source_receipt.read_bytes()).hexdigest() if source_receipt.is_file() else None
        source_state_before = _source_state()
        rig.session(shots.DESKTOP)
        if 'image-missing' in only:
            from grant_agent.subprocess_utils import capture_bounded_process
            bundle=root/'image-observer.js'
            captured=capture_bounded_process(['node',str(REPO/'scripts/p22_release_dom.mjs'),str(bundle)],
                cwd=REPO,env=dict(os.environ),input_text=None,timeout=15)
            if captured['returncode'] != 0 or captured['timedOut']:raise RuntimeError(captured['stderr'])
            rig.js('source => { (0,eval)(source); window.p22MissingImage(); }',bundle.read_text(encoding='utf-8'))
            try:
                rig.wait("() => document.querySelector('#p22-missing-image .image-thumb')?.dataset.state === 'missing' && window.p22MissingImageCount === 1",6)
                measured=rig.js("() => {const start=performance.now(),host=document.querySelector('#p22-missing-image');return {label:host?.innerText,images:host?.querySelectorAll('img').length,reported:window.p22MissingImageCount,queryMs:performance.now()-start};}")
                report['checks'].append({'contract':'image.library.missing-file',
                    'ok':measured['label']=='Image file not on this PC' and measured['images']==0 and measured['reported']==1,
                    **measured})
            finally:
                rig.js('() => window.p22RemoveImage?.()')
        if 'chips' in only or 'copy' in only:
            observed = observe([name for name in only if name in ['chips','copy']])
            report['home'] = observed
            for name, field in [('chips','chipsUnclipped'),('copy','copyClean')]:
                if name in only: report['checks'].append({'contract':'p22.visible-copy' if name=='copy' else 'p22.chips','ok':observed[field], 'queryMs':observed['durationMs']})
        if 'pdf' in only:
            pdf = root / 'home/outcome.pdf'
            pdf.parent.mkdir(parents=True,exist_ok=True)
            from grant_agent import pdf_compat
            doc = pdf_compat.Canvas(595, 842); doc.text((72,72),'P22 visible phrase'); doc.save(pdf)
            shots.PDF = pdf
            shots.open_from_launcher(rig, 'files:'+str(pdf), 'PDF')
            try:
                # Module fallback and traced raster I/O can outlast six seconds.
                # Readiness still requires the real text layer before measuring ink.
                rig.wait("() => !!document.querySelector('.nx-pdf-page canvas') && !!document.querySelector('.textLayer span')", 30)
                report['pageReady'] = True
            except TimeoutError:
                report['pageReady'] = False
            time.sleep(.2)
            if 'pdf' in only:
                measured = rig.js('() => { const started=performance.now(); '+source+'; const value=pdfOutcome(document.querySelector(".nx-pdf-page"),"P22 visible phrase");return {...value,queryMs:performance.now()-started}; }')
                report['pdf'] = measured
                report['checks'].append({'contract':'p22.pdf-render','ok':measured['canvasPresent'] and measured['nonBlank'] and measured['textLayerPresent'] and measured['phrasePresent'], 'queryMs':measured['queryMs']})
        if 'chips' in only:
            if not shots.window_id(rig,'PDF'):
                shots.open_from_launcher(rig,'Notes','Notes')
            rig.js(shots.KEY,['Home','Home',False,True,True,'.nx-surface .nx-stage-head'])
            time.sleep(.4)
            observed=observe(['chips']); report['composerBesideApp']=observed
            report['checks'].append({'contract':'p22.chips','ok':observed['chipsUnclipped'],'queryMs':observed['durationMs']})
        if 'panels' in only:
            # A side app narrows the composer. Arrange mode also puts real
            # shell controls behind the window, exposing stacking regressions.
            if not shots.window_id(rig,'PDF'):
                shots.open_from_launcher(rig,'Notes','Notes')
                title='Notes'
            else: title='PDF'
            wid=shots.window_id(rig,title)
            rig.js(shots.KEY, ['ArrowRight','ArrowRight',False,True,True,'.nx-surface .nx-stage-head'])
            rig.wait("id => document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`)?.dataset.placement === 'side'", 5, wid)
            rig.js("() => {const b=document.querySelector('.nx-home-head button'); if(b?.getAttribute('aria-pressed')!=='true')b?.click();}")
            time.sleep(.4)
            points=rig.js("() => {const grip=document.querySelector('.nx-widget-grip'),panel=document.querySelector('.nx-surface'); if(!grip||!panel)return null;const g=grip.getBoundingClientRect(),p=panel.getBoundingClientRect();return [g.x+g.width/2,g.y+g.height/2,p.x+p.width/2,p.y+p.height/2];}")
            if not points:raise ValueError('The real widget drag controls are unavailable')
            rig.js("p => {const grip=document.querySelector('.nx-widget-grip');grip.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:p[0],clientY:p[1],pointerId:1,isPrimary:true,button:0}));}",points)
            rig.js("p => document.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:p[2],clientY:p[3],pointerId:1,isPrimary:true,buttons:1}))",points)
            rig.wait("() => !!document.querySelector('.nx-widget.is-dragging')",5)
            observed=observe(['panels']); report['narrow']=observed
            if 'panels' in only:report['checks'].append({'contract':'p22.panels','ok':observed['panelsOpaque'],'queryMs':observed['durationMs']})
            rig.js("() => document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1,isPrimary:true,button:0}))")
        if 'copy' in only:
            observed=observe(['copy'])
            report['checks'].append({'contract':'p22.visible-copy','ok':observed['copyClean'],'queryMs':observed['durationMs']})
            rejected=[]
            for text in ['TypeError: unavailable', 'OSError: permission denied', '/api/files/%2Fprivate%2Fdocument', 'window_0123456789abcdef', '01a10b6a-b309-7ed3-b223-3d6d6dda34a8']:
                rig.js("text => {const p=document.createElement('p');p.id='p22-copy-negative';p.textContent=text;p.style.cssText='position:fixed;top:30px;left:30px;z-index:2147483647;color:white;background:black';document.querySelector('.nx-root').append(p);}",text)
                try:
                    negative=observe(['copy'])
                    rejected.append({'kind':text.split(':')[0], 'ok':not negative['copyClean'] and text in negative['leaks'],'queryMs':negative['durationMs']})
                finally:
                    rig.js("() => document.querySelector('#p22-copy-negative')?.remove()")
            report['copyRejections']=rejected
            report['checks'].append({'contract':'p22.visible-copy','ok':all(row['ok'] for row in rejected),'failurePath':'visible exception, encoded path and internal identity refused'})
        if coverage_session['started']:
            try:
                measured = coverage_session['cdp'].send('Profiler.takePreciseCoverage')
                raw_scripts = measured.get('result', [])
                has_ranges = isinstance(raw_scripts,list) and any(
                    isinstance(row,dict) and isinstance(row.get('functions'),list) and row['functions']
                    for row in raw_scripts)
                if not has_ranges:
                    execution['reason'] = 'Obscura Profiler returned no precise script coverage data'
                    raw_scripts = []
                scripts = []
                for script in raw_scripts:
                    row = dict(script)
                    try:
                        if not isinstance(row.get('scriptId'),(str,int)):
                            raise ValueError('V8 coverage row has no scriptId')
                        row['source'] = coverage_session['cdp'].send(
                            'Debugger.getScriptSource', {'scriptId':script['scriptId']}).get('scriptSource', '')
                    except Exception as error:
                        row['sourceError'] = str(error)[:300]
                    scripts.append({key:row[key] for key in ('scriptId','url','source','sourceError') if key in row})
                execution['scripts'] = scripts
                execution['result'] = raw_scripts
                execution['v8Timestamp'] = measured.get('timestamp')
                missing_sources = [row.get('scriptId') for row in scripts
                                   if not isinstance(row.get('source'),str) or not row['source']]
                execution['scriptSourcesComplete'] = bool(scripts) and not missing_sources
                execution['scriptsMissingSource'] = missing_sources
                if has_ranges and execution['scriptSourcesComplete']:
                    execution['available'] = True
                elif has_ranges:
                    execution['reason'] = 'Obscura returned coverage ranges but did not provide source for every script ID'
            except Exception as error:
                execution['error'] = str(error)[:500]
        else:
            execution['reason'] = coverage_session['error'] or 'Obscura CDP did not attach coverage before navigation'
        rig.page.screenshot(path=str(root/'proof.png'))
        report['screenshot'] = {'path':str(root/'proof.png'),'sha256':hashlib.sha256((root/'proof.png').read_bytes()).hexdigest()}
        report['ok'] = bool(report['checks']) and all(row['ok'] for row in report['checks'])
    except Exception as error:
        report['error'] = str(error)[-1000:]
        if rig.page:
            try: report['failureText'] = rig.page.locator('body').inner_text()[-4000:]
            except Exception: pass
    finally:
        cdp = coverage_session['cdp']
        if cdp is not None:
            cleanup_errors = []
            if coverage_session['started']:
                try:
                    cdp.send('Profiler.stopPreciseCoverage')
                except Exception as error:
                    cleanup_errors.append('Profiler.stopPreciseCoverage: '+str(error)[:250])
            if coverage_session['profilerEnabled']:
                try:
                    cdp.send('Profiler.disable')
                except Exception as error:
                    cleanup_errors.append('Profiler.disable: '+str(error)[:250])
            try:
                cdp.detach()
            except Exception as error:
                cleanup_errors.append('CDP.detach: '+str(error)[:250])
            if cleanup_errors:
                execution['cleanupErrors'] = cleanup_errors
        rig.stop()
        if backend_trace is not None:
            try:
                backend_execution = backend_trace.stop()
                passing = set(_passing_contracts(report['checks']))
                backend_execution['contracts'] = sorted(set(backend_execution.get('contracts', [])) & passing)
                backend_execution['ok'] = bool(backend_execution.get('ok') and backend_execution['contracts'])
            except Exception as error:
                backend_execution = {'available':False,'contracts':[],'error':str(error)[:500]}
        report['ownedProcessesStopped'] = all(process.poll() is not None for process in rig.processes)
        report['ok'] = report['ok'] and report['ownedProcessesStopped']
        source_receipt_after = hashlib.sha256(source_receipt.read_bytes()).hexdigest() if source_receipt.is_file() else None
        source_state_after = _source_state()
        execution['sourceStable'] = bool(source_receipt_before and source_receipt_before == source_receipt_after
                                          and source_state_before == source_state_after)
        execution['sourceState'] = {'before':source_state_before, 'after':source_state_after}
        execution['sourceReceiptSha256'] = source_receipt_after
        execution['passingContracts'] = _passing_contracts(report['checks'])
        group_identity = {
            'schema':'neyvia.p22.measured-execution-group.v1',
            'runRoot':str(root.resolve()),
            'build':str(build.resolve()),
            'buildSourceReceiptSha256':source_receipt_after,
            'sourceStateBefore':source_state_before,
            'sourceStateAfter':source_state_after,
            'checks':report['checks'],
            'contracts':execution['passingContracts'],
        }
        group_id = hashlib.sha256(json.dumps(group_identity,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
        execution['measurementGroup'] = {'id':group_id,'schema':group_identity['schema'],
            'contractScope':'combined passing outcome journey; source lines are the run union',
            'contracts':execution['passingContracts'],'buildSourceReceiptSha256':source_receipt_after}
        backend_execution['measurementGroupId'] = group_id
        backend_execution['traceRoot'] = str(trace_root.resolve())
        backend_files = backend_execution.get('files',{})
        if isinstance(backend_files,dict):
            backend_execution['witnessedFiles'] = sorted(path for path,row in backend_files.items()
                if isinstance(row,dict) and row.get('lineData') is True
                and isinstance(row.get('lines'),list) and row['lines']
                and isinstance(row.get('sha256'),str) and len(row['sha256']) == 64)
        backend_execution['available'] = bool(backend_execution.get('ok')
            and backend_execution.get('sourceStable') is True
            and backend_execution.get('contracts') and backend_execution.get('witnessedFiles'))
        backend_execution['ok'] = backend_execution['available']
        # Contract identities accompany measurements only for a fully passing,
        # source-bound journey. Failed runs may keep raw diagnostics but cannot
        # contribute coverage evidence to the gate.
        if report['ok'] and execution['sourceStable'] and execution['available']:
            mapped = _map_v8_coverage(build, root, execution)
            mapped['measurementGroupId'] = group_id
            mapped_receipt_path = mapped.get('receiptPath')
            if mapped_receipt_path:
                Path(mapped_receipt_path).write_text(json.dumps(mapped,indent=2)+'\n',encoding='utf-8')
            execution['sourceMapped'] = mapped
            if mapped.get('ok') and mapped.get('sourceStable'):
                execution['contracts'] = execution['passingContracts']
            else:
                execution['contracts'] = []
        else:
            execution['contracts'] = []
            reason = ('outcome journey failed' if not report['ok'] else
                      'checkout or build source changed during the measured journey' if not execution['sourceStable'] else
                      execution.get('reason') or execution.get('error') or 'Obscura precise coverage unavailable')
            execution['sourceMapped'] = {'ok':False, 'reason':reason}
        report['executionCoverage'] = {'browser':execution,'backend':backend_execution}
        report['durationMs'] = round((time.perf_counter()-started)*1000)
        (root/'receipt.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def _source_state():
    """Bound coverage evidence to the exact checkout state surrounding the run."""
    try:
        head = subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        status = subprocess.run(['git','status','--porcelain=v1'],cwd=REPO,capture_output=True,text=True,timeout=5,check=True).stdout
        tracked = subprocess.run(['git','diff','--binary','HEAD'],cwd=REPO,capture_output=True,timeout=10,check=True).stdout
        return {'head':head,'statusSha256':hashlib.sha256(status.encode()).hexdigest(),
                'trackedDiffSha256':hashlib.sha256(tracked).hexdigest()}
    except Exception as error:
        return {'error':str(error)[:300]}


def _map_v8_coverage(build, root, execution):
    """Map Obscura's raw precise coverage through the built sourcemaps."""
    raw_path = root / 'v8-raw.json'
    mapped_path = root / 'v8-source-map.json'
    raw_path.write_text(json.dumps({'result':execution['result'], 'scripts':execution['scripts'],
                                    'contracts':execution['passingContracts']},
                                   separators=(',',':')),encoding='utf-8')
    execution['rawPath'] = str(raw_path)
    command = ['node',str(REPO/'scripts/p22_v8_coverage.mjs'),'--raw',str(raw_path),
               '--build',str(build),'--repo',str(REPO),'--out',str(mapped_path)]
    try:
        completed = subprocess.run(command,cwd=REPO,capture_output=True,text=True,timeout=60)
        if mapped_path.is_file():
            mapped = json.loads(mapped_path.read_text(encoding='utf-8'))
            mapped['receiptPath'] = str(mapped_path)
            if completed.returncode != 0:
                mapped['mapperExitCode'] = completed.returncode
            execution.pop('result',None)
            execution.pop('scripts',None)
            return mapped
        if completed.returncode != 0:
            return {'ok':False,'reason':'source-map mapper failed','returncode':completed.returncode,
                    'stderr':completed.stderr[-1500:]}
        try:
            summary = json.loads(completed.stdout)
            return {**summary,'receiptPath':str(mapped_path)}
        except Exception:
            return {'ok':False,'reason':'source-map mapper produced no receipt','stdout':completed.stdout[-1000:]}
    except Exception as error:
        return {'ok':False,'reason':str(error)[:500]}


def _contracts_for(only):
    names = {'pdf':'p22.pdf-render','panels':'p22.panels','chips':'p22.chips',
             'copy':'p22.visible-copy','image-missing':'image.library.missing-file'}
    return [names[name] for name in only]


def _passing_contracts(checks):
    grouped = {}
    for row in checks:
        name = row.get('contract')
        if isinstance(name,str):
            grouped.setdefault(name,[]).append(row.get('ok') is True)
    return sorted(name for name, results in grouped.items() if results and all(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--only', nargs='+', choices=['pdf','panels','chips','copy','image-missing'], default=['pdf','panels','chips','copy'])
    parser.add_argument('--ports', nargs=2, type=int, default=[49081,49082])
    parser.add_argument('--wait-for-build',action='store_true')
    args = parser.parse_args()
    from grant_agent.contract_gate import output_root
    output_root(args.root,small=True)
    output_root(args.build,small=True)
    report = run(args.build.resolve(), args.root.resolve(), args.only, args.ports,args.wait_for_build)
    print(json.dumps({key:report.get(key) for key in ['ok','checks','error','durationMs','ownedProcessesStopped']}))
    raise SystemExit(int(not report['ok']))
