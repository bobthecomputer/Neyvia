"""Fresh native browser journeys in the registered host, never receipt replay."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import os
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
IDS={'control.neyvia-live-action','a.factory-notes-ui','a.factory-guided-ui','proofs-b.browser.blocked-receipt','proofs-b.browser.capacity-label','proofs-b.browser.capacity-explanation','native.tools.annotation','native.worker.reuse','livecontrol.provider-dom','livecontrol.hermes-dom','livecontrol.cli-browser-option','livecontrol.browser-failure-truth'}

def run_observed(root,contracts,categories,live_observations):
    spec=importlib.util.spec_from_file_location('c7d_native_browser',REPO/'scripts/prove_C7d_browser.py')
    driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
    exe=REPO/'.agent_control/C7d/browser-proof.exe'
    if not exe.is_file(): raise ValueError('Build the owned native browser probe offline first')
    from .proof_contracts import source_digest
    build=json.loads((REPO/'scripts/evidence/C7d-native-build.json').read_text(encoding='utf-8'))
    if not build['ok'] or not build['offline'] or build['exeSha256']!=hashlib.sha256(exe.read_bytes()).hexdigest() or any(source_digest(REPO/p)!=sha for p,sha in build['sourceBindings'].items()):
        raise ValueError('Owned native executable is not bound to current production browser source')
    rows=[]
    original=dict(os.environ)
    try:
        for category in categories:
            witnesses={}
            def captured(identity,actual_category,reader,guard):
                if identity not in {'native.tools.annotation','native.worker.reuse'} or actual_category!=category:raise ValueError('Unknown native capture binding')
                if identity not in witnesses:
                    witnesses[identity]=live_observations.capture(contracts[identity],category,reader,guard)
            def observed(identity,actual_category,reader,guard,proof_scope='rendered'):
                if identity not in contracts or actual_category!=category: raise ValueError('Unknown live case binding')
                row={'id':'c7d.native-rendered.'+identity+'.'+category,'contracts':[identity],'category':category,'status':'passed','proofScope':proof_scope,
                     'boundary':'Fresh production Neyvia Search/WebView2 DOM actions, downloads, persisted app exports or durable Harness UI; private desktop guarded throughout',
                     'detail':{'receipt':str(root/(category+'.json'))}}
                if proof_scope=='rendered':
                    live_observations.record(contracts[identity],category,row,reader,guard)
                elif identity=='livecontrol.browser-failure-truth' and proof_scope=='local_semantic':
                    row['boundary']='Actual production HTTP login retained after native DOM refusal; all unobserved claims remain skipped'
                else:raise ValueError('Unsupported native proof scope')
                rows.append(row)
            from .proof_ports import c7_port_block
            ports = c7_port_block(int(os.environ['NEYVIA_C7_PORT']))
            backend_port, vite_port = (48746,48747) if ports[0] == 48741 else ports[-2:]
            report=driver.main(['--backend-port',str(backend_port),'--vite-port',str(vite_port),'--native-exe',str(exe),'--category',category,'--output',str(root/(category+'.json'))],observed=observed,captured=captured)
            if not report['ok'] or not report['sourceStable'] or report['desktopGuard']['ownedVisibleWindows']:
                raise ValueError('Native rendered family did not complete safely')
            if set(witnesses)!={'native.tools.annotation','native.worker.reuse'}:raise ValueError('Worker did not expose actual owned live capture contexts')
            for identity,token in witnesses.items():
                row={'id':'c7d.native-rendered.'+identity+'.'+category,'contracts':[identity],'category':category,'status':'passed','proofScope':'rendered','boundary':'Actual production persistent worker and native capture context observed while alive; admitted only after real PNG artifacts, W3C geometry, counters and owned resource closure passed','detail':{'receipt':str(root/(category+'.json'))}}
                live_observations.admit(contracts[identity],category,row,token)
                rows.append(row)
            os.environ.clear();os.environ.update(original)
    finally:
        os.environ.clear();os.environ.update(original)
    if len(rows)!=len(categories)*len(IDS): raise ValueError('Native rendered obligation disappeared')
    return rows

def run(root,contracts,categories):
    raise ValueError('Use the registered campaign live-observation host for rendered proof')

def blocker(contract,category):
    if contract['id'] in IDS:
        return {'kind':'fixture_gap','reason':'This exact invariant requires fresh production native browser observations in the current campaign; saved hashes and frontend models are insufficient.'}
