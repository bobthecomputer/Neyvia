"""Game Dev's typed screen-selection state survives backend readback and rejects invalid tabs without overwriting it."""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

CONTRACT = "p22.gamedev.screen-state-persistence"
CONTRACTS = (CONTRACT,)


def screen_state_persists_and_refuses_invalid_tab(root: str | Path) -> dict:
    """Drive the production UI-state reporter and reopen its durable bus value."""
    from .neyvia_gamedev import report_state
    from .ui_command_bus import bus_for

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = (root / "local-game-project").resolve()
    project.mkdir(parents=True, exist_ok=True)
    # The production screen-state API bounds selected path strings at 128 chars.
    # Measurement scratch roots can be much deeper; persist the fixture's exact
    # root-relative project path rather than an overlong absolute scratch path.
    selected_project = project.relative_to(root).as_posix()
    if len(selected_project) > 128:
        raise AssertionError("Game Dev fixture project selection exceeds the production path bound")
    picked = {"godot": selected_project, "unity": ""}
    requested = {"tab": "godot", "picked": picked}
    prior_root = os.environ.get("NEYVIA_UI_STATE_ROOT")
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
    try:
        saved = report_state(root, requested, "p22-game-dev-client")
        bus = bus_for(root)
        reopened = bus_for(root).get("app:game-dev")
        if saved.get("ok") is not True or saved.get("state") != reopened:
            raise AssertionError("Game Dev state write did not round-trip through a new bus read")
        if reopened.get("tab") != "godot" or reopened.get("picked") != picked:
            raise AssertionError(f"Game Dev selected tab/project did not persist exactly: {reopened!r}")
        if reopened.get("clientId") != "p22-game-dev-client" or reopened.get("source") != "ui":
            raise AssertionError("Game Dev screen state lost its reporting client/source identity")
        try:
            datetime.fromisoformat(str(reopened.get("observedAt", "")).replace("Z", "+00:00"))
        except ValueError as error:
            raise AssertionError("Persisted Game Dev state has no valid observation timestamp") from error

        before_refusal = json.loads(json.dumps(reopened))
        refused = False
        try:
            report_state(root, {"tab": "external-editor", "picked": picked}, "p22-game-dev-client")
        except ValueError as error:
            refused = "Unknown Game Dev screen tab" in str(error)
        if not refused:
            raise AssertionError("Unknown Game Dev tab was not refused with the documented reason")
        after_refusal = bus.get("app:game-dev")
        if after_refusal != before_refusal:
            raise AssertionError("Refused Game Dev tab changed the last persisted user selection")
        return {"tab": reopened["tab"], "selectedProject": reopened["picked"]["godot"],
                "clientIdPreserved": True, "observationTimestampValid": True,
                "invalidTabRefused": True, "priorSelectionUnchanged": True}
    finally:
        if prior_root is None:
            os.environ.pop("NEYVIA_UI_STATE_ROOT", None)
        else:
            os.environ["NEYVIA_UI_STATE_ROOT"] = prior_root


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            with tempfile.TemporaryDirectory(prefix="game-dev-state-", dir=scratch) as folder:
                observed = screen_state_persists_and_refuses_invalid_tab(Path(folder))
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True, "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
