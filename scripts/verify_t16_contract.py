"""Check real stdio framing, native authority, manual schemas and launcher cleanup."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from grant_agent.cua_native import NativeWorker
from grant_agent.cua_launch import server_spec, claude_args
from grant_agent.neyvia_cua import NATIVE_CLIENT, call, service_for
from grant_agent.neyvia_cua_mcp import _read_message, CuaMCPServer
from grant_agent.neyvia_agent import _codex_neyvia_mcp_args
from grant_agent.native_tools import NativeToolRegistry
from grant_agent.neyvia_manuals import document, records, validate

os.environ["NEYVIA_UI_BACKEND_URL"] = "http://127.0.0.1:48171"
root = REPO / "scripts/evidence/.t16-runtime/contract-check"
root.mkdir(parents=True, exist_ok=True)
checks = {}
spec = server_spec("t16-proof", "codex")
assert spec["args"] == [sys.executable]
assert spec["command"] == str(NativeWorker.stdio_host())
claude = json.loads(claude_args("t16-proof")[1])["mcpServers"]["neyvia-cua"]
assert claude["args"] == [sys.executable] and claude["env"]["NEYVIA_APP"] == "claude"
cli = _codex_neyvia_mcp_args(root, session_id="t16-proof")
config = tomllib.loads("\n".join(cli[i + 1] for i, arg in enumerate(cli[:-1]) if arg == "--config"))
assert config["mcp_servers"]["neyvia-cua"]["env"]["NEYVIA_APP"] == "neyvia"
checks["processLocalCodexClaudeAndNeyviaConfig"] = True

proc = subprocess.Popen([spec["command"], *spec["args"]], cwd=REPO,
                        env={**os.environ, **spec["env"]}, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW)
child_handle = None
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
kernel.OpenProcess.restype = ctypes.c_void_p
kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
kernel.CloseHandle.argtypes = [ctypes.c_void_p]
try:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "T16-framing", "version": "1"}}}).encode()
    proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    proc.stdin.flush()
    response, framing = _read_message(proc.stdout)
    assert response["id"] == 1 and framing == "content_length" and "result" in response
    checks["contentLengthFraming"] = True
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode() + b"\n")
    proc.stdin.flush()
    response, framing = _read_message(proc.stdout)
    tools = response["result"]["tools"]
    assert len(tools) == 27 and framing == "newline"
    expected = "list_apps list_windows get_window_state get_desktop_state launch_app click double_click right_click type_text press_key hotkey scroll drag set_value invoke_menu verify_state get_screen_size get_cursor_position start_session get_session list_sessions end_session".split()
    assert {t["name"] for t in tools if not t["name"].startswith("preview_") and t["name"] != "request_app"} == set(expected)
    checks["newlineFramingAndExact27Tools"] = True
    command = f"Get-CimInstance Win32_Process -Filter 'ParentProcessId = {proc.pid}' | Where-Object {{ $_.Name -eq 'python.exe' -and $_.CommandLine -like '*grant_agent.neyvia_cua_mcp*' }} | Select-Object -ExpandProperty ProcessId"
    found = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True,
                           timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    child_pid = int(found.stdout.strip())
    child_handle = kernel.OpenProcess(0x100000, False, child_pid)
    assert child_handle
    proc.kill()
    proc.wait(timeout=5)
    assert kernel.WaitForSingleObject(child_handle, 3000) == 0
    checks["abruptHostTerminationReapsOwnedPython"] = True
finally:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
    if child_handle:
        kernel.CloseHandle(child_handle)

workspace = SimpleNamespace(bus=SimpleNamespace(root=root), backend=object())
service = service_for(root)
token = None
try:
    session = service.new_session([], {"chatId": "right-chat", "app": "neyvia"})
    token = NATIVE_CLIENT.set({"chatId": "other-chat", "app": "neyvia"})
    try:
        call(workspace, "cua.log", {"sessionId": session["id"]})
        raise AssertionError("Other chat read an unrelated grant")
    except ValueError as exc:
        assert str(exc) == "session_pending"
    checks["crossChatNativeGrantRefused"] = True
    lifecycle = service.driver({"tool": "get_session", "arguments": {}, "sessionId": session["id"],
                                "client": {"chatId": "right-chat", "app": "neyvia", "title": "New transport title"}})
    assert lifecycle["structuredContent"]["session"] == session["id"]
    listed = service.driver({"tool": "list_sessions", "arguments": {}, "client": {"chatId": "right-chat", "app": "neyvia"}})
    assert any(row["session"] == session["id"] for row in listed["structuredContent"]["sessions"])
    checks["ownerGrantLifecycleIndependentOfUpstreamLeaseAndTitle"] = True
    NATIVE_CLIENT.reset(token)
    token = NATIVE_CLIENT.set({"chatId": "right-chat", "app": "neyvia"})
    service.request("end", {"sessionId": session["id"]}, owner=True)
    try:
        call(workspace, "cua.inspect", {"sessionId": session["id"], "window_id": 1})
        raise AssertionError("Ended session remained actionable")
    except ValueError as exc:
        assert str(exc) == "session_ended"
    checks["endedNativeGrantRefusedBeforeDispatch"] = True
finally:
    if token is not None:
        NATIVE_CLIENT.reset(token)
    service.shutdown()

bridge = CuaMCPServer()
bridge._authenticate()
probe = json.loads((REPO / "scripts/evidence/T16-build-launch.json").read_text())
live = bridge._http("/api/ui/cua", {"op": "open", "args": {"apps": [probe["exe"]], "chatId": "t16-native-http", "app": "neyvia"}})
remote = SimpleNamespace(bus=SimpleNamespace(root=root), backend=None)
token = NATIVE_CLIENT.set({"chatId": "t16-native-http", "app": "neyvia"})
try:
    log = call(remote, "cua.log", {"sessionId": live["id"]})
    assert log["session"] == live["id"]
    checks["nativeWorkerCarriesBoundChatThroughPersistentHttpService"] = True
    observer = NativeWorker()
    try:
        focus_before = observer.request("status")
        unknown = call(remote, "cua.verify", {"sessionId": live["id"], "window_id": probe["window_id"],
                       "expect": [{"element": {"selector": {"role": "Text"}, "exists": True}}]})
        focus_after = observer.request("status")
        assert unknown["status"] == "unknown" and unknown["samples"] == 0
        assert unknown["predicates"][0]["unknown_reason"] == "unsupported_predicate"
        assert focus_before["foregroundGeneration"] == focus_after["foregroundGeneration"] and focus_before["cursor"] == focus_after["cursor"]
        checks["unsupportedVerificationExplicitlyUnknownWithoutUpstreamOrFocusChange"] = True
    finally:
        observer.close()
    NATIVE_CLIENT.reset(token)
    token = NATIVE_CLIENT.set({"chatId": "another-native-chat", "app": "neyvia"})
    try:
        call(remote, "cua.log", {"sessionId": live["id"]})
        raise AssertionError("HTTP forwarding lost chat ownership")
    except RuntimeError as exc:
        assert "HTTP 400" in str(exc)
    checks["crossChatHttpNativeGrantRefused"] = True
finally:
    NATIVE_CLIENT.reset(token)
    bridge._http("/api/ui/cua", {"op": "end", "args": {"sessionId": live["id"]}})

row = next(row for row in records() if row["id"] == "computer-use")
manual = validate(document(row)[1], NativeToolRegistry(root))
assert manual["grounded"]
checks["computerUseManualGroundedAgainstLiveRegistry"] = True
receipt = {"passed": True, "checks": checks, "manual": manual,
           "launcher": {"source": "tools/cua-driver-win/stdio-host.cs", "python": sys.executable,
                        "hostPid": proc.pid, "ownedChildPid": child_pid, "nativeTools": expected}}
(REPO / "scripts/evidence/T16-native-contract.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps({"passed": True, "checks": len(checks)}))
