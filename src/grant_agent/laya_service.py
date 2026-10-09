"""Typed advisory LAYA attachment; unavailable service never gains authority."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from .laya_client.contracts import T20Hook, canonical, digest


def endpoint():
    value = os.environ.get("NEYVIA_LAYA_URL", "").rstrip("/")
    if not value:
        # The backend owns the service by default (laya_host); the variable only overrides it.
        from .laya_host import current_url, status as host_status
        value = current_url() or ""
        if not value:
            raise ValueError("LAYA service is not running: " + str(host_status().get("reason") or "not started")
                             + ". Configure NEYVIA_LAYA_URL to use an external local LAYA service")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.port or parsed.port == 47881 or parsed.username or parsed.password or parsed.path:
        raise ValueError("NEYVIA_LAYA_URL must be an explicit loopback HTTP service port")
    return value


def attach_browser(browser):
    from .laya_client.browser_client import attach
    try:
        configured = endpoint()
    except ValueError as exc:
        browser.laya_status = "configuration_needed"
        browser.laya_reason = str(exc)
        return
    # Browser hot-path admission requires the resident fast CPU family or GPU.
    # The separate typed service route can still use a larger CPU off this path.
    browser.laya_client = attach(browser, endpoint=configured, timeout_s=5)
    browser.laya_status = "attached"
    browser.laya_health = None


def _browser_model_allowed(identity):
    if not isinstance(identity, dict):
        return False
    device = str(identity.get("device", ""))
    if device == "cuda" or device.startswith("cuda:"):
        return identity.get("weights_frozen") is True
    heads = identity.get("head_artifacts", {})
    checkpoint_proven = isinstance(heads, dict) and any(
        isinstance(head, dict) and head.get("head_sha256") == "c2712493a4ea15b476501d380f5ceb30711f986591195381fe45cf5a14446607"
        and head.get("effective_weights_sha256") == "0c55909c759ec24f3f3e30c1f21189f414290556afd3533d377081a217892138"
        for head in heads.values())
    return (device == "cpu" and checkpoint_proven and identity.get("architecture") == "shared-state-typed-evidence"
            and identity.get("model") == "laya/round5-state"
            and identity.get("candidate") == "g3-c2" and identity.get("weights_frozen") is True
            and identity.get("answer_memory") is False and identity.get("state_cache") is False
            and isinstance(identity.get("source_sha256"), dict) and bool(identity["source_sha256"])
            and identity.get("manifest_sha256") == "df2544cb30c9dc23db6dc04a0aaac8d993ca8be9bfc28d3ad656272aa7f67b94")


def browser_status(browser):
    if getattr(browser, "laya_client", None) is None and browser.laya_provider is None:
        attach_browser(browser)  # the backend-owned service may have become ready after the browser started
    client = getattr(browser, "laya_client", None)
    if client is None:
        return {"available": False, "status": getattr(browser, "laya_status", "not_attached"),
                "reason": getattr(browser, "laya_reason", "LAYA provider is not attached")}
    cached = getattr(browser, "laya_health", None)
    if cached is None or time.monotonic() - cached["checkedAt"] > 2:
        try:
            with urllib.request.urlopen(client.hook.endpoint + "/v1/health",
                                        timeout=getattr(browser, "laya_health_timeout", .25)) as response:
                value = json.load(response)
            model_allowed = _browser_model_allowed(value.get("browser_identity", value.get("identity")))
            ready = value.get("status") == "ready" and model_allowed
            browser.laya_status = "ready" if ready else "fast_cpu_or_gpu_required" if value.get("status") == "ready" else "service_unavailable"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            ready = False
            browser.laya_status = "service_unavailable"
        cached = {"checkedAt": time.monotonic(), "available": ready, "status": browser.laya_status}
        browser.laya_health = cached
    return {"available": cached["available"], "status": cached["status"]}


def _browser_decide(browser, args, *, owner=False):
    # Refuse a wrong tab, but do not queue a native observation when the
    # advisory service is already known to be unavailable.
    with browser.lock:
        browser.tab(args)
    if getattr(browser, "laya_client", None) is None and browser.laya_provider is None:
        attach_browser(browser)
    client = getattr(browser, "laya_client", None)
    if client is None:
        if browser.laya_provider is not None:
            return browser.request("decide", args, owner=owner)
        return {"ok": True, "available": False, "status": getattr(browser, "laya_status", "not_attached"),
                "tabId": args["tabId"], "decision": None,
                "selected_action": None, "browser_policy": {"policy": "escalate", "reason": "configuration_needed"},
                "reason": getattr(browser, "laya_reason", "LAYA provider is not attached")}
    health = browser_status(browser)
    if not health["available"]:
        return {"ok": True, "available": False, "status": health["status"],
                "tabId": args["tabId"], "decision": None,
                "selected_action": None, "browser_policy": {"policy": "escalate", "reason": health["status"]},
                "reason": "Browser decisions require the warm g3-c2 CPU family or a frozen model on GPU" if health["status"] == "fast_cpu_or_gpu_required" else "LAYA service is unavailable; use the existing checked model route"}
    try:
        result = client.decide(args["tabId"], args.get("question", "page_changed"), context=args.get("context"))
        if not _browser_model_allowed(result.get("decision", {}).get("identity")):
            browser.laya_status = "fast_cpu_or_gpu_required"
            browser.laya_health = None
            return {"ok": True, "available": False, "status": browser.laya_status,
                    "tabId": args["tabId"], "decision": None, "selected_action": None,
                    "browser_policy": {"policy": "escalate", "reason": "hot_path_model_identity_changed"},
                    "reason": "Refresh the warm fast CPU or GPU service identity before deciding"}
        if args.get("question") == "grounded_action":
            decision = result.get("decision", {})
            result["selected_action"] = decision.get("selected_action")
            result["browser_policy"] = decision.get("browser_policy", {"policy": "escalate", "reason": "missing_decision"})
        elif args.get("question") == "calibrated_advisory":
            decision = result.get("decision", {})
            result["selected_action"] = None
            result["accepted_decision"] = decision.get("accepted_decision")
            result["decision_policy"] = decision.get("decision_policy", {"policy": "escalate", "reason": "missing_advisory_decision"})
        browser.laya_status = "ready"
        browser.laya_health = {"checkedAt": time.monotonic(), "available": True, "status": "ready"}
        return result
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        browser.laya_status = "service_unavailable"
        browser.laya_health = {"checkedAt": time.monotonic(), "available": False, "status": browser.laya_status}
        return {"ok": True, "available": False, "status": getattr(browser, "laya_status", "not_attached"),
                "tabId": args["tabId"], "decision": None,
                "selected_action": None, "browser_policy": {"policy": "escalate", "reason": "service_timeout_or_unavailable"},
                "reason": "LAYA service is unavailable; refresh or use the existing checked model route"}
    except ValueError as exc:
        if str(exc) not in {"T20 observation changed during LAYA inference; refresh before deciding",
                            "T20 observation became stale during LAYA inference",
                            "observed CL-State is stale or has a future timestamp"}:
            raise
        return {"ok": True, "available": True, "status": "observation_refresh_required",
                "tabId": args["tabId"], "decision": None, "selected_action": None,
                "browser_policy": {"policy": "escalate", "reason": "observation_stale_or_changed"},
                "reason": "Refresh the page before deciding again"}


def _question(schema, instructions):
    if schema.get("type") == "boolean":
        return {"type": "noul", "instructions": instructions, "thresholds": {"answer": .95}}
    values = schema.get("enum")
    if isinstance(values, list) and len(values) >= 2:
        return {"type": "choice", "instructions": instructions,
                "criteria": {canonical(value): canonical(value) for value in values},
                "thresholds": {"answer": .95}}
    raise ValueError("LAYA supports Boolean and finite-choice decision fields")


def system1(prompt, schema, *, scope, preconditions, timeout_s=2):
    try:
        scalar = schema.get("type") != "object"
        fields = {"decision": schema} if scalar else schema.get("properties", {})
        if not fields or not scalar and set(fields) != set(schema.get("required", [])):
            return {"available": False, "reason": "LAYA requires a scalar or fully required flat typed decision"}
        questions = {key: _question(spec, prompt + ("\nReturn field: " + key if not scalar else "")) for key, spec in fields.items()}
        payload = {"questions": questions, "state": preconditions, "scope": scope,
                   "client": "neyvia-cascade-system1", "base_cache": False}
        response = T20Hook(endpoint(), timeout_s=timeout_s)._post(payload)
        values = response["answers"]
        if any(values[key]["answer"] not in {"true", "false"} for key, spec in fields.items() if spec.get("type") == "boolean"):
            return {"available": False, "reason": "LAYA returned an unknown Boolean option"}
        answer = {key: values[key]["answer"] == "true" if spec.get("type") == "boolean" else json.loads(values[key]["answer"]) for key, spec in fields.items()}
        confidence = min(values[key]["top_probability"] for key in fields)
        return {"available": True, "answer": answer["decision"] if scalar else answer,
                "confidence": confidence, "escalate": any(values[key]["policy"] != "answer" for key in fields),
                "decisionId": response["decision_id"], "identity": response["identity"],
                "binding": {"preconditionsSha256": digest(preconditions), "scopeSha256": digest(scope)},
                "providerResponse": response}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return {"available": False, "reason": "LAYA service is unavailable"}
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}


def browser_decide(browser, args, *, owner=False):
    """Advisory browser decision with a receipt of who answered, how fast, and what was handed up."""
    started = time.monotonic()
    result = _browser_decide(browser, args, owner=owner)
    try:
        from .laya_ledger import classify_browser, record
        outcome, confidence, detail = classify_browser(result)
        question = args.get("question", "page_changed")
        record(browser.root, task="browser", path="browser.decide",
               decision=question if isinstance(question, str) else "custom-question", outcome=outcome,
               latency_ms=(time.monotonic() - started) * 1000, confidence=confidence,
               prompt_chars=len(json.dumps(args.get("context") or {}, default=str)) + 400, detail=detail,
               **({'tokensSavedEstimate': 0} if args.get('question') == 'calibrated_advisory' else {}))
    except Exception:
        pass
    return result


def triage(root, task, question, options, *, context=None, path="triage", threshold=.95, system1_fn=None, timeout_s=8, estimate_savings=True):
    """Ask LAYA a routine routing question; hand it up unless it is confident, valid and available.

    The same acceptance gate as the cascade: the answer must be one of ``options`` and the
    provider must report an answer-policy at or above ``threshold``. Every call leaves a receipt.
    Returns ``{"route": "laya" | "escalate" | "unavailable", "decision": value-or-None, ...}``;
    the caller keeps the existing checked route for anything but ``laya``.
    """
    from .laya_ledger import record
    values = list(options)
    if len(values) < 2 or not all(isinstance(v, str) for v in values):
        raise ValueError("triage needs at least two string options")
    started = time.monotonic()
    prompt = str(question)
    scope = {"application": task, "workspace": str(Path(root).resolve()), "options": values}
    preconditions = {"context": context or {}}
    call = system1_fn or system1
    try:
        from .laya_instant import query
        domain = 'routing' if task == 'manual-routing' else 'triage:' + task
        observation = prompt if task == 'manual-routing' else {'question': prompt, 'context': context or {}, 'options': values}
        response = query(root, domain, observation, labels=values)
        if response.get('warming'):
            response = {"available": False, "reason": response["reason"]}
        elif response.get('escalate') and not response.get('conflict') and response.get('reason') != 'personal-region-ambiguous':
            response = call(prompt + " " + canonical(preconditions), {"type": "string", "enum": values},
                        scope=scope, preconditions=preconditions, **({"timeout_s": timeout_s} if system1_fn is None else {}))
    except Exception as exc:  # a broken service must not stop the gate
        response = {"available": False, "reason": type(exc).__name__}
    chars = len(prompt) + len(canonical(preconditions))
    elapsed = (time.monotonic() - started) * 1000
    if not response or response.get("available") is False:
        record(root, task=task, path=path, decision=prompt[:100], outcome="unavailable", latency_ms=elapsed,
               prompt_chars=chars, detail=str((response or {}).get("reason", "")), **({} if estimate_savings else {"tokensSavedEstimate": 0}))
        return {"route": "unavailable", "decision": None, "confidence": None}
    confidence = response.get("confidence")
    accepted = (not response.get("escalate") and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                and confidence >= threshold and response.get("answer") in values)
    record(root, task=task, path=path, decision=prompt[:100], outcome="answered" if accepted else "escalated", latency_ms=elapsed,
           confidence=confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
           prompt_chars=chars, detail="" if accepted else "below-threshold-or-invalid", **({} if estimate_savings else {"tokensSavedEstimate": 0}))
    return {"route": "laya" if accepted else "escalate", "decision": response.get("answer") if accepted else None,
            "confidence": confidence, 'source': response.get('source'), 'confidenceKind': response.get('confidenceKind')}


def verify(question, candidate, evidence, *, root=None, timeout_s=8):
    """Shared verification entry; hooks retain the existing typed fallback."""
    from .laya_hooks import verify as verify_hook
    return verify_hook(question, candidate, evidence, root=root, timeout_s=timeout_s)
