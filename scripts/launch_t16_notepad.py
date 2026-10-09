"""Open a disposable native Notepad document without requesting activation."""
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_native import NativeWorker

document = ROOT / "scripts/evidence/T16-native-note.txt"
document.parent.mkdir(parents=True, exist_ok=True)
if not document.exists():
    document.write_text("T16 native background proof.\n", encoding="utf-8")
worker = NativeWorker()
before = worker.request("status")
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 4  # SW_SHOWNOACTIVATE
process = subprocess.Popen([str(Path("C:/Windows/System32/notepad.exe")), str(document)], startupinfo=startup)
window = None
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    windows = worker.request("windows")
    window = next((w for w in windows if w["processName"].lower() == "notepad" and "T16-native-note" in w["title"]), None)
    if window:
        break
    time.sleep(0.2)
after = worker.request("status")
receipt = {"window": window, "launcherPid": process.pid, "document": str(document), "before": before, "after": after,
           "foregroundPreserved": before["foregroundWindowId"] == after["foregroundWindowId"], "cursorPreserved": before["cursor"] == after["cursor"]}
(ROOT / "scripts/evidence/T16-launch.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps(receipt))
worker.close()
