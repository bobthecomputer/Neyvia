"""Small adapter for the merged T20 two-argument advisory provider hook.

Attach to a BrowserService in the backend process, then call client.decide.
Fresh acquisition happens outside T20's decide lock; existing cached DOM is
never given a new observation timestamp. No browser actions are executed here.
"""
from __future__ import annotations

import copy
import time

from .contracts import T20Hook, digest, validate_questions


class BrowserClient:
    def __init__(self, browser_service, endpoint="http://127.0.0.1:8796", **hook_options):
        self.browser = browser_service
        self.hook = T20Hook(endpoint, **hook_options)
        self.captures = {}
        self.questions = {}

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

    def observe(self, tab_id, *, context=None):
        context = copy.deepcopy(context or {})
        allowed = {"goal", "options", "progress", "action_receipts", "query", "result", "previous"}
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
        controls = [{key: element.get(key) for key in
                     ("id", "role", "name", "value", "enabled", "checked", "actions",
                      "secret", "nameTruncated", "valueTruncated")}
                    for element in observation.get("elements", [])]
        for control in controls:
            if control["secret"]:
                control["value"] = "[secret]"
        current = {key: observation.get(key) for key in
                   ("text", "title", "url", "truncated", "tables", "tablesTruncated", "readyState")}
        state = {"revision": observation["revision"], "observed_at_ms": captured["observed_at_ms"],
                 "trust": observation.get("trust"),
                 "page": {"url": observation.get("url"), "title": observation.get("title")},
                 "controls": controls, "current": current}
        state.update(captured["context"])
        definition = self.questions.get(question, question) if isinstance(question, str) else question
        response = self.hook({"tabId": tab_id, "observed": state, "question": definition})
        current = self.browser.projection(tab_id)
        if digest(current) != captured["digest"]:
            raise ValueError("T20 observation changed during LAYA inference; refresh before deciding")
        if time.time() * 1000 - captured["observed_at_ms"] > self.hook.max_age_ms:
            raise ValueError("T20 observation became stale during LAYA inference")
        response["t20"] = {"tabId": tab_id, "revision": observation["revision"],
                           "projection_digest": captured["digest"], "advisory_only": True,
                           "execution_authority": "T20 owner grants and fresh revision checks"}
        return response


def attach(browser_service, endpoint="http://127.0.0.1:8796", **hook_options):
    return BrowserClient(browser_service, endpoint, **hook_options).attach()
