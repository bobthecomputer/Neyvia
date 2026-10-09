"""Outcome contract for grounded manual validation and nested-tool admission."""
from __future__ import annotations

import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path

CONTRACT = "p22.manuals.registry-action-admission"
CONTRACTS = (CONTRACT,)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def manual_registry_journey(root: str | Path) -> dict:
    from jsonschema.exceptions import SchemaError

    from . import neyvia_manuals
    from .manual_contracts import validate_structure
    from .neyvia_workspace_tools import workspace_for

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace = workspace_for(root / "manual-registry-workspace")
    try:
        registry, dispatch = neyvia_manuals.context(workspace)
        current = neyvia_manuals.call(
            workspace, "manual.validate", {"id": "manuals-next"}, registry=registry
        )
        _require(current.get("ok") is True and len(current.get("manuals", [])) == 1,
                 "production manual registry did not validate the owning manual")
        grounded = current["manuals"][0]
        _require(grounded.get("id") == "manuals-next" and grounded.get("grounded") is True,
                 "manual validation lost its identity or grounded status")
        _, _, data = neyvia_manuals.get_manual("manuals-next")
        procedure = next((row for row in grounded["procedures"]
                          if row.get("chapter") == "state" and row.get("procedure") == "verified-observe"), None)
        observer = data["chapters"]["versions"]["state"]["current"]
        _require(procedure is not None and "neyvia.manual.observe" in procedure["tools"],
                 "manual registry omitted the actual verified-observe action")
        _require(observer.get("tool") == "neyvia.manual.versions",
                 "owning manual no longer maps current-state observation to its version reader")
        malformed = deepcopy(data)
        malformed["chapters"]["versions"]["state"]["current"]["shape"] = {
            "type": "not-a-json-schema-type"
        }
        malformed_refused = False
        try:
            validate_structure(malformed)
        except SchemaError:
            malformed_refused = True
        _require(malformed_refused, "malformed manual observer schema was admitted")

        dispatched: list[str] = []

        def observed_dispatch(tool: str, arguments: dict, action_id: str = ""):
            dispatched.append(tool)
            return dispatch(tool, arguments, action_id=action_id)

        args = {"id": "manuals-next", "state": "current", "chapter": "versions",
                "inputs": {"id": "manuals-next"}, "scopeTools": []}
        denied = False
        try:
            neyvia_manuals.call(workspace, "manual.observe", args,
                                dispatcher=observed_dispatch, registry=registry)
        except PermissionError:
            denied = True
        _require(denied, "observer ran despite an empty nested-tool scope")
        _require(dispatched == [], "denied observer dispatched a nested action")
        _require(not list((workspace.bus.root / ".neyvia" / "manual-state").glob("*.json")),
                 "denied observer wrote a state handle")

        admitted = neyvia_manuals.call(
            workspace, "manual.observe",
            {**args, "scopeTools": ["neyvia.manual.versions"], "reset": True},
            dispatcher=observed_dispatch, registry=registry,
        )
        _require(admitted.get("ok") is True and admitted.get("mode") == "snapshot",
                 "permitted observer did not return its current snapshot")
        observed = admitted.get("observed")
        _require(isinstance(observed, dict) and observed.get("id") == "manuals-next"
                 and observed.get("lineage") == [],
                 "permitted observation lost the actual manual identity or lineage")
        _require(dispatched == ["neyvia.manual.versions"],
                 "observer exceeded its exact nested-tool grant")
        return {"manualId": grounded["id"], "grounded": grounded["grounded"],
                "procedureTools": procedure["tools"], "observerTool": observer["tool"],
                "malformedObserverSchemaRefused": malformed_refused,
                "scopeRefusalBeforeDispatch": denied, "deniedDispatchCount": 0,
                "admittedObserver": observed, "admittedNestedTools": dispatched}
    finally:
        workspace.close()


def self_check(scratch: str | Path) -> dict:
    from .contract_gate import wants

    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    cases = []
    if wants(CONTRACTS):
        try:
            with tempfile.TemporaryDirectory(prefix="manual-registry-", dir=scratch) as folder:
                observed = manual_registry_journey(folder)
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": True,
                          "observed": observed})
        except Exception as error:
            cases.append({"id": CONTRACT, "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    report = {"ok": bool(cases) and all(case["ok"] for case in cases), "cases": cases,
              "contracts": [CONTRACT] if cases and cases[0]["ok"] else [],
              "durationMs": round((time.perf_counter() - started) * 1000, 2)}
    (scratch / "outcomes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    return report
