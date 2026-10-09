"""Prove that capability catalog configuration changes real discovery and plans."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


CONTRACT_SEARCH_PLAN = "p22.capability-config.search-plan"
CONTRACT_ADAPTER_REFUSAL = "p22.capability-config.adapter-refusal"
CONTRACTS = (CONTRACT_SEARCH_PLAN, CONTRACT_ADAPTER_REFUSAL)
TARGET_CAPABILITY = "research.literature-review"
QUERY_MARKER = "p22catalogquasarping"


def _require(condition: bool, contract: str, detail: str) -> None:
    if not condition:
        raise ValueError(f"Contract {contract}: {detail}")


def _catalog_payload() -> dict:
    repo = Path(__file__).resolve().parents[2]
    payload = json.loads((repo / "config/capability_packs.json").read_text(encoding="utf-8"))
    pack = next((row for row in payload.get("packs", [])
                 if any(item.get("capabilityId") == TARGET_CAPABILITY
                        for item in row.get("capabilities", []))), None)
    if pack is None:
        raise ValueError(f"Configured capability is missing: {TARGET_CAPABILITY}")
    return payload


def _fixture(root: Path, payload: dict):
    """Create an isolated owner root with only an explicit empty broker fixture."""
    from .proofs_a_capabilities import _fixture_root

    workspace = _fixture_root(root / "workspace")
    catalog_path = workspace / "config" / "capability_packs.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return workspace, catalog_path


def _mutated_payload(*, adapter: str | None = None) -> dict:
    payload = _catalog_payload()
    pack = next(row for row in payload["packs"]
                if any(item.get("capabilityId") == TARGET_CAPABILITY
                       for item in row.get("capabilities", [])))
    capability = next(item for item in pack["capabilities"]
                      if item.get("capabilityId") == TARGET_CAPABILITY)
    capability["description"] = str(capability["description"]).rstrip() + f" {QUERY_MARKER}"
    if adapter is not None:
        capability["adapter"] = adapter
    return payload


def _search_plan_case(root: Path) -> None:
    from .capability_service import CapabilityService

    workspace, catalog_path = _fixture(root, _mutated_payload())
    service = CapabilityService(workspace, catalog_path=catalog_path)
    results = service.search({"query": QUERY_MARKER, "limit": 5})["results"]
    _require(bool(results) and results[0]["capabilityId"] == TARGET_CAPABILITY,
             CONTRACT_SEARCH_PLAN, "the changed description did not alter real capability search")

    described = service.describe(TARGET_CAPABILITY)
    _require(QUERY_MARKER in described["description"] and
             described["capabilityId"] == TARGET_CAPABILITY and
             described["available"] == described["adapterDescriptor"]["available"],
             CONTRACT_SEARCH_PLAN, "describe did not return the configured text and actual adapter state")

    plan = service.plan({"goal": QUERY_MARKER, "maxCapabilities": 1})
    _require(plan["capabilityIds"] == [TARGET_CAPABILITY],
             CONTRACT_SEARCH_PLAN, "the configured capability was not selected by the real planner")
    saved = service.get_plan(plan["planId"])
    _require(saved["goal"] == QUERY_MARKER and saved["capabilityIds"] == [TARGET_CAPABILITY],
             CONTRACT_SEARCH_PLAN, "the user-visible plan did not persist the configured selection")

    reloaded_payload = _mutated_payload()
    pack = next(row for row in reloaded_payload["packs"]
                if any(item.get("capabilityId") == TARGET_CAPABILITY
                       for item in row.get("capabilities", [])))
    configured = next(item for item in pack["capabilities"]
                      if item.get("capabilityId") == TARGET_CAPABILITY)
    configured["description"] = configured["description"].replace(f" {QUERY_MARKER}", "")
    catalog_path.write_text(json.dumps(reloaded_payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    service.registry.reload()
    removed = service.search({"query": QUERY_MARKER, "limit": 5})["results"]
    _require(all(row["capabilityId"] != TARGET_CAPABILITY for row in removed),
             CONTRACT_SEARCH_PLAN, "reloaded catalog retained a removed search term")


def _adapter_refusal_case(root: Path) -> None:
    from .capability_service import CapabilityService

    impossible_adapter = "p22.adapter.that-does-not-exist"
    workspace, catalog_path = _fixture(root, _mutated_payload(adapter=impossible_adapter))
    service = CapabilityService(workspace, catalog_path=catalog_path)
    described = service.describe(TARGET_CAPABILITY)
    _require(described["available"] is False and
             described["adapter"] == impossible_adapter and
             described["adapterDescriptor"]["available"] is False,
             CONTRACT_ADAPTER_REFUSAL, "an unregistered configured adapter was reported available")

    plan = service.plan({"goal": QUERY_MARKER, "maxCapabilities": 1})
    step = next((step for stage in plan["stages"] for step in stage["steps"]
                 if step.get("capabilityId") == TARGET_CAPABILITY), None)
    _require(step is not None and step["status"] == "adapter_required" and
             plan["readiness"]["status"] == "adapter_required" and
             TARGET_CAPABILITY in plan["readiness"]["unavailableCapabilities"] and
             plan["readiness"]["canExecuteImmediately"] is False,
             CONTRACT_ADAPTER_REFUSAL, "the real plan did not block execution for the missing adapter")
    saved = service.get_plan(plan["planId"])
    _require(saved["readiness"]["status"] == "adapter_required" and
             saved["readiness"]["canExecuteImmediately"] is False,
             CONTRACT_ADAPTER_REFUSAL, "the persisted plan lost the adapter refusal")


def self_check(root=None, selected=None) -> dict:
    """Interpret modified catalog fields through search, describe and plan."""
    from .contract_gate import wants

    started = time.perf_counter()
    selected_ids = ({selected} if isinstance(selected, str)
                    else set(selected) if selected is not None else set(CONTRACTS))
    active = [identity for identity in CONTRACTS
              if identity in selected_ids and wants([identity])]
    if not active:
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    base = Path(root or os.environ.get("P22_EVIDENCE_ROOT", "D:/NeyviaRuns/P22")).resolve()
    case_root = base / f"capability-config-journey-{uuid.uuid4().hex}"
    case_root.mkdir(parents=True, exist_ok=False)
    cases = []
    actions = {
        CONTRACT_SEARCH_PLAN: _search_plan_case,
        CONTRACT_ADAPTER_REFUSAL: _adapter_refusal_case,
    }
    for identity in active:
        try:
            actions[identity](case_root / identity.rsplit(".", 1)[-1])
            cases.append({"id": identity, "contracts": [identity], "ok": True})
        except Exception as error:
            cases.append({"id": identity, "contracts": [identity], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    passed = sorted({identity for row in cases if row["ok"]
                     for identity in row["contracts"]})
    return {"ok": all(row["ok"] for row in cases), "contracts": passed,
            "scratchRoot": str(case_root), "cases": cases,
            "durationMs": round((time.perf_counter() - started) * 1000, 3)}
