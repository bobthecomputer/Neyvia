"""Rendered T3 phone layout and T12 shared receipts in an owned Chrome profile."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit
import verify_follow_browser_authority as authority

REPO=Path(__file__).resolve().parents[1]
SCRATCH=REPO/".agent_control/follow-browser-render"
OUTPUT=REPO/"scripts/evidence/FOLLOW-browser-render.json"
BASE="http://127.0.0.1:48441"

def main():
    authority.SCRATCH=SCRATCH; authority.isolate()
    from playwright.sync_api import sync_playwright
    checks=[]; pictures=[]; blocked=[]; observations={}
    def check(name,passed):
        checks.append({"name":name,"passed":bool(passed)})
        assert passed,name
    with sync_playwright() as w:
        browser=w.chromium.launch(executable_path=str(authority.CHROME),headless=True,
            args=["--use-angle=swiftshader","--enable-unsafe-swiftshader"])
        context=browser.new_context(viewport={"width":390,"height":844},permissions=[])
        def route(r):
            u=urlsplit(r.request.url)
            if u.scheme in {"data","blob"} or (u.scheme=="http" and u.hostname=="127.0.0.1" and u.port==48441):r.continue_()
            else:blocked.append({"scheme":u.scheme,"host":u.hostname,"port":u.port});r.abort()
        context.route("**/*",route)
        def api(path,payload):
            response=context.request.post(BASE+path,data=payload)
            value=response.json(); assert response.ok,(path,response.status,value)
            return value
        def command(name,payload={}):return api("/api/backend",{"command":name,"payload":payload})["data"]
        def shot(name,locator=None):
            path=SCRATCH/(name+".png")
            if locator is None:page.screenshot(path=str(path),full_page=True)
            else:locator.screenshot(path=str(path))
            pictures.append({"path":str(path.relative_to(REPO)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        try:
            check("owned local authentication",api("/api/auth/local-session",{}).get("ok"))
            page=context.new_page(); page.goto(BASE+"/control?ui=next",wait_until="domcontentloaded")
            skip=page.get_by_role("button",name="Skip setup",exact=True)
            if skip.is_visible():skip.click()
            voice=page.get_by_role("button",name="Voice commands",exact=False)
            voice.wait_for(state="visible",timeout=20000)
            bounds=voice.bounding_box();observations["phoneVoiceBounds"]=bounds
            check("390px phone Voice button fully in viewport",bounds and bounds["x"]>=0 and bounds["y"]>=0 and bounds["x"]+bounds["width"]<=390 and bounds["y"]+bounds["height"]<=844)
            for _ in range(25):
                page.keyboard.press("Tab")
                if voice.evaluate("el=>el===document.activeElement"):break
            check("Voice reachable with keyboard Tab",voice.evaluate("el=>el===document.activeElement"))
            geometry="""el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect(),f=el.closest('footer').getBoundingClientRect(),e=parseFloat(s.outlineWidth)+parseFloat(s.outlineOffset);return {outline:s.outline,outlineWidth:parseFloat(s.outlineWidth),outlineOffset:parseFloat(s.outlineOffset),outlinedBounds:{top:r.top-e,bottom:r.bottom+e,left:r.left-e,right:r.right+e},footerBounds:{top:f.top,bottom:f.bottom,left:f.left,right:f.right},boxShadow:s.boxShadow,focusVisible:el.matches(':focus-visible'),name:el.getAttribute('aria-label')}}"""
            observations["voiceFocus"]=voice.evaluate(geometry)
            check("Voice has accessible label and visible keyboard focus",observations["voiceFocus"]["focusVisible"] and "Voice commands" in observations["voiceFocus"]["name"])
            def outline_fits(value,width):
                r,f=value["outlinedBounds"],value["footerBounds"]
                return r["top"]>=max(0,f["top"]) and r["bottom"]<=min(844,f["bottom"]) and r["left"]>=max(0,f["left"]) and r["right"]<=min(width,f["right"])
            check("390px Voice keyboard focus outline fits footer and viewport",outline_fits(observations["voiceFocus"],390))
            shot("phone-voice-focus")
            page.set_viewport_size({"width":320,"height":844});page.wait_for_timeout(250)
            for _ in range(25):
                page.keyboard.press("Tab")
                if voice.evaluate("el=>el===document.activeElement"):break
            observations["narrowPhoneVoiceFocus"]=voice.evaluate(geometry)
            check("320px Voice Tab focus outline fits footer and viewport",observations["narrowPhoneVoiceFocus"]["focusVisible"] and outline_fits(observations["narrowPhoneVoiceFocus"],320))
            shot("phone-320-voice-focus")
            page.set_viewport_size({"width":1440,"height":1000})
            opened=api("/api/ui/tools/call",{"tool":"neyvia.app.open","arguments":{"app":"playtest"}})
            check("bot opens actual Game Dev screen",opened.get("ok") and opened.get("data",{}).get("ok"))
            page.get_by_role("tablist",name="Editors").wait_for(timeout=20000)
            deadline=time.monotonic()+30;session=None
            while time.monotonic()<deadline:
                status=command("gamedev_status_command")
                session=next((s for s in status.get("sessions",[]) if s.get("engine")=="babylon" and s.get("status")=="connected"),None)
                if session:break
                page.wait_for_timeout(500)
            observations["gameSessions"]=status.get("sessions",[])
            check("actual browser WebGL scene connects its bridge",session is not None)
            session_id=session["sessionId"]
            actions=page.get_by_role("region",name="Actions",exact=True)
            actions.get_by_role("button",name="Edit",exact=True).click()
            form=page.get_by_role("form",name="Edit",exact=True)
            mesh_name="FOLLOW rendered box "+uuid.uuid4().hex[:8]
            form.get_by_label("Mesh",exact=True).fill(mesh_name)
            form.get_by_role("button",name="Edit",exact=True).click()
            form.wait_for(state="hidden",timeout=20000)
            ui_rows=command("gamedev_receipts_command",{"sessionId":session_id})["receipts"]
            ui_receipt=next(r for r in ui_rows if r.get("args",{}).get("name")==mesh_name)
            observations["uiCreateReceipt"]=ui_receipt
            check("rendered Edit form creates actual Babylon mesh",ui_receipt.get("status")=="succeeded" and ui_receipt.get("result",{}).get("selected")==mesh_name)
            shot("gamedev-real-webgl",page.frame_locator('iframe[title="Browser 3D scene editor"]').locator("#scene"))
            bot_id="render-inspect-"+uuid.uuid4().hex
            answer=api("/api/ui/tools/call",{"tool":"neyvia.gamedev.action","arguments":{"sessionId":session_id,"action":"inspect","requestId":bot_id}})
            check("bot action queues in shared production service",answer.get("ok") and answer.get("data",{}).get("ok"))
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                receipt=command("gamedev_receipt_command",{"requestId":bot_id})
                if receipt.get("status") in {"succeeded","failed"}:break
                page.wait_for_timeout(350)
            observations["botReceipt"]=receipt
            check("actual scene returns successful bot receipt",receipt.get("status")=="succeeded" and bool(receipt.get("result")))
            check("bot observes mesh created through actual UI",any(m.get("name")==mesh_name and m.get("vertices",0)>=8 for m in receipt.get("result",{}).get("meshes",[])))
            log=page.get_by_role("region",name="Action log")
            log.get_by_text("Inspect",exact=True).wait_for(timeout=12000)
            log.locator("summary").first.click()
            check("rendered log contains exact bot receipt",log.get_by_text(bot_id,exact=True).is_visible())
            shot("gamedev-bot-action",log)
            error_id="render-error-"+uuid.uuid4().hex
            command("gamedev_action_command",{"sessionId":session_id,"action":"edit","args":{"op":"transform","name":"FOLLOW deliberately absent mesh","position":[0,0,0]},"requestId":error_id})
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                failed=command("gamedev_receipt_command",{"requestId":error_id})
                if failed.get("status") in {"succeeded","failed"}:break
                page.wait_for_timeout(350)
            observations["failureReceipt"]=failed
            check("actual runtime missing-mesh action fails truthfully",failed.get("status")=="failed" and "No mesh named" in failed.get("error",""))
            log.get_by_text("No mesh named FOLLOW deliberately absent mesh",exact=False).first.wait_for(timeout=12000)
            log.locator("summary").first.click()
            check("rendered failure contains exact error receipt",log.get_by_text(error_id,exact=True).is_visible())
            shot("gamedev-action-failure",log)
            screen=command("gamedev_state_command")
            observations["screenState"]=screen
            check("bot observes actual selected Game Dev screen",screen.get("ui",{}).get("source")=="ui" and screen["ui"].get("tab")=="babylon")
        finally:
            context.close();browser.close()
            report={"schema":"neyvia.FOLLOW.browser-render.v1","passed":bool(checks) and all(r["passed"] for r in checks),"checks":checks,"screenshots":pictures,"observations":observations,"blockedOrigins":blocked,"ownedBrowserClosed":True,"ports":{"backend":48441,"asyncioWake":48448},"boundary":"Installed Chrome headless with task-only profile and actual production HTTP/WebGL scene. Phone layout and keyboard focus only; no microphone/ASR starts, personal profiles, private pages, or native Godot/Unity/Roblox execution."}
            OUTPUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":True,"checks":len(checks),"screenshots":len(pictures)}))

if __name__=="__main__":main()
