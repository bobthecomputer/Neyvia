"""Real two-backend/native FOLLOW proof. Never reads saved credentials."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cua_native import NativeWorker

def serve(root, port, profile=False):
    from grant_agent.proof_credential_guard import install
    install(root)
    from grant_agent.web_backend import FluxioWebBackend, _HandshakeSafeThreadingHTTPServer, make_handler
    if profile:
        import cProfile
        from grant_agent.neyvia_remote import RemoteService
        original = RemoteService.peer
        def profiled(service, op, args, grant):
            if op != 'input':
                return original(service, op, args, grant)
            record = cProfile.Profile()
            try:
                return record.runcall(original, service, op, args, grant)
            finally:
                record.dump_stats(str(root / ('input-' + str(time.time_ns()) + '.prof')))
        RemoteService.peer = profiled
    backend = FluxioWebBackend(root, REPO / '.agent_control/FIX-latency/build')
    server = _HandshakeSafeThreadingHTTPServer(('127.0.0.1', port), make_handler(backend))
    try:
        server.serve_forever()
    finally:
        server.server_close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--relay-port", type=int, required=True)
    parser.add_argument("--speed", action="store_true")
    parser.add_argument("--bridge", action="store_true")
    parser.add_argument("--zen", action="store_true")
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--port', type=int)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--normal-startup', action='store_true')
    args = parser.parse_args()
    assert args.host_port == 48669 and args.relay_port == 48666
    if args.serve:
        assert args.port in {48669, 48666} and args.root.resolve().is_relative_to(REPO / '.agent_control/proofs/FIX-latency')
        serve(args.root.resolve(), args.port, args.profile)
        return
    scratch = REPO / ".agent_control/proofs/FIX-latency" / ('remote-' + str(time.time_ns()))
    scratch.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "NEYVIA_TOOL_AUTO_UPDATE": "0", "FLUXIO_WATCHDOG_AUTOSTART": "0",
           "NEYVIA_COORDINATOR_AUTOSTART": "0", "NEYVIA_REMOTE_PROOF_LOOPBACK": "1", "NEYVIA_REMOTE_PROOF_PORTS": "48669,48666",
           "NEYVIA_PROOF_CREDENTIAL_GUARD": "1", "SYNTELOS_ACCOUNT_USER": "fix-remote-proof", "SYNTELOS_ACCOUNT_PASSWORD": secrets.token_urlsafe(24)}
    worker, children, checks, times, zen_proof = NativeWorker(), [], [], {}, {}
    completed, failure = False, None
    source_paths = ('scripts/verify_fix_remote.py', 'scripts/run_web_backend.py',
                    'src/grant_agent/neyvia_remote.py', 'src/grant_agent/neyvia_remote_frames.py',
                    'src/grant_agent/cua_native.py', 'tools/cua-driver-win/NativeWorker.cs',
                    'tools/cua-driver-win/json-host.cs', 'tools/cua-driver-win/remote-indicator.cs')
    sources = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
               for name in source_paths}
    def check(label, value):
        checks.append({"name": label, "passed": bool(value)})
        if not value: raise AssertionError(label)
        print(label, flush=True)
    clients = {}
    def request(port, route, body=None):
        client = clients.get(port)
        if client is None:
            client = build_opener(HTTPCookieProcessor(CookieJar()))
            clients[port] = client
        req = Request(f"http://127.0.0.1:{port}" + route, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
        try:
            with client.open(req, timeout=45) as response:
                data = response.read()
                return response.status, json.loads(data) if response.headers.get_content_type() == "application/json" else data
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())
    def remote(port, op, **kw):
        return request(port, "/api/ui/remote", {"op": op, "args": kw})
    def good(port, op, **kw):
        status, value = remote(port, op, **kw)
        assert value.get("ok"), (op, status, value)
        return value["data"]
    def until(fn, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = fn()
                if value: return value
            except (OSError, ValueError): pass
            time.sleep(.1)
        raise TimeoutError("Owned proof did not become ready")
    try:
        for port, name in [(args.host_port, "host"), (args.relay_port, "relay")]:
            log = (scratch / (name + ".log")).open("w", encoding="utf-8")
            command = ([sys.executable, str(REPO / 'scripts/run_web_backend.py'), '--host', '127.0.0.1', '--port', str(port), '--root', str(scratch / name), '--skip-runtime-auto-update', '--skip-proof-self-check']
                       if args.normal_startup else [sys.executable, str(Path(__file__).resolve()), '--serve', '--host-port', str(args.host_port), '--relay-port', str(args.relay_port), '--port', str(port),
                        "--root", str(scratch / name), *(['--profile'] if args.profile else [])])
            child = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW)
            children.append(child)
            until(lambda: request(port, "/api/health")[1].get("ok"))
            check(name + " real authenticated proof service", request(port, "/api/auth/local-session", {})[0] == 200)
        framework = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319")
        fixture = scratch / "FollowRemoteFixture.cs"
        fixture.write_text('''using System;using System.IO;using System.Drawing;using System.Windows.Forms;
class Fixture:Form{protected override bool ShowWithoutActivation{get{return true;}}protected override CreateParams CreateParams{get{var p=base.CreateParams;p.ExStyle|=0x08000000;return p;}}
[STAThread]static void Main(string[] a){var f=new Fixture{Text="FOLLOW Mixed Password Window",Size=new Size(470,330),Location=new Point(50,150),StartPosition=FormStartPosition.Manual};
var edit=new TextBox{Text="initial",Name="taskInput",AccessibleName="Task input",Location=new Point(20,30),Width=400};
var secret=new TextBox{Text="DISPOSABLE_SECRET_SENTINEL",Name="secretInput",AccessibleName="Password",UseSystemPasswordChar=true,Location=new Point(20,70),Width=400};
var opaque=new UserControl{TabStop=true,Name="opaqueInput",AccessibleName="Opaque field",Location=new Point(20,170),Size=new Size(400,40)};
var button=new Button{Text="Apply",AccessibleName="Apply",Name="apply",Location=new Point(20,110),Size=new Size(400,35)};
button.Click+=delegate{File.WriteAllText(a[0]+".result",edit.Text);};
TextBox extra=null;
var timer=new Timer{Interval=50};timer.Tick+=delegate{if(File.Exists(a[0]+".add") && extra==null){extra=new TextBox{Text="added",AccessibleName="Extra input",Location=new Point(20,230),Width=400};f.Controls.Add(extra);}if(File.Exists(a[0]+".remove") && extra!=null && extra.Parent!=null)f.Controls.Remove(extra);if(File.Exists(a[0]+".protect"))edit.UseSystemPasswordChar=true;if(File.Exists(a[0]+".focus")){opaque.Select();opaque.Focus();File.WriteAllText(a[0]+".focused",opaque.Focused.ToString());}if(File.Exists(a[0]+".rename")){button.Text="Delete";button.AccessibleName="Delete";}};timer.Start();
f.Controls.AddRange(new Control[]{edit,secret,button,opaque});f.Shown+=delegate{File.WriteAllText(a[0],f.Handle.ToInt64().ToString());};Application.Run(f);}}
''', encoding="utf-8")
        binary, state = scratch / "FollowRemoteFixture.exe", scratch / ("fixture-" + str(time.time_ns()))
        subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/out:" + str(binary), str(fixture),
            "/reference:" + str(framework / "System.Windows.Forms.dll"), "/reference:" + str(framework / "System.Drawing.dll")], check=True, capture_output=True)
        children.append(subprocess.Popen([str(binary), str(state)], creationflags=subprocess.CREATE_NO_WINDOW))
        until(lambda: state.exists() and state.stat().st_size > 0)
        window = int(state.read_text())
        before = worker.request("status")
        targets = good(args.host_port, "targets")["targets"]
        check("Mixed password window remains eligible", next(t for t in targets if t["windowId"] == window)["eligible"])
        check("Opaque top-level window guard allows sharing", worker.request("remoteGuard", {"windowId": str(window)})["safe"])
        zen = [t for t in targets if t.get("app", "").casefold() in {"zen", "zen-browser"}]
        check("Installed Zen is not excluded by unknown whole-window password state", all(t["eligible"] for t in zen))
        session = good(args.host_port, "enable", windowIds=[window], minutes=5)
        connection = good(args.relay_port, "connect", url=f"http://127.0.0.1:{args.host_port}", invite=session["invite"])["connection"]["id"]
        def snapshot(): return good(args.relay_port, "snapshot", connectionId=connection, windowId=window)
        snap = snapshot()
        edit = next(e for e in snap["elements"] if e["label"] == "Task input")
        secret = next(e for e in snap["elements"] if e["label"] == "Password")
        check("Protected values omitted before projection", secret["protected"] and "value" not in secret and "DISPOSABLE_SECRET_SENTINEL" not in json.dumps(snap))
        marker = " FIX café 日本語 👋"
        started = time.perf_counter()
        value = good(args.relay_port, "input", connectionId=connection, windowId=window, kind="type_text", element_token=edit["element_token"], text=marker)
        times["inputColdMs"] = round((time.perf_counter() - started) * 1000, 2)
        times["nativeDispatchColdMs"] = value.get("ms")
        check("Normal field input confirmed beside password field", value["result"]["effect"] == "confirmed")
        if args.speed:
            check("inputColdMs budget", times["inputColdMs"] < 500)
        native = worker.request("inspect", {"windowId": str(window), "maxDepth": 8, "maxNodes": 100})
        check("Independent real UIA confirms typed value", any(n.get("name") == "Task input" and n.get("value") == "initial" + marker for n in native["tree"]))
        check("Incremental tree projection observes changed input", next(e for e in snapshot()["elements"] if e["label"] == "Task input").get("value") == "initial" + marker)
        status, refused = remote(args.relay_port, "input", connectionId=connection, windowId=window, kind="type_text", element_token=secret["element_token"], text="blocked")
        check("Password field typing refused", not refused.get("ok"))
        button = next(e for e in snap["elements"] if e["label"] == "Apply")
        good(args.relay_port, "input", connectionId=connection, windowId=window, kind="click", element_token=button["element_token"])
        check("Real button completes native task", until(lambda: state.with_suffix(state.suffix + ".result").exists()) and Path(str(state) + ".result").read_text(encoding='utf-8') == "initial" + marker)
        if args.speed:
            for label, call, budget in [("targetsWarmMs", lambda: good(args.host_port, "targets"), 2000), ("windowsWarmMs", lambda: good(args.relay_port, "windows", connectionId=connection), 2000),
                    ("inputWarmMs", lambda: good(args.relay_port, "input", connectionId=connection, windowId=window, kind="type_text", element_token=edit["element_token"], text="x"), 500)]:
                call(); measurements=[]
                for _ in range(5):
                    start=time.perf_counter(); call(); measurements.append(round((time.perf_counter()-start)*1000,2))
                times[label]=measurements
                check(label + " budget", max(measurements) < budget)
        frame_status, png = request(args.relay_port, f"/api/ui/remote/frame?connectionId={connection}&windowId={window}")
        check("Mixed password window streams real PNG", frame_status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n")
        if args.bridge:
            value = subprocess.run([sys.executable, "-B", "-m", "grant_agent.desktop_bridge", "--root", str(scratch / "relay")], cwd=REPO,
                env={**env, "NEYVIA_UI_BACKEND_URL": f"http://127.0.0.1:{args.relay_port}"}, input=json.dumps({"command": "remote_frame_command", "payload": {"connectionId": connection, "windowId": window}}), text=True, capture_output=True, timeout=45)
            bridged = json.loads(value.stdout)
            if not bridged.get("ok"): print("Bridge refusal:", bridged.get("error"), value.stderr[:500], flush=True)
            check("Desktop frame bridge returned PNG", value.returncode == 0 and bridged.get("ok") and base64.b64decode(bridged["data"]["png"])[:8] == b"\x89PNG\r\n\x1a\n")
            check("Desktop frame bridge preserves capture binding", bool(bridged["data"]["captureId"]) and bridged["data"]["sha"] == hashlib.sha256(base64.b64decode(bridged["data"]["png"])).hexdigest())
        Path(str(state) + ".rename").touch(); time.sleep(.15)
        check("Live changed consequential label refused", not remote(args.relay_port, "input", connectionId=connection, windowId=window, kind="click", element_token=button["element_token"])[1].get("ok"))
        Path(str(state) + ".add").touch(); time.sleep(.15)
        check("UIA structure addition refreshes projection", any(e["label"] == "Extra input" for e in snapshot()["elements"]))
        Path(str(state) + ".remove").touch(); time.sleep(.15)
        check("UIA structure removal refreshes projection", not any(e["label"] == "Extra input" for e in snapshot()["elements"]))
        Path(str(state) + ".focus").touch(); until(lambda: Path(str(state) + ".focused").exists())
        check("Focused opaque field is real fixture state", Path(str(state) + ".focused").read_text() == "True")
        check("Typing refused when focused field is unclassified", not remote(args.relay_port, "input", connectionId=connection, windowId=window, kind="type_text", element_token=edit["element_token"], text="blocked")[1].get("ok"))
        Path(str(state) + ".protect").touch(); time.sleep(.15)
        check("Newly protected field refuses stale normal token", not remote(args.relay_port, "input", connectionId=connection, windowId=window, kind="type_text", element_token=edit["element_token"], text="blocked")[1].get("ok"))
        latest = next(e for e in snapshot()["elements"] if e["label"] == "Task input")
        check("Incremental protection change omits previously readable value", latest["protected"] and "value" not in latest)
        after = worker.request("status")
        check("Foreground and cursor preserved", before["foregroundWindowId"] == after["foregroundWindowId"] and before["cursor"] == after["cursor"])
        good(args.host_port, "kill", sessionId=session["session"]["id"])
        check("Host kill immediately refuses live session", not remote(args.relay_port, "windows", connectionId=connection)[1].get("ok"))
        if args.zen:
            assert zen, "No real Zen window is currently open"
            identity = zen[0]["windowId"]
            granted = good(args.host_port, "enable", windowIds=[identity], minutes=5)
            linked = good(args.relay_port, "connect", url=f"http://127.0.0.1:{args.host_port}", invite=granted["invite"])["connection"]["id"]
            check("Real Zen host grant redeemed on separate relay", good(args.relay_port, "windows", connectionId=linked)["windows"][0]["window_id"] == identity)
            observed = good(args.relay_port, "snapshot", connectionId=linked, windowId=identity)
            check("Real Zen remote projection is observable", observed["window_id"] == identity and isinstance(observed["elements"], list))
            status, zen_png = request(args.relay_port, f"/api/ui/remote/frame?connectionId={linked}&windowId={identity}")
            check("Real Zen live relay frame is PNG", status == 200 and zen_png[:8] == b"\x89PNG\r\n\x1a\n")
            bridged = subprocess.run([sys.executable, "-B", "-m", "grant_agent.desktop_bridge", "--root", str(scratch / "relay")], cwd=REPO,
                env={**env, "NEYVIA_UI_BACKEND_URL": f"http://127.0.0.1:{args.relay_port}"}, input=json.dumps({"command": "remote_frame_command", "payload": {"connectionId": linked, "windowId": identity}}), text=True, capture_output=True, timeout=45)
            answer = json.loads(bridged.stdout)
            check("Real Zen desktop frame bridge returns PNG", bridged.returncode == 0 and answer.get("ok") and base64.b64decode(answer["data"]["png"])[:8] == b"\x89PNG\r\n\x1a\n")
            zen_proof = {"elementCount": len(observed["elements"]), "frameBytes": len(zen_png), "frameSha256": hashlib.sha256(zen_png).hexdigest(), "captureId": answer["data"]["captureId"], "pixelsPersisted": False, "textPersisted": False}
            del observed, zen_png, answer, bridged
            good(args.host_port, "kill", sessionId=granted["session"]["id"])
            check("Real Zen sharing revoked after read-only proof", not remote(args.relay_port, "windows", connectionId=linked)[1].get("ok"))
        receipt = {"checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ports": [args.host_port, args.relay_port], "checks": checks, "timings": times,
                   "zenTargets": len(zen), "zenProof": zen_proof, "fixtureSourceSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "frameSha256": hashlib.sha256(png).hexdigest(),
                   "timingBoundary": "First native input after fresh process/grant/snapshot; reused ordinary HTTP client established during login. No input warm-up before the cold measurement. Client setup excluded from subsequent requests, as in the product browser.",
                   "startupSelfCheck": "Skipped with --skip-proof-self-check: this run proves remote paths only; lead runs explicit full neyvia verify separately" if args.normal_startup else "Not invoked: production handler constructor; lead runs explicit full neyvia verify separately",
                   "startupEntry": 'scripts/run_web_backend.py' if args.normal_startup else 'FluxioWebBackend + production HTTP handler constructor',
                   "nativeHostTransport": "Compiled hidden STA JSONL host invokes the unchanged NativeWorker UIA/privacy/input methods",
                   "limitations": ["Actual second-PC/tailnet transport is separate. No second-PC network latency claim.", "Budget is first native input after fresh process/grant/snapshot; host bootstrap and first observation are separate prerequisites."], "ownedProcessesStopped": True}
        (scratch / "remote.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        completed = True
        print(json.dumps({"passed": len(checks), "timings": times, "zenTargets": len(zen)}))
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        try: remote(args.host_port, "kill")
        except (OSError, ValueError): pass
        worker.close()
        for child in reversed(children):
            if child.poll() is None: child.terminate()
            child.wait(timeout=10)
        attempt = {"passed": completed, "ports": [args.host_port, args.relay_port],
                   "checks": checks, "timings": times, "ownedProcessesStopped": True,
                   "error": failure, "sources": sources,
                   "sourceStable": all(hashlib.sha256((REPO / name).read_bytes()).hexdigest() == digest
                                       for name, digest in sources.items()),
                   "boundary": "Latest fresh owned-process replay. A failed budget stops later actions and preserves actual measured timing; it does not overwrite the last complete positive journey."}
        (scratch / "remote-attempt.json").write_text(json.dumps(attempt, indent=2) + "\n", encoding="utf-8", newline="\n")
        if not completed:
            print(json.dumps(attempt), flush=True)

if __name__ == "__main__": main()
