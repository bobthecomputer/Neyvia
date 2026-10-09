"""GUI-track Obscura journeys on explicitly owned ports; no browser fallback."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import traceback
import time

REPO = Path(__file__).resolve().parents[1]
os.environ["NEYVIA_LAYA_AUTOSTART"] = "0"
sys.path[:0] = [str(REPO / "scripts"), str(REPO / "src")]
os.environ["NEYVIA_PLACEMENT_PORTS"] = ",".join(str(n) for n in range(48981,48990))
import placement_shots as shots
from grant_agent.browser_obscura import managed_executable

_placement_env = shots.isolated_env
def gui_env():
    env = _placement_env()
    # Reuse interpreter/worktree bytecode; a foreign prefix cold-compiles every
    # import and made owned health startup exceed its deadline after integration.
    env.pop("PYTHONPYCACHEPREFIX", None)
    env["NEYVIA_PROVISIONING_ROOT"] = str(shots.SMALL_STATE / "provisioning")
    return env
shots.isolated_env = gui_env


def capture_lab(rig, theme, receipt):
    """Observe the existing shared primitives with real pointer/keyboard input."""
    if rig.context:
        rig.context.close()
    rig.context = rig.browser.new_context(user_agent=shots.UA, viewport=shots.DESKTOP)
    rig.page = rig.context.new_page()
    rig.page.on("pageerror", lambda error: receipt["errors"].append(str(error)[:300]))
    rig.page.goto(f"http://127.0.0.1:{shots.BACKEND}/design-lab.html?theme={theme}&only=primitives", wait_until="load")
    rig.wait("() => !!document.querySelector('[data-specimen=primitives] .nx-btn-primary')", 40)
    def check(name, value):
        receipt.setdefault("checks", []).append({"theme":theme,"name":name,"passed":bool(value)})
    def shot(state):
        path=rig.shot(f"primitives-{theme}-{state}")
        receipt["screens"].append({"screen":"Primitives","theme":theme,"state":state,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    button=rig.page.locator('[data-specimen=primitives] .nx-btn-primary').first
    shot("rest")
    rest=button.evaluate("e => ({background:getComputedStyle(e).backgroundColor,transform:getComputedStyle(e).transform})")
    rest_input_shadow=rig.js("() => getComputedStyle(document.querySelector('input[aria-label=\"Search chats\"]')).boxShadow")
    box=button.bounding_box()
    rig.page.mouse.move(box["x"]+box["width"]/2,box["y"]+box["height"]/2)
    time.sleep(.4)
    shot("hover")
    hover=button.evaluate("e => ({matches:e.matches(':hover'),background:getComputedStyle(e).backgroundColor,token:getComputedStyle(e).getPropertyValue('--nx-accent-hover'),hit:document.elementFromPoint(e.getBoundingClientRect().x+e.offsetWidth/2,e.getBoundingClientRect().y+e.offsetHeight/2)?.tagName})")
    receipt.setdefault("observations",[]).append({"theme":theme,"rest":rest,"box":box,"hover":hover})
    check("hover fill changes",button.evaluate("e => getComputedStyle(e).backgroundColor") != rest["background"])
    rig.page.mouse.down()
    time.sleep(.4)
    shot("press")
    press=button.evaluate("e => ({matches:e.matches(':active'),background:getComputedStyle(e).backgroundColor,transform:getComputedStyle(e).transform})")
    receipt["observations"].append({"theme":theme,"press":press})
    check("press feedback",press["matches"] and (press["transform"] != rest["transform"] or press["background"] != hover["background"]))
    rig.page.mouse.up()
    rig.page.mouse.move(1,1)
    rig.page.locator('input[aria-label="Search chats"]').focus()
    rig.page.keyboard.press("Tab")
    rig.page.keyboard.press("Shift+Tab")
    shot("focus")
    receipt["observations"].append({"theme":theme,"focus":rig.js("() => {const e=document.querySelector('input[aria-label=\"Search chats\"]');return {active:document.activeElement===e,matches:e.matches(':focus-visible'),shadow:getComputedStyle(e).boxShadow,outline:getComputedStyle(e).outline};}")})
    check("keyboard input focus-visible",rig.js("() => document.querySelector('input[aria-label=\"Search chats\"]').matches(':focus-visible')"))
    focus=rig.js("() => {const e=document.querySelector('input[aria-label=\"Search chats\"]');return {active:document.activeElement===e,shadow:getComputedStyle(e).boxShadow};}")
    check("focus ring visible",focus["active"] and focus["shadow"] != rest_input_shadow)
    check("loading is native disabled and named",rig.js("() => {const b=[...document.querySelectorAll('[data-specimen=primitives] button')].find(b=>b.textContent==='Saving');return b?.disabled && b.getAttribute('aria-busy')==='true' && !!b.querySelector('.nx-spinner');}"))
    check("disabled click no-op",rig.js("() => {const b=[...document.querySelectorAll('[data-specimen=primitives] button')].find(b=>b.textContent==='Unavailable');let calls=0;const listener=()=>calls++;b.addEventListener('click',listener);b.click();b.removeEventListener('click',listener);return b.disabled && calls===0;}"))
    radio=rig.page.locator('[role=radiogroup][aria-label=Show] button').first
    radio.focus()
    rig.page.keyboard.press("ArrowRight")
    rig.page.keyboard.press("ArrowRight")
    check("radio arrows skip disabled option",rig.js("() => document.activeElement?.textContent==='Done' && document.activeElement?.getAttribute('aria-checked')==='true'"))
    rig.page.emulate_media(reduced_motion="reduce")
    time.sleep(.4)
    shot("reduced-motion")
    check("reduced motion disables CSS duration",rig.js("() => matchMedia('(prefers-reduced-motion: reduce)').matches && parseFloat(getComputedStyle(document.querySelector('.nx-spinner')).animationDuration)<=.001"))
    rig.page.set_viewport_size(shots.PHONE)
    time.sleep(.4)
    shot("phone")
    check("phone has no horizontal overflow",rig.js("() => document.documentElement.scrollWidth <= innerWidth"))
    receipt["observations"].append({"theme":theme,"final":rig.js("() => ({media:matchMedia('(prefers-reduced-motion: reduce)').matches,spinnerDuration:getComputedStyle(document.querySelector('.nx-spinner')).animationDuration,spinnerProperty:getComputedStyle(document.querySelector('.nx-spinner')).getPropertyValue('animation-duration'),active:document.activeElement?.textContent,focusVisible:document.activeElement?.matches(':focus-visible')})")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", choices=["before", "after"], required=True)
    parser.add_argument("--theme", choices=["dark", "light", "both"], default="both")
    parser.add_argument("--lab", action="store_true", help="Render the existing shared-control specimen and verify states")
    parser.add_argument("--backend", type=int, choices=range(48981,48990), default=48984)
    parser.add_argument("--engine", type=int, choices=range(48981,48990), default=48985)
    args = parser.parse_args()
    shots.use_ports(args.backend, args.engine)
    print("Resolving admitted Obscura", flush=True)
    try:
        shots.EXE = managed_executable()
    except FileNotFoundError:
        admission = json.loads((REPO / "scripts/evidence/C2g-engine-fragment-admission.json").read_text())
        shots.EXE = Path("D:/NeyviaRuns/gui/obscura/obscura.exe")
        shots.EXE.parent.mkdir(parents=True, exist_ok=True)
        for key, target in (("engineBinary",shots.EXE),("workerBinary",shots.EXE.with_name("obscura-worker.exe"))):
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==admission[key]["sha256"]:
                continue
            source = Path("C:/Users/user/Projects/nx-c13-taste") / admission[key]["path"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != admission[key]["sha256"]:
                raise ValueError("Existing Obscura differs from its admission")
            shutil.copy2(source,target)
    shots.BUILD = Path(f"D:/NeyviaRuns/gui/build-{'lab-' if args.lab else ''}{args.set}")
    shots.SCRATCH = Path(f"D:/NeyviaRuns/gui/runtime-{args.set}-{int(time.time())}")
    shots.SMALL_STATE = REPO / f".agent_control/gui/runtime-{args.set}-{int(time.time())}"
    laya = shots.SMALL_STATE / ".neyvia/laya/config.json"
    laya.parent.mkdir(parents=True, exist_ok=True)
    laya.write_text(json.dumps({"enabled": False, "port": 48989}))
    shots.OUT = Path(f"D:/NeyviaRuns/gui/{args.set}")
    shots.OUT.mkdir(parents=True, exist_ok=True)
    receipt = {"set": args.set, "theme":args.theme, "runtime":str(shots.SCRATCH),"errors": [], "screens": [],
               "build":str(shots.BUILD),"buildIndexSha256":hashlib.sha256((shots.BUILD / ("design-lab.html" if args.lab else "index.html")).read_bytes()).hexdigest()}
    rig = shots.Rig(receipt, connect_timeout=60000, direct_cdp=True)
    try:
        print("Starting owned backend and engine", flush=True)
        rig.start()
        for theme in (("dark", "light") if args.theme == "both" else (args.theme,)):
            print(f"Capturing {args.set} {theme}", flush=True)
            if args.lab:
                capture_lab(rig, theme, receipt)
                continue
            shots.THEME = theme
            rig.session(shots.DESKTOP)
            if theme == "light":
                shots.open_from_launcher(rig, "Settings", "Settings")
                rig.wait("() => !!document.querySelector('.nx-look-fonts')", 60)
                rig.js("() => [...document.querySelectorAll('.nx-seg[aria-label=Theme] button')].find(b => b.textContent.trim()==='Morning')?.click()")
            rig.wait("t => document.querySelector('.nx')?.dataset.nxTheme === t", 30, theme)
            path = rig.shot(f"shell-{theme}")
            receipt["screens"].append({"screen":"Shell","theme":theme,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
            for query, title in (("Settings", "Settings"), ("App Factory", "App Factory"), ("Files", "Files"), ("Notes", "Notes")):
                print(f"Opening {query}", flush=True)
                shots.open_from_launcher(rig, query, title)
                selector = {"Settings": ".nx-look-fonts", "App Factory": ".af", "Files": ".nx-files", "Notes": ".nx-notes"}[query]
                rig.wait("s => !!document.querySelector(s)", 60, selector)
                path = rig.shot(f"{query.lower().replace(' ', '-')}-{theme}")
                receipt["screens"].append({"screen": query, "theme": theme,"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
                if args.set == "after" and query == "Settings":
                    base_size=rig.js("() => parseFloat(getComputedStyle(document.querySelector('.nx-brand')).fontSize)")
                    choose_size="label => [...document.querySelectorAll('.nx-seg[aria-label=\"Text size\"] button')].find(b=>b.textContent.trim()===label)?.click()"
                    rig.js(choose_size,"Large")
                    rig.wait("() => document.querySelector('.nx-root')?.dataset.nxText==='l'",30)
                    large_path=rig.shot(f"settings-large-{theme}")
                    large_size=rig.js("() => parseFloat(getComputedStyle(document.querySelector('.nx-brand')).fontSize)")
                    passed=bool(base_size and large_size and abs(large_size/base_size-1.1)<.015)
                    receipt.setdefault("checks",[]).append({"theme":theme,"name":"Look large text scales once","passed":passed})
                    receipt.setdefault("journeys",[]).append({"theme":theme,"name":"Text size","medium":base_size,"large":large_size,"path":str(large_path),"sha256":hashlib.sha256(large_path.read_bytes()).hexdigest()})
                    rig.js(choose_size,"Medium")
                    rig.wait("() => !document.querySelector('.nx-root')?.hasAttribute('data-nx-text') && [...document.querySelectorAll('.nx-seg[aria-label=\"Text size\"] button')].some(b=>b.textContent.trim()==='Medium' && b.getAttribute('aria-checked')==='true')",30)
        failed=[c for c in receipt.get("checks",[]) if not c["passed"]]
        if failed:
            raise AssertionError(json.dumps(failed))
    except Exception as error:
        receipt["errors"].append(f"{type(error).__name__}: {error}")
        receipt["failure"] = traceback.format_exc()
        if rig.page:
            try:
                receipt["pageAtFailure"] = rig.js("() => ({url:location.href,title:document.title,text:document.body?.innerText?.slice(0,1500),scripts:[...document.scripts].map(s=>s.src)})")
                rig.shot(f"failure-{int(time.time())}")
            except Exception:
                pass
        raise
    finally:
        rig.stop()
        filename = f"receipt-failed-{int(time.time())}.json" if receipt["errors"] else f"receipt-{'lab-' if args.lab else ''}{args.theme}.json"
        (shots.OUT / filename).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if args.lab:
            (shots.OUT / "receipt-lab-latest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"screens": len(receipt["screens"]), "errors": receipt["errors"]}))
    if receipt["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
