"""Pure release admission and monotonic behavior-debt baseline checks."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath


SCHEMA = "neyvia.p22-behavior-debt-baseline.v1"
BASELINE_PATH = "scripts/evidence/P22-coverage-baseline.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_BINDING_FIELDS = ("path", "sha256", "commit", "policySha256")


def _paths(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of relative repository paths")
    normalized = []
    for path in value:
        if (not isinstance(path, str) or not path or "\\" in path or path.startswith("/")
                or any(part in ("", ".", "..") for part in path.split("/"))
                or ":" in path):
            raise ValueError(f"{label} contains an unsafe or non-normalized path: {path!r}")
        if PurePosixPath(path).as_posix() != path:
            raise ValueError(f"{label} contains a non-normalized path: {path!r}")
        normalized.append(path)
    if normalized != sorted(set(normalized)):
        raise ValueError(f"{label} must be sorted and unique")
    return normalized


def _binding_shape(binding, label):
    if not isinstance(binding, dict):
        raise ValueError(f"{label} is required")
    for field in _BINDING_FIELDS:
        if not isinstance(binding.get(field), str) or not binding[field]:
            raise ValueError(f"{label}.{field} is missing")
    if binding["path"] != BASELINE_PATH:
        raise ValueError(f"{label} does not identify the release baseline path")
    if not _SHA256.fullmatch(binding["sha256"]):
        raise ValueError(f"{label}.sha256 is malformed")
    if not _COMMIT.fullmatch(binding["commit"]):
        raise ValueError(f"{label}.commit is malformed")
    if not _SHA256.fullmatch(binding["policySha256"]):
        raise ValueError(f"{label}.policySha256 is malformed")


def payload_sha256(document):
    """Hash canonical JSON for schema+paths+coverageSince, excluding sourceBinding."""
    payload = {"schema": document.get("schema"), "paths": document.get("paths"),
               "coverageSince": document.get("coverageSince")}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_binding(baseline_binding, actual_binding, label):
    _binding_shape(baseline_binding, f"{label}.sourceBinding")
    if not isinstance(actual_binding, dict):
        raise ValueError(f"Independently verified {label} source binding is required")
    if (actual_binding.get("tracked") is not True
            or actual_binding.get("committed") is not True
            or actual_binding.get("measuredCommitAncestor") is not True):
        raise ValueError(f"{label} baseline blob must be tracked, committed, and descend from the measured candidate")
    if not _SHA256.fullmatch(str(actual_binding.get("blobSha256", ""))):
        raise ValueError(f"Independently verified {label} Git blob hash is missing or malformed")
    if not _COMMIT.fullmatch(str(actual_binding.get("containingCommit", ""))):
        raise ValueError(f"Independently verified {label} containing commit is missing or malformed")
    for field in _BINDING_FIELDS:
        if actual_binding.get(field) != baseline_binding[field]:
            raise ValueError(f"{label} source binding mismatch: {field}")


def validate_baseline(document, *, source_binding, previous_baseline=None,
                      previous_source_binding=None, bootstrap_authorized=False):
    """Validate exact debt paths and their Git/policy binding.

    ``sourceBinding.sha256`` hashes canonical JSON of ``schema``, ``paths``,
    and ``coverageSince`` (UTF-8, sorted keys, compact separators); it excludes
    ``sourceBinding`` to avoid a circular self-hash. ``coverageSince`` is the
    immutable original impact reference. ``sourceBinding.commit``
    is the measured candidate commit before the baseline commit. Callers must
    independently verify the containing Git blob/ref, tracked/committed
    state, active policy hash, and ancestry of that measured commit, then pass
    those facts in ``source_binding``. The first baseline requires explicit
    bootstrap authorization. Later baselines can only remove paths from the
    previous independently bound committed baseline.
    """
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("Unknown behavior-debt baseline schema")
    if set(document) != {"schema", "paths", "coverageSince", "sourceBinding"}:
        raise ValueError("Behavior-debt baseline has missing or unexpected fields")
    paths = _paths(document["paths"], "baseline.paths")
    if not isinstance(document["coverageSince"], str) or not _COMMIT.fullmatch(document["coverageSince"]):
        raise ValueError("baseline.coverageSince must be a full Git commit reference")
    _validate_binding(document["sourceBinding"], source_binding, "baseline")
    if document["sourceBinding"]["sha256"] != payload_sha256(document):
        raise ValueError("Baseline sourceBinding.sha256 must hash canonical schema+paths payload")

    if previous_baseline is None:
        if not bootstrap_authorized:
            raise ValueError("First baseline requires explicit bootstrap authorization")
    else:
        if previous_source_binding is None:
            raise ValueError("Previous baseline requires independent Git/source binding")
        previous_paths = validate_baseline(
            previous_baseline, source_binding=previous_source_binding,
            bootstrap_authorized=True)
        if document["coverageSince"] != previous_baseline["coverageSince"]:
            raise ValueError("coverageSince is immutable across baseline generations")
        expanded = sorted(set(paths) - set(previous_paths))
        if expanded:
            raise ValueError("Baseline may not add debt paths: " + ", ".join(expanded[:8]))
    return paths


def coverage_reference(document):
    """Return the immutable original impact ref after validating its shape."""
    if not isinstance(document, dict) or not isinstance(document.get("coverageSince"), str):
        raise ValueError("Baseline coverageSince is missing")
    if not _COMMIT.fullmatch(document["coverageSince"]):
        raise ValueError("Baseline coverageSince must be a full Git commit reference")
    return document["coverageSince"]


def _identities(value, label):
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{label} must be a collection of contract IDs")
    items = list(value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ValueError(f"{label} contains an invalid contract ID")
    return sorted(set(items))


def _counts(value, label):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an independent labeled count object")
    if any(not isinstance(key, str) or not key or isinstance(count, bool)
           or not isinstance(count, int) or count < 0 for key, count in value.items()):
        raise ValueError(f"{label} contains an invalid count")
    return dict(value)


def evaluate(document, current_uncovered, *, source_binding, previous_baseline=None,
             previous_source_binding=None, bootstrap_authorized=False,
             failed_contracts=(), stale_contracts=(), missing_runners=(),
             execution_counts=None, static_web_counts=None):
    """Compare measured behavior debt with a committed baseline.

    Static/web counts are carried as separate labeled evidence and never
    contribute coverage credit or alter the uncovered path comparison.
    """
    baseline_paths = validate_baseline(
        document, source_binding=source_binding, previous_baseline=previous_baseline,
        previous_source_binding=previous_source_binding,
        bootstrap_authorized=bootstrap_authorized)
    current_paths = _paths(sorted(current_uncovered) if isinstance(current_uncovered, (set, frozenset))
                           else current_uncovered, "current_uncovered")
    baseline_set, current_set = set(baseline_paths), set(current_paths)
    new_paths = sorted(current_set - baseline_set)
    retired_paths = sorted(baseline_set - current_set)
    failed = _identities(failed_contracts, "failed_contracts")
    stale = _identities(stale_contracts, "stale_contracts")
    missing = _identities(missing_runners, "missing_runners")
    reasons = []
    if new_paths:
        reasons.append("new uncovered behavior paths")
    if failed:
        reasons.append("failing outcome contracts")
    if stale:
        reasons.append("stale outcome witnesses")
    if missing:
        reasons.append("missing outcome runners")
    passed = not reasons
    return {
        "status": "passed" if passed else "failed",
        "ok": passed,
        "reasons": reasons,
        "baselinePaths": baseline_paths,
        "coverageSince": coverage_reference(document),
        "currentUncoveredPaths": current_paths,
        "newUncoveredPaths": new_paths,
        "remainingBaselineDebt": sorted(current_set & baseline_set),
        "retiredBaselineDebt": retired_paths,
        "failedContracts": failed,
        "staleContracts": stale,
        "missingRunners": missing,
        "shrinkProposal": (sorted(current_set & baseline_set) if passed else None),
        "executionCounts": _counts(execution_counts, "execution_counts"),
        "staticWebCounts": _counts(static_web_counts, "static_web_counts"),
    }
