"""Owned hidden Obscura journey controller; production DOM and SDK, no fixtures."""
import argparse
import base64
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.browser_obscura import ObscuraEngine, ProfileWorker


def dom(worker, tab, operation, args=None):
    page = worker.pages[tab]["page"]
    args = args or {}
    if operation == "auth":
        return page.evaluate("async () => {const r=await fetch('/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});return {ok:r.ok,status:r.status};}")
    if operation == "inspect":
        return page.evaluate("() => {const r=document.querySelector('.nx-launcher')||document.querySelector('.nx-stage')||document.querySelector('.ss')||document.body;return {title:document.title,text:r.innerText.slice(0,4500),buttons:[...r.querySelectorAll('button')].map(e=>({name:e.getAttribute('aria-label')||e.innerText,disabled:e.disabled})).slice(-40)};}")
    if operation == "ready":
        page.wait_for_function("!document.body.innerText.includes('Opening your workspace') && (window.neyviaApp || document.querySelectorAll('button').length > 1)", timeout=args.get("timeout", 60000))
        return {"ready": True}
    if operation == "skip-setup":
        from playwright.sync_api import TimeoutError
        try:
            page.get_by_role("button", name="Skip setup", exact=True).wait_for(state="visible", timeout=args.get("timeout", 3000))
        except TimeoutError:
            return {"setup": "not shown"}
        page.get_by_role("button", name="Skip setup", exact=True).click()
        return {"skipped": "task-local first-run setup"}
    if operation == "disabled-sdk":
        return page.evaluate("async () => {const {createNeyviaClient}=await import('/api/sdk/neyvia-sdk.js');try{await createNeyviaClient({appId:'scroll-study'}).providerStatus('codex');throw Error('Disabled app was admitted');}catch(error){if(error.status!==403)throw error;return {refused:true,status:error.status};}}")
    if operation == "ensure-enabled":
        row = page.locator("#neyvia-marketplace-sources li").filter(has=page.get_by_text(args["item"], exact=True))
        button = row.get_by_role("button", name="Enable", exact=True)
        if button.count():
            button.click()
            page.get_by_text(args["item"] + ": active.", exact=True).wait_for(state="visible")
        return {"active": args["item"]}
    if operation == "viewport":
        page.set_viewport_size({"width": int(args["width"]), "height": int(args["height"])})
        return {"viewport": page.viewport_size}
    if operation == "theme":
        # The shell's own saved theme (nxOsStore key nx.os.theme), applied by reloading.
        if args["theme"] not in {"dark", "light", "sunset", "night"}:
            raise ValueError("Unknown theme")
        page.evaluate("t => localStorage.setItem('nx.os.theme', JSON.stringify(t))", args["theme"])
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("t => document.querySelector('.nx-root')?.dataset.nxTheme === t", arg=args["theme"], timeout=30000)
        return {"theme": args["theme"]}
    if operation == "switch":
        control = page.get_by_role("switch", name=args["item"] + " enabled", exact=True).first
        if control.is_checked() != bool(args["on"]):
            control.click()  # the app answers asynchronously; the recipe waits for its status line
        return {"switch": args["item"], "requested": bool(args["on"])}
    if operation == "frame-text":
        page.frame_locator("iframe.nx-store-app-frame").get_by_text(args["text"], exact=False).first.wait_for(state="visible", timeout=args.get("timeout", 30000))
        return {"frameVisible": args["text"]}
    if operation == "frame-src":
        frame = page.locator("iframe.nx-store-app-frame").first
        frame.wait_for(state="attached", timeout=args.get("timeout", 30000))
        src = frame.get_attribute("src") or ""
        if not src.endswith(args["expect"]):
            raise RuntimeError("Store opened " + src + ", not " + args["expect"])
        return {"src": src}
    if operation == "frames":
        rows = []
        for frame in page.frames:
            try:
                text = frame.evaluate("() => document.body ? document.body.innerText.slice(0, 200) : ''")
            except Exception as error:
                text = "unreadable: " + str(error)[:120]
            rows.append({"url": frame.url, "text": text})
        return rows
    if operation == "gone":
        page.locator(args["selector"]).first.wait_for(state="detached", timeout=args.get("timeout", 30000))
        return {"gone": args["selector"]}
    if operation == "scroll-to":
        page.locator(args["selector"]).first.scroll_into_view_if_needed()
        return {"scrolled": args["selector"]}
    if operation == "scroll-top":
        page.evaluate("() => document.querySelectorAll('.nx-tool-screen').forEach(e => e.scrollTop = 0)")
        return {"scrolled": "top"}
    if operation == "styles":
        # Computed layout of named elements, for checking a rendered state.
        return page.evaluate("""a => [...document.querySelectorAll(a.selector)].slice(0, 6).map(e => { const c = getComputedStyle(e), r = e.getBoundingClientRect();
            return {tag: e.tagName, cls: e.className && String(e.className).slice(0, 80), box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
              style: Object.fromEntries((a.props || []).map(p => [p, c.getPropertyValue(p)]))}; })""", args)
    if operation == "state":
        return page.evaluate("() => [...document.querySelectorAll('[data-store-item]')].map(e => ({id: e.dataset.storeItem, state: e.dataset.storeState}))")
    if operation == "click":
        region = page.locator(args["scope"]).first if args.get("scope") else page.locator("li").filter(has=page.get_by_text(args["item"], exact=True)) if args.get("item") else page
        region.get_by_role(args.get("role", "button"), name=args["name"], exact=True).click()
        return {"clicked": args["name"]}
    if operation == "option":
        page.get_by_role("option").filter(has=page.get_by_text(args["name"], exact=True)).click()
        return {"selected": args["name"]}
    if operation == "marketplace-top":
        page.locator("#neyvia-marketplace-sources h3").scroll_into_view_if_needed()
        return {"visible": "Apps and mods from source"}
    if operation == "capture":
        selector = args["selector"]
        if selector not in {"#neyvia-marketplace-sources", ".ss-neyvia", "#neyvia-app"}:
            raise ValueError("Only this task's app and marketplace regions can be captured")
        return {"dataUrl": "data:image/png;base64," + base64.b64encode(page.locator(selector).screenshot()).decode()}
    if operation == "fill":
        page.get_by_label(args["name"], exact=True).fill(args["value"])
        return {"filled": args["name"]}
    if operation == "text":
        page.get_by_text(args["text"], exact=False).first.wait_for(state="visible", timeout=args.get("timeout", 30000))
        return {"visible": args["text"]}
    if operation == "scroll-services":
        button = page.get_by_role("button", name="Neyvia services", exact=True)
        button.click()
        if button.get_attribute("aria-expanded") != "true":
            raise RuntimeError("Services did not open")
        return {"opened": "Neyvia services"}
    if operation == "sdk":
        # Call the real app's public adapter, using the production shared client.
        return page.evaluate("async a => { const s=window.scrollStudyServices; if(!s)throw Error('Scroll SDK adapter is not mounted'); return await s[a.method](...(a.args||[])); }", args)
    if operation == "app-contract":
        state = page.evaluate("window.neyviaApp.state()")
        if state.get("connected") is not True:
            raise RuntimeError("Template's authored app.state().connected goal failed")
        return {"goal": "app.state().connected == true", "passed": True, "state": state}
    raise ValueError("Unknown bounded DOM operation")


ProfileWorker._mod_dom = dom
_open = ProfileWorker._open
def traced_open(worker, *args, **kwargs):
    worker._connect()
    worker.mod_errors = []
    worker.context.on("page", lambda page: page.on("pageerror", lambda error: worker.mod_errors.append(str(error)[:600])))
    return _open(worker, *args, **kwargs)
ProfileWorker._open = traced_open


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--output", type=Path, default=REPO / "scripts/evidence/MOD-render.json")
    parser.add_argument("--ports", default="48911-48919", help="Assigned local port range, low-high")
    parser.add_argument("--engine-port", type=int, default=48913)
    parser.add_argument("--color-scheme", default="dark", choices=["dark", "light"])
    parser.add_argument("--shots", type=Path, default=REPO / "scripts/evidence", help="Directory screenshots must stay inside")
    parser.add_argument("--profile", type=Path, default=REPO / ".agent_control/mod/renderer", help="Obscura profile directory")
    args = parser.parse_args()
    low, high = (int(value) for value in args.ports.split("-"))
    profile = args.profile
    engine = ObscuraEngine(profile, REPO / ".agent_control/mod/obscura/obscura.exe", port=args.engine_port,
        fixtures=True, assigned_ports=args.ports, color_scheme=args.color_scheme, reduced_motion="reduce", request_timeout_ms=60000)
    results = []
    try:
        for step in json.loads(args.recipe.read_text(encoding="utf-8")):
            if "navigate" in step:
                url = step["navigate"]
                from urllib.parse import urlsplit
                parsed = urlsplit(url)
                if parsed.hostname != "127.0.0.1" or parsed.port not in range(low, high + 1):
                    raise ValueError("Only assigned MOD URLs can be rendered")
                method = "navigate" if engine.profiles else "open"
                result = engine.run("mod", method, "shell", url)
                results.append({"navigate": url, "title": result.get("title")})
            elif "screenshot" in step:
                frame = engine.profiles["mod"].run("mod_dom", "shell", "capture", {"selector": step["selector"]}) if step.get("selector") else engine.run("mod", "frame", "shell")
                path = (args.shots / step["screenshot"]).resolve() if not Path(step["screenshot"]).is_absolute() and args.shots != REPO / "scripts/evidence" else (REPO / step["screenshot"]).resolve()
                path.relative_to(args.shots.resolve())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(frame["dataUrl"].split(",", 1)[1]))
                results.append({"screenshot": step["screenshot"]})
            else:
                # "retry": a slow backend answer may take longer than one bounded wait.
                for attempt in range(int(step.get("retry", 0)) + 1):
                    try:
                        result = engine.profiles["mod"].run("mod_dom", "shell", step["operation"], step.get("args"))
                        break
                    except Exception as error:
                        if attempt >= int(step.get("retry", 0)) or "Timeout" not in type(error).__name__ + str(error):
                            raise
                results.append({"operation": step["operation"], "result": result})
                print(json.dumps(results[-1], ensure_ascii=False)[:4500], flush=True)
    finally:
        if engine.profiles:
            worker = engine.profiles["mod"]
            try:
                if args.shots != REPO / "scripts/evidence":
                    frame = engine.run("mod", "frame", "shell")
                    (args.shots / "_last.png").write_bytes(base64.b64decode(frame["dataUrl"].split(",", 1)[1]))
            except Exception:
                pass
            try:
                results.append({"final": worker.run("mod_dom", "shell", "inspect"), "pageErrors": getattr(worker, "mod_errors", [])})
            except Exception:
                pass
        args.output.write_text(json.dumps({"engine": "obscura", "engineSha256": engine.engine_sha256,
            "executable": str(engine.executable), "results": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        engine.close()


if __name__ == "__main__":
    main()
