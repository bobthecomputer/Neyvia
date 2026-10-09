"""Real Bureau lifecycle and previsibility assignment, without desktop switching."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import sys
import time
import winreg

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from grant_agent.cua_bureau import BureauDesktop, VirtualDesktopLibrary, BROKER_FRONTIER
from grant_agent.cua_desktop import AgentDesktop
from grant_agent.cua_guard import ZeroDisturbanceGuard

area = root / ".agent_control/c11-parked"
import uuid
stamp = area / ("bureau-" + uuid.uuid4().hex)
receipt = {"route": "agent-bureau", "fixture": "disposable x64 hidden containment probe",
           "success": False, "sources": [
               "https://github.com/Ciantic/VirtualDesktopAccessor/tree/rust",
               "https://github.com/Ciantic/VirtualDesktopAccessor/releases/tag/2024-12-16-windows11",
               "https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iapplicationactivationmanager-activateapplication",
               "https://learn.microsoft.com/en-us/windows/uwp/launch-resume/handle-app-prelaunch",
               "https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ivirtualdesktopmanager-movewindowtodesktop",
               "https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute",
           ]}
receipt["sourceSha256"] = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [Path(__file__), *(root / "src/grant_agent").glob("cua_*.py"),
        root / "tools/cua-driver-win/parked-hook.cpp", root / "tools/cua-driver-win/parked-probe.cpp"]}
receipt["nativeSha256"] = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in [area / "parked-hook.dll", area / "parked-probe.exe"]}
receipt["cloakContinuation"] = {"showAttempted": True, "pixelsPermitted": False,
    "mechanism": "Owned in-process DWM cloak/readback before nonactivating shell registration, then Bureau assignment; no uncloak or desktop switch"}
with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
    receipt["windowsBuild"] = f"{winreg.QueryValueEx(key, 'CurrentBuild')[0]}.{winreg.QueryValueEx(key, 'UBR')[0]}"
guard = ZeroDisturbanceGuard().start()
desktop = None
bureau = None
try:
    baseline = guard.snapshot()
    assert all(baseline.get(key) for key in ("ok", "input_hooks_installed", "input_desktop_bound"))
    library = VirtualDesktopLibrary(root / ".agent_control/c11-bureau/VirtualDesktopAccessor.dll", root / ".agent_control")
    receipt["before"] = library.status()
    library.create()
    receipt["created"] = library.status()
    receipt["lifecycleCleanup"] = library.remove(C.WinDLL("user32"))
    receipt["after"] = library.status()
    receipt["lifecycleWorks"] = receipt["lifecycleCleanup"]["removed"]
    desktop = AgentDesktop(profile_root=root / ".agent_control")
    bureau = BureauDesktop(desktop, guard, area / "parked-hook.dll", registration_probe=True)
    desktop.parked = bureau
    process = desktop._launch([str(area / "parked-probe.exe"), str(stamp)], env=None, parked=True)
    deadline = time.monotonic() + 8
    while not Path(str(stamp) + ".hwnd").exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Hidden fixture exited: " + str(process.returncode))
        time.sleep(.02)
    hwnd = int(Path(str(stamp) + ".hwnd").read_text())
    try:
        receipt["assignment"] = bureau.verify_window(hwnd)
        receipt["assignmentRecheck"] = bureau.verify_window(hwnd)
        receipt["membershipVerified"] = bureau.library.dll.GetWindowDesktopNumber(hwnd) == bureau.library.index()
        assert receipt["membershipVerified"]
        receipt["success"] = True
    except Exception as exc:
        receipt["assignmentError"] = str(exc)
        receipt["assignmentDiagnostics"] = bureau.library.last_assignment
        receipt["failedAssignmentState"] = getattr(bureau, "last_registration_failure", None) or guard.snapshot()
        Path(str(stamp) + ".target").write_text("{" + str(bureau.library.desktop_id) + "}", encoding="utf-8")
        assert desktop.u.PostMessageW(hwnd, 0x8001, 0, 0)
        deadline = time.monotonic() + 3
        while not Path(str(stamp) + ".move").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        receipt["documentedInProcessMove"] = Path(str(stamp) + ".move").read_text() if Path(str(stamp) + ".move").exists() else "timeout"
        receipt["documentedGuidMatches"] = Path(str(stamp) + ".assigned").read_text() == "yes" if Path(str(stamp) + ".assigned").exists() else False
        receipt["documentedQuery"] = {suffix: Path(str(stamp) + suffix).read_text() for suffix in (".query", ".actual") if Path(str(stamp) + suffix).exists()}
        receipt["desktopAfterDocumentedMove"] = bureau.library.dll.GetWindowDesktopNumber(hwnd)
        assert desktop.u.PostMessageW(hwnd, 0x8002, 0, 0)
        deadline = time.monotonic() + 3
        while not Path(str(stamp) + ".cloak").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        receipt["hiddenCloakProbe"] = Path(str(stamp) + ".cloak").read_text() if Path(str(stamp) + ".cloak").exists() else "timeout"
        # Assignment refusal is a verified frontier, not a completed Bureau task.
        receipt["hiddenAfterRefusal"] = not desktop.u.IsWindowVisible(hwnd)
    receipt["nativeCounters"] = bureau.counters()
    receipt["brokerGate"] = {"allowed": False, "activationAttempted": False,
                             "reason": BROKER_FRONTIER}
    try:
        desktop.launch_bureau(["C:/Windows/System32/calc.exe"], guard=guard, dll_path=area / "parked-hook.dll")
    except Exception as exc:
        receipt["brokerGate"]["realLaunchRefusal"] = str(exc)
        receipt["brokerGate"]["ownedProcessesUnchanged"] = len(desktop.processes) == 1
except Exception as exc:
    receipt["error"] = str(exc)
finally:
    if desktop:
        try:
            receipt["desktopCleanup"] = desktop.close()
        except Exception as exc:
            receipt["cleanupError"] = str(exc)
            # Preserve containment through any cleanup failure: terminate the
            # owned job before detaching or removing its native hook.
            if desktop.job:
                desktop.k.TerminateJobObject(desktop.job, 1)
            desktop.parked = None
            desktop.close()
            if bureau:
                bureau.close()
    if bureau:
        receipt["bureauCleanup"] = bureau.library.cleanup
    receipt["guard"] = guard.close()
receipt["success"] = receipt["success"] and receipt["guard"]["ok"]
(root / "scripts/evidence/C11e-bureau.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: receipt.get(key) for key in ("success", "lifecycleWorks", "assignmentError", "error", "bureauCleanup")}))
print(json.dumps({"zeroDisturbance": receipt["guard"]["ok"], "violations": receipt["guard"]["violations"]}))
raise SystemExit(0 if receipt["success"] else 1)
