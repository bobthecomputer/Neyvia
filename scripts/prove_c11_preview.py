"""Actual authenticated preview HTTP -> isolated native app -> persisted effect.

No simulated backend, native results, captures or postconditions. An explicit
48701-48709 port is mandatory; all app launches use the production driver.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from http.cookiejar import CookieJar
from urllib.error import HTTPError
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import uuid
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def prove_learning(call, session_id, window_id, state):
    """Use the production manual compiler; selectors and effects stay native."""
    params = {"sessionId": session_id, "window_id": window_id}
    draft = call("adapt", params)
    steps = [
        {"selector": {"role": "Edit", "label": "Task input"}, "tool": "set_value", "args": {"value": "initial", "observation_timeout_ms": 3000},
         "expect": [{"element": {"selector": {"role": "Edit", "label": "Task input"}, "value_equals": "initial"}}]},
        {"selector": {"role": "Button", "label": "Apply"}, "tool": "click", "args": {"observation_timeout_ms": 3000},
         "expect": [{"element": {"selector": {"label": "Applied: initial"}, "exists": True}}]},
    ]
    runs = []
    for _ in range(5):
        try:
            runs.append(call("flow", {**params, "steps": steps}))
        except RuntimeError as exc:
            return {"draft": draft, "runs": runs, "compiledReplay": False, "ok": False,
                    "error": str(exc), "failedObservation": call("snapshot", {**params, "windowId": window_id})}
    if not all(r.get("ok") for r in runs) or not runs[-1].get("compiled"):
        return {"draft": draft, "runs": runs, "compiledReplay": False, "ok": False,
                "error": "Actual native flow did not reach successful compiled replay"}
    effect = state.with_suffix(".txt.result").read_text()
    if effect != "Applied: initial":
        raise RuntimeError("Compiled replay's persisted native effect did not match its independent check")
    return {"draft": draft, "runs": runs, "compiledReplay": True, "ok": True, "tokens": sum(r.get("tokens", 0) for r in runs),
            "appWrittenEffect": effect, "boundary": "Disposable native app; installed-app learning is recorded by the cohort"}


def observe_controls(call, session_id, window_id, labels):
    """Read-only retries for a bounded incomplete provider observation."""
    deadline = time.monotonic() + 3
    while True:
        observed = call("snapshot", {"sessionId": session_id, "windowId": window_id})
        if set(labels) <= {e["label"] for e in observed["elements"]}:
            return observed
        if time.monotonic() >= deadline:
            raise RuntimeError("Native observation did not resolve controls: " + ", ".join(labels))


def run(port, debug_port, output=None, journey_probe=None, scratch_parent=None, render_ui=True):
    from grant_agent.subprocess_utils import install_hidden_subprocess_default
    install_hidden_subprocess_default()
    scratch = Path(scratch_parent or ROOT / ".agent_control/c11-preview") / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    for name in ("NEYVIA_COORDINATOR_AUTOSTART", "NEYVIA_TOOL_AUTO_UPDATE", "FLUXIO_WATCHDOG_AUTOSTART"):
        os.environ[name] = "0"
    os.environ["FLUXIO_WORKSPACE_ROOT"] = str(scratch)
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(scratch)
    os.environ["FLUXIO_RUNTIME_AUTO_UPDATE"] = "0"
    os.environ["NEYVIA_PROOF_CREDENTIAL_GUARD"] = "1"
    os.environ["NEYVIA_PROOF_ALLOWED_PORTS"] = json.dumps([port, debug_port])
    os.environ["SYNTELOS_ACCOUNT_USER"] = "c11-proof-owner"
    os.environ["SYNTELOS_ACCOUNT_PASSWORD"] = secrets.token_urlsafe(40)
    from grant_agent.proof_credential_guard import install, prepare_broker_fixture
    install(scratch)
    if scratch.is_relative_to(ROOT / ".agent_control/proofs"):
        prepare_broker_fixture(scratch)
    from grant_agent.web_backend import FluxioWebBackend, make_handler, _HandshakeSafeThreadingHTTPServer
    from grant_agent.neyvia_cua import service_for
    from grant_agent.cua_fast import FastClient
    from grant_agent.cua_guard import ZeroDisturbanceGuard
    framework = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
    binary = scratch / "C11PreviewProbe.exe"
    subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/define:C11PREVIEW", "/out:" + str(binary),
        str(ROOT / "tools/cua-driver-win/c1-probe.cs"),
        "/reference:" + str(framework / "System.Windows.Forms.dll"),
        "/reference:" + str(framework / "System.Drawing.dll")],
        check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    receipt = {"schema": "neyvia.c11.preview-journey.v1", "at": datetime.now(timezone.utc).isoformat(),
        "port": port, "debugPort": debug_port,
        "boundary": "Real owner-authenticated HTTP/MCP/native preview and production right-pane renderer on a disposable native app",
        "ok": False, "scratch": str(scratch.relative_to(ROOT))}
    receipt["sourceSha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
        "src/grant_agent/cua_desktop.py", "src/grant_agent/cua_guard.py", "src/grant_agent/cua_native.py",
        "src/grant_agent/cua_fast.py", "src/grant_agent/cua_adaptation.py", "src/grant_agent/neyvia_cua.py",
        "src/grant_agent/cua_launch.py", "src/grant_agent/neyvia_cua_mcp.py",
        "src/grant_agent/manual_compiler.py", "src/grant_agent/manual_versions.py",
        "manuals/cl/computer-use.cl", "manuals/computer-use.manual.json",
        "scripts/prove_c11_preview.py", "scripts/c11_preview_ui.py", "tools/cua-driver-win/c1-probe.cs",
        "web/src/neyvia/next/NxShell.jsx", "web/src/neyvia/next/nxOsStore.js",
        "web/src/neyvia/next/NxStage.jsx", "web/src/neyvia/next/NxPanes.jsx",
        "web/src/neyvia/next/NxPreviewPane.jsx", "web/src/neyvia/next/nxCuaApi.js",
        "web/src/neyvia/next/nxCuaModel.js")}
    output = Path(output or ROOT / "scripts/evidence/C11-preview.json").resolve()
    if not output.is_relative_to(ROOT / "scripts/evidence"):
        raise ValueError("Preview receipts must remain in task-local evidence")
    if output.is_file():
        archive = output.parent / "C11-preview-runs"
        archive.mkdir(exist_ok=True)
        previous_bytes = output.read_bytes()
        (archive / (hashlib.sha256(previous_bytes).hexdigest() + ".json")).write_bytes(previous_bytes)
        previous = json.loads(output.read_text(encoding="utf-8"))
        receipt["previousRuns"] = (previous.get("previousRuns", []) + [{k: previous.get(k)
            for k in ("ok", "error", "scratch")}])[-4:]
    backend = server = service = guard = None
    try:
        from c11_preview_ui import build, exercise
        static_root = build(ROOT, scratch)
        receipt["previewBundle"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in static_root.iterdir()
            if p.suffix in {".js", ".css"}}
        backend = FluxioWebBackend(scratch, static_root)
        # This existing-owner proof exercises the preview, not the installer.
        # Persist production onboarding state in this disposable workspace so
        # mounting the complete shell cannot initiate a first-run download.
        from grant_agent.neyvia_onboarding import save_state
        save_state(scratch, {"completed": True})
        server = _HandshakeSafeThreadingHTTPServer(("127.0.0.1", port), make_handler(backend))
        threading.Thread(target=server.serve_forever, name="c11-proof-http", daemon=True).start()
        base = "http://127.0.0.1:" + str(port)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        def request(path, body=None):
            payload = json.dumps(body).encode() if body is not None else None
            try:
                return opener.open(Request(base + path, data=payload,
                    headers={"Origin": base, "Content-Type": "application/json"}), timeout=30)
            except HTTPError as exc:
                raise RuntimeError(path + ": " + exc.read(2048).decode(errors="replace")) from exc
        with request("/api/auth/local-session", {}) as response:
            if not json.load(response).get("ok"):
                raise RuntimeError("Real local owner authentication failed")
        receipt["authentication"] = "real-local-owner-session; cookie never recorded"
        service = service_for(scratch)
        native = service.native
        native.isolation()
        native.fast_client = FastClient(native)
        for lane in (native.fast_client.uia, native.fast_client.msaa, native.fast_client.capture, native.fast_client.policy):
            if not lane.ready.wait(5) or lane.error:
                raise RuntimeError("Native lane initialization failed: " + str(lane.error))
        native.request("status")
        preparation = native.guard.close()
        receipt["preparationGuard"] = {k: preparation[k] for k in (
            "ok", "violations", "owned_escaped_windows_hidden", "external_guard_entries")}
        if not preparation["ok"]:
            raise RuntimeError("Attributed disturbance during invisible preparation")
        receipt["idleWaitRequired"] = False
        guard = ZeroDisturbanceGuard().start()
        native.guard = guard
        if not guard.check()["ok"]:
            raise RuntimeError("Actual-run guard unavailable; no GUI launch admitted")
        def call(op, args):
            with request("/api/ui/cua/" + op, {"op": op, "args": args}) as response:
                data = json.load(response)
                if not data.get("ok"):
                    raise RuntimeError("HTTP CUA operation failed: " + str(data.get("error")))
                return data["data"]
        session = call("open", {"apps": [binary.stem, "calc"], "chatId": "c11-proof", "app": "neyvia"})
        sid = session["id"]
        state = scratch / "window.txt"
        launch = call("action", {"sessionId": sid, "tool": "launch_app",
            "args": {"path": str(binary), "args": [str(state)],
                "disposable_target": {"path": str(scratch), "token": scratch.name}}})
        if not (launch.get("launched") or launch.get("effect") == "launched"):
            raise RuntimeError("Isolated production launch failed: " + str(launch))
        until = time.monotonic() + 10
        while not state.exists() and time.monotonic() < until:
            if not guard.check()["ok"]:
                raise RuntimeError("Zero-disturbance failed during native startup")
            time.sleep(.02)
        if not state.exists():
            receipt["startupDiagnosis"] = {"processes": [{"pid": p.pid, "exitCode": p.poll()}
                for p in native.desktop.processes], "privateWindows": [{k: w.get(k) for k in
                    ("windowId", "pid", "className", "visible")} for w in native.desktop.windows()]}
            raise RuntimeError("Native app did not write its shown-window handle within ten seconds")
        wid = int(state.read_text())
        if not native.desktop.owns(wid):
            raise RuntimeError("Disposable preview HWND was not owned by this launch job")
        native.request("windows")
        receipt["previewFixtureBinding"] = native.desktop.disposable_target(wid)
        if not receipt["previewFixtureBinding"]:
            raise RuntimeError("Preview target did not bind to its public disposable launch scope")
        import ctypes as C
        from ctypes import wintypes as W
        native.desktop.u.SetWindowTextW.argtypes = [W.HWND, W.LPCWSTR]
        native.desktop.u.SetWindowTextW.restype = W.BOOL
        title = "C11 preview " + scratch.name
        if not native.desktop.u.SetWindowTextW(wid, title):
            raise RuntimeError("Could not label the independently owned preview window")
        observed_title = C.create_unicode_buffer(1024)
        native.desktop.u.GetWindowTextW(wid, observed_title, len(observed_title))
        if scratch.name not in observed_title.value:
            raise RuntimeError("Disposable preview token was absent from actual window title")
        receipt["fixtureOwnership"] = {"token": scratch.name, "title": observed_title.value,
            "windowId": wid, "path": str(scratch.relative_to(ROOT)), "jobOwned": True}
        receipt["launch"] = {"pid": launch["pid"], "desktop": launch["desktop"], "windowId": wid}
        from grant_agent.neyvia_cua_mcp import CuaMCPServer
        bridge = CuaMCPServer(base)
        bridge.client = {"chatId": "c11-proof", "app": "neyvia", "title": "C11 proof"}
        bridge.session_id = sid
        bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        mcp = bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "get_window_state", "arguments": {"window_id": wid, "include_screenshot": False}}})
        receipt["mcp"] = {"initialized": bridge._initialized,
            "nativeStateRead": bool(mcp and "result" in mcp and not mcp["result"].get("isError")),
            "error": (mcp or {}).get("error")}
        if not receipt["mcp"]["nativeStateRead"]:
            raise RuntimeError("Real MCP -> HTTP -> isolated native state failed")
        from grant_agent.cua_launch import server_spec
        os.environ["NEYVIA_UI_BACKEND_URL"] = base
        spec = server_spec("c11-proof", "neyvia", "C11 isolated proof")
        receipt["mcp"]["harnessSpecBound"] = bool(spec and spec["env"]["NEYVIA_UI_BACKEND_URL"] == base)
        if not receipt["mcp"]["harnessSpecBound"]:
            raise RuntimeError("Harness did not bind the explicit C11 proof port")
        if journey_probe:
            receipt["additionalJourneys"] = journey_probe(scratch, request, call, sid, wid, state)
        receipt["learning"] = prove_learning(call, sid, wid, state)
        first = call("inspect", {"sessionId": sid, "windowId": wid, "diff_only": True})
        receipt["clState"] = {"notation": "neyvia.window.cl-state.v1", "handle": first.get("handle"),
            "snapshot": first.get("snapshot_id")}
        input_frame = observe_controls(call, sid, wid, ["Task input"])
        receipt["inputObservation"] = input_frame
        input_control = next(e for e in input_frame["elements"] if e["label"] == "Task input")
        input_bounds = input_control["screenshot_frame"]
        selected = call("input", {"sessionId": sid, "windowId": wid, "kind": "click",
            "captureId": input_frame["capture_id"], "x": input_bounds["x"] + input_bounds["w"] / 2,
            "y": input_bounds["y"] + input_bounds["h"] / 2})
        receipt["inputSelection"] = selected
        if selected.get("status") != "ok":
            raise RuntimeError("Preview could not select the observed native Task input")
        edited = call("input", {"sessionId": sid, "windowId": wid,
            "kind": "type_text", "text": " C11 preview typed"})
        if edited.get("status") != "ok":
            receipt["typingObservation"] = call("snapshot", {"sessionId": sid, "windowId": wid})
            raise RuntimeError("Forwarded preview typing failed: " + str(edited.get("result")))
        changed = call("inspect", {"sessionId": sid, "windowId": wid,
            "diff_only": True, "previousHandle": first["handle"]})
        observation_deadline = time.monotonic() + .5
        observations = 1
        while not any(" C11 preview typed" in str(d.get("value", ""))
                      for d in changed.get("diff", [])) and time.monotonic() < observation_deadline:
            changed = call("inspect", {"sessionId": sid, "windowId": wid,
                "diff_only": True, "previousHandle": first["handle"]})
            observations += 1
        receipt["clState"].update(mode=changed.get("mode"), diff=changed.get("diff"),
            previousHandle=changed.get("previousHandle"), manual=first.get("manual"),
            observationAttempts=observations)
        if changed.get("mode") != "diff" or not any(" C11 preview typed" in str(d.get("value", ""))
                for d in changed.get("diff", [])):
            raise RuntimeError("Native CL observation did not report the typed effect as a diff")
        captured = observe_controls(call, sid, wid, ["Apply", "Task input", "Lock input", "Unlock input"])
        button = next(e for e in captured["elements"] if e["label"] == "Apply")
        query = urlencode({"sessionId": sid, "windowId": wid})
        with request("/api/ui/cua/frame?" + query) as response:
            png = response.read(2 * 1024 * 1024)
            capture_id = response.headers["X-Capture-Id"]
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Preview HTTP frame is not a native PNG")
        image_path = scratch / "preview.png"
        image_path.write_bytes(png)
        receipt["frame"] = {"bytes": len(png), "sha256": hashlib.sha256(png).hexdigest(),
            "file": str(image_path.relative_to(ROOT))}
        box = button["screenshot_frame"]
        stale = call("input", {"sessionId": sid, "windowId": wid, "kind": "click",
            "captureId": "expired-fixture-frame", "x": box["x"] + box["w"] / 2, "y": box["y"] + box["h"] / 2})
        receipt["staleFrameRefused"] = stale.get("status") == "refused"
        clicked = call("input", {"sessionId": sid, "windowId": wid, "kind": "click",
            "captureId": capture_id, "x": box["x"] + box["w"] / 2, "y": box["y"] + box["h"] / 2})
        effect = state.with_suffix(".txt.result").read_text()
        receipt["forwardedInput"] = {"typingStatus": edited["status"], "clickStatus": clicked["status"],
            "appWrittenEffect": effect}
        # Read the actual preview SSE route, including its native frame event.
        frame_events = []
        with request("/api/ui/cua/stream?sessionId=" + sid) as response:
            deadline = time.monotonic() + 10
            for _ in range(1024):
                if time.monotonic() >= deadline:
                    break
                line = response.readline(65536)
                if line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    if event["type"] == "frame":
                        frame_events.append(event["data"])
                        if len(frame_events) == 2:
                            break
        receipt["stream"] = {"nativeFrames": len(frame_events),
            "captureIds": [f["captureId"] for f in frame_events]}
        # SSE can replay pre-action events. Capture the current app after its
        # persisted effect before calling any screenshot the final frame.
        current = call("snapshot", {"sessionId": sid, "windowId": wid})
        final_png = service.frames[(sid, str(wid))]["raw"]
        final_path = output.with_suffix(".png")
        final_path.write_bytes(final_png)
        receipt["finalFrame"] = {"file": str(final_path.relative_to(ROOT)), "bytes": len(final_png),
            "sha256": hashlib.sha256(final_png).hexdigest()}
        receipt["engineJourneyPassed"] = (effect == "Applied: initial C11 preview typed" and clicked["status"] == "ok"
            and receipt["staleFrameRefused"] and len(frame_events) == 2 and receipt["mcp"]["nativeStateRead"])
        old_frame = service.frames[(sid, str(wid))]["metadata"]["captureId"]
        current = observe_controls(call, sid, wid, ["Lock input", "Task input"])
        lock_button = next(e for e in current["elements"] if e["label"] == "Lock input")
        locked = call("input", {"sessionId": sid, "windowId": wid, "kind": "click",
            "element_token": lock_button["element_token"]})
        input_box = next(e for e in current["elements"] if e["label"] == "Task input")["screenshot_frame"]
        disabled = call("input", {"sessionId": sid, "windowId": wid, "kind": "click", "captureId": old_frame,
            "x": input_box["x"] + input_box["w"] / 2, "y": input_box["y"] + input_box["h"] / 2})
        current = call("snapshot", {"sessionId": sid, "windowId": wid})
        until = time.monotonic() + 3
        while not any(e["label"] == "Unlock input" for e in current["elements"]) and time.monotonic() < until:
            time.sleep(.05)
            current = call("snapshot", {"sessionId": sid, "windowId": wid})
        unlock_button = next((e for e in current["elements"] if e["label"] == "Unlock input"), None)
        if unlock_button is None:
            receipt["unlockObservation"] = current
            raise RuntimeError("Native snapshot did not observe Unlock input; no unlock action issued")
        call("input", {"sessionId": sid, "windowId": wid, "kind": "click", "element_token": unlock_button["element_token"]})
        receipt["unlockVerified"] = call("verify", {"sessionId": sid, "window_id": wid,
            "expect": [{"element": {"selector": {"role": "Edit", "label": "Task input"}, "enabled_equals": True}}],
            "timeout_ms": 3000})
        if receipt["unlockVerified"].get("status") != "satisfied":
            raise RuntimeError("Input control did not independently verify enabled after unlock")
        current = call("snapshot", {"sessionId": sid, "windowId": wid})
        receipt["changedControlRefused"] = locked.get("status") == "ok" and disabled.get("status") == "refused"
        if not receipt["changedControlRefused"]:
            raise RuntimeError("Changed native control was not refused")
        # Use actual earlier capture geometry to choose browser pixels: this
        # disposable app never moves its controls when locking/unlocking.
        # Every forwarded input still binds the pane's fresh frame and native
        # control; no earlier token is sent or allowed to authorize delivery.
        receipt["renderedPreview"] = (exercise(ROOT, scratch, native, base, port, debug_port, sid, wid, captured, state,
            screenshot_path=output.with_name(output.stem + "-ui.png")) if render_ui else
            {"ok": False, "skipped": True, "reason": "Native-manual-only run; rendered preview is not claimed"})
        # Exercise the public optional target argument, not just the cohort's
        # direct fixture registration. This second launch stays private too.
        fixture_token = uuid.uuid4().hex
        fixture = scratch / fixture_token
        fixture.mkdir()
        fixture_state = fixture / "window.txt"
        fixture_launch = call("action", {"sessionId": sid, "tool": "launch_app", "args": {
            "path": str(binary), "args": [str(fixture_state)],
            "disposable_target": {"path": str(fixture), "token": fixture_token}}})
        receipt["publicFixtureLaunch"] = fixture_launch
        if not (fixture_launch.get("launched") or fixture_launch.get("effect") == "launched"):
            raise RuntimeError("Public disposable-target launch failed")
        until = time.monotonic() + 10
        while not fixture_state.exists() and time.monotonic() < until:
            time.sleep(.02)
        fixture_hwnd = int(fixture_state.read_text())
        native.request("windows")
        receipt["publicFixtureBinding"] = native.desktop.disposable_target(fixture_hwnd)
        if not receipt["publicFixtureBinding"] or receipt["publicFixtureBinding"]["token"] != fixture_token:
            raise RuntimeError("Public disposable-target argument was not bound to its actual owned HWND")
        receipt["ok"] = (effect == "Applied: initial C11 preview typed" and clicked["status"] == "ok"
            and receipt["staleFrameRefused"] and len(frame_events) == 2 and receipt["mcp"]["nativeStateRead"]
            and receipt["changedControlRefused"] and receipt["renderedPreview"]["ok"] and receipt["learning"]["ok"])
    except Exception as exc:
        receipt["error"] = type(exc).__name__ + ": " + str(exc)[:450]
        receipt["sourceFrames"] = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-6:]]
    finally:
        if service:
            receipt["frameFailures"] = [e["data"] for e in service.events
                if e.get("type") == "frame" and e.get("data", {}).get("unavailable")][-12:]
            service.shutdown()
        if server:
            server.shutdown()
            server.server_close()
        if guard:
            receipt["guard"] = guard.close()
            receipt["ok"] = receipt["ok"] and receipt["guard"]["ok"]
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt.get(k) for k in ("ok", "error", "forwardedInput", "stream")}))
    return receipt["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--debug-port", required=True, type=int)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.port not in range(48701, 48710):
        parser.error("C11 proof requires an explicit port in 48701-48709")
    if args.debug_port not in range(48701, 48710) or args.debug_port == args.port:
        parser.error("C11 proof requires a separate explicit CDP port in 48701-48709")
    raise SystemExit(0 if run(args.port, args.debug_port, args.receipt) else 2)
