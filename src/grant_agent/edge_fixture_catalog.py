"""Reviewed feature builders and honest per-contract/category obligations.

A generated obligation is not evidence. Only a builder that invokes the real
feature and observes its effect may attach a passed case to an obligation.
"""
from __future__ import annotations

import importlib
import hashlib
import json
from collections import Counter
from pathlib import Path

BUILDERS = {
    "p22-runtime": "grant_agent.proofs_runtime_edges",
    "local": "grant_agent.edge_fixture_local",
    "pure": "grant_agent.edge_fixture_pure",
    "scheduler": "grant_agent.edge_fixture_scheduler",
    "capabilities": "grant_agent.edge_fixture_capabilities",
    "mobile": "grant_agent.edge_fixture_mobile",
    "providers": "grant_agent.edge_fixture_providers",
    "native": "grant_agent.edge_fixture_native",
    "surfaces": "grant_agent.edge_fixture_surfaces",
    "models": "grant_agent.edge_fixture_models",
    "frontend": "grant_agent.edge_fixture_frontend",
    "missions": "grant_agent.edge_fixture_missions",
    "engine": "grant_agent.edge_fixture_engine",
    "control": "grant_agent.edge_fixture_control",
    "sessions": "grant_agent.edge_fixture_sessions",
    "chat-shell": "grant_agent.edge_fixture_chat_shell",
    "host-runtime": "grant_agent.edge_fixture_host_runtime",
    "preferences-skills": "grant_agent.edge_fixture_preferences_skills",
    "ui-remaining": "grant_agent.edge_fixture_ui_remaining",
    "core": "grant_agent.edge_fixture_core",
    "artifact-manual": "grant_agent.edge_fixture_artifact_manual",
    "control-remaining": "grant_agent.edge_fixture_control_remaining",
    "capability-models": "grant_agent.edge_fixture_capability_models",
    "ui-planning-local": "grant_agent.edge_fixture_ui_planning_local",
    "c7d-control": "grant_agent.edge_fixture_c7d_control",
    "local-completion": "grant_agent.edge_fixture_c7d_local",
    "mission-completion": "grant_agent.edge_fixture_c7d_mission_completion",
    "c7d-ui": "grant_agent.edge_fixture_c7d_ui",
    "c7d-ui-control": "grant_agent.edge_fixture_c7d_ui_control",
    "c7d-verification": "grant_agent.edge_fixture_c7d_verification",
    "c7d-wz": "grant_agent.edge_fixture_c7d_wz",
    "c7d-ui-settings": "grant_agent.edge_fixture_c7d_ui_settings",
    "c7d-engine": "grant_agent.edge_fixture_c7d_engine",
    "c7d-control-completion": "grant_agent.edge_fixture_c7d_control_completion",
    "c7d-provider-marks": "grant_agent.edge_fixture_c7d_provider_marks",
    "native-completion": "grant_agent.edge_fixture_c7d_native_completion",
    "c7d-providers": "grant_agent.edge_fixture_c7d_providers",
    "c7d-adapters": "grant_agent.edge_fixture_c7d_adapters",
    "c7d-projection": "grant_agent.edge_fixture_c7d_projection",
    "c7d-rendered": "grant_agent.edge_fixture_c7d_rendered",
    "c7d-desktop": "grant_agent.edge_fixture_c7d_desktop",
    "capability-completion": "grant_agent.edge_fixture_c7d_capability",
    "session-completion": "grant_agent.edge_fixture_c7d_sessions",
    "host-actions-completion": "grant_agent.edge_fixture_c7d_host_actions",
    "c7d-native-commands": "grant_agent.edge_fixture_c7d_native_commands",
}

# Observe all native adverse categories before the expensive control replay,
# then exercise newly completed owners and the complete historical replay.
# All families still run in this single campaign with their original checks.
_new=lambda name:name.startswith('c7d-') or name.endswith('completion')
BUILDERS={'c7d-rendered':BUILDERS['c7d-rendered'],
          **{name:module for name,module in BUILDERS.items() if _new(name) and name!='c7d-rendered'},
          **{name:module for name,module in BUILDERS.items() if not _new(name)}}


def run(root, contracts, categories, families=None, *, live_observations=None):
    from .proof_contracts import source_bindings, source_digest, REPO
    from .durability import atomic_write_json
    rows = []
    for family in families or BUILDERS:
        module = importlib.import_module(BUILDERS[family])
        family_root = root / family
        family_root.mkdir(parents=True, exist_ok=True)
        bindings = source_bindings()
        for path in (__file__, module.__file__):
            relative = Path(path).relative_to(REPO).as_posix()
            bindings[relative] = source_digest(REPO / relative)
        print(json.dumps({"family": family, "state": "running"}), flush=True)
        family_rows = []
        if hasattr(module,'run_observed'):
            if live_observations is None: raise ValueError('Native family requires a campaign live observer')
            generated=module.run_observed(family_root,contracts,categories,live_observations)
        else:
            generated=module.run(family_root,contracts,categories)
        for row in generated:
            unknown = set(row["contracts"]) - contracts.keys()
            if unknown or row["category"] not in categories or row["status"] not in {"passed", "failed", "blocked"}:
                raise ValueError(f"Invalid semantic fixture binding from {family}: {sorted(unknown)}")
            family_rows.append({**row, "builder": family,
                                "boundary": row.get("boundary", "real production feature call with independent effect observation")})
        stable = all(source_digest(REPO / name) == expected for name, expected in bindings.items())
        checkpoint = root / (family + ".receipt.json")
        atomic_write_json(checkpoint, {"schema": "neyvia.edge-family.v1", "family": family,
                                     "sourceBindings": bindings, "sourceStable": stable,
                                     "rows": family_rows})
        # This index points only to completed, source-bound family receipts. A
        # reboot leaves useful observed work without inventing a final campaign.
        index_path = root / "families.json"
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
        index.append({"family": family, "path": str(checkpoint),
                      "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(), "sourceStable": stable})
        atomic_write_json(index_path, index)
        if not stable:
            raise ValueError("Semantic fixture source changed during family: " + family)
        rows.extend(family_rows)
        print(json.dumps({"family": family, "state": "recorded", "counts": dict(Counter(r["status"] for r in family_rows))}), flush=True)
    identities = [row["id"] for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("Semantic fixture identities must be unique")
    return rows


def completed_receipts(root):
    """Validate completed artifacts before exposing their index to the caller."""
    from .proof_contracts import REPO, source_digest
    root = Path(root).resolve()
    index = json.loads((root / "families.json").read_text(encoding="utf-8"))
    for entry in index:
        path = Path(entry["path"]).resolve()
        path.relative_to(root)
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Corrupt semantic family receipt: " + entry["family"])
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["family"] != entry["family"] or not receipt["sourceStable"] or not entry["sourceStable"]:
            raise ValueError("Unstable semantic family receipt: " + entry["family"])
        for name, expected in receipt["sourceBindings"].items():
            source = (REPO / name).resolve()
            source.relative_to(REPO)
            if source_digest(source) != expected:
                raise ValueError("Stale semantic family receipt: " + entry["family"])
    return index


def blocker(contract, category):
    """Retain exact origins and never turn an absent builder into impossibility."""
    identity = contract["id"]
    pending = []
    for name in BUILDERS.values():
        module = importlib.import_module(name)
        reason = getattr(module, "blocked_reason", lambda *_: None)(identity, category)
        if reason:
            pending.append(reason if isinstance(reason, dict) else {"kind": "fixture_gap", "reason": reason})
        resolver = getattr(module, "blocker", None)
        if resolver:
            reason = resolver(contract, category)
            if reason:
                pending.append(reason if isinstance(reason, dict) else {"kind": "fixture_gap", "reason": reason})
    # Historical builders often retain an explicit implementation gap. A later
    # exact invariant audit must be reachable rather than masked by that gap.
    # Authority refusals stay strongest; an audit never grants external access.
    for kind in ("authority_boundary", "not_applicable"):
        matches = [r for r in pending if r.get("kind") == kind]
        if matches:
            return matches[0]
    if pending:
        return pending[0]
    sites = contract.get("checkedAt", [])
    origin = contract.get("source", contract.get("manual", "unknown origin"))
    claim = contract.get("claim", "")
    # A name mentioning devices, providers or releases does not prove a local
    # fixture impossible. Only an audited builder may assert non-applicability
    # or an external authority requirement; everything else remains work.
    kind = "fixture_gap"
    reason = (f"No implemented {category} feature builder for {identity}; the claim must be exercised at "
              + (", ".join(sites) if sites else origin)
              + ". This is remaining work, not proof that a real fixture is impossible")
    return {"kind": kind, "reason": reason, "source": origin, "requiredChecks": sites,
            "claim": claim}


def summarize(coverage):
    return {"statuses": dict(Counter(row["status"] for row in coverage)),
            "blockedKinds": dict(Counter(row.get("blockerKind", "unknown") for row in coverage if row["status"] == "blocked")),
            "families": dict(Counter(row["contract"].split(".")[0] for row in coverage if row["status"] == "passed"))}
