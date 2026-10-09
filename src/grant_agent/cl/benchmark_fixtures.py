"""Disposable five-layer fixtures backed by production Notes/Files/UIA/browser tools."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

from grant_agent.neyvia_notes_tools import call_notes
from grant_agent.neyvia_files_tools import call_files
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.subprocess_utils import hidden_windows_subprocess_kwargs

HTML = '''<!doctype html><html><title>Dispatch board</title><h1>Dispatch board</h1>
<table><tr><th>Job</th><th>Units</th><th>Status</th></tr>
<tr><td>Orchard</td><td>17</td><td>Ready</td></tr><tr><td>Harbor</td><td>40</td><td>Waiting</td></tr>
<tr><td>Meadow</td><td>25</td><td>Ready</td></tr></table>
<label>Result<input aria-label="Result"></label><button onclick="document.querySelector('h2').textContent='Confirmed: '+document.querySelector('input').value">Confirm</button><h2 role="status">Waiting</h2></html>'''

NATIVE = r'''param([string]$StatePath)
Add-Type -AssemblyName System.Windows.Forms
Add-Type 'using System; using System.Runtime.InteropServices; public class CLWindow { [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n); }'
$form = New-Object System.Windows.Forms.Form
$form.Text='CL disposable dispatch'; $form.Width=600; $form.Height=240
$field = New-Object System.Windows.Forms.TextBox
$field.Text='initial'; $field.AccessibleName='Dispatch text'; $field.SetBounds(20,20,400,30)
$button = New-Object System.Windows.Forms.Button
$button.Text='Apply'; $button.SetBounds(20,60,100,35)
$label = New-Object System.Windows.Forms.Label
$label.Text='Waiting'; $label.SetBounds(20,110,500,40)
$button.Add_Click({$label.Text='Applied: '+$field.Text})
$form.Controls.AddRange(@($field,$button,$label))
$form.Add_Shown({[CLWindow]::ShowWindow($form.Handle,5)|Out-Null; @{windowId=$form.Handle.ToInt64();pid=$PID}|ConvertTo-Json|Set-Content -LiteralPath $StatePath -Encoding UTF8})
[System.Windows.Forms.Application]::Run($form)
'''


class Fixture:
    def __init__(self, task: str, root: Path, chart_observation: dict | None = None, *, port=48289):
        self.task, self.root = task, root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.browser = self.cua = self.process = self.server = None
        self.answer = None
        self.latest = None
        self.paths = {}
        self.port = port
        self.workspace = workspace_for(self.root)
        if task == "notes":
            folder = self.root / "notes"
            call_notes(self.root, "folder", {"folder": str(folder)}, source="ui")
            self.original = "# Orchard plan\n17 + 25 ready units.\n#dispatch\n"
            for name, body in {"orchard.md": self.original, "other.md": "# Harbor plan\n40 waiting units. #dispatch\n"}.items():
                call_notes(self.root, "write", {"path": name, "body": body}, source="ui")
            self.paths["notesFolder"] = str(folder)
        elif task == "files":
            for folder in ("inbox", "archive"):
                (self.root / folder).mkdir()
            for name, text in {"ready.txt": "status=draft\nunits=90\n", "x17.txt": "status=approved\nunits=42\n", "approved.txt": "status=rejected\nunits=10\n"}.items():
                (self.root / "inbox" / name).write_text(text, encoding="utf-8")
            self.paths = {name: str(self.root / name) for name in ("inbox", "archive")}
        elif task == "native":
            self._native()
        elif task == "web":
            self._web()
        elif task == "chart":
            if chart_observation is None:
                raise RuntimeError("Real chart transcription is required")
            self.chart_observation = chart_observation

    def _native(self):
        from grant_agent.neyvia_cua import service_for
        script = self.root / "fixture.ps1"
        script.write_text(NATIVE, encoding="utf-8")
        state = self.root / "window.json"
        self.process = subprocess.Popen(["powershell.exe", "-NoProfile", "-STA", "-File", str(script), "-StatePath", str(state)],
                                        stdout=subprocess.DEVNULL, stderr=(self.root / "native.stderr").open("wb"),
                                        **hidden_windows_subprocess_kwargs())
        deadline = time.monotonic() + 30
        while not state.exists() and self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if not state.exists():
            raise RuntimeError("Disposable native fixture did not launch")
        self.window = json.loads(state.read_text(encoding="utf-8-sig"))["windowId"]
        self.cua = service_for(self.root)
        session = self.cua.request("open", {"apps": ["powershell.exe"], "chatId": "cl-benchmark", "app": "codex"}, owner=True)
        self.source = {"sessionId": session["id"], "window_id": self.window}
        self.paths["windowId"] = self.window

    def _web(self):
        from grant_agent.perception_browser import BrowserSessions
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *_):
                pass
        if self.port not in range(48281, 48290):
            raise ValueError("CL benchmark port is outside the assigned range")
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.browser = BrowserSessions()
        self.sid = self.browser.run("open", f"http://127.0.0.1:{self.port}/")["browserId"]

    def observe(self):
        if self.task == "native":
            raw = self.cua.request("inspect", self.source)
            self.latest = raw
            return {"elements": [{key: row.get(key) for key in ("role", "label", "value", "element_token", "actions")} for row in raw["elements"]],
                    "text": raw.get("tree_markdown", "")}
        if self.task == "web":
            self.latest = self.browser.run("observe", self.sid)
            return {key: self.latest[key] for key in ("revision", "text", "elements", "tables")}
        if self.task == "chart":
            return self.chart_observation
        return {"paths": self.paths}

    def dispatch(self, name: str, args: dict, action_id: str = ""):
        if name.startswith("notes.") and self.task == "notes":
            return call_notes(self.root, name.split(".", 1)[1], args, source="ui")
        if name.startswith("files.") and self.task == "files":
            scoped = dict(args)
            for key in ("path", "from", "to"):
                if key in scoped:
                    path = Path(scoped[key]).resolve()
                    path.relative_to(self.root)
                    scoped[key] = str(path)
            if not scoped and name != "files.undo":
                raise ValueError("A fixture path is required")
            return call_files(self.root, name.split(".", 1)[1], scoped, source="ui")
        if name == {"native": "win.observe", "web": "web.observe", "chart": "img.observe"}.get(self.task):
            return self.observe()
        if name == "img.answer" and self.task == "chart":
            self.answer = args
            return {"ok": True, "submitted": args}
        if name.startswith("win.") and self.task == "native":
            if not self.latest:
                raise ValueError("Observe before acting")
            token = args["target"]
            if not any(row.get("element_token") == token for row in self.latest["elements"]):
                raise ValueError("Target was not observed")
            tool = "set_value" if name == "win.fill" else "click"
            native_args = {"window_id": self.window, "element_token": token}
            if tool == "set_value":
                native_args["value"] = args["text"]
            result = self.cua.request("action", {**self.source, "tool": tool, "args": native_args})
            self.latest = None
            return result
        if name.startswith("web.") and self.task == "web":
            if not self.latest:
                raise ValueError("Observe before acting")
            result = self.browser.run("action", self.sid, args["revision"], args["target"],
                                      "fill" if name == "web.fill" else "click", args.get("text", ""))
            self.latest = None
            return result
        raise ValueError("Action outside this fixture")

    def check(self, *, refresh=False):
        if self.task == "notes":
            note = call_notes(self.root, "read", {"path": "orchard.md"}, source="ui")
            other = call_notes(self.root, "read", {"path": "other.md"}, source="ui")
            expected = self.original + "\nConfirmed: 42 units #verified"
            return {"passed": note["body"] == expected and note["pinned"] and other["body"] == "# Harbor plan\n40 waiting units. #dispatch\n",
                    "state": note}
        if self.task == "files":
            dest = self.root / "archive/approved.txt"
            passed = (dest.is_file() and dest.read_text() == "status=approved\nunits=42\n" and not (self.root / "inbox/x17.txt").exists()
                      and (self.root / "inbox/ready.txt").read_text() == "status=draft\nunits=90\n"
                      and (self.root / "inbox/approved.txt").read_text() == "status=rejected\nunits=10\n")
            return {"passed": passed, "destinationSha256": hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else None}
        if self.task in {"native", "web"}:
            if refresh:
                state = self.observe()
            elif self.latest is None:
                return {"passed": False, "state": None, "reason": "Model has not refreshed after its action"}
            else:
                state = self.latest
            expected = "Applied: INITIAL / checked" if self.task == "native" else "Confirmed: 42 units"
            return {"passed": expected in state.get("text", state.get("tree_markdown", "")), "state": state}
        return {"passed": self.answer == {"highest": "Apr", "lead": 7, "total": 94}, "submitted": self.answer}

    def close(self):
        if self.browser:
            self.browser.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.cua:
            self.cua.shutdown()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)

    def capture(self):
        if self.task == "native":
            return self.cua.request("capture", self.source)
        if self.task == "web":
            path = self.root / "final.png"
            self.browser.worker.submit(lambda: self.browser.sessions[self.sid]["page"].screenshot(path=str(path))).result()
            return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return None

    def contract(self, name):
        """Checks use actual observers; window pre-state reuses the model snapshot."""
        def snapshot():
            if self.task == "notes":
                return {"notes": {path: call_notes(self.root, "read", {"path": path}, source="ui") for path in ("orchard.md", "other.md")}}
            if self.task == "files":
                return {"files": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for folder in ("inbox", "archive") for path in (self.root / folder).glob("*.txt")}}
            if self.task in {"native", "web"} and self.latest is not None:
                return self.latest
            return self.observe()

        def check(args, result, previous):
            if name == "notes.write":
                note = call_notes(self.root, "read", {"path": args["path"]}, source="ui")
                note_path = Path(args["path"])
                if note_path.is_absolute():
                    note_path = note_path.relative_to(self.root / "notes")
                old = previous["notes"][note_path.as_posix()]["body"]
                expected = args["body"]
                if args.get("mode") == "append":
                    expected = old + ("" if not old or old.endswith("\n\n") else "\n" if old.endswith("\n") else "\n\n") + expected
                return note["body"] == expected
            if name == "notes.pin":
                return call_notes(self.root, "read", {"path": args["path"]}, source="ui")["pinned"] == args.get("pinned", True)
            if name == "files.move":
                dest = Path(args["to"])
                if dest.is_dir():
                    dest /= Path(args["from"]).name
                return dest.is_file() and not Path(args["from"]).exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == previous["files"][str(Path(args["from"]).resolve())]
            if name == "win.fill":
                return any(row.get("role") == "Edit" and row.get("value") == args["text"] for row in self.latest["elements"])
            if name == "win.click":
                value = next(row["value"] for row in self.latest["elements"] if row.get("role") == "Edit")
                return "Applied: " + value in self.latest.get("tree_markdown", "")
            if name == "web.fill":
                return any(row.get("role") == "textbox" and row.get("value") == args["text"] for row in self.latest["elements"])
            if name == "web.click":
                value = next(row["value"] for row in self.latest["elements"] if row.get("role") == "textbox")
                return "Confirmed: " + value in self.latest["text"]
            if name == "img.answer":
                points = self.chart_observation["charts"][0]["series"][0]["points"]
                ranked = sorted(points, key=lambda row: row["value"], reverse=True)
                return args == {"highest": ranked[0]["label"], "lead": ranked[0]["value"] - ranked[1]["value"], "total": sum(row["value"] for row in points)}
            return True

        mutable = name in {"notes.write", "notes.pin", "files.move", "win.fill", "win.click", "web.fill", "web.click", "img.answer"}
        impact = {"reads": self.task, "bounds": "disposable-fixture", "net": "localhost" if self.task == "web" else "none"}
        if mutable:
            impact.update(writes=self.task, undo="files.undo" if name == "files.move" else "none", ask="none")
        return {"checks": [{"name": "observed", "observer": True, "check": check}] if mutable else [],
                "observe": snapshot if mutable else None, "impact": impact}


def chart_source(directory: Path) -> dict:
    """Transcribe actual image once; all paired arms receive the identical observation."""
    from PIL import Image, ImageDraw, ImageFont
    from grant_agent.perception_visual import VISUAL_SCHEMA, _PROMPT
    from jsonschema import Draft202012Validator
    from .benchmark_provider import propose
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chart.png"
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 27)
    draw.text((100, 25), "Monthly orders (units)", fill="black", font=font)
    for tick in range(0, 41, 10):
        y = 500 - tick * 10
        draw.line((100, y, 850, y), fill="#ddd", width=2)
        draw.text((45, y - 15), str(tick), fill="black", font=font)
    for i, (label, number) in enumerate(zip(("Jan", "Feb", "Mar", "Apr"), (14, 27, 19, 34))):
        x = 180 + i * 170
        draw.rectangle((x, 500 - number * 10, x + 90, 500), fill="#267553")
        draw.text((x + 20, 510), label, fill="black", font=font)
        draw.text((x + 25, 460 - number * 10), str(number), fill="black", font=font)
    image.save(path)
    receipt = propose(_PROMPT.format(width=900, height=600), "gpt-6-luna", directory / "transcription", image=path, schema=VISUAL_SCHEMA)
    if not receipt["passed"]:
        raise RuntimeError("Chart image route failed: " + str(receipt["errors"] or receipt["stderr"]))
    value = json.loads(receipt["answer"])
    Draft202012Validator(VISUAL_SCHEMA).validate(value)
    value["provenance"] = {"model": "gpt-6-luna", "usage": receipt["usage"], "latencyMs": receipt["latencyMs"],
                           "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(), "receipt": str(directory / "transcription/receipt.json")}
    (directory / "observation.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return value
