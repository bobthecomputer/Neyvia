"""Real disposable Windows observe/action/check proof. No private app contents."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cua_native import NativeWorker


def run():
    raise RuntimeError("Historical input-desktop runner disabled. Use scripts/spike_c11_desktop.py")
    scratch=ROOT/'.agent_control/c1c-native'/str(time.time_ns())
    scratch.mkdir(parents=True)
    state=scratch/'window.txt'
    framework=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
    binary=scratch/'C1cNativeProbe.exe'
    source=ROOT/'tools/cua-driver-win/c1-probe.cs'
    subprocess.run([str(framework/'csc.exe'),'/nologo','/target:winexe','/out:'+str(binary),str(source),
        '/reference:'+str(framework/'System.Windows.Forms.dll'),'/reference:'+str(framework/'System.Drawing.dll')],
        capture_output=True,check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    worker=NativeWorker();proc=None
    receipt={'schema':'neyvia.c1c.native-proof.v1','boundary':'Own no-activate disposable WinForms window; installed-app cohort is separate',
        'runs':[],'ok':False,'sourceSha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'src/grant_agent/cua_fast.py','src/grant_agent/cua_native.py','tools/cua-driver-win/c1-probe.cs','scripts/prove_c1c_native.py')}}
    def compact(result):
        return {k:result.get(k) for k in ('mechanism','effect','elapsedMs','foregroundPreserved','cursorPreserved','preservationObservable','noRetry')} | {
            'check':result.get('check',{}).get('status'),'source':result.get('observation',{}).get('source'),
            'events':result.get('observation',{}).get('events'),'eventsSubscribed':result.get('observation',{}).get('eventsSubscribed')}
    try:
        receipt['desktop']=worker.request('desktopStatus',timeout=30)
        worker.request('windows')
        # Worker initialization is separate from first observation of the window.
        worker.fast_client.uia.ready.wait(5)
        proc=subprocess.Popen([str(binary),str(state)],creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+20
        while not state.exists() and time.monotonic()<deadline:time.sleep(.02)
        if not state.exists():raise RuntimeError('Owned window launch deadline')
        h=state.read_text().strip(); window=worker.request('window',{'windowId':h})
        if window['pid']!=proc.pid:raise RuntimeError('Owned window PID mismatch')
        start=time.perf_counter()
        observed=worker.request('inspect',{'windowId':h,'maxNodes':256,'maxDepth':12})
        receipt['firstObservation']={'elapsedMs':(time.perf_counter()-start)*1000,'source':observed['source'],
            'degradedReason':observed.get('degradedReason'),'nodes':len(observed['tree'])}
        receipt['uiaInitializationError']=worker.fast_client.uia.error
        receipt['observedControls']=[{k:r.get(k) for k in ('name','role','patterns','isPassword')} for r in observed['tree']]
        for repeat in range(12):
            observed=worker.request('inspect',{'windowId':h,'maxNodes':256,'maxDepth':12})
            edits=[r for r in observed['tree'] if r['role']=='Edit' and r['name']=='Task input' and not r['isPassword']]
            buttons=[r for r in observed['tree'] if r['role']=='Button' and r['name']=='Apply']
            if len(edits)!=1 or len(buttons)!=1:raise RuntimeError('Unique safe controls unavailable')
            value='C1c verified '+str(repeat)
            actions=[]
            for args in ({'elementId':edits[0]['id'],'action':'value','text':value,
                'expect':[{'selector':{'id':edits[0]['id']},'value_equals':value}]},
                {'elementId':buttons[0]['id'],'action':'click',
                 'expect':[{'selector':{'role':'Text','name':'Applied: '+value},'name_contains':value}]}):
                start=time.perf_counter()
                result=worker.request('cycle',{'windowId':h,'maxNodes':256,'maxDepth':12,**args})
                item=compact(result);item['roundTripMs']=(time.perf_counter()-start)*1000;actions.append(item)
            written=state.with_name('window.txt.result').read_text()
            passed=all(a['check']=='satisfied' for a in actions) and written=='Applied: '+value
            receipt['runs'].append({'edit':actions[0],'apply':actions[1],'fileEffect':written,'passed':passed})
            if not passed:raise RuntimeError('Native action/check/app-written file effect failed')
        observed=worker.request('inspect',{'windowId':h,'maxNodes':256,'maxDepth':12})
        receipt['eventJourney']={'source':observed['source'],'events':observed.get('events'),
            'eventsSubscribed':observed.get('eventsSubscribed'),'diff':observed.get('diff')}
        option=next(r for r in observed['tree'] if r['name']=='Include heading')
        receipt['toggle']=compact(worker.request('cycle',{'windowId':h,'elementId':option['id'],'action':'toggle',
            'expect':[{'selector':{'id':option['id']},'toggle_equals':1}]}))
        receipt['refusals']={}
        for label in ('Read-only fixture','API key','Password'):
            row=next(r for r in observed['tree'] if r['name']==label)
            if label in {'API key','Password'} and (not row['isPassword'] or 'value' in row):raise RuntimeError('Protected field disclosed')
            try:
                worker.request('action',{'windowId':h,'elementId':row['id'],'action':'value','text':'must not arrive'})
                raise RuntimeError('Protected fixture mutation accepted')
            except ValueError as exc:receipt['refusals'][label]=str(exc)
        values=sorted(r[k]['roundTripMs'] for r in receipt['runs'] for k in ('edit','apply'))
        def q(frac):
            pos=(len(values)-1)*frac;i=int(pos)
            return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(pos-i)
        receipt['atomicLatency']={'n':len(values),'p50Ms':q(.5),'p95Ms':q(.95),'includes':'NativeWorker.request cycle observe-action-fresh-check wall time'}
        receipt['uiaPatternJourneys']=all(r[k]['mechanism']=='uia.cachedPattern' for r in receipt['runs'] for k in ('edit','apply'))
        receipt['preservation']=all(r[k]['foregroundPreserved'] and r[k]['cursorPreserved'] for r in receipt['runs'] for k in ('edit','apply'))
        receipt['ok']=True
    except Exception as exc:receipt['error']=type(exc).__name__+': '+str(exc)
    finally:
        worker.close()
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=5)
        shutil.rmtree(scratch)
        (ROOT/'scripts/evidence/C1c-native.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt.get(k) for k in ('ok','error','firstObservation','atomicLatency','uiaPatternJourneys','preservation','eventJourney','uiaInitializationError')}))
    return receipt['ok']

if __name__=='__main__':sys.exit(0 if run() else 1)
