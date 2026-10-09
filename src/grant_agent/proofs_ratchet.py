"""C7 cases for the monotonic, source-bound release coverage ratchet."""
from __future__ import annotations

import time

from .contract_ratchet import BASELINE_PATH, SCHEMA, evaluate, payload_sha256, validate_baseline


CONTRACT = "p22.coverage-ratchet.monotonic"


def _binding(commit="1" * 40, digest="a" * 64, policy="c" * 64):
    return {"path": BASELINE_PATH, "sha256": digest, "commit": commit,
            "policySha256": policy}


def _source(binding, *, tracked=True, committed=True, measured_ancestor=True):
    return {**binding, "tracked": tracked, "committed": committed,
            "measuredCommitAncestor": measured_ancestor, "blobSha256": "e" * 64,
            "containingCommit": "f" * 40}


def _baseline(paths, binding):
    payload = {"schema": SCHEMA, "paths": paths, "coverageSince": "0" * 40}
    binding["sha256"] = payload_sha256(payload)
    return {**payload, "sourceBinding": binding}


def _require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def _case_shrink_and_regrowth():
    old_binding = _binding(commit="1" * 40, digest="a" * 64)
    old = _baseline(["src/a.py", "src/b.py"], old_binding)
    shrink_result = evaluate(old, ["src/a.py"],
                             source_binding=_source(old_binding),
                             bootstrap_authorized=True)
    _require(shrink_result["ok"]
             and shrink_result["retiredBaselineDebt"] == ["src/b.py"]
             and shrink_result["shrinkProposal"] == ["src/a.py"],
             "passing run did not retire b and propose the intersection with the old baseline")

    first_candidate_binding = _binding(commit="2" * 40, digest="b" * 64)
    first_candidate = _baseline(["src/a.py"], first_candidate_binding)
    validate_baseline(first_candidate, source_binding=_source(first_candidate_binding),
                      previous_baseline=old,
                      previous_source_binding=_source(old_binding))
    later_binding = _binding(commit="3" * 40, digest="d" * 64)
    later = _baseline(["src/a.py"], later_binding)
    regrowth = evaluate(later, ["src/a.py", "src/b.py"],
                        source_binding=_source(later_binding),
                        previous_baseline=first_candidate,
                        previous_source_binding=_source(first_candidate_binding))
    _require(not regrowth["ok"] and regrowth["newUncoveredPaths"] == ["src/b.py"]
             and regrowth["shrinkProposal"] is None,
             "previously retired debt was allowed to regrow")


def _case_new_path_fails():
    binding = _binding()
    result = evaluate(_baseline(["src/a.py", "src/b.py"], binding),
                      ["src/a.py", "src/b.py", "src/c.py"],
                      source_binding=_source(binding), bootstrap_authorized=True)
    _require(not result["ok"] and result["newUncoveredPaths"] == ["src/c.py"]
             and result["shrinkProposal"] is None,
             "new uncovered behavior path did not fail admission")


def _case_baseline_expansion_fails():
    previous_binding = _binding(commit="1" * 40, digest="a" * 64)
    candidate_binding = _binding(commit="2" * 40, digest="b" * 64)
    try:
        validate_baseline(_baseline(["src/a.py", "src/b.py"], candidate_binding),
                          source_binding=_source(candidate_binding),
                          previous_baseline=_baseline(["src/a.py"], previous_binding),
                          previous_source_binding=_source(previous_binding))
    except ValueError as error:
        _require("may not add debt" in str(error), "baseline growth failed for an unrelated reason")
        return
    raise AssertionError("expanded baseline was accepted")


def _case_malformed_paths_refused():
    binding = _binding()
    malformed = (["src/../secret.py"], ["src/b.py", "src/a.py"],
                 ["src/a.py", "src/a.py"], ["C:/outside.py"], ["src\\outside.py"])
    for paths in malformed:
        try:
            validate_baseline(_baseline(paths, binding), source_binding=_source(binding),
                              bootstrap_authorized=True)
        except ValueError:
            continue
        raise AssertionError(f"unsafe or noncanonical baseline paths were accepted: {paths!r}")


def _case_binding_refused():
    binding = _binding()
    doc = _baseline(["src/a.py"], binding)
    for source in (_source(binding, tracked=False), _source(binding, committed=False),
                   _source(binding, measured_ancestor=False),
                   _source({**binding, "policySha256": "e" * 64}),
                   _source({**binding, "sha256": "f" * 64})):
        try:
            validate_baseline(doc, source_binding=source, bootstrap_authorized=True)
        except ValueError:
            continue
        raise AssertionError("untracked, uncommitted, or mismatched baseline source binding was accepted")
    try:
        validate_baseline(doc, source_binding=_source(binding))
    except ValueError as error:
        _require("bootstrap authorization" in str(error), "first baseline failed for an unrelated reason")
    else:
        raise AssertionError("first baseline was accepted without explicit bootstrap authorization")


def _case_payload_hash_is_non_circular_and_checked():
    binding = _binding()
    document = _baseline(["src/a.py"], binding)
    _require(document["sourceBinding"]["sha256"] == payload_sha256(document),
             "payload hash includes sourceBinding or is not canonical")
    tampered = {**document, "paths": ["src/b.py"]}
    try:
        validate_baseline(tampered, source_binding=_source(binding), bootstrap_authorized=True)
    except ValueError as error:
        _require("canonical schema+paths" in str(error), "payload tampering failed for the wrong reason")
    else:
        raise AssertionError("schema+paths mutation passed with the old payload hash")


def _case_coverage_reference_is_immutable():
    previous_binding = _binding(commit="1" * 40, digest="a" * 64)
    previous = _baseline(["src/a.py", "src/b.py"], previous_binding)
    candidate_binding = _binding(commit="2" * 40, digest="b" * 64)
    candidate = {"schema": SCHEMA, "paths": ["src/a.py"], "coverageSince": "9" * 40}
    candidate_binding["sha256"] = payload_sha256(candidate)
    candidate["sourceBinding"] = candidate_binding
    try:
        validate_baseline(candidate, source_binding=_source(candidate_binding),
                          previous_baseline=previous,
                          previous_source_binding=_source(previous_binding))
    except ValueError as error:
        _require("coverageSince is immutable" in str(error),
                 "changing coverageSince failed for an unrelated reason")
    else:
        raise AssertionError("coverageSince changed during baseline shrink")


def _case_contract_failures_block():
    binding = _binding()
    doc = _baseline(["src/a.py"], binding)
    cases = (
        ({"failed_contracts": ["p22.ui.render"]}, "failing outcome contracts"),
        ({"stale_contracts": ["p22.ui.render"]}, "stale outcome witnesses"),
        ({"missing_runners": ["p22.ui.render"]}, "missing outcome runners"),
    )
    for inputs, reason in cases:
        result = evaluate(doc, ["src/a.py"], source_binding=_source(binding),
                          bootstrap_authorized=True, **inputs)
        _require(not result["ok"] and reason in result["reasons"]
                 and result["shrinkProposal"] is None,
                 f"{reason} did not independently block release")


def _case_count_labels_remain_separate():
    binding = _binding()
    execution = {"pythonExecutedLines": 17, "passingContracts": 4}
    static_web = {"v8CoveredLines": 11, "sourcemapUnknownLines": 2}
    result = evaluate(_baseline(["src/a.py"], binding), ["src/a.py"],
                      source_binding=_source(binding), bootstrap_authorized=True,
                      execution_counts=execution, static_web_counts=static_web)
    _require(result["executionCounts"] == execution and result["staticWebCounts"] == static_web,
             "execution and static-web measurements were merged or relabeled")


def _case_failed_rows_cannot_override_positive_witness():
    from .contract_measurements import outcome_passes
    identity = 'p22.ui.render'
    passed = {'ok': True, 'contracts': [identity], 'cases': [
        {'id': identity, 'contracts': [identity], 'ok': True}],
        'outcomes': [{'id': identity, 'status': 'PASS'}]}
    _require(outcome_passes(passed), 'consistent passing witnesses were refused')
    contradictions = (
        {'cases': [{'id': identity, 'ok': False}]},
        {'checks': [{'contract': identity, 'ok': False}]},
        {'outcomes': [{'id': identity, 'status': 'FAIL'}]},
        {'contracts': [{'id': identity, 'status': 'failed'}]},
        {'failures': ['failed observation']},
        {'ok': False},
    )
    for failed in contradictions:
        _require(not outcome_passes({**passed, **failed}),
                 'a positive witness overrode an explicit failure')


_CASES = (
    ("shrink_and_retired_debt_regrowth", _case_shrink_and_regrowth),
    ("new_uncovered_path_fails", _case_new_path_fails),
    ("expanded_baseline_fails", _case_baseline_expansion_fails),
    ("malformed_paths_refused", _case_malformed_paths_refused),
    ("source_binding_and_bootstrap_refused", _case_binding_refused),
    ("canonical_payload_hash_and_candidate_binding", _case_payload_hash_is_non_circular_and_checked),
    ("coverage_since_is_immutable", _case_coverage_reference_is_immutable),
    ("failing_stale_and_missing_runner_block", _case_contract_failures_block),
    ("execution_and_static_web_labels_separate", _case_count_labels_remain_separate),
    ("contradictory_positive_witness_refused", _case_failed_rows_cannot_override_positive_witness),
)


def self_check(root=None, selected=None):
    """Run pure C7 ratchet cases; no repository reads or external services."""
    from .contract_gate import wants

    started = time.perf_counter()
    selected_ids = ({selected} if isinstance(selected, str)
                    else set(selected) if selected is not None else {CONTRACT})
    if CONTRACT not in selected_ids or not wants([CONTRACT]):
        return {"ok": True, "contracts": [], "cases": [], "durationMs": 0}
    cases = []
    for name, action in _CASES:
        try:
            action()
            cases.append({"id": f"{CONTRACT}.{name}", "contracts": [CONTRACT], "ok": True})
        except Exception as error:
            cases.append({"id": f"{CONTRACT}.{name}", "contracts": [CONTRACT], "ok": False,
                          "error": f"{type(error).__name__}: {error}"})
    passed = all(row["ok"] for row in cases)
    return {"schema": "neyvia.p22-coverage-ratchet.c7.v1", "area": "coverage-ratchet",
            "ok": passed, "contracts": [CONTRACT] if passed else [], "cases": cases,
            "durationMs": round((time.perf_counter() - started) * 1000, 3)}
