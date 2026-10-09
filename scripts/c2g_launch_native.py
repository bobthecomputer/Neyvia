"""Run the normal task-only browser bridge under the reused C1 private launcher."""
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from http.cookiejar import CookieJar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.browser_native_launcher import NativeBrowserProcess
from grant_agent.durability import atomic_write_json

repo = Path(__file__).resolve().parents[1]
port = int(sys.argv[1])
if port not in range(48721, 48740):
    raise ValueError("Native launch needs an explicit assigned C2g port")
base = "http://127.0.0.1:" + str(port)
directory = repo / ".agent_control" / "C2g" / ("private-native-" + str(port))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar()))
def request(route, value):
    with opener.open(urllib.request.Request(base + route, json.dumps(value).encode(), {"Content-Type": "application/json"}), timeout=30) as response:
        return json.load(response)
request("/api/auth/local-session", {})
if request("/api/ui/browser", {"op": "state", "args": {}}).get("runtime", {}).get("connected"):
    raise RuntimeError("Close the existing native controller before connecting another")
connected = request("/api/ui/browser", {"op": "runtime.connect", "args": {}})
if not connected.get("ok"):
    raise RuntimeError(str(connected))
executable = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else repo / ".agent_control/C2d/native/browser-proof-c2d-priority.exe"
if (directory / "stop.request").exists():
    (directory / "stop.request").rename(directory / ("stop-" + str(time.time_ns()) + ".consumed"))
process = NativeBrowserProcess(executable, directory,
                               {**os.environ, "NEYVIA_BROWSER_BASE": base, "NEYVIA_BROWSER_TOKEN": connected["token"]})
def write_receipt(path, receipt):
    # Windows readers can briefly deny os.replace. Keep the guarded process alive
    # through a bounded sharing violation; persistent storage failures still stop it.
    for attempt in range(10):
        try:
            atomic_write_json(path, receipt)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)

try:
    print(json.dumps(process.receipt()), flush=True)
    write_receipt(directory / "launch.json", process.receipt())
    while process.process.poll() is None and not (directory / "stop.request").exists():
        write_receipt(directory / "native-live-guard.json", process.receipt())
        time.sleep(0.5)
finally:
    process.close()
