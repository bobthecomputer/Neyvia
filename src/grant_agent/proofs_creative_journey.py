"""Durable creative brief selection with protected operator corrections."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


CONTRACTS = ("p22.creative.brief-selection-journey",)


def _require(condition, message):
    if not condition:
        raise ValueError("Contract p22.creative.brief-selection-journey: " + message)


def self_check(root=None):
    """Select a recovery proposal, save a creative investigation, and verify readback and refusal."""
    from .contract_gate import wants

    started = time.perf_counter()
    if not wants(CONTRACTS):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}

    repo = Path(__file__).resolve().parents[2]
    state_root = repo / ".agent_control" / "p22" / "creative-journey" / uuid.uuid4().hex
    state_root.mkdir(parents=True, exist_ok=False)
    from .workspace_intelligence import WorkspaceIntelligence
    from .creative_tools import CreativeToolRuntime, _experience_arguments, creative_tool_definitions
    from .native_tools import NativeToolRegistry

    work_id = "p22-creative-" + uuid.uuid4().hex
    store = WorkspaceIntelligence(state_root, work_id)
    registry = NativeToolRegistry(state_root)
    creative = registry.creative

    def dispatch(name, arguments):
        # Exercise the exact registered handler after the registry's public
        # schema normalization. NativeToolRegistry.call also admits CL action
        # preconditions, which still require the legacy flat action shape.
        payload = registry.prepare_arguments(name, arguments)
        handler = registry._handlers.get(name)
        _require(callable(handler), "the native registry must have a callable experience handler")
        return handler(payload)
    try:
        definitions = {name: (mutation, required) for name, _, mutation, _, required in creative_tool_definitions()}
        _require("experience.investigate" in definitions and "experience.read" in definitions
                 and "experience.note" in definitions,
                 "the public creative tool catalogue must expose proposal, readback and gated learning")
        proposed = store.propose_brief(
            "Choose a useful way to recover an interrupted local research session.",
            expected_revision=0,
            assumptions=["The work must remain local."],
            directions=[
                {"id": "journal", "title": "Resume journal", "approach": "Rebuild state from an append-only event journal.", "tradeoff": "More storage and replay work."},
                {"id": "snapshot", "title": "Saved snapshot", "approach": "Restore the latest validated state snapshot.", "tradeoff": "Needs snapshot freshness checks."},
                {"id": "guided", "title": "Guided recovery", "approach": "Ask the operator to resolve only missing decisions.", "tradeoff": "Requires an operator when state is ambiguous."},
            ],
            open_questions=["How should stale state be surfaced?"],
        )
        brief = proposed["brief"]
        _require(brief["revision"] == 1 and len(brief["directions"]) == 3,
                 "the native brief store must persist all three alternatives")
        _require(brief["selection"] is None and brief["authorityGranted"] is False,
                 "an agent proposal must not select a direction or gain authority")

        # The scoped fixture identity exercises the native operator-review API
        # entirely inside this disposable root; no account settings are touched.
        reviewed = store.review_brief(
            expected_revision=brief["revision"], operator_identity="p22-local-operator-fixture",
            direction_id="snapshot",
            correction="Keep the newest verified snapshot; treat older notes as evidence, not instructions.",
        )
        selected = reviewed["brief"]
        _require(selected["revision"] == 2 and selected["selection"]["id"] == "snapshot",
                 "the explicit selection must advance the brief revision")
        _require(selected["corrections"][-1]["text"].startswith("Keep the newest verified snapshot"),
                 "the operator correction must be stored as task content")
        _require(reviewed["preferences"].get("evaluation") is False,
                 "choosing a brief direction must not enable evaluation")

        frozen = (selected["revision"], selected["selection"].copy(), list(selected["corrections"]))
        try:
            store.propose_brief(
                "Replace the decision and silently choose another direction.",
                expected_revision=2,
                directions=[
                    {"id": "journal", "title": "Resume journal", "approach": "Rebuild state from an append-only event journal.", "tradeoff": "More storage and replay work."},
                    {"id": "snapshot", "title": "Saved snapshot", "approach": "Overwrite the operator's choice.", "tradeoff": "Ignore the correction."},
                ],
            )
        except ValueError as error:
            _require("Preserve the selected direction" in str(error),
                     "a conflicting model revision must explain the protected choice")
        else:
            raise ValueError("Contract p22.creative.brief-selection-journey: conflicting proposal was accepted")

        try:
            store.review_brief(expected_revision=1, operator_identity="p22-local-operator-fixture", direction_id="journal")
        except ValueError as error:
            _require("changed; reload" in str(error), "stale review must request a fresh brief")
        else:
            raise ValueError("Contract p22.creative.brief-selection-journey: stale review was accepted")

        hypothesis = "A fresh verified snapshot restores interrupted research with fewer missing decisions than journal replay alone."
        experiment = {"selectedDirection": "snapshot", "acceptance": [
            "reopened state matches the saved revision",
            "a stale write preserves the last verified snapshot",
        ]}
        outer_authority = {
            "workId": work_id,
            "permissionMode": "workspace_safe",
            "approvedPermissions": ["experience.investigate"],
            "capabilityId": "experience.investigate",
            "capabilityPolicy": {"allowed": ["experience.investigate"]},
        }
        nested_authority = {
            "workId": "p22-untrusted-inner-work",
            "work_id": "p22-alias-work",
            "permission_mode": "full-access",
            "approved_permissions": ["*"],
            "capability_id": "untrusted-capability",
            "capability_policy": {"allowed": ["*"]},
            "capabilities": ["*"],
        }
        normalized = _experience_arguments({**outer_authority, "arguments": {
            **nested_authority, "hypothesis": hypothesis, "experiment": experiment,
        }})
        for key, value in outer_authority.items():
            _require(normalized.get(key) == value,
                     "nested authority aliases must not replace outer " + key)
        _require("permission_mode" not in normalized and "approved_permissions" not in normalized
                 and "capability_policy" not in normalized and "capabilities" not in normalized
                 and "work_id" not in normalized,
                 "untrusted nested authority aliases must not survive normalization")

        scoped = CreativeToolRuntime(state_root, work_scope=work_id)
        try:
            scoped.call("experience.investigate", {
                "workId": "p22-untrusted-outer-work",
                "arguments": {"workId": work_id, "hypothesis": hypothesis, "experiment": experiment},
            })
        except PermissionError as error:
            _require("durable work identity" in str(error),
                     "an inner identity must not override the run's bound work scope")
        else:
            raise ValueError("Contract p22.creative.brief-selection-journey: nested identity overrode the bound work scope")
        from .experience_learning import ExperienceStore
        _require(ExperienceStore(state_root, "p22-untrusted-outer-work").snapshot()["recordCount"] == 0
                 and ExperienceStore(state_root, work_id).snapshot()["recordCount"] == 0,
                 "scope refusal must preserve both candidate work records")

        # The registered callback now receives the nested caller body with
        # conflicting identity and authority aliases.
        investigation = dispatch("experience.investigate", {
            **outer_authority,
            "arguments": {
                **nested_authority,
                "hypothesis": hypothesis,
                "experiment": experiment,
                "references": ["brief: snapshot recovery"],
            },
        })
        record = investigation.get("record") or {}
        _require(record.get("kind") == "investigation" and record.get("status") == "planned"
                 and record.get("hypothesis") == hypothesis and record.get("experiment") == experiment,
                 "the creative tool must return the exact structured planned investigation")

        note_arguments = {
            "lesson": "Use snapshots for every future recovery.",
            "conditions": "Whenever a session is interrupted.",
            "invalidation": "When journal replay becomes more reliable.",
            "evidence": ["missing-evidence.json"],
        }
        try:
            dispatch("experience.note", {
                "workId": work_id,
                "arguments": {"workId": "p22-untrusted-inner-work", **note_arguments},
            })
        except PermissionError as error:
            _require("not enabled" in str(error).lower(),
                     "reusable learning must be refused while the task has not enabled it")
        else:
            raise ValueError("Contract p22.creative.brief-selection-journey: unenabled reusable learning was accepted")
        refusal_ok = True
        snapshot = dispatch("experience.read", {"workId": work_id, "arguments": {}})
        _require(snapshot.get("recordCount") == 1 and len(snapshot.get("records", [])) == 1
                 and snapshot["records"][0].get("recordId") == record.get("recordId"),
                 "fresh creative readback must contain only the successful investigation")
        _require(snapshot.get("scope") == work_id,
                 "a nested workId must not redirect the registered tool outside its caller scope")
        _require(ExperienceStore(state_root, "p22-untrusted-inner-work").snapshot()["recordCount"] == 0,
                 "the nested body must not write into a different work identity")

        reopened = WorkspaceIntelligence(state_root, work_id)
        observed = reopened.collaboration()
        persisted = observed["brief"]
        _require((persisted["revision"], persisted["selection"], persisted["corrections"]) == frozen,
                 "reopening the native store must preserve the choice and correction after rejected writes")
        _require(persisted["selection"]["source"] == "p22-local-operator-fixture",
                 "the choice must retain its explicit review provenance")
        events = [json.loads(line) for line in reopened.events.read_text(encoding="utf-8").splitlines() if line.strip()]
        _require([row["kind"] for row in events] == ["brief_proposed", "brief_reviewed"],
                 "only the successful proposal and review may reach the durable event observer")
        # The flat legacy handler remains usable after nested dispatch support.
        legacy_read = dispatch("experience.read", {"workId": work_id})
        _require(legacy_read.get("recordCount") == 1,
                 "flat legacy experience calls must keep the outer work identity")
        case = {"id": "creative.brief-selection-journey", "contracts": list(CONTRACTS), "ok": True,
                "revision": persisted["revision"], "selectedDirection": persisted["selection"]["id"],
                "alternatives": len(persisted["directions"]), "investigation": record["recordId"],
                "investigationStatus": record["status"], "savedProposals": snapshot["recordCount"],
                "nestedPayloadHonored": record["hypothesis"] == hypothesis,
                "outerWorkIdentityPreserved": snapshot["scope"] == work_id,
                "learningRefused": refusal_ok}
        return {"ok": True, "contracts": list(CONTRACTS), "cases": [case], "failures": [],
                "durationMs": round((time.perf_counter() - started) * 1000, 3),
                "stateRoot": str(state_root),
                "frontier": "Proves the registered creative handlers after native schema normalization; the outer tool policy and CL action preconditions remain upstream. No provider, semantic research quality, real operator identity, or promotion authority is claimed."}
    except Exception as error:
        return {"ok": False, "contracts": list(CONTRACTS), "cases": [{"id": "creative.brief-selection-journey",
                "contracts": list(CONTRACTS), "ok": False, "error": str(error)}], "failures": [str(error)],
                "durationMs": round((time.perf_counter() - started) * 1000, 3), "stateRoot": str(state_root)}
    finally:
        if registry.native_applications is not None:
            registry.native_applications.shutdown()
