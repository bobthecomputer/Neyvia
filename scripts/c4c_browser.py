"""C4c owned Obscura checks. No Chromium launch, fallback, or personal tabs.

Playwright is used solely as the existing Neyvia engine's CDP transport.
Rendered evidence and functional checks are separate from aesthetic judgement.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
ENGINE = Path(r"C:\Users\user\Projects\nx-c2-browser\.agent_control\C2d\obscura\obscura.exe")
URL = "https://devguide.python.org/versions/"

SNAPSHOT = r"""() => {
const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).display!=='none'};
const nodes=[...document.querySelectorAll('body *')].filter(e=>visible(e)&&e.childElementCount===0&&e.textContent.trim()&&!e.matches('script,style'));
const color=v=>{const a=(v.match(/[\d.]+/g)||[]).map(Number);return a.length>=3?a:null};
const luminance=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
const text=nodes.map(e=>{let bg=null,p=e;while(p&&!bg){let c=color(getComputedStyle(p).backgroundColor);if(c&&(c.length<4||c[3]===1))bg=c;p=p.parentElement}const s=getComputedStyle(e),fg=color(s.color),a=fg&&luminance(fg),b=bg&&luminance(bg);return {text:e.textContent.trim().slice(0,300),color:s.color,background:bg,contrast:a!=null&&b!=null?(Math.max(a,b)+.05)/(Math.min(a,b)+.05):null}});
const controls=[...document.querySelectorAll('button,input,select,[role=meter],progress')].map(e=>({tag:e.tagName,type:e.type,id:e.id,name:e.getAttribute('aria-label')||e.getAttribute('aria-labelledby')||e.textContent||e.labels?.[0]?.textContent,value:e.value,checked:e.checked,min:e.min,max:e.max,role:e.getAttribute('role'),ariaValue:e.getAttribute('aria-valuenow')}));
const card=document.querySelector('main,article,.card,.panel,.settings'),rect=card?.getBoundingClientRect();
return {text:document.body.innerText,controls,textContrast:text,card:rect&&{width:rect.width,x:rect.x},dark:matchMedia('(prefers-color-scheme: dark)').matches,bodyBackground:getComputedStyle(document.body).backgroundColor,viewport:{width:innerWidth,height:innerHeight}};
}"""


def _bounded(path):
    path = Path(path).resolve()
    if not path.is_relative_to(REPO) or path == REPO:
        raise ValueError("C4 browser fixture and receipts must stay below owned worktree")
    return path


def _start(destination, port):
    if port not in range(48731, 48739):
        raise ValueError("Explicit C4 fixture port 48731-48738 required; engine uses port+1")
    os.environ["NEYVIA_BROWSER_PROOF_PORTS"] = f"{port},{port+1}"
    from grant_agent.browser_obscura import ObscuraEngine
    return ObscuraEngine(destination / "engine", ENGINE, port=port+1, fixtures=True)


def check(task_id, root, destination, port):
    """Return objective UI checks and owned engine screenshots; retain failures."""
    root, destination = _bounded(root), _bounded(destination)
    destination.mkdir(parents=True, exist_ok=True)
    report = {"task":task_id,"passed":False,"checks":{},"screenshots":[],"modes":{},
              "engine":"obscura","enginePath":str(ENGINE),"limits":[
                  "Objective contrast and interaction checks do not establish aesthetic polish",
                  "Screenshots require separate visual inspection; Obscura differs from native WebView2"]}
    if task_id not in {"t1-ui","ui1-run-card","ui2-cost-settings"}:
        raise ValueError("Unsupported UI task")
    server = engine = None
    try:
        artifact = root / "index.html"
        report["artifactSha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        report["engineSha256"] = hashlib.sha256(ENGINE.read_bytes()).hexdigest()
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def translate_path(self, path):
                translated = Path(super().translate_path(path)).resolve()
                return str(translated) if translated.is_relative_to(root) else str(root / "__refused__")
        server = ThreadingHTTPServer(("127.0.0.1",port),functools.partial(Handler,directory=str(root)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        engine = _start(destination,port)
        engine.run("proof","open","proof",f"http://127.0.0.1:{port}/index.html")
        worker = engine.profiles["proof"]
        def run(fn):
            return worker.executor.submit(fn, worker.pages["proof"]["page"]).result(timeout=35)
        report["observation"] = engine.run("proof","observe","proof")
        run(lambda page:page.set_viewport_size({"width":1280,"height":1100}))
        errors=[]
        for mode in ("light","dark"):
            try:
                run(lambda page:page.emulate_media(color_scheme=mode))
                snap=run(lambda page:page.evaluate(SNAPSHOT))
                if mode=='dark' and not snap['dark']:
                    report['osThemeSwitchVerified']=False
                    report['unsupportedDarkEmulation']=snap
                    activation=run(lambda page:page.evaluate(r"""() => {let changed=0;for(const e of document.querySelectorAll('style')){const old=e.textContent;const next=old.replace(/@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)/gi,'@media all');if(next!==old){e.textContent=next;changed++}}return {changed,method:'Exact authored prefers-color-scheme:dark CSS condition replaced with @media all in disposable DOM only'}}"""))
                    report['authoredDarkActivation']=activation
                    snap=run(lambda page:page.evaluate(SNAPSHOT))
                    report['checks']['authored_dark_css_applied']=activation['changed']>0
                shot=destination / f"{mode}.png"
                run(lambda page:page.screenshot(path=str(shot),full_page=True,timeout=10000))
                report["screenshots"].append({"path":str(shot),"sha256":hashlib.sha256(shot.read_bytes()).hexdigest()})
                report["modes"][mode]=snap
                target_width={'t1-ui':360,'ui1-run-card':440,'ui2-cost-settings':480}[task_id]
                report['checks'][mode+'_specified_width']=abs((snap.get('card') or {}).get('width',0)-target_width)<=1
                report['checks'][mode+'_centered']=abs((snap.get('card') or {}).get('x',0)-(snap['viewport']['width']-target_width)/2)<=1
                report["checks"][f"{mode}_style_applied"]=snap["dark"]==(mode=="dark") or (mode=='dark' and report.get('authoredDarkActivation',{}).get('changed',0)>0)
                ratios=[x["contrast"] for x in snap["textContrast"]]
                report["checks"][f"{mode}_contrast_4_5"]=bool(ratios) and all(v is not None and v>=4.5 for v in ratios)
            except Exception as exc:
                errors.append({"mode":mode,"error":str(exc)})
        if errors:
            report["modeErrors"]=errors
        report["checks"]["two_rendered_modes"]=len(report["screenshots"])==2 and all(report["checks"].get(f"{m}_style_applied") for m in ("light","dark"))
        if report.get('osThemeSwitchVerified') is False:
            report["limits"].append("Obscura ignores CDP dark media emulation. Dark screenshot activates exact authored dark CSS in disposable DOM; automatic OS theme switching unverified")
        if task_id=="ui1-run-card":
            focus=run(lambda page:page.evaluate("""() => [...document.querySelectorAll('button')].map(e=>{e.focus();const s=getComputedStyle(e);return {name:e.textContent.trim(),focused:document.activeElement===e,outline:s.outline,boxShadow:s.boxShadow}})"""))
            report["focus"]=focus
            report["checks"]["real_named_buttons"]=any("Open changes" in e["name"] for e in focus) and any("Retry failed checks" in e["name"] for e in focus)
            report["checks"]["buttons_accept_focus"]=bool(focus) and all(e["focused"] for e in focus)
            report["limits"].append("Programmatic focus confirms focusability; visible keyboard focus requires screenshot review")
        elif task_id=="ui2-cost-settings":
            result=run(lambda page:page.evaluate(r"""() => {
const before=document.body.innerText, range=document.querySelector('input[type=range]'), toggle=document.querySelector('input[type=checkbox],[role=switch]'),select=document.querySelector('select'),radios=[...document.querySelectorAll('input[type=radio]')];
let model=false,budget=false,approval=false,bounds=false,details={};
if(select){const old=select.value, option=[...select.options].find(e=>e.value!==old);if(option){select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));model=select.value!==old;details.modelTextChanged=document.body.innerText!==before}}
else if(radios.length>=3){const old=radios.find(e=>e.checked),next=radios.find(e=>e!==old);next.click();model=next.checked&&(!old||!old.checked);details.modelTextChanged=document.body.innerText!==before}
if(range){const old=document.body.innerText;bounds=Number(range.min)===5&&Number(range.max)===100;range.value='65';range.dispatchEvent(new Event('input',{bubbles:true}));range.dispatchEvent(new Event('change',{bubbles:true}));budget=Number(range.value)===65&&document.body.innerText!==old&&document.body.innerText.includes('65');details.rangeAfter=range.value}
if(toggle){const old=toggle.checked,oldText=document.body.innerText;toggle.click();approval=typeof old==='boolean'?toggle.checked!==old:toggle.getAttribute('aria-checked')==='true';details.toggleTextChanged=document.body.innerText!==oldText}
return {model,budget,approval,bounds,details,after:document.body.innerText};} """))
            report["interaction"]=result
            report["checks"].update(model_selection=result["model"],model_display_updates=result["details"].get("modelTextChanged",False),budget_slider_updates=result["budget"],budget_bounds=result["bounds"],approval_toggles=result["approval"],approval_display_updates=result["details"].get("toggleTextChanged",False))
        else:
            # Substitute a high value in the owned HTTP response, rerunning the
            # submitted inline script naturally; never substitute its logic.
            source=artifact.read_text(encoding="utf-8-sig")
            light=report.get('modes',{}).get('light',{})
            meters=[e for e in light.get('controls',[]) if e.get('role')=='meter' or e.get('tag')=='PROGRESS']
            report['checks']['labeled_meter_values']=len(meters)==2 and all(e.get('name') for e in meters) and [float(e.get('ariaValue') or e.get('value') or 0) for e in meters]==[62,31]
            report['checks']['reset_text']=bool(re.search(r'1\s*h\s*48\s*min',light.get('text',''))) and bool(re.search(r'Thu\s*09:00',light.get('text','')))
            high=re.sub(r"(?<!\d)62(?!\d)","91",source)
            class HighHandler(Handler):
                def do_GET(self):
                    data=high.encode();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers();self.wfile.write(data)
            server.shutdown();server.server_close()
            server=ThreadingHTTPServer(("127.0.0.1",port),HighHandler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            engine.run("proof","reload","proof")
            after=run(lambda page:page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.childElementCount===0&&!e.matches('script,style')).map(e=>e.textContent).join(' ' )"))
            before=' '.join(x['text'] for x in report.get('modes',{}).get('light',{}).get('textContrast',[]))
            report["highUsage"]={"value":91,"before":before,"after":after}
            report["checks"]["above80_status_changes"]=high!=source and re.sub(r'\d','',before)!=re.sub(r'\d','',after) and bool(re.search(r"slow|pace|near|ease|careful",after,re.I))
        functional={k:v for k,v in report["checks"].items() if not any(k.startswith(m+'_') for m in ('light','dark')) and k not in {'two_rendered_modes','authored_dark_css_applied'}}
        report["functionalPassed"]=bool(functional) and all(functional.values())
        report["renderedPassed"]=report["checks"]["two_rendered_modes"] and all(report["checks"].get(f"{m}_contrast_4_5") for m in ('light','dark'))
        report["passed"]=all(report["checks"].values())
    except Exception as exc:
        report["blocker"]=f"{type(exc).__name__}: {exc}"
    finally:
        if engine:engine.close()
        if server:server.shutdown();server.server_close()
    (destination / "receipt.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def browse(artifact, destination, port):
    """Observe live supported Python branches through own Obscura engine."""
    artifact,destination=_bounded(artifact),_bounded(destination)
    destination.mkdir(parents=True,exist_ok=True)
    report={"passed":False,"engine":"obscura","sourceUrl":URL,"checks":{},"limits":[]}
    engine=None
    try:
        engine=_start(destination,port)
        from grant_agent.browser_obscura import ProfileWorker
        # Current engine's HTMLTableElement.rows is not iterable. Use the same
        # CDP/browser process and equivalent tr/th/td selectors for observation.
        class TableWorker(ProfileWorker):
            def _observe(self,tab_id):
                return self.pages[tab_id]["page"].evaluate("""() => ({url:location.href,text:document.body.innerText,tables:[...document.querySelectorAll('table')].map(t=>[...t.querySelectorAll('tr')].map(r=>[...r.querySelectorAll('th,td')].map(c=>c.innerText)))})""")
        engine.profiles["browse"]=TableWorker(engine.endpoint,engine.token,True,destination / "profile")
        observation=engine.run("browse","open","browse",URL)
        report["observation"]=observation
        table=next(t for t in observation["tables"] if t and len(t[0])>=5 and "branch" in t[0][0].lower())
        from verify_c4_browse import plain
        expected={plain(r[0]):[plain(c) for c in r[:5]] for r in table[1:] if len(r)>=5}
        text=artifact.read_text(encoding="utf-8-sig")
        rows=[[plain(c) for c in line.strip().strip('|').split('|')] for line in text.splitlines() if line.strip().startswith('|')]
        actual={r[0]:r for r in rows if len(r)==5 and (r[0]=='main' or re.fullmatch(r'3\.\d+',r[0]))}
        before2028=[branch for branch,row in expected.items() if re.search(r'202[0-7]',row[4])]
        prose=' '.join(line for line in text.splitlines() if not line.strip().startswith('|'))
        report["checks"]={"all_supported_rows":set(expected)==set(actual),"exact_cells":expected==actual,"source_cited":URL in text,
                          'eol_versions_in_prose':bool(before2028) and all(b in prose for b in before2028)}
        report['before2028']=before2028
        report["expectedRows"]=expected
        report["limits"].append("Own engine table selector compatibility adapter; live source observed, no answer key")
        report["passed"]=all(report["checks"].values())
    except Exception as exc:
        report["blocker"]=f"{type(exc).__name__}: {exc}"
    finally:
        if engine:engine.close()
    (destination / "receipt.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report
