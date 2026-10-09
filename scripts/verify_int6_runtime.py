"""INT6 real HTTP integration proof against an explicitly owned scratch backend.

No simulated browser/ASR reports, external downloads, harness launches or private
credentials. Optional browser-native uses the real task-only Tauri executable.
Missing runtime mechanisms stay separate from unexpected integration failures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
ABSENT = object()


def masked(value):
    if isinstance(value, dict):
        return {key: {"encodedBytes": len(item)} if key == "pcm" and isinstance(item, str) else
                "[masked]" if any(part in key.lower() for part in
                ("password", "capability", "invite", "token", "cookie")) else masked(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [masked(row) for row in value]
    return value


def unwrap(value):
    while isinstance(value, dict) and isinstance(value.get("result"), dict) and (value["result"] or value.get("ok") is not False):
        value = value["result"]
    return value


class Proof:
    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.output = args.output.resolve()
        self.http = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.anonymous = build_opener(ProxyHandler({}))
        self.receipt = {"schema": "neyvia.INT6-runtime/v1", "baseUrl": args.base_url,
                        "stateRoot": str(self.root), "startedAt": time.time(),
                        "calls": [], "checks": [], "missing": [],
                        "boundary": "Real authenticated scratch HTTP; optional actual native runtimes; no public release or cross-PC claim"}
        self.children = []

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(masked(self.receipt), indent=2) + "\n", encoding="utf-8")

    def request(self, path, body=ABSENT, *, authenticated=True, headers=None, expected=(200,)):
        data = None if body is ABSENT else body if isinstance(body, bytes) else json.dumps(body).encode()
        request = Request(self.args.base_url + path, data=data,
                          headers={"Content-Type": "application/json", **(headers or {})})
        began = time.monotonic()
        began_at = datetime.now(timezone.utc).isoformat()
        try:
            response = (self.http if authenticated else self.anonymous).open(request, timeout=self.args.timeout)
        except HTTPError as exc:
            response = exc
        raw = response.read()
        status = response.code
        if response.headers.get_content_type() == "image/png":
            value = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "format": "png"}
            (self.root / "int6-remote-frame.png").write_bytes(raw)
        else:
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                value = {"unparsedBytes": len(raw)}
        self.receipt["calls"].append({"path": path, "method": request.get_method(), "startedAt": began_at,
            "request": {"rawBytes": len(body)} if isinstance(body, bytes) else None if body is ABSENT else masked(body),
            "status": status, "expectedStatus": list(expected), "ms": round((time.monotonic() - began) * 1000),
            "response": masked(value)})
        self.save()
        assert status in expected, f"{path}: HTTP {status}, expected {expected}: {value}"
        return value

    def command(self, command, payload=None, **kwargs):
        value = self.request("/api/backend", {"command": command, "payload": payload or {}}, **kwargs)
        return value.get("data", value)

    def tool(self, name, arguments=None, **kwargs):
        value = self.request("/api/ui/tools/call", {"tool": "neyvia." + name, "arguments": arguments or {}}, **kwargs)
        return unwrap(value.get("data", value))

    def check(self, name, operation):
        began = time.monotonic()
        try:
            result = operation()
        except Exception as exc:
            self.receipt["checks"].append({"name": name, "ok": False, "error": str(exc)})
            print(f"FAIL {name}: {exc}", flush=True)
        else:
            self.receipt["checks"].append({"name": name, "ok": True, "ms": round((time.monotonic() - began) * 1000), "result": masked(result)})
            print(f"PASS {name}", flush=True)
        self.save()

    def missing(self, mechanism, reason):
        self.receipt["missing"].append({"mechanism": mechanism, "reason": reason})
        self.save()


def tool_registry(proof):
    rows = proof.request("/api/ui/tools")["data"]["tools"]
    registered = {row["name"] for row in rows}
    expected = {"neyvia." + name for name in (
        "mission.from_plan", "view.ambient", "dictation.process", "dictation.names",
        "settings.get", "settings.propose", "settings.setup", "settings.network_check",
        "remote.state", "remote.windows", "remote.snapshot", "remote.log",
        "browser.state", "browser.open", "browser.tab", "browser.observe", "browser.action",
        "browser.history", "browser.downloads", "browser.decide", "browser.receipt",
        "browser.promote", "browser.capture", "browser.wait")}
    assert not expected - registered, sorted(expected - registered)
    return {"allAddedToolsRegistered": sorted(expected), "count": len(expected)}


def backend_track(proof):
    validation = proof.tool("manual.validate")
    assert validation["ok"], validation
    for on in (False, True):
        result = proof.tool("view.ambient", {"on": on})
        assert result["on"] is on and result["event"]["action"] == "view.ambient"
    rejected = proof.tool("view.ambient", {"on": "invalid"})
    assert rejected.get("ok") is False, rejected
    fixture = proof.root / "plan-fixture"
    fixture.mkdir(exist_ok=True)
    for track in ("alpha", "beta"):
        directory = fixture / track
        directory.mkdir(exist_ok=True)
        if not (directory / ".git").exists():
            subprocess.run(["git", "init", "--quiet", str(directory)], check=True, capture_output=True)
    plan = fixture / "plan.md"
    plan.write_text("## §0 shared\nStore dormant. Never launch.\n\n"
                    "| Track | Worktree | Backend | Vite |\n|---|---|---|---|\n"
                    "| alpha | alpha | 48356 | 48357 |\n| beta | beta | 48358 | 48359 |\n"
                    "\n## §1 alpha: first\nStore alpha task.\n## §2 beta: second\nStore beta task.\n", encoding="utf-8")
    args = {"id": "int6-plan-" + str(time.time_ns()), "planPath": str(plan),
            "folder": str(fixture), "acceptanceChecks": ["Both tracks independently verified"]}
    created = proof.tool("mission.from_plan", args)
    assert created.get("template") == "lead-claude-codex", created
    proof.request("/api/ui/missions")
    plan.write_text(plan.read_text(encoding="utf-8").replace("| beta | beta |", "| beta | alpha |"), encoding="utf-8")
    denied = proof.tool("mission.from_plan", {**args, "id": "int6-invalid-" + str(time.time_ns())})
    assert denied.get("ok") is False or denied.get("error"), denied
    return {"manualValidation": validation, "mission": created, "dormantOnly": True}


def dictation_track(proof):
    cleaned = proof.request("/api/ui/dictation/process", {"text": "um cloud code build this new line send it", "history": [], "final": True})["data"]
    assert "Claude Code" in cleaned["text"], cleaned
    assert {row["op"] for row in cleaned["commands"]} >= {"new_line", "send"}, cleaned
    provisional = proof.tool("dictation.process", {"text": "send it", "final": False})
    assert not provisional["commands"] and provisional["requiresPreview"], provisional
    quoted = proof.command("dictation_process_command", {"text": 'write "send it" literally', "final": True})
    assert not quoted["commands"], quoted
    for language_text, language in (("Please write the prompt for this build", "en"), ("Je veux écrire ce prompt pour demain", "fr")):
        value = proof.tool("dictation.process", {"text": language_text})
        assert value["language"] == language, value
    proof.request("/api/ui/dictation/names")
    alias = {"action": "add", "to": "INTSix", "from": ["in tee six"]}
    proof.request("/api/ui/dictation/names", alias)
    proof.tool("dictation.names")
    proof.command("dictation_names_command", {"action": "remove", "to": "INTSix", "from": ["in tee six"]})
    proof.request("/api/ui/dictation/process", {"text": 12}, expected=(400,))
    proof.request("/api/ui/dictation/redecode/int6-missing", {}, expected=(400,))
    proof.command("dictation_redecode_command", {"sid": "int6-missing"}, expected=(400,))
    # This never starts either recognizer. The owning backend must have engine
    # URL env vars selected within INT6 ports before this script is invoked.
    configured = proof.command("dictation_settings_command", {"settings": {"port": 48357, "qwenUrl": "http://127.0.0.1:48352", "enabled": False}})
    assert configured["settings"]["port"] == 48357 and configured["settings"]["qwenUrl"] == "http://127.0.0.1:48352", configured
    assert configured["settings"]["enabled"] is False, configured
    proof.request("/api/ui/dictation/status")
    proof.command("dictation_status_command", {"start": False})
    proof.tool("dictation.status", {"start": False})
    proof.request("/api/ui/dictation/transcribe?engine=auto", b"x", expected=(400,))
    proof.request("/api/ui/dictation/stream/int6-stream/append?seq=1", b"x", expected=(400,))
    proof.request("/api/ui/dictation/stream/int6-finish/finish?seq=1", b"x", expected=(400,))
    proof.command("dictation_stream_command", {"sid": "int6-command", "op": "append", "seq": 1, "pcm": "eA=="}, expected=(400,))
    proof.request("/api/ui/dictation/stream/int6-cancel/cancel?seq=1", b"")
    proof.command("dictation_transcribe_command", {"engine": "invalid", "pcm": ""}, expected=(400,))
    denied = proof.tool("dictation.transcribe", {"path": str(proof.root / "no-audio.wav")})
    assert denied.get("ok") is False or denied.get("error"), denied
    if proof.args.audio_file:
        cleaned["realAudio"] = dictation_audio(proof)
        proof.missing("T1 French/mixed ASR and microphone", "Real recorded English speech uses the shared CPU Phonon-2 engine; no local multilingual PCM recognizer or live microphone journey supplied")
    else:
        proof.missing("T1 real ASR streaming and microphone", "No --audio-file supplied; text/grammar and malformed-audio paths are live")
    return {"cleanup": cleaned, "provisional": provisional, "quoted": quoted}


def dictation_audio(proof):
    source = proof.args.audio_file.resolve()
    with wave.open(str(source), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000), "Expected recorded 16 kHz mono PCM16"
        pcm = audio.readframes(audio.getnframes())
    assert pcm, "Recorded audio fixture is empty"
    sid = "int6-real-" + str(time.time_ns())
    partials, previous, seq = [], "", 0
    started = time.monotonic()
    for offset in range(0, len(pcm), 8000):
        chunk = pcm[offset:offset + 8000]
        result = proof.request(f"/api/ui/dictation/stream/{sid}/append?seq={seq}&history=%5B%22en%22%5D", chunk)["data"]
        assert result["stable"].startswith(previous) or result.get("revision"), "Stable frontier changed without an explicit revision"
        previous = result["stable"]
        partials.append(result)
        if seq == 0:
            duplicate = proof.request(f"/api/ui/dictation/stream/{sid}/append?seq=0", chunk)["data"]
            assert duplicate["duplicate"], duplicate
        seq += 1
        delay = started + min(offset + 8000, len(pcm)) / 32000 - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    released = time.monotonic()
    final = proof.request(f"/api/ui/dictation/stream/{sid}/finish?seq={seq}", b"")["data"]
    release_ms = round((time.monotonic() - released) * 1000)
    assert final["stable"].startswith(previous) or final.get("revision"), "Final changed stable frontier without an explicit revision"
    assert final["engine"] == "phonon2" and final["device"] == "cpu", final
    assert "ordinary sentence" in final["text"].lower() and not final["provisional"], final
    duplicate = proof.request(f"/api/ui/dictation/stream/{sid}/finish?seq={seq}", b"")["data"]
    assert duplicate["duplicate"] and duplicate["text"] == final["text"], duplicate
    transcribed = proof.request("/api/ui/dictation/transcribe?engine=auto&history=%5B%22en%22%5D", pcm)["data"]
    assert "ordinary sentence" in transcribed["text"].lower(), transcribed
    command = proof.command("dictation_transcribe_command", {"path": str(source), "engine": "auto", "history": ["en"]})
    model = proof.tool("dictation.transcribe", {"path": str(source), "engine": "auto", "history": ["en"]})
    assert "ordinary sentence" in command["text"].lower() and "ordinary sentence" in model["text"].lower(), (command, model)
    return {"path": str(source), "audioSha256": hashlib.sha256(pcm).hexdigest(), "audioMs": len(pcm) / 32,
            "releaseToTextMs": release_ms, "partials": partials,
            "stablePartials": sum(bool(row["stable"]) for row in partials), "final": final,
            "boundary": "Existing real recording, English-only CPU shared engine; no microphone/French claim"}


def settings_track(proof):
    proof.request("/api/ui/settings", authenticated=False, expected=(401,))
    saved = proof.request("/api/ui/settings")["data"]
    # Prove local-only before any broker-backed mission observer starts idle CLI
    # infrastructure. The owner prepares this canonical state before startup.
    if not saved["settings"]["localOnly"]:
        saved = proof.command("settings_update_command", {"expectedRevision": saved["revision"], "patch": {"localOnly": True}})
    assert saved["network"]["activeChildren"] == 0, saved["network"]
    try:
        report = proof.command("settings_network_check_command")
        assert report["ok"] and all(row["blocked"] for row in report["checks"]), report
        via_tool = proof.tool("settings.network_check")
        assert via_tool["ok"], via_tool
    finally:
        current = proof.command("settings_get_command")
        proof.command("settings_update_command", {"expectedRevision": current["revision"], "patch": {"localOnly": False}})
    saved = proof.request("/api/ui/settings")["data"]
    proposed = proof.tool("settings.propose", {"patch": {"density": "workshop"}, "expectedRevision": saved["revision"]})
    assert proposed["status"] == "approval_required", proposed
    proof.request("/api/ui/approve", {"id": proposed["approvalId"]})
    current = proof.tool("settings.get")
    assert current["settings"]["density"] == "workshop", current
    proof.request("/api/ui/approve", {"id": proposed["approvalId"]})
    repeated = proof.tool("settings.get")
    assert repeated["revision"] == current["revision"], "Repeated approval applied twice"
    proof.request("/api/ui/settings", {"expectedRevision": saved["revision"], "patch": {"theme": "morning"}}, expected=(409,))
    current = proof.command("settings_get_command")
    proof.request("/api/ui/settings", {"expectedRevision": current["revision"], "patch": {"theme": "morning", "initiative": "act-and-tell"}})
    proof.request("/api/ui/settings/setup", {})
    proof.tool("settings.setup")
    proof.command("settings_setup_command")
    proof.command("settings_network_check_command", expected=(409,))
    return {"proposal": proposed, "networkRefusals": report, "localOnlyRestoredOff": True}


def installer_track(proof):
    rows = []
    for path in sorted((REPO / "config/onboarding_packs").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows.append({"path": str(path.relative_to(REPO)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "packId": manifest.get("packId"), "fileCount": len(manifest.get("files", [])),
                     "deliveryStatus": manifest.get("deliveryStatus")})
    added = {"pack." + name for name in ("android-lab", "developer-toolchains", "documents-office",
             "media-creative", "mesh-control-plane", "models-gpu", "ocr-local")}
    assert added <= {row["packId"] for row in rows}, rows
    probe = REPO / "src-tauri/target/pack-probe/debug/neyvia-pack-probe.exe"
    proof.missing("T6 signed resumable Rust base-pack install", "Native bootstrap has no added HTTP/model tools; run relocated verify_T6.mjs with real pack-probe and signed local release. " +
                  ("Rust pack-probe exists" if probe.exists() else "Rust pack-probe binary absent in this worktree"))
    return {"externalManifestsParsed": rows, "nativeOnlyCommands": ["onboarding_base_pack_status_command", "onboarding_base_pack_start_command", "onboarding_base_pack_pause_command"], "downloadedBytes": 0}


def remote_request(proof, op, args=None, **kwargs):
    value = proof.request("/api/ui/remote", {"op": op, "args": args or {}}, **kwargs)
    return value.get("data", value)


def remote_track(proof):
    remote_request(proof, "state", authenticated=False, expected=(401,))
    remote_request(proof, "state", headers={"Origin": "https://unrelated.invalid"}, expected=(403,))
    remote_request(proof, "connect", {"url": "http://example.invalid", "invite": "x" * 32}, expected=(403,))
    proof.request("/api/ui/remote/state")
    proof.tool("remote.state")
    for op in ("windows", "snapshot", "log"):
        value = proof.tool("remote." + op, {"connectionId": "int6-missing", "windowId": 1})
        assert value.get("ok") is False or value.get("error"), value
    proof.request("/api/ui/remote/windows?connectionId=int6-missing", expected=(404,))
    proof.request("/api/ui/remote/frame?connectionId=int6-missing&windowId=1", expected=(404,))
    for op in ("redeem", "windows", "snapshot", "frame", "input", "log", "end"):
        proof.request("/api/ui/remote/peer/" + op, {}, authenticated=False, expected=(400, 401, 403))
    remote_request(proof, "enable", {"windowIds": []}, expected=(400,))
    remote_request(proof, "disconnect", {"connectionId": "int6-missing"}, expected=(404,))
    remote_request(proof, "input", {"connectionId": "int6-missing", "windowId": 1}, expected=(404,))
    remote_request(proof, "kill")
    if not proof.args.native_remote:
        proof.missing("T19 real native relay", "Use --native-remote to compile/open the disposable Windows Forms app and drive real T16 through loopback HTTP")
        return {"failurePaths": True}
    return native_remote(proof)


def native_remote(proof):
    framework = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319")
    binary = proof.root / "INT6NativeProbe.exe"
    compiled = subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/out:" + str(binary),
        str(REPO / "tools/cua-driver-win/remote-probe.cs"), "/reference:" + str(framework / "System.Windows.Forms.dll"),
        "/reference:" + str(framework / "System.Drawing.dll")], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    window_file = proof.root / ("remote-window-" + str(time.time_ns()))
    child = subprocess.Popen([str(binary), str(window_file)], creationflags=subprocess.CREATE_NO_WINDOW)
    proof.children.append(child)
    deadline = time.monotonic() + proof.args.timeout
    while not window_file.exists() and time.monotonic() < deadline:
        assert child.poll() is None, "Disposable native app exited"
        time.sleep(.1)
    assert window_file.exists(), "Disposable native app did not expose its HWND"
    window = int(window_file.read_text())
    proof.request("/api/ui/remote/targets")
    enabled = remote_request(proof, "enable", {"windowIds": [window], "minutes": 5, "name": "INT6 native loopback"})
    assert enabled["session"]["indicator"]["visible"], enabled
    session = enabled["session"]["id"]
    try:
        connected = remote_request(proof, "connect", {"url": proof.args.base_url, "invite": enabled["invite"]})
        cid = connected["connection"]["id"]
        remote_request(proof, "connect", {"url": proof.args.base_url, "invite": enabled["invite"]}, expected=(401,))
        args = {"connectionId": cid, "windowId": window}
        proof.tool("remote.windows", args)
        snap = proof.tool("remote.snapshot", args)
        proof.request("/api/ui/remote/windows?" + urlencode({"connectionId": cid}))
        proof.request("/api/ui/remote/frame?" + urlencode(args))
        entry = next(row for row in snap["elements"] if row.get("label") == "Task input")
        remote_request(proof, "input", {**args, "kind": "type_text", "element_token": entry["element_token"], "text": "INT6 live native"})
        snap = proof.tool("remote.snapshot", args)
        apply = next(row for row in snap["elements"] if row.get("label") == "Apply")
        remote_request(proof, "input", {**args, "kind": "click", "element_token": apply["element_token"]})
        deadline = time.monotonic() + 8
        output = Path(str(window_file) + ".result")
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        assert output.exists() and "INT6 live native" in output.read_text(), "Actual app never applied the input"
        proof.tool("remote.log", {"connectionId": cid})
        remote_request(proof, "disconnect", {"connectionId": cid})
        remote_request(proof, "windows", {"connectionId": cid}, expected=(409,))
        return {"actualNativeText": output.read_text(), "windowId": window, "hostIndicator": enabled["session"]["indicator"], "boundary": "One PC, actual native window over authenticated loopback HTTP, no Tailscale or cross-PC proof"}
    finally:
        remote_request(proof, "kill", {"sessionId": session})


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/download":
            raw = b"INT6 actual native download\n"
            kind = "application/octet-stream"
        else:
            raw = b'''<!doctype html><title>INT6 live browser</title><h1>INT6 browser fixture</h1>
<label>Name<input aria-label="Name" id="name"></label><button onclick="document.getElementById('result').textContent='Saved: '+document.getElementById('name').value">Save</button>
<p id="result">Waiting</p><label>Secret<input type="password" aria-label="Secret" value="INT6-private-canary"></label><a href="/second">Second page</a><a href="/download" download="int6.txt">Download</a>'''
            kind = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        if self.path == "/download":
            self.send_header("Content-Disposition", 'attachment; filename="int6.txt"')
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


def browser_request(proof, op, args=None, **kwargs):
    return proof.request("/api/ui/browser", {"op": op, "args": args or {}}, **kwargs)


def completed(proof, action):
    if not action.get("actionId"):
        return action
    deadline = time.monotonic() + proof.args.timeout
    while time.monotonic() < deadline:
        row = browser_request(proof, "action.get", {"actionId": action["actionId"]})
        assert row["status"] != "failed", row
        if row["status"] == "done":
            return row
        time.sleep(.15)
    raise AssertionError("Actual native action did not complete before the configurable HTTP timeout")


def browser_commands(proof, tab, action_id):
    """All thirteen command registrations use the real HTTP dispatcher."""
    for name, payload in (("call", {"op": "state"}), ("state", {}), ("open", {"url": "http://127.0.0.1:48353/second"}),
                          ("tab", {"tabId": tab, "op": "update", "pinned": True}), ("history", {}), ("downloads", {}),
                          ("receipt", {"actionId": action_id}), ("observe", {"tabId": tab, "cached": True}),
                          ("action", {"tabId": tab, "revision": "missing", "element": "missing", "action": "click"}),
                          ("decide", {"tabId": tab, "question": "Choose Save"}), ("promote", {"tabId": tab}),
                          ("capture", {"tabId": tab}), ("wait", {"actionId": action_id, "timeoutMs": 100})):
        proof.command("browser_" + name + "_command", payload, expected=(200, 400))


def browser_track(proof):
    proof.request("/api/ui/browser", authenticated=False, expected=(401,))
    proof.request("/api/ui/browser/runtime", {"op": "poll", "token": "invalid"}, authenticated=False, expected=(403,))
    browser_request(proof, "state", headers={"Origin": "https://unrelated.invalid"}, expected=(403,))
    browser_request(proof, "tab.open", {"url": "file:///C:/Windows"}, expected=(400,))
    state = proof.tool("browser.state")
    opened = proof.tool("browser.open", {"url": "http://127.0.0.1:48353/first", "pinned": True})
    tab = opened["tabId"]
    proof.tool("browser.tab", {"tabId": tab, "op": "update", "pinned": False})
    proof.tool("browser.history")
    proof.tool("browser.downloads")
    proof.tool("browser.receipt", {"actionId": opened["actionId"]})
    native = proof.args.browser_native
    if native and native.is_file():
        result = native_browser(proof, tab, native)
        browser_commands(proof, tab, opened["actionId"])
        return result
    for name, arguments in (("observe", {"tabId": tab, "cached": True}),
                            ("action", {"tabId": tab, "revision": "missing", "element": "missing", "action": "click"}),
                            ("decide", {"tabId": tab, "question": "Choose Save"}), ("promote", {"tabId": tab}),
                            ("capture", {"tabId": tab}), ("wait", {"actionId": opened["actionId"], "timeoutMs": 100})):
        proof.tool("browser." + name, arguments)
    browser_commands(proof, tab, opened["actionId"])
    proof.missing("T20 actual WebView2 browsing", "No --browser-native executable supplied; queue/state/refusal paths are live, page actions are not claimed complete")
    proof.missing("T20 Obscura and LAYA decision", "No actual Obscura executable/provider supplied; native browser never substitutes Chromium or a model")
    return {"state": state, "queuedTab": opened, "rendered": False}


def native_browser(proof, tab, native):
    grant = browser_request(proof, "runtime.connect")
    log = (proof.root / "native-browser.log").open("ab")
    child = subprocess.Popen([str(native.resolve())], cwd=REPO,
        env={**os.environ, "NEYVIA_BROWSER_BASE": proof.args.base_url, "NEYVIA_BROWSER_TOKEN": grant["token"]},
        stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    log.close()
    proof.children.append(child)
    deadline = time.monotonic() + proof.args.timeout
    while time.monotonic() < deadline:
        assert child.poll() is None, "Actual browser runtime exited; inspect scratch native-browser.log"
        state = browser_request(proof, "state")
        if next(row for row in state["tabs"] if row["id"] == tab)["live"]:
            break
        time.sleep(.2)
    else:
        raise AssertionError("Actual native tab never became live")
    browser_request(proof, "tab.grant", {"tabId": tab, "enabled": True})
    observed = proof.tool("browser.observe", {"tabId": tab})
    assert "INT6 browser fixture" in observed["text"] and "INT6-private-canary" not in json.dumps(observed), observed
    field = next(row for row in observed["elements"] if row.get("name") == "Name")
    completed(proof, proof.tool("browser.action", {"tabId": tab, "revision": observed["revision"], "element": field["id"], "action": "fill", "value": "INT6 live"}))
    observed = proof.tool("browser.observe", {"tabId": tab})
    save = next(row for row in observed["elements"] if row.get("name") == "Save")
    completed(proof, proof.tool("browser.action", {"tabId": tab, "revision": observed["revision"], "element": save["id"], "action": "click"}))
    final = proof.tool("browser.observe", {"tabId": tab})
    assert "Saved: INT6 live" in final["text"], final
    completed(proof, proof.tool("browser.capture", {"tabId": tab}))
    browser_request(proof, "action", {"tabId": tab, "revision": "stale", "element": save["id"], "action": "click"}, expected=(409,))
    proof.tool("browser.history")
    proof.tool("browser.downloads")
    proof.tool("browser.decide", {"tabId": tab, "question": "Choose Save"})
    proof.tool("browser.promote", {"tabId": tab})
    proof.tool("browser.wait", {"actionId": completed(proof, browser_request(proof, "tab.reload", {"tabId": tab}))["id"], "timeoutMs": 100})
    proof.command("browser_state_command")
    proof.command("browser_call_command", {"op": "state"})
    proof.missing("T20 Obscura and LAYA decision", "Native WebView2 journey is actual; no actual Obscura/provider supplied")
    return {"actualNativeText": final["text"], "secretRedacted": True, "rendered": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:48351")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=REPO / ".agent_control/INT6/runtime-receipt.json")
    parser.add_argument("--timeout", type=float, default=45, help="HTTP/native wait deadline; override for a slow owned runtime")
    parser.add_argument("--native-remote", action="store_true", help="Compile/open only the disposable Windows Forms native probe")
    parser.add_argument("--browser-native", type=Path, help="Real task-only browser-proof.exe supporting INT6 ports")
    parser.add_argument("--audio-file", type=Path, help="Existing Paul English seed-line-08 recorded WAV; never synthesizes audio")
    args = parser.parse_args()
    selected = urlsplit(args.base_url)
    if selected.scheme != "http" or selected.hostname != "127.0.0.1" or selected.port != 48351:
        parser.error("Use the explicitly owned scratch backend on 127.0.0.1:48351")
    try:
        args.root.resolve().relative_to((REPO / ".agent_control/INT6").resolve())
    except ValueError:
        parser.error("Scratch root must stay inside this worktree's .agent_control/INT6")
    args.root.mkdir(parents=True, exist_ok=True)
    proof = Proof(args)
    fixture = ThreadingHTTPServer(("127.0.0.1", 48353), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    try:
        proof.check("Scratch owner authentication", lambda: proof.request("/api/auth/local-session", {}))
        proof.check("Every added model tool registered under selected network policy", lambda: tool_registry(proof))
        for name, operation in (("T11 persistent settings/local-only", settings_track),
                                ("R backend tools/manual/mission", backend_track), ("T1 prompt dictation", dictation_track),
                                ("T6 external pack data", installer_track),
                                ("T19 owner-only remote", remote_track), ("T20 shared integrated browser", browser_track)):
            proof.check(name, lambda operation=operation: operation(proof))
    finally:
        for child in reversed(proof.children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        fixture.shutdown()
        fixture.server_close()
        proof.receipt["finishedAt"] = time.time()
        proof.receipt["unexpectedFailures"] = [row for row in proof.receipt["checks"] if not row["ok"]]
        proof.receipt["ok"] = not proof.receipt["unexpectedFailures"]
        proof.save()
    print(str(proof.output), flush=True)
    return 0 if proof.receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
