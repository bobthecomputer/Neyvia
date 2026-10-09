"""Source-bound Inception coverage and release decisions; never invent journeys."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def _declared_run_root():
    raw = os.environ.get('NEYVIA_C8_RUN_ROOT')
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute() or candidate.drive.lower() != 'd:':
        return None
    root = candidate.resolve()
    # External receipts are an explicit operator setting, restricted to the
    # release artifact volume. The original worktree roots remain supported.
    return root if root.is_relative_to(Path('D:/NeyviaRuns').resolve()) else None

SOURCE_FILES = ("src/grant_agent/neyvia_inception.py", "src/grant_agent/neyvia_workspace_tools.py",
                "scripts/c8_journey.py", "scripts/c8_backend.py", "scripts/c8_scope.py",
                "scripts/c8_desktop_guard.py", "scripts/run_c8_inception.py", "config/inception_journeys.json")
OPTIONAL_SOURCE_FILES = ("scripts/run_c8d.py", "scripts/c8d_worker.py", "scripts/c8_fixtures.py", "scripts/c8_headless.py", "scripts/seal_c8d.py",
                        "scripts/intn_rebind_inception.py", "config/inception_binding_reviews.json",
                        "scripts/c8e_prerequisites.py", "scripts/c8e_effects.py", "scripts/c8e_bug_checks.py",
                        "scripts/c8e_design_checks.py", "scripts/c8e_speech.py", "scripts/c8e_terminal.py", "scripts/c8e_onboarding.py", "scripts/c8e_local_checks.py", "scripts/c8e_sidebar.py", "scripts/c8e_vite.config.mjs",
                        "config/inception_c8e_prerequisites.json", "config/inception_c8e_effects.json", "config/inception_c8e_sidebar.json",
                        "scripts/c8e_extra_effects.py", "scripts/c8e_ui_effects.py",
                        "config/inception_c8e_extra_effects.json", "config/inception_c8e_ui_effects.json",
                        "scripts/c8e_session_checks.py", "config/inception_c8e_sessions.json",
                        "scripts/c8e_host_effects.py", "config/inception_c8e_host_effects.json",
                        "config/proofs/proofs-b-engine.json", "config/proofs/proofs-b-harness.json",
                        "scripts/c8e_state_effects.py", "config/inception_c8e_state_effects.json",
                        "scripts/c8e_scroll_checks.py", "scripts/seal_c8e.py", "scripts/c8e_browser_checks.py",
                        "scripts/c8e_slim_build.py", "scripts/c8e_verify_slim.mjs", "scripts/prove_c8_report.py", "scripts/verify_proofs.py",
                        "scripts/prepare_slim_release.mjs", "scripts/stage_portable_python.py",
                        "scripts/release-contracts.mjs", "scripts/check_installer_size.mjs", "scripts/package_onboarding_packs.py",
                        "src-tauri/installer-budget.json", "src-tauri/tauri.slim.conf.json",
                        "scripts/check_workflow_publication_integrity.py",
                        "scripts/proofs-e-shell.mjs", "scripts/proofs-e-models.mjs", "scripts/proofs-e-chat.mjs",
                        "config/proofs/proofs-e-shell.json", "config/proofs/proofs-e-models.json",
                        "config/proofs/proofs-e-chat.json", "config/base_pack/test-manifest.json",
                        "config/neyvia_onboarding.json", "config/capability_packs.json", "config/tool_suite_lock.json")
FAILURE_CLASSES = {"product bug", "journey bug", "environment"}


def source_files():
    repo = Path(__file__).resolve().parents[2]
    paths = set(SOURCE_FILES)
    paths.update(name for name in OPTIONAL_SOURCE_FILES if (repo / name).is_file())
    for folder in (repo / "src/grant_agent", repo / "web/src", repo / "config/app_sdk"):
        paths.update(path.relative_to(repo).as_posix() for path in folder.rglob("*")
                     if path.is_file() and path.suffix in {".py", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".css", ".html"})
    return sorted(paths)

DEFINITIONS = [
    ("inception.inventory", "Inventory every authoritative manual procedure and orphan goal check; missing coverage blocks release.", {}, []),
    ("inception.report", "Revalidate the last task-local Inception receipt against current manual hashes and proof bytes. No run is a blocked gate.", {}, []),
]


def call(workspace, name, args):
    if name == "inception.inventory":
        return inventory()
    if name != "inception.report":
        raise ValueError("Unknown Inception operation")
    path = workspace.bus.root / ".neyvia/inception/latest.json"
    if not path.is_file():
        return {"available": False, "releaseGate": False, "reason": "Run scripts/run_c8_inception.py with explicit ports and a pinned local revision"}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or not isinstance(row.get("provenance"), dict) or not isinstance(row.get("results"), list):
            raise ValueError("Invalid report structure")
    except (OSError, ValueError):
        return {"available": True, "releaseGate": False, "webCoverageGate": False, "errors": ["Unreadable or malformed Inception receipt"]}
    report = aggregate(inventory(), row["results"], row["provenance"])
    repo = Path(__file__).resolve().parents[2]
    provenance = row["provenance"]
    hashes = provenance.get("candidateSourceHashes")
    if not isinstance(hashes, dict) or set(source_files()) != set(hashes):
        report["errors"].append("Complete candidate source hash manifest required")
        hashes = {}
    for name, digest in hashes.items():
        path = (repo / name).resolve()
        if not path.is_relative_to(repo) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            report["errors"].append("Candidate source changed: " + name)
    candidate = provenance.get("candidate", {})
    if not isinstance(candidate, dict):
        candidate = {}
    build_value = candidate.get("build", "")
    if not isinstance(build_value, str):
        report["errors"].append("Invalid candidate build path")
        build_value = ""
    build = Path(build_value).resolve()
    builds = candidate.get("buildHashes")
    if not isinstance(builds, dict) or "index.html" not in builds or not any(name.startswith("assets/") for name in builds):
        report["errors"].append("Complete candidate build hash manifest required")
        builds = {}
    for name, digest in builds.items():
        path = (build / name).resolve()
        declared = _declared_run_root()
        if (not (build.is_relative_to(repo / ".agent_control") or (declared and build.is_relative_to(declared))) or not path.is_relative_to(build)
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            report["errors"].append("Candidate build changed: " + name)
    if not isinstance(provenance.get("desktopGuard"), dict) or provenance["desktopGuard"].get("passed") is not True:
        report["errors"].append("Completed desktop guard proof required")
    if report["errors"]:
        report.update(releaseGate=False, webCoverageGate=False)
        for manual in report["perManual"].values():
            manual.update(releaseGate=False, webCoverageGate=False)
    return {"available": True, **report}


def inventory():
    from .neyvia_manuals import records, get_manual
    rows, hashes = [], {}
    for record in records():
        identity = record["id"]
        _, digest, manual = get_manual(identity)
        hashes[identity] = digest
        procedures = 0
        for chapter_name, chapter in manual["chapters"].items():
            referenced = set()
            for name, procedure in chapter["procedures"].items():
                checks = sorted({step["check"] for step in procedure["steps"] if step.get("check")})
                referenced.update(checks)
                procedures += 1
                rows.append({"id": f"{identity}/{chapter_name}/{name}", "kind": "procedure",
                             "manual": identity, "chapter": chapter_name, "procedure": name,
                             "sourceHash": digest, "goal": procedure["goal"],
                             "inputs": procedure["inputs"], "steps": procedure["steps"],
                             "checks": checks, "checkContracts": {key: chapter["checks"][key] for key in checks},
                             "judges": {step["judge"]: chapter["judge"][step["judge"]]
                                        for step in procedure["steps"] if "judge" in step}})
            for name in sorted(set(chapter["checks"]) - referenced):
                rows.append({"id": f"{identity}/{chapter_name}/@check/{name}", "kind": "unreferenced-check",
                             "manual": identity, "chapter": chapter_name, "sourceHash": digest,
                             "checks": [name], "checkContracts": {name: chapter["checks"][name]}})
        if not procedures:
            rows.append({"id": f"{identity}/@manual", "kind": "manual-without-procedures",
                         "manual": identity, "sourceHash": digest, "checks": []})
    return {"schema": "neyvia.inception.inventory.v1", "manualHashes": hashes, "rows": rows,
            "counts": {"manuals": len(hashes), "procedures": sum(row["kind"] == "procedure" for row in rows),
                       "coverageRows": len(rows)}}


def validate_bindings(catalog, bindings):
    """Validate authored fixtures and explicitly deferred real-world inputs.

    A deferred slot is a named required input or declared judgement that this
    isolated run cannot truthfully supply. It must carry a concrete owner and
    receipt requirement. Deferred values are never substituted into the input
    or decision payload, so validation cannot turn missing context into a pass.
    """
    from copy import deepcopy
    from jsonschema import Draft202012Validator
    errors = []
    known = {row["id"]: row for row in catalog["rows"]}
    for identity, binding in bindings.items():
        row = known.get(identity)
        if row is None:
            errors.append(f"{identity}: unknown coverage row")
            continue
        if binding.get("sourceHash") != row["sourceHash"]:
            errors.append(f"{identity}: stale binding source hash")
        if row["kind"] != "procedure":
            continue
        inputs = binding.get("inputs")
        deferred_inputs = binding.get("deferredInputs", {})
        deferred_judges = binding.get("deferredJudges", {})
        setup_rows = binding.get("setup", [])
        dynamic_inputs = binding.get("dynamicInputs", {})
        def valid_deferred(mapping, known, label):
            if not isinstance(mapping, dict):
                errors.append(f"{identity}: {label} must be an object")
                return False
            valid = True
            for name, detail in mapping.items():
                if name not in known:
                    errors.append(f"{identity}: unknown {label} slot {name}")
                    valid = False
                if not isinstance(detail, dict) or set(detail) != {"reason", "owner", "requiredReceipt"}:
                    errors.append(f"{identity}: {label} {name} requires reason, owner and requiredReceipt")
                    valid = False
                    continue
                if not all(isinstance(detail[key], str) and detail[key].strip()
                           for key in ("reason", "owner", "requiredReceipt")):
                    errors.append(f"{identity}: {label} {name} has empty or invalid provenance")
                    valid = False
            return valid
        required = row.get("inputs", {}).get("required", [])
        valid_deferred(deferred_inputs, set(required), "deferred input")
        if not isinstance(setup_rows, list) or len(setup_rows) > 8:
            errors.append(f"{identity}: setup must be a bounded list of at most 8 typed actions")
            setup_rows = []
        setup_saves = set()
        for index, item in enumerate(setup_rows):
            if (not isinstance(item, dict) or set(item) != {"tool", "args", "save"}
                    or not isinstance(item.get("tool"), str) or not item["tool"].strip()
                    or not isinstance(item.get("args"), dict) or not isinstance(item.get("save"), str)
                    or not item["save"].strip()):
                errors.append(f"{identity}: setup[{index}] must contain typed tool, args and save fields")
                continue
            if item["save"] in setup_saves:
                errors.append(f"{identity}: duplicate setup save name {item['save']}")
            setup_saves.add(item["save"])
        if not isinstance(dynamic_inputs, dict):
            errors.append(f"{identity}: dynamicInputs must be an object")
            dynamic_inputs = {}
        for field, reference in dynamic_inputs.items():
            if field not in required:
                errors.append(f"{identity}: dynamic input {field} is not an authored required field")
            if isinstance(inputs, dict) and field in inputs:
                errors.append(f"{identity}: dynamic input {field} must not have a schema-valid placeholder value")
            if not isinstance(reference, dict) or set(reference) != {"$result"}:
                errors.append(f"{identity}: dynamic input {field} must name a real setup result")
                continue
            path = reference.get("$result")
            parts = path.split(".") if isinstance(path, str) else []
            if len(parts) < 2 or parts[0] not in setup_saves or any(not part for part in parts):
                errors.append(f"{identity}: dynamic input {field} must resolve from a declared setup save")
        if not isinstance(inputs, dict):
            errors.append(f"{identity}: inputs must be an object")
        else:
            overlap = set(inputs) & set(deferred_inputs) if isinstance(deferred_inputs, dict) else set()
            if overlap:
                errors.append(f"{identity}: deferred inputs must not contain fabricated values: {sorted(overlap)}")
            dynamic_names = set(dynamic_inputs) if isinstance(dynamic_inputs, dict) else set()
            if isinstance(deferred_inputs, dict) and set(deferred_inputs) & dynamic_names:
                errors.append(f"{identity}: input cannot be both deferred and setup-derived")
            missing = set(required) - set(inputs) - (set(deferred_inputs) if isinstance(deferred_inputs, dict) else set()) - dynamic_names
            if missing:
                errors.append(f"{identity}: required inputs must be supplied, setup-derived, or explicitly deferred: {sorted(missing)}")
            schema = deepcopy(row["inputs"])
            schema["required"] = [name for name in required
                                  if (not isinstance(deferred_inputs, dict) or name not in deferred_inputs)
                                  and name not in dynamic_names]
            if not Draft202012Validator(schema).is_valid(inputs):
                errors.append(f"{identity}: supplied inputs do not match the authored JSON schema")
        valid_deferred(deferred_judges, set(row.get("judges", {})), "deferred judge")
        decisions = binding.get("decisions", {})
        if not isinstance(decisions, dict):
            errors.append(f"{identity}: decisions must be an object")
        else:
            deferred_judge_names = set(deferred_judges) if isinstance(deferred_judges, dict) else set()
            for name, judge in row["judges"].items():
                if name in decisions and name in deferred_judge_names:
                    errors.append(f"{identity}: deferred judge {name} must not contain a fabricated decision")
                elif name not in decisions and name not in deferred_judge_names:
                    errors.append(f"{identity}: missing or invalid decision {name}")
                elif name in decisions and decisions[name] not in judge["options"]:
                    errors.append(f"{identity}: missing or invalid decision {name}")
            if set(decisions) - set(row["judges"]):
                errors.append(f"{identity}: unknown decision")
        if deferred_judges and not isinstance(deferred_judges, dict):
            errors.append(f"{identity}: deferred judges must be an object")
        if not binding.get("actions") or not binding.get("goals"):
            errors.append(f"{identity}: explicit UI actions and goal assertions required")
        if binding.get("journey") == "manual":
            expected_actions = [step["action"] for step in row.get("steps", []) if "action" in step]
            expected_goals = [row.get("goal")]
            if binding.get("actions") != expected_actions:
                errors.append(f"{identity}: actions must exactly name authored procedure actions")
            if binding.get("goals") != expected_goals:
                errors.append(f"{identity}: goals must exactly match the authored procedure goal")
            if binding.get("contracts") != row.get("checkContracts", {}):
                errors.append(f"{identity}: contracts must exactly match authored check contracts")
    return {"valid": not errors, "errors": errors,
            "unbound": sorted(set(known) - set(bindings))}


def _origin(url):
    try:
        parsed = urlsplit(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _receipts_valid(receipts, target, driver, run_id, journey):
    if not isinstance(receipts, list) or not receipts or not _origin(target):
        return False
    for receipt in receipts:
        if not isinstance(receipt, dict) or receipt.get("fresh") is not True or receipt.get("success") is not True:
            return False
        if _origin(receipt.get("target")) != _origin(target):
            return False
        try:
            repo = Path(__file__).resolve().parents[2]
            raw = Path(receipt["proof"])
            proof = (raw if raw.is_absolute() else repo / raw).resolve()
            roots = (repo / "scripts/evidence/C8-runs", repo / ".agent_control/proofs/C8", repo / ".agent_control/C8")
            declared = _declared_run_root()
            if declared:
                roots = (*roots, declared)
            if not any(proof.is_relative_to(root) for root in roots):
                return False
            if not proof.is_file() or hashlib.sha256(proof.read_bytes()).hexdigest() != receipt.get("sha256"):
                return False
            import json
            data = json.loads(proof.read_text(encoding="utf-8"))
            if (data.get("schema") != "neyvia.inception.proof.v1" or data.get("kind") != driver
                    or data.get("runId") != run_id or data.get("journey") != journey or not journey
                    or _origin(data.get("target")) != _origin(target)):
                return False
            if driver == "t18":
                if data.get("source") not in {"T18.DOM", "T18.action", "T18.boot-recovery"}:
                    return False
                action = data.get("result", {})
                observed = data.get("observation") or action.get("observation", {})
                if _origin(observed.get("url")) != _origin(target) or not observed.get("revision"):
                    return False
                if data["source"] == "T18.action" and action.get("ok") is not True:
                    return False
            elif (data.get("source") != "T16.pinned-UIA-pattern"
                  or data.get("foregroundAndCursorPreserved") is not True
                  or data.get("postcondition", {}).get("passed") is not True
                  or not data.get("window", {}).get("pid")):
                return False
        except (KeyError, OSError, TypeError, ValueError, AttributeError):
            return False
    return True


def aggregate(catalog, results, provenance):
    """A partial run is useful evidence, but cannot produce a passing release gate."""
    malformed = []
    if not isinstance(provenance, dict):
        provenance = {}
        malformed.append("Invalid provenance structure")
    if not isinstance(results, (list, dict)):
        results = []
        malformed.append("Invalid results structure")
    results = list(results.values()) if isinstance(results, dict) else list(results)
    if any(not isinstance(result, dict) for result in results):
        malformed.append("Invalid result row")
        results = [result for result in results if isinstance(result, dict)]
    candidate = provenance.get("candidate", {})
    stable = provenance.get("stable", {})
    candidate = candidate if isinstance(candidate, dict) else {}
    stable = stable if isinstance(stable, dict) else {}
    target = provenance.get("candidateUrl") or candidate.get("url")
    errors = list(malformed)
    if provenance.get("runErrors"):
        errors.extend(provenance["runErrors"])
    if "desktopGuard" in provenance and (not isinstance(provenance["desktopGuard"], dict) or provenance["desktopGuard"].get("passed") is not True):
        errors.append("Owned desktop guard failed")
    if not provenance.get("runId") or not (provenance.get("stableCommit") or stable.get("commit")):
        errors.append("Pinned stable commit and runId required")
    if not (provenance.get("candidateCommit") or candidate.get("commit")) or not _origin(target):
        errors.append("Candidate commit and explicit candidate URL required")
    known = {row["id"] for row in catalog["rows"]}
    by_id = {}
    for result in results:
        identity = result.get("id")
        if not isinstance(identity, str):
            errors.append("Invalid result identity")
            continue
        if identity not in known:
            errors.append(f"Unknown result: {identity}")
        if identity in by_id:
            errors.append(f"Duplicate result: {identity}")
        by_id[identity] = result
    report = []
    for row in catalog["rows"]:
        result = by_id.get(row["id"])
        targets = provenance.get("journeyTargets", {})
        row_target = targets.get(row["id"], target) if isinstance(targets, dict) else target
        reasons = []
        waiting_step = result.get("waitingStep") if result else None
        waiting = (result is not None and result.get("status") == "waiting"
                   and bool(waiting_step) and result.get("waitingFor", "C11") == "C11"
                   and result.get("sourceHash") == row["sourceHash"])
        if result is None:
            reasons.append("No journey result")
        elif waiting:
            reasons.append("Native-only journey waiting for C11: " + str(waiting_step))
        else:
            if result.get("status") != "passed":
                reasons.append(f"Journey status: {result.get('status', 'missing')}")
            if result.get("exitCode", 0) != 0:
                reasons.append("Journey process did not complete successfully")
            if result.get("pageErrors"):
                reasons.append("Candidate page raised an unhandled error")
            if result.get("cleanupError"):
                reasons.append("Owned browser cleanup did not complete successfully")
            if result.get("sourceHash") != row["sourceHash"]:
                reasons.append("Result source hash differs from inventory")
            checks = result.get("checks", [])
            if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
                reasons.append("Invalid check structure")
                checks = []
            for name in row["checks"]:
                matching = [check for check in checks if check.get("id") == name]
                if len(matching) != 1 or matching[0].get("passed") is not True or "observed" not in matching[0]:
                    reasons.append(f"Missing or failed fresh goal check: {name}")
            if any(check.get("passed") is not True for check in checks):
                reasons.append("A reported check failed")
            goals = result.get("goals", [])
            if not isinstance(goals, list) or any(not isinstance(goal, dict) for goal in goals):
                goals = []
            if not goals or any(goal.get("passed") is not True or "observed" not in goal for goal in goals):
                reasons.append("Missing or failed independently observed goal assertion")
            # Reading a missing/incomplete proof status is not a feature journey.
            # This requirement is derived from the authoritative source contract,
            # not from a runner flag that a receipt can omit to gain a pass.
            if any(contract.get('tool') == 'neyvia.verify.status' for contract in row.get('checkContracts', {}).values()):
                effect = result.get('effectEvidence')
                if (not isinstance(effect, dict) or effect.get('passed') is not True
                        or not effect.get('boundary') or not isinstance(effect.get('observed'), dict)
                        or not effect.get('checks') or any(not isinstance(c, dict) or c.get('passed') is not True or c.get('fresh') is not True
                                                          for c in effect.get('checks', []))
                        or effect.get('observed', {}).get('unprovedDefiningMechanisms')
                        or effect.get('missingPrerequisite')):
                    reasons.append('Missing or incomplete defining-effect proof; status reads and synthetic model evidence are insufficient')
                policy_path = Path(__file__).resolve().parents[2] / 'config/inception_c8e_effects.json'
                try:
                    policy = json.loads(policy_path.read_text(encoding='utf-8'))['bindings'][row['id']]['c8eEffect']
                    for overlay_name in ('inception_c8e_extra_effects.json', 'inception_c8e_ui_effects.json', 'inception_c8e_host_effects.json', 'inception_c8e_state_effects.json'):
                        additions = json.loads((policy_path.parent / overlay_name).read_text(encoding='utf-8'))['bindings'].get(row['id'], {})
                        policy.update(additions.get('c8eEffect', {}))
                    required = set(policy.get('requiredContractIds', []))
                    coverage = effect.get('contractEffects', []) if isinstance(effect, dict) else []
                    covered = [c['id'] for c in coverage if isinstance(c, dict) and c.get('passed') is True
                               and c.get('boundary') in {'rendered-user-action', 'production-device', 'production-provider', 'production-state'}
                               and c.get('observed') and c.get('fresh') is True]
                    if (not isinstance(coverage, list) or not required
                            or len(coverage) != len(covered) or len(covered) != len(set(covered)) or set(covered) != required):
                        reasons.append('Not every applicable source contract has a fresh real defining effect')
                except (OSError, ValueError, KeyError, TypeError):
                    reasons.append('Missing authoritative defining-effect coverage policy')
                calls = result.get('calls', [])
                if not any(call.get('tool') == 'neyvia.verify' for call in calls):
                    reasons.append('No real fresh proof producer ran before the status reader')
                # Retained HTTP receipt bytes remain necessary, and cannot by
                # themselves confer rendered/device/provider authority.
                for call in calls:
                    try:
                        proof = Path(call['receipt']).resolve()
                        proof.relative_to(Path(__file__).resolve().parents[2] / 'scripts/evidence/C8-runs')
                        data = json.loads(proof.read_text(encoding='utf-8'))
                        if (hashlib.sha256(proof.read_bytes()).hexdigest() != call.get('sha256')
                                or data.get('tool') != call.get('tool') or data.get('body') != call.get('body')):
                            raise ValueError('Changed call receipt')
                        if call.get('tool') == 'neyvia.verify':
                            wire = Path(call['bodyWireProof']).resolve()
                            wire.relative_to(Path(__file__).resolve().parents[2] / 'scripts/evidence/C8-runs')
                            if (hashlib.sha256(wire.read_bytes()).hexdigest() != call['bodyWireSha256']
                                    or json.loads(wire.read_text(encoding='utf-8')) != data['body']):
                                raise ValueError('Changed production HTTP body')
                    except (OSError, KeyError, ValueError, TypeError):
                        reasons.append('Missing or invalid defining-effect call receipt')
                        break
            if not _receipts_valid(result.get("t18"), row_target, "t18", provenance.get("runId"), result.get("journey")):
                reasons.append("Missing, stale, wrong-target or invalid T18 proof")
        if row["kind"] == "manual-without-procedures":
            reasons.append("Manual has no authored executable procedure")
        web_reasons = list(reasons)
        native_waiting_step = None
        if result is not None:
            if provenance.get("executionMode") == "headless" or result.get("executionMode") == "headless":
                reasons.append("Native T16 journey blocked pending isolated C11 desktop")
                native_waiting_step = waiting_step or {
                    "phase": "native T16 replay", "journey": row["id"],
                    "required": "Drive this manual's procedure and goal checks through the pinned T16 UIA driver on the isolated C11 agent desktop"}
            elif not _receipts_valid(result.get("t16"), row_target, "t16", provenance.get("runId"), result.get("journey")):
                reasons.append("Missing, stale, wrong-target or invalid T16 proof")
        web_outcome = "waiting" if waiting else "fail" if web_reasons else "pass"
        outcome = "fail" if web_outcome == "fail" else "waiting" if reasons else "pass"
        classification = None
        if web_outcome == "fail":
            classification = result.get("failureClassification") if result else None
            if classification not in FAILURE_CLASSES:
                classification = "journey bug"
        error = result.get("error") if result else "No journey result"
        report.append({**row, "status": "passed" if not reasons else "uncovered" if result is None else "blocked",
                       "webStatus": "passed" if not web_reasons else "blocked", "webReasons": web_reasons,
                       "outcome": outcome, "webOutcome": web_outcome,
                       "failureClassification": classification,
                       "error": error or ("; ".join(web_reasons) if web_outcome == "fail" else None),
                       "waitingFor": "C11" if outcome == "waiting" else None,
                       "waitingStep": native_waiting_step or (waiting_step if waiting else None),
                       "reasons": reasons, "result": result})
    passed = sum(row["status"] == "passed" for row in report)
    web_passed = sum(row["webStatus"] == "passed" for row in report)
    per_manual = {}
    for row in report:
        manual = per_manual.setdefault(row["manual"], {
            "expected": 0, "web": {"pass": 0, "fail": 0, "waiting": 0},
            "release": {"pass": 0, "fail": 0, "waiting": 0},
            "failureClasses": {name: 0 for name in sorted(FAILURE_CLASSES)}, "journeys": []})
        manual["expected"] += 1
        manual["web"][row["webOutcome"]] += 1
        manual["release"][row["outcome"]] += 1
        if row["failureClassification"]:
            manual["failureClasses"][row["failureClassification"]] += 1
        manual["journeys"].append({key: row[key] for key in (
            "id", "webOutcome", "outcome", "failureClassification", "error", "waitingFor", "waitingStep")})
    for manual in per_manual.values():
        manual["webCoverageGate"] = manual["web"]["pass"] == manual["expected"] and not errors
        manual["releaseGate"] = manual["release"]["pass"] == manual["expected"] and not errors
    return {"schema": "neyvia.inception.report.v1", "releaseGate": bool(report) and passed == len(report) and not errors,
            "webCoverageGate": bool(report) and web_passed == len(report) and not errors,
            "provenance": provenance, "errors": errors, "rows": report, "perManual": per_manual,
            "counts": {**catalog.get("counts", {}), "expected": len(report), "passed": passed, "webPassed": web_passed,
                       "webFailed": sum(row["webOutcome"] == "fail" for row in report),
                       "webWaiting": sum(row["webOutcome"] == "waiting" for row in report),
                       "failed": sum(row["outcome"] == "fail" for row in report),
                       "waiting": sum(row["outcome"] == "waiting" for row in report),
                       "attempted": sum("startedAt" in result for result in results),
                       "unbound": sum(result.get("coverageGap") == "no-binding" for result in results),
                       "uncovered": sum(row["status"] == "uncovered" for row in report),
                       "blocked": sum(row["status"] == "blocked" for row in report)}}
