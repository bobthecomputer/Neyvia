"""Build and launch the disposable native proof app using installed .NET only."""
import hashlib
import json
from pathlib import Path
import subprocess
from grant_agent.cua_native import NativeWorker

repo = Path(__file__).resolve().parents[1]
source = repo / "tools/cua-driver-win/probe.cs"
directory = repo / "scripts/evidence/.t16-runtime/probe"
directory.mkdir(parents=True, exist_ok=True)
binary = directory / "T16NativeProbe.exe"
framework = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319")
args = [str(framework / "csc.exe"), "/nologo", "/target:winexe", "/out:" + str(binary), str(source)]
args += ["/reference:" + str(framework / (name + ".dll")) for name in ("System.Windows.Forms", "System.Drawing")]
build = subprocess.run(args, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
if build.returncode:
    raise RuntimeError(build.stdout.decode(errors="replace") + build.stderr.decode(errors="replace"))
with_worker = NativeWorker()
NativeWorker.stdio_host()
before = with_worker.request("status")
(directory / "state").unlink(missing_ok=True)
(directory / "state.result").unlink(missing_ok=True)
proc = subprocess.Popen([str(binary), str(directory / "state")], creationflags=subprocess.CREATE_NO_WINDOW)
import time
deadline = time.monotonic() + 10
while not (directory / "state").exists() and time.monotonic() < deadline:
    time.sleep(.1)
after = with_worker.request("status")
receipt = {"pid": proc.pid, "exe": str(binary), "window_id": int((directory / "state").read_text()),
           "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
           "before": before, "after": after, "foregroundPreserved": before["foregroundWindowId"] == after["foregroundWindowId"], "cursorPreserved": before["cursor"] == after["cursor"]}
(repo / "scripts/evidence/T16-build-launch.json").write_text(json.dumps(receipt, indent=2))
with_worker.close()
print(json.dumps(receipt))
