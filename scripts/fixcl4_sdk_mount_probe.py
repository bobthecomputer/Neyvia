"""Actual SDK Phone iframe and CL proof through the owned Neyvia renderer."""
from __future__ import annotations
import hashlib,importlib.util,json,sys,time
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]

def sdk_extension(receipt,checks,cl,dom,ui,session,root,service,state):
    from grant_agent.app_sdk import new_app
    from grant_agent.neyvia_browser import service_for
    from grant_agent.cl.fixcl4_render_effects import observe
    browser=service_for(root)
    browser.request('headless.start',{'port':sdk_extension.pane_port,'allowLocalFixtures':True},owner=True)
    cl('sdk-phone-open','preparation','G: time.now()["unixSeconds"] > 0\napp.open(app="mobile-studio")\ndone()',session())
    time.sleep(2)
    dom('''() => { const button=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Skip setup');if(button)button.click();return true; }''')
    for _ in range(80):
        if dom('() => !document.querySelector(".nx-onb-scrim")'):break
        time.sleep(.25)
    checks['sdk.setupDismissed']=dom('() => !document.querySelector(".nx-onb-scrim")')
    app=root/'mounted-sdk-app';new_app(root,{'path':str(app),'name':'Mounted actual SDK','kind':'web'})
    token=session()
    source='G: time.now()["unixSeconds"] > 0\nrun local-browser-sdk.app_sdk-preview(project='+json.dumps(str(app))+',device="iphone-16-pro",port='+str(sdk_extension.backend_port)+')\ndone()'
    result=cl('sdk-mounted','positive',source,token)
    checks['sdk.previewActualPositiveCL']=result.get('ok') is True
    receipt['sdkOwner']=service.bus.get('app:mobile')
    receipt['sdkActualShell']=observe(service.bus)
    from grant_agent.app_sdk import AppBrowser,descriptor
    observed_frame=receipt['sdkActualShell'].get('dom',{}).get('phone',{}).get('frames',[])
    checks['sdk.exactMountedFrame']=len(observed_frame)==1 and '/api/ui/mobile-preview/' in observed_frame[0]['src']
    if len(observed_frame)!=1:raise ValueError('Exactly one actual mounted Phone frame required')
    observed_app=AppBrowser(observed_frame[0]['src'],root=root)
    try:
        receipt['sdkSameUrlActualDOM']=observed_app.observe()
        receipt['sdkSameUrlIdentity']=observed_app.sdk('identity')
        receipt['sdkSameUrlState']=observed_app.sdk('state')
        checks['sdk.sameUrlRealDOMAndSDKIdentity']=('Count:' in receipt['sdkSameUrlActualDOM']['text'] and receipt['sdkSameUrlIdentity']==descriptor(app)['instance'])
    finally:observed_app.close()
    receipt['directFrameBoundary']='Obscura opaque-frame CDP evaluation times out; same-URL SDK identity/state are observed in a separate owned Obscura context, and the actual mounted frame is captured as native pixels.'
    # The direct child realm is the product. A separate same-URL context above
    # remains supplemental and cannot establish the mounted app's controls.
    try:
        dom('''() => {const frame=document.querySelector('.nx-ms-phone iframe');
          delete frame.__nxSdkControl;
          frame.contentWindow.postMessage({source:'nx-studio',type:'sdk-control',action:'increment',id:'fixcl7-increment'},'*');return true;}''')
        report=None
        for _ in range(100):
            report=dom('() => document.querySelector(".nx-ms-phone iframe")?.__nxSdkControl || null')
            if report:break
            time.sleep(.1)
        if not report:raise RuntimeError('Mounted child did not report its actual button action')
        receipt['sdkMountedInteraction']={'before':{'identity':report['instance'],'state':report['before']},
            'after':{'identity':report['instance'],'state':report['after'],'text':report['text']}}
        interaction=receipt['sdkMountedInteraction']
        checks['sdk.actualMountedControlChangesState']=(interaction['before']['identity']==descriptor(app)['instance']
            and interaction['after']['state']['count']==interaction['before']['state']['count']+1
            and 'Count:' in interaction['after']['text'])
        receipt['directFrameBoundary']='Identity, text and increment are observed in the actual mounted Phone child realm; the native screenshot captures that same frame.'
    except Exception as error:
        receipt['sdkMountedInteractionError']=str(error)
        checks['sdk.actualMountedControlChangesState']=False
    receipt['sdkNativeVisibility']=dom('''() => {
      const phone=document.querySelector('.nx-ms-phone');if(!phone)return {visible:false};
      phone.scrollIntoView({block:'center',inline:'center'});
      const box=phone.getBoundingClientRect(), stage=document.querySelector('.nx-stage')?.getBoundingClientRect();
      const left=Math.max(0,box.left,stage?.left||0),right=Math.min(innerWidth,box.right,stage?.right||innerWidth);
      const top=Math.max(0,box.top,stage?.top||0),bottom=Math.min(innerHeight,box.bottom,stage?.bottom||innerHeight);
      const hit=right>left&&bottom>top?document.elementFromPoint((left+right)/2,(top+bottom)/2):null;
      return {visible:!!hit?.closest('.nx-ms-phone'),left:box.left,top:box.top,width:box.width,height:box.height,hit:hit?.tagName,hitClass:hit?.className};
    }''')
    checks['sdk.nativePhoneActuallyVisible']=receipt['sdkNativeVisibility']['visible'] is True
    screenshot=REPO/'scripts/evidence'/f'{sdk_extension.wave}-sdk-phone.png'
    ui(lambda:state['page'].screenshot(path=str(screenshot)))
    receipt['screenshot']={'path':str(screenshot),'sha256':hashlib.sha256(screenshot.read_bytes()).hexdigest()}
    from PIL import Image
    box=dom('''() => {const b=document.querySelector('.nx-ms-phone iframe').getBoundingClientRect();return {left:b.left,top:b.top,width:b.width,height:b.height};}''')
    with Image.open(screenshot) as native:
        crop=native.convert('RGB').crop((int(box['left']+box['width']*.1),int(box['top']+box['height']*.1),
                                       int(box['left']+box['width']*.9),int(box['top']+box['height']*.9)))
        colors=crop.getcolors(crop.width*crop.height) or []
    receipt['nativeAppPixelObservation']={'uniqueColors':len(colors),'sampledPixels':crop.width*crop.height,
        'boundary':'Actual central mounted iframe pixels, excluding hardware/status overlays; nonuniform pixels alone do not establish SDK content.'}
    checks['sdk.nativeAppPixelsPresent']=len(colors)>16
    receipt['sdkActualPhone']=dom('''() => { const p=document.querySelector('.nx-ms-phone'), f=p?.querySelector('iframe');return {mounted:!!p,width:p?.getBoundingClientRect().width,height:p?.getBoundingClientRect().height,src:f?.src,
      layout:['.nx-ms','.nx-ms-main','.nx-ms-stage','.nx-ms-phone-box'].map(s=>{const e=document.querySelector(s),b=e?.getBoundingClientRect();return {selector:s,width:b?.width,height:b?.height,clientHeight:e?.clientHeight,style:e?.getAttribute('style')};})}; }''')
    phone=receipt['sdkActualPhone'];checks['sdk.actualVisiblePhone']=phone['mounted'] and phone['width']>0 and phone['height']>0
    receipt['manualReceipts']=[row['payload'] for row in service.bus.since(0) if row['action']=='cl.manual.use']
    checks['sdk.currentManualEffectReceipt']=result.get('ok') is True and any(row.get('tool')=='neyvia.app_sdk.preview' and row.get('status')=='admitted' and row.get('effectChecks') for row in receipt['manualReceipts'])
    observation=root/'sdk-mounted-observation.json'
    observation.write_text(json.dumps({key.removeprefix('sdk.'):value for key,value in checks.items()
        if key.startswith('sdk.')},indent=2)+'\n',encoding='utf-8')
    contract=cl('sdk-mounted-contract','positive',
        'G: time.now()["unixSeconds"] > 0\nrun local-browser-sdk.prove-sdk-mounted-observation(observation='+json.dumps(str(observation))+')\ndone()',session())
    receipt['sdkMountedManualContract']=contract
    checks['sdk.mountedObservationManualContract']=contract.get('ok') is True
    path=app/'www/sdk.js';raw=path.read_bytes();path.write_bytes(raw+b'\n// source drift actual mounted SDK\n')
    checks['sdk.changedSourceRefusesDone']=cl('sdk-mounted','sourceDrift','done()',token).get('ok') is False
    path.write_bytes(raw)
    checks['sdk.restoredSourceRevalidates']=cl('sdk-mounted','sourceRestored','done()',token).get('ok') is True
    dom('''() => { const veil=document.createElement('div');veil.id='fixcl-sdk-veil';
      Object.assign(veil.style,{position:'fixed',inset:'0',zIndex:'2147483647',background:'#fff'});
      document.body.append(veil);return true; }''');time.sleep(2)
    checks['sdk.overlayVisibilityObserverWithdraws']=not any(row.get('visibility',{}).get('visible') for row in observe(service.bus).get('dom',{}).get('phone',{}).get('frames',[]))
    checks['sdk.occludedFrameRefusesDone']=cl('sdk-mounted','occluded','done()',token).get('ok') is False
    dom('() => { document.getElementById("fixcl-sdk-veil").remove();return true; }');time.sleep(2)
    checks['sdk.uncoveredVisibilityObserverReturns']=any(row.get('visibility',{}).get('visible') for row in observe(service.bus).get('dom',{}).get('phone',{}).get('frames',[]))
    checks['sdk.uncoveredFrameRevalidates']=cl('sdk-mounted','uncovered','done()',token).get('ok') is True
    dom('() => { location.href="about:blank"; return true; }');time.sleep(3)
    checks['sdk.unmountedRuntimeRefusesDone']=cl('sdk-mounted','unmounted','done()',token).get('ok') is False
    receipt['sdkMountedReady']=all(value is True for key,value in checks.items() if key.startswith('sdk.'))

def main():
    existing=REPO/'scripts/fixcl3_renderer_probe.py'
    spec=importlib.util.spec_from_file_location('fixcl4_sdk_mount',existing);module=importlib.util.module_from_spec(spec)
    wave=sys.argv[sys.argv.index('--wave')+1] if '--wave' in sys.argv else 'FIXCL4'
    sdk_extension.wave=wave
    output=f'{wave}-sdk-mount.json'
    source=existing.read_text(encoding='utf-8').replace('FIXCL3-renderer-pdf.json',output).replace('(15 if args.pdf_only','(7 if args.pdf_only')
    source=source.replace("output_name = args.wave + '-renderer-pdf.json'", 'output_name = '+repr(output))
    # SDK verification opens several sequential private contexts. Reuse only
    # the last explicitly assigned IPC listener after earlier contexts close.
    source=source.replace("if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):\n                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)",
                          'listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)')
    source=source.replace('listener.bind((address, next(ipc_ports)))', 'listener.bind((address, next(ipc_ports, args.ipc_port[-1])))')
    source=source.replace('    start = hashes(sources)', '    sources[0:0] = [REPO / name for name in ("scripts/fixcl4_sdk_mount_probe.py", "src/grant_agent/app_sdk.py", "src/grant_agent/perception_browser.py")]\n    start = hashes(sources)')
    exec(compile(source,str(existing),'exec'),module.__dict__)
    module.pdf_extension=sdk_extension
    sdk_extension.backend_port=int(sys.argv[sys.argv.index('--backend-port')+1]);sdk_extension.pane_port=int(sys.argv[sys.argv.index('--pane-port')+1])
    if '--pdf-only' not in sys.argv:sys.argv.append('--pdf-only')
    code=module.main();path=REPO/'scripts/evidence'/output;receipt=json.loads(path.read_bytes())
    receipt['probeHash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt['ok']=code==0 and receipt.get('sdkMountedReady') is True;receipt['passed']=receipt['ok']
    path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return 0 if receipt['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
