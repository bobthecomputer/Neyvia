"""Render Neyvia's complete production shell against the actual native driver."""
from pathlib import Path
import json
import subprocess
import time


def build(root, scratch):
    area = scratch / "rendered-preview"
    area.mkdir()
    source = (root / "web/src/neyvia/next/NxShell.jsx").as_posix()
    store = (root / "web/src/neyvia/next/nxOsStore.js").as_posix()
    css = (root / "web/src/neyvia/next/nxShell.css").as_posix()
    tokens = (root / "web/src/neyvia/next/nxTokens.css").as_posix()
    themes = (root / "web/src/neyvia/next/nxThemes.css").as_posix()
    workspace_css = (root / "web/src/neyvia/next/nxOs.css").as_posix()
    entry = area / "entry.jsx"
    entry.write_text('import React from "react"; import {createRoot} from "react-dom/client";\n'
        + 'import {NxShell} from ' + json.dumps(source) + ';\n'
        + 'import {os} from ' + json.dumps(store) + ';\n'
        + 'import ' + json.dumps(css) + ';\n'
        + 'import ' + json.dumps(tokens) + '; import ' + json.dumps(themes) + ';\n'
        + 'import ' + json.dumps(workspace_css) + ';\n'
        + 'await fetch("/api/auth/local-session",{method:"POST",credentials:"include",'
          'headers:{"Content-Type":"application/json"},body:"{}"});\n'
        + 'const target=new URLSearchParams(location.search).get("sessionId");\n'
        + 'os.updateLayout(layout=>({...layout,dock:"left"}));\n'
        + 'os.showPane("preview",target);\n'
        + 'createRoot(document.getElementById("root")).render(<NxShell/>);\n',
        encoding="utf-8")
    out = area / "dist"
    binary = root / "node_modules/@esbuild/win32-x64/esbuild.exe"
    if not binary.is_file():
        raise RuntimeError("Installed esbuild executable unavailable; no download attempted")
    subprocess.run([str(binary), str(entry), "--bundle", "--format=esm", "--jsx=automatic",
        "--define:import.meta.env={}", "--outdir=" + str(out), "--log-level=error"],
        cwd=root, capture_output=True, check=True, timeout=150, creationflags=subprocess.CREATE_NO_WINDOW)
    (out / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Neyvia C11 preview proof</title>'
        '<link rel="stylesheet" href="/entry.css"><style>html,body,#root{margin:0;width:100%;height:100%;}'
        'body{background:#17211d;color:#fff;font-family:Segoe UI,sans-serif}'
        '#root{display:flex}button,input{font:inherit}button{border:0;background:none}</style>'
        '<div id="root" class="nx" data-nx-theme="forest"></div>'
        '<script type="module" src="/entry.js"></script>', encoding="utf-8")
    return out


def exercise(root, scratch, native, base, port, debug_port, session_id, window_id, snapshot, state, permission=None,
             screenshot_path=None):
    screenshot = Path(screenshot_path or root / "scripts/evidence/C11-ui.png")
    import psutil
    from playwright.sync_api import sync_playwright
    if port == debug_port or debug_port not in (*range(48701, 48710), *range(48751, 48760)):
        raise ValueError("Preview CDP requires a separate explicit assigned port")
    if any(c.laddr.port == debug_port and c.status == "LISTEN" for c in psutil.net_connections("tcp")):
        raise RuntimeError("Assigned CDP port is already occupied; preserve its owner and select another assigned port")
    from contextlib import closing
    import os
    from c8e_prerequisites import stage
    from grant_agent.browser_obscura import ObscuraEngine
    stage({'installedObscura': 'C:/Users/user/Projects/nx-c2-browser/.agent_control/C2f/obscura-v0.2.4/extracted/obscura.exe'}, scratch)
    os.environ['NEYVIA_BROWSER_PROOF_PORTS'] = str(debug_port)
    os.environ['NEYVIA_PROOF_ALLOWED_PORTS'] = json.dumps([port, debug_port])
    forbidden = []
    failures = []
    responses = []
    forwarded = []
    frame_responses = []
    with closing(ObscuraEngine(scratch / 'obscura', scratch / 'c8/obscura.exe',
            port=debug_port, fixtures=True)) as engine, sync_playwright() as playwright:
        native.guard.register_pid(engine.process.pid)
        browser = playwright.chromium.connect_over_cdp(engine.endpoint,
            headers={'Authorization': 'Bearer ' + engine.token})
        context = browser.new_context(user_agent='NeyviaAgent/1.0 (Automation; Obscura)', accept_downloads=False)
        def admit(route):
            from urllib.parse import urlsplit
            parsed = urlsplit(route.request.url)
            if parsed.hostname == "127.0.0.1" and parsed.port == port:
                route.continue_()
            else:
                forbidden.append({"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port})
                route.abort()
        context.route("**/*", admit)
        page = context.new_page()
        # Observe the page's actual fetches where this engine's CDP does not
        # publish complete Network response events. Do not change requests.
        page.add_init_script("""(() => {
          window.__c8hInputs = [];
          const original = window.fetch;
          window.fetch = async function(input, init) {
            const response = await original.call(this, input, init);
            if (String(input).endsWith('/api/ui/cua') && init?.body) {
              const sent = JSON.parse(init.body);
              if (sent.op === 'input') {
                const body = await response.clone().json();
                window.__c8hInputs.push({kind:sent.args.kind, args:sent.args,
                  httpStatus:response.status, result:body.data ?? body});
              }
            }
            return response;
          };
        })();""")
        page.set_viewport_size({"width": 1500, "height": 900})
        page.on("pageerror", lambda error: failures.append(str(error)[:250]))
        def failed_response(response):
            path = response.url.split(base)[-1]
            if path.startswith("/api/ui/cua/frame?"):
                from urllib.parse import urlsplit, parse_qs
                requested_seq = parse_qs(urlsplit(response.url).query).get("seq", [""])[0]
                headers = response.headers
                frame_responses.append({"requestedSeq": requested_seq, "servedSeq": headers.get("x-frame-seq"),
                    "captureId": headers.get("x-capture-id"), "status": response.status})
            if path == "/api/ui/cua" and response.request.method == "POST":
                try:
                    body = response.request.post_data_json
                    if body.get("op") == "input":
                        data = response.json()
                        forwarded.append({"kind": body.get("args", {}).get("kind"),
                            "httpStatus": response.status, "result": data.get("data", data)})
                except Exception:
                    pass
            if response.status < 400:
                return
            row = {"path": path[:150], "status": response.status}
            try:
                row["error"] = str(response.json().get("error", ""))[:300]
            except Exception:
                pass
            if row["path"] == "/api/backend":
                try:
                    row["command"] = response.request.post_data_json.get("command")
                except Exception:
                    pass
            responses.append(row)
        page.on("response", failed_response)
        page.goto(base + "/?sessionId=" + session_id, wait_until="domcontentloaded")
        canvas = page.locator(".nx-pv-canvas")
        try:
            owned_window = native.request("window", {"windowId": window_id})
            main_window = page.locator('.nx-pv-tab[title=' + json.dumps(owned_window["title"]) + ']')
            main_window.wait_for(timeout=20000)
            main_window.click()
            canvas.wait_for(timeout=20000)
            page.wait_for_function("document.querySelector('.nx-pv-canvas img')?.naturalWidth > 0", timeout=20000)
        except Exception as exc:
            page.screenshot(path=str(screenshot), full_page=True)
            diagnostic = {"ok": False, "error": str(exc)[:300], "pageErrors": failures,
                "failedHttp": responses[-12:], "forbiddenRequests": forbidden,
                "visibleText": page.locator("body").inner_text()[:1000],
                "selectedWindowTitle": (page.locator('.nx-pv-tab[aria-selected="true"]').get_attribute('title') if page.locator('.nx-pv-tab[aria-selected="true"]').count() else None),
                "screenshot": str(screenshot.relative_to(root))}
            browser.close()
            return diagnostic
        box = canvas.bounding_box()
        image = page.locator(".nx-pv-canvas img")
        dimensions = image.evaluate("e=>({width:e.naturalWidth,height:e.naturalHeight})")
        geometry = {"canvas": box, "viewer": page.locator('.nx-pv-view').bounding_box(), "image": image.bounding_box(), "pixels": dimensions,
            "controls": [{k: e.get(k) for k in ('label', 'role', 'screenshot_frame')} for e in snapshot['elements']]}
        def observed_inputs():
            forwarded[:] = page.evaluate('window.__c8hInputs || []')
            return forwarded
        def point(label):
            box = canvas.bounding_box()
            dimensions = image.evaluate("e=>({width:e.naturalWidth,height:e.naturalHeight})")
            element = next(e for e in snapshot["elements"] if e["label"] == label or
                label == "Preview scroll list" and e["role"] == "List" and "scroll" in e.get("actions", []))
            area = element["screenshot_frame"]
            return (box["x"] + (area["x"] + area["w"] / 2) / dimensions["width"] * box["width"],
                    box["y"] + (area["y"] + area["h"] / 2) / dimensions["height"] * box["height"])
        page.mouse.click(*point("Task input"))
        page.wait_for_timeout(800)
        page.keyboard.type(" UI")
        page.wait_for_timeout(600)
        page.mouse.click(*point("Apply"))
        until = time.monotonic() + 8
        while time.monotonic() < until:
            if state.with_suffix(".txt.result").read_text() == "Applied: initial C11 preview typed UI":
                break
            page.wait_for_timeout(150)
        effect = state.with_suffix(".txt.result").read_text()
        page.wait_for_timeout(600)
        # A wheel over a nested list must resolve its scrollable ancestor,
        # rather than accidentally selecting a list item or the entire window.
        scroll_before = int(Path(str(state) + ".scroll").read_text())
        page.mouse.move(*point("Preview scroll list"))
        page.mouse.wheel(0, 240)
        until = time.monotonic() + 8
        scroll_after = scroll_before
        while time.monotonic() < until:
            scroll_after = int(Path(str(state) + ".scroll").read_text())
            if scroll_after > scroll_before:
                break
            page.wait_for_timeout(150)
        # Exercise the refusal through the rendered pane, then independently
        # read the native value. No blocked input may mutate the application.
        page.mouse.click(*point("Lock input"))
        owned_input = next(e for e in snapshot["elements"] if e["label"] == "Task input")
        until = time.monotonic() + 8
        while native.desktop.u.IsWindowEnabled(int(owned_input["nativeHandle"])) and time.monotonic() < until:
            page.wait_for_timeout(150)
        refusal_start = len(observed_inputs())
        page.mouse.click(*point("Task input"))
        until = time.monotonic() + 8
        while not any(a["kind"] == "click" and a["result"].get("status") == "refused"
            for a in observed_inputs()[refusal_start:]) and time.monotonic() < until:
            page.wait_for_timeout(150)
        input_handle = int(owned_input["nativeHandle"])
        enabled_now = bool(native.desktop.u.IsWindowEnabled(input_handle))
        still_owned = native.desktop.owns(window_id) and bool(native.desktop.u.IsChild(window_id, input_handle))
        blocked_seen = any(a["kind"] == "click" and a["result"].get("status") == "refused"
            for a in observed_inputs()[refusal_start:]) and still_owned and not enabled_now
        page.screenshot(path=str(screenshot.with_name(screenshot.stem + "-blocked.png")), full_page=True)
        page.mouse.click(*point("Unlock input"))
        page.wait_for_timeout(600)
        banner_seen = False
        if permission:
            banner = page.get_by_role("alert").filter(has_text=permission["app"])
            banner.wait_for(timeout=8000)
            banner_seen = banner.is_visible()
        page.screenshot(path=str(screenshot), full_page=True)
        if permission:
            banner.get_by_role("button", name="Don't", exact=True).click()
            banner.wait_for(state="hidden", timeout=8000)
        chat_box = page.locator(".nx-work-chat").bounding_box()
        pane_box = page.locator(".nx-work-app").bounding_box()
        right_pane = bool(chat_box and pane_box and pane_box["x"] >= chat_box["x"] + chat_box["width"] - 2)
        preview_http_failures = [r for r in responses if r["path"].startswith("/api/ui/cua")]
        frame_responses = page.evaluate("""async () => {
          const url = document.querySelector('.nx-pv-canvas img').src;
          const response = await fetch(url, {credentials:'include'});
          await response.arrayBuffer();
          return [{requestedSeq:new URL(url).searchParams.get('seq'),
            servedSeq:response.headers.get('x-frame-seq'),
            captureId:response.headers.get('x-capture-id'),status:response.status}];
        }""")
        result = {"component": "NxShell -> NxStage -> PaneView -> NxPreviewPane (complete production shell, actual HTTP/SSE)",
            "fixtureApi": False, "browser": "Neyvia Obscura engine; private proof host; no Chromium fallback", "debugPort": debug_port,
            "appWrittenEffect": effect, "screenshot": str(screenshot.relative_to(root)),
            "scroll": {"before": scroll_before, "after": scroll_after, "independentNativeTopIndex": scroll_after > scroll_before},
            "disabledInputRefusedThroughUi": blocked_seen,
            "disabledInputReadback": {"nativeHandle": input_handle, "stillOwned": still_owned, "enabled": enabled_now, "refusalStart": refusal_start},
            "blockedScreenshot": str(screenshot.with_name(screenshot.stem + "-blocked.png").relative_to(root)),
            "forwardedActions": forwarded,
            "geometry": geometry,
            "immutableFrameResponses": frame_responses,
            "pageErrors": failures, "failedHttp": responses[-12:], "previewHttpFailures": preview_http_failures,
            "forbiddenRequests": forbidden,
            "permissionBannerSeen": banner_seen, "permissionDeniedThroughUi": bool(permission and banner_seen),
            "unavailableForegroundOffered": page.get_by_role("button", name="Bring forward once", exact=True).count() > 0,
            "rightPane": right_pane, "chatBounds": chat_box, "paneBounds": pane_box,
            "ok": effect == "Applied: initial C11 preview typed UI" and scroll_after > scroll_before and blocked_seen and right_pane and not failures and not forbidden and not preview_http_failures
                and bool(frame_responses) and all(f["requestedSeq"] == f["servedSeq"] and f["captureId"] for f in frame_responses)}
        browser.close()
    return result
