"""Transaction-local provider circuit and secret-free auth-queue contracts.

The startup procedure supplies presence and flow metadata as explicit lab inputs.
It proves durable scheduling behavior, never real provider authentication.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from .proofs_d_runtime import require


def check_queue_payload(payload):
    from .provider_auth_queue import AUTH_QUEUE_SCHEMA, PROVIDER_SPECS, KNOWN_ITEM_STATES, FLOW_FIELDS, AUTH_FLOW_START_LEASE_SECONDS, AUTH_FLOW_START_CLOCK_SKEW_SECONDS
    identity = "d.runtime.auth-queue.state"
    require(payload.get("schema") == AUTH_QUEUE_SCHEMA and isinstance(payload.get("items"), list), identity, "unsupported durable queue shape")
    providers = []
    for item in payload["items"]:
        require(isinstance(item, dict) and item.get("providerId") in PROVIDER_SPECS
                and item.get("state") in KNOWN_ITEM_STATES and isinstance(item.get("flow", {}), dict),
                identity, "provider identity/lifecycle/flow is not canonical")
        require(set(item.get("flow", {})) <= FLOW_FIELDS, "d.runtime.auth-queue.flow", "durable flow retained nonpublic helper/secret fields")
        providers.append(item["providerId"])
        claim = item.get("flowStartClaim")
        if claim is not None:
            try:
                parsed = uuid.UUID(hex=claim["claimId"])
                claimed = datetime.strptime(claim["claimedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                expiration = claim["expiresAtEpoch"]
                valid = (parsed.hex == claim["claimId"] and parsed.version == 4 and parsed.variant == uuid.RFC_4122
                    and claimed.strftime("%Y-%m-%dT%H:%M:%SZ") == claim["claimedAt"]
                    and not isinstance(expiration, bool) and isinstance(expiration, (float, int)) and math.isfinite(expiration)
                    and 0 <= expiration - claimed.timestamp() <= AUTH_FLOW_START_LEASE_SECONDS + 2
                    and claimed.timestamp() <= time.time() + AUTH_FLOW_START_CLOCK_SKEW_SECONDS
                    and expiration <= time.time() + AUTH_FLOW_START_LEASE_SECONDS + AUTH_FLOW_START_CLOCK_SKEW_SECONDS)
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                valid = False
            require(valid, "d.runtime.auth-queue.startup", "startup claim identity/time/lease is malformed")
    require(len(providers) == len(set(providers)), identity, "a provider is duplicated in one operation sequence")


def check_queue_save(payload, directory, filename):
    check_queue_payload(payload)
    require(json.loads(directory.read_text(filename)) == payload,
            "d.runtime.auth-queue.persisted", "anchored durable queue differs from successful save")


def check_queue_transition(action, arguments, before, after, observations):
    """Called while holding the existing process/advisory mutation lock."""
    from .provider_auth_queue import _clean_provider_ids, FLOW_FIELDS
    identity = "d.runtime.auth-queue.transition"
    check_queue_payload(after)
    if action == "start":
        expected_ids = _clean_provider_ids(arguments["provider_ids"])
        require([r["providerId"] for r in after["items"]] == expected_ids, identity, "start lost requested provider order")
        for item in after["items"]:
            present = observations.get(item["providerId"], False)
            require((item["state"] == "connected") is bool(present), identity, "start connection state must derive from supplied presence evidence")
        return
    require(before["queueId"] == after["queueId"]
            and [r["providerId"] for r in before["items"]] == [r["providerId"] for r in after["items"]],
            identity, "transition replaced queue or provider sequence")
    prior = {r["providerId"]: r for r in before["items"]}
    current = {r["providerId"]: r for r in after["items"]}
    require(all(current[k].get("operationId") == row.get("operationId") for k, row in prior.items()),
            identity, "transition changed a durable provider operation identity")
    target = str(arguments.get("provider_id") or "").strip().lower()
    for provider, original in prior.items():
        result = current[provider]
        if action == "status" and provider in observations:
            if observations[provider]:
                require(result["state"] == "connected" and not result.get("flow") and not result.get("flowStartClaim"),
                        identity, "observed presence did not settle connection state")
            elif original["state"] == "connected":
                require(result["state"] == "blocked" and result.get("blockerKind") == "provider-auth-evidence-missing"
                        and not result.get("completedAt"), identity, "lost evidence must become a visible blocker")
        if original["state"] in {"cancelled", "skipped"}:
            require(result == original, identity, "terminal provider was resurrected or changed")
        if action == "cancel" and original["state"] in {"active", "pending", "blocked"}:
            require(result["state"] == "cancelled" and not result["flow"] and "flowStartClaim" not in result,
                    identity, "cancel must clear unfinished flows and startup ownership")
        if provider != target:
            continue
        if action == "record_flow" and original["state"] in {"active", "blocked"}:
            old_flow = original.get("flow", {})
            incoming = {k: v for k, v in arguments["flow"].items() if k in FLOW_FIELDS and v not in (None, "")}
            if old_flow.get("sessionId") and not incoming.get("sessionId"):
                require(result == original, identity, "sessionless observer erased the owning flow")
            else:
                require(result["flow"] == incoming and result["state"] == "active" and "flowStartClaim" not in result,
                        "d.runtime.auth-queue.flow", "accepted flow differs from sanitized supplied metadata")
        elif action == "mark_connected" and original["state"] in {"active", "blocked"}:
            require(result["state"] == "connected" and not result["flow"] and "flowStartClaim" not in result,
                    identity, "completion did not settle the active provider")
            require(not any("flowStartClaim" in row for row in after["items"] if row["providerId"] != provider and row["state"] == "active"),
                    "d.runtime.auth-queue.startup", "side-effect callback leased the next provider before a poller")
        elif action == "skip":
            require(result["state"] == "skipped" and not result["flow"] and "flowStartClaim" not in result,
                    identity, "skip did not become terminal")
        elif action == "release_claim":
            old_claim = original.get("flowStartClaim") or {}
            owned = original["state"] in {"active", "blocked"} and not original.get("flow") and old_claim.get("claimId") == arguments["claim_id"]
            require(("flowStartClaim" not in result) if owned else result == original,
                    "d.runtime.auth-queue.startup", "claim release changed a different startup owner")
    if action == "cancel":
        require(after["status"] == "cancelled" and after["activeProviderId"] == "", identity, "cancelled queue remains actionable")


def check_queue_present(payload, result, *, flow_start_waiting, suppress_next_action, claim_owner):
    from .provider_auth_queue import PROVIDER_SPECS
    identity = "d.runtime.auth-queue.projection"
    require(result["queueId"] == payload["queueId"] and result["activeProviderId"] == payload["activeProviderId"]
            and result["secretMaterialStored"] is False and result["automaticAdvance"] is True
            and len(result["items"]) == len(payload["items"]), identity, "public queue projection changed durable identity")
    for source, visible in zip(payload["items"], result["items"]):
        require("flowStartClaim" not in visible
                and all(visible.get(k) == v for k, v in source.items() if k != "flowStartClaim")
                and visible["credentialPolicy"] == PROVIDER_SPECS[source["providerId"]]["credentialPolicy"]
                and visible["consumers"] == PROVIDER_SPECS[source["providerId"]]["consumers"],
                identity, "public item altered durable metadata, leaked claim or changed provider policy")
    active = next((r for r in payload["items"] if r["providerId"] == payload["activeProviderId"]), None)
    should_offer = active is not None and not flow_start_waiting and not suppress_next_action
    require((result["nextAction"] is not None) is should_offer and result["providerFlowStarting"] is bool(flow_start_waiting),
            "d.runtime.auth-queue.startup", "waiting/suppressed startup was offered twice")
    if should_offer:
        require(result["nextAction"]["providerId"] == active["providerId"]
                and result["nextAction"]["flow"] == (active.get("flow") or {}), identity, "action projection selected a different provider/flow")
    if claim_owner and should_offer:
        require(getattr(result, "_flow_start_claim_id", "") == claim_owner[1], "d.runtime.auth-queue.startup", "owning caller lost opaque startup claim")


def circuit_admission(function):
    @wraps(function)
    def invoke(self, db, job, host_id):
        from .cluster import _provider_route_key, _parse_time, _utc_now
        key = _provider_route_key(job, host_id)
        if key is None:
            result = function(self, db, job, host_id)
            require(result.get("allowed") is True and result.get("probe") is False,
                    "d.runtime.circuit.admission", "providerless local job was circuit gated")
            return result
        before = db.execute("SELECT * FROM provider_circuits WHERE host_id=? AND runtime_id=? AND provider=?", key).fetchone()
        before = dict(before) if before else {"state": "closed", "probe_job_id": "", "retry_after": ""}
        prior_probe = None
        if before["probe_job_id"]:
            prior_probe = db.execute("SELECT jobs.status AS job_status,leases.status AS lease_status FROM jobs LEFT JOIN leases ON leases.lease_id=jobs.lease_id WHERE jobs.job_id=?",
                                    (before["probe_job_id"],)).fetchone()
        now = _utc_now()
        result = function(self, db, job, host_id)
        after = db.execute("SELECT * FROM provider_circuits WHERE host_id=? AND runtime_id=? AND provider=?", key).fetchone()
        blocked_probe = (before["state"] == "half_open" and before["probe_job_id"] != job["jobId"] and prior_probe
            and prior_probe["job_status"] in {"leased", "running"} and prior_probe["lease_status"] == "active")
        retry = _parse_time(before["retry_after"])
        blocked_cooldown = before["state"] == "open" and retry is not None and retry > now
        if blocked_probe or blocked_cooldown:
            require(result["allowed"] is False and result["probe"] is False,
                    "d.runtime.circuit.admission", "open cooldown or active canary admitted another job")
        elif before["state"] == "closed":
            require(result["allowed"] is True and result["probe"] is False and after["state"] == "closed",
                    "d.runtime.circuit.admission", "closed circuit must admit without canary mutation")
        else:
            require(result["allowed"] is True and result["probe"] is True and after["state"] == "half_open"
                    and after["probe_job_id"] == job["jobId"], "d.runtime.circuit.admission", "canary admission must reserve exactly this job inside the transaction")
        return result
    return invoke


def check_circuit_result(before, after, classification, *, is_probe, key):
    identity = "d.runtime.circuit.transition"
    require((after["host_id"], after["runtime_id"], after["provider"]) == key
            and after["state"] in {"closed", "open", "half_open"} and after["failure_count"] >= 0,
            identity, "circuit lost host/runtime/provider key or valid state")
    kind = classification["kind"]
    if before["state"] == "open" and not is_probe:
        require(after["state"] == "open", identity, "late in-flight result closed an open circuit")
        if before["last_failure_kind"] in {"auth", "credit"} and kind != before["last_failure_kind"]:
            require(after["retry_after"] >= before["retry_after"], identity, "late transient result weakened credential cooldown")
    elif is_probe and classification.get("success") and not classification.get("providerFailure"):
        require(after["state"] == "closed" and after["failure_count"] == 0 and not after["probe_job_id"] and not after["retry_after"],
                identity, "successful owned canary did not close/reset its circuit")
    elif is_probe and not classification.get("providerFailure"):
        require(after["state"] == "open" and after["last_failure_kind"] == "probe_inconclusive" and not after["probe_job_id"],
                identity, "inconclusive owned canary must reopen briefly")
    elif classification.get("providerFailure") and kind in {"auth", "credit", "rate_limit"}:
        require(after["state"] == "open" and after["last_failure_kind"] == kind and after["retry_after"],
                identity, "route-specific provider failure did not open its cooldown")
    elif classification.get("providerFailure") and kind in {"provider_overload", "provider_transport"}:
        from .cluster import PROVIDER_TRANSIENT_FAILURE_THRESHOLD
        require(after["last_failure_kind"] == kind and after["failure_count"] >= 1
                and after["state"] == ("open" if is_probe or after["failure_count"] >= PROVIDER_TRANSIENT_FAILURE_THRESHOLD else "closed"),
                identity, "transient threshold/canary failure policy changed")


def check_classification(job, payload, result):
    from .cluster import _job_target_provider, _job_target_model
    identity = "d.runtime.circuit.classification"
    require(result["provider"] == _job_target_provider(job) and result["model"] == _job_target_model(job)
            and result["kind"] in {"none", "success", "auth", "credit", "rate_limit", "provider_overload", "provider_transport"}
            and set(result) <= {"provider", "model", "statusCode", "retryAfterSeconds", "context", "kind", "providerFailure", "success"},
            identity, "classification lost route or retained raw process output")
    payload = payload if isinstance(payload, dict) else {}
    return_code = payload.get("returnCode", payload.get("return_code"))
    successful = payload.get("ok") is True or (str(payload.get("status") or "").strip().lower() in {"completed", "success", "succeeded"}
        and (return_code in (None, "") or str(return_code) == "0"))
    if successful and result["provider"]:
        require(result["kind"] == "success" and result["providerFailure"] is False,
                identity, "successful output mentioning auth was classified as credential failure")
    if result["kind"] in {"rate_limit", "provider_overload"}:
        require(result["kind"] != "auth", identity, "load/rate failure became an auth failure")


def classification(function):
    @wraps(function)
    def invoke(job, result):
        value = function(job, result)
        check_classification(job, result, value)
        return value
    return invoke


def check_circuit_reset(row, key, actor, reason):
    require((row["host_id"], row["runtime_id"], row["provider"]) == key and row["state"] == "half_open"
            and row["failure_count"] == 0 and not row["probe_job_id"] and row["last_failure_kind"] == "manual_reset",
            "d.runtime.circuit.reset", "manual reset must request one future canary")
    require(len(actor) <= 120 and len(reason) <= 240 and not re.search(r"(?i)\b(?:token|password|secret)\s*[:=]\s*(?!<redacted>)[^\s,;]+", actor + " " + reason),
            "d.runtime.circuit.reset", "reset evidence retained credential assignment")


def check_circuit_reporting(lease, job_id, host_id):
    require(lease is not None and lease["job_id"] == job_id
            and str(lease["host_id"]).strip().casefold() == str(host_id).strip().casefold()
            and lease["status"] == "active" and lease["job_status"] in {"leased", "running"},
            "d.runtime.circuit.reporting", "provider result must belong to its current active lease and reporting host")


def observed_worker_capabilities(root, host_id, observation):
    """A trusted local observation can suppress detection, not expand roots."""
    from pathlib import Path
    require(isinstance(observation, dict) and observation.get("hostId") == host_id
            and Path(observation.get("workspaceRoot", "")).resolve() == Path(root).resolve()
            and isinstance(observation.get("runtimes"), list) and isinstance(observation.get("capabilities"), list),
            "d.runtime.circuit.worker", "explicit capability evidence must belong to this local host/root")
    require(all(Path(path).resolve().is_relative_to(Path(root).resolve()) for path in observation.get("workspaceMappings", {}).values()),
            "d.runtime.circuit.worker", "capability fixture cannot grant an external workspace route")
    return {**observation, "capabilityEvidence": "explicit-local-observation"}


def check_worker_circuit_before_completion(registry, job, circuit_result):
    classification = circuit_result.get("classification", {})
    if classification.get("providerFailure"):
        require(registry.get_job(job["jobId"])["status"] in {"leased", "running"}
                and circuit_result.get("ok") is True and bool(circuit_result.get("circuit")),
                "d.runtime.circuit.worker", "worker completed a failed provider job before recording the circuit")


def check_worker_doctor(result):
    expected = [row for row in result["providerCircuits"] if row["state"] in {"open", "half_open"}]
    require([row["circuit"] for row in result["circuitIssues"]] == expected
            and all(row["kind"] == "provider_circuit_" + row["circuit"]["state"] for row in result["circuitIssues"])
            and result["status"] == ("limited" if not result["capabilities"]["runtimes"] else "warn" if expected else "ready"),
            "d.runtime.circuit.worker", "doctor omitted an open/half-open circuit or changed its warning status")


def self_check(root):
    """Run real local durable state and scheduling with explicit lab metadata."""
    import os
    import sys
    import threading
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor
    from .provider_auth_queue import ProviderAuthQueue, AUTH_QUEUE_SCHEMA
    from .cluster import ClusterRegistry, classify_provider_result
    from .worker import run_local_worker_once, build_worker_doctor, execute_job
    root = Path(root) / "provider-coordination"
    root.mkdir(parents=True, exist_ok=True)
    checks, rejected, frontier = [], [], []

    def reject(identity, action, retained=None):
        before = retained.read_bytes() if retained is not None else None
        try:
            action()
        except (ValueError, RuntimeError, OSError):
            if retained is not None:
                require(retained.read_bytes() == before, identity, "rejected operation replaced durable evidence")
            rejected.append({"contract": identity, "rejected": True})
        else:
            raise ValueError(identity + ": invalid local operation was accepted")

    presence = {"openai-codex": True, "minimax-portal": False, "anthropic": False}
    def queue(name):
        (root / name).mkdir(exist_ok=True)
        return ProviderAuthQueue(root / name, presence=lambda ids: {p: presence.get(p, False) for p in ids})
    q = queue("advance")
    reject("d.runtime.auth-queue.state", lambda: q.start(["unsupported"]))
    state = q.start(["openai-codex", "minimax-portal", "minimax-portal"])
    require([i["state"] for i in state["items"]] == ["connected", "active"] and state["activeProviderId"] == "minimax-portal",
            "d.runtime.auth-queue.transition", "existing observed connection did not select next route")
    presence["minimax-portal"] = True
    require(q.status()["status"] == "completed", "d.runtime.auth-queue.transition", "presence polling failed to advance without a new start")
    presence["openai-codex"] = False
    presence["minimax-portal"] = False
    blocked = q.status()
    require(blocked["items"][0]["state"] == "blocked" and blocked["nextAction"]["reason"] == "provider-auth-evidence-missing",
            "d.runtime.auth-queue.transition", "lost presence was not actionable")
    q.record_flow("openai-codex", {"sessionId": "lab-repair", "status": "waiting"},
                  startup_claim_id=getattr(blocked, "_flow_start_claim_id", ""))
    require(q.status(refresh_presence=False)["items"][0]["state"] == "active", "d.runtime.auth-queue.flow", "blocked route refused repair metadata")

    q = queue("ownership")
    owner = q.start(["openai-codex", "minimax-portal"])
    claim = getattr(owner, "_flow_start_claim_id", "")
    require(bool(claim) and "flowStartClaim" not in owner["items"][0], "d.runtime.auth-queue.startup", "startup ownership leaked or was not reserved")
    observer = ProviderAuthQueue(q.root, presence=q._presence)
    require(observer._lock is q._lock and observer.status(refresh_presence=False)["nextAction"] is None,
            "d.runtime.auth-queue.startup", "independent process-local coordinator did not wait on durable ownership")
    reject("d.runtime.auth-queue.transition", lambda: observer.start(["anthropic"]), q.path)
    q.record_flow("openai-codex", {"sessionId": "lab-owned", "status": "waiting", "relayToken": "lab-private", "helperSecret": "lab-private"}, startup_claim_id=claim)
    expected = q.path.read_bytes()
    observer.record_flow("openai-codex", {"status": "not_found"})
    require(q.path.read_bytes() == expected and b"lab-private" not in expected,
            "d.runtime.auth-queue.flow", "sessionless observation erased owner or persisted private metadata")
    reject("d.runtime.auth-queue.flow", lambda: observer.record_flow("openai-codex", {"sessionId": "different"}), q.path)
    completed = q.mark_connected("openai-codex")
    require(completed["nextAction"] is None and "flowStartClaim" not in json.loads(q.path.read_text())["items"][1],
            "d.runtime.auth-queue.startup", "side-effect completion reserved next provider without a consumer")
    next_owner = observer.status(refresh_presence=False)
    next_claim = getattr(next_owner, "_flow_start_claim_id", "")
    require(bool(next_claim) and q.status(refresh_presence=False)["nextAction"] is None,
            "d.runtime.auth-queue.startup", "one real poller did not exclusively own next startup")
    observer.release_flow_start_claim("minimax-portal", "wrong-owner")
    require(json.loads(q.path.read_text())["items"][1]["flowStartClaim"]["claimId"] == next_claim,
            "d.runtime.auth-queue.startup", "different caller released startup ownership")
    observer.release_flow_start_claim("minimax-portal", next_claim)
    successor = q.status(refresh_presence=False)
    successor_claim = getattr(successor, "_flow_start_claim_id", "")
    require(successor_claim and successor_claim != next_claim, "d.runtime.auth-queue.startup", "released startup lease was not reissued")
    reject("d.runtime.auth-queue.startup", lambda: observer.record_flow("minimax-portal", {"sessionId": "stale"}, startup_claim_id=next_claim), q.path)
    reject("d.runtime.auth-queue.startup", lambda: observer.mark_connected("minimax-portal", startup_claim_id=next_claim), q.path)
    q.record_flow("minimax-portal", {"sessionId": "successor"}, startup_claim_id=successor_claim)
    cancelled = q.cancel()
    q.mark_connected("minimax-portal")
    require(q.status(refresh_presence=False)["items"][1]["state"] == "cancelled" and not cancelled["nextAction"]
            and json.loads(q.path.read_text())["status"] == "cancelled",
            "d.runtime.auth-queue.transition", "late callback resurrected cancelled state")
    policy = queue("policy").start(["anthropic"])
    require(policy["nextAction"]["manualRequired"] and policy["items"][0]["credentialPolicy"] == "official-only"
            and not any("proxy" in str(c).lower() for c in policy["items"][0]["consumers"]),
            "d.runtime.auth-queue.projection", "official route offered unauthorized proxy binding")
    skipq = queue("skip")
    skipq.start(["openai-codex", "minimax-portal"])
    require(skipq.skip("openai-codex")["activeProviderId"] == "minimax-portal", "d.runtime.auth-queue.transition", "skip did not advance")

    # Real independent instances and threads share one local mutation lock; OS
    # locks may also be process-reentrant, but cannot bypass this shared lock.
    qa, qb = queue("race"), queue("race")
    barrier = threading.Barrier(2)
    def start_contender(instance):
        barrier.wait()
        try:
            return instance.start(["openai-codex"])["queueId"]
        except RuntimeError:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = list(executor.map(start_contender, [qa, qb]))
    require(sum(bool(x) for x in winners) == 1 and qa._lock is qb._lock, "d.runtime.auth-queue.startup", "concurrent starts both replaced the durable queue")
    valid = json.loads(qa.path.read_text())
    invalid = [{"raw": "{"}, {**valid, "schema": AUTH_QUEUE_SCHEMA + ".future"}, {**valid, "items": [None]}]
    for key, value in (("providerId", "OPENAI-CODEX"), ("state", "ACTIVE"), ("providerId", []), ("state", {})):
        payload = copy.deepcopy(valid); payload["items"][0][key] = value; invalid.append(payload)
    for field, value in (("claimId", "not-uuid"), ("expiresAtEpoch", float("inf")), ("expiresAtEpoch", True),
                         ("expiresAtEpoch", time.time() + 100000), ("claimedAt", "2026-01-01t00:00:00z")):
        payload = copy.deepcopy(valid); payload["items"][0]["flowStartClaim"][field] = value; invalid.append(payload)
    for i, payload in enumerate(invalid):
        invalidq = queue("invalid-" + str(i)); invalidq.path.parent.mkdir(parents=True)
        invalidq.path.write_text(payload["raw"] if isinstance(payload, dict) and "raw" in payload else json.dumps(payload), encoding="utf-8")
        reject("d.runtime.auth-queue.state", lambda q=invalidq: q.status(refresh_presence=False), invalidq.path)
        reject("d.runtime.auth-queue.state", lambda q=invalidq: q.start(["anthropic"]), invalidq.path)
    symlink_queue = queue("dangling")
    symlink_queue.path.parent.mkdir()
    try:
        symlink_queue.path.symlink_to(symlink_queue.path.parent / "missing-state.json")
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        frontier.append({"test": "tests/test_provider_auth_queue.py", "case": "ProviderAuthQueueTests.test_dangling_queue_symlink_fails_closed",
                         "case_id": "tests/test_provider_auth_queue.py::ProviderAuthQueueTests.test_dangling_queue_symlink_fails_closed",
                         "reason": "Real file symlink creation denied by Windows privilege (WinError 1314); sentinel retained."})
    else:
        reject("d.runtime.auth-queue.state", lambda: symlink_queue.status(refresh_presence=False))
        require(symlink_queue.path.is_symlink() and not (symlink_queue.path.parent / "missing-state.json").exists(),
                "d.runtime.auth-queue.state", "dangling queue symlink was followed or replaced")

    def registry(name):
        return ClusterRegistry(root / name, use_configured_root=False)
    def host(directory, name="LAB-A"):
        return {"hostId": name, "hostType": "workstation", "role": "worker", "runtimes": ["hermes"],
                "capabilities": ["runtime.launch"], "workspaceMappings": {"workspace": str(directory)},
                "maxConcurrentJobs": 4, "currentLoad": 0, "workspaceRoot": str(directory)}
    def job(reg, name, *, preferred="LAB-A", payload=None, provider="OpenAI-Codex"):
        return reg.upsert_job(job_id=name, mission_id="local-proof", workspace_id="workspace", runtime_id="hermes",
                              target_provider=provider, target_model="lab-model", preferred_host=preferred,
                              required_capabilities=["runtime.launch"], planned_file_scope=[name], payload=payload)
    def result(reg, j, value, lease="", reporter="LAB-A"):
        return reg.record_provider_result(job=j, lease_id=lease, host_id=reporter, result=value)
    auth = {"status": "failed", "returnCode": 1, "stderr": "HTTP 401 unauthorized: lab scheduling input"}
    rate = {"status": "failed", "returnCode": 1, "stderr": "HTTP 429 rate limit", "retryAfterSeconds": 60}
    overload = {"status": "failed", "returnCode": 1, "stderr": "HTTP 503 overloaded"}
    r = registry("route")
    j = job(r, "auth-source")
    for return_code in (None, "", 0, "0", 0.0, False, [0]):
        category = classify_provider_result(j, {"status": "completed", "returnCode": return_code, "stderr": auth["stderr"]})
        expected = "success" if return_code in (None, "") or str(return_code) == "0" else "auth"
        require(category["kind"] == expected, "d.runtime.circuit.classification", "return-code coercion changed provider success semantics")
    opened = result(r, j, auth)["circuit"]
    job(r, "blocked-same-host")
    require(not r.claim_next_job(host(r.root))["job"], "d.runtime.circuit.admission", "open route admitted same host")
    job(r, "other-host", preferred="LAB-B")
    require(bool(r.claim_next_job(host(r.root, "LAB-B"))["job"]), "d.runtime.circuit.admission", "one host failure blocked another host")
    direct = r._create_lease("blocked-same-host", "LAB-A", lease_ttl_seconds=60)
    require(not direct, "d.runtime.circuit.admission", "direct assignment bypassed circuit transaction")
    late = result(r, j, overload)["circuit"]
    require(late["retryAfter"] >= opened["retryAfter"] and late["lastFailureKind"] == "auth", "d.runtime.circuit.transition", "late transient weakened authentication cooldown")
    reset = r.reset_provider_circuit(host_id="LAB-A", runtime_id="hermes", provider="OpenAI-Codex", actor="token=lab-private", reason="password=lab-private")
    require("lab-private" not in json.dumps(reset), "d.runtime.circuit.reset", "manual reset retained credential assignments")
    job(r, "canary-extra")
    with ThreadPoolExecutor(max_workers=2) as executor:
        admissions = list(executor.map(lambda _: r.claim_next_job(host(r.root)), range(2)))
    probes = [a for a in admissions if a.get("job")]
    require(len(probes) == 1, "d.runtime.circuit.admission", "concurrent claim admitted multiple canaries")
    probe = probes[0]
    wrong = result(r, probe["job"], auth, probe["lease"]["leaseId"], "LAB-B")
    require(wrong.get("error") == "provider_result_lease_mismatch"
            and r.get_provider_circuit(host_id="LAB-B", runtime_id="hermes", provider="OpenAI-Codex")["state"] == "closed",
            "d.runtime.circuit.reporting", "different host published lease result")
    successful = result(r, probe["job"], {"ok": True, "status": "completed", "returnCode": 0, "stderr": "401 unauthorized documentation"}, probe["lease"]["leaseId"])
    require(successful["circuit"]["state"] == "closed" and successful["classification"]["kind"] == "success", "d.runtime.circuit.classification", "successful output text became an auth failure")
    r.complete_job(job_id=probe["job"]["jobId"], lease_id=probe["lease"]["leaseId"], host_id="LAB-A", status="completed")
    result(r, j, auth)
    r.reset_provider_circuit(host_id="LAB-A", runtime_id="hermes", provider="OpenAI-Codex")
    second = r.claim_next_job(host(r.root))
    require(result(r, second["job"], auth, second["lease"]["leaseId"])["circuit"]["state"] == "open", "d.runtime.circuit.transition", "failed canary did not reopen")
    r.complete_job(job_id=second["job"]["jobId"], lease_id=second["lease"]["leaseId"], host_id="LAB-A", status="failed")
    r.reset_provider_circuit(host_id="LAB-A", runtime_id="hermes", provider="OpenAI-Codex")
    job(r, "inconclusive-canary")
    uncertain = r.claim_next_job(host(r.root))
    reopened = result(r, uncertain["job"], {"status": "failed", "returnCode": 1, "stderr": "local operation failed"}, uncertain["lease"]["leaseId"])
    require(reopened["circuit"]["lastFailureKind"] == "probe_inconclusive" and ClusterRegistry(r.root, use_configured_root=False).list_provider_circuits() == r.list_provider_circuits(),
            "d.runtime.circuit.transition", "inconclusive circuit did not survive durable registry restart")
    for label, metadata, kind in (("rate", rate, "rate_limit"), ("overload", overload, "provider_overload"),
                                  ("credit", {"status": "failed", "stderr": "HTTP 402 insufficient credits", "returnCode": 1}, "credit")):
        reg = registry(label); source = job(reg, label + "-source")
        classified = result(reg, source, metadata)
        require(classified["classification"]["kind"] == kind, "d.runtime.circuit.classification", "provider failure category became authentication")
        if kind == "provider_overload":
            from .cluster import PROVIDER_TRANSIENT_FAILURE_THRESHOLD
            for _ in range(PROVIDER_TRANSIENT_FAILURE_THRESHOLD - 1):
                classified = result(reg, source, metadata)
        require(classified["circuit"]["state"] == "open", "d.runtime.circuit.transition", "failure threshold did not open route")
        unrelated = job(reg, label + "-unrelated", provider="lab-other")
        reg.heartbeat_host(host(reg.root))
        require(reg.assign_job(job_id=unrelated["jobId"], preferred_host="LAB-A", allow_remote=True)["ok"],
                "d.runtime.circuit.admission", "affected provider failure gated unrelated route")

    # This child prints explicit lab scheduling metadata. It contacts no provider.
    worker_root = root / "worker"; worker_root.mkdir()
    names = ("FLUXIO_CLUSTER_ROOT", "FLUXIO_CONTROL_PROJECT_ROOT", "FLUXIO_HOST_ID", "FLUXIO_WORKSPACE_MAPPINGS")
    saved = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update({"FLUXIO_CLUSTER_ROOT": str(worker_root), "FLUXIO_CONTROL_PROJECT_ROOT": str(worker_root), "FLUXIO_HOST_ID": "LAB-A"})
        os.environ.pop("FLUXIO_WORKSPACE_MAPPINGS", None)
        wr = ClusterRegistry(worker_root, use_configured_root=False)
        worker_job = job(wr, "scratch-child", payload={"command": [sys.executable, "-c", "print('HTTP 401 unauthorized: lab scheduling input');raise SystemExit(1)"], "workspacePath": str(worker_root)})
        environment = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"), "PATH": str(Path(sys.executable).parent), "TEMP": str(worker_root), "TMP": str(worker_root)}
        run = run_local_worker_once(worker_root, host_id="LAB-A", observed_capabilities=host(worker_root), process_environment=environment)
        require(run["claimed"] and wr.get_job(worker_job["jobId"])["status"] == "failed" and wr.list_provider_circuits()[0]["state"] == "open",
                "d.runtime.circuit.worker", "actual local child failure did not durably open circuit before completion")
        doctor = build_worker_doctor(worker_root, host_id="LAB-A", observed_capabilities=host(worker_root))
        require(doctor["status"] == "warn" and doctor["circuitIssues"], "d.runtime.circuit.worker", "doctor did not warn on actual durable failed route")
        reject("d.runtime.circuit.worker", lambda: observed_worker_capabilities(worker_root, "LAB-A", {**host(worker_root), "workspaceMappings": {"escape": str(root.parent)}}))
        escape = root / "refused-worker-escape"
        reject("d.runtime.circuit.worker", lambda: execute_job({"workspaceId": "unmapped", "payload": {
            "command": [sys.executable, "-c", "raise SystemExit(0)"], "executionRoot": str(escape.resolve()),
            "coordination": {"lab": True}}}, {}, root=worker_root, process_environment=environment))
        require(not escape.exists(), "d.runtime.circuit.worker", "rejected environment route wrote coordination outside the worker root")
    finally:
        for name, value in saved.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value
    identities = ["d.runtime.auth-queue." + name for name in ("state", "persisted", "transition", "flow", "projection", "startup")]
    identities += ["d.runtime.circuit." + name for name in ("admission", "transition", "classification", "reset", "reporting", "worker")]
    checks.extend({"contract": identity, "ok": True} for identity in identities)
    return {"ok": True, "contracts": identities, "checks": checks, "rejections": rejected, "frontier": frontier,
            "truthBoundary": "Local durable coordination only; provider presence, flow and result labels are explicit lab inputs, not authentication evidence."}
