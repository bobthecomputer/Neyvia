"""Verify attribution policy, then passively observe the real input desktop.

No windows are launched and no input is generated. The synthetic policy cases
invoke parser methods directly, never a Windows input API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from grant_agent.cua_guard import ZeroDisturbanceGuard
from grant_agent.cua_fast import FastClient


def policy_checks():
    checks = {}
    guard = ZeroDisturbanceGuard(owner_pid=101)
    guard._started = time.monotonic()
    hidden = []
    baseline = {"visible": {1001: 202}, "foreground": 1001,
                "foreground_pid": 202, "cursor": [20, 30]}
    guard._record_state(baseline, hidden.append)
    guard._record_input("mouse", 0)
    guard._record_input("keyboard", 0)
    guard._record_state({"visible": {1001: 202, 1002: 303},
                         "foreground": 1002, "foreground_pid": 303,
                         "cursor": [21, 45]}, hidden.append)
    guard._record_external_entry('{"pid":303,"action":"hide"}')
    guard._record_external_entry('{"event":"unattributed"}')
    assert not guard._violations and not hidden
    assert guard._unowned_foreground_events == 1
    assert len(guard._unowned_windows) == 1
    assert guard._physical_keyboard_events == guard._physical_mouse_events == 1
    assert guard._external_unowned_entries == guard._external_unattributed_entries == 1
    checks["physical_and_unowned_activity_allowed"] = True

    guard._record_input("mouse", 0x01)
    guard._record_input("mouse", 0x03)
    guard._record_input("keyboard", 0x10)
    guard._record_input("keyboard", 0x12)
    assert guard._cursor_events == guard._injected_keyboard_events == 2
    assert guard._violations["injected_mouse_input"] == 2
    assert guard._violations["injected_keyboard_input"] == 2
    checks["injected_and_lower_integrity_flags_rejected"] = True

    guard.register_pid(404)
    guard._record_state({"visible": {1003: 404}, "foreground": 1003,
                         "foreground_pid": 404, "cursor": [21, 45]}, hidden.append)
    guard._record_external_entry('{"pid":404,"action":"hide"}')
    assert hidden == [1003]
    assert guard._foreground_events == 1 and guard._new_windows == {1003}
    assert guard._external_entries == 1
    assert guard._violations["external_guard_hid_owned_window"] == 1
    checks["owned_window_foreground_and_external_containment_rejected"] = True

    parked = ZeroDisturbanceGuard(owner_pid=101)
    parked._started = time.monotonic()
    parked.register_pid(404)
    parked._record_state(baseline, hidden.append)
    parked.register_parked_window(1004, 404, {"delete_tab_ok": True})
    value = {"visible": {1004: 404}, "foreground": 1001, "foreground_pid": 202,
             "cursor": [20, 30], "monitor_bounds": [0, 0, 1920, 1080],
             "window_details": {1004: {"rect": [-2000, -2000, -1000, -1000],
                                       "extended_style": 0x08000080}}}
    parked._record_state(value, hidden.append)
    assert parked._violations["new_owned_visible_input_window"] == 1
    checks["registered_offscreen_window_still_refused_when_visible"] = True
    try:
        parked.register_parked_window(1004, 505, {"delete_tab_ok": True})
        raise AssertionError("unowned parked PID accepted")
    except ValueError:
        checks["parked_registration_requires_owned_process"] = True
    try:
        parked.register_parked_window(1005, 404, {"delete_tab_ok": False})
        raise AssertionError("failed DeleteTab accepted")
    except ValueError:
        checks["failed_taskbar_removal_rejected"] = True
    return checks


def action_checks():
    """Exercise the real action dispatcher against bounded transport fixtures."""
    checks = {}
    snapshot = {"ok": True, "input_desktop_bound": True,
                "input_hooks_installed": True, "violations": {},
                "foreground_changes": 0, "new_visible_windows": 0,
                "injected_mouse_events": 0, "injected_keyboard_events": 0,
                "unowned_activity": {"physical_mouse_events": 12}}
    physical_before = {"foregroundWindowId": "800", "foregroundGeneration": 1,
                       "inputGeneration": 3, "lastInputTick": 10, "cursor": [2, 3]}
    physical_after = {"foregroundWindowId": "900", "foregroundGeneration": 2,
                      "inputGeneration": 9, "lastInputTick": 20, "cursor": [5, 6]}
    client = object.__new__(FastClient)
    client.uncertain = set()
    client.win = SimpleNamespace(valid=lambda hwnd: hwnd,
                                contained_hidden=False,
                                foreground_action=lambda *_: (_ for _ in ()).throw(
                                    AssertionError("foreground route called")))
    statuses = iter((physical_before, physical_after))
    guards = iter((snapshot, snapshot))
    client.transport = SimpleNamespace(
        request=lambda *_args, **_kwargs: next(statuses),
        guard=SimpleNamespace(check=lambda: next(guards)))
    row = {"id": "native:1", "name": "Button", "role": "Button", "className": "Button"}
    client.read = lambda *_: {"tree": [row]}
    dispatched = []
    client.native_action = lambda h, r, a, args: (
        dispatched.append(args) or {"mechanism": "Win32.BM_CLICK", "effect": "unverifiable"})
    args = {"action": "buttonClick", "elementId": row["id"], "inputGeneration": -1,
            "_lastInputTick": -1, "_physicalGeneration": -1, "allowForeground": True}
    result = client.action(1, args)
    assert result["foregroundPreserved"] and result["cursorPreserved"]
    assert result["before"] != result["after"]
    assert not set(dispatched[0]) & {"_lastInputTick", "_physicalGeneration",
                                    "inputGeneration", "allowForeground"}
    checks["real_dispatcher_allows_unowned_physical_activity"] = True

    statuses = iter((physical_before, physical_after))
    guards = iter((snapshot, {**snapshot, "ok": False,
                             "injected_keyboard_events": 1,
                             "violations": {"injected_keyboard_input": 1}}))
    result = client.action(1, args)
    assert not result["foregroundPreserved"] and not result["cursorPreserved"]
    assert result["attributedGuard"]["deltas"]["injected_keyboard_events"] == 1
    checks["real_dispatcher_rejects_attributed_disturbance"] = True

    statuses = iter((physical_before,))
    guards = iter((snapshot,))
    client.native_action = lambda *_: (_ for _ in ()).throw(NotImplementedError("unsupported"))
    try:
        client.action(1, args)
        raise AssertionError("unsupported route accepted")
    except NotImplementedError as exc:
        assert "foreground input is disabled" in str(exc)
    checks["foreground_route_disabled_even_with_caller_grant"] = True
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--passive-only", action="store_true",
                        help="Observe the real guard without executing synthetic policy cases")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "scripts/evidence/C11b-attribution.json")
    args = parser.parse_args()
    checks = {} if args.passive_only else policy_checks()
    if not args.passive_only:
        checks.update(action_checks())
    guard = ZeroDisturbanceGuard().start()
    initial = guard.snapshot()
    # Duration controls how much existing user activity can be observed. It does
    # not wait for quiet or generate any activity to improve the receipt.
    deadline = time.monotonic() + max(0, args.seconds)
    while initial["ok"] and time.monotonic() < deadline:
        time.sleep(min(.1, max(0, deadline - time.monotonic())))
    final = guard.close()
    activity = final["unowned_activity"]
    receipt = {
        "schema": "c11b-attribution-proof-v1",
        "policy_checks": checks,
        "policyCasesExecuted": not args.passive_only,
        "synthetic_cases_generated_os_input": False,
        "real_probe_launched_windows": False,
        "real_probe_generated_os_input": False,
        "physical_user_input_observed": bool(activity["physical_mouse_events"] or
                                             activity["physical_keyboard_events"]),
        "unowned_activity_observed": bool(activity["foreground_changes"] or
                                           activity["new_visible_windows"] or
                                           activity["physical_mouse_events"] or
                                           activity["physical_keyboard_events"]),
        "initial": initial,
        "final": final,
        "ok": all(checks.values()) and final["ok"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": receipt["ok"], "out": str(args.out),
                      "physical_user_input_observed": receipt["physical_user_input_observed"],
                      "unowned_activity_observed": receipt["unowned_activity_observed"],
                      "unowned_activity": activity,
                      "violations": final["violations"],
                      "input_hooks_installed": final["input_hooks_installed"]}))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
