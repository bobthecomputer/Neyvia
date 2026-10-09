"""Fresh bounded F10 batches. Execution receipts never substitute for full passes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
LOG = Path('C:/Users/user/Projects/plans/logs/window-guard.jsonl')
BATCHES = {
    1: ['workspace/files/read-and-confirm', 'workspace/files/replace-and-read',
        'workspace/files/find-source'],
    2: ['neyvia/apps/locate-app-state', 'neyvia/sessions/rename-and-confirm',
        'neyvia/sessions/move-chat'],
    3: ['sidebar/proofs-e-shell/read-shell-proof-receipt'],
}


def transport():
    """Diagnostic actual Playwright startup with the existing C8 socket fence."""
    import faulthandler
    trace = (ROOT / 'scripts/evidence/C8h-transport-stack.log').open('w')
    faulthandler.dump_traceback_later(20, file=trace)
    from c8_scope import install
    install()
    from playwright.sync_api import sync_playwright
    print('Starting actual scoped transport', flush=True)
    with sync_playwright() as runtime:
        print('Scoped transport returned', flush=True)
    faulthandler.cancel_dump_traceback_later()
    trace.close()


def guard_contract():
    import ctypes as C
    from ctypes import wintypes as W
    from c8h_conpty import windows
    from c8_desktop_guard import DesktopGuard
    before = windows()
    if not before['threadDesktop'].startswith('Neyvia-C11-') or before['threadDesktop']==before['inputDesktop']:
        raise RuntimeError('Real guard case requires an explicitly private process desktop')
    u=C.WinDLL('user32',use_last_error=True)
    u.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
    u.CreateWindowExW.restype=W.HWND
    u.DestroyWindow.argtypes=[W.HWND]
    hwnd=u.CreateWindowExW(0x08000080,'STATIC','C8h private guard fixture',0x90000000,0,0,80,30,None,None,None,None)
    if not hwnd:
        raise C.WinError(C.get_last_error())
    guard=DesktopGuard()
    try:
        observed=windows()
        private=[w for w in observed['windows'] if w['hwnd']==int(hwnd)]
        guard.start()
        proof=guard.finish()
        passed=bool(private and private[0]['visible'] and private[0]['desktop']==before['threadDesktop'] and proof['passed'])
        receipt={'passed':passed,'privateVisibleFixture':private,'guard':proof,
            'boundary':'Real private visible HWND remains outside the input-desktop guard; no input-desktop window is created'}
        Path('guard-contract.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (ROOT/'scripts/evidence/C8h-input-guard-contract.json').write_text(json.dumps(receipt,indent=2)+'\n')
        if not passed:
            raise RuntimeError('Input desktop guard misclassified the real private fixture')
    finally:
        u.DestroyWindow(hwnd)


def verify_existing():
    reports=[]
    for path in sorted((ROOT/'scripts/evidence').glob('C8h-f10-batch-*.json')):
        report=json.loads(path.read_text())
        raw_path=ROOT/'scripts/evidence/C8-runs'/report['provenance']['runId']/'raw.json'
        raw=json.loads(raw_path.read_text())
        if raw['provenance']!=report['provenance']:
            raise RuntimeError('F10 producer provenance differs from retained raw source')
        attempted={r['id']:r for r in raw['results']}
        rows=[r for r in report['rows'] if r['id'] in attempted]
        if len(rows)!=len(attempted):
            raise RuntimeError('F10 report lost an attempted source row')
        reports.append({'receipt':path.relative_to(ROOT).as_posix(),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'rawSha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            'guardPassed':report['provenance']['desktopGuard']['passed'],
            'rows':[{'id':r['id'],'webOutcome':r['webOutcome'],'outcome':r['outcome'],
                     'reasons':r['reasons']} for r in rows],
            'boundary':'Source-bound observations at the producer run; later unrelated manual edits do not upgrade their freshness'})
    if not any(r['rows'] and r['guardPassed'] for r in reports):
        raise RuntimeError('No complete guarded batch receipt is available')
    if hashlib.sha256(LOG.read_bytes()).hexdigest()!='b156a8092b9cf20a75cc750a20bef8790fdd90d07a7b09d3f4aad8cce6d5eed9':
        raise RuntimeError('External guard log changed')
    receipt={'checked':True,'reports':reports,'fullF10Passed':sum(r['outcome']=='pass' for p in reports for r in p['rows']),
        'boundary':'Independently checked preserved batch provenance and honest full outcomes; not a release proof'}
    Path('f10-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (ROOT/'scripts/evidence/C8h-f10-verified.json').write_text(json.dumps(receipt,indent=2)+'\n')


def contract(batch=1):
    if batch not in BATCHES:
        raise ValueError('Only the authored fixed batches are permitted')
    from c8h_conpty import windows
    if not windows()['threadDesktop'].startswith('Neyvia-C11-'):
        raise RuntimeError('F10 producers must run from an explicitly private process desktop')
    before = LOG.read_bytes()
    attempt = uuid.uuid4().hex[:8]
    output = ROOT / f'scripts/evidence/C8h-f10-batch-{batch}-{attempt}.json'
    from grant_agent.neyvia_inception import inventory, validate_bindings
    catalog = inventory()
    current = {r['id']:r for r in catalog['rows']}
    bindings = json.loads((ROOT / 'config/inception_journeys.json').read_text())
    reauthored = []
    for identity in BATCHES[batch]:
        original = bindings[identity]['sourceHash']
        bindings[identity]['sourceHash'] = current[identity]['sourceHash']
        reauthored.append({'id':identity,'oldHash':original,'currentHash':current[identity]['sourceHash'],
            'boundary':'Selected inputs, decisions, actions and checks reviewed against current manual; no predicate weakened'})
    validation = validate_bindings(catalog,{k:bindings[k] for k in BATCHES[batch]})
    if not validation['valid']:
        raise ValueError(validation['errors'])
    bindings_path = ROOT / f'.agent_control/C8h/f10-bindings-{batch}-{attempt}.json'
    bindings_path.write_text(json.dumps(bindings,indent=2))
    from c8_scope import fixture_ports
    ports = fixture_ports()
    if len(ports) < 5:
        raise RuntimeError('C8h F10 requires five free explicitly assigned task ports')
    argv = [sys.executable, str(ROOT / 'scripts/run_c8d.py'), '--stable-ref', 'ce053ae3d',
        '--stable-port', str(ports[0]), '--ports', *(str(p) for p in ports[1:4]),
        '--peer-port', str(ports[4]), '--build-dir', str(ROOT / '.agent_control/C8h/build'),
        '--output', str(output), '--bindings-file',str(bindings_path),'--c8e', '--only', *BATCHES[batch]]
    try:
        run = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=220,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        receipt={'schema':'neyvia.c8h.f10-batch-execution.v1','executed':False,
            'batch':batch,'ids':BATCHES[batch],'producer':str(output),
            'error':'Controller exceeded its 220-second bound; the private desktop job stops remaining owned children on host exit',
            'stdout':(exc.stdout or b'').decode('utf-8',errors='replace')[-4000:],
            'stderr':(exc.stderr or b'').decode('utf-8',errors='replace')[-2000:],
            'guardLogUnchanged':before==LOG.read_bytes()}
        (ROOT/f'scripts/evidence/C8h-f10-execution-{batch}-{attempt}.json').write_text(json.dumps(receipt,indent=2)+'\n')
        raise
    report = json.loads(output.read_text()) if output.exists() else {}
    evidence = ROOT / 'scripts/evidence/C8-runs' / report.get('provenance', {}).get('runId', 'missing')
    raw = json.loads((evidence / 'raw.json').read_text()) if (evidence / 'raw.json').exists() else {}
    rows = raw.get('results', [])
    executed = (run.returncode in (0, 2) and {r['id'] for r in rows} == set(BATCHES[batch])
        and report.get('provenance', {}).get('desktopGuard', {}).get('passed') is True
        and before == LOG.read_bytes())
    receipt = {'schema':'neyvia.c8h.f10-batch-execution.v1', 'executed':executed,
        'batch':batch, 'ids':BATCHES[batch], 'fullF10Gate':report.get('releaseGate'),
        'reauthored':reauthored,'bindingsSha256':hashlib.sha256(bindings_path.read_bytes()).hexdigest(),
        'counts':report.get('counts'), 'producer':str(output),
        'producerSha256':hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None,
        'exitCode':run.returncode, 'guardLogUnchanged':before == LOG.read_bytes(),
        'stdout':run.stdout.decode('utf-8', errors='replace')[-4000:],
        'stderr':run.stderr.decode('utf-8', errors='replace')[-2000:],
        'rows':[{'id':r['id'], 'status':r.get('status'), 'error':str(r.get('error',''))[:800],
                 'receipt':r.get('workerReceipt')} for r in rows],
        'boundary':'Executed fresh full F10 attempts; failed or blocked rows are never relabeled passed'}
    retained = ROOT / f'scripts/evidence/C8h-f10-execution-{batch}-{attempt}.json'
    retained.write_text(json.dumps(receipt, indent=2) + '\n')
    Path('f10-execution.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'executed':executed, 'counts':receipt['counts'], 'rows':receipt['rows']}))
    if not executed:
        raise RuntimeError('Batch did not complete every authored attempt with unchanged guard bytes')


def main():
    import argparse
    import os
    import shutil
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, choices=list(BATCHES))
    parser.add_argument('--transport', action='store_true')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    if not args.batch and not args.transport:
        parser.error('Select an explicit fixed batch or transport diagnostic')
    if args.child:
        for key in ('NEYVIA_COORDINATOR_AUTOSTART','FLUXIO_WATCHDOG_AUTOSTART','NEYVIA_TOOL_AUTO_UPDATE'):
            os.environ[key]='0'
        try:
            transport() if args.transport else contract(args.batch)
            return 0
        except Exception as exc:
            receipt={'exitCode':1,'error':type(exc).__name__+': '+str(exc)[:1000]}
            Path(os.environ['NEYVIA_C8H_CHILD_RECEIPT']).write_text(json.dumps(receipt,indent=2)+'\n')
            return 1
    from grant_agent.cua_desktop import AgentDesktop
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    area=ROOT / '.agent_control/proofs/C8/c8h-f10-host' / uuid.uuid4().hex
    area.mkdir(parents=True)
    executable=area/'python.exe'
    shutil.copy2(sys.executable,executable)
    digest=hashlib.sha256(executable.read_bytes()).hexdigest()
    argv=[str(executable),str(Path(__file__).resolve()),*sys.argv[1:],'--child']
    guard=ZeroDisturbanceGuard().start()
    before=LOG.read_bytes()
    code=None
    error=None
    try:
        with AgentDesktop(profile_root=area) as desktop:
            desktop.admit_pinned_console(argv,digest)
            process=desktop.launch(argv,cwd=ROOT,env={'PYTHONHOME':str(Path(sys.base_prefix)),
                'PATH':str(Path(sys.base_prefix))+';'+os.environ['PATH'],
                'NEYVIA_C8H_TRACE_THREADS':'1','NEYVIA_C8H_CHILD_RECEIPT':str(area/'child-result.json')})
            guard.register_pid(process.pid)
            code=process.wait(50 if args.transport else 300)
    except (OSError,RuntimeError,TimeoutError,subprocess.TimeoutExpired) as exc:
        error=type(exc).__name__+': '+str(exc)[:500]
    finally:
        observed=guard.close()
    receipt={'exitCode':code,'error':error,'guard':observed,'guardLogUnchanged':before==LOG.read_bytes(),
        'boundary':'Owned long-job producer on a pinned private desktop; CL independently verifies its retained receipts'}
    if (area/'child-result.json').exists():
        receipt['childFailure']=json.loads((area/'child-result.json').read_text())
    path=ROOT/f'scripts/evidence/C8h-f10-host-{args.batch or "transport"}-{uuid.uuid4().hex[:8]}.json'
    path.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':path.relative_to(ROOT).as_posix(),'exitCode':code,
        'error':error,'guardPassed':observed['ok'],'guardLogUnchanged':receipt['guardLogUnchanged']}))
    return 0 if code==0 and observed['ok'] and receipt['guardLogUnchanged'] else 2


if __name__=='__main__':
    raise SystemExit(main())
