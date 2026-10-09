"""Small adapter for the merged T20 two-argument advisory provider hook.

Attach to a BrowserService in the backend process, then call client.decide.
Fresh acquisition happens outside T20's decide lock; existing cached DOM is
never given a new observation timestamp. No browser actions are executed here.
"""
from __future__ import annotations

import copy
import math
import os
import re
import threading
import time

from .contracts import T20Hook, digest, validate_questions


def grounded_action_instructions(goal, decision_profile=None):
    return ("Choose the candidate that advances the user's goal using only observed page evidence. "
            "Do not assume pending actions succeeded. Goal: " + goal)


def grounded_action_view(decision_profile=None):
    # Explicit control intent is encoded once. Repeating every candidate name
    # as evidence makes both alternatives look equally relevant to this model.
    return ["goal", "current"] if decision_profile == "public_explicit_intent@1" else ["goal", "controls", "current", "progress", "action_receipts"]


def explicit_intent_safe(observation, context):
    """Scope admission only; the model still chooses the candidate unchanged."""
    options = context.get("options", [])
    if len(options) != 2 or context.get("goal") not in [o.get("description") for o in options]:
        return False
    for option in options:
        args = option.get("args") or {}
        control = next((e for e in observation.get("elements", []) if e.get("id") == args.get("element")), None)
        if not control or args.get("action") != "click" or control.get("role") not in {"link", "button"}:
            return False
        name = " ".join(str(control.get("name") or "").split())
        if (not name or len(name) > 120 or control.get("secret") or not control.get("enabled")
                or control.get("nameTruncated") or "click" not in control.get("actions", [])
                or re.search(r"\b(delete|remove|purchase|buy|checkout|pay|submit|password|login|log in|sign in|sign up|register|upload|download)\b", name, re.I)
                or option.get("description") != f'Click {control["role"]} "{name}".'):
            return False
        if sum(e.get("role") == control["role"] and " ".join(str(e.get("name") or "").split()) == name
               for e in observation.get("elements", [])) != 1:
            return False
    return len({o["args"]["element"] for o in options}) == 2


def project_grounded_state(observation, context):
    """One model projection shared by live decisions and recorded calibration."""
    if context.get("decision_profile") == "public_explicit_intent@1":
        return {"goal": context.get("goal"), "current": {
            "title": observation.get("title"), "readyState": observation.get("readyState")}}
    if context.get("decision_profile") == "public_observed_fields@1":
        text = observation.get("text") or ""
        start = max(0, text.find("Meaning of"))
        return {"page": {"url": observation.get("url"), "title": observation.get("title")},
                "controls": [{key: (str(element.get(key) or "")[:120] if key == "name" else "[secret]" if key == "value" and element.get("secret") else element.get(key))
                              for key in ("id", "role", "name", "value", "enabled", "secret", "actions")}
                             for element in observation.get("elements", [])
                             if "fill" in element.get("actions", []) or "click" in element.get("actions", [])][:16],
                "current": {"text": text[start:start+1600], "tables": observation.get("tables"),
                            "readyState": observation.get("readyState"), "authentication": observation.get("authentication")}}
    controls = [{key: element.get(key) for key in
                 ("id", "role", "name", "value", "enabled", "checked", "actions",
                  "secret", "nameTruncated", "valueTruncated")}
                for element in observation.get("elements", [])]
    for control in controls:
        if control["secret"]:
            control["value"] = "[secret]"
    options = context.get("options")
    if isinstance(options, list):
        targets = {option.get("args", {}).get("element") for option in options
                   if isinstance(option, dict) and isinstance(option.get("args"), dict)}
        if targets:
            controls = [control for control in controls if control["id"] in targets]
    public_controls = context.get("decision_profile") == "public_document_controls@1"
    keys = ("title", "readyState", "authentication") if public_controls else (
        "text", "title", "url", "truncated", "tables", "tablesTruncated", "readyState", "authentication")
    return {"goal": context.get("goal"), "controls": controls,
            "current": {key: observation.get(key) for key in keys},
            "progress": context.get("progress"), "action_receipts": context.get("action_receipts")}


class BrowserClient:
    def __init__(self, browser_service, endpoint="http://127.0.0.1:8796", **hook_options):
        self.browser = browser_service
        self.hook = T20Hook(endpoint, **hook_options)
        self.captures = {}
        self.questions = {}
        self._tab_locks = {}
        self._tab_locks_guard = threading.Lock()
        calibration_path = os.environ.get("NEYVIA_LAYA_BROWSER_CALIBRATION")
        self.calibration = None
        if calibration_path:
            from .calibration import BrowserCalibration
            self.calibration = BrowserCalibration(calibration_path)

    def register_question(self, name, question):
        if not isinstance(name, str) or not name or name in {'next_action', 'relevance', 'page_done', 'page_changed'}:
            raise ValueError('Custom question needs a distinct provider name')
        validate_questions({'decision': question})
        if name in self.questions and digest(self.questions[name]) != digest(question):
            raise ValueError('Named question is immutable; use a new version/name')
        self.questions[name] = copy.deepcopy(question)
        return name

    def attach(self):
        with self.browser.lock:
            if self.browser.laya_provider not in (None, self):
                raise ValueError("T20 already has a different LAYA provider")
            self.browser.laya_provider = self
        return self

    def detach(self):
        with self.browser.lock:
            if self.browser.laya_provider is self:
                self.browser.laya_provider = None
            self.captures.clear()

    def _tab_lock(self, tab_id):
        with self._tab_locks_guard:
            return self._tab_locks.setdefault(tab_id, threading.RLock())

    def observe(self, tab_id, *, context=None):
        with self._tab_lock(tab_id):
            return self._observe(tab_id, context=context)

    def _observe(self, tab_id, *, context=None):
        context = copy.deepcopy(context or {})
        allowed = {"goal", "options", "progress", "action_receipts", "query", "result", "previous", "decision_profile", "advisory_field", "evidence"}
        if not isinstance(context, dict) or set(context) - allowed:
            raise ValueError("Context must contain only CL-State task fields")
        # This is a conservative age: queueing/wait time counts as observation age.
        started_ms = time.time() * 1000
        observed = self.browser.request("observe", {"tabId": tab_id, "cached": False})
        if observed.get("actionId"):
            from grant_agent.neyvia_browser import wait_observation
            observed = wait_observation(self.browser, observed)
        if observed.get("tabId") != tab_id or not observed.get("revision"):
            raise ValueError("T20 did not return a bound native observation")
        if observed.get("readyState") != "complete":
            raise ValueError("T20 native observation is still loading")
        with self.browser.lock:
            self.captures[tab_id] = {"digest": digest(observed), "observed_at_ms": started_ms,
                                     "context": context}
        return observed

    def decide(self, tab_id, question="page_changed", *, context=None):
        # A second decision on this tab cannot replace the first call's goal.
        with self._tab_lock(tab_id):
            return self._decide(tab_id, question, context=context)

    def _decide(self, tab_id, question="page_changed", *, context=None):
        advisory = question == "calibrated_advisory"
        if context and context.get("advisory_field") and not advisory:
            raise ValueError("Advisory field checks require the calibrated_advisory question")
        if question == "grounded_action" or advisory:
            context = copy.deepcopy(context or {})
            options = context.get("options")
            if not isinstance(context.get("goal"), str) or not context["goal"].strip():
                raise ValueError("Grounded browser decision requires a goal")
            if not isinstance(options, list) or not 2 <= len(options) <= 12:
                raise ValueError("Grounded browser decision requires 2 to 12 candidates")
            criteria = {}
            for option in options:
                if not isinstance(option, dict) or set(option) - {"id", "description", "args"}:
                    raise ValueError("Candidate requires id, description and optional args")
                key, description = option.get("id"), option.get("description")
                if not isinstance(key, str) or not 1 <= len(key) <= 128 or key in criteria or not isinstance(description, str) or not description.strip() or len(description) > 1000:
                    raise ValueError("Candidates require unique nonempty IDs and descriptions")
                args = option.get("args")
                if args is not None and (not isinstance(args, dict) or set(args) - {"element", "action", "value", "tabId", "revision", "expect"}
                                         or args.get("action") not in {"click", "fill", "select", "scroll"}
                                         or not isinstance(args.get("element"), str)):
                    raise ValueError("Candidate args must describe a grounded browser.action")
                if args is not None:
                    from grant_agent.browser_verification import validate_expect
                    validate_expect(args)
                criteria[key] = description
            question = {"type": "choice", "view": grounded_action_view(context.get("decision_profile")),
                        "instructions": grounded_action_instructions(context["goal"], context.get("decision_profile")),
                        "criteria": criteria, "thresholds": {"answer": self.calibration.threshold if self.calibration else .8},
                        "stakes": {"default": "reversible_costly"}}
            if advisory:
                if context.get("decision_profile") != "public_observed_fields@1" or context.get("advisory_field") not in {"title", "url", "readyState", "hostname"} or any(option.get("args") for option in options):
                    raise ValueError("Calibrated advisory uses observed fields and never action candidates")
                question = {"type": "choice", "instructions": context["goal"], "criteria": criteria,
                            "view": ["page", "controls", "current"],
                            "thresholds": {"answer": self.calibration.spec.get("advisory_threshold", 1.000001) if self.calibration else 1.000001}}
        if isinstance(question, dict):
            question = self.register_question('q_' + digest(question), question)
        self.observe(tab_id, context=context)
        return self.browser.request("decide", {"tabId": tab_id, "question": question})

    def __call__(self, observation, question):
        tab_id = observation.get("tabId")
        captured = self.captures.get(tab_id)
        if captured is None or captured["digest"] != digest(observation):
            raise ValueError("Acquire a fresh native observation with BrowserClient.observe first")
        # The executor retains geometry/engine metadata in its exact projection.
        # Typed judgments need visible content first, without repeated DOM data
        # displacing goal evidence from the small encoder's context window.
        projected = project_grounded_state(observation, captured["context"])
        state = {"revision": observation["revision"], "observed_at_ms": captured["observed_at_ms"],
                 "trust": observation.get("trust"),
                 "page": {"url": observation.get("url"), "title": observation.get("title")},
                 **projected}
        if captured["context"].get("decision_profile") != "public_observed_fields@1":
            state.update(captured["context"])
        else:
            # Exact original fitting projection; metadata is checked separately.
            state = projected
            state.update(revision=observation["revision"], observed_at_ms=captured["observed_at_ms"])
        definition = self.questions.get(question, question) if isinstance(question, str) else question
        call = {"tabId": tab_id, "observed": state, "question": definition}
        if definition == "page_done" and isinstance(state.get("evidence"), str) and state["evidence"].strip():
            # The caller named the evidence that proves completion: LAYA's learned page_done applies.
            from grant_agent.laya_hooks import SET, page_done_state
            learned = page_done_state(state.get("goal"), state.get("page"), state.get("current"), state.get("action_receipts"), state["evidence"])
            state["receipt_summary"] = learned["receipt_summary"]
            call["set"] = SET
        response = self.hook(call)
        current = self.browser.projection(tab_id)
        if digest(current) != captured["digest"]:
            raise ValueError("T20 observation changed during LAYA inference; refresh before deciding")
        if time.time() * 1000 - captured["observed_at_ms"] > self.hook.max_age_ms:
            raise ValueError("T20 observation became stale during LAYA inference")
        response["t20"] = {"tabId": tab_id, "revision": observation["revision"],
                           "projection_digest": captured["digest"], "advisory_only": True,
                           "execution_authority": "T20 owner grants and fresh revision checks"}
        if captured["context"].get("advisory_field"):
            field = captured["context"]["advisory_field"]
            answer = response.get("answers", {}).get("decision", {})
            confidence = self.calibration.advisory_confidence(response, answer, definition,
                field=field, url=observation.get("url")) if self.calibration else None
            threshold = definition.get("thresholds", {}).get("answer", 1.000001)
            candidate = next((option for option in captured["context"].get("options", []) if option["id"] == answer.get("answer")), None)
            expected = observation.get(field)
            if field == "hostname":
                from urllib.parse import urlsplit
                expected = urlsplit(observation.get("url") or "").hostname
            verified = bool(candidate and candidate["description"] == expected)
            accepted = bool(confidence is not None and confidence >= threshold and verified and answer.get("policy") == "answer")
            response["selected_action"] = None
            response["accepted_decision"] = answer.get("answer") if accepted else None
            response["decision_policy"] = {"policy": "answer+postcheck" if accepted else "escalate",
                "reason": "fresh_native_field_postcheck" if accepted else "scope_confidence_or_postcheck_failed",
                "threshold": threshold, "confidence": confidence, "field": field,
                "postcheck_passed": verified, "advisory_only": True}
            return response
        options = captured["context"].get("options")
        if options and isinstance(definition, dict):
            answer = response.get("answers", {}).get("decision", {})
            threshold = definition.get("thresholds", {}).get("answer", .8)
            top_probability = answer.get("top_probability")
            confidence = self.calibration.confidence(response, answer,
                decision_profile=captured["context"].get("decision_profile"), url=observation.get("url")) if self.calibration else None
            trusted = (not isinstance(confidence, bool) and isinstance(confidence, (float, int))
                       and math.isfinite(confidence) and 0 <= confidence <= 1 and confidence >= threshold
                       and answer.get("policy") in {"answer", "answer+postcheck"}
                       and answer.get("source") == "laya")
            candidate = next((option for option in options if option.get("id") == answer.get("answer")), None)
            selected = None
            reason = "below_confidence_threshold_or_uncalibrated_memory"
            if self.calibration and confidence is None:
                reason = "action_calibration_scope_or_identity_unproven"
            authentication = observation.get("authentication") or {}
            if authentication.get("required"):
                reason = "owner_authentication_required"
            elif captured["context"].get("decision_profile") == "public_explicit_intent@1" and not explicit_intent_safe(observation, captured["context"]):
                reason = "explicit_intent_scope_or_control_postcheck_failed"
            elif trusted and candidate and candidate.get("args"):
                args = candidate["args"]
                element = next((element for element in observation.get("elements", []) if element.get("id") == args.get("element")), None)
                if element and element.get("enabled", True) and not element.get("secret") and args["action"] in element.get("actions", []):
                    selected = {**args, "tabId": tab_id, "revision": observation["revision"]}
                    reason = "fresh_observed_candidate"
                else:
                    reason = "candidate_is_not_a_current_safe_control"
            elif trusted and candidate:
                reason = "candidate_requires_inspection_or_completion_check"
            response["selected_action"] = selected
            response["browser_policy"] = {"policy": "ask" if authentication.get("required") else "answer+postcheck" if selected else "escalate",
                "reason": reason, "threshold": threshold, "top_probability": top_probability,
                "model_confidence_definition": "raw_model_top_probability; acceptance gate fitted on separate real decisions" if self.calibration else "raw_model_top_probability; uncalibrated_for_browser_actions",
                "decision_confidence": confidence,
                "confidence_definition": "model_probability_with_heldout_validated_acceptance_gate" if self.calibration and confidence is not None else "browser action calibration unproven",
                "calibration_scope": self.calibration.spec.get("decision_scope") if self.calibration else None,
                "fallback": "existing_checked_model_or_owner", "advisory_only": True}
        return response


def attach(browser_service, endpoint="http://127.0.0.1:8796", **hook_options):
    return BrowserClient(browser_service, endpoint, **hook_options).attach()
