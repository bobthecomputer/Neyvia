"""Run LAYAG live scene contracts in an owned headless browser; no test framework."""
import json
from pathlib import Path
import statistics
import time

ROOT=Path(__file__).resolve().parents[2]


from contextlib import contextmanager


@contextmanager
def _obscura(port=None):
    """The admitted headless Obscura engine over CDP (no Chrome/Edge, no window)."""
    import os
    import secrets
    if port is None:
        port = int(os.environ.get("NEYVIA_LAYAG_PORT", "49095"))
    import socket
    import subprocess
    import urllib.request
    from playwright.sync_api import sync_playwright
    from .laya_glance_gate import _admitted_engine
    exe, _ = _admitted_engine()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
    token = secrets.token_urlsafe(24)
    process = subprocess.Popen([str(exe), 'serve', '--host', '127.0.0.1', '--port', str(port), '--max-connections', '4'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                               env={**os.environ, 'OBSCURA_CDP_TOKEN': token, 'OBSCURA_ROTATE_PROFILE': '0'})
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                req = urllib.request.Request(f'http://127.0.0.1:{port}/json/version', headers={'Authorization': 'Bearer ' + token})
                urllib.request.urlopen(req, timeout=2).read()
                break
            except Exception:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError('Obscura did not start on port %d' % port)
                time.sleep(0.25)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', headers={'Authorization': 'Bearer ' + token}, timeout=20000)
            try:
                yield browser
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()


def observe():
    from .laya_glance import glance
    source=(ROOT/'src/grant_agent/perception_scene.js').read_text(encoding='utf-8')
    cases=[]
    with _obscura() as browser:
        context=browser.new_context()
        try:
            for theme in ('dark','light'):
                for width in (390,1280):
                    page=context.new_page()
                    page.set_viewport_size({'width':width,'height':800})
                    for kind,broken,fixed in (
                        ('clipped-text','width:35px;overflow:hidden;text-align:center','width:160px;overflow:visible'),
                        ('unreadable-contrast','color:#777;background:#777','color:#111;background:#fff'),
                        ('off-screen-control',f'position:fixed;left:{width-10}px;width:100px','width:100px'),
                    ):
                        for phase,style in (('before',broken),('after',fixed)):
                            page.set_content(f'<html><title>{kind}</title><body style="background:{"#111" if theme=="dark" else "#fff"}"><button style="{style}">Readable label</button></body></html>')
                            scene=page.evaluate(source,{})
                            result=glance(scene)
                            detected=kind in {b['type'] for b in result['bugs']}
                            cases.append({'type':kind,'theme':theme,'width':width,'phase':phase,'detected':detected,'expected':phase=='before','ms':result['ms']})
                    for phase in ('before','after'):
                        page.set_content('<title>PDF canvas contract</title><div class="nx-pdf-page"><canvas data-content-expected width="300" height="300"></canvas></div>')
                        page.evaluate("(fixed)=>{const c=document.querySelector('canvas').getContext('2d');c.fillStyle='black';c.fillRect(0,0,300,300);if(fixed){c.fillStyle='white';c.fillRect(0,0,300,300);c.fillStyle='black';c.font='24px sans-serif';c.fillText('A real rendered page',15,40);}}",phase=='after')
                        result=glance(page.evaluate(source,{}))
                        cases.append({'type':'blank-render','theme':theme,'width':width,'phase':phase,
                                      'detected':'blank-render' in {b['type'] for b in result['bugs']},'expected':phase=='before','ms':result['ms']})
                    for kind,before,after in (
                        ('raw-error','TypeError: cannot read properties','Could not open the file. Retry'),
                        ('encoded-path','raw?path=D%3A%5Cprivate%5Cdocument.pdf','document.pdf'),
                        ('internal-id','Editor browser-null','Browser editor'),
                    ):
                        for phase,text in (('before',before),('after',after)):
                            page.set_content('<title>Visible text</title><p></p>')
                            page.locator('p').evaluate('(e,t)=>e.textContent=t',text)
                            result=glance(page.evaluate(source,{}))
                            cases.append({'type':kind,'theme':theme,'width':width,'phase':phase,'detected':kind in {b['type'] for b in result['bugs']},'expected':phase=='before','ms':result['ms']})
                    for kind in ('see-through','overlap'):
                        for phase in ('before','after'):
                            if kind=='see-through':
                                bg='transparent' if phase=='before' else 'white'
                                page.set_content(f'<title>Panel</title><div style="position:absolute;left:10px;top:10px;width:300px;height:150px">Behind text</div><div role="dialog" style="position:absolute;left:10px;top:10px;width:300px;height:150px;background:{bg}">Panel text</div>')
                            else:
                                left=20 if phase=='before' else 180
                                page.set_content(f'<title>Siblings</title><div><span style="position:absolute;left:10px;top:10px">First label</span><span style="position:absolute;left:{left}px;top:10px">Second label</span></div>')
                            result=glance(page.evaluate(source,{}))
                            cases.append({'type':kind,'theme':theme,'width':width,'phase':phase,'detected':kind in {b['type'] for b in result['bugs']},'expected':phase=='before','ms':result['ms']})
                    page.close()
        finally:
            context.close()
    shared=shared_core()
    result={'passed':all(c['detected']==c['expected'] for c in cases) and all(shared.values()),'sharedCore':shared,'cases':cases,
            'count':len(cases),'judgeMedianMs':statistics.median(c['ms'] for c in cases),
            'engine':'admitted Obscura (headless, CDP)',
            'boundary':'Owned headless DOM/canvas contract fixtures, not proof of the mounted Neyvia app'}
    return result


def shared_core():
    """Same real state transition, judge and store used by every domain adapter."""
    import copy
    import tempfile
    import uuid
    from .scene_core import Adapter,register,transcribe,judge,improve,episode
    from .laya_instant import store
    domain='contract-'+uuid.uuid4().hex[:12]
    def observe(source):
        return {'surface':'contract','nodes':[{'id':'object','kind':'object','attributes':{},
                 'measurements':{'defects':source.get('defects')},'relations':{}}],
                 'metrics':{'quality':source['quality']}}
    rules=[{'id':'bad-object','condition':{'field':'measurements.defects','op':'gt','value':0},
            'severity':'error','evidence':['measurements.defects'],'fix':{'action':'repair','arguments':{}}}]
    def fix(source,finding):
        source['defects']=0
        if source.get('regress'):source['quality']-=1
    def restore(source,snapshot):
        source.clear();source.update(snapshot)
    register(domain,Adapter(observe,lambda:rules,{'repair':fix},copy.deepcopy,restore))
    facts={}
    parent=ROOT/'.agent_control/layag-contracts'
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='scene-',dir=parent) as temp:
        original={'defects':1,'quality':10}
        scene=transcribe(domain,original)
        result=judge(scene)
        facts['predicatePointsToNode']=result['findings'][0]['node']=='object'
        facts['unknownAbstains']=not judge(transcribe(domain,{'quality':10}))['admitted']
        tampered=copy.deepcopy(scene);tampered['nodes'][0]['measurements']['defects']=0
        try:
            judge(tampered)
            facts['tamperRefused']=False
        except ValueError:
            facts['tamperRefused']=True
        budget={'max_steps':1,'max_seconds':30,'allowed_fixes':['repair'],'guards':{'quality':'min'}}
        accepted=improve(domain,original,budget,root=temp)
        facts['keepsImprovement']=accepted['steps'][0]['status']=='kept' and original=={'defects':0,'quality':10}
        bad={'defects':1,'quality':10,'regress':True}
        rejected=improve(domain,bad,budget,root=temp)
        facts['restoresRegression']=rejected['steps'][0]['status']=='reverted' and bad['defects']==1 and bad['quality']==10
        episode(temp,scene,'broken','Human labelled example','explicit')
        data={'nodes':[{k:n.get(k,{}) for k in ('kind','attributes','measurements')} for n in scene['nodes']]}
        first=store(temp).query('scene:'+domain,data)
        episode(temp,scene,'fine','Human correction','explicit')
        second=store(temp).query('scene:'+domain,data)
        facts['instantCorrection']=first['answer']=='broken' and second['answer']=='fine'
        facts['noHead']=not list(Path(temp).rglob('*head*.json'))
        facts['receiptsPersist']=len(list((Path(temp)/'.neyvia/laya/improve').glob('*.json')))==2
    return facts
